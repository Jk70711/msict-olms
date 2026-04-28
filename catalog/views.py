from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse, FileResponse, JsonResponse
from django.db.models import Q
from django.conf import settings
from django.views.decorators.http import require_POST

from accounts.views import librarian_required
from accounts.utils import log_audit
from .models import Category, Course, Book, BookCopy, ExternalLibrary, News, InventoryLog, MediaSlide, Shelf


@login_required
@librarian_required
def librarian_dashboard_view(request):
    from circulation.models import BorrowRequest, BorrowingTransaction, Reservation
    from accounts.models import OLMSUser

    pending_requests = BorrowRequest.objects.filter(status='pending').select_related('user', 'copy__book').order_by('-request_date')
    overdue_transactions = BorrowingTransaction.objects.filter(status='overdue').select_related('user', 'copy__book')
    total_books = Book.objects.count()
    total_copies = BookCopy.objects.count()
    available_copies = BookCopy.objects.filter(status='available').count()
    total_members = OLMSUser.objects.filter(role='member').count()

    context = {
        'pending_requests': pending_requests[:10],
        'overdue_transactions': overdue_transactions[:10],
        'total_books': total_books,
        'total_copies': total_copies,
        'available_copies': available_copies,
        'total_members': total_members,
        'pending_count': pending_requests.count(),
        'overdue_count': overdue_transactions.count(),
    }
    return render(request, 'catalog/librarian_dashboard.html', context)


@login_required
def book_list_view(request):
    query = request.GET.get('q', '')
    category_id = request.GET.get('category', '')
    books = Book.objects.select_related('category').prefetch_related('copies', 'courses')
    if query:
        books = books.filter(
            Q(title__icontains=query) | Q(author__icontains=query) | Q(isbn__icontains=query)
        )
    if category_id:
        books = books.filter(category_id=category_id)
    categories = Category.objects.all()
    can_manage = request.user.role in ('librarian', 'admin')
    return render(request, 'catalog/book_list.html', {
        'books': books,
        'query': query,
        'categories': categories,
        'selected_category': category_id,
        'can_manage': can_manage,
    })


@login_required
@librarian_required
def book_create_view(request):
    categories = Category.objects.all()
    courses = Course.objects.all()
    if request.method == 'POST':
        book = Book(
            title=request.POST.get('title', ''),
            author=request.POST.get('author', ''),
            publisher=request.POST.get('publisher', ''),
            year=request.POST.get('year') or None,
            isbn=request.POST.get('isbn') or None,
            summary=request.POST.get('summary', ''),
            show_in_carousel=True,
        )
        cat_id = request.POST.get('category')
        if cat_id:
            book.category_id = cat_id
        if 'cover_image' in request.FILES:
            book.cover_image = request.FILES['cover_image']
        book.save()

        course_ids = request.POST.getlist('courses')
        if course_ids:
            from .models import BookCourse
            for cid in course_ids:
                BookCourse.objects.get_or_create(book=book, course_id=cid)

        book_type = request.POST.get('book_type', 'hardcopy')
        created_summary = []

        # Guard: only 1 softcopy allowed per book
        if book_type in ('softcopy', 'both') and book.copies.filter(copy_type='softcopy').exists():
            messages.error(
                request,
                f'"{book.title}" already has a softcopy. Only 1 softcopy is allowed per book. '
                'Edit the existing softcopy copy instead.'
            )
            return redirect('book_detail', book_id=book.pk)

        # ── Hardcopy creation ──────────────────────────────────────
        if book_type in ('hardcopy', 'both'):
            num_copies = int(request.POST.get('number_of_copies') or 0)
            shelf_loc = request.POST.get('shelf_location', '')
            if num_copies > 0:
                for i in range(num_copies):
                    accession_no = BookCopy.get_next_accession_number()
                    BookCopy.objects.create(
                        book=book,
                        copy_type='hardcopy',
                        accession_no=accession_no,
                        status='available',
                        shelf_location=shelf_loc,
                    )
                log_audit(request.user, f"Created {num_copies} hardcopies for '{book.title}'", request)
                created_summary.append(f"{num_copies} hardcopy{'s' if num_copies > 1 else ''}")

        # ── Softcopy creation ──────────────────────────────────────
        if book_type in ('softcopy', 'both'):
            if book_type == 'both':
                access_type = 'borrow'
            else:
                access_type = request.POST.get('access_type') or request.POST.get('access_type_forced') or 'free'
            softcopy = BookCopy(
                book=book,
                copy_type='softcopy',
                access_type=access_type,
                accession_no=BookCopy.get_next_accession_number(),
                status='available',
            )
            if 'softcopy_file' in request.FILES:
                softcopy.file_path = request.FILES['softcopy_file']
            softcopy.save()
            InventoryLog.objects.create(copy=softcopy, action='added', performed_by=request.user)
            log_audit(request.user, f"Created softcopy ({access_type}) for '{book.title}'", request)
            created_summary.append(f"1 softcopy ({access_type})")

        if created_summary:
            messages.success(request, f"Book '{book.title}' created with {', '.join(created_summary)}.")
        else:
            messages.success(request, f"Book '{book.title}' created successfully.")

        log_audit(request.user, f"Created book '{book.title}'", request)
        return redirect('book_detail', book_id=book.pk)
    return render(request, 'catalog/book_form.html', {'categories': categories, 'courses': courses})


