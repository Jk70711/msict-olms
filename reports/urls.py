# ============================================================
# reports/urls.py — URL za Ripoti na Takwimu
# Inashughulikia: ripoti za wanachama, vitabu, mikopo, faini
# na uuzaji wa data kama CSV na SQL maalum
# ============================================================

from django.urls import path
from . import views

urlpatterns = [
    path('', views.reports_home_view, name='reports_home'),                              # /reports/ — Ukurasa mkuu wa ripoti
    path('members/', views.report_members_view, name='report_members'),                  # Ripoti ya wanachama wote
    path('books/', views.report_books_view, name='report_books'),                        # Ripoti ya vitabu
    path('circulation/', views.report_circulation_view, name='report_circulation'),      # Ripoti ya mikopo
    path('fines/', views.report_fines_view, name='report_fines'),                        # Ripoti ya faini
    path('export/members/csv/', views.export_members_csv_view, name='export_members_csv'),  # Pakua wanachama (CSV)
    path('export/books/csv/', views.export_books_csv_view, name='export_books_csv'),    # Pakua vitabu (CSV)
    path('export/members/pdf/', views.export_members_pdf_view, name='export_members_pdf'),  # Pakua wanachama (PDF)
    path('export/books/pdf/', views.export_books_pdf_view, name='export_books_pdf'),    # Pakua vitabu (PDF)
    path('export/circulation/pdf/', views.export_circulation_pdf_view, name='export_circulation_pdf'),  # Pakua mikopo (PDF)
    path('export/fines/pdf/', views.export_fines_pdf_view, name='export_fines_pdf'),    # Pakua faini (PDF)
    path('sql/', views.sql_report_view, name='sql_report'),                              # Ripoti maalum kwa SQL (admin)
]
