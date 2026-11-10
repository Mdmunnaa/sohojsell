"""
বাকির তাগাদা নিজে থেকে পাঠানো (দিনে একবার চালান — Render Cron Job বা Cloudflare Cron):
    python manage.py due_reminders
যেসব দোকানে "নিজে থেকে তাগাদা" চালু আছে, সেখানে বাকি থাকা কাস্টমারদের নির্ধারিত দিন পর পর SMS যায়।
"""
from django.core.management.base import BaseCommand

from store import dues


class Command(BaseCommand):
    help = 'বাকি থাকা কাস্টমারদের নিজে থেকে তাগাদা SMS (যেসব দোকানে চালু)'

    def handle(self, *args, **options):
        sent = dues.run_auto_reminders()
        total = sum(sent.values())
        self.stdout.write(f'{len(sent)} shop(s), {total} reminder SMS sent')
