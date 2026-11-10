# store/reports.py
"""
রিপোর্ট পেইজের সব হিসাব: সময় বাছাই (আজ, এই মাস, ...), আগের সময়ের সাথে তুলনা, বিক্রির ধারা, কোথা থেকে বিক্রি,
টাকা কীভাবে এসেছে, বেশি বিক্রি হওয়া প্রোডাক্ট ও ক্যাটাগরি, সেরা কাস্টমার, কখন বেশি বিক্রি, অনলাইন অর্ডারের
ডেলিভারি, স্টকের দাম আর বাকি — আর Excel ফাইল।

হিসাবের নিয়ম ড্যাশবোর্ডের মতোই (store/dashboard.py): বিক্রি = অর্ডারের মোট − ডেলিভারি চার্জ; লাভ = বিক্রি − VAT −
কেনা দাম; ফেরত আর বাতিল অর্ডার বিক্রিতে ধরা হয় না। দিন ধরা হয় ঢাকার সময়ে।
"""
import math
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.db.models import Count, DecimalField, ExpressionWrapper, F, OuterRef, Q, Subquery, Sum
from django.db.models.functions import ExtractHour, ExtractWeekDay, TruncDate, TruncMonth
from django.utils import timezone

from .dashboard import (BN_MONTHS, BN_MONTHS_SHORT, BN_WEEKDAYS_SHORT, ITEM_COST, NET_OF_VAT, SALE_VALUE, STATUS_LABELS,
                        _change, bn_date, bn_num, nice_ceiling, short_taka)
from .models import Customer, Order, OrderItem, Product, SalePayment, StorefrontPayment
from .pos import NOT_COUNTED, WALK_IN_PHONE

ZERO = Decimal('0')
MAX_DAYS = 366 * 3
PRESETS = [
    ('today', 'আজ'),
    ('yesterday', 'গতকাল'),
    ('7d', '৭ দিন'),
    ('30d', '৩০ দিন'),
    ('month', 'এই মাস'),
    ('last_month', 'গত মাস'),
    ('year', 'এই বছর'),
]
# চার্ট আর কার্ডে একই রং: দোকান নীল, ওয়েবসাইট কমলা, ফোন/ইনবক্স সবুজাভ (ক্যাটাগরির ক্রম, রং-অন্ধদের জন্যও আলাদা)
CHANNELS = [
    ('pos', 'দোকানে (POS)', '#2a78d6'),
    ('storefront', 'ওয়েবসাইট', '#eb6834'),
    ('dashboard', 'ফোন/ইনবক্স', '#1baf7a'),
]
CHANNEL_LABELS = {key: label for key, label, _color in CHANNELS}
PAYMENT_LABELS = dict(SalePayment.METHOD_CHOICES)
# Django-র ExtractWeekDay: ১ = রবিবার … ৭ = শনিবার; বাংলাদেশে সপ্তাহ শুরু শনিবার
WEEK_ORDER = [7, 1, 2, 3, 4, 5, 6]
WEEKDAY_NAMES = {7: 'শনি', 1: 'রবি', 2: 'সোম', 3: 'মঙ্গল', 4: 'বুধ', 5: 'বৃহঃ', 6: 'শুক্র'}
LINE_SALES = ExpressionWrapper(F('price') * F('quantity'), output_field=DecimalField(max_digits=14, decimal_places=2))


# ---------------------------------------------------------------- সময়
def bn_full(day):
    """১০ নভেম্বর ২০২৬"""
    return f'{bn_num(day.day)} {BN_MONTHS[day.month - 1]} {bn_num(day.year)}'


def range_label(start, end):
    if start == end:
        return f'{bn_date(start)} {bn_num(start.year)}'
    if start.year == end.year:
        return f'{bn_num(start.day)} {BN_MONTHS[start.month - 1]} – {bn_full(end)}'
    return f'{bn_full(start)} – {bn_full(end)}'


@dataclass
class Period:
    key: str
    start: date
    end: date
    prev_start: date
    prev_end: date

    @property
    def days(self):
        return (self.end - self.start).days + 1

    @property
    def label(self):
        return range_label(self.start, self.end)

    @property
    def prev_label(self):
        return range_label(self.prev_start, self.prev_end)


