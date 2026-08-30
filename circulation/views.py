# ============================================================
# circulation/views.py
# Views za mzunguko wote wa kukopa vitabu:
#   - Mwanachama: tuma ombi, fuatilia mikopo, hifadhi nafasi
#   - Mtunzaji: idhinisha/kataa maombi, rudisha vitabu, simamia faini
# ============================================================

from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.utils import timezone
from django.db.models import Q
from django.conf import settings
import re
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from accounts.views import librarian_required
from accounts.utils import log_audit, send_sms, send_email_notification, create_notification, notify_user, mark_badge_viewed
from accounts.models import OLMSUser


# ----------------------------------------------------------------------
# Msaidizi wa Kusoma Mipangilio — Anasoma mipangilio kutoka DB au settings.py
# ----------------------------------------------------------------------
def _pref(key, default):
    """Read from SystemPreference DB, fallback to settings, then default."""
    try:
        from accounts.models import SystemPreference
        val = SystemPreference.objects.filter(key=key).values_list('value', flat=True).first()
        if val is not None:
            return val
    except Exception:
        pass
    return getattr(settings, key, default)


from catalog.models import BookCopy, Book, Course
from .models import BorrowRequest, BorrowingTransaction, Reservation, Fine, Notification, LossReport, DamageReport


def _ensure_member_borrower(request):
    """Allow only full members to perform borrow/reservation actions."""
    if request.user.role != 'member' or request.user.is_guest:
        messages.error(request, 'Borrowing and reservation are available to approved members only.')
        return redirect('dashboard')
    return None


def _record_revenue(user, account_type, amount, description='', reference_id=None, reference_table='', recorded_by=None):
    """Best-effort revenue recording. Never blocks core user flow."""
    try:
        from .models import RevenueTransaction
        RevenueTransaction.objects.create(
            user=user,
            account_type=account_type,
            amount=amount,
            description=description,
            reference_id=reference_id,
            reference_table=reference_table,
            recorded_by=recorded_by,
        )
    except Exception:
        pass


# Dashboard ya mwanachama — inaonyesha:
#   - Vitabu alivyokopa (active na overdue)
#   - Maombi yanayosubiri idhini
#   - Uhifadhi wa nafasi
#   - Faini ambazo hazijalipwa
#   - Arifa 10 za hivi karibuni
@login_required
# ----------------------------------------------------------------------
# View ya Dashboard ya Mwanachama — Dashboard ya mwanachama
# ----------------------------------------------------------------------
def member_dashboard_view(request):
    user = request.user

    if user.role != 'member' or user.is_guest:
        messages.error(request, 'This dashboard is available to approved members only.')
        return redirect('dashboard')
    
    # Check account status
    if user.registration_status == 'pending':
        return render(request, 'circulation/member_dashboard.html', {
            'account_pending': True,
            'registration_status': user.registration_status,
        })
    
    active_transactions = BorrowingTransaction.objects.filter(
        user=user, status__in=['borrowed', 'overdue']
    ).exclude(
        copy__copy_type='softcopy',
        copy__access_type='borrow',
        due_date__lt=timezone.now(),
    ).select_related('copy__book').order_by('-borrow_date')

    overdue_transactions = active_transactions.filter(status='overdue').exclude(copy__copy_type='softcopy')
    lost_transactions = BorrowingTransaction.objects.filter(
        user=user, status='lost', copy__book__isnull=False,
        loss_report__status__in=['pending', 'confirmed'],
    ).select_related('copy__book').order_by('-borrow_date')
    pending_requests = BorrowRequest.objects.filter(user=user, status='pending').select_related('copy__book', 'temp_book')
    approved_requests = BorrowRequest.objects.filter(
        user=user, status='approved'
    ).exclude(
        copy__copy_type='softcopy'
    ).select_related('copy__book', 'temp_book')
    reservations = Reservation.objects.filter(
        user=user, status__in=['pending', 'notified']
    ).select_related('book')
    notified_reservations = reservations.filter(status='notified')
    unpaid_fines = Fine.objects.filter(user=user, paid=False)
    notifications = Notification.objects.filter(user=user).order_by('-created_at')[:10]
    borrow_history = BorrowingTransaction.objects.filter(
        user=user, status__in=['returned', 'lost']
    ).select_related('copy__book').order_by('-return_date')[:5]

    # Get fines for overdue transactions (excluding loss report transactions)
    # If a book is reported lost, we only count overdue fine if it was already overdue before loss report
    loss_report_tx_ids = LossReport.objects.filter(user=user, status__in=['pending', 'confirmed']).values_list('transaction_id', flat=True)
    overdue_tx_ids = overdue_transactions.values_list('id', flat=True)

    # Overdue fines for transactions NOT reported as lost
    overdue_fines = Fine.objects.filter(
        transaction_id__in=overdue_tx_ids
    ).exclude(transaction_id__in=loss_report_tx_ids)

    # Get loss fines (from active loss reports only — not resolved/recovered)
    loss_reports_with_fines = LossReport.objects.filter(
        user=user, status__in=['pending', 'confirmed'],
        loss_fine__isnull=False
    ).select_related('loss_fine', 'transaction')
    loss_fines = [r.loss_fine for r in loss_reports_with_fines]

    # For loss reports, check if the transaction was overdue at the time of loss report
    # If yes, count both overdue fine and loss fine concurrently
    # If no, only count loss fine (no overdue fine)
    loss_report_overdue_fines = []
    for lr in loss_reports_with_fines:
        if lr.transaction and lr.transaction.status == 'overdue' and lr.reported_at:
            # Check if it was already overdue when reported
            if lr.transaction.due_date and lr.reported_at > lr.transaction.due_date:
                # It was overdue when reported - add to overdue fines
                overdue_fines_for_tx = Fine.objects.filter(transaction=lr.transaction)
                overdue_fines = overdue_fines | overdue_fines_for_tx

    # Calculate fine totals for overdue books
    total_fine_amount = sum(f.amount for f in overdue_fines)
    total_unpaid = sum(f.remaining_balance for f in overdue_fines)
    total_paid = sum(f.amount_paid for f in overdue_fines)

    # Calculate loss fine totals
    total_loss_fine_amount = sum(f.amount for f in loss_fines)
    total_loss_unpaid = sum(f.remaining_balance for f in loss_fines)
    total_loss_paid = sum(f.amount_paid for f in loss_fines)

    # Combined totals (all unpaid fines)
    all_unpaid_fines = list(overdue_fines.filter(paid=False)) + [f for f in loss_fines if not f.paid]
    total_all_unpaid = sum(f.remaining_balance for f in all_unpaid_fines)

    # Get damage reports (active — not resolved/dismissed)
    damage_reports_qs = DamageReport.objects.filter(
        user=user, status__in=['pending', 'confirmed']
    ).select_related('transaction__copy__book', 'damage_fine').order_by('-reported_at')
    my_damage_reports = list(damage_reports_qs[:5])

    damage_fines = [r.damage_fine for r in my_damage_reports if r.damage_fine]
    total_damage_fine_amount = sum(f.amount for f in damage_fines)
    total_damage_unpaid = sum(f.remaining_balance for f in damage_fines)
    total_damage_paid = sum(f.amount_paid for f in damage_fines)

    # Include damage fines in combined unpaid total
    all_unpaid_fines = list(overdue_fines.filter(paid=False)) + [f for f in loss_fines if not f.paid] + [f for f in damage_fines if not f.paid]
    total_all_unpaid = sum(f.remaining_balance for f in all_unpaid_fines)

    # Build fine info dictionary for each transaction (for softcopy return check)
    tx_fines = {}
    for fine in overdue_fines:
        if fine.transaction_id not in tx_fines:
            tx_fines[fine.transaction_id] = {
                'amount': fine.amount,
                'remaining': fine.remaining_balance,
                'paid': fine.paid,
                'amount_paid': fine.amount_paid,
            }

    my_loss_reports = LossReport.objects.filter(
        user=user, status__in=['pending', 'confirmed']
    ).select_related('transaction__copy__book', 'loss_fine').order_by('-reported_at')
    my_loss_reports_top5 = list(my_loss_reports[:5])

    # ── Personal analytics chart data (JSON for Chart.js) ────────────
    import json as _json
    from datetime import datetime as _dt, timedelta as _td
    from collections import defaultdict as _dd

    # Personal monthly borrowing activity (last 6 months)
    my_monthly_borrows = {}
    for i in range(6):
        month = _dt.now() - _td(days=30 * i)
        month_key = month.strftime('%b %Y')
        cnt = BorrowingTransaction.objects.filter(
            user=user,
            borrow_date__month=month.month,
            borrow_date__year=month.year
        ).count()
        my_monthly_borrows[month_key] = cnt
    # Reverse so oldest is first
    my_monthly_borrows = dict(reversed(list(my_monthly_borrows.items())))

    my_borrow_chart_data = _json.dumps({
        'labels': list(my_monthly_borrows.keys()),
        'values': list(my_monthly_borrows.values()),
    })

    # Fine breakdown doughnut (overdue vs loss vs damage)
    my_fine_chart_data = _json.dumps({
        'labels': ['Overdue Fines', 'Loss Fines', 'Damage Fines'],
        'values': [
            float(total_unpaid),
            float(total_loss_unpaid),
            float(total_damage_unpaid),
        ],
    })

    # Borrow status distribution doughnut
    my_active_count = active_transactions.filter(status='borrowed').count()
    my_overdue_count = overdue_transactions.count()
    my_lost_count = lost_transactions.count()
    my_returned_count = BorrowingTransaction.objects.filter(user=user, status='returned').count()

    my_status_chart_data = _json.dumps({
        'labels': ['Borrowed', 'Overdue', 'Lost', 'Returned'],
        'values': [my_active_count, my_overdue_count, my_lost_count, my_returned_count],
    })

    context = {
        'active_transactions': active_transactions,
        'overdue_transactions': overdue_transactions,
        'lost_transactions': lost_transactions,
        'pending_requests': pending_requests,
        'reservations': reservations,
        'notified_reservations': notified_reservations,
        'unpaid_fines': unpaid_fines,
        'overdue_fines': overdue_fines,
        'loss_fines': loss_fines,
        'damage_fines': damage_fines,
        'my_damage_reports': my_damage_reports,
        'all_unpaid_fines': all_unpaid_fines,
        'tx_fines': tx_fines,
        'total_fines': sum(f.amount for f in unpaid_fines),
        'total_fine_amount': total_fine_amount,
        'total_unpaid': total_unpaid,
        'total_paid': total_paid,
        'total_loss_fine_amount': total_loss_fine_amount,
        'total_loss_unpaid': total_loss_unpaid,
        'total_loss_paid': total_loss_paid,
        'total_damage_fine_amount': total_damage_fine_amount,
        'total_damage_unpaid': total_damage_unpaid,
        'total_damage_paid': total_damage_paid,
        'total_all_unpaid': total_all_unpaid,
        'notifications': notifications,
        # has_overdue: only show alert if there are overdue transactions with unpaid/no fines
        'has_overdue': overdue_transactions.filter(
            fines__paid=False
        ).exists() | overdue_transactions.filter(fines__isnull=True).exists(),
        # has_lost: only show alert if there are active loss reports with unpaid fines
        # (status pending = no fine yet, or confirmed with unpaid fine)
        'has_lost': my_loss_reports.filter(
            loss_fine__isnull=True
        ).exists() | my_loss_reports.filter(
            loss_fine__isnull=False, loss_fine__paid=False
        ).exists(),
        # has_damaged: show alert if there are active damage reports with unpaid fines
        'has_damaged': damage_reports_qs.filter(
            damage_fine__isnull=False, damage_fine__paid=False
        ).exists(),
        'borrow_history': borrow_history,
        'my_loss_reports': my_loss_reports_top5,
        'approved_requests': approved_requests,
        'my_borrow_chart_data': my_borrow_chart_data,
        'my_fine_chart_data': my_fine_chart_data,
        'my_status_chart_data': my_status_chart_data,
    }
    return render(request, 'circulation/member_dashboard.html', context)


# ── Book-level hardcopy request — copy assigned later by librarian ────────────
@login_required
# ----------------------------------------------------------------------
# View ya Omba Kukopa Kitabu — Mwanachama anaomba kukopa hardcopy
# ----------------------------------------------------------------------
def request_borrow_book_view(request, book_id):
    """Member requests a hardcopy book title. No copy is auto-assigned yet.
    The librarian issues the specific copy via the 'Issue Copy' modal at pickup."""
    guard = _ensure_member_borrower(request)
    if guard:
        return guard

    book = get_object_or_404(Book, pk=book_id)

    if request.user.has_overdue():
        messages.error(request, 'You have overdue items with unpaid fines. Resolve them before borrowing.')
        return redirect('member_dashboard')
    if request.user.has_unpaid_fines():
        messages.error(request, 'You have unpaid fines. Pay at the circulation desk before borrowing.')
        return redirect('member_dashboard')

    if not book.copies.filter(copy_type='hardcopy', status='available').exists():
        messages.error(request, f'No available hardcopy for "{book.title}" right now.')
        return redirect('borrow_catalog')

    active_borrows = request.user.active_borrows_count()
    pending_requests = BorrowRequest.objects.filter(user=request.user, status='pending').count()
    max_copies = int(_pref('MAX_COPIES_PER_BORROW', 3))
    if active_borrows + pending_requests >= max_copies:
        messages.error(request, f'Maximum of {max_copies} books allowed. Return a book before requesting more.')
        return redirect('member_dashboard')

    # Duplicate check — already has a pending/approved request for this book
    already = (
        BorrowRequest.objects.filter(user=request.user, temp_book=book, status__in=['pending', 'approved']).exists() or
        BorrowRequest.objects.filter(user=request.user, copy__book=book, status__in=['pending', 'approved']).exists()
    )
    if already:
        messages.warning(request, f'You already have an active request for "{book.title}".')
        return redirect('borrow_catalog')

    BorrowRequest.objects.create(user=request.user, temp_book=book, copy=None)
    log_audit(request.user, f"Hardcopy borrow request submitted for '{book.title}'", request)
    messages.success(request, f'Request submitted for "{book.title}". Please come to the library once approved.')
    return redirect('member_dashboard')


@login_required
# ----------------------------------------------------------------------
# View ya Omba Kukopa Softcopy — Mwanachama anaomba kukopa softcopy
# ----------------------------------------------------------------------
def request_borrow_softcopy_view(request, book_id):
    """Auto-selects the first available borrowable softcopy and submits a request."""
    guard = _ensure_member_borrower(request)
    if guard:
        return guard

    book = get_object_or_404(Book, pk=book_id)
    copy = book.copies.filter(copy_type='softcopy', access_type='borrow', status='available').first()
    if not copy:
        messages.error(request, f'No special soft copy is available for "{book.title}" right now.')
        return redirect('borrow_catalog')
    return redirect('submit_borrow_request', copy.pk)


@login_required
# ----------------------------------------------------------------------
# View ya Pakua Kitabu Bure — Mwanachama anapakua softcopy bure
# ----------------------------------------------------------------------
def download_free_book_view(request, book_id):
    """Redirects to the free softcopy download for the given book."""
    book = get_object_or_404(Book, pk=book_id)
    copy = book.copies.filter(copy_type='softcopy', access_type='free').first()
    if not copy:
        messages.error(request, f'No free softcopy available for "{book.title}".')
        return redirect('borrow_catalog')
    return redirect('free_softcopy_download', copy.pk)


@login_required
def read_free_book_view(request, book_id):
    """Redirects to the free softcopy inline reader for the given book."""
    book = get_object_or_404(Book, pk=book_id)
    copy = book.copies.filter(copy_type='softcopy', access_type='free').first()
    if not copy:
        messages.error(request, f'No free softcopy available for "{book.title}".')
        return redirect('borrow_catalog')
    return redirect('serve_softcopy', copy.pk)


# Ukurasa wa kutafuta na kuomba kukopa vitabu (kwa mwanachama)
# Inazuia mwanachama ambaye ana vitabu vilivyochelewa
@login_required
# ----------------------------------------------------------------------
# View ya Katalogi ya Kukopa — Mwanachama anaona vitabu vya kukopa
# ----------------------------------------------------------------------
def borrow_catalog_view(request):
    if request.user.has_overdue():
        messages.error(request, 'You have overdue books. Return them before borrowing new ones.')
        return redirect('member_dashboard')
    if request.user.has_unpaid_fines():
        messages.error(request, 'You have unpaid fines. Pay at the circulation desk before browsing new borrows.')
        return redirect('member_dashboard')

    query = request.GET.get('q', '')
    course_id = request.GET.get('course', '')
    category_id = request.GET.get('category', '')

    # Oracle-safe: use correlated Subquery/Exists instead of Count annotations.
    # Count() triggers GROUP BY on ALL columns incl. NCLOB (ORA-22848). Subquery/Exists do not.
    from django.db.models import (
        Count, Q as _Q, Exists, OuterRef, Subquery, IntegerField, Value
    )
    from django.db.models.functions import Coalesce

    _any_hard     = BookCopy.objects.filter(book=OuterRef('pk'), copy_type='hardcopy')
    _hard_avail   = BookCopy.objects.filter(book=OuterRef('pk'), copy_type='hardcopy', status='available')
    _soft_borrow  = BookCopy.objects.filter(book=OuterRef('pk'), copy_type='softcopy', access_type='borrow', status='available')
    _soft_free    = BookCopy.objects.filter(book=OuterRef('pk'), copy_type='softcopy', access_type='free')

    _avail_hard_count_sq = (
        BookCopy.objects
        .filter(book=OuterRef('pk'), copy_type='hardcopy', status='available')
        .values('book')
        .annotate(_c=Count('id'))
        .values('_c')
    )

    books = (
        Book.objects
        .select_related('category')
        .prefetch_related('courses')
        .filter(
            # Show: available hardcopy OR all-borrowed hardcopy (reservable) OR softcopy
            Exists(_any_hard) | Exists(_soft_borrow) | Exists(_soft_free)
        )
        .annotate(
            avail_hard=Coalesce(
                Subquery(_avail_hard_count_sq, output_field=IntegerField()),
                Value(0),
            ),
            has_hard=Exists(_any_hard),          # book has at least one hardcopy (available or not)
            soft_borrow_avail=Exists(_soft_borrow),
            soft_free=Exists(_soft_free),
        )
    )

    if query:
        books = books.filter(
            Q(title__icontains=query) | Q(author__icontains=query) | Q(isbn__icontains=query)
        )
    if course_id:
        books = books.filter(courses__pk=course_id)
    if category_id:
        books = books.filter(category_id=category_id)

    courses = Course.objects.all()
    from catalog.models import Category
    categories = Category.objects.all()

    # IDs of books the current user has already reserved (pending or notified) — for UI feedback
    user_reserved_ids = list(
        Reservation.objects.filter(
            user=request.user, status__in=['pending', 'notified']
        ).values_list('book_id', flat=True)
    )

    return render(request, 'circulation/borrow_catalog.html', {
        'books': books,
        'query': query,
        'courses': courses,
        'categories': categories,
        'selected_course': course_id,
        'selected_category': category_id,
        'user_reserved_ids': user_reserved_ids,
    })


# Tuma ombi la kukopa nakala moja
# Inazuia: mwanachama ambaye ana overdue, faini, au amefika kikomo cha mikopo
@login_required
# ----------------------------------------------------------------------
# View ya Tuma Ombi la Kukopa — Mwanachama anatuma ombi la kukopa
# ----------------------------------------------------------------------
def submit_borrow_request_view(request, copy_id):
    guard = _ensure_member_borrower(request)
    if guard:
        return guard

    copy = get_object_or_404(BookCopy, pk=copy_id)

    # Damaged or lost hardcopies cannot be borrowed or requested
    if copy.copy_type == 'hardcopy' and copy.status in ('lost', 'damaged'):
        messages.error(request, f'This copy is marked as {copy.status} and cannot be borrowed.')
        return redirect('book_detail_public', book_id=copy.book_id)

    if copy.access_type == 'free':
        messages.info(request, 'Free soft copies do not need borrowing. Download directly.')
        return redirect('book_detail_public', book_id=copy.book_id)

    if request.user.has_overdue():
        messages.error(request, 'You have overdue items. Return them before borrowing new ones.')
        return redirect('member_dashboard')

    if request.user.has_unpaid_fines():
        messages.error(request, 'You have unpaid fines. Pay at the circulation desk before borrowing.')
        return redirect('member_dashboard')

    active_borrows = request.user.active_borrows_count()
    pending_requests = BorrowRequest.objects.filter(user=request.user, status='pending').count()
    total = active_borrows + pending_requests
    max_copies = int(_pref('MAX_COPIES_PER_BORROW', 3))
    if total >= max_copies:
        remaining = max_copies - active_borrows
        if remaining <= 0:
            messages.error(request, f'Maximum of {max_copies} books allowed. Return a book before requesting more.')
        else:
            messages.error(request, f'You have {active_borrows} active borrows. You can only request {remaining} more book(s).')
        return redirect('member_dashboard')

    if BorrowRequest.objects.filter(user=request.user, copy=copy, status='pending').exists():
        messages.warning(request, 'You already have a pending request for this copy.')
        return redirect('book_detail_public', book_id=copy.book_id)

    if copy.copy_type == 'softcopy':
        active_tx_exists = BorrowingTransaction.objects.filter(
            user=request.user,
            copy=copy,
            status__in=['borrowed', 'overdue'],
            due_date__gte=timezone.now(),
        ).exists()
        if active_tx_exists:
            messages.warning(request, 'You are already borrowing this soft copy. Check your borrowings to read it.')
            return redirect('member_dashboard')

        # ── Softcopy: redirect to payment page first ──
        if copy.prepaid_fee > 0:
            return redirect('softcopy_payment', copy_id=copy.pk)
        else:
            # Free softcopy: create transaction instantly
            tx = BorrowingTransaction.objects.create(
                user=request.user,
                copy=copy,
                borrow_type='softcopy',
            )
            fine_per_day = float(_pref('FINE_PER_DAY', 1000))
            _loan_days = int(_pref('LOAN_PERIOD_DAYS', 7))
            softcopy_url = request.build_absolute_uri(reverse('softcopy_access', args=[tx.access_token]))
            # Store access log
            from .models import SoftcopyAccessLog
            SoftcopyAccessLog.objects.create(
                user=request.user,
                copy=copy,
                transaction=tx,
                access_token=str(tx.access_token),
                access_url=softcopy_url,
                expires_at=tx.due_date,
            )
            msg_sms = (
                f"MSICT OLMS: You have been issued digital copy \"{copy.book.title}\" "
                f"from {tx.borrow_date.strftime('%d %b %Y')} to {tx.due_date.strftime('%d %b %Y')}. "
                f"Your ebook link: {softcopy_url} "
                f"Valid for {_loan_days} days. Sharing or misuse may lead to disciplinary action."
            )
            msg_email = (
                f"Dear {request.user.get_full_name() or request.user.username},<br><br>"
                f"You have been issued digital copy <b>\"{copy.book.title}\"</b>.<br>"
                f"<b>Borrow Date:</b> {tx.borrow_date.strftime('%d %b %Y')}<br>"
                f"<b>Due Date:</b> {tx.due_date.strftime('%d %b %Y')}<br>"
                f"<b>Access Link:</b> <a href='{softcopy_url}'>{softcopy_url}</a><br><br>"
                f"<i>Note: Your access is valid for {_loan_days} days. Sharing or misuse of digital content may lead to disciplinary action.</i>"
            )
            notify_user(request.user, msg_sms, 'sms', message_type='softcopy_link')
            notify_user(request.user, msg_email, 'email', subject=f'Digital Copy Issued — {copy.book.title}', message_type='softcopy_link')
            log_audit(request.user, f"Softcopy auto-issued '{copy.book.title}' [{copy.accession_no}]", request)
            messages.success(request, f'"{copy.book.title}" is ready to read. Access it from My Borrowings.')
            return redirect('member_msict_borrowings')

    # ── Hardcopy: create BorrowRequest for librarian approval ──────────────
    if copy.status != 'available':
        messages.error(request, 'This hardcopy is not available right now.')
        return redirect('book_detail_public', book_id=copy.book_id)

    BorrowRequest.objects.create(user=request.user, copy=copy)
    log_audit(request.user, f"Borrow request submitted for '{copy.book.title}' [{copy.accession_no}]", request)
    messages.success(request, f'Request submitted for "{copy.book.title}". Awaiting librarian approval.')
    return redirect('member_dashboard')


# Futa ombi la kukopa ambalo bado ni 'pending' (mwanachama anaweza kufuta yake tu)
@login_required
@require_POST
# ----------------------------------------------------------------------
# View ya Futa Ombi la Kukopa — Mwanachama anafuta ombi lake
# ----------------------------------------------------------------------
def cancel_borrow_request_view(request, request_id):
    """POST-only — prevents CSRF-style attacks via image tags or malicious links."""
    req = get_object_or_404(BorrowRequest, pk=request_id, user=request.user, status='pending')
    req.status = 'cancelled'
    req.save(update_fields=['status'])
    log_audit(request.user, f"Cancelled borrow request #{request_id}", request)
    messages.success(request, 'Borrow request cancelled.')
    return redirect('member_dashboard')


# Librarian deletes a borrow request — behavior depends on row type
@login_required
@librarian_required
@require_POST
def delete_borrow_request_view(request, request_id):
    """Librarian deletes a borrow request.
    - Approved & waiting issuing (no copy assigned): status → 'deleted' (record kept)
    - All other statuses (pending, rejected, cancelled, issued, process-payment): permanent deletion
    """
    req = get_object_or_404(BorrowRequest, pk=request_id)

    if req.status == 'approved' and not req.copy_id:
        # Waiting issuing — soft delete, keep record with 'deleted' status
        req.status = 'deleted'
        req.save(update_fields=['status'])
        log_audit(request.user, f"Soft-deleted approved borrow request #{request_id} ({req.user.username}) — waiting issuing", request)
        messages.success(request, f'Approved request #{request_id} (waiting issuing) has been deleted.')
    else:
        # All other rows — permanent deletion
        title = req.copy.book.title if req.copy_id else (req.temp_book.title if req.temp_book_id else '?')
        username = req.user.username
        req.delete()
        log_audit(request.user, f"Permanently deleted borrow request #{request_id} ({username} — {title}) [{req.status}]", request)
        messages.success(request, f'Request #{request_id} has been permanently deleted.')

    return redirect('all_requests')


