"""
কেনা, সাপ্লায়ার আর খরচের খাতা।

কেনা (Purchase) জমা হলে:
  - স্টক বাড়ে (সাইজ/রং হলে সেটারই — store/variants.py)
  - প্রোডাক্টের কেনা দাম গড় করে বসে: (আগের স্টক × আগের দাম + নতুন মাল × নতুন দাম) ÷ মোট স্টক
  - সাপ্লায়ার থাকলে যা দেওয়া হয়নি তা তার বাকিতে ওঠে
সাপ্লায়ারের বাকি = আগের বাকি (opening_due) + সব কেনা − সব পরিশোধ।
খরচ (Expense) রিপোর্টে পণ্যের লাভ থেকে বাদ গিয়ে নিট লাভ দেয়।
"""
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Count, F, Sum
from django.utils import timezone

from . import variants
from .models import (PAY_METHOD_CHOICES, Expense, Product, ProductVariant, Purchase, PurchaseItem, Supplier,
                     SupplierPayment)

ZERO = Decimal('0')
CENT = Decimal('0.01')
MAX_LINES = 100
MAX_QTY = 100000
METHODS = dict(PAY_METHOD_CHOICES)
EXPENSE_LABELS = dict(Expense.CATEGORY_CHOICES)
BN_TO_EN = str.maketrans('০১২৩৪৫৬৭৮৯', '0123456789')


class LedgerError(ValueError):
    """সেলারকে দেখানোর মতো বাংলা বার্তা।"""


# ---------------------------------------------------------------- ছোট সাহায্য
def to_money(value, label, *, allow_zero=True):
    text = str(value if value is not None else '').translate(BN_TO_EN).replace(',', '').strip()
    if not text:
        number = ZERO
    else:
        try:
            number = Decimal(text)
        except InvalidOperation:
            raise LedgerError(f'{label} সংখ্যায় লিখুন।')
    if not number.is_finite() or number < 0 or number > Decimal('99999999'):
        raise LedgerError(f'{label} ঠিক নেই।')
    if number == 0 and not allow_zero:
        raise LedgerError(f'{label} লিখুন।')
    return number.quantize(CENT, rounding=ROUND_HALF_UP)


def to_date(value, today=None):
    """ফর্মের তারিখ; ফাঁকা বা ভুল হলে আজ, ভবিষ্যতের তারিখ হলে আজ।"""
    today = today or timezone.localdate()
    try:
        day = date.fromisoformat(str(value or '').strip())
    except ValueError:
        return today
    return min(day, today)


def to_method(value):
    return value if value in METHODS else 'cash'


# ---------------------------------------------------------------- সাপ্লায়ার
def clean_supplier(shop, name, phone='', address='', note='', opening_due=None, *, exclude_id=None):
    name = ' '.join(str(name or '').split())[:120]
    if not name:
        raise LedgerError('সাপ্লায়ারের নাম লিখুন।')
    same = Supplier.objects.filter(shop=shop, name__iexact=name)
    if exclude_id:
        same = same.exclude(pk=exclude_id)
    if same.exists():
        raise LedgerError(f'"{name}" নামে একজন সাপ্লায়ার আগে থেকেই আছে।')
    return {'name': name, 'phone': str(phone or '').translate(BN_TO_EN).strip()[:20],
            'address': str(address or '').strip()[:200], 'note': str(note or '').strip()[:300],
            'opening_due': to_money(opening_due, 'আগের বাকি')}


def supplier_rows(shop):
    """সব সাপ্লায়ার, সাথে মোট কেনা, মোট পরিশোধ আর বাকি।"""
    bought = dict(Purchase.objects.filter(shop=shop, supplier__isnull=False).values_list('supplier_id')
                  .annotate(total=Sum('total_amount')))
    counts = dict(Purchase.objects.filter(shop=shop, supplier__isnull=False).values_list('supplier_id')
                  .annotate(n=Count('id')))
    paid = dict(SupplierPayment.objects.filter(shop=shop).values_list('supplier_id').annotate(total=Sum('amount')))
    rows = []
    for supplier in Supplier.objects.filter(shop=shop):
        supplier.bought = bought.get(supplier.id) or ZERO
        supplier.paid = paid.get(supplier.id) or ZERO
        supplier.purchase_count = counts.get(supplier.id, 0)
        supplier.due = supplier.opening_due + supplier.bought - supplier.paid
        rows.append(supplier)
    return rows