def _parse(value):
    try:
        return date.fromisoformat(str(value or '').strip())
    except ValueError:
        return None


def _same_day_in(year, month, day):
    return date(year, month, min(day, monthrange(year, month)[1]))


def resolve_period(params, today=None):
    """?period=month বা ?start=2026-11-01&end=2026-11-10 → Period (আগের সময়সহ, তুলনার জন্য)।"""
    today = today or timezone.localdate()
    key = params.get('period') or ('custom' if params.get('start') or params.get('end') else 'month')
    if key == 'custom':
        start = _parse(params.get('start')) or today.replace(day=1)
        end = _parse(params.get('end')) or today
        end = min(end, today)
        start = min(start, end)
        if (end - start).days > MAX_DAYS:
            start = end - timedelta(days=MAX_DAYS)
    elif key == 'today':
        start = end = today
    elif key == 'yesterday':
        start = end = today - timedelta(days=1)
    elif key in ('7d', '30d'):
        start, end = today - timedelta(days=int(key[:-1]) - 1), today
    elif key == 'last_month':
        end = today.replace(day=1) - timedelta(days=1)
        start = end.replace(day=1)
        prev_end = start - timedelta(days=1)
        return Period(key, start, end, prev_end.replace(day=1), prev_end)
    elif key == 'year':
        start, end = date(today.year, 1, 1), today
        return Period(key, start, end, date(today.year - 1, 1, 1), _same_day_in(today.year - 1, today.month, today.day))
    else:
        key = 'month'
        start, end = today.replace(day=1), today
        prev_start = (start - timedelta(days=1)).replace(day=1)
        return Period(key, start, end, prev_start, _same_day_in(prev_start.year, prev_start.month, today.day))
    length = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    return Period(key, start, end, prev_end - timedelta(days=length - 1), prev_end)


# ---------------------------------------------------------------- ছোট সাহায্য
def _orders(shop, start, end):
    return Order.objects.filter(shop=shop, created_at__date__gte=start, created_at__date__lte=end)


def _counted(shop, start, end):
    return _orders(shop, start, end).exclude(status__in=NOT_COUNTED)


def _pct(part, whole):
    part, whole = Decimal(part or 0), Decimal(whole or 0)
    return float(round(part * 100 / whole, 1)) if whole > 0 else 0.0


def _taka(value):
    return '৳' + bn_num(f'{Decimal(value or 0):,.0f}')


def bn_hour(hour):
    """২৪ ঘণ্টার সময় → "সকাল ১০টা", "সন্ধ্যা ৬টা"।"""
    if hour < 4:
        part = 'রাত'
    elif hour < 6:
        part = 'ভোর'
    elif hour < 12:
        part = 'সকাল'
    elif hour < 15:
        part = 'দুপুর'
    elif hour < 18:
        part = 'বিকাল'
    elif hour < 20:
        part = 'সন্ধ্যা'
    else:
        part = 'রাত'
    return f'{part} {bn_num(hour % 12 or 12)}টা'


def bn_time(moment):
    """১০ নভে · সকাল ১০:৩০"""
    local = timezone.localtime(moment)
    part = bn_hour(local.hour).split(' ')[0]
    return f'{bn_num(local.day)} {BN_MONTHS_SHORT[local.month - 1]} · {part} {bn_num(local.hour % 12 or 12)}:{bn_num(f"{local.minute:02d}")}'


