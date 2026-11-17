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
def _return_stock(order, user=None):
    for item in order.items.all():
        variants.give_back(item.product_id, item.variant_id, item.quantity, reason='order_cancel', order=order, user=user)


def _take_stock_again(order, user=None):
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
        variants.take(sellable, qty, reason='order_restore', order=order, user=user)


def _coupon_count(order, change):
    if not order.coupon_code:
        return
    from django.db.models import F
    from django.db.models.functions import Greatest
    from .models import Coupon
    Coupon.objects.filter(shop_id=order.shop_id, code=order.coupon_code).update(
        used_count=Greatest(F('used_count') + change, 0))


def set_status(order, new_status, *, notify=True, user=None):
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
                _return_stock(locked, user)
                locked.stock_returned = True
                _coupon_count(locked, -1)       # বাতিল অর্ডার কুপনের সীমায় ধরা হয় না
            elif new_status not in NOT_COUNTED and locked.stock_returned:
                _take_stock_again(locked, user)
                locked.stock_returned = False
                _coupon_count(locked, +1)
        locked.status = new_status
        locked.save(update_fields=['status', 'stock_returned'])
        StorefrontOrder.objects.filter(order=locked).update(
            status='Cancelled' if new_status in NOT_COUNTED else new_status)
    order.status, order.stock_returned = locked.status, locked.stock_returned
    if notify:
        notify_customer(order, new_status)
    return True


def notify_customer(order, status):
    """
    অবস্থা বদলালে কাস্টমারকে খবর: Messenger থেকে আসা অর্ডারে Messenger-এ (ফ্রি, store/messenger.py), আর SMS —
    সেলার সেই সুইচ চালু রাখলে তবেই। কোনো সমস্যায় অর্ডার আটকায় না।
    """
    from . import messenger, sms
    if order.messenger_contact_id:
        messenger.order_update(order, status)
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


# ---------------------------------------------------------------- অর্ডার এডিট: প্রোডাক্ট যোগ-বাদ, পরিমাণ, দাম
EDITABLE_STATUSES = ('Pending', 'Confirmed')


def items_locked_reason(order):
    """প্রোডাক্ট বদলানো না গেলে কেন (সেলারকে দেখানোর বাংলা), গেলে ''।"""
    if order.source == 'pos':
        return 'POS-এর বিক্রি এখানে বদলানো যায় না — POS-এর "আজকের বিক্রি" থেকে ফেরত নিন।'
    if order.status not in EDITABLE_STATUSES:
        labels = {'Shipped': 'পাঠানো', 'Delivered': 'ডেলিভারি হয়ে যাওয়া', 'Returned': 'ফেরত আসা', 'Cancelled': 'বাতিল'}
        return f'{labels.get(order.status, order.status)} অর্ডারের প্রোডাক্ট বদলানো যায় না।'
    if order.steadfast_tracking_code:
        return 'অর্ডারটা কুরিয়ারে বুক হয়ে গেছে — এখন প্রোডাক্ট বদলালে কুরিয়ারের টাকার হিসাব মিলবে না।'
    return ''


