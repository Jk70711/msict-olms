import io
import re

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Count, Sum, Q
from django.http import HttpResponse
from django.utils import timezone
from django.views.decorators.http import require_POST
from datetime import timedelta

from accounts.views import librarian_required, admin_required
from accounts.models import OLMSUser
from catalog.models import Book, BookCopy, Category
from circulation.models import BorrowingTransaction, Fine, BorrowRequest, LossReport


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
        if widths:
            cw = [w * mm for w in widths]
        else:
            cw = [pw / ncol] * ncol
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
    role_filter = request.GET.get('role', 'all')
    member_type_filter = request.GET.get('member_type', '')
    
    users = OLMSUser.objects.select_related('virtual_card')
    
    # Filter by role (admin, librarian, member, or all)
    if role_filter and role_filter != 'all':
        users = users.filter(role=role_filter)
    
    # Filter by member type (only applicable for members)
    if member_type_filter and role_filter == 'member':
        users = users.filter(member_type=member_type_filter)
    
    total = users.count()
    active = users.filter(is_active=True).count()
    
    # Count by role
    admin_count = users.filter(role='admin').count()
    librarian_count = users.filter(role='librarian').count()
    member_count = users.filter(role='member').count()
    
    return render(request, 'reports/report_members.html', {
        'users': users,
        'total': total,
        'active': active,
        'role_filter': role_filter,
        'member_type_filter': member_type_filter,
        'admin_count': admin_count,
        'librarian_count': librarian_count,
        'member_count': member_count,
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
    
    # Loss fine statistics for lost copies
    loss_reports = LossReport.objects.filter(status='confirmed').select_related('loss_fine', 'transaction__copy__book')
    total_loss_fine = sum(lr.loss_fine.amount for lr in loss_reports if lr.loss_fine)
    loss_fine_paid = sum(lr.loss_fine.amount_paid for lr in loss_reports if lr.loss_fine)
    loss_fine_unpaid = total_loss_fine - loss_fine_paid

    # Add shelf information to books - query actual shelf per book per category
    for book in books:
        if book.category:
            # Get shelves for this book's category
            shelves = book.category.shelves.all()
            shelf_codes = [shelf.shelf_code for shelf in shelves]
            book.shelf_list = ', '.join(shelf_codes) if shelf_codes else '—'
        else:
            book.shelf_list = '—'

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
        'total_loss_fine': total_loss_fine,
        'loss_fine_paid': loss_fine_paid,
        'loss_fine_unpaid': loss_fine_unpaid,
    })


@login_required
@librarian_required
def report_circulation_view(request):
    period = request.GET.get('period', '30')
    days = int(period) if period.isdigit() else 30
    since = timezone.now() - timedelta(days=days)

    transactions = BorrowingTransaction.objects.filter(borrow_date__gte=since).select_related('user', 'copy__book', 'approved_by')
    total_borrowed = transactions.count()
    total_overdue = transactions.filter(status='overdue').count()
    total_returned = transactions.filter(status='returned').count()
    total_lost = transactions.filter(status='lost').count()
    
    # Loss fine statistics
    loss_reports = LossReport.objects.filter(status='confirmed', reported_at__gte=since).select_related('loss_fine')
    total_loss_fine = sum(lr.loss_fine.amount for lr in loss_reports if lr.loss_fine)
    loss_fine_paid = sum(lr.loss_fine.amount_paid for lr in loss_reports if lr.loss_fine)
    loss_fine_unpaid = total_loss_fine - loss_fine_paid
    
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
        'total_lost': total_lost,
        'total_loss_fine': total_loss_fine,
        'loss_fine_paid': loss_fine_paid,
        'loss_fine_unpaid': loss_fine_unpaid,
        'top_books': top_books,
        'top_borrowers': top_borrowers,
        'period': period,
    })


@login_required
@librarian_required
def report_fines_view(request):
    fines = Fine.objects.select_related('user', 'transaction__copy__book', 'transaction__approved_by').order_by('-created_at')
    total_fines = fines.aggregate(total=Sum('amount'))['total'] or 0
    total_paid = fines.aggregate(paid=Sum('amount_paid'))['paid'] or 0
    total_remaining = fines.aggregate(remaining=Sum('amount') - Sum('amount_paid'))['remaining'] or 0
    
    # Count by status
    fully_paid = fines.filter(paid=True).count()
    unpaid = fines.filter(amount_paid=0).count()
    partial = fines.filter(amount_paid__gt=0, paid=False).count()
    
    # Loss fine statistics
    loss_reports = LossReport.objects.filter(loss_fine__isnull=False).select_related('loss_fine')
    loss_fine_ids = [lr.loss_fine_id for lr in loss_reports]
    
    # Separate overdue fines from loss fines
    overdue_fines = fines.exclude(id__in=loss_fine_ids)
    loss_fines = fines.filter(id__in=loss_fine_ids)
    
    total_overdue_fines = overdue_fines.aggregate(total=Sum('amount'))['total'] or 0
    overdue_fine_paid = overdue_fines.aggregate(paid=Sum('amount_paid'))['paid'] or 0
    overdue_fine_unpaid = total_overdue_fines - overdue_fine_paid
    
    total_loss_fines = loss_fines.aggregate(total=Sum('amount'))['total'] or 0
    loss_fine_paid = loss_fines.aggregate(paid=Sum('amount_paid'))['paid'] or 0
    loss_fine_unpaid = total_loss_fines - loss_fine_paid
    
    return render(request, 'reports/report_fines.html', {
        'fines': fines[:100],
        'total_fines': total_fines,
        'total_paid': total_paid,
        'total_remaining': total_remaining,
        'fully_paid': fully_paid,
        'unpaid': unpaid,
        'partial': partial,
        'total_overdue_fines': total_overdue_fines,
        'overdue_fine_paid': overdue_fine_paid,
        'overdue_fine_unpaid': overdue_fine_unpaid,
        'total_loss_fines': total_loss_fines,
        'loss_fine_paid': loss_fine_paid,
        'loss_fine_unpaid': loss_fine_unpaid,
    })


