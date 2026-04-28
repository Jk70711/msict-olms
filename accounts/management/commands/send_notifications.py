from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from circulation.models import BorrowingTransaction, Notification
from accounts.utils import send_sms, send_email_notification


class Command(BaseCommand):
    help = 'Send due-date reminders for books due in 1 day. Run daily via cron.'

    def handle(self, *args, **options):
        tomorrow = timezone.now().date() + timedelta(days=1)
        due_soon = BorrowingTransaction.objects.filter(
            status='borrowed',
            due_date__date=tomorrow
        ).select_related('user', 'copy__book')

        count = 0
        for tx in due_soon:
            msg = (
                f"MSICT OLMS: Reminder – '{tx.copy.book.title}' is due tomorrow "
                f"({tx.due_date.date()}). Please return on time to avoid fines."
            )
            Notification.objects.create(user=tx.user, message=msg, channel='sms')
            Notification.objects.create(user=tx.user, message=msg, channel='email')
            send_sms(tx.user.phone, msg)
            send_email_notification(tx.user.email, "MSICT OLMS – Due Tomorrow", msg)
            count += 1

        self.stdout.write(self.style.SUCCESS(
            f'[send_notifications] Sent {count} due-date reminder(s).'
        ))
