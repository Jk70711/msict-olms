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
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from accounts.views import librarian_required
from accounts.utils import log_audit, send_sms, send_email_notification, create_notification, notify_user
from accounts.models import OLMSUser


# Msaidizi wa kusoma mipangilio kutoka DB au settings.py
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
from .models import BorrowRequest, BorrowingTransaction, Reservation, Fine, Notification, LossReport


# Dashboard ya mwanachama — inaonyesha:
#   - Vitabu alivyokopa (active na overdue)
#   - Maombi yanayosubiri idhini
#   - Uhifadhi wa nafasi
#   - Faini ambazo hazijalipwa
#   - Arifa 10 za hivi karibuni
@login_required
def member_dashboard_view(request):
    user = request.user
    active_transactions = BorrowingTransaction.objects.filter(
        user=user, status__in=['borrowed', 'overdue', 'lost']
    ).select_related('copy__book').order_by('-borrow_date')

    overdue_transactions = active_transactions.filter(status='overdue')
    lost_transactions = active_transactions.filter(status='lost')
    pending_requests = BorrowRequest.objects.filter(user=user, status='pending').select_related('copy__book')
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
    loss_report_tx_ids = LossReport.objects.filter(user=user, status__in=['pending', 'confirmed', 'resolved']).values_list('transaction_id', flat=True)
    overdue_tx_ids = overdue_transactions.values_list('id', flat=True)

    # Overdue fines for transactions NOT reported as lost
    overdue_fines = Fine.objects.filter(
        transaction_id__in=overdue_tx_ids
    ).exclude(transaction_id__in=loss_report_tx_ids)

    # Get loss fines (from loss reports)
    loss_reports_with_fines = LossReport.objects.filter(
        user=user,
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
        user=user
    ).select_related('transaction__copy__book', 'loss_fine').order_by('-reported_at')[:5]

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
        'all_unpaid_fines': all_unpaid_fines,
        'tx_fines': tx_fines,
        'total_fines': sum(f.amount for f in unpaid_fines),
        'total_fine_amount': total_fine_amount,
        'total_unpaid': total_unpaid,
        'total_paid': total_paid,
        'total_loss_fine_amount': total_loss_fine_amount,
        'total_loss_unpaid': total_loss_unpaid,
        'total_loss_paid': total_loss_paid,
        'total_all_unpaid': total_all_unpaid,
        'notifications': notifications,
        'has_overdue': overdue_transactions.exists(),
        'has_lost': lost_transactions.exists(),
        'borrow_history': borrow_history,
        'my_loss_reports': my_loss_reports,
    }
    return render(request, 'circulation/member_dashboard.html', context)


# ── Book-level hardcopy request — copy assigned later by librarian ────────────
@login_required
def request_borrow_book_view(request, book_id):
    """Member requests a hardcopy book title. No copy is auto-assigned yet.
    The librarian issues the specific copy via the 'Issue Copy' modal at pickup."""
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
def request_borrow_softcopy_view(request, book_id):
    """Auto-selects the first available borrowable softcopy and submits a request."""
    book = get_object_or_404(Book, pk=book_id)
    copy = book.copies.filter(copy_type='softcopy', access_type='borrow', status='available').first()
    if not copy:
        messages.error(request, f'No special soft copy is available for "{book.title}" right now.')
        return redirect('borrow_catalog')
    return redirect('submit_borrow_request', copy.pk)


@login_required
def download_free_book_view(request, book_id):
    """Redirects to the free softcopy download for the given book."""
    book = get_object_or_404(Book, pk=book_id)
    copy = book.copies.filter(copy_type='softcopy', access_type='free').first()
    if not copy:
        messages.error(request, f'No free PDF available for "{book.title}".')
        return redirect('borrow_catalog')
    return redirect('free_softcopy_download', copy.pk)


