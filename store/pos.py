# store/pos.py
"""
POS (দোকানে বিক্রি)-র হিসাব আর ডাটাবেসের কাজ। ভিউ (views_pos.py) শুধু অনুরোধ নেয়-দেয়।

নিয়ম:
- দাম সবসময় ডাটাবেস থেকে; শুধু দোকানের মালিক চাইলে লাইনের দাম বদলাতে পারেন (দামাদামি)।
- পুরো বিক্রি একসাথে হয় বা একদম হয় না (transaction); স্টক লক করে কমানো হয়।
- নগদে কাস্টমার বেশি দিলে ফেরত হিসাব হয়; পুরো টাকা না পেলে "বাকি" — তখন কাস্টমারের নাম-মোবাইল লাগে।
- প্রতিটা টাকার লেনদেন SalePayment-এ থাকে, তাই দিনশেষের ক্যাশ হিসাব মেলে।
"""
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.db.models import Count, F, Q, Sum

from .models import Customer, Order, OrderItem, Product, SalePayment, Shop

ZERO = Decimal('0')
CENT = Decimal('0.01')
WALK_IN_PHONE = '00000000000'
WALK_IN_NAME = 'Walk-in Customer'
POS_ADDRESS = 'POS / In-store'
MAX_LINES = 300
MAX_QTY = 100000
NOT_COUNTED = ('Returned', 'Cancelled')

METHOD_TO_ORDER_LABEL = {
    SalePayment.CASH: 'Paid', SalePayment.BKASH: 'bKash', SalePayment.NAGAD: 'Nagad',
    SalePayment.CARD: 'Card', SalePayment.BANK: 'Paid',
}
VALID_METHODS = {key for key, _label in SalePayment.METHOD_CHOICES}


class POSError(Exception):
    """কাস্টমার/ক্যাশিয়ারকে দেখানোর মতো বাংলা ভুলের বার্তা।"""


def money(value):
    """যেকোনো ইনপুট → দুই দশমিকের Decimal; ভুল হলে POSError।"""
    try:
        amount = Decimal(str(value if value not in (None, '') else 0))
    except (InvalidOperation, ValueError, TypeError):
        raise POSError('টাকার অঙ্কটা ঠিকমতো লিখুন।')
    if not amount.is_finite():
        raise POSError('টাকার অঙ্কটা ঠিকমতো লিখুন।')
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def normalize_phone(raw):
    from accounts.forms import normalize_bd_mobile
    return normalize_bd_mobile(raw) if raw else None


# ============================================================
# হিসাব (ডাটাবেস ছাড়া — টেস্ট করা সহজ)
# ============================================================
def compute_totals(line_totals, discount_type, discount_value, vat_percent, vat_mode):
    """
    (subtotal, discount, vat, total)।
    discount_type: 'amount' (টাকা) বা 'percent'। ছাড় কখনো subtotal-এর বেশি হয় না।
    VAT exclusive হলে (দাম − ছাড়)-এর উপর যোগ হয়; inclusive হলে দামের ভেতর থেকে আলাদা করে দেখানো হয়।
    """
    subtotal = sum((money(x) for x in line_totals), ZERO)
    value = money(discount_value)
    if value < 0:
        raise POSError('ছাড় ঋণাত্মক হতে পারে না।')
    if discount_type == 'percent':
        if value > 100:
            raise POSError('ছাড় ১০০%-এর বেশি হতে পারে না।')
        discount = (subtotal * value / 100).quantize(CENT, rounding=ROUND_HALF_UP)
    else:
        discount = min(value, subtotal)
    taxable = subtotal - discount
    pct = money(vat_percent)
    vat = ZERO
    total = taxable
    if pct > 0:
        if vat_mode == Shop.VAT_INCLUSIVE:
            vat = (taxable - taxable / (1 + pct / 100)).quantize(CENT, rounding=ROUND_HALF_UP)
        else:
            vat = (taxable * pct / 100).quantize(CENT, rounding=ROUND_HALF_UP)
            total = taxable + vat
    return subtotal, discount, vat, total


