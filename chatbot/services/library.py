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
        'detail_url': reverse('book_detail', args=[book.id]),
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
def list_categories():
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
    """Return general library policies (loan period, fine, etc.) from Django settings."""
    return {
        'name':              'MSICT Library',
        'institution':       'Military School of Information and Communication Technology',
        'loan_period_days':  getattr(settings, 'LOAN_PERIOD_DAYS', 7),
        'max_renewals':      getattr(settings, 'MAX_RENEWALS', 2),
        'max_copies_per_borrow': getattr(settings, 'MAX_COPIES_PER_BORROW', 3),
        'fine_per_day_tzs':  getattr(settings, 'FINE_PER_DAY', 1000),
        'note': (
            'To borrow a book, you must be logged in. Click the book title to '
            'view its detail page, then use the Borrow button.'
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
