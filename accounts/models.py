# ============================================================
# accounts/models.py
# Mifano ya data kwa watumiaji, vikao, OTP, kadi za maktaba
# na mipangilio ya mfumo
# ============================================================

import re
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.core.validators import RegexValidator
from django.utils import timezone

# Uthibitishaji wa nambari ya jeshi — lazima ianze na MT, MTM, P, au PW
army_no_validator = RegexValidator(
    regex=r'^(MTM|MT|PW|P)\s?\d+$',
    message='Army number must start with MT, MTM, P, or PW followed by digits. E.g. MT 134513, MTM 456, P 789, PW 101.'
)


# Manager maalum wa kuunda watumiaji wa OLMSUser
class OLMSUserManager(BaseUserManager):
    def create_user(self, username, password=None, **extra_fields):
        if not username:
            raise ValueError('Username is required')
        user = self.model(username=username, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, username, password=None, **extra_fields):
        extra_fields.setdefault('role', 'admin')
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        extra_fields.setdefault('army_no', extra_fields.get('army_no', 'MT 000001'))
        extra_fields.setdefault('first_name', extra_fields.get('first_name', 'System'))
        extra_fields.setdefault('surname', extra_fields.get('surname', 'Admin'))
        extra_fields.setdefault('email', extra_fields.get('email', 'admin@msict.ac.tz'))
        extra_fields.setdefault('phone', extra_fields.get('phone', '0000000000'))
        extra_fields.setdefault('last_password_change', timezone.now())
        return self.create_user(username, password, **extra_fields)


# Mfano mkuu wa mtumiaji — unarithi kutoka AbstractBaseUser
# Kila mtu anayeingia kwenye mfumo ni OLMSUser
class OLMSUser(AbstractBaseUser, PermissionsMixin):
    ROLE_CHOICES = [
        ('admin', 'Admin'),
        ('librarian', 'Librarian'),
        ('member', 'Member'),
    ]
    MEMBER_TYPE_CHOICES = [
        ('student', 'Student'),
        ('lecturer', 'Instructor'),
        ('staff', 'School Staff'),
    ]

    army_no = models.CharField(max_length=20, unique=True, validators=[army_no_validator])  # Nambari ya jeshi — lazima iwe ya kipekee
    registration_no = models.CharField(max_length=30, null=True, blank=True)  # Nambari ya usajili (kwa wanafunzi tu)
    first_name = models.CharField(max_length=100)   # Jina la kwanza
    middle_name = models.CharField(max_length=100, blank=True, default='')  # Jina la kati (si lazima)
    surname = models.CharField(max_length=100)      # Jina la familia
    username = models.CharField(max_length=100, unique=True)  # Jina la kuingia
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='member')  # Jukumu: admin, librarian, member
    member_type = models.CharField(max_length=10, choices=MEMBER_TYPE_CHOICES, null=True, blank=True)  # Aina: student, lecturer, staff
    email = models.EmailField()        # Barua pepe
    phone = models.CharField(max_length=20)  # Nambari ya simu (kwa SMS)
    is_active = models.BooleanField(default=True)    # Kama False — mtumiaji amezuiwa
    is_staff = models.BooleanField(default=False)    # Ruhusa ya Django admin
    failed_attempts = models.IntegerField(default=0)  # Idadi ya majaribio mabaya ya kuingia
    last_login = models.DateTimeField(null=True, blank=True)  # Mara ya mwisho kuingia
    last_password_change = models.DateTimeField(default=timezone.now)  # Mara ya mwisho kubadilisha nywila
    created_at = models.DateTimeField(auto_now_add=True)  # Tarehe ya kuunda akaunti
    photo = models.ImageField(upload_to='user_photos/', null=True, blank=True)  # Picha ya wasifu
    theme = models.CharField(
        max_length=10,
        choices=[('light', 'Light'), ('dark', 'Dark')],
        default='light',
    )

    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = ['army_no', 'first_name', 'surname', 'email', 'phone']

    objects = OLMSUserManager()

    class Meta:
        db_table = 'users'
        verbose_name = 'User'
        verbose_name_plural = 'Users'

    def __str__(self):
        return f"{self.get_full_name()} ({self.username})"

    def get_full_name(self):
        parts = [self.first_name]
        if self.middle_name:
            parts.append(self.middle_name)
        parts.append(self.surname)
        return ' '.join(parts)

    def get_short_name(self):
        return self.first_name

    @staticmethod
    def generate_username(role, member_type, surname, registration_no):
        if member_type == 'student' and registration_no:
            return registration_no.strip()
        return surname.strip()

    @staticmethod
    def generate_initial_password(army_no):
        return re.sub(r'[^0-9]', '', army_no)

    def has_overdue(self):
        from circulation.models import BorrowingTransaction
        from django.db.models import Q
        return BorrowingTransaction.objects.filter(
            Q(user=self, status='overdue') |
            Q(user=self, status='borrowed', due_date__lt=timezone.now())
        ).exists()

    def active_borrows_count(self):
        from circulation.models import BorrowingTransaction
        return BorrowingTransaction.objects.filter(
            user=self, status__in=['borrowed', 'overdue']
        ).count()

    def has_unpaid_fines(self):
        from circulation.models import Fine
        return Fine.objects.filter(user=self, paid=False).exists()

    def password_is_old(self):
        from django.conf import settings
        days = getattr(settings, 'PASSWORD_CHANGE_REMINDER_DAYS', 30)
        if self.last_password_change:
            delta = timezone.now() - self.last_password_change
            return delta.days >= days
        return False


