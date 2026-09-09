# OLMS Project Architecture & Conventions

## Chat Module Architecture

The real-time chat module is implemented in the `chat/` Django app using:
- Django Channels 4.1
- channels-redis
- Daphne ASGI
- Redis running locally on 127.0.0.1:6379

### Key Files

**Models** (`chat/models.py`):
- `Conversation` — Canonical pair via lower-id user_a + higher-id user_b, unique together
- `Message` — Chat messages
- `UserPresence` — User online status

**Views** (`chat/views.py`):
- `inbox` — List of conversations
- `conversation` — Single conversation view
- `new_chat` — Form to start new conversation
- `start_chat` — Create new conversation
- `messages_json` — JSON endpoint for messages
- `unread_count` — Get unread message count
- `mark_read` — Mark messages as read

**Consumers** (`chat/consumers.py`):
- `ChatConsumer` — Per-conversation WebSocket consumer
- `NotificationConsumer` — Per-user global badge notifications

**Routing** (`chat/routing.py`):
- `ws/chat/<conv_id>/` — Conversation WebSocket
- `ws/notifications/` — Global notification WebSocket

**Configuration**:
- `OLMS/asgi.py` — ProtocolTypeRouter with AllowedHostsOriginValidator + AuthMiddlewareStack
- `OLMS/settings.py` — daphne first in INSTALLED_APPS, ASGI_APPLICATION='OLMS.asgi.application', CHANNEL_LAYERS using Redis

**Templates**:
- `templates/chat/inbox.html` — Conversation inbox
- `templates/chat/new_chat.html` — New chat form
- `templates/partials/sidebar_nav.html` — Sidebar links with unread badge (admin/librarian/member)
- `templates/base.html` — Topbar chat icon + global notification toast

### RBAC Rules
Members can only chat with librarians/admins (not other members). This is enforced in:
- `_can_chat()` function
- `_allowed_partners_qs()` function

### Future Plans
Phase 2: Gemini-powered AI chatbot with Google Books fallback for the OLMS library assistant.
