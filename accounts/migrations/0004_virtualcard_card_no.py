from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0003_user_theme_field'),
    ]

    operations = [
        migrations.AddField(
            model_name='virtualcard',
            name='card_no',
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text='Auto-generated card number e.g. MSICT-CARD-000001',
                max_length=20,
                null=True,
                unique=True,
            ),
        ),
    ]
