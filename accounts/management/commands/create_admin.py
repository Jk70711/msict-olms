from django.core.management.base import BaseCommand
from accounts.models import OLMSUser


class Command(BaseCommand):
    help = 'Create the default OLMS superuser/admin account.'

    def handle(self, *args, **options):
        if OLMSUser.objects.filter(username='admin').exists():
            self.stdout.write(self.style.WARNING('[create_admin] Admin user already exists. Skipping.'))
            return

        user = OLMSUser.objects.create_superuser(
            username='admin',
            email='admin@msict.mil.tz',
            password='Admin@MSICT2024',
            first_name='System',
            surname='Administrator',
            army_no='MT 000001',
            role='admin',
            phone='255000000000',
        )
        user.is_staff = True
        user.is_superuser = True
        user.save()
        self.stdout.write(self.style.SUCCESS(
            '[create_admin] Admin user created: username=admin, password=Admin@MSICT2024\n'
            '              IMPORTANT: Change this password immediately after first login!'
        ))
