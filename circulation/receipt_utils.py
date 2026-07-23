"""
Shared PDF receipt generator for all payment types in OLMS.
Generates branded A5 receipts styled like a POS receipt:
  - Courier font, dashed separators, right-aligned values
  - Logo as full-page background watermark (10 % opacity)
  - "PAID" diagonal stamp across the content (green, 18 % opacity)
  - QR code at the bottom for authenticity verification
"""
from io import BytesIO
import os

from django.http import HttpResponse
from django.utils import timezone


def generate_receipt_pdf(
    *,
    receipt_id,
    title,
    user,
    items,
    qr_data,
    payment_method='',
    amount_label='Amount Paid',
    amount_value=None,
    filename='receipt',
    extra_notes=None,
):
    """
    Generate a branded PDF receipt and return an HttpResponse.

    Args:
        receipt_id:     Unique receipt identifier string (e.g. "RCPT-GUEST-5-20260704")
        title:          Receipt title shown at top (e.g. "Guest Session Receipt")
        user:           OLMSUser instance the receipt is for
        items:          List of (label, value) tuples for the itemized section
        qr_data:        String to encode in the QR code
        payment_method: Payment method string (e.g. "M-PESA")
        amount_label:   Label for the total row
        amount_value:   Formatted amount string (e.g. "TZS 5,000")
        filename:       Base filename for the PDF download
        extra_notes:    Optional list of extra note strings to append

    Returns:
        HttpResponse with PDF content.
    """
    from reportlab.lib.pagesizes import A5
    from reportlab.lib.units import mm
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.colors import HexColor, Color
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
        Image as RLImage,
    )
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.pdfgen import canvas as canvas_mod
    import qrcode

    PAGE_W, PAGE_H = A5
    MARGIN_H = 12 * mm
    MARGIN_V = 10 * mm
    CW = PAGE_W - 2 * MARGIN_H   # usable content width

    # ── QR code ────────────────────────────────────────────────────
    qr = qrcode.QRCode(version=1, box_size=6, border=2)
    qr.add_data(qr_data)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color='black', back_color='white')
    qr_buf = BytesIO()
    qr_img.save(qr_buf, format='PNG')
    qr_buf.seek(0)

    # ── Logo path ──────────────────────────────────────────────────
    logo_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        'static', 'images', 'msict_logo.png',
    )

    # ── Watermark PNG (logo at 10 % opacity) ───────────────────────
    watermark_buf = None
    if os.path.exists(logo_path):
        try:
            from PIL import Image as PILImage
            pil_img = PILImage.open(logo_path).convert('RGBA')
            a_ch = pil_img.split()[3]
            a_ch = a_ch.point(lambda p: int(p * 0.08))
            pil_img.putalpha(a_ch)
            watermark_buf = BytesIO()
            pil_img.save(watermark_buf, format='PNG')
            watermark_buf.seek(0)
        except Exception:
            watermark_buf = None

    # ── Custom canvas: logo watermark + "PAID" diagonal stamp ──────
    class WatermarkCanvas(canvas_mod.Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._saved_page_states = []

        def showPage(self):
            self._saved_page_states.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            for state in self._saved_page_states:
                self.__dict__.update(state)
                self._draw_bg()
                super().showPage()
            super().save()

        def _draw_bg(self):
            # 1. Logo — centred, fills most of the page
            if watermark_buf:
                try:
                    self.saveState()
                    wm_size = 145 * mm
                    watermark_buf.seek(0)
                    self.drawImage(
                        watermark_buf,
                        (PAGE_W - wm_size) / 2,
                        (PAGE_H - wm_size) / 2,
                        wm_size, wm_size,
                        mask='auto',
                    )
                    self.restoreState()
                except Exception:
                    pass

            # 2. "PAID" diagonal text — green, semi-transparent, centred
            self.saveState()
            self.setFont('Helvetica-Bold', 72)
            self.setFillColor(Color(0.02, 0.55, 0.02, alpha=0.12))
            self.translate(PAGE_W / 2, PAGE_H / 2)
            self.rotate(45)
            self.drawCentredString(0, 0, 'PAID')
            self.restoreState()

    # ── Style helpers ──────────────────────────────────────────────
    def ps(name, font='Courier', size=8, bold=False, align=TA_LEFT, color='#000000', leading=None):
        ff = f'{font}-Bold' if bold else font
        return ParagraphStyle(
            name, fontName=ff, fontSize=size,
            alignment=align,
            textColor=HexColor(color),
            leading=leading or size * 1.4,
            spaceAfter=0, spaceBefore=0,
        )

    s_center_bold = ps('cb', size=10, bold=True, align=TA_CENTER)
    s_center      = ps('cs', size=8,  align=TA_CENTER, color='#444444')
    s_left        = ps('ls', size=8)
    s_right       = ps('rs', size=8,  align=TA_RIGHT)
    s_total_l     = ps('tl', size=10, bold=True)
    s_total_r     = ps('tr', size=10, bold=True, align=TA_RIGHT)
    s_foot        = ps('ft', size=7,  align=TA_CENTER, color='#888888')
    s_dash        = ps('ds', size=7,  align=TA_CENTER, color='#aaaaaa')

    DASHES = '- ' * 30

    def dash():
        return [Paragraph(DASHES, s_dash), Spacer(1, 1 * mm)]

    def row(label, value, ls=None, rs=None, col_split=0.48):
        ls = ls or s_left
        rs = rs or s_right
        t = Table(
            [[Paragraph(str(label), ls), Paragraph(str(value), rs)]],
            colWidths=[CW * col_split, CW * (1 - col_split)],
        )
        t.setStyle(TableStyle([
            ('VALIGN',         (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING',    (0, 0), (-1, -1), 0),
            ('RIGHTPADDING',   (0, 0), (-1, -1), 0),
            ('TOPPADDING',     (0, 0), (-1, -1), 1),
            ('BOTTOMPADDING',  (0, 0), (-1, -1), 1),
        ]))
        return t

    # ── Assemble flowables ─────────────────────────────────────────
    elems = []

    # Header logo (small, centred, clear)
    if os.path.exists(logo_path):
        try:
            logo = RLImage(logo_path)
            lw, lh = logo.drawWidth, logo.drawHeight
            scale = min(20 * mm / lw, 20 * mm / lh)
            logo._restrictSize(lw * scale, lh * scale)
            logo.hAlign = 'CENTER'
            elems.append(logo)
            elems.append(Spacer(1, 1 * mm))
        except Exception:
            pass

    elems.append(Paragraph('MSICT OLMS', s_center_bold))
    elems.append(Paragraph(
        'Military School of Information Technology Online Library Management System',
        s_center,
    ))
    elems.extend(dash())

    # Receipt title
    elems.append(Paragraph(title.upper(), s_center_bold))
    elems.extend(dash())

    # Date
    elems.append(row('DATE:', timezone.now().strftime('%d/%m/%Y  %H:%M')))
    elems.extend(dash())

    # Meta rows
    elems.append(row('RECEIPT NO:', receipt_id))
    elems.append(Spacer(1, 0.5 * mm))
    elems.append(row('NAME:', f"{user.get_full_name()} ({user.username})"))
    elems.extend(dash())

    # Item rows
    for label, value in items:
        elems.append(row(f"{str(label).upper()}:", str(value)))
        elems.append(Spacer(1, 0.5 * mm))
    elems.extend(dash())

    # Payment method
    if payment_method:
        elems.append(row('PAYMENT METHOD:', payment_method.upper()))
        elems.extend(dash())

    # Total / Amount row — prominent double-border style
    if amount_value:
        total_tbl = Table(
            [[Paragraph(f'{amount_label.upper()}:', s_total_l),
              Paragraph(amount_value, s_total_r)]],
            colWidths=[CW * 0.52, CW * 0.48],
        )
        total_tbl.setStyle(TableStyle([
            ('VALIGN',         (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING',    (0, 0), (-1, -1), 0),
            ('RIGHTPADDING',   (0, 0), (-1, -1), 0),
            ('TOPPADDING',     (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING',  (0, 0), (-1, -1), 3),
            ('LINEABOVE',      (0, 0), (-1,  0), 1.0, HexColor('#222222')),
            ('LINEBELOW',      (0, 0), (-1, -1), 1.0, HexColor('#222222')),
        ]))
        elems.append(total_tbl)
        elems.extend(dash())

    # Extra notes
    if extra_notes:
        for note in extra_notes:
            elems.append(Paragraph(note, s_center))
            elems.append(Spacer(1, 0.5 * mm))
        elems.extend(dash())

    # QR code + verify note
    qr_rl = RLImage(qr_buf, width=22 * mm, height=22 * mm)
    qr_tbl = Table(
        [[qr_rl, Paragraph('Scan to verify\nreceipt authenticity', s_center)]],
        colWidths=[25 * mm, CW - 25 * mm],
    )
    qr_tbl.setStyle(TableStyle([
        ('VALIGN',      (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
    ]))
    elems.append(qr_tbl)
    elems.extend(dash())

    # Footer
    elems.append(Paragraph('This is a system-generated receipt. Keep for your records.', s_center))
    elems.append(Spacer(1, 1 * mm))
    elems.append(Paragraph(
        f'&copy; {timezone.now().year} Military School of Information Technology (MSICT). '
        'All rights reserved. Powered by MSICT OLMS.',
        s_foot,
    ))

    # ── Build PDF ──────────────────────────────────────────────────
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A5,
        topMargin=MARGIN_V, bottomMargin=MARGIN_V,
        leftMargin=MARGIN_H, rightMargin=MARGIN_H,
    )
    doc.build(elems, canvasmaker=WatermarkCanvas)
    buf.seek(0)
    resp = HttpResponse(buf, content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="{filename}.pdf"'
    return resp


# ── Bytes variant ───────────────────────────────────────────────────────────
def generate_receipt_bytes(
    *,
    receipt_id, title, user, items, qr_data,
    payment_method='', amount_label='Amount Paid', amount_value=None,
    filename='receipt', extra_notes=None,
):
    """Same as generate_receipt_pdf but returns raw PDF bytes."""
    return generate_receipt_pdf(
        receipt_id=receipt_id, title=title, user=user, items=items, qr_data=qr_data,
        payment_method=payment_method, amount_label=amount_label, amount_value=amount_value,
        filename=filename, extra_notes=extra_notes,
    ).content


# ── Core email sender ───────────────────────────────────────────────────────
def email_receipt(user, subject, body, pdf_bytes, filename='receipt'):
    """Send email to user with the receipt PDF attached. Returns True on success."""
    from django.core.mail import EmailMessage
    from django.conf import settings
    if not getattr(user, 'email', None):
        return False
    try:
        msg = EmailMessage(
            subject=subject,
            body=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[user.email],
        )
        msg.attach(f'{filename}.pdf', pdf_bytes, 'application/pdf')
        msg.send()
        return True
    except Exception:
        return False


# ── Per-payment-type email helpers ──────────────────────────────────────────
def email_fine_receipt(fine):
    """Generate and email a fine (overdue or damage) receipt after any payment."""
    try:
        from circulation.models import DamageReport
        is_damage = DamageReport.objects.filter(damage_fine=fine).exists()
        fine_type_label = 'Damage Fine' if is_damage else 'Overdue Fine'
        receipt_id = f"RCPT-FINE-{fine.pk}-{timezone.now().strftime('%Y%m%d%H%M')}"
        book_title = fine.transaction.copy.book.title if fine.transaction else '—'
        copy_acc = fine.transaction.copy.accession_no if fine.transaction else '—'
        status_str = 'FULLY PAID' if fine.paid else 'PARTIAL PAYMENT'
        items = [
            ('Book', book_title),
            ('Accession No', copy_acc),
            ('Fine Type', fine_type_label),
            ('Total Fine', f"TZS {fine.amount:,.0f}"),
            ('Amount Paid', f"TZS {fine.amount_paid:,.0f}"),
            ('Remaining', f"TZS {fine.remaining_balance:,.0f}"),
            ('Status', status_str),
        ]
        qr_data = (
            f"MSICT-OLMS|FINE|{receipt_id}|{fine.user.username}|"
            f"TZS {fine.amount_paid:,.0f}|{status_str}"
        )
        pdf_bytes = generate_receipt_bytes(
            receipt_id=receipt_id,
            title=f'{fine_type_label} Receipt',
            user=fine.user,
            items=items,
            qr_data=qr_data,
            payment_method=fine.payment_method or '',
            amount_label='Amount Paid',
            amount_value=f"TZS {fine.amount_paid:,.0f}",
            filename=f'fine_receipt_{fine.pk}',
        )
        body = (
            f"Dear {fine.user.get_full_name() or fine.user.username},\n\n"
            f"Please find attached your payment receipt.\n\n"
            f"  Receipt No : {receipt_id}\n"
            f"  Book       : {book_title}\n"
            f"  Fine Type  : {fine_type_label}\n"
            f"  Amount Paid: TZS {fine.amount_paid:,.0f}\n"
            f"  Status     : {status_str}\n\n"
            f"Thank you for your payment.\n\n"
            f"MSICT OLMS\nMilitary School of Information Technology"
        )
        email_receipt(
            fine.user,
            f'MSICT OLMS — {fine_type_label} Receipt ({receipt_id})',
            body, pdf_bytes, f'fine_receipt_{fine.pk}',
        )
    except Exception:
        pass


def email_loss_receipt(report):
    """Generate and email a loss fine receipt after any loss fine payment."""
    try:
        fine = report.loss_fine
        if not fine:
            return
        receipt_id = f"RCPT-LOSS-{report.pk}-{timezone.now().strftime('%Y%m%d%H%M')}"
        book_title = report.transaction.copy.book.title if report.transaction else '—'
        copy_acc = report.transaction.copy.accession_no if report.transaction else '—'
        status_str = 'FULLY PAID' if fine.paid else 'PARTIAL PAYMENT'
        items = [
            ('Loss Report #', f'LR-{report.pk}'),
            ('Book Title', book_title),
            ('Accession No', copy_acc),
            ('Total Fine', f"TZS {fine.amount:,.0f}"),
            ('Amount Paid', f"TZS {fine.amount_paid:,.0f}"),
            ('Remaining', f"TZS {fine.remaining_balance:,.0f}"),
            ('Status', status_str),
        ]
        qr_data = (
            f"MSICT-OLMS|LOSS|{receipt_id}|{fine.user.username}|"
            f"TZS {fine.amount_paid:,.0f}|LR-{report.pk}"
        )
        pdf_bytes = generate_receipt_bytes(
            receipt_id=receipt_id,
            title='Loss Fine Receipt',
            user=fine.user,
            items=items,
            qr_data=qr_data,
            payment_method=fine.payment_method or '',
            amount_label='Amount Paid',
            amount_value=f"TZS {fine.amount_paid:,.0f}",
            filename=f'loss_receipt_{report.pk}',
        )
        body = (
            f"Dear {fine.user.get_full_name() or fine.user.username},\n\n"
            f"Please find attached your payment receipt for Loss Report LR-{report.pk}.\n\n"
            f"  Receipt No : {receipt_id}\n"
            f"  Book       : {book_title}\n"
            f"  Amount Paid: TZS {fine.amount_paid:,.0f}\n"
            f"  Status     : {status_str}\n\n"
            f"Thank you for your payment.\n\n"
            f"MSICT OLMS\nMilitary School of Information Technology"
        )
        email_receipt(
            fine.user,
            f'MSICT OLMS — Loss Fine Receipt ({receipt_id})',
            body, pdf_bytes, f'loss_receipt_{report.pk}',
        )
    except Exception:
        pass


def email_softcopy_receipt(prepaid_tx):
    """Generate and email a softcopy link fee receipt after payment."""
    try:
        from circulation.models import BorrowingTransaction
        copy = prepaid_tx.copy
        book_title = copy.book.title if copy and copy.book else '—'
        receipt_id = f"RCPT-LINK-{prepaid_tx.pk}-{prepaid_tx.created_at.strftime('%Y%m%d%H%M')}"
        items = [
            ('Transaction ID', prepaid_tx.transaction_id or f'TXN-{prepaid_tx.pk}'),
            ('Book Title', book_title),
            ('Status', prepaid_tx.get_status_display()),
        ]
        bt = BorrowingTransaction.objects.filter(
            user=prepaid_tx.user, copy=copy,
        ).order_by('-id').first()
        if bt:
            items.append(('Due Date', bt.due_date.strftime('%d %b %Y, %H:%M')))
        qr_data = (
            f"MSICT-OLMS|LINK|{receipt_id}|{prepaid_tx.user.username}|"
            f"TZS {prepaid_tx.amount:,.0f}|{book_title}"
        )
        pdf_bytes = generate_receipt_bytes(
            receipt_id=receipt_id,
            title='Softcopy Link Fee Receipt',
            user=prepaid_tx.user,
            items=items,
            qr_data=qr_data,
            payment_method=prepaid_tx.payment_method or '',
            amount_label='Amount Paid',
            amount_value=f"TZS {float(prepaid_tx.amount):,.0f}",
            filename=f'softcopy_receipt_{prepaid_tx.pk}',
            extra_notes=[
                'Digital access is valid for 7 days from issue date.',
                'Sharing or misuse of digital content may lead to disciplinary action.',
            ],
        )
        body = (
            f"Dear {prepaid_tx.user.get_full_name() or prepaid_tx.user.username},\n\n"
            f"Please find attached your payment receipt for the softcopy link fee.\n\n"
            f"  Receipt No : {receipt_id}\n"
            f"  Book       : {book_title}\n"
            f"  Amount Paid: TZS {float(prepaid_tx.amount):,.0f}\n\n"
            f"Your digital access link has been sent in a separate notification.\n\n"
            f"MSICT OLMS\nMilitary School of Information Technology"
        )
        email_receipt(
            prepaid_tx.user,
            f'MSICT OLMS — Softcopy Link Fee Receipt ({receipt_id})',
            body, pdf_bytes, f'softcopy_receipt_{prepaid_tx.pk}',
        )
    except Exception:
        pass


def email_guest_receipt(session, is_renewal=False):
    """Generate and email a guest session receipt after payment."""
    try:
        from datetime import timedelta
        title = 'Guest Session Renewal Receipt' if is_renewal else 'Guest Session Receipt'
        receipt_id = f"RCPT-GUEST-{session.pk}-{timezone.now().strftime('%Y%m%d%H%M')}"
        paid_hours = float(session.paid_hours)
        amount_paid = float(session.amount_paid)
        hourly_rate = amount_paid / paid_hours if paid_hours else 0
        expiry_dt = session.sign_in_time + timedelta(hours=paid_hours)
        items = [
            ('Session #', f'GS-{session.pk}'),
            ('Duration', f"{paid_hours:.0f} hour(s)"),
            ('Hourly Rate', f"TZS {hourly_rate:,.0f}"),
            ('Session Start', session.sign_in_time.strftime('%d %b %Y %H:%M')),
            ('Expires At', expiry_dt.strftime('%d %b %Y %H:%M')),
        ]
        qr_data = (
            f"MSICT-OLMS|GUEST|{receipt_id}|{session.user.username}|"
            f"TZS {amount_paid:,.0f}|Session #{session.pk}"
        )
        pdf_bytes = generate_receipt_bytes(
            receipt_id=receipt_id,
            title=title,
            user=session.user,
            items=items,
            qr_data=qr_data,
            payment_method=session.payment_method or '',
            amount_label='Total Paid',
            amount_value=f"TZS {amount_paid:,.0f}",
            filename=f'guest_receipt_{session.pk}',
            extra_notes=[
                'Payment is non-refundable. Unused time is not carried over.',
                f'Session status: {session.get_status_display()}',
            ],
        )
        expiry_str = expiry_dt.strftime('%d %b %Y %H:%M')
        body = (
            f"Dear {session.user.get_full_name() or session.user.username},\n\n"
            f"Please find attached your receipt for the guest library session.\n\n"
            f"  Receipt No : {receipt_id}\n"
            f"  Duration   : {paid_hours:.0f} hour(s)\n"
            f"  Amount Paid: TZS {amount_paid:,.0f}\n"
            f"  Expires At : {expiry_str}\n\n"
            f"Enjoy your library access!\n\n"
            f"MSICT OLMS\nMilitary School of Information Technology"
        )
        email_receipt(
            session.user,
            f'MSICT OLMS — {title} ({receipt_id})',
            body, pdf_bytes, f'guest_receipt_{session.pk}',
        )
    except Exception:
        pass
