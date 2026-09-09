# ============================================================
# chatbot/services/library.py
# Internal-database search functions used as Gemini "tools".
# All functions return plain JSON-serialisable dicts/lists.
# ============================================================

from urllib.parse import quote_plus

from django.db.models import Q, Count
from django.urls import reverse
from django.conf import settings

from catalog.models import Book, BookCopy, Category


def _book_to_dict(book, include_copies=False):
    """Serialise a Book for the chatbot."""
    avail_hard = book.available_hardcopy_count()
    free_soft  = book.free_softcopy_count()
    spec_soft  = book.available_special_softcopy_count()
    total_avail = avail_hard + free_soft + spec_soft
    available = total_avail > 0

    data = {
        'id':         book.id,
        'title':      book.title,
        'author':     book.author or '—',
        'isbn':       book.isbn or '',
        'year':       book.year,
        'publisher':  book.publisher or '',
        'category':   book.category.name if book.category_id else '',
        'summary':    (book.summary or '')[:400],
        'cover_url':  book.cover_image.url if book.cover_image else '',
        'detail_url': reverse('book_detail_public', args=[book.id]),
        'availability': {
            'available':         available,
            'hardcopy_available': avail_hard,
            'free_softcopy':     free_soft,
            'special_softcopy_available': spec_soft,
            'total_hardcopies':  book.total_hardcopies(),
        },
    }

    if include_copies:
        copies = book.copies.all().order_by('copy_type', 'accession_no')[:20]
        data['copies'] = [{
            'accession_no':   c.accession_no,
            'copy_type':      c.copy_type,
            'access_type':    c.access_type or '',
            'status':         c.status,
            'shelf_location': c.shelf_location or '',
        } for c in copies]

    return data


# ----------------------------------------------------------------------
# TOOL: search_library_books
# ----------------------------------------------------------------------
def search_library_books(query='', author='', category='', limit=8):
    """
    Search MSICT library for books by title / author / category.
    Returns: { 'count': int, 'books': [book_dict, ...] }
    """
    q_obj = Q()
    if query:
        q_obj |= Q(title__icontains=query)
        q_obj |= Q(isbn__icontains=query)
        q_obj |= Q(summary__icontains=query)
        q_obj |= Q(author__icontains=query)
    if author:
        q_obj &= Q(author__icontains=author)
    if category:
        q_obj &= (Q(category__name__icontains=category) |
                  Q(category__parent__name__icontains=category))

    if not q_obj:
        return {'count': 0, 'books': [], 'message': 'No search terms supplied.'}

    # Oracle cannot apply DISTINCT to queries that select NCLOB columns
    # (Book.summary / Book.marc_xml). Resolve the dedup on plain integer
    # IDs first, then fetch the full rows for those IDs.
    cap = max(1, min(int(limit), 20))
    ids = list(
        Book.objects.filter(q_obj)
        .values_list('id', flat=True)
        .distinct()[:cap]
    )
    qs = Book.objects.filter(id__in=ids).select_related('category')
    books = [_book_to_dict(b) for b in qs]
    return {'count': len(books), 'books': books}


# ----------------------------------------------------------------------
# TOOL: get_book_detail
# ----------------------------------------------------------------------
def get_book_detail(book_id):
    """Return full info (with copies & shelf locations) for one book."""
    try:
        book = Book.objects.select_related('category').get(pk=int(book_id))
    except (Book.DoesNotExist, ValueError, TypeError):
        return {'error': f'Book id={book_id} not found.'}
    return _book_to_dict(book, include_copies=True)


