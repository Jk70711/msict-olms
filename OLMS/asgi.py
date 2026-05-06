"""
ASGI config for OLMS project.

Routes HTTP traffic to the standard Django ASGI app, and WebSocket
traffic to Channels consumers (real-time chat).
"""

import os
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'OLMS.settings')

# IMPORTANT: get_asgi_application() must be called BEFORE importing
# anything that touches Django models / consumers, otherwise the app
# registry is not yet ready.
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from channels.security.websocket import AllowedHostsOriginValidator

import chat.routing

application = ProtocolTypeRouter({
    'http': django_asgi_app,
    'websocket': AllowedHostsOriginValidator(
        AuthMiddlewareStack(
            URLRouter(chat.routing.websocket_urlpatterns)
        )
    ),
})
