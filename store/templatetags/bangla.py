from django import template

register = template.Library()

BN_DIGITS = str.maketrans('0123456789', '০১২৩৪৫৬৭৮৯')


@register.filter
def bn(value):
    """{{ 120|bn }} → ১২০ (সংখ্যা বাংলা অঙ্কে)।"""
    if value is None:
        return ''
    return str(value).translate(BN_DIGITS)