def split_payments(total, payments):
    """
    payments: [{'method', 'amount', 'reference'}] — নগদের amount = কাস্টমার যত দিয়েছে।
    ফেরত দেয়: (প্রযোজ্য লেনদেনের তালিকা, নগদ পাওয়া, ফেরত, মোট পরিশোধ, বাকি)।
    """
    cash_given = ZERO
    others = []
    rows = []
    for raw in payments or []:
        if not isinstance(raw, dict):
            raise POSError('পেমেন্টের তথ্য ঠিক নেই।')
        method = str(raw.get('method') or '').strip().lower()
        if method not in VALID_METHODS:
            raise POSError('পেমেন্টের মাধ্যমটা ঠিক নেই।')
        amount = money(raw.get('amount'))
        if amount < 0:
            raise POSError('পেমেন্টের অঙ্ক ঋণাত্মক হতে পারে না।')
        rows.append([method, amount, bool(raw.get('full')), str(raw.get('reference') or '')])
    # "full" = বাকি পুরোটা এই মাধ্যমে (স্ক্রিনের হিসাব আর সার্ভারের হিসাবে পয়সার গরমিল হলেও কম পড়বে না)
    full_rows = [row for row in rows if row[2]]
    if len(full_rows) > 1:
        raise POSError('শুধু একটা মাধ্যমে "বাকি পুরোটা" দেওয়া যায়।')
    if full_rows:
        others_sum = sum((row[1] for row in rows if not row[2]), ZERO)
        full_rows[0][1] = max(full_rows[0][1], total - others_sum, ZERO)
    for method, amount, _full, reference in rows:
        if amount == 0:
            continue
        if method == SalePayment.CASH:
            cash_given += amount
        else:
            others.append((method, amount, reference.strip()[:60]))
    non_cash = sum((amount for _m, amount, _r in others), ZERO)
    if non_cash > total:
        raise POSError('bKash/কার্ডে বিলের চেয়ে বেশি টাকা ধরা হয়েছে।')
    cash_applied = min(cash_given, total - non_cash)
    change = cash_given - cash_applied
    applied = list(others)
    if cash_applied > 0:
        applied.insert(0, (SalePayment.CASH, cash_applied, ''))
    paid = non_cash + cash_applied
    return applied, cash_given, change, paid, total - paid


def order_payment_label(applied, due):
    if due > 0:
        return 'Credit'
    methods = {method for method, _a, _r in applied}
    if len(methods) > 1:
        return 'Mixed'
    if methods:
        return METHOD_TO_ORDER_LABEL[methods.pop()]
    return 'Paid'     # ১০০% ছাড়ে বিল শূন্য


# ============================================================
# বিক্রি
# ============================================================
def _customer_for(shop, name, phone, need_real_customer):
    name = ' '.join((name or '').split())[:150]
    phone = normalize_phone(phone)
    if need_real_customer and not (phone and name):
        raise POSError('বাকি রাখতে কাস্টমারের নাম আর মোবাইল নম্বর দিন।')
    if not phone:
        walk_in = Customer.objects.filter(shop=shop, phone=WALK_IN_PHONE).order_by('id').first()
        return walk_in or Customer.objects.create(shop=shop, phone=WALK_IN_PHONE, name=WALK_IN_NAME,
                                                  address=POS_ADDRESS)
    customer = Customer.objects.filter(shop=shop, phone=phone).order_by('-id').first()
    if customer is None:
        return Customer.objects.create(shop=shop, phone=phone, name=name or 'কাস্টমার', address=POS_ADDRESS)
    if name and customer.name != name:
        customer.name = name
        customer.save(update_fields=['name'])
    return customer


