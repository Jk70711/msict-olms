# ============================================================
# accounts/middleware.py
#
# Security middleware stack for OLMS:
#   1. SingleSessionMiddleware  — anti session-hijacking: only one
#      active session per user at a time (enforces logout of older
#      sessions when the same account signs in from another device).
#   2. SecurityHeadersMiddleware — defence-in-depth HTTP headers:
#      Content-Security-Policy (XSS), Permissions-Policy,
#      Cross-Origin-Opener-Policy, Referrer-Policy, etc.
#   3. LoginRateLimitMiddleware — IP-based throttle for /login/ POSTs
#      to mitigate brute-force / credential-stuffing attacks at the
#      network edge (the per-account throttle in views.py still applies).
# ============================================================

import time
from collections import defaultdict, deque

from django.conf import settings
from django.contrib.auth import logout
from django.contrib import messages
from django.http import HttpResponseForbidden
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


# ----------------------------------------------------------------------
# 2. SecurityHeadersMiddleware
# ----------------------------------------------------------------------
class SecurityHeadersMiddleware:
    """
    Adds defence-in-depth HTTP response headers on every request:

    - Content-Security-Policy : restricts where scripts / styles / images
      / iframes can be loaded from. Mitigates the impact of any XSS that
      bypasses Django's auto-escape.
    - Permissions-Policy      : disables sensitive browser APIs the app
      does not need (camera, microphone, geolocation, USB, payment, etc.).
    - Cross-Origin-Opener-Policy : prevents cross-origin windows from
      sharing a browsing context (mitigates Spectre-like leaks and some
      tab-napping / window.opener attacks).
    - Cross-Origin-Resource-Policy : blocks other origins from embedding
      our resources by default.
    - Referrer-Policy         : already set via Django, kept here as a
      safety net in case a view overrides the default.
    - X-Content-Type-Options  : nosniff — kept here to also cover any
      response that bypasses the SecurityMiddleware (e.g. websockets).
    - X-Permitted-Cross-Domain-Policies : 'none' (Adobe legacy lockdown).

    The CSP is intentionally compatible with the templates that ship with
    OLMS today (Bootstrap 5 + Bootstrap-Icons + Swiper from jsDelivr,
    Google Fonts, YouTube embeds for news videos, inline <style> and
    <script> blocks). To tighten further, replace 'unsafe-inline' with
    nonces / hashes — but that is a project-wide refactor.

    All directives can be overridden in settings.py:
        OLMS_CSP_OVERRIDE = "default-src 'self'; …"   # full replacement
        OLMS_CSP_REPORT_ONLY = True                    # don't enforce, just report
        OLMS_CSP_REPORT_URI = '/csp-report/'
    """

    DEFAULT_CSP = (
        "default-src 'self'; "
        # Scripts: self + jsDelivr (Bootstrap, Swiper). 'unsafe-inline' is
        # required because the templates contain many inline <script> blocks.
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        # Styles: self + jsDelivr + Google Fonts. 'unsafe-inline' is required
        # because the templates use inline style="…" attributes extensively.
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
        # Fonts come from Google Fonts CDN and Bootstrap-Icons (jsDelivr).
        "font-src 'self' data: https://fonts.gstatic.com https://cdn.jsdelivr.net; "
        # Images: allow https sources (book covers from external lookups,
        # Google Books thumbnails, member-uploaded photos served via /media/).
        "img-src 'self' data: blob: https:; "
        # WebSocket connections for real-time chat (ws:// in dev, wss:// in prod)
        # plus same-origin XHR / fetch.
        "connect-src 'self' ws: wss: https:; "
        # YouTube embeds for news videos.
        "frame-src 'self' https://www.youtube.com https://www.youtube-nocookie.com; "
        # No legacy Flash / Java applets.
        "object-src 'none'; "
        # Lock <base href> to same-origin to prevent base-tag injection attacks.
        "base-uri 'self'; "
        # All <form action="…"> targets must be same-origin (anti-CSRF defence).
        "form-action 'self'; "
        # Clickjacking — also enforced by X-Frame-Options: DENY.
        "frame-ancestors 'none'; "
        # Tell the browser to upgrade any accidental http:// references to https://
        "upgrade-insecure-requests"
    )

    DEFAULT_PERMISSIONS_POLICY = (
        "accelerometer=(), "
        "camera=(), "
        "geolocation=(), "
        "gyroscope=(), "
        "magnetometer=(), "
        "microphone=(), "
        "payment=(), "
        "usb=(), "
        "interest-cohort=()"
    )

    def __init__(self, get_response):
        self.get_response = get_response
        self.csp = getattr(settings, 'OLMS_CSP_OVERRIDE', None) or self.DEFAULT_CSP
        report_uri = getattr(settings, 'OLMS_CSP_REPORT_URI', '')
        if report_uri:
            self.csp = self.csp.rstrip('; ') + f"; report-uri {report_uri}"
        self.report_only = bool(getattr(settings, 'OLMS_CSP_REPORT_ONLY', False))
        self.permissions_policy = getattr(
            settings, 'OLMS_PERMISSIONS_POLICY', self.DEFAULT_PERMISSIONS_POLICY
        )

    def __call__(self, request):
        response = self.get_response(request)

        # Skip CSP for the Django admin: it relies on inline JS the strict
        # CSP would otherwise allow anyway, but we keep it permissive so
        # debug pages render correctly.
        header_name = (
            'Content-Security-Policy-Report-Only' if self.report_only
            else 'Content-Security-Policy'
        )
        response.setdefault(header_name, self.csp)

        response.setdefault('Permissions-Policy', self.permissions_policy)
        response.setdefault('Cross-Origin-Opener-Policy', 'same-origin')
        response.setdefault('Cross-Origin-Resource-Policy', 'same-origin')
        response.setdefault('X-Content-Type-Options', 'nosniff')
        response.setdefault('X-Permitted-Cross-Domain-Policies', 'none')
        # Belt-and-braces clickjacking header in case a view drops X-Frame-Options.
        response.setdefault('X-Frame-Options', 'DENY')
        return response


