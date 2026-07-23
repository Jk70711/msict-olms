"""
OLMS/settings.py

Mipangilio yote ya mfumo wa Django.
Badilisha thamani nyeti kwa kutumia faili ya .env (si moja kwa moja hapa).

Maeneo Muhimu:
  - DEBUG          : True kwa maendeleo, False kwa seva ya uzalishaji (VPS)
  - ALLOWED_HOSTS  : IP au domain zinazoruhusiwa kufikia mfumo
  - DATABASES      : Muunganisho wa Oracle database
  - INSTALLED_APPS : Apps zote za mfumo
  - EMAIL_*        : Mipangilio ya Gmail SMTP (kwa barua pepe)
  - BEEM_*         : API ya Beem Africa (kwa SMS)
"""
import os
from pathlib import Path
from decouple import config
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

# Funguo ya siri ya Django — lazima ibadilishwe kwenye VPS!
SECRET_KEY = config('SECRET_KEY')

# True = maendeleo (inaonyesha makosa kwa undani). Weka False kwenye VPS!
DEBUG = config('DEBUG', default=True, cast=bool)
#DEBUG = False

# Enforce a strong SECRET_KEY in production to protect signed cookies/tokens.
if not DEBUG and (SECRET_KEY.startswith('django-insecure-') or len(set(SECRET_KEY)) < 5 or len(SECRET_KEY) < 50):
    raise ImproperlyConfigured(
        "Set a strong SECRET_KEY in .env before running with DEBUG=False."
    )

# Seva zinazoruhusiwa. Ongeza IP ya VPS hapa kwenye faili ya .env
# Mfano wa .env: ALLOWED_HOSTS=81.17.97.229,localhost,127.0.0.1
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1').split(',')

# Build CSRF_TRUSTED_ORIGINS from ALLOWED_HOSTS automatically
# (also supports manual override via CSRF_TRUSTED_ORIGINS env var)
_csrf_extra = config('CSRF_TRUSTED_ORIGINS', default='').strip()
CSRF_TRUSTED_ORIGINS = [
    'http://localhost:8000',
    'http://127.0.0.1:8000',
    'http://127.0.0.1:36569',
    'http://localhost:36569',
] + [
    f'http://{h}' for h in ALLOWED_HOSTS if h not in ('localhost', '127.0.0.1', '')
] + [
    f'https://{h}' for h in ALLOWED_HOSTS if h not in ('localhost', '127.0.0.1', '')
] + (
    [o.strip() for o in _csrf_extra.split(',') if o.strip()] if _csrf_extra else []
)

# Kwa VPS inayotumia Nginx kama proxy: tumia Host header iliyopelekwa na Nginx
USE_X_FORWARDED_HOST = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# -----------------------------
# Security hardening (production)
# -----------------------------
# HTTPS / HSTS
SECURE_SSL_REDIRECT = config('SECURE_SSL_REDIRECT', default=not DEBUG, cast=bool)
SECURE_HSTS_SECONDS = config('SECURE_HSTS_SECONDS', default=31536000 if not DEBUG else 0, cast=int)
SECURE_HSTS_INCLUDE_SUBDOMAINS = config('SECURE_HSTS_INCLUDE_SUBDOMAINS', default=not DEBUG, cast=bool)
SECURE_HSTS_PRELOAD = config('SECURE_HSTS_PRELOAD', default=not DEBUG, cast=bool)

# MIME sniffing / Clickjacking / Referrer
SECURE_CONTENT_TYPE_NOSNIFF = config('SECURE_CONTENT_TYPE_NOSNIFF', default=True, cast=bool)
X_FRAME_OPTIONS = config('X_FRAME_OPTIONS', default='DENY')
SECURE_REFERRER_POLICY = config('SECURE_REFERRER_POLICY', default='same-origin')
SECURE_CROSS_ORIGIN_OPENER_POLICY = config('SECURE_CROSS_ORIGIN_OPENER_POLICY', default='same-origin')

# Session cookie — anti session-hijacking
SESSION_COOKIE_SECURE   = config('SESSION_COOKIE_SECURE',   default=not DEBUG, cast=bool)
SESSION_COOKIE_HTTPONLY = True            # JS cannot read session cookie (XSS mitigation)
SESSION_COOKIE_SAMESITE = config('SESSION_COOKIE_SAMESITE', default='Lax')   # CSRF mitigation
# Idle timeout: log users out after N seconds of inactivity. 1 hour by default;
# the login view extends this to 30 days when "Remember me" is ticked.
SESSION_COOKIE_AGE = config('SESSION_COOKIE_AGE', default=3600, cast=int)
SESSION_SAVE_EVERY_REQUEST = True         # rolls expiry on every request

# CSRF cookie — anti cross-site request forgery
CSRF_COOKIE_SECURE   = config('CSRF_COOKIE_SECURE',   default=not DEBUG, cast=bool)
CSRF_COOKIE_HTTPONLY = config('CSRF_COOKIE_HTTPONLY', default=True, cast=bool)
CSRF_COOKIE_SAMESITE = config('CSRF_COOKIE_SAMESITE', default='Lax')
CSRF_USE_SESSIONS    = False              # token in cookie is fine; SameSite + HTTPS protect it
CSRF_FAILURE_VIEW    = 'django.views.csrf.csrf_failure'

