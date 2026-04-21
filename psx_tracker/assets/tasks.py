import yfinance as yf
import requests
import json
from datetime import datetime, timedelta
from celery import shared_task
from django.utils import timezone
from django.core.cache import cache
from decimal import Decimal
from .models import Asset, PriceHistory, OHLCV, PortfolioHolding, TechnicalIndicator, NewsHeadline, Commodity
from django.db import connection
import random
from bs4 import BeautifulSoup
import logging
import time
import re








logger = logging.getLogger(__name__)


# Add retry decorator for better reliability
def with_retry(max_retries=3, delay=1):
    def decorator(func):
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_retries - 1:
                        logger.error(f"Task {func.__name__} failed after {max_retries} attempts: {e}")
                        raise
                    logger.warning(f"Task {func.__name__} failed (attempt {attempt+1}): {e}, Retrying...")
                    time.sleep(delay * (attempt + 1))      # Exponential backoff
                return None
            return wrapper
        return decorator 


@shared_task(bind=True, max_retries=3, soft_time_limit=60)
def fetch_kse100_data(self):
    """Fetch KSE-100 index data from reliable sources"""
    try:
        # Try multiple sources in order
        result = try_psx_official()
        if result:
            return result
        
        result = try_investing_com()
        if result:
            return result
        
        result = try_dawn_news()
        if result:
            return result
        return "❌ KSE100: All sources failed"
    except Exception as e:
        logger.error(f"❌ KSE100 task failed: {e}")
        # Retry the task
        self.retry(countdown=60)      # Retry after 60 seconds


