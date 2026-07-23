# ============================================================
# accounts/utils.py — Kazi za Msaidizi (Helper Functions)
# Inashughulikia: SMS, barua pepe, OTP, kadi za maktaba, IP
# ============================================================

import io
import base64
import random
import string
import requests
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone
from datetime import timedelta


def get_client_ip(request):
    """Pata anwani ya IP ya mtumiaji kutoka kwenye request"""
    x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded:
        return x_forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '127.0.0.1')


def generate_otp():
    """Tengeneza nambari ya siri ya 6 tarakimu (OTP)"""
    return ''.join(random.choices(string.digits, k=6))


def create_otp_for_user(user):
    """Unda OTP mpya kwa mtumiaji na izima zote zilizopo"""
    from .models import OTPRecord
    OTPRecord.objects.filter(user=user, used=False).update(used=True)
    expiry = timezone.now() + timedelta(minutes=getattr(settings, 'OTP_EXPIRY_MINUTES', 10))
    return OTPRecord.objects.create(user=user, otp_code=generate_otp(), expires_at=expiry)


def format_phone_for_sms(phone):
    """Badilisha nambari ya simu ya Tanzania kuwa muundo wa kimataifa kwa BEEM API"""
    phone = str(phone).strip().replace(' ', '').replace('-', '')
    
    # Kama tayari ina +, rudisha kama ilivyo
    if phone.startswith('+'):
        return phone
    
    # Ondoa 0 ya mwanzo na ongeza nambari ya nchi ya Tanzania (+255)
    if phone.startswith('0'):
        return '+255' + phone[1:]
    
    # Kama hakuna nambari ya nchi na haianzi na 0, ongeza +255
    if not phone.startswith('255'):
        return '+255' + phone
    
    # Ina 255 lakini haina +
    return '+' + phone


def send_sms(phone, message):
    """Tuma SMS kwa kutumia BEEM Africa API"""
    import logging
    logger = logging.getLogger(__name__)
    
    url = settings.BEEM_SMS_URL
    sender = settings.BEEM_SENDER_NAME
    api_key = settings.BEEM_API_KEY
    secret_key = settings.BEEM_SECRET_KEY
    
    # Badilisha nambari ya simu
    formatted_phone = format_phone_for_sms(phone)
    
    logger.info(f"SMS Request: to={formatted_phone} (original: {phone}), sender={sender}, api_key={api_key[:8]}...")
    
    payload = {
        "source_addr": sender,
        "schedule_time": "",
        "encoding": 0,
        "message": message,
        "recipients": [{"recipient_id": "1", "dest_addr": formatted_phone}],
    }
    try:
        resp = requests.post(
            url,
            json=payload,
            auth=(api_key, secret_key),
            timeout=10,
        )
        logger.info(f"SMS Response: status={resp.status_code}, body={resp.text[:200]}")
        
        if resp.status_code == 200:
            try:
                data = resp.json()
                if data.get('successful', False):
                    return True
                else:
                    logger.error(f"BEEM API error: {data}")
                    return False
            except:
                return True
        else:
            logger.error(f"SMS failed: HTTP {resp.status_code} - {resp.text[:200]}")
            return False
    except Exception as e:
        logger.error(f"SMS exception: {str(e)}")
        return False


def send_email_notification(to_email, subject, body):
    """Tuma barua pepe kwa kutumia Django mail"""
    import logging
    logger = logging.getLogger(__name__)
    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [to_email], fail_silently=False)
        logger.info(f"Email sent to {to_email}: {subject}")
        return True
    except Exception as e:
        logger.error(f"Email failed to {to_email} [{subject}]: {e}")
        return False


def create_notification(user, message, channel, priority='normal', is_security_alert=False, message_type='approval'):
    """Unda rekodi ya arifa kwenye database (bila kutuma)"""
    from circulation.models import Notification
    return Notification.objects.create(user=user, message=message, channel=channel, priority=priority, is_security_alert=is_security_alert, message_type=message_type)


