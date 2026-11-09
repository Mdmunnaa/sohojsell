# store/subdomains.py
"""
দোকানের সাবডোমেইন (munnafashion.sellpunch.com-এর "munnafashion" অংশ) — নিয়ম এক জায়গায়।
Edumi-র নিয়ম থেকে আনা: ৩-৩০ অক্ষর, ছোট হাতের ইংরেজি অক্ষর/সংখ্যা/হাইফেন, শুরু-শেষে হাইফেন নয়।
সাবডোমেইন ডেটাবেসে Shop.slug ফিল্ডে থাকে।
"""
import re
import secrets

from django.core.exceptions import ValidationError
from django.utils.text import slugify

SUBDOMAIN_RE = re.compile(r'^[a-z0-9](?:[a-z0-9-]{1,28})[a-z0-9]$')

# এই নামগুলো কোনো দোকান নিতে পারবে না — প্ল্যাটফর্মের নিজের কাজে লাগে বা বিভ্রান্তিকর
RESERVED_SUBDOMAINS = frozenset({
    'www', 'admin', 'administrator', 'root', 'demo', 'test', 'testing', 'staging', 'dev', 'api', 'app', 'apps',
    'mail', 'email', 'smtp', 'imap', 'pop', 'ftp', 'cdn', 'static', 'media', 'assets', 'files', 'img', 'images',
    'sohojsell', 'sellpunch', 'support', 'help', 'helpdesk', 'blog', 'docs', 'guide', 'status', 'billing', 'pay', 'payment',
    'master', 'hq', 'dashboard', 'login', 'signup', 'register', 'account', 'accounts', 'info', 'hello', 'refund',
    'partner', 'partners', 'affiliate', 'affiliates', 'news', 'shop', 'store', 'ns1', 'ns2', 'mx',
    'domains', 'domain', 'localhost', 'saas-master', 'webhook', 'webhooks', 'privacy', 'terms', 'contact',
})

BENGALI_DIGITS = str.maketrans('০১২৩৪৫৬৭৮৯', '0123456789')

RULES_MESSAGE = '৩-৩০ অক্ষর: শুধু ছোট হাতের ইংরেজি অক্ষর (a-z), সংখ্যা আর হাইফেন (-); শুরু ও শেষে হাইফেন নয়।'


def normalize(value):
    return (value or '').translate(BENGALI_DIGITS).strip().lower()


def is_valid_format(value):
    return bool(SUBDOMAIN_RE.match(value or '')) and value not in RESERVED_SUBDOMAINS


def _taken(value, exclude_shop_id=None):
    from .models import Shop
    qs = Shop.objects.filter(slug__iexact=value)
    if exclude_shop_id:
        qs = qs.exclude(pk=exclude_shop_id)
    return qs.exists()


def suggest_available(base, exclude_shop_id=None):
    base = (base or '')[:27].strip('-')
    if not base:
        return ''
    for n in range(2, 100):
        candidate = f'{base}{n}'
        if is_valid_format(candidate) and not _taken(candidate, exclude_shop_id):
            return candidate
    return ''


def validate_subdomain(value, exclude_shop_id=None):
    """ঠিক থাকলে পরিষ্কার করা মান ফেরত দেয়, নইলে বাংলায় কারণসহ ValidationError।"""
    value = normalize(value)
    if not SUBDOMAIN_RE.match(value):
        raise ValidationError(RULES_MESSAGE)
    if value in RESERVED_SUBDOMAINS:
        raise ValidationError('এই নামটা সংরক্ষিত, অন্য একটা নাম বেছে নিন।')
    if _taken(value, exclude_shop_id):
        suggestion = suggest_available(value, exclude_shop_id)
        raise ValidationError(f'"{value}" আগেই নেওয়া হয়েছে।' + (f' যেমন "{suggestion}" চেষ্টা করুন।' if suggestion else ''))
    return value


def suggest_from_name(name):
    """দোকানের ইংরেজি নাম থেকে প্রস্তাব (যেমন "Munna Fashion" → "munnafashion")। বাংলা নাম হলে খালি।"""
    base = slugify(name or '').replace('-', '')[:30]
    return base if SUBDOMAIN_RE.match(base) else ''


def generate_unique(name='', exclude_shop_id=None):
    """নাম থেকে বা এলোমেলোভাবে একটা বৈধ, খালি সাবডোমেইন — পুরনো/অ্যাডমিনে বানানো শপের জন্য।"""
    base = suggest_from_name(name)
    if base and base not in RESERVED_SUBDOMAINS and not _taken(base, exclude_shop_id):
        return base
    if base:
        suggestion = suggest_available(base, exclude_shop_id)
        if suggestion:
            return suggestion
    while True:
        candidate = f'shop{secrets.randbelow(900000) + 100000}'
        if not _taken(candidate, exclude_shop_id):
            return candidate
