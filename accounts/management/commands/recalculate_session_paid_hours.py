from django.core.management.base import BaseCommand
from accounts.models import GuestSession, SystemPreference
from decimal import Decimal


class Command(BaseCommand):
    help = 'Recalculate total_guest_hours for all guest users based on their session paid_hours'

    def handle(self, *args, **options):
        self.stdout.write('Recalculating total_guest_hours for all guest users...')
        
        from accounts.models import OLMSUser
        
        guest_users = OLMSUser.objects.filter(is_guest=True)
        
        user_updated_count = 0
        for user in guest_users:
            # Calculate total paid hours manually to avoid Oracle NCLOB aggregation issue
            sessions = GuestSession.objects.filter(user=user)
            total_hours = Decimal('0')
            for s in sessions:
                total_hours += s.paid_hours
            
            if total_hours and user.total_guest_hours != total_hours:
                user.total_guest_hours = total_hours
                user.save(update_fields=['total_guest_hours'])
                user_updated_count += 1
                self.stdout.write(
                    f'Updated {user.username}: {user.total_guest_hours}h -> {total_hours}h'
                )
        
        self.stdout.write(
            self.style.SUCCESS(
                f'Successfully recalculated total_guest_hours. Updated {user_updated_count} users.'
            )
        )