def _parse_custom_period(raw):
    """Parse natural-language period like '6 days', '3 months', '9 years' into a since datetime.
    Uses .lower() so input is case-insensitive. Returns None if unparseable."""
    s = raw.strip().lower()
    m = re.match(r'(\d+)\s*(day|days|week|weeks|month|months|year|years)', s)
    if not m:
        return None, None
    n = int(m.group(1))
    unit = m.group(2)
    if unit in ('day', 'days'):
        delta = timedelta(days=n)
        label = f'{n} day{"s" if n != 1 else ""}'
    elif unit in ('week', 'weeks'):
        delta = timedelta(weeks=n)
        label = f'{n} week{"s" if n != 1 else ""}'
    elif unit in ('month', 'months'):
        delta = timedelta(days=n * 30)
        label = f'{n} month{"s" if n != 1 else ""}'
    elif unit in ('year', 'years'):
        delta = timedelta(days=n * 365)
        label = f'{n} year{"s" if n != 1 else ""}'
    else:
        return None, None
    return timezone.now() - delta, label


ALL_ACCOUNT_TYPES = ['overdue', 'link_fee', 'guest_fee', 'damage', 'loss']


def _revenue_summary(since=None, account_types=None):
    """Compute revenue aggregates from RevenueTransaction. Returns a dict.
    account_types: list of account_type values to include; None = all."""
    from circulation.models import RevenueTransaction
    from decimal import Decimal
    qs = RevenueTransaction.objects.all()
    if since:
        qs = qs.filter(recorded_at__gte=since)
    if account_types:
        qs = qs.filter(account_type__in=account_types)

    def _sum(**kw):
        return qs.filter(**kw).aggregate(t=Sum('amount'))['t'] or Decimal('0')

    overdue    = _sum(account_type='overdue')
    link_fee   = _sum(account_type='link_fee')
    guest_fee  = _sum(account_type='guest_fee')
    loss       = _sum(account_type='loss')  # usually negative (loss/refund)
    damage     = _sum(account_type='damage')

    total_revenue = overdue + link_fee + guest_fee + damage  # positive income streams
    total_loss = loss
    net_revenue = total_revenue + total_loss
    return {
        'overdue': overdue,
        'link_fee': link_fee,
        'guest_fee': guest_fee,
        'loss': total_loss,
        'damage': damage,
        'total_revenue': total_revenue,
        'net_revenue': net_revenue,
        'qs': qs,
    }


@login_required
@librarian_required
def report_revenue_view(request):
    """Revenue accounting overview — overdue, link, guest fees, loss and net revenue."""
    period = request.GET.get('period', 'all')
    custom_input = request.GET.get('custom', '').strip()
    account_types = request.GET.getlist('account_type')  # empty list = all

    since = None
    period_label = 'All Time'
    custom_error = None

    if custom_input:
        since, lbl = _parse_custom_period(custom_input)
        if since is None:
            custom_error = f'Could not parse "{custom_input}". Try e.g. "6 days", "3 months", "9 years".'
        else:
            period_label = f'Last {lbl}'
            period = 'custom'
    elif period != 'all' and period.isdigit():
        since = timezone.now() - timedelta(days=int(period))
        period_label = f'Last {period} days'

    if custom_error:
        messages.error(request, custom_error)

    active_types = account_types if account_types else None
    data = _revenue_summary(since=since, account_types=active_types)
    qs = data['qs'].select_related('user', 'recorded_by').order_by('-recorded_at')

    total_income = data['total_revenue'] or 1
    def _pct(v):
        try:
            return int((float(v) / float(total_income)) * 100)
        except Exception:
            return 0

    breakdown = [
        {'label': 'Overdue Fees',  'amount': data['overdue'],   'pct': _pct(data['overdue']),   'color': '#f59e0b'},
        {'label': 'Link Fees',     'amount': data['link_fee'],  'pct': _pct(data['link_fee']),  'color': '#3b82f6'},
        {'label': 'Guest Fees',    'amount': data['guest_fee'], 'pct': _pct(data['guest_fee']), 'color': '#10b981'},
        {'label': 'Damage Fines',  'amount': data['damage'],    'pct': _pct(data['damage']),    'color': '#ea580c'},
    ]

    return render(request, 'reports/report_revenue.html', {
        'overdue':        data['overdue'],
        'link_fee':       data['link_fee'],
        'guest_fee':      data['guest_fee'],
        'damage':         data['damage'],
        'loss':           data['loss'],
        'total_revenue':  data['total_revenue'],
        'net_revenue':    data['net_revenue'],
        'breakdown':      breakdown,
        'transactions':   qs[:100],
        'txn_count':      qs.count(),
        'period':         period,
        'period_label':   period_label,
        'custom_input':   custom_input,
        'account_types':  account_types,
    })


