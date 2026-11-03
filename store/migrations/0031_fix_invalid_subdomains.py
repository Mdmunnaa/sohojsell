import re
import secrets

from django.db import migrations
from django.utils.text import slugify

# সাবডোমেইন হিসেবে চলে এমন (DNS-এর নিয়ম): ছোট হাতের অক্ষর/সংখ্যা/হাইফেন, শুরু-শেষে হাইফেন নয়, ৬৩ অক্ষর পর্যন্ত।
USABLE = re.compile(r'^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$')
NEW_RULE = re.compile(r'^[a-z0-9](?:[a-z0-9-]{1,28})[a-z0-9]$')


def fix_invalid_subdomains(apps, schema_editor):
    """
    আগে দোকানের নাম থেকে slug বানানো হতো — বাংলা নামে খালি ('') বা '-1' হয়ে যেত, যা সাবডোমেইন
    হিসেবে চলে না আর দোকানের লিংকও ভাঙা ছিল। শুধু এমন ভাঙা slug ঠিক করা হচ্ছে; যেগুলো এখন চলছে
    সেগুলো বদলানো হচ্ছে না, যাতে কারো শেয়ার করা লিংক না ভাঙে।
    """
    Shop = apps.get_model('store', 'Shop')
    taken = set(Shop.objects.exclude(slug__isnull=True).values_list('slug', flat=True))
    for shop in Shop.objects.all().order_by('id'):
        if shop.slug and USABLE.match(shop.slug):
            continue
        base = slugify(shop.name or '').replace('-', '')[:30]
        candidate = base if NEW_RULE.match(base) else ''
        n = 2
        while candidate and candidate in taken:
            candidate = f'{base[:27]}{n}'
            n += 1
            if n > 99:
                candidate = ''
        while not candidate or candidate in taken:
            candidate = f'shop{secrets.randbelow(900000) + 100000}'
        taken.discard(shop.slug)
        taken.add(candidate)
        shop.slug = candidate
        shop.save(update_fields=['slug'])


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0030_onlinepayment'),
    ]

    operations = [
        migrations.RunPython(fix_invalid_subdomains, migrations.RunPython.noop),
    ]
