# ============================================================
# chat/consumers.py
# WebSocket consumer for real-time chat messaging.
#
# One consumer per conversation. Connects to a channel-layer group
# named "chat_{conv_id}" so both participants receive each broadcast.
# Also broadcasts to user-specific groups "user_{id}" for global
# notification badges (unread count update on every page).
# ============================================================

import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone
from .models import Conversation, Message, UserPresence


class ChatConsumer(AsyncWebsocketConsumer):
    """Handles realtime messaging inside a single conversation."""

    async def connect(self):
        self.user = self.scope.get('user')
        if not self.user or not self.user.is_authenticated:
            await self.close(code=4001)
            return

        self.conv_id = int(self.scope['url_route']['kwargs']['conv_id'])
        if not await self._user_in_conv():
            await self.close(code=4003)
            return

        self.group_name = f'chat_{self.conv_id}'
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self._set_online(True)
        await self.accept()

        # Notify the other user of online status
        await self.channel_layer.group_send(self.group_name, {
            'type': 'presence.update',
            'user_id': self.user.id,
            'is_online': True,
        })

    async def disconnect(self, code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_send(self.group_name, {
                'type': 'presence.update',
                'user_id': self.user.id,
                'is_online': False,
            })
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
        if hasattr(self, 'user') and self.user and self.user.is_authenticated:
            await self._set_online(False)

    async def receive(self, text_data=None, bytes_data=None):
        try:
            data = json.loads(text_data or '{}')
        except (ValueError, TypeError):
            return
        action = data.get('action')

        if action == 'message':
            body = (data.get('body') or '').strip()
            if not body:
                return
            msg = await self._save_message(body)
            other_id = await self._get_other_user_id()

            payload = {
                'type': 'chat.message',
                'id': msg.id,
                'sender_id': self.user.id,
                'sender_name': self.user.get_full_name() or self.user.username,
                'body': msg.body,
                'created_at': msg.created_at.isoformat(),
            }
            await self.channel_layer.group_send(self.group_name, payload)

            # Notify the OTHER user globally (for badges on every page)
            await self.channel_layer.group_send(f'user_{other_id}', {
                'type': 'notify.new_message',
                'conv_id': self.conv_id,
                'sender_name': payload['sender_name'],
                'preview': msg.body[:80],
            })

        elif action == 'typing':
            await self.channel_layer.group_send(self.group_name, {
                'type': 'chat.typing',
                'user_id': self.user.id,
                'is_typing': bool(data.get('is_typing')),
            })

        elif action == 'mark_read':
            await self._mark_read()
            await self.channel_layer.group_send(self.group_name, {
                'type': 'chat.read',
                'reader_id': self.user.id,
            })

    # --- channel-layer handlers ------------------------------------------

    async def chat_message(self, event):
        await self.send(text_data=json.dumps({
            'type': 'message',
            'id': event['id'],
            'sender_id': event['sender_id'],
            'sender_name': event['sender_name'],
            'body': event['body'],
            'created_at': event['created_at'],
            'mine': event['sender_id'] == self.user.id,
        }))

    async def chat_typing(self, event):
        if event['user_id'] == self.user.id:
            return  # don't echo own typing back
        await self.send(text_data=json.dumps({
            'type': 'typing',
            'user_id': event['user_id'],
            'is_typing': event['is_typing'],
        }))

    async def chat_read(self, event):
        if event['reader_id'] == self.user.id:
            return
        await self.send(text_data=json.dumps({
            'type': 'read',
            'reader_id': event['reader_id'],
        }))

    async def presence_update(self, event):
        if event['user_id'] == self.user.id:
            return
        await self.send(text_data=json.dumps({
            'type': 'presence',
            'user_id': event['user_id'],
            'is_online': event['is_online'],
        }))

    # --- DB helpers ------------------------------------------------------

    @database_sync_to_async
    def _user_in_conv(self):
        try:
            conv = Conversation.objects.get(pk=self.conv_id)
        except Conversation.DoesNotExist:
            return False
        self._conv = conv
        return conv.includes(self.user)

    @database_sync_to_async
    def _save_message(self, body):
        msg = Message.objects.create(
            conversation_id=self.conv_id,
            sender=self.user,
            body=body,
        )
        Conversation.objects.filter(pk=self.conv_id).update(
            last_message_at=timezone.now()
        )
        return msg

    @database_sync_to_async
    def _get_other_user_id(self):
        conv = Conversation.objects.get(pk=self.conv_id)
        return conv.other_participant(self.user).id

    @database_sync_to_async
    def _mark_read(self):
        Message.objects.filter(
            conversation_id=self.conv_id, is_read=False,
        ).exclude(sender=self.user).update(is_read=True, read_at=timezone.now())

    @database_sync_to_async
    def _set_online(self, is_online):
        UserPresence.objects.update_or_create(
            user=self.user,
            defaults={'is_online': is_online, 'last_seen': timezone.now()},
        )


class NotificationConsumer(AsyncWebsocketConsumer):
    """User-wide consumer for cross-page unread-message badge updates."""

    async def connect(self):
        self.user = self.scope.get('user')
        if not self.user or not self.user.is_authenticated:
            await self.close(code=4001)
            return
        self.group_name = f'user_{self.user.id}'
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def notify_new_message(self, event):
        await self.send(text_data=json.dumps({
            'type': 'new_message',
            'conv_id': event['conv_id'],
            'sender_name': event['sender_name'],
            'preview': event['preview'],
        }))
