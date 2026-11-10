"""
প্রোডাক্টের সাইজ/রং (ভ্যারিয়েন্ট): কার্টে যা বিক্রি হয় সেটা চেনা, স্টক কমানো-বাড়ানো, ফর্ম থেকে সেভ।

কার্টে (POS, ওয়েবসাইট, অর্ডার ফর্ম) প্রতিটা জিনিসের একটাই নম্বর থাকে:
  ধনাত্মক  → সাধারণ প্রোডাক্টের id
  ঋণাত্মক → ভ্যারিয়েন্টের id (যেমন -12 = ProductVariant #12)
ভ্যারিয়েন্ট থাকা প্রোডাক্টের stock_quantity সব ভ্যারিয়েন্টের যোগফল — তাই পুরনো সব লিস্ট-রিপোর্ট আগের মতোই চলে।
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import F, Sum

from .models import Product, ProductVariant

MAX_VARIANTS = 60


class VariantError(ValueError):
    """সেলারকে দেখানোর মতো বাংলা বার্তা।"""


@dataclass
class Sellable:
    product: Product
    variant: ProductVariant = None

    @property
    def key(self):
        return -self.variant.id if self.variant else self.product.id

    @property
    def name(self):
        return f'{self.product.name} ({self.variant.name})' if self.variant else self.product.name

    @property
    def variant_name(self):
        return self.variant.name if self.variant else ''

    @property
    def price(self):
        return self.variant.sell_price if self.variant else self.product.price

    @property
    def stock(self):
        return self.variant.stock_quantity if self.variant else self.product.stock_quantity

    @property
    def cost_price(self):
        return self.product.cost_price

    @property
    def needs_choice(self):
        """ভ্যারিয়েন্ট আছে অথচ কোনটা সেটা বলা হয়নি।"""
        return self.variant is None and self.product.has_variants


def resolve(shop, keys, *, lock=False):
    """কার্টের নম্বরগুলো → {key: Sellable}। যেটা এই দোকানের না বা মুছে গেছে সেটা বাদ পড়ে।"""
    keys = {int(k) for k in keys}
    product_ids = {k for k in keys if k > 0}
    variant_ids = {-k for k in keys if k < 0}
    variants = ProductVariant.objects.filter(product__shop=shop, id__in=variant_ids)
    if lock:
        variants = variants.select_for_update().order_by('id')
    variants = list(variants)
    products = Product.objects.filter(shop=shop, id__in=product_ids | {v.product_id for v in variants})
    if lock:
        products = products.select_for_update().order_by('id')
    products = {p.id: p for p in products}
    found = {pid: Sellable(products[pid]) for pid in product_ids if pid in products}
    for variant in variants:
        variant.product = products[variant.product_id]
        found[-variant.id] = Sellable(variant.product, variant)
    return found


def take(sellable, qty):
    """বিক্রি হলে স্টক কমায় (ভ্যারিয়েন্ট হলে দুই জায়গাতেই)।"""
    if sellable.variant:
        ProductVariant.objects.filter(pk=sellable.variant.pk).update(stock_quantity=F('stock_quantity') - qty)
    Product.objects.filter(pk=sellable.product.pk).update(stock_quantity=F('stock_quantity') - qty)


def give_back(product_id, variant_id, qty):
    """ফেরত বা অর্ডার মুছলে স্টক ফেরত। ভ্যারিয়েন্টটা মুছে গিয়ে থাকলে প্রোডাক্টের মোট স্টক আবার মেলানো হয়।"""
    if variant_id and ProductVariant.objects.filter(pk=variant_id, product_id=product_id).update(
            stock_quantity=F('stock_quantity') + qty):
        Product.objects.filter(pk=product_id).update(stock_quantity=F('stock_quantity') + qty)
    elif Product.objects.filter(pk=product_id, has_variants=True).exists():
        sync_stock(product_id)
    else:
        Product.objects.filter(pk=product_id).update(stock_quantity=F('stock_quantity') + qty)


def sync_stock(product_id):
    """প্রোডাক্টের has_variants আর মোট স্টক ভ্যারিয়েন্ট থেকে মিলিয়ে নেয়।"""
    agg = ProductVariant.objects.filter(product_id=product_id).aggregate(total=Sum('stock_quantity'))
    if agg['total'] is None:
        Product.objects.filter(pk=product_id).update(has_variants=False)
    else:
        Product.objects.filter(pk=product_id).update(has_variants=True, stock_quantity=agg['total'])


def _number(value, label, *, whole=False, blank_ok=False):
    text = str(value if value is not None else '').strip()
    for bn, en in zip('০১২৩৪৫৬৭৮৯', '0123456789'):
        text = text.replace(bn, en)
    if not text:
        if blank_ok:
            return None
        return 0 if whole else Decimal('0')
    try:
        number = int(text) if whole else Decimal(text)
    except (ValueError, InvalidOperation):
        raise VariantError(f'{label} সংখ্যায় লিখুন।')
    if number < 0:
        raise VariantError(f'{label} ঋণাত্মক হতে পারে না।')
    return number


def rows_from_post(post):
    """ফর্মের variant_id[] / variant_name[] / variant_price[] / variant_stock[] → পরিষ্কার সারি।"""
    ids, names = post.getlist('variant_id[]'), post.getlist('variant_name[]')
    prices, stocks = post.getlist('variant_price[]'), post.getlist('variant_stock[]')
    rows, seen = [], set()
    for index, raw_name in enumerate(names):
        name = ' '.join(raw_name.split())[:80]
        if not name:
            continue
        if name.lower() in seen:
            raise VariantError(f'"{name}" দুবার লেখা হয়েছে।')
        seen.add(name.lower())
        raw_id = ids[index] if index < len(ids) else ''
        rows.append({
            'id': int(raw_id) if str(raw_id).isdigit() else None,
            'name': name,
            'price': _number(prices[index] if index < len(prices) else '', f'"{name}"-এর দাম', blank_ok=True),
            'stock': _number(stocks[index] if index < len(stocks) else '', f'"{name}"-এর স্টক', whole=True),
        })
    if len(rows) > MAX_VARIANTS:
        raise VariantError(f'এক প্রোডাক্টে সর্বোচ্চ {MAX_VARIANTS}টা সাইজ/রং রাখা যায়।')
    return rows


@transaction.atomic
def save_rows(product, rows):
    """ফর্মের সারি অনুযায়ী ভ্যারিয়েন্ট বানায়/বদলায়/মোছে, তারপর প্রোডাক্টের মোট স্টক মেলায়।"""
    existing = {v.id: v for v in product.variants.select_for_update()}
    keep = {row['id'] for row in rows if row['id'] in existing}
    ProductVariant.objects.filter(pk__in=set(existing) - keep).delete()
    # দুটো ভ্যারিয়েন্টের নাম অদলবদল হলে unique constraint-এ না আটকাতে আগে সাময়িক নাম
    for row in rows:
        if row['id'] in keep and existing[row['id']].name != row['name']:
            ProductVariant.objects.filter(pk=row['id']).update(name=f'~{row["id"]}')
    for position, row in enumerate(rows):
        variant = existing[row['id']] if row['id'] in keep else ProductVariant(product=product)
        variant.name, variant.price = row['name'], row['price']
        variant.stock_quantity, variant.position = row['stock'], position
        variant.save()
    sync_stock(product.pk)
    product.refresh_from_db(fields=['has_variants', 'stock_quantity'])