# ----------------------------------------------------------------------
# 3. LoginRateLimitMiddleware
# ----------------------------------------------------------------------
class LoginRateLimitMiddleware:
    """
    In-memory sliding-window rate limit for POST requests to the login
    endpoint, keyed by client IP. This complements the per-account
    failed-attempts throttle implemented in accounts.views.login_view by
    blocking distributed brute-force / credential-stuffing attacks that
    cycle through usernames.

    Defaults: max 10 POSTs per 60 seconds per IP. Tunable via settings:
        LOGIN_RATELIMIT_MAX     = 10
        LOGIN_RATELIMIT_WINDOW  = 60   # seconds
        LOGIN_RATELIMIT_PATHS   = ('/accounts/login/',)

    NB: For a multi-process deployment (Gunicorn workers) this should be
    backed by Redis to share state. The in-memory implementation still
    raises the cost of brute force significantly per worker.
    """

    _hits = defaultdict(deque)  # ip -> deque[timestamp]

    def __init__(self, get_response):
        self.get_response = get_response
        self.max_hits = int(getattr(settings, 'LOGIN_RATELIMIT_MAX', 10))
        self.window = int(getattr(settings, 'LOGIN_RATELIMIT_WINDOW', 60))
        self.paths = tuple(getattr(
            settings, 'LOGIN_RATELIMIT_PATHS',
            ('/accounts/login/', '/login/')
        ))

    @staticmethod
    def _client_ip(request):
        xff = request.META.get('HTTP_X_FORWARDED_FOR', '')
        if xff:
            return xff.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR', '0.0.0.0')

    def __call__(self, request):
        if request.method == 'POST' and any(
            request.path.startswith(p) for p in self.paths
        ):
            ip = self._client_ip(request)
            now = time.time()
            bucket = self._hits[ip]
            # Drop timestamps outside the sliding window
            cutoff = now - self.window
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= self.max_hits:
                retry_after = int(self.window - (now - bucket[0])) + 1
                resp = HttpResponseForbidden(
                    "Too many login attempts from your IP. "
                    f"Please wait {retry_after} second(s) and try again."
                )
                resp['Retry-After'] = str(retry_after)
                return resp
            bucket.append(now)

        return self.get_response(request)
