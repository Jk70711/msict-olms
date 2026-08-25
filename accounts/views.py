# ============================================================
# accounts/views.py
# Views zote za watumiaji: kuingia, OTP, wasifu, kadi, usimamizi
# wa watumiaji, mipangilio ya mfumo, na mandhari ya mfumo.
#
# Decorators zinazotumika:
#   @login_required       — lazima mtumiaji aingie kwanza
#   @librarian_required   — lazima librarian au admin
#   @admin_required       — lazima admin peke yake
# ============================================================

import re
import logging
from decimal import Decimal
from datetime import datetime, timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.db.models import Sum, Max, Count, Q
from django.core.paginator import Paginator
from django.views.decorators.http import require_POST
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from .models import OLMSUser, LoginAttempt, OTPRecord, VirtualCard, AuditLog, SystemPreference, BlockedIP, GuestSession, BulkMessage, BulkMessageRecipient
from .utils import get_client_ip, notify_user, send_sms, send_email_notification, log_audit, generate_virtual_card, generate_virtual_card_pdf, create_otp_for_user, log_credentials_fallback, mark_badge_viewed
from .forms import LoginForm
from .security_utils import safe_redirect, build_content_disposition
from .models import Rank

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Msaidizi wa WebSocket — Tuma arifa za status ya akaunti kwa watumiaji
# ----------------------------------------------------------------------
def send_account_status_update(user, action):
    """Tuma arifa ya WebSocket kwa watumiaji wote kuhusu mabadiliko ya status ya akaunti"""
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        'librarians',
        {
            'type': 'account_status_update',
            'user_id': user.id,
            'username': user.username,
            'full_name': user.get_full_name(),
            'status': user.registration_status,
            'action': action,
        }
    )


# ----------------------------------------------------------------------
# View ya Terms and Conditions — Ukurasa wa Masharti na Mataruzisho
# ----------------------------------------------------------------------
def terms_and_conditions_view(request):
    """Terms and Conditions page for MSICT OLMS"""
    return render(request, 'pages/terms_and_conditions.html')


# ----------------------------------------------------------------------
# View ya User Manual — Mwongozo wa Matumizi kwa Watumiaji
# ----------------------------------------------------------------------
def user_manual_view(request):
    """User Manual page with dynamic system preferences"""
    from accounts.models import SystemPreference
    from django.contrib.humanize.templatetags.humanize import intcomma
    
    # Fetch current system preferences
    loan_period_days = int(SystemPreference.get('LOAN_PERIOD_DAYS', 7))
    fine_per_day = int(SystemPreference.get('FINE_PER_DAY', 500))
    max_renewals = int(SystemPreference.get('MAX_RENEWALS', 2))
    otp_validity_minutes = int(SystemPreference.get('OTP_VALIDITY_MINUTES', 10))
    password_expiry_days = int(SystemPreference.get('PASSWORD_EXPIRY_DAYS', 90))
    max_borrow_limit = int(SystemPreference.get('MAX_COPIES_PER_BORROW', 3))
    renewal_window_days = int(SystemPreference.get('RENEWAL_WINDOW_DAYS', 2))
    reservation_expiry_days = int(SystemPreference.get('RESERVATION_EXPIRY_DAYS', 7))
    max_login_attempts = int(SystemPreference.get('MAX_LOGIN_ATTEMPTS', 6))
    suspend_attempts = int(SystemPreference.get('SUSPEND_ATTEMPTS', 3))
    suspend_duration_minutes = int(SystemPreference.get('SUSPEND_DURATION_MINUTES', 10))
    session_timeout_minutes = int(SystemPreference.get('SESSION_TIMEOUT_MINUTES', 30))
    guest_max_hours = int(SystemPreference.get('GUEST_MAX_HOURS', 12))
    guest_hourly_rate = float(SystemPreference.get('GUEST_HOURLY_RATE', 500))
    
    return render(request, 'pages/user_manual.html', {
        'loan_period_days': loan_period_days,
        'fine_per_day': fine_per_day,
        'max_renewals': max_renewals,
        'otp_validity_minutes': otp_validity_minutes,
        'password_expiry_days': password_expiry_days,
        'max_borrow_limit': max_borrow_limit,
        'renewal_window_days': renewal_window_days,
        'reservation_expiry_days': reservation_expiry_days,
        'max_login_attempts': max_login_attempts,
        'suspend_attempts': suspend_attempts,
        'suspend_duration_minutes': suspend_duration_minutes,
        'session_timeout_minutes': session_timeout_minutes,
        'guest_max_hours': guest_max_hours,
        'guest_hourly_rate': guest_hourly_rate,
        'intcomma': intcomma,
    })


# ----------------------------------------------------------------------
# View ya Usajili wa Umma — Self-registration kwa wanachama
# ----------------------------------------------------------------------
def public_register_view(request):
    """Usajili wa umma kwa wanachama wa maktaba (wanafunzi, walimu, wafanyakazi)"""
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        # Extract form data
        army_no = request.POST.get('army_no', '').strip()
        first_name = request.POST.get('first_name', '').strip()
        middle_name = request.POST.get('middle_name', '').strip()
        surname = request.POST.get('surname', '').strip()
        email = request.POST.get('email', '').strip()
        phone = request.POST.get('phone', '').strip()
        member_type = request.POST.get('member_type', '').strip()
        registration_no = request.POST.get('registration_no', '').strip() or None
        rank_name = request.POST.get('rank', '').strip() or None

        # Validation
        if not re.match(r'^(MTM|MT|PW|P)\s?\d+$', army_no):
            messages.error(request, 'Army number must start with MT, MTM, P, or PW followed by digits (e.g. MT 134513, MTM 456, P 789, PW 101).')
            return render(request, 'accounts/register.html', {'rank_list': Rank.RANK_LIST})

        if OLMSUser.objects.filter(army_no=army_no).exists():
            messages.error(request, 'Army number already registered.')
            return render(request, 'accounts/register.html', {'rank_list': Rank.RANK_LIST})

        if OLMSUser.objects.filter(email=email).exists():
            messages.error(request, 'Email already registered.')
            return render(request, 'accounts/register.html', {'rank_list': Rank.RANK_LIST})

        if not re.match(r'^0\d{9}$', phone):
            messages.error(request, 'Phone number must be exactly 10 digits starting with 0 (e.g. 0712345678).')
            return render(request, 'accounts/register.html', {'rank_list': Rank.RANK_LIST})

        # Registration number only required for students
        if member_type == 'student' and not registration_no:
            messages.error(request, 'Registration number is required for students.')
            return render(request, 'accounts/register.html', {'rank_list': Rank.RANK_LIST})

        if member_type != 'student':
            registration_no = None

        # Generate username and initial password
        username = OLMSUser.generate_username('member', member_type, surname, registration_no, first_name, middle_name)
        initial_password = OLMSUser.generate_initial_password(army_no)

        # Handle duplicate username by adding random variations
        if OLMSUser.objects.filter(username=username).exists():
            import random
            import string
            while OLMSUser.objects.filter(username=username).exists():
                suffix = ''.join(random.choices(string.ascii_lowercase, k=2))
                username = f"{username}{suffix}"

        rank_obj = Rank.objects.filter(rank_name=rank_name).first() if rank_name else None

        user = OLMSUser.objects.create_user(
            username=username,
            password=initial_password,
            army_no=army_no,
            first_name=first_name,
            middle_name=middle_name,
            surname=surname,
            email=email,
            phone=phone,
            role='member',
            member_type=member_type,
            registration_no=registration_no,
            rank=rank_obj,
            last_password_change=timezone.now(),
            registration_status='pending',
            is_active=False,
        )

        log_audit(None, f"Self-registration submitted by {user.get_full_name()} (Army No: {army_no})", request)

        login_url = request.build_absolute_uri('/login/')
        subject = "MSICT OLMS — Registration Request Received"
        body = (
            f"Dear {user.get_full_name()},\n\n"
            f"Thank you for registering with the MSICT Library (OLMS).\n\n"
            f"Your registration request has been received and is now pending librarian review.\n\n"
            f"  Full Name    : {user.get_full_name()}\n"
            f"  Army No      : {army_no}\n"
            f"  Member Type  : {dict(OLMSUser.MEMBER_TYPE_CHOICES).get(member_type, member_type).title()}\n"
            f"  Email        : {email}\n"
            f"  Phone        : {phone}\n\n"
            f"You will receive a separate SMS and email with your login credentials once approved.\n\n"
            f"Login URL : {login_url}\n\n"
            f"Regards,\nMSICT Library Administration"
        )
        sms_body = (
            f"MSICT OLMS: Reg received, {user.get_full_name()}. Pending approval. "
            f"Credentials sent via SMS/email after approval."
        )

        sms_ok = notify_user(user, sms_body, 'sms', priority='high')
        email_ok = notify_user(user, body, 'email', subject=subject)

        if sms_ok.status == 'sent' and email_ok.status == 'sent':
            messages.success(request, 'Registration submitted successfully! A confirmation has been sent to your phone and email. You will be notified once approved.')
        elif sms_ok.status == 'sent':
            messages.success(request, 'Registration submitted! SMS confirmation sent. Email delivery failed.')
        elif email_ok.status == 'sent':
            messages.success(request, 'Registration submitted! Email confirmation sent. SMS delivery failed.')
        else:
            messages.success(request, 'Registration submitted! However, we could not send confirmation via SMS or email. Please check back later.')
        return redirect('login')

    return render(request, 'accounts/register.html', {'rank_list': Rank.RANK_LIST})


def guest_register_view(request):
    """Public quick registration for walk-in guest accounts."""
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        first_name = request.POST.get('first_name', '').strip()
        middle_name = request.POST.get('middle_name', '').strip()
        surname = request.POST.get('surname', '').strip()
        email = request.POST.get('email', '').strip().lower()
        phone = request.POST.get('phone', '').strip()
        password = request.POST.get('password', '')
        confirm_password = request.POST.get('confirm_password', '')

        if not first_name or not surname:
            messages.error(request, 'First name and surname are required.')
            return render(request, 'accounts/guest_register.html')

        if not email or not phone:
            messages.error(request, 'Email and phone are required for guest access.')
            return render(request, 'accounts/guest_register.html')

        if not re.match(r'^0\d{9}$', phone):
            messages.error(request, 'Phone number must be exactly 10 digits starting with 0 (e.g. 0712345678).')
            return render(request, 'accounts/guest_register.html')

        if OLMSUser.objects.filter(email=email).exists():
            messages.error(request, 'Email already registered. Please sign in.')
            return redirect('login')

        if password != confirm_password:
            messages.error(request, 'Password and confirm password do not match.')
            return render(request, 'accounts/guest_register.html')

        complexity_errors = []
        if len(password) < 8:
            complexity_errors.append('at least 8 characters')
        if not re.search(r'[A-Z]', password):
            complexity_errors.append('an uppercase letter')
        if not re.search(r'[a-z]', password):
            complexity_errors.append('a lowercase letter')
        if not re.search(r'\d', password):
            complexity_errors.append('a number')
        if not re.search(r'[^A-Za-z0-9]', password):
            complexity_errors.append('a special character')

        if complexity_errors:
            messages.error(request, f"Password must include {', '.join(complexity_errors)}.")
            return render(request, 'accounts/guest_register.html')

        pw_err = _validate_password(password)
        if pw_err:
            messages.error(request, pw_err)
            return render(request, 'accounts/guest_register.html')

        username = email
        if OLMSUser.objects.filter(username=username).exists():
            username = phone
        if OLMSUser.objects.filter(username=username).exists():
            username = f"guest_{timezone.now().strftime('%y%m%d%H%M%S')}"

        user = OLMSUser.objects.create_user(
            username=username,
            password=password,
            first_name=first_name,
            middle_name=middle_name,
            surname=surname,
            email=email,
            phone=phone,
            role='guest',
            is_guest=True,
            last_password_change=timezone.now(),
        )

        login_url = request.build_absolute_uri('/login/')
        subject = 'MSICT OLMS — Guest Account Created'
        body = (
            f"Dear {user.get_full_name()},\n\n"
            f"Your guest account for MSICT Library (OLMS) has been created successfully.\n\n"
            f"  Full Name : {user.get_full_name()}\n"
            f"  Email     : {user.email}\n"
            f"  Phone     : {user.phone}\n"
            f"  Username  : {user.username}\n"
            f"  Password  : {password}\n"
            f"  Login URL : {login_url}\n\n"
            f"Use this account for walk-in guest sessions only. Keep your credentials confidential.\n"
            f"Pay session fees at the circulation desk before starting a session.\n\n"
            f"Regards,\nMSICT Library Administration"
        )
        sms_body = (
            f"MSICT OLMS: Guest acct created. "
            f"User:{user.username} Pwd:{password}. "
            f"Login at /login/ Check email for details."
        )
        sms_notif = notify_user(user, sms_body, 'sms', priority='high')
        email_notif = notify_user(user, body, 'email', subject=subject)

        log_audit(None, f"Guest account created: {user.username}", request)

        delivery_warnings = []
        if sms_notif and sms_notif.status != 'sent':
            delivery_warnings.append('SMS')
            logger.warning(f"Guest SMS failed for {user.username} (phone={user.phone})")
        if email_notif and email_notif.status != 'sent':
            delivery_warnings.append('email')
            logger.warning(f"Guest email failed for {user.username} (email={user.email})")

        if delivery_warnings:
            log_credentials_fallback(user, password, login_url)
            warn_msg = (
                f"Account created, but {' and '.join(delivery_warnings)} delivery failed. "
                f"Please note your username: {user.username}. "
                f"Use the password you set during registration to sign in."
            )
            messages.warning(request, warn_msg)
        else:
            messages.success(request, 'Guest account created successfully. Credentials sent via SMS and email. Please sign in to start your session.')
        return redirect('login')

    return render(request, 'accounts/guest_register.html')


# ----------------------------------------------------------------------
# Password helper — runs the FULL configured AUTH_PASSWORD_VALIDATORS list
# (length, common-password, user-similarity, numeric-only) and returns the
# first validation error message, or None if the password is acceptable.
# ----------------------------------------------------------------------
def _validate_password(password, user=None):
    """Thibitisha nguvu ya nywila"""
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError
    try:
        validate_password(password, user=user)
    except ValidationError as exc:
        return ' '.join(exc.messages)
    return None


