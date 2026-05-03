# ============================================================
# circulation/views.py
# Views za mzunguko wote wa kukopa vitabu:
#   - Mwanachama: tuma ombi, fuatilia mikopo, hifadhi nafasi
#   - Mtunzaji: idhinisha/kataa maombi, rudisha vitabu, simamia faini
# ============================================================

from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.db.models import Q
from django.conf import settings
from datetime import timedelta

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
from .models import BorrowRequest, BorrowingTransaction, Reservation, Fine, Notification


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
        user=user, status__in=['borrowed', 'overdue']
    ).select_related('copy__book').order_by('due_date')
    overdue_transactions = active_transactions.filter(status='overdue')
    pending_requests = BorrowRequest.objects.filter(user=user, status='pending').select_related('copy__book')
    reservations = Reservation.objects.filter(
        user=user, status__in=['pending', 'notified']
    ).select_related('book')
    notified_reservations = reservations.filter(status='notified')
    unpaid_fines = Fine.objects.filter(user=user, paid=False)
    notifications = Notification.objects.filter(user=user).order_by('-created_at')[:10]
    borrow_history = BorrowingTransaction.objects.filter(
        user=user, status='returned'
    ).select_related('copy__book').order_by('-return_date')[:5]

    context = {
        'active_transactions': active_transactions,
        'overdue_transactions': overdue_transactions,
        'pending_requests': pending_requests,
        'reservations': reservations,
        'notified_reservations': notified_reservations,
        'unpaid_fines': unpaid_fines,
        'total_fines': sum(f.amount for f in unpaid_fines),
        'notifications': notifications,
        'has_overdue': overdue_transactions.exists(),
        'borrow_history': borrow_history,
    }
    return render(request, 'circulation/member_dashboard.html', context)


# ── Book-level borrow helpers (auto-pick a copy; one URL per book) ───────────
@login_required
def request_borrow_book_view(request, book_id):
    """Auto-selects the first available hardcopy and submits a borrow request."""
    book = get_object_or_404(Book, pk=book_id)
    copy = book.copies.filter(copy_type='hardcopy', status='available').first()
    if not copy:
        messages.error(request, f'No hardcopy is available for "{book.title}" right now.')
        return redirect('borrow_catalog')
    return redirect('submit_borrow_request', copy.pk)


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
    max_copies = int(_pref('MAX_COPIES_PER_BORROW', 3))
    if active_borrows >= max_copies:
        messages.error(request, f'Maximum of {max_copies} active borrows allowed. Return or clear overdue items first.')
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
    else:
        if copy.status != 'available':
            messages.error(request, 'This hardcopy is not available right now.')
            return redirect('book_detail_public', book_id=copy.book_id)

    BorrowRequest.objects.create(user=request.user, copy=copy)
    log_audit(request.user, f"Borrow request submitted for '{copy.book.title}' [{copy.accession_no}]", request)
    messages.success(request, f'Request submitted for "{copy.book.title}". Awaiting librarian approval.')
    return redirect('member_dashboard')


# Futa ombi la kukopa ambalo bado ni 'pending' (mwanachama anaweza kufuta yake tu)
@login_required
def cancel_borrow_request_view(request, request_id):
    req = get_object_or_404(BorrowRequest, pk=request_id, user=request.user, status='pending')
    req.status = 'cancelled'
    req.save(update_fields=['status'])
    messages.success(request, 'Borrow request cancelled.')
    return redirect('member_dashboard')


