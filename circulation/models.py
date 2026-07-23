# ============================================================
# circulation/models.py
# Mifano ya data kwa mikopo, maombi, uhifadhi, faini, arifa
# Hii ndiyo moyo wa mfumo — inashughulikia harakati zote za vitabu
# ============================================================

from django.db import models
import uuid
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
from django.conf import settings
from accounts.models import OLMSUser
from catalog.models import BookCopy, Book


# Msaidizi wa kusoma mipangilio: kwanza angalia DB, kisha settings.py
def _pref(key, default):
    """Read from SystemPreference DB first, fallback to Django settings, then default."""
    try:
        from accounts.models import SystemPreference
        val = SystemPreference.objects.filter(key=key).values_list('value', flat=True).first()
        if val is not None:
            return val
    except Exception:
        pass
    return getattr(settings, key, default)


# ----------------------------------------------------------------------
# Model ya BorrowRequest — Ombi la kukopa kitabu
# Mwanachama anatuma, mtunzaji anaidhinisha au kukataa
# Hali: pending (inasubiri) → approved (imeidhinishwa) / rejected (imekataliwa)
# ----------------------------------------------------------------------
class BorrowRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
        ('deleted', 'Deleted'),
    ]
    user = models.ForeignKey(OLMSUser, on_delete=models.CASCADE, related_name='borrow_requests')
    copy = models.ForeignKey(
        BookCopy, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='borrow_requests'
    )  # NULL until librarian assigns physical copy (hardcopy flow)
    temp_book = models.ForeignKey(
        Book, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='hardcopy_requests'
    )  # Book title requested before a specific copy is assigned
    request_date = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='pending')
    approved_by = models.ForeignKey(
        OLMSUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='approved_requests'
    )
    rejection_reason = models.CharField(max_length=500, blank=True)

    class Meta:
        db_table = 'borrow_requests'
        ordering = ['-request_date']

    def __str__(self):
        title = self.copy.book.title if self.copy_id else (self.temp_book.title if self.temp_book_id else '?')
        return f"{self.user.username} → {title} [{self.status}]"

    @property
    def book(self):
        """Returns the Book regardless of whether a specific copy has been assigned."""
        if self.copy_id:
            return self.copy.book
        return self.temp_book


