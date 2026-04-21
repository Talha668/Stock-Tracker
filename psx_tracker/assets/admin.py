from django.contrib import admin
from django.contrib.postgres import fields
from django_json_widget.widgets import JSONEditorWidget
from .models import *




class PriceHistoryInline(admin.TabularInline):
    model = PriceHistory
    extra = 0
    fields = ['price', 'timestamp', 'change_percent']
    readonly_fields = ['timestamp']
    ordering = ['-timestamp']
    max_num = 10


class IndexConstituentInline(admin.TabularInline):
    model = IndexConstituent
    extra = 1

@admin.register(Asset)
class AssetAdmin(admin.ModelAdmin):
    list_display = ['symbol', 'name', 'asset_type', 'currency', 'updated_at']
    list_filter = ['asset_type', 'currency']
    search_fields = ['symbol', 'name']
    inlines = [PriceHistoryInline]
    
    # PostgreSQL JSON field widget
    formfield_overrides = {
        fields.JSONField: {'widget': JSONEditorWidget},
    }

@admin.register(Stocks)
class StockAdmin(admin.ModelAdmin):
    list_display = ['symbol', 'company_name', 'sector', 'market_cap', 'pe_ratio']
    list_filter = ['sector', 'industry']
    search_fields = ['symbol', 'company_name']
    fieldsets = (
        ('Basic Information', {
            'fields': ('symbol', 'name', 'company_name', 'sector', 'industry')
        }),
        ('Financials', {
            'fields': ('market_cap', 'pe_ratio', 'eps', 'dividend_yield', 'beta')
        }),
        ('Trading Info', {
            'fields': ('listing_date', 'shares_outstanding', 'week_52_high', 'week_52_low')
        }),
    )

@admin.register(Index)
class IndexAdmin(admin.ModelAdmin):
    list_display = ['symbol', 'name', 'base_date', 'base_value']
    search_fields = ['symbol', 'name']
    inlines = [IndexConstituentInline]

@admin.register(IndexConstituent)
class IndexConstituentAdmin(admin.ModelAdmin):
    list_display = ['index', 'stock', 'weight']
    list_filter = ['index']
    search_fields = ['stock__symbol', 'stock__company_name']

@admin.register(Commodity)
class CommodityAdmin(admin.ModelAdmin):
    list_display = ['symbol', 'name', 'commodity_type', 'unit', 'currency']
    list_filter = ['commodity_type', 'currency']
    search_fields = ['symbol', 'name']

@admin.register(Cryptocurrency)
class CryptocurrencyAdmin(admin.ModelAdmin):
    list_display = ['symbol', 'name', 'market_cap_rank', 'circulating_supply']
    search_fields = ['symbol', 'name']

@admin.register(UserPortfolio)
class UserPortfolioAdmin(admin.ModelAdmin):
    list_display = ['user', 'name', 'created_at', 'updated_at']
    list_filter = ['created_at']
    search_fields = ['user__username', 'name']

class PortfolioHoldingInline(admin.TabularInline):
    model = PortfolioHolding
    extra = 1
    fields = ['asset', 'quantity', 'average_price', 'current_value', 'unrealized_pl_percent']
    readonly_fields = ['current_value', 'unrealized_pl', 'unrealized_pl_percent', 'last_updated']

@admin.register(PortfolioHolding)
class PortfolioHoldingAdmin(admin.ModelAdmin):
    list_display = ['portfolio', 'asset', 'quantity', 'invested_amount', 'current_value', 'unrealized_pl_percent']
    list_filter = ['portfolio__user', 'asset__asset_type']
    search_fields = ['asset__symbol', 'asset__name']
    readonly_fields = ['current_value', 'unrealized_pl', 'unrealized_pl_percent', 'last_updated']

@admin.register(Watchlist)
class WatchlistAdmin(admin.ModelAdmin):
    list_display = ['user', 'name', 'created_at']
    list_filter = ['user']
    search_fields = ['user__username', 'name']

@admin.register(WatchlistItem)
class WatchlistItemAdmin(admin.ModelAdmin):
    list_display = ['watchlist', 'asset', 'added_at']
    list_filter = ['watchlist__user']
    search_fields = ['asset__symbol']

@admin.register(NewsHeadline)
class NewsHeadlineAdmin(admin.ModelAdmin):
    list_display = ['title', 'asset', 'source', 'published_at', 'sentiment_label']
    list_filter = ['source', 'published_at', 'sentiment_label']
    search_fields = ['title', 'summary']
    readonly_fields = ['sentiment_score', 'sentiment_label']

@admin.register(TechnicalIndicator)
class TechnicalIndicatorAdmin(admin.ModelAdmin):
    list_display = ['asset', 'indicator_type', 'period', 'timestamp']
    list_filter = ['indicator_type', 'asset']
    search_fields = ['asset__symbol']
    
    formfield_overrides = {
        fields.JSONField: {'widget': JSONEditorWidget},
    }

@admin.register(MarketHoliday)
class MarketHolidayAdmin(admin.ModelAdmin):
    list_display = ['date', 'name']
    list_filter = ['date']
    search_fields = ['name']

@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ['user', 'asset', 'condition', 'target_price', 'is_active', 'triggered_at']
    list_filter = ['condition', 'is_active', 'asset__asset_type']
    search_fields = ['user__username', 'asset__symbol']
    list_editable = ['is_active']