@login_required
@librarian_required
def export_revenue_pdf_view(request):
    """Export the revenue accounting report to PDF — respects custom period and account_type filters."""
    period = request.GET.get('period', 'all')
    custom_input = request.GET.get('custom', '').strip()
    account_types = request.GET.getlist('account_type')

    since = None
    period_label = 'All Time'

    if custom_input:
        since, lbl = _parse_custom_period(custom_input)
        if since is not None:
            period_label = f'Last {lbl}'
    elif period != 'all' and period.isdigit():
        since = timezone.now() - timedelta(days=int(period))
        period_label = f'Last {period} days'

    active_types = account_types if account_types else None
    data = _revenue_summary(since=since, account_types=active_types)
    qs = data['qs'].select_related('user').order_by('-recorded_at')

    type_label = ', '.join(account_types) if account_types else 'All Types'
    rows = [
        [i + 1,
         t.recorded_at.strftime('%d %b %Y %H:%M'),
         (t.user.get_full_name() if t.user else 'System'),
         t.get_account_type_display(),
         f'TZS {t.amount:,.2f}',
         (t.description or '')[:60]]
        for i, t in enumerate(qs[:300])
    ]

    return _render_report_pdf(
        filename=f'revenue_report_{period}.pdf',
        report_title='Revenue Accounting Report',
        subtitle=f'{period_label}  |  {type_label}  |  {timezone.now().strftime("%d %b %Y")}',
        summary_pairs=[
            ('Overdue Fees',  f'TZS {data["overdue"]:,.2f}'),
            ('Link Fees',     f'TZS {data["link_fee"]:,.2f}'),
            ('Guest Fees',    f'TZS {data["guest_fee"]:,.2f}'),
            ('Damage Fines',  f'TZS {data["damage"]:,.2f}'),
            ('Total Revenue', f'TZS {data["total_revenue"]:,.2f}'),
            ('Total Loss',    f'TZS {data["loss"]:,.2f}'),
            ('Net Revenue',   f'TZS {data["net_revenue"]:,.2f}'),
        ],
        table_headers=['#', 'Date', 'User', 'Account Type', 'Amount', 'Description'],
        table_rows=rows,
        landscape=True,
    )


