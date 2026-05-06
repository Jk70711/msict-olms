# ============================================================
# chat/urls.py — HTTP URL patterns for the chat module.
# WebSocket routes live in chat/routing.py
# ============================================================

from django.urls import path
from . import views

urlpatterns = [
    path('',                        views.inbox,         name='chat_inbox'),
    path('new/',                    views.new_chat,      name='chat_new'),
    path('start/<int:user_id>/',    views.start_chat,    name='chat_start'),
    path('c/<int:conv_id>/',        views.conversation,  name='chat_conversation'),
    path('c/<int:conv_id>/messages/', views.messages_json, name='chat_messages_json'),
    path('c/<int:conv_id>/read/',   views.mark_read,     name='chat_mark_read'),
    path('unread/',                 views.unread_count,  name='chat_unread_count'),
]
