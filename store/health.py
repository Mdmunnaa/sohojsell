"""
সার্ভারের সেটিংসে গোলমাল থাকলে মাস্টারকে বলা (Render-এর env var ভুল হলে ছবি আপলোড চুপচাপ ভেঙে থাকে)।
- Django system check: deploy-এর log-এ (migrate/collectstatic চালানোর সময়) WARNING দেখায়
- warnings(): মাস্টার ড্যাশবোর্ডে লাল বার্তা
"""
import re

from django.conf import settings
from django.core.checks import Warning, register

BUCKET_RE = re.compile(r'^[a-zA-Z0-9.\-_]{1,255}$')
ACCOUNT_RE = re.compile(r'^[0-9a-f]{32}$')


def warnings():
    found = []
    if getattr(settings, 'USE_R2', False):
        bucket = getattr(settings, 'R2_BUCKET_NAME', '')
        if not BUCKET_RE.match(bucket):
            found.append(f'Render-এর R2_BUCKET_NAME ভুল: "{bucket}" — এটা bucket-এর নাম না (নামে স্পেস/বড় হাতের অক্ষর চলে না)। '
                         'Cloudflare R2 → Buckets-এ যে নামটা আছে সেটা দিন। ঠিক না করা পর্যন্ত প্রোডাক্টের ছবি আপলোড আর ডেমো দোকান কাজ করবে না।')
        account = getattr(settings, 'R2_ACCOUNT_ID', '')
        if not ACCOUNT_RE.match(account):
            found.append(f'Render-এর R2_ACCOUNT_ID ভুল: "{account}" — Cloudflare R2-র ৩২ অক্ষরের Account ID দিন '
                         '(R2 পাতার ডান পাশে "Account ID"), পুরো লিংক না।')
        if not getattr(settings, 'R2_PUBLIC_DOMAIN', ''):
            found.append('R2_PUBLIC_DOMAIN দেওয়া নেই — ছবির লিংক সাময়িক (signed) হবে, Facebook-এ শেয়ার করলে ছবি দেখাবে না।')
    elif getattr(settings, 'IS_PRODUCTION', False):
        found.append('R2 সেট করা নেই — ছবি সার্ভারের ডিস্কে যাচ্ছে, প্রতি deploy-এ মুছে যাবে।')
    return found


@register()
def storage_check(app_configs, **kwargs):
    return [Warning(text, id=f'store.W{n:03d}') for n, text in enumerate(warnings(), start=1)]
