# ============================================================
# circulation/models.py
# Mifano ya data kwa mikopo, maombi, uhifadhi, faini, arifa
# Hii ndiyo moyo wa mfumo — inashughulikia harakati zote za vitabu
# ============================================================

from django.db import models
from django.utils import timezone
from datetime import timedelta
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


# Ombi la kukopa kitabu — mwanachama anatuma, mtunzaji anaidhinisha au kukataa
# Hali: pending (inasubiri) → approved (imeidhinishwa) / rejected (imekataliwa)
class BorrowRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
    ]
    user = models.ForeignKey(OLMSUser, on_delete=models.CASCADE, related_name='borrow_requests')  # Mwanachama aliyeomba
    copy = models.ForeignKey(BookCopy, on_delete=models.CASCADE, related_name='borrow_requests')  # Nakala iliyoombiwa
    request_date = models.DateTimeField(auto_now_add=True)  # Tarehe ya ombi
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')  # Hali ya sasa
    approved_by = models.ForeignKey(
        OLMSUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='approved_requests'
    )  # Mtunzaji aliyeidhinisha au kukataa
    rejection_reason = models.CharField(max_length=500, blank=True)  # Sababu ya kukataliwa

    class Meta:
        db_table = 'borrow_requests'
        ordering = ['-request_date']

    def __str__(self):
        return f"{self.user.username} → {self.copy.book.title} [{self.status}]"


# Mkopo ulioidhinishwa — unafuatilia vitabu vilivyokopwa
# Hali: borrowed → returned (imerudishwa) / overdue (imechelewa)
class BorrowingTransaction(models.Model):
    BORROW_TYPE_CHOICES = [('hardcopy', 'Hardcopy'), ('softcopy', 'Softcopy')]
    STATUS_CHOICES = [
        ('borrowed', 'Borrowed'),
        ('returned', 'Returned'),
        ('overdue', 'Overdue'),
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
    renewed_count = models.IntegerField(default=0)  # Mara ngapi mkopo umefanyiwa upya

    class Meta:
        db_table = 'borrowing_transactions'
        ordering = ['-borrow_date']

    def __str__(self):
        return f"{self.user.username} – {self.copy.book.title} (due {self.due_date.date()})"

    def save(self, *args, **kwargs):
        if not self.pk and not self.due_date:
            if self.borrow_type == 'softcopy':
                loan_days = int(_pref('SOFTCOPY_LOAN_PERIOD_DAYS', 3))
            else:
                loan_days = int(_pref('LOAN_PERIOD_DAYS', 7))
            self.due_date = timezone.now() + timedelta(days=loan_days)
        super().save(*args, **kwargs)

    def is_overdue(self):
        return self.status == 'borrowed' and timezone.now() > self.due_date

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
        """Human-readable countdown: '3d 4h left', '5h 20m left', 'Due now', '2d overdue'."""
        if self.status == 'returned':
            return '—'
        delta = self.due_date - timezone.now()
        total_secs = int(delta.total_seconds())
        if total_secs <= 0:
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
        return self.status in ('borrowed', 'overdue') and timezone.now() <= self.due_date

    @property
    def renewals_left(self):
        max_renewals = int(_pref('MAX_RENEWALS', 2))
        return max(0, max_renewals - self.renewed_count)

    def can_renew(self):
        max_renewals = int(_pref('MAX_RENEWALS', 2))
        if self.renewed_count >= max_renewals:
            return False
        is_soft = self.copy.copy_type == 'softcopy'
        if not is_soft and self.is_overdue():
            return False
        if not is_soft:
            if Reservation.objects.filter(
                book=self.copy.book, status='pending'
            ).exists():
                return False
        return True

    def renew(self):
        if self.can_renew():
            if self.copy.copy_type == 'softcopy':
                loan_days = int(_pref('SOFTCOPY_LOAN_PERIOD_DAYS', 3))
            else:
                loan_days = int(_pref('LOAN_PERIOD_DAYS', 7))
            self.due_date = timezone.now() + timedelta(days=loan_days)
            self.renewed_count += 1
            if self.status == 'overdue':
                self.status = 'borrowed'
            self.save()
            return True
        return False


# Uhifadhi wa nafasi — kwa vitabu vya hardcopy (nakala za kimwili) zilizokopwa zote
# Nafasi inagawiwa otomatiki (FIFO) kulingana na wakati wa kuhifadhi
# Mtiririko: pending → notified (nakala imerudishwa, subiri kukopa) → fulfilled/cancelled/expired
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


# Faini ya kuchelewa kurudisha kitabu
# Kiasi kinahesabiwa kulingana na FINE_PER_DAY kwenye mipangilio
class Fine(models.Model):
    user = models.ForeignKey(OLMSUser, on_delete=models.CASCADE, related_name='fines')
    transaction = models.ForeignKey(
        BorrowingTransaction, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='fines'
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    reason = models.CharField(max_length=200, blank=True)
    paid = models.BooleanField(default=False)
    payment_method = models.CharField(max_length=50, blank=True)
    receipt_no = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'fines'
        ordering = ['-created_at']

    def __str__(self):
        return f"Fine {self.amount} for {self.user.username}"


# Arifa zilizotumwa kwa mwanachama — SMS au barua pepe
# channel: 'sms' au 'email' | status: pending → sent / failed
class Notification(models.Model):
    CHANNEL_CHOICES = [('email', 'Email'), ('sms', 'SMS')]
    STATUS_CHOICES = [('pending', 'Pending'), ('sent', 'Sent'), ('failed', 'Failed')]
    PRIORITY_CHOICES = [('low', 'Low'), ('normal', 'Normal'), ('high', 'High')]

    user = models.ForeignKey(OLMSUser, on_delete=models.CASCADE, related_name='notifications')
    message = models.TextField()
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='normal')
    channel = models.CharField(max_length=10, choices=CHANNEL_CHOICES)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'notifications'
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.channel}] to {self.user.username}: {self.message[:50]}"
