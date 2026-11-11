"""Master HQ-র ছোট ফিল্টার — সংখ্যা ভারতীয় কমায় (1,23,456), টাকা, "কত আগে", দোকানের অবস্থা।"""
from decimal import Decimal, InvalidOperation

from django import template
from django.utils import timezone

from store.hq import STATUS_LABELS

register = template.Library()


def _group(n):
    s = str(abs(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ','.join(parts + [tail])
    return ('-' if n < 0 else '') + s


@register.filter
def hq_num(value):
    try:
        number = Decimal(str(value if value is not None else 0))
    except (InvalidOperation, ValueError):
        return value
    whole = int(number.quantize(Decimal('1')))
    return _group(whole)


@register.filter
def hq_taka(value):
    return '৳' + hq_num(value)


@register.filter
def ago(value):
    if not value:
        return '-'
    now = timezone.now()
    if not hasattr(value, 'tzinfo'):          # শুধু তারিখ
        days = (timezone.localdate() - value).days
        return 'আজ' if days == 0 else ('গতকাল' if days == 1 else f'{days} দিন আগে')
    seconds = int((now - value).total_seconds())
    if seconds < 60:
        return 'এইমাত্র'
    if seconds < 3600:
        return f'{seconds // 60} মিনিট আগে'
    if seconds < 86400:
        return f'{seconds // 3600} ঘণ্টা আগে'
    days = seconds // 86400
    if days < 31:
        return f'{days} দিন আগে'
    return timezone.localtime(value).strftime('%d %b %Y')


@register.filter
def hq_status(key):
    return STATUS_LABELS.get(key, key)


@register.filter
def days_left(day):
    """মেয়াদের বাকি দিন (শেষ হয়ে গেলে ঋণাত্মক)।"""
    if not day:
        return None
    if hasattr(day, 'tzinfo'):
        day = timezone.localtime(day).date()
    return (day - timezone.localdate()).days