def notify_user(user, message, channel, subject=None, priority='normal', is_security_alert=False, message_type='approval'):
    """Tuma arifa kwa SMS au barua pepe NA rekodi status ya kumewasilika/kushindwa"""
    import logging
    from django.utils import timezone as tz
    from circulation.models import Notification
    logger = logging.getLogger(__name__)
    ok = False
    if channel == 'sms':
        ok = send_sms(user.phone, message)
    elif channel == 'email':
        ok = send_email_notification(user.email, subject or 'MSICT OLMS Notification', message)
    else:
        logger.warning(f"notify_user: unknown channel '{channel}'")
    return Notification.objects.create(
        user=user,
        message=message,
        channel=channel,
        priority=priority,
        is_security_alert=is_security_alert,
        message_type=message_type,
        status='sent' if ok else 'failed',
        sent_at=tz.now() if ok else None,
    )


def log_credentials_fallback(user, password, login_url):
    """Andika credentials kwenye file log kama SMS/email zote zimeshindwa"""
    import logging
    import os
    from django.conf import settings
    logger = logging.getLogger('accounts.credentials')
    cred_log = os.path.join(settings.BASE_DIR, 'guest_credentials.log')
    from django.utils import timezone as tz
    entry = (
        f"[{tz.now().isoformat()}] "
        f"username={user.username}, name={user.get_full_name()}, "
        f"phone={user.phone}, email={user.email}, "
        f"password={password}, login_url={login_url}\n"
    )
    try:
        with open(cred_log, 'a') as f:
            f.write(entry)
    except Exception as e:
        logger.error(f"Failed to write credentials fallback log: {e}")
    logger.info(f"Credentials logged to fallback file for {user.username}")


def log_audit(user, action, request=None):
    """Rekodi kitendo kwenye audit log (nani alifanya nini na lini)"""
    from .models import AuditLog
    ip = get_client_ip(request) if request else None
    AuditLog.objects.create(user=user, action=action, ip_address=ip)


def generate_virtual_card(user):
    """Tengeneza kadi ya maktaba ya kidijitali na QR code"""
    import qrcode
    from .models import VirtualCard

    card, created = VirtualCard.objects.get_or_create(user=user)

    # Tumia user.card_no kama imewekwa; vinginevyo tengeneza mpya na usawazisha
    if user.card_no:
        card.card_no = user.card_no
    elif not card.card_no:
        card.card_no = VirtualCard.generate_card_no()
        user.card_no = card.card_no
        user.save(update_fields=['card_no'])

    qr_data = f"MSICT-OLMS|{user.army_no}|{user.get_full_name()}|{user.role}|{card.card_no}"
    qr = qrcode.QRCode(version=1, box_size=6, border=2)
    qr.add_data(qr_data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    qr_base64 = base64.b64encode(buf.getvalue()).decode('utf-8')

    card.qr_code = qr_base64
    card.barcode = user.army_no.replace(' ', '')
    card.save()
    return card


def generate_virtual_card_pdf(user):
    """Tengeneza PDF ya kadi ya maktaba (kadi 2 kwenye ukurasa mmoja wa A4)"""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    from reportlab.lib import colors
    from reportlab.lib.utils import ImageReader
    import qrcode

    # Hakikisha card_no inaopo
    card = generate_virtual_card(user)

    buf = io.BytesIO()

    # Use the card dimensions as the PDF page size so the downloaded PDF matches
    # the physical card size instead of a full A4 page. This makes viewing/printing
    # the card match the on-screen virtual card layout.
    card_w = 85 * mm
    card_h = 54 * mm
    c = canvas.Canvas(buf, pagesize=(card_w, card_h))
    w, h = card_w, card_h

    # Draw background rounded card covering the whole page
    padding = 2 * mm
    x = 0
    y = 0
    radius = 4 * mm
    c.setFillColor(colors.HexColor('#1e40af'))
    c.roundRect(x, y, w, h, radius, fill=1, stroke=0)

    # Header: library name
    c.setFillColor(colors.white)
    c.setFont('Helvetica-Bold', 12)
    c.drawString(x + 6 * mm, h - 10 * mm, "MSICT LIBRARY")

    c.setFont('Helvetica', 7.5)
    c.drawString(x + 6 * mm, h - 15 * mm, "Military School of Information & Technology")

    # Member name and details (stacked with comfortable spacing)
    name_y = h - 24 * mm
    c.setFont('Helvetica-Bold', 10)
    c.drawString(x + 6 * mm, name_y, user.get_full_name())

    c.setFont('Helvetica', 8)
    spacing = 4.5 * mm
    cur = name_y - spacing

    if user.rank:
        c.drawString(x + 6 * mm, cur, f"Rank: {user.rank.rank_name}")
        cur -= spacing

    c.drawString(x + 6 * mm, cur, f"Army No: {user.army_no}")
    cur -= spacing

    c.drawString(x + 6 * mm, cur, f"Role: {user.get_role_display()}")
    cur -= spacing

    if user.member_type:
        c.drawString(x + 6 * mm, cur, f"Type: {user.get_member_type_display()}")
        cur -= spacing

    if user.registration_no:
        c.drawString(x + 6 * mm, cur, f"Reg No: {user.registration_no}")
        cur -= spacing

    # Card number in gold at the bottom-left
    c.setFillColor(colors.HexColor('#FFD700'))
    c.setFont('Helvetica-Bold', 8)
    c.drawString(x + 6 * mm, 6 * mm, f"Card No: {card.card_no or 'N/A'}")

    # QR code at bottom-right (contrasting background for better scanning)
    qr_data = f"MSICT-OLMS|{user.army_no}|{user.get_full_name()}|{card.card_no or ''}"
    qr = qrcode.QRCode(version=1, box_size=4, border=1)
    qr.add_data(qr_data)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="white", back_color="#003366")
    qr_buf = io.BytesIO()
    qr_img.save(qr_buf, format='PNG')
    qr_buf.seek(0)
    qr_reader = ImageReader(qr_buf)
    qr_size = 26 * mm
    c.drawImage(qr_reader, w - qr_size - 6 * mm, 6 * mm, qr_size, qr_size)

    c.save()
    buf.seek(0)
    return buf