# Ukurasa wa kutafuta na kuomba kukopa vitabu (kwa mwanachama)
# Inazuia mwanachama ambaye ana vitabu vilivyochelewa
@login_required
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
def submit_borrow_request_view(request, copy_id):
    copy = get_object_or_404(BookCopy, pk=copy_id)

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
        if BorrowingTransaction.objects.filter(
            user=request.user, copy=copy, status__in=['borrowed', 'overdue']
        ).exists():
            messages.warning(request, 'You are already borrowing this soft copy. Check your borrowings to read it.')
            return redirect('member_dashboard')

        # ── Softcopy: no librarian approval needed — create transaction instantly ──
        tx = BorrowingTransaction.objects.create(
            user=request.user,
            copy=copy,
            borrow_type='softcopy',
        )
        fine_per_day = float(_pref('FINE_PER_DAY', 500))
        softcopy_url = request.build_absolute_uri(reverse('serve_softcopy', args=[copy.pk]))
        msg_sms = (
            f"MSICT OLMS: You have been issued digital copy \"{copy.book.title}\" "
            f"from {tx.borrow_date.strftime('%d %b %Y')} to {tx.due_date.strftime('%d %b %Y')}. "
            f"Sharing or misuse may lead to disciplinary action. "
            f"Overdue fine = TZS {fine_per_day:,.0f}/day (access blocked if overdue)."
        )
        msg_email = (
            f"Dear {request.user.get_full_name() or request.user.username},<br><br>"
            f"You have been issued digital copy <b>\"{copy.book.title}\"</b>.<br>"
            f"<b>Borrow Date:</b> {tx.borrow_date.strftime('%d %b %Y')}<br>"
            f"<b>Due Date:</b> {tx.due_date.strftime('%d %b %Y')}<br>"
            f"<b>Read Online:</b> <a href='{softcopy_url}'>{softcopy_url}</a><br><br>"
            f"<i>Note: Sharing or misuse of digital content may lead to disciplinary action. "
            f"Overdue fine: TZS {fine_per_day:,.0f} per day — access will be blocked.</i>"
        )
        notify_user(request.user, msg_sms, 'sms')
        notify_user(request.user, msg_email, 'email', subject=f'Digital Copy Issued — {copy.book.title}')
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
def cancel_borrow_request_view(request, request_id):
    """POST-only — prevents CSRF-style attacks via image tags or malicious links."""
    req = get_object_or_404(BorrowRequest, pk=request_id, user=request.user, status='pending')
    req.status = 'cancelled'
    req.save(update_fields=['status'])
    log_audit(request.user, f"Cancelled borrow request #{request_id}", request)
    messages.success(request, 'Borrow request cancelled.')
    return redirect('member_dashboard')


# Idhinisha ombi la kukopa (kwa mtunzaji au admin)
# Hardcopy: inathibitisha tu (copy inatolewa baadaye na librarian - "Issue Copy")
# Softcopy: inaunda transaction mara moja na kutuma kiungo
@login_required
@librarian_required
@require_POST
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

    # ── Softcopy: create transaction immediately ─────────────────────────────
    copy = req.copy
    if copy.copy_type == 'hardcopy' and copy.status != 'available':
        messages.error(request, 'Hardcopy is no longer available.')
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

    fine_per_day = float(_pref('FINE_PER_DAY', 500))
    librarian_name = request.user.get_full_name() or request.user.username
    softcopy_url = request.build_absolute_uri(reverse('serve_softcopy', args=[copy.pk]))

    msg_sms = (
        f"MSICT OLMS: You have borrowed digital copy \"{copy.book.title}\" "
        f"from {tx.borrow_date.strftime('%d %b %Y')} to {tx.due_date.strftime('%d %b %Y')}. "
        f"No physical loss, but sharing or misuse may lead to disciplinary action. "
        f"Overdue fine = TZS {fine_per_day:,.0f}/day (access blocked if overdue). "
        f"Processed by {librarian_name}."
    )
    msg_email = (
        f"Dear {user.get_full_name() or user.username},<br><br>"
        f"You have borrowed digital copy <b>\"{copy.book.title}\"</b>.<br>"
        f"<b>Borrow Date:</b> {tx.borrow_date.strftime('%d %b %Y')}<br>"
        f"<b>Due Date:</b> {tx.due_date.strftime('%d %b %Y')}<br>"
        f"<b>Direct Link:</b> <a href='{softcopy_url}'>{softcopy_url}</a><br><br>"
        f"<i>Note: Sharing or misuse of digital content may lead to disciplinary action. "
        f"Overdue fine: TZS {fine_per_day:,.0f} per day — access will be blocked.</i><br><br>"
        f"Processed by Librarian: <b>{librarian_name}</b>"
    )
    notify_user(user, msg_sms, 'sms')
    notify_user(user, msg_email, 'email', subject=f'Digital Copy Issued — {copy.book.title}')
    log_audit(request.user, f"Approved softcopy for '{user.username}' – '{copy.book.title}'", request)
    messages.success(request, f'Softcopy issued to {user.username}.')
    return redirect('all_requests')


# ── Issue Copy — librarian assigns physical copy to approved hardcopy request ─
@login_required
@librarian_required
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

    fine_per_day = float(_pref('FINE_PER_DAY', 500))
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
def reject_borrow_request_view(request, request_id):
    """POST-only — protected by CSRF + librarian role decorator."""
    req = get_object_or_404(BorrowRequest, pk=request_id, status='pending')
    reason = request.POST.get('rejection_reason', 'Rejected by librarian.')
    req.status = 'rejected'
    req.rejection_reason = reason
    req.approved_by = request.user
    req.save()

    msg = f"MSICT OLMS: Your borrow request for '{req.copy.book.title}' was rejected. Reason: {reason}"
    notify_user(req.user, msg, 'sms')
    notify_user(req.user, msg, 'email', subject='Borrow Request Rejected')
    log_audit(request.user, f"Rejected borrow request for '{req.user.username}' – '{req.copy.book.title}'", request)
    messages.warning(request, f'Request rejected for {req.user.username}.')
    return redirect('librarian_dashboard')