# ----------------------------------------------------------------------
# View ya Kuingia — Inashughulikia uthibitishaji wa mtumiaji
# Inalinda kwa: kuzuia baada ya majaribio 3 mabaya kwa dakika 10
# Inakumbuka vikao kwa "remember me"
# ----------------------------------------------------------------------
def login_view(request):
    """Ukurasa wa kuingia kwa watumiaji"""
    if request.user.is_authenticated:
        return redirect('dashboard')
    if request.method == 'POST':
        form = LoginForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data['username']
            identifier = username
            password = form.cleaned_data['password']
            ip = get_client_ip(request)
            
            try:
                db_user = OLMSUser.objects.get(username=username)
            except OLMSUser.DoesNotExist:
                db_user = OLMSUser.objects.filter(Q(email=identifier) | Q(phone=identifier)).first()
                if db_user:
                    username = db_user.username

            # ── Gate check before attempting authentication ─────────────
            if db_user:
                # Pending/cancelled checks apply to members only — admin & librarian
                # are created directly by staff and never go through the approval queue.
                if db_user.role == 'member':
                    if db_user.registration_status == 'pending':
                        messages.error(request, 'Your account is pending librarian approval. You will receive a notification once approved.')
                        return render(request, 'accounts/login.html', {'form': form})

                    if db_user.registration_status == 'cancelled':
                        messages.error(request, f'Your account registration was cancelled. Reason: {db_user.cancelled_reason or "Contact library administration."}')
                        return render(request, 'accounts/login.html', {'form': form})

                # Locked account check (admin action or 6 failed attempts)
                if not db_user.is_active:
                    messages.error(request, 'Account is locked. Contact admin to restore access.')
                    return render(request, 'accounts/login.html', {'form': form})

                # Second login restriction: user must change password via forgot password if they haven't changed after first login
                # Guests are exempt — librarians set their passwords explicitly
                if db_user.last_login and not db_user.password_changed_after_first_login and not db_user.is_guest:
                    messages.error(request, 'You must change your password via "Forgot Password" before your second login.')
                    return redirect('forgot_password')

                # Suspension gate-check: dynamic thresholds from preferences
                _lock_at = int(SystemPreference.get('MAX_LOGIN_ATTEMPTS', 6) or 6)
                _suspend_at = int(SystemPreference.get('SUSPEND_ATTEMPTS', 3) or 3)
                _suspend_duration = int(SystemPreference.get('SUSPEND_DURATION_MINUTES', 10) or 10)
                if db_user.failed_attempts == _suspend_at:
                    last_fail = LoginAttempt.objects.filter(
                        username=username, status='failed'
                    ).order_by('-timestamp').first()
                    if last_fail:
                        elapsed = (timezone.now() - last_fail.timestamp).total_seconds()
                        if elapsed < _suspend_duration * 60:
                            remaining_min = max(1, int((_suspend_duration * 60 - elapsed) / 60) + 1)
                            messages.error(request, f'Account suspended. Please try again in ~{remaining_min} minute(s).')
                            return render(request, 'accounts/login.html', {'form': form})
                        # Suspension expired → group 2 starts, allow attempt

            user = authenticate(request, username=username, password=password)
            
            if user is not None:
                login(request, user)
                # Handle remember me option
                remember_me = request.POST.get('remember_me')
                if remember_me:
                    # Set session to expire in 30 days
                    request.session.set_expiry(60 * 60 * 24 * 30)
                    request.session['remember_me'] = True
                else:
                    # Session idle-timeout controlled by SessionTimeoutMiddleware
                    # using the SESSION_TIMEOUT_MINUTES system preference
                    request.session.pop('remember_me', None)
                    timeout_min = int(SystemPreference.get('SESSION_TIMEOUT_MINUTES', 30) or 30)
                    request.session.set_expiry(timeout_min * 60)
                if user.failed_attempts > 0:
                    user.failed_attempts = 0
                    user.save(update_fields=['failed_attempts'])
                LoginAttempt.objects.create(username=username, ip_address=ip, status='success', attempt_count=0)
                request.session.save()
                from .models import UserSession
                from django.contrib.sessions.models import Session as DjangoSession
                # Invalidate ALL previous sessions for this user (single-session enforcement)
                old_keys = list(UserSession.objects.filter(user=user).values_list('session_id', flat=True))
                if old_keys:
                    DjangoSession.objects.filter(session_key__in=old_keys).delete()
                UserSession.objects.filter(user=user).delete()
                # Register the new session
                UserSession.objects.create(session_id=request.session.session_key, user=user, ip_address=ip)
                log_audit(user, f'Logged in from {ip} — previous sessions invalidated', request)
                
                if user.password_is_old():
                    _expiry_days = int(SystemPreference.get('PASSWORD_EXPIRY_DAYS', 90) or 90)
                    messages.warning(request, f'Your password is over {_expiry_days} days old. Please change it now.')
                
                return redirect('dashboard')
            else:
                if db_user:
                    db_user.failed_attempts += 1
                    db_user.save(update_fields=['failed_attempts'])
                    total = db_user.failed_attempts
                    now = timezone.now()

                    # Always log each failure for audit trail
                    LoginAttempt.objects.create(
                        username=username, ip_address=ip, status='failed',
                        attempt_count=1, password_chars=len(password)
                    )

                    admins = OLMSUser.objects.filter(role='admin', is_active=True)
                    admin_phones = ', '.join(a.phone for a in admins if a.phone)

                    # Read dynamic thresholds from system preferences
                    auto_lockout = SystemPreference.get('ENABLE_AUTO_LOCKOUT', '1') != '0'
                    lock_at = int(SystemPreference.get('MAX_LOGIN_ATTEMPTS', 6) or 6)
                    suspend_at = int(SystemPreference.get('SUSPEND_ATTEMPTS', 3) or 3)
                    suspend_duration = int(SystemPreference.get('SUSPEND_DURATION_MINUTES', 10) or 10)

                    if not auto_lockout:
                        # Lockout disabled — just warn the user
                        messages.error(request, 'Invalid credentials.')

                    # ── PERMANENT LOCK at lock_at failures ────────────────────
                    elif total >= lock_at:
                        db_user.is_active = False
                        db_user.save(update_fields=['is_active'])
                        lock_msg_user = (
                            f"MSICT OLMS SECURITY ALERT: Your account '{username}' has been "
                            f"permanently LOCKED after {lock_at} consecutive failed login attempts from IP {ip}. "
                            f"Contact admin to restore access. Admin phone(s): {admin_phones}."
                        )
                        lock_msg_admin = (
                            f"SECURITY ALERT: Account '{username}' permanently LOCKED after "
                            f"{lock_at} failed attempts from IP {ip} at {now.strftime('%Y-%m-%d %H:%M:%S')}."
                        )
                        notify_user(db_user, lock_msg_user, 'sms', priority='high', is_security_alert=True, message_type='account_lock')
                        notify_user(db_user, lock_msg_user, 'email', subject='MSICT OLMS – Account Locked', priority='high', is_security_alert=True, message_type='account_lock')
                        for admin in admins:
                            notify_user(admin, lock_msg_admin, 'sms', priority='high', is_security_alert=True, message_type='account_lock')
                            notify_user(admin, lock_msg_admin, 'email', subject='SECURITY ALERT – Account Locked', priority='high', is_security_alert=True, message_type='account_lock')
                        messages.error(request, 'YOUR ACCOUNT HAS BEEN LOCKED. CONTACT ADMIN FOR UNLOCKING.')

                    # ── Approaching permanent lock (> suspend_at, < lock_at) ──
                    elif total > suspend_at:
                        remaining = lock_at - total
                        messages.error(request, f'Invalid credentials. {remaining} attempt(s) remaining before your account is permanently locked.')

                    # ── SUSPENSION at suspend_at failures ─────────────────────
                    elif total == suspend_at:
                        susp_msg_user = (
                            f"MSICT OLMS: Your account '{username}' has been temporarily "
                            f"SUSPENDED for {suspend_duration} minutes after {suspend_at} failed login attempts from IP {ip}. "
                            f"After {suspend_duration} minutes, you may try again ({lock_at - suspend_at} more attempts before permanent lock)."
                        )
                        susp_msg_admin = (
                            f"Security Notice: Account '{username}' temporarily suspended ({suspend_duration} min) "
                            f"after {suspend_at} failed attempts from IP {ip} at {now.strftime('%Y-%m-%d %H:%M:%S')}."
                        )
                        notify_user(db_user, susp_msg_user, 'sms', priority='high', is_security_alert=True, message_type='suspended')
                        notify_user(db_user, susp_msg_user, 'email', subject='MSICT OLMS – Account Suspended', priority='high', is_security_alert=True, message_type='suspended')
                        for admin in admins:
                            notify_user(admin, susp_msg_admin, 'sms', priority='high', is_security_alert=True, message_type='suspended')
                            notify_user(admin, susp_msg_admin, 'email', subject='Security Notice – Account Suspended', priority='high', is_security_alert=True, message_type='suspended')
                        messages.error(request, f'Account suspended for {suspend_duration} minutes after {suspend_at} failed attempts. Try again after {suspend_duration} minutes.')

                    # ── Before suspension: count down ─────────────────────────
                    else:
                        remaining = suspend_at - total
                        messages.error(request, f'Invalid credentials. {remaining} attempt(s) remaining before account suspension.')

                else:
                    LoginAttempt.objects.create(username=username, ip_address=ip, status='failed', attempt_count=1)
                    messages.error(request, 'Invalid credentials.')
    else:
        form = LoginForm()

    from catalog.models import MediaSlide, LoginContent
    logo = MediaSlide.get_active_logo()
    login_content = LoginContent.get_active_content()
    slideshow_images = MediaSlide.objects.filter(
        slide_type='login_slideshow', is_active=True
    ).order_by('display_order', '-created_at')
    return render(request, 'accounts/login.html', {
        'form': form,
        'logo': logo,
        'login_content': login_content,
        'slideshow_images': slideshow_images,
    })


# ----------------------------------------------------------------------
# View ya Kutoka Nje — Inahifadhi rekodi ya kutoka na kuelekeza kwenye ukurasa wa nyumbani
# ----------------------------------------------------------------------
def logout_view(request):
    if request.user.is_authenticated:
        log_audit(request.user, f"User '{request.user.username}' logged out", request)
        from .models import UserSession
        UserSession.objects.filter(
            session_id=request.session.session_key, user=request.user
        ).delete()
    logout(request)
    return redirect('home')


# ----------------------------------------------------------------------
# View ya Omba Kubadilisha Nywila — Inatuma OTP kwa SMS na barua pepe
# Mtumiaji anaweza kutumia nambari ya jeshi au barua pepe
# ----------------------------------------------------------------------
def forgot_password_view(request):
    # Pre-fill identifier if admin/librarian initiated reset for a specific user
    prefill_identifier = request.session.pop('reset_for_user_identifier', None)

    if request.method == 'POST':
        identifier = request.POST.get('identifier', '').strip()
        try:
            user = OLMSUser.objects.get(Q(army_no=identifier) | Q(email=identifier))

            # ── Rate-limit OTP issuance: max 3 OTPs per user per hour ──
            window_start = timezone.now() - timedelta(hours=1)
            recent_otps = OTPRecord.objects.filter(
                user=user, created_at__gte=window_start,
            ).count()
            if recent_otps >= 3:
                log_audit(user, f"OTP rate-limit hit (>=3/hr) for '{user.username}'", request)
                messages.error(
                    request,
                    'Too many OTP requests. Please wait an hour before requesting another.'
                )
                return render(request, 'accounts/forgot_password.html')

            otp = create_otp_for_user(user)
            _otp_mins = getattr(otp, '_validity_minutes', int(SystemPreference.get('OTP_VALIDITY_MINUTES', 10) or 10))
            msg = f"MSICT OLMS: Your password reset OTP is {otp.otp_code}. Valid for {_otp_mins} minute(s)."

            # Always attempt OTP delivery on BOTH channels for every user.
            sms_notif = notify_user(
                user,
                msg,
                'sms',
                priority='high',
                is_security_alert=True,
            )
            email_notif = notify_user(
                user,
                msg,
                'email',
                subject="MSICT OLMS - Password Reset OTP",
                priority='high',
                is_security_alert=True,
            )

            request.session['otp_user_id'] = user.pk
            if sms_notif.status == 'sent' and email_notif.status == 'sent':
                messages.success(request, 'OTP sent to your registered phone and email.')
            elif sms_notif.status == 'sent':
                messages.warning(request, 'OTP sent by SMS, but email delivery failed.')
            elif email_notif.status == 'sent':
                messages.warning(request, 'OTP sent by email, but SMS delivery failed.')
            else:
                messages.error(request, 'Failed to send OTP via both SMS and email. Please try again.')
            return redirect('verify_otp')
        except OLMSUser.DoesNotExist:
            messages.error(request, 'No account found with that Army Number or Email.')
    return render(request, 'accounts/forgot_password.html', {'prefill_identifier': prefill_identifier})


# Thibitisha OTP — inachunguza kama OTP ni sahihi na bado haijaisha muda
# Brute-force protection: max 5 wrong attempts per session — then the
# pending OTP is invalidated and the user must request a fresh one.
# ----------------------------------------------------------------------
# View ya Thibitisha OTP — Mtumiaji anaweka OTP aliyopokea
# ----------------------------------------------------------------------
def verify_otp_view(request):
    user_id = request.session.get('otp_user_id')
    if not user_id:
        return redirect('forgot_password')

    MAX_OTP_ATTEMPTS = 5
    attempts = int(request.session.get('otp_attempts', 0))

    if request.method == 'POST':
        if attempts >= MAX_OTP_ATTEMPTS:
            # Burn ALL pending OTPs for this user so the brute force has
            # nothing left to grind against, and force a fresh request.
            OTPRecord.objects.filter(user_id=user_id, used=False).update(used=True)
            request.session.pop('otp_attempts', None)
            request.session.pop('otp_user_id', None)
            try:
                _u = OLMSUser.objects.get(pk=user_id)
                log_audit(_u, f"OTP brute-force lockout for '{_u.username}' after {attempts} attempts", request)
            except OLMSUser.DoesNotExist:
                pass
            messages.error(request, 'Too many incorrect OTP attempts. Please request a new OTP.')
            return redirect('forgot_password')

        code = request.POST.get('otp_code', '').strip()
        try:
            otp = OTPRecord.objects.get(user_id=user_id, otp_code=code, used=False)
            if otp.is_valid():
                otp.used = True
                otp.save()
                request.session['otp_verified_user_id'] = user_id
                request.session.pop('otp_attempts', None)
                return redirect('reset_password')
            else:
                messages.error(request, 'OTP expired.')
        except OTPRecord.DoesNotExist:
            attempts += 1
            request.session['otp_attempts'] = attempts
            remaining = MAX_OTP_ATTEMPTS - attempts
            if remaining > 0:
                messages.error(request, f'Invalid OTP. {remaining} attempt(s) remaining.')
            else:
                messages.error(request, 'Invalid OTP.')
    return render(request, 'accounts/verify_otp.html')


# Weka nywila mpya — inafanya kazi tu baada ya OTP kuthibitishwa
# ----------------------------------------------------------------------
# View ya Kubadilisha Nywila — Mtumiaji anaweka nywila mpya
# ----------------------------------------------------------------------
def reset_password_view(request):
    user_id = request.session.get('otp_verified_user_id')
    if not user_id:
        return redirect('forgot_password')

    if request.method == 'POST':
        new_password = request.POST.get('new_password', '')
        confirm = request.POST.get('confirm_password', '')
        user = get_object_or_404(OLMSUser, pk=user_id)
        err = None
        if new_password != confirm:
            err = 'Passwords do not match.'
        else:
            err = _validate_password(new_password, user=user)
            # Check password history (last 5 passwords)
            if not err:
                from accounts.utils import is_password_reused
                if is_password_reused(user, new_password):
                    err = 'You cannot reuse your last 5 passwords. Please choose a different password.'
        if err:
            messages.error(request, err)
        else:
            _old_hash = user.password  # capture BEFORE set_password()
            user.set_password(new_password)
            user.last_password_change = timezone.now()
            user.password_changed_after_first_login = True
            user.save(update_fields=['password', 'last_password_change', 'password_changed_after_first_login'])
            # Save OLD hash so history tracks every password that was ever used
            from accounts.utils import add_password_to_history
            add_password_to_history(user, _old_hash)
            del request.session['otp_verified_user_id']
            request.session.pop('otp_user_id', None)
            log_audit(user, f"Password reset via OTP for '{user.username}'", request)
            messages.success(request, 'Password reset successfully. Please log in.')
            return redirect('login')
    return render(request, 'accounts/reset_password.html')


# Elekeza mtumiaji kwa dashboard yake kulingana na jukumu lake
# admin → admin_dashboard | librarian → librarian_dashboard | member → member_dashboard
@login_required
def dashboard_redirect(request):
    role = request.user.role
    if role == 'admin':
        return redirect('admin_dashboard')
    elif role == 'librarian':
        return redirect('librarian_dashboard')
    elif role == 'guest' or request.user.is_guest:
        has_active = GuestSession.objects.filter(user=request.user, status__in=['active', 'renewed']).exists()
        if has_active:
            return redirect('guest_dashboard')
        return redirect('guest_start_session')
    return redirect('member_dashboard')


@login_required
def guest_dashboard_view(request):
    if request.user.role != 'guest' and not request.user.is_guest:
        return redirect('dashboard')

    active_session = GuestSession.objects.filter(user=request.user, status__in=['active', 'renewed']).order_by('-sign_in_time').first()

    # Server-side auto-expiry enforcement
    if active_session:
        now = timezone.now()
        expiry = active_session.sign_in_time + timedelta(hours=float(active_session.paid_hours))
        if now >= expiry:
            duration_hours = max(0.01, (now - active_session.sign_in_time).total_seconds() / 3600)
            active_session.sign_out_time = now
            active_session.duration_hours = round(duration_hours, 2)
            active_session.status = 'expired'
            # amount_paid already set at payment time — no refund
            active_session.save(update_fields=['sign_out_time', 'duration_hours', 'status'])
            request.user.total_guest_hours = (request.user.total_guest_hours or Decimal('0')) + Decimal(str(active_session.duration_hours))
            request.user.save(update_fields=['total_guest_hours'])
            # Revenue already recorded at payment time — no new RevenueTransaction
            log_audit(request.user, f"Guest session auto-expired ({active_session.duration_hours}h, TZS {active_session.amount_paid:,.0f} already paid)", request)
            messages.warning(request, f'Your previous session has expired. Duration: {active_session.duration_hours} hour(s). Amount paid: TZS {active_session.amount_paid:,.0f}.')
            active_session = None

    # No active session → redirect to standalone start-session page
    if not active_session:
        return redirect('guest_start_session')

    recent_sessions = GuestSession.objects.filter(user=request.user).order_by('-sign_in_time')[:10]
    return render(request, 'accounts/guest_dashboard.html', {
        'active_session': active_session,
        'recent_sessions': recent_sessions,
    })