# ----------------------------------------------------------------------
# Model ya BorrowingTransaction — Mkopo ulioidhinishwa
# Unafuatilia vitabu vilivyokopwa
# Hali: borrowed → returned (imerudishwa) / overdue (imechelewa)
# ----------------------------------------------------------------------
class BorrowingTransaction(models.Model):
    BORROW_TYPE_CHOICES = [('hardcopy', 'Hardcopy'), ('softcopy', 'Softcopy')]
    STATUS_CHOICES = [
        ('borrowed', 'Borrowed'),
        ('returned', 'Returned'),
        ('overdue', 'Overdue'),
        ('lost', 'Lost'),
    ]

    user = models.ForeignKey(OLMSUser, on_delete=models.CASCADE, related_name='transactions')   # Mwanachama aliyekopa
    copy = models.ForeignKey(BookCopy, on_delete=models.CASCADE, related_name='transactions')   # Nakala iliyokopwa
    borrow_type = models.CharField(max_length=10, choices=BORROW_TYPE_CHOICES)  # Aina: hardcopy au softcopy
    borrow_date = models.DateTimeField(auto_now_add=True)  # Tarehe ya kukopa
    due_date = models.DateTimeField()                      # Tarehe ya mwisho ya kurudisha
    return_date = models.DateTimeField(null=True, blank=True)  # Tarehe halisi ya kurudisha
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='borrowed')  # Hali ya mkopo
    approved_by = models.ForeignKey(
        OLMSUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='approved_transactions'
    )  # Mtunzaji aliyeidhinisha
    access_token = models.UUIDField(unique=True, editable=False, null=True, blank=True)
    token_expires = models.DateTimeField(null=True, blank=True)
    renewed_count = models.IntegerField(default=0)  # Mara ngapi mkopo umefanyiwa upya

    class Meta:
        db_table = 'borrowing_transactions'
        ordering = ['-borrow_date']

    def __str__(self):
        return f"{self.user.username} – {self.copy.book.title} (due {self.due_date.date()})"

    def save(self, *args, **kwargs):
        if not self.pk and not self.due_date:
            loan_days = int(_pref('LOAN_PERIOD_DAYS', 7))
            self.due_date = timezone.now() + timedelta(days=loan_days)
        if self.copy.copy_type == 'softcopy' and self.borrow_type == 'softcopy':
            if not self.access_token:
                self.access_token = uuid.uuid4()
            if not self.token_expires:
                self.token_expires = self.due_date
        super().save(*args, **kwargs)

    @property
    def loss_report_exists(self):
        from circulation.models import LossReport as _LR
        return _LR.objects.filter(transaction=self).exists()

    def is_overdue(self):
        return self.status in ('borrowed', 'overdue') and timezone.now() > self.due_date

    def days_overdue(self):
        if timezone.now() > self.due_date and self.status in ('borrowed', 'overdue'):
            return (timezone.now() - self.due_date).days
        return 0

    @property
    def days_remaining(self):
        """Days left before due_date. 0 if already expired."""
        delta = self.due_date - timezone.now()
        return max(0, delta.days)

    @property
    def duration_borrowed(self):
        """Duration borrowed in format: 'X days - Y hours - Z minutes'"""
        if not self.return_date or not self.borrow_date:
            return "—"
        delta = self.return_date - self.borrow_date
        total_seconds = int(delta.total_seconds())
        days = total_seconds // 86400
        hours = (total_seconds % 86400) // 3600
        minutes = (total_seconds % 3600) // 60
        return f"{days} days - {hours} hours - {minutes} minutes"

    @property
    def time_remaining_display(self):
        """Human-readable countdown: '3d 4h left', '5h 20m left', 'Due now', '2d overdue'.
        For softcopies past due date, shows 'Expired' instead of 'overdue'."""
        if self.status == 'returned':
            return '—'
        delta = self.due_date - timezone.now()
        total_secs = int(delta.total_seconds())
        if total_secs <= 0:
            # Softcopies expire (no overdue concept)
            if self.copy.copy_type == 'softcopy':
                return 'Expired'
            over_secs = abs(total_secs)
            over_days = over_secs // 86400
            over_hrs  = (over_secs % 86400) // 3600
            if over_days >= 1:
                return f'{over_days}d {over_hrs}h overdue'
            if over_hrs >= 1:
                return f'{over_hrs}h overdue'
            return 'Due now'
        days  = delta.days
        hours = (total_secs % 86400) // 3600
        mins  = (total_secs % 3600) // 60
        if days >= 2:
            return f'{days}d {hours}h left'
        if days == 1:
            return f'1d {hours}h left'
        if hours >= 1:
            return f'{hours}h {mins}m left'
        return f'{mins}m left'

    @property
    def time_remaining_badge_class(self):
        """Bootstrap badge colour class matching urgency."""
        if self.status == 'returned':
            return 'bg-secondary'
        if self.status == 'overdue':
            return 'bg-danger'
        delta = self.due_date - timezone.now()
        days = delta.days
        if days <= 1:
            return 'bg-danger'
        if days <= 3:
            return 'bg-warning text-dark'
        return 'bg-info text-dark'

    @property
    def is_link_active(self):
        """For softcopy: True only when borrow period has not yet expired."""
        # For free softcopies, link is always active while borrowed
        if self.copy.copy_type == 'softcopy' and self.copy.access_type == 'free':
            return self.status == 'borrowed'
        # For special (borrow) softcopies, link is only active within due_date
        return self.status == 'borrowed' and timezone.now() <= self.due_date
    
    @property
    def is_link_expired(self):
        """Check if special softcopy link has expired (past due date)."""
        if self.copy.copy_type == 'softcopy' and self.copy.access_type == 'borrow':
            return self.status == 'borrowed' and timezone.now() > self.due_date
        return False
    
    @property
    def calculated_fine(self):
        """Calculate current fine amount based on overdue days and FINE_PER_DAY."""
        # Softcopies do not have overdue fines - link simply expires
        if self.copy.copy_type == 'softcopy':
            return 0
        if not self.is_overdue():
            return 0
        days_overdue = self.days_overdue()
        fine_per_day = float(_pref('FINE_PER_DAY', 1000))
        return days_overdue * fine_per_day
    
    @property
    def has_unpaid_fine(self):
        """Check if this transaction has any unpaid fine."""
        return self.fines.filter(paid=False).exists()

    @property
    def total_fine_paid(self):
        """Get total amount paid for fines on this transaction."""
        return sum(fine.amount_paid for fine in self.fines.all())

    @property
    def total_fine_remaining(self):
        """Get total remaining fine amount for this transaction."""
        return sum(fine.remaining_balance for fine in self.fines.filter(paid=False))

    @property
    def renewals_left(self):
        max_renewals = int(_pref('MAX_RENEWALS', 2))
        return max(0, max_renewals - self.renewed_count)

    @property
    def is_renewable(self):
        """Boolean property for templates - check all renewal conditions without message."""
        can_renew, _ = self.can_renew()
        return can_renew

    def can_renew(self):
        max_renewals = int(_pref('MAX_RENEWALS', 2))
        is_soft = self.copy.copy_type == 'softcopy' and self.borrow_type == 'softcopy'

        # 1. Max renewals: capped by system preference
        if self.renewed_count >= max_renewals:
            return False, f"Maximum renewals reached ({max_renewals} time(s))."

        renew_window = int(_pref('RENEWAL_WINDOW_DAYS', 2))
        if is_soft:
            # ── Softcopy renewal logic (different from hardcopy) ──
            # No unpaid fines check — softcopy has no fine/overdue concept.
            # No reservation check — digital copies are not physically reserved.
            # Renewal allowed when renew_window days or fewer remain, OR when link already expired.
            days_remaining = (self.due_date - timezone.now()).days
            if self.is_link_expired or (self.token_expires and timezone.now() > self.token_expires):
                return True, "Eligible for renewal (link expired)"
            if days_remaining > renew_window:
                return False, f"Renewal available when {renew_window} day(s) or fewer remain before due date. ({days_remaining} days remaining)"
            return True, "Eligible for renewal"
        else:
            # ── Hardcopy renewal logic ──
            # 2. Check for unpaid fines - block renewal if user has fines
            if Fine.objects.filter(user=self.user, paid=False).exists():
                return False, "You have unpaid fines. Please pay all fines before renewing."
            # 3. Renewal available only when renew_window days or fewer remain before due date
            days_remaining = (self.due_date - timezone.now()).days
            if days_remaining > renew_window:
                return False, f"Renewal available when {renew_window} day(s) or fewer remain before due date. ({days_remaining} days remaining)"
            # 4. Overdue check
            if self.is_overdue():
                return False, "Overdue books cannot be renewed. Please return the book."
            # 5. Hardcopy check for reservations
            if Reservation.objects.filter(
                book=self.copy.book, status='pending'
            ).exists():
                return False, "This book has pending reservations. Cannot renew."
            return True, "Eligible for renewal"

    def renew(self):
        """Renew the borrowing transaction.
        For softcopy: called AFTER payment is confirmed in softcopy_renewal_payment_view.
        For hardcopy: called directly from renew_transaction_view.
        """
        can_renew, message = self.can_renew()
        if not can_renew:
            return False, message

        loan_days = int(_pref('LOAN_PERIOD_DAYS', 7))
        self.due_date = timezone.now() + timedelta(days=loan_days)
        self.renewed_count += 1
        if self.status == 'overdue':
            self.status = 'borrowed'
        # For softcopy: generate new access token and extend expiry
        is_soft = self.copy.copy_type == 'softcopy' and self.borrow_type == 'softcopy'
        if is_soft:
            self.access_token = uuid.uuid4()
            self.token_expires = self.due_date
        self.save()
        # Create new SoftcopyAccessLog entry for softcopy renewals
        if is_soft:
            SoftcopyAccessLog.objects.create(
                user=self.user,
                copy=self.copy,
                transaction=self,
                access_token=str(self.access_token),
                access_url='',  # URL will be built by the view when needed
                expires_at=self.due_date,
            )
        return True, "Renewal successful"