# Ongeza muda wa mkopo (renew) — kwa mwanachama tu
# Kwa softcopy: inaweza kufanywa wakati wowote ndani ya muda
# Kwa hardcopy: haiwezekani kama kuna uhifadhi au ni overdue
@login_required
@require_POST
def renew_transaction_view(request, transaction_id):
    """POST-only — prevents CSRF-style attacks via image tags or malicious links."""
    tx = get_object_or_404(BorrowingTransaction, pk=transaction_id, user=request.user)
    success, message = tx.renew()
    if success:
        msg = f"MSICT OLMS: '{tx.copy.book.title}' renewed. New due date: {tx.due_date.date()}"
        notify_user(request.user, msg, 'sms')
        notify_user(request.user, msg, 'email', subject='Renewal Confirmation')
        log_audit(request.user, f"Renewed '{tx.copy.book.title}'. New due: {tx.due_date.date()}", request)
        messages.success(request, f'Renewed successfully. New due date: {tx.due_date.date()}')
    else:
        messages.error(request, message)
    return redirect('member_dashboard')


# Rudisha softcopy mapema kabla ya muda haujaisha
@login_required
@require_POST
def return_early_view(request, transaction_id):
    """POST-only — prevents CSRF-style attacks via image tags or malicious links."""
    tx = get_object_or_404(
        BorrowingTransaction, pk=transaction_id,
        user=request.user, status__in=['borrowed', 'overdue']
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
                f'Outstanding fine: TZS {tx.total_fine_remaining}. '
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
def _process_desk_return(request, copy_pk_str):
    """Process a single copy return from the librarian desk (hard or soft).
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

    from circulation.models import Fine

    # Calculate overdue days BEFORE changing status (days_overdue checks status field)
    days_late = 0
    if tx.status in ('borrowed', 'overdue') and timezone.now() > tx.due_date:
        days_late = max(1, (timezone.now() - tx.due_date).days)

    tx.return_date = timezone.now()
    tx.status      = 'returned'
    tx.save(update_fields=['return_date', 'status'])

    if copy.copy_type == 'hardcopy':
        copy.status = 'available'
        copy.save(update_fields=['status'])

    fine_per_day = float(_pref('FINE_PER_DAY', 500))
    if days_late > 0:
        fine_amount = days_late * fine_per_day
        # Upsert fine record (never block the return — just ensure fine exists)
        existing_fine = Fine.objects.filter(transaction=tx).first()
        if existing_fine and not existing_fine.paid:
            existing_fine.amount = fine_amount
            existing_fine.reason = f"Overdue fine for '{copy.book.title}' ({days_late} days)"
            existing_fine.save(update_fields=['amount', 'reason'])
        elif not existing_fine:
            Fine.objects.create(
                user=tx.user, transaction=tx, amount=fine_amount,
                reason=f"Overdue fine for '{copy.book.title}' ({days_late} days)",
            )
        messages.warning(request, f'"{copy.book.title}" returned — overdue fine of TZS {fine_amount:,.0f} raised. Please collect payment.')
        fine_msg = (
            f"MSICT OLMS: Overdue fine of TZS {fine_amount:,.0f} for '{copy.book.title}'. "
            f"Please pay at the library counter."
        )
        notify_user(tx.user, fine_msg, 'sms')
        notify_user(tx.user, fine_msg, 'email', subject='Overdue Fine Notice – MSICT OLMS')
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

    _notify_next_reservation(copy.book, request)
    log_audit(request.user,
              f"Returned {copy.copy_type} '{copy.accession_no}' – '{copy.book.title}'",
              request)
    return tx


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
def return_hardcopy_view(request):
    if request.method == 'POST':
        search_input   = request.POST.get('barcode', '').strip()
        card_input     = request.POST.get('card_no', '').strip()
        copy_pk        = request.POST.get('copy_pk', '').strip()
        return_card_no = request.POST.get('return_card_no', '').strip()

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
                    return render(request, 'circulation/return_desk.html', {
                        'lookup_tx':     lookup_tx,
                        'barcode_input': search_input,
                        'recent_returns': _get_recent_returns(),
                    })
            except BookCopy.DoesNotExist:
                messages.error(request, f'Hardcopy not found: "{search_input}". Check barcode or accession number.')

    return render(request, 'circulation/return_desk.html', {'recent_returns': _get_recent_returns()})


# ============================================================
# RESERVATION HELPER — recalculate position-based expiry dates
# expires_at = nearest_borrowed_due_date + (position × RESERVATION_WINDOW_DAYS)
# If no active borrows, base = now(). Notified users keep min 24 h.
# ============================================================
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
def reserve_book_view(request, book_id):
    book = get_object_or_404(Book, pk=book_id)

    # Only hardcopy books support reservation
    hardcopies = book.copies.filter(copy_type='hardcopy')
    if not hardcopies.exists():
        messages.info(request, 'This book has no hardcopy. Reservation is not applicable.')
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

    return render(request, 'circulation/my_reservations.html', {
        'annotated': annotated,
        'history': history,
    })


# Maombi yote ya kukopa — inaonekana kwa mtunzaji peke yake
# Inaweza kuchujwa kwa hali: pending, approved, rejected, cancelled
@login_required
@librarian_required
def all_requests_view(request):
    requests_qs = BorrowRequest.objects.select_related('user', 'copy__book').order_by('-request_date')
    status_filter = request.GET.get('status', '')
    if status_filter:
        requests_qs = requests_qs.filter(status=status_filter)
    return render(request, 'circulation/all_requests.html', {
        'requests': requests_qs,
        'status_filter': status_filter,
    })


# Vitabu vilivyopita tarehe ya kurudisha — kwa mtunzaji
@login_required
@librarian_required
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
        .filter(has_unpaid_fine | has_no_fine)
        .select_related('user', 'copy__book')
        .order_by('due_date')
    )
    return render(request, 'circulation/overdue_list.html', {'overdue': overdue})


def _auto_mark_overdue():
    """Inline guard: mark any 'borrowed' transactions past their due_date as 'overdue'.
    Called at the top of every librarian page that shows overdue/fine data so the
    view is always accurate even when the nightly cron hasn't fired yet."""
    stale = BorrowingTransaction.objects.filter(
        status='borrowed',
        due_date__lt=timezone.now(),
    ).only('id', 'status')
    if stale.exists():
        stale.update(status='overdue')


def _extract_total_paid_from_log(receipt_no):
    """Parse the payment history log to sum actual amounts paid.
    Returns Decimal total if parseable, else None."""
    import re
    if not receipt_no:
        return None
    amounts = re.findall(r'TZS\s*([\d]+(?:\.\d+)?)', receipt_no)
    if amounts:
        try:
            return sum(Decimal(a) for a in amounts)
        except Exception:
            return None
    return None


def _sync_overdue_fines(fine_per_day):
    """Shared helper: update existing unpaid fines and create missing ones for overdue transactions.
    Also merges any duplicates (paid + unpaid for same transaction) into a single fine record.
    """
    _auto_mark_overdue()  # Ensure borrowed+past-due are marked overdue before syncing
    overdue_transactions = BorrowingTransaction.objects.filter(
        status='overdue'
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
            # Fix inflated amount_paid: if receipt log shows a LOWER total than DB,
            # the DB value was incorrectly set (e.g. by old capping bug). Correct it.
            if fine.receipt_no and fine.amount_paid > 0:
                actual_paid = _extract_total_paid_from_log(fine.receipt_no)
                if actual_paid is not None and actual_paid < fine.amount_paid:
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
def fine_list_view(request):
    from django.db.models import Sum, Count
    fine_per_day = float(_pref('FINE_PER_DAY', 500))
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
    return render(request, 'circulation/fine_list.html', {
        'fines': fines,
        'fine_per_day': fine_per_day,
        'user_summary': user_summary,
        'loan_period_days': loan_period_days,
        'fine_start_day': loan_period_days + 1,
    })


@login_required
@librarian_required
def user_fines_view(request, user_id):
    user_obj = get_object_or_404(OLMSUser, pk=user_id)
    fine_per_day = float(_pref('FINE_PER_DAY', 500))
    
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
    return render(request, 'circulation/my_fines.html', {
        'fines': overdue_fines,
        'unpaid_fines': unpaid_fines,
        'total_unpaid': total_unpaid,
    })


@login_required
def my_loss_reports_view(request):
    """Member views their loss reports and loss fines."""
    reports = LossReport.objects.filter(
        user=request.user
    ).select_related('transaction__copy__book', 'loss_fine').order_by('-reported_at')
    unpaid_loss_reports = [r for r in reports if r.loss_fine and not r.loss_fine.paid]
    total_unpaid_loss_fine = sum(r.loss_fine.remaining_balance for r in unpaid_loss_reports)
    return render(request, 'circulation/my_loss_reports.html', {
        'reports': reports,
        'unpaid_loss_reports': unpaid_loss_reports,
        'total_unpaid_loss_fine': total_unpaid_loss_fine,
    })


@login_required
def pay_fine_view(request, fine_id):
    """
    Member-facing self-service fine payment request.

    GET  : show the payment options page.
    POST : record the member's intent to pay (method, amount, reference)
           on the fine's audit log, notify the librarian queue, and tell
           the member to bring proof to the desk so a librarian can
           finalise via `record_fine_payment_view`.

    The fine is NOT marked paid here — actual money cannot be received
    over the web without a real payment-gateway integration. Recording
    the intent gives full audit traceability and replaces the previous
    JavaScript-only alert.
    """
    fine = get_object_or_404(Fine, id=fine_id, user=request.user, paid=False)

    if request.method == 'POST':
        method = (request.POST.get('payment_method') or '').strip().lower()
        amount_str = (request.POST.get('payment_amount') or '').strip()
        reference = (request.POST.get('reference') or '').strip()  # phone / txn / acct
        ALLOWED_METHODS = {
            'mpesa', 'tigopesa', 'airtel', 'halotel',
            'card', 'bank',
        }

        # ── Validate ────────────────────────────────────────────────
        if method not in ALLOWED_METHODS:
            messages.error(request, 'Please select a valid payment method.')
            return redirect('pay_fine', fine_id=fine.pk)

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
                f'Amount TZS {amount} exceeds remaining balance '
                f'TZS {fine.remaining_balance}.'
            )
            return redirect('pay_fine', fine_id=fine.pk)

        # ── Record the intent (append-only audit log on the fine) ───
        ts = timezone.now().strftime('%d %b %Y %H:%M')
        line = f"[{ts}] REQUEST {method.upper()} TZS {amount} (pending verification)"
        if reference:
            line += f" | Ref: {reference}"
        fine.receipt_no = (fine.receipt_no + "\n" + line).strip()
        fine.save(update_fields=['receipt_no'])

        # ── Tell the librarians via the existing audit + notify path ──
        log_audit(
            request.user,
            f"Member submitted self-service payment request: "
            f"fine #{fine.pk}, {method.upper()} TZS {amount}",
            request,
        )

        # Notify librarians (in-app notification) so the queue is visible.
        try:
            from accounts.models import OLMSUser as _U
            for lib in _U.objects.filter(role__in=['librarian', 'admin'], is_active=True):
                Notification.objects.create(
                    user=lib,
                    message=(
                        f"Fine payment request from {request.user.get_full_name() or request.user.username}: "
                        f"{method.upper()} TZS {amount} for fine #{fine.pk}. "
                        f"Verify via Circulation > Fines."
                    ),
                    channel='email',
                    priority='normal',
                    status='pending',
                )
        except Exception:
            # Notifications are best-effort; never block the user's submission.
            pass

        messages.success(
            request,
            f'Payment request recorded: {method.upper()} TZS {amount}. '
            f'Please bring proof of payment to the librarian to finalise. '
            f'Your reference: FINE-{fine.pk}-{int(amount)}.'
        )
        return redirect('my_fines')

    return render(request, 'circulation/pay_fine.html', {'fine': fine})


@login_required
def pay_loss_fine_view(request, report_id):
    """
    Member-facing self-service loss fine payment request.

    GET  : show the payment options page.
    POST : record the member's intent to pay (method, amount, reference)
           on the fine's audit log, notify the librarian queue, and tell
           the member to bring proof to the desk so a librarian can
           finalise via `record_fine_payment_view`.

    The fine is NOT marked paid here — actual money cannot be received
    over the web without a real payment-gateway integration. Recording
    the intent gives full audit traceability.
    """
    report = get_object_or_404(LossReport, pk=report_id, user=request.user)
    if not report.loss_fine or report.loss_fine.paid:
        messages.error(request, 'This loss report has no unpaid fine to pay.')
        return redirect('member_dashboard')

    fine = report.loss_fine

    if request.method == 'POST':
        method = (request.POST.get('payment_method') or '').strip().lower()
        amount_str = (request.POST.get('payment_amount') or '').strip()
        reference = (request.POST.get('reference') or '').strip()
        ALLOWED_METHODS = {
            'mpesa', 'tigopesa', 'airtel', 'halotel',
            'card', 'bank',
        }

        # ── Validate ────────────────────────────────────────────────
        if method not in ALLOWED_METHODS:
            messages.error(request, 'Please select a valid payment method.')
            return redirect('pay_loss_fine', report_id=report.pk)

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
                f'Amount TZS {amount} exceeds remaining balance '
                f'TZS {fine.remaining_balance}.'
            )
            return redirect('pay_loss_fine', report_id=report.pk)

        # ── Record the intent (append-only audit log on the fine) ───
        ts = timezone.now().strftime('%d %b %Y %H:%M')
        line = f"[{ts}] REQUEST {method.upper()} TZS {amount} (pending verification)"
        if reference:
            line += f" | Ref: {reference}"
        fine.receipt_no = (fine.receipt_no + "\n" + line).strip()
        fine.save(update_fields=['receipt_no'])

        # ── Tell the librarians via the existing audit + notify path ──
        log_audit(
            request.user,
            f"Member submitted loss fine payment request: "
            f"loss report #{report.pk}, {method.upper()} TZS {amount}",
            request,
        )

        # Notify librarians (in-app notification) so the queue is visible.
        try:
            from accounts.models import OLMSUser as _U
            for lib in _U.objects.filter(role__in=['librarian', 'admin'], is_active=True):
                Notification.objects.create(
                    user=lib,
                    message=(
                        f"Loss fine payment request from {request.user.get_full_name() or request.user.username}: "
                        f"{method.upper()} TZS {amount} for loss report #{report.pk}. "
                        f"Verify via Circulation > Loss Reports."
                    ),
                    channel='email',
                    priority='normal',
                    status='pending',
                )
        except Exception:
            # Notifications are best-effort; never block the user's submission.
            pass

        messages.success(
            request,
            f'Loss fine payment request recorded: {method.upper()} TZS {amount}. '
            f'Please bring proof of payment to the librarian to finalise. '
            f'Your reference: LOSS-{report.pk}-{int(amount)}.'
        )
        return redirect('member_dashboard')

    return render(request, 'circulation/pay_loss_fine.html', {'report': report, 'fine': fine})


