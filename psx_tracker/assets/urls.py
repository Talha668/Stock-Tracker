from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views




router = DefaultRouter()
router.register(r'assets', views.AssetViewSet)
router.register(r'prices', views.PriceHistoryViewSet)
router.register(r'alerts', views.AlertViewSet)
router.register(r'portfolios', views.UserPortfolioViewSet)
router.register(r'watchlists', views.WatchlistViewSet)
router.register(r'stocks', views.StockViewSet)
router.register(r'indicators', views.TechnicalIndicatorViewSet)
router.register(r'commodities', views.CommodityViewSet)


urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    
    # SPECIFIC API ROUTES FIRST (before the router catch-all)
    path('api/assets/<str:asset_symbol>/historical/', views.asset_historical, name='asset-historical'),
    path('api/assets/<str:asset_symbol>/', views.get_asset_details, name='asset-detail'),
    path('api/assets/', views.asset_list, name='asset-list'),
    
    # OTHER API ROUTES
    path('api/fetch-all-prices/', views.api_fetch_all_prices, name='fetch_all_prices'),
    path('api/psql-stats/', views.psql_stats, name='psql_stats'),
    path('api/market-summary/', views.market_summary, name='market_summary'),
    path('api/sector-performance/', views.sector_performance, name='sector_performance'),
    path('api/commodities/', views.CommodityViewSet.as_view({'get': 'list'}), name='commodities'),
    path('api/commodities/energy/', views.CommodityViewSet.as_view({'get': 'energy'}), name='energy'),
    path('api/oil/prices/', views.oil_prices, name='oil-prices'),
    path('api/oil/<str:symbol>/', views.oil_detail, name='oil-detail'),
    path('api/oil/comparison/', views.oil_comparison, name='oil-comparison'),
    path('api/fetch-oil-prices/', views.fetch_all_prices, name='fetch-prices'),
    path('api/market-overview/', views.get_market_overview, name='market-overview'),
    
    # ROUTER (catch-all for remaining API patterns)
    path('api/', include(router.urls)),
    
    # Portfolio and watchlist views
    path('portfolio/<int:portfolio_id>/', views.portfolio_detail, name='portfolio_detail'),
    path('watchlist/', views.watchlist_view, name='watchlist'),
]