# ----------------------------------------------------------------------
# Model ya Reservation — Uhifadhi wa nafasi
# Kwa vitabu vya hardcopy (nakala za kimwili) zilizokopwa zote
# Nafasi inagawiwa otomatiki (FIFO) kulingana na wakati wa kuhifadhi
# Mtiririko: pending → notified (nakala imerudishwa, subiri kukopa) → fulfilled/cancelled/expired
# ----------------------------------------------------------------------
class Reservation(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),        # Inasubiri — bado hakuna nakala iliyopatikana
        ('notified', 'Notified'),      # Ameariifiwa — nakala ipo tayari, bonyeza Borrow ndani ya siku 1
        ('fulfilled', 'Fulfilled'),    # Amekopa — mzunguko umekamilika
        ('cancelled', 'Cancelled'),   # Amefuta mwenyewe au mtunzaji amefuta
        ('expired', 'Expired'),        # Imekwisha muda bila hatua — foleni imesogea mbele
    ]

    user = models.ForeignKey(OLMSUser, on_delete=models.CASCADE, related_name='reservations')
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name='reservations')
    position = models.IntegerField(default=0)          # Nafasi kwenye foleni (1 = kwanza)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()                # Siku 14 kutoka tarehe ya kuhifadhi
    notified_at = models.DateTimeField(null=True, blank=True)  # Wakati alipoariifiwa

    class Meta:
        db_table = 'reservations'
        ordering = ['position', 'created_at']

    def __str__(self):
        return f"{self.user.username} reserving {self.book.title} (pos {self.position}) [{self.status}]"

    def save(self, *args, **kwargs):
        if not self.pk:
            if not self.expires_at:
                reservation_days = int(_pref('RESERVATION_EXPIRY_DAYS', 14))
                self.expires_at = timezone.now() + timedelta(days=reservation_days)
            # Nafasi inategemea reservations zote hai (pending + notified)
            last = Reservation.objects.filter(
                book=self.book, status__in=['pending', 'notified']
            ).order_by('-position').first()
            self.position = (last.position + 1) if last else 1
        super().save(*args, **kwargs)

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at and self.status in ('pending', 'notified')

    @property
    def hours_since_notified(self):
        if self.notified_at:
            return (timezone.now() - self.notified_at).total_seconds() / 3600
        return None


