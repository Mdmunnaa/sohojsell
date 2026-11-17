"""দোকানের ওয়েবসাইটের লেখা দোকানের ভাষায় — store/sf_lang.py দেখুন।"""
from django import template
from django.utils.html import escapejs
from django.utils.safestring import mark_safe

from store import sf_lang

register = template.Library()


def _lang(context):
    if context.get('sf_lang'):
        return sf_lang.lang_of(context['sf_lang'])
    return sf_lang.lang_of(context.get('shop'))


@register.simple_tag(takes_context=True)
def t(context, text, **values):
    """{% t "কার্টে যোগ করুন" %} · {% t "আর মাত্র {n}টা আছে" n=stock %}"""
    return sf_lang.t(text, _lang(context), **values)


@register.simple_tag(takes_context=True)
def tjs(context, text, **values):
    """JS স্ট্রিংয়ের ভেতরে: showToast('{% tjs "কার্ট খালি" %}')। {n} না দিলে JS-এ .replace('{n}', ...) করুন।"""
    return mark_safe(escapejs(sf_lang.t(text, _lang(context), **values)))


@register.simple_tag(takes_context=True)
def num(context, value):
    """{% num product.sold_count %} → বাংলায় ২৯, ইংরেজিতে 29"""
    return sf_lang.num(value, _lang(context))


@register.simple_tag(takes_context=True)
def sf_lang_code(context):
    """<html lang="{% sf_lang_code %}">"""
    return _lang(context)


@register.simple_tag(takes_context=True)
def status_label(context, status):
    return sf_lang.status_label(status, _lang(context))


@register.simple_tag(takes_context=True)
def sf_date(context, day):
    """{% sf_date order_day %} → বাংলায় ১০ নভেম্বর ২০২৬, ইংরেজিতে 10 Nov 2026"""
    if not day:
        return ''
    if _lang(context) == sf_lang.EN:
        return f'{day.day} {day.strftime("%b")} {day.year}'
    from .bangla import bn_day
    return bn_day(day)


@register.simple_tag(takes_context=True)
def sf_taka(context, value):
    """{% sf_taka order.total_amount %} → বাংলায় ৳১,২৫০, ইংরেজিতে ৳1,250"""
    from .bangla import taka
    return sf_lang.num(taka(value), _lang(context))


def _bd_digits(value):
    """'8801712345678', '+880 1712-345678', '01712345678' → '01712345678' (না মিললে খালি)।"""
    digits = ''.join(ch for ch in str(value or '') if ch.isdigit())
    if digits.startswith('880'):
        digits = digits[2:]
    return digits if len(digits) == 11 and digits.startswith('01') else ''


@register.filter
def wa_number(value):
    """wa.me লিংকের নম্বর: 8801XXXXXXXXX (দোকানের সেটিংসে যেভাবেই রাখা থাকুক)।"""
    local = _bd_digits(value)
    return '88' + local if local else ''.join(ch for ch in str(value or '') if ch.isdigit())


@register.filter
def bd_phone(value):
    """দেখানোর জন্য: 01712-345678।"""
    local = _bd_digits(value)
    return f'{local[:5]}-{local[5:]}' if local else value


@register.inclusion_tag('store/storefront/_pay_pending.html', takes_context=True)
def pay_pending_bar(context):
    """
    দোকানের ওয়েবসাইটের উপরে "অর্ডার #… — অনলাইন পেমেন্ট এখনো হয়নি, পেমেন্ট করুন": কাস্টমার অনলাইনে দেবেন বলে অর্ডার দিয়ে
    পেমেন্টের পাতা থেকে অন্য পাতায় চলে গেলে ফেরার রাস্তা। শুধু যে ব্রাউজার থেকে অর্ডার হয়েছে (session-এর sf_orders)।
    """
    request, shop = context.get('request'), context.get('shop')
    item = None
    ids = request.session.get('sf_orders') if request is not None and shop is not None else None
    if ids:
        from store import shop_payments
        from store.models import Order, StorefrontOrder
        recent = (StorefrontOrder.objects.filter(shop=shop, id__in=ids[-5:], order__online_payment_status=Order.ONLINE_PENDING,
                                                 order__status__in=('Pending', 'Confirmed'))
                  .select_related('order').order_by('-id'))
        for sf_order in recent[:3]:
            pending = shop_payments.pending_payment(sf_order.order)
            if pending:
                # দোকানের পাতার দামের মতো (sf_lang.money)
                # অর্ডার নম্বর আর টাকা দুটোই ইংরেজি অঙ্কে — পাশের দামগুলোর মতো (str দিলে {% t %} অঙ্ক বদলায় না)
                item = {'sf_id': sf_order.id, 'number': str(sf_order.order.id), 'amount': sf_lang.money(pending['amount'])}
                break
    return {'item': item, 'shop': shop, 'request': request, 'csrf_token': context.get('csrf_token'),
            'sf_lang': context.get('sf_lang')}
