from django.core.management.base import BaseCommand
from circulation.models import Fine, RevenueTransaction, LossReport
from decimal import Decimal


class Command(BaseCommand):
    help = 'Backfill RevenueTransaction records for historically paid fines that were never recorded.'

    def handle(self, *args, **options):
        # Find all paid fines
        paid_fines = Fine.objects.filter(paid=True, amount_paid__gt=0)
        created = 0
        skipped = 0

        for fine in paid_fines:
            # Check if revenue already recorded for this fine
            existing = RevenueTransaction.objects.filter(
                reference_id=fine.pk,
                reference_table='fines'
            ).exists()

            if existing:
                skipped += 1
                continue

            is_loss_fine = LossReport.objects.filter(loss_fine=fine).exists()
            account_type = 'loss' if is_loss_fine else 'overdue'

            RevenueTransaction.objects.create(
                user=fine.user,
                account_type=account_type,
                amount=fine.amount_paid,
                description=f"Backfilled payment for fine #{fine.pk}",
                reference_id=fine.pk,
                reference_table='fines',
            )
            created += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'Backfill complete: {created} revenue records created, {skipped} already had records.'
            )
        )