@login_required
def guest_start_session_page_view(request):
    """GET page: standalone start-session form (no nav, no sidebar).
    Guest must fill hours and pay before accessing the dashboard."""
    if request.user.role != 'guest' and not request.user.is_guest:
        return redirect('dashboard')

    existing = GuestSession.objects.filter(user=request.user, status__in=['active', 'renewed']).first()
    if existing:
        return redirect('guest_dashboard')

    hourly_rate = float(SystemPreference.get('GUEST_HOURLY_RATE', 500) or 500)
    max_hours = int(SystemPreference.get('GUEST_MAX_HOURS', 12) or 12)

    return render(request, 'accounts/guest_start_session.html', {
        'hourly_rate': hourly_rate,
        'max_hours': max_hours,
        'show_payment': False,
    })


@login_required
@require_POST
def start_guest_session_view(request):
    """Guest fills hours → render payment form on standalone page (no session created yet)."""
    if request.user.role != 'guest' and not request.user.is_guest:
        messages.error(request, 'Only guest accounts can start guest sessions.')
        return redirect('dashboard')

    existing = GuestSession.objects.filter(user=request.user, status__in=['active', 'renewed']).first()
    if existing:
        messages.info(request, 'You already have an active session. End it or renew it.')
        return redirect('guest_dashboard')

    try:
        paid_hours = float(request.POST.get('paid_hours', '1') or '1')
    except ValueError:
        paid_hours = 1.0

    paid_hours = max(1.0, paid_hours)
    max_hours = int(SystemPreference.get('GUEST_MAX_HOURS', 12) or 12)

    # Enforce daily limit: max 12h total per day
    hours_used_today = float(_guest_hours_used_today(request.user))
    available_today = float(max_hours) - hours_used_today
    if available_today <= 0:
        messages.error(request, f'You have reached the daily limit of {max_hours}h. Try again tomorrow.')
        return redirect('guest_start_session')
    paid_hours = min(paid_hours, available_today)

    hourly_rate = float(SystemPreference.get('GUEST_HOURLY_RATE', 500) or 500)
    total_amount = paid_hours * hourly_rate

    return render(request, 'accounts/guest_start_session.html', {
        'paid_hours': paid_hours,
        'hourly_rate': hourly_rate,
        'total_amount': total_amount,
        'show_payment': True,
    })


@login_required
@require_POST
def guest_payment_view(request):
    """Process guest payment, create session, and record revenue immediately."""
    if request.user.role != 'guest' and not request.user.is_guest:
        messages.error(request, 'Only guest accounts can start guest sessions.')
        return redirect('dashboard')

    existing = GuestSession.objects.filter(user=request.user, status__in=['active', 'renewed']).first()
    if existing:
        messages.info(request, 'You already have an active session. End it or renew it.')
        return redirect('guest_dashboard')

    try:
        paid_hours = float(request.POST.get('paid_hours', '1') or '1')
    except ValueError:
        paid_hours = 1.0

    paid_hours = max(1.0, paid_hours)
    max_hours = int(SystemPreference.get('GUEST_MAX_HOURS', 12) or 12)
    hourly_rate = float(SystemPreference.get('GUEST_HOURLY_RATE', 500) or 500)

    # Enforce daily limit: max 12h total per day
    hours_used_today = float(_guest_hours_used_today(request.user))
    available_today = float(max_hours) - hours_used_today
    if available_today <= 0:
        messages.error(request, f'Daily limit of {max_hours}h reached. Try again tomorrow.')
        return redirect('guest_start_session')
    paid_hours = min(paid_hours, available_today)
    total_amount = paid_hours * hourly_rate

    payment_method = request.POST.get('payment_method', '').strip()
    if not payment_method:
        messages.error(request, 'Please select a payment method.')
        return render(request, 'accounts/guest_start_session.html', {
            'paid_hours': paid_hours,
            'hourly_rate': hourly_rate,
            'total_amount': total_amount,
            'show_payment': True,
        })

    # Collect payment details based on method
    phone_number = request.POST.get('phone_number', '').strip()
    bank_name = request.POST.get('bank_name', '').strip()
    bank_account_no = request.POST.get('bank_account_no', '').strip()
    card_holder = request.POST.get('card_holder', '').strip()
    card_last4 = request.POST.get('card_last4', '').strip()
    card_expiry = request.POST.get('card_expiry', '').strip()
    receipt_ref = request.POST.get('receipt_no', '').strip()

    # Validate required fields per payment method
    is_mobile = payment_method in ['mpesa', 'tigopesa', 'airtel_money', 'halopesa']
    is_bank = payment_method == 'bank_transfer'
    is_card = payment_method in ['visa', 'mastercard']

    if is_mobile and not phone_number:
        messages.error(request, 'Phone number is required for mobile money payment.')
        return render(request, 'accounts/guest_start_session.html', {
            'paid_hours': paid_hours, 'hourly_rate': hourly_rate, 'total_amount': total_amount,
            'show_payment': True,
        })
    if is_mobile and phone_number and not re.match(r'^0\d{9}$', phone_number):
        messages.error(request, 'Phone number must be exactly 10 digits starting with 0 (e.g. 0712345678).')
        return render(request, 'accounts/guest_start_session.html', {
            'paid_hours': paid_hours, 'hourly_rate': hourly_rate, 'total_amount': total_amount,
            'show_payment': True,
        })
    if is_bank and (not bank_name or not bank_account_no):
        messages.error(request, 'Bank name and account number are required for bank transfer.')
        return render(request, 'accounts/guest_start_session.html', {
            'paid_hours': paid_hours, 'hourly_rate': hourly_rate, 'total_amount': total_amount,
            'show_payment': True,
        })
    if is_card and (not card_holder or not card_last4):
        messages.error(request, 'Cardholder name and last 4 digits are required for card payment.')
        return render(request, 'accounts/guest_start_session.html', {
            'paid_hours': paid_hours, 'hourly_rate': hourly_rate, 'total_amount': total_amount,
            'show_payment': True,
        })

    # Create session with payment already recorded
    session = GuestSession.objects.create(
        user=request.user,
        paid_hours=paid_hours,
        amount_paid=total_amount,
        payment_status='paid',
        payment_method=payment_method,
        ip_address=get_client_ip(request),
        device_info=request.META.get('HTTP_USER_AGENT', '')[:400],
        status='active',
    )

    # Record revenue immediately
    try:
        from circulation.models import RevenueTransaction
        RevenueTransaction.objects.create(
            user=request.user,
            account_type='guest_fee',
            amount=total_amount,
            description=f'Guest session fee ({paid_hours:.0f}h) — {payment_method.upper()}',
            reference_id=session.id,
            reference_table='accounts_guestsession',
            recorded_by=request.user,
        )
    except Exception:
        pass

    # Update user totals
    request.user.total_guest_hours = (request.user.total_guest_hours or 0) + Decimal(str(paid_hours))
    request.user.total_guest_paid = (request.user.total_guest_paid or 0) + Decimal(str(total_amount))
    request.user.save(update_fields=['total_guest_hours', 'total_guest_paid'])

    log_audit(request.user, f"Guest session started ({paid_hours}h, TZS {total_amount:,.0f} paid via {payment_method})", request)

    # Compute expiry time for notifications
    expiry_dt = session.sign_in_time + timedelta(hours=float(paid_hours))
    expiry_str = expiry_dt.strftime('%d %b %Y, %H:%M')

    # SMS + Email notification
    try:
        sms_msg = (f"MSICT OLMS: Session started — {paid_hours:.0f}h at TZS {hourly_rate:,.0f}/h. "
                   f"Total paid: TZS {total_amount:,.0f} via {payment_method.upper()}. "
                   f"Expires at: {expiry_str}. Session #{session.id}.")
        notify_user(request.user, sms_msg, 'sms', message_type='guest_session_start')
    except Exception:
        pass
    try:
        email_body = (
            f"Dear {request.user.get_full_name()},\n\n"
            f"Your guest session has started successfully.\n\n"
            f"  Duration   : {paid_hours:.0f} hour(s)\n"
            f"  Rate       : TZS {hourly_rate:,.0f}/hour\n"
            f"  Total      : TZS {total_amount:,.0f}\n"
            f"  Method     : {payment_method.upper()}\n"
            f"  Session #  : {session.id}\n"
            f"  Expires at : {expiry_str}\n\n"
            f"Enjoy your library access!"
        )
        notify_user(request.user, email_body, 'email', subject='MSICT OLMS — Guest Session Started', message_type='guest_session_start')
    except Exception:
        pass

    try:
        from circulation.receipt_utils import email_guest_receipt
        email_guest_receipt(session, is_renewal=False)
    except Exception:
        pass

    messages.success(request, f'Payment successful! Session started for {paid_hours:.0f} hour(s). TZS {total_amount:,.0f} paid via {payment_method.upper()}.')
    return redirect('guest_dashboard')


@login_required
@require_POST
def end_guest_session_view(request):
    if request.user.role != 'guest' and not request.user.is_guest:
        messages.error(request, 'Only guest accounts can end guest sessions.')
        return redirect('dashboard')

    session = GuestSession.objects.filter(user=request.user, status__in=['active', 'renewed']).order_by('-sign_in_time').first()
    if not session:
        messages.info(request, 'No active guest session found.')
        return redirect('guest_dashboard')

    now = timezone.now()
    duration_hours = max(0.01, (now - session.sign_in_time).total_seconds() / 3600)

    auto_expired = request.POST.get('auto_expire') == '1'
    session.sign_out_time = now
    session.duration_hours = round(duration_hours, 2)
    # amount_paid already set at payment time — no refund on early sign-out
    session.status = 'expired' if auto_expired else 'ended'
    session.save(update_fields=['sign_out_time', 'duration_hours', 'status'])

    request.user.total_guest_hours = (request.user.total_guest_hours or Decimal('0')) + Decimal(str(session.duration_hours))
    request.user.save(update_fields=['total_guest_hours'])

    # Revenue already recorded at payment time — no new RevenueTransaction here

    log_audit(request.user, f"Guest session {'auto-expired' if auto_expired else 'ended'} ({session.duration_hours}h, TZS {session.amount_paid:,.0f} already paid)", request)

    # SMS + Email notification
    event_label = 'expired' if auto_expired else 'ended'
    try:
        sms_msg = (f"MSICT OLMS: Session {event_label}. Duration: {session.duration_hours}h. "
                   f"Amount paid: TZS {session.amount_paid:,.0f}. No refund for unused time. Session #{session.id}.")
        notify_user(request.user, sms_msg, 'sms', message_type='guest_session_end')
    except Exception:
        pass
    try:
        email_body = (
            f"Dear {request.user.get_full_name()},\n\n"
            f"Your guest session has {event_label}.\n\n"
            f"  Duration    : {session.duration_hours} hour(s)\n"
            f"  Amount paid : TZS {session.amount_paid:,.0f}\n"
            f"  Session #   : {session.id}\n\n"
            f"Note: Payment is non-refundable. Unused time is not carried over.\n"
            f"You can start a new session anytime if daily limit allows."
        )
        notify_user(request.user, email_body, 'email', subject=f'MSICT OLMS — Guest Session {event_label.title()}', message_type='guest_session_end')
    except Exception:
        pass

    if auto_expired:
        messages.warning(request, f'Your session has expired. Duration: {session.duration_hours} hour(s). Amount paid: TZS {session.amount_paid:,.0f}. Please start a new session to continue.')
        return redirect('guest_start_session')
    else:
        messages.success(request, f'Session ended. Duration: {session.duration_hours} hour(s). Amount paid: TZS {session.amount_paid:,.0f}. No refund for unused time.')
    return redirect('guest_dashboard')


@login_required
@require_POST
def guest_session_delete_view(request, session_id):
    """Guest deletes a non-active session from their history."""
    session = get_object_or_404(GuestSession, pk=session_id, user=request.user)
    if session.status in ('active', 'renewed'):
        messages.error(request, 'Cannot delete an active session. End it first.')
        return redirect('guest_dashboard')
    session.delete()
    log_audit(request.user, f"Deleted guest session #{session_id}", request)
    messages.success(request, 'Session record deleted.')
    return redirect('guest_dashboard')


def _guest_hours_used_today(user):
    """Calculate total paid hours for sessions started today by this user."""
    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    sessions_today = GuestSession.objects.filter(
        user=user,
        sign_in_time__gte=today_start,
    ).exclude(status__in=['active', 'renewed'])  # active/renewed session handled separately
    used = Decimal('0')
    for s in sessions_today:
        used += s.paid_hours
    # Add active session's paid_hours if exists
    active = GuestSession.objects.filter(user=user, status__in=['active', 'renewed']).first()
    if active:
        used += active.paid_hours
    return used


@login_required
@require_POST
def guest_session_renew_view(request):
    """Show renewal payment form — user adds hours to active session.
    Max 12h per day total (including current session + past sessions today).
    """
    if request.user.role != 'guest' and not request.user.is_guest:
        messages.error(request, 'Only guest accounts can renew sessions.')
        return redirect('dashboard')

    active_session = GuestSession.objects.filter(user=request.user, status__in=['active', 'renewed']).first()
    if not active_session:
        messages.error(request, 'No active session to renew. Start a new session first.')
        return redirect('guest_dashboard')

    try:
        renew_hours = float(request.POST.get('renew_hours', '1') or '1')
    except ValueError:
        renew_hours = 1.0

    renew_hours = max(1.0, renew_hours)

    max_daily = float(SystemPreference.get('GUEST_MAX_HOURS', 12) or 12)
    hours_used_today = float(_guest_hours_used_today(request.user))
    available_today = max_daily - hours_used_today

    if available_today <= 0:
        messages.error(request, f'You have reached the daily limit of {max_daily:.0f}h. Try again tomorrow.')
        return redirect('guest_dashboard')

    renew_hours = min(renew_hours, available_today)
    hourly_rate = float(SystemPreference.get('GUEST_HOURLY_RATE', 500) or 500)
    total_amount = renew_hours * hourly_rate

    # Remaining time in current session
    now = timezone.now()
    expiry = active_session.sign_in_time + timedelta(hours=float(active_session.paid_hours))
    remaining_seconds = max(0, (expiry - now).total_seconds())
    remaining_hours = remaining_seconds / 3600

    return render(request, 'accounts/guest_renew_payment.html', {
        'active_session': active_session,
        'renew_hours': renew_hours,
        'hourly_rate': hourly_rate,
        'total_amount': total_amount,
        'remaining_hours': round(remaining_hours, 2),
        'available_today': available_today,
        'max_daily': max_daily,
    })


