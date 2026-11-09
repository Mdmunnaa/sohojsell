# store/pos.py
"""
POS (দোকানে বিক্রি)-র হিসাব আর ডাটাবেসের কাজ। ভিউ (views_pos.py) শুধু অনুরোধ নেয়-দেয়।

নিয়ম:
- দাম সবসময় ডাটাবেস থেকে; শুধু দোকানের মালিক চাইলে লাইনের দাম বদলাতে পারেন (দামাদামি)।
- পুরো বিক্রি একসাথে হয় বা একদম হয় না (transaction); স্টক লক করে কমানো হয়।
- নগদে কাস্টমার বেশি দিলে ফেরত হিসাব হয়; পুরো টাকা না পেলে "বাকি" — তখন কাস্টমারের নাম-মোবাইল লাগে।
- প্রতিটা টাকার লেনদেন SalePayment-এ থাকে, তাই দিনশেষের ক্যাশ হিসাব মেলে।
"""
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


def _locked_pos_order(shop, order_id):
    order = Order.objects.select_for_update().filter(shop=shop, source='pos', pk=order_id).first()
    if order is None:
        raise POSError('বিক্রিটা পাওয়া যায়নি।')
    if order.status in NOT_COUNTED:
        raise POSError('এই বিক্রি আগেই পুরো ফেরত বা বাতিল হয়েছে।')
    return order


def default_refund_method(order):
    """যে মাধ্যমে টাকা এসেছিল (একটাই হলে), নাহলে নগদ।"""
    methods = {m for m, a in order.payments.filter(kind=SalePayment.SALE).values_list('method', 'amount') if a > 0}
    return methods.pop() if len(methods) == 1 else SalePayment.CASH


def _is_vat_inclusive(order, subtotal):
    return order.vat_amount > 0 and abs(order.total_amount - (subtotal - order.discount)) < CENT