@login_required
@librarian_required
@require_POST
def book_delete_view(request, book_id):
    book = get_object_or_404(Book, pk=book_id)
    title = book.title
    book.delete()
    log_audit(request.user, f"Librarian deleted book '{title}'", request)
    messages.success(request, f"Book '{title}' was deleted successfully.")
    return redirect('book_list')


@login_required
@librarian_required
def book_edit_view(request, book_id):
    book = get_object_or_404(Book, pk=book_id)
    categories = Category.objects.all()
    courses = Course.objects.all()
    if request.method == 'POST':
        book.title = request.POST.get('title', book.title)
        book.author = request.POST.get('author', book.author)
        book.publisher = request.POST.get('publisher', book.publisher)
        book.year = request.POST.get('year') or book.year
        book.isbn = request.POST.get('isbn') or book.isbn
        book.summary = request.POST.get('summary', book.summary)
        book.show_in_carousel = request.POST.get('show_in_carousel') == 'on'
        cat_id = request.POST.get('category')
        if cat_id:
            book.category_id = cat_id
        if 'cover_image' in request.FILES:
            book.cover_image = request.FILES['cover_image']
        book.save()

        from .models import BookCourse
        BookCourse.objects.filter(book=book).delete()
        course_ids = request.POST.getlist('courses')
        for cid in course_ids:
            BookCourse.objects.get_or_create(book=book, course_id=cid)

        log_audit(request.user, f"Edited book '{book.title}'", request)
        messages.success(request, 'Book updated successfully.')
        return redirect('book_detail', book_id=book.pk)
    return render(request, 'catalog/book_form.html', {
        'book': book, 'categories': categories, 'courses': courses,
        'selected_courses': list(book.courses.values_list('pk', flat=True)),
    })


def book_detail_view(request, book_id):
    book = get_object_or_404(Book, pk=book_id)
    copies = book.copies.all()
    reservations = book.reservations.filter(status='pending').order_by('position')
    user_reservation = None
    if request.user.is_authenticated:
        user_reservation = reservations.filter(user=request.user).first()
    has_softcopy = copies.filter(copy_type='softcopy').exists()
    return render(request, 'catalog/book_detail.html', {
        'book': book,
        'copies': copies,
        'reservations': reservations,
        'user_reservation': user_reservation,
        'has_softcopy': has_softcopy,
    })


@login_required
@librarian_required
def copy_create_view(request, book_id):
    book = get_object_or_404(Book, pk=book_id)
    if request.method == 'POST':
        copy_type = request.POST.get('copy_type', 'hardcopy')
        access_type = request.POST.get('access_type') or None
        accession_no = request.POST.get('accession_no', '').strip()
        shelf_location = request.POST.get('shelf_location', '')
        barcode = request.POST.get('barcode', accession_no)

        if copy_type == 'softcopy' and book.copies.filter(copy_type='softcopy').exists():
            messages.error(request, f'"{book.title}" already has a softcopy. Only 1 softcopy per book is allowed.')
            return redirect('book_detail', book_id=book_id)

        if not accession_no:
            accession_no = BookCopy.get_next_accession_number()

        copy = BookCopy(
            book=book, copy_type=copy_type, access_type=access_type,
            accession_no=accession_no, shelf_location=shelf_location, barcode=barcode or accession_no,
        )
        if copy_type == 'softcopy' and 'file_path' in request.FILES:
            copy.file_path = request.FILES['file_path']
        copy.save()

        InventoryLog.objects.create(copy=copy, action='added', performed_by=request.user)
        log_audit(request.user, f"Added copy '{accession_no}' for book '{book.title}'", request)
        messages.success(request, 'Copy added successfully.')
    return redirect('book_detail', book_id=book_id)