@login_required
@require_POST
def guest_session_renew_pay_view(request):
    """Process renewal payment and extend active session hours."""
    if request.user.role != 'guest' and not request.user.is_guest:
        messages.error(request, 'Only guest accounts can renew sessions.')
        return redirect('dashboard')

    active_session = GuestSession.objects.filter(user=request.user, status__in=['active', 'renewed']).first()
    if not active_session:
        messages.error(request, 'No active session to renew.')
        return redirect('guest_dashboard')

    try:
        renew_hours = float(request.POST.get('renew_hours', '1') or '1')
    except ValueError:
        renew_hours = 1.0

    renew_hours = max(1.0, renew_hours)

    max_daily = float(SystemPreference.get('GUEST_MAX_HOURS', 12) or 12)
    hours_used_today = float(_guest_hours_used_today(request.user))
    available_today = max_daily - hours_used_today

    if available_today <= 0:
        messages.error(request, f'Daily limit of {max_daily:.0f}h reached. Try again tomorrow.')
        return redirect('guest_dashboard')

    renew_hours = min(renew_hours, available_today)
    hourly_rate = float(SystemPreference.get('GUEST_HOURLY_RATE', 500) or 500)
    total_amount = renew_hours * hourly_rate

    payment_method = request.POST.get('payment_method', '').strip()
    if not payment_method:
        messages.error(request, 'Please select a payment method.')
        return render(request, 'accounts/guest_renew_payment.html', {
            'active_session': active_session,
            'renew_hours': renew_hours,
            'hourly_rate': hourly_rate,
            'total_amount': total_amount,
            'remaining_hours': 0,
            'available_today': available_today,
            'max_daily': max_daily,
        })

    # Validate payment fields (same logic as guest_payment_view)
    phone_number = request.POST.get('phone_number', '').strip()
    bank_name = request.POST.get('bank_name', '').strip()
    bank_account_no = request.POST.get('bank_account_no', '').strip()
    card_holder = request.POST.get('card_holder', '').strip()
    card_last4 = request.POST.get('card_last4', '').strip()

    is_mobile = payment_method in ['mpesa', 'tigopesa', 'airtel_money', 'halopesa']
    is_bank = payment_method == 'bank_transfer'
    is_card = payment_method in ['visa', 'mastercard']

    if is_mobile and not phone_number:
        messages.error(request, 'Phone number is required for mobile money payment.')
        return redirect('guest_dashboard')
    if is_mobile and phone_number and not re.match(r'^0\d{9}$', phone_number):
        messages.error(request, 'Phone number must be exactly 10 digits starting with 0 (e.g. 0712345678).')
        return redirect('guest_dashboard')
    if is_bank and (not bank_name or not bank_account_no):
        messages.error(request, 'Bank name and account number are required.')
        return redirect('guest_dashboard')
    if is_card and (not card_holder or not card_last4):
        messages.error(request, 'Cardholder name and last 4 digits are required.')
        return redirect('guest_dashboard')

    # Extend the session: add renew_hours to paid_hours (same row, no new session)
    old_paid = float(active_session.paid_hours)
    active_session.paid_hours = Decimal(str(old_paid + renew_hours))
    active_session.amount_paid = Decimal(str(float(active_session.amount_paid) + total_amount))
    active_session.payment_method = payment_method
    active_session.status = 'renewed'
    active_session.renewed = True
    active_session.expiry_notification_sent = False
    active_session.save(update_fields=['paid_hours', 'amount_paid', 'payment_method', 'status', 'renewed', 'expiry_notification_sent'])

    # Record revenue for renewal
    try:
        from circulation.models import RevenueTransaction
        RevenueTransaction.objects.create(
            user=request.user,
            account_type='guest_fee',
            amount=total_amount,
            description=f'Guest session renewal (+{renew_hours:.0f}h) — {payment_method.upper()} — Session #{active_session.id}',
            reference_id=active_session.id,
            reference_table='accounts_guestsession',
            recorded_by=request.user,
        )
    except Exception:
        pass

    # Update user totals
    request.user.total_guest_paid = (request.user.total_guest_paid or Decimal('0')) + Decimal(str(total_amount))
    request.user.save(update_fields=['total_guest_paid'])

    log_audit(request.user, f"Guest session renewed (+{renew_hours}h, TZS {total_amount:,.0f} via {payment_method}) — Session #{active_session.id}", request)

    # Compute new expiry time for notifications
    renew_expiry_dt = active_session.sign_in_time + timedelta(hours=float(active_session.paid_hours))
    renew_expiry_str = renew_expiry_dt.strftime('%d %b %Y, %H:%M')

    # SMS + Email notification
    try:
        sms_msg = (f"MSICT OLMS: Session renewed — +{renew_hours:.0f}h added. "
                   f"Total paid: TZS {total_amount:,.0f} via {payment_method.upper()}. "
                   f"New total: {float(active_session.paid_hours):.0f}h. "
                   f"Expires at: {renew_expiry_str}. Session #{active_session.id}.")
        notify_user(request.user, sms_msg, 'sms', message_type='guest_session_renew')
    except Exception:
        pass
    try:
        email_body = (
            f"Dear {request.user.get_full_name()},\n\n"
            f"Your guest session has been renewed successfully.\n\n"
            f"  Added Hours : {renew_hours:.0f}\n"
            f"  Amount Paid : TZS {total_amount:,.0f}\n"
            f"  Method      : {payment_method.upper()}\n"
            f"  Total Hours : {float(active_session.paid_hours):.0f}\n"
            f"  Session #   : {active_session.id}\n"
            f"  Expires at  : {renew_expiry_str}\n\n"
            f"Enjoy your extended library access!"
        )
        notify_user(request.user, email_body, 'email', subject='MSICT OLMS — Session Renewed', message_type='guest_session_renew')
    except Exception:
        pass

    try:
        from circulation.receipt_utils import email_guest_receipt
        email_guest_receipt(active_session, is_renewal=True)
    except Exception:
        pass

    messages.success(request, f'Session renewed! +{renew_hours:.0f}h added. TZS {total_amount:,.0f} paid via {payment_method.upper()}. Total: {float(active_session.paid_hours):.0f}h.')
    return redirect('guest_dashboard')


@login_required
def guest_session_receipt_pdf_view(request, session_id):
    """Generate a PDF receipt for a guest session payment (start or renewal)."""
    from circulation.receipt_utils import generate_receipt_pdf

    session = get_object_or_404(GuestSession, pk=session_id, user=request.user)
    if session.payment_status != 'paid':
        messages.error(request, 'No payment record found for this session.')
        return redirect('guest_dashboard')

    receipt_id = f"RCPT-GUEST-{session.pk}-{session.sign_in_time.strftime('%Y%m%d%H%M')}"
    expiry_dt = session.sign_in_time + timedelta(hours=float(session.paid_hours))
    is_renewed = session.renewed

    title = 'Guest Session Receipt' + (' (Renewed)' if is_renewed else '')
    items = [
        ('Session #', f'#{session.pk}'),
        ('Signed In', session.sign_in_time.strftime('%d %b %Y, %H:%M')),
        ('Total Hours', f'{float(session.paid_hours):.0f}h'),
        ('Expires At', expiry_dt.strftime('%d %b %Y, %H:%M')),
    ]

    qr_data = (
        f"MSICT-OLMS|GUEST-RECEIPT|{receipt_id}|{request.user.username}|"
        f"TZS {session.amount_paid:,.0f}|Session #{session.pk}"
    )

    return generate_receipt_pdf(
        receipt_id=receipt_id,
        title=title,
        user=request.user,
        items=items,
        qr_data=qr_data,
        payment_method=session.payment_method,
        amount_label='Total Paid',
        amount_value=f"TZS {float(session.amount_paid):,.0f}",
        filename=f'guest_receipt_{session.pk}',
        extra_notes=[
            'Payment is non-refundable. Unused time is not carried over.',
            f'Session status: {session.get_status_display()}',
        ],
        download=request.GET.get('download') == '1',
    )


@login_required
def upgrade_to_member_view(request):
    """Guest submits a request to upgrade to a full member (pending librarian approval)."""
    if request.user.role != 'guest' and not request.user.is_guest:
        messages.info(request, 'Only guest accounts can upgrade to membership.')
        return redirect('dashboard')

    prefill = {
        'first_name': request.user.first_name,
        'middle_name': request.user.middle_name,
        'surname': request.user.surname,
        'email': request.user.email,
        'phone': request.user.phone,
        'army_no': '',
    }

    if request.method == 'POST':
        army_no = request.POST.get('army_no', '').strip()
        member_type = request.POST.get('member_type', '').strip()
        registration_no = request.POST.get('registration_no', '').strip() or None
        rank_name = request.POST.get('rank', '').strip() or None
        first_name = request.POST.get('first_name', '').strip() or request.user.first_name
        middle_name = request.POST.get('middle_name', '').strip()
        surname = request.POST.get('surname', '').strip() or request.user.surname
        phone = request.POST.get('phone', '').strip() or request.user.phone

        ctx = {'rank_list': Rank.RANK_LIST, 'upgrade': True, 'prefill': prefill}

        if not re.match(r'^(MTM|MT|PW|P)\s?\d+$', army_no):
            messages.error(request, 'Army number must start with MT, MTM, P, or PW followed by digits.')
            return render(request, 'accounts/register.html', ctx)

        if OLMSUser.objects.filter(army_no=army_no).exclude(pk=request.user.pk).exists():
            messages.error(request, 'Army number already registered.')
            return render(request, 'accounts/register.html', ctx)

        if not re.match(r'^0\d{9}$', phone):
            messages.error(request, 'Phone number must be exactly 10 digits starting with 0 (e.g. 0712345678).')
            return render(request, 'accounts/register.html', ctx)

        if member_type == 'student' and not registration_no:
            messages.error(request, 'Registration number is required for students.')
            return render(request, 'accounts/register.html', ctx)
        if member_type != 'student':
            registration_no = None

        rank_obj = Rank.objects.filter(rank_name=rank_name).first() if rank_name else None

        user = request.user
        user.army_no = army_no
        user.member_type = member_type
        user.registration_no = registration_no
        user.rank = rank_obj
        user.first_name = first_name
        user.middle_name = middle_name
        user.surname = surname
        user.phone = phone
        # Convert to a pending member — must clear is_guest so model.save() does
        # not force the account back to guest_auto/active state.
        user.is_guest = False
        user.role = 'member'
        user.registration_status = 'pending'
        user.is_active = False
        user.save()

        log_audit(None, f"Guest {user.username} submitted member upgrade (Army No: {army_no})", request)

        # Notify librarians (non-blocking)
        try:
            send_account_status_update(user, 'pending')
        except Exception:
            pass

        from django.contrib.auth import logout as _logout
        _logout(request)
        messages.success(request, 'Upgrade request submitted! It is now pending librarian approval. You will receive your member credentials once approved.')
        return redirect('login')

    return render(request, 'accounts/register.html', {
        'rank_list': Rank.RANK_LIST,
        'upgrade': True,
        'prefill': prefill,
    })


@login_required
# ----------------------------------------------------------------------
# View ya Dashboard ya Superuser — Dashboard ya msimamizi mkuu
# ----------------------------------------------------------------------
def superuser_dashboard_view(request):
    """Allows Django superusers to visit any dashboard directly."""
    if not request.user.is_superuser:
        return redirect('dashboard')
    target = request.GET.get('view', 'admin')
    if target == 'librarian':
        from catalog.views import librarian_dashboard_view
        return librarian_dashboard_view(request)
    elif target == 'member':
        from circulation.views import member_dashboard_view
        return member_dashboard_view(request)
    else:
        return redirect('admin_dashboard')


# Badilisha nywila ya mtumiaji aliyeingia — inahitaji nywila ya zamani
@login_required
# ----------------------------------------------------------------------
# View ya Kubadilisha Nywila — Mtumiaji anabadilisha nywila yake
# ----------------------------------------------------------------------
def change_password_view(request):
    if request.method == 'POST':
        old_pw = request.POST.get('old_password', '')
        new_pw = request.POST.get('new_password', '')
        confirm = request.POST.get('confirm_password', '')

        err = None
        if not request.user.check_password(old_pw):
            err = 'Current password is incorrect.'
        elif new_pw != confirm:
            err = 'New passwords do not match.'
        elif old_pw == new_pw:
            err = 'New password must be different from your current password.'
        else:
            err = _validate_password(new_pw, user=request.user)
            # Check password history (last 5 passwords)
            if not err:
                from accounts.utils import is_password_reused
                if is_password_reused(request.user, new_pw):
                    err = 'You cannot reuse your last 5 passwords. Please choose a different password.'

        if err:
            messages.error(request, err)
        else:
            _old_hash = request.user.password  # capture BEFORE set_password()
            request.user.set_password(new_pw)
            request.user.last_password_change = timezone.now()
            request.user.password_changed_after_first_login = True
            request.user.save(update_fields=['password', 'last_password_change', 'password_changed_after_first_login'])
            # Save OLD hash so history tracks every password that was ever used
            from accounts.utils import add_password_to_history
            add_password_to_history(request.user, _old_hash)
            login(request, request.user)
            log_audit(request.user, f"Password changed by '{request.user.username}'", request)
            messages.success(request, 'Password changed successfully.')
            return redirect('profile')
    return render(request, 'accounts/change_password.html')


# Wasifu wa mtumiaji — anaweza kusasisha barua pepe, simu na picha
@login_required
# ----------------------------------------------------------------------
# View ya Wasifu — Mtumiaji anaona na kuhariri wasifu wake
# ----------------------------------------------------------------------
def profile_view(request):
    if request.method == 'POST':
        user = request.user
        is_admin = user.role == 'admin'
        new_phone = request.POST.get('phone', user.phone).strip()
        if not re.match(r'^0\d{9}$', new_phone):
            messages.error(request, 'Phone number must be exactly 10 digits starting with 0 (e.g. 0712345678).')
            return redirect('profile')
        user.phone = new_phone
        user.email = request.POST.get('email', user.email)
        rank_id = request.POST.get('rank_id')
        if rank_id:
            user.rank_id = rank_id
        else:
            user.rank_id = None
        if 'photo' in request.FILES:
            from django.core.exceptions import ValidationError as _VErr
            from .security_utils import validate_upload as _vu
            try:
                _vu(
                    request.FILES['photo'],
                    allowed_extensions={'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'},
                    max_size=5 * 1024 * 1024,
                )
                user.photo = request.FILES['photo']
            except _VErr as _exc:
                messages.error(request, f'Profile photo: {_exc.messages[0]}')
                return redirect('profile')

        # Role editing — only admins can change their own role (but not remove admin from themselves)
        new_role = request.POST.get('role', '').strip()
        if new_role and is_admin:
            if new_role in dict(OLMSUser.ROLE_CHOICES).keys():
                if new_role != 'admin':
                    messages.warning(request, 'You cannot remove your own admin role. Ask another admin.')
                else:
                    user.role = new_role
        elif new_role and not is_admin:
            messages.warning(request, 'Only admins can change roles.')

        # Member type editing — all users can change their own member type (if they are members)
        new_member_type = request.POST.get('member_type', '').strip() or None
        if user.role == 'member':
            if new_member_type and new_member_type in dict(OLMSUser.MEMBER_TYPE_CHOICES).keys():
                user.member_type = new_member_type
            elif not new_member_type:
                user.member_type = None

        update_fields = ['email', 'phone', 'photo', 'rank_id', 'member_type']
        if is_admin and new_role:
            update_fields.append('role')
        user.save(update_fields=update_fields)
        messages.success(request, 'Profile updated successfully.')
        return redirect('profile')

    ranks = Rank.objects.all()
    return render(request, 'accounts/profile.html', {
        'user_obj': request.user,
        'ranks': ranks,
        'is_admin': request.user.role == 'admin',
        'role_choices': OLMSUser.ROLE_CHOICES,
        'member_type_choices': OLMSUser.MEMBER_TYPE_CHOICES,
    })


# Onyesha kadi ya maktaba ya kidijitali (QR code + barcode)
@login_required
# ----------------------------------------------------------------------
# View ya Kadi ya Maktaba — Mtumiaji anaona kadi yake ya kidijitali
# ----------------------------------------------------------------------
def virtual_card_view(request):
    card = generate_virtual_card(request.user)
    return render(request, 'accounts/virtual_card.html', {'card': card, 'user_obj': request.user})


# ----------------------------------------------------------------------
# View ya Pakua Kadi ya Maktaba kama PDF
# ----------------------------------------------------------------------
@login_required
def virtual_card_pdf_view(request):
    buf = generate_virtual_card_pdf(request.user)
    response = HttpResponse(buf, content_type='application/pdf')
    response['Content-Disposition'] = build_content_disposition(
        'attachment', f'MSICT_Card_{request.user.username}.pdf'
    )
    return response


