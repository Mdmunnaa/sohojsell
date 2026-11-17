from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("store", "0061_merge_duplicate_customers"),
    ]

    operations = [
        migrations.AlterField(
            model_name="productvariant",
            name="barcode",
            field=models.CharField(blank=True, db_index=True, max_length=50),
        ),
        migrations.AddIndex(
            model_name="pageview",
            index=models.Index(
                fields=["shop", "created_at"], name="pageview_shop_time"
            ),
        ),
        migrations.AddConstraint(
            model_name="customer",
            constraint=models.UniqueConstraint(
                fields=("shop", "phone"), name="unique_customer_phone_per_shop"
            ),
        ),
    ]