# ----------------------------------------------------------------------
# TOOL: suggest_similar_books
# ----------------------------------------------------------------------
def suggest_similar_books(query='', author='', category='', exclude_id=None, limit=5):
    """
    Suggest similar books when requested book is unavailable or not found.
    Searches by same category, author, or keywords.
    """
    base = Book.objects.all()
    if exclude_id:
        base = base.exclude(pk=int(exclude_id))

    q_obj = Q()
    if category:
        q_obj |= Q(category__name__icontains=category)
        q_obj |= Q(category__parent__name__icontains=category)
    if author:
        q_obj |= Q(author__icontains=author)
    if query:
        keywords = [k for k in query.split() if len(k) > 3]
        for kw in keywords[:3]:
            q_obj |= Q(title__icontains=kw)
            q_obj |= Q(summary__icontains=kw)

    cap = max(1, int(limit or 5))

    # Oracle ORA-22848 workaround: dedup on integer ids first.
    if not q_obj:
        ids = list(
            base.filter(copies__status='available')
            .values_list('id', flat=True)
            .distinct()[:cap]
        )
    else:
        ids = list(
            base.filter(q_obj)
            .values_list('id', flat=True)
            .distinct()[:cap]
        )

    books = list(Book.objects.filter(id__in=ids).select_related('category'))

    return {
        'count': len(books),
        'books': [_book_to_dict(b) for b in books],
        'suggestion_reason': f"Showing books similar to '{query}'" if query else "Showing available books"
    }


# ----------------------------------------------------------------------
# TOOL: list_categories
# ----------------------------------------------------------------------
def list_categories(**kwargs):
    """Return top-level categories with their book counts."""
    cats = (Category.objects
            .filter(parent__isnull=True)
            .order_by('name'))
    return {
        'categories': [{
            'id':    c.id,
            'name':  c.name,
            'count': c.books.count(),
        } for c in cats]
    }