def return_items(shop, user, order_id, items=None, method=None, reason=''):
    """
    বিক্রির কয়েকটা (বা সব) প্রোডাক্ট ফেরত।
    - items: [{'item_id', 'qty'}]; না দিলে যা আছে সব।
    - দাম কমে আনুপাতিক হারে (ছাড় আর VAT সহ)। কাস্টমারের বাকি থাকলে আগে বাকি কমে, তারপর টাকা ফেরত।
    - সব প্রোডাক্ট ফেরত হলে বিক্রিটা "Returned" (রিপোর্টে আর গোনা হয় না)।
    """
    from .models import SaleReturn, SaleReturnItem
    reason = (reason or '').strip()[:200]
    with transaction.atomic():
        order = _locked_pos_order(shop, order_id)
        order_items = {item.id: item for item in order.items.select_related('product').order_by('id')}
        if items is None:
            wanted = {item_id: item.quantity for item_id, item in order_items.items() if item.quantity > 0}
        else:
            wanted = {}
            for raw in items if isinstance(items, list) else []:
                try:
                    item_id, qty = int(raw.get('item_id')), int(raw.get('qty'))
                except (TypeError, ValueError, AttributeError):
                    raise POSError('ফেরতের তথ্য ঠিক নেই, আবার চেষ্টা করুন।')
                if qty <= 0:
                    continue
                if item_id not in order_items:
                    raise POSError('এই প্রোডাক্ট এই বিক্রিতে নেই।')
                wanted[item_id] = wanted.get(item_id, 0) + qty
        if not wanted:
            raise POSError('কোন প্রোডাক্ট কয়টা ফেরত নেবেন বেছে নিন।')
        for item_id, qty in wanted.items():
            item = order_items[item_id]
            if qty > item.quantity:
                raise POSError(f'"{item.product.name}" এই বিল থেকে সর্বোচ্চ {item.quantity}টা ফেরত নেওয়া যায়।')

        method = (method or default_refund_method(order)).lower()
        if method not in VALID_METHODS:
            raise POSError('টাকা ফেরতের মাধ্যমটা ঠিক নেই।')

        subtotal = sum((item.price * item.quantity for item in order_items.values()), ZERO)
        returned_sub = sum((order_items[i].price * q for i, q in wanted.items()), ZERO)
        everything = all(wanted.get(i, 0) == item.quantity for i, item in order_items.items())
        old_total = order.total_amount

        if everything:
            value = old_total
            refund = max(order.advance_paid, ZERO)
            order.advance_paid -= refund
            order.status = 'Returned'
        else:
            remaining_sub = subtotal - returned_sub
            ratio = remaining_sub / subtotal if subtotal else Decimal('1')
            inclusive = _is_vat_inclusive(order, subtotal)
            new_total = (old_total * ratio).quantize(CENT, rounding=ROUND_HALF_UP)
            new_discount = (order.discount * ratio).quantize(CENT, rounding=ROUND_HALF_UP)
            if inclusive:
                new_vat = (order.vat_amount * ratio).quantize(CENT, rounding=ROUND_HALF_UP)
            else:
                new_vat = max(new_total - (remaining_sub - new_discount), ZERO)
            value = old_total - new_total
            refund = max(order.advance_paid - new_total, ZERO)
            order.total_amount, order.discount, order.vat_amount = new_total, new_discount, new_vat
            order.advance_paid -= refund
            for item_id, qty in wanted.items():
                OrderItem.objects.filter(pk=item_id).update(quantity=F('quantity') - qty)

        for item_id, qty in wanted.items():
            Product.objects.filter(pk=order_items[item_id].product_id).update(
                stock_quantity=F('stock_quantity') + qty)

        cashier = user if getattr(user, 'is_authenticated', False) else None
        sale_return = SaleReturn.objects.create(
            shop=shop, order=order, full=everything, value=value, refund=refund,
            refund_method=method if refund > 0 else '', reason=reason, created_by=cashier)
        # প্রতিটা লাইনের ভাগ; শেষ লাইনে পয়সার গরমিল মিলিয়ে নেওয়া
        rows, assigned = [], ZERO
        pairs = list(wanted.items())
        for index, (item_id, qty) in enumerate(pairs):
            item = order_items[item_id]
            if index == len(pairs) - 1:
                share = value - assigned
            else:
                share = ((item.price * qty * value / returned_sub) if returned_sub else ZERO).quantize(
                    CENT, rounding=ROUND_HALF_UP)
            assigned += share
            rows.append(SaleReturnItem(sale_return=sale_return, product_id=item.product_id,
                                       product_name=item.product.name[:200], quantity=qty,
                                       unit_price=item.price, value=share))
        SaleReturnItem.objects.bulk_create(rows)
        if refund > 0:
            SalePayment.objects.create(shop=shop, order=order, method=method, amount=-refund,
                                       kind=SalePayment.REFUND, received_by=cashier)

        label = 'পুরো ফেরত' if everything else 'আংশিক ফেরত'
        note = f'{label}: ' + ', '.join(f'{order_items[i].product.name} ×{q}' for i, q in pairs)
        if reason:
            note += f' ({reason})'
        order.note = f'{order.note}\n{note}' if order.note else note
        order.save(update_fields=['status', 'note', 'total_amount', 'discount', 'vat_amount', 'advance_paid'])
    restocked = [{'id': order_items[i].product_id, 'qty': q} for i, q in wanted.items()]
    return order, sale_return, restocked


def return_sale(shop, user, order_id, reason=''):
    """পুরো বিক্রি ফেরত। ফেরত: (order, ফেরত দেওয়া টাকা)।"""
    order, sale_return, _restocked = return_items(shop, user, order_id, None, None, reason)
    return order, sale_return.refund


def sale_detail(shop, order_id):
    """ফেরতের পপআপের জন্য: প্রতিটা লাইনে কয়টা বাকি আছে আর একটা ফেরত দিলে বিল কত কমবে।"""
    order = (Order.objects.filter(shop=shop, source='pos', pk=order_id)
             .select_related('customer', 'served_by').first())
    if order is None:
        raise POSError('বিক্রিটা পাওয়া যায়নি।')
    items = list(order.items.select_related('product').order_by('id'))
    subtotal = sum((i.price * i.quantity for i in items), ZERO)
    factor = (order.total_amount / subtotal) if subtotal else ZERO
    return order, [{
        'item_id': i.id, 'product_id': i.product_id, 'name': i.product.name, 'qty': i.quantity,
        'price': i.price, 'unit_value': (i.price * factor).quantize(CENT, rounding=ROUND_HALF_UP),
    } for i in items if i.quantity > 0], default_refund_method(order)


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
    from .models import SaleReturn
    returns = SaleReturn.objects.filter(shop=shop, created_at__date=day)
    returns_agg = returns.aggregate(count=Count('id'), value=Sum('value'))
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
        'returned_count': returns_agg['count'] or 0,
        'returned_value': returns_agg['value'] or ZERO,
        'methods': methods,
        'cash_in_drawer': by_method[SalePayment.CASH]['net'],
        'total_received': sum((m['net'] for m in methods), ZERO),
        'cashiers': list(cashiers),
        'top_products': list(top),
    }
