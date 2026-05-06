# ============================================================
# chat/models.py
# Real-time chat models — 1-on-1 conversations between users.
# Spec allowed pairs:  Member ↔ Librarian, Member ↔ Admin, Librarian ↔ Admin
# (Member ↔ Member is disallowed; enforced at view/consumer level.)
# ============================================================

from django.db import models
from django.conf import settings
from django.utils import timezone


class Conversation(models.Model):
    """A 1-on-1 conversation between two users.

    user_a is always the user with the LOWER id, user_b the higher id.
    This canonical ordering guarantees a unique conversation per pair.
    """
    user_a = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name='conversations_as_a',
        on_delete=models.CASCADE,
    )
    user_b = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name='conversations_as_b',
        on_delete=models.CASCADE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_message_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = 'chat_conversations'
        unique_together = ('user_a', 'user_b')
        ordering = ['-last_message_at']

    def __str__(self):
        return f"Chat #{self.pk}: {self.user_a_id} ↔ {self.user_b_id}"

    @classmethod
    def get_or_create_for(cls, user1, user2):
        """Return the canonical conversation between two users (or create)."""
        if user1.id == user2.id:
            raise ValueError("Cannot create a conversation with yourself.")
        a, b = (user1, user2) if user1.id < user2.id else (user2, user1)
        conv, _ = cls.objects.get_or_create(user_a=a, user_b=b)
        return conv

    def other_participant(self, user):
        """Return the OTHER participant (not the given user)."""
        return self.user_b if self.user_a_id == user.id else self.user_a

    def includes(self, user):
        return user.id in (self.user_a_id, self.user_b_id)

    def unread_count_for(self, user):
        return self.messages.filter(is_read=False).exclude(sender=user).count()


class Message(models.Model):
    """A single message inside a conversation."""
    conversation = models.ForeignKey(
        Conversation, related_name='messages', on_delete=models.CASCADE
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='chat_messages_sent',
    )
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'chat_messages'
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['conversation', '-created_at']),
        ]

    def __str__(self):
        return f"Msg #{self.pk} from {self.sender_id} in conv {self.conversation_id}"

    def mark_read(self):
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=['is_read', 'read_at'])


class UserPresence(models.Model):
    """Tracks online/offline state. Updated by the WebSocket consumer."""
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        related_name='presence',
        on_delete=models.CASCADE,
    )
    is_online = models.BooleanField(default=False)
    last_seen = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'chat_user_presence'

    def __str__(self):
        return f"{self.user_id}: {'online' if self.is_online else 'offline'}"
