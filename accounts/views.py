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
from datetime import timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.db.models import Q, Sum, Count
from django.views.decorators.http import require_POST

from .models import OLMSUser, LoginAttempt, OTPRecord, VirtualCard, AuditLog, SystemPreference, BlockedIP
from .utils import get_client_ip, notify_user, send_sms, send_email_notification, log_audit, generate_virtual_card, generate_virtual_card_pdf, create_otp_for_user
from .forms import LoginForm


# Ukurasa wa kuingia — inashughulikia uthibitishaji wa mtumiaji
# Inalinda kwa: kuzuia baada ya majaribio 3 mabaya kwa dakika 10
# Inakumbuka vikao kwa "remember me"
def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    if request.method == 'POST':
        form = LoginForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data['username']
            password = form.cleaned_data['password']
            ip = get_client_ip(request)
            
            try:
                db_user = OLMSUser.objects.get(username=username)
            except OLMSUser.DoesNotExist:
                db_user = None

            # ── Gate check before attempting authentication ─────────────
            if db_user:
                if not db_user.is_active:
                    messages.error(request, 'Account is permanently locked. Contact admin to restore access.')
                    return render(request, 'accounts/login.html', {'form': form})

                # Group-1 suspension: active when failed_attempts == 3 and within 10-min window
                if db_user.failed_attempts == 3:
                    last_fail = LoginAttempt.objects.filter(
                        username=username, status='failed'
                    ).order_by('-timestamp').first()
                    if last_fail:
                        elapsed = (timezone.now() - last_fail.timestamp).total_seconds()
                        if elapsed < 600:  # still within 10-minute suspension
                            remaining_min = max(1, int((600 - elapsed) / 60) + 1)
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
                else:
                    # Session expires when browser closes (default)
                    request.session.set_expiry(0)
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
                    messages.warning(request, 'Your password is 30 days old. Please change it now.')
                
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

                    # ── GROUP 2: failures 4-6 — counting toward permanent lock ──
                    if total >= 6:
                        # ── Failure 6: PERMANENT LOCK ─────────────────────────
                        db_user.is_active = False
                        db_user.save(update_fields=['is_active'])
                        lock_msg_user = (
                            f"MSICT OLMS SECURITY ALERT: Your account '{username}' has been "
                            f"permanently LOCKED after 6 consecutive failed login attempts from IP {ip}. "
                            f"Contact admin to restore access. Admin phone(s): {admin_phones}."
                        )
                        lock_msg_admin = (
                            f"SECURITY ALERT: Account '{username}' permanently LOCKED after "
                            f"6 failed attempts from IP {ip} at {now.strftime('%Y-%m-%d %H:%M:%S')}."
                        )
                        notify_user(db_user, lock_msg_user, 'sms', priority='high')
                        notify_user(db_user, lock_msg_user, 'email', subject='MSICT OLMS – Account Locked', priority='high')
                        for admin in admins:
                            notify_user(admin, lock_msg_admin, 'sms', priority='high')
                            notify_user(admin, lock_msg_admin, 'email', subject='SECURITY ALERT – Account Locked', priority='high')
                        messages.error(request, 'YOUR ACCOUNT HAS BEEN LOCKED. CONTACT ADMIN FOR UNLOCKING.')

                    elif total == 5:
                        # ── Failure 5: 1 attempt left before lock ─────────────
                        messages.error(request, 'Invalid credentials. 1 attempt remaining before your account is permanently locked.')

                    elif total == 4:
                        # ── Failure 4: 2 attempts left before lock ────────────
                        messages.error(request, 'Invalid credentials. 2 attempts remaining before your account is permanently locked.')

                    # ── GROUP 1: failures 1-3 — counting toward suspension ───
                    elif total == 3:
                        # ── Failure 3: SUSPEND for 10 minutes ─────────────────
                        susp_msg_user = (
                            f"MSICT OLMS: Your account '{username}' has been temporarily "
                            f"SUSPENDED for 10 minutes after 3 failed login attempts from IP {ip}. "
                            f"After 10 minutes, you may try again (3 more attempts before permanent lock)."
                        )
                        susp_msg_admin = (
                            f"Security Notice: Account '{username}' temporarily suspended (10 min) "
                            f"after 3 failed attempts from IP {ip} at {now.strftime('%Y-%m-%d %H:%M:%S')}."
                        )
                        notify_user(db_user, susp_msg_user, 'sms', priority='high')
                        notify_user(db_user, susp_msg_user, 'email', subject='MSICT OLMS – Account Suspended', priority='high')
                        for admin in admins:
                            notify_user(admin, susp_msg_admin, 'sms', priority='high')
                            notify_user(admin, susp_msg_admin, 'email', subject='Security Notice – Account Suspended', priority='high')
                        messages.error(request, 'Account suspended for 10 minutes after 3 failed attempts. You will be notified. Try again after 10 minutes.')

                    elif total == 2:
                        # ── Failure 2: 1 attempt left before suspension ────────
                        messages.error(request, 'Invalid credentials. 1 attempt remaining before account suspension.')

                    else:
                        # ── Failure 1: 2 attempts left before suspension ───────
                        messages.error(request, 'Invalid credentials. 2 attempts remaining before account suspension.')

                else:
                    LoginAttempt.objects.create(username=username, ip_address=ip, status='failed', attempt_count=1)
                    messages.error(request, 'Invalid credentials.')
    else:
        form = LoginForm()

    from catalog.models import MediaSlide
    logo = MediaSlide.get_active_logo()
    return render(request, 'accounts/login.html', {'form': form, 'logo': logo})


