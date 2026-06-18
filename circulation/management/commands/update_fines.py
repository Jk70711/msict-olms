"""
Management command: update_fines
Continuously calculate and update fines for all users with overdue books.
This ensures Fine records are created/updated for all overdue transactions.

Run daily via cron (recommended: 02:00 AM):
    0 2 * * * /path/venv/bin/python /path/manage.py update_fines >> /var/log/olms_fines.log 2>&1
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from decimal import Decimal
from circulation.models import BorrowingTransaction, Fine
from accounts.models import SystemPreference


class Command(BaseCommand):
    help = 'Continuously calculate and update fines for all users with overdue books'

    def handle(self, *args, **options):
        now = timezone.now()
        updated = 0
        created = 0
        skipped = 0

        # Get all overdue transactions (borrowed or overdue status)
        overdue_qs = BorrowingTransaction.objects.filter(
            status__in=['borrowed', 'overdue'],
            due_date__lt=now,
        ).select_related('user', 'copy__book')

        for tx in overdue_qs:
            days_overdue = tx.days_overdue()
            if days_overdue <= 0:
                skipped += 1
                continue

            fine_per_day = float(SystemPreference.get('FINE_PER_DAY', 1000))
            calculated_amount = days_overdue * fine_per_day

            # Check if Fine record exists for this transaction
            existing_fine = Fine.objects.filter(transaction=tx).first()

            if existing_fine:
                # Update existing fine record - preserve amount_paid
                if existing_fine.amount != calculated_amount:
                    old_amount = existing_fine.amount
                    existing_fine.amount = calculated_amount
                    existing_fine.reason = f"Overdue fine for '{tx.copy.book.title}' ({days_overdue} days)"
                    # Keep amount_paid as is - don't reset it
                    existing_fine.save(update_fields=['amount', 'reason'])
                    updated += 1
                    self.stdout.write(f'Updated fine for {tx.user.username}: {old_amount} -> {calculated_amount} (Paid: {existing_fine.amount_paid}, Remaining: {existing_fine.remaining_balance})')
                else:
                    skipped += 1
            else:
                # Create new fine record
                Fine.objects.create(
                    user=tx.user,
                    transaction=tx,
                    amount=calculated_amount,
                    reason=f"Overdue fine for '{tx.copy.book.title}' ({days_overdue} days)",
                    paid=False,
                )
                created += 1
                self.stdout.write(f'Created fine for {tx.user.username}: {calculated_amount}')

        self.stdout.write(self.style.SUCCESS(
            f'[update_fines] Created: {created} | Updated: {updated} | Skipped: {skipped} | Total overdue: {len(overdue_qs)}'
        ))
