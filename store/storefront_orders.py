"""
দোকানের অর্ডার তৈরি — ওয়েবসাইটের চেকআউট আর Messenger-এর চ্যাট-অর্ডার দুটোই এখান দিয়ে যায়, তাই নিয়ম এক:
দাম, স্টক, ডেলিভারি চার্জ, কুপন, ব্লক করা নম্বর, পেমেন্টের ধরন — সব সার্ভারে হিসাব; বাইরে থেকে শুধু প্রোডাক্ট-পরিমাণ,
এলাকার id আর কাস্টমারের তথ্য আসে।
"""
from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction

from . import delivery, offers, risk, sf_lang, shop_payments, variants
from .models import Customer, Order, OrderItem, StorefrontOrder, StorefrontOrderItem


class OrderError(Exception):
    def __init__(self, message, *, coupon_error=False):
        super().__init__(message)
        self.coupon_error = coupon_error


@dataclass
class Placed:
    order: Order
    sf_order: StorefrontOrder
    pay_now: Decimal
    choice: str


def place(shop, *, quantities, name, phone, address, note='', zone_id=None, coupon_code=None,
          payment_choice=None, landing_slug=None, fb_source='', fb_post_id='', messenger_contact=None):
    """
    quantities: {কার্টের নম্বর (প্রোডাক্ট id, ভ্যারিয়েন্ট হলে -id): পরিমাণ}। phone আগেই ঠিক করা (normalize)।
    ভুল হলে OrderError (কাস্টমারকে দেখানোর মতো লেখা)। সফল হলে Placed — SMS, পেমেন্ট শুরু ইত্যাদি ডাকে যে ডাকে সে।
    """
    if not quantities:
        raise OrderError(sf_lang.t('কার্ট খালি!', shop))
    name, address, note = (name or '').strip()[:150], (address or '').strip()[:500], (note or '').strip()[:500]
    if not name or not address:
        raise OrderError(sf_lang.t('নাম, মোবাইল নম্বর আর ঠিকানা দিন।', shop))
    if not phone:
        raise OrderError(sf_lang.t('সঠিক মোবাইল নম্বর দিন (০১ দিয়ে শুরু, ১১ সংখ্যা)।', shop))
    if risk.is_blocked(shop, phone):
        raise OrderError(sf_lang.t('এই নম্বর থেকে এখন অর্ডার নেওয়া যাচ্ছে না। দোকানে সরাসরি যোগাযোগ করুন।', shop))

    choices = shop_payments.checkout_choices(shop)
    choice = payment_choice or choices[0]
    if choice not in choices:
        raise OrderError(sf_lang.t('পেমেন্টের ধরন বেছে নিন।', shop))

    with transaction.atomic():
        # একসাথে অনেকে অর্ডার দিলেও স্টকের চেয়ে বেশি বিক্রি না হয়
        chosen = variants.resolve(shop, quantities.keys(), lock=True)
        if len(chosen) != len(quantities) or any(not item.product.is_active for item in chosen.values()):
            raise OrderError(sf_lang.t('কার্টের একটা প্রোডাক্ট আর পাওয়া যাচ্ছে না। কার্ট দেখে আবার চেষ্টা করুন।', shop))
        subtotal = Decimal('0')
        for key, qty in quantities.items():
            item = chosen[key]
            if item.needs_choice:
                raise OrderError(sf_lang.t("'{name}'-এর সাইজ/রং বেছে নিয়ে আবার কার্টে যোগ করুন।", shop, name=item.name))
            if item.stock < qty:
                raise OrderError(sf_lang.t("'{name}' স্টকে আছে মাত্র {n}টা।", shop, name=item.name, n=item.stock))
            subtotal += item.price * qty

        zone, delivery_charge = delivery.charge_for(shop, zone_id, subtotal)
        if delivery_charge is None:
            raise OrderError(sf_lang.t('ডেলিভারির এলাকা বেছে নিন।', shop))
        try:
            coupon, discount, delivery_off = offers.find(shop, coupon_code, subtotal, delivery_charge)
        except offers.CouponError as exc:
            raise OrderError(str(exc), coupon_error=True)
        delivery_charge = delivery_charge - delivery_off
        total = subtotal - discount + delivery_charge
        pay_now = shop_payments.amount_now(choice, total, delivery_charge)

        sf_order = StorefrontOrder.objects.create(
            shop=shop, customer_name=name, customer_phone=phone, customer_address=address,
            customer_note=note, total_amount=total, delivery_charge=delivery_charge,
            delivery_zone=zone.name if zone else '', status='Pending')
        customer, _ = Customer.objects.get_or_create(shop=shop, phone=phone,
                                                     defaults={'name': name, 'address': address})
        customer.name, customer.address = name, address
        customer.save(update_fields=['name', 'address'])
        landing = None
        if landing_slug:
            from .models import LandingPage
            landing = LandingPage.objects.filter(shop=shop, slug=str(landing_slug)[:60]).first()
        order_note = ' · '.join(x for x in [f'এলাকা: {zone.name}' if zone else '',
                                            f'কুপন {coupon.code}' if coupon else '',
                                            f'ল্যান্ডিং পেজ: {landing.headline}' if landing else '', note] if x) or None
        main_order = Order.objects.create(
            shop=shop, customer=customer, source='storefront', delivery_charge=delivery_charge, discount=discount,
            payment_method='COD', status='Pending', total_amount=total, note=order_note,
            coupon_code=coupon.code if coupon else '', landing=landing,
            online_payment_status=Order.ONLINE_PENDING if pay_now > 0 else Order.ONLINE_NONE,
            fb_source=fb_source or '', fb_post_id=(fb_post_id or '')[:100], messenger_contact=messenger_contact)
        sf_order.order = main_order
        sf_order.save(update_fields=['order'])
        if coupon:
            offers.mark_used(coupon)
        offers.mark_recovered(shop, phone, main_order)
        for key, qty in quantities.items():
            item = chosen[key]
            StorefrontOrderItem.objects.create(order=sf_order, product=item.product, quantity=qty, price=item.price,
                                               variant_name=item.variant_name)
            OrderItem.objects.create(order=main_order, product=item.product, variant=item.variant,
                                     variant_name=item.variant_name, price=item.price, quantity=qty,
                                     cost_price=item.cost_price)
            variants.take(item, qty)
    return Placed(order=main_order, sf_order=sf_order, pay_now=pay_now, choice=choice)