# Rekodi ya kila jaribio la kuingia — inatumika kwa usalama na kugundua shughuli za tuhuma
class LoginAttempt(models.Model):
    STATUS_CHOICES = [('success', 'Success'), ('failed', 'Failed')]
    username = models.CharField(max_length=100, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    attempt_count = models.IntegerField(default=1)
    password_chars = models.IntegerField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'login_attempts'
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.username} - {self.status} @ {self.ip_address}"


# Nambari ya siri ya mara moja (OTP) — inatumika wakati wa kubadilisha nywila
class OTPRecord(models.Model):
    user = models.ForeignKey(OLMSUser, on_delete=models.CASCADE, related_name='otps')
    otp_code = models.CharField(max_length=6)
    expires_at = models.DateTimeField()
    used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'otp_records'

    def is_valid(self):
        return not self.used and timezone.now() < self.expires_at


class UserSession(models.Model):
    session_id = models.CharField(max_length=255, primary_key=True)
    user = models.ForeignKey(OLMSUser, on_delete=models.CASCADE, related_name='sessions')
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    login_time = models.DateTimeField(auto_now_add=True)
    logout_time = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'user_sessions'


# Kadi ya maktaba ya kidijitali — kila mtumiaji ana kadi moja
# Nambari ya kadi: MSICT-CARD-000001, 000002, ...
class VirtualCard(models.Model):
    user = models.OneToOneField(OLMSUser, on_delete=models.CASCADE, related_name='virtual_card')
    card_no = models.CharField(max_length=25, unique=True, null=True, blank=True, db_index=True,
                               help_text='Auto-generated card number e.g. MSICT-LIB-26-000001')
    qr_code = models.TextField(blank=True)
    barcode = models.CharField(max_length=100, blank=True)
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'virtual_cards'

    def __str__(self):
        return f"Card for {self.user.get_full_name()} [{self.card_no or 'No Card No'}]"

    @property
    def short_card_no(self):
        """Return only the unique number part (e.g., 000001) instead of full card number."""
        if not self.card_no:
            return 'N/A'
        import re
        m = re.search(r'(\d+)$', self.card_no)
        return m.group(1) if m else self.card_no

    @classmethod
    def generate_card_no(cls):
        """Return the next sequential card number: MSICT-LIB-{YY}-{NNNNNN}"""
        import re
        from django.utils import timezone as _tz
        yy = _tz.now().strftime('%y')
        max_num = 0
        for cn in cls.objects.exclude(card_no__isnull=True).exclude(card_no='').values_list('card_no', flat=True):
            m = re.search(r'MSICT-LIB-\d+-(\d+)', cn) or re.search(r'MSICT-CARD-(\d+)', cn)
            if m:
                n = int(m.group(1))
                if n > max_num:
                    max_num = n
        return f'MSICT-LIB-{yy}-{max_num + 1:06d}'


# Historia ya vitendo vikubwa kwenye mfumo — nani alifanya nini na lini
class AuditLog(models.Model):
    user = models.ForeignKey(OLMSUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='audit_logs')
    action = models.CharField(max_length=500)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'audit_logs'
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.action} at {self.timestamp}"


# Mipangilio ya mfumo — inabadilishwa kupitia /admin/preferences/
# Mfano: LOAN_PERIOD_DAYS=7, FINE_PER_DAY=500
class SystemPreference(models.Model):
    key = models.CharField(max_length=100, unique=True)
    value = models.TextField()
    description = models.CharField(max_length=500, blank=True)

    class Meta:
        db_table = 'system_preferences'

    def __str__(self):
        return f"{self.key} = {self.value}"

    @classmethod
    def get(cls, key, default=None):
        try:
            return cls.objects.get(key=key).value
        except cls.DoesNotExist:
            return default


# Anwani za IP zilizozuiwa — zinakatazwa kuingia kwenye mfumo
class BlockedIP(models.Model):
    ip_address = models.GenericIPAddressField(unique=True)
    blocked_by = models.ForeignKey(OLMSUser, on_delete=models.SET_NULL, null=True)
    reason = models.CharField(max_length=255, blank=True)
    blocked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'blocked_ips'

    def __str__(self):
        return self.ip_address