@login_required
@librarian_required
def export_members_csv_view(request):
    import csv
    role_filter = request.GET.get('role', 'all')
    member_type_filter = request.GET.get('member_type', '')
    
    users = OLMSUser.objects.select_related('virtual_card')
    
    # Filter by role
    if role_filter and role_filter != 'all':
        users = users.filter(role=role_filter)
    
    # Filter by member type (only applicable for members)
    if member_type_filter and role_filter == 'member':
        users = users.filter(member_type=member_type_filter)
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="users.csv"'
    writer = csv.writer(response)
    writer.writerow(['Username', 'Army No', 'Full Name', 'Email', 'Phone', 'Role', 'Member Type', 'Active', 'Created'])
    for u in users:
        writer.writerow([u.username, u.army_no, u.get_full_name(), u.email, u.phone, u.role, u.get_member_type_display() if u.member_type else '', u.is_active, u.created_at.date()])
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
    role_filter = request.GET.get('role', 'all')
    member_type_filter = request.GET.get('member_type', '')
    
    users = OLMSUser.objects.select_related('virtual_card').order_by('surname', 'first_name')
    
    # Filter by role
    if role_filter and role_filter != 'all':
        users = users.filter(role=role_filter)
    
    # Filter by member type (only applicable for members)
    if member_type_filter and role_filter == 'member':
        users = users.filter(member_type=member_type_filter)

    total  = users.count()
    active = users.filter(is_active=True).count()
    locked = total - active
    
    # Count by role
    admin_count = users.filter(role='admin').count()
    librarian_count = users.filter(role='librarian').count()
    member_count = users.filter(role='member').count()

    rows = [
        [i + 1,
         u.username,
         u.get_full_name(),
         u.army_no or '—',
         u.role.title(),
         u.get_member_type_display() if u.member_type else '—',
         u.email or '—',
         'Active' if u.is_active else 'Locked',
         u.created_at.strftime('%d %b %Y') if u.created_at else '—']
        for i, u in enumerate(users)
    ]

    return _render_report_pdf(
        filename='users_report.pdf',
        report_title='Users Report',
        subtitle=f'Role: {role_filter.title() or "All"} | Type: {member_type_filter.title() or "All"}  |  Generated {timezone.now().strftime("%d %b %Y")}',
        summary_pairs=[
            ('Total Users',    total),
            ('Active',         active),
            ('Locked',         locked),
            ('Admin',          admin_count),
            ('Librarian',      librarian_count),
            ('Member',         member_count),
        ],
        table_headers=['#', 'Username', 'Full Name', 'Army No', 'Role', 'Type', 'Email', 'Status', 'Joined'],
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

    # Add shelf information to books - query actual shelf per book per category
    for book in books:
        if book.category:
            # Get shelves for this book's category
            shelves = book.category.shelves.all()
            shelf_codes = [shelf.shelf_code for shelf in shelves]
            book.shelf_list = ', '.join(shelf_codes) if shelf_codes else '—'
        else:
            book.shelf_list = '—'

    rows = [
        [i + 1,
         b.title[:60],
         b.author[:35],
         b.isbn or '—',
         b.category.name if b.category else '—',
         b.year or '—',
         b.shelf_list,
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
        table_headers=['#', 'Title', 'Author', 'ISBN', 'Category', 'Year', 'Shelf', 'Copies', 'Available'],
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
    total_paid  = fines.aggregate(paid=Sum('amount_paid'))['paid'] or 0
    total_remaining = fines.aggregate(remaining=Sum('amount') - Sum('amount_paid'))['remaining'] or 0
    
    # Count by status
    fully_paid = fines.filter(paid=True).count()
    unpaid = fines.filter(amount_paid=0).count()
    partial = fines.filter(amount_paid__gt=0, paid=False).count()

    rows = [
        [i + 1,
         f.user.get_full_name(),
         f.user.army_no or '—',
         f.reason[:50] if f.reason else '—',
         f'TZS {f.amount:,.2f}',
         f'TZS {f.amount_paid:,.2f}',
         f'TZS {f.remaining_balance:,.2f}',
         'Paid' if f.paid else 'Partial' if f.amount_paid > 0 else 'Unpaid',
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
            ('Total Collected',      f'TZS {total_paid:,.2f}'),
            ('Total Outstanding',    f'TZS {total_remaining:,.2f}'),
            ('Fully Paid',           fully_paid),
            ('Partial Payments',     partial),
            ('Unpaid',               unpaid),
        ],
        table_headers=['#', 'Member', 'Army No', 'Reason', 'Total', 'Paid', 'Remaining', 'Status', 'Date', 'Paid On'],
        table_rows=rows,
        landscape=True,
    )


def _validate_select_sql(sql):
    """Validate that SQL is a safe read-only SELECT query.
    Returns (is_valid, error_message)."""
    if not sql:
        return False, 'Empty query.'
    sql_lower = sql.lower().strip()
    if not sql_lower.startswith('select'):
        return False, 'Only SELECT queries are allowed.'
    # Block dangerous keywords that could modify data
    dangerous = ['insert', 'update', 'delete', 'drop', 'alter', 'truncate',
                 'create', 'grant', 'revoke', 'exec', 'execute', 'merge',
                 'into', 'call']
    # Check for semicolons (statement injection)
    if ';' in sql.rstrip(';').strip():
        return False, 'Multiple statements are not allowed.'
    # Check for dangerous keywords as whole words
    import re as _re
    for kw in dangerous:
        if _re.search(r'\b' + kw + r'\b', sql_lower):
            return False, f'Keyword "{kw.upper()}" is not allowed in SELECT queries.'
    return True, None


@login_required
@admin_required
def sql_report_view(request):
    result = None
    columns = []
    error = None
    sql = ''
    if request.method == 'POST':
        sql = request.POST.get('sql', '').strip()
        is_valid, err_msg = _validate_select_sql(sql)
        if is_valid:
            try:
                from django.db import connection
                with connection.cursor() as cursor:
                    cursor.execute(sql)
                    columns = [col[0] for col in cursor.description]
                    result = cursor.fetchmany(500)
            except Exception as e:
                error = str(e)
        else:
            error = err_msg
    return render(request, 'reports/sql_report.html', {
        'result': result, 'columns': columns, 'error': error, 'sql': sql
    })


@login_required
@admin_required
@require_POST
def export_sql_pdf_view(request):
    """Export SQL query results to PDF"""
    from django.db import connection
    sql = request.POST.get('sql', '').strip()
    is_valid, err_msg = _validate_select_sql(sql)
    if not is_valid:
        return HttpResponse(f'Invalid SQL query: {err_msg}', status=400)

    try:
        with connection.cursor() as cursor:
            cursor.execute(sql)
            columns = [col[0] for col in cursor.description]
            result = cursor.fetchall()
    except Exception as e:
        return HttpResponse(f'Error: {str(e)}', status=400)

    rows = [[i + 1] + [str(cell) if cell is not None else 'NULL' for cell in row]
            for i, row in enumerate(result)]

    header_row = ['#'] + columns

    return _render_report_pdf(
        filename='sql_report.pdf',
        report_title='Custom SQL Report',
        subtitle=timezone.now().strftime('%d %b %Y'),
        summary_pairs=[
            ('Total Rows', len(result)),
            ('Columns', len(columns)),
        ],
        table_headers=header_row,
        table_rows=rows
    )


@login_required
@admin_required
@require_POST
def export_sql_csv_view(request):
    """Export SQL query results to CSV"""
    from django.db import connection
    sql = request.POST.get('sql', '').strip()
    is_valid, err_msg = _validate_select_sql(sql)
    if not is_valid:
        return HttpResponse(f'Invalid SQL query: {err_msg}', status=400)

    try:
        with connection.cursor() as cursor:
            cursor.execute(sql)
            columns = [col[0] for col in cursor.description]
            result = cursor.fetchall()
    except Exception as e:
        return HttpResponse(f'Error: {str(e)}', status=400)

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="sql_report.csv"'

    writer = csv.writer(response)
    writer.writerow(columns)
    for row in result:
        writer.writerow([str(cell) if cell is not None else 'NULL' for cell in row])

    return response


# ── Custom report builder (admin + librarian; ORM-only, no raw SQL) ─────────
import json as _json

from .custom_report_config import REPORT_TABLES, TIME_PRESETS, get_tables_for_role
from .custom_report_service import (
    get_table_config,
    report_params_from_request,
    run_report,
    validate_columns,
    parse_filters,
)
from .models import ReportTemplate


def _role_tables(request):
    """Return the table dict visible to the requesting user's role."""
    return get_tables_for_role(request.user.role)


def _custom_report_context(request, preview_result=None, form_errors=None):
    table_key, preset, custom_text, selected_columns, page, filters = report_params_from_request(request)
    role_tables = _role_tables(request)

    # Guard: librarian cannot access admin-only tables even via direct POST
    table_cfg = None
    if table_key and table_key in role_tables:
        table_cfg = get_table_config(table_key)

    available_columns = table_cfg['columns'] if table_cfg else {}
    filter_fields = table_cfg.get('filter_fields', {}) if table_cfg else {}

    if table_cfg and not selected_columns:
        selected_columns = list(table_cfg['default_columns'])
    elif table_cfg:
        selected_columns = validate_columns(table_key, selected_columns)

    saved_templates = ReportTemplate.objects.filter(created_by=request.user).order_by('-created_at')[:20]

    # Build filter_fields serialisable for JS
    filter_fields_js = {
        k: {'label': v['label'], 'type': v['type'],
            'choices': v.get('choices', [])}
        for k, v in filter_fields.items()
    }
    all_filter_fields_js = {
        tbl_key: {
            fk: {'label': fv['label'], 'type': fv['type'], 'choices': fv.get('choices', [])}
            for fk, fv in tbl_cfg.get('filter_fields', {}).items()
        }
        for tbl_key, tbl_cfg in role_tables.items()
    }
    all_columns_js = {
        tbl_key: list(tbl_cfg['columns'].items())
        for tbl_key, tbl_cfg in role_tables.items()
    }

    # Reconstruct current filters as indexed dict for template rendering
    current_filters = {}
    for i, (fk, fv) in enumerate(filters, start=1):
        current_filters[i] = {'key': fk, 'val': fv}

    return {
        'report_tables': role_tables,
        'time_presets': TIME_PRESETS,
        'table_key': table_key,
        'table_cfg': table_cfg,
        'available_columns': available_columns,
        'selected_columns': selected_columns,
        'filter_fields': filter_fields,
        'current_filters': current_filters,
        'preset': preset,
        'custom_duration': custom_text,
        'preview': preview_result,
        'form_errors': form_errors or [],
        'saved_templates': saved_templates,
        'all_filter_fields_js': _json.dumps(all_filter_fields_js),
        'all_columns_js': _json.dumps(all_columns_js),
    }


@login_required
@librarian_required
def custom_report_view(request):
    ctx = _custom_report_context(request)
    return render(request, 'reports/custom_report.html', ctx)


@login_required
@librarian_required
def custom_report_preview_view(request):
    if request.method != 'POST':
        return redirect('custom_report')

    table_key, preset, custom_text, columns, page, filters = report_params_from_request(request)

    # Role guard
    role_tables = _role_tables(request)
    if table_key not in role_tables:
        messages.error(request, 'You do not have permission to access that table.')
        return redirect('custom_report')

    result = run_report(table_key, columns, preset, custom_text, page=page, filters=filters)
    ctx = _custom_report_context(request, preview_result=result)
    if result.get('error'):
        ctx['form_errors'] = [result['error']]
    return render(request, 'reports/custom_report.html', ctx)


@login_required
@librarian_required
def custom_report_export_view(request):
    fmt = request.GET.get('format', 'csv').lower()
    table_key, preset, custom_text, columns, _page, filters = report_params_from_request(request)

    role_tables = _role_tables(request)
    if table_key not in role_tables:
        messages.error(request, 'You do not have permission to access that table.')
        return redirect('custom_report')

    result = run_report(table_key, columns, preset, custom_text, for_export=True, filters=filters)
    if result.get('error'):
        messages.error(request, result['error'])
        return redirect('custom_report')

    headers = result['headers']
    rows = result['rows']
    safe_name = (result['table_label'] or 'report').replace(' ', '_').lower()
    stamp = timezone.now().strftime('%Y%m%d')

    if fmt == 'pdf':
        pdf_rows = [[i + 1] + row for i, row in enumerate(rows)]
        pdf_headers = ['#'] + headers
        summary = [
            ('Table', result['table_label']),
            ('Time Range', result['range_label']),
            ('Total Rows', result['total']),
        ]
        if result.get('truncated'):
            summary.append(('Note', f'Export capped at {len(rows)} rows'))
        return _render_report_pdf(
            filename=f'{safe_name}_{stamp}.pdf',
            report_title=f'Custom Report — {result["table_label"]}',
            subtitle=f'{result["range_label"]}  |  {timezone.now().strftime("%d %b %Y")}',
            summary_pairs=summary,
            table_headers=pdf_headers,
            table_rows=pdf_rows,
            landscape=len(headers) > 5,
        )

    if fmt == 'xlsx':
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = 'Report'
        ws.append(headers)
        for row in rows:
            ws.append(row)
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        response = HttpResponse(
            buf.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response['Content-Disposition'] = f'attachment; filename="{safe_name}_{stamp}.xlsx"'
        return response

    import csv
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{safe_name}_{stamp}.csv"'
    writer = csv.writer(response)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(row)
    return response


@login_required
@librarian_required
def save_report_template_view(request):
    if request.method != 'POST':
        return redirect('custom_report')
    name = (request.POST.get('template_name') or '').strip()
    table_key, preset, custom_text, columns, _page, filters = report_params_from_request(request)
    if not name:
        messages.error(request, 'Please enter a template name.')
        return redirect('custom_report')
    if not table_key:
        messages.error(request, 'Please select a table before saving.')
        return redirect('custom_report')
    role_tables = _role_tables(request)
    if table_key not in role_tables:
        messages.error(request, 'Invalid table.')
        return redirect('custom_report')
    ReportTemplate.objects.create(
        name=name,
        created_by=request.user,
        table_key=table_key,
        columns_json=_json.dumps(columns),
        preset=preset,
        custom_duration=custom_text,
        filters_json=_json.dumps(filters),
    )
    messages.success(request, f'Template "{name}" saved successfully.')
    return redirect('custom_report')


@login_required
@librarian_required
@require_POST
def delete_report_template_view(request, template_id):
    tmpl = ReportTemplate.objects.filter(pk=template_id, created_by=request.user).first()
    if tmpl:
        tmpl.delete()
        messages.success(request, f'Template "{tmpl.name}" deleted.')
    else:
        messages.error(request, 'Template not found or not yours.')
    return redirect('custom_report')


@login_required
@librarian_required
def report_loss_view(request):
    """Loss report summary for librarians and admins."""
    from django.db.models import DecimalField, Value
    from django.db.models.functions import Coalesce
    from decimal import Decimal

    period = request.GET.get('period', 'all')
    status_filter = request.GET.get('status', '')
    search_query = request.GET.get('search', '')

    reports = LossReport.objects.select_related(
        'user__rank', 'transaction__copy__book', 'reviewed_by', 'loss_fine'
    ).order_by('-reported_at')

    # Apply period filter
    if period != 'all':
        days = int(period) if period.isdigit() else 30
        since = timezone.now() - timedelta(days=days)
        reports = reports.filter(reported_at__gte=since)

    # Apply status filter
    if status_filter:
        reports = reports.filter(status=status_filter)

    # Apply search filter
    if search_query:
        reports = reports.filter(
            Q(user__first_name__icontains=search_query) |
            Q(user__surname__icontains=search_query) |
            Q(user__army_no__icontains=search_query) |
            Q(transaction__copy__book__title__icontains=search_query)
        )

    total        = reports.count()
    pending      = reports.filter(status='pending').count()
    confirmed    = reports.filter(status='confirmed').count()
    resolved     = reports.filter(status='resolved').count()
    dismissed    = reports.filter(status='dismissed').count()

    loss_fine_total = Fine.objects.filter(
        loss_report__isnull=False
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
    loss_fine_paid = Fine.objects.filter(
        loss_report__isnull=False, paid=True
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

    return render(request, 'reports/report_loss.html', {
        'reports':         reports,
        'total':           total,
        'pending':         pending,
        'confirmed':       confirmed,
        'resolved':        resolved,
        'dismissed':       dismissed,
        'loss_fine_total': loss_fine_total,
        'loss_fine_paid':  loss_fine_paid,
        'loss_fine_unpaid': loss_fine_total - loss_fine_paid,
        'period':          period,
        'status_filter':   status_filter,
        'search_query':    search_query,
    })


@login_required
@librarian_required
def export_loss_pdf_view(request):
    """Export loss reports to PDF with optional filters."""
    from decimal import Decimal

    period = request.GET.get('period', 'all')
    status_filter = request.GET.get('status', '')
    search_query = request.GET.get('search', '')

    reports = LossReport.objects.select_related(
        'user__rank', 'transaction__copy__book', 'reviewed_by', 'loss_fine'
    ).order_by('-reported_at')

    # Apply period filter
    if period != 'all':
        days = int(period) if period.isdigit() else 30
        since = timezone.now() - timedelta(days=days)
        reports = reports.filter(reported_at__gte=since)

    # Apply status filter
    if status_filter:
        reports = reports.filter(status=status_filter)

    # Apply search filter
    if search_query:
        reports = reports.filter(
            Q(user__first_name__icontains=search_query) |
            Q(user__surname__icontains=search_query) |
            Q(user__army_no__icontains=search_query) |
            Q(transaction__copy__book__title__icontains=search_query)
        )

    total = reports.count()
    pending = reports.filter(status='pending').count()
    confirmed = reports.filter(status='confirmed').count()
    resolved = reports.filter(status='resolved').count()
    dismissed = reports.filter(status='dismissed').count()

    loss_fine_total = Fine.objects.filter(
        loss_report__isnull=False
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
    loss_fine_paid = Fine.objects.filter(
        loss_report__isnull=False, paid=True
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

    # Build table rows
    report_rows = []
    for i, report in enumerate(reports[:200]):
        tx = report.transaction
        copy = report.transaction.copy
        
        # Calculate overdue fine
        overdue_fine_amount = 0
        overdue_fine_paid = 0
        for f in tx.fines.all():
            if not hasattr(f, 'loss_report') or f.loss_report is None:
                overdue_fine_amount = float(f.amount)
                overdue_fine_paid = float(f.amount_paid)
                break
        
        # Calculate loss fine
        loss_fine_amount = float(report.loss_fine.amount) if report.loss_fine else 0
        loss_fine_paid_amount = float(report.loss_fine.amount_paid) if report.loss_fine else 0
        
        # Calculate total fine
        total_fine = overdue_fine_amount + loss_fine_amount
        
        # Payment status
        payment_status = 'No Fines'
        if tx.fines.exists() or report.loss_fine:
            payment_status = ''
            for f in tx.fines.all():
                if not hasattr(f, 'loss_report') or f.loss_report is None:
                    if f.paid:
                        payment_status += 'OD Paid '
                    elif f.amount_paid > 0:
                        payment_status += 'OD Partial '
                    else:
                        payment_status += 'OD Unpaid '
            if report.loss_fine:
                if report.loss_fine.paid:
                    payment_status += 'LF Paid'
                elif report.loss_fine.amount_paid > 0:
                    payment_status += 'LF Partial'
                else:
                    payment_status += 'LF Unpaid'
        
        report_rows.append([
            i + 1,
            f'LR-{report.pk}',
            report.user.get_full_name(),
            report.user.army_no or '—',
            report.user.rank.rank_name if report.user.rank else '—',
            copy.book.title[:50],
            copy.accession_no,
            tx.borrow_date.strftime('%d %b %Y'),
            tx.due_date.strftime('%d %b %Y'),
            f'TZS {overdue_fine_amount:,.0f}',
            f'TZS {loss_fine_amount:,.0f}' if report.loss_fine else '—',
            f'TZS {total_fine:,.0f}',
            payment_status,
            report.reported_at.strftime('%d %b %Y'),
            report.get_status_display(),
            report.reviewed_by.get_full_name() if report.reviewed_by else '—',
        ])

    period_label = 'All Time' if period == 'all' else f'Last {period} days'
    subtitle = f'{period_label}  |  {timezone.now().strftime("%d %b %Y")}'
    if status_filter:
        subtitle += f'  |  Status: {status_filter.title()}'
    if search_query:
        subtitle += f'  |  Search: {search_query}'

    return _render_report_pdf(
        filename=f'loss_reports_{period}.pdf',
        report_title='Loss Reports',
        subtitle=subtitle,
        summary_pairs=[
            ('Total Reports', total),
            ('Pending', pending),
            ('Confirmed', confirmed),
            ('Resolved', resolved),
            ('Dismissed', dismissed),
            ('Loss Fines Total', f'TZS {int(loss_fine_total):,}'),
            ('Loss Fines Paid', f'TZS {int(loss_fine_paid):,}'),
            ('Loss Fines Unpaid', f'TZS {int(loss_fine_total - loss_fine_paid):,}'),
        ],
        table_headers=[
            '#', 'Ref', 'Member', 'Army No', 'Rank', 'Book Title', 'Accession No',
            'Borrowed', 'Due Date', 'Overdue Fine', 'Loss Fine', 'Total Fine',
            'Payment Status', 'Reported', 'Status', 'Reviewed By'
        ],
        table_rows=report_rows,
        col_widths=[7, 10, 22, 13, 13, 35, 13, 13, 13, 13, 13, 13, 18, 13, 13, 18],
        landscape=True,
    )


# ── Excel (xlsx) exports for standard reports ────────────────────────────────

def _make_xlsx_response(wb, filename):
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    response = HttpResponse(
        buf.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    stamp = timezone.now().strftime('%Y%m%d_%H%M')
    response['Content-Disposition'] = f'attachment; filename="{filename}_{stamp}.xlsx"'
    return response


@login_required
@librarian_required
def export_members_xlsx_view(request):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    role_filter = request.GET.get('role', 'all')
    member_type_filter = request.GET.get('member_type', '')
    users = OLMSUser.objects.select_related('virtual_card')
    if role_filter and role_filter != 'all':
        users = users.filter(role=role_filter)
    if member_type_filter and role_filter == 'member':
        users = users.filter(member_type=member_type_filter)
    wb = Workbook()
    ws = wb.active
    ws.title = 'Members'
    headers = ['#', 'Username', 'Army No', 'Full Name', 'Email', 'Phone',
               'Role', 'Member Type', 'Status', 'Created']
    ws.append(headers)
    hdr_fill = PatternFill('solid', fgColor='1F3864')
    for cell in ws[1]:
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = hdr_fill
        cell.alignment = Alignment(horizontal='center')
    for i, u in enumerate(users, start=1):
        ws.append([
            i, u.username, u.army_no or '', u.get_full_name(), u.email or '',
            u.phone or '', u.get_role_display(),
            u.get_member_type_display() if u.member_type else '',
            'Active' if u.is_active else 'Inactive',
            u.created_at.strftime('%d %b %Y') if u.created_at else '',
        ])
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = max(
            len(str(cell.value or '')) for cell in col
        ) + 4
    return _make_xlsx_response(wb, 'members_report')


@login_required
@librarian_required
def export_books_xlsx_view(request):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    books = Book.objects.select_related('category').prefetch_related('copies')
    wb = Workbook()
    ws = wb.active
    ws.title = 'Books'
    headers = ['#', 'Title', 'Author', 'ISBN', 'Publisher', 'Year',
               'Category', 'Total Copies', 'Available Hardcopies', 'Softcopies']
    ws.append(headers)
    hdr_fill = PatternFill('solid', fgColor='1F3864')
    for cell in ws[1]:
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = hdr_fill
        cell.alignment = Alignment(horizontal='center')
    for i, b in enumerate(books, start=1):
        ws.append([
            i, b.title, b.author, b.isbn or '', b.publisher or '',
            b.year or '', b.category.name if b.category else '',
            b.total_hardcopies(), b.available_hardcopy_count(),
            b.copies.filter(copy_type='softcopy').count(),
        ])
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = max(
            len(str(cell.value or '')) for cell in col
        ) + 4
    return _make_xlsx_response(wb, 'books_report')


@login_required
@librarian_required
def export_circulation_xlsx_view(request):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    period = request.GET.get('period', '30')
    days = int(period) if period.isdigit() else 30
    since = timezone.now() - timedelta(days=days)
    txs = BorrowingTransaction.objects.filter(
        borrow_date__gte=since
    ).select_related('user', 'copy__book', 'approved_by').order_by('-borrow_date')
    wb = Workbook()
    ws = wb.active
    ws.title = 'Circulation'
    headers = ['#', 'Member', 'Army No', 'Book Title', 'Accession No',
               'Copy Type', 'Borrow Date', 'Due Date', 'Returned Date', 'Status']
    ws.append(headers)
    hdr_fill = PatternFill('solid', fgColor='1F3864')
    for cell in ws[1]:
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = hdr_fill
        cell.alignment = Alignment(horizontal='center')
    for i, tx in enumerate(txs, start=1):
        ws.append([
            i,
            tx.user.get_full_name() or tx.user.username,
            tx.user.army_no or '',
            tx.copy.book.title if tx.copy and tx.copy.book else '',
            tx.copy.accession_no if tx.copy else '',
            tx.copy.get_copy_type_display() if tx.copy else '',
            tx.borrow_date.strftime('%d %b %Y') if tx.borrow_date else '',
            tx.due_date.strftime('%d %b %Y') if tx.due_date else '',
            tx.return_date.strftime('%d %b %Y') if tx.return_date else '',
            tx.get_status_display(),
        ])
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = max(
            len(str(cell.value or '')) for cell in col
        ) + 4
    return _make_xlsx_response(wb, 'circulation_report')


@login_required
@librarian_required
def export_fines_xlsx_view(request):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    fines = Fine.objects.select_related(
        'user', 'transaction__copy__book'
    ).order_by('-created_at')
    wb = Workbook()
    ws = wb.active
    ws.title = 'Fines'
    headers = ['#', 'Member', 'Army No', 'Book Title', 'Reason',
               'Amount (TZS)', 'Paid (TZS)', 'Remaining (TZS)', 'Status', 'Created']
    ws.append(headers)
    hdr_fill = PatternFill('solid', fgColor='1F3864')
    for cell in ws[1]:
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = hdr_fill
        cell.alignment = Alignment(horizontal='center')
    for i, f in enumerate(fines, start=1):
        ws.append([
            i,
            f.user.get_full_name() or f.user.username,
            f.user.army_no or '',
            f.transaction.copy.book.title if f.transaction and f.transaction.copy and f.transaction.copy.book else '',
            f.reason or '',
            float(f.amount),
            float(f.amount_paid),
            float(f.remaining_balance),
            'Paid' if f.paid else ('Partial' if f.amount_paid > 0 else 'Unpaid'),
            f.created_at.strftime('%d %b %Y') if f.created_at else '',
        ])
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = max(
            len(str(cell.value or '')) for cell in col
        ) + 4
    return _make_xlsx_response(wb, 'fines_report')

