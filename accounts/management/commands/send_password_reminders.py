from django.core.management.base import BaseCommand
from django.utils import timezone
from django.conf import settings
from accounts.models import OLMSUser
from accounts.utils import notify_user


class Command(BaseCommand):
    help = 'Send password change reminders to users whose password is 30+ days old'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show who would be notified without actually sending messages',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        days = getattr(settings, 'PASSWORD_CHANGE_REMINDER_DAYS', 30)
        cutoff = timezone.now() - timezone.timedelta(days=days)

        users = OLMSUser.objects.filter(
            is_active=True,
            last_password_change__lte=cutoff,
        ).exclude(last_password_change=None)

        self.stdout.write(self.style.NOTICE(
            f"Found {users.count()} user(s) with password older than {days} days."
        ))

        sent_sms = sent_email = 0

        for user in users:
            delta = timezone.now() - user.last_password_change
            days_old = delta.days

            sms_body = (
                f"MSICT OLMS Security Reminder:\n"
                f"Dear {user.get_full_name()}, your password is {days_old} day(s) old.\n"
                f"Please change it immediately for security.\n"
                f"Steps: Login → Dashboard → Change Password."
            )
            email_body = (
                f"Dear {user.get_full_name()},\n\n"
                f"This is a security reminder from MSICT Library System (OLMS).\n\n"
                f"Your account password was last changed {days_old} day(s) ago. "
                f"For security purposes, we strongly recommend changing your password immediately.\n\n"
                f"Steps to change your password:\n"
                f"  1. Login to OLMS\n"
                f"  2. Go to Dashboard\n"
                f"  3. Click 'Change Password'\n\n"
                f"If you recently changed your password, please disregard this message.\n\n"
                f"Regards,\nMSICT Library Administration"
            )

            if dry_run:
                self.stdout.write(f"  [DRY RUN] Would notify: {user.username} ({user.email} / {user.phone}) — {days_old} days old")
                continue

            sms_notif = notify_user(user, sms_body, 'sms')
            email_notif = notify_user(user, email_body, 'email', subject='MSICT OLMS — Password Change Reminder')

            status = []
            if sms_notif.status == 'sent':
                sent_sms += 1
                status.append('SMS ok')
            else:
                status.append('SMS FAILED')
            if email_notif.status == 'sent':
                sent_email += 1
                status.append('email ok')
            else:
                status.append('email FAILED')

            self.stdout.write(f"  Notified: {user.username} — {', '.join(status)}")

        if not dry_run:
            self.stdout.write(self.style.SUCCESS(
                f"Done. SMS sent: {sent_sms}, Email sent: {sent_email} out of {users.count()} users."
            ))