# ---------------------------------------------------------------- সারাংশ
def summary(shop, start, end):
    orders = _orders(shop, start, end)
    counted = orders.exclude(status__in=NOT_COUNTED)
    agg = counted.aggregate(
        sales=Sum(SALE_VALUE), net=Sum(NET_OF_VAT), orders=Count('id'), discount=Sum('discount'), vat=Sum('vat_amount'),
        delivery=Sum('delivery_charge'),
        **{f'sales_{key}': Sum(SALE_VALUE, filter=Q(source=key)) for key, *_rest in CHANNELS},
        **{f'orders_{key}': Count('id', filter=Q(source=key)) for key, *_rest in CHANNELS},
    )
    items = OrderItem.objects.filter(order__in=counted)
    item_agg = items.aggregate(cost=Sum(ITEM_COST), units=Sum('quantity'))
    lost = orders.filter(status__in=NOT_COUNTED).aggregate(
        returned=Count('id', filter=Q(status='Returned')), cancelled=Count('id', filter=Q(status='Cancelled')),
        value=Sum(SALE_VALUE))
    sales = agg['sales'] or ZERO
    profit = (agg['net'] or ZERO) - (item_agg['cost'] or ZERO)
    count = agg['orders'] or 0
    return {
        'sales': sales,
        'profit': profit,
        'profit_negative': profit < 0,
        'profit_abs': abs(profit),
        'margin': _pct(profit, sales),
        'orders': count,
        'aov': (sales / count) if count else ZERO,
        'units': item_agg['units'] or 0,
        'cost': item_agg['cost'] or ZERO,
        'discount': agg['discount'] or ZERO,
        'vat': agg['vat'] or ZERO,
        'delivery': agg['delivery'] or ZERO,
        'returned': lost['returned'] or 0,
        'cancelled': lost['cancelled'] or 0,
        'lost_value': lost['value'] or ZERO,
        'missing_cost': items.filter(cost_price__lte=0, price__gt=0).values('product_id').distinct().count(),
        'channels': [{'key': key, 'label': label, 'color': color,
                      'sales': agg[f'sales_{key}'] or ZERO, 'orders': agg[f'orders_{key}'] or 0,
                      'share': _pct(agg[f'sales_{key}'], sales)} for key, label, color in CHANNELS],
    }


def compare(current, previous):
    return {key: _change(current[key], previous[key]) for key in ('sales', 'profit', 'orders', 'aov', 'units')}


# ---------------------------------------------------------------- বিক্রির ধারা
def _bucket_label(day, monthly, span_years):
    if monthly:
        return BN_MONTHS_SHORT[day.month - 1] + (f' {bn_num(day.year % 100)}' if span_years else '')
    return f'{bn_num(day.day)} {BN_MONTHS_SHORT[day.month - 1]}'


def trend(shop, start, end):
    """প্রতিদিনের (বা ৬২ দিনের বেশি হলে প্রতি মাসের) বিক্রি — দোকান/ওয়েবসাইট/ফোন আলাদা, লাভ টুলটিপে।"""
    monthly = (end - start).days + 1 > 62
    counted = _counted(shop, start, end)
    trunc = TruncMonth('created_at') if monthly else TruncDate('created_at')
    rows = (counted.annotate(b=trunc).values('b')
            .annotate(count=Count('id'), net=Sum(NET_OF_VAT),
                      **{key: Sum(SALE_VALUE, filter=Q(source=key)) for key, *_rest in CHANNELS}))
    costs = (OrderItem.objects.filter(order__in=counted)
             .annotate(b=TruncMonth('order__created_at') if monthly else TruncDate('order__created_at'))
             .values('b').annotate(cost=Sum(ITEM_COST)))

    def key_of(value):
        if hasattr(value, 'hour'):          # TruncMonth দেয় datetime
            value = timezone.localtime(value).date() if timezone.is_aware(value) else value.date()
        return value.replace(day=1) if monthly else value

    data = {key_of(r['b']): r for r in rows}
    cost_by = {key_of(r['b']): r['cost'] or ZERO for r in costs}
    buckets = []
    day = start.replace(day=1) if monthly else start
    while day <= end:
        buckets.append(day)
        day = (day.replace(day=28) + timedelta(days=4)).replace(day=1) if monthly else day + timedelta(days=1)

    today = timezone.localdate()
    span_years = start.year != end.year
    bars = []
    for day in buckets:
        row = data.get(day, {})
        parts = {key: row.get(key) or ZERO for key, *_rest in CHANNELS}
        total = sum(parts.values(), ZERO)
        bars.append({'day': day, 'parts': parts, 'total': total, 'count': row.get('count', 0),
                     'profit': (row.get('net') or ZERO) - cost_by.get(day, ZERO),
                     'is_today': not monthly and day == today})
    ceiling = nice_ceiling(max((bar['total'] for bar in bars), default=ZERO))
    n = len(bars)
    step = 1 if n <= 14 else math.ceil(n / 8)
    for index, bar in enumerate(bars):
        bar['segments'] = [{'key': key, 'color': color, 'label': label, 'value': bar['parts'][key],
                            'pct': (round(max(float(bar['parts'][key]) * 100 / ceiling, 1.5), 2)
                                    if ceiling and bar['parts'][key] > 0 else 0)}
                           for key, label, color in reversed(CHANNELS)]     # উপর থেকে নিচে: ফোন, ওয়েবসাইট, দোকান
        bar['top_pct'] = round(sum(s['pct'] for s in bar['segments']), 2)
        bar['label'] = (('আজ' if bar['is_today'] else (BN_WEEKDAYS_SHORT[bar['day'].weekday()] if n <= 7 else
                                                       _bucket_label(bar['day'], monthly, span_years)))
                        if (n - 1 - index) % step == 0 else '')
        bar['title'] = (f"{BN_MONTHS[bar['day'].month - 1]} {bn_num(bar['day'].year)}" if monthly
                        else bn_date(bar['day']))
        bar['align'] = 'l' if index < n * 0.2 else ('r' if index >= n * 0.8 else '')
    best = max(bars, key=lambda b: b['total'], default=None)
    return {
        'bars': bars, 'monthly': monthly, 'dense': n > 20,
        'grid': [short_taka(ceiling), short_taka(ceiling / 2), '0'] if ceiling else [],
        'empty': not ceiling,
        'best': best if best and best['total'] > 0 else None,
    }


