from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.core.cache import cache
from django.utils import timezone
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import json
from .models import Asset, PriceHistory, Alert, PortfolioHolding





@receiver(post_save, sender=PriceHistory)
def broadcast_price_update(sender, instance, created, **kwargs):
    """Broadcast price updates via WebSocket"""
    if created:
        channel_layer = get_channel_layer()
        
        # Get previous price for change calculation
        previous = PriceHistory.objects.filter(
            asset=instance.asset
        ).exclude(id=instance.id).order_by('-timestamp').first()
        
        change = 0
        change_percent = 0
        
        if previous:
            change = float(instance.price) - float(previous.price)
            change_percent = (change / float(previous.price)) * 100
        
        # Broadcast to asset-specific group
        async_to_sync(channel_layer.group_send)(
            f'price_{instance.asset.symbol}',
            {
                'type': 'price_update',
                'symbol': instance.asset.symbol,
                'price': str(instance.price),
                'change': str(change),
                'change_percent': str(change_percent),
                'timestamp': instance.timestamp.isoformat()
            }
        )
        
        # Broadcast to all group
        async_to_sync(channel_layer.group_send)(
            'prices_all',
            {
                'type': 'price_update',
                'symbol': instance.asset.symbol,
                'price': str(instance.price),
                'change': str(change),
                'change_percent': str(change_percent),
                'timestamp': instance.timestamp.isoformat()
            }
        )
        
        # Update cache
        cache.set(f'latest_price_{instance.asset.symbol}', {
            'price': str(instance.price),
            'timestamp': instance.timestamp.isoformat()
        }, timeout=300)  # 5 minutes cache

@receiver(post_save, sender=PriceHistory)
def update_portfolio_values(sender, instance, created, **kwargs):
    """Update portfolio holdings values when price changes"""
    if created:
        # Update all holdings of this asset
        holdings = PortfolioHolding.objects.filter(asset=instance.asset)
        for holding in holdings:
            holding.current_value = holding.quantity * instance.price
            holding.unrealized_pl = holding.current_value - holding.invested_amount
            if holding.invested_amount > 0:
                holding.unrealized_pl_percent = (holding.unrealized_pl / holding.invested_amount) * 100
            holding.save()

@receiver(post_save, sender=Alert)
def check_alert_on_creation(sender, instance, created, **kwargs):
    """Check if alert should be triggered immediately on creation"""
    if created and instance.is_active:
        latest_price = instance.asset.prices.first()
        if latest_price:
            should_trigger = False
            
            if instance.condition == 'ABOVE' and latest_price.price > instance.target_price:
                should_trigger = True
            elif instance.condition == 'BELOW' and latest_price.price < instance.target_price:
                should_trigger = True
            
            if should_trigger:
                instance.is_active = False
                instance.triggered_at = timezone.now()
                instance.save()
                
                # Send WebSocket notification
                channel_layer = get_channel_layer()
                async_to_sync(channel_layer.group_send)(
                    f'alerts_{instance.user.id}',
                    {
                        'type': 'alert_triggered',
                        'alert_id': instance.id,
                        'symbol': instance.asset.symbol,
                        'price': str(latest_price.price),
                        'target': str(instance.target_price),
                        'condition': instance.condition,
                        'timestamp': timezone.now().isoformat()
                    }
                )

@receiver(post_delete, sender=PriceHistory)
def cleanup_cache(sender, instance, **kwargs):
    """Cleanup cache when price is deleted"""
    cache_key = f'latest_price_{instance.asset.symbol}'
    cache.delete(cache_key)