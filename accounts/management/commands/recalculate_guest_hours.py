from django.core.management.base import BaseCommand
from django.db.models import Sum
from accounts.models import OLMSUser, GuestSession
from decimal import Decimal


class Command(BaseCommand):
    help = 'Recalculate total_guest_hours for all guest users based on paid_hours from their sessions'

    def handle(self, *args, **options):
        self.stdout.write('Recalculating total_guest_hours for all guest users...')
        
        # Get all guest users
        guest_users = OLMSUser.objects.filter(is_guest=True)
        
        updated_count = 0
        for user in guest_users:
            # Calculate total paid hours from all sessions
            result = GuestSession.objects.filter(user=user).aggregate(
                total_paid_hours=Sum('paid_hours')
            )
            
            total_hours = result['total_paid_hours'] or Decimal('0')
            
            # Update the user's total_guest_hours
            if user.total_guest_hours != total_hours:
                user.total_guest_hours = total_hours
                user.save(update_fields=['total_guest_hours'])
                updated_count += 1
                self.stdout.write(
                    f'Updated {user.username}: {user.total_guest_hours} -> {total_hours} hours'
                )
        
        self.stdout.write(
            self.style.SUCCESS(
                f'Successfully recalculated total_guest_hours. Updated {updated_count} users.'
            )
        )