def _clean_lines(raw_items):
    if not isinstance(raw_items, list) or not raw_items:
        raise POSError('কার্টে কোনো প্রোডাক্ট নেই।')
    if len(raw_items) > MAX_LINES:
        raise POSError(f'এক বিলে সর্বোচ্চ {MAX_LINES}টা প্রোডাক্ট।')
    merged = {}
    for raw in raw_items:
        try:
            product_id, qty = int(raw.get('id')), int(raw.get('qty'))
        except (TypeError, ValueError, AttributeError):
            raise POSError('কার্টের তথ্য ঠিক নেই, পেইজটা রিফ্রেশ করুন।')
        if not 0 < qty <= MAX_QTY:
            raise POSError('পরিমাণ ১ বা তার বেশি হতে হবে।')
        line = merged.setdefault(product_id, {'qty': 0, 'price': None})
        line['qty'] += qty
        if raw.get('price') not in (None, ''):
            line['price'] = raw.get('price')
    return merged


def create_sale(shop, user, payload, *, can_override_price=False):
    """
    POS বিক্রি জমা করে (Order, OrderItem, SalePayment, স্টক কমানো)। ফেরত: (order, created)।
    একই pos_ref দুবার এলে (নেট কেটে আবার পাঠালে) আগের বিক্রিটাই ফেরত দেয়।
    """
    ref = str(payload.get('ref') or '')[:40]
    if ref:
        existing = Order.objects.filter(shop=shop, pos_ref=ref).first()
        if existing:
            return existing, False
    try:
        with transaction.atomic():
            return _create_sale(shop, user, payload, ref, can_override_price), True
    except IntegrityError:
        existing = Order.objects.filter(shop=shop, pos_ref=ref).first() if ref else None
        if existing:
            return existing, False
        raise


def _create_sale(shop, user, payload, ref, can_override_price):
    lines = _clean_lines(payload.get('items'))
    products = {p.id: p for p in Product.objects.select_for_update()
                .filter(shop=shop, id__in=lines.keys()).order_by('id')}
    if len(products) != len(lines):
        raise POSError('কিছু প্রোডাক্ট আর পাওয়া যাচ্ছে না, পেইজটা রিফ্রেশ করুন।')

    priced = []
    for product_id, line in lines.items():
        product = products[product_id]
        if not product.is_active:
            raise POSError(f'"{product.name}" এখন বিক্রি বন্ধ।')
        if product.stock_quantity < line['qty']:
            raise POSError(f'"{product.name}" স্টকে আছে মাত্র {product.stock_quantity}টা।')
        price = product.price
        if can_override_price and line['price'] is not None:
            price = money(line['price'])
            if price < 0:
                raise POSError('দাম ঋণাত্মক হতে পারে না।')
        priced.append((product, line['qty'], price))

    discount_info = payload.get('discount') or {}
    subtotal, discount, vat, total = compute_totals(
        [price * qty for _p, qty, price in priced], discount_info.get('type'), discount_info.get('value'),
        shop.pos_vat_percent, shop.pos_vat_mode)
    applied, cash_given, change, paid, due = split_payments(total, payload.get('payments'))
    if due > 0 and not payload.get('allow_due'):
        raise POSError(f'আরও ৳{due} নেওয়া বাকি। বাকিতে বিক্রি করতে "বাকি রাখুন" বেছে নিন।')

    customer_info = payload.get('customer') or {}
    customer = _customer_for(shop, customer_info.get('name'), customer_info.get('phone'),
                             need_real_customer=due > 0)
    cashier = user if getattr(user, 'is_authenticated', False) else None
    order = Order.objects.create(
        shop=shop, customer=customer, source='pos', status='Delivered', delivery_charge=0,
        discount=discount, vat_amount=vat, total_amount=total, advance_paid=paid,
        payment_method=order_payment_label(applied, due), cash_received=cash_given, change_given=change,
        served_by=cashier, pos_ref=ref, note=str(payload.get('note') or '').strip()[:500] or None,
    )
    OrderItem.objects.bulk_create([
        OrderItem(order=order, product=product, quantity=qty, price=price, cost_price=product.cost_price)
        for product, qty, price in priced
    ])
    for product, qty, _price in priced:
        Product.objects.filter(pk=product.pk).update(stock_quantity=F('stock_quantity') - qty)
    SalePayment.objects.bulk_create([
        SalePayment(shop=shop, order=order, method=method, amount=amount, reference=reference,
                    kind=SalePayment.SALE, received_by=cashier)
        for method, amount, reference in applied
    ])
    return order