# ----------------------------------------------------------------------
# Model ya Fine — Faini ya kuchelewa kurudisha kitabu
# Kiasi kinahesabiwa kulingana na FINE_PER_DAY kwenye mipangilio
# ----------------------------------------------------------------------
class Fine(models.Model):
    user = models.ForeignKey(OLMSUser, on_delete=models.CASCADE, related_name='fines')
    transaction = models.ForeignKey(
        BorrowingTransaction, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='fines'
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)  # Total fine amount
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0)  # Amount paid so far
    reason = models.CharField(max_length=200, blank=True)
    paid = models.BooleanField(default=False)  # Fully paid flag
    payment_method = models.CharField(max_length=50, blank=True)
    receipt_no = models.TextField(blank=True, default='')  # Payment history log — each payment appended
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'fines'
        ordering = ['-created_at']

    def __str__(self):
        return f"Fine {self.amount} for {self.user.username} (Paid: {self.amount_paid})"
    
    @property
    def remaining_balance(self):
        """Calculate remaining balance to be paid"""
        return max(0, self.amount - self.amount_paid)
    
    @property
    def is_fully_paid(self):
        """Check if fine is fully paid"""
        return self.amount_paid >= self.amount


# ----------------------------------------------------------------------
# Model ya LossReport — Ripoti ya kupoteza kitabu
# Mwanachama anaweza kutuma baada ya kukopa
# Hali: pending → confirmed (mtunzaji akithibitisha) → resolved (faini imelipwa)
# ----------------------------------------------------------------------
class LossReport(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending Review'),
        ('confirmed', 'Confirmed – Awaiting Payment'),
        ('resolved', 'Resolved – Fine Paid'),
        ('dismissed', 'Dismissed'),
    ]

    transaction = models.OneToOneField(
        'BorrowingTransaction', on_delete=models.CASCADE, related_name='loss_report'
    )
    user = models.ForeignKey(OLMSUser, on_delete=models.CASCADE, related_name='loss_reports')
    description = models.TextField(help_text='Describe how/when the book was lost')
    circumstances = models.CharField(
        max_length=200, blank=True,
        help_text='Brief circumstances (e.g. fire, theft, misplaced)'
    )
    date_noticed = models.DateTimeField(null=True, blank=True, help_text='Date/time the book was noticed missing')
    last_known_location = models.CharField(max_length=200, blank=True, help_text='Where the book was last seen')
    authority_reported = models.BooleanField(default=False, help_text='Whether loss was reported to police/security')
    authority_reference = models.CharField(max_length=100, blank=True, help_text='Police/security report reference number')
    reported_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='pending')
    loss_fine = models.OneToOneField(
        'Fine', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='loss_report'
    )
    reviewed_by = models.ForeignKey(
        OLMSUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='reviewed_loss_reports'
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    librarian_notes = models.TextField(blank=True)

    class Meta:
        db_table = 'loss_reports'
        ordering = ['-reported_at']

    def __str__(self):
        return f"Loss: {self.user.username} – {self.transaction.copy.book.title} [{self.status}]"


# ----------------------------------------------------------------------
# Model ya DamageReport — Ripoti ya uharibifu wa kitabu
# Mtunzaji anaweka baada ya mwanachama kurudisha kitabu kilichoharibika
# Hali: pending → confirmed (faini imewekwa) → resolved (faini imelipwa)
# ----------------------------------------------------------------------
class DamageReport(models.Model):
    DAMAGE_TYPE_CHOICES = [
        ('pages_torn', 'Pages Torn'),
        ('cover_damaged', 'Cover Damaged'),
        ('water_damage', 'Water Damage'),
        ('spine_broken', 'Spine Broken'),
        ('writing_marking', 'Writing / Marking'),
        ('missing_pages', 'Missing Pages'),
        ('other', 'Other'),
    ]
    STATUS_CHOICES = [
        ('pending', 'Pending Review'),
        ('confirmed', 'Confirmed – Awaiting Payment'),
        ('resolved', 'Resolved – Fine Paid'),
        ('dismissed', 'Dismissed'),
    ]

    transaction = models.OneToOneField(
        'BorrowingTransaction', on_delete=models.CASCADE, related_name='damage_report'
    )
    user = models.ForeignKey(OLMSUser, on_delete=models.CASCADE, related_name='damage_reports')
    damage_type = models.CharField(max_length=20, choices=DAMAGE_TYPE_CHOICES)
    damage_description = models.TextField(blank=True, help_text='Detailed description of damage')
    reported_by = models.ForeignKey(
        OLMSUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='reported_damage_reports'
    )
    reported_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='confirmed')
    damage_fine = models.OneToOneField(
        'Fine', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='damage_report'
    )
    librarian_notes = models.TextField(blank=True)

    class Meta:
        db_table = 'damage_reports'
        ordering = ['-reported_at']

    def __str__(self):
        return f"Damage: {self.user.username} – {self.transaction.copy.book.title} [{self.status}]"

    @property
    def total_remaining(self):
        """Total remaining balance across damage fine and any overdue fine on this transaction."""
        total = Decimal('0')
        if self.damage_fine and not self.damage_fine.paid:
            total += self.damage_fine.remaining_balance
        # Include overdue fine if present
        overdue_fine = Fine.objects.filter(
            transaction=self.transaction,
            reason__icontains='Overdue',
        ).exclude(id=self.damage_fine_id if self.damage_fine_id else 0).first()
        if overdue_fine and not overdue_fine.paid:
            total += overdue_fine.remaining_balance
        return total


