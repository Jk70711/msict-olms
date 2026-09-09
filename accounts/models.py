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


# Jedwali la vyeo vya kijeshi — linatumika kwa utambulisho wa kijeshi
class Rank(models.Model):
    rank_name = models.CharField(max_length=50, unique=True)

    RANK_LIST = [
        'GENERAL', 'LT GENERAL', 'MJ GENERAL', 'B GENERAL',
        'COL', 'LT COL', 'MAJ', 'CAPT',
        'LT', 'S LT',
        'WI', 'WII', 'SSGT', 'SGT', 'CPL', 'PTE',
    ]

    class Meta:
        db_table = 'ranks'
        ordering = ['pk']

    def __str__(self):
        return self.rank_name


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
        ('guest', 'Guest'),
    ]
    MEMBER_TYPE_CHOICES = [
        ('student', 'Student'),
        ('lecturer', 'Instructor'),
        ('staff', 'School Staff'),
    ]
    REGISTRATION_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
        ('guest_auto', 'Guest Auto Approved'),
    ]

    army_no = models.CharField(max_length=20, unique=True, null=True, blank=True, validators=[army_no_validator])  # Nambari ya jeshi — lazima iwe ya kipekee (si lazima kwa guest)
    registration_no = models.CharField(max_length=30, null=True, blank=True)  # Nambari ya usajili (kwa wanafunzi tu)
    first_name = models.CharField(max_length=100)   # Jina la kwanza
    middle_name = models.CharField(max_length=100, blank=True, default='')  # Jina la kati (si lazima)
    surname = models.CharField(max_length=100)      # Jina la familia
    username = models.CharField(max_length=100, unique=True)  # Jina la kuingia
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='member')  # Jukumu: admin, librarian, member
    member_type = models.CharField(max_length=10, choices=MEMBER_TYPE_CHOICES, null=True, blank=True)  # Aina: student, lecturer, staff
    registration_status = models.CharField(max_length=10, choices=REGISTRATION_STATUS_CHOICES, default='pending')  # Status: pending, approved, cancelled
    email = models.EmailField()        # Barua pepe
    phone = models.CharField(max_length=20)  # Nambari ya simu (kwa SMS)
    is_active = models.BooleanField(default=True)    # Kama False — mtumiaji amezuiwa
    is_staff = models.BooleanField(default=False)    # Ruhusa ya Django admin
    failed_attempts = models.IntegerField(default=0)  # Idadi ya majaribio mabaya ya kuingia
    last_login = models.DateTimeField(null=True, blank=True)  # Mara ya mwisho kuingia
    last_password_change = models.DateTimeField(default=timezone.now)  # Mara ya mwisho kubadilisha nywila
    created_at = models.DateTimeField(auto_now_add=True)  # Tarehe ya kuunda akaunti
    approved_by = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_users')  # Aliyeidhinisha akaunti
    approved_at = models.DateTimeField(null=True, blank=True)  # Tarehe ya idhinisho
    cancelled_reason = models.TextField(blank=True)  # Sababu ya kukataa akaunti
    photo = models.ImageField(upload_to='user_photos/', null=True, blank=True)  # Picha ya wasifu
    card_no = models.CharField(max_length=25, unique=True, null=True, blank=True, db_index=True,
                               help_text='Auto-generated card number e.g. MSICT-2026-00001')
    is_guest = models.BooleanField(default=False)
    total_guest_hours = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_guest_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    rank = models.ForeignKey(
        'Rank', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='users', db_column='rank_id'
    )  # Cheo cha kijeshi
    password_changed_after_first_login = models.BooleanField(default=False)  # Kuzuia kuingia mara ya pili bila kubadilisha nywila
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

    def save(self, *args, **kwargs):
        # Admin and librarian accounts are created by staff — they must never
        # sit in the member approval queue regardless of how they were created.
        if self.role in ('admin', 'librarian'):
            self.registration_status = 'approved'
            self.is_active = True
        elif self.role == 'guest' or self.is_guest:
            self.is_guest = True
            self.registration_status = 'guest_auto'
            self.is_active = True
            self.card_no = None
            self.rank = None
            self.member_type = None
            self.registration_no = None
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.get_full_name()} ({self.username})"

    def get_full_name(self):
        parts = [self.first_name]
        if self.middle_name:
            parts.append(self.middle_name)
        parts.append(self.surname)
        return ' '.join(parts)

    def get_ranked_name(self):
        """Return rank + full name, e.g. 'MAJOR J. Mkombozi'"""
        name = self.get_full_name()
        if self.rank:
            return f'{self.rank.rank_name} {name}'
        return name

    def get_short_name(self):
        return self.first_name

    @staticmethod
    def generate_username(role, member_type, surname, registration_no, first_name='', middle_name=''):
        """Generate username based on role and member type.
        - Students: use registration_no
        - Librarians/Members (staff/instructor): use full surname + 2 random letters from first/middle names
        """
        import random
        import string
        
        # Students use registration_no
        if member_type == 'student' and registration_no:
            return registration_no.strip()
        
        # Librarians and Members (staff/instructor) use full surname + 2 random letters
        if role in ('librarian', 'member') and member_type in ('staff', 'instructor'):
            # Get full surname as base
            base_surname = surname.strip().lower() if surname else 'user'
            
            # Get letters from first and middle names ONLY
            letters_pool = []
            if first_name:
                letters_pool.extend([c.lower() for c in first_name.strip() if c.isalpha()])
            if middle_name:
                letters_pool.extend([c.lower() for c in middle_name.strip() if c.isalpha()])
            
            # If no letters from first/middle names, use surname letters as fallback
            if not letters_pool and base_surname:
                letters_pool = [c for c in base_surname if c.isalpha()]
            
            # Pick 2 random letters from the pool (without replacement if possible)
            if len(letters_pool) >= 2:
                random_letters = random.sample(letters_pool, 2)
            elif len(letters_pool) == 1:
                random_letters = [letters_pool[0], letters_pool[0]]
            else:
                # Ultimate fallback: use 'aa' if no letters available at all
                random_letters = ['a', 'a']
            
            # Shuffle the 2 letters for variety
            random.shuffle(random_letters)
            
            # Combine: full surname + 2 random letters
            username = base_surname + ''.join(random_letters)
            
            return username
        
        # For other member types (students without reg_no, etc.), use surname + 2 random letters
        if surname:
            base_surname = surname.strip().lower()
            letters_pool = [c for c in base_surname if c.isalpha()]
            if len(letters_pool) >= 2:
                random_letters = random.sample(letters_pool, 2)
            elif len(letters_pool) == 1:
                random_letters = [letters_pool[0], letters_pool[0]]
            else:
                random_letters = ['a', 'a']
            random.shuffle(random_letters)
            return base_surname + ''.join(random_letters)
        
        return 'user'

    @staticmethod
    def generate_initial_password(army_no):
        return re.sub(r'[^0-9]', '', army_no)

    def has_overdue(self):
        """Returns True when the user has overdue hardcopy items
        where the fine is still unpaid (or no fine has been created yet).
        Users who have fully paid their overdue fines are NOT restricted.
        
        IMPORTANT: Overdue hardcopies block ALL borrowing, including softcopy (Option A).
        Softcopies never go overdue — they simply expire."""
        from circulation.models import BorrowingTransaction, Fine
        from django.db.models import Q, Exists, OuterRef, F
        
        overdue_qs = BorrowingTransaction.objects.filter(
            Q(user=self, status='overdue') |
            Q(user=self, status='borrowed', due_date__lt=timezone.now())
        ).exclude(
            copy__copy_type='softcopy'
        )
        if not overdue_qs.exists():
            return False
        unpaid_fine = Exists(
            Fine.objects.filter(transaction=OuterRef('pk'), paid=False, amount__gt=F('amount_paid'))
        )
        no_fine_yet = ~Exists(Fine.objects.filter(transaction=OuterRef('pk')))
        return overdue_qs.filter(unpaid_fine | no_fine_yet).exists()

    def active_borrows_count(self):
        from circulation.models import BorrowingTransaction
        from django.db.models import Q
        return BorrowingTransaction.objects.filter(
            user=self,
            status__in=['borrowed', 'overdue'],
        ).exclude(
            Q(copy__copy_type='softcopy', copy__access_type='borrow', due_date__lt=timezone.now())
        ).count()

    def has_unpaid_fines(self):
        from circulation.models import Fine, LossReport, DamageReport
        from django.db.models import F
        # Check BOTH the paid flag AND that amount_paid < amount (guards against stale flags)
        # This includes overdue fines, loss fines, and damage fines
        unpaid_overdue_fines = Fine.objects.filter(user=self, paid=False, amount__gt=F('amount_paid')).exists()
        unpaid_loss_fines = LossReport.objects.filter(
            user=self,
            loss_fine__isnull=False,
            loss_fine__paid=False,
            loss_fine__amount__gt=F('loss_fine__amount_paid')
        ).exists()
        unpaid_damage_fines = DamageReport.objects.filter(
            user=self,
            damage_fine__isnull=False,
            damage_fine__paid=False,
            damage_fine__amount__gt=F('damage_fine__amount_paid')
        ).exists()
        return unpaid_overdue_fines or unpaid_loss_fines or unpaid_damage_fines

    def password_is_old(self):
        try:
            days = int(SystemPreference.objects.filter(key='PASSWORD_EXPIRY_DAYS').values_list('value', flat=True).first() or 90)
        except Exception:
            days = 90
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