# ============================================================
# কাস্টমার, বাকি আদায়, ফেরত
# ============================================================
def _due_orders(shop, customer_ids):
    return (Order.objects.filter(shop=shop, source='pos', customer_id__in=customer_ids)
            .exclude(status__in=NOT_COUNTED).filter(advance_paid__lt=F('total_amount')))


def customer_summary(shop, phone):
    phone = normalize_phone(phone)
    if not phone:
        return None
    customers = list(Customer.objects.filter(shop=shop, phone=phone).order_by('-id'))
    if not customers:
        return {'found': False, 'phone': phone}
    ids = [c.id for c in customers]
    orders = Order.objects.filter(shop=shop, customer_id__in=ids).exclude(status__in=NOT_COUNTED)
    stats = orders.aggregate(count=Count('id'), spent=Sum('total_amount'))
    due = _due_orders(shop, ids).aggregate(due=Sum(F('total_amount') - F('advance_paid')))['due'] or ZERO
    last = orders.order_by('-created_at').values_list('created_at', flat=True).first()
    return {
        'found': True, 'phone': phone, 'name': customers[0].name,
        'orders': stats['count'] or 0, 'spent': stats['spent'] or ZERO, 'due': due, 'last_visit': last,
    }


def collect_due(shop, user, phone, amount, method, reference=''):
    """কাস্টমারের পুরনো বাকি থেকে আগেরটা আগে শোধ। ফেরত: (আদায়, এখনো বাকি)।"""
    phone = normalize_phone(phone)
    amount = money(amount)
    if not phone:
        raise POSError('কাস্টমারের মোবাইল নম্বর দিন।')
    if amount <= 0:
        raise POSError('কত টাকা আদায় হলো লিখুন।')
    if method not in VALID_METHODS:
        raise POSError('পেমেন্টের মাধ্যমটা ঠিক নেই।')
    ids = list(Customer.objects.filter(shop=shop, phone=phone).values_list('id', flat=True))
    with transaction.atomic():
        orders = list(_due_orders(shop, ids).select_for_update().order_by('created_at', 'id'))
        total_due = sum((o.total_amount - o.advance_paid for o in orders), ZERO)
        if total_due <= 0:
            raise POSError('এই কাস্টমারের কোনো বাকি নেই।')
        if amount > total_due:
            raise POSError(f'বাকি আছে মাত্র ৳{total_due}।')
        remaining = amount
        cashier = user if getattr(user, 'is_authenticated', False) else None
        for order in orders:
            if remaining <= 0:
                break
            take = min(order.total_amount - order.advance_paid, remaining)
            Order.objects.filter(pk=order.pk).update(advance_paid=F('advance_paid') + take)
            SalePayment.objects.create(shop=shop, order=order, method=method, amount=take,
                                       reference=(reference or '')[:60], kind=SalePayment.DUE_COLLECTION,
                                       received_by=cashier)
            remaining -= take
    return amount, total_due - amount


