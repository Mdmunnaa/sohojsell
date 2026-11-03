# store/plans.py
"""
প্যাকেজের নিয়ম এক জায়গায়।

- ফ্রি প্ল্যান নেই, আছে শুধু ৩০ দিনের ফ্রি ট্রায়াল (ডেটাবেসে subscription_plan = 'Free')।
  ট্রায়ালে Standard-এর সব সুবিধা থাকে, Facebook অটোমেশনসহ।
- ওয়েবসাইট (স্টোরফ্রন্ট) সব প্ল্যানে আর ট্রায়ালে চালু। মেয়াদ শেষ হলে ড্যাশবোর্ড সাথে সাথে লক হয়,
  কিন্তু ওয়েবসাইট আরও ৭ দিন চালু থাকে, তারপর বন্ধ।
"""
from datetime import timedelta

from django.utils import timezone

TRIAL_PLAN = 'Free'
STOREFRONT_GRACE_DAYS = 7

# None = সীমাহীন
PLAN_LIMITS = {
    'Free':     {'products': 1000, 'staff': 3,  'facebook': True,  'custom_domain': False},   # ৩০ দিনের ট্রায়াল
    'Basic':    {'products': 200,  'staff': 1,  'facebook': False, 'custom_domain': False},
    'Standard': {'products': 1000, 'staff': 3,  'facebook': True,  'custom_domain': False},
    'Premium':  {'products': None, 'staff': 10, 'facebook': True,  'custom_domain': True},
}

PLAN_LABELS = {
    'Free': 'ফ্রি ট্রায়াল',
    'Basic': 'Basic',
    'Standard': 'Standard',
    'Premium': 'Premium',
}


def limits_for(shop):
    return PLAN_LIMITS.get(getattr(shop, 'subscription_plan', '') or TRIAL_PLAN, PLAN_LIMITS['Basic'])


def subscription_end(shop):
    """মেয়াদ কোন দিন শেষ (সেদিন পর্যন্ত চালু)। ট্রায়ালে trial_ends_at, পেইড প্ল্যানে valid_until।"""
    if shop.subscription_plan == TRIAL_PLAN:
        return timezone.localtime(shop.trial_ends_at).date() if shop.trial_ends_at else None
    return shop.valid_until


def storefront_is_open(shop, today=None):
    """
    কাস্টমাররা ওয়েবসাইট দেখতে পাবে কিনা। মেয়াদ চলাকালে আর মেয়াদ শেষের পর ৭ দিন পর্যন্ত চালু।
    পুরনো কোনো পেইড শপের মেয়াদের তারিখ না থাকলে বন্ধ না করে চালু রাখা হয়।
    """
    end = subscription_end(shop)
    if end is None:
        return shop.subscription_plan != TRIAL_PLAN
    today = today or timezone.localdate()
    return today <= end + timedelta(days=STOREFRONT_GRACE_DAYS)


def storefront_closes_on(shop):
    end = subscription_end(shop)
    return end + timedelta(days=STOREFRONT_GRACE_DAYS) if end else None
