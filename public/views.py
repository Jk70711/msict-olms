# ============================================================
# public/views.py
# Views za kurasa za umma — zinaonekana bila kuingia kwenye mfumo.
# Hii ni "uso" wa maktaba unaowasiliana na wageni na wanachama.
# ============================================================

from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Q
from django.utils import timezone
from django.http import JsonResponse

from catalog.models import Book, BookCopy, ExternalLibrary, News, Category, Course, MediaSlide


# API ya utambuzi wa haraka wa vitabu (inaitwa kwa AJAX wakati unaandika kwenye kisanduku cha tafuta)
# Inarudisha vitabu 10 vya kwanza vinavyolingana na swali lililotumwa
def catalog_autocomplete_api(request):
    query = request.GET.get('q', '').strip()
    if len(query) < 1:
        return JsonResponse({'results': []})

    # Search books by title / author / isbn
    books_qs = Book.objects.filter(
        Q(title__icontains=query) | Q(author__icontains=query) | Q(isbn__icontains=query)
    ).values('id', 'title', 'author', 'isbn')[:10]

    # Also match by accession number (BookCopy)
    accession_qs = BookCopy.objects.filter(
        accession_no__icontains=query
    ).select_related('book').values('book__id', 'book__title', 'book__author', 'book__isbn', 'accession_no')[:6]

    seen_ids = set()
    results = []

    for b in books_qs:
        seen_ids.add(b['id'])
        results.append({'id': b['id'], 'title': b['title'], 'author': b['author'],
                        'isbn': b['isbn'], 'accession_no': None})

    for m in accession_qs:
        if m['book__id'] not in seen_ids:
            seen_ids.add(m['book__id'])
            results.append({'id': m['book__id'], 'title': m['book__title'],
                            'author': m['book__author'], 'isbn': m['book__isbn'],
                            'accession_no': m['accession_no']})
        else:
            # Attach accession_no to already-found book entry
            for r in results:
                if r['id'] == m['book__id'] and not r['accession_no']:
                    r['accession_no'] = m['accession_no']
                    break

    return JsonResponse({'results': results[:12]})


# Ukurasa wa nyumbani wa maktaba
# Inakusanya: picha za carousel, vitabu vya 3D carousel, matangazo, habari
def home_view(request):
    # Pata picha za carousel zilizo hai (si zilizoisha muda)
    carousel_qs = MediaSlide.objects.filter(
        slide_type='carousel',
        is_active=True
    ).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gte=timezone.now())
    ).order_by('display_order', '-created_at')

    # Pata rangi ya nyuma ya carousel kutoka slide ya kwanza ya carousel
    carousel_bg_color = '#001a33'  # Default
    first_carousel = carousel_qs.first()
    if first_carousel and first_carousel.bg_color:
        carousel_bg_color = first_carousel.bg_color

    carousel_slides = carousel_qs[:6]

    # Kama picha za carousel hazipo, tumia picha za vitabu badala yake
    carousel_books = Book.objects.filter(show_in_carousel=True).select_related('category').prefetch_related('copies')[:8]
    if carousel_books.count() < 3:
        carousel_books = Book.objects.select_related('category').prefetch_related('copies').order_by('-created_at')[:8]

    # Pata matangazo yanayoonekana kwenye ukurasa wa nyumbani
    advertisements = MediaSlide.objects.filter(
        slide_type='advertisement',
        is_active=True
    ).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gte=timezone.now())
    ).order_by('display_order')[:3]

    # Pata mabango ya habari/matangazo
    news_banners = MediaSlide.objects.filter(
        slide_type__in=['news', 'announcement'],
        is_active=True
    ).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gte=timezone.now())
    ).order_by('-created_at')[:3]

    news_items = News.objects.filter(is_active=True).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gte=timezone.now())
    ).order_by('-created_at')[:5]

    # Pata logo ya sasa ya mfumo
    logo = MediaSlide.get_active_logo()

    # Pata picha ya nyuma (watermark) ya ukurasa wa nyumbani
    home_bg = MediaSlide.get_active_home_bg()

    # Vitabu 10 vya hivi karibuni — vinaonekana kwenye carousel ya 3D
    latest_books = Book.objects.select_related('category').prefetch_related('copies').order_by('-created_at')[:10]

    # Jumla ya vitabu vyote kwenye maktaba (inaonyeshwa kwenye takwimu)
    total_books_count = Book.objects.count()

    return render(request, 'public/home.html', {
        'carousel_slides': carousel_slides,
        'carousel_books': carousel_books,
        'latest_books': latest_books,
        'total_books_count': total_books_count,
        'advertisements': advertisements,
        'news_banners': news_banners,
        'news_items': news_items,
        'logo': logo,
        'home_bg': home_bg,
        'carousel_bg_color': carousel_bg_color,
    })


