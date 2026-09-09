from django.utils import timezone
from datetime import timedelta
from circulation.models import Reservation
from circulation.views import _recalculate_reservation_expiries, _notify_next_reservation

# Find reservations that were created in the last 24 hours but are expired
recent = timezone.now() - timedelta(hours=24)
wrongly_expired = Reservation.objects.filter(status='expired', created_at__gte=recent)

print(f"Found {wrongly_expired.count()} wrongly expired reservations.")

for res in wrongly_expired:
    res.status = 'pending'
    res.save(update_fields=['status'])
    _recalculate_reservation_expiries(res.book)
    # Also notify next in queue if appropriate just in case they were the one
    _notify_next_reservation(res.book)

print("Restored wrongly expired reservations.")
