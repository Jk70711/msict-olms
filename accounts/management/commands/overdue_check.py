from django.core.management.base import BaseCommand
from django.utils import timezone
from circulation.models import BorrowingTransaction, Fine, Notification
from accounts.utils import send_sms, send_email_notification


class Command(BaseCommand):
    help = 'Mark overdue transactions and send reminders. Run daily via cron.'

    def handle(self, *args, **options):
        now = timezone.now()
        updated = 0
        notified = 0

        active_txs = BorrowingTransaction.objects.filter(
            status='borrowed', due_date__lt=now
        ).select_related('user', 'copy__book')

        for tx in active_txs:
            tx.status = 'overdue'
            tx.save(update_fields=['status'])
            updated += 1

            msg = (
                f"MSICT OLMS: Your borrow of '{tx.copy.book.title}' is overdue by "
                f"{tx.days_overdue()} day(s). Please return immediately to avoid further fines."
            )
            Notification.objects.create(user=tx.user, message=msg, channel='sms')
            Notification.objects.create(user=tx.user, message=msg, channel='email')
            send_sms(tx.user.phone, msg)
            send_email_notification(tx.user.email, "MSICT OLMS – Overdue Book", msg)
            notified += 1

        self.stdout.write(self.style.SUCCESS(
            f'[overdue_check] Marked {updated} transactions as overdue. Notified {notified} members.'
        ))
