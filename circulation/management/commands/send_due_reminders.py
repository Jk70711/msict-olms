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
from accounts.models import SystemPreference
from circulation.models import BorrowingTransaction


class Command(BaseCommand):
    help = 'Send due-date reminder SMS/email: 2 days before, 1 day before, and on due day'

    def handle(self, *args, **options):
        now = timezone.now()
        total = 0

        # Fetch fine rate from system settings (not hardcoded)
        fine_per_day = float(SystemPreference.get('FINE_PER_DAY', 1000))

        reminders = [
            (
                '2-day',
                now + timedelta(hours=47),
                now + timedelta(hours=49),
                lambda book, copy_type, due, fpd=fine_per_day: (
                    f"MSICT OLMS: REMINDER - '{book}' is due in 2 days "
                    f"({due.strftime('%d %b %Y %H:%M')}). "
                    + (f"Your softcopy access link expires in 2 days. Renew from your dashboard to keep access."
                       if copy_type == 'softcopy'
                       else f"Please return the book to the library on time to avoid fines (TZS {fpd:,.0f}/day).")
                ),
            ),
            (
                '1-day',
                now + timedelta(hours=23),
                now + timedelta(hours=25),
                lambda book, copy_type, due, fpd=fine_per_day: (
                    f"MSICT OLMS: URGENT - '{book}' softcopy access expires TOMORROW "
                    f"({due.strftime('%d %b %Y %H:%M')}). "
                    + (f"Renew your access link from your dashboard before it expires — no overdue fine, but access will stop."
                       if copy_type == 'softcopy'
                       else f"Bring the book to the library tomorrow to avoid a TZS {fpd:,.0f}/day overdue fine.")
                ),
            ),
            (
                'due-day',
                now - timedelta(hours=1),
                now + timedelta(hours=1),
                lambda book, copy_type, due, fpd=fine_per_day: (
                    f"MSICT OLMS: ACCESS EXPIRING TODAY - '{book}' softcopy link expires at "
                    f"{due.strftime('%H:%M')}. "
                    + (f"Renew now from your dashboard to keep access. No fine — link simply expires."
                       if copy_type == 'softcopy'
                       else f"Return the book to the library immediately. A TZS {fpd:,.0f}/day fine starts after the deadline.")
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

                _priority = 'normal' if label == '2-day' else 'high'
                notify_user(tx.user, msg, 'sms', priority=_priority, message_type='borrowing')
                notify_user(tx.user, msg, 'email',
                            subject=f"MSICT OLMS — {label.replace('-', ' ').title()} Due Date Reminder",
                            priority=_priority, message_type='borrowing')
                total += 1

            self.stdout.write(self.style.WARNING(
                f'[{label}] Sent {count} reminder(s).'
            ))

        self.stdout.write(self.style.SUCCESS(
            f'[send_due_reminders] Done. Total sent: {total}.'
        ))
