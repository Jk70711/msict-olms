def guest_session_context(request):
    """Inject guest session expiry data into template context for countdown JS."""
    expiry_iso = getattr(request, 'guest_session_expiry', None)
    session_id = getattr(request, 'guest_session_id', None)
    if expiry_iso and session_id:
        return {
            'guest_session_expiry_iso': expiry_iso,
            'guest_session_id': session_id,
        }
    return {}