# Kutoka nje — inahifadhi rekodi ya kutoka na kuelekeza kwenye ukurasa wa nyumbani
def logout_view(request):
    if request.user.is_authenticated:
        log_audit(request.user, f"User '{request.user.username}' logged out", request)
        from .models import UserSession
        UserSession.objects.filter(
            session_id=request.session.session_key, user=request.user
        ).delete()
    logout(request)
    return redirect('home')


# Omba kubadilisha nywila — inatuma OTP kwa SMS na barua pepe
# Mtumiaji anaweza kutumia nambari ya jeshi au barua pepe
def forgot_password_view(request):
    if request.method == 'POST':
        identifier = request.POST.get('identifier', '').strip()
        try:
            user = OLMSUser.objects.get(Q(army_no=identifier) | Q(email=identifier))
            otp = create_otp_for_user(user)
            msg = f"MSICT OLMS: Your password reset OTP is {otp.otp_code}. Valid for 10 minutes."

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
    return render(request, 'accounts/forgot_password.html')


# Thibitisha OTP — inachunguza kama OTP ni sahihi na bado haijaisha muda
def verify_otp_view(request):
    user_id = request.session.get('otp_user_id')
    if not user_id:
        return redirect('forgot_password')

    if request.method == 'POST':
        code = request.POST.get('otp_code', '').strip()
        try:
            otp = OTPRecord.objects.get(user_id=user_id, otp_code=code, used=False)
            if otp.is_valid():
                otp.used = True
                otp.save()
                request.session['otp_verified_user_id'] = user_id
                return redirect('reset_password')
            else:
                messages.error(request, 'OTP expired.')
        except OTPRecord.DoesNotExist:
            messages.error(request, 'Invalid OTP.')
    return render(request, 'accounts/verify_otp.html')


# Weka nywila mpya — inafanya kazi tu baada ya OTP kuthibitishwa
def reset_password_view(request):
    user_id = request.session.get('otp_verified_user_id')
    if not user_id:
        return redirect('forgot_password')

    if request.method == 'POST':
        new_password = request.POST.get('new_password', '')
        confirm = request.POST.get('confirm_password', '')
        if new_password != confirm:
            messages.error(request, 'Passwords do not match.')
        elif len(new_password) < 8:
            messages.error(request, 'Password must be at least 8 characters.')
        else:
            user = get_object_or_404(OLMSUser, pk=user_id)
            user.set_password(new_password)
            user.last_password_change = timezone.now()
            user.save()
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
    return redirect('member_dashboard')


