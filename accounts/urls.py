# ============================================================
# accounts/urls.py — URL za Watumiaji na Usalama
# Inashughulikia: login, OTP, wasifu, kadi, watumiaji, mipangilio
# ============================================================

from django.urls import path
from . import views

urlpatterns = [
    # ── Kuingia na Kutoka ────────────────────────────────────
    path('login/', views.login_view, name='login'),                                          # /login/ — Ukurasa wa kuingia
    path('logout/', views.logout_view, name='logout'),                                       # /logout/ — Kutoka nje
    path('forgot-password/', views.forgot_password_view, name='forgot_password'),            # Omba OTP kwa barua pepe
    path('verify-otp/', views.verify_otp_view, name='verify_otp'),                           # Thibitisha OTP uliopokea
    path('reset-password/', views.reset_password_view, name='reset_password'),               # Weka nywila mpya

    # ── Wasifu na Kadi ────────────────────────────────────
    path('dashboard/', views.dashboard_redirect, name='dashboard'),                          # Elekeza kwa dashboard sahihi
    path('profile/', views.profile_view, name='profile'),                                    # Wasifu wa mtumiaji
    path('change-password/', views.change_password_view, name='change_password'),            # Badilisha nywila
    path('virtual-card/', views.virtual_card_view, name='virtual_card'),                     # Kadi ya maktaba
    path('virtual-card/pdf/', views.virtual_card_pdf_view, name='virtual_card_pdf'),         # Pakua kadi kama PDF

    # ── Usimamizi wa Watumiaji (librarian/admin) ─────────────────
    path('users/', views.user_list_view, name='user_list'),                                  # Orodha ya watumiaji wote
    path('users/create/', views.create_user_view, name='create_user'),                       # Unda mtumiaji mpya
    path('users/<int:user_id>/detail/', views.user_detail_view, name='user_detail'),         # Maelezo ya mtumiaji
    path('users/<int:user_id>/edit/', views.edit_user_view, name='edit_user'),               # Hariri mtumiaji
    path('users/<int:user_id>/reset-password/', views.reset_user_password_view, name='reset_user_password'),  # Weka upya nywila
    path('users/<int:user_id>/<str:action>/', views.user_action_view, name='user_action'),   # Zuia/fungua akaunti

    # ── Dashboard na Mipangilio ya Msimamizi (admin) ────────────
    path('admin-dashboard/', views.admin_dashboard_view, name='admin_dashboard'),            # Dashboard ya msimamizi
    path('admin/suspicious-activity/', views.suspicious_activity_view, name='suspicious_activity'),  # Shughuli za tuhuma
    path('admin/suspended-members/', views.suspended_members_view, name='suspended_members'),       # Wanachama waliofungiwa
    path('admin/unlock/<int:user_id>/', views.unlock_account_view, name='unlock_account'),   # Fungua akaunti iliyozuiwa
    path('admin/audit-logs/', views.audit_log_view, name='audit_logs'),                      # Historia ya vitendo
    path('admin/audit-logs/clear/', views.clear_audit_logs_view, name='clear_audit_logs'),   # Futa vitendo vyote
    path('admin/audit-log/<int:pk>/delete/', views.delete_audit_log_view, name='delete_audit_log'),  # Futa rekodi moja
    path('admin/security-alert/<int:pk>/delete/', views.delete_security_alert_view, name='delete_security_alert'),  # Futa tahadhari
    path('admin/security-alerts/', views.security_alerts_view, name='security_alerts'),                               # Tahadhari zote
    path('admin/preferences/', views.system_preferences_view, name='system_preferences'),    # Mipangilio ya mfumo
    path('superuser/dashboard/', views.superuser_dashboard_view, name='superuser_dashboard'),# Dashboard ya superuser
    path('toggle-theme/', views.toggle_theme_view, name='toggle_theme'),                     # Badilisha dark/light mode
    path('system-appearance/', views.system_appearance_view, name='system_appearance'),      # Badilisha rangi/fonti
]
