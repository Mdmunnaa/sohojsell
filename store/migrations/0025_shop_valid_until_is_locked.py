from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0024_pageview'),
    ]

    operations = [
        migrations.AddField(
            model_name='shop',
            name='valid_until',
            field=models.DateField(
                null=True, blank=True,
                help_text='Plan valid until this date'
            ),
        ),
        migrations.AddField(
            model_name='shop',
            name='is_locked',
            field=models.BooleanField(
                default=False,
                help_text='Account locked due to expired subscription'
            ),
        ),
    ]
