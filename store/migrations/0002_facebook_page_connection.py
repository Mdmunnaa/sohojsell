from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='FacebookPageConnection',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('page_id', models.CharField(max_length=50, verbose_name='Facebook Page ID')),
                ('page_name', models.CharField(max_length=200, verbose_name='Page Name')),
                ('page_access_token', models.TextField(verbose_name='Page Access Token')),
                ('page_picture', models.URLField(blank=True, null=True, verbose_name='Page Profile Picture')),
                ('fan_count', models.PositiveIntegerField(default=0, verbose_name='Page Followers')),
                ('category', models.CharField(blank=True, max_length=100, null=True)),
                ('user_access_token', models.TextField(blank=True, null=True)),
                ('is_active', models.BooleanField(default=True)),
                ('connected_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('shop', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='fb_page',
                    to='store.shop',
                )),
            ],
            options={
                'verbose_name': 'Facebook Page Connection',
                'verbose_name_plural': 'Facebook Page Connections',
            },
        ),
    ]
