"""
Management command: send_due_reminders
Sends SMS + email reminders for borrowing transactions due in ~2 days, ~1 day, and on due day.

Schedule via cron to run every hour:
    0 * * * * /path/to/olmsvenv/bin/python /path/to/manage.py send_due_reminders

Window logic (prevents duplicate sends when run hourly):
  - 2-day reminder : due_date in (now + 47h, now + 49h)
  - 1-day reminder : due_date in (now + 23h, now + 25h)
  - Due-day notice : due_date in (now - 1h,  now + 1h)
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.utils import notify_user
from circulation.models import BorrowingTransaction


class Command(BaseCommand):
    help = 'Send due-date reminder SMS/email: 2 days before, 1 day before, and on due day'

    def handle(self, *args, **options):
        now = timezone.now()
        total = 0

        reminders = [
            (
                '2-day',
                now + timedelta(hours=47),
                now + timedelta(hours=49),
                lambda book, copy_type, due: (
                    f"MSICT OLMS: Reminder — '{book}' is due in 2 days "
                    f"({due.strftime('%d %b %Y %H:%M')}). "
                    + ("Sign in to your dashboard to read or return online."
                       if copy_type == 'softcopy'
                       else "Please return to the library on time to avoid fines.")
                ),
            ),
            (
                '1-day',
                now + timedelta(hours=23),
                now + timedelta(hours=25),
                lambda book, copy_type, due: (
                    f"MSICT OLMS: URGENT — '{book}' is due TOMORROW "
                    f"({due.strftime('%d %b %Y %H:%M')}). "
                    + ("Return it online from your dashboard before the link expires."
                       if copy_type == 'softcopy'
                       else "Bring the book to the library tomorrow to avoid a TZS 500/day fine.")
                ),
            ),
            (
                'due-day',
                now - timedelta(hours=1),
                now + timedelta(hours=1),
                lambda book, copy_type, due: (
                    f"MSICT OLMS: '{book}' is DUE TODAY "
                    f"({due.strftime('%H:%M')}). "
                    + ("Return it now from your dashboard to avoid overdue status."
                       if copy_type == 'softcopy'
                       else "Return the book immediately to avoid overdue fines (TZS 500/day).")
                ),
            ),
        ]

        for label, window_start, window_end, msg_fn in reminders:
            qs = BorrowingTransaction.objects.filter(
                status='borrowed',
                due_date__gte=window_start,
                due_date__lte=window_end,
            ).select_related('user', 'copy__book')

            count = qs.count()
            if count == 0:
                self.stdout.write(f'[{label}] No transactions in window.')
                continue

            for tx in qs:
                book      = tx.copy.book.title
                copy_type = tx.copy.copy_type
                due       = timezone.localtime(tx.due_date)
                msg       = msg_fn(book, copy_type, due)

                notify_user(tx.user, msg, 'sms')
                notify_user(tx.user, msg, 'email',
                            subject=f"MSICT OLMS – Due Date Reminder ({label.replace('-', ' ').title()})")
                total += 1

            self.stdout.write(self.style.WARNING(
                f'[{label}] Sent {count} reminder(s).'
            ))

        self.stdout.write(self.style.SUCCESS(
            f'Done. Total reminders sent: {total}.'
        ))
