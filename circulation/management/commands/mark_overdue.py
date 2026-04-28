"""
Management command: mark_overdue
Marks all borrowed transactions past their due date as 'overdue'.
Run via cron or manually:
    python manage.py mark_overdue
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from circulation.models import BorrowingTransaction
from accounts.utils import create_notification, send_sms, send_email_notification


class Command(BaseCommand):
    help = 'Mark overdue borrowing transactions and notify affected users'

    def handle(self, *args, **options):
        now = timezone.now()
        overdue_qs = BorrowingTransaction.objects.filter(
            status='borrowed',
            due_date__lt=now,
        ).select_related('user', 'copy__book')

        count = overdue_qs.count()
        if count == 0:
            self.stdout.write(self.style.SUCCESS('No new overdue transactions found.'))
            return

        updated = 0
        for tx in overdue_qs:
            tx.status = 'overdue'
            tx.save(update_fields=['status'])
            days = (now - tx.due_date).days
            msg = (
                f"MSICT OLMS: '{tx.copy.book.title}' is OVERDUE by {days} day(s). "
                f"{'Return the soft copy online or ' if tx.copy.copy_type == 'softcopy' else ''}"
                f"Return immediately to avoid additional fines."
            )
            create_notification(tx.user, msg, 'sms')
            create_notification(tx.user, msg, 'email')
            send_sms(tx.user.phone, msg)
            send_email_notification(tx.user.email, "Overdue Notice – MSICT OLMS", msg)
            updated += 1

        self.stdout.write(self.style.WARNING(
            f'Marked {updated} transaction(s) as overdue and notified users.'
        ))