# Vikao vya wageni (walk-in) — ufuatiliaji wa muda, malipo na hali ya session
class GuestSession(models.Model):
    PAYMENT_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('paid', 'Paid'),
        ('waived', 'Waived'),
    ]
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('renewed', 'Renewed'),
        ('ended', 'Ended'),
        ('expired', 'Expired'),
    ]

    user = models.ForeignKey(OLMSUser, on_delete=models.CASCADE, related_name='guest_sessions')
    sign_in_time = models.DateTimeField(auto_now_add=True)
    sign_out_time = models.DateTimeField(null=True, blank=True)
    paid_hours = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    duration_hours = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    payment_status = models.CharField(max_length=10, choices=PAYMENT_STATUS_CHOICES, default='pending')
    payment_method = models.CharField(max_length=20, blank=True, default='')
    renewed = models.BooleanField(default=False)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    device_info = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='active')
    expiry_notification_sent = models.BooleanField(default=False, help_text='True if 15-min pre-expiry SMS/email was sent')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'guest_sessions'
        ordering = ['-sign_in_time']

    def __str__(self):
        return f"GuestSession #{self.pk} {self.user.username} [{self.status}]"


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
        m = re.search(r'(\d+)$', self.card_no)
        return m.group(1) if m else self.card_no

    @classmethod
    def generate_card_no(cls):
        """Return the next sequential card number: MSICT-LIB-YY-XXXXXX
        
        Format: MSICT-LIB-{2-digit year}-{6-digit sequence}
        Example: MSICT-LIB-26-000009
        Scans both VirtualCard and OLMSUser.card_no to find the true last number.
        """
        from django.utils import timezone as _tz
        from accounts.models import OLMSUser
        yy = _tz.now().strftime('%y')          # 2-digit year e.g. '26'
        prefix = f'MSICT-LIB-{yy}-'
        pattern = re.compile(r'MSICT-LIB-(\d{2})-(\d+)')
        max_num = 0
        # Scan all existing card numbers from both tables
        vc_cards = list(cls.objects.exclude(card_no__isnull=True).exclude(card_no='').values_list('card_no', flat=True))
        user_cards = list(OLMSUser.objects.exclude(card_no__isnull=True).exclude(card_no='').values_list('card_no', flat=True))
        for cn in vc_cards + user_cards:
            m = pattern.search(cn)
            if m:
                n = int(m.group(2))
                if n > max_num:
                    max_num = n
        return f'{prefix}{max_num + 1:06d}'


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