# ----------------------------------------------------------------------
# Model ya Notification — Arifa zilizotumwa kwa mwanachama
# SMS au barua pepe
# channel: 'sms' au 'email' | status: pending → sent / failed
# ----------------------------------------------------------------------
class Notification(models.Model):
    CHANNEL_CHOICES = [('email', 'Email'), ('sms', 'SMS')]
    STATUS_CHOICES = [('pending', 'Pending'), ('sent', 'Sent'), ('failed', 'Failed')]
    PRIORITY_CHOICES = [('low', 'Low'), ('normal', 'Normal'), ('high', 'High')]
    MESSAGE_TYPE_CHOICES = [
        ('otp', 'OTP'),
        ('account_lock', 'Account Lock'),
        ('suspended', 'Suspended'),
        ('suspicious', 'Suspicious'),
        ('borrowing', 'Borrowing'),
        ('approval', 'Approval'),
        ('rejection', 'Rejection'),
        ('fine', 'Fine'),
        ('overdue', 'Overdue'),
        ('loss_report', 'Loss Report'),
        ('loss_fine', 'Loss Fine'),
        ('damage_report', 'Damage Report'),
        ('damage_fine', 'Damage Fine'),
        ('softcopy_link', 'Softcopy Link'),
        ('softcopy_expiry', 'Softcopy Expiry Warning'),
        ('password_reminder', 'Password Change Reminder'),
        ('registration_approved', 'Registration Approved'),
        ('registration_rejected', 'Registration Rejected'),
        ('bulk_message', 'Bulk Message'),
        ('new_arrival', 'New Arrival'),
    ]

    user = models.ForeignKey(OLMSUser, on_delete=models.CASCADE, related_name='notifications')
    message = models.TextField()
    message_type = models.CharField(max_length=30, choices=MESSAGE_TYPE_CHOICES, default='approval', blank=True, null=True)
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='normal')
    channel = models.CharField(max_length=10, choices=CHANNEL_CHOICES)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    is_security_alert = models.BooleanField(default=False, help_text='Mark as security alert (suspension, lock attempts, suspicious activity)')
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'notifications'
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.channel}] to {self.user.username}: {self.message[:50]}"