@login_required
@librarian_required
def record_loss_fine_payment_view(request, report_id):
    """
    Librarian loss fine payment handler.

    GET  : show the payment form page.
    POST : validate and record payment.
    """
    report = get_object_or_404(LossReport, pk=report_id)
    if not report.loss_fine:
        messages.error(request, 'This loss report has no fine to pay.')
        return redirect('loss_report_list')

    fine = report.loss_fine

    if request.method != 'POST':
        return render(request, 'circulation/loss_fine_payment.html', {'report': report, 'fine': fine})

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
        return redirect('record_loss_fine_payment', report_id=report.pk)

    # Validate payment amount does not exceed remaining balance
    remaining_balance = fine.amount - fine.amount_paid
    if payment_amount > remaining_balance:
        messages.error(
            request,
            f'Payment amount TZS {payment_amount} exceeds remaining balance TZS {remaining_balance}. '
            f'Please enter correct amount not exceeding TZS {remaining_balance}.'
        )
        return redirect('record_loss_fine_payment', report_id=report.pk)

    # Build payment log entry (appended — never overwritten)
    MOBILE_METHODS = {'mpesa', 'tigopesa', 'airtel_money', 'halopesa'}
    CARD_METHODS   = {'visa', 'mastercard'}
    now_str = timezone.now().strftime('%d %b %Y %H:%M')
    log_entry = f"[{now_str}] {payment_method.upper()} TZS {payment_amount}"

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

    # Determine SMS message based on payment status
    remaining_balance = fine.remaining_balance
    book_name = report.transaction.copy.book.title
    if fine.paid:
        sms_message = f"Umelipa deni lote la faini ya hasara TZS {fine.amount} kwa kitabu '{book_name}' kwa {payment_method.upper()}. Asante."
    else:
        sms_message = f"Umelipa TZS {payment_amount} kwa faini ya hasara TZS {fine.amount} ya kitabu '{book_name}'. Bado unadaiwa TZS {remaining_balance}. karibu tena."

    # Send SMS notification
    try:
        notify_user(fine.user, sms_message, 'sms')
    except Exception as e:
        # Log error but don't fail the payment process
        log_audit(request.user, f"SMS failed for loss fine {fine.pk}: {str(e)}", request)

    log_audit(request.user, f"Loss fine {fine.pk} payment of TZS {payment_amount} by {fine.user.username} via {payment_method}", request)

    if fine.paid:
        # If fully paid, mark loss report as resolved
        report.status = 'resolved'
        report.resolved_at = timezone.now()
        report.save(update_fields=['status', 'resolved_at'])
        messages.success(
            request,
            f'Loss fine fully paid. TZS {payment_amount} recorded. '
            f'Loss report LR-{report.pk} marked as resolved.'
        )
    else:
        messages.success(
            request,
            f'Payment recorded: TZS {payment_amount}. '
            f'Remaining balance: TZS {remaining_balance}.'
        )

    return redirect('loss_report_list')


