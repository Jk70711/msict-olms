"""
Management command: update_card_numbers
=======================================
Re-numbers ALL existing virtual cards to the new format:
    MSICT-LIB-{YY}-{NNNNNN}
    e.g.  MSICT-LIB-26-000001

Cards are ordered by their original creation date (oldest → lowest number)
so the natural seniority is preserved.  QR codes are regenerated to embed
the new card number.

Usage (once Oracle DB is running):
    python manage.py update_card_numbers
    python manage.py update_card_numbers --dry-run      # preview only
"""

import io
import base64

from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = 'Renumber all virtual cards to MSICT-LIB-YY-NNNNNN and regenerate QR codes.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Preview changes without writing to the database.',
        )

    def handle(self, *args, **options):
        import qrcode
        from accounts.models import VirtualCard

        dry = options['dry_run']
        yy = timezone.now().strftime('%y')          # '26' for 2026

        cards = VirtualCard.objects.select_related('user').order_by('generated_at', 'pk')
        total = cards.count()

        if not total:
            self.stdout.write(self.style.WARNING('No virtual cards found — nothing to do.'))
            return

        mode = '[DRY-RUN] ' if dry else ''
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f'{mode}Updating {total} card(s) → MSICT-LIB-{yy}-NNNNNN format...'
            )
        )

        for seq, card in enumerate(cards, start=1):
            old_no = card.card_no or 'N/A'
            new_no = f'MSICT-LIB-{yy}-{seq:06d}'
            user = card.user

            # Regenerate QR code embedding the new card number
            qr_data = (
                f"MSICT-OLMS|{user.army_no}|{user.get_full_name()}|{user.role}|{new_no}"
            )
            qr = qrcode.QRCode(version=1, box_size=6, border=2)
            qr.add_data(qr_data)
            qr.make(fit=True)
            img = qr.make_image(fill_color='black', back_color='white')
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            qr_base64 = base64.b64encode(buf.getvalue()).decode('utf-8')

            self.stdout.write(
                f'  [{seq:>4}/{total}]  {user.username:<20}  {old_no:<25} → {new_no}'
            )

            if not dry:
                card.card_no = new_no
                card.qr_code = qr_base64
                card.save(update_fields=['card_no', 'qr_code'])

        if dry:
            self.stdout.write(self.style.WARNING('\nDry-run complete — no changes were saved.'))
        else:
            self.stdout.write(
                self.style.SUCCESS(f'\nDone! {total} card(s) renumbered and QR codes regenerated.')
            )
