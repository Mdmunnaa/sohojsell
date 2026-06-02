from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0016_storefrontorder'),
    ]

    operations = [
        migrations.AddField(
            model_name='shop',
            name='custom_domain',
            field=models.CharField(
                blank=True, null=True, unique=True, max_length=255,
                help_text='e.g. www.myanshop.com'
            ),
        ),
    ]
