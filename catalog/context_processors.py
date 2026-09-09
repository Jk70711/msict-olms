def _badge_last_viewed(user, badge_key):
    """Return last_viewed_at for a badge, or None if never viewed."""
    from accounts.utils import get_badge_last_viewed
    return get_badge_last_viewed(user, badge_key)


def security_badges(request):
    """Pass unseen counts for sidebar badges (available on every page).
    Each count shows only items created AFTER the user's last visit to that page.
    Visiting the page resets the count to 0 via mark_badge_viewed()."""
    security_alerts_count = 0
    suspicious_users_count = 0
    locked_accounts_count = 0
    suspicious_ips_count = 0
    recent_failed_logins_count = 0
    pending_requests_count = 0
    pending_registrations_count = 0
    pending_loss_reports_count = 0
    pending_reservations_count = 0
    unpaid_fines_count = 0
    pending_damage_reports_count = 0
    pending_ill_requests_count = 0
    active_guest_sessions_count = 0
    member_active_borrowings = 0
    member_reservations = 0
    member_unpaid_fines = 0
    member_ill_pending = 0
    member_loss_fines = 0
    member_damage_fines = 0
    try:
        if request.user.is_authenticated:
            from circulation.models import (
                Notification, BorrowRequest, Reservation,
                BorrowingTransaction, Fine, LossReport, DamageReport,
            )
            from accounts.models import OLMSUser, LoginAttempt, GuestSession, SystemPreference
            from django.db.models import Q, Count, Sum
            from datetime import timedelta
            from django.utils import timezone
            from django.db.models import F

            # ── Admin-specific counts (match actual page queries) ──
            if request.user.role == 'admin':
                # Security Alerts: match security_alerts_view (ALL is_security_alert=True)
                sa_last = _badge_last_viewed(request.user, 'security_alerts')
                sa_qs = Notification.objects.filter(is_security_alert=True)
                if sa_last:
                    sa_qs = sa_qs.filter(created_at__gt=sa_last)
                security_alerts_count = sa_qs.count()

                # Suspicious/Suspended Members: match suspended_members_view logic
                # Only count users currently suspended (within suspend_duration) or permanently locked
                from datetime import timedelta as _td
                _suspend_at = int(SystemPreference.get('SUSPEND_ATTEMPTS', 3) or 3)
                _suspend_dur = int(SystemPreference.get('SUSPEND_DURATION_MINUTES', 10) or 10)
                _lock_at = int(SystemPreference.get('MAX_LOGIN_ATTEMPTS', 6) or 6)
                _cutoff = timezone.now() - _td(minutes=_suspend_dur)
                _suspended_unames = set(
                    LoginAttempt.objects.filter(
                        status='failed', timestamp__gte=_cutoff
                    ).values_list('username', flat=True)
                )
                su_last = _badge_last_viewed(request.user, 'suspicious_users')
                su_qs = OLMSUser.objects.filter(
                    Q(
                        failed_attempts__gte=_suspend_at,
                        username__in=_suspended_unames,
                        is_active=True,
                    ) | Q(
                        is_active=False,
                        failed_attempts__gte=_lock_at,
                    )
                )
                if su_last:
                    su_qs = su_qs.filter(created_at__gt=su_last)
                suspicious_users_count = su_qs.count()

                # Locked Accounts: match user_list?status=locked
                # (non-admin, inactive OR pending registration)
                la_last = _badge_last_viewed(request.user, 'locked_users')
                la_qs = OLMSUser.objects.exclude(role='admin').filter(
                    Q(is_active=False) | Q(registration_status='pending')
                ).distinct()
                if la_last:
                    la_qs = la_qs.filter(created_at__gt=la_last)
                locked_accounts_count = la_qs.count()

                # Suspicious IPs: match suspicious_activity_view (configurable window and threshold)
                _si_window = timezone.now() - timedelta(minutes=_suspend_dur)
                si_last = _badge_last_viewed(request.user, 'suspicious_ips')
                si_qs = LoginAttempt.objects.filter(status='failed', timestamp__gte=_si_window)
                if si_last and si_last > _si_window:
                    si_qs = si_qs.filter(timestamp__gt=si_last)
                suspicious_ips_count = si_qs.values('ip_address').annotate(
                    total=Sum('attempt_count')
                ).filter(total__gte=_suspend_at).count()

                # Recent failed logins: match suspicious_activity_view (last 24h)
                window_24h = timezone.now() - timedelta(days=1)
                recent_failed_logins_count = LoginAttempt.objects.filter(
                    status='failed', timestamp__gte=window_24h
                ).count()

            # ── Librarian/Admin counts ──
            if request.user.role in ('admin', 'librarian'):
                # Pending Borrow Requests: match all_requests_view with status='pending'
                br_last = _badge_last_viewed(request.user, 'pending_requests')
                br_qs = BorrowRequest.objects.filter(status='pending')
                if br_last:
                    br_qs = br_qs.filter(request_date__gt=br_last)
                pending_requests_count = br_qs.count()

                # Pending Registrations: match public_registrations_view
                # (role='member', registration_status='pending')
                pr_last = _badge_last_viewed(request.user, 'pending_registrations')
                pr_qs = OLMSUser.objects.filter(role='member', registration_status='pending')
                if pr_last:
                    pr_qs = pr_qs.filter(created_at__gt=pr_last)
                pending_registrations_count = pr_qs.count()

                # Pending Loss Reports: match loss_report_list_view with status='pending'
                lr_last = _badge_last_viewed(request.user, 'pending_loss_reports')
                lr_qs = LossReport.objects.filter(status='pending')
                if lr_last:
                    lr_qs = lr_qs.filter(reported_at__gt=lr_last)
                pending_loss_reports_count = lr_qs.count()

                # Pending Reservations: match reservation_list_view (pending + notified)
                res_last = _badge_last_viewed(request.user, 'pending_reservations')
                res_qs = Reservation.objects.filter(status__in=['pending', 'notified'])
                if res_last:
                    res_qs = res_qs.filter(created_at__gt=res_last)
                pending_reservations_count = res_qs.count()

                # Unpaid Fines: match fine_list_view (paid=False)
                uf_last = _badge_last_viewed(request.user, 'unpaid_fines')
                uf_qs = Fine.objects.filter(paid=False)
                if uf_last:
                    uf_qs = uf_qs.filter(created_at__gt=uf_last)
                unpaid_fines_count = uf_qs.count()

                # Pending Damage Reports: DamageReport with unpaid damage fines
                dr_last = _badge_last_viewed(request.user, 'pending_damage_reports')
                dr_qs = DamageReport.objects.filter(
                    damage_fine__isnull=False, damage_fine__paid=False
                )
                if dr_last:
                    dr_qs = dr_qs.filter(reported_at__gt=dr_last)
                pending_damage_reports_count = dr_qs.count()

                # Pending ILL Requests: match ill_request_list_view with status='pending'
                from acquisitions.models import ILLRequest
                ill_last = _badge_last_viewed(request.user, 'pending_ill_requests')
                ill_qs = ILLRequest.objects.filter(status='pending')
                if ill_last:
                    ill_qs = ill_qs.filter(request_date__gt=ill_last)
                pending_ill_requests_count = ill_qs.count()

                # Active Guest Sessions: match guest_manage_view
                gs_last = _badge_last_viewed(request.user, 'active_guest_sessions')
                gs_qs = GuestSession.objects.filter(status__in=['active', 'renewed'])
                if gs_last:
                    gs_qs = gs_qs.filter(sign_in_time__gt=gs_last)
                active_guest_sessions_count = gs_qs.count()

            # ── Member-specific counts (match actual page queries) ──
            if request.user.role == 'member':
                # Active Borrowings: match member_msict_borrowings_view
                # (borrowed/overdue only, exclude expired special softcopies)
                now = timezone.now()
                mb_last = _badge_last_viewed(request.user, 'member_active_borrowings')
                mb_qs = BorrowingTransaction.objects.filter(
                    user=request.user,
                    status__in=['borrowed', 'overdue'],
                    copy__book__isnull=False,
                ).exclude(
                    copy__copy_type='softcopy',
                    copy__access_type='borrow',
                    due_date__lt=now,
                )
                if mb_last:
                    mb_qs = mb_qs.filter(borrow_date__gt=mb_last)
                member_active_borrowings = mb_qs.count()

                # Reservations: match my_reservations_view
                mr_last = _badge_last_viewed(request.user, 'member_reservations')
                mr_qs = Reservation.objects.filter(user=request.user, status__in=['pending', 'notified'])
                if mr_last:
                    mr_qs = mr_qs.filter(created_at__gt=mr_last)
                member_reservations = mr_qs.count()

                # Unpaid Fines: match my_fines_view (exclude loss fines)
                loss_fine_ids = set(
                    LossReport.objects.filter(
                        user=request.user, loss_fine__isnull=False
                    ).values_list('loss_fine_id', flat=True)
                )
                mf_last = _badge_last_viewed(request.user, 'member_unpaid_fines')
                mf_qs = Fine.objects.filter(user=request.user, paid=False).exclude(id__in=loss_fine_ids)
                if mf_last:
                    mf_qs = mf_qs.filter(created_at__gt=mf_last)
                member_unpaid_fines = mf_qs.count()

                # ILL Pending: match member_ill_borrowings_view (pending status)
                from acquisitions.models import ILLRequest
                mil_last = _badge_last_viewed(request.user, 'member_ill_pending')
                mil_qs = ILLRequest.objects.filter(user=request.user, status='pending')
                if mil_last:
                    mil_qs = mil_qs.filter(request_date__gt=mil_last)
                member_ill_pending = mil_qs.count()

                # Loss Fines: match my_loss_reports_view (unpaid loss fines)
                ml_last = _badge_last_viewed(request.user, 'member_loss_fines')
                ml_qs = LossReport.objects.filter(
                    user=request.user, loss_fine__isnull=False, loss_fine__paid=False
                )
                if ml_last:
                    ml_qs = ml_qs.filter(reported_at__gt=ml_last)
                member_loss_fines = ml_qs.count()

                # Damage Fines: match my_damage_reports_view (unpaid damage fines)
                md_last = _badge_last_viewed(request.user, 'member_damage_fines')
                md_qs = DamageReport.objects.filter(
                    user=request.user, damage_fine__isnull=False, damage_fine__paid=False
                )
                if md_last:
                    md_qs = md_qs.filter(reported_at__gt=md_last)
                member_damage_fines = md_qs.count()
    except Exception:
        pass
    return {
        'security_alerts_count': security_alerts_count,
        'suspicious_users_count': suspicious_users_count,
        'locked_users': locked_accounts_count,
        'suspicious_ips_count': suspicious_ips_count,
        'recent_failed_logins_count': recent_failed_logins_count,
        'pending_requests_count': pending_requests_count,
        'pending_registrations_count': pending_registrations_count,
        'pending_loss_reports_count': pending_loss_reports_count,
        'pending_reservations_count': pending_reservations_count,
        'unpaid_fines_count': unpaid_fines_count,
        'pending_damage_reports_count': pending_damage_reports_count,
        'pending_ill_requests_count': pending_ill_requests_count,
        'active_guest_sessions_count': active_guest_sessions_count,
        'member_active_borrowings': member_active_borrowings,
        'member_reservations': member_reservations,
        'member_unpaid_fines': member_unpaid_fines,
        'member_ill_pending': member_ill_pending,
        'member_loss_fines': member_loss_fines,
        'member_damage_fines': member_damage_fines,
    }


