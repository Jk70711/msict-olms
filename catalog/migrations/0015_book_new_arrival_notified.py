from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0014_add_font_size_to_logincontent'),
    ]

    operations = [
        migrations.AddField(
            model_name='book',
            name='new_arrival_notified',
            field=models.BooleanField(default=False, help_text='True if a new-arrival broadcast was sent for this book'),
        ),
    ]