@login_required
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
def change_password_view(request):
    if request.method == 'POST':
        old_pw = request.POST.get('old_password', '')
        new_pw = request.POST.get('new_password', '')
        confirm = request.POST.get('confirm_password', '')

        if not request.user.check_password(old_pw):
            messages.error(request, 'Current password is incorrect.')
        elif new_pw != confirm:
            messages.error(request, 'New passwords do not match.')
        elif len(new_pw) < 8:
            messages.error(request, 'Password must be at least 8 characters.')
        else:
            request.user.set_password(new_pw)
            request.user.last_password_change = timezone.now()
            request.user.save()
            login(request, request.user)
            log_audit(request.user, f"Password changed by '{request.user.username}'", request)
            messages.success(request, 'Password changed successfully.')
            return redirect('profile')
    return render(request, 'accounts/change_password.html')


# Wasifu wa mtumiaji — anaweza kusasisha barua pepe, simu na picha
@login_required
def profile_view(request):
    if request.method == 'POST':
        user = request.user
        user.email = request.POST.get('email', user.email)
        user.phone = request.POST.get('phone', user.phone)
        if 'photo' in request.FILES:
            user.photo = request.FILES['photo']
        user.save(update_fields=['email', 'phone', 'photo'])
        messages.success(request, 'Profile updated successfully.')
        return redirect('profile')
    return render(request, 'accounts/profile.html', {'user_obj': request.user})


# Onyesha kadi ya maktaba ya kidijitali (QR code + barcode)
@login_required
def virtual_card_view(request):
    card = generate_virtual_card(request.user)
    return render(request, 'accounts/virtual_card.html', {'card': card, 'user_obj': request.user})