@login_required
@librarian_required
def users_with_unpaid_fines_view(request):
    from django.db.models import Sum, Count, Q
    from collections import defaultdict
    fine_per_day = float(_pref('FINE_PER_DAY', 500))
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
    overdue_users = (
        BorrowingTransaction.objects
        .filter(status='overdue')
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

    # Validate payment amount does not exceed remaining balance
    remaining_balance = fine.amount - fine.amount_paid
    if payment_amount > remaining_balance:
        messages.error(
            request,
            f'Payment amount TZS {payment_amount} exceeds remaining balance TZS {remaining_balance}. '
            f'Please enter correct amount not exceeding TZS {remaining_balance}.'
        )
        return redirect('user_fines', user_id=fine.user.pk)

    # Build payment log entry (appended — never overwritten)
    MOBILE_METHODS = {'mpesa', 'tigopesa', 'airtel_money', 'halopesa'}
    CARD_METHODS   = {'visa', 'mastercard'}
    now_str = timezone.now().strftime('%d %b %Y %H:%M')
    log_entry = f"[{now_str}] {payment_method.upper()} TZS {payment_amount}"

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

    # Determine SMS message based on payment status
    remaining_balance = fine.remaining_balance
    book_name = fine.transaction.copy.book.title if fine.transaction else "kitabu"
    if fine.paid:
        sms_message = f"Umelipa deni lote la faini ya TZS {fine.amount} kwa kitabu '{book_name}' kwa {payment_method.upper()}. Asante."
    else:
        sms_message = f"Umelipa TZS {payment_amount} kwa faini ya TZS {fine.amount} ya kitabu '{book_name}'. Bado unadaiwa TZS {remaining_balance}. karibu tena."

    # Send SMS notification
    try:
        notify_user(fine.user, sms_message, 'sms')
    except Exception as e:
        # Log error but don't fail the payment process
        log_audit(request.user, f"SMS failed for fine {fine.pk}: {str(e)}", request)

    log_audit(request.user, f"Fine {fine.pk} payment of TZS {payment_amount} by {fine.user.username} via {payment_method}", request)

    if fine.paid:
        messages.success(request, f'Full payment recorded: {payment_method.upper()} — TZS {payment_amount}. Fine fully paid!')
    else:
        messages.success(request, f'Partial payment: {payment_method.upper()} — TZS {payment_amount} paid. Remaining: TZS {remaining_balance}')

    return redirect('user_fines', user_id=fine.user.pk)


@login_required
@librarian_required
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
                f'Payment amount TZS {payment_amount} exceeds total remaining balance TZS {total_remaining_balance}. '
                f'Please enter correct amount not exceeding TZS {total_remaining_balance}.'
            )
            return redirect('user_fines', user_id=user_id)
        
        # Build detailed payment info based on method
        payment_details = []
        
        if payment_method in ['mpesa', 'tigopesa', 'airtel_money', 'halopesa']:
            phone = request.POST.get('phone_number', '')
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
            payment_details.append(f"Received: TZS {payment_amount}")
        
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
            log_line = f"[{now_str}] {payment_method.upper()} TZS {payment_for_fine} | {full_receipt}"
            fine.receipt_no = (fine.receipt_no + '\n' + log_line).strip()
            fine.paid_at = timezone.now()
            fine.save()
            
            remaining_payment -= payment_for_fine
        
        # Determine SMS message based on payment status
        total_remaining = sum(f.remaining_balance for f in Fine.objects.filter(user=user_obj, paid=False))
        if total_remaining == 0:
            sms_message = f"Umelipa deni lote la faini ya TZS {payment_amount} kwa {payment_method.upper()}. Asante."
        else:
            sms_message = f"Umelipa TZS {payment_amount} kwa faini. Bado unadaiwa TZS {total_remaining}."
        
        # Send SMS notification
        try:
            notify_user(user_obj, sms_message, 'sms')
        except Exception as e:
            # Log error but don't fail the payment process
            log_audit(request.user, f"SMS failed for bulk payment {user_obj.pk}: {str(e)}", request)
        
        log_audit(request.user, f"Bulk payment of TZS {payment_amount} for {user_obj.username} via {payment_method}", request)
        
        if total_remaining == 0:
            messages.success(request, f'Full payment recorded: {payment_method.upper()} - TZS {payment_amount}. All fines fully paid!')
        else:
            messages.success(request, f'Partial payment recorded: {payment_method.upper()} - TZS {payment_amount}. {fully_paid_count} fine(s) fully paid. Remaining: TZS {total_remaining}')
        
        return redirect('user_fines', user_id=user_id)
    
    return redirect('user_fines', user_id=user_id)


