# ============================================================
# acquisitions/urls.py — URL za Manunuzi ya Vitabu
# Inashughulikia: wauzaji, bajeti, maagizo ya kununua, na ILL
# ============================================================

from django.urls import path
from . import views

urlpatterns = [
    # ── Wauzaji wa Vitabu ─────────────────────────────────
    path('vendors/', views.vendor_list_view, name='vendor_list'),                                  # Orodha ya wauzaji
    path('vendors/create/', views.vendor_create_view, name='vendor_create'),                       # Ongeza muuzaji mpya

    # ── Bajeti ──────────────────────────────────────────
    path('budgets/', views.budget_list_view, name='budget_list'),                                  # Orodha ya bajeti
    path('budgets/create/', views.budget_create_view, name='budget_create'),                       # Unda bajeti mpya

    # ── Maagizo ya Kununua (Purchase Orders) ─────────────────
    path('orders/', views.purchase_order_list_view, name='purchase_order_list'),                   # Maagizo yote ya kununua
    path('orders/create/', views.purchase_order_create_view, name='purchase_order_create'),        # Unda agizo jipya
    path('orders/<int:po_id>/', views.purchase_order_detail_view, name='purchase_order_detail'),   # Maelezo ya agizo moja

    # ── ILL — Kukopa kutoka Maktaba Nyingine ────────────────
    path('ill/', views.ill_request_list_view, name='ill_request_list'),                            # Maombi ya ILL
    path('ill/create/', views.ill_request_create_view, name='ill_request_create'),                 # Ombi jipya la ILL
    path('ill/<int:ill_id>/status/', views.ill_request_update_status_view, name='ill_request_update_status'),  # Sasisha hali ya ILL
]
