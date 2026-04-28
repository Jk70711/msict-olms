# ============================================================
# circulation/urls.py — URL za Mikopo, Maombi, Faini na Uhifadhi
# Inashughulikia mzunguko wote wa kukopa vitabu na kurudisha
# ============================================================

from django.urls import path
from . import views

urlpatterns = [
    # ── Dashboard na Orodha ya Mwanachama ────────────────────
    path('member-dashboard/', views.member_dashboard_view, name='member_dashboard'),             # Dashboard ya mwanachama
    path('my-borrowings/msict/', views.member_msict_borrowings_view, name='member_msict_borrowings'),  # Mikopo yangu
    path('my-borrowings/ill/', views.member_ill_borrowings_view, name='member_ill_borrowings'),  # Mikopo ya ILL
    path('softcopy-library/', views.softcopy_library_view, name='softcopy_library'),             # Vitabu vya kidijitali nilivyokopa

    # ── Maombi ya Kukopa ─────────────────────────────────
    path('borrow/', views.borrow_catalog_view, name='borrow_catalog'),                           # Tafuta vitabu vya kukopa
    path('borrow/request/<int:copy_id>/', views.submit_borrow_request_view, name='submit_borrow_request'),   # Tuma ombi la kukopa (copy-level)
    path('borrow/request-book/<int:book_id>/', views.request_borrow_book_view, name='request_borrow_book'),         # Auto-pick hardcopy
    path('borrow/request-softcopy/<int:book_id>/', views.request_borrow_softcopy_view, name='request_borrow_softcopy'), # Auto-pick borrowable softcopy
    path('borrow/download-free/<int:book_id>/', views.download_free_book_view, name='download_free_book'),          # Auto-pick free softcopy
    path('borrow/cancel/<int:request_id>/', views.cancel_borrow_request_view, name='cancel_borrow_request'), # Futa ombi
    path('borrow/approve/<int:request_id>/', views.approve_borrow_request_view, name='approve_borrow_request'), # Idhinisha ombi
    path('borrow/reject/<int:request_id>/', views.reject_borrow_request_view, name='reject_borrow_request'),    # Kataa ombi
    path('requests/', views.all_requests_view, name='all_requests'),                             # Maombi yote (kwa mtunzaji)

    # ── Kurudisha na Kuongeza Muda ──────────────────────────
    path('renew/<int:transaction_id>/', views.renew_transaction_view, name='renew_transaction'), # Ongeza muda wa mkopo
    path('return-early/<int:transaction_id>/', views.return_early_view, name='return_early'),    # Rudisha mapema (softcopy)
    path('return-desk/', views.return_hardcopy_view, name='return_desk'),                        # Desk ya kurudisha hardcopy
    path('desk/', views.circulation_desk_view, name='circulation_desk'),                         # Desk ya jumla ya circulation

    # ── Uhifadhi wa Nafasi (Softcopy Queue) ───────────────────────
    path('reserve/<int:book_id>/', views.reserve_book_view, name='reserve_book'),
    path('reserve/cancel/<int:reservation_id>/', views.cancel_reservation_view, name='cancel_reservation'),
    path('reserve/borrow/<int:reservation_id>/', views.softcopy_queue_borrow_view, name='queue_borrow'),
    path('my-reservations/', views.my_reservations_view, name='my_reservations'),
    path('reservations/', views.reservation_list_view, name='reservation_list'),
    path('reservations/cancel/<int:reservation_id>/', views.librarian_cancel_reservation_view, name='librarian_cancel_reservation'),
    path('reservations/renew/<int:reservation_id>/', views.renew_reservation_view, name='renew_reservation'),

    # ── Vitabu Vilivyochelewa na Faini ─────────────────────
    path('overdue/', views.overdue_list_view, name='overdue_list'),                              # Vitabu vilivyopita tarehe
    path('fines/', views.fine_list_view, name='fine_list'),                                      # Orodha ya faini
    path('fines/<int:fine_id>/pay/', views.record_fine_payment_view, name='record_fine_payment'), # Rekodi malipo ya faini

    # ── Historia ya Kurudisha na Mikopo Yote ───────────────
    path('return-history/', views.return_history_view, name='return_history'),   # Historia ya vitabu vilivyorudishwa
    path('borrowings/', views.all_borrowings_view, name='all_borrowings'),       # Orodha yote ya mikopo
]
