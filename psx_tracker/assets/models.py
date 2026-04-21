from django.db import models
from django.contrib.postgres.fields import JSONField, ArrayField
from django.contrib.postgres.indexes import BrinIndex
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import RangeOperators, DateTimeRangeField
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator






class Asset(models.Model):
    ASSET_TYPES = [
        ('INDEX', 'Stock Index'),
        ('COMMODITY', 'Commodity'),
        ('CRYPTO', 'Cryptocurrency'),
    ]
    
    symbol = models.CharField(max_length=20, unique=True, db_index=True)
    name = models.CharField(max_length=100)
    asset_type = models.CharField(max_length=20, choices=ASSET_TYPES)
    exchange = models.CharField(max_length=50, null=True, blank=True)
    currency = models.CharField(max_length=10, default='PKR')
    
    # PostgreSQL specific field
    metadata = models.JSONField(default=dict, null=True, blank=True)
    
    # Audit fields
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['symbol']
        indexes = [
            models.Index(fields=['symbol', 'asset_type']),
            BrinIndex(fields=['created_at'], pages_per_range=16),  # PostgreSQL BRIN index
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['symbol', 'asset_type'],
                name='unique_asset_symbol_type'
            )
        ]
    
    def __str__(self):
        return f"{self.symbol} - {self.name}"


class PriceHistory(models.Model):
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name='prices')
    price = models.DecimalField(max_digits=20, decimal_places=4)
    open_price = models.DecimalField(max_digits=20, decimal_places=4, null=True)
    high_price = models.DecimalField(max_digits=20, decimal_places=4, null=True)
    low_price = models.DecimalField(max_digits=20, decimal_places=4, null=True)
    volume = models.BigIntegerField(null=True)
    change_percent = models.DecimalField(max_digits=10, decimal_places=4, null=True)
    
    # Using PostgreSQL's DateTimeRangeField
    valid_period = DateTimeRangeField(null=True, blank=True)
    timestamp = models.DateTimeField(db_index=True)
    
    # PostgreSQL specific field for storing additional data
    indicators = models.JSONField(default=dict, null=True, blank=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['asset', 'timestamp']),
            BrinIndex(fields=['timestamp'], pages_per_range=32),  # Optimize for time-based queries
        ]
        ordering = ['-timestamp']
        constraints = [
            models.UniqueConstraint(
                fields=['asset', 'timestamp'],
                name='unique_asset_timestamp'
            )
        ]
    
    def __str__(self):
        return f"{self.asset.symbol} - {self.price} at {self.timestamp}"


class Alert(models.Model):
    ALERT_CONDITIONS = [
        ('ABOVE', 'Price Above'),
        ('BELOW', 'Price Below'),
        ('CROSS_ABOVE', 'Cross Above'),
        ('CROSS_BELOW', 'Cross Below'),
    ]
    
    user = models.ForeignKey('auth.User', on_delete=models.CASCADE)
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE)
    condition = models.CharField(max_length=20, choices=ALERT_CONDITIONS)
    target_price = models.DecimalField(max_digits=20, decimal_places=4)
    is_active = models.BooleanField(default=True)
    triggered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.user.username} - {self.asset.symbol} {self.condition} {self.target_price}"


class OHLCV(models.Model):
    """For storing OHLCV data (PostgreSQL array example)"""
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name='ohlcv')
    timeframe = models.CharField(max_length=10, default='1d')  # 1m, 5m, 15m, 1h, 1d, 1w
    
    # Using PostgreSQL array fields
    timestamps = models.JSONField(default=list)  # Array of timestamps
    opens = models.JSONField(default=list)  # Array of open prices
    highs = models.JSONField(default=list)  # Array of high prices
    lows = models.JSONField(default=list)  # Array of low prices
    closes = models.JSONField(default=list)  # Array of close prices
    volumes = models.JSONField(default=list)  # Array of volumes
    
    last_updated = models.DateTimeField(auto_now=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['asset', 'timeframe', '-last_updated'])
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['asset', 'timeframe'],
                name='unique_asset_timeframe'
            )
        ]


class Stocks(Asset):
    """Stock model inheriting from Asset"""
    # PostgreSQL specific: using materialized path for company hierarchy
    company_name = models.CharField(max_length=200)
    sector = models.CharField(max_length=100, db_index=True)
    industry = models.CharField(max_length=100, null=True, blank=True)
    listing_date = models.DateField(null=True, blank=True)
    shares_outstanding = models.BigIntegerField(null=True, blank=True)
    market_cap = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    pe_ratio = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    eps = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    dividend_yield = models.DecimalField(max_digits=8, decimal_places=4, null=True, blank=True)
    beta = models.DecimalField(max_digits=6, decimal_places=4, null=True, blank=True)
    week_52_high = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    week_52_low = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    
    # PostgreSQL full-text search fields
    search_vector = models.TextField(null=True, blank=True)  # Will be populated with searchable content
    
    class Meta:
        indexes = [
            models.Index(fields=['sector', 'industry']),
            models.Index(fields=['market_cap']),
        ]
    
    def __str__(self):
        return f"{self.symbol} - {self.company_name}"


class Index(Asset):
    """Stock index model"""
    constituents = models.ManyToManyField(Stocks, through='IndexConstituent', blank=True)
    calculation_method = models.CharField(max_length=50, default='Market Cap Weighted')
    base_value = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    base_date = models.DateField(null=True, blank=True)
    
    def __str__(self):
        return f"{self.symbol} - {self.name}"