def return_sale(shop, user, order_id, reason=''):
    """পুরো বিক্রি ফেরত: স্টক ফেরত, পাওয়া টাকা ফেরত (একই মাধ্যমে), অর্ডার "Returned"।"""
    with transaction.atomic():
        order = (Order.objects.select_for_update()
                 .filter(shop=shop, source='pos', pk=order_id).first())
        if order is None:
            raise POSError('বিক্রিটা পাওয়া যায়নি।')
        if order.status in NOT_COUNTED:
            raise POSError('এই বিক্রি আগেই ফেরত বা বাতিল হয়েছে।')
        for item in order.items.all():
            Product.objects.filter(pk=item.product_id).update(stock_quantity=F('stock_quantity') + item.quantity)
        net = defaultdict(lambda: ZERO)
        for method, amount in order.payments.values_list('method', 'amount'):
            net[method] += amount
        cashier = user if getattr(user, 'is_authenticated', False) else None
        refunds = [SalePayment(shop=shop, order=order, method=method, amount=-amount, kind=SalePayment.REFUND,
                               received_by=cashier)
                   for method, amount in net.items() if amount > 0]
        SalePayment.objects.bulk_create(refunds)
        order.status = 'Returned'
        note = f'ফেরত{": " + reason.strip()[:200] if reason and reason.strip() else ""}'
        order.note = f'{order.note}\n{note}' if order.note else note
        order.save(update_fields=['status', 'note'])
    return order, sum((-r.amount for r in refunds), ZERO)


# ============================================================
# রিপোর্ট
# ============================================================
def sales_on(shop, day):
    return (Order.objects.filter(shop=shop, source='pos', created_at__date=day)
            .select_related('customer', 'served_by').order_by('-created_at'))


def day_summary(shop, day):
    """দিনশেষের হিসাব: বিক্রি, ছাড়, VAT, ফেরত, বাকি, মাধ্যম অনুযায়ী টাকা, ড্রয়ারে নগদ।"""
    sales = Order.objects.filter(shop=shop, source='pos', created_at__date=day)
    kept = sales.exclude(status__in=NOT_COUNTED)
    totals = kept.aggregate(count=Count('id'), net=Sum('total_amount'), discount=Sum('discount'),
                            vat=Sum('vat_amount'))
    items = OrderItem.objects.filter(order__in=kept)
    gross = items.aggregate(v=Sum(F('price') * F('quantity')))['v'] or ZERO
    qty = items.aggregate(v=Sum('quantity'))['v'] or 0

    payments = SalePayment.objects.filter(shop=shop, created_at__date=day)
    by_method = {key: {'label': label, 'sale': ZERO, 'due': ZERO, 'refund': ZERO, 'net': ZERO}
                 for key, label in SalePayment.METHOD_CHOICES}
    for row in payments.values('method', 'kind').annotate(total=Sum('amount')):
        bucket = by_method.setdefault(row['method'], {'label': row['method'], 'sale': ZERO, 'due': ZERO,
                                                      'refund': ZERO, 'net': ZERO})
        bucket[row['kind']] = bucket.get(row['kind'], ZERO) + row['total']
        bucket['net'] += row['total']
    methods = [dict(key=key, **value) for key, value in by_method.items() if any(value[k] for k in
                                                                                 ('sale', 'due', 'refund'))]

    sale_paid = (SalePayment.objects.filter(order__in=kept, kind=SalePayment.SALE)
                 .aggregate(v=Sum('amount'))['v'] or ZERO)
    returned = sales.filter(status='Returned')
    cashiers = (kept.values('served_by__name', 'served_by__phone_number')
                .annotate(count=Count('id'), total=Sum('total_amount')).order_by('-total'))
    top = (items.values('product__name').annotate(qty=Sum('quantity'), amount=Sum(F('price') * F('quantity')))
           .order_by('-qty')[:5])
    return {
        'day': day,
        'count': totals['count'] or 0,
        'items_sold': qty,
        'gross': gross,
        'discount': totals['discount'] or ZERO,
        'vat': totals['vat'] or ZERO,
        'net': totals['net'] or ZERO,
        'due_given': (totals['net'] or ZERO) - sale_paid,
        'due_collected': payments.filter(kind=SalePayment.DUE_COLLECTION).aggregate(v=Sum('amount'))['v'] or ZERO,
        'refunded': -(payments.filter(kind=SalePayment.REFUND).aggregate(v=Sum('amount'))['v'] or ZERO),
        'returned_count': returned.count(),
        'methods': methods,
        'cash_in_drawer': by_method[SalePayment.CASH]['net'],
        'total_received': sum((m['net'] for m in methods), ZERO),
        'cashiers': list(cashiers),
        'top_products': list(top),
    }