# ---------------------------------------------------------------- টাকা কীভাবে এসেছে
def payment_methods(shop, start, end):
    rows = (SalePayment.objects.filter(shop=shop, created_at__date__gte=start, created_at__date__lte=end)
            .values('method').annotate(sale=Sum('amount', filter=Q(kind=SalePayment.SALE)),
                                       due=Sum('amount', filter=Q(kind=SalePayment.DUE_COLLECTION)),
                                       refund=Sum('amount', filter=Q(kind=SalePayment.REFUND))))
    result = []
    for row in rows:
        # ফেরতের টাকা মাইনাস হিসেবে রাখা (store/pos.py), তাই যোগ করলেই হাতে থাকা টাকা
        refund = row['refund'] or ZERO
        net = (row['sale'] or ZERO) + (row['due'] or ZERO) + refund
        if net or refund:
            result.append({'label': PAYMENT_LABELS.get(row['method'], row['method']), 'amount': net,
                           'due': row['due'] or ZERO, 'refund': abs(refund)})
    online = (StorefrontPayment.objects.filter(shop=shop, status=StorefrontPayment.STATUS_COMPLETED,
                                               completed_at__date__gte=start, completed_at__date__lte=end)
              .aggregate(total=Sum('amount'), fee=Sum('fee_amount')))
    if online['total']:
        result.append({'label': 'ওয়েবসাইটে অনলাইন পেমেন্ট', 'amount': online['total'], 'due': ZERO,
                       'refund': ZERO, 'fee': online['fee'] or ZERO})
    result.sort(key=lambda r: r['amount'], reverse=True)
    total = sum((r['amount'] for r in result), ZERO)
    top = max((r['amount'] for r in result), default=ZERO)
    for r in result:
        r['share'] = _pct(r['amount'], total)
        r['bar'] = _pct(r['amount'], top)
        notes = []
        if r['due']:
            notes.append(f"বাকি আদায় {_taka(r['due'])}")
        if r['refund']:
            notes.append(f"ফেরত দেওয়া {_taka(r['refund'])}")
        if r.get('fee'):
            notes.append(f"PayStation ফি {_taka(r['fee'])}")
        r['note'] = ' · '.join(notes)
    return {'rows': result, 'total': total}


# ---------------------------------------------------------------- প্রোডাক্ট, ক্যাটাগরি, কাস্টমার
def product_rows(shop, start, end, limit=None):
    rows = (OrderItem.objects.filter(order__in=_counted(shop, start, end), quantity__gt=0)
            .values('product_id', 'product__name', 'product__category__name')
            .annotate(qty=Sum('quantity'), sales=Sum(LINE_SALES), cost=Sum(ITEM_COST))
            .order_by('-sales', '-qty'))
    rows = list(rows[:limit] if limit else rows)
    products = Product.objects.in_bulk([r['product_id'] for r in rows]) if limit else {}
    top = max((r['sales'] or ZERO for r in rows), default=ZERO)
    for r in rows:
        r['sales'] = r['sales'] or ZERO
        r['cost'] = r['cost'] or ZERO
        r['profit'] = r['sales'] - r['cost']
        r['margin'] = _pct(r['profit'], r['sales'])
        r['bar'] = _pct(r['sales'], top)
        r['product'] = products.get(r['product_id'])
        r['no_cost'] = r['cost'] <= 0
    return rows