class IndexConstituent(models.Model):
    """Many-to-many relationship between Index and Stock with weight"""
    index = models.ForeignKey(Index, on_delete=models.CASCADE)
    stock = models.ForeignKey(Stocks, on_delete=models.CASCADE)
    weight = models.DecimalField(max_digits=8, decimal_places=4, validators=[MinValueValidator(0), MaxValueValidator(100)])
    added_date = models.DateField(auto_now_add=True)
    
    class Meta:
        unique_together = ['index', 'stock']
        indexes = [
            models.Index(fields=['index', 'weight']),
        ]


class Commodity(Asset):
    """Commodity model (Gold, Silver, Oil etc.)"""
    COMMODITY_TYPES = [
        ('PRECIOUS', 'Precious Metal'),
        ('BASE', 'Base Metal'),
        ('ENERGY', 'Energy'),
        ('AGRICULTURAL', 'Agricultural'),
    ]
    
    commodity_type = models.CharField(max_length=50, choices=COMMODITY_TYPES)
    unit = models.CharField(max_length=20, default='oz')  # ounce, gram, tola
    purity = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)  # 99.99% etc
    
    def __str__(self):
        return f"{self.name} ({self.unit})"


class Cryptocurrency(Asset):
    """Cryptocurrency model"""
    coin_gecko_id = models.CharField(max_length=50, null=True, blank=True)
    circulating_supply = models.BigIntegerField(null=True, blank=True)
    total_supply = models.BigIntegerField(null=True, blank=True)
    max_supply = models.BigIntegerField(null=True, blank=True)
    market_cap_rank = models.IntegerField(null=True, blank=True)
    
    def __str__(self):
        return f"{self.symbol} - {self.name}"


class UserPortfolio(models.Model):
    """User investment portfolio"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='portfolios')
    name = models.CharField(max_length=100)
    description = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # PostgreSQL array field for performance metrics
    performance_history = models.JSONField(default=list, blank=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['user', '-created_at']),
        ]
    
    def __str__(self):
        return f"{self.user.username}'s {self.name}"


class PortfolioHolding(models.Model):
    """Individual holdings in a portfolio"""
    portfolio = models.ForeignKey(UserPortfolio, on_delete=models.CASCADE, related_name='holdings')
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE)
    quantity = models.DecimalField(max_digits=20, decimal_places=8)
    average_price = models.DecimalField(max_digits=20, decimal_places=4)
    invested_amount = models.DecimalField(max_digits=20, decimal_places=2)
    purchase_date = models.DateField()
    notes = models.TextField(null=True, blank=True)
    
    # Current value (updated via task)
    current_value = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    unrealized_pl = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    unrealized_pl_percent = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    last_updated = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['portfolio', 'asset']
        indexes = [
            models.Index(fields=['portfolio', 'asset']),
        ]
    
    def __str__(self):
        return f"{self.portfolio.name} - {self.asset.symbol} ({self.quantity})"


class Watchlist(models.Model):
    """User watchlist for tracking assets"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='watchlists')
    name = models.CharField(max_length=100, default='My Watchlist')
    assets = models.ManyToManyField(Asset, through='WatchlistItem', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.user.username}'s {self.name}"


class WatchlistItem(models.Model):
    """Items in a watchlist with alert preferences"""
    watchlist = models.ForeignKey(Watchlist, on_delete=models.CASCADE)
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE)
    added_at = models.DateTimeField(auto_now_add=True)
    notes = models.CharField(max_length=200, null=True, blank=True)
    
    # Notification preferences
    price_alert_enabled = models.BooleanField(default=False)
    alert_threshold_above = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    alert_threshold_below = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    
    class Meta:
        unique_together = ['watchlist', 'asset']
        indexes = [
            models.Index(fields=['watchlist', '-added_at']),
        ]


class NewsHeadline(models.Model):
    """Market news and announcements"""
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name='news', null=True, blank=True)
    title = models.CharField(max_length=500)
    summary = models.TextField(null=True, blank=True)
    source = models.CharField(max_length=100)
    url = models.URLField(max_length=500)
    published_at = models.DateTimeField()
    
    # PostgreSQL full-text search
    search_vector = models.TextField(null=True, blank=True)
    
    # Sentiment analysis
    sentiment_score = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)
    sentiment_label = models.CharField(max_length=20, null=True, blank=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['-published_at']),
            models.Index(fields=['asset', '-published_at']),
        ]
        ordering = ['-published_at']
    
    def __str__(self):
        return f"{self.title[:50]}..."


class TechnicalIndicator(models.Model):
    """Technical indicators for assets"""
    INDICATOR_TYPES = [
        ('SMA', 'Simple Moving Average'),
        ('EMA', 'Exponential Moving Average'),
        ('RSI', 'Relative Strength Index'),
        ('MACD', 'Moving Average Convergence Divergence'),
        ('BB', 'Bollinger Bands'),
        ('STOCH', 'Stochastic Oscillator'),
    ]
    
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name='indicators')
    indicator_type = models.CharField(max_length=20, choices=INDICATOR_TYPES)
    period = models.IntegerField()
    value = models.JSONField()  # Could be single value or multiple values
    timestamp = models.DateTimeField(db_index=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['asset', 'indicator_type', '-timestamp']),
        ]
        unique_together = ['asset', 'indicator_type', 'period', 'timestamp']
    
    def __str__(self):
        return f"{self.asset.symbol} - {self.indicator_type}({self.period})"


class MarketHoliday(models.Model):
    """PSX market holidays"""
    date = models.DateField(unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(null=True, blank=True)
    
    def __str__(self):
        return f"{self.date} - {self.name}"