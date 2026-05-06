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
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('django-admin/', admin.site.urls),
    path('', include('public.urls')),
    path('', include('accounts.urls')),
    path('catalog/', include('catalog.urls')),
    path('circulation/', include('circulation.urls')),
    path('acquisitions/', include('acquisitions.urls')),
    path('reports/', include('reports.urls')),
    path('chat/', include('chat.urls')),
    path('assistant/', include('chatbot.urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT) \
  + static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)


if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
