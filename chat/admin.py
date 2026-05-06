from django.contrib import admin
from .models import Conversation, Message, UserPresence


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ('id', 'user_a', 'user_b', 'last_message_at', 'created_at')
    search_fields = ('user_a__username', 'user_b__username')
    readonly_fields = ('created_at',)


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'conversation', 'sender', 'short_body', 'is_read', 'created_at')
    list_filter = ('is_read',)
    search_fields = ('body', 'sender__username')
    readonly_fields = ('created_at', 'read_at')

    def short_body(self, obj):
        return (obj.body[:50] + '…') if len(obj.body) > 50 else obj.body
    short_body.short_description = 'Body'


@admin.register(UserPresence)
class UserPresenceAdmin(admin.ModelAdmin):
    list_display = ('user', 'is_online', 'last_seen')
    list_filter = ('is_online',)
    readonly_fields = ('last_seen',)
