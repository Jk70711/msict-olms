# ============================================================
# accounts/middleware.py
# Enforces one active session per user at a time.
# If the same account signs in from a second device/browser,
# the first device's session is deleted on the next request.
# ============================================================

from django.contrib.auth import logout
from django.contrib import messages
from django.shortcuts import redirect

# Paths that must be exempt to avoid infinite redirect loops
_EXEMPT_PATHS = {'/accounts/login/', '/accounts/logout/', '/'}


class SingleSessionMiddleware:
    """
    On every authenticated request, verify that the current session key
    is still registered in UserSession for this user.  If it has been
    replaced (a newer login invalidated it), log the user out immediately
    and send them back to the login page with an explanatory warning.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            request.user.is_authenticated
            and request.path not in _EXEMPT_PATHS
            and not request.path.startswith('/admin/')
        ):
            from .models import UserSession
            session_key = request.session.session_key
            if session_key and not UserSession.objects.filter(
                session_id=session_key, user=request.user
            ).exists():
                logout(request)
                messages.warning(
                    request,
                    'Your session was ended because this account signed in from another '
                    'device or browser. Only one active session is allowed per account.'
                )
                return redirect('login')

        return self.get_response(request)