def is_password_reused(user, raw_password):
    """Angalia kama nywila imetumika awali (historia ya PASSWORD_HISTORY_DEPTH za mwisho)"""
    from .models import PasswordHistory
    from django.contrib.auth.hashers import check_password
    from django.conf import settings

    depth = getattr(settings, 'PASSWORD_HISTORY_DEPTH', 5)

    # Pata nywila za mwisho za mtumiaji huyu kulingana na depth
    recent_passwords = PasswordHistory.objects.filter(
        user=user
    ).order_by('-created_at')[:depth]
    
    for ph in recent_passwords:
        if check_password(raw_password, ph.password_hash):
            return True
    return False


def add_password_to_history(user, password_hash):
    """Hifadhi nywila kwenye historia, ukiweka zile PASSWORD_HISTORY_DEPTH za mwisho tu.
    
    MUHIMU: pita password_hash ya ZAMANI (kabla ya kubadilisha), si ya mpya.
    Mfano wa matumizi sahihi:
        old_hash = user.password               # hifadhi ya zamani
        user.set_password(new_pw)
        user.save(...)
        add_password_to_history(user, old_hash) # rekodi ya zamani
    """
    from .models import PasswordHistory
    from django.conf import settings
    
    depth = getattr(settings, 'PASSWORD_HISTORY_DEPTH', 5)
    
    # Unda rekodi mpya ya historia ya nywila
    PasswordHistory.objects.create(
        user=user,
        password_hash=password_hash
    )
    
    # Hifadhi zile `depth` za mwisho tu — futa za zamani zaidi
    old_entries = PasswordHistory.objects.filter(
        user=user
    ).order_by('-created_at')[depth:]
    
    if old_entries:
        old_entries.delete()


def mark_badge_viewed(user, badge_key):
    """Record that user has viewed a badge page — resets the sidebar count to 0."""
    from accounts.models import BadgeViewed
    BadgeViewed.objects.update_or_create(
        user=user, badge_key=badge_key,
        defaults={'last_viewed_at': timezone.now()},
    )


def get_badge_last_viewed(user, badge_key):
    """Return the last_viewed_at timestamp for a badge, or None if never viewed."""
    from accounts.models import BadgeViewed
    try:
        return BadgeViewed.objects.get(user=user, badge_key=badge_key).last_viewed_at
    except BadgeViewed.DoesNotExist:
        return None
