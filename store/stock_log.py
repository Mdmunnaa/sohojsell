"""
স্টক বদলের খাতা: variants.take / give_back আর হাতে বদলানোর জায়গাগুলো এখানে একটা করে StockMovement লেখে।
খাতা লিখতে গিয়ে ভুল হলে বিক্রি থামে না — শুধু লগে যায়।
"""
import logging
from decimal import Decimal

logger = logging.getLogger(__name__)


def record(product_id, variant_id, change, *, reason='other', order=None, purchase=None, user=None, note=''):
    """একটা বদল লেখে। change: + মানে বাড়ল, − মানে কমল। পরে কত থাকল সেটা ডাটাবেস থেকে পড়ে।"""
    if not change:
        return
    from .models import Product, ProductVariant, StockMovement
    try:
        row = Product.objects.filter(pk=product_id).values('shop_id', 'stock_quantity').first()
        if row is None:
            return
        after, variant_name = row['stock_quantity'], ''
        if variant_id:
            variant = ProductVariant.objects.filter(pk=variant_id).values('name', 'stock_quantity').first()
            if variant is None:
                variant_id = None
            else:
                after, variant_name = variant['stock_quantity'], variant['name']
        actor = user if getattr(user, 'is_authenticated', False) else None
        StockMovement.objects.create(
            shop_id=row['shop_id'], product_id=product_id, variant_id=variant_id, variant_name=variant_name[:80],
            change=Decimal(str(change)), stock_after=after, reason=reason, order=order,
            order_ref=getattr(order, 'pk', None), purchase=purchase, user=actor, note=str(note or '')[:200])
    except Exception:    # noqa: BLE001
        logger.exception('stock log failed for product %s', product_id)


def record_bulk(shop, rows, *, reason, user=None):
    """অনেক প্রোডাক্ট একসাথে (ফাইল থেকে আনা): rows = [(product, variant_or_None, qty), …]। প্রতিটার পরের স্টক = qty।"""
    from .models import StockMovement
    actor = user if getattr(user, 'is_authenticated', False) else None
    try:
        StockMovement.objects.bulk_create([
            StockMovement(shop=shop, product=product, variant=variant, variant_name=(variant.name if variant else '')[:80],
                          change=qty, stock_after=qty, reason=reason, user=actor)
            for product, variant, qty in rows if qty])
    except Exception:    # noqa: BLE001
        logger.exception('bulk stock log failed')
