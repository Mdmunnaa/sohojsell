from django import template

register = template.Library()

BN_DIGITS = str.maketrans('0123456789', '০১২৩৪৫৬৭৮৯')


@register.filter
def bn(value):
    """{{ 120|bn }} → ১২০ (সংখ্যা বাংলা অঙ্কে)।"""
    if value is None:
        return ''
    return str(value).translate(BN_DIGITS)


@register.filter
def taka(value):
    """{{ 12500|taka }} → ৳১২,৫০০ (পয়সা থাকলে ৳১২,৫০০.৫০)।"""
    from decimal import Decimal, InvalidOperation
    try:
        number = Decimal(str(value if value not in (None, '') else 0))
    except InvalidOperation:
        return ''
    text = f'{number:,.2f}'
    if text.endswith('.00'):
        text = text[:-3]
    sign = '−' if number < 0 else ''
    return f'{sign}৳{text.lstrip("-")}'.translate(BN_DIGITS)


@register.filter
def bn_day(day):
    """{{ purchase.purchased_on|bn_day }} → ১০ নভেম্বর ২০২৬"""
    if not day:
        return ''
    from store.dashboard import BN_MONTHS
    return f'{day.day} {BN_MONTHS[day.month - 1]} {day.year}'.translate(BN_DIGITS)


@register.filter
def bn_month(number):
    """{{ date|date:"n"|bn_month }} → নভেম্বর"""
    from store.dashboard import BN_MONTHS
    try:
        return BN_MONTHS[int(str(number).translate(str.maketrans('০১২৩৪৫৬৭৮৯', '0123456789'))) - 1]
    except (ValueError, IndexError):
        return ''


@register.filter
def star_flags(avg):
    """৪.৩ → [True, True, True, True, False] (কোন তারাগুলো ভরা)।"""
    try:
        value = float(avg)
    except (TypeError, ValueError):
        value = 0.0
    return [n <= value + 0.5 for n in range(1, 6)]


@register.filter
def bn_when(value):
    """{{ order.created_at|bn_when }} → ১০ নভেম্বর, বিকাল ৩:২০"""
    if not value:
        return ''
    from django.utils import timezone
    from store.dashboard import BN_MONTHS
    if timezone.is_aware(value):
        value = timezone.localtime(value)
    hour = value.hour
    part = 'রাত' if hour < 5 else 'সকাল' if hour < 12 else 'দুপুর' if hour < 16 else 'বিকাল' if hour < 18 else 'সন্ধ্যা' if hour < 20 else 'রাত'
    clock = f'{hour % 12 or 12}:{value.minute:02d}'
    return f'{value.day} {BN_MONTHS[value.month - 1]}, {part} {clock}'.translate(BN_DIGITS)
