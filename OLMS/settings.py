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
SECURE_SSL_REDIRECT = config('SECURE_SSL_REDIRECT', default=not DEBUG, cast=bool)
SESSION_COOKIE_SECURE = config('SESSION_COOKIE_SECURE', default=not DEBUG, cast=bool)
CSRF_COOKIE_SECURE = config('CSRF_COOKIE_SECURE', default=not DEBUG, cast=bool)
SECURE_HSTS_SECONDS = config('SECURE_HSTS_SECONDS', default=31536000 if not DEBUG else 0, cast=int)
SECURE_HSTS_INCLUDE_SUBDOMAINS = config('SECURE_HSTS_INCLUDE_SUBDOMAINS', default=not DEBUG, cast=bool)
SECURE_HSTS_PRELOAD = config('SECURE_HSTS_PRELOAD', default=not DEBUG, cast=bool)
SECURE_CONTENT_TYPE_NOSNIFF = config('SECURE_CONTENT_TYPE_NOSNIFF', default=True, cast=bool)
X_FRAME_OPTIONS = config('X_FRAME_OPTIONS', default='DENY')
SECURE_REFERRER_POLICY = config('SECURE_REFERRER_POLICY', default='same-origin')

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
    'accounts.middleware.SingleSessionMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
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

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            'hosts': [(REDIS_HOST, REDIS_PORT)],
        },
    },
}

# ----------------------------------------------------------------------
# AI Chatbot (Gemini) + Google Books external knowledge fallback.
# Empty values = chatbot will fall back to a rule-based response.
# ----------------------------------------------------------------------
GEMINI_API_KEY       = config('GEMINI_API_KEY',       default='')
GEMINI_MODEL         = config('GEMINI_MODEL',         default='gemini-1.5-flash')
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
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
]

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
