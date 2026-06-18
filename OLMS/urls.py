"""
URL configuration for OLMS project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
# ============================================================
# OLMS/urls.py — URL Kuu ya Mfumo
#
# Faili hii inaelekeza maombi yote kwa apps zinazohusika.
# Kila app ina faili yake ya urls.py inayoshughulikia URLs zake.
#
# Muundo:
#   /              → public/urls.py   (ukurasa wa nyumbani, tafuta)
#   /login/ n.k.   → accounts/urls.py  (watumiaji, login, OTP)
#   /catalog/      → catalog/urls.py   (vitabu, nakala, rafu)
#   /circulation/  → circulation/urls.py (mikopo, maombi, faini)
#   /acquisitions/ → acquisitions/urls.py (manunuzi)
#   /reports/      → reports/urls.py   (ripoti na takwimu)
# ============================================================

from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth.decorators import login_required
from django.views.static import serve as _serve
from django.http import Http404
from decouple import config as _env

# Admin URL ya siri — soma kutoka .env ili kuzuia uvumbuzi rahisi
_ADMIN_URL = _env('ADMIN_URL', default='django-admin').strip('/')


def _protected_media(request, path):
    """Serve /media/ebooks/ and /media/user_photos/ — login required."""
    if not request.user.is_authenticated:
        from django.shortcuts import redirect
        return redirect(f'{settings.LOGIN_URL}?next={request.path}')
    import os
    full_path = os.path.join(settings.MEDIA_ROOT, path)
    if not os.path.realpath(full_path).startswith(os.path.realpath(settings.MEDIA_ROOT)):
        raise Http404  # path traversal guard
    return _serve(request, path, document_root=settings.MEDIA_ROOT)


urlpatterns = [
    path(f'{_ADMIN_URL}/', admin.site.urls),
    path('', include('public.urls')),
    path('', include('accounts.urls')),
    path('catalog/', include('catalog.urls')),
    path('circulation/', include('circulation.urls')),
    path('acquisitions/', include('acquisitions.urls')),
    path('reports/', include('reports.urls')),
    path('chat/', include('chat.urls')),
    path('assistant/', include('chatbot.urls')),
    # Sensitive media paths — login required before serving file
    re_path(r'^media/(?P<path>ebooks/.+)$',   _protected_media),
    re_path(r'^media/(?P<path>user_photos/.+)$', _protected_media),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT) \
  + static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)


if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Custom error handlers — huzuia Django kuonyesha stack traces / debug info
handler400 = 'django.views.defaults.bad_request'
handler403 = 'django.views.defaults.permission_denied'
handler404 = 'django.views.defaults.page_not_found'
handler500 = 'django.views.defaults.server_error'
