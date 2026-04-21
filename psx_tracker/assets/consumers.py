import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone
from .models import Asset, PriceHistory
from decimal import Decimal





class PriceConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.asset_symbol = self.scope['url_route']['kwargs'].get('symbol', 'all')
        
        if self.asset_symbol == 'all':
            self.room_group_name = 'prices_all'
        else:
            self.room_group_name = f'price_{self.asset_symbol}'
        
        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        
        await self.accept()
        
        # Send latest price immediately
        await self.send_latest_price()
    
    async def disconnect(self, close_code):
        # Leave room group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )
    
    async def receive(self, text_data):
        """Handle messages from WebSocket"""
        try:
            data = json.loads(text_data)
            command = data.get('command')
            
            if command == 'subscribe':
                symbol = data.get('symbol')
                if symbol:
                    # Leave current group
                    await self.channel_layer.group_discard(
                        self.room_group_name,
                        self.channel_name
                    )
                    # Join new group
                    self.asset_symbol = symbol
                    self.room_group_name = f'price_{symbol}'
                    await self.channel_layer.group_add(
                        self.room_group_name,
                        self.channel_name
                    )
                    await self.send(text_data=json.dumps({
                        'type': 'subscription',
                        'symbol': symbol,
                        'status': 'subscribed'
                    }))
                    # Send latest price
                    await self.send_latest_price()
                    
        except json.JSONDecodeError:
            await self.send(text_data=json.dumps({
                'error': 'Invalid JSON'
            }))
    
    async def price_update(self, event):
        """Send price update to WebSocket"""
        await self.send(text_data=json.dumps({
            'type': 'price_update',
            'symbol': event['symbol'],
            'price': event['price'],
            'change': event['change'],
            'change_percent': event['change_percent'],
            'timestamp': event['timestamp']
        }))
    
    @database_sync_to_async
    def get_latest_price(self):
        """Get latest price from database"""
        try:
            if self.asset_symbol != 'all':
                asset = Asset.objects.filter(symbol=self.asset_symbol).first()
                if asset:
                    latest = asset.prices.first()
                    if latest:
                        previous = asset.prices.all()[1:2].first()
                        change = 0
                        change_percent = 0
                        
                        if previous:
                            change = float(latest.price) - float(previous.price)
                            change_percent = (change / float(previous.price)) * 100
                        
                        return {
                            'symbol': asset.symbol,
                            'price': str(latest.price),
                            'change': str(change),
                            'change_percent': str(change_percent),
                            'timestamp': latest.timestamp.isoformat()
                        }
        except Exception as e:
            print(f"Error getting latest price: {e}")
        return None
    
    async def send_latest_price(self):
        """Send latest price to client"""
        price_data = await self.get_latest_price()
        if price_data:
            await self.send(text_data=json.dumps({
                'type': 'initial_price',
                'data': price_data
            }))

class AlertConsumer(AsyncWebsocketConsumer):
    """WebSocket for user alerts"""
    async def connect(self):
        self.user = self.scope['user']
        
        if not self.user.is_authenticated:
            await self.close()
        else:
            self.room_group_name = f'alerts_{self.user.id}'
            
            await self.channel_layer.group_add(
                self.room_group_name,
                self.channel_name
            )
            
            await self.accept()
    
    async def disconnect(self, close_code):
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )
    
    async def alert_triggered(self, event):
        """Send alert to user"""
        await self.send(text_data=json.dumps({
            'type': 'alert',
            'alert_id': event['alert_id'],
            'symbol': event['symbol'],
            'price': event['price'],
            'target': event['target'],
            'condition': event['condition'],
            'timestamp': event['timestamp']
        }))