# Idhinisha ombi la kukopa (kwa mtunzaji au admin)
# Kwa hardcopy: inabadilisha hali ya nakala kuwa 'borrowed'
# Kwa softcopy: inatuma kiungo cha PDF kwa SMS na barua pepe
@login_required
@librarian_required
def approve_borrow_request_view(request, request_id):
    req = get_object_or_404(BorrowRequest, pk=request_id)
    if req.status != 'pending':
        messages.warning(request, f'Request #{request_id} is already {req.status} and cannot be approved again.')
        return redirect('all_requests')
    user = req.user
    copy = req.copy

    if user.has_overdue():
        req.status = 'rejected'
        req.rejection_reason = 'User has overdue books.'
        req.approved_by = request.user
        req.save()
        messages.error(request, f'Rejected: {user.username} has overdue books.')
        return redirect('librarian_dashboard')

    if copy.copy_type == 'hardcopy' and copy.status != 'available':
        messages.error(request, 'Hardcopy is no longer available.')
        return redirect('librarian_dashboard')

    tx = BorrowingTransaction.objects.create(
        user=user,
        copy=copy,
        borrow_type=copy.copy_type,
        approved_by=request.user,
    )
    if copy.copy_type == 'hardcopy':
        copy.status = 'borrowed'
        copy.save(update_fields=['status'])
        # Nearest due_date changed — recalculate queue expiry dates for this book
        _recalculate_reservation_expiries(copy.book)

    req.status = 'approved'
    req.approved_by = request.user
    req.save()

    if copy.copy_type == 'softcopy':
        # Build absolute URL for email only (not exposed in SMS)
        softcopy_url = request.build_absolute_uri(reverse('serve_softcopy', args=[copy.pk]))

        msg_sms = (f"MSICT OLMS: Your request for '{copy.book.title}' (Softcopy) has been approved. "
                   f"Due: {tx.due_date.date()}. Sign in to your dashboard to read the book.")
        msg_email = (f"Your request for '<b>{copy.book.title}</b>' (Softcopy) was approved.<br>"
                     f"<b>Due Date:</b> {tx.due_date.date()}<br>"
                     f"<b>Direct Link:</b> <a href='{softcopy_url}'>{softcopy_url}</a><br><br>"
                     f"Or visit <b>My Borrowings</b> on your dashboard to access all your softcopies.")
        msg_dashboard = f"'{copy.book.title}' (Softcopy) approved. Due: {tx.due_date.date()}. Click 'Read Online' below to access."
    else:
        msg_sms = (f"MSICT OLMS: Your borrow request for '{copy.book.title}' has been approved. "
                   f"Due: {tx.due_date.date()}. Go to library with your card or card number to take the book.")
        msg_email = (f"Your borrow request for '<b>{copy.book.title}</b>' has been approved.<br>"
                     f"<b>Due Date:</b> {tx.due_date.date()}<br><br>"
                     f"Please go to the library with your library card or card number to collect the book.")
        msg_dashboard = (f"'{copy.book.title}' approved. Due: {tx.due_date.date()}. "
                         f"Go to the library with your card to collect the book.")

    notify_user(user, msg_sms, 'sms')
    notify_user(user, msg_email, 'email', subject='MSICT OLMS - Borrow Approved')
    log_audit(request.user, f"Approved borrow request for '{user.username}' – '{copy.book.title}'", request)
    messages.success(request, f'Borrow approved for {user.username}.')
    return redirect('librarian_dashboard')


# Kataa ombi la kukopa — inahitaji sababu ya kukataa
# Mwanachama anapata arifa ya SMS na barua pepe
@login_required
@librarian_required
def reject_borrow_request_view(request, request_id):
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
def renew_transaction_view(request, transaction_id):
    tx = get_object_or_404(BorrowingTransaction, pk=transaction_id, user=request.user)
    if tx.renew():
        msg = f"MSICT OLMS: '{tx.copy.book.title}' renewed. New due date: {tx.due_date.date()}"
        notify_user(request.user, msg, 'sms')
        notify_user(request.user, msg, 'email', subject='Renewal Confirmation')
        log_audit(request.user, f"Renewed '{tx.copy.book.title}'. New due: {tx.due_date.date()}", request)
        messages.success(request, f'Renewed successfully. New due date: {tx.due_date.date()}')
    else:
        messages.error(request, 'Cannot renew. Check overdue status, max renewals, or reservations.')
    return redirect('member_dashboard')


