from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0018_mastersetting_delivery_charge_default_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='barcode',
            field=models.CharField(
                blank=True, null=True, unique=True,
                max_length=50, help_text='Leave blank to auto-generate'
            ),
        ),
    ]