def categories(shop, start, end, limit=8):
    rows = list(OrderItem.objects.filter(order__in=_counted(shop, start, end), quantity__gt=0)
                .values('product__category__name')
                .annotate(qty=Sum('quantity'), sales=Sum(LINE_SALES), cost=Sum(ITEM_COST)).order_by('-sales'))
    total = sum((r['sales'] or ZERO for r in rows), ZERO)
    shown, rest = rows[:limit], rows[limit:]
    if rest:
        shown.append({'product__category__name': f'অন্যান্য ({bn_num(len(rest))}টা)',
                      'qty': sum(r['qty'] or 0 for r in rest), 'sales': sum((r['sales'] or ZERO for r in rest), ZERO),
                      'cost': sum((r['cost'] or ZERO for r in rest), ZERO)})
    for r in shown:
        r['name'] = r['product__category__name'] or 'ক্যাটাগরি ছাড়া'
        r['share'] = _pct(r['sales'], total)
        r['profit'] = (r['sales'] or ZERO) - (r['cost'] or ZERO)
    return shown


def customer_rows(shop, start, end, limit=None):
    counted = _counted(shop, start, end).exclude(customer__phone=WALK_IN_PHONE)
    rows = (counted.values('customer_id', 'customer__name', 'customer__phone')
            .annotate(orders=Count('id'), spent=Sum(SALE_VALUE)).order_by('-spent'))
    return list(rows[:limit] if limit else rows)


def customer_mix(shop, start, end):
    """এই সময়ে কেনা কাস্টমারদের কতজন নতুন (প্রথম অর্ডার এই সময়েই), কতজন আবার কিনেছেন।"""
    first_order = (Order.objects.filter(customer=OuterRef('pk')).exclude(status__in=NOT_COUNTED)
                   .order_by('created_at').values('created_at')[:1])
    ids = _counted(shop, start, end).exclude(customer__phone=WALK_IN_PHONE).values('customer_id')
    customers = (Customer.objects.filter(pk__in=ids).annotate(first=Subquery(first_order)))
    start_moment = timezone.make_aware(datetime.combine(start, datetime.min.time()))
    new = customers.filter(first__gte=start_moment).count()
    total = customers.count()
    walk_in = _counted(shop, start, end).filter(customer__phone=WALK_IN_PHONE).count()
    return {'total': total, 'new': new, 'returning': total - new, 'walk_in': walk_in,
            'returning_pct': _pct(total - new, total)}


# ---------------------------------------------------------------- কখন বেশি বিক্রি
def by_hour(shop, start, end):
    rows = {r['h']: r for r in _counted(shop, start, end).annotate(h=ExtractHour('created_at'))
            .values('h').annotate(sales=Sum(SALE_VALUE), count=Count('id'))}
    top = max((r['sales'] or ZERO for r in rows.values()), default=ZERO)
    hours = []
    for h in range(24):
        sales = (rows.get(h) or {}).get('sales') or ZERO
        hours.append({'hour': h, 'label': bn_hour(h), 'sales': sales, 'count': (rows.get(h) or {}).get('count', 0),
                      'pct': round(max(float(sales) * 100 / float(top), 3), 1) if top and sales > 0 else 0,
                      'tick': bn_hour(h) if h in (0, 6, 12, 18) else ''})
    best = max(hours, key=lambda x: x['sales'])
    return {'hours': hours, 'best': best if best['sales'] > 0 else None,
            'best_label': f"{best['label']} থেকে {bn_hour((best['hour'] + 1) % 24)}" if best['sales'] > 0 else ''}


