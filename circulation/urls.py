# ============================================================
# circulation/urls.py — URL za Mikopo, Maombi, Faini na Uhifadhi
# Inashughulikia mzunguko wote wa kukopa vitabu na kurudisha
# ============================================================

from django.urls import path
from . import views

urlpatterns = [
    # ── Dashboard na Orodha ya Mwanachama ────────────────────
    path('member-dashboard/', views.member_dashboard_view, name='member_dashboard'),             # Dashboard ya mwanachama
    path('my-fines/', views.my_fines_view, name='my_fines'),                                    # Faini zangu
    path('my-loss-reports/', views.my_loss_reports_view, name='my_loss_reports'),                # Ripoti za hasara zangu
    path('my-fines/pay/<int:fine_id>/', views.pay_fine_view, name='pay_fine'),                 # Lipa faini
    path('loss-report/pay/<int:report_id>/', views.pay_loss_fine_view, name='pay_loss_fine'), # Lipa faini ya hasara
    path('my-borrowings/msict/', views.member_msict_borrowings_view, name='member_msict_borrowings'),  # Mikopo yangu
    path('my-borrowings/ill/', views.member_ill_borrowings_view, name='member_ill_borrowings'),  # Mikopo ya ILL
    path('softcopy-library/', views.softcopy_library_view, name='softcopy_library'),             # Vitabu vya kidijitali nilivyokopa

    # ── Maombi ya Kukopa ─────────────────────────────────
    path('borrow/', views.borrow_catalog_view, name='borrow_catalog'),                           # Tafuta vitabu vya kukopa
    path('borrow/request/<int:copy_id>/', views.submit_borrow_request_view, name='submit_borrow_request'),   # Tuma ombi la kukopa (copy-level)
    path('borrow/request-book/<int:book_id>/', views.request_borrow_book_view, name='request_borrow_book'),         # Auto-pick hardcopy
    path('borrow/request-softcopy/<int:book_id>/', views.request_borrow_softcopy_view, name='request_borrow_softcopy'), # Auto-pick borrowable softcopy
    path('borrow/download-free/<int:book_id>/', views.download_free_book_view, name='download_free_book'),          # Auto-pick free softcopy
    path('borrow/read-free/<int:book_id>/', views.read_free_book_view, name='read_free_book'),                      # Read free softcopy inline
    path('softcopy/payment/<int:copy_id>/', views.softcopy_payment_view, name='softcopy_payment'),                 # Softcopy payment page
    path('softcopy/renewal-payment/<int:transaction_id>/', views.softcopy_renewal_payment_view, name='softcopy_renewal_payment'),  # Softcopy renewal payment
    path('borrow/cancel/<int:request_id>/', views.cancel_borrow_request_view, name='cancel_borrow_request'), # Futa ombi
    path('borrow/approve/<int:request_id>/', views.approve_borrow_request_view, name='approve_borrow_request'),
    path('borrow/reject/<int:request_id>/', views.reject_borrow_request_view, name='reject_borrow_request'),
    path('borrow/delete/<int:request_id>/', views.delete_borrow_request_view, name='delete_borrow_request'),
    path('borrow/issue/<int:request_id>/', views.issue_copy_view, name='issue_copy'),
    path('softcopy/process-payment/<int:request_id>/', views.process_softcopy_payment_view, name='process_softcopy_payment'),
    path('softcopy/cancel-access/<int:tx_id>/', views.cancel_softcopy_access_view, name='cancel_softcopy_access'),  # Cancel softcopy access early
    path('borrow/copy-lookup/', views.copy_lookup_view, name='copy_lookup'),
    path('requests/', views.all_requests_view, name='all_requests'),
    path('issued-records/', views.issued_records_view, name='issued_records'),

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
    path('loss-reports/<int:report_id>/pay/', views.record_loss_fine_payment_view, name='record_loss_fine_payment'), # Rekodi malipo ya faini ya hasara
    path('fines/users/', views.users_with_unpaid_fines_view, name='users_with_fines'),           # Watumiaji wanaodaiwa
    path('fines/user/<int:user_id>/', views.user_fines_view, name='user_fines'),                 # Faini za mtumiaji mahususi
    path('fines/user/<int:user_id>/bulk-pay/', views.bulk_fine_payment_view, name='bulk_fine_payment'),  # Malipo ya pamoja
    path('fines/<int:fine_id>/receipt/', views.fine_receipt_pdf_view, name='fine_receipt_pdf'),  # Pakua risiti ya faini
    path('softcopy/<int:tx_id>/receipt/', views.softcopy_receipt_pdf_view, name='softcopy_receipt_pdf'),  # Softcopy link fee receipt
    path('loss/<int:report_id>/receipt/', views.loss_fine_receipt_pdf_view, name='loss_fine_receipt_pdf'),  # Loss fine receipt

    # ── Historia ya Kurudisha na Mikopo Yote ───────────────
    path('return-history/', views.return_history_view, name='return_history'),   # Historia ya vitabu vilivyorudishwa
    path('borrowings/', views.all_borrowings_view, name='all_borrowings'),       # Orodha yote ya mikopo

    # ── Loss Reports ────────────────────────────────────
    path('loss/report/<int:transaction_id>/', views.report_loss_view, name='report_loss'),        # Member: submit loss report
    path('loss/reports/', views.loss_report_list_view, name='loss_report_list'),                  # Librarian: view all loss reports
    path('loss/confirm/<int:report_id>/', views.confirm_loss_view, name='confirm_loss'),          # Librarian: confirm or dismiss
    path('loss/recover/<int:report_id>/', views.recover_book_view, name='recover_book'),          # Librarian: mark book recovered

    # ── Damage Reports & Lost/Damaged Copies ────────────────────
    path('damage/pay/<int:report_id>/', views.pay_damage_fine_view, name='pay_damage_fine'),       # Member: pay damage fine
    path('my-damage-reports/', views.my_damage_reports_view, name='my_damage_reports'),            # Member: view own damage reports
    path('damage/<int:report_id>/pay/', views.record_damage_fine_payment_view, name='record_damage_fine_payment'),  # Librarian: record damage fine payment
    path('lost-damaged-copies/', views.lost_damaged_copies_view, name='lost_damaged_copies'),      # Librarian: manage lost & damaged copies
]