@login_required
@librarian_required
def circulation_desk_view(request):
    return render(request, 'circulation/circulation_desk.html')


@login_required
def member_msict_borrowings_view(request):
    """Member view for MSICT borrowings - history, pending, active"""
    user = request.user

    # Active borrowings (borrowed, overdue, or lost) - filter out missing books
    active_borrows = BorrowingTransaction.objects.filter(
        user=user, status__in=['borrowed', 'overdue', 'lost'], copy__book__isnull=False
    ).select_related('copy__book').order_by('-borrow_date')

    # Borrow history (returned or lost) - filter out missing books
    borrow_history = BorrowingTransaction.objects.filter(
        user=user, status__in=['returned', 'lost'], copy__book__isnull=False
    ).select_related('copy__book').order_by('-return_date')[:50]

    # Pending borrow requests - filter out missing books
    pending_requests = BorrowRequest.objects.filter(
        user=user, status='pending', copy__book__isnull=False
    ).select_related('copy__book').order_by('-request_date')

    # Rejected/Cancelled requests - filter out missing books
    rejected_requests = BorrowRequest.objects.filter(
        user=user, status__in=['rejected', 'cancelled'], copy__book__isnull=False
    ).select_related('copy__book').order_by('-request_date')[:20]

    # Current reservations - filter out missing books
    reservations = Reservation.objects.filter(
        user=user, status='pending', book__isnull=False
    ).select_related('book').order_by('-created_at')

    # Reservation history
    reservation_history = Reservation.objects.filter(
        user=user, status__in=['fulfilled', 'cancelled', 'expired']
    ).select_related('book').order_by('-created_at')[:20]

    # Unpaid fines
    from .models import Fine
    unpaid_fines = Fine.objects.filter(
        transaction__user=user, paid=False
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
        'borrow_history': borrow_history,
        'pending_requests': pending_requests,
        'rejected_requests': rejected_requests,
        'reservations': reservations,
        'reservation_history': reservation_history,
        'unpaid_fines': unpaid_fines,
        'tx_fines': tx_fines,
    }
    return render(request, 'circulation/member_msict_borrowings.html', context)