@login_required
@librarian_required
def copy_add_standalone_view(request):
    """Standalone Add Copy form — lets the librarian pick the book from a dropdown."""
    books = Book.objects.select_related('category').order_by('title')
    categories = Category.objects.all()

    if request.method == 'POST':
        book_id = request.POST.get('book_id')
        book = get_object_or_404(Book, pk=book_id)
        copy_type = request.POST.get('copy_type', 'hardcopy')
        access_type = request.POST.get('access_type') or None
        accession_no = request.POST.get('accession_no', '').strip()
        shelf_location = request.POST.get('shelf_location', '')
        barcode = request.POST.get('barcode', '').strip()

        if copy_type == 'softcopy' and book.copies.filter(copy_type='softcopy').exists():
            messages.error(request, f'"{book.title}" already has a softcopy. Only 1 softcopy per book is allowed.')
            return render(request, 'catalog/copy_add_form.html', {
                'books': Book.objects.select_related('category').order_by('title'),
                'categories': Category.objects.all(),
                'error_book': book,
            })

        if not accession_no:
            accession_no = BookCopy.get_next_accession_number()

        copy = BookCopy(
            book=book,
            copy_type=copy_type,
            access_type=access_type if copy_type == 'softcopy' else None,
            accession_no=accession_no,
            shelf_location=shelf_location,
            barcode=barcode or accession_no,
        )
        if copy_type == 'softcopy' and 'file_path' in request.FILES:
            copy.file_path = request.FILES['file_path']
        copy.save()

        InventoryLog.objects.create(copy=copy, action='added', performed_by=request.user)
        log_audit(request.user, f"Added copy '{accession_no}' for book '{book.title}'", request)
        messages.success(request, f"Copy '{accession_no}' added for \"{book.title}\".")
        return redirect('book_detail', book_id=book.pk)

    books_with_softcopy = set(
        BookCopy.objects.filter(copy_type='softcopy').values_list('book_id', flat=True)
    )
    return render(request, 'catalog/copy_add_form.html', {
        'books': books,
        'categories': categories,
        'books_with_softcopy': list(books_with_softcopy),
    })


@login_required
@librarian_required
def copy_mark_lost_view(request, copy_id):
    copy = get_object_or_404(BookCopy, pk=copy_id)
    copy.status = 'lost'
    copy.save(update_fields=['status'])
    InventoryLog.objects.create(copy=copy, action='marked_lost', performed_by=request.user)
    log_audit(request.user, f"Marked copy '{copy.accession_no}' as lost", request)
    messages.warning(request, f"Copy {copy.accession_no} marked as lost.")
    return redirect('book_detail', book_id=copy.book_id)


@login_required
@librarian_required
def course_list_view(request):
    courses = Course.objects.all()
    return render(request, 'catalog/course_list.html', {'courses': courses})


@login_required
@librarian_required
def course_create_view(request):
    categories = Category.objects.all()
    if request.method == 'POST':
        name = request.POST.get('course_name', '').strip()
        duration = request.POST.get('duration', '').strip()
        category_id = request.POST.get('category') or None
        if name:
            Course.objects.create(course_name=name, duration=duration, category_id=category_id)
            messages.success(request, f"Course '{name}' created.")
            return redirect('course_list')
        messages.error(request, 'Course name is required.')
    return render(request, 'catalog/course_form.html', {'categories': categories})


@login_required
@librarian_required
def course_edit_view(request, course_id):
    course = get_object_or_404(Course, pk=course_id)
    categories = Category.objects.all()
    if request.method == 'POST':
        course.course_name = request.POST.get('course_name', course.course_name)
        course.duration = request.POST.get('duration', course.duration)
        course.category_id = request.POST.get('category') or None
        course.save()
        messages.success(request, 'Course updated.')
        return redirect('course_list')
    return render(request, 'catalog/course_form.html', {'course': course, 'categories': categories})


@login_required
@librarian_required
def external_library_list_view(request):
    libs = ExternalLibrary.objects.all()
    return render(request, 'catalog/external_library_list.html', {'libs': libs})


@login_required
@librarian_required
def external_library_create_view(request):
    if request.method == 'POST':
        ExternalLibrary.objects.create(
            name=request.POST.get('name', ''),
            base_url=request.POST.get('base_url', ''),
            search_param=request.POST.get('search_param', 'q'),
            lib_type=request.POST.get('lib_type', 'opac'),
            is_active=request.POST.get('is_active') == 'on',
        )
        messages.success(request, 'External library added.')
        return redirect('external_library_list')
    return render(request, 'catalog/external_library_form.html')


@login_required
@librarian_required
def carousel_manage_view(request):
    if request.method == 'POST':
        carousel_ids = set(map(int, request.POST.getlist('carousel_books')))
        Book.objects.filter(show_in_carousel=True).update(show_in_carousel=False)
        Book.objects.filter(pk__in=carousel_ids).update(show_in_carousel=True)
        log_audit(request.user, f"Carousel updated with book IDs: {carousel_ids}", request)
        messages.success(request, 'Carousel updated.')
        return redirect('carousel_manage')
    books = Book.objects.select_related('category').order_by('-created_at')
    return render(request, 'catalog/carousel_manage.html', {'books': books})