# Ukurasa wa kutafuta vitabu (catalog ya umma)
# Inachuja vitabu kulingana na: maneno ya tafuta, kozi, kategoria
# Matokeo yanagawanywa kurasa 12 kwa kurasa moja
def catalog_search_view(request):
    from django.core.paginator import Paginator
    query = request.GET.get('q', '')  # Maneno ya tafuta
    course_id = request.GET.get('course', '')
    category_id = request.GET.get('category', '')
    copy_type = request.GET.get('copy_type', '')  # 'softcopy' or 'hardcopy'
    has_course = request.GET.get('has_course', '')  # '1' = only books assigned to a course
    federated = request.GET.getlist('federated')

    books = Book.objects.select_related('category').prefetch_related('copies', 'courses')

    if query:
        books = books.filter(
            Q(title__icontains=query) | Q(author__icontains=query)
            | Q(isbn__icontains=query) | Q(copies__accession_no__icontains=query)
        ).distinct()
    if course_id:
        course_book_ids = Book.objects.filter(courses__pk=course_id).values('pk')
        books = books.filter(pk__in=course_book_ids)
    if category_id:
        books = books.filter(category_id=category_id)
    if copy_type:
        book_ids = Book.objects.filter(copies__copy_type=copy_type).values('pk')
        books = books.filter(pk__in=book_ids)
    if has_course == '1':
        # Only books that are assigned to at least one course
        course_book_ids = Book.objects.filter(courses__isnull=False).values('pk').distinct()
        books = books.filter(pk__in=course_book_ids)

    # Paginate results (12 books per page)
    paginator = Paginator(books, 12)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    active_ext_libs = ExternalLibrary.objects.filter(is_active=True)
    fed_urls = []
    for lib_id in federated:
        try:
            lib = active_ext_libs.get(pk=lib_id)
            fed_urls.append({'name': lib.name, 'url': lib.build_search_url(query)})
        except ExternalLibrary.DoesNotExist:
            pass

    courses = Course.objects.all()
    categories = Category.objects.all()

    return render(request, 'public/catalog_search.html', {
        'books': page_obj,
        'page_obj': page_obj,
        'paginator': paginator,
        'query': query,
        'courses': courses,
        'categories': categories,
        'selected_course': course_id,
        'selected_category': category_id,
        'selected_copy_type': copy_type,
        'has_course_filter': has_course,
        'active_ext_libs': active_ext_libs,
        'fed_urls': fed_urls,
        'federated_selected': federated,
    })


# Ukurasa wa maelezo ya kitabu mmoja (kwa umma)
# Inaonyesha: taarifa za kitabu, nakala zilizopo, viungo vya kukopa au kupakua
# Kwa mwanachama aliyeingia: inaonyesha hali ya mkopo wake wa kitabu hiki
def book_detail_public_view(request, book_id):
    from circulation.models import BorrowingTransaction, BorrowRequest
    from django.conf import settings as _settings
    book = get_object_or_404(Book, pk=book_id)  # Tafuta kitabu au onyesha ukurasa wa 404
    copies = book.copies.all()
    free_copies = copies.filter(copy_type='softcopy', access_type='free')
    special_copies = copies.filter(copy_type='softcopy', access_type='borrow')
    available_special = special_copies.filter(status='available')
    hardcopies = copies.filter(copy_type='hardcopy')

    user_active_softcopy_tx = None
    user_pending_softcopy_req = False
    user_can_borrow = True
    borrow_block_reason = ''
    if request.user.is_authenticated:
        user_active_softcopy_tx = BorrowingTransaction.objects.filter(
            user=request.user,
            copy__book=book,
            copy__copy_type='softcopy',
            status__in=['borrowed', 'overdue'],
        ).select_related('copy').first()
        user_pending_softcopy_req = BorrowRequest.objects.filter(
            user=request.user, copy__in=special_copies, status='pending'
        ).exists()
        if request.user.has_overdue():
            user_can_borrow = False
            borrow_block_reason = 'overdue'
        elif request.user.has_unpaid_fines():
            user_can_borrow = False
            borrow_block_reason = 'fines'
        elif request.user.active_borrows_count() >= getattr(_settings, 'MAX_COPIES_PER_BORROW', 3):
            user_can_borrow = False
            borrow_block_reason = 'limit'

    return render(request, 'public/book_detail.html', {
        'book': book,
        'copies': copies,
        'free_copies': free_copies,
        'special_copies': special_copies,
        'available_special': available_special,
        'hardcopies': hardcopies,
        'user_active_softcopy_tx': user_active_softcopy_tx,
        'user_pending_softcopy_req': user_pending_softcopy_req,
        'user_can_borrow': user_can_borrow,
        'borrow_block_reason': borrow_block_reason,
    })


# API ya kupata data ya kitabu kwa modal popup (inaitwa kwa AJAX)
# Inarudisha JSON na taarifa muhimu za kitabu
def book_modal_data_view(request, book_id):
    from django.http import JsonResponse
    book = get_object_or_404(Book, pk=book_id)
    data = {
        'id': book.pk,
        'title': book.title,
        'author': book.author,
        'category': book.category.name if book.category else '',
        'summary': book.summary,
        'cover_image': book.cover_image.url if book.cover_image else '',
        'hardcopy_available': book.available_hardcopy_count(),
        'has_free_softcopy': book.has_free_softcopy(),
        'has_special_softcopy': book.has_special_softcopy(),
        'detail_url': f'/books/{book.pk}/',
    }
    return JsonResponse(data)