def supplier_due(supplier):
    bought = supplier.purchases.aggregate(t=Sum('total_amount'))['t'] or ZERO
    paid = supplier.payments.aggregate(t=Sum('amount'))['t'] or ZERO
    return supplier.opening_due + bought - paid


def total_supplier_due(shop):
    return sum((s.due for s in supplier_rows(shop) if s.due > 0), ZERO)


@transaction.atomic
def pay_supplier(shop, user, supplier, amount, method='cash', paid_on=None, note=''):
    supplier = Supplier.objects.select_for_update().get(pk=supplier.pk, shop=shop)
    amount = to_money(amount, 'টাকার পরিমাণ', allow_zero=False)
    due = supplier_due(supplier)
    if amount > due:
        raise LedgerError(f'{supplier.name}-এর বাকি আছে ৳{due:,.0f}। এর বেশি দেওয়া যাবে না।')
    return SupplierPayment.objects.create(
        shop=shop, supplier=supplier, amount=amount, method=to_method(method), paid_on=to_date(paid_on),
        note=str(note or '').strip()[:200], created_by=user if getattr(user, 'is_authenticated', False) else None)


def supplier_ledger(supplier):
    """সাপ্লায়ারের খাতা: কেনা আর পরিশোধ তারিখ ধরে, প্রতিটার পরে বাকি কত দাঁড়াল।"""
    entries = [{'day': p.purchased_on, 'order': (p.purchased_on, 0, p.id), 'kind': 'purchase', 'purchase': p,
                'text': f'মাল কেনা #{p.id}' + (f' · চালান {p.invoice_no}' if p.invoice_no else ''),
                'plus': p.total_amount, 'minus': ZERO} for p in supplier.purchases.all()]
    entries += [{'day': p.paid_on, 'order': (p.paid_on, 1, p.id), 'kind': 'payment', 'payment': p,
                 'text': ('কেনার সময় দেওয়া' if p.purchase_id else 'বাকি পরিশোধ') + f' · {METHODS.get(p.method, p.method)}'
                         + (f' · {p.note}' if p.note else ''),
                 'plus': ZERO, 'minus': p.amount} for p in supplier.payments.all()]
    entries.sort(key=lambda e: e['order'])
    balance = supplier.opening_due
    for entry in entries:
        balance += entry['plus'] - entry['minus']
        entry['balance'] = balance
    entries.reverse()
    return entries, balance


# ---------------------------------------------------------------- কেনা
def lines_from_post(post):
    """item_key[] / item_qty[] / item_cost[] → [{'key', 'qty', 'cost'}] (ফাঁকা সারি বাদ)।"""
    keys, qtys, costs = post.getlist('item_key[]'), post.getlist('item_qty[]'), post.getlist('item_cost[]')
    lines = []
    for index, raw_key in enumerate(keys):
        if not str(raw_key).strip():
            continue
        try:
            key = int(raw_key)
            qty = int(str(qtys[index] if index < len(qtys) else '').translate(BN_TO_EN).strip() or 0)
        except ValueError:
            raise LedgerError('পরিমাণ সংখ্যায় লিখুন।')
        if not 0 < qty <= MAX_QTY:
            raise LedgerError('প্রতিটা মালের পরিমাণ ১ বা তার বেশি দিন।')
        lines.append({'key': key, 'qty': qty,
                      'cost': to_money(costs[index] if index < len(costs) else '', 'কেনা দাম')})
    if not lines:
        raise LedgerError('অন্তত একটা প্রোডাক্ট বেছে নিন।')
    if len(lines) > MAX_LINES:
        raise LedgerError(f'এক চালানে সর্বোচ্চ {MAX_LINES}টা সারি।')
    return lines


def _average_cost(old_stock, old_cost, added_qty, added_value):
    """নতুন গড় কেনা দাম। আগের দাম জানা না থাকলে (০) শুধু নতুন মালের দামই ধরা হয়।"""
    old_stock = max(int(old_stock or 0), 0)
    if not old_cost or old_cost <= 0:
        old_stock = 0
    total_qty = old_stock + added_qty
    if total_qty <= 0:
        return old_cost or ZERO
    return ((old_stock * (old_cost or ZERO) + added_value) / total_qty).quantize(CENT, rounding=ROUND_HALF_UP)


