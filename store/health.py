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
NEON_REGION_RE = re.compile(r'\.([a-z]{2}-[a-z]+-\d)\.aws\.neon\.tech$')
SERVER_REGION = 'ap-southeast-1'      # সার্ভার (Render Singapore / Cloudflare APAC) — ডাটাবেসও এখানে থাকা দরকার


def database_region():
    """Neon-এর হোস্টের নাম থেকে অঞ্চল (যেমন ap-southeast-1); Neon না হলে ''।"""
    host = (settings.DATABASES.get('default', {}).get('HOST') or '').lower()
    match = NEON_REGION_RE.search(host)
    return match.group(1) if match else ''


def database_latency_ms(tries=3):
    """ডাটাবেস এক প্রশ্নে কত সময় নেয় (ms, সবচেয়ে কম) — পাতা ধীর হলে আগে এটা দেখুন।"""
    import time
    from django.db import connection
    best = None
    try:
        with connection.cursor() as cursor:
            for _ in range(tries):
                started = time.perf_counter()
                cursor.execute('SELECT 1')
                cursor.fetchone()
                spent = (time.perf_counter() - started) * 1000
                best = spent if best is None else min(best, spent)
    except Exception:    # noqa: BLE001 — মাপা না গেলে চুপচাপ বাদ
        return None
    return round(best, 1)


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
    region = database_region()
    if region and region != SERVER_REGION:
        found.append(f'Neon ডাটাবেস {region} অঞ্চলে, কিন্তু সার্ভার সিঙ্গাপুরে ({SERVER_REGION}) — প্রতিটা প্রশ্ন সমুদ্র পেরিয়ে যায়, '
                     'তাই সব পাতা অনেক ধীর। Neon-এ সিঙ্গাপুরে (AWS ap-southeast-1) নতুন প্রজেক্ট বানিয়ে ডাটা সরান।')
    return found


@register()
def storage_check(app_configs, **kwargs):
    return [Warning(text, id=f'store.W{n:03d}') for n, text in enumerate(warnings(), start=1)]