@login_required
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
    return render(request, 'circulation/member_ill_borrowings.html', context)


# Maktaba ya kidijitali — vitabu vya PDF ambavyo mwanachama amekopa au vya bure
@login_required
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

    active_borrow_copy_ids = set(
        BorrowingTransaction.objects.filter(
            user=user, status__in=['borrowed', 'overdue'], copy__copy_type='softcopy'
        ).values_list('copy_id', flat=True)
    )
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
        'pending_copy_ids': pending_copy_ids,
        'total_free': total_free,
        'total_special': total_special,
    })


# Orodha ya uhifadhi wote — mtunzaji anaweza kuchuja kwa hali (pending, fulfilled...)
@login_required
@librarian_required
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

    counts = {
        'all':      BorrowingTransaction.objects.count(),
        'borrowed': BorrowingTransaction.objects.filter(status='borrowed').count(),
        'overdue':  BorrowingTransaction.objects.filter(status='overdue').count(),
        'returned': BorrowingTransaction.objects.filter(status='returned').count(),
    }

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


# ── Loss Report Views ─────────────────────────────────────────────────────────

@login_required
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
def loss_report_list_view(request):
    """Librarian views all loss reports."""
    status_filter = request.GET.get('status', '')
    qs = LossReport.objects.select_related(
        'user__rank', 'transaction__copy__book', 'reviewed_by', 'loss_fine'
    ).prefetch_related('transaction__fines')
    if status_filter:
        qs = qs.filter(status=status_filter)
    
    # Calculate overdue fine count for each report
    reports_with_counts = []
    for report in qs:
        overdue_count = 0
        if report.transaction:
            overdue_count = report.transaction.fines.filter(loss_report__isnull=True).count()
        report.overdue_count = overdue_count
        reports_with_counts.append(report)
    
    return render(request, 'circulation/loss_report_list.html', {
        'reports': reports_with_counts,
        'status_filter': status_filter,
    })