# ----------------------------------------------------------------------
# TOOL: get_library_info
# ----------------------------------------------------------------------
def get_library_info():
    """Return comprehensive MSICT library policies from the SystemPreference DB."""
    def _p(key, default):
        try:
            from accounts.models import SystemPreference
            val = SystemPreference.objects.filter(key=key).values_list('value', flat=True).first()
            if val is not None:
                return val
        except Exception:
            pass
        return getattr(settings, key, default)

    loan_days      = int(_p('LOAN_PERIOD_DAYS',           7))
    max_renewals   = int(_p('MAX_RENEWALS',                2))
    renew_window   = int(_p('RENEWAL_WINDOW_DAYS',         2))
    max_copies     = int(_p('MAX_COPIES_PER_BORROW',       3))
    fine_per_day   = float(_p('FINE_PER_DAY',              1000))
    resv_expiry    = int(_p('RESERVATION_EXPIRY_DAYS',     7))
    guest_max_hrs  = int(_p('GUEST_MAX_HOURS',             12))
    guest_rate     = float(_p('GUEST_HOURLY_RATE',         500))
    soft_fee       = float(_p('SOFTCOPY_PREPAID_FEE',      0))
    otp_validity   = int(_p('OTP_VALIDITY_MINUTES',        10))
    max_attempts   = int(_p('MAX_LOGIN_ATTEMPTS',          6))
    suspend_at     = int(_p('SUSPEND_ATTEMPTS',            3))
    suspend_dur    = int(_p('SUSPEND_DURATION_MINUTES',    10))
    session_tmout  = int(_p('SESSION_TIMEOUT_MINUTES',     30))
    pwd_expiry     = int(_p('PASSWORD_EXPIRY_DAYS',        90))
    pwd_history    = int(_p('PASSWORD_HISTORY_DEPTH',      5))
    auto_lockout   = _p('ENABLE_AUTO_LOCKOUT',             '1') == '1'
    notify_enabled = _p('NEW_ARRIVAL_NOTIFY_ENABLED',      '1') == '1'
    notify_channel = str(_p('NEW_ARRIVAL_NOTIFY_CHANNEL',  'sms'))

    return {
        'name':        'MSICT Library',
        'institution': 'Military School of Information and Communication Technology',

        # ── Borrowing ──────────────────────────────────────────────────────
        'borrowing': {
            'loan_period_days':        loan_days,
            'max_copies_per_borrow':   max_copies,
            'reservation_expiry_days': resv_expiry,
            'note': (
                f"Members may borrow up to {max_copies} book(s) at a time. "
                f"Each loan lasts {loan_days} day(s). "
                f"To borrow, log in → open book detail page → click Borrow. "
                f"Reservations use a smart queue expiry formula: queue position 1 waits "
                f"until the current borrower returns (approx. {loan_days} days), then each "
                f"subsequent queue member adds {loan_days} days + 1 day (24-hr claim window)."
            ),
        },

        # ── Renewals ───────────────────────────────────────────────────────
        'renewals': {
            'max_renewals':        max_renewals,
            'renewal_window_days': renew_window,
            'note': (
                f"A borrowing can be renewed up to {max_renewals} time(s). "
                f"Renewal is only allowed when {renew_window} day(s) or fewer remain before the due date, "
                f"or when the link has expired (softcopy). "
                f"Books with pending reservations cannot be renewed. "
                f"Unpaid fines block renewal of hardcopy books."
            ),
        },

        # ── Fines ──────────────────────────────────────────────────────────
        'fines': {
            'overdue_fine_per_day_tzs': fine_per_day,
            'note': (
                f"Overdue hardcopy books are charged TZS {fine_per_day:,.0f} per day. "
                f"Softcopy (digital) books do NOT incur overdue fines — the access link simply expires. "
                f"Fines must be paid at the circulation desk before borrowing more books. "
                f"Loss fine: charged based on the replacement cost of the book. "
                f"Damage fine: assessed by librarian based on level of damage."
            ),
        },

        # ── Softcopy / Digital Books ────────────────────────────────────────
        'softcopy': {
            'prepaid_fee_tzs': soft_fee,
            'note': (
                f"Softcopy (digital/ebook) books are accessed via a secure time-limited link. "
                f"{'Free access — no fee required.' if soft_fee == 0 else f'Access fee: TZS {soft_fee:,.0f} per borrow period.'} "
                f"The link is valid for {loan_days} day(s) (same as the loan period). "
                f"After expiry, you can renew (pay again if fee > 0) up to {max_renewals} time(s). "
                f"Softcopy books do not have overdue fines — link simply expires."
            ),
        },

        # ── Guest Sessions ──────────────────────────────────────────────────
        'guest_sessions': {
            'max_hours_per_day': guest_max_hrs,
            'hourly_rate_tzs':   guest_rate,
            'note': (
                f"Guest users can access library facilities (reading room/internet) without a full membership. "
                f"Guests pay TZS {guest_rate:,.0f} per hour. "
                f"Maximum session time is {guest_max_hrs} hour(s) per day. "
                f"To start a session: log in as guest → go to Guest Dashboard → click Pay & Start Session. "
                f"Sessions can be extended (renewed) before they expire. "
                f"Total daily usage cannot exceed {guest_max_hrs} hour(s). "
                f"Guests CANNOT borrow books — they can only use in-house resources."
            ),
        },

        # ── Damage & Loss Reports ───────────────────────────────────────────
        'damage_and_loss': {
            'note': (
                "If a borrowed book is damaged: the member or librarian files a Damage Report. "
                "The librarian assesses the damage level and sets a damage fine. "
                "The fine must be paid at the circulation desk before further borrowing. "
                "If a book is lost: the member or librarian files a Loss Report. "
                "A loss fine (replacement cost) is charged. "
                "Once the fine is paid, the member's account is cleared. "
                "Both damage and loss reports are tracked in the member's dashboard under 'My Reports'."
            ),
        },

        # ── Security & Accounts ─────────────────────────────────────────────
        'security': {
            'otp_validity_minutes':     otp_validity,
            'max_login_attempts':       max_attempts,
            'suspend_attempts':         suspend_at,
            'suspend_duration_minutes': suspend_dur,
            'session_timeout_minutes':  session_tmout,
            'password_expiry_days':     pwd_expiry,
            'password_history_depth':   pwd_history,
            'auto_lockout_enabled':     auto_lockout,
            'note': (
                f"OTP codes expire after {otp_validity} minute(s). "
                f"{'Accounts are locked after ' + str(max_attempts) + ' failed login attempts. ' if auto_lockout else 'Auto-lockout is currently disabled. '}"
                f"Suspension ({suspend_dur}-min cooldown) occurs at {suspend_at} failed attempts. "
                f"After suspension expires, {max_attempts - suspend_at} more attempts remain before permanent lock. "
                f"Sessions expire after {session_tmout} minute(s) of inactivity. "
                f"Password change is prompted every {pwd_expiry} day(s). "
                f"The system remembers the last {pwd_history} password(s) to prevent reuse. "
                f"Locked accounts can only be unlocked by an administrator."
            ),
        },

        # ── Notifications ───────────────────────────────────────────────────
        'notifications': {
            'new_arrival_notify_enabled': notify_enabled,
            'new_arrival_notify_channel': notify_channel,
            'note': (
                f"New book arrival notifications are {'ENABLED' if notify_enabled else 'DISABLED'}. "
                f"When enabled, members are notified via {notify_channel.upper()} when new books are added to the catalog. "
                f"Members can also set up personal alerts from their dashboard."
            ),
        },

        'general_note': (
            'All policies above are live values from the system and may be updated by the administrator at any time. '
            'Always use these exact numbers when answering questions about fines, fees, limits, or security rules.'
        ),
    }



