# ============================================================
# chatbot/views.py
# JSON endpoints used by the floating chat widget + a dedicated
# full-page assistant view.
# ============================================================

import json

from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import ensure_csrf_cookie

from .models import ChatbotSession, ChatbotMessage
from .services import gemini


# ----------------------------------------------------------------------
# Session helpers
# ----------------------------------------------------------------------
def _ensure_session_key(request):
    if not request.session.session_key:
        request.session.save()
    return request.session.session_key


def _get_or_create_session(request):
    """Find (or create) the active chatbot session for this user/visitor."""
    skey = _ensure_session_key(request)

    if request.user.is_authenticated:
        sess = (ChatbotSession.objects
                .filter(user=request.user)
                .order_by('-updated_at').first())
        if sess is None:
            sess = ChatbotSession.objects.create(
                user=request.user, session_key=skey,
            )
    else:
        sess = (ChatbotSession.objects
                .filter(user__isnull=True, session_key=skey)
                .order_by('-updated_at').first())
        if sess is None:
            sess = ChatbotSession.objects.create(session_key=skey)

    return sess


def _history_for_gemini(session, max_turns=10):
    """Return last N message pairs as Gemini-format history."""
    msgs = list(session.messages.exclude(role='system')
                .order_by('-created_at')[: max_turns * 2])
    msgs.reverse()
    out = []
    for m in msgs:
        out.append({
            'role': 'model' if m.role == 'assistant' else 'user',
            'text': m.content,
        })
    return out


# ----------------------------------------------------------------------
# Pages
# ----------------------------------------------------------------------
@ensure_csrf_cookie
def assistant_page(request):
    """Dedicated full-page assistant (also embeddable). Public — no login."""
    sess = _get_or_create_session(request)
    return render(request, 'chatbot/assistant.html', {
        'history': sess.messages.exclude(role='system').order_by('created_at'),
        'session': sess,
    })


# ----------------------------------------------------------------------
# JSON API
# ----------------------------------------------------------------------
@require_GET
def history(request):
    """Return the recent conversation as JSON (used to populate the widget)."""
    sess = _get_or_create_session(request)
    msgs = sess.messages.exclude(role='system').order_by('created_at')[:50]
    return JsonResponse({
        'session_id': sess.id,
        'messages': [{
            'role':       m.role,
            'content':    m.content,
            'metadata':   m.metadata or {},
            'created_at': m.created_at.isoformat(),
        } for m in msgs],
    })


@require_POST
def send(request):
    """
    Accept the user's message, run Gemini (with tool-calling),
    persist both messages, return the assistant reply as JSON.
    """
    try:
        data = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return HttpResponseBadRequest('Invalid JSON.')

    text = (data.get('message') or '').strip()
    if not text:
        return HttpResponseBadRequest('Empty message.')
    if len(text) > 2000:
        return JsonResponse({'error': 'Message too long (max 2000 chars).'}, status=400)

    sess = _get_or_create_session(request)

    # Persist the user message
    ChatbotMessage.objects.create(session=sess, role='user', content=text)

    # Auto-title the session from the first message
    if not sess.title:
        sess.title = text[:80]
        sess.save(update_fields=['title'])

    # Call Gemini with prior history (excluding the message we just stored — Gemini receives it via `user_message`)
    history_payload = _history_for_gemini(sess)
    # Drop the last entry because it's the message we just stored — already passed separately.
    if history_payload and history_payload[-1]['text'] == text:
        history_payload = history_payload[:-1]

    result = gemini.chat(history_payload, text)

    reply = result.get('reply', '')
    metadata = {
        'tool_calls':           result.get('tool_calls', []),
        'referenced_book_ids':  result.get('referenced_book_ids', []),
    }

    ChatbotMessage.objects.create(
        session=sess, role='assistant',
        content=reply, metadata=metadata,
    )
    sess.save()  # bump updated_at

    return JsonResponse({
        'reply':    reply,
        'metadata': metadata,
    })


@require_POST
def reset(request):
    """Start a fresh conversation thread."""
    sess = _get_or_create_session(request)
    sess.messages.all().delete()
    sess.title = ''
    sess.save()
    return JsonResponse({'ok': True})
