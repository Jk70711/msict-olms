from django.contrib import admin
from .models import ChatbotSession, ChatbotMessage


class ChatbotMessageInline(admin.TabularInline):
    model = ChatbotMessage
    extra = 0
    readonly_fields = ('role', 'content', 'metadata', 'created_at')
    can_delete = False


@admin.register(ChatbotSession)
class ChatbotSessionAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'session_key', 'title', 'updated_at')
    search_fields = ('user__username', 'session_key', 'title')
    readonly_fields = ('created_at', 'updated_at')
    inlines = [ChatbotMessageInline]


@admin.register(ChatbotMessage)
class ChatbotMessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'session', 'role', 'short', 'created_at')
    list_filter = ('role',)
    search_fields = ('content',)
    readonly_fields = ('created_at',)

    def short(self, obj):
        return (obj.content[:60] + '…') if len(obj.content) > 60 else obj.content
    short.short_description = 'Content'