# Idhinisha ombi la kukopa (kwa mtunzaji au admin)
# Hardcopy: inathibitisha tu (copy inatolewa baadaye na librarian - "Issue Copy")
# Softcopy: inaunda transaction mara moja na kutuma kiungo
@login_required
@librarian_required
@require_POST
# ----------------------------------------------------------------------
# View ya Idhinisha Ombi la Kukopa — Mtunzaji anaidhinisha ombi
# ----------------------------------------------------------------------
def approve_borrow_request_view(request, request_id):
    """POST-only — protected by CSRF + librarian role decorator."""
    req = get_object_or_404(BorrowRequest, pk=request_id)
    if req.status != 'pending':
        messages.warning(request, f'Request #{request_id} is already {req.status}.')
        return redirect('all_requests')
    user = req.user

    if user.has_overdue():
        req.status = 'rejected'
        req.rejection_reason = 'User has overdue books with unpaid fines.'
        req.approved_by = request.user
        req.save()
        messages.error(request, f'Rejected: {user.username} has overdue items with unpaid fines.')
        return redirect('all_requests')

    if user.has_unpaid_fines():
        req.status = 'rejected'
        req.rejection_reason = 'User has unpaid fines.'
        req.approved_by = request.user
        req.save()
        messages.error(request, f'Rejected: {user.username} has unpaid fines.')
        return redirect('all_requests')

    max_copies = int(_pref('MAX_COPIES_PER_BORROW', 3))
    if user.active_borrows_count() >= max_copies:
        req.status = 'rejected'
        req.rejection_reason = f'User already has {max_copies} active borrows.'
        req.approved_by = request.user
        req.save()
        messages.error(request, f'Rejected: {user.username} has reached the borrow limit.')
        return redirect('all_requests')

    # ── Hardcopy: approve-only; copy assigned at physical handover ──────────
    if req.copy is None:
        req.status = 'approved'
        req.approved_by = request.user
        req.save()
        book = req.temp_book
        msg_sms = (
            f"MSICT OLMS: Your request for \"{book.title}\" has been approved. "
            f"Please come to the library to collect your book. Bring your library card or Army No."
        )
        msg_email = (
            f"Your hardcopy request for <b>\"{book.title}\"</b> has been approved.<br><br>"
            f"Please visit the library circulation desk to collect the book.<br>"
            f"Bring your <b>library card or Army No</b>."
        )
        notify_user(user, msg_sms, 'sms')
        notify_user(user, msg_email, 'email', subject='Borrow Approved — MSICT OLMS')
        log_audit(request.user, f"Approved hardcopy request for '{user.username}' – '{book.title}'", request)
        messages.success(request, f'Request approved for {user.username}. Use "Issue Copy" when they arrive.')
        return redirect('all_requests')

    # ── Softcopy: redirect to payment if fee required, else create transaction ─────────────────────────────
    copy = req.copy
    if copy.copy_type == 'hardcopy' and copy.status != 'available':
        messages.error(request, 'Hardcopy is no longer available.')
        return redirect('all_requests')

    # Softcopy payment check
    if copy.copy_type == 'softcopy' and copy.prepaid_fee > 0:
        # Mark request as approved but don't create transaction yet
        # User must complete payment first
        req.status = 'approved'
        req.approved_by = request.user
        req.save()
        messages.info(request, f'Request approved for {user.username}. User must complete payment (TZS {copy.prepaid_fee:,.0f}) to access softcopy.')
        # Notify user that request is approved and payment is required
        msg_sms = (
            f"MSICT OLMS: Your softcopy request for \"{copy.book.title}\" has been approved. "
            f"Please pay TZS {copy.prepaid_fee:,.0f} to access the book. Visit the library to complete payment."
        )
        msg_email = (
            f"Dear {user.get_full_name() or user.username},<br><br>"
            f"Your softcopy request for <b>\"{copy.book.title}\"</b> has been approved.<br>"
            f"<b>Payment Required:</b> TZS {copy.prepaid_fee:,.0f}<br>"
            f"Please visit the library circulation desk to complete payment and receive your access link."
        )
        notify_user(user, msg_sms, 'sms', message_type='softcopy_link')
        notify_user(user, msg_email, 'email', subject='Softcopy Request Approved — Payment Required', message_type='softcopy_link')
        log_audit(request.user, f"Approved softcopy request for '{user.username}' – '{book.title}' (payment required)", request)
        return redirect('all_requests')

    tx = BorrowingTransaction.objects.create(
        user=user,
        copy=copy,
        borrow_type=copy.copy_type,
        approved_by=request.user,
    )
    req.status = 'approved'
    req.approved_by = request.user
    req.save()

    librarian_name = request.user.get_full_name() or request.user.username
    _loan_days = int(_pref('LOAN_PERIOD_DAYS', 7))
    softcopy_url = request.build_absolute_uri(reverse('softcopy_access', args=[tx.access_token]))

    # Store access log for softcopy
    if copy.copy_type == 'softcopy':
        from .models import SoftcopyAccessLog
        SoftcopyAccessLog.objects.create(
            user=user,
            copy=copy,
            transaction=tx,
            access_token=str(tx.access_token),
            access_url=softcopy_url,
            expires_at=tx.due_date,
        )

    msg_sms = (
        f"MSICT OLMS: You have borrowed digital copy \"{copy.book.title}\" "
        f"from {tx.borrow_date.strftime('%d %b %Y')} to {tx.due_date.strftime('%d %b %Y')}. "
        f"Your ebook link: {softcopy_url} "
        f"Valid for {_loan_days} days. Sharing or misuse may lead to disciplinary action. "
        f"Processed by {librarian_name}."
    )
    msg_email = (
        f"Dear {user.get_full_name() or user.username},<br><br>"
        f"You have borrowed digital copy <b>\"{copy.book.title}\"</b>.<br>"
        f"<b>Borrow Date:</b> {tx.borrow_date.strftime('%d %b %Y')}<br>"
        f"<b>Due Date:</b> {tx.due_date.strftime('%d %b %Y')}<br>"
        f"<b>Access Link:</b> <a href='{softcopy_url}'>{softcopy_url}</a><br><br>"
        f"<i>Note: Your access is valid for {_loan_days} days. Sharing or misuse of digital content may lead to disciplinary action.</i><br><br>"
        f"Processed by Librarian: <b>{librarian_name}</b>"
    )
    notify_user(user, msg_sms, 'sms', message_type='softcopy_link')
    notify_user(user, msg_email, 'email', subject=f'Digital Copy Issued — {copy.book.title}', message_type='softcopy_link')
    log_audit(request.user, f"Approved softcopy for '{user.username}' – '{copy.book.title}'", request)
    messages.success(request, f'Softcopy issued to {user.username}.')
    return redirect('all_requests')


# ── Issue Copy — librarian assigns physical copy to approved hardcopy request ─
@login_required
@librarian_required
# ----------------------------------------------------------------------
# View ya Toa Nakala — Mtunzaji anatoa nakala kwa mwanachama
# ----------------------------------------------------------------------
def issue_copy_view(request, request_id):
    """GET: show Issue Copy modal page. POST: validate accession, create transaction."""
    req = get_object_or_404(
        BorrowRequest.objects.select_related('user', 'temp_book'),
        pk=request_id,
    )
    if req.status != 'approved' or req.copy_id is not None:
        messages.error(request, 'This request is not eligible for copy issuance.')
        return redirect('all_requests')

    book = req.temp_book
    if not book:
        messages.error(request, 'No book associated with this request.')
        return redirect('all_requests')

    available_copies = BookCopy.objects.filter(
        book=book, copy_type='hardcopy', status='available'
    ).order_by('accession_no')

    if request.method == 'GET':
        return render(request, 'circulation/issue_copy.html', {
            'req': req,
            'book': book,
            'available_copies': available_copies,
        })

    # ── POST: transact ───────────────────────────────────────────────────────
    accession_no = (request.POST.get('accession_no') or '').strip()
    if not accession_no:
        messages.error(request, 'Please enter an accession number.')
        return render(request, 'circulation/issue_copy.html', {
            'req': req, 'book': book, 'available_copies': available_copies,
        })

    try:
        copy = BookCopy.objects.select_related('book').get(accession_no=accession_no)
    except BookCopy.DoesNotExist:
        messages.error(request, f'No copy found with accession number "{accession_no}".')
        return render(request, 'circulation/issue_copy.html', {
            'req': req, 'book': book, 'available_copies': available_copies,
        })

    if copy.book_id != book.pk:
        messages.error(request, f'"{accession_no}" belongs to "{copy.book.title}", not "{book.title}".')
        return render(request, 'circulation/issue_copy.html', {
            'req': req, 'book': book, 'available_copies': available_copies,
        })

    if copy.status != 'available':
        messages.error(request, f'Copy "{accession_no}" is not available (status: {copy.status}).')
        return render(request, 'circulation/issue_copy.html', {
            'req': req, 'book': book, 'available_copies': available_copies,
        })

    user = req.user
    tx = BorrowingTransaction.objects.create(
        user=user,
        copy=copy,
        borrow_type='hardcopy',
        approved_by=request.user,
    )
    copy.status = 'borrowed'
    copy.save(update_fields=['status'])
    req.copy = copy
    req.save(update_fields=['copy'])
    _recalculate_reservation_expiries(book)

    # Delete the borrow request — the BorrowingTransaction now tracks this borrowing
    req.delete()

    fine_per_day = float(_pref('FINE_PER_DAY', 1000))
    lost_fine = float(getattr(book, 'lost_fine', 0) or 0)
    librarian_name = request.user.get_full_name() or request.user.username

    msg_sms = (
        f"MSICT OLMS: You have borrowed \"{book.title}\" "
        f"(Accession No: {copy.accession_no}) "
        f"from {tx.borrow_date.strftime('%d %b %Y')} to {tx.due_date.strftime('%d %b %Y')}. "
        f"If lost, fine = TZS {lost_fine:,.0f}. "
        f"Overdue fine = TZS {fine_per_day:,.0f} per day. "
        f"Processed by Librarian: {librarian_name}. Thank you."
    )
    msg_email = (
        f"Dear {user.get_full_name() or user.username},<br><br>"
        f"You have borrowed <b>\"{book.title}\"</b>.<br>"
        f"<b>Accession No:</b> {copy.accession_no}<br>"
        f"<b>Shelf:</b> {copy.shelf_location or '—'}<br>"
        f"<b>Borrow Date:</b> {tx.borrow_date.strftime('%d %b %Y')}<br>"
        f"<b>Due Date:</b> {tx.due_date.strftime('%d %b %Y')}<br><br>"
        f"<b>Lost Fine:</b> TZS {lost_fine:,.0f}<br>"
        f"<b>Overdue Fine:</b> TZS {fine_per_day:,.0f} per day<br><br>"
        f"Please return the book by the due date.<br>"
        f"Processed by Librarian: <b>{librarian_name}</b>"
    )
    notify_user(user, msg_sms, 'sms')
    notify_user(user, msg_email, 'email', subject=f'Book Issued — {book.title} — MSICT OLMS')
    log_audit(request.user,
              f"Issued '{copy.accession_no}' ({book.title}) to {user.username} — TX#{tx.pk}",
              request)
    messages.success(
        request,
        f'"{copy.accession_no}" issued to {user.username}. Due: {tx.due_date.strftime("%d %b %Y")}.'
    )
    return redirect('all_requests')


# ── Copy autocomplete (AJAX) — returns available hardcopies for a book ────────
@login_required
@librarian_required
# ----------------------------------------------------------------------
# View ya Tafuta Nakala — Mtunzaji anatafuta nakala kwa accession number
# ----------------------------------------------------------------------
def copy_lookup_view(request):
    from django.http import JsonResponse
    book_id = request.GET.get('book_id', '')
    q = (request.GET.get('q') or '').strip()
    qs = BookCopy.objects.filter(book_id=book_id, copy_type='hardcopy', status='available')
    if q:
        qs = qs.filter(accession_no__icontains=q)
    data = [{'accession_no': c.accession_no, 'shelf': c.shelf_location or '—'} for c in qs[:15]]
    return JsonResponse({'copies': data})


# Kataa ombi la kukopa — inahitaji sababu ya kukataa
# Mwanachama anapata arifa ya SMS na barua pepe
@login_required
@librarian_required
@require_POST
# ----------------------------------------------------------------------
# View ya Kataa Ombi la Kukopa — Mtunzaji anakataa ombi
# ----------------------------------------------------------------------
def reject_borrow_request_view(request, request_id):
    """POST-only — protected by CSRF + librarian role decorator."""
    req = get_object_or_404(BorrowRequest, pk=request_id, status='pending')
    reason = request.POST.get('rejection_reason', 'Rejected by librarian.')
    req.status = 'rejected'
    req.rejection_reason = reason
    req.approved_by = request.user
    req.save()

    msg = f"MSICT OLMS: Your borrow request for '{req.book.title}' was rejected. Reason: {reason}"
    notify_user(req.user, msg, 'sms')
    notify_user(req.user, msg, 'email', subject='Borrow Request Rejected')
    log_audit(request.user, f"Rejected borrow request for '{req.user.username}' – '{req.book.title}'", request)
    messages.warning(request, f'Request rejected for {req.user.username}.')
    return redirect('librarian_dashboard')


# Ongeza muda wa mkopo (renew) — kwa mwanachama tu
# Kwa softcopy: inaweza kufanywa wakati wowote ndani ya muda
# Kwa hardcopy: haiwezekani kama kuna uhifadhi au ni overdue
@login_required
@require_POST
# ----------------------------------------------------------------------
# View ya Ongeza Muda wa Mkopo — Mwanachama anahitaji upya mkopo
# ----------------------------------------------------------------------
def renew_transaction_view(request, transaction_id):
    """POST-only — prevents CSRF-style attacks via image tags or malicious links."""
    tx = get_object_or_404(BorrowingTransaction, pk=transaction_id, user=request.user)

    # ── Softcopy: ALWAYS redirect to renewal payment page ──
    # Payment page handles both paid (fee > 0) and free (fee == 0) renewals.
    # Hardcopy renewal logic stays unchanged (direct renew below).
    if tx.copy.copy_type == 'softcopy' and tx.borrow_type == 'softcopy':
        return redirect('softcopy_renewal_payment', transaction_id=tx.pk)

    # ── Hardcopy: renew directly (unchanged) ──
    success, message = tx.renew()
    if success:
        msg = f"MSICT OLMS: '{tx.copy.book.title}' renewed. New due date: {tx.due_date.date()}"
        notify_user(request.user, msg, 'sms')
        notify_user(request.user, msg, 'email', subject='Renewal Confirmation')
        log_audit(request.user, f"Renewed '{tx.copy.book.title}'. New due: {tx.due_date.date()}", request)
        messages.success(request, f'Renewed successfully. New due date: {tx.due_date.date()}')
    else:
        messages.error(request, message)
    return redirect('member_msict_borrowings')


# Rudisha softcopy mapema kabla ya muda haujaisha
@login_required
@require_POST
# ----------------------------------------------------------------------
# View ya Rudisha Mapema — Mwanachama anarudisha softcopy mapema
# ----------------------------------------------------------------------
def return_early_view(request, transaction_id):
    """POST-only — prevents CSRF-style attacks via image tags or malicious links."""
    tx = get_object_or_404(
        BorrowingTransaction, pk=transaction_id,
        user=request.user, status='borrowed'
    )
    if tx.copy.copy_type != 'softcopy':
        messages.error(request, 'Only soft copies can be returned online. Bring hardcopies to the desk.')
        return redirect('member_dashboard')
    
    # Special softcopy expiry logic: check if link is expired
    if tx.copy.access_type == 'borrow' and tx.is_link_expired:
        # Link expired - check if fine is paid
        if tx.has_unpaid_fine:
            # Fine not paid - block return
            messages.error(
                request,
                f'Your access to "{tx.copy.book.title}" expired on {tx.due_date.strftime("%d %b %Y")}. '
                f'Outstanding fine: TZS {tx.total_fine_remaining:,.0f}. '
                f'Please pay the fine at the circulation desk before returning this book.'
            )
            return redirect('member_msict_borrowings')
        # Fine paid - allow return to complete
    
    # Regular return process (non-expired or fine paid)
    tx.return_date = timezone.now()
    tx.status = 'returned'
    tx.save(update_fields=['return_date', 'status'])
    tx.copy.status = 'available'
    tx.copy.save(update_fields=['status'])
    msg = (
        f"MSICT OLMS: Your softcopy access for '{tx.copy.book.title}' has been returned. "
        f"Your read link has been removed from your dashboard. Thank you!"
    )
    notify_user(request.user, msg, 'sms')
    notify_user(request.user, msg, 'email', subject='Softcopy Returned – MSICT OLMS')
    log_audit(request.user, f"Member returned softcopy: '{tx.copy.book.title}'", request)
    messages.success(request, f'"{tx.copy.book.title}" access returned. Read link removed.')
    return redirect('member_dashboard')


# ── Desk return helper ───────────────────────────────────────────────────────
# ----------------------------------------------------------------------
# Msaidizi wa Kusudia Kurudisha — Anatumia kurudisha kutoka desk ya mtunzaji
# ----------------------------------------------------------------------
def _process_desk_return(request, copy_pk_str):
    """Process a single copy return from the librarian desk (hard or soft).
    Supports optional damage marking via POST params:
      mark_damaged=1, damage_type, damage_description
    Returns the BorrowingTransaction on success, None on failure."""
    try:
        copy = BookCopy.objects.select_related('book').get(pk=int(copy_pk_str))
    except (BookCopy.DoesNotExist, ValueError):
        messages.error(request, 'Copy not found.')
        return None

    tx = BorrowingTransaction.objects.filter(
        copy=copy, status__in=['borrowed', 'overdue']
    ).select_related('user').first()
    if not tx:
        messages.error(request, f'No active borrowing found for "{copy.accession_no}".')
        return None

    # ── Block return if there is an unpaid fine on this transaction ──────────
    unpaid_fine = Fine.objects.filter(transaction=tx, paid=False).first()
    if unpaid_fine:
        remaining = unpaid_fine.remaining_balance
        messages.error(
            request,
            f'⚠️ Cannot return "{copy.book.title}" — unpaid fine of '
            f'TZS {remaining:,.0f} must be settled first. '
            f'Direct the member to the payment desk.'
        )
        return None

    # Check if librarian marked this book as damaged
    mark_damaged = request.POST.get('mark_damaged', '') == '1'
    damage_type = request.POST.get('damage_type', '').strip()
    damage_description = request.POST.get('damage_description', '').strip()

    # Damage is discovered and reported at return time — both events are simultaneous.
    # Rule: if returned/damaged AFTER due date → both damage + overdue fine.
    #        if returned/damaged BEFORE due date → only damage fine.
    report_time = timezone.now()
    days_late = 0
    if tx.status in ('borrowed', 'overdue') and report_time > tx.due_date:
        days_late = max(1, (report_time - tx.due_date).days)

    tx.return_date = report_time
    tx.status      = 'returned'
    tx.save(update_fields=['return_date', 'status'])

    # Set copy status: 'damaged' if marked, otherwise 'available'
    if copy.copy_type == 'hardcopy':
        if mark_damaged:
            copy.status = 'damaged'
        else:
            copy.status = 'available'
        copy.save(update_fields=['status'])

    # ── Handle overdue fine ──────────────────────────────────────────────
    fine_per_day = float(_pref('FINE_PER_DAY', 1000))
    overdue_fine = None
    if days_late > 0:
        fine_amount = days_late * fine_per_day
        existing_fine = Fine.objects.filter(
            transaction=tx, reason__icontains='Overdue'
        ).first()
        if existing_fine and not existing_fine.paid:
            existing_fine.amount = fine_amount
            existing_fine.reason = f"Overdue fine for '{copy.book.title}' ({days_late} days)"
            existing_fine.save(update_fields=['amount', 'reason'])
            overdue_fine = existing_fine
        elif not existing_fine:
            overdue_fine = Fine.objects.create(
                user=tx.user, transaction=tx, amount=fine_amount,
                reason=f"Overdue fine for '{copy.book.title}' ({days_late} days)",
            )
        messages.warning(request, f'Overdue fine of TZS {fine_amount:,.0f} raised ({days_late} days).')

    # ── Handle damage fine ───────────────────────────────────────────────
    damage_fine = None
    if mark_damaged and copy.copy_type == 'hardcopy':
        # Damage fine = book's lost_fine amount
        damage_amount = Decimal(str(copy.book.lost_fine or 0))
        if damage_amount > 0:
            damage_fine = Fine.objects.create(
                user=tx.user,
                transaction=tx,
                amount=damage_amount,
                reason=f"Damage fine – '{copy.book.title}' (Acc: {copy.accession_no}) – {damage_type}",
                paid=False,
            )

        # Create DamageReport
        dr = DamageReport.objects.create(
            transaction=tx,
            user=tx.user,
            damage_type=damage_type or 'other',
            damage_description=damage_description,
            reported_by=request.user,
            status='confirmed',
            damage_fine=damage_fine,
        )

        # Notify member about damage
        total_fines = Decimal(str(damage_amount))
        if overdue_fine:
            total_fines += overdue_fine.amount
        due_str = tx.due_date.strftime('%d %b %Y')
        dmg_msg = (
            f"MSICT OLMS: DAMAGE REPORTED for '{copy.book.title}' (DR-{dr.pk}). "
            f"Damage type: {dr.get_damage_type_display()}. "
        )
        if damage_fine:
            dmg_msg += f"Damage fine: TZS {damage_amount:,.0f}. "
        if overdue_fine:
            dmg_msg += (
                f"Your loan expired on {due_str} and the book was returned {days_late} day(s) late, "
                f"so an Overdue fine of TZS {overdue_fine.amount:,.0f} also applies. "
            )
        elif damage_fine:
            dmg_msg += f"Returned within loan period (due: {due_str}) — no overdue fine applies. "
        if damage_fine or overdue_fine:
            dmg_msg += f"Total outstanding: TZS {total_fines:,.0f}. Please pay at the library or online."
        notify_user(tx.user, dmg_msg, 'sms', message_type='damage_fine', priority='high')
        notify_user(tx.user, dmg_msg, 'email', subject='Damage Report – MSICT OLMS',
                     message_type='damage_fine', priority='high')

        flash = f'"{copy.book.title}" returned — DAMAGED ({dr.get_damage_type_display()}). Copy marked damaged.'
        if damage_fine:
            flash += f' Damage fine TZS {damage_amount:,.0f}.'
        if overdue_fine:
            flash += f' Overdue fine TZS {overdue_fine.amount:,.0f}.'
        messages.warning(request, flash)
        log_audit(request.user,
                  f"Marked damaged: {copy.accession_no} – '{copy.book.title}' (DR-{dr.pk})",
                  request)
    elif overdue_fine:
        fine_msg = (
            f"MSICT OLMS: Overdue fine of TZS {overdue_fine.amount:,.0f} for '{copy.book.title}'. "
            f"Please pay at the library counter."
        )
        notify_user(tx.user, fine_msg, 'sms')
        notify_user(tx.user, fine_msg, 'email', subject='Overdue Fine Notice – MSICT OLMS')
        messages.warning(request, f'"{copy.book.title}" returned — overdue fine of TZS {overdue_fine.amount:,.0f} raised.')
    elif days_late > 0:
        messages.success(request, f'"{copy.book.title}" returned — overdue by {days_late} day(s), fine already paid.')
    else:
        messages.success(request, f'"{copy.book.title}" returned successfully.')

    librarian_name = request.user.get_full_name() or request.user.username
    if copy.copy_type == 'hardcopy':
        ret_msg = (
            f"MSICT OLMS: '{copy.book.title}' (Hardcopy) returned successfully. "
            f"Processed by {librarian_name}. Thank you!"
        )
    else:
        ret_msg = (
            f"MSICT OLMS: Your softcopy access for '{copy.book.title}' has been returned "
            f"by the librarian. Your read link has been removed from your dashboard."
        )
    notify_user(tx.user, ret_msg, 'sms')
    notify_user(tx.user, ret_msg, 'email', subject='Book Returned – MSICT OLMS')

    if not mark_damaged:
        _notify_next_reservation(copy.book, request)
    log_audit(request.user,
              f"Returned {copy.copy_type} '{copy.accession_no}' – '{copy.book.title}'",
              request)
    return tx


# ----------------------------------------------------------------------
# Msaidizi wa Kurudisha za Hivi Karibuni — Anarudisha mikopo 30 ya hivi karibuni
# ----------------------------------------------------------------------
def _get_recent_returns():
    """Return the last 30 returned/softcopy-returned transactions for the return desk."""
    return (
        BorrowingTransaction.objects.filter(status='returned')
        .select_related('user', 'copy__book', 'approved_by')
        .order_by('-return_date')[:30]
    )