def edit_items(order, changes, additions, *, delivery_charge, discount, user=None):
    """
    অর্ডারের প্রোডাক্ট বদলানো, স্টক ঠিক রেখে (সব একসাথে — ভুল হলে কিছুই বদলায় না)।
      changes:   {OrderItem id: (নতুন পরিমাণ, নতুন দাম)} — পরিমাণ ০ মানে বাদ
      additions: [(কার্টের key, পরিমাণ, দাম)] — key: প্রোডাক্ট id, বা সাইজ/রং হলে −ভ্যারিয়েন্ট id
    পরিমাণ বাড়লে বাড়তিটা স্টক থেকে কাটে (স্টকে না থাকলে FlowError), কমলে বা বাদ দিলে স্টকে ফেরে।
    মোট = প্রোডাক্টের দাম × পরিমাণ + ডেলিভারি চার্জ − ছাড়। কাস্টমার অনলাইনে যা দিয়েছে তার নিচে মোট নামানো যায় না।
    """
    from decimal import Decimal
    from .models import OrderItem, StorefrontOrderItem

    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        reason = items_locked_reason(order)
        if reason:
            raise FlowError(reason)
        items = {item.id: item for item in order.items.select_related('product', 'variant')}
        keys = {(-i.variant_id if i.variant_id else i.product_id) for i in items.values()} | {k for k, _q, _p in additions}
        stock = variants.resolve(order.shop, keys, lock=True)

        plan_take, plan_give, updates, deletes = [], [], [], []
        for item_id, (qty, price) in changes.items():
            item = items.get(item_id)
            if item is None:
                continue
            delta = qty - item.quantity
            sellable = stock.get(-item.variant_id if item.variant_id else item.product_id)
            if delta > 0:
                if sellable is None or sellable.needs_choice:
                    raise FlowError(f'"{item.display_name}"-এর পরিমাণ বাড়ানো যাচ্ছে না — প্রোডাক্ট বা সাইজটা আর নেই।')
                if sellable.stock < delta:
                    raise FlowError(f'"{item.display_name}" স্টকে আছে মাত্র {sellable.stock}টা, '
                                    f'তাই {delta}টা বাড়ানো যাচ্ছে না।')
                plan_take.append((sellable, delta))
            elif delta < 0:
                plan_give.append((item.product_id, item.variant_id, -delta))
            if qty == 0:
                deletes.append(item.id)
            elif delta or price != item.price:
                updates.append((item, qty, price))

        merged = {}
        for key, qty, price in additions:
            entry = merged.setdefault(key, [0, price])
            entry[0] += qty
        new_rows = []
        for key, (qty, price) in merged.items():
            sellable = stock.get(key)
            if sellable is None or sellable.needs_choice:
                raise FlowError('যোগ করা একটা প্রোডাক্ট আর পাওয়া যাচ্ছে না। পাতাটা আবার খুলুন।')
            already = sum(t[1] for t in plan_take if t[0].key == key)
            if sellable.stock < qty + already:
                raise FlowError(f'"{sellable.name}" স্টকে আছে মাত্র {sellable.stock}টা।')
            plan_take.append((sellable, qty))
            new_rows.append((sellable, qty, price))

        kept = [i for i in items.values() if i.id not in deletes]
        if not kept and not new_rows:
            raise FlowError('অর্ডারে অন্তত একটা প্রোডাক্ট রাখতে হবে। পুরো অর্ডার না লাগলে বাতিল করুন।')

        subtotal = Decimal('0')
        for item in kept:
            qty, price = changes.get(item.id, (item.quantity, item.price))
            subtotal += price * qty
        subtotal += sum((price * qty for _s, qty, price in new_rows), Decimal('0'))
        total = max(subtotal + delivery_charge - discount, Decimal('0'))
        if order.online_payment_status == Order.ONLINE_PAID and total < order.advance_paid:
            raise FlowError(f'কাস্টমার অনলাইনে ৳{order.advance_paid:,.0f} দিয়েছে, মোট এর কম করা যায় না। '
                            'কিছু টাকা ফেরত দিতে হলে অর্ডারটা বাতিল করে "টাকা ফেরত" দিন।')

        for sellable, qty in plan_take:
            variants.take(sellable, qty, reason='order_edit', order=order, user=user)
        for product_id, variant_id, qty in plan_give:
            variants.give_back(product_id, variant_id, qty, reason='order_edit', order=order, user=user)
        OrderItem.objects.filter(pk__in=deletes).delete()
        for item, qty, price in updates:
            OrderItem.objects.filter(pk=item.pk).update(quantity=qty, price=price)
        for sellable, qty, price in new_rows:
            OrderItem.objects.create(order=order, product=sellable.product, variant=sellable.variant,
                                     variant_name=sellable.variant_name, price=price, quantity=qty,
                                     cost_price=sellable.cost_price)
        order.delivery_charge, order.discount, order.total_amount = delivery_charge, discount, total
        if order.online_payment_status != Order.ONLINE_PAID:
            order.advance_paid = min(order.advance_paid, total)
        order.save(update_fields=['delivery_charge', 'discount', 'total_amount', 'advance_paid'])

        sf_order = StorefrontOrder.objects.filter(order=order).first()
        if sf_order is not None:            # ওয়েবসাইটের অর্ডারের কপিটাও মেলানো (কাস্টমারের ট্র্যাক পাতা)
            sf_order.items.all().delete()
            StorefrontOrderItem.objects.bulk_create([
                StorefrontOrderItem(order=sf_order, product=i.product, quantity=i.quantity, price=i.price,
                                    variant_name=i.variant_name) for i in order.items.select_related('product')])
            StorefrontOrder.objects.filter(pk=sf_order.pk).update(total_amount=total, delivery_charge=delivery_charge)
    return order
