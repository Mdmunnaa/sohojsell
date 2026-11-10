"""
অর্ডারের অবস্থা বদলানোর একটাই রাস্তা (set_status):
  - বাতিল/ফেরত হলে মাল স্টকে ফেরে, আবার চালু করলে স্টক থেকে কাটে (POS বাদে — তার নিজের ফেরতের ব্যবস্থা আছে)
  - ওয়েবসাইটের অর্ডারের (StorefrontOrder) অবস্থাও একসাথে বদলায়
  - সেলার চালু রাখলে কাস্টমারকে SMS যায় (কনফার্ম, কুরিয়ারে দেওয়া, ডেলিভারি)
সাথে কাস্টমারের অর্ডার ট্র্যাক করার লিংকের কোড।
"""
import hashlib
import hmac

from django.conf import settings
from django.db import transaction

from . import variants
from .models import Order, ProductVariant, StorefrontOrder

NOT_COUNTED = ('Returned', 'Cancelled')
STATUSES = [key for key, _label in Order.STATUS_CHOICES]
STATUS_BN = {'Pending': 'নতুন', 'Confirmed': 'কনফার্ম', 'Shipped': 'কুরিয়ারে', 'Delivered': 'ডেলিভারি হয়েছে',
             'Returned': 'ফেরত', 'Cancelled': 'বাতিল'}
# কোন অবস্থায় কোন সুইচ চালু থাকলে SMS যাবে
SMS_SWITCH = {'Confirmed': 'sms_on_confirmed', 'Shipped': 'sms_on_shipped', 'Delivered': 'sms_on_delivered'}
WALK_IN_PHONE = '00000000000'


class FlowError(ValueError):
    """সেলারকে দেখানোর মতো বাংলা বার্তা।"""


# ---------------------------------------------------------------- ট্র্যাকিং লিংক
def _token(order_id):
    digest = hmac.new(settings.SECRET_KEY.encode(), f'order-track:{order_id}'.encode(), hashlib.sha256)
    return digest.hexdigest()[:6]


def track_code(order):
    """লিংকের শেষ অংশ, যেমন 123-a1b2c3 — অর্ডার নম্বর জানলেই অন্যের অর্ডার দেখা যায় না।"""
    return f'{order.id}-{_token(order.id)}'


def order_from_code(shop, code):
    order_id, _, token = str(code or '').partition('-')
    if not order_id.isdigit() or not hmac.compare_digest(token, _token(order_id)):
        return None
    return (Order.objects.filter(shop=shop, pk=order_id).exclude(source='pos')
            .select_related('customer').first())


def track_link(shop, order, *, short=False):
    from .links import absolute_storefront_link
    link = absolute_storefront_link(shop, 'storefront_track_order', track_code(order))
    return link.split('://', 1)[-1] if short else link


# ---------------------------------------------------------------- অবস্থা বদল
def _return_stock(order):
    for item in order.items.all():
        variants.give_back(item.product_id, item.variant_id, item.quantity)


def _take_stock_again(order):
    items = list(order.items.select_related('product'))
    variant_rows = {v.id: v for v in ProductVariant.objects.select_for_update()
                    .filter(id__in=[i.variant_id for i in items if i.variant_id])}
    plan = []
    for item in items:
        product = type(item.product).objects.select_for_update().get(pk=item.product_id)
        variant = variant_rows.get(item.variant_id)
        if product.has_variants and variant is None:
            continue                    # সাইজ/রংটা মুছে ফেলা হয়েছে; স্টকে হাত দেওয়া যায় না
        sellable = variants.Sellable(product, variant)
        if sellable.stock < item.quantity:
            raise FlowError(f'"{sellable.name}" স্টকে আছে মাত্র {sellable.stock}টা, তাই অর্ডারটা আবার চালু করা যাচ্ছে না।')
        plan.append((sellable, item.quantity))
    for sellable, qty in plan:
        variants.take(sellable, qty)


def set_status(order, new_status, *, notify=True):
    """
    অর্ডারের অবস্থা বদলায়। কিছু বদলালে True। ভুল অবস্থা বা স্টক না থাকলে FlowError।
    order অবজেক্টটাও হালনাগাদ হয়ে যায়।
    """
    if new_status not in STATUSES:
        raise FlowError('অর্ডারের অবস্থা ঠিক নেই।')
    with transaction.atomic():
        locked = Order.objects.select_for_update().get(pk=order.pk)
        if locked.status == new_status:
            return False
        if locked.source != 'pos':
            if new_status in NOT_COUNTED and not locked.stock_returned:
                _return_stock(locked)
                locked.stock_returned = True
            elif new_status not in NOT_COUNTED and locked.stock_returned:
                _take_stock_again(locked)
                locked.stock_returned = False
        locked.status = new_status
        locked.save(update_fields=['status', 'stock_returned'])
        StorefrontOrder.objects.filter(order=locked).update(
            status='Cancelled' if new_status in NOT_COUNTED else new_status)
    order.status, order.stock_returned = locked.status, locked.stock_returned
    if notify:
        notify_customer(order, new_status)
    return True


def notify_customer(order, status):
    """অবস্থা বদলালে কাস্টমারকে SMS — সেলার সেই সুইচ চালু রাখলে তবেই। কোনো সমস্যায় অর্ডার আটকায় না।"""
    from . import sms
    switch = SMS_SWITCH.get(status)
    shop = order.shop
    if not switch or order.source == 'pos' or not shop.is_sms_active or not getattr(shop, switch):
        return None
    phone = order.customer.phone
    if not phone or phone == WALK_IN_PHONE:
        return None
    link = track_link(shop, order, short=True) if status == 'Shipped' else None
    return sms.send_auto(shop, phone, sms.status_text(shop, order, status, link),
                         f'অর্ডার নং {sms.bn_num(order.id)} · {STATUS_BN[status]}')
