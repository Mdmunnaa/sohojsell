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
