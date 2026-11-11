"""প্রোডাক্টের রিভিউ: কাস্টমার দেয়, সেলার অনুমোদন দিলে (বা অটো চালু থাকলে) ওয়েবসাইটে দেখায়।"""
from django.db.models import Avg, Count, Q

from .models import OrderItem, ProductReview

BN_TO_EN = str.maketrans('০১২৩৪৫৬৭৮৯', '0123456789')
MAX_IMAGE_BYTES = 5 * 1024 * 1024


class ReviewError(ValueError):
    """কাস্টমারকে দেখানোর মতো বাংলা বার্তা।"""


def has_bought(shop, phone, product):
    """এই নম্বরে এই প্রোডাক্ট ডেলিভারি হয়েছে কিনা (যাচাই করা ক্রেতা)।"""
    if not phone:
        return False
    return OrderItem.objects.filter(order__shop=shop, order__customer__phone=phone, order__status='Delivered',
                                    product=product).exists()


def submit(shop, product, *, name, phone, rating, text, image=None):
    from accounts.forms import normalize_bd_mobile

    from .sf_lang import t           # কাস্টমার দেখে — দোকানের ভাষায়
    if not shop.reviews_enabled:
        raise ReviewError(t('এই দোকানে এখন রিভিউ নেওয়া হচ্ছে না।', shop))
    name = ' '.join(str(name or '').split())[:80]
    if len(name) < 2:
        raise ReviewError(t('আপনার নাম লিখুন।', shop))
    phone = normalize_bd_mobile(str(phone or ''))
    if not phone:
        raise ReviewError(t('সঠিক মোবাইল নম্বর দিন (০১ দিয়ে শুরু, ১১ সংখ্যা)।', shop))
    try:
        rating = int(str(rating or '').translate(BN_TO_EN))
    except ValueError:
        rating = 0
    if not 1 <= rating <= 5:
        raise ReviewError(t('১ থেকে ৫ তারা দিন।', shop))
    text = ' '.join(str(text or '').split())[:1000]
    if ProductReview.objects.filter(shop=shop, product=product, phone=phone).exists():
        raise ReviewError(t('এই নম্বর থেকে এই প্রোডাক্টে আগেই রিভিউ দেওয়া হয়েছে।', shop))
    if image is not None and image.size > MAX_IMAGE_BYTES:
        raise ReviewError(t('ছবিটা ৫ MB-এর ছোট হতে হবে।', shop))
    review = ProductReview(shop=shop, product=product, name=name, phone=phone, rating=rating, text=text,
                           verified=has_bought(shop, phone, product), is_approved=shop.reviews_auto_approve)
    if image is not None:
        from . import images
        main, _thumb, _size = images.product_versions(image)
        review.image = main if main is not None else image
    review.save()
    return review


def summary_for(products):
    """{product_id: {'avg': 4.6, 'count': 12}} — শুধু অনুমোদিত রিভিউ।"""
    ids = [p.id for p in products]
    if not ids:
        return {}
    rows = (ProductReview.objects.filter(product_id__in=ids, is_approved=True).values('product_id')
            .annotate(avg=Avg('rating'), count=Count('id')))
    return {r['product_id']: {'avg': round(float(r['avg']), 1), 'count': r['count']} for r in rows}


def attach(products):
    found = summary_for(products)
    for p in products:
        p.rating = found.get(p.id)
    return products


def approved_for(product, limit=None):
    rows = ProductReview.objects.filter(product=product, is_approved=True)
    return list(rows[:limit] if limit else rows)


def stars_breakdown(product):
    """৫ তারা কয়টা, ৪ তারা কয়টা... (ওয়েবসাইটে বার দেখাতে)।"""
    counts = dict(ProductReview.objects.filter(product=product, is_approved=True).values_list('rating')
                  .annotate(n=Count('id')))
    total = sum(counts.values())
    return [{'star': star, 'count': counts.get(star, 0),
             'pct': round(counts.get(star, 0) * 100 / total) if total else 0} for star in (5, 4, 3, 2, 1)]


def pending_count(shop):
    return ProductReview.objects.filter(shop=shop, is_approved=False).count()
