from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0025_simplify_guest_session'),
        ('catalog', '0018_remove_bookcopy_prepaid_fee_access_type'),
        ('circulation', '0021_add_payment_detail_fields'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='softcopyaccesslog',
            name='transaction',
        ),
        migrations.RemoveField(
            model_name='softcopyaccesslog',
            name='expires_at',
        ),
        migrations.AlterField(
            model_name='softcopyaccesslog',
            name='access_url',
            field=models.URLField(blank=True),
        ),
        migrations.AlterField(
            model_name='revenuetransaction',
            name='account_type',
            field=models.CharField(
                max_length=20,
                choices=[
                    ('overdue', 'Overdue Fee'),
                    ('loss', 'Loss Fine'),
                    ('damage', 'Damage Fine'),
                    ('link_fee', '[Legacy] Softcopy Link Fee'),
                    ('guest_fee', '[Legacy] Guest Session Fee'),
                ],
            ),
        ),
    ]