# ----------------------------------------------------------------------
# Model ya PrepaidTransaction — Malipo ya awali kwa softcopy access
# Inafuatilia malipo ya M-Pesa na payment gateway nyingine
# ----------------------------------------------------------------------
class PrepaidTransaction(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]
    PAYMENT_METHOD_CHOICES = [
        ('mpesa', 'M-Pesa'),
        ('tigopesa', 'Tigo Pesa'),
        ('airtel', 'Airtel Money'),
        ('halotel', 'Halotel'),
        ('card', 'Card'),
        ('bank', 'Bank'),
        ('cash', 'Cash'),
    ]

    user = models.ForeignKey(OLMSUser, on_delete=models.CASCADE, related_name='prepaid_transactions')
    copy = models.ForeignKey(BookCopy, on_delete=models.CASCADE, related_name='prepaid_transactions')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_method = models.CharField(max_length=10, choices=PAYMENT_METHOD_CHOICES, default='mpesa')
    transaction_id = models.CharField(max_length=100, unique=True, blank=True, null=True)  # External payment gateway ID
    phone_number = models.CharField(max_length=15, blank=True, default='')  # Mobile money phone
    bank_name = models.CharField(max_length=50, blank=True, default='')  # Bank name for bank transfers
    bank_account_no = models.CharField(max_length=20, blank=True, default='')  # Bank account number
    card_last4 = models.CharField(max_length=4, blank=True, default='')  # Last 4 digits of card
    card_holder = models.CharField(max_length=100, blank=True, default='')  # Cardholder name
    receipt_no = models.CharField(max_length=50, blank=True, default='')  # Reference/receipt number
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    payment_date = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'prepaid_transactions'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} - TZS {self.amount} [{self.status}]"


# ----------------------------------------------------------------------
# Model ya SoftcopyAccessLogs — Kufuatilia links za softcopy access
# Inahifadhi links za kipekee zinazoexpire baada ya siku 7
# ----------------------------------------------------------------------
class SoftcopyAccessLog(models.Model):
    user = models.ForeignKey(OLMSUser, on_delete=models.CASCADE, related_name='softcopy_access_logs')
    copy = models.ForeignKey(BookCopy, on_delete=models.CASCADE, related_name='softcopy_access_logs')
    transaction = models.ForeignKey(BorrowingTransaction, on_delete=models.CASCADE, related_name='softcopy_access_logs')
    access_token = models.CharField(max_length=100, unique=True)  # Unique token for URL
    access_url = models.URLField()  # Full secure URL
    expires_at = models.DateTimeField()  # 7 days from creation
    access_count = models.IntegerField(default=0)  # How many times accessed
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'softcopy_access_logs'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} - {self.copy.book.title} (expires: {self.expires_at})"

    def is_expired(self):
        return timezone.now() > self.expires_at

    def days_until_expiry(self):
        delta = self.expires_at - timezone.now()
        return max(0, delta.days)


# ----------------------------------------------------------------------
# Model ya RevenueTransaction — Ufuatiliaji wa mapato/hasara
# account_type: overdue, link_fee, guest_fee, loss
# amount: chanya = mapato, hasi = hasara/refund
# ----------------------------------------------------------------------
class RevenueTransaction(models.Model):
    ACCOUNT_TYPE_CHOICES = [
        ('overdue', 'Overdue Fee'),
        ('link_fee', 'Softcopy Link Fee'),
        ('guest_fee', 'Guest Session Fee'),
        ('loss', 'Loss / Refund'),
        ('damage', 'Damage Fee'),
    ]

    user = models.ForeignKey(OLMSUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='revenue_transactions')
    account_type = models.CharField(max_length=20, choices=ACCOUNT_TYPE_CHOICES)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.TextField(blank=True)
    reference_id = models.BigIntegerField(null=True, blank=True)
    reference_table = models.CharField(max_length=100, blank=True)
    recorded_at = models.DateTimeField(auto_now_add=True)
    recorded_by = models.ForeignKey(OLMSUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='recorded_revenue_transactions')

    class Meta:
        db_table = 'revenue_transactions'
        ordering = ['-recorded_at']

    def __str__(self):
        who = self.user.username if self.user else 'System'
        return f"{self.account_type} | TZS {self.amount} | {who}"


