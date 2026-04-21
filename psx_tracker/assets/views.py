from django.shortcuts import render, redirect
from django.db.models import Avg, Max, Min, Count, Q, Sum, F, Window, Avg
from django.db.models.functions import TruncHour, TruncDate, Rank
from django.http import JsonResponse
from rest_framework import viewsets, generics, status
from rest_framework.decorators import action, api_view
from rest_framework.response import Response
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from .models import Asset, PriceHistory, Alert, OHLCV, Stocks, UserPortfolio, PortfolioHolding, Watchlist, TechnicalIndicator, NewsHeadline, Commodity
from .serializers import AssetSerializer, PriceHistorySerializer, AlertSerializer, OHLCVSerializer, CommoditySerializer
from .tasks import fetch_kse100_data, fetch_gold_silver_prices, fetch_bitcoin_price
from django.db import connection
from celery import current_app
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from decimal import Decimal
import random









def dashboard(request):
    """Main dashboard view"""
    try:
        assets = Asset.objects.all().prefetch_related('prices')
        return render(request, 'assets/dashboard.html', {'assets': assets})
    except Exception as e:
        # Log the error but don't break the connection
        print(f"Dashboard error: {e}")
        return render(request, 'assets/dashboard.html', {'assets': []})


class AssetViewSet(viewsets.ModelViewSet):
    queryset = Asset.objects.all()
    serializer_class = AssetSerializer
    
    @action(detail=True, methods=['get'], url_path='price-history')
    def historical(self, request, pk=None):
        """Get historical data with PostgreSQL aggregations"""
        asset = self.get_object()
        days = int(request.query_params.get('days', 7))
        cutoff = timezone.now() - timedelta(days=days)
        
        # PostgreSQL specific: using aggregation
        history = PriceHistory.objects.filter(
            asset=asset, 
            timestamp__gte=cutoff
        ).annotate(
            date=TruncDate('timestamp')
        ).values('date').annotate(
            avg_price=Avg('price'),
            max_price=Max('high_price'),
            min_price=Min('low_price'),
            count=Count('id')
        ).order_by('date')
        
        return Response(history)


class PriceHistoryViewSet(viewsets.ModelViewSet):
    queryset = PriceHistory.objects.all()
    serializer_class = PriceHistorySerializer
    
    def get_queryset(self):
        queryset = PriceHistory.objects.all()
        asset_id = self.request.query_params.get('asset', None)
        if asset_id:
            queryset = queryset.filter(asset_id=asset_id)
        return queryset.order_by('-timestamp')[:1000]  # PostgreSQL efficient limit


class AlertViewSet(viewsets.ModelViewSet):
    queryset = Alert.objects.all()
    serializer_class = AlertSerializer
    
    @action(detail=False, methods=['post'])
    def check_alerts(self, request):
        """Check and trigger alerts"""
        alerts = Alert.objects.filter(is_active=True)
        triggered = []
        
        for alert in alerts:
            latest_price = alert.asset.prices.first()
            if latest_price:
                should_trigger = False
                
                if alert.condition == 'ABOVE' and latest_price.price > alert.target_price:
                    should_trigger = True
                elif alert.condition == 'BELOW' and latest_price.price < alert.target_price:
                    should_trigger = True
                
                if should_trigger:
                    alert.is_active = False
                    alert.triggered_at = timezone.now()
                    alert.save()
                    triggered.append({
                        'alert_id': alert.id,
                        'asset': alert.asset.symbol,
                        'price': float(latest_price.price),
                        'target': float(alert.target_price)
                    })
        
        return Response({'triggered_alerts': triggered})

def api_fetch_all_prices(request):
    """Force the broker URL right before calling the task"""
    current_app.conf.broker_url = 'redis://172.28.179.241:6379/0'
    current_app.conf.result_backend = 'redis://172.28.179.241:6379/0'
    
    # API endpoint to manually trigger price updates
    fetch_kse100_data.delay()
    fetch_gold_silver_prices.delay()
    fetch_bitcoin_price.delay()
    return JsonResponse({'status': 'Price updates started'})

def psql_stats(request):
    """PostgreSQL specific statistics"""
    
    with connection.cursor() as cursor:
        # Get table size
        cursor.execute("""
            SELECT 
                relname as table_name,
                pg_size_pretty(pg_total_relation_size(relid)) as total_size,
                pg_size_pretty(pg_relation_size(relid)) as table_size,
                pg_size_pretty(pg_total_relation_size(relid) - pg_relation_size(relid)) as index_size,
                n_live_tup as rows
            FROM pg_stat_user_tables 
            WHERE schemaname = 'public'
            ORDER BY pg_total_relation_size(relid) DESC;
        """)
        table_stats = cursor.fetchall()
    
    return JsonResponse({'table_stats': table_stats})


