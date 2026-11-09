# store/delivery.py
"""
ডেলিভারি চার্জ: সেলার এলাকা আর চার্জ ঠিক করে, কাস্টমার চেকআউটে নিজের এলাকা বেছে নেয়।
চার্জ সবসময় সার্ভারে হিসাব হয়; ব্রাউজার থেকে শুধু এলাকার id আসে।
"""
from decimal import Decimal

DEFAULT_ZONES = [('ঢাকা সিটির ভিতরে', Decimal('60')), ('ঢাকার বাইরে', Decimal('120'))]


def zones_for(shop):
    """চালু এলাকাগুলো। কোনো এলাকা না থাকলে (নতুন দোকান) সাধারণ দুটো এলাকা বানিয়ে দেয়।"""
    from .models import DeliveryZone
    zones = list(DeliveryZone.objects.filter(shop=shop, is_active=True))
    if zones or DeliveryZone.objects.filter(shop=shop).exists():
        return zones
    DeliveryZone.objects.bulk_create([
        DeliveryZone(shop=shop, name=name, charge=charge, sort_order=i)
        for i, (name, charge) in enumerate(DEFAULT_ZONES)
    ])
    return list(DeliveryZone.objects.filter(shop=shop, is_active=True))


def is_free(shop, subtotal):
    return bool(shop.free_delivery_min and Decimal(subtotal) >= shop.free_delivery_min)


def charge_for(shop, zone_id, subtotal):
    """
    (এলাকা, চার্জ) ফেরত দেয়। ভুল বা অন্য দোকানের এলাকা হলে (None, None)।
    ফ্রি ডেলিভারির সীমা পার হলে চার্জ ০।
    """
    zones = zones_for(shop)
    if not zones:
        # সেলার সব এলাকা বন্ধ করে রাখলে: পুরনো একটা চার্জ
        return None, (Decimal('0') if is_free(shop, subtotal) else Decimal(shop.delivery_charge or 0))
    try:
        zone_id = int(zone_id)
    except (TypeError, ValueError):
        zone_id = None
    zone = next((z for z in zones if z.id == zone_id), None)
    if zone is None:
        if len(zones) == 1:
            zone = zones[0]
        else:
            return None, None
    return zone, (Decimal('0') if is_free(shop, subtotal) else zone.charge)
