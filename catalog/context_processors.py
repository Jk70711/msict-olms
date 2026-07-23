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
    member_active_borrowings = 0
    member_reservations = 0
    member_unpaid_fines = 0
    try:
        if request.user.is_authenticated:
            from circulation.models import (
                Notification, BorrowRequest, Reservation,
                BorrowingTransaction, Fine, LossReport,
            )
            from accounts.models import OLMSUser, LoginAttempt
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

                # Suspicious/Suspended Members: match suspended_members_view
                # (failed_attempts >= 3, role='member')
                su_last = _badge_last_viewed(request.user, 'suspicious_users')
                su_qs = OLMSUser.objects.filter(failed_attempts__gte=3, role='member')
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

                # Suspicious IPs: last 1h with >=5 failed attempts (match suspicious_activity_view)
                window_1h = timezone.now() - timedelta(hours=1)
                si_last = _badge_last_viewed(request.user, 'suspicious_ips')
                si_qs = LoginAttempt.objects.filter(status='failed', timestamp__gte=window_1h)
                if si_last and si_last > window_1h:
                    si_qs = si_qs.filter(timestamp__gt=si_last)
                suspicious_ips_count = si_qs.values('ip_address').annotate(
                    total=Sum('attempt_count')
                ).filter(total__gte=5).count()

                # Recent failed logins: match suspicious_activity_view (last 24h)
                window_24h = timezone.now() - timedelta(days=1)
                recent_failed_logins_count = LoginAttempt.objects.filter(
                    status='failed', timestamp__gte=window_24h
                ).count()

                # Pending Registrations: match public_registrations_view
                # (role='member', registration_status='pending')
                pr_last = _badge_last_viewed(request.user, 'pending_registrations')
                pr_qs = OLMSUser.objects.filter(role='member', registration_status='pending')
                if pr_last:
                    pr_qs = pr_qs.filter(created_at__gt=pr_last)
                pending_registrations_count = pr_qs.count()

            # ── Librarian/Admin counts ──
            if request.user.role in ('admin', 'librarian'):
                # Pending Borrow Requests: match all_requests_view with status='pending'
                br_last = _badge_last_viewed(request.user, 'pending_requests')
                br_qs = BorrowRequest.objects.filter(status='pending')
                if br_last:
                    br_qs = br_qs.filter(request_date__gt=br_last)
                pending_requests_count = br_qs.count()

            # ── Member-specific counts (match actual page queries) ──
            if request.user.role == 'member':
                # Active Borrowings: match member_msict_borrowings_view
                # (borrowed/overdue/lost, exclude expired special softcopies)
                now = timezone.now()
                mb_last = _badge_last_viewed(request.user, 'member_active_borrowings')
                mb_qs = BorrowingTransaction.objects.filter(
                    user=request.user,
                    status__in=['borrowed', 'overdue', 'lost'],
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
        'member_active_borrowings': member_active_borrowings,
        'member_reservations': member_reservations,
        'member_unpaid_fines': member_unpaid_fines,
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