class StockViewSet(viewsets.ModelViewSet):
    queryset = Stocks.objects.all()
    serializer_class = AssetSerializer
    
    @action(detail=False, methods=['get'])
    def by_sector(self, request):
        """Group stocks by sector using PostgreSQL aggregation"""
        sectors = Stocks.objects.values('sector').annotate(
            count=Count('id'),
            avg_market_cap=Avg('market_cap'),
            avg_pe_ratio=Avg('pe_ratio'),
            total_companies=Count('id')
        ).order_by('sector')
        
        return Response(sectors)
    
    @action(detail=False, methods=['get'])
    def top_gainers(self, request):
        """Get top gaining stocks today"""
        from django.utils import timezone
        today = timezone.now().date()
        
        stocks = Stocks.objects.filter(
            prices__timestamp__date=today
        ).annotate(
            current_price=F('prices__price'),
            change_percent=F('prices__change_percent')
        ).order_by('-change_percent')[:10]
        
        serializer = self.get_serializer(stocks, many=True)
        return Response(serializer.data)


class UserPortfolioViewSet(viewsets.ModelViewSet):
    queryset = UserPortfolio.objects.all()
    serializer_class = None  # You would create a serializer
    
    @action(detail=True, methods=['get'])
    def performance(self, request, pk=None):
        """Get portfolio performance using PostgreSQL window functions"""
        portfolio = self.get_object()
        
        holdings = PortfolioHolding.objects.filter(
            portfolio=portfolio
        ).annotate(
            current_price=F('asset__prices__price'),
            market_value=F('quantity') * F('current_price'),
            return_amount=F('market_value') - F('invested_amount'),
            return_percent=(F('return_amount') / F('invested_amount')) * 100
        )
        
        total_invested = holdings.aggregate(total=Sum('invested_amount'))['total'] or 0
        total_value = holdings.aggregate(total=Sum(F('quantity') * F('asset__prices__price')))['total'] or 0
        total_return = total_value - total_invested
        total_return_percent = (total_return / total_invested * 100) if total_invested > 0 else 0
        
        return Response({
            'total_invested': total_invested,
            'total_value': total_value,
            'total_return': total_return,
            'total_return_percent': total_return_percent,
            'holdings': list(holdings.values(
                'asset__symbol', 'quantity', 'average_price', 
                'invested_amount', 'market_value', 'return_percent'
            ))
        })


class WatchlistViewSet(viewsets.ModelViewSet):
    queryset = Watchlist.objects.all()
    serializer_class = None
    
    @action(detail=True, methods=['post'])
    def add_asset(self, request, pk=None):
        """Add asset to watchlist"""
        watchlist = self.get_object()
        asset_id = request.data.get('asset_id')
        
        try:
            asset = Asset.objects.get(id=asset_id)
            item, created = WatchlistItem.objects.get_or_create(
                watchlist=watchlist,
                asset=asset
            )
            if created:
                return Response({'status': 'added'}, status=status.HTTP_201_CREATED)
            else:
                return Response({'status': 'already_exists'}, status=status.HTTP_200_OK)
        except Asset.DoesNotExist:
            return Response({'error': 'Asset not found'}, status=status.HTTP_404_NOT_FOUND)


class TechnicalIndicatorViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = TechnicalIndicator.objects.all()
    serializer_class = None
    
    @action(detail=False, methods=['get'])
    def latest(self, request):
        """Get latest indicators for all assets"""
        asset_id = request.query_params.get('asset')
        indicator_type = request.query_params.get('type')
        
        # Use PostgreSQL DISTINCT ON
        indicators = TechnicalIndicator.objects.filter(
            asset_id=asset_id if asset_id else None,
            indicator_type=indicator_type if indicator_type else None
        ).order_by('asset', 'indicator_type', 'period', '-timestamp').distinct('asset', 'indicator_type', 'period')
        
        data = []
        for indicator in indicators[:20]:
            data.append({
                'asset': indicator.asset.symbol,
                'type': indicator.indicator_type,
                'period': indicator.period,
                'value': indicator.value,
                'timestamp': indicator.timestamp
            })
        
        return Response(data)

