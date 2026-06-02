from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0015_mastersetting'),
    ]

    operations = [
        migrations.CreateModel(
            name='StorefrontOrder',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('customer_name', models.CharField(max_length=150)),
                ('customer_phone', models.CharField(max_length=15)),
                ('customer_address', models.TextField()),
                ('customer_note', models.TextField(blank=True, null=True)),
                ('total_amount', models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ('delivery_charge', models.DecimalField(decimal_places=2, default=80, max_digits=10)),
                ('status', models.CharField(
                    choices=[('Pending', 'Pending'), ('Confirmed', 'Confirmed'), ('Shipped', 'Shipped'), ('Delivered', 'Delivered'), ('Cancelled', 'Cancelled')],
                    default='Pending', max_length=20
                )),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('shop', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='storefront_orders', to='store.shop')),
            ],
        ),
        migrations.CreateModel(
            name='StorefrontOrderItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('quantity', models.PositiveIntegerField(default=1)),
                ('price', models.DecimalField(decimal_places=2, max_digits=10)),
                ('order', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='items', to='store.storefrontorder')),
                ('product', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='store.product')),
            ],
        ),
    ]
