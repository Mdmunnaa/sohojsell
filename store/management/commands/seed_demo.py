"""
লাইভ ডেমো দোকান বানানো / আগের মতো করা:
    python manage.py seed_demo
build.sh প্রতি deploy-এ চালায়; কেউ /demo/ খুললে ২৪ ঘণ্টার পুরনো হলে নিজে থেকেও হয়।
Render Cron Job-এ রাতে চালাতে চাইলে: python manage.py seed_demo
"""
import time

from django.core.management.base import BaseCommand

from store import demo


class Command(BaseCommand):
    help = 'লাইভ ডেমো দোকান ("ফ্যাশন পয়েন্ট") বানায় বা আবার আগের মতো সাজায়'

    def handle(self, *args, **options):
        started = time.monotonic()
        shop = demo.build()
        self.stdout.write(self.style.SUCCESS(
            f'ডেমো দোকান "{shop.name}" (/{shop.slug}/) তৈরি: {shop.products.count()} products, '
            f'{shop.orders.count()} orders, {shop.customers.count()} customers — {time.monotonic() - started:.1f}s'))