def overdue_counter(request):
    """Pass overdue count to templates for sidebar badge.
    Matches overdue_list_view: status='overdue' with unpaid fine or no fine,
    excluding special softcopies (they auto-expire, never overdue)."""
    count = 0
    try:
        if request.user.is_authenticated and request.user.role in ('admin', 'librarian'):
            from circulation.models import BorrowingTransaction, Fine
            from django.db.models import Exists, OuterRef, F
            has_unpaid_fine = Exists(
                Fine.objects.filter(
                    transaction=OuterRef('pk'), paid=False,
                    amount__gt=F('amount_paid')
                )
            )
            has_no_fine = ~Exists(
                Fine.objects.filter(transaction=OuterRef('pk'))
            )
            od_last = _badge_last_viewed(request.user, 'overdue')
            od_qs = BorrowingTransaction.objects.filter(
                status='overdue'
            ).exclude(
                copy__copy_type='softcopy',
                copy__access_type='borrow'
            ).filter(
                has_unpaid_fine | has_no_fine
            )
            if od_last:
                od_qs = od_qs.filter(due_date__gt=od_last)
            count = od_qs.count()
    except Exception:
        pass
    return {'overdue_count': count}


def active_logo(request):
    try:
        from .models import MediaSlide
        logo = MediaSlide.get_active_logo()
    except Exception:
        logo = None
    return {'active_logo': logo}


