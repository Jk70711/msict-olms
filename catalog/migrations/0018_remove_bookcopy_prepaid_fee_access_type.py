from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0017_footer_bg_color'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='bookcopy',
            name='access_type',
        ),
        migrations.RemoveField(
            model_name='bookcopy',
            name='prepaid_fee',
        ),
    ]