# Pakua kadi ya maktaba kama PDF
@login_required
def virtual_card_pdf_view(request):
    buf = generate_virtual_card_pdf(request.user)
    response = HttpResponse(buf, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="MSICT_Card_{request.user.username}.pdf"'
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
def user_list_view(request):
    if request.user.role not in ['admin', 'librarian']:
        messages.error(request, 'Access denied.')
        return redirect('dashboard')
        
    query = request.GET.get('q', '')
    status = request.GET.get('status', '')
    role_filter = request.GET.get('role', '')
    users = OLMSUser.objects.exclude(role='admin').select_related('virtual_card').order_by('surname', 'first_name')

    if query:
        users = users.filter(
            Q(username__icontains=query) | Q(army_no__icontains=query) |
            Q(first_name__icontains=query) | Q(surname__icontains=query)
        )
    if status == 'locked':
        users = users.filter(is_active=False)
    if role_filter:
        users = users.filter(role=role_filter)

    return render(request, 'accounts/user_list.html', {'users': users, 'query': query, 'status': status})


@login_required
@librarian_required
def user_action_view(request, user_id, action):
    user_obj = get_object_or_404(OLMSUser, pk=user_id)
    is_admin = request.user.role == 'admin'
    is_librarian = request.user.role == 'librarian'

    if action == 'lock':
        if not is_admin:
            messages.error(request, 'Only admins can lock accounts.')
            return redirect('user_list')
        user_obj.is_active = False
        user_obj.save(update_fields=['is_active'])
        log_audit(request.user, f"{request.user.role.capitalize()} manually locked account '{user_obj.username}'", request)
        messages.warning(request, f"Account '{user_obj.username}' locked.")

    elif action == 'unlock':
        if not is_admin:
            messages.error(request, 'Only admins can unlock accounts.')
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

    elif action == 'delete':
        if is_librarian and user_obj.role != 'member':
            messages.error(request, 'Librarians can only delete member accounts.')
            return redirect('user_list')
        if user_obj.role == 'admin':
            messages.error(request, 'Admin accounts cannot be deleted here.')
            return redirect('user_list')
        username = user_obj.username
        user_obj.delete()
        log_audit(request.user, f"{request.user.role.capitalize()} deleted account '{username}'", request)
        messages.success(request, f"Account '{username}' deleted successfully.")

    return redirect('user_list')


@login_required
@librarian_required
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

        if not re.match(r'^(MTM|MT|PW|P)\s?\d+$', army_no):
            messages.error(request, 'Army number must start with MT, MTM, P, or PW followed by digits (e.g. MT 134513, MTM 456, P 789, PW 101).')
            return render(request, 'accounts/create_user.html')

        if OLMSUser.objects.filter(army_no=army_no).exists():
            messages.error(request, 'Army number already exists.')
            return render(request, 'accounts/create_user.html')

        username = OLMSUser.generate_username(role, member_type, surname, registration_no)
        initial_password = OLMSUser.generate_initial_password(army_no)

        if OLMSUser.objects.filter(username=username).exists():
            username = f"{username}_{army_no.replace(' ', '').replace('MT', '').lower()}"

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
            last_password_change=timezone.now(),
        )

        card = generate_virtual_card(user)
        card_no = card.card_no or 'N/A'

        role_label = dict(OLMSUser.ROLE_CHOICES).get(role, role).title()
        type_label = dict(OLMSUser.MEMBER_TYPE_CHOICES).get(member_type, '') if member_type else ''
        login_url = request.build_absolute_uri('/login/')

        subject = "MSICT OLMS — Your Account Credentials"
        body = (
            f"Dear {user.get_full_name()},\n\n"
            f"Your MSICT Library (OLMS) account has been created. Below are your login details:\n\n"
            f"  Full Name    : {user.get_full_name()}\n"
            f"  Army No      : {army_no}\n"
            f"  Role         : {role_label}{(' — ' + type_label) if type_label else ''}\n"
            f"  Username     : {username}\n"
            f"  Password     : {initial_password}\n"
            f"  Library Card : {card_no}\n"
            f"  Login URL    : {login_url}\n\n"
            f"IMPORTANT: You must change your password immediately on first login for security.\n"
            f"  Steps: Login → Dashboard → Change Password\n\n"
            f"Keep this message confidential. Do not share your credentials.\n\n"
            f"Regards,\nMSICT Library Administration"
        )
        sms_body = (
            f"MSICT OLMS: Account created.\n"
            f"Name: {user.get_full_name()}\n"
            f"ArmyNo: {army_no}\n"
            f"Username: {username}\n"
            f"Pwd: {initial_password}\n"
            f"Card: {card_no}\n"
            f"Login: {login_url}\n"
            f"IMPORTANT: Change your password on first login!"
        )
        sms_ok = notify_user(user, sms_body, 'sms')
        email_ok = notify_user(user, body, 'email', subject=subject)
        log_audit(request.user, f"Librarian '{request.user.username}' created user '{username}' (email={'sent' if email_ok.status == 'sent' else 'FAILED'}, sms={'sent' if sms_ok.status == 'sent' else 'FAILED'})", request)
        log_audit(request.user, f"Librarian '{request.user.username}' created user '{username}'", request)

        messages.success(request, f"User '{username}' created. Password: {initial_password}")
        request.session['new_user_credentials'] = {'username': username, 'password': initial_password, 'name': user.get_full_name()}
        return redirect('user_list')

    return render(request, 'accounts/create_user.html')


@login_required
@librarian_required
def edit_user_view(request, user_id):
    user_obj = get_object_or_404(OLMSUser, pk=user_id)
    if request.method == 'POST':
        user_obj.email = request.POST.get('email', user_obj.email)
        user_obj.phone = request.POST.get('phone', user_obj.phone)
        user_obj.first_name = request.POST.get('first_name', user_obj.first_name)
        user_obj.middle_name = request.POST.get('middle_name', user_obj.middle_name)
        user_obj.surname = request.POST.get('surname', user_obj.surname)
        user_obj.army_no = request.POST.get('army_no', user_obj.army_no)

        new_reg_no = request.POST.get('registration_no', '').strip() or None
        # Update username for students if registration_no changed
        if user_obj.member_type == 'student' and new_reg_no and new_reg_no != user_obj.registration_no:
            user_obj.username = new_reg_no
        user_obj.registration_no = new_reg_no

        user_obj.save()
        log_audit(request.user, f"Edited user '{user_obj.username}'", request)
        messages.success(request, 'User updated successfully.')
        return redirect('user_list')
    return render(request, 'accounts/edit_user.html', {'user_obj': user_obj})