@transaction.atomic
def create_purchase(shop, user, *, lines, supplier=None, purchased_on=None, invoice_no='', paid=None,
                    method='cash', note=''):
    """
    মাল কেনা জমা করে। lines = lines_from_post()-এর ফল।
    supplier না থাকলে পুরো টাকা দেওয়া ধরা হয় (বাকি রাখতে হলে সাপ্লায়ার লাগবে)।
    """
    chosen = variants.resolve(shop, [line['key'] for line in lines], lock=True)
    per_product, rows, total = {}, [], ZERO
    for line in lines:
        item = chosen.get(line['key'])
        if item is None:
            raise LedgerError('একটা প্রোডাক্ট আর পাওয়া যাচ্ছে না, পেইজটা রিফ্রেশ করুন।')
        if item.needs_choice:
            raise LedgerError(f'"{item.name}"-এর কোন সাইজ/রং কেনা হলো সেটা বেছে নিন।')
        value = line['cost'] * line['qty']
        total += value
        rows.append((item, line['qty'], line['cost']))
        bucket = per_product.setdefault(item.product.id, {'product': item.product, 'qty': 0, 'value': ZERO})
        bucket['qty'] += line['qty']
        bucket['value'] += value

    paid = total if paid in (None, '') else to_money(paid, 'দেওয়া টাকা')
    if paid > total:
        raise LedgerError(f'মোট দাম ৳{total:,.0f}; এর বেশি দেওয়া টাকা লেখা যাবে না।')
    if supplier is None and paid < total:
        raise LedgerError('বাকিতে কিনলে সাপ্লায়ার বেছে নিন, নাহলে কার কাছে বাকি সেটা থাকবে না।')

    day = to_date(purchased_on)
    creator = user if getattr(user, 'is_authenticated', False) else None
    purchase = Purchase.objects.create(
        shop=shop, supplier=supplier, purchased_on=day, invoice_no=str(invoice_no or '').strip()[:40],
        total_amount=total, paid_amount=paid, note=str(note or '').strip()[:300], created_by=creator)
    PurchaseItem.objects.bulk_create([
        PurchaseItem(purchase=purchase, product=item.product, variant=item.variant, name=item.name[:290],
                     quantity=qty, unit_cost=cost) for item, qty, cost in rows])

    for bucket in per_product.values():
        product = bucket['product']
        new_cost = _average_cost(product.stock_quantity, product.cost_price, bucket['qty'], bucket['value'])
        Product.objects.filter(pk=product.pk).update(cost_price=new_cost)
    for item, qty, _cost in rows:
        variants.give_back(item.product.id, item.variant.id if item.variant else None, qty)

    if supplier is not None and paid > 0:
        SupplierPayment.objects.create(shop=shop, supplier=supplier, purchase=purchase, amount=paid,
                                       method=to_method(method), paid_on=day, created_by=creator)
    return purchase