# Kama kuna uhifadhi — inatuma arifa kwa mwanachama wa kwanza kwenye foleni
@login_required
@librarian_required
# ----------------------------------------------------------------------
# View ya Rudisha Hardcopy — Mtunzaji anarudisha hardcopy
# ----------------------------------------------------------------------
def return_hardcopy_view(request):
    if request.method == 'POST':
        search_input   = request.POST.get('barcode', '').strip()
        card_input     = request.POST.get('card_no', '').strip()
        copy_pk        = request.POST.get('copy_pk', '').strip()
        return_card_no = request.POST.get('return_card_no', '').strip()
        damage_action  = request.POST.get('damage_action', '').strip()

        # ── Branch 0: Damaged return — create report + fine, redirect to payment ──
        # The book is NOT returned yet. After payment completes, the transaction
        # is marked as returned.
        if copy_pk and damage_action == 'create_damage':
            try:
                copy = BookCopy.objects.select_related('book').get(pk=int(copy_pk))
            except (BookCopy.DoesNotExist, ValueError):
                messages.error(request, 'Copy not found.')
                return render(request, 'circulation/return_desk.html', {'recent_returns': _get_recent_returns()})

            tx = BorrowingTransaction.objects.filter(
                copy=copy, status__in=['borrowed', 'overdue']
            ).select_related('user').first()
            if not tx:
                messages.error(request, f'No active borrowing found for "{copy.accession_no}".')
                return render(request, 'circulation/return_desk.html', {'recent_returns': _get_recent_returns()})

            damage_type = request.POST.get('damage_type', '').strip()
            damage_description = request.POST.get('damage_description', '').strip()

            if not damage_type:
                messages.error(request, 'Please select a damage type.')
                return render(request, 'circulation/return_desk.html', {
                    'lookup_tx': tx,
                    'barcode_input': search_input or copy.accession_no,
                    'recent_returns': _get_recent_returns(),
                })

            # Calculate overdue days BEFORE any changes
            days_late = 0
            if tx.status in ('borrowed', 'overdue') and timezone.now() > tx.due_date:
                days_late = max(1, (timezone.now() - tx.due_date).days)

            # Create overdue fine if applicable
            overdue_fine = None
            if days_late > 0:
                fine_per_day = float(_pref('FINE_PER_DAY', 1000))
                fine_amount = days_late * fine_per_day
                existing_fine = Fine.objects.filter(
                    transaction=tx, reason__icontains='Overdue'
                ).first()
                if existing_fine and not existing_fine.paid:
                    existing_fine.amount = fine_amount
                    existing_fine.reason = f"Overdue fine for '{copy.book.title}' ({days_late} days)"
                    existing_fine.save(update_fields=['amount', 'reason'])
                    overdue_fine = existing_fine
                elif not existing_fine:
                    overdue_fine = Fine.objects.create(
                        user=tx.user, transaction=tx, amount=fine_amount,
                        reason=f"Overdue fine for '{copy.book.title}' ({days_late} days)",
                    )

            # Create damage fine
            damage_amount = Decimal(str(copy.book.lost_fine or 0))
            damage_fine = None
            if damage_amount > 0:
                damage_fine = Fine.objects.create(
                    user=tx.user,
                    transaction=tx,
                    amount=damage_amount,
                    reason=f"Damage fine – '{copy.book.title}' (Acc: {copy.accession_no}) – {damage_type}",
                    paid=False,
                )

            # Create DamageReport (status=confirmed, awaiting payment)
            dr = DamageReport.objects.create(
                transaction=tx,
                user=tx.user,
                damage_type=damage_type,
                damage_description=damage_description,
                reported_by=request.user,
                status='confirmed',
                damage_fine=damage_fine,
            )

            # Mark copy as damaged
            if copy.copy_type == 'hardcopy':
                copy.status = 'damaged'
                copy.save(update_fields=['status'])

            # Notify member
            total_fines = Decimal(str(damage_amount))
            if overdue_fine:
                total_fines += overdue_fine.amount
            due_str_b0 = tx.due_date.strftime('%d %b %Y')
            dmg_msg = (
                f"MSICT OLMS: DAMAGE REPORTED for '{copy.book.title}' (DR-{dr.pk}). "
                f"Damage type: {dr.get_damage_type_display()}. "
            )
            if damage_fine:
                dmg_msg += f"Damage fine: TZS {damage_amount:,.0f}. "
            if overdue_fine:
                dmg_msg += (
                    f"Your loan expired on {due_str_b0} and the book was returned {days_late} day(s) late, "
                    f"so an Overdue fine of TZS {overdue_fine.amount:,.0f} also applies. "
                )
            elif damage_fine:
                dmg_msg += f"Returned within loan period (due: {due_str_b0}) — no overdue fine applies. "
            if damage_fine or overdue_fine:
                dmg_msg += f"Total outstanding: TZS {total_fines:,.0f}. Please pay at the library to complete the return."
            notify_user(tx.user, dmg_msg, 'sms', message_type='damage_fine', priority='high')
            notify_user(tx.user, dmg_msg, 'email', subject='Damage Report – Payment Required',
                         message_type='damage_fine', priority='high')

            log_audit(request.user,
                      f"Marked damaged (pending payment): {copy.accession_no} – '{copy.book.title}' (DR-{dr.pk})",
                      request)

            if damage_fine or overdue_fine:
                messages.warning(request,
                    f'Damage report DR-{dr.pk} created. Total fines: TZS {total_fines:,.0f}. '
                    f'Book will be returned after payment is completed.')
                return redirect('record_damage_fine_payment', report_id=dr.pk)
            else:
                # No fine — complete the return immediately
                tx.return_date = timezone.now()
                tx.status = 'returned'
                tx.save(update_fields=['return_date', 'status'])
                messages.success(request, f'"{copy.book.title}" returned — damaged (no fine). DR-{dr.pk}.')
                return redirect('return_desk')

        # ── Branch 1: Per-row Return from card-lookup table ───────────────────
        # Process the return, then re-run card lookup to show updated borrows.
        if copy_pk:
            _process_desk_return(request, copy_pk)
            card_input = return_card_no  # fall through to card lookup

        # ── Branch 2: Card-number lookup (shows ALL active copies) ────────────
        if card_input:
            from accounts.models import VirtualCard
            try:
                vc = VirtualCard.objects.select_related('user').get(card_no=card_input)
                member = vc.user
                member_borrows = BorrowingTransaction.objects.filter(
                    user=member,
                    status__in=['borrowed', 'overdue'],
                ).select_related('copy__book').order_by('due_date')
                
                # Get all unpaid fines for this member
                unpaid_fines = Fine.objects.filter(user=member, paid=False)
                has_unpaid_fines = unpaid_fines.exists()
                
                # Create a dictionary of transaction_id -> fine information
                tx_fines = {}
                for tx in member_borrows:
                    tx_fine = unpaid_fines.filter(transaction=tx).first()
                    tx_fines[tx.id] = {
                        'fine': tx_fine,
                        'amount': tx_fine.amount if tx_fine else 0,
                        'remaining': tx_fine.remaining_balance if tx_fine else 0,
                    }
                
                return render(request, 'circulation/return_desk.html', {
                    'member':        member,
                    'member_borrows': member_borrows,
                    'card_input':    card_input,
                    'recent_returns': _get_recent_returns(),
                    'has_unpaid_fines': has_unpaid_fines,
                    'tx_fines': tx_fines,
                })
            except VirtualCard.DoesNotExist:
                messages.error(request, f'No library card found with Card No "{card_input}".')
            return render(request, 'circulation/return_desk.html', {'recent_returns': _get_recent_returns()})

        # ── Branch 3: Barcode / accession-number – lookup first, then confirm ──
        if search_input:
            try:
                try:
                    copy = BookCopy.objects.select_related('book').get(
                        barcode=search_input, copy_type='hardcopy')
                except BookCopy.DoesNotExist:
                    copy = BookCopy.objects.select_related('book').get(
                        accession_no=search_input, copy_type='hardcopy')

                lookup_tx = BorrowingTransaction.objects.filter(
                    copy=copy, status__in=['borrowed', 'overdue']
                ).select_related('user', 'copy__book').first()

                if not lookup_tx:
                    messages.error(
                        request,
                        f'No active borrowing for "{search_input}". '
                        f'The copy may already be returned or available.'
                    )
                else:
                    # Fetch unpaid fine for this transaction (same logic as card lookup)
                    lookup_tx_fine = Fine.objects.filter(
                        transaction=lookup_tx, paid=False
                    ).first()
                    lookup_tx_has_unpaid_fine = lookup_tx_fine is not None and lookup_tx_fine.remaining_balance > 0

                    return render(request, 'circulation/return_desk.html', {
                        'lookup_tx':                  lookup_tx,
                        'barcode_input':              search_input,
                        'recent_returns':             _get_recent_returns(),
                        'lookup_tx_fine':             lookup_tx_fine,
                        'lookup_tx_has_unpaid_fine':  lookup_tx_has_unpaid_fine,
                    })
            except BookCopy.DoesNotExist:
                messages.error(request, f'Hardcopy not found: "{search_input}". Check barcode or accession number.')

    return render(request, 'circulation/return_desk.html', {'recent_returns': _get_recent_returns()})


# ============================================================
# RESERVATION HELPER — recalculate position-based expiry dates
# expires_at = nearest_borrowed_due_date + (position × RESERVATION_WINDOW_DAYS)
# If no active borrows, base = now(). Notified users keep min 24 h.
# ============================================================
# ----------------------------------------------------------------------
# Msaidizi wa Kuhesabu Uhifadhi — Anahesabu muda wa uhifadhi upya
# ----------------------------------------------------------------------
def _recalculate_reservation_expiries(book):
    window = int(_pref('RESERVATION_WINDOW_DAYS', 7))
    nearest_tx = BorrowingTransaction.objects.filter(
        copy__book=book, copy__copy_type='hardcopy',
        status__in=['borrowed', 'overdue']
    ).order_by('due_date').first()
    base = nearest_tx.due_date if nearest_tx else timezone.now()
    for res in Reservation.objects.filter(
        book=book, status__in=['pending', 'notified']
    ).order_by('position'):
        new_exp = base + timedelta(days=res.position * window)
        if res.status == 'notified' and res.notified_at:
            new_exp = max(new_exp, res.notified_at + timedelta(hours=24))
        res.expires_at = new_exp
        res.save(update_fields=['expires_at'])


# ============================================================
# RESERVATION HELPER — auto-expire + skip stale notified users
# Sets had_notified_skip=True when a 'notified' user misses 24 h.
# At the end, auto-notifies the next member if a copy is available.
# ============================================================
# ----------------------------------------------------------------------
# Msaidizi wa Kusudia Uhifadhi — Anasudia uhifadhi uliopita muda
# ----------------------------------------------------------------------
def _process_reservation_expiry(book):
    """Mark expired reservations, skip notified users who waited > 24 h, re-queue."""
    had_notified_skip = False
    active = Reservation.objects.filter(
        book=book, status__in=['pending', 'notified']
    ).order_by('position')
    for res in active:
        # Expire if past position-based deadline
        if timezone.now() > res.expires_at:
            res.status = 'expired'
            res.save(update_fields=['status'])
            exp_msg = (
                f"MSICT OLMS: Your reservation for '{book.title}' has expired "
                f"(deadline {res.expires_at.strftime('%d %b %Y')} passed). Queue position released."
            )
            notify_user(res.user, exp_msg, 'sms')
            notify_user(res.user, exp_msg, 'email', subject='Reservation Expired')
            continue
        # Skip notified user who did not request borrow within 24 hours
        if res.status == 'notified' and res.notified_at:
            hours_waited = (timezone.now() - res.notified_at).total_seconds() / 3600
            if hours_waited > 24:
                res.status = 'expired'
                res.save(update_fields=['status'])
                had_notified_skip = True
                skip_msg = (
                    f"MSICT OLMS: Your turn for '{book.title}' was SKIPPED — "
                    f"you did not request borrow within 24 hours. "
                    f"The next member in queue has been notified. Your reservation is closed."
                )
                notify_user(res.user, skip_msg, 'sms')
                notify_user(res.user, skip_msg, 'email', subject='Queue Position Skipped')

    # Re-number remaining active queue (FIFO integrity)
    remaining = Reservation.objects.filter(
        book=book, status__in=['pending', 'notified']
    ).order_by('created_at')
    for idx, res in enumerate(remaining, start=1):
        if res.position != idx:
            res.position = idx
            res.save(update_fields=['position'])
    # Recalculate position-based expiry for every remaining member
    _recalculate_reservation_expiries(book)

    # A notified user was skipped — auto-notify next member if a copy is available
    if had_notified_skip:
        _notify_next_in_queue(book, reason='skip')


# ============================================================
# RESERVATION HELPER — core notify logic (no expiry processing)
# reason='return' → triggered by desk return
# reason='skip'   → triggered by 24-h timeout skip
# Guards against over-notifying: available_copies > notified_count
# ============================================================
# ----------------------------------------------------------------------
# Msaidizi wa Kuambia Mwanachama wa Kwanza — Anamwambia mwanachama wa kwanza foleni
# ----------------------------------------------------------------------
def _notify_next_in_queue(book, reason='return'):
    """Notify the next PENDING member if unmatched available copies exist."""
    available = book.copies.filter(copy_type='hardcopy', status='available').count()
    already_notified = Reservation.objects.filter(book=book, status='notified').count()
    if available <= already_notified:
        return  # Every available copy is already claimed by a notified user

    queue = list(
        Reservation.objects.filter(
            book=book, status__in=['pending', 'notified']
        ).order_by('position')
    )
    if not queue:
        return

    total_in_queue = len(queue)
    next_res = next((r for r in queue if r.status == 'pending'), None)
    if not next_res:
        return

    nearest_return = BorrowingTransaction.objects.filter(
        copy__book=book, copy__copy_type='hardcopy',
        status__in=['borrowed', 'overdue']
    ).order_by('due_date').first()

    # ── Notify first pending user ───────────────────────────────
    next_res.status = 'notified'
    next_res.notified_at = timezone.now()
    next_res.expires_at = max(next_res.expires_at, timezone.now() + timedelta(hours=24))
    next_res.save(update_fields=['status', 'notified_at', 'expires_at'])

    if reason == 'skip':
        first_msg = (
            f"MSICT OLMS: It's YOUR TURN for '{book.title}'! "
            f"The previous member was skipped (missed 24-hour window). "
            f"You are now #1 of {total_in_queue} in queue. "
            f"Log in and click 'Request Borrow' within 24 hours "
            f"(deadline: {next_res.expires_at.strftime('%d %b %Y %H:%M')})."
        )
        broad_event = "The previous member was skipped"
    else:
        first_msg = (
            f"MSICT OLMS: It's YOUR TURN! A hardcopy of '{book.title}' is now available. "
            f"You are #1 of {total_in_queue} in queue. "
            f"Log in and click 'Request Borrow' within 24 hours "
            f"(deadline: {next_res.expires_at.strftime('%d %b %Y %H:%M')}). "
            f"Then wait for librarian approval."
        )
        broad_event = "A hardcopy was returned"

    notify_user(next_res.user, first_msg, 'sms')
    notify_user(next_res.user, first_msg, 'email', subject=f'Your Turn: {book.title}')

    # ── Broadcast to ALL other waiting members ──────────────────
    for res in queue:
        if res.pk == next_res.pk:
            continue
        ahead = res.position - 1
        ahead_word = 'member' if ahead == 1 else 'members'
        est_info = ''
        if nearest_return:
            est_info = f" Nearest expected return: {nearest_return.due_date.strftime('%d %b %Y')}."
        broad_msg = (
            f"MSICT OLMS: Queue update for '{book.title}'. "
            f"{broad_event} — member #1 in queue has been notified to borrow. "
            f"Your position: #{res.position} ({ahead} {ahead_word} ahead, {total_in_queue} total). "
            f"Your reservation deadline: {res.expires_at.strftime('%d %b %Y')}.{est_info}"
        )
        notify_user(res.user, broad_msg, 'sms')
        notify_user(res.user, broad_msg, 'email', subject=f'Queue Update: {book.title}')


# ============================================================
# RESERVATION HELPER — entry point called after a book is returned
# ============================================================
# ----------------------------------------------------------------------
# Msaidizi wa Kuambia Uhifadhi Ujao — Anamwambia mwanachama wa uhifadhi ujao
# ----------------------------------------------------------------------
def _notify_next_reservation(book, request=None):
    """Called after a hardcopy is returned at the desk.
    1. Process expiry/skips (may auto-notify if a skip occurs + copy available).
    2. Then notify next member for this return event.
    """
    _process_reservation_expiry(book)
    _notify_next_in_queue(book, reason='return')


# ============================================================
# RESERVE HARDCOPY — FIFO queue for physical book copies
# Eligibility: all hardcopies borrowed/reserved, no overdue, no unpaid fines
# ============================================================
@login_required
# ----------------------------------------------------------------------
# View ya Hifadhi Kitabu — Mwanachama anahifadhi nafasi kwa kitabu
# ----------------------------------------------------------------------
def reserve_book_view(request, book_id):
    guard = _ensure_member_borrower(request)
    if guard:
        return guard

    book = get_object_or_404(Book, pk=book_id)

    # Only hardcopy books support reservation; damaged/lost copies cannot be reserved
    hardcopies = book.copies.filter(copy_type='hardcopy').exclude(status__in=['lost', 'damaged'])
    if not hardcopies.exists():
        messages.info(request, 'This book has no borrowable hardcopy. Damaged or lost copies cannot be reserved.')
        return redirect('book_detail_public', book_id=book_id)

    # Check if any hardcopy is still available — no reservation needed
    available = hardcopies.filter(status='available').exists()
    if available:
        messages.info(request, 'A hardcopy is currently available. You can borrow it directly.')
        return redirect('borrow_catalog')

    # Eligibility checks
    if request.user.has_overdue():
        messages.error(request, 'You have overdue books. Clear them before reserving.')
        return redirect('member_dashboard')
    if request.user.has_unpaid_fines():
        messages.error(request, 'You have unpaid fines. Pay at the desk before reserving.')
        return redirect('member_dashboard')

    # Prevent duplicate reservation
    if Reservation.objects.filter(
        user=request.user, book=book, status__in=['pending', 'notified']
    ).exists():
        messages.warning(request, 'You already have an active reservation for this book.')
        return redirect('my_reservations')

    # Create reservation — position auto-assigned in model.save()
    # expires_at placeholder set by model; corrected immediately below
    reservation = Reservation.objects.create(
        user=request.user,
        book=book,
    )
    # Set position-based expiry: nearest_due_date + (position × 7 days)
    _recalculate_reservation_expiries(book)
    reservation.refresh_from_db()

    # Build notification: nearest due date + queue position + actual expiry
    active_borrows = BorrowingTransaction.objects.filter(
        copy__book=book, copy__copy_type='hardcopy',
        status__in=['borrowed', 'overdue']
    ).order_by('due_date')
    nearest = active_borrows.first()
    total_queue = Reservation.objects.filter(
        book=book, status__in=['pending', 'notified']
    ).count()
    ahead_count = reservation.position - 1
    ahead_word = 'member' if ahead_count == 1 else 'members'
    exp_date = reservation.expires_at.strftime('%d %b %Y')

    est_info = ''
    if nearest:
        est_info = f" Nearest expected return: {nearest.due_date.strftime('%d %b %Y')}."

    if reservation.position == 1:
        msg = (
            f"MSICT OLMS: You are #1 in queue for '{book.title}'."
            f" You will be notified as soon as a hardcopy is returned."
            f"{est_info} Your reservation deadline: {exp_date}."
        )
    else:
        msg = (
            f"MSICT OLMS: You reserved '{book.title}'. Queue position: #{reservation.position}."
            f" {ahead_count} {ahead_word} ahead of you. Total in queue: {total_queue}."
            f"{est_info} Your reservation deadline: {exp_date}. You will be notified when it's your turn."
        )

    notify_user(request.user, msg, 'sms')
    notify_user(request.user, msg, 'email', subject='Book Reserved — Queue Confirmed')
    log_audit(request.user, f"Reserved hardcopy '{book.title}' (position #{reservation.position})", request)
    messages.success(request, f'Reserved "{book.title}". Position #{reservation.position} in queue. Deadline: {exp_date}.')
    return redirect('my_reservations')


# ============================================================
# CANCEL RESERVATION — member cancels their own active reservation
# Queue positions re-numbered automatically
# ============================================================
@login_required
@require_POST
# ----------------------------------------------------------------------
# View ya Futa Uhifadhi — Mwanachama anafuta uhifadhi wake
# ----------------------------------------------------------------------
def cancel_reservation_view(request, reservation_id):
    """POST-only — prevents CSRF-style attacks via image tags or malicious links."""
    res = get_object_or_404(
        Reservation, pk=reservation_id, user=request.user,
        status__in=['pending', 'notified']
    )
    book = res.book
    res.status = 'cancelled'
    res.save(update_fields=['status'])

    msg = f"MSICT OLMS: Your reservation for '{book.title}' has been cancelled. Queue updated."
    notify_user(request.user, msg, 'sms')
    notify_user(request.user, msg, 'email', subject='Reservation Cancelled')
    log_audit(request.user, f"Cancelled reservation for '{book.title}'", request)

    # Re-number queue and notify next user if the cancelled user was first
    _process_reservation_expiry(book)
    messages.success(request, f'Reservation for "{book.title}" cancelled. Queue updated.')
    return redirect('my_reservations')


# ============================================================
# LIBRARIAN — Cancel any reservation
# ============================================================
@login_required
@librarian_required
@require_POST
# ----------------------------------------------------------------------
# View ya Mtunzaji Afute Uhifadhi — Mtunzaji anafuta uhifadhi
# ----------------------------------------------------------------------
def librarian_cancel_reservation_view(request, reservation_id):
    """POST-only — protected by CSRF + librarian role decorator."""
    res = get_object_or_404(Reservation, pk=reservation_id, status__in=['pending', 'notified'])
    reason = request.POST.get('reason', '').strip()
    if not reason:
        messages.error(request, 'A reason is required to cancel a reservation.')
        return redirect('reservation_list')
    book = res.book
    res.status = 'cancelled'
    res.save(update_fields=['status'])
    msg = (f"MSICT OLMS: Your reservation for '{book.title}' has been cancelled by the librarian. "
           f"Reason: {reason}")
    notify_user(res.user, msg, 'sms')
    notify_user(res.user, msg, 'email', subject='Reservation Cancelled')
    log_audit(request.user, f"Cancelled reservation #{res.pk} for '{res.user.username}' — '{book.title}'. Reason: {reason}", request)
    _process_reservation_expiry(book)
    messages.success(request, f'Reservation for {res.user.username} cancelled and user notified.')
    return redirect('reservation_list')


# ============================================================
# QUEUE BORROW — notified user clicks "Borrow Now" for a hardcopy
# Creates a BorrowRequest for the first available hardcopy
# Marks reservation as fulfilled
# ============================================================
@login_required
# ----------------------------------------------------------------------
# View ya Kukopa kutoka Foleni — Mwanachama anatoka foleni kukopa
# ----------------------------------------------------------------------
def softcopy_queue_borrow_view(request, reservation_id):
    res = get_object_or_404(
        Reservation, pk=reservation_id, user=request.user, status='notified'
    )
    book = res.book

    # Eligibility re-check
    if request.user.has_overdue():
        messages.error(request, 'You have overdue books. Return them before borrowing.')
        return redirect('my_reservations')
    if request.user.has_unpaid_fines():
        messages.error(request, 'You have unpaid fines. Pay them before borrowing.')
        return redirect('my_reservations')

    # Check 24-hour window has not expired
    if res.notified_at and (timezone.now() - res.notified_at).total_seconds() > 86400:
        res.status = 'expired'
        res.save(update_fields=['status'])
        _process_reservation_expiry(book)
        messages.error(request, 'Your 24-hour borrow window has expired. Queue updated.')
        return redirect('my_reservations')

    # Find an available hardcopy to assign
    copy = book.copies.filter(
        copy_type='hardcopy', status='available'
    ).first()

    if not copy:
        messages.warning(
            request,
            'No copy is currently available for this book. '
            'Please wait \u2014 you will be notified again when one becomes available.'
        )
        return redirect('my_reservations')

    # Check duplicate pending request
    if BorrowRequest.objects.filter(user=request.user, copy=copy, status='pending').exists():
        messages.info(request, 'You already have a pending borrow request for this book.')
        return redirect('my_reservations')

    # Create BorrowRequest (normal approval flow)
    BorrowRequest.objects.create(user=request.user, copy=copy)
    res.status = 'fulfilled'
    res.save(update_fields=['status'])

    # Re-number remaining queue after this slot is fulfilled
    remaining = Reservation.objects.filter(
        book=book, status__in=['pending', 'notified']
    ).order_by('created_at')
    for idx, r in enumerate(remaining, start=1):
        if r.position != idx:
            r.position = idx
            r.save(update_fields=['position'])

    msg = (
        f"MSICT OLMS: Your borrow request for '{book.title}' has been submitted. "
        f"Please wait for librarian approval. You will receive an SMS/email once approved."
    )
    notify_user(request.user, msg, 'sms')
    notify_user(request.user, msg, 'email', subject='Borrow Request Submitted')
    log_audit(request.user, f"Queue borrow submitted for '{book.title}' via reservation #{res.pk}", request)
    messages.success(request, f'Borrow request submitted for "{book.title}". Awaiting librarian approval.')
    return redirect('member_dashboard')


# ============================================================
# MY RESERVATIONS — member view with queue position, actions
# ============================================================
@login_required
# ----------------------------------------------------------------------
# View ya Uhifadhi Wangu — Mwanachama anaona uhifadhi wake
# ----------------------------------------------------------------------
def my_reservations_view(request):
    user = request.user
    # Run expiry checks on all books the user has reservations for
    active_books = Reservation.objects.filter(
        user=user, status__in=['pending', 'notified']
    ).values_list('book_id', flat=True).distinct()
    for book_id in active_books:
        try:
            _process_reservation_expiry(Book.objects.get(pk=book_id))
        except Book.DoesNotExist:
            pass

    active_reservations = Reservation.objects.filter(
        user=user, status__in=['pending', 'notified']
    ).select_related('book').order_by('created_at')

    # Annotate each with queue context
    loan_days  = int(_pref('LOAN_PERIOD_DAYS', 7))
    skip_days  = 1  # 24-h borrow window each queue member gets
    annotated = []
    for res in active_reservations:
        total_q = Reservation.objects.filter(
            book=res.book, status__in=['pending', 'notified']
        ).count()
        ahead = res.position - 1
        borrows = BorrowingTransaction.objects.filter(
            copy__book=res.book, copy__copy_type='hardcopy',
            status__in=['borrowed', 'overdue']
        ).order_by('due_date')
        nearest = borrows.first()
        # Estimate when the book will actually reach this user in queue.
        # Each person ahead: 24h borrow window + loan_days before they return.
        # Position #1 → base date (original borrower's return).
        # Position #2 → base + 1×(1+7) = base + 8 days, etc.
        if nearest and ahead > 0:
            est_your_turn = nearest.due_date + timedelta(days=ahead * (skip_days + loan_days))
        else:
            est_your_turn = nearest.due_date if nearest else None
        annotated.append({
            'res': res,
            'total_queue': total_q,
            'ahead': ahead,
            'nearest_return': nearest,
            'est_your_turn': est_your_turn,
            'hours_notified': res.hours_since_notified,
        })

    history = Reservation.objects.filter(
        user=user, status__in=['fulfilled', 'cancelled', 'expired']
    ).select_related('book').order_by('-created_at')[:30]

    mark_badge_viewed(request.user, 'member_reservations')
    return render(request, 'circulation/my_reservations.html', {
        'annotated': annotated,
        'history': history,
    })


# Maombi yote ya kukopa — inaonekana kwa mtunzaji peke yake
# Inaweza kuchujwa kwa hali: pending, approved, rejected, cancelled
@login_required
@librarian_required
# ----------------------------------------------------------------------
# View ya Orodha ya Maombi Yote — Mtunzaji anaona maombi yote
# ----------------------------------------------------------------------
def all_requests_view(request):
    from django.core.paginator import Paginator
    requests_qs = BorrowRequest.objects.select_related('user', 'copy__book').order_by('-request_date')
    status_filter = request.GET.get('status', '')
    if status_filter:
        requests_qs = requests_qs.filter(status=status_filter)
    paginator = Paginator(requests_qs, 25)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    mark_badge_viewed(request.user, 'pending_requests')
    return render(request, 'circulation/all_requests.html', {
        'requests': page_obj,
        'page_obj': page_obj,
        'status_filter': status_filter,
    })


@login_required
@librarian_required
def issued_records_view(request):
    from django.core.paginator import Paginator
    txs = BorrowingTransaction.objects.select_related(
        'user', 'copy__book', 'approved_by'
    ).order_by('-borrow_date')
    status_filter = request.GET.get('status', '')
    if status_filter:
        txs = txs.filter(status=status_filter)
    paginator = Paginator(txs, 25)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    return render(request, 'circulation/issued_records.html', {
        'transactions': page_obj,
        'page_obj': page_obj,
        'status_filter': status_filter,
    })


