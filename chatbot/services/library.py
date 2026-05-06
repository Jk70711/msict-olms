# ============================================================
# chatbot/services/library.py
# Internal-database search functions used as Gemini "tools".
# All functions return plain JSON-serialisable dicts/lists.
# ============================================================

from django.db.models import Q
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
    qs = Book.objects.all().select_related('category')

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

    qs = qs.filter(q_obj).distinct()[:max(1, min(int(limit), 20))]
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
    qs = Book.objects.all().select_related('category')
    
    # Exclude the book that was not found (if provided)
    if exclude_id:
        qs = qs.exclude(pk=int(exclude_id))
    
    q_obj = Q()
    if category:
        q_obj |= Q(category__name__icontains=category)
        q_obj |= Q(category__parent__name__icontains=category)
    if author:
        q_obj |= Q(author__icontains=author)
    if query:
        # Extract keywords from query
        keywords = [k for k in query.split() if len(k) > 3]
        for kw in keywords[:3]:  # Use first 3 meaningful keywords
            q_obj |= Q(title__icontains=kw)
            q_obj |= Q(summary__icontains=kw)
    
    if not q_obj:
        # Fallback: return recent available books
        books = qs.filter(copies__status='available').distinct()[:limit]
    else:
        books = qs.filter(q_obj).distinct()[:limit]
    
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
        'name':              'MSICT Online Library',
        'institution':       'Military School of Information and Communication Technology',
        'loan_period_days':  getattr(settings, 'LOAN_PERIOD_DAYS', 7),
        'max_renewals':      getattr(settings, 'MAX_RENEWALS', 2),
        'max_copies_per_borrow': getattr(settings, 'MAX_COPIES_PER_BORROW', 3),
        'fine_per_day_tzs':  getattr(settings, 'FINE_PER_DAY', 500),
        'note': (
            'To borrow a book, you must be logged in. Click the book title to '
            'view its detail page, then use the Borrow button.'
        ),
    }