def try_psx_official():
    """Try official PSX data portal"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        }
        
        # Get the main page
        url = "https://dps.psx.com.pk/"
        print(f"🔍 Fetching: {url}")
        response = requests.get(url, headers=headers, timeout=15)
        
        if response.status_code != 200:
            print(f"❌ Failed to fetch page: {response.status_code}")
            return None
            
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Find all H1 tags
        h1s = soup.find_all('h1')
        
        # The first H1 after "Indices" contains the KSE100 data
        kse100_value = None
        kse100_change = None
        kse100_change_pct = None
        
        for i, h1 in enumerate(h1s):
            text = h1.get_text().strip()
            
            # Skip the "Indices" header
            if text == "Indices":
                continue
                
            match = re.match(r'([\d,]+\.?\d*)\s+([\d,.-]+\.?\d*)\s*\(([\d.-]+)%\)', text)
            if match:
                value = float(match.group(1).replace(',', ''))
                change = float(match.group(2).replace(',', ''))
                change_pct = float(match.group(3))
                
                # The first matching H1 after "Indices" is KSE100
                if kse100_value is None:
                    kse100_value = value
                    kse100_change = change
                    kse100_change_pct = change_pct
                    print(f"✅ Found KSE100: {value} (change: {change}, {change_pct}%)")
                    break
        
        if kse100_value:
            save_kse100_data(kse100_value, kse100_change, kse100_change_pct)
            return f"✅ KSE100 updated: {kse100_value} ({kse100_change:+.2f}, {kse100_change_pct:+.2f}%)"
        else:
            print("❌ Could not find KSE100 value in H1 tags")
            return None
            
    except Exception as e:
        print(f"❌ Error in PSX Official: {e}")
        return None   
                

def try_investing_com():
    """Try investing.com widget"""
    try:
        # Investing.com KSE-100 widget
        url = "https://www.investing.com/indices/kse-100"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Find the current price (inspect the page for correct selector)
        price_elem = soup.find('span', {'data-test': 'instrument-price-last'})
        if price_elem:
            price = float(price_elem.text.replace(',', ''))
            
            # Try to get additional data
            high_elem = soup.find('span', {'data-test': 'instrument-price-high'})
            low_elem = soup.find('span', {'data-test': 'instrument-price-low'})
            open_elem = soup.find('span', {'data-test': 'instrument-price-open'})
            
            high = float(high_elem.text.replace(',', '')) if high_elem else price
            low = float(low_elem.text.replace(',', '')) if low_elem else price
            open_price = float(open_elem.text.replace(',', '')) if open_elem else price
            
            save_kse100_data(price, open_price, high, low, 0)
            return f"KSE100 updated: {price} (Investing.com)"
        
        return None
        
    except Exception as e:
        print(f"Investing.com failed: {e}")
        return None

def try_dawn_news():
    """Try Dawn News business section"""
    try:
        url = "https://www.dawn.com/business"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Look for KSE-100 mention (this is approximate)
        text = soup.get_text()
        import re
        
        # Find pattern like "KSE-100: 45,234" or similar
        match = re.search(r'KSE-100[^\d]*(\d{2},?\d{3})', text)
        if match:
            price_str = match.group(1).replace(',', '')
            price = float(price_str)
            
            save_kse100_data(price, price, price, price, 0)
            return f"KSE100 updated: {price} (Dawn News)"
        
        return None
        
    except Exception as e:
        print(f"Dawn News failed: {e}")
        return None

def save_kse100_data(price, open_price=None, high=None, low=None, volume=None):
    """Save KSE-100 data to database"""
    asset, _ = Asset.objects.get_or_create(
        symbol="KSE100",
        defaults={
            'name': "KSE-100 Index",
            'asset_type': 'INDEX',
            'exchange': 'PSX',
            'currency': 'PKR'
        }
    )
    
    if price > 0:
        # We are using the if function because if we do not get these values we get the price instead.
        PriceHistory.objects.create(
            asset=asset,
            price=price,
            open_price=open_price if open_price is not None else price,           
            high_price=high if high is not None else price,
            low_price=low if low is not None else price,
            volume=int(volume) if volume else 0,
            timestamp=timezone.now()
        )
        return True
    return False


@shared_task(bind=True, max_retries=3, soft_time_limit=60)
def fetch_gold_silver_prices(self):
    """
    Fetch gold (XAU) and silver (XAG) prices from gold-api.com
    Completely free, no API key required, updates in real-time
    """
    
    # Base URL for the API
    base_url = "https://api.gold-api.com/price/"
    
    commodities = [
        {'symbol': 'XAU', 'name': 'Gold', 'code': 'XAU', 'unit': 'oz'},
        {'symbol': 'XAG', 'name': 'Silver', 'code': 'XAG', 'unit': 'oz'},
    ]
    
    results = []
    successful_fetches = 0
    
    for commodity in commodities:
        try:
            # Construct URL for each commodity
            url = f"{base_url}{commodity['code']}"
            
            # Simple request with a standard user-agent
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            logger.info(f"Fetching {commodity['name']} from {url}")
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                # Extract the price (it's a float in the response)
                price = float(data.get('price', 0))
                api_timestamp = data.get('updatedAt')
                
                if price > 0:
                    # Try to get or create as Commodity first (your specialized model)
                    try:
                        asset, created = Commodity.objects.get_or_create(
                            symbol=commodity['symbol'],
                            defaults={
                                'name': commodity['name'],
                                'asset_type': 'COMMODITY',
                                'commodity_type': 'PRECIOUS',
                                'unit': commodity['unit'],
                                'currency': 'USD',
                                'metadata': {
                                    'source': 'gold-api.com',
                                    'api_response': data
                                }
                            }
                        )
                    except (ImportError, NameError):
                        # Fallback to base Asset model if Commodity isn't available
                        asset, created = Asset.objects.get_or_create(
                            symbol=commodity['symbol'],
                            defaults={
                                'name': commodity['name'],
                                'asset_type': 'COMMODITY',
                                'currency': 'USD',
                                'metadata': {
                                    'source': 'gold-api.com',
                                    'unit': commodity['unit']
                                }
                            }
                        )
                    
                    # Create price history record
                    price_history = PriceHistory.objects.create(
                        asset=asset,
                        price=Decimal(str(price)),  # Convert to Decimal for Django
                        timestamp=timezone.now(),
                        volume=0,  # API doesn't provide volume
                        change_percent=0,  # Would need previous price to calculate
                    )
                    
                    # Optionally store the API's timestamp in metadata
                    if api_timestamp:
                        if not asset.metadata:
                            asset.metadata = {}
                        asset.metadata['last_api_update'] = api_timestamp
                        asset.save(update_fields=['metadata'])
                    
                    successful_fetches += 1
                    result_msg = f"{commodity['symbol']}: ${price:.2f}"
                    results.append(result_msg)
                    logger.info(f"✅ Updated {commodity['name']}: ${price}")
                    
                else:
                    error_msg = f"{commodity['symbol']}: Invalid price (0 or negative)"
                    results.append(error_msg)
                    logger.warning(error_msg)
                    
            else:
                error_msg = f"{commodity['symbol']}: HTTP {response.status_code}"
                results.append(error_msg)
                logger.error(f"API error for {commodity['name']}: {response.status_code}")
                
        except requests.exceptions.Timeout:
            error_msg = f"{commodity['symbol']}: Request timeout"
            results.append(error_msg)
            logger.error(f"Timeout fetching {commodity['name']}")
            
        except requests.exceptions.ConnectionError:
            error_msg = f"{commodity['symbol']}: Connection error"
            results.append(error_msg)
            logger.error(f"Connection error fetching {commodity['name']}")
            
        except requests.exceptions.RequestException as e:
            error_msg = f"{commodity['symbol']}: Network error - {str(e)[:50]}"
            results.append(error_msg)
            logger.error(f"Network error for {commodity['name']}: {e}")
            
        except ValueError as e:
            error_msg = f"{commodity['symbol']}: JSON parse error"
            results.append(error_msg)
            logger.error(f"JSON error for {commodity['name']}: {e}")
            
        except Exception as e:
            error_msg = f"{commodity['symbol']}: Unexpected error - {str(e)[:50]}"
            results.append(error_msg)
            logger.exception(f"Unexpected error for {commodity['name']}: {e}")
    
    # Retry if both failed
    if successful_fetches == 0 and self.request.retries < self.max_retries:
        logger.warning("Both gold and silver failed, scheduling retry...")
        self.retry(countdown=60)  # Retry after 60 seconds
    
    return "Gold/Silver update: " + ", ".join(results)


# Separate task for just gold
@shared_task
def fetch_gold_price():
    """Convenience task to fetch only gold price"""
    return fetch_gold_silver_prices.delay()


# Separate task for just silver
@shared_task
def fetch_silver_price():
    """Convenience task to fetch only silver price"""
    return fetch_gold_silver_prices.delay()


@shared_task(bind=True, max_retries=3, soft_time_limit=60)
def fetch_bitcoin_price(self):
    """Fetch Bitcoin price using gold-api.com (primary) with CoinGecko fallback"""
    try:
        # PRIMARY SOURCE: gold-api.com (no key required)
        primary_url = "https://api.gold-api.com/price/BTC"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        logger.info("Fetching Bitcoin price from gold-api.com")
        response = requests.get(primary_url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            price_usd = float(data.get('price', 0))
            api_timestamp = data.get('updatedAt')
            
            if price_usd > 0:
                # Save to database
                return save_bitcoin_price(price_usd, 'gold-api.com', api_timestamp)
            else:
                logger.warning("Invalid price from gold-api.com, trying fallback")
                return fetch_bitcoin_fallback_coingecko(self)
        else:
            logger.warning(f"gold-api.com returned {response.status_code}, trying fallback")
            return fetch_bitcoin_fallback_coingecko(self)
            
    except Exception as e:
        logger.error(f"Primary source failed: {e}")
        return fetch_bitcoin_fallback_coingecko(self)


def fetch_bitcoin_fallback_coingecko(self=None):
    """Fallback to CoinGecko API using your exact URL"""
    try:
        # FALLBACK SOURCE: CoinGecko (exactly as you specified)
        fallback_url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"
        
        logger.info("Trying fallback: CoinGecko API")
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        response = requests.get(fallback_url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            # Parse the response: {"bitcoin":{"usd":74363}}
            price_usd = float(data['bitcoin']['usd'])
            
            if price_usd > 0:
                return save_bitcoin_price(price_usd, 'coingecko')
            else:
                return "Bitcoin fallback: Invalid price"
        else:
            error_msg = f"CoinGecko returned HTTP {response.status_code}"
            logger.error(error_msg)
            
            # If both sources fail and we have retries left
            if self and self.request.retries < self.max_retries:
                self.retry(countdown=60)
            return f"Bitcoin fetch failed: {error_msg}"
            
    except requests.exceptions.Timeout:
        logger.error("CoinGecko timeout")
        return "Bitcoin fallback: Timeout"
    except requests.exceptions.ConnectionError:
        logger.error("CoinGecko connection error")
        return "Bitcoin fallback: Connection error"
    except KeyError as e:
        logger.error(f"CoinGecko response parsing error: {e}")
        return "Bitcoin fallback: Invalid response format"
    except Exception as e:
        logger.exception(f"CoinGecko unexpected error: {e}")
        return f"Bitcoin fallback error: {str(e)[:50]}"


def save_bitcoin_price(price_usd, source, api_timestamp=None):
    """Helper function to save Bitcoin price to database"""
    try:
        # Get or create asset (store in USD as standard for crypto)
        asset, created = Asset.objects.get_or_create(
            symbol="BTC",
            defaults={
                'name': "Bitcoin",
                'asset_type': 'CRYPTO',
                'currency': 'USD',
                'metadata': {
                    'source': source,
                    'first_fetched': timezone.now().isoformat()
                }
            }
        )
        
        # Update metadata if asset existed
        if not created:
            if not asset.metadata:
                asset.metadata = {}
            asset.metadata['last_source'] = source
            if api_timestamp:
                asset.metadata['last_api_timestamp'] = api_timestamp
            asset.save(update_fields=['metadata'])
        
        # Get previous price for change calculation
        previous = PriceHistory.objects.filter(
            asset=asset
        ).order_by('-timestamp').first()
        
        change_percent = 0
        if previous and previous.price > 0:
            change = price_usd - float(previous.price)
            change_percent = (change / float(previous.price)) * 100
        
        # Create price history
        price_history = PriceHistory.objects.create(
            asset=asset,
            price=price_usd,
            change_percent=change_percent,
            timestamp=timezone.now(),
            volume=0,
        )
        
        success_msg = f"Bitcoin updated from {source}: ${price_usd:.2f} USD"
        logger.info(f"✅ {success_msg}")
        return success_msg
        
    except Exception as e:
        logger.exception(f"Error saving Bitcoin price: {e}")
        return f"Error saving Bitcoin: {str(e)[:50]}"


@shared_task
def cleanup_old_data():
    
    # Delete data older than 30 days
    cutoff_date = timezone.now() - timezone.timedelta(days=30)
    deleted_count = PriceHistory.objects.filter(timestamp__lt=cutoff_date).delete()
    
    # PostgreSQL specific: VACUUM ANALYZE (use with caution in production)
    with connection.cursor() as cursor:
        cursor.execute("VACUUM ANALYZE assets_pricehistory;")
    
    return f"Cleaned up {deleted_count} old records"


@shared_task
def update_portfolio_values():
    """Update current values for all portfolio holdings"""
    holdings = PortfolioHolding.objects.select_related('asset').all()
    updated_count = 0
    
    for holding in holdings:
        latest_price = holding.asset.prices.first()
        if latest_price:
            holding.current_value = holding.quantity * latest_price.price
            holding.unrealized_pl = holding.current_value - holding.invested_amount
            if holding.invested_amount > 0:
                holding.unrealized_pl_percent = (holding.unrealized_pl / holding.invested_amount) * 100
            holding.save()
            updated_count += 1
    
    return f"Updated {updated_count} portfolio holdings"


@shared_task
def calculate_technical_indicators():
    """Calculate technical indicators for major assets"""
    from django.db.models import Avg
    import numpy as np
    
    assets = Asset.objects.filter(
        asset_type__in=['STOCK', 'INDEX', 'CRYPTO']
    )[:20]  # Limit to 20 assets for performance
    
    for asset in assets:
        # Get last 50 price points
        prices = PriceHistory.objects.filter(
            asset=asset
        ).order_by('timestamp')[:50]
        
        price_values = [float(p.price) for p in prices]
        
        if len(price_values) >= 20:
            # Calculate SMA 20
            sma20 = sum(price_values[-20:]) / 20
            
            TechnicalIndicator.objects.update_or_create(
                asset=asset,
                indicator_type='SMA',
                period=20,
                timestamp=timezone.now(),
                defaults={
                    'value': {'sma': sma20}
                }
            )
            
            # Calculate RSI 14
            if len(price_values) >= 15:
                gains = []
                losses = []
                
                for i in range(1, 15):
                    change = price_values[-i] - price_values[-i-1]
                    if change > 0:
                        gains.append(change)
                        losses.append(0)
                    else:
                        gains.append(0)
                        losses.append(abs(change))
                
                avg_gain = sum(gains) / 14
                avg_loss = sum(losses) / 14
                
                if avg_loss > 0:
                    rs = avg_gain / avg_loss
                    rsi = 100 - (100 / (1 + rs))
                else:
                    rsi = 100
                
                TechnicalIndicator.objects.update_or_create(
                    asset=asset,
                    indicator_type='RSI',
                    period=14,
                    timestamp=timezone.now(),
                    defaults={
                        'value': {'rsi': rsi}
                    }
                )
    
    return "Technical indicators calculated"


@shared_task
def fetch_market_news():
    """Fetch market news (mock implementation)"""
    assets = Asset.objects.all()[:10]
    
    news_sources = ['Business Recorder', 'Dawn', 'The News', 'Bloomberg', 'Reuters']
    headlines = [
        "PSX hits new record high",
        "KSE-100 crosses 50,000 points",
        "Oil prices stabilize in international market",
        "Gold prices drop amid strong dollar",
        "Bitcoin surges above $50,000",
        "Pakistan's forex reserves increase",
        "IMF praises Pakistan's economic reforms",
        "PSX attracts foreign investment",
        "Cement sector shows strong growth",
        "Banking stocks rally on positive outlook"
    ]
    
    for asset in assets:
        NewsHeadline.objects.create(
            asset=asset,
            title=random.choice(headlines),
            summary=f"This is a sample news summary for {asset.name}",
            source=random.choice(news_sources),
            url="https://example.com/news",
            published_at=timezone.now() - timedelta(hours=random.randint(1, 24)),
            sentiment_score=Decimal(str(random.uniform(-0.5, 0.5))),
            sentiment_label=random.choice(['positive', 'neutral', 'negative'])
        )
    
    return f"Created {len(assets)} news items"   


@shared_task(bind=True, max_retries=3, soft_time_limit=60)
def fetch_oil_prices(self):
    """Fetch Brent and WTI crude oil prices"""
    try:
        oils = [
            {
                'symbol': 'BRENT',
                'name': 'Brent Crude',
                'unit': 'barrel',
                'yf_symbol': 'BZ=F',
                'commodity_type': 'ENERGY'
            },
            {
                'symbol': 'WTI',
                'name': 'WTI Crude',
                'unit': 'barrel',
                'yf_symbol': 'CL=F',
                'commodity_type': 'ENERGY'
            }
        ]

        results = []
        
        for oil in oils:
            # Try primary source (yfinance)
            price_data = fetch_oil_from_yfinance(oil)

            # Fallback to API id yfinance fails
            if not price_data:
                price_data = fetch_oil_from_url(oil)

            if price_data: 
                # save to database
                asset, created = Commodity.objects.get_or_create(
                    symbol=oil['symbol'],
                    defaults={
                        'name': oil['name'],
                        'asset_type': 'COMMODITY',
                        'commodity_type': oil['commodity_type'],
                        'unit': oil['unit'],
                        'currency': 'USD'
                    }
                )

                # If asset exists but is not a commodity instance, update it
                if not created and asset.asset_type == 'COMMODITY':
                    # Update commodity specific field if needed
                    if hasattr(asset, 'commodity_type'):
                        asset.commodity_type = oil['commodity_type']
                        asset.unit = oil['unit']
                        asset.save()

                # Create price history
                PriceHistory.objects.create(
                    asset=asset,
                    price=price_data['price'],
                    open_price=price_data.get('open', price_data['price']),
                    high_price=price_data.get('high', price_data['price']),
                    low_price=price_data.get('low', price_data['price']),
                    volume=price_data.get('volume', 0),
                    change_percent=price_data.get('change_percent', 0.0),
                    timestamp=timezone.now()
                )             

                results.append(f"{oil['symbol']}: ${price_data['price']:.2f}")
                logger.info(f"✅ Updated {oil['name']}: ${price_data['price']:.2f}")

        return "Oil prices updated: " + ", ".join(results)        
    
    except Exception as e:
        logger.error(f"Oil prices task failed: {e}")
        self.retry(countdown=60)


@shared_task(bind=True, max_retries=3)
def fetch_oil_from_url(self, oil):
    """Method to fetch oil prices using the url link for a specific oil type"""
    
    # Map your oil symbol to API codes
    api_code_map = {
        'WTI': 'WTI_USD',
        'BRENT': 'BRENT_CRUDE_USD'
    }
    
    # Get the API code for this specific oil
    target_api_code = api_code_map.get(oil['symbol'])
    
    if not target_api_code:
        print(f"⚠ No API mapping for {oil['symbol']}")
        return None

    try:
        # Fetch from the endpoint
        response = requests.get(
            'https://api.oilpriceapi.com/v1/demo/prices',
            timeout=10
        )

        if response.status_code == 200:
            data = response.json()

            if data.get('status') == 'success' and 'data' in data:
                prices_list = data['data'].get('prices', [])

                # Find the specific oil price
                for price_item in prices_list:
                    code = price_item.get('code')
                    
                    if code == target_api_code:
                        price = float(price_item['price'])
                        currency = price_item.get('currency', 'USD')
                        
                        return {
                            'price': price,
                            'currency': currency,
                            'timestamp': timezone.now()
                        }
                
                print(f"🔴 {oil['symbol']} not found in API response")
                return None
                
            else:
                print(f"🔴 Unexpected response format: {data}")
                return None

        elif response.status_code == 429:
            print(f"⚠ Rate limit reached (20 requests per hour)")
            return None
        else:
            print(f"⚠ API returned status code: {response.status_code}")
            return None

    except requests.exceptions.RequestException as e:
        error_msg = f"❌ Network error for {oil['symbol']}: {e}"
        print(error_msg)
        raise  # Re-raise to let the calling function handle retry
    except Exception as e:
        error_msg = f"❌ Unexpected error for {oil['symbol']}: {e}"
        print(error_msg)
        raise  # Re-raise to let the calling function handle retry
                       
                                                
def fetch_oil_from_yfinance(oil):
    """Fetch oil prices from Yahoo finance"""
    try:
        ticker = yf.Ticker(oil['yf_symbol'])
        data = ticker.history(period="1d", interval="5m")

        if not data.empty:
            latest = data.iloc[-1]

            # Get privous day's close for change calculations
            hist = ticker.history(period="2d")
            prev_close = hist['Close'].iloc[-2] if len(hist) > 1 else latest['Close']
            change_percent = ((latest['Close'] - prev_close) / prev_close) * 100

            return{
                'price': float(latest['Close']),
                'open': float(data['Open'].iloc[0]) if len(data) > 0 else float(latest['Close']),
                'high': float(data['High'].max()),
                'low': float(data['Low'].min()),
                'volume': int(latest['Volume']) if 'Volume' in latest else 0,
                'change_percent': float(change_percent)
            }

    except Exception as e:
        logger.warning(f"YFinance failed for {oil['symbol']}: {e}")

    return None   


@shared_task
def fetch_all_commodities():
    """Fetch all commodities prices"""

    # Fetch oil prices
    fetch_oil_prices.delay()

    return "All commodities update triggered"