# Login brute-force throttle (see accounts.middleware.LoginRateLimitMiddleware).
LOGIN_RATELIMIT_MAX    = config('LOGIN_RATELIMIT_MAX',    default=10, cast=int)
LOGIN_RATELIMIT_WINDOW = config('LOGIN_RATELIMIT_WINDOW', default=60, cast=int)

# Content-Security-Policy (see accounts.middleware.SecurityHeadersMiddleware).
# Set OLMS_CSP_REPORT_ONLY=True in .env to roll out without enforcement first.
OLMS_CSP_REPORT_ONLY = config('OLMS_CSP_REPORT_ONLY', default=False, cast=bool)
OLMS_CSP_REPORT_URI  = config('OLMS_CSP_REPORT_URI',  default='')

# File upload safety: cap memory upload size to mitigate DoS via huge POSTs.
DATA_UPLOAD_MAX_MEMORY_SIZE = config('DATA_UPLOAD_MAX_MEMORY_SIZE', default=10 * 1024 * 1024, cast=int)  # 10 MB
FILE_UPLOAD_MAX_MEMORY_SIZE = config('FILE_UPLOAD_MAX_MEMORY_SIZE', default=10 * 1024 * 1024, cast=int)  # 10 MB
DATA_UPLOAD_MAX_NUMBER_FIELDS = 200
# Files written to disk should not be world-readable (protects /media uploads).
FILE_UPLOAD_PERMISSIONS = 0o640
FILE_UPLOAD_DIRECTORY_PERMISSIONS = 0o750

INSTALLED_APPS = [
    # 'daphne' MUST be first so its `runserver` overrides Django's default
    'daphne',
    'channels',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sites',
    'accounts.apps.AccountsConfig',
    'catalog.apps.CatalogConfig',
    'circulation.apps.CirculationConfig',
    'acquisitions.apps.AcquisitionsConfig',
    'reports.apps.ReportsConfig',
    'public.apps.PublicConfig',
    'chat.apps.ChatConfig',
    'chatbot.apps.ChatbotConfig',
]

SITE_ID = 1

# Middleware — zinaendesha kila ombi kabla na baada ya view
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    # IP-based brute-force throttle for /login/ POSTs.
    'accounts.middleware.LoginRateLimitMiddleware',
    # Single session enforcement (must be after MessageMiddleware since it uses messages).
    'accounts.middleware.SingleSessionMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # Defence-in-depth response headers (CSP, Permissions-Policy, COOP, …).
    # Must be LAST so it sees the final response and can set headers on it.
    'accounts.middleware.SecurityHeadersMiddleware',
]

ROOT_URLCONF = 'OLMS.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'catalog.context_processors.active_logo',
                'catalog.context_processors.system_appearance',
                'catalog.context_processors.category_menu',
                'catalog.context_processors.overdue_counter',
                'catalog.context_processors.security_badges',
            ],
        },
    },
]

WSGI_APPLICATION = 'OLMS.wsgi.application'
ASGI_APPLICATION = 'OLMS.asgi.application'

# ----------------------------------------------------------------------
# Channels: Redis backend for real-time chat WebSockets.
# Configurable via .env: REDIS_HOST, REDIS_PORT, REDIS_DB
# ----------------------------------------------------------------------
REDIS_HOST = config('REDIS_HOST', default='127.0.0.1')
REDIS_PORT = config('REDIS_PORT', default=6379, cast=int)
REDIS_DB   = config('REDIS_DB',   default=0,    cast=int)
CHANNEL_LAYER_BACKEND = config(
    'CHANNEL_LAYER_BACKEND',
    default='inmemory' if DEBUG else 'redis'
).strip().lower()

if CHANNEL_LAYER_BACKEND == 'redis':
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels_redis.core.RedisChannelLayer',
            'CONFIG': {
                'hosts': [(REDIS_HOST, REDIS_PORT)],
            },
        },
    }
else:
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels.layers.InMemoryChannelLayer',
        },
    }

# ----------------------------------------------------------------------
# AI Chatbot (Gemini) + Google Books external knowledge fallback.
# Empty values = chatbot will fall back to a rule-based response.
# ----------------------------------------------------------------------
GEMINI_API_KEY       = config('GEMINI_API_KEY',       default='')
# Use the rolling alias so we always point at Google's current free-tier
# flash model (gemini-1.5-flash and 2.0-flash are no longer free-tier).
GEMINI_MODEL         = config('GEMINI_MODEL',         default='gemini-flash-latest')
GOOGLE_BOOKS_API_KEY = config('GOOGLE_BOOKS_API_KEY', default='')

