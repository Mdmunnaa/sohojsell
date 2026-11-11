"""
কুপন ও অফার (ওয়েবসাইটের চেকআউট) আর অসম্পূর্ণ অর্ডার।

কুপন: % ছাড় (সর্বোচ্চ টাকা ঠিক করা যায়), নির্দিষ্ট টাকা ছাড়, বা ফ্রি ডেলিভারি।
শর্ত: চালু থাকা, তারিখের মধ্যে, কমপক্ষে এত টাকার অর্ডার, মোট কতবার ব্যবহার।
"""
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import AbandonedCheckout, Coupon

ZERO = Decimal('0')
CENT = Decimal('0.01')
CODE_RE = re.compile(r'^[A-Z0-9][A-Z0-9_-]{1,29}$')
BN_TO_EN = str.maketrans('০১২৩৪৫৬৭৮৯', '0123456789')
MAX_COUPONS = 50
ABANDONED_KEEP_DAYS = 30


class CouponError(ValueError):
    """কাস্টমার বা সেলারকে দেখানোর মতো বাংলা বার্তা।"""


def normalize_code(code):
    return str(code or '').strip().upper().translate(BN_TO_EN)


def _money(value, label, *, allow_zero=False, blank_ok=False):
    text = str(value if value is not None else '').translate(BN_TO_EN).replace(',', '').strip()
    if not text:
        if blank_ok:
            return None
        if allow_zero:
            return ZERO
        raise CouponError(f'{label} লিখুন।')
    try:
        number = Decimal(text)
    except InvalidOperation:
        raise CouponError(f'{label} সংখ্যায় লিখুন।')
    if not number.is_finite() or number < 0 or number > Decimal('9999999'):
        raise CouponError(f'{label} ঠিক নেই।')
    if number == 0 and not allow_zero:
        raise CouponError(f'{label} ০-এর বেশি হতে হবে।')
    return number.quantize(CENT, rounding=ROUND_HALF_UP)


def _date(value):
    from datetime import date
    text = str(value or '').strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise CouponError('তারিখটা ঠিকমতো দিন।')


def clean_coupon(shop, post, *, exclude_id=None):
    """সেলারের ফর্ম → Coupon-এর ফিল্ড (dict)। ভুল হলে CouponError।"""
    code = normalize_code(post.get('code'))
    if not CODE_RE.match(code):
        raise CouponError('কুপন কোড ২–৩০ অক্ষরের, শুধু ইংরেজি অক্ষর আর সংখ্যা (যেমন EID20)।')
    same = Coupon.objects.filter(shop=shop, code=code)
    if exclude_id:
        same = same.exclude(pk=exclude_id)
    if same.exists():
        raise CouponError(f'"{code}" কোডটা আগে থেকেই আছে।')
    kind = post.get('kind') if post.get('kind') in dict(Coupon.KIND_CHOICES) else Coupon.PERCENT
    value = ZERO
    if kind == Coupon.PERCENT:
        value = _money(post.get('value'), 'ছাড়ের শতাংশ')
        if value > 100:
            raise CouponError('শতাংশ ছাড় ১০০-এর বেশি হতে পারে না।')
    elif kind == Coupon.AMOUNT:
        value = _money(post.get('value'), 'ছাড়ের টাকা')
    starts, ends = _date(post.get('starts_on')), _date(post.get('ends_on'))
    if starts and ends and ends < starts:
        raise CouponError('শেষের তারিখ শুরুর আগে হতে পারে না।')
    limit = str(post.get('usage_limit') or '').translate(BN_TO_EN).strip()
    if limit and not limit.isdigit():
        raise CouponError('কতবার ব্যবহার, সেটা সংখ্যায় লিখুন।')
    return {
        'code': code, 'kind': kind, 'value': value,
        'min_order': _money(post.get('min_order'), 'কমপক্ষে অর্ডার', allow_zero=True),
        'max_discount': _money(post.get('max_discount'), 'সর্বোচ্চ ছাড়', blank_ok=True) if kind == Coupon.PERCENT else None,
        'usage_limit': int(limit) if limit else None,
        'starts_on': starts, 'ends_on': ends,
    }


def status_of(coupon, today=None):
    """সেলারের লিস্টে দেখানোর অবস্থা: চালু / বন্ধ / শেষ / আসছে / সীমা শেষ।"""
    today = today or timezone.localdate()
    if not coupon.is_active:
        return 'off', 'বন্ধ'
    if coupon.ends_on and coupon.ends_on < today:
        return 'expired', 'মেয়াদ শেষ'
    if coupon.usage_limit is not None and coupon.used_count >= coupon.usage_limit:
        return 'used_up', 'সীমা শেষ'
    if coupon.starts_on and coupon.starts_on > today:
        return 'upcoming', 'এখনো শুরু হয়নি'
    return 'live', 'চালু'