def active_footer_cp(request):
    try:
        from .models import Footer
        footer = Footer.get_active_footer()
    except Exception:
        footer = None
    return {'active_footer': footer}


def system_appearance(request):
    try:
        from accounts.models import SystemPreference
        KEYS = ['APP_FONT_FAMILY', 'APP_FONT_SIZE', 'APP_FONT_COLOR', 'APP_BODY_BG',
                'APP_SIDEBAR_BG', 'APP_TOPBAR_BG', 'APP_FOOTER_BG']
        prefs = dict(SystemPreference.objects.filter(key__in=KEYS).values_list('key', 'value'))
    except Exception:
        prefs = {}
    return {'sys_ap': prefs}


def category_menu(request):
    try:
        from .models import Category, BookCopy, Shelf
        from django.db.models import Count, Q, Prefetch

        cats = list(
            Category.objects.filter(parent__isnull=True)
            .prefetch_related(
                Prefetch('shelves',
                         queryset=Shelf.objects.order_by('shelf_number'),
                         to_attr='_shelves')
            )
            .annotate(
                book_count=Count('books', distinct=True),
                hardcopy_count=Count(
                    'books__copies',
                    filter=Q(books__copies__copy_type='hardcopy'),
                    distinct=True,
                ),
                softcopy_count=Count(
                    'books__copies',
                    filter=Q(books__copies__copy_type='softcopy'),
                    distinct=True,
                ),
            )
            .order_by('name')
        )

        fill_map = dict(
            BookCopy.objects
            .filter(copy_type='hardcopy')
            .exclude(shelf_location__isnull=True)
            .exclude(shelf_location='')
            .values('shelf_location')
            .annotate(cnt=Count('pk'))
            .values_list('shelf_location', 'cnt')
        )

        from circulation.models import BorrowingTransaction
        borrow_map = dict(
            BorrowingTransaction.objects
            .filter(status__in=['borrowed', 'overdue'])
            .values('copy__book__category_id')
            .annotate(cnt=Count('pk'))
            .values_list('copy__book__category_id', 'cnt')
        )

        def _cls(pct):
            if pct >= 90: return 'danger'
            if pct >= 70: return 'warn'
            return ''

        for cat in cats:
            cat.active_borrows = borrow_map.get(cat.pk, 0)

            cat_shelves = []
            total_cap = 0
            total_fill = 0
            for shelf in cat._shelves:
                cap  = shelf.capacity or 0
                fill = fill_map.get(shelf.shelf_code, 0)
                pct  = min(round((fill / cap) * 100), 100) if cap > 0 else 0
                cat_shelves.append({
                    'code':     shelf.shelf_code,
                    'number':   shelf.shelf_number,
                    'name':     shelf.name,
                    'capacity': cap,
                    'fill':     fill,
                    'pct':      pct,
                    'cls':      _cls(pct),
                })
                total_cap  += cap
                total_fill += fill

            cat.cat_shelves    = cat_shelves
            cat.shelf_count    = len(cat_shelves)
            cat.total_capacity = total_cap
            cat.fill_pct  = min(round((total_fill / total_cap) * 100), 100) if total_cap > 0 else 0
            cat.fill_cls  = _cls(cat.fill_pct)

    except Exception:
        cats = []

    return {'cat_menu': cats}


