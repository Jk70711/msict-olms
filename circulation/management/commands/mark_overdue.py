"""
Management command: mark_overdue
Three jobs in one daily run:
  1. Mark newly-overdue transactions (borrowed → overdue) and send first-overdue alert.
  2. Send daily consecutive reminder to transactions that are ALREADY overdue.
  3. Send daily reminder for members with unpaid LOSS fines.

Run daily via cron (recommended: 01:00 AM):
    0 1 * * * /path/venv/bin/python /path/manage.py mark_overdue >> /path/logs/olms_overdue.log 2>&1
"""

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone
from circulation.models import BorrowingTransaction, Fine, LossReport
from accounts.utils import notify_user


class Command(BaseCommand):
    help = 'Mark overdue transactions and send daily consecutive SMS/email/in-app alerts'

    def handle(self, *args, **options):
        now = timezone.now()
        newly_marked = 0
        daily_reminded = 0
        loss_reminded = 0

        from accounts.models import SystemPreference
        fine_per_day = Decimal(str(SystemPreference.get('FINE_PER_DAY', 1000)))

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
            notify_user(tx.user, msg, 'sms', priority='high', message_type='overdue')
            notify_user(tx.user, msg, 'email',
                        subject='OVERDUE Book Notice - MSICT OLMS', priority='high', message_type='overdue')
            newly_marked_ids.append(tx.pk)
            newly_marked += 1

        # ── Step 2: Daily consecutive alert — EXCLUDE transactions just marked ─
        # "until paid": skip if fine is fully paid (amount_paid >= amount).
        # We use Exists() to avoid duplicate rows from the join.
        from django.db.models import Exists, OuterRef, Q
        unpaid_fine_exists = Exists(
            Fine.objects.filter(transaction=OuterRef('pk'), paid=False)
        )
        no_fine_yet = ~Exists(Fine.objects.filter(transaction=OuterRef('pk')))

        already_overdue_qs = BorrowingTransaction.objects.filter(
            status='overdue',
        ).exclude(
            pk__in=newly_marked_ids,  # Don't double-notify on day 1
        ).filter(
            unpaid_fine_exists | no_fine_yet  # Stop reminders once fine is fully paid
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
                remaining = float(existing_fine.remaining_balance)
            else:
                Fine.objects.create(
                    user=tx.user,
                    transaction=tx,
                    amount=total_fine,
                    reason=f"Overdue fine for '{tx.copy.book.title}' ({days} days)",
                    paid=False,
                )
                remaining = total_fine

            return_hint = (
                "Return online from your dashboard or "
                if tx.copy.copy_type == 'softcopy'
                else "Return the book to the library or "
            )
            msg = (
                f"MSICT OLMS: DAILY REMINDER - '{tx.copy.book.title}' is {days} day(s) overdue. "
                f"Total fine: TZS {total_fine:,.0f} | Remaining: TZS {remaining:,.0f}. "
                f"{return_hint}pay fines at the circulation desk."
            )
            notify_user(tx.user, msg, 'sms', priority='high', message_type='overdue')
            notify_user(tx.user, msg, 'email',
                        subject=f'Overdue Reminder (Day {days}) - MSICT OLMS', priority='high', message_type='overdue')
            daily_reminded += 1

        # ── Step 3: Lost transactions PAST due date — dual concurrent fines ──
        # Rules:
        #   A) Loss reported BEFORE due date, paid BEFORE due date → no overdue fine.
        #   B) Loss reported BEFORE due date, NOT paid by due date → BOTH fines.
        #   C) Loss reported AFTER due date (confirmed after due) → BOTH fines.
        #
        # We find all confirmed LossReports whose transaction.due_date < now.
        # The overdue fine is identified by reason__icontains='Overdue' and is
        # distinct from the loss fine (excluded by loss_fine_id).
        from django.db.models import Q as _Q

        lost_past_due_qs = LossReport.objects.filter(
            status='confirmed',
            transaction__isnull=False,
            transaction__due_date__lt=now,
        ).select_related('user', 'transaction__copy__book', 'loss_fine')

        lost_reminded = 0
        for lr in lost_past_due_qs:
            tx = lr.transaction
            loss_fine = lr.loss_fine
            book_title = tx.copy.book.title
            days = max(1, (now - tx.due_date).days)
            total_overdue = days * fine_per_day

            # Rule A: Loss fine paid on time (before due date) → no overdue fine.
            loss_paid_on_time = (
                loss_fine is not None
                and loss_fine.paid
                and loss_fine.paid_at is not None
                and loss_fine.paid_at <= tx.due_date
            )
            if loss_paid_on_time:
                continue

            # Find or create the overdue fine (separate from the loss fine).
            # Identified by 'Overdue' in reason, excluding the loss fine row.
            loss_fine_id = lr.loss_fine_id
            overdue_fine_qs = Fine.objects.filter(
                transaction=tx,
                reason__icontains='Overdue',
            )
            if loss_fine_id:
                overdue_fine_qs = overdue_fine_qs.exclude(id=loss_fine_id)
            overdue_fine = overdue_fine_qs.first()

            if overdue_fine:
                if not overdue_fine.paid:
                    overdue_fine.amount = total_overdue
                    overdue_fine.reason = f"Overdue fine for '{book_title}' ({days} days)"
                    overdue_fine.save(update_fields=['amount', 'reason'])
            else:
                overdue_fine = Fine.objects.create(
                    user=tx.user,
                    transaction=tx,
                    amount=total_overdue,
                    reason=f"Overdue fine for '{book_title}' ({days} days)",
                    paid=False,
                )

            # Compute remaining balances for both fines.
            loss_remaining = loss_fine.remaining_balance if loss_fine else Decimal('0')
            overdue_remaining = overdue_fine.remaining_balance

            # Nothing to remind if both fully paid.
            if loss_remaining <= 0 and overdue_remaining <= 0:
                continue

            # Build a combined message listing each unpaid fine.
            fine_parts = []
            if loss_remaining > 0:
                fine_parts.append(f"LOSS fine: TZS {loss_remaining:,.0f}")
            if overdue_remaining > 0:
                fine_parts.append(f"OVERDUE fine ({days} day(s) @ TZS {fine_per_day:,.0f}/day): TZS {overdue_remaining:,.0f}")
            total_due = loss_remaining + overdue_remaining
            msg = (
                f"MSICT OLMS: LOST BOOK FINES - '{book_title}'. "
                + " | ".join(fine_parts)
                + f" | Total outstanding: TZS {total_due:,.0f}."
                f" Pay at the circulation desk to clear your account."
            )
            notify_user(lr.user, msg, 'sms', priority='high', message_type='loss_fine')
            notify_user(lr.user, msg, 'email',
                        subject='Lost Book – Outstanding Fines – MSICT OLMS',
                        priority='high', message_type='loss_fine')
            lost_reminded += 1

        # ── Step 4: Loss-only reminder (still within loan period) ────────────
        # Targets confirmed LossReports whose transaction.due_date is still in
        # the future — only the loss fine applies here (no overdue fine yet).
        loss_only_qs = LossReport.objects.filter(
            status='confirmed',
            loss_fine__isnull=False,
            loss_fine__paid=False,
            transaction__due_date__gte=now,
        ).select_related('user', 'transaction__copy__book', 'loss_fine')

        loss_only_reminded = 0
        for lr in loss_only_qs:
            fine = lr.loss_fine
            remaining = fine.remaining_balance
            if remaining <= 0:
                continue
            book_title = lr.transaction.copy.book.title if lr.transaction else 'Unknown Book'
            days_left = max(0, (lr.transaction.due_date - now).days) if lr.transaction else 0
            days_since = (now - lr.reviewed_at).days if lr.reviewed_at else 0
            msg = (
                f"MSICT OLMS: LOSS FINE REMINDER - You have an unpaid loss fine for "
                f"'{book_title}'. Amount due: TZS {remaining:,.0f}. "
                f"Days since confirmed: {days_since} day(s). "
                f"NOTE: If not paid within {days_left} day(s), an overdue fine will also apply. "
                f"Please pay at the circulation desk."
            )
            notify_user(lr.user, msg, 'sms', priority='high', message_type='loss_fine')
            notify_user(lr.user, msg, 'email',
                        subject='Loss Fine Reminder - MSICT OLMS',
                        priority='high', message_type='loss_fine')
            loss_only_reminded += 1

        self.stdout.write(self.style.SUCCESS(
            f'[mark_overdue] Newly marked: {newly_marked} | '
            f'Overdue reminders: {daily_reminded} | '
            f'Lost+overdue reminders: {lost_reminded} | '
            f'Loss-only reminders: {loss_only_reminded}'
        ))