def by_weekday(shop, start, end):
    rows = {r['d']: r for r in _counted(shop, start, end).annotate(d=ExtractWeekDay('created_at'))
            .values('d').annotate(sales=Sum(SALE_VALUE), count=Count('id'))}
    top = max((r['sales'] or ZERO for r in rows.values()), default=ZERO)
    days = []
    for d in WEEK_ORDER:
        sales = (rows.get(d) or {}).get('sales') or ZERO
        days.append({'label': WEEKDAY_NAMES[d], 'sales': sales, 'count': (rows.get(d) or {}).get('count', 0),
                     'pct': round(max(float(sales) * 100 / float(top), 3), 1) if top and sales > 0 else 0})
    best = max(days, key=lambda x: x['sales'])
    return {'days': days, 'best': best if best['sales'] > 0 else None}


# ---------------------------------------------------------------- অনলাইন অর্ডার, স্টক, বাকি
def online_delivery(shop, start, end):
    counts = dict(_orders(shop, start, end).exclude(source='pos').values_list('status').annotate(n=Count('id')))
    total = sum(counts.values())
    delivered, returned = counts.get('Delivered', 0), counts.get('Returned', 0)
    steps = []
    for status in ('Pending', 'Confirmed', 'Shipped', 'Delivered', 'Returned', 'Cancelled'):
        label, tone = STATUS_LABELS[status]
        steps.append({'status': status, 'label': label, 'tone': tone, 'count': counts.get(status, 0),
                      'pct': _pct(counts.get(status, 0), total)})
    return {'total': total, 'steps': steps, 'delivered': delivered, 'returned': returned,
            'success': _pct(delivered, delivered + returned) if delivered + returned else None}


def stock_value(shop):
    products = Product.objects.filter(shop=shop, is_active=True)
    in_stock = products.filter(stock_quantity__gt=0)
    agg = in_stock.aggregate(
        units=Sum('stock_quantity'),
        cost=Sum(ExpressionWrapper(F('stock_quantity') * F('cost_price'), output_field=DecimalField(max_digits=16, decimal_places=2))),
        value=Sum(ExpressionWrapper(F('stock_quantity') * F('price'), output_field=DecimalField(max_digits=16, decimal_places=2))))
    cost, value = agg['cost'] or ZERO, agg['value'] or ZERO
    return {'products': products.count(), 'units': agg['units'] or 0, 'cost': cost, 'value': value,
            'margin': value - cost, 'low': products.filter(stock_quantity__lt=5, stock_quantity__gt=0).count(),
            'out': products.filter(stock_quantity__lte=0).count(),
            'missing_cost': in_stock.filter(cost_price__lte=0).count()}


def dues(shop, start, end):
    from .dashboard import pos_dues
    outstanding = pos_dues(shop)
    collected = (SalePayment.objects.filter(shop=shop, kind=SalePayment.DUE_COLLECTION, created_at__date__gte=start,
                                            created_at__date__lte=end).aggregate(n=Sum('amount'))['n'] or ZERO)
    given = (_counted(shop, start, end).filter(source='pos', advance_paid__lt=F('total_amount'))
             .aggregate(n=Sum(F('total_amount') - F('advance_paid')))['n'] or ZERO)
    return {'outstanding': outstanding['amount'], 'people': outstanding['people'], 'collected': collected,
            'given': given}


def order_rows(shop, start, end, limit=None):
    orders = (_orders(shop, start, end).select_related('customer')
              .annotate(cost=Sum(ExpressionWrapper(F('items__cost_price') * F('items__quantity'),
                                                   output_field=DecimalField(max_digits=14, decimal_places=2))),
                        units=Sum('items__quantity'))
              .order_by('-created_at'))
    orders = list(orders[:limit] if limit else orders)
    for order in orders:
        order.when = bn_time(order.created_at)
        order.sale_value = order.total_amount - order.delivery_charge
        counted = order.status not in NOT_COUNTED
        order.profit = (order.sale_value - order.vat_amount - (order.cost or ZERO)) if counted else None
        order.walk_in = order.customer.phone == WALK_IN_PHONE
        order.channel = CHANNEL_LABELS.get(order.source, order.source)
        order.status_label, order.status_tone = STATUS_LABELS.get(order.status, (order.status, 'muted'))
        if order.source == 'pos' and order.status == 'Delivered':
            order.status_label = 'বাকি আছে' if order.due_amount > 0 else 'বিক্রি হয়েছে'
            order.status_tone = 'confirmed' if order.due_amount > 0 else 'done'
    return orders