def market_summary(request):
    """Get overall market summary"""
    from django.db import connection
    
    with connection.cursor() as cursor:
        # PostgreSQL query for market summary
        cursor.execute("""
            SELECT 
                COUNT(DISTINCT a.id) as total_assets,
                COUNT(DISTINCT CASE WHEN a.asset_type = 'STOCK' THEN a.id END) as total_stocks,
                AVG(ph.price) as avg_price,
                MAX(ph.price) as max_price,
                MIN(ph.price) as min_price
            FROM assets_asset a
            LEFT JOIN assets_pricehistory ph ON a.id = ph.asset_id
            WHERE ph.timestamp = (
                SELECT MAX(timestamp) 
                FROM assets_pricehistory 
                WHERE asset_id = a.id
            )
        """)
        
        row = cursor.fetchone()
    
    return JsonResponse({
        'total_assets': row[0],
        'total_stocks': row[1],
        'avg_price': float(row[2]) if row[2] else 0,
        'max_price': float(row[3]) if row[3] else 0,
        'min_price': float(row[4]) if row[4] else 0,
    })

def sector_performance(request):
    """Get sector-wise performance"""
    from django.db.models import Avg, Max, Min
    
    sectors = Stocks.objects.values('sector').annotate(
        avg_change=Avg('prices__change_percent'),
        avg_price=Avg('prices__price'),
        total_market_cap=Sum('market_cap'),
        stocks_count=Count('id')
    ).order_by('-avg_change')
    
    return JsonResponse(list(sectors), safe=False)

def portfolio_detail(request, portfolio_id):
    """Render portfolio detail page"""
    try:
        portfolio = UserPortfolio.objects.get(id=portfolio_id)
        holdings = PortfolioHolding.objects.filter(portfolio=portfolio).select_related('asset')
        
        context = {
            'portfolio': portfolio,
            'holdings': holdings
        }
        return render(request, 'assets/portfolio_detail.html', context)
    except UserPortfolio.DoesNotExist:
        return render(request, '404.html', status=404)

def watchlist_view(request):
    """Render watchlist page"""
    if request.user.is_authenticated:
        watchlists = Watchlist.objects.filter(user=request.user).prefetch_related('assets')
        context = {'watchlists': watchlists}
        return render(request, 'assets/watchlist.html', context)
    else:
        return redirect('login')
    

class CommodityViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for commodities"""
    queryset = Commodity.objects.all()
    serializer_class = CommoditySerializer

    @action(detail=False, methods=['get'])
    def by_type(self, request):
        """Get commodities by type"""
        commodity_type = request.query_params.get('type', None)
        if commodity_type:
            commodities = self.queryset.filter(commodity_type=commodity_type)
        else:
            commodities = self.queryset

        serializer = self.get_serializer(commodities, many=True)
        return Response(serializer.data)    
    
    @action(detail=False, methods=['get'])
    def energy(self, request):
        """Get energy commodities"""
        energy = self.queryset.filter(Commodity_type='ENERGY')
        serializer =  self.get_serializer(energy, many=True)
        return Response(serializer.data)
    

@api_view(['GET'])
def oil_prices(request):
    """Get latest oil prices with 24h stats"""
    oils = Commodity.objects.filter(
        Q(symbol='BRENT') | Q(symbol='WTI'),
        commodity_type='ENERGY'
    )
    
    result = []
    for oil in oils:
        latest = oil.prices.first()
        if latest:
            # Get 24h high/low
            day_ago = timezone.now() - timedelta(hours=24)
            day_prices = oil.prices.filter(timestamp__gte=day_ago)
            
            high_24h = day_prices.aggregate(Max('high_price'))['high_price__max'] or latest.price
            low_24h = day_prices.aggregate(Min('low_price'))['low_price__min'] or latest.price
            
            # Get previous price for change
            previous = oil.prices.filter(timestamp__lt=latest.timestamp).first()
            change = 0
            change_percent = 0
            
            if previous:
                change = float(latest.price) - float(previous.price)
                change_percent = (change / float(previous.price)) * 100
            
            # Get price history for chart (last 24 hours, 1 point per hour)
            hourly_prices = []
            for hour in range(24, 0, -1):
                hour_time = timezone.now() - timedelta(hours=hour)
                hour_price = oil.prices.filter(
                    timestamp__gte=hour_time,
                    timestamp__lt=hour_time + timedelta(hours=1)
                ).first()
                if hour_price:
                    hourly_prices.append({
                        'time': hour_time.strftime('%H:00'),
                        'price': float(hour_price.price)
                    })
            
            result.append({
                'symbol': oil.symbol,
                'name': oil.name,
                'price': float(latest.price),
                'change': change,
                'change_percent': change_percent,
                'high_24h': float(high_24h) if high_24h else None,
                'low_24h': float(low_24h) if low_24h else None,
                'volume': latest.volume,
                'unit': oil.unit,
                'currency': oil.currency,
                'timestamp': latest.timestamp,
                'hourly_prices': hourly_prices
            })
    
    return Response(result)

@api_view(['GET'])
def oil_detail(request, symbol):
    """Get detailed oil data for a specific symbol"""
    try:
        oil = Commodity.objects.get(
            Q(symbol=symbol.upper()),
            commodity_type='ENERGY'
        )
    except Commodity.DoesNotExist:
        return Response({'error': 'Oil not found'}, status=404)
    
    latest = oil.prices.first()
    if not latest:
        return Response({'error': 'No price data'}, status=404)
    
    # Get 7-day history
    week_ago = timezone.now() - timedelta(days=7)
    week_prices = oil.prices.filter(timestamp__gte=week_ago).order_by('timestamp')
    
    # Calculate stats
    prices = [float(p.price) for p in week_prices if p.price > 0]
    
    stats = {
        'current': float(latest.price),
        'high_7d': max(prices) if prices else None,
        'low_7d': min(prices) if prices else None,
        'avg_7d': sum(prices) / len(prices) if prices else None,
        'volume_7d_avg': week_prices.aggregate(Avg('volume'))['volume__avg'] or 0,
    }
    
    # Get technical indicators if available
    indicators = TechnicalIndicator.objects.filter(
        asset=oil,
        timestamp__gte=week_ago
    ).order_by('-timestamp')[:10]
    
    # Format price history for chart
    price_history = [
        {
            'date': p.timestamp.strftime('%Y-%m-%d %H:00'),
            'price': float(p.price),
            'volume': p.volume
        }
        for p in week_prices
    ]
    
    return Response({
        'symbol': oil.symbol,
        'name': oil.name,
        'unit': oil.unit,
        'currency': oil.currency,
        'latest_price': {
            'price': float(latest.price),
            'timestamp': latest.timestamp,
            'change_percent': float(latest.change_percent) if latest.change_percent else 0
        },
        'statistics': stats,
        'price_history': price_history,
        'indicators': [
            {
                'type': i.indicator_type,
                'period': i.period,
                'value': i.value,
                'timestamp': i.timestamp
            }
            for i in indicators
        ]
    })

@api_view(['GET'])
def oil_comparison(request):
    """Compare Brent vs WTI"""
    brent = Commodity.objects.filter(symbol='BRENT', commodity_type='ENERGY').first()
    wti = Commodity.objects.filter(symbol='WTI', commodity_type='ENERGY').first()
    
    if not brent or not wti:
        return Response({'error': 'Oil data not available'}, status=404)
    
    brent_latest = brent.prices.first()
    wti_latest = wti.prices.first()
    
    if not brent_latest or not wti_latest:
        return Response({'error': 'Price data not available'}, status=404)
    
    # Get spread history (Brent - WTI)
    week_ago = timezone.now() - timedelta(days=7)
    brent_week = brent.prices.filter(timestamp__gte=week_ago).order_by('timestamp')
    wti_week = wti.prices.filter(timestamp__gte=week_ago).order_by('timestamp')
    
    # Match timestamps for spread calculation
    spread_history = []
    for b, w in zip(brent_week, wti_week):
        if abs((b.timestamp - w.timestamp).total_seconds()) < 3600:  # Within 1 hour
            spread_history.append({
                'timestamp': b.timestamp,
                'spread': float(b.price - w.price),
                'brent_price': float(b.price),
                'wti_price': float(w.price)
            })
    
    return Response({
        'brent': {
            'price': float(brent_latest.price),
            'change': float(brent_latest.change_percent or 0)
        },
        'wti': {
            'price': float(wti_latest.price),
            'change': float(wti_latest.change_percent or 0)
        },
        'spread': float(brent_latest.price - wti_latest.price),
        'spread_history': spread_history[-24:],  # Last 24 points
        'timestamp': timezone.now()
    })


def asset_list(request):
    """Return all assets with current prices"""
    assets = Asset.objects.all()
    
    data = {
        'results': [{
            'id': asset.id,
            'symbol': asset.symbol,
            'name': asset.name,
            'asset_type': asset.asset_type,
            'current_price': float(asset.current_price) if hasattr(asset, 'current_price') else get_latest_price(asset),
            'currency': asset.currency,
            'price_change': calculate_price_change(asset)
        } for asset in assets]
    }
    return JsonResponse(data)


def get_latest_price(asset):
    """Get latest price from PriceHistory model"""
    latest = PriceHistory.objects.filter(asset=asset).order_by('-timestamp').first()
    return float(latest.price) if latest else None


def calculate_price_change(asset):
    """Calculate 24h price change percentage from PriceHistory"""
    now = timezone.now()
    yesterday = now - timedelta(days=1)
    
    # Get current price
    current = PriceHistory.objects.filter(asset=asset).first()
    # Get price from 24 hours ago
    old = PriceHistory.objects.filter(
        asset=asset, 
        timestamp__gte=yesterday
    ).order_by('timestamp').first()
    
    if current and old and old.price > 0:
        change = ((current.price - old.price) / old.price) * 100
        return round(float(change), 2)
    return 0.00


def asset_historical(request, asset_symbol):
    """Return historical prices for an asset from PriceHistory model"""
    days = request.GET.get('days', 7)
    
    try:
        asset = Asset.objects.get(symbol=asset_symbol)
    except Asset.DoesNotExist:
        return JsonResponse({'error': 'Asset not found'}, status=404)
    
    # Get historical data from PriceHistory model
    cutoff_date = timezone.now() - timedelta(days=int(days))
    history = PriceHistory.objects.filter(
        asset=asset,
        timestamp__gte=cutoff_date
    ).order_by('timestamp')
    
    if history.exists():
        data = [{
            'date': h.timestamp.date().isoformat(),
            'timestamp': h.timestamp.isoformat(),
            'price': float(h.price),
            'avg_price': float(h.price),
            'open': float(h.open_price) if h.open_price else None,
            'high': float(h.high_price) if h.high_price else None,
            'low': float(h.low_price) if h.low_price else None,
            'volume': h.volume
        } for h in history]
        return JsonResponse(data, safe=False)
    else:
        # Generate realistic historical data if none exists
        return generate_realistic_history(asset, days)


def generate_realistic_history(asset, days):
    """Generate realistic up/down historical data with true stock movement"""
    data = []
    now = timezone.now()
    
    # Get current price or set a realistic baseline
    latest_price = get_latest_price(asset)
    if latest_price:
        base_price = latest_price
    else:
        # Set realistic baseline prices based on asset type and symbol
        base_prices = {
            'KSE100': 46820, 'BRENT': 84.50, 'WTI': 79.30,
            'XAU': 2358.20, 'XAG': 28.45, 'BTC': 64200
        }
        base_price = base_prices.get(asset.symbol, 100)
    
    # Generate random walk with realistic volatility
    prices = []
    current_price = base_price
    
    # Determine volatility based on asset type
    if hasattr(asset, 'asset_type'):
        if asset.asset_type == 'CRYPTO':
            volatility = 0.045  # 4.5% daily volatility
        elif asset.asset_type == 'COMMODITY':
            volatility = 0.025  # 2.5% daily volatility
        else:
            volatility = 0.018  # 1.8% daily volatility
    else:
        volatility = 0.02
    
    # Generate prices with realistic up/down movement
    for i in range(int(days), -1, -1):
        # Add randomness with trend component
        random_component = random.uniform(-volatility, volatility)
        # Add slight momentum (makes it look more realistic)
        momentum = 0.002 * random.choice([-1, 1])
        change_percent = random_component + momentum
        
        current_price = current_price * (1 + change_percent)
        
        # Ensure price doesn't go negative or unrealistic
        if asset.symbol == 'KSE100':
            current_price = max(current_price, 30000)
            price_value = round(current_price)
        elif asset.symbol == 'BTC':
            current_price = max(current_price, 15000)
            price_value = round(current_price)
        elif asset.symbol == 'XAG':
            price_value = round(current_price, 3)
        else:
            price_value = round(current_price, 2)
        
        date = now - timedelta(days=i)
        data.append({
            'date': date.date().isoformat(),
            'timestamp': date.isoformat(),
            'price': price_value,
            'avg_price': price_value,
            'open': price_value * random.uniform(0.995, 1.005),
            'high': price_value * random.uniform(1.002, 1.01),
            'low': price_value * random.uniform(0.99, 0.998),
            'volume': random.randint(100000, 10000000)
        })
    
    return JsonResponse(data, safe=False)


@csrf_exempt
def fetch_all_prices(request):
    """Manual price update endpoint"""
    try:
        # This is where you would integrate with external APIs
        # For now, we'll generate realistic price movements
        
        assets = Asset.objects.all()
        updated_count = 0
        
        for asset in assets:
            # Get last price
            last_price = PriceHistory.objects.filter(asset=asset).first()
            
            if last_price:
                # Generate new price with realistic movement
                if hasattr(asset, 'asset_type'):
                    if asset.asset_type == 'CRYPTO':
                        change = random.uniform(-0.05, 0.05)
                    elif asset.asset_type == 'COMMODITY':
                        change = random.uniform(-0.03, 0.03)
                    else:
                        change = random.uniform(-0.02, 0.02)
                else:
                    change = random.uniform(-0.02, 0.02)
                
                new_price = last_price.price * (1 + Decimal(str(change)))
                
                # Create new price history entry
                PriceHistory.objects.create(
                    asset=asset,
                    price=new_price,
                    timestamp=timezone.now(),
                    open_price=last_price.price,
                    high_price=new_price * Decimal('1.005'),
                    low_price=new_price * Decimal('0.995'),
                    change_percent=Decimal(str(change * 100))
                )
                updated_count += 1
        
        return JsonResponse({
            'status': 'success',
            'message': f'Updated {updated_count} assets',
            'updated_assets': updated_count
        })
        
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)


def get_asset_details(request, asset_symbol):
    """Get detailed information about a specific asset"""
    try:
        asset = Asset.objects.get(symbol=asset_symbol)
        
        # Get additional data based on asset type
        additional_data = {}
        
        # Check if it's an Index
        if hasattr(asset, 'index'):
            index = asset.index
            additional_data['constituents_count'] = index.constituents.count()
            additional_data['calculation_method'] = index.calculation_method
        
        # Check if it's a Commodity
        elif hasattr(asset, 'commodity'):
            commodity = asset.commodity
            additional_data['commodity_type'] = commodity.commodity_type
            additional_data['unit'] = commodity.unit
        
        # Check if it's a Cryptocurrency
        elif hasattr(asset, 'cryptocurrency'):
            crypto = asset.cryptocurrency
            additional_data['coin_gecko_id'] = crypto.coin_gecko_id
            additional_data['market_cap_rank'] = crypto.market_cap_rank
        
        # Get latest price
        latest_price = PriceHistory.objects.filter(asset=asset).first()
        
        # Get 24h stats
        yesterday = timezone.now() - timedelta(days=1)
        daily_prices = PriceHistory.objects.filter(
            asset=asset,
            timestamp__gte=yesterday
        )
        
        data = {
            'id': asset.id,
            'symbol': asset.symbol,
            'name': asset.name,
            'asset_type': asset.asset_type,
            'currency': asset.currency,
            'current_price': float(latest_price.price) if latest_price else None,
            'exchange': asset.exchange,
            'metadata': asset.metadata,
            'additional_info': additional_data,
            'stats_24h': {
                'high': float(daily_prices.aggregate(Max('price'))['price__max']) if daily_prices else None,
                'low': float(daily_prices.aggregate(Min('price'))['price__min']) if daily_prices else None,
                'average': float(daily_prices.aggregate(Avg('price'))['price__avg']) if daily_prices else None,
                'volume': daily_prices.aggregate(Sum('volume'))['volume__sum'] if daily_prices else None,
            }
        }
        
        return JsonResponse(data)
        
    except Asset.DoesNotExist:
        return JsonResponse({'error': 'Asset not found'}, status=404)


def get_market_overview(request):
    """Get market overview with indices and commodities"""
    indices = Asset.objects.filter(asset_type='INDEX')
    commodities = Asset.objects.filter(asset_type='COMMODITY')
    crypto = Asset.objects.filter(asset_type='CRYPTO')
    
    def get_asset_data(asset):
        latest_price = PriceHistory.objects.filter(asset=asset).first()
        return {
            'symbol': asset.symbol,
            'name': asset.name,
            'price': float(latest_price.price) if latest_price else None,
            'currency': asset.currency,
        }
    
    return JsonResponse({
        'indices': [get_asset_data(asset) for asset in indices],
        'commodities': [get_asset_data(asset) for asset in commodities],
        'cryptocurrencies': [get_asset_data(asset) for asset in crypto],
        'last_updated': timezone.now().isoformat()
    })