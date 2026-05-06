# ============================================================
# chatbot/models.py
# Persistent conversation history for the AI library assistant.
# Anonymous (logged-out) users get a session-key based session;
# authenticated users get a user-attached session.
# ============================================================

from django.conf import settings
from django.db import models


class ChatbotSession(models.Model):
    """A single chatbot conversation thread."""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        related_name='chatbot_sessions',
        on_delete=models.CASCADE,
    )
    session_key = models.CharField(max_length=64, db_index=True, blank=True)
    title = models.CharField(max_length=200, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'chatbot_sessions'
        ordering = ['-updated_at']

    def __str__(self):
        who = self.user.username if self.user_id else f'anon:{self.session_key[:8]}'
        return f"ChatbotSession #{self.pk} ({who})"


class ChatbotMessage(models.Model):
    """One message in a chatbot conversation."""
    ROLE_CHOICES = [
        ('user',      'User'),
        ('assistant', 'Assistant'),
        ('system',    'System'),
    ]

    session = models.ForeignKey(
        ChatbotSession, related_name='messages',
        on_delete=models.CASCADE,
    )
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    content = models.TextField()
    # Free-form metadata: book ids referenced, tool calls made, language detected, etc.
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'chatbot_messages'
        ordering = ['created_at']

    def __str__(self):
        return f"[{self.role}] {self.content[:40]}"