@login_required
@librarian_required
@require_POST
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

        report.status = 'confirmed'
        report.save()

        notify_user(
            report.user,
            f"MSICT OLMS: LOSS FINE - Loss of '{copy.book.title}' confirmed (LR-{report.pk}). "
            + (f"A LOSS FINE of TZS {loss_fine_amount} has been raised. Please pay at the library." if loss_fine_amount > 0 else "No fine has been raised."),
            'sms',
            message_type='loss_fine' if loss_fine_amount > 0 else 'loss_report',
        )
        notify_user(
            report.user,
            f"MSICT OLMS: LOSS FINE - Loss confirmed for '{copy.book.title}'. Ref: LR-{report.pk}. "
            + (f"A LOSS FINE of TZS {loss_fine_amount} has been raised." if loss_fine_amount > 0 else ""),
            'email',
            subject='LOSS FINE – Loss Report Confirmed – MSICT OLMS',
            message_type='loss_fine' if loss_fine_amount > 0 else 'loss_report',
        )
        messages.success(
            request,
            f'Loss confirmed for LR-{report.pk}. Copy marked lost.'
            + (f' Fine of TZS {loss_fine_amount} created.' if loss_fine_amount > 0 else ''),
        )
        log_audit(request.user, f"Confirmed loss report LR-{report.pk} for '{copy.book.title}'", request)

    return redirect('loss_report_list')


@login_required
@librarian_required
@require_POST
def recover_book_view(request, report_id):
    """Librarian marks a lost book as physically recovered (returned at desk)."""
    report = get_object_or_404(LossReport, pk=report_id)
    if report.status not in ('pending', 'confirmed'):
        messages.warning(request, f'LR-{report.pk} cannot be recovered from status "{report.get_status_display()}".')
        return redirect('loss_report_list')

    copy = report.transaction.copy
    tx = report.transaction
    notes = request.POST.get('recovery_notes', '').strip()

    # Restore copy to available
    copy.status = 'available'
    copy.save(update_fields=['status'])

    # Mark transaction returned
    tx.status = 'returned'
    tx.return_date = timezone.now()
    tx.save(update_fields=['status', 'return_date'])

    # If there was a loss fine and it's unpaid, cancel it (waive) unless partially paid
    if report.loss_fine and not report.loss_fine.paid:
        if report.loss_fine.amount_paid == 0:
            report.loss_fine.delete()
            report.loss_fine = None

    report.status = 'resolved'
    report.reviewed_by = request.user
    report.reviewed_at = timezone.now()
    if notes:
        report.librarian_notes = (report.librarian_notes + '\n[RECOVERED] ' + notes).strip()
    else:
        report.librarian_notes = (report.librarian_notes + '\n[RECOVERED] Book physically returned at desk.').strip()
    report.save()

    notify_user(
        report.user,
        f"MSICT OLMS: Recovery confirmed for '{copy.book.title}' (LR-{report.pk}). "
        f"Thank you for returning the book. Any applicable fines have been reviewed.",
        'sms',
        message_type='loss_report',
    )
    log_audit(request.user, f"Book recovered for LR-{report.pk}: '{copy.book.title}'  by {report.user.username}", request)
    messages.success(request, f"Book '{copy.book.title}' marked as recovered. Copy restored to available.")
    return redirect('loss_report_list')