# Vitabu vilivyopita tarehe ya kurudisha — kwa mtunzaji
@login_required
@librarian_required
# ----------------------------------------------------------------------
# View ya Orodha ya Vitabu Vilivyopita Tarehe — Mtunzaji anaona overdue
# ----------------------------------------------------------------------
def overdue_list_view(request):
    _auto_mark_overdue()  # Catch any borrowed+past-due not yet marked by cron
    from django.db.models import Exists, OuterRef, F
    from circulation.models import Fine as _Fine
    # Only show transactions that still have an unpaid fine (or no fine yet).
    # Transactions whose fines are fully paid are removed from this list.
    has_unpaid_fine = Exists(
        _Fine.objects.filter(transaction=OuterRef('pk'), paid=False, amount__gt=F('amount_paid'))
    )
    has_no_fine = ~Exists(_Fine.objects.filter(transaction=OuterRef('pk')))
    overdue = (
        BorrowingTransaction.objects
        .filter(status='overdue')
        .exclude(copy__copy_type='softcopy')
        .filter(has_unpaid_fine | has_no_fine)
        .select_related('user', 'copy__book')
        .order_by('due_date')
    )
    mark_badge_viewed(request.user, 'overdue')
    return render(request, 'circulation/overdue_list.html', {'overdue': overdue})


# ----------------------------------------------------------------------
# Msaidizi wa Kuonyesha Vilivyopita Tarehe — Anaonyesha mikopo iliyopita tarehe
# ----------------------------------------------------------------------
def _auto_mark_overdue():
    """Inline guard: mark any 'borrowed' transactions past their due_date as 'overdue'.
    Called at the top of every librarian page that shows overdue/fine data so the
    view is always accurate even when the nightly cron hasn't fired yet.
    EXCLUDES softcopies — they never go overdue."""
    stale = BorrowingTransaction.objects.filter(
        status='borrowed',
        due_date__lt=timezone.now(),
    ).exclude(
        copy__copy_type='softcopy'
    ).only('id', 'status')
    if stale.exists():
        stale.update(status='overdue')


# ----------------------------------------------------------------------
# Msaidizi wa Kuchukua Malipo kutoka Log — Anachukua jumla ya malipo kutoka log
# ----------------------------------------------------------------------
def _extract_total_paid_from_log(receipt_no):
    """Parse the payment history log to sum actual amounts paid.
    Returns Decimal total if parseable, else None."""
    if not receipt_no:
        return None
    amounts = re.findall(r'TZS\s*([\d,]+(?:\.\d+)?)', receipt_no)
    if amounts:
        try:
            return sum(Decimal(a.replace(',', '')) for a in amounts)
        except Exception:
            return None
    return None


# ----------------------------------------------------------------------
# Msaidizi wa Kusawazisha Faini — Anasawazisha faini za kuchelewa
# ----------------------------------------------------------------------
def _sync_overdue_fines(fine_per_day):
    """Shared helper: update existing unpaid fines and create missing ones for overdue transactions.
    Also merges any duplicates (paid + unpaid for same transaction) into a single fine record.
    """
    _auto_mark_overdue()  # Ensure borrowed+past-due are marked overdue before syncing
    overdue_transactions = BorrowingTransaction.objects.filter(
        status='overdue'
    ).exclude(
        copy__copy_type='softcopy'
    ).select_related('user', 'copy__book')
    for tx in overdue_transactions:
        days = tx.days_overdue()
        if days <= 0:
            continue
        new_amount = days * fine_per_day
        title = tx.copy.book.title
        reason = f"Overdue fine for '{title}' ({days} days)"

        paid_fines = Fine.objects.filter(transaction=tx, paid=True).order_by('created_at')
        unpaid_fines = Fine.objects.filter(transaction=tx, paid=False).order_by('created_at')

        if paid_fines.exists() and unpaid_fines.exists():
            # Duplicate: paid + unpaid fine for the same transaction.
            # Merge: delete unpaid duplicates, reactivate the paid fine with updated amount.
            base_fine = paid_fines.last()
            unpaid_fines.delete()
            # Recalculate actual amount_paid from payment log entries
            actual_paid = _extract_total_paid_from_log(base_fine.receipt_no)
            if actual_paid is not None and actual_paid != base_fine.amount_paid:
                base_fine.amount_paid = actual_paid
            base_fine.paid = base_fine.amount_paid >= new_amount
            base_fine.amount = new_amount
            base_fine.reason = reason
            base_fine.save(update_fields=['paid', 'amount', 'amount_paid', 'reason'])

        elif unpaid_fines.exists():
            # Normal: update accumulated amount on existing unpaid fine
            fine = unpaid_fines.last()
            updates = []
            if fine.amount != new_amount:
                fine.amount = new_amount
                updates.append('amount')
            if fine.reason != reason:
                fine.reason = reason
                updates.append('reason')
            # Auto-correct stale paid flag in both directions
            correct_paid = fine.amount_paid >= fine.amount
            if fine.paid != correct_paid:
                fine.paid = correct_paid
                updates.append('paid')
            # Fix incorrectly recorded amount_paid: if receipt log total differs from DB
            # (e.g. due to previous regex truncation bug or capping), correct it.
            if fine.receipt_no and fine.amount_paid > 0:
                actual_paid = _extract_total_paid_from_log(fine.receipt_no)
                if actual_paid is not None and actual_paid != fine.amount_paid:
                    fine.amount_paid = actual_paid
                    fine.paid = fine.amount_paid >= fine.amount
                    if 'paid' not in updates:
                        updates.append('paid')
                    updates.append('amount_paid')
            if updates:
                fine.save(update_fields=updates)

        elif paid_fines.exists():
            # Already paid: check for inconsistency (paid=True but amount_paid < amount)
            base_fine = paid_fines.last()
            if base_fine.amount_paid < base_fine.amount:
                # Inconsistent: was marked paid but amount increased after sync
                # Correct: set paid=False so remaining balance is shown
                base_fine.paid = False
                base_fine.amount = new_amount
                base_fine.reason = reason
                base_fine.save(update_fields=['paid', 'amount', 'reason'])

        else:
            # No fine yet: create one
            Fine.objects.create(
                user=tx.user,
                transaction=tx,
                amount=new_amount,
                reason=reason,
                paid=False,
            )


# Orodha ya faini zote — kwa mtunzaji (pamoja na faini zinazojumlisha kwa siku)
@login_required
@librarian_required
# ----------------------------------------------------------------------
# View ya Orodha ya Faini — Mtunzaji anaona faini zote
# ----------------------------------------------------------------------
def fine_list_view(request):
    from django.db.models import Sum, Count
    from django.core.paginator import Paginator
    fine_per_day = float(_pref('FINE_PER_DAY', 1000))
    _sync_overdue_fines(fine_per_day)
    
    fines = Fine.objects.select_related('user__rank', 'transaction__copy__book').order_by('-created_at')
    
    # Build per-user summary for the top panel (replaces separate 'Users with Fines' page)
    user_summary_qs = (
        Fine.objects.filter(paid=False)
        .values('user__pk', 'user__first_name', 'user__surname', 'user__army_no', 'user__rank__rank_name')
        .annotate(total_amount=Sum('amount'), total_paid=Sum('amount_paid'), fine_count=Count('pk'))
        .order_by('-total_amount')
    )
    user_summary = [
        {
            'user_id': r['user__pk'],
            'name': f"{r['user__first_name']} {r['user__surname']}".strip(),
            'army_no': r['user__army_no'],
            'rank': r['user__rank__rank_name'] or '—',
            'fine_count': r['fine_count'],
            'remaining': (r['total_amount'] or 0) - (r['total_paid'] or 0),
        }
        for r in user_summary_qs
    ]
    
    loan_period_days = int(_pref('LOAN_PERIOD_DAYS', 7))
    paginator = Paginator(fines, 25)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    mark_badge_viewed(request.user, 'unpaid_fines')
    return render(request, 'circulation/fine_list.html', {
        'fines': page_obj,
        'page_obj': page_obj,
        'fine_per_day': fine_per_day,
        'user_summary': user_summary,
        'loan_period_days': loan_period_days,
        'fine_start_day': loan_period_days + 1,
    })


@login_required
@librarian_required
# ----------------------------------------------------------------------
# View ya Faini za Mwanachama — Mtunzaji anaona faini za mtumiaji mahususi
# ----------------------------------------------------------------------
def user_fines_view(request, user_id):
    user_obj = get_object_or_404(OLMSUser, pk=user_id)
    fine_per_day = float(_pref('FINE_PER_DAY', 1000))
    
    # Reuse shared helper to sync this user's overdue fines
    _sync_overdue_fines(fine_per_day)
    
    fines = Fine.objects.filter(
        user=user_obj
    ).select_related('transaction__copy__book').order_by('-created_at')
    unpaid_fines = fines.filter(paid=False)
    # Use remaining_balance (accounts for partial payments)
    total_unpaid = sum(f.remaining_balance for f in unpaid_fines)
    total_paid_count = fines.filter(paid=True).count()
    loan_period_days = int(_pref('LOAN_PERIOD_DAYS', 7))
    return render(request, 'circulation/user_fines.html', {
        'user_obj': user_obj,
        'fines': fines,
        'unpaid_fines': unpaid_fines,
        'total_unpaid': total_unpaid,
        'total_paid_count': total_paid_count,
        'fine_per_day': fine_per_day,
        'loan_period_days': loan_period_days,
        'fine_start_day': loan_period_days + 1,
    })


@login_required
# ----------------------------------------------------------------------
# View ya Faini Zangu — Mwanachama anaona faini zake
# ----------------------------------------------------------------------
def my_fines_view(request):
    # Show only overdue fines (exclude loss fines)
    fines = Fine.objects.filter(
        user=request.user
    ).select_related('transaction__copy__book').order_by('-created_at')
    
    # Get loss report transaction IDs to exclude loss fines
    loss_report_tx_ids = LossReport.objects.filter(
        user=request.user,
        loss_fine__isnull=False
    ).values_list('loss_fine_id', flat=True)
    
    # Exclude loss fines (those associated with loss reports)
    overdue_fines = [f for f in fines if f.id not in loss_report_tx_ids]
    
    unpaid_fines = [f for f in overdue_fines if not f.paid]
    total_unpaid = sum(f.remaining_balance for f in unpaid_fines)
    mark_badge_viewed(request.user, 'member_unpaid_fines')
    return render(request, 'circulation/my_fines.html', {
        'fines': overdue_fines,
        'unpaid_fines': unpaid_fines,
        'total_unpaid': total_unpaid,
    })


@login_required
# ----------------------------------------------------------------------
# View ya Ripoti za Hasara Zangu — Mwanachama anaona ripoti zake
# ----------------------------------------------------------------------
def my_loss_reports_view(request):
    """Member views their loss reports and loss fines."""
    reports = LossReport.objects.filter(
        user=request.user
    ).select_related('transaction__copy__book', 'loss_fine').order_by('-reported_at')
    unpaid_loss_reports = [r for r in reports if r.loss_fine and not r.loss_fine.paid]
    total_unpaid_loss_fine = sum(r.loss_fine.remaining_balance for r in unpaid_loss_reports)
    mark_badge_viewed(request.user, 'member_loss_fines')
    return render(request, 'circulation/my_loss_reports.html', {
        'reports': reports,
        'unpaid_loss_reports': unpaid_loss_reports,
        'total_unpaid_loss_fine': total_unpaid_loss_fine,
    })


@login_required
# ----------------------------------------------------------------------
# View ya Ripoti za Uharibifu Zangu — Mwanachama anaona ripoti zake
# ----------------------------------------------------------------------
def my_damage_reports_view(request):
    """Member views their damage reports and damage fines."""
    reports = DamageReport.objects.filter(
        user=request.user
    ).select_related('transaction__copy__book', 'damage_fine').order_by('-reported_at')
    unpaid_damage_reports = [r for r in reports if r.damage_fine and not r.damage_fine.paid]
    total_unpaid_damage_fine = sum(r.damage_fine.remaining_balance for r in unpaid_damage_reports)
    mark_badge_viewed(request.user, 'member_damage_fines')
    return render(request, 'circulation/my_damage_reports.html', {
        'reports': reports,
        'unpaid_damage_reports': unpaid_damage_reports,
        'total_unpaid_damage_fine': total_unpaid_damage_fine,
    })


@login_required
# ----------------------------------------------------------------------
# View ya Lipa Faini — Mwanachama anapangia kulipa faini
# ----------------------------------------------------------------------
def pay_fine_view(request, fine_id):
    """
    Member-facing self-service fine payment.

    GET  : show the payment options page.
    POST : process the payment — update fine.amount_paid, fine.paid,
           record revenue, send SMS notification, and redirect to receipt.
           No cash/manual option — only mobile, bank, card.
    """
    fine = get_object_or_404(Fine, id=fine_id, user=request.user)
    if fine.paid:
        messages.info(request, 'This fine has already been fully paid. Here is your receipt.')
        return redirect('fine_receipt_pdf', fine_id=fine.pk)

    if request.method == 'POST':
        raw_method = (request.POST.get('payment_method') or '').strip().lower()
        amount_str = (request.POST.get('payment_amount') or '').strip()
        reference = (request.POST.get('reference') or '').strip()

        # Map member-facing method names to standard ones used by _record_fine_payment
        METHOD_MAP = {
            'mpesa': 'mpesa',
            'tigopesa': 'tigopesa',
            'airtel': 'airtel_money',
            'halotel': 'halopesa',
            'card': 'visa',
            'bank': 'bank_transfer',
        }
        ALLOWED_METHODS = set(METHOD_MAP.keys())

        if raw_method not in ALLOWED_METHODS:
            messages.error(request, 'Please select a valid payment method.')
            return redirect('pay_fine', fine_id=fine.pk)

        payment_method = METHOD_MAP[raw_method]

        try:
            amount = Decimal(amount_str)
        except (ValueError, TypeError, InvalidOperation):
            messages.error(request, 'Please enter a valid payment amount.')
            return redirect('pay_fine', fine_id=fine.pk)

        if amount <= 0:
            messages.error(request, 'Payment amount must be greater than 0.')
            return redirect('pay_fine', fine_id=fine.pk)

        if amount > fine.remaining_balance:
            messages.error(
                request,
                f'Amount TZS {amount:,.0f} exceeds remaining balance '
                f'TZS {fine.remaining_balance:,.0f}.'
            )
            return redirect('pay_fine', fine_id=fine.pk)

        # Extract payment details based on method
        phone_number = ''
        bank_name = ''
        bank_account_no = ''
        card_holder = ''
        card_last4 = ''
        card_expiry = ''
        receipt_ref = ''

        if payment_method in ('mpesa', 'tigopesa', 'airtel_money', 'halopesa'):
            phone_number = reference
            if phone_number and not re.match(r'^0\d{9}$', phone_number):
                messages.error(request, 'Phone number must be exactly 10 digits starting with 0 (e.g. 0712345678).')
                return redirect('pay_fine', fine_id=fine.pk)
        elif payment_method == 'bank_transfer':
            bank_name = (request.POST.get('bank_name') or '').strip()
            receipt_ref = reference
        elif payment_method in ('visa', 'mastercard'):
            card_holder = request.user.get_full_name() or request.user.username
            card_number = (request.POST.get('card_number') or '').strip()
            card_last4 = card_number[-4:] if len(card_number) >= 4 else card_number
            card_expiry = (request.POST.get('card_expiry') or '').strip()

        # Process the actual payment
        _record_fine_payment(
            fine, amount, payment_method,
            receipt_ref=receipt_ref,
            phone_number=phone_number,
            bank_name=bank_name,
            bank_account_no=bank_account_no,
            card_holder=card_holder,
            card_last4=card_last4,
            card_expiry=card_expiry,
            recorded_by=request.user,
        )

        # Refresh from DB
        fine.refresh_from_db()

        # SMS notification
        try:
            book_name = fine.transaction.copy.book.title if fine.transaction else 'book'
            if fine.paid:
                sms = (f"MSICT OLMS: Fine fully paid. TZS {fine.amount:,.0f} for '{book_name}' "
                       f"via {payment_method.upper()}. Thank you.")
            else:
                sms = (f"MSICT OLMS: Payment of TZS {amount:,.0f} received for '{book_name}' fine. "
                       f"Remaining balance: TZS {fine.remaining_balance:,.0f}.")
            notify_user(fine.user, sms, 'sms', message_type='fine')
        except Exception:
            pass

        log_audit(
            request.user,
            f"Member self-service fine payment: fine #{fine.pk}, "
            f"{payment_method.upper()} TZS {amount:,.0f} (paid={fine.paid})",
            request,
        )

        if fine.paid:
            messages.success(
                request,
                f'Payment successful! TZS {amount:,.0f} paid via {payment_method.upper()}. '
                f'Fine fully settled. Receipt is ready to print.'
            )
        else:
            messages.success(
                request,
                f'Payment of TZS {amount:,.0f} recorded via {payment_method.upper()}. '
                f'Remaining balance: TZS {fine.remaining_balance:,.0f}. Receipt is ready to print.'
            )

        # Email receipt to user
        try:
            from .receipt_utils import email_fine_receipt
            email_fine_receipt(fine)
        except Exception:
            pass

        # Redirect to receipt PDF
        return redirect('fine_receipt_pdf', fine_id=fine.pk)

    return render(request, 'circulation/pay_fine.html', {'fine': fine})


@login_required
# ----------------------------------------------------------------------
# View ya Lipa Faini ya Hasara — Mwanachama anapangia kulipa faini ya hasara
# ----------------------------------------------------------------------
def pay_loss_fine_view(request, report_id):
    """
    Member-facing self-service loss fine payment.

    GET  : show the payment options page.
    POST : process the payment — update fine.amount_paid, fine.paid,
           record revenue, send SMS notification, update loss report
           status if fully paid, and redirect to receipt.
           No cash/manual option — only mobile, bank, card.
    """
    report = get_object_or_404(LossReport, pk=report_id, user=request.user)
    if not report.loss_fine:
        messages.error(request, 'This loss report has no fine to pay.')
        return redirect('member_dashboard')
    if report.loss_fine.paid:
        messages.info(request, 'This loss fine has already been fully paid. Here is your receipt.')
        return redirect('loss_fine_receipt_pdf', report_id=report.pk)

    fine = report.loss_fine

    if request.method == 'POST':
        raw_method = (request.POST.get('payment_method') or '').strip().lower()
        amount_str = (request.POST.get('payment_amount') or '').strip()
        reference = (request.POST.get('reference') or '').strip()

        METHOD_MAP = {
            'mpesa': 'mpesa',
            'tigopesa': 'tigopesa',
            'airtel': 'airtel_money',
            'halotel': 'halopesa',
            'card': 'visa',
            'bank': 'bank_transfer',
        }
        ALLOWED_METHODS = set(METHOD_MAP.keys())

        if raw_method not in ALLOWED_METHODS:
            messages.error(request, 'Please select a valid payment method.')
            return redirect('pay_loss_fine', report_id=report.pk)

        payment_method = METHOD_MAP[raw_method]

        try:
            amount = Decimal(amount_str)
        except (ValueError, TypeError, InvalidOperation):
            messages.error(request, 'Please enter a valid payment amount.')
            return redirect('pay_loss_fine', report_id=report.pk)

        if amount <= 0:
            messages.error(request, 'Payment amount must be greater than 0.')
            return redirect('pay_loss_fine', report_id=report.pk)

        if amount > fine.remaining_balance:
            messages.error(
                request,
                f'Amount TZS {amount:,.0f} exceeds remaining balance '
                f'TZS {fine.remaining_balance:,.0f}.'
            )
            return redirect('pay_loss_fine', report_id=report.pk)

        # Extract payment details based on method
        phone_number = ''
        bank_name = ''
        bank_account_no = ''
        card_holder = ''
        card_last4 = ''
        card_expiry = ''
        receipt_ref = ''

        if payment_method in ('mpesa', 'tigopesa', 'airtel_money', 'halopesa'):
            phone_number = reference
            if phone_number and not re.match(r'^0\d{9}$', phone_number):
                messages.error(request, 'Phone number must be exactly 10 digits starting with 0 (e.g. 0712345678).')
                return redirect('pay_loss_fine', report_id=report.pk)
        elif payment_method == 'bank_transfer':
            bank_name = (request.POST.get('bank_name') or '').strip()
            receipt_ref = reference
        elif payment_method in ('visa', 'mastercard'):
            card_holder = request.user.get_full_name() or request.user.username
            card_number = (request.POST.get('card_number') or '').strip()
            card_last4 = card_number[-4:] if len(card_number) >= 4 else card_number
            card_expiry = (request.POST.get('card_expiry') or '').strip()

        # Process the actual payment
        _record_fine_payment(
            fine, amount, payment_method,
            receipt_ref=receipt_ref,
            phone_number=phone_number,
            bank_name=bank_name,
            bank_account_no=bank_account_no,
            card_holder=card_holder,
            card_last4=card_last4,
            card_expiry=card_expiry,
            recorded_by=request.user,
        )

        # Refresh from DB
        fine.refresh_from_db()

        # Update loss report status if fully paid
        if fine.paid:
            report.status = 'resolved'
            report.save(update_fields=['status'])
            # Mark transaction as returned so it leaves active borrowing
            tx = report.transaction
            if tx.status != 'returned':
                tx.status = 'returned'
                tx.return_date = timezone.now()
                tx.save(update_fields=['status', 'return_date'])

        # SMS notification
        try:
            book_name = report.transaction.copy.book.title if report.transaction else 'book'
            if fine.paid:
                sms = (f"MSICT OLMS: Loss fine fully paid. TZS {fine.amount:,.0f} for '{book_name}' "
                       f"via {payment_method.upper()}. Loss report LR-{report.pk} is now closed.")
            else:
                sms = (f"MSICT OLMS: Payment of TZS {amount:,.0f} received for loss fine on '{book_name}'. "
                       f"Remaining balance: TZS {fine.remaining_balance:,.0f}.")
            notify_user(fine.user, sms, 'sms', message_type='loss_fine')
        except Exception:
            pass

        log_audit(
            request.user,
            f"Member self-service loss fine payment: loss report #{report.pk}, "
            f"{payment_method.upper()} TZS {amount:,.0f} (paid={fine.paid})",
            request,
        )

        if fine.paid:
            messages.success(
                request,
                f'Payment successful! TZS {amount:,.0f} paid via {payment_method.upper()}. '
                f'Loss fine fully settled. Receipt is ready to print.'
            )
        else:
            messages.success(
                request,
                f'Payment of TZS {amount:,.0f} recorded via {payment_method.upper()}. '
                f'Remaining balance: TZS {fine.remaining_balance:,.0f}. Receipt is ready to print.'
            )

        # Email receipt to user
        try:
            from .receipt_utils import email_loss_receipt
            email_loss_receipt(report)
        except Exception:
            pass

        # Redirect to loss fine receipt PDF
        return redirect('loss_fine_receipt_pdf', report_id=report.pk)

    return render(request, 'circulation/pay_loss_fine.html', {'report': report, 'fine': fine})


def _record_fine_payment(fine, amount, payment_method, receipt_ref='',
                          phone_number='', bank_name='', bank_account_no='',
                          card_holder='', card_last4='', card_expiry='',
                          recorded_by=None):
    """Apply a payment to a Fine row and save. Pure helper — no redirect/messages."""
    MOBILE_METHODS = {'mpesa', 'tigopesa', 'airtel_money', 'halopesa'}
    CARD_METHODS   = {'visa', 'mastercard'}
    now_str = timezone.now().strftime('%d %b %Y %H:%M')
    entry = f"[{now_str}] {payment_method.upper()} TZS {amount:,.0f}"
    if payment_method in MOBILE_METHODS and phone_number:
        entry += f" | Phone: {phone_number}"
    elif payment_method == 'bank_transfer':
        if bank_name:       entry += f" | Bank: {bank_name}"
        if bank_account_no: entry += f" | Acct: {bank_account_no}"
        if receipt_ref:     entry += f" | Ref: {receipt_ref}"
    elif payment_method in CARD_METHODS:
        if card_holder: entry += f" | Name: {card_holder}"
        if card_last4:  entry += f" | Card: ****{card_last4}"
        if card_expiry: entry += f" | Exp: {card_expiry}"
    fine.amount_paid    += amount
    fine.payment_method  = payment_method
    fine.paid_at         = timezone.now()
    fine.receipt_no      = (fine.receipt_no + "\n" + entry).strip()
    fine.paid            = fine.amount_paid >= fine.amount
    fine.save()

    is_loss_fine = LossReport.objects.filter(loss_fine=fine).exists()
    is_damage_fine = DamageReport.objects.filter(damage_fine=fine).exists()
    if is_loss_fine:
        rev_type = 'loss'
    elif is_damage_fine:
        rev_type = 'damage'
    else:
        rev_type = 'overdue'
    _record_revenue(
        user=fine.user,
        account_type=rev_type,
        amount=amount,
        description=f"Fine payment via {payment_method.upper()} (fine #{fine.pk})",
        reference_id=fine.pk,
        reference_table='fines',
        recorded_by=recorded_by,
    )

    # If a loss fine is fully paid, mark the loss report as resolved
    if is_loss_fine and fine.paid:
        LossReport.objects.filter(loss_fine=fine).update(status='resolved')


