from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0024_seed_terms_sections'),
    ]

    operations = [
        # OLMSUser: remove total_guest_hours and total_guest_paid, add total_guest_visits
        migrations.RemoveField(
            model_name='olmsuser',
            name='total_guest_hours',
        ),
        migrations.RemoveField(
            model_name='olmsuser',
            name='total_guest_paid',
        ),
        migrations.AddField(
            model_name='olmsuser',
            name='total_guest_visits',
            field=models.IntegerField(default=0, help_text='Total number of library visits by this guest'),
        ),

        # GuestSession: remove payment-related fields
        migrations.RemoveField(
            model_name='guestsession',
            name='paid_hours',
        ),
        migrations.RemoveField(
            model_name='guestsession',
            name='duration_hours',
        ),
        migrations.RemoveField(
            model_name='guestsession',
            name='amount_paid',
        ),
        migrations.RemoveField(
            model_name='guestsession',
            name='payment_status',
        ),
        migrations.RemoveField(
            model_name='guestsession',
            name='payment_method',
        ),
        migrations.RemoveField(
            model_name='guestsession',
            name='renewed',
        ),
        migrations.RemoveField(
            model_name='guestsession',
            name='expiry_notification_sent',
        ),

        # GuestSession: add duration_minutes
        migrations.AddField(
            model_name='guestsession',
            name='duration_minutes',
            field=models.IntegerField(
                null=True, blank=True,
                help_text='Actual visit duration in minutes (set on sign-out)'
            ),
        ),

        # GuestSession: update status choices (remove 'renewed'/'expired', keep 'active'/'ended')
        migrations.AlterField(
            model_name='guestsession',
            name='status',
            field=models.CharField(
                max_length=10,
                choices=[('active', 'Active'), ('ended', 'Ended')],
                default='active',
            ),
        ),
    ]
