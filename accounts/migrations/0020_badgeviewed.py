from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0019_bulk_messaging_models'),
    ]

    operations = [
        migrations.CreateModel(
            name='BadgeViewed',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('badge_key', models.CharField(max_length=50)),
                ('last_viewed_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('user', models.ForeignKey(on_delete=models.deletion.CASCADE, related_name='badge_views', to='accounts.olmsuser')),
            ],
            options={
                'db_table': 'badge_views',
                'unique_together': {('user', 'badge_key')},
            },
        ),
    ]