@login_required
@librarian_required
# ----------------------------------------------------------------------
# View ya Rekodi Malipo ya Faini ya Hasara — Mtunzaji anarekodi malipo
# ----------------------------------------------------------------------
def record_loss_fine_payment_view(request, report_id):
    """
    Librarian loss fine payment handler.

    Supports fine_type POST parameter:
      'loss'   – pay the loss fine only (default)
      'overdue' – pay the overdue fine only
      'both'   – pay both; loss fine is cleared first, remainder to overdue fine

    GET : show the payment form page (passes overdue_fine to template).
    POST: validate and record payment on the selected fine(s).
    """
    report = get_object_or_404(LossReport, pk=report_id)
    if not report.loss_fine:
        messages.error(request, 'This loss report has no fine to pay.')
        return redirect('loss_report_list')

    fine = report.loss_fine

    # Resolve the overdue fine for this transaction (distinct from the loss fine)
    overdue_fine = None
    if report.transaction:
        overdue_qs = Fine.objects.filter(
            transaction=report.transaction,
            reason__icontains='Overdue',
        )
        if report.loss_fine_id:
            overdue_qs = overdue_qs.exclude(id=report.loss_fine_id)
        overdue_fine = overdue_qs.first()

    if request.method != 'POST':
        return render(request, 'circulation/loss_fine_payment.html', {
            'report': report,
            'fine': fine,
            'overdue_fine': overdue_fine,
        })

    # ── POST ────────────────────────────────────────────────────────────
    fine_type       = request.POST.get('fine_type', 'loss')
    payment_method  = request.POST.get('payment_method', 'cash')
    receipt_ref     = request.POST.get('receipt_no', '').strip()
    payment_amount_str = request.POST.get('payment_amount', '')
    phone_number    = request.POST.get('phone_number', '').strip()
    bank_name       = request.POST.get('bank_name', '').strip()
    bank_account_no = request.POST.get('bank_account_no', '').strip()
    card_holder     = request.POST.get('card_holder', '').strip()
    card_last4      = request.POST.get('card_last4', '').strip()
    card_expiry     = request.POST.get('card_expiry', '').strip()

    try:
        payment_amount = Decimal(payment_amount_str) if payment_amount_str else Decimal('0')
    except (ValueError, TypeError, InvalidOperation):
        payment_amount = Decimal('0')

    if payment_amount <= 0:
        messages.error(request, 'Payment amount must be greater than 0.')
        return redirect('record_loss_fine_payment', report_id=report.pk)

    mobile_methods = {'mpesa', 'tigopesa', 'airtel_money', 'halopesa'}
    if payment_method in mobile_methods and phone_number and not re.match(r'^0\d{9}$', phone_number):
        messages.error(request, 'Phone number must be exactly 10 digits starting with 0 (e.g. 0712345678).')
        return redirect('record_loss_fine_payment', report_id=report.pk)

    kwargs = dict(payment_method=payment_method, receipt_ref=receipt_ref,
                  phone_number=phone_number, bank_name=bank_name,
                  bank_account_no=bank_account_no, card_holder=card_holder,
                  card_last4=card_last4, card_expiry=card_expiry)

    # ── Route by fine_type ───────────────────────────────────────────────
    if fine_type == 'overdue':
        if not overdue_fine:
            messages.error(request, 'No overdue fine found for this loss report.')
            return redirect('record_loss_fine_payment', report_id=report.pk)
        if payment_amount > overdue_fine.remaining_balance:
            messages.error(request,
                f'TZS {payment_amount:,.0f} exceeds overdue fine remaining balance '
                f'TZS {overdue_fine.remaining_balance:,.0f}.')
            return redirect('record_loss_fine_payment', report_id=report.pk)
        _record_fine_payment(overdue_fine, payment_amount, **kwargs)

    elif fine_type == 'both' and overdue_fine:
        total_rem = fine.remaining_balance + overdue_fine.remaining_balance
        if payment_amount > total_rem:
            messages.error(request,
                f'TZS {payment_amount:,.0f} exceeds total remaining balance '
                f'TZS {total_rem:,.0f}.')
            return redirect('record_loss_fine_payment', report_id=report.pk)
        # Apply to loss fine first, remainder to overdue fine
        loss_pay    = min(payment_amount, fine.remaining_balance)
        overdue_pay = payment_amount - loss_pay
        if loss_pay > 0:
            _record_fine_payment(fine, loss_pay, **kwargs)
        if overdue_pay > 0:
            _record_fine_payment(overdue_fine, overdue_pay, **kwargs)

    else:  # fine_type == 'loss' (default)
        if payment_amount > fine.remaining_balance:
            messages.error(request,
                f'TZS {payment_amount:,.0f} exceeds loss fine remaining balance '
                f'TZS {fine.remaining_balance:,.0f}.')
            return redirect('record_loss_fine_payment', report_id=report.pk)
        _record_fine_payment(fine, payment_amount, **kwargs)

    # ── Refresh and check if ALL fines are now settled ───────────────────
    fine.refresh_from_db()
    if overdue_fine:
        overdue_fine.refresh_from_db()
        all_paid = fine.paid and overdue_fine.paid
        total_remaining = fine.remaining_balance + overdue_fine.remaining_balance
    else:
        all_paid = fine.paid
        total_remaining = fine.remaining_balance

    if all_paid:
        report.status = 'resolved'
        report.save(update_fields=['status'])
        # Mark transaction as returned so it leaves active borrowing
        tx = report.transaction
        if tx.status != 'returned':
            tx.status = 'returned'
            tx.return_date = timezone.now()
            tx.save(update_fields=['status', 'return_date'])
        msg = f'All fines fully paid (TZS {payment_amount:,.0f}). Loss report LR-{report.pk} marked Resolved.'
        messages.success(request, msg)
    else:
        # Build detailed message based on fine_type
        if fine_type == 'both' and overdue_fine:
            loss_paid = min(payment_amount, fine.amount)
            overdue_paid = payment_amount - loss_paid
            loss_remaining = fine.amount - loss_paid
            overdue_remaining = overdue_fine.amount - overdue_paid
            details = []
            if loss_paid:
                details.append(f'Loss fine TZS {loss_paid:,.0f} (remaining TZS {loss_remaining:,.0f})')
            if overdue_paid:
                details.append(f'Overdue fine TZS {overdue_paid:,.0f} (remaining TZS {overdue_remaining:,.0f})')
            msg = f'Payment recorded: {", ".join(details)}. Total still outstanding: TZS {total_remaining:,.0f}.'
        elif fine_type == 'loss':
            msg = (f'Loss fine payment: TZS {payment_amount:,.0f} '
                   f'(remaining TZS {total_remaining:,.0f}).')
        elif fine_type == 'overdue':
            msg = (f'Overdue fine payment: TZS {payment_amount:,.0f} '
                   f'(remaining TZS {total_remaining:,.0f}).')
        else:
            msg = (f'Payment of TZS {payment_amount:,.0f} recorded ({fine_type} fine). '
                   f'Total still outstanding: TZS {total_remaining:,.0f}.')
        messages.success(request, msg)

    # Debug: log message count
    from django.contrib.messages import get_messages
    msg_count = len(list(get_messages(request)))
    log_audit(request.user, f"DEBUG: {msg_count} messages in queue after loss payment", request)

    # ── SMS notification ─────────────────────────────────────────────────
    try:
        book_name = report.transaction.copy.book.title
        if all_paid:
            sms = (f"MSICT OLMS: All fines fully settled for '{book_name}'. "
                   f"Thank you. LR-{report.pk}.")
        else:
            sms = (f"MSICT OLMS: Payment of TZS {payment_amount:,.0f} received for '{book_name}'. "
                   f"Remaining balance: TZS {total_remaining:,.0f}. LR-{report.pk}.")
        notify_user(fine.user, sms, 'sms', message_type='loss_fine')
    except Exception as exc:
        log_audit(request.user, f"SMS failed for LR-{report.pk}: {exc}", request)

    log_audit(request.user,
        f"LR-{report.pk} payment TZS {payment_amount:,.0f} ({fine_type}) "
        f"by {fine.user.username} via {payment_method}", request)

    try:
        from .receipt_utils import email_loss_receipt
        email_loss_receipt(report)
    except Exception:
        pass

    # Store messages before redirect to ensure they persist
    storage = messages.get_messages(request)
    stored_messages = []
    for message in storage:
        stored_messages.append({
            'level': message.level,
            'message': message.message,
            'tags': message.tags
        })
    
    # Use redirect with explicit message passing if needed
    response = redirect('loss_report_list')
    
    # If messages were lost, add them back
    if not stored_messages:
        for msg in stored_messages:
            messages.add_message(request, msg['level'], msg['message'], extra_tags=msg['tags'])
    
    return response


# ----------------------------------------------------------------------
# View ya Lipa Faini ya Uharibifu — Mwanachama analipa faini ya uharibifu
# ----------------------------------------------------------------------
@login_required
def pay_damage_fine_view(request, report_id):
    """Member-facing self-service damage fine payment.
    No cash/manual option — only mobile, bank, card."""
    report = get_object_or_404(DamageReport, pk=report_id, user=request.user)
    if not report.damage_fine:
        messages.error(request, 'This damage report has no fine to pay.')
        return redirect('member_dashboard')
    if report.damage_fine.paid:
        messages.info(request, 'This damage fine has already been fully paid.')
        return redirect('member_dashboard')

    fine = report.damage_fine

    # Also check for overdue fine on same transaction
    overdue_fine = Fine.objects.filter(
        transaction=report.transaction,
        reason__icontains='Overdue',
    ).exclude(id=fine.id).first()

    if request.method == 'POST':
        raw_method = (request.POST.get('payment_method') or '').strip().lower()
        amount_str = (request.POST.get('payment_amount') or '').strip()
        reference = (request.POST.get('reference') or '').strip()

        METHOD_MAP = {
            'mpesa': 'mpesa',
            'tigopesa': 'tigopesa',
            'airtel': 'airtel_money',
            'halotel': 'halopesa',
            'card': 'visa',
            'bank': 'bank_transfer',
        }
        ALLOWED_METHODS = set(METHOD_MAP.keys())

        if raw_method not in ALLOWED_METHODS:
            messages.error(request, 'Please select a valid payment method.')
            return redirect('pay_damage_fine', report_id=report.pk)

        payment_method = METHOD_MAP[raw_method]

        try:
            amount = Decimal(amount_str)
        except (ValueError, TypeError, InvalidOperation):
            messages.error(request, 'Please enter a valid payment amount.')
            return redirect('pay_damage_fine', report_id=report.pk)

        if amount <= 0:
            messages.error(request, 'Payment amount must be greater than 0.')
            return redirect('pay_damage_fine', report_id=report.pk)

        if amount > fine.remaining_balance:
            messages.error(
                request,
                f'Amount TZS {amount:,.0f} exceeds remaining balance TZS {fine.remaining_balance:,.0f}.'
            )
            return redirect('pay_damage_fine', report_id=report.pk)

        phone_number = ''
        bank_name = ''
        bank_account_no = ''
        card_holder = ''
        card_last4 = ''
        card_expiry = ''
        receipt_ref = ''

        if payment_method in ('mpesa', 'tigopesa', 'airtel_money', 'halopesa'):
            phone_number = reference
            if phone_number and not re.match(r'^0\d{9}$', phone_number):
                messages.error(request, 'Phone number must be exactly 10 digits starting with 0 (e.g. 0712345678).')
                return redirect('pay_damage_fine', report_id=report.pk)
        elif payment_method == 'bank_transfer':
            bank_name = (request.POST.get('bank_name') or '').strip()
            receipt_ref = reference
        elif payment_method in ('visa', 'mastercard'):
            card_holder = request.user.get_full_name() or request.user.username
            card_number = (request.POST.get('card_number') or '').strip()
            card_last4 = card_number[-4:] if len(card_number) >= 4 else card_number
            card_expiry = (request.POST.get('card_expiry') or '').strip()

        _record_fine_payment(
            fine, amount, payment_method,
            receipt_ref=receipt_ref,
            phone_number=phone_number,
            bank_name=bank_name,
            bank_account_no=bank_account_no,
            card_holder=card_holder,
            card_last4=card_last4,
            card_expiry=card_expiry,
            recorded_by=request.user,
        )

        fine.refresh_from_db()

        if fine.paid:
            report.status = 'resolved'
            report.save(update_fields=['status'])

        try:
            book_name = report.transaction.copy.book.title
            if fine.paid:
                sms = (f"MSICT OLMS: Damage fine fully paid. TZS {fine.amount:,.0f} for '{book_name}' "
                       f"via {payment_method.upper()}. Damage report DR-{report.pk} is now closed.")
            else:
                sms = (f"MSICT OLMS: Payment of TZS {amount:,.0f} received for damage fine on '{book_name}'. "
                       f"Remaining balance: TZS {fine.remaining_balance:,.0f}.")
            notify_user(fine.user, sms, 'sms', message_type='damage_fine')
        except Exception:
            pass

        log_audit(
            request.user,
            f"Member self-service damage fine payment: DR-{report.pk}, "
            f"{payment_method.upper()} TZS {amount:,.0f} (paid={fine.paid})",
            request,
        )

        if fine.paid:
            messages.success(request,
                f'Payment successful! TZS {amount:,.0f} paid via {payment_method.upper()}. '
                f'Damage fine fully settled.')
        else:
            messages.success(request,
                f'Payment of TZS {amount:,.0f} recorded via {payment_method.upper()}. '
                f'Remaining balance: TZS {fine.remaining_balance:,.0f}.')

        # Email receipt to user
        try:
            from .receipt_utils import email_fine_receipt
            email_fine_receipt(fine)
        except Exception:
            pass

        return redirect('member_dashboard')

    return render(request, 'circulation/damage_fine_payment.html', {
        'report': report,
        'fine': fine,
        'overdue_fine': overdue_fine,
    })


# ----------------------------------------------------------------------
# View ya Rekodi Malipo ya Faini ya Uharibifu — Mtunzaji anarekodi malipo
# ----------------------------------------------------------------------
@login_required
@librarian_required
def record_damage_fine_payment_view(request, report_id):
    """Librarian damage fine payment handler.
    Supports fine_type POST parameter: 'damage', 'overdue', 'both'."""
    report = get_object_or_404(DamageReport, pk=report_id)
    if not report.damage_fine:
        messages.error(request, 'This damage report has no fine to pay.')
        return redirect('lost_damaged_copies')

    fine = report.damage_fine

    overdue_fine = None
    if report.transaction:
        overdue_qs = Fine.objects.filter(
            transaction=report.transaction,
            reason__icontains='Overdue',
        )
        if report.damage_fine_id:
            overdue_qs = overdue_qs.exclude(id=report.damage_fine_id)
        overdue_fine = overdue_qs.first()

    if request.method != 'POST':
        return render(request, 'circulation/damage_fine_payment.html', {
            'report': report,
            'fine': fine,
            'overdue_fine': overdue_fine,
            'librarian_mode': True,
        })

    fine_type       = request.POST.get('fine_type', 'damage')
    payment_method  = request.POST.get('payment_method', 'cash')
    receipt_ref     = request.POST.get('receipt_no', '').strip()
    payment_amount_str = request.POST.get('payment_amount', '')
    phone_number    = request.POST.get('phone_number', '').strip()
    bank_name       = request.POST.get('bank_name', '').strip()
    bank_account_no = request.POST.get('bank_account_no', '').strip()
    card_holder     = request.POST.get('card_holder', '').strip()
    card_last4      = request.POST.get('card_last4', '').strip()
    card_expiry     = request.POST.get('card_expiry', '').strip()

    try:
        payment_amount = Decimal(payment_amount_str) if payment_amount_str else Decimal('0')
    except (ValueError, TypeError, InvalidOperation):
        payment_amount = Decimal('0')

    if payment_amount <= 0:
        messages.error(request, 'Payment amount must be greater than 0.')
        return redirect('record_damage_fine_payment', report_id=report.pk)

    mobile_methods = {'mpesa', 'tigopesa', 'airtel_money', 'halopesa'}
    if payment_method in mobile_methods and phone_number and not re.match(r'^0\d{9}$', phone_number):
        messages.error(request, 'Phone number must be exactly 10 digits starting with 0 (e.g. 0712345678).')
        return redirect('record_damage_fine_payment', report_id=report.pk)

    kwargs = dict(payment_method=payment_method, receipt_ref=receipt_ref,
                  phone_number=phone_number, bank_name=bank_name,
                  bank_account_no=bank_account_no, card_holder=card_holder,
                  card_last4=card_last4, card_expiry=card_expiry)

    if fine_type == 'overdue':
        if not overdue_fine:
            messages.error(request, 'No overdue fine found for this damage report.')
            return redirect('record_damage_fine_payment', report_id=report.pk)
        if payment_amount > overdue_fine.remaining_balance:
            messages.error(request, f'TZS {payment_amount:,.0f} exceeds overdue fine remaining balance.')
            return redirect('record_damage_fine_payment', report_id=report.pk)
        _record_fine_payment(overdue_fine, payment_amount, **kwargs)

    elif fine_type == 'both' and overdue_fine:
        total_rem = fine.remaining_balance + overdue_fine.remaining_balance
        if payment_amount > total_rem:
            messages.error(request, f'TZS {payment_amount:,.0f} exceeds total remaining balance.')
            return redirect('record_damage_fine_payment', report_id=report.pk)
        damage_pay = min(payment_amount, fine.remaining_balance)
        overdue_pay = payment_amount - damage_pay
        if damage_pay > 0:
            _record_fine_payment(fine, damage_pay, **kwargs)
        if overdue_pay > 0:
            _record_fine_payment(overdue_fine, overdue_pay, **kwargs)

    else:  # fine_type == 'damage'
        if payment_amount > fine.remaining_balance:
            messages.error(request, f'TZS {payment_amount:,.0f} exceeds damage fine remaining balance.')
            return redirect('record_damage_fine_payment', report_id=report.pk)
        _record_fine_payment(fine, payment_amount, **kwargs)

    fine.refresh_from_db()
    if overdue_fine:
        overdue_fine.refresh_from_db()
        all_paid = fine.paid and overdue_fine.paid
        total_remaining = fine.remaining_balance + overdue_fine.remaining_balance
    else:
        all_paid = fine.paid
        total_remaining = fine.remaining_balance

    if all_paid:
        report.status = 'resolved'
        report.save(update_fields=['status'])

        # ── Complete the return: mark transaction as returned ──────
        tx = report.transaction
        if tx.status in ('borrowed', 'overdue'):
            tx.return_date = timezone.now()
            tx.status = 'returned'
            tx.save(update_fields=['return_date', 'status'])
            log_audit(request.user,
                      f"Auto-return completed after damage fine payment: '{tx.copy.book.title}' (DR-{report.pk})",
                      request)

        messages.success(request, f'All fines fully paid (TZS {payment_amount:,.0f}). Damage report DR-{report.pk} marked Resolved. Book return completed.')
    else:
        messages.success(request, f'Payment of TZS {payment_amount:,.0f} recorded. Total still outstanding: TZS {total_remaining:,.0f}.')

    try:
        book_name = report.transaction.copy.book.title
        if all_paid:
            sms = (f"MSICT OLMS: All damage fines fully settled for '{book_name}'. Thank you. DR-{report.pk}.")
        else:
            sms = (f"MSICT OLMS: Payment of TZS {payment_amount:,.0f} received for '{book_name}'. Remaining balance: TZS {total_remaining:,.0f}. DR-{report.pk}.")
        notify_user(fine.user, sms, 'sms', message_type='damage_fine')
    except Exception:
        pass

    log_audit(request.user,
        f"DR-{report.pk} payment TZS {payment_amount:,.0f} ({fine_type}) by {fine.user.username} via {payment_method}", request)

    # Email receipt to user (damage fine and/or overdue fine)
    try:
        from .receipt_utils import email_fine_receipt
        email_fine_receipt(fine)
        if overdue_fine and fine_type in ('overdue', 'both'):
            email_fine_receipt(overdue_fine)
    except Exception:
        pass

    return redirect('lost_damaged_copies')


@login_required
@librarian_required
# ----------------------------------------------------------------------
# View ya Watumiaji Wanaodaiwa — Mtunzaji anaona watumiaji wanaodaiwa
# ----------------------------------------------------------------------
def users_with_unpaid_fines_view(request):
    from collections import defaultdict
    fine_per_day = float(_pref('FINE_PER_DAY', 1000))
    _sync_overdue_fines(fine_per_day)  # Mark status + sync fine amounts before listing

    # Get users with unpaid fines
    users_with_fines = (
        Fine.objects
        .filter(paid=False)
        .values('user__pk', 'user__username', 'user__first_name', 'user__surname', 'user__army_no')
        .annotate(total_amount=Sum('amount'), total_paid=Sum('amount_paid'), fine_count=Count('pk'))
        .order_by('-total_amount')
    )
    
    # Get users with overdue books (even if no fines yet)
    # Exclude softcopies — they never go overdue
    overdue_users = (
        BorrowingTransaction.objects
        .filter(status='overdue')
        .exclude(copy__copy_type='softcopy')
        .values('user__pk', 'user__username', 'user__first_name', 'user__surname', 'user__army_no')
        .annotate(overdue_count=Count('pk'))
        .order_by('-overdue_count')
    )
    
    # Combine both sets
    users_dict = {}
    
    # Add users with fines
    for item in users_with_fines:
        remaining = (item['total_amount'] or 0) - (item['total_paid'] or 0)
        users_dict[item['user__pk']] = {
            'user_id': item['user__pk'],
            'username': item['user__username'],
            'full_name': f"{item['user__first_name']} {item['user__surname']}".strip() or item['user__username'],
            'army_no': item['user__army_no'],
            'total_amount': remaining,
            'fine_count': item['fine_count'],
            'overdue_count': 0,
        }
    
    # Add or update users with overdue books
    for item in overdue_users:
        if item['user__pk'] in users_dict:
            users_dict[item['user__pk']]['overdue_count'] = item['overdue_count']
        else:
            users_dict[item['user__pk']] = {
                'user_id': item['user__pk'],
                'username': item['user__username'],
                'full_name': f"{item['user__first_name']} {item['user__surname']}".strip() or item['user__username'],
                'army_no': item['user__army_no'],
                'total_amount': 0,
                'fine_count': 0,
                'overdue_count': item['overdue_count'],
            }
    
    # Convert to list and sort by total amount + overdue priority
    users_list = list(users_dict.values())
    users_list.sort(key=lambda x: (x['total_amount'], x['overdue_count']), reverse=True)
    
    return render(request, 'circulation/users_with_fines.html', {
        'users_list': users_list,
    })


# Rekodi malipo ya faini — mtunzaji anaweka nambari ya risiti na njia ya malipo
@login_required
@librarian_required
# ----------------------------------------------------------------------
# View ya Rekodi Malipo ya Faini — Mtunzaji anarekodi malipo
# ----------------------------------------------------------------------
def record_fine_payment_view(request, fine_id):
    """
    Librarian fine payment handler.

    GET  : show the payment form page.
    POST : validate and record payment.
    """
    fine = get_object_or_404(Fine, pk=fine_id)

    if request.method != 'POST':
        return render(request, 'circulation/fine_payment.html', {'fine': fine})

    payment_method = request.POST.get('payment_method', 'cash')
    receipt_no = request.POST.get('receipt_no', '').strip()
    payment_amount_str = request.POST.get('payment_amount', '')
    # Extra fields per payment method
    phone_number    = request.POST.get('phone_number', '').strip()
    bank_name       = request.POST.get('bank_name', '').strip()
    bank_account_no = request.POST.get('bank_account_no', '').strip()
    card_holder     = request.POST.get('card_holder', '').strip()
    card_last4      = request.POST.get('card_last4', '').strip()
    card_expiry     = request.POST.get('card_expiry', '').strip()
    card_cvv        = request.POST.get('card_cvv', '').strip()

    # Validate payment amount
    try:
        payment_amount = Decimal(payment_amount_str) if payment_amount_str else Decimal('0')
    except (ValueError, TypeError):
        payment_amount = Decimal('0')

    if payment_amount <= 0:
        messages.error(request, 'Payment amount must be greater than 0')
        return redirect('user_fines', user_id=fine.user.pk)

    mobile_methods = {'mpesa', 'tigopesa', 'airtel_money', 'halopesa'}
    if payment_method in mobile_methods and phone_number and not re.match(r'^0\d{9}$', phone_number):
        messages.error(request, 'Phone number must be exactly 10 digits starting with 0 (e.g. 0712345678).')
        return redirect('user_fines', user_id=fine.user.pk)

    # Validate payment amount does not exceed remaining balance
    remaining_balance = fine.amount - fine.amount_paid
    if payment_amount > remaining_balance:
        messages.error(
            request,
            f'Payment amount TZS {payment_amount:,.0f} exceeds remaining balance TZS {remaining_balance:,.0f}. '
            f'Please enter correct amount not exceeding TZS {remaining_balance:,.0f}.'
        )
        return redirect('user_fines', user_id=fine.user.pk)

    # Build payment log entry (appended — never overwritten)
    MOBILE_METHODS = {'mpesa', 'tigopesa', 'airtel_money', 'halopesa'}
    CARD_METHODS   = {'visa', 'mastercard'}
    now_str = timezone.now().strftime('%d %b %Y %H:%M')
    log_entry = f"[{now_str}] {payment_method.upper()} TZS {payment_amount:,.0f}"

    if payment_method in MOBILE_METHODS and phone_number:
        log_entry += f" | Phone: {phone_number}"
    elif payment_method == 'bank_transfer':
        if bank_name:
            log_entry += f" | Bank: {bank_name}"
        if bank_account_no:
            log_entry += f" | Acct: {bank_account_no}"
        if receipt_no:
            log_entry += f" | Ref: {receipt_no}"
    elif payment_method in CARD_METHODS:
        if card_holder:
            log_entry += f" | Name: {card_holder}"
        if card_last4:
            log_entry += f" | Card: ****{card_last4}"
        if card_expiry:
            log_entry += f" | Exp: {card_expiry}"
        # CVV not stored for security

    # Accumulate payment
    fine.amount_paid += payment_amount
    fine.payment_method = payment_method
    fine.paid_at = timezone.now()
    # Append to log (never overwrite — preserves full payment history)
    fine.receipt_no = (fine.receipt_no + "\n" + log_entry).strip()

    # Determine paid status based on actual accumulated amount
    if fine.amount_paid >= fine.amount:
        fine.paid = True
    else:
        fine.paid = False

    fine.save()

    # Record revenue for this fine payment
    is_loss_fine = LossReport.objects.filter(loss_fine=fine).exists()
    is_damage_fine = DamageReport.objects.filter(damage_fine=fine).exists()
    if is_loss_fine:
        rev_type = 'loss'
    elif is_damage_fine:
        rev_type = 'damage'
    else:
        rev_type = 'overdue'
    _record_revenue(
        user=fine.user,
        account_type=rev_type,
        amount=payment_amount,
        description=f"Fine payment via {payment_method.upper()} (fine #{fine.pk})",
        reference_id=fine.pk,
        reference_table='fines',
        recorded_by=request.user,
    )

    # Determine SMS message based on payment status
    remaining_balance = fine.remaining_balance
    book_name = fine.transaction.copy.book.title if fine.transaction else "book"
    if fine.paid:
        sms_message = f"MSICT OLMS: Fine fully paid. TZS {fine.amount:,.0f} for '{book_name}' via {payment_method.upper()}. Thank you."
    else:
        sms_message = f"MSICT OLMS: Payment of TZS {payment_amount:,.0f} received for '{book_name}' fine (total TZS {fine.amount:,.0f}). Remaining balance: TZS {remaining_balance:,.0f}."

    # Send SMS notification
    try:
        notify_user(fine.user, sms_message, 'sms')
    except Exception as e:
        # Log error but don't fail the payment process
        log_audit(request.user, f"SMS failed for fine {fine.pk}: {str(e)}", request)

    log_audit(request.user, f"Fine {fine.pk} payment of TZS {payment_amount:,.0f} by {fine.user.username} via {payment_method}", request)

    if fine.paid:
        messages.success(request, f'Full payment recorded: {payment_method.upper()} — TZS {payment_amount:,.0f}. Fine fully paid!')
    else:
        messages.success(request, f'Partial payment: {payment_method.upper()} — TZS {payment_amount:,.0f} paid. Remaining: TZS {remaining_balance:,.0f}')

    try:
        from .receipt_utils import email_fine_receipt
        email_fine_receipt(fine)
    except Exception:
        pass

    return redirect('user_fines', user_id=fine.user.pk)


