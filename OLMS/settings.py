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

BASE_DIR = Path(__file__).resolve().parent.parent

# Funguo ya siri ya Django — lazima ibadilishwe kwenye VPS!
SECRET_KEY = config('SECRET_KEY', default='django-insecure-!*8^5b)8!8k$z)3g&y66h-#%o)f&zwec$^l6ns$svphicp%srk')

# True = maendeleo (inaonyesha makosa kwa undani). Weka False kwenye VPS!
DEBUG = config('DEBUG', default=True, cast=bool)

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

INSTALLED_APPS = [
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

# Muunganisho wa Oracle database — host, jina la DB, mtumiaji, nywila
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.oracle',
        'NAME': 'localhost:1521/FREEPDB1',
        'USER': 'olms',
        'PASSWORD': '12345',
    }
}
AUTH_USER_MODEL = 'accounts.OLMSUser'

LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/'

# Domain settings for generating absolute URLs in emails/SMS
DEFAULT_DOMAIN = 'localhost:8000'
DEFAULT_PROTOCOL = 'http'

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
EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='jk7college@gmail.com')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
DEFAULT_FROM_EMAIL = EMAIL_HOST_USER

BEEM_API_KEY = config('BEEM_API_KEY', default='7a20aa440f62d83a')
BEEM_SECRET_KEY = config('BEEM_SECRET_KEY', default='OTRhMzkzYzQyNTdhZGZkNmIzYWQzYmZlMDJmZDBlMGExYjA3MTBlNWUzMjk4MWM4ODY5N2E2Mzg4MDI5ZDgxMQ==')
BEEM_SENDER_NAME = config('BEEM_SENDER_NAME', default='JK7')
BEEM_SMS_URL = 'https://apisms.beem.africa/v1/send'

LOAN_PERIOD_DAYS = 7
SOFTCOPY_LOAN_PERIOD_DAYS = 3
MAX_RENEWALS = 2
MAX_COPIES_PER_BORROW = 3
FINE_PER_DAY = 500
LOGIN_FAILURE_LIMIT = 5
OTP_EXPIRY_MINUTES = 10
PASSWORD_CHANGE_REMINDER_DAYS = 30
