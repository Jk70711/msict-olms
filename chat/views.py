# ============================================================
# chat/views.py
# HTTP views: inbox, conversation page, start-chat, message history,
# unread-count API, mark-as-read endpoint.
# ============================================================

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Max, Count, Case, When, IntegerField
from django.http import JsonResponse, Http404, HttpResponseForbidden
from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Conversation, Message, UserPresence

User = get_user_model()


# --- helpers ---------------------------------------------------------------

def _can_chat(u1, u2):
    """Spec: members can only chat with staff (librarian/admin), not other members."""
    if u1.id == u2.id:
        return False
    roles = {u1.role, u2.role}
    if roles == {'member'}:
        return False
    return True


def _allowed_partners_qs(user):
    """Return a queryset of users this user is allowed to start a chat with."""
    qs = User.objects.exclude(id=user.id).filter(is_active=True)
    if user.role == 'member':
        qs = qs.filter(role__in=('librarian', 'admin'))
    return qs.order_by('first_name', 'surname')


# --- pages -----------------------------------------------------------------

@login_required
def inbox(request):
    """Conversation list (left pane). Right pane is empty placeholder."""
    convs = (
        Conversation.objects
        .filter(Q(user_a=request.user) | Q(user_b=request.user))
        .select_related('user_a', 'user_b')
        .order_by('-last_message_at')
    )
    items = []
    for c in convs:
        other = c.other_participant(request.user)
        last_msg = c.messages.order_by('-created_at').first()
        unread = c.unread_count_for(request.user)
        items.append({
            'conv': c,
            'other': other,
            'last_msg': last_msg,
            'unread': unread,
        })
    return render(request, 'chat/inbox.html', {
        'items': items,
        'active_conv': None,
    })


@login_required
def conversation(request, conv_id):
    """Open a specific conversation in the right pane (full inbox layout)."""
    conv = get_object_or_404(Conversation, pk=conv_id)
    if not conv.includes(request.user):
        return HttpResponseForbidden("You are not part of this conversation.")

    # Mark all unread messages from the other party as read
    Message.objects.filter(
        conversation=conv, is_read=False,
    ).exclude(sender=request.user).update(is_read=True, read_at=timezone.now())

    other = conv.other_participant(request.user)
    messages = conv.messages.select_related('sender').order_by('created_at')

    # Sidebar list
    convs = (
        Conversation.objects
        .filter(Q(user_a=request.user) | Q(user_b=request.user))
        .select_related('user_a', 'user_b')
        .order_by('-last_message_at')
    )
    items = []
    for c in convs:
        op = c.other_participant(request.user)
        last_msg = c.messages.order_by('-created_at').first()
        unread = c.unread_count_for(request.user)
        items.append({
            'conv': c,
            'other': op,
            'last_msg': last_msg,
            'unread': unread,
        })

    return render(request, 'chat/inbox.html', {
        'items': items,
        'active_conv': conv,
        'active_other': other,
        'messages': messages,
    })


@login_required
def new_chat(request):
    """Pick a user to start a new conversation with."""
    q = (request.GET.get('q') or '').strip()
    partners = _allowed_partners_qs(request.user)
    if q:
        partners = partners.filter(
            Q(first_name__icontains=q) |
            Q(surname__icontains=q) |
            Q(username__icontains=q) |
            Q(email__icontains=q)
        )
    return render(request, 'chat/new_chat.html', {
        'partners': partners[:50],
        'q': q,
    })


@login_required
def start_chat(request, user_id):
    """Get-or-create a conversation with the given user, then redirect."""
    other = get_object_or_404(User, pk=user_id, is_active=True)
    if not _can_chat(request.user, other):
        return HttpResponseForbidden("You are not allowed to chat with this user.")
    conv = Conversation.get_or_create_for(request.user, other)
    return redirect('chat_conversation', conv_id=conv.pk)


# --- AJAX / JSON endpoints -------------------------------------------------

@login_required
def messages_json(request, conv_id):
    """Return all messages of a conversation as JSON. Used as fallback / initial load."""
    conv = get_object_or_404(Conversation, pk=conv_id)
    if not conv.includes(request.user):
        return HttpResponseForbidden()
    msgs = conv.messages.select_related('sender').order_by('created_at')
    data = [{
        'id': m.id,
        'sender_id': m.sender_id,
        'sender_name': m.sender.get_full_name() or m.sender.username,
        'body': m.body,
        'created_at': m.created_at.isoformat(),
        'is_read': m.is_read,
        'mine': m.sender_id == request.user.id,
    } for m in msgs]
    return JsonResponse({'messages': data})


@login_required
def unread_count(request):
    """Total unread count across all conversations (for topbar/sidebar badge)."""
    total = Message.objects.filter(
        conversation__in=Conversation.objects.filter(
            Q(user_a=request.user) | Q(user_b=request.user)
        ),
        is_read=False,
    ).exclude(sender=request.user).count()
    return JsonResponse({'unread': total})


@login_required
@require_POST
def mark_read(request, conv_id):
    """Mark all messages from the other party in this conversation as read."""
    conv = get_object_or_404(Conversation, pk=conv_id)
    if not conv.includes(request.user):
        return HttpResponseForbidden()
    Message.objects.filter(
        conversation=conv, is_read=False,
    ).exclude(sender=request.user).update(is_read=True, read_at=timezone.now())
    return JsonResponse({'ok': True})