@login_required
@librarian_required
# ----------------------------------------------------------------------
# View ya Malipo ya Pamoja — Mtunzaji anarekodi malipo ya pamoja
# ----------------------------------------------------------------------
def bulk_fine_payment_view(request, user_id):
    user_obj = get_object_or_404(OLMSUser, pk=user_id)
    unpaid_fines = Fine.objects.filter(user=user_obj, paid=False)
    
    if request.method == 'POST':
        payment_method = request.POST.get('payment_method', 'cash')
        receipt_no = request.POST.get('receipt_no', '')
        payment_amount_str = request.POST.get('payment_amount', '')
        
        try:
            payment_amount = Decimal(payment_amount_str) if payment_amount_str else Decimal('0')
        except (ValueError, TypeError):
            payment_amount = Decimal('0')

        if payment_amount <= 0:
            messages.error(request, 'Payment amount must be greater than 0')
            return redirect('user_fines', user_id=user_id)

        # Validate payment amount does not exceed total remaining balance
        total_remaining_balance = sum(fine.remaining_balance for fine in unpaid_fines)
        if payment_amount > total_remaining_balance:
            messages.error(
                request,
                f'Payment amount TZS {payment_amount:,.0f} exceeds total remaining balance TZS {total_remaining_balance:,.0f}. '
                f'Please enter correct amount not exceeding TZS {total_remaining_balance:,.0f}.'
            )
            return redirect('user_fines', user_id=user_id)
        
        # Build detailed payment info based on method
        payment_details = []
        
        if payment_method in ['mpesa', 'tigopesa', 'airtel_money', 'halopesa']:
            phone = request.POST.get('phone_number', '').strip()
            if phone and not re.match(r'^0\d{9}$', phone):
                messages.error(request, 'Phone number must be exactly 10 digits starting with 0 (e.g. 0712345678).')
                return redirect('user_fines', user_id=user_id)
            if phone:
                payment_details.append(f"Phone: {phone}")
        elif payment_method == 'bank_transfer':
            bank = request.POST.get('bank_name', '')
            account = request.POST.get('account_number', '')
            ref = request.POST.get('bank_reference', '')
            if bank:
                payment_details.append(f"Bank: {bank}")
            if account:
                payment_details.append(f"Acc: {account}")
            if ref:
                payment_details.append(f"Ref: {ref}")
        elif payment_method in ['visa', 'mastercard']:
            card_num = request.POST.get('card_number', '')
            expiry = request.POST.get('card_expiry', '')
            card_name = request.POST.get('card_name', '')
            if card_num:
                masked = 'XXXX-' + card_num[-4:] if len(card_num) >= 4 else card_num
                payment_details.append(f"Card: {masked}")
            if expiry:
                payment_details.append(f"Exp: {expiry}")
            if card_name:
                payment_details.append(f"Name: {card_name}")
        elif payment_method == 'cash':
            payment_details.append(f"Received: TZS {payment_amount:,.0f}")
        
        # Build receipt info (receipt number now optional)
        full_receipt = receipt_no if receipt_no else "N/A"
        if payment_details:
            full_receipt += f" | {'; '.join(payment_details)}"
        
        # Distribute payment across fines (pay oldest fines first)
        remaining_payment = payment_amount
        fully_paid_count = 0
        
        for fine in unpaid_fines:
            if remaining_payment <= 0:
                break
            
            fine_remaining = fine.remaining_balance
            if fine_remaining <= 0:
                continue
            
            # Calculate payment for this fine
            if remaining_payment >= fine_remaining:
                # Can fully pay this fine
                payment_for_fine = fine_remaining
                fine.amount_paid += payment_for_fine
                fine.paid = True
                fine.amount_paid = fine.amount  # Cap at total
                fully_paid_count += 1
            else:
                # Partial payment for this fine
                payment_for_fine = remaining_payment
                fine.amount_paid += payment_for_fine
                fine.paid = False
            
            fine.payment_method = payment_method
            now_str = timezone.now().strftime('%d %b %Y %H:%M')
            log_line = f"[{now_str}] {payment_method.upper()} TZS {payment_for_fine:,.0f} | {full_receipt}"
            fine.receipt_no = (fine.receipt_no + '\n' + log_line).strip()
            fine.paid_at = timezone.now()
            fine.save()

            # Record revenue for this fine payment
            is_loss_fine = LossReport.objects.filter(loss_fine=fine).exists()
            is_damage_fine = DamageReport.objects.filter(damage_fine=fine).exists()
            if is_loss_fine:
                rev_type = 'loss'
            elif is_damage_fine:
                rev_type = 'damage'
            else:
                rev_type = 'overdue'
            _record_revenue(
                user=fine.user,
                account_type=rev_type,
                amount=payment_for_fine,
                description=f"Bulk fine payment via {payment_method.upper()} (fine #{fine.pk})",
                reference_id=fine.pk,
                reference_table='fines',
                recorded_by=request.user,
            )

            remaining_payment -= payment_for_fine
        
        # Determine SMS message based on payment status
        total_remaining = sum(f.remaining_balance for f in Fine.objects.filter(user=user_obj, paid=False))
        if total_remaining == 0:
            sms_message = f"MSICT OLMS: All fines fully paid. TZS {payment_amount:,.0f} via {payment_method.upper()}. Thank you."
        else:
            sms_message = f"MSICT OLMS: Payment of TZS {payment_amount:,.0f} received for fines. Remaining balance: TZS {total_remaining:,.0f}."
        
        # Send SMS notification
        try:
            notify_user(user_obj, sms_message, 'sms')
        except Exception as e:
            # Log error but don't fail the payment process
            log_audit(request.user, f"SMS failed for bulk payment {user_obj.pk}: {str(e)}", request)
        
        log_audit(request.user, f"Bulk payment of TZS {payment_amount:,.0f} for {user_obj.username} via {payment_method}", request)
        
        if total_remaining == 0:
            messages.success(request, f'Full payment recorded: {payment_method.upper()} - TZS {payment_amount:,.0f}. All fines fully paid!')
        else:
            messages.success(request, f'Partial payment recorded: {payment_method.upper()} - TZS {payment_amount:,.0f}. {fully_paid_count} fine(s) fully paid. Remaining: TZS {total_remaining:,.0f}')
        
        try:
            from .receipt_utils import email_fine_receipt
            for fine in Fine.objects.filter(user=user_obj, paid_at__isnull=False).order_by('-paid_at')[:fully_paid_count or 1]:
                email_fine_receipt(fine)
        except Exception:
            pass

        return redirect('user_fines', user_id=user_id)
    
    return redirect('user_fines', user_id=user_id)


@login_required
@librarian_required
# ----------------------------------------------------------------------
# View ya Desk ya Circulation — Mtunzaji anaona desk ya jumla
# ----------------------------------------------------------------------
def circulation_desk_view(request):
    return render(request, 'circulation/circulation_desk.html')


@login_required
# ----------------------------------------------------------------------
# View ya Mikopo ya MSICT — Mwanachama anaona mikopo yake ya MSICT
# ----------------------------------------------------------------------
def member_msict_borrowings_view(request):
    """Member view for MSICT borrowings - history, pending, active"""
    user = request.user

    # Active borrowings (borrowed or overdue only - lost books are separate) - filter out expired special softcopy links and missing books
    active_borrows = BorrowingTransaction.objects.filter(
        user=user,
        status__in=['borrowed', 'overdue'],
        copy__book__isnull=False,
    ).exclude(
        copy__copy_type='softcopy',
        copy__access_type='borrow',
        due_date__lt=timezone.now(),
    ).select_related('copy__book').order_by('-borrow_date')

    # Lost borrowings (books reported lost with active loss reports - pending or confirmed)
    # Resolved/dismissed reports are historical records shown in my_loss_reports page only
    lost_borrows = BorrowingTransaction.objects.filter(
        user=user,
        status='lost',
        copy__book__isnull=False,
        loss_report__status__in=['pending', 'confirmed'],
    ).select_related('copy__book', 'loss_report', 'loss_report__loss_fine').order_by('-borrow_date')

    expired_softcopies = BorrowingTransaction.objects.filter(
        user=user,
        copy__copy_type='softcopy',
        copy__access_type='borrow',
        status='borrowed',
        due_date__lt=timezone.now(),
        copy__book__isnull=False,
    ).select_related('copy__book').order_by('-borrow_date')

    # Borrow history (returned or lost) - filter out missing books
    borrow_history = BorrowingTransaction.objects.filter(
        user=user, status__in=['returned', 'lost'], copy__book__isnull=False
    ).select_related('copy__book').order_by('-return_date')[:50]

    # Pending borrow requests - include both copy-based and temp_book-based
    pending_requests = BorrowRequest.objects.filter(
        user=user, status='pending'
    ).select_related('copy__book', 'temp_book').order_by('-request_date')

    # Approved requests — waiting for librarian to issue the physical copy
    # Softcopy requests are excluded — they auto-process via payment, no issuing needed
    approved_requests = BorrowRequest.objects.filter(
        user=user, status='approved'
    ).exclude(
        copy__copy_type='softcopy'
    ).select_related('copy__book', 'temp_book').order_by('-request_date')

    # Rejected/Cancelled/Deleted requests - filter out missing books
    rejected_requests = BorrowRequest.objects.filter(
        user=user, status__in=['rejected', 'cancelled', 'deleted']
    ).select_related('copy__book', 'temp_book').order_by('-request_date')[:20]

    # Current reservations - filter out missing books
    reservations = Reservation.objects.filter(
        user=user, status='pending', book__isnull=False
    ).select_related('book').order_by('-created_at')

    # Reservation history
    reservation_history = Reservation.objects.filter(
        user=user, status__in=['fulfilled', 'cancelled', 'expired']
    ).select_related('book').order_by('-created_at')[:20]

    # Unpaid fines - exclude fines from renewed transactions (renewal doesn't incur fines)
    unpaid_fines = Fine.objects.filter(
        transaction__user=user, paid=False, transaction__renewed_count=0
    ).select_related('transaction__copy__book')

    # Get fines for overdue transactions
    overdue_tx_ids = active_borrows.filter(status='overdue').values_list('id', flat=True)
    overdue_fines = Fine.objects.filter(transaction_id__in=overdue_tx_ids)

    # Build fine info dictionary for each transaction (for softcopy return check)
    tx_fines = {}
    for fine in overdue_fines:
        if fine.transaction_id not in tx_fines:
            tx_fines[fine.transaction_id] = {
                'amount': fine.amount,
                'remaining': fine.remaining_balance,
                'paid': fine.paid,
                'amount_paid': fine.amount_paid,
            }

    context = {
        'active_borrows': active_borrows,
        'lost_borrows': lost_borrows,
        'expired_softcopies': expired_softcopies,
        'borrow_history': borrow_history,
        'pending_requests': pending_requests,
        'approved_requests': approved_requests,
        'rejected_requests': rejected_requests,
        'reservations': reservations,
        'reservation_history': reservation_history,
        'unpaid_fines': unpaid_fines,
        'tx_fines': tx_fines,
    }
    mark_badge_viewed(request.user, 'member_active_borrowings')
    return render(request, 'circulation/member_msict_borrowings.html', context)


@login_required
# ----------------------------------------------------------------------
# View ya Mikopo ya ILL — Mwanachama anaona mikopo yake ya ILL
# ----------------------------------------------------------------------
def member_ill_borrowings_view(request):
    """Member view for ILL borrowings - history and pending requests"""
    from acquisitions.models import ILLRequest
    user = request.user

    # All ILL requests grouped by status
    pending_ill = ILLRequest.objects.filter(
        user=user, status='pending'
    ).order_by('-request_date')

    sent_ill = ILLRequest.objects.filter(
        user=user, status='sent'
    ).order_by('-request_date')

    fulfilled_ill = ILLRequest.objects.filter(
        user=user, status='fulfilled'
    ).order_by('-request_date')

    received_ill = ILLRequest.objects.filter(
        user=user, status='received'
    ).order_by('-request_date')

    cancelled_ill = ILLRequest.objects.filter(
        user=user, status='cancelled'
    ).order_by('-request_date')[:20]

    # ILL history (all statuses)
    ill_history = ILLRequest.objects.filter(
        user=user
    ).order_by('-request_date')[:50]

    context = {
        'pending_ill': pending_ill,
        'sent_ill': sent_ill,
        'fulfilled_ill': fulfilled_ill,
        'received_ill': received_ill,
        'cancelled_ill': cancelled_ill,
        'ill_history': ill_history,
    }
    mark_badge_viewed(request.user, 'member_ill_pending')
    return render(request, 'circulation/member_ill_borrowings.html', context)


# Maktaba ya kidijitali — vitabu vya PDF ambavyo mwanachama amekopa au vya bure
@login_required
# ----------------------------------------------------------------------
# View ya Maktaba ya Vitabu vya Kidijitali — Mwanachama anaona softcopies
# ----------------------------------------------------------------------
def softcopy_library_view(request):
    query = request.GET.get('q', '').strip()
    category_id = request.GET.get('category', '')
    sc_type = request.GET.get('type', '')  # 'free' | 'borrow' | ''

    free_book_ids = BookCopy.objects.filter(
        copy_type='softcopy', access_type='free'
    ).values('book_id')
    special_book_ids = BookCopy.objects.filter(
        copy_type='softcopy', access_type='borrow'
    ).values('book_id')

    books_qs = Book.objects.select_related('category').prefetch_related('copies')
    if sc_type == 'free':
        books_qs = books_qs.filter(pk__in=free_book_ids)
    elif sc_type == 'borrow':
        books_qs = books_qs.filter(pk__in=special_book_ids)
    else:
        books_qs = books_qs.filter(
            Q(pk__in=free_book_ids) | Q(pk__in=special_book_ids)
        )

    if query:
        books_qs = books_qs.filter(
            Q(title__icontains=query) | Q(author__icontains=query) | Q(isbn__icontains=query)
        )
    if category_id:
        books_qs = books_qs.filter(category_id=category_id)

    books_qs = books_qs.order_by('title')

    user = request.user
    user_can_borrow = True
    borrow_block_reason = ''
    active_borrow_copy_ids = set()
    pending_copy_ids = set()

    if user.has_overdue():
        user_can_borrow = False
        borrow_block_reason = 'overdue'
    elif user.has_unpaid_fines():
        user_can_borrow = False
        borrow_block_reason = 'fines'
    elif user.active_borrows_count() >= getattr(settings, 'MAX_COPIES_PER_BORROW', 3):
        user_can_borrow = False
        borrow_block_reason = 'limit'

    active_borrow_copy_ids = set()
    active_borrow_tokens = {}
    for tx in BorrowingTransaction.objects.filter(
        user=user, status__in=['borrowed', 'overdue'], copy__copy_type='softcopy'
    ).select_related('copy'):
        active_borrow_copy_ids.add(tx.copy_id)
        active_borrow_tokens[tx.copy_id] = str(tx.access_token)
    # Softcopies are auto-issued instantly — no pending BorrowRequest state needed
    pending_copy_ids = set()

    from catalog.models import Category
    categories = Category.objects.all()
    total_free = BookCopy.objects.filter(copy_type='softcopy', access_type='free').values('book_id').distinct().count()
    total_special = BookCopy.objects.filter(copy_type='softcopy', access_type='borrow').values('book_id').distinct().count()

    return render(request, 'circulation/softcopy_library.html', {
        'books': books_qs,
        'query': query,
        'category_id': category_id,
        'sc_type': sc_type,
        'categories': categories,
        'user_can_borrow': user_can_borrow,
        'borrow_block_reason': borrow_block_reason,
        'active_borrow_copy_ids': active_borrow_copy_ids,
        'active_borrow_tokens': active_borrow_tokens,
        'pending_copy_ids': pending_copy_ids,
        'total_free': total_free,
        'total_special': total_special,
    })


# Orodha ya uhifadhi wote — mtunzaji anaweza kuchuja kwa hali (pending, fulfilled...)
@login_required
@librarian_required
# ----------------------------------------------------------------------
# View ya Orodha ya Uhifadhi — Mtunzaji anaona uhifadhi wote
# ----------------------------------------------------------------------
def reservation_list_view(request):
    status_filter = request.GET.get('status', 'pending')
    query = request.GET.get('q', '')

    # Auto-expire any pending/notified reservations that have passed 14 days
    stale = Reservation.objects.filter(
        status__in=['pending', 'notified'],
        expires_at__lt=timezone.now()
    ).select_related('user', 'book')
    for res in stale:
        res.status = 'expired'
        res.save(update_fields=['status'])
        exp_msg = (
            f"MSICT OLMS: Your reservation for '{res.book.title}' has expired "
            f"(14 days elapsed). Please re-reserve if you still need the book."
        )
        notify_user(res.user, exp_msg, 'sms')
        notify_user(res.user, exp_msg, 'email', subject='Reservation Expired')

    reservations = Reservation.objects.select_related('user', 'book').order_by('book__title', 'position')

    if status_filter:
        reservations = reservations.filter(status=status_filter)
    if query:
        reservations = reservations.filter(
            Q(user__first_name__icontains=query) |
            Q(user__surname__icontains=query) |
            Q(user__username__icontains=query) |
            Q(book__title__icontains=query)
        )

    counts = {
        'pending': Reservation.objects.filter(status='pending').count(),
        'notified': Reservation.objects.filter(status='notified').count(),
        'fulfilled': Reservation.objects.filter(status='fulfilled').count(),
        'cancelled': Reservation.objects.filter(status='cancelled').count(),
        'expired': Reservation.objects.filter(status='expired').count(),
    }

    mark_badge_viewed(request.user, 'pending_reservations')
    return render(request, 'circulation/reservation_list.html', {
        'reservations': reservations,
        'status_filter': status_filter,
        'query': query,
        'counts': counts,
        'now': timezone.now(),
    })


# ── Renew Reservation ────────────────────────────────────────────────────────
@login_required
@librarian_required
@require_POST
# ----------------------------------------------------------------------
# View ya Ongeza Muda wa Uhifadhi — Mtunzaji anaongeza muda wa uhifadhi
# ----------------------------------------------------------------------
def renew_reservation_view(request, reservation_id):
    """POST-only — protected by CSRF + librarian role decorator."""
    res = get_object_or_404(Reservation, pk=reservation_id)
    reservation_days = int(_pref('RESERVATION_EXPIRY_DAYS', 14))
    new_expires = timezone.now() + timedelta(days=reservation_days)
    res.expires_at = new_expires
    res.status = 'pending'
    res.save(update_fields=['expires_at', 'status'])
    renew_msg = (
        f"MSICT OLMS: Your reservation for '{res.book.title}' has been renewed by the librarian. "
        f"New expiry date: {new_expires.strftime('%d %b %Y')}. "
        f"You will be notified when it is your turn."
    )
    notify_user(res.user, renew_msg, 'sms')
    notify_user(res.user, renew_msg, 'email', subject=f'Reservation Renewed — {res.book.title}')
    log_audit(request.user, f"Renewed reservation #{res.pk} for '{res.book.title}' by {res.user.get_full_name()}", request)
    messages.success(request, f"Reservation for '{res.book.title}' renewed for 14 more days. Member notified.")
    return redirect('reservation_list')


# ── Return History ───────────────────────────────────────────────────────────
@login_required
@librarian_required
# ----------------------------------------------------------------------
# View ya Historia ya Kurudisha — Mtunzaji anaona historia ya kurudisha
# ----------------------------------------------------------------------
def return_history_view(request):
    """All returned transactions (hard + soft) descending by return date, with filtering."""
    qs = (
        BorrowingTransaction.objects.filter(status='returned')
        .select_related('user', 'copy__book', 'approved_by')
        .order_by('-return_date')
    )

    copy_type_filter = request.GET.get('copy_type', '')
    query            = request.GET.get('q', '')

    if copy_type_filter:
        qs = qs.filter(copy__copy_type=copy_type_filter)
    if query:
        qs = qs.filter(
            Q(user__first_name__icontains=query) |
            Q(user__surname__icontains=query)    |
            Q(user__username__icontains=query)   |
            Q(user__army_no__icontains=query)    |
            Q(copy__book__title__icontains=query)|
            Q(copy__accession_no__icontains=query)
        )

    total_returned   = BorrowingTransaction.objects.filter(status='returned').count()
    hard_returned    = BorrowingTransaction.objects.filter(status='returned', borrow_type='hardcopy').count()
    soft_returned    = BorrowingTransaction.objects.filter(status='returned', borrow_type='softcopy').count()

    return render(request, 'circulation/return_history.html', {
        'transactions':      qs,
        'copy_type_filter':  copy_type_filter,
        'query':             query,
        'total_returned':    total_returned,
        'hard_returned':     hard_returned,
        'soft_returned':     soft_returned,
    })


# ── All Borrowings (librarian full view) ─────────────────────────────────────
@login_required
@librarian_required
# ----------------------------------------------------------------------
# View ya Orodha ya Mikopo Yote — Mtunzaji anaona mikopo yote
# ----------------------------------------------------------------------
def all_borrowings_view(request):
    """All borrowing transactions across all statuses with filtering and day calculations."""
    from django.utils import timezone as tz
    _auto_mark_overdue()  # Catch any borrowed+past-due not yet marked by cron

    qs = (
        BorrowingTransaction.objects.all()
        .select_related('user', 'copy__book', 'approved_by')
        .order_by('-borrow_date')
    )

    status_filter    = request.GET.get('status', '')
    copy_type_filter = request.GET.get('copy_type', '')
    query            = request.GET.get('q', '')

    if status_filter:
        if status_filter == 'overdue':
            # Exclude softcopies from overdue filter since they never go overdue (matching count logic)
            qs = qs.filter(status='overdue').exclude(copy__copy_type='softcopy')
        else:
            qs = qs.filter(status=status_filter)
    if copy_type_filter:
        qs = qs.filter(copy__copy_type=copy_type_filter)
    if query:
        qs = qs.filter(
            Q(user__first_name__icontains=query) |
            Q(user__surname__icontains=query)    |
            Q(user__username__icontains=query)   |
            Q(user__army_no__icontains=query)    |
            Q(copy__book__title__icontains=query)|
            Q(copy__accession_no__icontains=query)
        )

    # Calculate counts based on the filtered queryset (without status filter for accurate totals)
    # Exclude softcopies from overdue count since they never go overdue (matching _auto_mark_overdue logic)
    base_qs = BorrowingTransaction.objects.all()
    if copy_type_filter:
        base_qs = base_qs.filter(copy__copy_type=copy_type_filter)
    if query:
        base_qs = base_qs.filter(
            Q(user__first_name__icontains=query) |
            Q(user__surname__icontains=query)    |
            Q(user__username__icontains=query)   |
            Q(user__army_no__icontains=query)    |
            Q(copy__book__title__icontains=query)|
            Q(copy__accession_no__icontains=query)
        )

    counts = {
        'all':      base_qs.count(),
        'borrowed': base_qs.filter(status='borrowed').count(),
        'overdue':  base_qs.filter(status='overdue').exclude(copy__copy_type='softcopy').count(),
        'returned': base_qs.filter(status='returned').count(),
        'lost':     base_qs.filter(status='lost').count(),
    }

    # Debug: log the actual counts and queryset size
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"All Borrowings counts: {counts}")
    logger.info(f"Queryset size: {qs.count()}")
    logger.info(f"Status filter: {status_filter}, Copy type filter: {copy_type_filter}, Query: {query}")

    # Build fine info dictionary for each transaction
    tx_ids = qs.values_list('id', flat=True)
    fines = Fine.objects.filter(transaction_id__in=tx_ids)
    tx_fines = {}
    for fine in fines:
        if fine.transaction_id not in tx_fines:
            tx_fines[fine.transaction_id] = {
                'amount': fine.amount,
                'remaining': fine.remaining_balance,
                'paid': fine.paid,
                'amount_paid': fine.amount_paid,
            }

    return render(request, 'circulation/all_borrowings.html', {
        'transactions':      qs,
        'status_filter':     status_filter,
        'copy_type_filter':  copy_type_filter,
        'query':             query,
        'counts':            counts,
        'tx_fines':          tx_fines,
        'now':               tz.now(),
    })


@login_required
@librarian_required
@require_POST
def delete_borrowing_view(request, tx_id):
    """
    Librarian-only: permanently delete a borrowing transaction record.
    Safety guards:
      - Cannot delete ACTIVE (borrowed/overdue) transactions — must be returned first.
      - Cannot delete if there are unpaid fines — financial integrity.
      - Cannot delete if a loss report or damage report is attached — audit trail.
    """
    tx = get_object_or_404(
        BorrowingTransaction.objects.select_related('copy__book', 'user'),
        pk=tx_id
    )
    book_title = tx.copy.book.title
    member_name = tx.user.get_full_name() or tx.user.username

    # ── Guard 1: Cannot delete active borrows ───────────────────────────────
    if tx.status in ('borrowed', 'overdue'):
        messages.error(
            request,
            f'⚠️ Cannot delete an active borrowing for "{book_title}" — '
            f'the book is still checked out by {member_name}. '
            f'Process a return first.'
        )
        return _safe_redirect(request, 'all_borrowings')

    # ── Guard 2: Cannot delete if unpaid fines exist ─────────────────────────
    unpaid_fines = Fine.objects.filter(transaction=tx, paid=False)
    if unpaid_fines.exists():
        total_remaining = sum(f.remaining_balance for f in unpaid_fines)
        messages.error(
            request,
            f'⚠️ Cannot delete — this transaction has unpaid fines totalling '
            f'TZS {total_remaining:,.0f}. Settle all fines before deleting.'
        )
        return _safe_redirect(request, 'all_borrowings')

    # ── Guard 3: Cannot delete if active loss/damage report is attached ────────
    if LossReport.objects.filter(transaction=tx, status__in=['pending', 'confirmed']).exists():
        messages.error(
            request,
            f'⚠️ Cannot delete — there is an active Loss Report for "{book_title}". '
            f'Resolve or dismiss the loss report first.'
        )
        return _safe_redirect(request, 'all_borrowings')

    if DamageReport.objects.filter(transaction=tx, status__in=['pending', 'confirmed']).exists():
        messages.error(
            request,
            f'⚠️ Cannot delete — there is an active Damage Report for "{book_title}". '
            f'Resolve or dismiss the damage report first.'
        )
        return _safe_redirect(request, 'all_borrowings')

    # All guards passed — safe to delete
    log_audit(
        request.user,
        f'Deleted borrowing record #{tx_id} — "{book_title}" borrowed by {member_name} '
        f'(returned: {tx.return_date.strftime("%d %b %Y") if tx.return_date else "N/A"})',
        request
    )
    tx.delete()
    messages.success(request, f'Borrowing record for "{book_title}" has been deleted.')
    return _safe_redirect(request, 'all_borrowings')


