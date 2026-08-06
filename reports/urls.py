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
    path('revenue/', views.report_revenue_view, name='report_revenue'),                  # Ripoti ya mapato
    path('export/revenue/pdf/', views.export_revenue_pdf_view, name='export_revenue_pdf'),  # Pakua mapato (PDF)
    path('export/members/csv/', views.export_members_csv_view, name='export_members_csv'),  # Pakua wanachama (CSV)
    path('export/books/csv/', views.export_books_csv_view, name='export_books_csv'),    # Pakua vitabu (CSV)
    path('export/members/pdf/', views.export_members_pdf_view, name='export_members_pdf'),  # Pakua wanachama (PDF)
    path('export/books/pdf/', views.export_books_pdf_view, name='export_books_pdf'),    # Pakua vitabu (PDF)
    path('export/circulation/pdf/', views.export_circulation_pdf_view, name='export_circulation_pdf'),  # Pakua mikopo (PDF)
    path('export/fines/pdf/', views.export_fines_pdf_view, name='export_fines_pdf'),    # Pakua faini (PDF)
    path('custom/', views.custom_report_view, name='custom_report'),
    path('custom/preview/', views.custom_report_preview_view, name='custom_report_preview'),
    path('custom/export/', views.custom_report_export_view, name='custom_report_export'),
    path('custom/save-template/', views.save_report_template_view, name='save_report_template'),
    path('custom/delete-template/<int:template_id>/', views.delete_report_template_view, name='delete_report_template'),
    path('export/members/xlsx/', views.export_members_xlsx_view, name='export_members_xlsx'),      # Pakua wanachama (Excel)
    path('export/books/xlsx/', views.export_books_xlsx_view, name='export_books_xlsx'),          # Pakua vitabu (Excel)
    path('export/circulation/xlsx/', views.export_circulation_xlsx_view, name='export_circulation_xlsx'),  # Pakua mikopo (Excel)
    path('export/fines/xlsx/', views.export_fines_xlsx_view, name='export_fines_xlsx'),          # Pakua faini (Excel)
    path('loss-reports/', views.report_loss_view, name='report_loss_list'),                   # Ripoti ya vitabu vilivyopotea
    path('export/loss/pdf/', views.export_loss_pdf_view, name='export_loss_pdf'),      # Pakua ripoti ya upoteaji (PDF)
    path('sql/', views.sql_report_view, name='sql_report'),                              # Ripoti maalum kwa SQL (admin)
    path('export/sql/pdf/', views.export_sql_pdf_view, name='export_sql_pdf'),          # Pakua SQL (PDF)
    path('export/sql/csv/', views.export_sql_csv_view, name='export_sql_csv'),          # Pakua SQL (CSV)
]
