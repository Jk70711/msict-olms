import io

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Count, Sum, Q
from django.http import HttpResponse
from django.utils import timezone
from datetime import timedelta

from accounts.views import librarian_required, admin_required
from accounts.models import OLMSUser
from catalog.models import Book, BookCopy, Category
from circulation.models import BorrowingTransaction, Fine, BorrowRequest


# ── Shared PDF builder ──────────────────────────────────────────────────────
def _render_report_pdf(filename, report_title, subtitle, summary_pairs,
                       table_headers, table_rows, col_widths=None,
                       extra_sections=None, landscape=False):
    """
    Build a professional A4 PDF report and return an HttpResponse.

    summary_pairs  : list of (label, value) shown as a summary box
    table_headers  : column header strings
    table_rows     : list of lists (each cell converted to str automatically)
    extra_sections : list of (section_title, headers, rows) appended after main table
    landscape      : True for landscape A4
    """
    from reportlab.lib.pagesizes import A4, landscape as ls_func
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                    Paragraph, Spacer, HRFlowable)
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

    MSICT_BLUE = colors.HexColor('#1e40af')
    ALT_ROW    = colors.HexColor('#f1f5f9')

    pagesize = ls_func(A4) if landscape else A4
    pw = pagesize[0] - 30 * mm          # usable page width

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=pagesize,
                            leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=12 * mm, bottomMargin=12 * mm)

    s = getSampleStyleSheet()
    center = ParagraphStyle('c', parent=s['Normal'], alignment=TA_CENTER)
    hdr_s  = ParagraphStyle('h', parent=s['Normal'], fontName='Helvetica-Bold',
                             fontSize=8, textColor=colors.white, alignment=TA_CENTER)
    cell_s = ParagraphStyle('d', parent=s['Normal'], fontName='Helvetica',
                             fontSize=8, alignment=TA_LEFT)

    elems = []

    # ── Institution banner ──────────────────────────────────────────────────
    elems.append(Paragraph(
        '<b>MILITARY SCHOOL OF INFORMATION &amp; TECHNOLOGY (MSICT)</b>',
        ParagraphStyle('inst', parent=s['Normal'], fontName='Helvetica-Bold',
                       fontSize=13, alignment=TA_CENTER, textColor=MSICT_BLUE)))
    elems.append(Paragraph(
        'MSICT Library Management System',
        ParagraphStyle('sys', parent=s['Normal'], fontName='Helvetica',
                       fontSize=9, alignment=TA_CENTER, textColor=colors.grey)))
    elems.append(Spacer(1, 3 * mm))
    elems.append(HRFlowable(width='100%', thickness=1.5, color=MSICT_BLUE, spaceAfter=3 * mm))

    # ── Report title ────────────────────────────────────────────────────────
    elems.append(Paragraph(
        report_title.upper(),
        ParagraphStyle('title', parent=s['Normal'], fontName='Helvetica-Bold',
                       fontSize=14, alignment=TA_CENTER)))
    if subtitle:
        elems.append(Paragraph(
            subtitle,
            ParagraphStyle('sub', parent=s['Normal'], fontName='Helvetica',
                           fontSize=9, alignment=TA_CENTER, textColor=colors.grey)))
    elems.append(Spacer(1, 4 * mm))

    # ── Summary box ─────────────────────────────────────────────────────────
    if summary_pairs:
        sum_data = [[Paragraph(f'<b>{lbl}</b>', cell_s),
                     Paragraph(str(val), cell_s)]
                    for lbl, val in summary_pairs]
        ncols = 2
        chunk = [sum_data[i:i + 3] for i in range(0, len(sum_data), 3)]
        # lay pairs in rows of 3 side by side
        flat = []
        for grp in chunk:
            row = []
            for pair in grp:
                row += pair
            while len(row) < 6:
                row.append(Paragraph('', cell_s))
            flat.append(row)
        sum_col_w = pw / 6
        st = Table(flat, colWidths=[sum_col_w] * 6)
        st.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), ALT_ROW),
            ('FONTNAME',   (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE',   (0, 0), (-1, -1), 9),
            ('GRID',       (0, 0), (-1, -1), 0.4, colors.white),
            ('VALIGN',     (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        elems.append(st)
        elems.append(Spacer(1, 4 * mm))

    # ── Helper: build one data table ────────────────────────────────────────
    def _make_table(headers, rows, widths=None):
        if not rows:
            return Paragraph('<i>No data available.</i>', cell_s)
        ncol = len(headers)
        cw = widths if widths else [pw / ncol] * ncol
        hdr = [Paragraph(h, hdr_s) for h in headers]
        body = [[Paragraph(str(cell), cell_s) for cell in row] for row in rows]
        tdata = [hdr] + body
        ts = TableStyle([
            ('BACKGROUND',    (0, 0), (-1, 0), MSICT_BLUE),
            ('TEXTCOLOR',     (0, 0), (-1, 0), colors.white),
            ('FONTNAME',      (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE',      (0, 0), (-1, -1), 8),
            ('GRID',          (0, 0), (-1, -1), 0.3, colors.lightgrey),
            ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING',    (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, ALT_ROW]),
        ])
        t = Table(tdata, colWidths=cw, repeatRows=1)
        t.setStyle(ts)
        return t

    # ── Main table ───────────────────────────────────────────────────────────
    if table_headers and table_rows:
        elems.append(_make_table(table_headers, table_rows, col_widths))
        elems.append(Spacer(1, 5 * mm))

    # ── Extra sections ───────────────────────────────────────────────────────
    for sec_title, sec_headers, sec_rows in (extra_sections or []):
        elems.append(Paragraph(
            f'<b>{sec_title}</b>',
            ParagraphStyle('sec', parent=s['Normal'], fontName='Helvetica-Bold',
                           fontSize=10, textColor=MSICT_BLUE)))
        elems.append(Spacer(1, 2 * mm))
        elems.append(_make_table(sec_headers, sec_rows))
        elems.append(Spacer(1, 5 * mm))

    # ── Footer ───────────────────────────────────────────────────────────────
    gen_time = timezone.now().strftime('%d %b %Y  %H:%M')
    elems.append(HRFlowable(width='100%', thickness=0.5, color=colors.lightgrey,
                            spaceBefore=2 * mm, spaceAfter=2 * mm))
    elems.append(Paragraph(
        f'Generated: {gen_time} &nbsp;|&nbsp; MSICT OLMS',
        ParagraphStyle('foot', parent=s['Normal'], fontName='Helvetica',
                       fontSize=7, textColor=colors.grey, alignment=TA_CENTER)))

    doc.build(elems)
    buf.seek(0)
    resp = HttpResponse(buf, content_type='application/pdf')
    resp['Content-Disposition'] = f'attachment; filename="{filename}"'
    return resp


@login_required
@librarian_required
def reports_home_view(request):
    return render(request, 'reports/reports_home.html')


@login_required
@librarian_required
def report_members_view(request):
    members = OLMSUser.objects.filter(role='member').select_related()
    role_filter = request.GET.get('member_type', '')
    if role_filter:
        members = members.filter(member_type=role_filter)
    total = members.count()
    active = members.filter(is_active=True).count()
    return render(request, 'reports/report_members.html', {
        'members': members,
        'total': total,
        'active': active,
        'role_filter': role_filter,
    })


@login_required
@librarian_required
def report_books_view(request):
    books = Book.objects.select_related('category').prefetch_related('copies')
    total_books = books.count()
    total_copies = BookCopy.objects.count()
    available_copies = BookCopy.objects.filter(status='available').count()
    borrowed_copies = BookCopy.objects.filter(status='borrowed').count()
    lost_copies = BookCopy.objects.filter(status='lost').count()
    free_softcopies = BookCopy.objects.filter(copy_type='softcopy', access_type='free').count()
    special_softcopies = BookCopy.objects.filter(copy_type='softcopy', access_type='borrow').count()
    category_stats = Category.objects.annotate(book_count=Count('books')).order_by('-book_count')[:10]
    return render(request, 'reports/report_books.html', {
        'books': books[:50],
        'total_books': total_books,
        'total_copies': total_copies,
        'available_copies': available_copies,
        'borrowed_copies': borrowed_copies,
        'lost_copies': lost_copies,
        'free_softcopies': free_softcopies,
        'special_softcopies': special_softcopies,
        'category_stats': category_stats,
    })


@login_required
@librarian_required
def report_circulation_view(request):
    period = request.GET.get('period', '30')
    days = int(period) if period.isdigit() else 30
    since = timezone.now() - timedelta(days=days)

    transactions = BorrowingTransaction.objects.filter(borrow_date__gte=since).select_related('user', 'copy__book')
    total_borrowed = transactions.count()
    total_overdue = transactions.filter(status='overdue').count()
    total_returned = transactions.filter(status='returned').count()
    top_books = (
        BorrowingTransaction.objects.values('copy__book__title')
        .annotate(borrow_count=Count('id'))
        .order_by('-borrow_count')[:10]
    )
    top_borrowers = (
        BorrowingTransaction.objects.values('user__username', 'user__first_name', 'user__surname')
        .annotate(borrow_count=Count('id'))
        .order_by('-borrow_count')[:10]
    )
    return render(request, 'reports/report_circulation.html', {
        'transactions': transactions[:50],
        'total_borrowed': total_borrowed,
        'total_overdue': total_overdue,
        'total_returned': total_returned,
        'top_books': top_books,
        'top_borrowers': top_borrowers,
        'period': period,
    })


@login_required
@librarian_required
def report_fines_view(request):
    fines = Fine.objects.select_related('user', 'transaction__copy__book').order_by('-created_at')
    total_fines = fines.aggregate(total=Sum('amount'))['total'] or 0
    collected = fines.filter(paid=True).aggregate(total=Sum('amount'))['total'] or 0
    outstanding = fines.filter(paid=False).aggregate(total=Sum('amount'))['total'] or 0
    return render(request, 'reports/report_fines.html', {
        'fines': fines[:100],
        'total_fines': total_fines,
        'collected': collected,
        'outstanding': outstanding,
    })


@login_required
@librarian_required
def export_members_csv_view(request):
    import csv
    members = OLMSUser.objects.filter(role='member')
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="members.csv"'
    writer = csv.writer(response)
    writer.writerow(['Username', 'Army No', 'Full Name', 'Email', 'Phone', 'Role', 'Member Type', 'Active', 'Created'])
    for m in members:
        writer.writerow([m.username, m.army_no, m.get_full_name(), m.email, m.phone, m.role, m.get_member_type_display() if m.member_type else '', m.is_active, m.created_at.date()])
    return response


@login_required
@librarian_required
def export_books_csv_view(request):
    import csv
    books = Book.objects.select_related('category').prefetch_related('copies')
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="books.csv"'
    writer = csv.writer(response)
    writer.writerow(['Title', 'Author', 'ISBN', 'Publisher', 'Year', 'Category', 'Total Copies', 'Available'])
    for b in books:
        writer.writerow([b.title, b.author, b.isbn or '', b.publisher, b.year or '', b.category.name if b.category else '', b.total_hardcopies(), b.available_hardcopy_count()])
    return response


@login_required
@librarian_required
def export_members_pdf_view(request):
    members = OLMSUser.objects.filter(role='member').order_by('surname', 'first_name')
    member_type = request.GET.get('member_type', '')
    if member_type:
        members = members.filter(member_type=member_type)

    total  = members.count()
    active = members.filter(is_active=True).count()
    locked = total - active

    rows = [
        [i + 1,
         m.username,
         m.get_full_name(),
         m.army_no or '—',
         m.get_member_type_display() if m.member_type else '—',
         m.email or '—',
         'Active' if m.is_active else 'Locked',
         m.created_at.strftime('%d %b %Y') if m.created_at else '—']
        for i, m in enumerate(members)
    ]

    return _render_report_pdf(
        filename='members_report.pdf',
        report_title='Member Report',
        subtitle=f'Member Type: {member_type.title() or "All"}  |  Generated {timezone.now().strftime("%d %b %Y")}',
        summary_pairs=[
            ('Total Members', total),
            ('Active',        active),
            ('Locked',        locked),
        ],
        table_headers=['#', 'Username', 'Full Name', 'Army No', 'Type', 'Email', 'Status', 'Joined'],
        table_rows=rows,
        landscape=True,
    )


@login_required
@librarian_required
def export_books_pdf_view(request):
    books          = Book.objects.select_related('category').prefetch_related('copies').order_by('title')
    total_books    = books.count()
    total_copies   = BookCopy.objects.count()
    available      = BookCopy.objects.filter(status='available').count()
    borrowed       = BookCopy.objects.filter(status='borrowed').count()
    lost           = BookCopy.objects.filter(status='lost').count()
    free_sc        = BookCopy.objects.filter(copy_type='softcopy', access_type='free').count()
    special_sc     = BookCopy.objects.filter(copy_type='softcopy', access_type='borrow').count()
    category_stats = Category.objects.annotate(book_count=Count('books')).order_by('-book_count')[:10]

    rows = [
        [i + 1,
         b.title[:60],
         b.author[:35],
         b.isbn or '—',
         b.category.name if b.category else '—',
         b.year or '—',
         b.total_hardcopies(),
         b.available_hardcopy_count()]
        for i, b in enumerate(books)
    ]

    cat_rows = [[i + 1, c.name, c.book_count]
                for i, c in enumerate(category_stats)]

    return _render_report_pdf(
        filename='books_report.pdf',
        report_title='Book Inventory Report',
        subtitle=timezone.now().strftime('%d %b %Y'),
        summary_pairs=[
            ('Total Books',    total_books),
            ('Total Copies',   total_copies),
            ('Available',      available),
            ('Borrowed',       borrowed),
            ('Lost',           lost),
            ('Free PDFs',      free_sc),
            ('Special PDFs',   special_sc),
        ],
        table_headers=['#', 'Title', 'Author', 'ISBN', 'Category', 'Year', 'Copies', 'Available'],
        table_rows=rows,
        extra_sections=[
            ('Top Categories by Book Count',
             ['#', 'Category', 'Books'],
             cat_rows),
        ],
        landscape=True,
    )


@login_required
@librarian_required
def export_circulation_pdf_view(request):
    period = request.GET.get('period', '30')
    days   = int(period) if period.isdigit() else 30
    since  = timezone.now() - timedelta(days=days)

    txns          = BorrowingTransaction.objects.filter(borrow_date__gte=since).select_related('user', 'copy__book')
    total_borrow  = txns.count()
    total_overdue = txns.filter(status='overdue').count()
    total_return  = txns.filter(status='returned').count()

    top_books = (
        BorrowingTransaction.objects.values('copy__book__title')
        .annotate(cnt=Count('id')).order_by('-cnt')[:15]
    )
    top_borrowers = (
        BorrowingTransaction.objects.values('user__username', 'user__first_name', 'user__surname')
        .annotate(cnt=Count('id')).order_by('-cnt')[:15]
    )

    txn_rows = [
        [i + 1,
         t.user.get_full_name(),
         t.user.army_no or '—',
         t.copy.book.title[:45],
         t.borrow_type.title(),
         t.borrow_date.strftime('%d %b %Y'),
         t.due_date.strftime('%d %b %Y'),
         t.status.title()]
        for i, t in enumerate(txns[:100])
    ]

    top_book_rows     = [[i + 1, r['copy__book__title'][:55], r['cnt']]
                         for i, r in enumerate(top_books)]
    top_borrow_rows   = [[i + 1,
                          f"{r['user__first_name']} {r['user__surname']} ({r['user__username']})",
                          r['cnt']]
                         for i, r in enumerate(top_borrowers)]

    return _render_report_pdf(
        filename=f'circulation_report_{period}days.pdf',
        report_title='Circulation Report',
        subtitle=f'Last {days} day(s)  |  {timezone.now().strftime("%d %b %Y")}',
        summary_pairs=[
            ('Total Borrowed', total_borrow),
            ('Overdue',        total_overdue),
            ('Returned',       total_return),
        ],
        table_headers=['#', 'Member', 'Army No', 'Book Title', 'Type', 'Borrowed', 'Due', 'Status'],
        table_rows=txn_rows,
        extra_sections=[
            ('Top 15 Borrowed Books',
             ['#', 'Title', 'Times Borrowed'],
             top_book_rows),
            ('Top 15 Borrowers',
             ['#', 'Member', 'Total Borrows'],
             top_borrow_rows),
        ],
        landscape=True,
    )


@login_required
@librarian_required
def export_fines_pdf_view(request):
    fines       = Fine.objects.select_related('user', 'transaction__copy__book').order_by('-created_at')
    total_fines = fines.aggregate(total=Sum('amount'))['total'] or 0
    collected   = fines.filter(paid=True).aggregate(total=Sum('amount'))['total'] or 0
    outstanding = fines.filter(paid=False).aggregate(total=Sum('amount'))['total'] or 0

    rows = [
        [i + 1,
         f.user.get_full_name(),
         f.user.army_no or '—',
         f.reason[:55] if f.reason else '—',
         f'TZS {f.amount:,.2f}',
         'Paid' if f.paid else 'Unpaid',
         f.created_at.strftime('%d %b %Y'),
         f.paid_at.strftime('%d %b %Y') if f.paid_at else '—']
        for i, f in enumerate(fines)
    ]

    return _render_report_pdf(
        filename='fines_report.pdf',
        report_title='Fines Report',
        subtitle=timezone.now().strftime('%d %b %Y'),
        summary_pairs=[
            ('Total Fines Levied', f'TZS {total_fines:,.2f}'),
            ('Collected',          f'TZS {collected:,.2f}'),
            ('Outstanding',        f'TZS {outstanding:,.2f}'),
        ],
        table_headers=['#', 'Member', 'Army No', 'Reason', 'Amount', 'Status', 'Date', 'Paid On'],
        table_rows=rows,
        landscape=True,
    )


@login_required
@admin_required
def sql_report_view(request):
    result = None
    columns = []
    error = None
    sql = ''
    if request.method == 'POST':
        sql = request.POST.get('sql', '').strip()
        if sql.lower().startswith('select'):
            try:
                from django.db import connection
                with connection.cursor() as cursor:
                    cursor.execute(sql)
                    columns = [col[0] for col in cursor.description]
                    result = cursor.fetchmany(500)
            except Exception as e:
                error = str(e)
        else:
            error = 'Only SELECT queries are allowed.'
    return render(request, 'reports/sql_report.html', {
        'result': result, 'columns': columns, 'error': error, 'sql': sql
    })
