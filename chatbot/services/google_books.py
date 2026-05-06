# ============================================================
# chatbot/services/google_books.py
# Thin Google Books API wrapper used as the "external knowledge" fallback.
# https://developers.google.com/books/docs/v1/using
# ============================================================

import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)
GOOGLE_BOOKS_URL = 'https://www.googleapis.com/books/v1/volumes'


def search_external_books(query, limit=5):
    """
    Search Google Books for `query`.
    Returns: { 'count': N, 'books': [...], 'source': 'google_books' }
    """
    if not query:
        return {'count': 0, 'books': [], 'error': 'Empty query.'}

    params = {'q': query, 'maxResults': max(1, min(int(limit), 10))}
    if settings.GOOGLE_BOOKS_API_KEY:
        params['key'] = settings.GOOGLE_BOOKS_API_KEY

    try:
        r = requests.get(GOOGLE_BOOKS_URL, params=params, timeout=8)
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as e:
        logger.warning('Google Books request failed: %s', e)
        return {'count': 0, 'books': [], 'error': 'Google Books API unreachable.'}

    items = data.get('items') or []
    books = []
    for it in items:
        info = it.get('volumeInfo', {}) or {}
        identifiers = info.get('industryIdentifiers') or []
        isbn = next(
            (x['identifier'] for x in identifiers
             if x.get('type', '').startswith('ISBN')),
            ''
        )
        books.append({
            'title':       info.get('title', '—'),
            'authors':     info.get('authors', []),
            'publisher':   info.get('publisher', ''),
            'year':        (info.get('publishedDate') or '')[:4],
            'isbn':        isbn,
            'description': (info.get('description') or '')[:400],
            'page_count':  info.get('pageCount'),
            'categories':  info.get('categories', []),
            'thumbnail':   (info.get('imageLinks') or {}).get('thumbnail', ''),
            'preview_url': info.get('previewLink', ''),
            'info_url':    info.get('infoLink', ''),
        })

    return {
        'count': len(books),
        'books': books,
        'source': 'google_books',
    }
