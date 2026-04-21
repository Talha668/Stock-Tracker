"""
ASGI config for tracker project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""

import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from assets import routing


os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'tracker.settings')

application = get_asgi_application({
    'http': get_asgi_application(),
    'websockets': AuthMiddlewareStack(
        URLRouter(
            routing.websocket_urlpatterns
        )
    ),
})
