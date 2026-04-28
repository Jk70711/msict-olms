"""
Management command: resequence_accessions
Re-assigns all hardcopy accession numbers sequentially as MSICT/000001, 000002, ...
ordered by the existing number (preserving relative order where possible).

Usage:
    python manage.py resequence_accessions          # dry-run (preview only)
    python manage.py resequence_accessions --apply  # actually update the DB
"""

from django.core.management.base import BaseCommand
from catalog.models import BookCopy


def _parse_num(acc):
    """Extract integer from MSICT/XXXXXX or ACC-XXXXXX; return float('inf') for unknowns."""
    try:
        if acc and acc.startswith('MSICT/'):
            return int(acc[6:])
        if acc and acc.startswith('ACC-'):
            return int(acc[4:])
    except ValueError:
        pass
    return float('inf')


class Command(BaseCommand):
    help = 'Resequence hardcopy accession numbers to MSICT/000001, 000002, ...'

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply',
            action='store_true',
            help='Actually apply changes (default is dry-run/preview only)',
        )

    def handle(self, *args, **options):
        apply = options['apply']

        copies = list(
            BookCopy.objects.all().order_by('created_at', 'pk')
        )

        copies.sort(key=lambda c: (_parse_num(c.accession_no), c.pk))

        changes = []
        counter = 1
        for copy in copies:
            new_acc = f"MSICT/{counter:06d}"
            if copy.accession_no != new_acc:
                changes.append((copy, copy.accession_no, new_acc))
            counter += 1

        if not changes:
            self.stdout.write(self.style.SUCCESS('All accession numbers already sequential. Nothing to do.'))
            return

        self.stdout.write(f'{"DRY RUN – " if not apply else ""}Found {len(changes)} copies to update:\n')
        for copy, old, new in changes[:20]:
            self.stdout.write(f'  [{copy.pk}] "{copy.book.title[:40]}"  {old}  →  {new}')
        if len(changes) > 20:
            self.stdout.write(f'  ... and {len(changes) - 20} more')

        if not apply:
            self.stdout.write(self.style.WARNING(
                '\nDry run complete. Run with --apply to commit changes.'
            ))
            return

        # Apply: use a temp prefix to avoid unique constraint collisions mid-update
        self.stdout.write('\nApplying...')
        for copy, old, new in changes:
            BookCopy.objects.filter(pk=copy.pk).update(
                accession_no='_TMP_' + new,
                barcode='_TMP_' + new,
            )
        for copy, old, new in changes:
            BookCopy.objects.filter(pk=copy.pk).update(
                accession_no=new,
                barcode=new,
            )

        self.stdout.write(self.style.SUCCESS(
            f'\nDone. {len(changes)} copies resequenced to MSICT/000001 … MSICT/{len(copies):06d}'
        ))
