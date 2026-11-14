"""
ব্যাকআপ থেকে ফেরত আনা ডাটাবেস SellPunch-এর নিজের কোড দিয়ে পড়ে দেখা — scripts/backup_restore_check.py চালায়
(DATABASE_URL = অস্থায়ী ডাটাবেস, কখনো লাইভ নয়)। প্রতিটা জরুরি মডেলের সব ঘরসহ কয়েকশো সারি পড়ে;
শেষ লাইনে {মডেল: মোট সারি} JSON। কোনো সারি পড়া না গেলে (তারিখ/টাকা/JSON ভাঙা) exit 1।
"""
import json

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError

MODELS = ('store.Shop', 'accounts.User', 'store.Product', 'store.ProductVariant', 'store.Category', 'store.Customer',
          'store.Order', 'store.OrderItem', 'store.SalePayment', 'store.OnlinePayment', 'store.Expense', 'store.Purchase')
SAMPLE = 300


class Command(BaseCommand):
    help = 'ফেরত আনা ডাটাবেসের জরুরি মডেলগুলো পড়ে দেখা (ব্যাকআপ পরীক্ষার জন্য)'

    def handle(self, *args, **options):
        counts = {}
        for label in MODELS:
            model = apps.get_model(label)
            fields = [f.attname for f in model._meta.concrete_fields]
            try:
                counts[label] = model._default_manager.count()
                for row in model._default_manager.order_by('-pk').values_list(*fields)[:SAMPLE]:
                    len(row)
            except Exception as exc:
                raise CommandError(f'{label} পড়া যায়নি: {exc.__class__.__name__}: {exc}') from exc
        self.stdout.write(json.dumps(counts, ensure_ascii=False))
