from django.core.management.base import BaseCommand
from accounts.models import OLMSUser
from accounts.utils import send_sms, send_email_notification


class Command(BaseCommand):
    help = 'Test email and SMS notifications for a specific user'

    def add_arguments(self, parser):
        parser.add_argument('username', type=str, help='Username of the user to test notifications')

    def handle(self, *args, **options):
        username = options['username']
        
        try:
            user = OLMSUser.objects.get(username=username)
        except OLMSUser.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'User "{username}" not found'))
            return
        
        self.stdout.write(self.style.NOTICE(f'Testing notifications for: {user.get_full_name()}'))
        self.stdout.write(f'  Email: {user.email}')
        self.stdout.write(f'  Phone: {user.phone}')
        
        # Test Email
        self.stdout.write('\n' + '='*50)
        self.stdout.write('Testing EMAIL...')
        email_subject = 'MSICT OLMS - Test Notification'
        email_body = f'''Dear {user.get_full_name()},

This is a test notification from MSICT Library System.

If you received this email, your email notifications are working correctly.

Best regards,
MSICT Library Team'''
        
        email_result = send_email_notification(user.email, email_subject, email_body)
        if email_result:
            self.stdout.write(self.style.SUCCESS('  ✓ Email sent successfully'))
        else:
            self.stdout.write(self.style.ERROR('  ✗ Email failed to send'))
        
        # Test SMS
        self.stdout.write('\n' + '='*50)
        self.stdout.write('Testing SMS...')
        sms_message = f'MSICT OLMS: Test SMS notification for {user.get_full_name()}. If you received this, SMS notifications are working!'
        
        sms_result = send_sms(user.phone, sms_message)
        if sms_result:
            self.stdout.write(self.style.SUCCESS('  ✓ SMS sent successfully'))
        else:
            self.stdout.write(self.style.ERROR('  ✗ SMS failed to send'))
        
        self.stdout.write('\n' + '='*50)
        self.stdout.write('Test complete!')
        
        if email_result and sms_result:
            self.stdout.write(self.style.SUCCESS('All notifications working correctly!'))
        elif email_result:
            self.stdout.write(self.style.WARNING('Email working, SMS failed'))
        elif sms_result:
            self.stdout.write(self.style.WARNING('SMS working, Email failed'))
        else:
            self.stdout.write(self.style.ERROR('Both email and SMS failed!'))
