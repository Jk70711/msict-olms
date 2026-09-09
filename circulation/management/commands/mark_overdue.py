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
from circulation.models import BorrowingTransaction, Fine, LossReport, SoftcopyAccessLog
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

        # ── Cleanup: Mark any existing overdue softcopies back to 'borrowed' ─
        # ALL softcopies should NEVER be marked as 'overdue' — no fine concept.
        # They simply expire after their loan period.
        overdue_softcopies = BorrowingTransaction.objects.filter(
            status='overdue',
            copy__copy_type='softcopy'
        )
        if overdue_softcopies.exists():
            count = overdue_softcopies.count()
            overdue_softcopies.update(status='borrowed')
            self.stdout.write(
                self.style.WARNING(
                    f'Cleaned up {count} overdue special softcopy transaction(s) → status "borrowed"'
                )
            )

        # ── Cleanup 2: Fix orphaned borrowed copies (Data Consistency) ──────
        from circulation.models import BookCopy
        from django.db.models import Exists, OuterRef
        
        # Find copies marked borrowed but with NO active transaction
        active_tx_exists = Exists(
            BorrowingTransaction.objects.filter(
                copy=OuterRef('pk'),
                status__in=['borrowed', 'overdue']
            )
        )
        orphaned_copies = BookCopy.objects.filter(
            status='borrowed'
        ).annotate(
            has_active_tx=active_tx_exists
        ).filter(has_active_tx=False)
        
        orphaned_count = orphaned_copies.count()
        if orphaned_count > 0:
            # We must use update() to quickly reset them to 'lost'
            # (If the transaction was deleted abruptly without return, the physical book is missing)
            orphaned_copies.update(status='lost')
            self.stdout.write(
                self.style.SUCCESS(
                    f'Self-Healed: Marked {orphaned_count} orphaned "borrowed" copies as "lost"'
                )
            )


        # ── Step 1: Mark borrowed→overdue and send first alert ─────────────
        # EXCLUDE ALL softcopies — they just expire without penalty
        new_overdue_qs = BorrowingTransaction.objects.filter(
            status='borrowed',
            due_date__lt=now,
        ).exclude(
            copy__copy_type='softcopy'
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

            msg = (
                f"MSICT OLMS: OVERDUE - '{tx.copy.book.title}' is overdue by {days} day(s). "
                f"Fine so far: TZS {fine_amount:,.0f}. "
                f"Bring the book to the library or contact the librarian immediately to avoid further fines."
            )
            notify_user(tx.user, msg, 'sms', priority='high', message_type='overdue')
            notify_user(tx.user, msg, 'email',
                        subject='OVERDUE Book Notice - MSICT OLMS', priority='high', message_type='overdue')
            newly_marked_ids.append(tx.pk)
            newly_marked += 1

        # ── Step 2: Daily consecutive alert — EXCLUDE transactions just marked ─
        # EXCLUDE ALL softcopies — they just expire without penalty
        already_overdue_qs = BorrowingTransaction.objects.filter(
            status='overdue',
        ).exclude(
            pk__in=newly_marked_ids,  # Don't double-notify on day 1
        ).exclude(
            copy__copy_type='softcopy'
        ).select_related('user', 'copy__book')

        for tx in already_overdue_qs:
            days = max(1, (now - tx.due_date).days)
            total_fine = days * fine_per_day

            # Find all overdue fines for this transaction
            all_overdue_fines = Fine.objects.filter(transaction=tx, reason__icontains='Overdue fine')
            
            # Sum up the amount of ALL overdue fines for this transaction
            from decimal import Decimal
            total_billed_so_far = sum(fine.amount for fine in all_overdue_fines)
            
            remaining_to_bill = Decimal(str(total_fine)) - total_billed_so_far
            
            if remaining_to_bill > 0:
                # Find an unpaid overdue fine for this transaction
                unpaid_fine = all_overdue_fines.filter(paid=False).first()
                if unpaid_fine:
                    unpaid_fine.amount += remaining_to_bill
                    unpaid_fine.reason = f"Overdue fine for '{tx.copy.book.title}' (Unpaid portion up to {days} days)"
                    unpaid_fine.save(update_fields=['amount', 'reason'])
                    remaining = float(unpaid_fine.remaining_balance)
                else:
                    # They paid the previous fine completely, but kept the book!
                    # Create a new fine for the NEW remaining amount
                    new_fine = Fine.objects.create(
                        user=tx.user,
                        transaction=tx,
                        amount=remaining_to_bill,
                        reason=f"Overdue fine for '{tx.copy.book.title}' (Additional overdue days)",
                        paid=False,
                    )
                    remaining = float(new_fine.remaining_balance)
            else:
                # If they don't owe anything new today, get the remaining balance from the most recent fine
                last_fine = all_overdue_fines.order_by('-created_at').first()
                remaining = float(last_fine.remaining_balance) if last_fine else 0

            msg = (
                f"MSICT OLMS: DAILY REMINDER - '{tx.copy.book.title}' is {days} day(s) overdue. "
                f"Total fine: TZS {total_fine:,.0f} | Remaining: TZS {remaining:,.0f}. "
                f"Return the book to the library or pay fines at the circulation desk."
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
        ).exclude(
            transaction__copy__copy_type='softcopy'
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
            total_billed_so_far = sum(fine.amount for fine in overdue_fine_qs)
            remaining_to_bill = Decimal(str(total_overdue)) - total_billed_so_far

            overdue_remaining = Decimal('0')
            if remaining_to_bill > 0:
                unpaid_fine = overdue_fine_qs.filter(paid=False).first()
                if unpaid_fine:
                    unpaid_fine.amount += remaining_to_bill
                    unpaid_fine.reason = f"Overdue fine for '{book_title}' (Unpaid portion up to {days} days)"
                    unpaid_fine.save(update_fields=['amount', 'reason'])
                    overdue_remaining = unpaid_fine.remaining_balance
                else:
                    new_fine = Fine.objects.create(
                        user=tx.user,
                        transaction=tx,
                        amount=remaining_to_bill,
                        reason=f"Overdue fine for '{book_title}' (Additional overdue days)",
                        paid=False,
                    )
                    overdue_remaining = new_fine.remaining_balance
            else:
                last_fine = overdue_fine_qs.order_by('-created_at').first()
                overdue_remaining = last_fine.remaining_balance if last_fine else Decimal('0')

            # Compute remaining balances for both fines.
            loss_remaining = loss_fine.remaining_balance if loss_fine else Decimal('0')

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
        ).exclude(
            transaction__copy__copy_type='softcopy'
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

        # ── Step 5: Auto-expire SoftcopyAccessLog entries ─────────────────
        # Deactivate all access logs past their expires_at timestamp.
        expired_logs = SoftcopyAccessLog.objects.filter(
            is_active=True,
            expires_at__lt=now,
        )
        expired_count = expired_logs.count()
        if expired_count:
            expired_logs.update(is_active=False)
            self.stdout.write(
                self.style.WARNING(
                    f'Deactivated {expired_count} expired softcopy access log(s)'
                )
            )

        # Send 2-day expiry warning for active logs expiring within 2 days
        from datetime import timedelta
        warning_cutoff = now + timedelta(days=2)
        expiring_soon = SoftcopyAccessLog.objects.filter(
            is_active=True,
            expires_at__lte=warning_cutoff,
            expires_at__gt=now,
        ).select_related('user', 'copy__book', 'transaction')

        expiry_warned = 0
        for log in expiring_soon:
            days_left = log.days_until_expiry()
            book_title = log.copy.book.title if log.copy.book else 'Unknown'
            msg = (
                f"MSICT OLMS: Your softcopy access for '{book_title}' expires in "
                f"{days_left} day(s). Renew now to keep your access."
            )
            notify_user(
                log.user, msg, 'sms',
                priority='normal', message_type='softcopy_expiry'
            )
            notify_user(
                log.user, msg, 'email',
                subject=f'Softcopy Expiry Warning — {book_title}',
                priority='normal', message_type='softcopy_expiry'
            )
            expiry_warned += 1

        # ── Step 6: Auto-expire reservations and process 24h timeouts ───────
        from circulation.models import Book, Reservation
        from circulation.views import _process_reservation_expiry
        
        # Get distinct book IDs from Reservation to avoid ORA-22848 on Book's LOB fields
        active_book_ids = Reservation.objects.filter(
            status__in=['pending', 'notified']
        ).values_list('book_id', flat=True).distinct()
        
        books_with_active_res = Book.objects.filter(id__in=list(active_book_ids))
        
        books_processed = 0
        for book in books_with_active_res:
            try:
                _process_reservation_expiry(book)
                books_processed += 1
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Failed to process reservations for '{book.title}': {e}"))

        self.stdout.write(self.style.SUCCESS(
            f'[mark_overdue] Newly marked: {newly_marked} | '
            f'Overdue reminders: {daily_reminded} | '
            f'Lost+overdue reminders: {lost_reminded} | '
            f'Loss-only reminders: {loss_only_reminded} | '
            f'Softcopy logs expired: {expired_count} | '
            f'Softcopy expiry warnings: {expiry_warned} | '
            f'Reservation books processed: {books_processed}'
        ))
