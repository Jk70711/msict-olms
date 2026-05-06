# ============================================================
# chatbot/urls.py — AI Library Assistant URLs
# Public endpoints (no login required for chatting).
# ============================================================

from django.urls import path
from . import views

urlpatterns = [
    path('',          views.assistant_page, name='assistant_page'),
    path('history/',  views.history,        name='assistant_history'),
    path('send/',     views.send,           name='assistant_send'),
    path('reset/',    views.reset,          name='assistant_reset'),
]
