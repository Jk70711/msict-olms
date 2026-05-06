from django.core.management.base import BaseCommand
from django.core.management import call_command


class Command(BaseCommand):
    help = 'Deprecated alias — delegates to circulation send_due_reminders command.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING(
            '[send_notifications] Deprecated: delegating to send_due_reminders command.'
        ))
        call_command('send_due_reminders')