# Historia ya nywila — inahifadhi nywila 3 za mwisho kwa kila mtumiaji
# Inazuia mtumiaji kutumia tena nywila zilizotumika hapo awali
class PasswordHistory(models.Model):
    user = models.ForeignKey(OLMSUser, on_delete=models.CASCADE, related_name='password_history')
    password_hash = models.CharField(max_length=255)  # Django password hash
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'password_history'
        ordering = ['-created_at']
        verbose_name = 'Password History'
        verbose_name_plural = 'Password Histories'

    def __str__(self):
        return f"{self.user.username} password at {self.created_at.strftime('%Y-%m-%d %H:%M')}"


# Mipangilio ya mfumo — inabadilishwa kupitia /admin/preferences/
# Mfano: LOAN_PERIOD_DAYS=7, FINE_PER_DAY=500
class SystemPreference(models.Model):
    UNIT_CHOICES = [
        ('days', 'Days'),
        ('minutes', 'Minutes'),
        ('boolean', 'Boolean'),
        ('text', 'Text'),
        ('decimal', 'Decimal'),
        ('integer', 'Integer'),
    ]

    key = models.CharField(max_length=100, unique=True)
    value = models.TextField()
    unit = models.CharField(max_length=20, choices=UNIT_CHOICES, default='text')
    description = models.CharField(max_length=500, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        OLMSUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='updated_preferences'
    )

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


# User Manual Sections — Editable content for the User Manual page
# Librarians can CRUD these sections via admin under Member & Media
class UserManualSection(models.Model):
    SECTION_CHOICES = [
        ('getting_started', 'Getting Started'),
        ('borrowing', 'Borrowing Books'),
        ('returning', 'Returning Books'),
        ('renewals', 'Renewals'),
        ('reservations', 'Reservations'),
        ('fines', 'Fines & Payments'),
        ('loss', 'Lost Books'),
        ('softcopy', 'Digital Resources (Softcopies)'),
        ('notifications', 'Notifications'),
        ('chat', 'Chat & Support'),
        ('passwords', 'Password Security'),
        ('login_attempts', 'Login Attempts & Security'),
        ('guest', 'Guest Access'),
        ('ai', 'AI Assistant'),
    ]

    section_key = models.CharField(
        max_length=50,
        choices=SECTION_CHOICES,
        unique=True,
        help_text="Unique identifier for this section"
    )
    title = models.CharField(max_length=200, help_text="Section title displayed to users")
    icon = models.CharField(max_length=50, default='bi-info-circle', help_text="Bootstrap icon class")
    content = models.TextField(help_text="HTML content for this section")
    order = models.PositiveIntegerField(default=0, help_text="Display order (lower numbers first)")
    is_active = models.BooleanField(default=True, help_text="Whether this section is visible")
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        OLMSUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='updated_manual_sections'
    )

    class Meta:
        db_table = 'user_manual_sections'
        ordering = ['order', 'section_key']
        verbose_name = 'User Manual Section'
        verbose_name_plural = 'User Manual Sections'

    def __str__(self):
        return self.title