def _safe_redirect(request, fallback_url_name):
    """Redirect back to the referring page if it is a local URL, otherwise use fallback."""
    from urllib.parse import urlparse
    referer = request.META.get('HTTP_REFERER', '')
    if referer:
        parsed = urlparse(referer)
        # Only follow the referer if it points to the same host (open-redirect guard)
        if not parsed.netloc or parsed.netloc == request.get_host():
            local_path = parsed.path
            if parsed.query:
                local_path += '?' + parsed.query
            return redirect(local_path or '/')
    return redirect(fallback_url_name)


# ── Loss Report Views ─────────────────────────────────────────────────────────

@login_required
# ----------------------------------------------------------------------
# View ya Ripoti ya Kupoteza — Mwanachama anaripoti kitabu kilichopotea
# ----------------------------------------------------------------------
def report_loss_view(request, transaction_id):
    """Member submits a loss report for one of their active/overdue borrowed books."""
    tx = get_object_or_404(
        BorrowingTransaction,
        pk=transaction_id,
        user=request.user,
        status__in=['borrowed', 'overdue'],
        borrow_type='hardcopy',
    )

    # Prevent duplicate reports
    if LossReport.objects.filter(transaction=tx).exists():
        messages.warning(request, 'A loss report has already been submitted for this book.')
        return redirect('member_msict_borrowings')

    if request.method == 'POST':
        description = request.POST.get('description', '').strip()
        circumstances = request.POST.get('circumstances', '').strip()
        date_noticed_raw = request.POST.get('date_noticed', '').strip()
        last_known_location = request.POST.get('last_known_location', '').strip()
        authority_reported = request.POST.get('authority_reported') == 'on'
        authority_reference = request.POST.get('authority_reference', '').strip()

        if not description:
            messages.error(request, 'Please provide a description of how the book was lost.')
        else:
            from datetime import date as _date
            date_noticed = None
            if date_noticed_raw:
                try:
                    date_noticed = _date.fromisoformat(date_noticed_raw)
                except ValueError:
                    pass
            report = LossReport.objects.create(
                transaction=tx,
                user=request.user,
                description=description,
                circumstances=circumstances,
                date_noticed=date_noticed,
                last_known_location=last_known_location,
                authority_reported=authority_reported,
                authority_reference=authority_reference,
            )
            # Immediately mark transaction and copy as lost
            tx.status = 'lost'
            tx.save(update_fields=['status'])
            tx.copy.status = 'lost'
            tx.copy.save(update_fields=['status'])
            # Notify librarians
            from accounts.models import OLMSUser as _User
            librarians = _User.objects.filter(role__in=['librarian', 'admin'], is_active=True)
            for lib in librarians:
                notify_user(
                    lib,
                    f"Loss report submitted by {request.user.get_full_name()} ({request.user.army_no}) "
                    f"for book: '{tx.copy.book.title}' (Acc: {tx.copy.accession_no}). "
                    f"Please review and confirm.",
                    'email',
                    subject='Loss Report – MSICT OLMS',
                    is_security_alert=False,
                    message_type='loss_report',
                )
            # Notify the member
            notify_user(
                request.user,
                f"MSICT OLMS: Your loss report for '{tx.copy.book.title}' has been submitted. "
                f"Ref: LR-{report.pk}. A librarian will review it shortly.",
                'sms',
                message_type='loss_report',
            )
            log_audit(
                request.user,
                f"Loss report submitted for '{tx.copy.book.title}' (Acc: {tx.copy.accession_no})",
                request,
            )
            messages.success(request, f'Loss report submitted successfully. Reference: LR-{report.pk}.')
            return redirect('member_msict_borrowings')

    return render(request, 'circulation/report_loss.html', {'tx': tx})


@login_required
@librarian_required
# ----------------------------------------------------------------------
# View ya Orodha ya Ripoti za Hasara — Mtunzaji anaona ripoti zote
# ----------------------------------------------------------------------
@login_required
@librarian_required
def loss_report_list_view(request):
    """Librarian views all loss reports."""
    status_filter = request.GET.get('status', '')
    qs = LossReport.objects.select_related(
        'user__rank', 'transaction__copy__book', 'reviewed_by', 'loss_fine'
    ).prefetch_related('transaction__fines').order_by('reported_at')
    if status_filter:
        qs = qs.filter(status=status_filter)

    reports_with_counts = []
    for seq, report in enumerate(qs, start=1):
        overdue_fine = None
        if report.transaction:
            overdue_qs = report.transaction.fines.filter(reason__icontains='Overdue')
            if report.loss_fine_id:
                overdue_qs = overdue_qs.exclude(id=report.loss_fine_id)
            overdue_fine = overdue_qs.first()

        report.overdue_count = 1 if overdue_fine else 0
        report.overdue_fine = overdue_fine

        loss_amount    = report.loss_fine.amount            if report.loss_fine    else Decimal('0')
        overdue_amount = overdue_fine.amount                if overdue_fine        else Decimal('0')
        loss_rem       = report.loss_fine.remaining_balance if report.loss_fine    else Decimal('0')
        overdue_rem    = overdue_fine.remaining_balance     if overdue_fine        else Decimal('0')

        report.total_amount    = loss_amount    + overdue_amount
        report.total_remaining = loss_rem       + overdue_rem

        # Assign a stable, human-readable sequential reference number (LR-1, LR-2 …)
        report.seq_no = seq

        reports_with_counts.append(report)

    # Group reports by member — order is preserved from the sorted queryset above
    from collections import OrderedDict
    grouped = OrderedDict()
    for r in reports_with_counts:
        key = r.user.pk if r.user else f'user-{r.pk}'
        if key not in grouped:
            grouped[key] = {
                'user': r.user,
                'reports': [],
            }
        grouped[key]['reports'].append(r)

    grouped_reports = list(grouped.values())

    mark_badge_viewed(request.user, 'pending_loss_reports')
    return render(request, 'circulation/loss_report_list.html', {
        'reports': reports_with_counts,
        'grouped_reports': grouped_reports,
        'status_filter': status_filter,
    })


@login_required
@librarian_required
@require_POST
# ----------------------------------------------------------------------
# View ya Thibitisha Hasara — Mtunzaji anathibitisha au kataa ripoti
# ----------------------------------------------------------------------
def confirm_loss_view(request, report_id):
    """Librarian confirms loss: marks copy lost, creates a loss fine, updates report status."""
    report = get_object_or_404(LossReport, pk=report_id, status='pending')
    action = request.POST.get('action', 'confirm')
    notes = request.POST.get('librarian_notes', '').strip()
    copy = report.transaction.copy
    book = copy.book

    # Use book's lost_fine as default if not provided
    loss_fine_amount = request.POST.get('loss_fine_amount', '').strip()
    if loss_fine_amount == '':
        loss_fine_amount = str(book.lost_fine or 0)
    loss_fine_amount = Decimal(loss_fine_amount or '0')

    report.reviewed_by = request.user
    report.reviewed_at = timezone.now()
    report.librarian_notes = notes

    if action == 'dismiss':
        # Restore transaction and copy to active status
        tx = report.transaction
        if tx.status == 'lost':
            if timezone.now() > tx.due_date and tx.copy.copy_type != 'softcopy':
                tx.status = 'overdue'
            else:
                tx.status = 'borrowed'
            tx.save(update_fields=['status'])
        if copy.status == 'lost':
            copy.status = 'borrowed'
            copy.save(update_fields=['status'])
        report.status = 'dismissed'
        report.save()
        notify_user(
            report.user,
            f"MSICT OLMS: Your loss report (LR-{report.pk}) for '{report.transaction.copy.book.title}' "
            f"has been dismissed. Contact the library for more information.",
            'sms',
            message_type='loss_report',
        )
        messages.info(request, f'Loss report LR-{report.pk} dismissed.')
        log_audit(request.user, f"Dismissed loss report LR-{report.pk}", request)
    else:
        # Mark copy as lost
        copy.status = 'lost'
        copy.save(update_fields=['status'])

        # Mark transaction as lost (override overdue status if present)
        tx = report.transaction
        if tx.status != 'returned':
            tx.status = 'lost'
            tx.save(update_fields=['status'])

        # Create loss fine if amount provided
        fine = None
        if loss_fine_amount > 0:
            fine = Fine.objects.create(
                user=report.user,
                transaction=tx,
                amount=loss_fine_amount,
                reason=f"Lost book fine – '{copy.book.title}' (Acc: {copy.accession_no})",
                paid=False,
            )
            report.loss_fine = fine
        else:
            # Check if there's already a loss fine for this transaction (e.g., manually created)
            existing_loss_fine = Fine.objects.filter(
                transaction=tx,
                reason__icontains='loss'
            ).first()
            if existing_loss_fine:
                report.loss_fine = existing_loss_fine
                fine = existing_loss_fine

        # ── Concurrent overdue fine — based on REPORT DATE vs due date ──────
        # Rule:
        #   • Reported WITHIN loan period (reported_at <= due_date):
        #     → Only the loss fine applies. User reported on time; no overdue charge.
        #   • Reported AFTER loan period expired (reported_at > due_date):
        #     → Both the loss fine AND an overdue fine apply.
        #     → Overdue days = due_date → reported_at (fair: not penalised for slow confirmation).
        overdue_fine = None
        overdue_amount = Decimal('0')
        days_late = 0
        reported_past_due = report.reported_at > tx.due_date
        if reported_past_due:
            fine_per_day_val = Decimal(str(_pref('FINE_PER_DAY', 1000)))
            days_late = max(1, (report.reported_at - tx.due_date).days)
            overdue_amount = days_late * fine_per_day_val

            # Find existing overdue fine for this transaction (mark_overdue may have created one)
            existing_overdue = Fine.objects.filter(
                transaction=tx,
                reason__icontains='Overdue',
            )
            if fine:  # exclude the just-created loss fine
                existing_overdue = existing_overdue.exclude(id=fine.id)
            overdue_fine = existing_overdue.first()

            if overdue_fine:
                if not overdue_fine.paid:
                    overdue_fine.amount = overdue_amount
                    overdue_fine.reason = f"Overdue fine for '{copy.book.title}' ({days_late} days)"
                    overdue_fine.save(update_fields=['amount', 'reason'])
            else:
                overdue_fine = Fine.objects.create(
                    user=report.user,
                    transaction=tx,
                    amount=overdue_amount,
                    reason=f"Overdue fine for '{copy.book.title}' ({days_late} days)",
                    paid=False,
                )

        report.status = 'confirmed'
        report.save()

        # Build notification — combine both fines when applicable
        due_str = tx.due_date.strftime('%d %b %Y')
        if loss_fine_amount > 0 and overdue_fine:
            notify_body = (
                f"A LOSS FINE of TZS {loss_fine_amount:,.0f} has been raised. "
                f"Your loan expired on {due_str} and the book was reported lost {days_late} day(s) after the due date, "
                f"so an OVERDUE FINE of TZS {overdue_amount:,.0f} also applies. "
                f"Total outstanding: TZS {loss_fine_amount + overdue_amount:,.0f}. "
                f"Please pay at the library."
            )
            msg_type = 'loss_fine'
        elif loss_fine_amount > 0:
            notify_body = (
                f"A LOSS FINE of TZS {loss_fine_amount:,.0f} has been raised. "
                f"The loss was reported within your loan period (due: {due_str}), "
                f"so no overdue fine applies — only the loss fine. "
                f"Please pay at the library."
            )
            msg_type = 'loss_fine'
        else:
            notify_body = "No fine has been raised at this time."
            msg_type = 'loss_report'

        notify_user(
            report.user,
            f"MSICT OLMS: LOSS CONFIRMED (LR-{report.pk}) - '{copy.book.title}'. {notify_body}",
            'sms',
            message_type=msg_type,
            priority='high',
        )
        notify_user(
            report.user,
            f"MSICT OLMS: LOSS CONFIRMED (LR-{report.pk}) - '{copy.book.title}'. {notify_body}",
            'email',
            subject='Loss Report Confirmed – Fines Notice – MSICT OLMS',
            message_type=msg_type,
            priority='high',
        )
        flash_msg = f'Loss confirmed for LR-{report.pk}. Copy marked lost.'
        if loss_fine_amount > 0:
            flash_msg += f' Loss fine TZS {loss_fine_amount:,.0f} created.'
        if overdue_fine:
            flash_msg += f' Overdue fine TZS {overdue_amount:,.0f} also created ({days_late} day(s)).'
        messages.success(request, flash_msg)
        log_audit(request.user, f"Confirmed loss report LR-{report.pk} for '{copy.book.title}'", request)

    return redirect('loss_report_list')


@login_required
@librarian_required
@require_POST
# ----------------------------------------------------------------------
# View ya Rejesha Kitabu — Mtunzaji anarejesha kitabu kilichopotea
# ----------------------------------------------------------------------
def recover_book_view(request, report_id):
    """Librarian marks a lost book as physically recovered.

    On recovery:
      - The book goes back to ACTIVE borrowing (not returned).
      - The loss fine is cancelled (deleted if unpaid).
      - The system recalculates overdue from the original borrow date:
        * If past due_date → status='overdue', overdue fine created/updated.
        * If within loan period → status='borrowed' (active).
      - Any existing overdue fine (from before the loss report) is kept.
    """
    from decimal import Decimal as _Dec

    report = get_object_or_404(LossReport, pk=report_id)
    if report.status not in ('pending', 'confirmed', 'resolved'):
        messages.warning(request, f'LR-{report.pk} cannot be recovered from status "{report.get_status_display()}".')
        return redirect('loss_report_list')

    copy = report.transaction.copy
    tx = report.transaction
    notes = request.POST.get('recovery_notes', '').strip()
    now = timezone.now()

    # ── Special case: fine already paid (resolved) → copy goes back to catalog ──
    fine_already_paid = report.status == 'resolved'

    if fine_already_paid:
        # Loss fine was paid; book was written off. Physical recovery puts it
        # back in the catalog as a fresh available copy (new borrowing possible).
        copy.status = 'available'
        copy.save(update_fields=['status'])
        report.status = 'resolved'
        report.reviewed_by = request.user
        report.reviewed_at = now
        recovery_note = notes or 'Book physically recovered after fine payment — returned to catalog.'
        report.librarian_notes = (report.librarian_notes + '\n[RECOVERED→CATALOG] ' + recovery_note).strip()
        report.save()
        log_audit(request.user, f"Recovered lost copy '{copy.accession_no}' (LR-{report.pk}) → back to catalog", request)
        messages.success(request, f"LR-{report.pk}: Copy '{copy.accession_no}' recovered — returned to catalog as available.")
        return redirect('lost_damaged_copies')

    # ── 1. Cancel the loss fine ──────────────────────────────────────────
    # Delete if fully unpaid; if partially paid, keep the record but it's
    # no longer tracked as an active loss fine (report becomes 'resolved').
    loss_fine_pk = report.loss_fine_id
    if report.loss_fine:
        if not report.loss_fine.paid and report.loss_fine.amount_paid == 0:
            report.loss_fine.delete()
            report.loss_fine = None
        # If partially paid or fully paid, keep the fine record as-is
        # (it won't appear in active loss reports since report → resolved)

    # ── 2. Restore copy and transaction to active borrowing ──────────────
    copy.status = 'borrowed'
    copy.save(update_fields=['status'])

    tx.status = 'borrowed'
    tx.save(update_fields=['status'])

    # ── 3. Recalculate overdue based on original due_date ────────────────
    # If the book is past its due date, mark as overdue and create/update
    # the overdue fine. The mark_overdue command will keep it synced daily.
    if now > tx.due_date:
        tx.status = 'overdue'
        tx.save(update_fields=['status'])

        fine_per_day = _Dec(str(_pref('FINE_PER_DAY', 1000)))
        days_late = max(1, (now - tx.due_date).days)
        overdue_amount = days_late * fine_per_day

        # Find existing overdue fine (exclude the loss fine if still present)
        overdue_qs = Fine.objects.filter(
            transaction=tx,
            reason__icontains='Overdue',
        )
        if loss_fine_pk:
            overdue_qs = overdue_qs.exclude(id=loss_fine_pk)
        overdue_fine = overdue_qs.first()

        if overdue_fine:
            if not overdue_fine.paid:
                overdue_fine.amount = overdue_amount
                overdue_fine.reason = f"Overdue fine for '{copy.book.title}' ({days_late} days)"
                overdue_fine.save(update_fields=['amount', 'reason'])
        else:
            Fine.objects.create(
                user=report.user,
                transaction=tx,
                amount=overdue_amount,
                reason=f"Overdue fine for '{copy.book.title}' ({days_late} days)",
                paid=False,
            )
    # else: within loan period → status stays 'borrowed' (active), no fine

    # ── 4. Mark the loss report as resolved ──────────────────────────────
    report.status = 'resolved'
    report.reviewed_by = request.user
    report.reviewed_at = now
    if notes:
        report.librarian_notes = (report.librarian_notes + '\n[RECOVERED] ' + notes).strip()
    else:
        report.librarian_notes = (report.librarian_notes + '\n[RECOVERED] Book recovered — back to active borrowing.').strip()
    report.save()

    # ── 5. Notify the member ─────────────────────────────────────────────
    if tx.status == 'overdue':
        notify_body = (
            f"Your book has been recovered and is back on active loan. "
            f"However, it is now overdue ({days_late} day(s)). "
            f"Overdue fine: TZS {overdue_amount:,.0f}. "
            f"Please pay at the library or return the book."
        )
    else:
        notify_body = (
            f"Your book has been recovered and is back on active loan. "
            f"Loss fine has been cancelled. No overdue fine applies. "
            f"Please return the book by {tx.due_date.strftime('%d %b %Y')}."
        )

    notify_user(
        report.user,
        f"MSICT OLMS: Recovery confirmed for '{copy.book.title}' (LR-{report.pk}). {notify_body}",
        'sms',
        message_type='loss_report',
    )
    notify_user(
        report.user,
        f"MSICT OLMS: Recovery confirmed for '{copy.book.title}' (LR-{report.pk}). {notify_body}",
        'email',
        subject='Book Recovered – MSICT OLMS',
        message_type='loss_report',
    )
    log_audit(request.user, f"Book recovered for LR-{report.pk}: '{copy.book.title}' by {report.user.username}", request)

    if tx.status == 'overdue':
        messages.success(request, f"Book '{copy.book.title}' recovered → now OVERDUE ({days_late} days). Loss fine cancelled. Overdue fine TZS {overdue_amount:,.0f} applies.")
    else:
        messages.success(request, f"Book '{copy.book.title}' recovered → back to ACTIVE borrowing. Loss fine cancelled. Due date: {tx.due_date.strftime('%d %b %Y')}.")
    return redirect('loss_report_list')


# ----------------------------------------------------------------------
# Softcopy Payment View — Payment gateway integration for softcopy access
# ----------------------------------------------------------------------
@login_required
def softcopy_payment_view(request, copy_id):
    """Display payment options and process payment for softcopy access."""
    copy = get_object_or_404(BookCopy, pk=copy_id, copy_type='softcopy')
    
    if copy.prepaid_fee <= 0:
        messages.warning(request, 'This softcopy is free. No payment required.')
        return redirect('submit_borrow_request', copy_id=copy.pk)
    
    if BorrowingTransaction.objects.filter(
        user=request.user, copy=copy, status__in=['borrowed', 'overdue'], due_date__gte=timezone.now()
    ).exists():
        messages.warning(request, 'You already have access to this softcopy.')
        return redirect('member_msict_borrowings')
    
    if request.method == 'POST':
        payment_method = request.POST.get('payment_method')
        # Always use the fixed prepaid_fee — user cannot modify the amount
        amount = copy.prepaid_fee
        
        if not payment_method:
            messages.error(request, 'Please select a payment method.')
            return render(request, 'circulation/softcopy_payment.html', {
                'copy': copy,
                'amount': copy.prepaid_fee,
            })
        
        # Validate payment details based on method
        mobile_methods = ['mpesa', 'tigopesa', 'airtel_money', 'halopesa']
        card_methods = ['visa', 'mastercard']
        phone_number = request.POST.get('phone_number', '').strip()
        bank_name = request.POST.get('bank_name', '').strip()
        bank_account_no = request.POST.get('bank_account_no', '').strip()
        card_last4 = request.POST.get('card_last4', '').strip()
        card_holder = request.POST.get('card_holder', '').strip()
        receipt_no = request.POST.get('receipt_no', '').strip()
        
        if payment_method in mobile_methods:
            if not phone_number:
                messages.error(request, 'Please enter your mobile money phone number.')
                return render(request, 'circulation/softcopy_payment.html', {
                    'copy': copy, 'amount': copy.prepaid_fee,
                })
            if not re.match(r'^0\d{9}$', phone_number):
                messages.error(request, 'Phone number must be exactly 10 digits starting with 0 (e.g. 0712345678).')
                return render(request, 'circulation/softcopy_payment.html', {
                    'copy': copy, 'amount': copy.prepaid_fee,
                })
        elif payment_method == 'bank_transfer':
            if not bank_name:
                messages.error(request, 'Please select your bank.')
                return render(request, 'circulation/softcopy_payment.html', {
                    'copy': copy, 'amount': copy.prepaid_fee,
                })
            if not bank_account_no:
                messages.error(request, 'Please enter your bank account number.')
                return render(request, 'circulation/softcopy_payment.html', {
                    'copy': copy, 'amount': copy.prepaid_fee,
                })
        elif payment_method in card_methods:
            if not card_holder:
                messages.error(request, 'Please enter the cardholder name.')
                return render(request, 'circulation/softcopy_payment.html', {
                    'copy': copy, 'amount': copy.prepaid_fee,
                })
            if not card_last4 or len(card_last4) != 4:
                messages.error(request, 'Please enter the last 4 digits of your card.')
                return render(request, 'circulation/softcopy_payment.html', {
                    'copy': copy, 'amount': copy.prepaid_fee,
                })
        
        # Create prepaid transaction record
        from .models import PrepaidTransaction
        tx = PrepaidTransaction.objects.create(
            user=request.user,
            copy=copy,
            amount=amount,
            payment_method=payment_method,
            status='pending',
            phone_number=phone_number,
            bank_name=bank_name,
            bank_account_no=bank_account_no,
            card_last4=card_last4,
            card_holder=card_holder,
            receipt_no=receipt_no,
        )
        
        # For now, simulate successful payment (integrate with actual payment gateway later)
        # TODO: Integrate with M-Pesa, card payment, bank APIs
        tx.status = 'completed'
        tx.transaction_id = f"TXN-{timezone.now().strftime('%Y%m%d%H%M%S')}-{request.user.id}"
        tx.save()
        _record_revenue(
            user=request.user,
            account_type='link_fee',
            amount=tx.amount,
            description=f"Softcopy prepaid fee for '{copy.book.title}'",
            reference_id=tx.pk,
            reference_table='prepaid_transactions',
        )
        
        # Create borrowing transaction after successful payment
        borrowing_tx = BorrowingTransaction.objects.create(
            user=request.user,
            copy=copy,
            borrow_type='softcopy',
        )
        
        # Generate secure access URL and store in SoftcopyAccessLog
        _loan_days = int(_pref('LOAN_PERIOD_DAYS', 7))
        softcopy_url = request.build_absolute_uri(reverse('softcopy_access', args=[borrowing_tx.access_token]))
        from .models import SoftcopyAccessLog
        SoftcopyAccessLog.objects.create(
            user=request.user,
            copy=copy,
            transaction=borrowing_tx,
            access_token=str(borrowing_tx.access_token),
            access_url=softcopy_url,
            expires_at=borrowing_tx.due_date,
        )
        
        # Send softcopy link via SMS/email
        msg_sms = (
            f"MSICT OLMS: Payment received for \"{copy.book.title}\" (TZS {tx.amount:,.0f}). "
            f"Your ebook link: {softcopy_url} "
            f"Valid for {_loan_days} days. Sharing or misuse may lead to disciplinary action."
        )
        msg_email = (
            f"Dear {request.user.get_full_name() or request.user.username},<br><br>"
            f"Payment confirmed for digital copy <b>\"{copy.book.title}\"</b>.<br>"
            f"<b>Amount Paid:</b> TZS {tx.amount:,.0f}<br>"
            f"<b>Transaction ID:</b> {tx.transaction_id}<br>"
            f"<b>Due Date:</b> {borrowing_tx.due_date.strftime('%d %b %Y')}<br>"
            f"<b>Access Link:</b> <a href='{softcopy_url}'>{softcopy_url}</a><br><br>"
            f"<i>Note: Your access is valid for {_loan_days} days. Sharing or misuse of digital content may lead to disciplinary action.</i>"
        )
        notify_user(request.user, msg_sms, 'sms', message_type='softcopy_link')
        notify_user(request.user, msg_email, 'email', subject=f'Payment Confirmed — {copy.book.title}', message_type='softcopy_link')
        log_audit(request.user, f"Softcopy payment completed for '{copy.book.title}' [{copy.accession_no}] - TXN: {tx.transaction_id}", request)
        try:
            from .receipt_utils import email_softcopy_receipt
            email_softcopy_receipt(tx)
        except Exception:
            pass
        payment_method_labels = {
            'mpesa': 'M-Pesa', 'tigopesa': 'Tigo Pesa', 'airtel_money': 'Airtel Money',
            'halopesa': 'Halopesa', 'bank_transfer': 'Bank Transfer', 'visa': 'Visa Card',
            'mastercard': 'Mastercard', 'cash': 'Cash',
        }
        return render(request, 'circulation/payment_success.html', {
            'book_title': copy.book.title,
            'amount': tx.amount,
            'txn_id': tx.transaction_id,
            'payment_method_label': payment_method_labels.get(payment_method, payment_method),
            'due_date': borrowing_tx.due_date.strftime('%d %b %Y, %H:%M'),
            'prepaid_tx_id': tx.pk,
            'librarian_mode': False,
        })
    
    return render(request, 'circulation/softcopy_payment.html', {
        'copy': copy,
        'amount': copy.prepaid_fee,
    })


# ----------------------------------------------------------------------
# Cancel Softcopy Access — Member cancels their own softcopy access early
# ----------------------------------------------------------------------
@login_required
@require_POST
def cancel_softcopy_access_view(request, tx_id):
    """Member cancels their own softcopy access early.
    Marks the transaction as returned and frees up the borrow slot."""
    tx = get_object_or_404(
        BorrowingTransaction,
        pk=tx_id,
        user=request.user,
        copy__copy_type='softcopy',
        status__in=['borrowed', 'overdue'],
    )
    tx.return_date = timezone.now()
    tx.status = 'returned'
    tx.save(update_fields=['return_date', 'status'])
    log_audit(request.user,
              f"Cancelled softcopy access early: '{tx.copy.book.title}' [{tx.copy.accession_no}]",
              request)
    messages.success(request, f'Access to "{tx.copy.book.title}" has been cancelled.')
    return redirect('member_msict_borrowings')