# ---------------------------------------------------------------- Excel
def build_workbook(shop, period):
    """সারাংশ, অর্ডার, প্রোডাক্ট, কাস্টমার — চারটা শিট।"""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    head_font = Font(bold=True, color='FFFFFF')
    head_fill = PatternFill('solid', fgColor='0F172A')
    money = '#,##0.00'

    def sheet(ws, headers, rows, widths, money_cols=()):
        ws.append(headers)
        for cell in ws[1]:
            cell.font, cell.fill = head_font, head_fill
            cell.alignment = Alignment(vertical='center')
        for row in rows:
            ws.append(row)
        for index, width in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(index)].width = width
        for col in money_cols:
            for cell in ws.iter_cols(min_col=col, max_col=col, min_row=2):
                for c in cell:
                    c.number_format = money
        ws.freeze_panes = 'A2'

    s = summary(shop, period.start, period.end)
    wb = Workbook()
    ws = wb.active
    ws.title = 'সারাংশ'
    ws.append([shop.name])
    ws['A1'].font = Font(bold=True, size=14)
    ws.append([f'রিপোর্ট: {period.label}'])
    ws.append([])
    rows = [('বিক্রি (ডেলিভারি চার্জ বাদে)', s['sales']), ('লাভ (কেনা দাম, ছাড় আর VAT বাদে)', s['profit']),
            ('লাভের হার %', s['margin']), ('অর্ডার ও বিল', s['orders']), ('গড় বিল', s['aov']),
            ('বিক্রি হওয়া প্রোডাক্ট (পিস)', s['units']), ('ছাড় দেওয়া', s['discount']), ('VAT', s['vat']),
            ('ডেলিভারি চার্জ নেওয়া', s['delivery']), ('ফেরত অর্ডার', s['returned']), ('বাতিল অর্ডার', s['cancelled'])]
    rows += [(f"{c['label']} — বিক্রি", c['sales']) for c in s['channels']]
    for label, value in rows:
        ws.append([label, float(value) if isinstance(value, Decimal) else value])
    ws.column_dimensions['A'].width = 40
    ws.column_dimensions['B'].width = 18
    for row in ws.iter_rows(min_row=4, min_col=2, max_col=2):
        for c in row:
            c.number_format = money

    orders = order_rows(shop, period.start, period.end)
    sheet(wb.create_sheet('অর্ডার'),
          ['তারিখ', 'অর্ডার নং', 'কাস্টমার', 'মোবাইল', 'কোথা থেকে', 'অবস্থা', 'পিস', 'ছাড়', 'ডেলিভারি চার্জ', 'VAT',
           'মোট', 'বিক্রি', 'কেনা দাম', 'লাভ'],
          [[timezone.localtime(o.created_at).strftime('%Y-%m-%d %I:%M %p'), f'ORD-{o.id}',
            'দোকানের কাস্টমার' if o.walk_in else o.customer.name, '' if o.walk_in else o.customer.phone, o.channel,
            o.status_label, o.units or 0, float(o.discount), float(o.delivery_charge), float(o.vat_amount),
            float(o.total_amount), float(o.sale_value), float(o.cost or 0),
            float(o.profit) if o.profit is not None else None] for o in orders],
          [20, 12, 24, 14, 16, 16, 7, 10, 14, 10, 12, 12, 12, 12], money_cols=range(8, 15))
    sheet(wb.create_sheet('প্রোডাক্ট'),
          ['প্রোডাক্ট', 'ক্যাটাগরি', 'বিক্রি (পিস)', 'বিক্রি (টাকা)', 'কেনা দাম', 'লাভ', 'লাভের হার %'],
          [[r['product__name'], r['product__category__name'] or '', r['qty'], float(r['sales']), float(r['cost']),
            float(r['profit']), r['margin']] for r in product_rows(shop, period.start, period.end)],
          [34, 18, 12, 14, 14, 14, 12], money_cols=(4, 5, 6))
    sheet(wb.create_sheet('কাস্টমার'),
          ['কাস্টমার', 'মোবাইল', 'অর্ডার', 'কিনেছেন (টাকা)'],
          [[r['customer__name'], r['customer__phone'], r['orders'], float(r['spent'] or 0)]
           for r in customer_rows(shop, period.start, period.end)],
          [28, 16, 10, 16], money_cols=(4,))
    return wb