# Muunganisho wa Oracle database — host, jina la DB, mtumiaji, nywila
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.oracle',
        'NAME': config('DB_NAME', default='localhost:1521/FREEPDB1'),
        'USER': config('DB_USER', default='olms'),
        'PASSWORD': config('DB_PASSWORD'),
    }
}
AUTH_USER_MODEL = 'accounts.OLMSUser'

LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/'

# Domain settings for generating absolute URLs in emails/SMS
DEFAULT_DOMAIN = 'localhost:8000'
DEFAULT_PROTOCOL = 'https' if not DEBUG else 'http'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 8}},
    {'NAME': 'accounts.security_utils.PasswordMaxLengthValidator', 'OPTIONS': {'max_length': 12}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Password hashers — PBKDF2-SHA256 (Django default, OWASP-recommended) is
# primary. If `argon2-cffi` is installed in the environment, prepend the
# Argon2 hasher (memory-hard, GPU-resistant) for new password hashes;
# Django will transparently re-hash existing records on next login.
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher',
    'django.contrib.auth.hashers.BCryptSHA256PasswordHasher',
]
try:
    import argon2  # noqa: F401  -- dependency probe for argon2-cffi
    PASSWORD_HASHERS.insert(0, 'django.contrib.auth.hashers.Argon2PasswordHasher')
except ImportError:
    pass

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Africa/Dar_es_Salaam'
USE_I18N = True
USE_TZ = True

# Faili za kudumu (CSS, JS, picha) zinazohudumia frontend
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']  # Folda ya maendeleo
STATIC_ROOT = BASE_DIR / 'staticfiles'    # Inajazwa na 'collectstatic' kwa VPS

# Faili zinazopakiwa na watumiaji (picha za vitabu, PDF, picha za wasifu)
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = config('EMAIL_HOST', default='smtp.gmail.com')
EMAIL_PORT = config('EMAIL_PORT', default=587, cast=int)
EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=True, cast=bool)
EMAIL_HOST_USER = config('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
DEFAULT_FROM_EMAIL = EMAIL_HOST_USER

BEEM_API_KEY = config('BEEM_API_KEY')
BEEM_SECRET_KEY = config('BEEM_SECRET_KEY')
BEEM_SENDER_NAME = config('BEEM_SENDER_NAME', default='JK7')
BEEM_SMS_URL = 'https://apisms.beem.africa/v1/send'

LOAN_PERIOD_DAYS = 7
MAX_RENEWALS = 2
MAX_COPIES_PER_BORROW = 3
FINE_PER_DAY = 1000
LOGIN_FAILURE_LIMIT = 5
OTP_EXPIRY_MINUTES = 10
PASSWORD_CHANGE_REMINDER_DAYS = 30
PASSWORD_HISTORY_DEPTH = 5

# ── Security Logging (A09) ───────────────────────────────────────────
# All security events, errors, and warnings are written to rotating log
# files in BASE_DIR/logs/. Handlers: file (errors) + security (warnings+).
# StreamHandler is always active so runserver still prints to console.
_LOG_DIR = BASE_DIR / 'logs'
_LOG_DIR.mkdir(exist_ok=True)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{asctime} [{levelname}] {name} {process:d} {thread:d} — {message}',
            'style': '{',
        },
        'simple': {
            'format': '{asctime} [{levelname}] {name} — {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
        'file_error': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': str(_LOG_DIR / 'olms_errors.log'),
            'maxBytes': 5 * 1024 * 1024,  # 5 MB
            'backupCount': 5,
            'formatter': 'verbose',
            'level': 'ERROR',
        },
        'file_security': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': str(_LOG_DIR / 'olms_security.log'),
            'maxBytes': 5 * 1024 * 1024,
            'backupCount': 10,
            'formatter': 'verbose',
            'level': 'WARNING',
        },
        'file_django': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': str(_LOG_DIR / 'olms_django.log'),
            'maxBytes': 5 * 1024 * 1024,
            'backupCount': 5,
            'formatter': 'verbose',
            'level': 'WARNING',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'file_django'],
            'level': 'WARNING',
            'propagate': False,
        },
        'django.security': {
            'handlers': ['console', 'file_security'],
            'level': 'WARNING',
            'propagate': False,
        },
        'django.request': {
            'handlers': ['console', 'file_error'],
            'level': 'ERROR',
            'propagate': False,
        },
        # OLMS application loggers
        'accounts': {
            'handlers': ['console', 'file_security'],
            'level': 'WARNING',
            'propagate': False,
        },
        'circulation': {
            'handlers': ['console', 'file_django'],
            'level': 'WARNING',
            'propagate': False,
        },
        'catalog': {
            'handlers': ['console', 'file_django'],
            'level': 'WARNING',
            'propagate': False,
        },
        'chat': {
            'handlers': ['console', 'file_django'],
            'level': 'WARNING',
            'propagate': False,
        },
        'chatbot': {
            'handlers': ['console', 'file_django'],
            'level': 'WARNING',
            'propagate': False,
        },
    },
    'root': {
        'handlers': ['console', 'file_error'],
        'level': 'ERROR',
    },
}
