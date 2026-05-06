from django.core.management.base import BaseCommand
from django.core.management import call_command


class Command(BaseCommand):
    help = 'Deprecated alias — delegates to circulation mark_overdue command.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING(
            '[overdue_check] Deprecated: delegating to mark_overdue command.'
        ))
        call_command('mark_overdue')