# ----------------------------------------------------------------------
# TOOL: get_user_recommendations  (authenticated users only)
# user_id is bound via closure in gemini.py — not exposed to the model
# ----------------------------------------------------------------------
def get_user_recommendations(user_id, limit=5):
    """
    Return personalised book recommendations derived from the user's
    borrowing history. Falls back to most-popular if history is empty.
    """
    from circulation.models import BorrowingTransaction

    cap = max(1, min(int(limit or 5), 10))

    transactions = (
        BorrowingTransaction.objects
        .filter(user_id=user_id, status__in=['returned', 'borrowed', 'overdue', 'lost'])
        .select_related('copy__book__category')
        .order_by('-borrow_date')[:60]
    )

    if not transactions:
        # No history → popular books
        popular_ids = list(
            BorrowingTransaction.objects
            .values('copy__book')
            .annotate(cnt=Count('id'))
            .order_by('-cnt')
            .values_list('copy__book_id', flat=True)[:cap]
        )
        books = list(Book.objects.filter(id__in=popular_ids).select_related('category'))
        return {
            'personalized': False,
            'message': 'Haujaborrow kitabu chochote bado / You have not borrowed any books yet. '
                       'Here are our most popular titles:',
            'count': len(books),
            'books': [_book_to_dict(b) for b in books],
        }

    # Build preference profile from borrowing history
    category_counts: dict = {}
    author_counts: dict   = {}
    borrowed_ids: set     = set()

    for tx in transactions:
        try:
            book = tx.copy.book
        except Exception:
            continue
        borrowed_ids.add(book.id)
        if book.category_id:
            cn = book.category.name
            category_counts[cn] = category_counts.get(cn, 0) + 1
        if book.author:
            author_counts[book.author] = author_counts.get(book.author, 0) + 1

    top_cats    = sorted(category_counts, key=category_counts.get, reverse=True)[:3]
    top_authors = sorted(author_counts,   key=author_counts.get,   reverse=True)[:2]

    q_obj = Q()
    for cat in top_cats:
        q_obj |= Q(category__name__icontains=cat)
    for auth in top_authors:
        q_obj |= Q(author__icontains=auth)

    base = Book.objects.exclude(id__in=borrowed_ids)
    if q_obj:
        ids = list(base.filter(q_obj).values_list('id', flat=True).distinct()[:cap])
    else:
        ids = list(base.values_list('id', flat=True)[:cap])

    books = list(Book.objects.filter(id__in=ids).select_related('category'))

    return {
        'personalized': True,
        'based_on': {
            'top_categories': top_cats,
            'top_authors':    top_authors,
            'books_borrowed': len(borrowed_ids),
        },
        'count': len(books),
        'books': [_book_to_dict(b) for b in books],
        'message': (
            f"Mapendekezo yanategemea historia yako ya kukopa vitabu / "
            f"Recommendations based on your borrowing history "
            f"({len(borrowed_ids)} book(s) borrowed)."
        ),
    }


