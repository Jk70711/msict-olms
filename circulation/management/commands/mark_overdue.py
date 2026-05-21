"""
Management command: mark_overdue
Two jobs in one daily run:
  1. Mark newly-overdue transactions (borrowed → overdue) and send first-overdue alert.
  2. Send daily consecutive reminder to transactions that are ALREADY overdue.

Run daily via cron (recommended: 01:00 AM):
    0 1 * * * /path/venv/bin/python /path/manage.py mark_overdue >> /var/log/olms_overdue.log 2>&1
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from circulation.models import BorrowingTransaction, Fine
from accounts.utils import notify_user


class Command(BaseCommand):
    help = 'Mark overdue transactions and send daily consecutive SMS/email/in-app alerts'

    def handle(self, *args, **options):
        now = timezone.now()
        newly_marked = 0
        daily_reminded = 0

        from accounts.models import SystemPreference
        fine_per_day = float(SystemPreference.get('FINE_PER_DAY', 500))

        # ── Step 1: Mark borrowed→overdue and send first alert ─────────────
        new_overdue_qs = BorrowingTransaction.objects.filter(
            status='borrowed',
            due_date__lt=now,
        ).select_related('user', 'copy__book')

        newly_marked_ids = []
        for tx in new_overdue_qs:
            tx.status = 'overdue'
            tx.save(update_fields=['status'])
            days = max(1, (now - tx.due_date).days)
            fine_amount = days * fine_per_day

            # Upsert fine — never use paid=False as lookup key (avoids duplicates)
            existing_fine = Fine.objects.filter(transaction=tx).first()
            if existing_fine:
                if not existing_fine.paid:
                    existing_fine.amount = fine_amount
                    existing_fine.reason = f"Overdue fine for '{tx.copy.book.title}' ({days} days)"
                    existing_fine.save(update_fields=['amount', 'reason'])
            else:
                Fine.objects.create(
                    user=tx.user,
                    transaction=tx,
                    amount=fine_amount,
                    reason=f"Overdue fine for '{tx.copy.book.title}' ({days} days)",
                    paid=False,
                )

            return_hint = (
                "Return the soft copy online from your dashboard or "
                if tx.copy.copy_type == 'softcopy'
                else "Bring the book to the library or "
            )
            msg = (
                f"MSICT OLMS: OVERDUE - '{tx.copy.book.title}' is overdue by {days} day(s). "
                f"Fine so far: TZS {fine_amount:,.0f}. "
                f"{return_hint}contact the librarian immediately to avoid further fines."
            )
            notify_user(tx.user, msg, 'sms', priority='high')
            notify_user(tx.user, msg, 'email',
                        subject='OVERDUE Book Notice - MSICT OLMS', priority='high')
            newly_marked_ids.append(tx.pk)
            newly_marked += 1

        # ── Step 2: Daily consecutive alert — EXCLUDE transactions just marked ─
        already_overdue_qs = BorrowingTransaction.objects.filter(
            status='overdue',
        ).exclude(
            pk__in=newly_marked_ids,  # Don't double-notify on day 1
        ).select_related('user', 'copy__book')

        for tx in already_overdue_qs:
            days = max(1, (now - tx.due_date).days)
            total_fine = days * fine_per_day

            # Update fine amount (accumulated daily)
            existing_fine = Fine.objects.filter(transaction=tx).first()
            if existing_fine:
                if not existing_fine.paid:
                    existing_fine.amount = total_fine
                    existing_fine.reason = f"Overdue fine for '{tx.copy.book.title}' ({days} days)"
                    existing_fine.save(update_fields=['amount', 'reason'])
            else:
                Fine.objects.create(
                    user=tx.user,
                    transaction=tx,
                    amount=total_fine,
                    reason=f"Overdue fine for '{tx.copy.book.title}' ({days} days)",
                    paid=False,
                )

            return_hint = (
                "Return online from your dashboard or "
                if tx.copy.copy_type == 'softcopy'
                else "Return the book to the library or "
            )
            msg = (
                f"MSICT OLMS: DAILY REMINDER - '{tx.copy.book.title}' is {days} day(s) overdue. "
                f"Accumulated fine: TZS {total_fine:,.0f}. "
                f"{return_hint}pay fines at the circulation desk."
            )
            notify_user(tx.user, msg, 'sms', priority='high')
            notify_user(tx.user, msg, 'email',
                        subject=f'Overdue Reminder ({days}d) - MSICT OLMS', priority='high')
            daily_reminded += 1

        self.stdout.write(self.style.SUCCESS(
            f'[mark_overdue] Newly marked: {newly_marked} | Daily reminders: {daily_reminded}'
        ))
