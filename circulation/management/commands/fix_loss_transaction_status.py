"""
Management command: fix_loss_transaction_status
Updates transactions for confirmed loss reports from 'overdue' or 'borrowed' to 'lost' status.
This is a one-time fix for existing loss reports that were confirmed before the
'lost' status was introduced.

Run once:
    python manage.py fix_loss_transaction_status
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from circulation.models import LossReport, BorrowingTransaction


class Command(BaseCommand):
    help = 'Update transaction status to lost for confirmed loss reports'

    def handle(self, *args, **options):
        updated_count = 0
        
        # Find all loss reports (pending, confirmed, resolved) where transaction status is 'overdue' or 'borrowed'
        loss_reports = LossReport.objects.filter(
            status__in=['pending', 'confirmed', 'resolved'],
            transaction__status__in=['overdue', 'borrowed']
        ).select_related('transaction')
        
        for lr in loss_reports:
            tx = lr.transaction
            old_status = tx.status
            tx.status = 'lost'
            tx.save(update_fields=['status'])
            updated_count += 1
            self.stdout.write(
                self.style.SUCCESS(
                    f'Updated transaction {tx.pk} for loss report LR-{lr.pk} (status: {lr.status}) from {old_status} to lost'
                )
            )
        
        if updated_count == 0:
            self.stdout.write(self.style.WARNING('No transactions needed updating.'))
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f'Updated {updated_count} transaction(s) to lost.'
                )
            )