# ----------------------------------------------------------------------
# Terms and Conditions Sections — Editable via Django admin
# Admin can CRUD these sections via /admin/
# ----------------------------------------------------------------------
class TermsSection(models.Model):
    SECTION_CHOICES = [
        ('acceptance',    'Acceptance of Terms'),
        ('user_resp',     'User Responsibilities'),
        ('borrowing',     'Borrowing Rules'),
        ('fines',         'Fines and Payments'),
        ('digital',       'Digital Resources'),
        ('privacy',       'Privacy and Data'),
        ('conduct',       'Conduct and Discipline'),
        ('system_usage',  'System Usage'),
        ('changes',       'Changes to Terms'),
        ('contact',       'Contact Information'),
        ('custom',        'Custom Section'),
    ]

    section_key = models.CharField(
        max_length=50,
        choices=SECTION_CHOICES,
        help_text='Section identifier (multiple custom sections allowed)'
    )
    title = models.CharField(max_length=200, help_text='Section heading displayed to users')
    icon = models.CharField(max_length=50, default='bi-file-text', help_text='Bootstrap icon class e.g. bi-shield-check')
    content = models.TextField(help_text='HTML content for this section (tags like <ul>, <p>, <strong> allowed)')
    order = models.PositiveIntegerField(default=0, help_text='Display order (lower numbers first)')
    is_active = models.BooleanField(default=True, help_text='Uncheck to hide this section')
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        OLMSUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='updated_terms_sections'
    )

    class Meta:
        db_table = 'terms_sections'
        ordering = ['order', 'section_key']
        verbose_name = 'Terms & Conditions Section'
        verbose_name_plural = 'Terms & Conditions Sections'

    def __str__(self):
        return f"{self.order}. {self.title}"


# ----------------------------------------------------------------------
# Bulk Messaging — Admin/Librarian sends notifications to groups
# ----------------------------------------------------------------------
class BulkMessage(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
    ]

    subject = models.CharField(max_length=255, blank=True)
    body = models.TextField()
    target_roles = models.JSONField(default=list, blank=True, help_text='e.g. ["member","librarian"]')
    target_member_types = models.JSONField(default=list, blank=True, null=True, help_text='e.g. ["student","lecturer"]')
    send_via = models.JSONField(default=list, help_text='["email","sms"]')
    sent_at = models.DateTimeField(null=True, blank=True)
    sent_by = models.ForeignKey(OLMSUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='sent_bulk_messages')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='draft')
    total_recipients = models.IntegerField(default=0)
    total_sent = models.IntegerField(default=0)
    total_failed = models.IntegerField(default=0)
    is_new_arrival = models.BooleanField(default=False, help_text='Auto-generated for new book arrivals')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'bulk_messages'
        ordering = ['-sent_at']

    def __str__(self):
        return f"BulkMessage #{self.pk} — {self.subject or '(no subject)'} [{self.status}]"


class BulkMessageRecipient(models.Model):
    DELIVERED_VIA_CHOICES = [('email', 'Email'), ('sms', 'SMS')]
    STATUS_CHOICES = [('pending', 'Pending'), ('sent', 'Sent'), ('failed', 'Failed')]

    message = models.ForeignKey(BulkMessage, on_delete=models.CASCADE, related_name='recipients')
    user = models.ForeignKey(OLMSUser, on_delete=models.CASCADE, related_name='bulk_message_receipts')
    delivered_via = models.CharField(max_length=10, choices=DELIVERED_VIA_CHOICES)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    delivered_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True, default='')

    class Meta:
        db_table = 'bulk_message_recipients'
        ordering = ['-message']

    def __str__(self):
        return f"Recipient {self.user.username} — {self.status} via {self.delivered_via}"


class BadgeViewed(models.Model):
    user = models.ForeignKey(OLMSUser, on_delete=models.CASCADE, related_name='badge_views')
    badge_key = models.CharField(max_length=50)
    last_viewed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'badge_views'
        unique_together = ('user', 'badge_key')

    def __str__(self):
        return f"{self.user.username} — {self.badge_key} @ {self.last_viewed_at:%Y-%m-%d %H:%M}"