def describe(coupon, lang='bn'):
    """কুপনের এক লাইনের বিবরণ। lang: সেলারের পাতায় বাংলা; চেকআউটে দোকানের ভাষা (দোকান দিলেও চলে)।"""
    from .sf_lang import num, t
    if coupon.kind == Coupon.FREE_DELIVERY:
        text = t('ফ্রি ডেলিভারি', lang)
    elif coupon.kind == Coupon.AMOUNT:
        text = t('{amount} ছাড়', lang, amount='৳' + num(f'{coupon.value:,.0f}', lang))
    else:
        text = t('{p}% ছাড়', lang, p=num(f'{coupon.value.normalize():f}', lang))
        if coupon.max_discount:
            text += t(' (সর্বোচ্চ {amount})', lang, amount='৳' + num(f'{coupon.max_discount:,.0f}', lang))
    if coupon.min_order:
        text += t(' · কমপক্ষে {amount} অর্ডারে', lang, amount='৳' + num(f'{coupon.min_order:,.0f}', lang))
    return text


def find(shop, code, subtotal, delivery_charge, today=None):
    """
    চেকআউটে কোড যাচাই। ফেরত: (coupon, discount, delivery_discount)।
    কোড ফাঁকা হলে (None, 0, 0); না মিললে বা শর্ত না মানলে CouponError।
    """
    code = normalize_code(code)
    if not code:
        return None, ZERO, ZERO
    coupon = Coupon.objects.filter(shop=shop, code=code).first()
    today = today or timezone.localdate()
    from .sf_lang import num, t        # কাস্টমার দেখে — দোকানের ভাষায়
    if coupon is None or not coupon.is_active:
        raise CouponError(t('এই কুপন কোডটা ঠিক নেই।', shop))
    if coupon.starts_on and coupon.starts_on > today:
        raise CouponError(t('এই কুপন এখনো চালু হয়নি।', shop))
    if coupon.ends_on and coupon.ends_on < today:
        raise CouponError(t('এই কুপনের মেয়াদ শেষ।', shop))
    if coupon.usage_limit is not None and coupon.used_count >= coupon.usage_limit:
        raise CouponError(t('এই কুপন আর ব্যবহার করা যাচ্ছে না।', shop))
    subtotal, delivery_charge = Decimal(subtotal), Decimal(delivery_charge or 0)
    if subtotal < coupon.min_order:
        raise CouponError(t('এই কুপন কমপক্ষে {amount} টাকার অর্ডারে চলে।', shop,
                            amount='৳' + num(f'{coupon.min_order:,.0f}', shop)))
    if coupon.kind == Coupon.FREE_DELIVERY:
        return coupon, ZERO, delivery_charge
    if coupon.kind == Coupon.AMOUNT:
        return coupon, min(coupon.value, subtotal), ZERO
    discount = (subtotal * coupon.value / 100).quantize(CENT, rounding=ROUND_HALF_UP)
    if coupon.max_discount:
        discount = min(discount, coupon.max_discount)
    return coupon, min(discount, subtotal), ZERO


def mark_used(coupon):
    Coupon.objects.filter(pk=coupon.pk).update(used_count=F('used_count') + 1)


# ---------------------------------------------------------------- অসম্পূর্ণ অর্ডার
def save_draft(shop, phone, name, address, cart, total):
    """চেকআউটে নম্বর লিখলেই কার্টটা জমা থাকে; একই নম্বরের খোলা ড্রাফট থাকলে সেটাই বদলায়।"""
    if not phone or not cart:
        return None
    cart = [{'key': int(i.get('key', 0)), 'name': str(i.get('name', ''))[:200], 'price': float(i.get('price', 0)),
             'qty': int(i.get('qty', 1))} for i in cart[:50] if str(i.get('name', '')).strip()]
    draft = AbandonedCheckout.objects.filter(shop=shop, phone=phone, recovered_order__isnull=True).first()
    fields = {'name': str(name or '')[:150], 'address': str(address or '')[:500], 'cart': cart,
              'total': Decimal(str(total or 0)).quantize(CENT)}
    if draft is None:
        return AbandonedCheckout.objects.create(shop=shop, phone=phone, **fields)
    for key, value in fields.items():
        setattr(draft, key, value)
    draft.save()
    return draft


def mark_recovered(shop, phone, order):
    AbandonedCheckout.objects.filter(shop=shop, phone=phone, recovered_order__isnull=True).update(recovered_order=order)


def open_drafts(shop):
    """এখনো অর্ডার হয়নি এমন ড্রাফট, নতুনটা উপরে; ৩০ দিনের পুরনোগুলো মুছে ফেলা হয়।"""
    from datetime import timedelta
    AbandonedCheckout.objects.filter(shop=shop, updated_at__lt=timezone.now() - timedelta(days=ABANDONED_KEEP_DAYS)).delete()
    return AbandonedCheckout.objects.filter(shop=shop, recovered_order__isnull=True)