@login_required
@librarian_required
def reset_user_password_view(request, user_id):
    user_obj = get_object_or_404(OLMSUser, pk=user_id)
    new_pw = OLMSUser.generate_initial_password(user_obj.army_no)
    user_obj.set_password(new_pw)
    user_obj.last_password_change = timezone.now()
    user_obj.save()
    send_email_notification(user_obj.email, "MSICT OLMS - Password Reset", f"Your new password is: {new_pw}")
    send_sms(user_obj.phone, f"MSICT OLMS: Your password has been reset to: {new_pw}")
    log_audit(request.user, f"Reset password for user '{user_obj.username}'", request)
    messages.success(request, f"Password reset to: {new_pw}")
    return redirect('user_list')


@login_required
@admin_required
def admin_dashboard_view(request):
    from circulation.models import BorrowingTransaction, Fine
    from django.db.models.functions import TruncDay
    
    # Check if user is admin
    if request.user.role != 'admin':
        messages.error(request, 'Access denied. Admin privileges required.')
        return redirect('dashboard')

    total_users = OLMSUser.objects.count()
    active_users = OLMSUser.objects.filter(is_active=True).count()
    locked_users = OLMSUser.objects.filter(is_active=False).count()

    overdue_count = BorrowingTransaction.objects.filter(status='overdue').count()
    total_borrows = BorrowingTransaction.objects.filter(status='borrowed').count()
    unpaid_fines = sum(fine.remaining_balance for fine in Fine.objects.filter(paid=False))

    # Analytics - Users by role
    users_by_role = OLMSUser.objects.values('role').annotate(count=Count('id'))
    
    # Analytics - Most borrowed books
    most_borrowed = BorrowingTransaction.objects.values('copy__book__title').annotate(
        total=Count('id')
    ).order_by('-total')[:10]

    recent_logs = AuditLog.objects.select_related('user').order_by('-timestamp')[:20]

    recent_suspended = OLMSUser.objects.filter(
        is_active=False, role='member'
    ).select_related('virtual_card').order_by('-created_at')[:5]

    # Security - System Alerts
    from circulation.models import Notification
    security_alerts = Notification.objects.filter(
        is_security_alert=True
    ).order_by('-created_at')[:5]

    context = {
        'total_users': total_users,
        'active_users': active_users,
        'locked_users': locked_users,
        'overdue_count': overdue_count,
        'total_borrows': total_borrows,
        'unpaid_fines': unpaid_fines,
        'users_by_role': users_by_role,
        'most_borrowed': most_borrowed,
        'recent_logs': recent_logs,
        'recent_suspended': recent_suspended,
        'security_alerts': security_alerts,
    }
    return render(request, 'accounts/admin_dashboard.html', context)


@login_required
@admin_required
def suspicious_activity_view(request):
    from django.db.models import Max
    window_24h = timezone.now() - timedelta(days=1)
    failed_logins = LoginAttempt.objects.filter(
        status='failed', timestamp__gte=window_24h
    ).order_by('-timestamp')[:100]

    known_usernames = set(OLMSUser.objects.values_list('username', flat=True))

    # Build username → {role, member_type} map for enriching failed login rows
    user_info_map = {
        u['username']: {'role': u['role'], 'member_type': u['member_type']}
        for u in OLMSUser.objects.values('username', 'role', 'member_type')
    }

    window_1h = timezone.now() - timedelta(hours=1)
    suspicious_ips_qs = (
        LoginAttempt.objects.filter(status='failed', timestamp__gte=window_1h)
        .values('ip_address')
        .annotate(total=Sum('attempt_count'), last_attempt=Max('timestamp'))
        .filter(total__gte=5)
        .order_by('-total')
    )

    suspicious_ips = []
    for row in suspicious_ips_qs:
        usernames = list(
            LoginAttempt.objects.filter(
                status='failed', timestamp__gte=window_1h, ip_address=row['ip_address']
            ).values_list('username', flat=True).distinct()
        )
        is_known = any(u in known_usernames for u in usernames)
        suspicious_ips.append({
            'ip_address': row['ip_address'],
            'total': row['total'],
            'last_attempt': row['last_attempt'],
            'usernames': usernames,
            'is_known': is_known,
        })

    enriched_logins = []
    for fl in failed_logins:
        info = user_info_map.get(fl.username, {})
        enriched_logins.append({
            'obj': fl,
            'role': info.get('role', ''),
            'member_type': info.get('member_type', '') or '',
            'is_known': fl.username in known_usernames,
        })

    # Get security alerts related to suspicious activity
    from circulation.models import Notification
    security_alerts = Notification.objects.filter(
        is_security_alert=True,
        message__icontains='suspicious'
    ).order_by('-created_at')[:10]

    return render(request, 'accounts/suspicious_activity.html', {
        'failed_logins': enriched_logins,
        'suspicious_ips': suspicious_ips,
        'known_usernames': known_usernames,
        'security_alerts': security_alerts,
    })