# ----------------------------------------------------------------------
# Softcopy Renewal Payment View — Member pays renewal fee for softcopy
# ----------------------------------------------------------------------
@login_required
def softcopy_renewal_payment_view(request, transaction_id):
    """Member pays the prepaid fee to renew a softcopy borrowing for another 7 days.
    If fee == 0, shows a free renewal confirmation page instead."""
    tx = get_object_or_404(
        BorrowingTransaction, pk=transaction_id, user=request.user,
        copy__copy_type='softcopy', borrow_type='softcopy',
        status__in=['borrowed', 'overdue'],
    )
    copy = tx.copy

    # Only check max renewals here — softcopy has no fine/overdue concept
    max_renewals = int(_pref('MAX_RENEWALS', 2))
    if tx.renewed_count >= max_renewals:
        messages.error(request, f'Maximum renewals reached ({max_renewals} times).')
        return redirect('member_msict_borrowings')

    # ── Free softcopy (prepaid_fee == 0): show confirmation page, renew on POST ──
    if copy.prepaid_fee <= 0:
        if request.method == 'POST':
            success, message = tx.renew()
            if success:
                softcopy_url = request.build_absolute_uri(
                    reverse('softcopy_access', args=[tx.access_token])
                )
                _loan_days = int(_pref('LOAN_PERIOD_DAYS', 7))
                msg_sms = (
                    f"MSICT OLMS: '{copy.book.title}' renewed. New due date: {tx.due_date.date()}. "
                    f"Your ebook link: {softcopy_url} Valid for {_loan_days} days."
                )
                msg_email = (
                    f"Dear {request.user.get_full_name() or request.user.username},<br><br>"
                    f"Renewal confirmed for digital copy <b>\"{copy.book.title}\"</b>.<br>"
                    f"<b>New Due Date:</b> {tx.due_date.strftime('%d %b %Y')}<br>"
                    f"<b>Access Link:</b> <a href='{softcopy_url}'>{softcopy_url}</a><br><br>"
                    f"<i>Note: Your access is valid for {_loan_days} days.</i>"
                )
                notify_user(request.user, msg_sms, 'sms', message_type='softcopy_link')
                notify_user(request.user, msg_email, 'email',
                            subject=f'Renewal Confirmed — {copy.book.title}',
                            message_type='softcopy_link')
                log_audit(request.user,
                          f"Softcopy renewed (free) '{copy.book.title}'. New due: {tx.due_date.date()}",
                          request)
                messages.success(request,
                    f'Renewed successfully. New due date: {tx.due_date.date()}')
            else:
                messages.error(request, message)
            return redirect('member_msict_borrowings')

        return render(request, 'circulation/softcopy_renewal_payment.html', {
            'tx': tx,
            'copy': copy,
            'amount': Decimal('0'),
            'is_free': True,
        })

    # ── Paid softcopy (prepaid_fee > 0): show payment form, process payment then renew ──
    if request.method == 'POST':
        payment_method = request.POST.get('payment_method')
        amount_str = request.POST.get('amount')
        try:
            amount = Decimal(amount_str)
        except (InvalidOperation, TypeError):
            messages.error(request, 'Invalid payment amount entered.')
            return render(request, 'circulation/softcopy_renewal_payment.html', {
                'tx': tx, 'copy': copy, 'amount': copy.prepaid_fee,
            })
        if amount < copy.prepaid_fee:
            messages.error(request,
                f'Entered amount is less than required fee TZS {copy.prepaid_fee:,.0f}.')
            return render(request, 'circulation/softcopy_renewal_payment.html', {
                'tx': tx, 'copy': copy, 'amount': copy.prepaid_fee,
            })
        if not payment_method:
            messages.error(request, 'Please select a payment method.')
            return render(request, 'circulation/softcopy_renewal_payment.html', {
                'tx': tx, 'copy': copy, 'amount': copy.prepaid_fee,
            })

        # 1. Record payment FIRST
        from .models import PrepaidTransaction
        prepaid_tx = PrepaidTransaction.objects.create(
            user=request.user,
            copy=copy,
            amount=amount,
            payment_method=payment_method,
            status='completed',
            transaction_id=f"TXN-REN-{timezone.now().strftime('%Y%m%d%H%M%S')}-{request.user.id}",
        )
        _record_revenue(
            user=request.user,
            account_type='link_fee',
            amount=prepaid_tx.amount,
            description=f"Softcopy renewal fee for '{copy.book.title}'",
            reference_id=prepaid_tx.pk,
            reference_table='prepaid_transactions',
        )

        # 2. Renew the transaction (generates new token + extends expiry)
        success, renew_msg = tx.renew()
        if not success:
            messages.error(request, f'Payment recorded but renewal failed: {renew_msg}')
            return redirect('member_msict_borrowings')

        # 3. Build new access URL and notify user
        softcopy_url = request.build_absolute_uri(
            reverse('softcopy_access', args=[tx.access_token])
        )
        _loan_days = int(_pref('LOAN_PERIOD_DAYS', 7))
        msg_sms = (
            f"MSICT OLMS: Renewal payment received for \"{copy.book.title}\" "
            f"(TZS {prepaid_tx.amount:,.0f}). "
            f"Your new ebook link: {softcopy_url} "
            f"Valid for {_loan_days} days. Sharing or misuse may lead to disciplinary action."
        )
        msg_email = (
            f"Dear {request.user.get_full_name() or request.user.username},<br><br>"
            f"Renewal confirmed for digital copy <b>\"{copy.book.title}\"</b>.<br>"
            f"<b>Amount Paid:</b> TZS {prepaid_tx.amount:,.0f}<br>"
            f"<b>Transaction ID:</b> {prepaid_tx.transaction_id}<br>"
            f"<b>New Due Date:</b> {tx.due_date.strftime('%d %b %Y')}<br>"
            f"<b>Access Link:</b> <a href='{softcopy_url}'>{softcopy_url}</a><br><br>"
            f"<i>Note: Your access is valid for {_loan_days} days. Sharing or misuse of digital "
            f"content may lead to disciplinary action.</i>"
        )
        notify_user(request.user, msg_sms, 'sms', message_type='softcopy_link')
        notify_user(request.user, msg_email, 'email',
                    subject=f'Renewal Confirmed — {copy.book.title}',
                    message_type='softcopy_link')
        log_audit(request.user,
                  f"Softcopy renewal paid for '{copy.book.title}' - TXN: {prepaid_tx.transaction_id}",
                  request)
        try:
            from .receipt_utils import email_softcopy_receipt
            email_softcopy_receipt(prepaid_tx)
        except Exception:
            pass
        
        payment_method_labels = {
            'mpesa': 'M-Pesa', 'tigopesa': 'Tigo Pesa', 'airtel_money': 'Airtel Money',
            'halopesa': 'Halopesa', 'bank_transfer': 'Bank Transfer', 'visa': 'Visa Card',
            'mastercard': 'Mastercard', 'cash': 'Cash',
        }
        return render(request, 'circulation/payment_success.html', {
            'book_title': copy.book.title,
            'amount': prepaid_tx.amount,
            'txn_id': prepaid_tx.transaction_id,
            'payment_method_label': payment_method_labels.get(payment_method, payment_method),
            'due_date': tx.due_date.strftime('%d %b %Y, %H:%M'),
            'prepaid_tx_id': prepaid_tx.pk,
            'librarian_mode': False,
        })

    return render(request, 'circulation/softcopy_renewal_payment.html', {
        'tx': tx,
        'copy': copy,
        'amount': copy.prepaid_fee,
    })


# ----------------------------------------------------------------------
# Process Softcopy Payment View — Librarian records payment for approved softcopy request
# ----------------------------------------------------------------------
@login_required
@librarian_required
def process_softcopy_payment_view(request, request_id):
    """Process payment for an approved softcopy request and create borrowing transaction."""
    req = get_object_or_404(BorrowRequest, pk=request_id, status='approved')
    copy = req.copy
    
    if copy.copy_type != 'softcopy':
        messages.error(request, 'This is not a softcopy request.')
        return redirect('all_requests')
    
    if copy.prepaid_fee <= 0:
        messages.warning(request, 'This softcopy is free. No payment required.')
        return redirect('issue_copy', request_id=req.pk)
    
    if BorrowingTransaction.objects.filter(
        user=req.user, copy=copy, status__in=['borrowed', 'overdue'], due_date__gte=timezone.now()
    ).exists():
        messages.warning(request, 'User already has access to this softcopy.')
        return redirect('all_requests')
    
    if request.method == 'POST':
        payment_method = request.POST.get('payment_method')
        
        if not payment_method:
            messages.error(request, 'Please select a payment method.')
            return render(request, 'circulation/process_softcopy_payment.html', {
                'req': req,
                'copy': copy,
                'amount': copy.prepaid_fee,
            })
        
        # Validate payment details based on method
        mobile_methods = ['mpesa', 'tigopesa', 'airtel_money', 'halopesa']
        card_methods = ['visa', 'mastercard']
        phone_number = request.POST.get('phone_number', '').strip()
        bank_name = request.POST.get('bank_name', '').strip()
        bank_account_no = request.POST.get('bank_account_no', '').strip()
        card_last4 = request.POST.get('card_last4', '').strip()
        card_holder = request.POST.get('card_holder', '').strip()
        receipt_no = request.POST.get('receipt_no', '').strip()
        
        if payment_method in mobile_methods:
            if not phone_number:
                messages.error(request, 'Please enter the member\'s mobile money phone number.')
                return render(request, 'circulation/process_softcopy_payment.html', {
                    'req': req, 'copy': copy, 'amount': copy.prepaid_fee,
                })
            if not re.match(r'^0\d{9}$', phone_number):
                messages.error(request, 'Phone number must be exactly 10 digits starting with 0 (e.g. 0712345678).')
                return render(request, 'circulation/process_softcopy_payment.html', {
                    'req': req, 'copy': copy, 'amount': copy.prepaid_fee,
                })
        elif payment_method == 'bank_transfer':
            if not bank_name:
                messages.error(request, 'Please select the bank.')
                return render(request, 'circulation/process_softcopy_payment.html', {
                    'req': req, 'copy': copy, 'amount': copy.prepaid_fee,
                })
            if not bank_account_no:
                messages.error(request, 'Please enter the bank account number.')
                return render(request, 'circulation/process_softcopy_payment.html', {
                    'req': req, 'copy': copy, 'amount': copy.prepaid_fee,
                })
        elif payment_method in card_methods:
            if not card_holder:
                messages.error(request, 'Please enter the cardholder name.')
                return render(request, 'circulation/process_softcopy_payment.html', {
                    'req': req, 'copy': copy, 'amount': copy.prepaid_fee,
                })
            if not card_last4 or len(card_last4) != 4:
                messages.error(request, 'Please enter the last 4 digits of the card.')
                return render(request, 'circulation/process_softcopy_payment.html', {
                    'req': req, 'copy': copy, 'amount': copy.prepaid_fee,
                })
        
        # Create prepaid transaction record
        from .models import PrepaidTransaction
        tx = PrepaidTransaction.objects.create(
            user=req.user,
            copy=copy,
            amount=copy.prepaid_fee,
            payment_method=payment_method,
            status='completed',
            transaction_id=f"TXN-{timezone.now().strftime('%Y%m%d%H%M%S')}-{req.user.id}",
            phone_number=phone_number,
            bank_name=bank_name,
            bank_account_no=bank_account_no,
            card_last4=card_last4,
            card_holder=card_holder,
            receipt_no=receipt_no,
        )
        _record_revenue(
            user=req.user,
            account_type='link_fee',
            amount=tx.amount,
            description=f"Softcopy prepaid fee recorded by librarian for '{copy.book.title}'",
            reference_id=tx.pk,
            reference_table='prepaid_transactions',
            recorded_by=request.user,
        )
        
        # Create borrowing transaction after successful payment
        borrowing_tx = BorrowingTransaction.objects.create(
            user=req.user,
            copy=copy,
            borrow_type='softcopy',
            approved_by=request.user,
        )
        
        # Generate secure access URL and store in SoftcopyAccessLog
        softcopy_url = request.build_absolute_uri(reverse('softcopy_access', args=[borrowing_tx.access_token]))
        from .models import SoftcopyAccessLog
        SoftcopyAccessLog.objects.create(
            user=req.user,
            copy=copy,
            transaction=borrowing_tx,
            access_token=str(borrowing_tx.access_token),
            access_url=softcopy_url,
            expires_at=borrowing_tx.due_date,
        )
        
        # Update request status
        req.status = 'approved'
        req.approved_by = request.user
        req.save()
        
        # Send softcopy link via SMS/email
        _loan_days = int(_pref('LOAN_PERIOD_DAYS', 7))
        msg_sms = (
            f"MSICT OLMS: Payment received for \"{copy.book.title}\" (TZS {copy.prepaid_fee:,.0f}). "
            f"Your ebook link: {softcopy_url} "
            f"Valid for {_loan_days} days. Sharing or misuse may lead to disciplinary action."
        )
        msg_email = (
            f"Dear {req.user.get_full_name() or req.user.username},<br><br>"
            f"Payment confirmed for digital copy <b>\"{copy.book.title}\"</b>.<br>"
            f"<b>Amount Paid:</b> TZS {copy.prepaid_fee:,.0f}<br>"
            f"<b>Transaction ID:</b> {tx.transaction_id}<br>"
            f"<b>Due Date:</b> {borrowing_tx.due_date.strftime('%d %b %Y')}<br>"
            f"<b>Access Link:</b> <a href='{softcopy_url}'>{softcopy_url}</a><br><br>"
            f"<i>Note: Your access is valid for {_loan_days} days. Sharing or misuse of digital content may lead to disciplinary action.</i>"
        )
        notify_user(req.user, msg_sms, 'sms', message_type='softcopy_link')
        notify_user(req.user, msg_email, 'email', subject=f'Payment Confirmed — {copy.book.title}', message_type='softcopy_link')
        log_audit(request.user, f"Softcopy payment processed for '{req.user.username}' – '{copy.book.title}' - TXN: {tx.transaction_id}", request)
        try:
            from .receipt_utils import email_softcopy_receipt
            email_softcopy_receipt(tx)
        except Exception:
            pass
        
        payment_method_labels = {
            'mpesa': 'M-Pesa', 'tigopesa': 'Tigo Pesa', 'airtel_money': 'Airtel Money',
            'halopesa': 'Halopesa', 'bank_transfer': 'Bank Transfer', 'visa': 'Visa Card',
            'mastercard': 'Mastercard', 'cash': 'Cash',
        }
        return render(request, 'circulation/payment_success.html', {
            'book_title': copy.book.title,
            'amount': tx.amount,
            'txn_id': tx.transaction_id,
            'payment_method_label': payment_method_labels.get(payment_method, payment_method),
            'due_date': borrowing_tx.due_date.strftime('%d %b %Y, %H:%M'),
            'prepaid_tx_id': tx.pk,
            'librarian_mode': True,
        })
    
    return render(request, 'circulation/process_softcopy_payment.html', {
        'req': req,
        'copy': copy,
        'amount': copy.prepaid_fee,
    })


# ----------------------------------------------------------------------
# Fine Receipt PDF — Generate a printable receipt for a fine payment
# ----------------------------------------------------------------------
@login_required
def fine_receipt_pdf_view(request, fine_id):
    from .receipt_utils import generate_receipt_pdf

    fine = get_object_or_404(Fine, pk=fine_id)
    if fine.user != request.user and request.user.role not in ('librarian', 'admin'):
        messages.error(request, 'You are not authorised to view this receipt.')
        return redirect('my_fines')

    book_title = fine.transaction.copy.book.title if fine.transaction else '—'
    copy_acc = fine.transaction.copy.accession_no if fine.transaction else '—'
    is_damage = DamageReport.objects.filter(damage_fine=fine).exists()
    fine_type_label = 'Damage Fine' if is_damage else 'Overdue Fine'
    receipt_id = f"RCPT-FINE-{fine.pk}-{timezone.now().strftime('%Y%m%d%H%M')}"

    items = [
        ('Book', book_title),
        ('Accession No', copy_acc),
        ('Fine Type', fine_type_label),
        ('Total Fine', f"TZS {fine.amount:,.0f}"),
        ('Amount Paid', f"TZS {fine.amount_paid:,.0f}"),
        ('Remaining', f"TZS {fine.remaining_balance:,.0f}"),
        ('Status', 'FULLY PAID' if fine.paid else 'PARTIAL'),
    ]
    qr_data = (
        f"MSICT-OLMS|FINE|{receipt_id}|{fine.user.username}|"
        f"TZS {fine.amount_paid:,.0f}|{'PAID' if fine.paid else 'PARTIAL'}"
    )
    return generate_receipt_pdf(
        receipt_id=receipt_id,
        title=f'{fine_type_label} Receipt',
        user=fine.user,
        items=items,
        qr_data=qr_data,
        payment_method=fine.payment_method or '',
        amount_label='Amount Paid',
        amount_value=f"TZS {fine.amount_paid:,.0f}",
        filename=f'fine_receipt_{fine.pk}',
        download=request.GET.get('download') == '1',
    )


# ----------------------------------------------------------------------
# Softcopy Link Fee Receipt PDF
# ----------------------------------------------------------------------
@login_required
def softcopy_receipt_pdf_view(request, tx_id):
    """Generate a PDF receipt for a softcopy link fee payment."""
    from .receipt_utils import generate_receipt_pdf
    from .models import PrepaidTransaction

    tx = get_object_or_404(PrepaidTransaction, pk=tx_id)
    # Allow the user who paid or any librarian/admin
    if tx.user != request.user and request.user.role not in ('librarian', 'admin'):
        messages.error(request, 'You are not authorised to view this receipt.')
        return redirect('member_dashboard')

    copy = tx.copy
    book_title = copy.book.title if copy and copy.book else '—'
    receipt_id = f"RCPT-LINK-{tx.pk}-{tx.created_at.strftime('%Y%m%d%H%M')}"

    items = [
        ('Transaction ID', tx.transaction_id or f'TXN-{tx.pk}'),
        ('Book Title', book_title),
        ('Accession No', copy.accession_no if copy else '—'),
        ('Status', tx.get_status_display()),
    ]

    # Find borrowing transaction for due date
    bt = BorrowingTransaction.objects.filter(user=tx.user, copy=copy).order_by('-id').first()
    if bt:
        items.append(('Due Date', bt.due_date.strftime('%d %b %Y, %H:%M')))

    qr_data = (
        f"MSICT-OLMS|LINK-RECEIPT|{receipt_id}|{tx.user.username}|"
        f"TZS {tx.amount:,.0f}|{book_title}"
    )

    return generate_receipt_pdf(
        receipt_id=receipt_id,
        title='Softcopy Link Fee Receipt',
        user=tx.user,
        items=items,
        qr_data=qr_data,
        payment_method=tx.payment_method,
        amount_label='Amount Paid',
        amount_value=f"TZS {float(tx.amount):,.0f}",
        filename=f'softcopy_receipt_{tx.pk}',
        extra_notes=[
            'Digital access is valid for 7 days from issue date.',
            'Sharing or misuse of digital content may lead to disciplinary action.',
        ],
        download=request.GET.get('download') == '1',
    )


# ----------------------------------------------------------------------
# Loss Fine Receipt PDF
# ----------------------------------------------------------------------
@login_required
def loss_fine_receipt_pdf_view(request, report_id):
    """Generate a PDF receipt for a loss fine payment."""
    from .receipt_utils import generate_receipt_pdf

    report = get_object_or_404(LossReport, pk=report_id)
    fine = report.loss_fine
    if not fine:
        messages.error(request, 'No fine found for this loss report.')
        return redirect('loss_report_list')

    # Allow the user who paid or any librarian/admin
    if fine.user != request.user and request.user.role not in ('librarian', 'admin'):
        messages.error(request, 'You are not authorised to view this receipt.')
        return redirect('member_dashboard')

    book_title = report.transaction.copy.book.title if report.transaction else '—'
    copy_acc = report.transaction.copy.accession_no if report.transaction else '—'
    receipt_id = f"RCPT-LOSS-{report.pk}-{timezone.now().strftime('%Y%m%d%H%M')}"

    items = [
        ('Loss Report #', f'LR-{report.pk}'),
        ('Book Title', book_title),
        ('Accession No', copy_acc),
        ('Total Fine', f"TZS {fine.amount:,.0f}"),
        ('Amount Paid', f"TZS {fine.amount_paid:,.0f}"),
        ('Remaining', f"TZS {fine.remaining_balance:,.0f}"),
        ('Status', 'FULLY PAID' if fine.paid else 'PARTIAL'),
    ]

    qr_data = (
        f"MSICT-OLMS|LOSS-RECEIPT|{receipt_id}|{fine.user.username}|"
        f"TZS {fine.amount_paid:,.0f}|LR-{report.pk}"
    )

    return generate_receipt_pdf(
        receipt_id=receipt_id,
        title='Loss Fine Receipt',
        user=fine.user,
        items=items,
        qr_data=qr_data,
        payment_method=fine.payment_method,
        amount_label='Amount Paid',
        amount_value=f"TZS {float(fine.amount_paid):,.0f}",
        filename=f'loss_receipt_{report.pk}',
        extra_notes=[
            'This receipt covers the loss fine for the reported book.',
            'Loss report status: ' + report.get_status_display(),
        ],
        download=request.GET.get('download') == '1',
    )


# ----------------------------------------------------------------------
# View ya Nakala Zilizopotea na Kuharibika — Mtunzaji anaona copies zote
# zilizo lost au damaged, pamoja na damage reports
# ----------------------------------------------------------------------
@login_required
@librarian_required
def lost_damaged_copies_view(request):
    """Librarian/admin view: all lost and damaged book copies, plus damage reports."""
    from django.db.models import Count, Sum

    tab = request.GET.get('tab', 'all')

    # Lost copies — ALL (paid and unpaid) so librarian sees everything
    lost_copies = (
        LossReport.objects.select_related(
            'user__rank', 'transaction__copy__book', 'loss_fine', 'reviewed_by'
        ).order_by('-reported_at')
    )

    # Damaged copies — ALL (paid and unpaid)
    damaged_copies = (
        DamageReport.objects.filter(
            damage_fine__isnull=False
        ).select_related(
            'user__rank', 'transaction__copy__book', 'damage_fine', 'reported_by'
        ).order_by('-reported_at')
    )

    # Damage reports — ALL with overdue fine enrichment
    damage_reports = (
        DamageReport.objects.filter(
            damage_fine__isnull=False
        ).select_related(
            'user__rank', 'transaction__copy__book', 'reported_by', 'damage_fine'
        ).prefetch_related('transaction__fines').order_by('-reported_at')
    )

    # Enrich damage reports with overdue fine info
    for report in damage_reports:
        overdue_fine = None
        if report.transaction:
            overdue_qs = report.transaction.fines.filter(reason__icontains='Overdue')
            if report.damage_fine_id:
                overdue_qs = overdue_qs.exclude(id=report.damage_fine_id)
            overdue_fine = overdue_qs.first()
        report.overdue_fine = overdue_fine

    # Loss reports — all, for the loss tab reference
    loss_reports = (
        LossReport.objects.select_related(
            'user__rank', 'transaction__copy__book', 'loss_fine', 'reviewed_by'
        ).order_by('-reported_at')
    )

    # Combined records list for the "All Records" tab with a reason field
    combined_records = []
    for lr in lost_copies:
        combined_records.append({
            'reason': 'Lost',
            'reason_class': 'danger',
            'ref': f'LR-{lr.pk}',
            'report_id': lr.pk,
            'book_title': lr.transaction.copy.book.title if lr.transaction and lr.transaction.copy and lr.transaction.copy.book else '—',
            'accession_no': lr.transaction.copy.accession_no if lr.transaction and lr.transaction.copy else '—',
            'copy_status': lr.transaction.copy.status if lr.transaction and lr.transaction.copy else '—',
            'member_name': lr.user.get_full_name(),
            'member_id': lr.user.army_no or lr.user.registration_no or '—',
            'fine_amount': lr.loss_fine.amount if lr.loss_fine else None,
            'fine_paid': lr.loss_fine.paid if lr.loss_fine else None,
            'fine_paid_at': lr.loss_fine.paid_at if lr.loss_fine else None,
            'status': lr.get_status_display(),
            'reported_at': lr.reported_at,
            'can_recover': lr.status in ('confirmed', 'resolved') and lr.transaction and lr.transaction.copy and lr.transaction.copy.status in ('lost', 'borrowed', 'overdue'),
        })
    for dr in damaged_copies:
        combined_records.append({
            'reason': 'Damaged',
            'reason_class': 'warning',
            'ref': f'DR-{dr.pk}',
            'report_id': None,
            'book_title': dr.transaction.copy.book.title if dr.transaction and dr.transaction.copy and dr.transaction.copy.book else '—',
            'accession_no': dr.transaction.copy.accession_no if dr.transaction and dr.transaction.copy else '—',
            'copy_status': dr.transaction.copy.status if dr.transaction and dr.transaction.copy else '—',
            'member_name': dr.user.get_full_name(),
            'member_id': dr.user.army_no or dr.user.registration_no or '—',
            'fine_amount': dr.damage_fine.amount if dr.damage_fine else None,
            'fine_paid': dr.damage_fine.paid if dr.damage_fine else None,
            'fine_paid_at': dr.damage_fine.paid_at if dr.damage_fine else None,
            'status': dr.get_status_display(),
            'reported_at': dr.reported_at,
            'can_recover': False,
        })
    combined_records.sort(key=lambda x: x['reported_at'], reverse=True)

    stats = {
        'lost_count': lost_copies.count(),
        'damaged_count': damaged_copies.count(),
        'damage_reports_count': damage_reports.count(),
        'damage_unpaid_count': DamageReport.objects.filter(
            damage_fine__isnull=False, damage_fine__paid=False
        ).count(),
        'lost_unpaid_count': LossReport.objects.filter(
            loss_fine__isnull=False, loss_fine__paid=False
        ).count(),
        'all_records': len(combined_records),
    }

    mark_badge_viewed(request.user, 'pending_damage_reports')
    return render(request, 'circulation/lost_damaged_copies.html', {
        'tab': tab,
        'lost_copies': lost_copies,
        'damaged_copies': damaged_copies,
        'damage_reports': damage_reports,
        'loss_reports': loss_reports,
        'combined_records': combined_records,
        'stats': stats,
    })
