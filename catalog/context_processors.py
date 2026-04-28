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