@transaction.atomic
def delete_purchase(shop, purchase):
    """ভুল এন্ট্রি মুছে ফেলা: স্টক কমে যায়, গড় কেনা দাম আগের জায়গায় ফেরে। মাল বিক্রি হয়ে গেলে মোছা যায় না।"""
    purchase = Purchase.objects.select_for_update().get(pk=purchase.pk, shop=shop)
    items = list(purchase.items.all())
    products = {p.id: p for p in Product.objects.select_for_update()
                .filter(shop=shop, id__in=[i.product_id for i in items if i.product_id])}
    variant_rows = {v.id: v for v in ProductVariant.objects.select_for_update()
                    .filter(product__shop=shop, id__in=[i.variant_id for i in items if i.variant_id])}
    needed, per_product = {}, {}
    for item in items:
        product = products.get(item.product_id)
        if product is None:
            continue            # প্রোডাক্টটাই মুছে ফেলা হয়েছে
        holder = variant_rows.get(item.variant_id) if item.variant_id else product
        if holder is None:
            continue            # সাইজ/রংটা মুছে ফেলা হয়েছে
        key = ('v', holder.id) if item.variant_id else ('p', holder.id)
        needed[key] = needed.get(key, 0) + item.quantity
        if holder.stock_quantity < needed[key]:
            raise LedgerError(f'"{item.name}" থেকে কিছু বিক্রি হয়ে গেছে (স্টকে আছে {holder.stock_quantity}টা), '
                              'তাই এই কেনাটা মোছা যাবে না।')
        bucket = per_product.setdefault(product.id, {'product': product, 'qty': 0, 'value': ZERO})
        bucket['qty'] += item.quantity
        bucket['value'] += item.unit_cost * item.quantity

    for (kind, holder_id), qty in needed.items():
        if kind == 'v':
            ProductVariant.objects.filter(pk=holder_id).update(stock_quantity=F('stock_quantity') - qty)
            Product.objects.filter(pk=variant_rows[holder_id].product_id).update(
                stock_quantity=F('stock_quantity') - qty)
        else:
            Product.objects.filter(pk=holder_id).update(stock_quantity=F('stock_quantity') - qty)
    for bucket in per_product.values():
        product = bucket['product']
        left = product.stock_quantity - bucket['qty']
        if left > 0:
            old = (product.stock_quantity * product.cost_price - bucket['value']) / left
            if old > 0:
                Product.objects.filter(pk=product.pk).update(cost_price=old.quantize(CENT, rounding=ROUND_HALF_UP))
    purchase.delete()           # সাথে কেনার সময়ের পেমেন্টও মোছে (CASCADE)


def purchase_summary(shop, start, end):
    rows = Purchase.objects.filter(shop=shop, purchased_on__gte=start, purchased_on__lte=end)
    agg = rows.aggregate(total=Sum('total_amount'), count=Count('id'))
    paid = SupplierPayment.objects.filter(shop=shop, paid_on__gte=start, paid_on__lte=end).aggregate(t=Sum('amount'))
    cash_bought = rows.filter(supplier__isnull=True).aggregate(t=Sum('total_amount'))['t'] or ZERO
    return {'total': agg['total'] or ZERO, 'count': agg['count'] or 0,
            'paid': (paid['t'] or ZERO) + cash_bought, 'supplier_due': total_supplier_due(shop)}


def product_options(shop):
    """কেনার ফর্মের ড্রপডাউন: প্রোডাক্ট আর সাইজ/রং (স্টক শেষ হলেও, বন্ধ প্রোডাক্ট বাদে)।"""
    options = []
    for product in Product.objects.filter(shop=shop, is_active=True).prefetch_related('variants').order_by('name'):
        if product.has_variants:
            options += [{'key': -v.id, 'name': f'{product.name} ({v.name})', 'cost': float(product.cost_price),
                         'stock': v.stock_quantity, 'barcode': v.barcode} for v in product.variants.all()]
        else:
            options.append({'key': product.id, 'name': product.name, 'cost': float(product.cost_price),
                            'stock': product.stock_quantity, 'barcode': product.barcode or ''})
    return options


# ---------------------------------------------------------------- খরচ
def add_expense(shop, user, *, category, amount, title='', spent_on=None, method='cash'):
    if category not in EXPENSE_LABELS:
        category = 'other'
    return Expense.objects.create(
        shop=shop, category=category, title=' '.join(str(title or '').split())[:120],
        amount=to_money(amount, 'খরচের পরিমাণ', allow_zero=False), spent_on=to_date(spent_on),
        method=to_method(method), created_by=user if getattr(user, 'is_authenticated', False) else None)


def expense_summary(shop, start, end):
    """মোট খরচ আর কোন খাতে কত (বেশি থেকে কম)।"""
    rows = (Expense.objects.filter(shop=shop, spent_on__gte=start, spent_on__lte=end)
            .values('category').annotate(total=Sum('amount'), count=Count('id')).order_by('-total'))
    total = sum((r['total'] for r in rows), ZERO)
    top = max((r['total'] for r in rows), default=ZERO)
    return {'total': total,
            'rows': [{'key': r['category'], 'label': EXPENSE_LABELS.get(r['category'], r['category']),
                      'total': r['total'], 'count': r['count'],
                      'share': float(round(r['total'] * 100 / total, 1)) if total else 0.0,
                      'bar': float(round(r['total'] * 100 / top, 1)) if top else 0.0} for r in rows]}