# Rudisha softcopy mapema kabla ya muda haujaisha
@login_required
def return_early_view(request, transaction_id):
    tx = get_object_or_404(
        BorrowingTransaction, pk=transaction_id,
        user=request.user, status__in=['borrowed', 'overdue']
    )
    if tx.copy.copy_type != 'softcopy':
        messages.error(request, 'Only soft copies can be returned online. Bring hardcopies to the desk.')
        return redirect('member_dashboard')
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

    tx.return_date = timezone.now()
    tx.status      = 'returned'
    tx.save(update_fields=['return_date', 'status'])

    if copy.copy_type == 'hardcopy':
        copy.status = 'available'
        copy.save(update_fields=['status'])

    fine_per_day = float(_pref('FINE_PER_DAY', 500))
    if tx.days_overdue() > 0:
        fine_amount = tx.days_overdue() * fine_per_day
        Fine.objects.create(
            user=tx.user, transaction=tx, amount=fine_amount,
            reason=f"Overdue fine for '{copy.book.title}' ({tx.days_overdue()} days)",
        )
        messages.warning(request, f'"{copy.book.title}" returned with overdue fine of TZS {fine_amount:,.0f}.')
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
                return render(request, 'circulation/return_desk.html', {
                    'member':        member,
                    'member_borrows': member_borrows,
                    'card_input':    card_input,
                    'recent_returns': _get_recent_returns(),
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
def cancel_reservation_view(request, reservation_id):
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
def librarian_cancel_reservation_view(request, reservation_id):
    res = get_object_or_404(Reservation, pk=reservation_id, status__in=['pending', 'notified'])
    if request.method != 'POST':
        messages.error(request, 'Invalid request.')
        return redirect('reservation_list')
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
    overdue = BorrowingTransaction.objects.filter(status='overdue').select_related('user', 'copy__book').order_by('due_date')
    return render(request, 'circulation/overdue_list.html', {'overdue': overdue})


# Orodha ya faini zote — kwa mtunzaji
@login_required
@librarian_required
def fine_list_view(request):
    fines = Fine.objects.select_related('user', 'transaction__copy__book').order_by('-created_at')
    return render(request, 'circulation/fine_list.html', {'fines': fines})


# Rekodi malipo ya faini — mtunzaji anaweka nambari ya risiti na njia ya malipo
@login_required
@librarian_required
def record_fine_payment_view(request, fine_id):
    fine = get_object_or_404(Fine, pk=fine_id)
    if request.method == 'POST':
        fine.paid = True
        fine.payment_method = request.POST.get('payment_method', 'cash')
        fine.receipt_no = request.POST.get('receipt_no', '')
        fine.paid_at = timezone.now()
        fine.save()
        log_audit(request.user, f"Fine {fine.pk} paid by {fine.user.username}", request)
        messages.success(request, 'Fine payment recorded.')
        return redirect('fine_list')
    return render(request, 'circulation/fine_payment.html', {'fine': fine})


@login_required
@librarian_required
def circulation_desk_view(request):
    return render(request, 'circulation/circulation_desk.html')


@login_required
def member_msict_borrowings_view(request):
    """Member view for MSICT borrowings - history, pending, active"""
    user = request.user

    # Active borrowings (borrowed or overdue)
    active_borrows = BorrowingTransaction.objects.filter(
        user=user, status__in=['borrowed', 'overdue']
    ).select_related('copy__book').order_by('-borrow_date')

    # Borrow history (returned)
    borrow_history = BorrowingTransaction.objects.filter(
        user=user, status='returned'
    ).select_related('copy__book').order_by('-return_date')[:50]

    # Pending borrow requests
    pending_requests = BorrowRequest.objects.filter(
        user=user, status='pending'
    ).select_related('copy__book').order_by('-request_date')

    # Rejected/Cancelled requests
    rejected_requests = BorrowRequest.objects.filter(
        user=user, status__in=['rejected', 'cancelled']
    ).select_related('copy__book').order_by('-request_date')[:20]

    # Current reservations
    reservations = Reservation.objects.filter(
        user=user, status='pending'
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

    context = {
        'active_borrows': active_borrows,
        'borrow_history': borrow_history,
        'pending_requests': pending_requests,
        'rejected_requests': rejected_requests,
        'reservations': reservations,
        'reservation_history': reservation_history,
        'unpaid_fines': unpaid_fines,
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
    pending_copy_ids = set(
        BorrowRequest.objects.filter(
            user=user, status='pending', copy__copy_type='softcopy'
        ).values_list('copy_id', flat=True)
    )

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
def renew_reservation_view(request, reservation_id):
    """Librarian renews an expired or pending reservation by resetting expires_at to 14 days from now."""
    res = get_object_or_404(Reservation, pk=reservation_id)
    if request.method == 'POST':
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

    return render(request, 'circulation/all_borrowings.html', {
        'transactions':      qs,
        'status_filter':     status_filter,
        'copy_type_filter':  copy_type_filter,
        'query':             query,
        'counts':            counts,
        'now':               tz.now(),
    })
