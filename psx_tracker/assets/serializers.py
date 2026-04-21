from rest_framework import serializers
from .models import Asset, PriceHistory, Alert, OHLCV, Commodity





class AssetSerializer(serializers.ModelSerializer):
    current_price = serializers.SerializerMethodField()
    price_change = serializers.SerializerMethodField()
    
    class Meta:
        model = Asset
        fields = ['id', 'symbol', 'name', 'asset_type', 'exchange', 
                 'currency', 'current_price', 'price_change', 'metadata']
    
    def get_current_price(self, obj):
        latest_price = obj.prices.first()
        return float(latest_price.price) if latest_price else None
    
    def get_price_change(self, obj):
        latest_price = obj.prices.first()
        return float(latest_price.change_percent) if latest_price and latest_price.change_percent is not None else None


class PriceHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = PriceHistory
        fields = '__all__'


class AlertSerializer(serializers.ModelSerializer):
    class Meta:
        model = Alert
        fields = '__all__'


class OHLCVSerializer(serializers.ModelSerializer):
    class Meta:
        model = OHLCV
        fields = '__all__'


class CommoditySerializer(serializers.ModelSerializer):
    current_price = serializers.SerializerMethodField()
    price_change = serializers.SerializerMethodField()

    class Meta:
        model = Commodity
        fields = ['id', 'symbol', 'name', 'commodity_type', 'unit',
                 'currency','cuurent_price', 'price_change', 'metadata']

        def get_current_price(self, obj):
            latest = obj.prices.first()
            return float(latest.price) if latest else None 

        def get_price_change(self, obj):
            latest = obj.prices.first()
            return float(latest.price_change) if latest else None


class OilPriceSerializer(serializers.Serializer):
    """Serializer for oil price responses"""
    symbol = serializers.CharField()
    name = serializers.CharField()
    price = serializers.FloatField()
    change = serializers.FloatField()
    change_percent = serializers.FloatField()
    high_24h = serializers.FloatField()
    low_24h = serializers.FloatField()
    volume = serializers.IntegerField()
    timestamp = serializers.DateTimeField()