@login_required
def serve_softcopy_view(request, copy_id):
    copy = get_object_or_404(BookCopy, pk=copy_id, copy_type='softcopy')

    if copy.access_type == 'free':
        if not copy.file_path:
            messages.error(request, 'File not available.')
            return redirect('book_detail', book_id=copy.book_id)
        response = FileResponse(copy.file_path.open('rb'), content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="{copy.book.title}.pdf"'
        return response

    if copy.access_type == 'borrow':
        from circulation.models import BorrowingTransaction
        from django.utils import timezone as tz
        now = tz.now()
        # Only an active, non-expired borrow grants access
        tx = BorrowingTransaction.objects.filter(
            user=request.user, copy=copy
        ).order_by('-borrow_date').first()
        if not tx or tx.status == 'returned':
            messages.error(
                request,
                f'Access denied — you do not have an active borrowing for '
                f'"{copy.book.title}". Please submit a borrow request first.'
            )
            return redirect('book_detail_public', book_id=copy.book_id)
        if now > tx.due_date:
            messages.warning(
                request,
                f'Your access to "{copy.book.title}" expired on '
                f'{tx.due_date.strftime("%d %b %Y")}. '
                f'Renew your borrowing to restore access.'
            )
            return redirect('member_msict_borrowings')
        if not copy.file_path:
            messages.error(request, 'File not available. Contact the librarian.')
            return redirect('member_msict_borrowings')
        response = FileResponse(copy.file_path.open('rb'), content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="{copy.book.title}.pdf"'
        response['X-Frame-Options'] = 'SAMEORIGIN'
        response['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
        response['Pragma'] = 'no-cache'
        return response

    messages.error(request, 'Unauthorized access.')
    return redirect('home')


@login_required
def free_softcopy_download_view(request, copy_id):
    copy = get_object_or_404(BookCopy, pk=copy_id, copy_type='softcopy', access_type='free')
    if not copy.file_path:
        messages.error(request, 'File not available for this copy.')
        return redirect('book_detail_public', book_id=copy.book_id)
    response = FileResponse(copy.file_path.open('rb'), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{copy.book.title}.pdf"'
    return response


@login_required
@librarian_required
@require_POST
def course_delete_view(request, course_id):
    course = get_object_or_404(Course, pk=course_id)
    name = course.course_name
    course.delete()
    log_audit(request.user, f"Deleted course '{name}'", request)
    messages.success(request, f"Course '{name}' deleted.")
    return redirect('course_list')


@login_required
@librarian_required
def copy_list_view(request):
    query = request.GET.get('q', '')
    status = request.GET.get('status', '')
    book_id = request.GET.get('book', '')
    copy_type = request.GET.get('copy_type', '')
    copies = BookCopy.objects.select_related('book').order_by('-accession_no')
    if query:
        copies = copies.filter(
            Q(accession_no__icontains=query) | Q(book__title__icontains=query) |
            Q(book__isbn__icontains=query) | Q(shelf_location__icontains=query)
        )
    if status:
        copies = copies.filter(status=status)
    if book_id:
        copies = copies.filter(book_id=book_id)
    if copy_type:
        copies = copies.filter(copy_type=copy_type)
    books = Book.objects.all().order_by('title')
    return render(request, 'catalog/copy_list.html', {
        'copies': copies, 'query': query, 'status': status,
        'selected_book': book_id, 'books': books, 'copy_type': copy_type,
    })


@login_required
@librarian_required
def copy_edit_view(request, copy_id):
    copy = get_object_or_404(BookCopy, pk=copy_id)
    if request.method == 'POST':
        copy.accession_no = request.POST.get('accession_no', copy.accession_no)
        copy.shelf_location = request.POST.get('shelf_location', copy.shelf_location)
        copy.barcode = request.POST.get('barcode', copy.barcode)
        new_status = request.POST.get('status')
        if new_status:
            copy.status = new_status
        copy.save()
        InventoryLog.objects.create(copy=copy, action='updated', performed_by=request.user)
        log_audit(request.user, f"Updated copy '{copy.accession_no}'", request)
        messages.success(request, f"Copy '{copy.accession_no}' updated.")
        return redirect('copy_list')
    return render(request, 'catalog/copy_form.html', {'copy': copy})


@login_required
@librarian_required
@require_POST
def copy_delete_view(request, copy_id):
    copy = get_object_or_404(BookCopy, pk=copy_id)
    accession_no = copy.accession_no
    book_id = copy.book_id
    copy.delete()
    log_audit(request.user, f"Deleted copy '{accession_no}'", request)
    messages.success(request, f"Copy '{accession_no}' deleted.")
    return redirect('copy_list')


@login_required
@librarian_required
def category_list_view(request):
    categories = Category.objects.all()
    return render(request, 'catalog/category_list.html', {'categories': categories})


@login_required
@librarian_required
def shelf_location_view(request):
    from django.db.models import Count, Q, Case, When, IntegerField
    from circulation.models import BorrowingTransaction

    # Get all categories (treating each as a shelf)
    categories = Category.objects.annotate(
        total_books=Count('books', distinct=True),
        total_copies=Count('books__copies'),
        available=Count('books__copies', filter=Q(books__copies__status='available')),
        borrowed=Count('books__copies', filter=Q(books__copies__status='borrowed')),
        reserved=Count('books__copies', filter=Q(books__copies__status='reserved')),
        lost=Count('books__copies', filter=Q(books__copies__status='lost')),
    ).order_by('name')

    # Calculate borrow counts per category (for most borrowed shelf)
    borrow_stats = []
    total_borrows_all = 0
    for cat in categories:
        borrow_count = BorrowingTransaction.objects.filter(
            copy__book__category=cat
        ).count()
        total_borrows_all += borrow_count
        borrow_stats.append({
            'category': cat,
            'borrow_count': borrow_count,
        })

    # Sort by borrow count descending for most borrowed
    borrow_stats_sorted = sorted(borrow_stats, key=lambda x: x['borrow_count'], reverse=True)
    most_borrowed = borrow_stats_sorted[:5] if borrow_stats_sorted else []

    # Calculate totals
    totals = {
        'total_books': sum(c.total_books for c in categories),
        'total_copies': sum(c.total_copies for c in categories),
        'total_available': sum(c.available for c in categories),
        'total_borrowed': sum(c.borrowed for c in categories),
        'total_reserved': sum(c.reserved for c in categories),
        'total_lost': sum(c.lost for c in categories),
        'total_borrows': total_borrows_all,
    }

    return render(request, 'catalog/shelf_location.html', {
        'shelves': categories,
        'borrow_stats': borrow_stats,
        'most_borrowed': most_borrowed,
        'totals': totals,
    })


@login_required
@librarian_required
def shelf_detail_view(request, shelf_id):
    shelf = get_object_or_404(Category, pk=shelf_id)

    # Get books in this shelf (without annotate to avoid NCLOB GROUP BY issue)
    from django.db.models import Count, Q, OuterRef, Subquery
    books = Book.objects.filter(category=shelf).order_by('title')

    # Calculate copy counts in Python to avoid NCLOB issues with GROUP BY
    books_with_counts = []
    for book in books:
        copies = book.copies.all()
        books_with_counts.append({
            'book': book,
            'total_copies': copies.count(),
            'available_copies': copies.filter(status='available').count(),
            'borrowed_copies': copies.filter(status='borrowed').count(),
            'reserved_copies': copies.filter(status='reserved').count(),
            'lost_copies': copies.filter(status='lost').count(),
        })

    # Get subcategories under this shelf (without distinct to avoid NCLOB issues)
    subcategories = Category.objects.filter(parent=shelf)
    subcategories_with_count = []
    for sub in subcategories:
        subcategories_with_count.append({
            'category': sub,
            'book_count': Book.objects.filter(category=sub).count(),
        })

    # Get courses linked to this shelf (without distinct to avoid NCLOB issues)
    courses = Course.objects.filter(category=shelf)
    courses_with_count = []
    for course in courses:
        courses_with_count.append({
            'course': course,
            'book_count': Book.objects.filter(courses=course).count(),
        })

    # Shelf statistics
    shelf_stats = {
        'total_books': len(books_with_counts),
        'total_copies': sum(b['total_copies'] for b in books_with_counts),
        'total_available': sum(b['available_copies'] for b in books_with_counts),
        'total_borrowed': sum(b['borrowed_copies'] for b in books_with_counts),
        'total_reserved': sum(b['reserved_copies'] for b in books_with_counts),
        'total_lost': sum(b['lost_copies'] for b in books_with_counts),
    }

    return render(request, 'catalog/shelf_detail.html', {
        'shelf': shelf,
        'books': books_with_counts,
        'subcategories': subcategories_with_count,
        'courses': courses_with_count,
        'stats': shelf_stats,
    })


@login_required
@librarian_required
def category_create_view(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        parent_id = request.POST.get('parent') or None
        if name:
            Category.objects.create(name=name, parent_id=parent_id)
            messages.success(request, f"Category '{name}' created.")
            return redirect('category_list')
    categories = Category.objects.all()
    return render(request, 'catalog/category_form.html', {'categories': categories})


@login_required
@librarian_required
def next_accession_api(request):
    """AJAX: return the next auto-generated accession number."""
    offset = int(request.GET.get('offset', 0))
    accession_no = BookCopy.get_next_accession_number(offset=offset)
    return JsonResponse({'accession_no': accession_no})


# ─── Shelf CRUD + API ────────────────────────────────────────────────────────

@login_required
@librarian_required
def shelf_list_all_view(request):
    """List all shelves across all categories"""
    categories = Category.objects.prefetch_related('shelves').order_by('shelf_prefix')
    return render(request, 'catalog/shelf_list.html', {'categories': categories})


@login_required
@librarian_required
def shelf_create_view(request):
    if request.method == 'POST':
        category_id = request.POST.get('category')
        shelf_number = request.POST.get('shelf_number', '').strip()
        name = request.POST.get('name', '').strip()
        capacity = request.POST.get('capacity', 50)
        notes = request.POST.get('notes', '').strip()
        cat = get_object_or_404(Category, pk=category_id)
        if not shelf_number:
            last = Shelf.objects.filter(category=cat).order_by('-shelf_number').first()
            shelf_number = (last.shelf_number + 1) if last else 1
        if Shelf.objects.filter(category=cat, shelf_number=shelf_number).exists():
            messages.error(request, f'{cat.shelf_code if hasattr(cat, "shelf_code") else cat.shelf_prefix}{shelf_number} already exists.')
        else:
            shelf = Shelf.objects.create(category=cat, shelf_number=int(shelf_number), name=name, capacity=int(capacity), notes=notes)
            log_audit(request.user, f"Created shelf {shelf.shelf_code}", request)
            messages.success(request, f'Shelf {shelf.shelf_code} created.')
        return redirect('shelf_list_all')
    categories = Category.objects.order_by('shelf_prefix')
    return render(request, 'catalog/shelf_form.html', {'categories': categories})


@login_required
@librarian_required
def shelf_edit_view(request, shelf_id):
    shelf = get_object_or_404(Shelf, pk=shelf_id)
    if request.method == 'POST':
        shelf.name = request.POST.get('name', '').strip()
        shelf.capacity = int(request.POST.get('capacity', 50))
        shelf.notes = request.POST.get('notes', '').strip()
        shelf.save()
        log_audit(request.user, f"Updated shelf {shelf.shelf_code}", request)
        messages.success(request, f'Shelf {shelf.shelf_code} updated.')
        return redirect('shelf_list_all')
    categories = Category.objects.order_by('shelf_prefix')
    return render(request, 'catalog/shelf_form.html', {'shelf': shelf, 'categories': categories})


@login_required
@librarian_required
@require_POST
def shelf_delete_view(request, shelf_id):
    shelf = get_object_or_404(Shelf, pk=shelf_id)
    code = shelf.shelf_code
    shelf.delete()
    log_audit(request.user, f"Deleted shelf {code}", request)
    messages.warning(request, f'Shelf {code} deleted.')
    return redirect('shelf_list_all')


@login_required
def shelves_by_category_api(request, category_id):
    """AJAX: return shelves JSON for a given category"""
    try:
        cat = Category.objects.get(pk=category_id)
    except Category.DoesNotExist:
        return JsonResponse({'shelves': [], 'prefix': '', 'category': ''})
    shelves = Shelf.objects.filter(category_id=category_id).order_by('shelf_number')
    data = [
        {
            'id': s.pk,
            'code': s.shelf_code,
            'name': s.name,
            'capacity': s.capacity,
            'book_count': s.book_count(),
            'notes': s.notes,
        }
        for s in shelves
    ]
    return JsonResponse({
        'shelves': data,
        'prefix': cat.shelf_prefix,
        'category': cat.name,
    })


def federated_proxy_view(request):
    """Public AJAX proxy: fetch one external library and return normalised JSON results."""
    import requests as _req

    lib_id = request.GET.get('lib_id', '').strip()
    query  = request.GET.get('q', '').strip()

    if not lib_id or not query:
        return JsonResponse({'status': 'error', 'error': 'lib_id and q required',
                             'results': [], 'total': 0})
    try:
        lib = ExternalLibrary.objects.get(pk=lib_id, is_active=True)
    except ExternalLibrary.DoesNotExist:
        return JsonResponse({'status': 'error', 'error': 'Library not found',
                             'results': [], 'total': 0})

    search_url = lib.build_search_url(query)

    try:
        resp = _req.get(
            search_url, timeout=8,
            headers={'User-Agent': 'MSICT-OLMS/1.0 (FederatedSearch)',
                     'Accept': 'application/json, */*'},
        )
        resp.raise_for_status()
    except _req.exceptions.Timeout:
        return JsonResponse({'status': 'timeout', 'lib_name': lib.name,
                             'search_url': search_url, 'results': [], 'total': 0})
    except _req.exceptions.RequestException as exc:
        return JsonResponse({'status': 'error', 'lib_name': lib.name,
                             'error': str(exc), 'search_url': search_url,
                             'results': [], 'total': 0})

    results = []
    total   = 0

    def _text(*keys, src):
        for k in keys:
            v = src.get(k)
            if v:
                return ', '.join(v) if isinstance(v, list) else str(v)
        return '—'

    if lib.lib_type == 'api':
        try:
            data = resp.json()
            if isinstance(data, dict):
                # Google Books
                if 'items' in data:
                    total = data.get('totalItems', 0)
                    for item in data['items'][:12]:
                        vi = item.get('volumeInfo', item)
                        results.append({
                            'title':  _text('title', src=vi),
                            'author': _text('authors', 'author', src=vi),
                            'year':   str(vi.get('publishedDate', ''))[:4],
                            'isbn':   (_text('industryIdentifiers', src=vi) if False else ''),
                            'url':    vi.get('infoLink') or search_url,
                        })
                # Open Library
                elif 'docs' in data:
                    total = data.get('numFound', len(data['docs']))
                    for doc in data['docs'][:12]:
                        results.append({
                            'title':  _text('title', src=doc),
                            'author': _text('author_name', 'author', src=doc),
                            'year':   str(doc.get('first_publish_year', '')),
                            'isbn':   (_text('isbn', src=doc) if doc.get('isbn') else ''),
                            'url':    f"https://openlibrary.org{doc['key']}" if doc.get('key') else search_url,
                        })
                # Generic: look for common result-list keys
                else:
                    items = (data.get('results') or data.get('data') or
                             data.get('books') or [])
                    total = data.get('total') or data.get('count') or len(items)
                    for item in items[:12]:
                        results.append({
                            'title':  _text('title', 'Title', src=item),
                            'author': _text('author', 'Author', 'creator', src=item),
                            'year':   str(item.get('year') or item.get('publishedYear') or ''),
                            'isbn':   str(item.get('isbn') or item.get('ISBN') or ''),
                            'url':    item.get('url') or item.get('link') or search_url,
                        })
            elif isinstance(data, list):
                total = len(data)
                for item in data[:12]:
                    results.append({
                        'title':  _text('title', 'Title', src=item),
                        'author': _text('author', 'Author', src=item),
                        'year':   str(item.get('year') or ''),
                        'isbn':   str(item.get('isbn') or ''),
                        'url':    item.get('url') or search_url,
                    })
        except ValueError:
            pass

    return JsonResponse({
        'status':     'ok',
        'lib_name':   lib.name,
        'lib_type':   lib.lib_type,
        'search_url': search_url,
        'total':      total,
        'results':    results,
    })


# Media Slide Management Views (CRUD for Librarians)
@login_required
@librarian_required
def media_slide_list_view(request):
    """List all media slides for librarian management"""
    slides = MediaSlide.objects.all().order_by('display_order', '-created_at')
    return render(request, 'catalog/media_slide_list.html', {'slides': slides})


@login_required
@librarian_required
def media_slide_create_view(request):
    """Create new media slide (carousel, advertisement, news)"""
    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        description = request.POST.get('description', '').strip()
        slide_type = request.POST.get('slide_type', 'carousel')
        bg_color = request.POST.get('bg_color', '#001a33').strip()
        link_url = request.POST.get('link_url', '').strip()
        display_order = request.POST.get('display_order', 0)
        is_active = request.POST.get('is_active') == 'on'
        expires_at = request.POST.get('expires_at') or None
        image = request.FILES.get('image')

        if title and image:
            slide = MediaSlide.objects.create(
                title=title,
                description=description,
                slide_type=slide_type,
                bg_color=bg_color,
                image=image,
                link_url=link_url,
                display_order=display_order,
                is_active=is_active,
                expires_at=expires_at,
                created_by=request.user
            )
            log_audit(request.user, f"Created {slide_type} slide: '{title}'", request)
            messages.success(request, f"'{title}' created successfully.")
            return redirect('media_slide_list')
        else:
            messages.error(request, "Title and image are required.")

    return render(request, 'catalog/media_slide_form.html')


@login_required
@librarian_required
def media_slide_edit_view(request, slide_id):
    """Edit existing media slide"""
    slide = get_object_or_404(MediaSlide, pk=slide_id)
    if request.method == 'POST':
        slide.title = request.POST.get('title', '').strip()
        slide.description = request.POST.get('description', '').strip()
        slide.slide_type = request.POST.get('slide_type', slide.slide_type)
        slide.bg_color = request.POST.get('bg_color', '#001a33').strip()
        slide.link_url = request.POST.get('link_url', '').strip()
        slide.display_order = request.POST.get('display_order', 0)
        slide.is_active = request.POST.get('is_active') == 'on'
        slide.expires_at = request.POST.get('expires_at') or None

        if request.FILES.get('image'):
            slide.image = request.FILES.get('image')

        slide.save()
        log_audit(request.user, f"Updated slide: '{slide.title}'", request)
        messages.success(request, f"'{slide.title}' updated successfully.")
        return redirect('media_slide_list')

    return render(request, 'catalog/media_slide_form.html', {'slide': slide})


@login_required
@librarian_required
def media_slide_delete_view(request, slide_id):
    """Delete media slide"""
    slide = get_object_or_404(MediaSlide, pk=slide_id)
    if request.method == 'POST':
        title = slide.title
        slide.delete()
        log_audit(request.user, f"Deleted slide: '{title}'", request)
        messages.success(request, f"'{title}' deleted successfully.")
        return redirect('media_slide_list')
    return render(request, 'catalog/media_slide_confirm_delete.html', {'slide': slide})


# ─────────────────────────────────────────────────────────────────────────────
# News Management
# ─────────────────────────────────────────────────────────────────────────────

@login_required
@librarian_required
def news_list_view(request):
    type_filter = request.GET.get('type', '')
    status_filter = request.GET.get('status', 'active')
    query = request.GET.get('q', '')

    news = News.objects.select_related('posted_by').all()

    if type_filter:
        news = news.filter(news_type=type_filter)
    if status_filter == 'active':
        news = news.filter(is_active=True)
    elif status_filter == 'inactive':
        news = news.filter(is_active=False)
    if query:
        news = news.filter(Q(title__icontains=query) | Q(content__icontains=query))

    counts = {
        'all':      News.objects.count(),
        'active':   News.objects.filter(is_active=True).count(),
        'featured': News.objects.filter(is_featured=True, is_active=True).count(),
        'news':     News.objects.filter(news_type='news').count(),
        'announcement': News.objects.filter(news_type='announcement').count(),
        'event':    News.objects.filter(news_type='event').count(),
        'advertisement': News.objects.filter(news_type='advertisement').count(),
    }

    return render(request, 'catalog/news_list.html', {
        'news': news,
        'type_filter': type_filter,
        'status_filter': status_filter,
        'query': query,
        'counts': counts,
        'type_choices': News.TYPE_CHOICES,
    })


@login_required
@librarian_required
def news_create_view(request):
    if request.method == 'POST':
        title       = request.POST.get('title', '').strip()
        content     = request.POST.get('content', '').strip()
        news_type   = request.POST.get('news_type', 'news')
        video_url   = request.POST.get('video_url', '').strip()
        link_url    = request.POST.get('link_url', '').strip()
        is_active   = request.POST.get('is_active') == 'on'
        is_featured = request.POST.get('is_featured') == 'on'
        expires_at  = request.POST.get('expires_at') or None

        if not title:
            messages.error(request, 'Title is required.')
            return render(request, 'catalog/news_form.html', {'type_choices': News.TYPE_CHOICES})

        news = News(
            title=title, content=content, news_type=news_type,
            video_url=video_url, link_url=link_url,
            is_active=is_active, is_featured=is_featured,
            posted_by=request.user,
        )
        if expires_at:
            from django.utils.dateparse import parse_datetime
            news.expires_at = parse_datetime(expires_at + ':00') if len(expires_at) == 16 else parse_datetime(expires_at)

        if 'image' in request.FILES:
            news.image = request.FILES['image']
        if 'attachment' in request.FILES:
            news.attachment = request.FILES['attachment']

        news.save()
        log_audit(request.user, f"Created news post: '{news.title}'", request)
        messages.success(request, f"'{news.title}' published successfully.")
        return redirect('news_list')

    return render(request, 'catalog/news_form.html', {'type_choices': News.TYPE_CHOICES})


@login_required
@librarian_required
def news_edit_view(request, news_id):
    news = get_object_or_404(News, pk=news_id)
    if request.method == 'POST':
        news.title       = request.POST.get('title', news.title).strip()
        news.content     = request.POST.get('content', news.content).strip()
        news.news_type   = request.POST.get('news_type', news.news_type)
        news.video_url   = request.POST.get('video_url', '').strip()
        news.link_url    = request.POST.get('link_url', '').strip()
        news.is_active   = request.POST.get('is_active') == 'on'
        news.is_featured = request.POST.get('is_featured') == 'on'

        expires_at = request.POST.get('expires_at') or None
        if expires_at:
            from django.utils.dateparse import parse_datetime
            news.expires_at = parse_datetime(expires_at + ':00') if len(expires_at) == 16 else parse_datetime(expires_at)
        else:
            news.expires_at = None

        if 'image' in request.FILES:
            news.image = request.FILES['image']
        elif request.POST.get('clear_image'):
            news.image = None

        if 'attachment' in request.FILES:
            news.attachment = request.FILES['attachment']
        elif request.POST.get('clear_attachment'):
            news.attachment = None

        news.save()
        log_audit(request.user, f"Updated news post: '{news.title}'", request)
        messages.success(request, f"'{news.title}' updated.")
        return redirect('news_list')

    return render(request, 'catalog/news_form.html', {
        'news': news,
        'type_choices': News.TYPE_CHOICES,
    })


@login_required
@librarian_required
def news_delete_view(request, news_id):
    news = get_object_or_404(News, pk=news_id)
    if request.method == 'POST':
        title = news.title
        news.delete()
        log_audit(request.user, f"Deleted news post: '{title}'", request)
        messages.success(request, f"'{title}' deleted.")
        return redirect('news_list')
    return render(request, 'catalog/news_confirm_delete.html', {'news': news})


@login_required
@librarian_required
@require_POST
def news_toggle_view(request, news_id):
    news = get_object_or_404(News, pk=news_id)
    news.is_active = not news.is_active
    news.save(update_fields=['is_active'])
    state = 'activated' if news.is_active else 'deactivated'
    log_audit(request.user, f"News post '{news.title}' {state}", request)
    messages.success(request, f"'{news.title}' {state}.")
    return redirect('news_list')