@login_required
@admin_required
def suspended_members_view(request):
    suspended = OLMSUser.objects.filter(
        is_active=False, role='member'
    ).select_related('virtual_card').order_by('-created_at')

    # Get security alerts related to suspensions
    from circulation.models import Notification
    security_alerts = Notification.objects.filter(
        is_security_alert=True,
        message__icontains='suspended'
    ).order_by('-created_at')[:10]

    return render(request, 'accounts/suspended_members.html', {
        'suspended': suspended,
        'security_alerts': security_alerts,
    })


@login_required
@admin_required
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
def delete_security_alert_view(request, pk):
    from circulation.models import Notification
    alert = get_object_or_404(Notification, pk=pk, priority='high')
    alert.delete()
    messages.success(request, 'Security alert dismissed.')
    return redirect('admin_dashboard')


@login_required
@admin_required
def security_alerts_view(request):
    from circulation.models import Notification
    alerts = Notification.objects.filter(
        is_security_alert=True
    ).select_related('user').order_by('-created_at')
    return render(request, 'accounts/security_alerts.html', {'alerts': alerts})


@login_required
@admin_required
@require_POST
def delete_audit_log_view(request, pk):
    entry = get_object_or_404(AuditLog, pk=pk)
    entry.delete()
    messages.success(request, 'Audit log entry deleted.')
    return redirect(request.POST.get('next', 'admin_dashboard'))


@login_required
@admin_required
@require_POST
def clear_audit_logs_view(request):
    count = AuditLog.objects.count()
    AuditLog.objects.all().delete()
    messages.success(request, f'All {count} audit log entries cleared.')
    return redirect('audit_logs')


@login_required
@admin_required
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
        
    logs = logs.order_by('-timestamp')[:200]
    return render(request, 'accounts/audit_logs.html', {'logs': logs})


@login_required
@require_POST
def toggle_theme_view(request):
    """Toggle dark/light mode for the current user."""
    user = request.user
    user.theme = 'dark' if user.theme == 'light' else 'light'
    user.save(update_fields=['theme'])
    return JsonResponse({'theme': user.theme})


@login_required
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
def system_preferences_view(request):
    # Ensure all core preferences exist with defaults
    DEFAULTS = [
        ('LOAN_PERIOD_DAYS',          '7',   'Loan period for all books (days)'),
        ('MAX_RENEWALS',              '2',   'Maximum number of renewals per borrow'),
        ('MAX_COPIES_PER_BORROW',     '3',   'Maximum active borrows per member'),
        ('FINE_PER_DAY',              '1000', 'Overdue fine per day (TZS)'),
        ('RESERVATION_EXPIRY_DAYS',   '7',   'Days before a reservation expires'),
    ]
    for key, value, description in DEFAULTS:
        SystemPreference.objects.get_or_create(key=key, defaults={'value': value, 'description': description})

    if request.method == 'POST':
        for post_key, value in request.POST.items():
            if post_key.startswith('pref_'):
                pref_key = post_key[5:]
                SystemPreference.objects.filter(key=pref_key).update(value=value.strip())
        messages.success(request, 'Preferences updated successfully.')
        return redirect('system_preferences')
    prefs = SystemPreference.objects.exclude(key__startswith='APP_').order_by('key')
    return render(request, 'accounts/system_preferences.html', {'prefs': prefs})