# ----------------------------------------------------------------------
# TOOL: get_online_libraries
# ----------------------------------------------------------------------
def get_online_libraries(query=''):
    """
    Return a curated list of free / open-access online libraries with
    direct search links pre-populated with the given query.
    """
    q = quote_plus(query) if query else ''

    def _url(base_search, base_home):
        return base_search.format(q=q) if q else base_home

    libraries = [
        {
            'name':        'Google Books',
            'url':         _url('https://books.google.com/search?q={q}', 'https://books.google.com'),
            'description': 'Search millions of books; preview chapters online. / Tafuta vitabu vingi; angalia sehemu za vitabu mtandaoni.',
            'type':        'General',
            'free':        'Preview (some free)',
            'languages':   'English, Multi-language',
        },
        {
            'name':        'Open Library (Internet Archive)',
            'url':         _url('https://openlibrary.org/search?q={q}', 'https://openlibrary.org'),
            'description': 'Borrow millions of digital books for free. / Kopa vitabu vya kidijitali bure kabisa.',
            'type':        'General Academic',
            'free':        'Free to borrow',
            'languages':   'Multi-language',
        },
        {
            'name':        'Project Gutenberg',
            'url':         _url('https://www.gutenberg.org/ebooks/search/?query={q}', 'https://www.gutenberg.org'),
            'description': 'Over 70,000 free classic eBooks. / Vitabu zaidi ya 70,000 vya bure.',
            'type':        'Classics / Literature',
            'free':        'Completely Free',
            'languages':   'Multi-language',
        },
        {
            'name':        'MIT OpenCourseWare',
            'url':         _url('https://ocw.mit.edu/search/?q={q}', 'https://ocw.mit.edu'),
            'description': 'Free MIT lecture notes, textbooks, course materials — great for ICT/tech. / Vifaa vya masomo ya MIT bure — vizuri kwa TEHAMA.',
            'type':        'Academic / Technology',
            'free':        'Completely Free',
            'languages':   'English',
        },
        {
            'name':        'DOAB – Open Access Books',
            'url':         _url('https://directory.doabooks.org/search?query={q}', 'https://www.doabooks.org'),
            'description': 'Peer-reviewed academic books freely downloadable. / Vitabu vya kitaaluma vinavyoweza kupakuliwa bure.',
            'type':        'Academic',
            'free':        'Completely Free',
            'languages':   'Multi-language',
        },
        {
            'name':        'SpringerOpen / Springer Free',
            'url':         _url('https://link.springer.com/search?query={q}&search-within=Books', 'https://link.springer.com'),
            'description': 'Thousands of free Springer academic books and chapters. / Vitabu elfu vya Springer bure.',
            'type':        'Academic / Science',
            'free':        'Many free chapters & books',
            'languages':   'English, Multi-language',
        },
        {
            'name':        'Bookboon (Textbooks)',
            'url':         _url('https://bookboon.com/en/search#{q}', 'https://bookboon.com/en/textbooks'),
            'description': 'Free university-level textbooks, especially IT/Business. / Vitabu vya chuo bure, hasa TEHAMA/Biashara.',
            'type':        'Textbooks',
            'free':        'Free (registration required)',
            'languages':   'English, Multi-language',
        },
        {
            'name':        'Standard Ebooks',
            'url':         _url('https://standardebooks.org/ebooks?query={q}', 'https://standardebooks.org'),
            'description': 'High-quality, beautifully formatted free public domain eBooks. / Vitabu vya bure vya ubora wa juu.',
            'type':        'Literature / Classics',
            'free':        'Completely Free',
            'languages':   'English',
        },
    ]

    return {
        'count':     len(libraries),
        'query':     query,
        'libraries': libraries,
        'tip': (
            'Click the URL link to open and search directly. '
            'Bonyeza kiungo cha URL kufungua na kutafuta moja kwa moja. '
            'Prefer Open Library and Project Gutenberg for free full-text access.'
        ),
    }
