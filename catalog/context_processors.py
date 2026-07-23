def security_badges(request):
    """Pass accurate counts for sidebar badges (available on every page).
    Each count matches the actual query used by the corresponding list view."""
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
                security_alerts_count = Notification.objects.filter(
                    is_security_alert=True
                ).count()

                # Suspicious/Suspended Members: match suspended_members_view
                # (failed_attempts >= 3, role='member')
                suspicious_users_count = OLMSUser.objects.filter(
                    failed_attempts__gte=3, role='member'
                ).count()

                # Locked Accounts: match user_list?status=locked
                # (non-admin, inactive OR pending registration)
                locked_accounts_count = OLMSUser.objects.exclude(
                    role='admin'
                ).filter(
                    Q(is_active=False) | Q(registration_status='pending')
                ).distinct().count()

                # Suspicious IPs: last 1h with >=5 failed attempts (match suspicious_activity_view)
                window_1h = timezone.now() - timedelta(hours=1)
                suspicious_ips_count = LoginAttempt.objects.filter(
                    status='failed', timestamp__gte=window_1h
                ).values('ip_address').annotate(
                    total=Sum('attempt_count')
                ).filter(total__gte=5).count()

                # Recent failed logins: match suspicious_activity_view (last 24h)
                window_24h = timezone.now() - timedelta(days=1)
                recent_failed_logins_count = LoginAttempt.objects.filter(
                    status='failed', timestamp__gte=window_24h
                ).count()

                # Pending Registrations: match public_registrations_view
                # (role='member', registration_status='pending')
                pending_registrations_count = OLMSUser.objects.filter(
                    role='member', registration_status='pending'
                ).count()

            # ── Librarian/Admin counts ──
            if request.user.role in ('admin', 'librarian'):
                # Pending Borrow Requests: match all_requests_view with status='pending'
                pending_requests_count = BorrowRequest.objects.filter(
                    status='pending'
                ).count()

            # ── Member-specific counts (match actual page queries) ──
            if request.user.role == 'member':
                # Active Borrowings: match member_msict_borrowings_view
                # (borrowed/overdue/lost, exclude expired special softcopies)
                now = timezone.now()
                member_active_borrowings = BorrowingTransaction.objects.filter(
                    user=request.user,
                    status__in=['borrowed', 'overdue', 'lost'],
                    copy__book__isnull=False,
                ).exclude(
                    copy__copy_type='softcopy',
                    copy__access_type='borrow',
                    due_date__lt=now,
                ).count()

                # Reservations: match my_reservations_view
                member_reservations = Reservation.objects.filter(
                    user=request.user, status__in=['pending', 'notified']
                ).count()

                # Unpaid Fines: match my_fines_view (exclude loss fines)
                loss_fine_ids = set(
                    LossReport.objects.filter(
                        user=request.user, loss_fine__isnull=False
                    ).values_list('loss_fine_id', flat=True)
                )
                member_unpaid_fines = Fine.objects.filter(
                    user=request.user, paid=False
                ).exclude(id__in=loss_fine_ids).count()
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
            count = BorrowingTransaction.objects.filter(
                status='overdue'
            ).exclude(
                copy__copy_type='softcopy',
                copy__access_type='borrow'
            ).filter(
                has_unpaid_fine | has_no_fine
            ).count()
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