# Decorator: inazuia ufikiaji kwa watu ambao si librarian wala admin
def librarian_required(func):
    from functools import wraps
    @wraps(func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated or request.user.role not in ('librarian', 'admin'):
            messages.error(request, 'Access denied.')
            return redirect('dashboard')
        return func(request, *args, **kwargs)
    return wrapper


# ----------------------------------------------------------------------
# Librarian Guest Management — active sessions, history, mark-paid, suspend
# ----------------------------------------------------------------------
@login_required
@librarian_required
def guest_manage_view(request):
    """Librarian view: see all active guest sessions and recent history."""
    active_sessions = GuestSession.objects.filter(
        status__in=['active', 'renewed']
    ).select_related('user').order_by('-sign_in_time')

    # Auto-expire any sessions past their paid hours
    now = timezone.now()
    hourly_rate = float(SystemPreference.get('GUEST_HOURLY_RATE', 500) or 500)
    for s in active_sessions:
        expiry = s.sign_in_time + timedelta(hours=float(s.paid_hours))
        if now >= expiry:
            duration_hours = max(0.01, (now - s.sign_in_time).total_seconds() / 3600)
            s.sign_out_time = now
            s.duration_hours = round(duration_hours, 2)
            s.status = 'expired'
            # amount_paid already set at payment time — no refund
            s.save(update_fields=['sign_out_time', 'duration_hours', 'status'])
            s.user.total_guest_hours = (s.user.total_guest_hours or Decimal('0')) + Decimal(str(s.duration_hours))
            s.user.save(update_fields=['total_guest_hours'])
            # Revenue already recorded at payment time
            log_audit(request.user, f"Auto-expired guest session #{s.id} for {s.user.username}", request)

    # Re-query after auto-expiry
    active_sessions = GuestSession.objects.filter(
        status__in=['active', 'renewed']
    ).select_related('user').order_by('-sign_in_time')

    history = GuestSession.objects.exclude(
        status__in=['active', 'renewed']
    ).select_related('user').order_by('-sign_in_time')[:50]

    # Guest users
    guest_users = OLMSUser.objects.filter(is_guest=True).order_by('-created_at')

    mark_badge_viewed(request.user, 'active_guest_sessions')
    return render(request, 'accounts/guest_manage.html', {
        'active_sessions': active_sessions,
        'history': history,
        'guest_users': guest_users,
        'hourly_rate': hourly_rate,
    })


@login_required
@librarian_required
@require_POST
def guest_mark_paid_view(request, session_id):
    """Librarian marks a guest session as paid."""
    session = get_object_or_404(GuestSession, pk=session_id)
    session.payment_status = 'paid'
    session.save(update_fields=['payment_status'])
    log_audit(request.user, f"Marked guest session #{session.id} as paid (TZS {session.amount_paid:,.0f})", request)
    messages.success(request, f'Session #{session.id} marked as paid.')
    return redirect('guest_manage')


@login_required
@librarian_required
@require_POST
def guest_session_end_view(request, session_id):
    """Librarian force-ends an active guest session."""
    session = get_object_or_404(GuestSession, pk=session_id, status__in=['active', 'renewed'])
    now = timezone.now()
    duration_hours = max(0.01, (now - session.sign_in_time).total_seconds() / 3600)
    hourly_rate = float(SystemPreference.get('GUEST_HOURLY_RATE', 500) or 500)
    billed_hours = max(1, int(duration_hours) + (0 if duration_hours.is_integer() else 1))
    session.sign_out_time = now
    session.duration_hours = round(duration_hours, 2)
    session.status = 'ended'
    # amount_paid already set at payment time — no refund
    session.save(update_fields=['sign_out_time', 'duration_hours', 'status'])
    session.user.total_guest_hours = (session.user.total_guest_hours or Decimal('0')) + Decimal(str(session.duration_hours))
    session.user.save(update_fields=['total_guest_hours'])
    # Revenue already recorded at payment time
    log_audit(request.user, f"Force-ended guest session #{session.id} for {session.user.username}", request)
    messages.success(request, f'Session #{session.id} ended. Amount paid: TZS {session.amount_paid:,.0f}.')
    return redirect('guest_manage')


@login_required
@librarian_required
@require_POST
def guest_suspend_view(request, user_id):
    """Librarian suspends a guest account."""
    user = get_object_or_404(OLMSUser, pk=user_id, is_guest=True)
    user.is_active = False
    user.save(update_fields=['is_active'])
    # End any active sessions
    GuestSession.objects.filter(user=user, status__in=['active', 'renewed']).update(
        sign_out_time=timezone.now(),
        status='ended'
    )
    log_audit(request.user, f"Suspended guest account {user.username}", request)
    messages.success(request, f'Guest {user.username} has been suspended.')
    return redirect('guest_manage')


@login_required
@librarian_required
@require_POST
def guest_reactivate_view(request, user_id):
    """Librarian reactivates a suspended guest account."""
    user = get_object_or_404(OLMSUser, pk=user_id, is_guest=True)
    user.is_active = True
    user.save(update_fields=['is_active'])
    log_audit(request.user, f"Reactivated guest account {user.username}", request)
    messages.success(request, f'Guest {user.username} has been reactivated.')
    return redirect('guest_manage')


@login_required
@librarian_required
def bulk_message_view(request):
    """Enhanced bulk messaging: target by role/member_type, send via email+sms, track delivery, save drafts, view history."""
    import json

    # ── Build recipient queryset from filters ──────────────────────
    def _build_recipient_qs(roles, member_types, custom_user_ids=None):
        qs = OLMSUser.objects.filter(is_active=True).exclude(role='admin')
        if roles:
            qs = qs.filter(role__in=roles)
        if member_types:
            qs = qs.filter(member_type__in=member_types)
        if custom_user_ids:
            qs = qs.filter(pk__in=custom_user_ids)
        return qs.distinct()

    # ── Handle POST: send or save draft ────────────────────────────
    if request.method == 'POST':
        action = request.POST.get('action', 'send')
        roles = request.POST.getlist('roles')
        member_types = request.POST.getlist('member_types')
        channels = request.POST.getlist('channels')
        subject = request.POST.get('subject', '').strip()
        body = request.POST.get('message', '').strip()
        custom_user_ids = request.POST.getlist('custom_users')

        if not body:
            messages.error(request, 'Message body cannot be empty.')
            return redirect('bulk_message')
        if not channels:
            messages.error(request, 'Select at least one channel (Email and/or SMS).')
            return redirect('bulk_message')

        target_qs = _build_recipient_qs(roles, member_types, custom_user_ids if custom_user_ids else None)
        recipient_count = target_qs.count()

        if recipient_count == 0:
            messages.error(request, 'No recipients match the selected filters.')
            return redirect('bulk_message')

        # Create BulkMessage record
        bm = BulkMessage.objects.create(
            subject=subject,
            body=body,
            target_roles=roles,
            target_member_types=member_types or None,
            send_via=channels,
            sent_by=request.user,
            status='draft' if action == 'draft' else 'sent',
            total_recipients=recipient_count,
        )

        if action == 'draft':
            messages.info(request, f'Draft saved — {recipient_count} recipients will receive when sent.')
            return redirect('bulk_message')

        # ── Send: iterate recipients × channels ─────────────────────
        sent_count = 0
        failed_count = 0
        now = timezone.now()

        for user in target_qs:
            # Substitute placeholders
            personalized = body.replace('{name}', user.get_full_name())
            personalized = personalized.replace('{army_no}', user.army_no or '')
            personalized = personalized.replace('{username}', user.username)

            for ch in channels:
                recipient_row = BulkMessageRecipient.objects.create(
                    message=bm,
                    user=user,
                    delivered_via='email' if ch == 'email' else 'sms',
                    status='pending',
                )
                try:
                    if ch == 'email':
                        notify_user(user, personalized, 'email',
                                    subject=subject or 'MSICT OLMS Notice',
                                    message_type='bulk_message')
                    else:
                        notify_user(user, personalized, 'sms',
                                    message_type='bulk_message')
                    recipient_row.status = 'sent'
                    recipient_row.delivered_at = timezone.now()
                    recipient_row.save(update_fields=['status', 'delivered_at'])
                    sent_count += 1
                except Exception as e:
                    recipient_row.status = 'failed'
                    recipient_row.error_message = str(e)[:500]
                    recipient_row.save(update_fields=['status', 'error_message'])
                    failed_count += 1

        bm.sent_at = now
        bm.total_sent = sent_count
        bm.total_failed = failed_count
        bm.save(update_fields=['sent_at', 'total_sent', 'total_failed'])

        log_audit(request.user,
                  f"Bulk message sent: {sent_count}/{recipient_count} delivered, {failed_count} failed — '{subject or '(no subject)'}'",
                  request)
        messages.success(request,
                         f'Message sent to {recipient_count} users. {sent_count} delivered, {failed_count} failed.')
        return redirect('bulk_message')

    # ── GET: show form + history ───────────────────────────────────
    # Preview count based on GET filters
    roles_get = request.GET.getlist('roles')
    member_types_get = request.GET.getlist('member_types')

    preview_qs = _build_recipient_qs(roles_get, member_types_get)
    preview_count = preview_qs.count()

    # Build user lists grouped by role for custom selection
    members_list = OLMSUser.objects.filter(
        is_active=True, role='member'
    ).exclude(role='admin').order_by('first_name', 'surname')
    guests_list = OLMSUser.objects.filter(
        is_active=True, role='guest'
    ).order_by('first_name', 'surname')
    librarians_list = OLMSUser.objects.filter(
        is_active=True, role='librarian'
    ).order_by('first_name', 'surname')

    # Message history
    message_history = BulkMessage.objects.filter(
        status__in=['sent', 'failed']
    ).select_related('sent_by').order_by('-sent_at')[:20]

    # Drafts
    drafts = BulkMessage.objects.filter(status='draft').select_related('sent_by').order_by('-created_at')[:10]

    return render(request, 'accounts/bulk_message.html', {
        'preview_count': preview_count,
        'roles_get': roles_get,
        'member_types_get': member_types_get,
        'message_history': message_history,
        'drafts': drafts,
        'members_list': members_list,
        'guests_list': guests_list,
        'librarians_list': librarians_list,
    })


# ----------------------------------------------------------------------
# Account Approval View — Librarian approves pending registration
# ----------------------------------------------------------------------
@login_required
@librarian_required
@require_POST
# ----------------------------------------------------------------------
# View ya Idhinisha Akaunti — Mtunzaji anaidhinisha akaunti iliyosajiliwa
# ----------------------------------------------------------------------
def approve_account_view(request, user_id):
    """Approve a pending user account and send credentials."""
    user = get_object_or_404(OLMSUser, pk=user_id, role='member', registration_status='pending')
    
    # Generate initial password from army number
    initial_password = OLMSUser.generate_initial_password(user.army_no)
    user.set_password(initial_password)
    
    # Update account status
    user.registration_status = 'approved'
    user.is_active = True
    user.approved_by = request.user
    user.approved_at = timezone.now()
    
    # Generate card number if not exists
    if not user.card_no:
        user.card_no = VirtualCard.generate_card_no()
    user.save()
    
    # Generate virtual card (QR, barcode)
    card = generate_virtual_card(user)
    card_no = user.card_no
    
    # Log audit
    log_audit(request.user, f"Approved account for {user.get_full_name()} (Army No: {user.army_no})", request)
    
    # Send websocket notification to librarians (non-blocking)
    try:
        send_account_status_update(user, 'approved')
    except Exception as e:
        print(f"WebSocket notification error: {e}")
    
    # Send approval notification with credentials
    login_url = request.build_absolute_uri('/login/')
    subject = "MSICT OLMS — Account Approved – Your Credentials"
    body = (
        f"Dear {user.get_full_name()},\n\n"
        f"Your MSICT Library (OLMS) account has been approved. Below are your login credentials:\n\n"
        f"  Full Name    : {user.get_full_name()}\n"
        f"  Army No      : {user.army_no}\n"
        f"  Member Type  : {dict(OLMSUser.MEMBER_TYPE_CHOICES).get(user.member_type, user.member_type).title() if user.member_type else 'Member'}\n"
        f"  Username     : {user.username}\n"
        f"  Password     : {initial_password}\n"
        f"  Library Card : {card_no}\n"
        f"  Login URL    : {login_url}\n\n"
        f"IMPORTANT: Change your password immediately on first login.\n"
        f"  Steps: Login → Dashboard → Change Password\n\n"
        f"Keep this message confidential. Do not share your credentials with anyone.\n\n"
        f"Regards,\nMSICT Library Administration"
    )
    sms_body = (
        f"MSICT OLMS: Approved! "
        f"User:{user.username} Pwd:{initial_password} Card:{card_no}. "
        f"Change pwd on 1st login. /login/"
    )
    
    sms_ok = notify_user(user, sms_body, 'sms', priority='high', is_security_alert=True)
    email_ok = notify_user(user, body, 'email', subject=subject)
    
    if sms_ok.status == 'sent' and email_ok.status == 'sent':
        messages.success(request, f'Account for {user.get_full_name()} approved. Credentials sent via email and SMS.')
    elif sms_ok.status == 'sent':
        messages.warning(request, f'Account approved. SMS sent, but email delivery failed.')
    elif email_ok.status == 'sent':
        messages.warning(request, f'Account approved. Email sent, but SMS delivery failed.')
    else:
        messages.warning(request, f'Account approved, but both SMS and email failed. Inform the user manually.')
    
    return redirect('public_registrations')


# ----------------------------------------------------------------------
# Account Rejection View — Librarian rejects pending registration
# ----------------------------------------------------------------------
@login_required
@librarian_required
@require_POST
# ----------------------------------------------------------------------
# View ya Kataa Akaunti — Mtunzaji anakataa akaunti iliyosajiliwa
# ----------------------------------------------------------------------
def reject_account_view(request, user_id):
    """Reject a pending user account with reason."""
    user = get_object_or_404(OLMSUser, pk=user_id, role='member', registration_status='pending')
    
    cancelled_reason = request.POST.get('cancelled_reason', '').strip()
    if not cancelled_reason:
        messages.error(request, 'Cancellation reason is required.')
        return redirect('public_registrations')
    
    # Update account status to rejected (not cancelled)
    user.registration_status = 'rejected'
    user.cancelled_reason = cancelled_reason
    user.save()
    
    # Log audit
    log_audit(request.user, f"Rejected account for {user.get_full_name()} (Army No: {user.army_no}). Reason: {cancelled_reason}", request)
    
    # Send websocket notification to librarians (non-blocking)
    try:
        send_account_status_update(user, 'rejected')
    except Exception as e:
        print(f"WebSocket notification error: {e}")
    
    # Send rejection notification
    subject = "MSICT OLMS — Registration Request Rejected"
    body = (
        f"Dear {user.get_full_name()},\n\n"
        f"Your MSICT Library (OLMS) registration request has been rejected.\n\n"
        f"  Full Name    : {user.get_full_name()}\n"
        f"  Army No      : {user.army_no}\n"
        f"  Reason       : {cancelled_reason}\n\n"
        f"If you believe this is an error, please visit the library administration for assistance.\n\n"
        f"Regards,\nMSICT Library Administration"
    )
    sms_body = (
        f"MSICT OLMS: Reg rejected ({user.army_no}). "
        f"Reason: {cancelled_reason[:60]}{'...' if len(cancelled_reason) > 60 else ''}. "
        f"Visit library for info."
    )
    
    sms_ok = notify_user(user, sms_body, 'sms')
    email_ok = notify_user(user, body, 'email', subject=subject)
    
    if sms_ok.status == 'sent' or email_ok.status == 'sent':
        messages.success(request, f'Account for {user.get_full_name()} has been cancelled. Notification sent.')
    else:
        messages.warning(request, f'Account cancelled, but notification delivery failed.')
    
    return redirect('public_registrations')


# ----------------------------------------------------------------------
# Public Registrations View — Librarian manages self-registrations
# ----------------------------------------------------------------------
@login_required
@librarian_required
# ----------------------------------------------------------------------
# View ya Usajili wa Umma — Mtunzaji anaona orodha ya waliyosajili
# ----------------------------------------------------------------------
def public_registrations_view(request):
    """View all public self-registrations — pending and rejected users shown together."""

    qs = OLMSUser.objects.filter(
        role='member', registration_status__in=['pending', 'rejected']
    ).select_related('rank').order_by('-created_at')

    # Count for stats
    pending_count = OLMSUser.objects.filter(role='member', registration_status='pending').count()
    rejected_count = OLMSUser.objects.filter(role='member', registration_status='rejected').count()
    approved_count = OLMSUser.objects.filter(role='member', registration_status='approved').count()

    mark_badge_viewed(request.user, 'pending_registrations')
    return render(request, 'accounts/public_registrations.html', {
        'registrations': qs,
        'pending_count': pending_count,
        'rejected_count': rejected_count,
        'approved_count': approved_count,
    })


# ----------------------------------------------------------------------
# Rejected Applications View — Librarian manages rejected registrations
# ----------------------------------------------------------------------
@login_required
@librarian_required
def rejected_registrations_view(request):
    """View all rejected registrations with rollback, edit, and delete options."""
    
    qs = OLMSUser.objects.filter(role='member', registration_status='rejected').select_related('rank').order_by('-created_at')
    
    return render(request, 'accounts/rejected_registrations.html', {
        'rejected_users': qs,
    })


# ----------------------------------------------------------------------
# Rollback Registration View — Librarian can rollback rejected to approved
# ----------------------------------------------------------------------
@login_required
@librarian_required
def rollback_registration_view(request, user_id):
    """Rollback a rejected registration to approved (acts exactly like approve)."""
    if request.method != 'POST':
        messages.error(request, 'Invalid request. Use the Rollback button to approve a rejected application.')
        return redirect('public_registrations')

    user = get_object_or_404(OLMSUser, pk=user_id, role='member', registration_status='rejected')
    
    # Generate initial password from army number
    initial_password = OLMSUser.generate_initial_password(user.army_no)
    user.set_password(initial_password)
    
    # Update account status to approved
    user.registration_status = 'approved'
    user.is_active = True
    user.approved_by = request.user
    user.approved_at = timezone.now()
    user.cancelled_reason = ''  # Clear rejection reason
    
    # Generate card number if not exists
    if not user.card_no:
        user.card_no = VirtualCard.generate_card_no()
    user.save()
    
    # Generate virtual card (QR, barcode) if not exists
    if not hasattr(user, 'virtual_card'):
        card = generate_virtual_card(user)
    card_no = user.card_no
    
    # Log audit
    log_audit(request.user, f"Rolled back and approved account for {user.get_full_name()} (Army No: {user.army_no})", request)
    
    # Send approval notification with credentials
    login_url = request.build_absolute_uri('/login/')
    subject = "MSICT OLMS — Account Approved – Your Credentials"
    body = (
        f"Dear {user.get_full_name()},\n\n"
        f"Your MSICT Library (OLMS) account has been approved after review. Below are your login credentials:\n\n"
        f"  Full Name    : {user.get_full_name()}\n"
        f"  Army No      : {user.army_no}\n"
        f"  Member Type  : {dict(OLMSUser.MEMBER_TYPE_CHOICES).get(user.member_type, user.member_type).title() if user.member_type else 'Member'}\n"
        f"  Username     : {user.username}\n"
        f"  Password     : {initial_password}\n"
        f"  Library Card : {card_no}\n"
        f"  Login URL    : {login_url}\n\n"
        f"IMPORTANT: Change your password immediately on first login.\n"
        f"  Steps: Login → Dashboard → Change Password\n\n"
        f"Keep this message confidential. Do not share your credentials with anyone.\n\n"
        f"Regards,\nMSICT Library Administration"
    )
    sms_body = (
        f"MSICT OLMS: Approved! "
        f"User:{user.username} Pwd:{initial_password} Card:{card_no}. "
        f"Change pwd on 1st login. /login/"
    )
    
    sms_ok = notify_user(user, sms_body, 'sms')
    email_ok = notify_user(user, body, 'email', subject=subject)
    
    if sms_ok.status == 'sent' and email_ok.status == 'sent':
        messages.success(request, f'Account for {user.get_full_name()} rolled back and approved. Credentials sent.')
    else:
        messages.warning(request, f'Account rolled back and approved, but notification delivery failed.')
    
    return redirect('public_registrations')


# ----------------------------------------------------------------------
# Delete Registration View — Librarian permanently deletes a pending or rejected registration
# ----------------------------------------------------------------------
@login_required
@librarian_required
def delete_user_view(request, user_id):
    """Permanently delete a registration or approved member account."""
    if request.method != 'POST':
        messages.error(request, 'Invalid request. Use the delete button.')
        return redirect('public_registrations')

    user = get_object_or_404(OLMSUser, pk=user_id)
    full_name = user.get_full_name()
    army_no = user.army_no
    reg_status = user.registration_status

    # Librarians can delete members and guest accounts (not admins/librarians)
    target_is_guest = getattr(user, 'is_guest', False) or user.role == 'guest'
    if request.user.role == 'librarian' and user.role not in ('member',) and not target_is_guest:
        messages.error(request, 'Librarians can only delete member or guest accounts.')
        return redirect('user_list')

    # Delete virtual card if exists
    try:
        if hasattr(user, 'virtual_card'):
            user.virtual_card.delete()
    except Exception:
        pass

    user.delete()
    log_audit(request.user, f"Deleted {reg_status} account for {full_name} (Army No: {army_no})", request)
    messages.success(request, f'Account for {full_name} has been permanently deleted.')

    # Redirect based on original status / role
    if target_is_guest:
        return redirect('guest_manage')
    if reg_status in ('pending', 'rejected'):
        return redirect('public_registrations')
    return redirect('user_list')


# Decorator: inazuia ufikiaji kwa watu ambao si admin peke yake
def admin_required(func):
    from functools import wraps
    @wraps(func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated or request.user.role != 'admin':
            messages.error(request, 'Access denied. Admin only.')
            return redirect('dashboard')
        return func(request, *args, **kwargs)
    return wrapper


@login_required
# ----------------------------------------------------------------------
# View ya Orodha ya Watumiaji — Mtunzaji anaona watumiaji wote
# ----------------------------------------------------------------------
def user_list_view(request):
    if request.user.role not in ['admin', 'librarian']:
        messages.error(request, 'Access denied.')
        return redirect('dashboard')
        
    query = request.GET.get('q', '')
    status = request.GET.get('status', '')
    role_filter = request.GET.get('role', '')
    if status == 'locked':
        # Show ALL locked non-admin users: inactive OR pending (unapproved)
        users = OLMSUser.objects.exclude(role='admin').filter(
            Q(is_active=False) | Q(registration_status='pending')
        ).distinct()
    else:
        users = OLMSUser.objects.exclude(role='admin').filter(registration_status='approved')
    users = users.select_related('virtual_card', 'rank').order_by('-id')

    if query:
        users = users.filter(
            Q(username__icontains=query) | Q(army_no__icontains=query) |
            Q(first_name__icontains=query) | Q(surname__icontains=query)
        )
    if role_filter:
        users = users.filter(role=role_filter)

    if status == 'locked':
        mark_badge_viewed(request.user, 'locked_users')
    paginator = Paginator(users, 25)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    return render(request, 'accounts/user_list.html', {
        'users': page_obj,
        'page_obj': page_obj,
        'query': query,
        'status': status,
    })


@login_required
@librarian_required
@require_POST
# ----------------------------------------------------------------------
# View ya Hatua za Mtumiaji — Zuia/fungua akaunti (lock/unlock)
# ----------------------------------------------------------------------
def user_action_view(request, user_id, action):
    user_obj = get_object_or_404(OLMSUser, pk=user_id)
    is_admin = request.user.role == 'admin'
    is_librarian = request.user.role == 'librarian'

    # Librarians may lock/unlock guest accounts; only admins for members/staff
    target_is_guest = getattr(user_obj, 'is_guest', False) or user_obj.role == 'guest'

    if action == 'lock':
        if not is_admin and not (is_librarian and target_is_guest):
            messages.error(request, 'Only admins can lock non-guest accounts.')
            return redirect('user_list')
        user_obj.is_active = False
        user_obj.save(update_fields=['is_active'])
        log_audit(request.user, f"{request.user.role.capitalize()} manually locked account '{user_obj.username}'", request)
        messages.warning(request, f"Account '{user_obj.username}' locked.")

    elif action == 'unlock':
        if not is_admin and not (is_librarian and target_is_guest):
            messages.error(request, 'Only admins can unlock non-guest accounts.')
            return redirect('user_list')
        user_obj.is_active = True
        user_obj.failed_attempts = 0
        user_obj.save(update_fields=['is_active', 'failed_attempts'])
        unlock_msg = (
            f"MSICT OLMS: Your account '{user_obj.username}' has been UNLOCKED by the administrator. "
            f"You may visit login page to login again. If you did not request this, contact the admin immediately."
        )
        notify_user(user_obj, unlock_msg, 'sms')
        notify_user(user_obj, unlock_msg, 'email', subject='MSICT OLMS – Account Unlocked')
        log_audit(request.user, f"{request.user.role.capitalize()} manually unlocked account '{user_obj.username}'", request)
        messages.success(request, f"Account '{user_obj.username}' unlocked. User notified via SMS and email.")

    return redirect('user_list')


@login_required
@librarian_required
# ----------------------------------------------------------------------
# View ya Maelezo ya Mtumiaji — Anaona maelezo kamili ya mtumiaji
# ----------------------------------------------------------------------
def user_detail_view(request, user_id):
    from circulation.models import BorrowingTransaction, Fine
    user_obj = get_object_or_404(OLMSUser, pk=user_id)
    active_borrows = BorrowingTransaction.objects.filter(user=user_obj, status='borrowed').select_related('copy__book').order_by('-borrow_date')
    overdue = BorrowingTransaction.objects.filter(user=user_obj, status='overdue').select_related('copy__book').order_by('-due_date')
    unpaid_fines = Fine.objects.filter(transaction__user=user_obj, paid=False).select_related('transaction__copy__book')
    borrow_history = BorrowingTransaction.objects.filter(user=user_obj).select_related('copy__book').order_by('-borrow_date')[:20]
    audit_logs = AuditLog.objects.filter(user=user_obj).order_by('-timestamp')[:20]
    try:
        virtual_card = user_obj.virtual_card
    except Exception:
        virtual_card = None
    return render(request, 'accounts/user_detail.html', {
        'user_obj': user_obj,
        'active_borrows': active_borrows,
        'overdue': overdue,
        'unpaid_fines': unpaid_fines,
        'borrow_history': borrow_history,
        'audit_logs': audit_logs,
        'virtual_card': virtual_card,
    })


@login_required
@librarian_required
# ----------------------------------------------------------------------
# View ya Unda Mtumiaji — Mtunzaji anaweka mtumiaji mpya
# ----------------------------------------------------------------------
def create_user_view(request):
    if request.method == 'POST':
        role = request.POST.get('role', 'member')
        member_type = request.POST.get('member_type') or None
        if role != 'member':
            member_type = None
        army_no = request.POST.get('army_no', '').strip()
        first_name = request.POST.get('first_name', '').strip()
        middle_name = request.POST.get('middle_name', '').strip()
        surname = request.POST.get('surname', '').strip()
        email = request.POST.get('email', '').strip()
        phone = request.POST.get('phone', '').strip()
        registration_no = request.POST.get('registration_no', '').strip() or None
        if member_type != 'student':
            registration_no = None
        rank_id = request.POST.get('rank_id') or None

        if not re.match(r'^(MTM|MT|PW|P)\s?\d+$', army_no):
            messages.error(request, 'Army number must start with MT, MTM, P, or PW followed by digits (e.g. MT 134513, MTM 456, P 789, PW 101).')
            return render(request, 'accounts/create_user.html')

        if OLMSUser.objects.filter(army_no=army_no).exists():
            messages.error(request, 'Army number already exists.')
            return render(request, 'accounts/create_user.html')

        if not re.match(r'^0\d{9}$', phone):
            messages.error(request, 'Phone number must be exactly 10 digits starting with 0 (e.g. 0712345678).')
            return render(request, 'accounts/create_user.html')

        username = OLMSUser.generate_username(role, member_type, surname, registration_no, first_name, middle_name)
        initial_password = OLMSUser.generate_initial_password(army_no)

        # Handle duplicate username by adding random variations
        if OLMSUser.objects.filter(username=username).exists():
            import random
            import string
            # Add random suffix until unique
            while OLMSUser.objects.filter(username=username).exists():
                suffix = ''.join(random.choices(string.ascii_lowercase, k=2))
                username = f"{username}{suffix}"

        from accounts.models import Rank as RankModel
        rank_obj = RankModel.objects.filter(pk=rank_id).first() if rank_id else None

        user = OLMSUser.objects.create_user(
            username=username,
            password=initial_password,
            army_no=army_no,
            first_name=first_name,
            middle_name=middle_name,
            surname=surname,
            email=email,
            phone=phone,
            role=role,
            member_type=member_type,
            registration_no=registration_no,
            rank=rank_obj,
            last_password_change=timezone.now(),
            registration_status='approved',
            is_active=True,
        )
        
        # Generate card number
        user.card_no = VirtualCard.generate_card_no()
        user.save()

        card = generate_virtual_card(user)
        card_no = user.card_no or 'N/A'

        role_label = dict(OLMSUser.ROLE_CHOICES).get(role, role).title()
        type_label = dict(OLMSUser.MEMBER_TYPE_CHOICES).get(member_type, '') if member_type else ''
        login_url = request.build_absolute_uri('/login/')

        subject = "MSICT OLMS — Your Account Credentials"
        body = (
            f"Dear {user.get_full_name()},\n\n"
            f"Your MSICT Library (OLMS) account has been created by the librarian. Below are your login details:\n\n"
            f"  Full Name    : {user.get_full_name()}\n"
            f"  Army No      : {army_no}\n"
            f"  Role         : {role_label}{(' — ' + type_label) if type_label else ''}\n"
            f"  Username     : {username}\n"
            f"  Password     : {initial_password}\n"
            f"  Library Card : {card_no}\n"
            f"  Login URL    : {login_url}\n\n"
            f"IMPORTANT: Change your password immediately on first login for security.\n"
            f"  Steps: Login → Dashboard → Change Password\n\n"
            f"Keep this message confidential. Do not share your credentials with anyone.\n\n"
            f"Regards,\nMSICT Library Administration"
        )
        sms_body = (
            f"MSICT OLMS: Acct created. "
            f"User:{username} Pwd:{initial_password} Card:{card_no}. "
            f"Change pwd on 1st login. /login/"
        )
        sms_ok = notify_user(user, sms_body, 'sms', priority='high', is_security_alert=True)
        email_ok = notify_user(user, body, 'email', subject=subject)
        log_audit(request.user, f"Librarian '{request.user.username}' created user '{username}' (email={'sent' if email_ok.status == 'sent' else 'FAILED'}, sms={'sent' if sms_ok.status == 'sent' else 'FAILED'})", request)
        log_audit(request.user, f"Librarian '{request.user.username}' created user '{username}'", request)

        messages.success(request, f"User '{username}' created. Password: {initial_password}")
        request.session['new_user_credentials'] = {'username': username, 'password': initial_password, 'name': user.get_full_name()}
        return redirect('user_list')

    from accounts.models import Rank as RankModel
    return render(request, 'accounts/create_user.html', {'ranks': RankModel.objects.all()})


@login_required
@librarian_required
# ----------------------------------------------------------------------
# View ya Hariri Mtumiaji — Mtunzaji anahariri maelezo ya mtumiaji
# ----------------------------------------------------------------------
def edit_user_view(request, user_id):
    user_obj = get_object_or_404(OLMSUser, pk=user_id)
    is_admin = request.user.role == 'admin'

    if request.method == 'POST':
        new_phone = request.POST.get('phone', user_obj.phone).strip()
        if not re.match(r'^0\d{9}$', new_phone):
            messages.error(request, 'Phone number must be exactly 10 digits starting with 0 (e.g. 0712345678).')
            return redirect('edit_user', user_id=user_obj.pk)
        user_obj.phone = new_phone
        user_obj.email = request.POST.get('email', user_obj.email)
        user_obj.first_name = request.POST.get('first_name', user_obj.first_name)
        user_obj.middle_name = request.POST.get('middle_name', user_obj.middle_name)
        user_obj.surname = request.POST.get('surname', user_obj.surname)
        user_obj.army_no = request.POST.get('army_no', user_obj.army_no)
        rank_id = request.POST.get('rank_id') or None
        from accounts.models import Rank as RankModel
        user_obj.rank = RankModel.objects.filter(pk=rank_id).first() if rank_id else None

        # Role editing — only admins can change roles
        new_role = request.POST.get('role', '').strip()
        if new_role and is_admin:
            if new_role in dict(OLMSUser.ROLE_CHOICES).keys():
                # Prevent admin from removing their own admin role (avoid lockout)
                if user_obj.pk == request.user.pk and new_role != 'admin':
                    messages.warning(request, 'You cannot change your own admin role.')
                else:
                    user_obj.role = new_role
                    # Non-members don't have member_type
                    if new_role != 'member':
                        user_obj.member_type = None
        elif new_role and not is_admin:
            messages.warning(request, 'Only admins can change user roles.')

        # Member type editing — admins and librarians can change
        new_member_type = request.POST.get('member_type', '').strip() or None
        if user_obj.role == 'member':
            if new_member_type and new_member_type in dict(OLMSUser.MEMBER_TYPE_CHOICES).keys():
                user_obj.member_type = new_member_type
            elif not new_member_type:
                user_obj.member_type = None

        new_reg_no = request.POST.get('registration_no', '').strip() or None
        # Update username for students if registration_no changed
        if user_obj.member_type == 'student' and new_reg_no and new_reg_no != user_obj.registration_no:
            user_obj.username = new_reg_no
        user_obj.registration_no = new_reg_no

        user_obj.save()
        log_audit(request.user, f"Edited user '{user_obj.username}' (Role: {user_obj.role}, MemberType: {user_obj.member_type or '—'})", request)
        messages.success(request, 'User updated successfully.')
        return redirect('user_list')

    from accounts.models import Rank as RankModel
    return render(request, 'accounts/edit_user.html', {
        'user_obj': user_obj,
        'ranks': RankModel.objects.all(),
        'is_admin': is_admin,
        'role_choices': OLMSUser.ROLE_CHOICES,
        'member_type_choices': OLMSUser.MEMBER_TYPE_CHOICES,
    })


@login_required
@librarian_required
@require_POST
# ----------------------------------------------------------------------
# View ya Weka Upya Nywila ya Mtumiaji — Mtunzaji anaweka upya nywila
# ----------------------------------------------------------------------
def reset_user_password_view(request, user_id):
    """
    Admin/librarian-triggered password reset.

    Redirects to the normal OTP-based password reset flow (forgot_password → verify_otp → reset_password)
    instead of generating a temporary password. The target user's identifier is stored in session
    and pre-filled on the forgot_password page.
    """
    user_obj = get_object_or_404(OLMSUser, pk=user_id)

    # Use army_no if available, otherwise email
    identifier = user_obj.army_no if user_obj.army_no else user_obj.email

    # Store the identifier in session so forgot_password can pre-fill it
    request.session['reset_for_user_identifier'] = identifier
    log_audit(request.user, f"Initiated password reset for user '{user_obj.username}' via OTP flow", request)
    messages.info(request, f"Password reset initiated for {user_obj.username}. The user will receive an OTP to complete the reset.")
    return redirect('forgot_password')


@login_required
@admin_required
# ----------------------------------------------------------------------
# View ya Dashboard ya Msimamizi — Dashboard ya msimamizi wa mfumo
# ----------------------------------------------------------------------
def admin_dashboard_view(request):
    from circulation.models import BorrowingTransaction, Fine
    from django.db.models.functions import TruncDay
    from catalog.models import Book, BookCopy
    from collections import defaultdict
    
    # Check if user is admin
    if request.user.role != 'admin':
        messages.error(request, 'Access denied. Admin privileges required.')
        return redirect('dashboard')

    # All non-admin users (includes cancelled/pending) so locked users always show
    _all_users   = OLMSUser.objects.exclude(role='admin')
    total_users  = _all_users.count()
    active_users = _all_users.filter(is_active=True).count()
    # Locked = inactive OR unapproved (pending registration can't login either)
    locked_users = _all_users.filter(Q(is_active=False) | Q(registration_status='pending')).distinct().count()

    overdue_count = BorrowingTransaction.objects.filter(
        status='overdue'
    ).exclude(
        copy__copy_type='softcopy', copy__access_type='borrow'
    ).count()
    currently_borrowed = BorrowingTransaction.objects.filter(status='borrowed').count()
    # Total active loans = borrowed + overdue (denominator for overdue rate)
    total_borrows = currently_borrowed + overdue_count
    unpaid_fines = sum(fine.remaining_balance for fine in Fine.objects.filter(paid=False))

    # Analytics - Users by role
    users_by_role = list(OLMSUser.objects.values('role').annotate(count=Count('id')))
    
    # Analytics - Most borrowed books
    most_borrowed = BorrowingTransaction.objects.values('copy__book__title').annotate(
        total=Count('id')
    ).order_by('-total')[:10]

    recent_logs = AuditLog.objects.select_related('user').order_by('-timestamp')[:20]

    # Find users currently suspended (within suspend_duration) or permanently locked
    _suspend_at = int(SystemPreference.get('SUSPEND_ATTEMPTS', 3) or 3)
    _suspend_dur = int(SystemPreference.get('SUSPEND_DURATION_MINUTES', 10) or 10)
    _lock_at = int(SystemPreference.get('MAX_LOGIN_ATTEMPTS', 6) or 6)
    _cutoff = timezone.now() - timedelta(minutes=_suspend_dur)
    _suspended_unames = set(
        LoginAttempt.objects.filter(status='failed', timestamp__gte=_cutoff)
        .values_list('username', flat=True)
    )
    recent_suspended = OLMSUser.objects.filter(
        Q(
            failed_attempts__gte=_suspend_at,
            username__in=_suspended_unames,
            is_active=True,
        ) | Q(
            is_active=False,
            failed_attempts__gte=_lock_at,
        )
    ).select_related('virtual_card').order_by('-failed_attempts', '-created_at')[:5]

    # All users with ANY failed login attempts — for suspicious activity alert panel
    suspicious_activity_users = OLMSUser.objects.filter(
        failed_attempts__gte=1
    ).exclude(role='admin').select_related('rank').order_by('-failed_attempts', '-created_at')

    # Locked accounts detail — inactive OR unapproved (pending) non-admin users
    locked_accounts_detail = (
        OLMSUser.objects.exclude(role='admin')
        .filter(Q(is_active=False) | Q(registration_status='pending'))
        .distinct()
        .select_related('rank', 'virtual_card')
        .order_by('registration_status', '-failed_attempts', 'surname', 'first_name')
    )

    # Unapproved (pending) registrations
    unapproved_accounts = (
        OLMSUser.objects.exclude(role='admin')
        .filter(registration_status='pending')
        .select_related('rank')
        .order_by('-created_at')
    )

    # Security - System Alerts (exclude OTP and password reset messages)
    from circulation.models import Notification
    security_alerts = Notification.objects.filter(
        is_security_alert=True
    ).exclude(
        message__icontains='OTP'
    ).exclude(
        message__icontains='password reset'
    ).order_by('-created_at')[:5]

    # Suspicious IPs (last 1 hour, >=5 failed attempts)
    window_1h = timezone.now() - timedelta(hours=1)
    suspicious_ips_qs = (
        LoginAttempt.objects.filter(status='failed', timestamp__gte=window_1h)
        .values('ip_address')
        .annotate(total=Sum('attempt_count'), last_attempt=Max('timestamp'))
        .filter(total__gte=5)
        .order_by('-total')[:5]
    )
    suspicious_ips = []
    for row in suspicious_ips_qs:
        usernames = list(
            LoginAttempt.objects.filter(
                status='failed', timestamp__gte=window_1h, ip_address=row['ip_address']
            ).values_list('username', flat=True).distinct()
        )
        suspicious_ips.append({
            'ip_address': row['ip_address'],
            'total': row['total'],
            'last_attempt': row['last_attempt'],
            'usernames': usernames,
            'user_count': len(usernames),
        })

    # Additional Analytics
    # Monthly borrowing stats for the last 6 months
    monthly_borrows = defaultdict(int)
    for i in range(6):
        month = datetime.now() - timedelta(days=30*i)
        month_key = month.strftime('%b %Y')
        count = BorrowingTransaction.objects.filter(
            borrow_date__month=month.month,
            borrow_date__year=month.year
        ).count()
        monthly_borrows[month_key] = count

    # Calculate max borrows for percentage
    max_borrows = max(monthly_borrows.values()) if monthly_borrows else 1
    monthly_borrows_with_pct = {}
    for month, count in monthly_borrows.items():
        monthly_borrows_with_pct[month] = {
            'count': count,
            'percentage': int((count / max_borrows) * 100) if max_borrows > 0 else 0
        }

    # Category distribution with percentages
    from catalog.models import Category
    category_stats = list(Book.objects.values('category__name').annotate(
        count=Count('id')
    ).order_by('-count')[:5])
    total_category_books = sum(stat['count'] for stat in category_stats) if category_stats else 1
    for stat in category_stats:
        stat['percentage'] = int((stat['count'] / total_category_books) * 100)

    # Copy type distribution
    copy_type_stats = list(BookCopy.objects.values('copy_type').annotate(
        count=Count('id')
    ))

    # Total books and copies
    total_books = Book.objects.count()
    total_copies = BookCopy.objects.count()
    available_copies = BookCopy.objects.filter(status='available').count()

    # Fine statistics
    total_fines_amount = sum(fine.amount for fine in Fine.objects.all())
    paid_fines_amount = sum(fine.amount_paid for fine in Fine.objects.all())

    # Guest analytics
    guest_sessions_qs = GuestSession.objects.all()
    guest_total_visits = guest_sessions_qs.count()
    guest_total_revenue = guest_sessions_qs.aggregate(
        total=Sum('amount_paid')
    )['total'] or 0
    guest_avg_duration = guest_sessions_qs.aggregate(
        avg=Sum('duration_hours')
    )['avg'] or 0
    if guest_total_visits > 0:
        guest_avg_duration = round(float(guest_avg_duration) / guest_total_visits, 2)
    else:
        guest_avg_duration = 0
    guest_active_sessions = guest_sessions_qs.filter(status__in=['active', 'renewed']).count()
    guest_total_users = OLMSUser.objects.filter(is_guest=True).count()
    guest_recent_sessions = guest_sessions_qs.select_related('user').order_by('-sign_in_time')[:10]

    # Revenue / Financial summary
    from reports.views import _revenue_summary
    revenue = _revenue_summary()

    # ── Chart data (JSON for Chart.js) ───────────────────────────────
    import json as _json

    # Security: login attempts last 7 days (success vs failed)
    login_chart_labels = []
    login_success = []
    login_failed = []
    for i in range(6, -1, -1):
        day = datetime.now() - timedelta(days=i)
        day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        login_chart_labels.append(day.strftime('%a'))
        login_success.append(LoginAttempt.objects.filter(
            status='success', timestamp__gte=day_start, timestamp__lt=day_end
        ).count())
        login_failed.append(LoginAttempt.objects.filter(
            status='failed', timestamp__gte=day_start, timestamp__lt=day_end
        ).count())

    security_chart_data = _json.dumps({
        'labels': login_chart_labels,
        'success': login_success,
        'failed': login_failed,
    })

    # User role doughnut
    role_chart_data = _json.dumps({
        'labels': [r['role'].title() for r in users_by_role],
        'values': [r['count'] for r in users_by_role],
    })

    # Revenue breakdown doughnut
    revenue_chart_data = _json.dumps({
        'labels': ['Overdue', 'Link Fee', 'Guest Fee', 'Damage', 'Loss'],
        'values': [
            float(revenue['overdue']),
            float(revenue['link_fee']),
            float(revenue['guest_fee']),
            float(revenue.get('damage', 0)),
            float(revenue['loss']),
        ],
    })

    # Monthly borrowing bar chart
    borrow_chart_data = _json.dumps({
        'labels': list(monthly_borrows_with_pct.keys()),
        'values': [v['count'] for v in monthly_borrows_with_pct.values()],
    })

    # Copy status distribution
    copy_status_data = _json.dumps({
        'labels': ['Available', 'Borrowed', 'Reserved', 'Lost', 'Damaged'],
        'values': [
            BookCopy.objects.filter(status='available').count(),
            BookCopy.objects.filter(status='borrowed').count(),
            BookCopy.objects.filter(status='reserved').count(),
            BookCopy.objects.filter(status='lost').count(),
            BookCopy.objects.filter(status='damaged').count(),
        ],
    })

    context = {
        'total_users': total_users,
        'active_users': active_users,
        'locked_users': locked_users,
        'overdue_count': overdue_count,
        'currently_borrowed': currently_borrowed,
        'total_borrows': total_borrows,
        'unpaid_fines': unpaid_fines,
        'users_by_role': users_by_role,
        'most_borrowed': most_borrowed,
        'recent_logs': recent_logs,
        'suspicious_ips': suspicious_ips,
        'recent_suspended': recent_suspended,
        'locked_accounts_detail': locked_accounts_detail,
        'unapproved_accounts': unapproved_accounts,
        'security_alerts': security_alerts,
        'suspicious_activity_users': suspicious_activity_users,
        'monthly_borrows': monthly_borrows_with_pct,
        'category_stats': category_stats,
        'copy_type_stats': copy_type_stats,
        'total_books': total_books,
        'total_copies': total_copies,
        'available_copies': available_copies,
        'total_fines_amount': total_fines_amount,
        'paid_fines_amount': paid_fines_amount,
        'guest_total_visits': guest_total_visits,
        'guest_total_revenue': guest_total_revenue,
        'guest_avg_duration': guest_avg_duration,
        'guest_active_sessions': guest_active_sessions,
        'guest_total_users': guest_total_users,
        'guest_recent_sessions': guest_recent_sessions,
        'revenue_overdue': revenue['overdue'],
        'revenue_link_fee': revenue['link_fee'],
        'revenue_guest_fee': revenue['guest_fee'],
        'revenue_damage': revenue.get('damage', 0),
        'revenue_loss': revenue['loss'],
        'revenue_total': revenue['total_revenue'],
        'revenue_net': revenue['net_revenue'],
        'security_chart_data': security_chart_data,
        'role_chart_data': role_chart_data,
        'revenue_chart_data': revenue_chart_data,
        'borrow_chart_data': borrow_chart_data,
        'copy_status_data': copy_status_data,
    }
    return render(request, 'accounts/admin_dashboard.html', context)


@login_required
@admin_required
# ----------------------------------------------------------------------
# View ya Shughuli za Tuhuma — Anaona jaribio zilizoshindwa za kuingia
# ----------------------------------------------------------------------
def suspicious_activity_view(request):
    window_24h = timezone.now() - timedelta(days=1)

    known_usernames = set(OLMSUser.objects.values_list('username', flat=True))

    # Build lookup map keyed by username, email, and phone so login attempts
    # using email or phone can be resolved to the actual user's info.
    user_info_map = {}
    for u in OLMSUser.objects.values('username', 'email', 'phone', 'role', 'member_type', 'is_guest'):
        info = {'role': u['role'], 'member_type': u['member_type'], 'is_guest': u['is_guest']}
        user_info_map[u['username']] = info
        if u['email']:
            user_info_map[u['email']] = info
            known_usernames.add(u['email'])
        if u['phone']:
            user_info_map[u['phone']] = info
            known_usernames.add(u['phone'])

    # Suspicious IPs: use configurable suspend_duration window and suspend_at threshold
    # so that suspended users' IPs appear while suspended and disappear when suspension expires
    suspend_at = int(SystemPreference.get('SUSPEND_ATTEMPTS', 3) or 3)
    suspend_duration = int(SystemPreference.get('SUSPEND_DURATION_MINUTES', 10) or 10)
    suspicious_window = timezone.now() - timedelta(minutes=suspend_duration)
    suspicious_ips_qs = (
        LoginAttempt.objects.filter(status='failed', timestamp__gte=suspicious_window)
        .values('ip_address')
        .annotate(total=Sum('attempt_count'), last_attempt=Max('timestamp'))
        .filter(total__gte=suspend_at)
        .order_by('-total')
    )

    suspicious_ips = []
    for row in suspicious_ips_qs:
        per_user = (
            LoginAttempt.objects.filter(
                status='failed', timestamp__gte=suspicious_window, ip_address=row['ip_address']
            )
            .values('username')
            .annotate(
                user_fails=Sum('attempt_count'),
                user_last=Max('timestamp'),
            )
            .order_by('-user_fails')
        )
        for urow in per_user:
            uname = urow['username'] or '(empty)'
            info = user_info_map.get(uname, {})
            is_guest = info.get('is_guest', False)
            role = info.get('role', '')
            if is_guest and not role:
                role = 'guest'
            suspicious_ips.append({
                'ip_address': row['ip_address'],
                'ip_total': row['total'],
                'ip_last_attempt': row['last_attempt'],
                'username': uname,
                'user_fails': urow['user_fails'],
                'user_last_attempt': urow['user_last'],
                'is_known': uname in known_usernames,
                'role': role,
                'member_type': info.get('member_type', '') or '',
                'is_guest': is_guest,
            })

    # Group failed logins by username + IP to avoid duplicate rows
    failed_logins_qs = (
        LoginAttempt.objects.filter(status='failed', timestamp__gte=window_24h)
        .values('username', 'ip_address')
        .annotate(
            total_attempts=Sum('attempt_count'),
            last_attempt=Max('timestamp'),
        )
        .order_by('-last_attempt')[:100]
    )

    # Build a map of (username, ip_address) → password_chars from the most recent attempt
    last_attempt_pws = {}
    for la in LoginAttempt.objects.filter(
        status='failed', timestamp__gte=window_24h
    ).order_by('-timestamp').values('username', 'ip_address', 'password_chars'):
        key = (la['username'], la['ip_address'])
        if key not in last_attempt_pws:
            last_attempt_pws[key] = la['password_chars']

    enriched_logins = []
    for row in failed_logins_qs:
        uname = row['username'] or '(empty)'
        info = user_info_map.get(uname, {})
        is_guest = info.get('is_guest', False)
        role = info.get('role', '')
        if is_guest and not role:
            role = 'guest'
        enriched_logins.append({
            'username': uname,
            'ip_address': row['ip_address'],
            'total_attempts': row['total_attempts'],
            'last_attempt': row['last_attempt'],
            'password_chars': last_attempt_pws.get((row['username'], row['ip_address'])),
            'role': role,
            'member_type': info.get('member_type', '') or '',
            'is_known': uname in known_usernames,
            'is_guest': is_guest,
        })

    # Get security alerts related to suspicious activity
    from circulation.models import Notification
    security_alerts = Notification.objects.filter(
        is_security_alert=True,
        message__icontains='suspicious'
    ).exclude(
        message__icontains='OTP'
    ).exclude(
        message__icontains='password reset'
    ).order_by('-created_at')[:10]

    users_with_failed_attempts = (
        OLMSUser.objects.filter(failed_attempts__gte=1)
        .exclude(role='admin')
        .select_related('rank', 'virtual_card')
        .order_by('-failed_attempts', '-created_at')
    )

    blocked_ips = set(BlockedIP.objects.values_list('ip_address', flat=True))
    for ip in suspicious_ips:
        ip['is_blocked'] = ip['ip_address'] in blocked_ips

    all_blocked_ips = BlockedIP.objects.select_related('blocked_by').order_by('-blocked_at')[:50]

    mark_badge_viewed(request.user, 'suspicious_ips')
    return render(request, 'accounts/suspicious_activity.html', {
        'failed_logins': enriched_logins,
        'suspicious_ips': suspicious_ips,
        'suspicious_ips_count': len(suspicious_ips),
        'recent_failed_logins_count': len(enriched_logins),
        'known_usernames': known_usernames,
        'security_alerts': security_alerts,
        'users_with_failed_attempts': users_with_failed_attempts,
        'all_blocked_ips': all_blocked_ips,
        'suspend_at': suspend_at,
        'suspend_duration': suspend_duration,
    })


@login_required
@admin_required
# ----------------------------------------------------------------------
# View ya Wanachama Waliofungiwa — Anaona wanachama waliozuiwa
# ----------------------------------------------------------------------
def suspended_members_view(request):
    # Read dynamic thresholds from system preferences
    suspend_at = int(SystemPreference.get('SUSPEND_ATTEMPTS', 3) or 3)
    suspend_duration = int(SystemPreference.get('SUSPEND_DURATION_MINUTES', 10) or 10)
    lock_at = int(SystemPreference.get('MAX_LOGIN_ATTEMPTS', 6) or 6)

    # Currently suspended: failed_attempts >= suspend_at AND last failed attempt within suspend_duration
    # Permanently locked: is_active=False AND failed_attempts >= lock_at
    cutoff = timezone.now() - timedelta(minutes=suspend_duration)

    # Get usernames with recent failed attempts (within suspension window)
    suspended_usernames = set(
        LoginAttempt.objects.filter(
            status='failed', timestamp__gte=cutoff
        ).values_list('username', flat=True)
    )

    suspended = OLMSUser.objects.filter(
        Q(
            failed_attempts__gte=suspend_at,
            username__in=suspended_usernames,
            is_active=True,
        ) | Q(
            is_active=False,
            failed_attempts__gte=lock_at,
        )
    ).select_related('virtual_card').order_by('-failed_attempts', '-created_at')

    # Get security alerts related to suspensions
    from circulation.models import Notification
    security_alerts = Notification.objects.filter(
        is_security_alert=True,
        message__icontains='suspended'
    ).exclude(
        message__icontains='OTP'
    ).exclude(
        message__icontains='password reset'
    ).order_by('-created_at')[:10]

    mark_badge_viewed(request.user, 'suspicious_users')
    return render(request, 'accounts/suspended_members.html', {
        'suspended': suspended,
        'security_alerts': security_alerts,
        'suspend_at': suspend_at,
        'suspend_duration': suspend_duration,
        'lock_at': lock_at,
    })


@login_required
@admin_required
@require_POST
# ----------------------------------------------------------------------
# View ya Fungua Akaunti — Msimamizi anafungua akaunti iliyozuiwa
# ----------------------------------------------------------------------
def unlock_account_view(request, user_id):
    user_obj = get_object_or_404(OLMSUser, pk=user_id)
    user_obj.is_active = True
    user_obj.failed_attempts = 0
    user_obj.save(update_fields=['is_active', 'failed_attempts'])
    unlock_msg = (
        f"MSICT OLMS: Your account '{user_obj.username}' has been UNLOCKED by the administrator. "
        f"You may visit now login to login again. If you did not request this, contact the admin immediately."
    )
    notify_user(user_obj, unlock_msg, 'sms', is_security_alert=True)
    notify_user(user_obj, unlock_msg, 'email', subject='MSICT OLMS – Account Unlocked', is_security_alert=True)
    log_audit(request.user, f"Admin '{request.user.username}' unlocked account '{user_obj.username}'", request)
    messages.success(request, f"Account '{user_obj.username}' unlocked. User notified via SMS and email.")
    return redirect('admin_dashboard')


@login_required
@admin_required
@require_POST
# ----------------------------------------------------------------------
# View ya Futa Tahadhari ya Usalama — Msimamizi anafuta tahadhari
# ----------------------------------------------------------------------
def delete_security_alert_view(request, pk):
    from circulation.models import Notification
    alert = get_object_or_404(Notification, pk=pk, priority='high')
    alert.delete()
    messages.success(request, 'Security alert dismissed.')
    return redirect('admin_dashboard')


@login_required
@admin_required
# ----------------------------------------------------------------------
# View ya Tahadhari za Usalama — Anaona tahadhari zote za usalama
# ----------------------------------------------------------------------
def security_alerts_view(request):
    from circulation.models import Notification
    type_filter = request.GET.get('type', '')
    alerts_qs = Notification.objects.filter(
        is_security_alert=True
    ).select_related('user').order_by('-created_at')
    if type_filter:
        alerts_qs = alerts_qs.filter(message_type=type_filter)
    alert_types = (
        Notification.objects.filter(is_security_alert=True)
        .values_list('message_type', flat=True)
        .distinct()
        .order_by('message_type')
    )
    mark_badge_viewed(request.user, 'security_alerts')
    return render(request, 'accounts/security_alerts.html', {
        'alerts': alerts_qs,
        'alert_types': alert_types,
        'type_filter': type_filter,
    })


@login_required
@admin_required
@require_POST
# ----------------------------------------------------------------------
# View ya Futa Rekodi ya Vitendo — Msimamizi anafuta rekodi moja
# ----------------------------------------------------------------------
def delete_audit_log_view(request, pk):
    entry = get_object_or_404(AuditLog, pk=pk)
    entry.delete()
    messages.success(request, 'Audit log entry deleted.')
    # Anti open-redirect: validate the user-supplied "next" before honouring it.
    return safe_redirect(request, request.POST.get('next'), 'admin_dashboard')


@login_required
@admin_required
@require_POST
# ----------------------------------------------------------------------
# View ya Futa Vitendo Vyote — Msimamizi anafuta rekodi zote za vitendo
# ----------------------------------------------------------------------
def clear_audit_logs_view(request):
    count = AuditLog.objects.count()
    AuditLog.objects.all().delete()
    messages.success(request, f'All {count} audit log entries cleared.')
    return redirect('audit_logs')


@login_required
@admin_required
# ----------------------------------------------------------------------
# View ya Vitendo — Anaona historia ya vitendo vyote kwenye mfumo
# ----------------------------------------------------------------------
def audit_log_view(request):
    logs = AuditLog.objects.select_related('user').all()

    q = request.GET.get('q', '').strip()
    user_q = request.GET.get('user', '').strip()
    date_q = request.GET.get('date', '').strip()

    if q:
        logs = logs.filter(action__icontains=q)
    if user_q:
        logs = logs.filter(user__username__icontains=user_q)
    if date_q:
        logs = logs.filter(timestamp__date=date_q)

    logs = logs.order_by('-timestamp')
    paginator = Paginator(logs, 50)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'accounts/audit_logs.html', {
        'logs': page_obj,
        'page_obj': page_obj,
        'paginator': paginator,
        'q': q,
        'user_q': user_q,
        'date_q': date_q,
    })


@login_required
@require_POST
# ----------------------------------------------------------------------
# View ya Kubadilisha Mandhari — Mtumiaji anabadilisha dark/light mode
# ----------------------------------------------------------------------
def toggle_theme_view(request):
    """Toggle dark/light mode for the current user."""
    user = request.user
    user.theme = 'dark' if user.theme == 'light' else 'light'
    user.save(update_fields=['theme'])
    return JsonResponse({'theme': user.theme})


@login_required
# ----------------------------------------------------------------------
# View ya Mwonekano wa Mfumo — Msimamizi anabadilisha rangi na fonti
# ----------------------------------------------------------------------
def system_appearance_view(request):
    """Librarian/admin: customise global site appearance."""
    if request.user.role not in ('librarian', 'admin'):
        messages.error(request, 'Access denied.')
        return redirect('dashboard')

    APPEARANCE_DEFAULTS = [
        ('APP_FONT_FAMILY', 'Inter',       'Body font family'),
        ('APP_FONT_SIZE',   'md',          'Body font size (sm / md / lg)'),
        ('APP_FONT_COLOR',  '#0f172a',     'Body text colour'),
        ('APP_BODY_BG',     '#f1f5d3',     'Page background colour'),
        ('APP_SIDEBAR_BG',  '#0f172a',     'Sidebar background colour'),
        ('APP_TOPBAR_BG',   '#ffffff',     'Top bar background colour'),
        ('APP_FOOTER_BG',   '#0f172a',     'Footer background colour'),
    ]
    for key, value, description in APPEARANCE_DEFAULTS:
        SystemPreference.objects.get_or_create(key=key, defaults={'value': value, 'description': description})

    if request.method == 'POST':
        for key, _default, _desc in APPEARANCE_DEFAULTS:
            val = request.POST.get(f'pref_{key}', '').strip()
            if val:
                SystemPreference.objects.filter(key=key).update(value=val)
        messages.success(request, 'Appearance settings saved.')
        return redirect('system_appearance')

    prefs = {p.key: p.value for p in SystemPreference.objects.filter(
        key__in=[k for k, _, _ in APPEARANCE_DEFAULTS]
    )}
    fonts = ['Inter', 'Roboto', 'Open Sans', 'Georgia', 'Lato', 'Poppins', 'Source Sans Pro']
    return render(request, 'accounts/system_appearance.html', {'prefs': prefs, 'fonts': fonts, 'appearance_defaults': APPEARANCE_DEFAULTS})


@login_required
@admin_required
# ----------------------------------------------------------------------
# View ya Mipangilio ya Mfumo — Msimamizi anabadilisha mipangilio
# ----------------------------------------------------------------------
def system_preferences_view(request):
    # Full set of system preference keys with defaults, units, and descriptions
    DEFAULTS = [
        # ── Borrowing ─────────────────────────────────────────────────────────
        ('LOAN_PERIOD_DAYS',           '7',     'integer', 'How long members can borrow a book (days)'),
        ('MAX_COPIES_PER_BORROW',      '3',     'integer', 'Maximum books a member can borrow at once'),
        # ── Renewals ──────────────────────────────────────────────────────────
        ('MAX_RENEWALS',               '2',     'integer', 'Maximum number of renewals allowed per borrowing'),
        ('RENEWAL_WINDOW_DAYS',        '2',     'integer', 'Days before due date that a renewal is allowed'),
        # ── Fines ─────────────────────────────────────────────────────────────
        ('FINE_PER_DAY',               '1000',  'decimal', 'Overdue fine per day (TZS)'),
        # ── Reservations ──────────────────────────────────────────────────────
        ('RESERVATION_EXPIRY_DAYS',    '7',     'integer', 'Days before an unconfirmed reservation expires'),
        # ── Guest Sessions ────────────────────────────────────────────────────
        ('GUEST_MAX_HOURS',            '12',    'integer', 'Maximum hours per guest session'),
        ('GUEST_HOURLY_RATE',          '500',   'decimal', 'Guest session fee per hour (TZS)'),
        ('SOFTCOPY_PREPAID_FEE',       '0',     'decimal', 'Default prepaid fee for softcopy access (0 = free)'),
        # ── Security ──────────────────────────────────────────────────────────
        ('ENABLE_AUTO_LOCKOUT',        '1',     'boolean', 'Lock account after max failed login attempts (1=yes, 0=no)'),
        ('MAX_LOGIN_ATTEMPTS',         '6',     'integer', 'Failed login attempts before permanent account lockout'),
        ('SUSPEND_ATTEMPTS',           '3',     'integer', 'Failed login attempts before temporary suspension (first session)'),
        ('SUSPEND_DURATION_MINUTES',   '10',    'minutes', 'Suspension duration in minutes before second session begins'),
        ('OTP_VALIDITY_MINUTES',       '10',    'minutes', 'OTP validity period (minutes)'),
        # ── Sessions & Passwords ──────────────────────────────────────────────
        ('SESSION_TIMEOUT_MINUTES',    '30',    'minutes', 'Inactivity timeout before session expires (minutes)'),
        ('PASSWORD_EXPIRY_DAYS',       '90',    'days',    'Days before password change is prompted'),
        ('PASSWORD_HISTORY_DEPTH',     '5',     'integer', 'Number of previous passwords remembered to prevent reuse'),
        # ── Notifications ─────────────────────────────────────────────────────
        ('NEW_ARRIVAL_NOTIFY_ENABLED', '1',     'boolean', 'Send automatic new arrival notifications (1=yes, 0=no)'),
        ('NEW_ARRIVAL_NOTIFY_CHANNEL', 'sms',   'text',    'Notification channel for new arrivals: sms or email'),
    ]

    for key, value, unit, description in DEFAULTS:
        pref, created = SystemPreference.objects.get_or_create(
            key=key,
            defaults={'value': value, 'unit': unit, 'description': description}
        )
        if not created:
            update_fields = []
            if not pref.description:
                pref.description = description
                update_fields.append('description')
            if not pref.unit:
                pref.unit = unit
                update_fields.append('unit')
            if update_fields:
                pref.save(update_fields=update_fields)

    if request.method == 'POST':
        # Boolean prefs rendered as checkboxes: HTML only submits them when checked.
        # Any boolean pref key absent from POST means the checkbox was unchecked → force '0'.
        BOOLEAN_PREF_KEYS = ['ENABLE_AUTO_LOCKOUT', 'NEW_ARRIVAL_NOTIFY_ENABLED']

        changed = []
        for post_key, raw_value in request.POST.items():
            if not post_key.startswith('pref_'):
                continue
            pref_key = post_key[5:]
            new_value = raw_value.strip()
            try:
                pref_obj = SystemPreference.objects.get(key=pref_key)
            except SystemPreference.DoesNotExist:
                continue
            if pref_obj.value != new_value:
                old_value = pref_obj.value
                pref_obj.value = new_value
                pref_obj.updated_by = request.user
                pref_obj.save(update_fields=['value', 'updated_by', 'updated_at'])
                changed.append(f"{pref_key}: {old_value} → {new_value}")
                log_audit(request.user, f"System preference changed — {pref_key}: '{old_value}' → '{new_value}'", request)

        # Handle unchecked boolean checkboxes (not present in POST → set to '0')
        for bool_key in BOOLEAN_PREF_KEYS:
            if f'pref_{bool_key}' not in request.POST:
                try:
                    pref_obj = SystemPreference.objects.get(key=bool_key)
                    if pref_obj.value != '0':
                        old_value = pref_obj.value
                        pref_obj.value = '0'
                        pref_obj.updated_by = request.user
                        pref_obj.save(update_fields=['value', 'updated_by', 'updated_at'])
                        changed.append(f"{bool_key}: {old_value} → 0")
                        log_audit(request.user, f"System preference changed — {bool_key}: '{old_value}' → '0'", request)
                except SystemPreference.DoesNotExist:
                    pass

        if changed:
            messages.success(request, f'Saved {len(changed)} change(s): ' + ', '.join(changed[:3]) + ('…' if len(changed) > 3 else ''))
        else:
            messages.info(request, 'No changes detected.')
        return redirect('system_preferences')

    prefs = {p.key: p for p in SystemPreference.objects.exclude(key__startswith='APP_')}
    return render(request, 'accounts/system_preferences.html', {
        'prefs': prefs,
        'defaults': DEFAULTS,
    })


@login_required
@admin_required
def block_ip_view(request):
    if request.method == 'POST':
        ip_address = request.POST.get('ip_address', '').strip()
        reason = request.POST.get('reason', '').strip()
        if ip_address:
            obj, created = BlockedIP.objects.get_or_create(
                ip_address=ip_address,
                defaults={'blocked_by': request.user, 'reason': reason or 'Blocked via suspicious activity page'},
            )
            if not created:
                messages.warning(request, f'IP {ip_address} is already blocked.')
            else:
                log_audit(request.user, f'Blocked IP {ip_address}: {reason}', request)
                messages.success(request, f'IP {ip_address} blocked successfully.')
        else:
            messages.error(request, 'Invalid IP address.')
    return redirect('suspicious_activity')


@login_required
@require_POST
def clear_import_skipped_view(request):
    request.session.pop('import_skipped', None)
    return JsonResponse({'ok': True})


@login_required
@admin_required
@require_POST
def unblock_ip_view(request, ip_id):
    try:
        blocked = BlockedIP.objects.get(pk=ip_id)
        ip = blocked.ip_address
        blocked.delete()
        log_audit(request.user, f'Unblocked IP {ip}', request)
        messages.success(request, f'IP {ip} unblocked.')
    except BlockedIP.DoesNotExist:
        messages.error(request, 'IP not found in blocked list.')
    return redirect('suspicious_activity')