def guest_expiry_alerts(request):
    """Inject expiring-soon guest sessions for the librarian in-app popup.

    For librarians and admins only: returns a list of active sessions that
    will expire within the next 5 minutes (300 seconds), with full detail
    per session so the librarian popup can show a per-guest countdown table.

    Returned context key: ``librarian_expiring_sessions``  — a list of dicts:
        id, name, username, phone, session_id, paid_hours, amount_paid,
        expiry_iso (ISO-8601), minutes_left, seconds_left
    """
    empty = {'librarian_expiring_sessions': []}
    try:
        user = getattr(request, 'user', None)
        if not (user and user.is_authenticated and getattr(user, 'role', '') in ('admin', 'librarian')):
            return empty

        from accounts.models import GuestSession
        from django.utils import timezone
        from datetime import timedelta

        now = timezone.now()
        window_end = now + timedelta(minutes=5)

        active = GuestSession.objects.filter(
            status__in=['active', 'renewed']
        ).select_related('user').order_by('sign_in_time')

        expiring = []
        for s in active:
            expiry = s.sign_in_time + timedelta(hours=float(s.paid_hours))
            delta = expiry - now
            total_secs = delta.total_seconds()
            # Include sessions expiring between now and 5 min from now
            if 0 < total_secs <= 300:
                mins_left = int(total_secs // 60)
                secs_left = int(total_secs % 60)
                expiring.append({
                    'id': s.id,
                    'name': s.user.get_full_name() or s.user.username,
                    'username': s.user.username,
                    'phone': getattr(s.user, 'phone', '') or '',
                    'paid_hours': float(s.paid_hours),
                    'amount_paid': float(s.amount_paid),
                    'payment_status': s.get_payment_status_display(),
                    'expiry_iso': expiry.isoformat(),
                    'expiry_display': expiry.strftime('%H:%M'),
                    'mins_left': mins_left,
                    'secs_left': secs_left,
                })

        return {'librarian_expiring_sessions': expiring}
    except Exception:
        return empty
