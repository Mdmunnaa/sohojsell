# store/dashboard.py
"""
সেলারের ড্যাশবোর্ডের হিসাব: আজকের বিক্রি-লাভ, গত ৭/৩০ দিনের চার্ট, এখন যা করতে হবে,
সাম্প্রতিক অর্ডার, স্টক কম, বেশি বিক্রি আর নতুন দোকানের সেটআপের ধাপ।

"বিক্রি" = অর্ডারের মোট টাকা থেকে ডেলিভারি চার্জ বাদে (ওটা কুরিয়ারের)। POS-এ ডেলিভারি চার্জ নেই,
তাই POS-এর দিনশেষের "নিট বিক্রি"-র সাথে মিলে যায়। ফেরত আর বাতিল অর্ডার ধরা হয় না।
"""
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum
from django.db.models.functions import TruncDate
from django.urls import reverse
from django.utils import timezone

from . import couriers
from .models import Banner, Order, OrderItem, PageView, Product
from .pos import NOT_COUNTED, WALK_IN_PHONE

ZERO = Decimal('0')
LOW_STOCK = 5
CHART_RANGES = (7, 30)
BN_DIGITS = str.maketrans('0123456789', '০১২৩৪৫৬৭৮৯')
# date.weekday(): সোমবার = 0
BN_WEEKDAYS = ['সোমবার', 'মঙ্গলবার', 'বুধবার', 'বৃহস্পতিবার', 'শুক্রবার', 'শনিবার', 'রবিবার']
BN_WEEKDAYS_SHORT = ['সোম', 'মঙ্গল', 'বুধ', 'বৃহঃ', 'শুক্র', 'শনি', 'রবি']
BN_MONTHS = ['জানুয়ারি', 'ফেব্রুয়ারি', 'মার্চ', 'এপ্রিল', 'মে', 'জুন', 'জুলাই', 'আগস্ট', 'সেপ্টেম্বর',
             'অক্টোবর', 'নভেম্বর', 'ডিসেম্বর']
BN_MONTHS_SHORT = ['জানু', 'ফেব্রু', 'মার্চ', 'এপ্রি', 'মে', 'জুন', 'জুলা', 'আগ', 'সেপ্টে', 'অক্টো', 'নভে', 'ডিসে']

STATUS_LABELS = {
    'Pending': ('নতুন', 'new'),
    'Confirmed': ('কনফার্ম', 'confirmed'),
    'Shipped': ('পথে আছে', 'shipped'),
    'Delivered': ('ডেলিভারি হয়েছে', 'done'),
    'Returned': ('ফেরত', 'bad'),
    'Cancelled': ('বাতিল', 'bad'),
}
SOURCE_LABELS = {'pos': 'দোকানে', 'storefront': 'ওয়েবসাইট', 'dashboard': 'ম্যানুয়াল'}

SALE_VALUE = ExpressionWrapper(F('total_amount') - F('delivery_charge'),
                               output_field=DecimalField(max_digits=14, decimal_places=2))
NET_OF_VAT = ExpressionWrapper(F('total_amount') - F('delivery_charge') - F('vat_amount'),
                               output_field=DecimalField(max_digits=14, decimal_places=2))
ITEM_COST = ExpressionWrapper(F('cost_price') * F('quantity'),
                              output_field=DecimalField(max_digits=14, decimal_places=2))


def bn_num(value):
    return str(value).translate(BN_DIGITS)


def bn_date(day, weekday=True):
    """মঙ্গলবার, ১০ নভেম্বর"""
    text = f'{bn_num(day.day)} {BN_MONTHS[day.month - 1]}'
    return f'{BN_WEEKDAYS[day.weekday()]}, {text}' if weekday else text


def bn_ago(moment, now=None):
    """অর্ডার কতক্ষণ আগে এসেছে: এইমাত্র / ১০ মিনিট আগে / ৩ ঘণ্টা আগে / গতকাল / ৫ নভেম্বর।"""
    now = now or timezone.now()
    seconds = max(int((now - moment).total_seconds()), 0)
    if seconds < 60:
        return 'এইমাত্র'
    if seconds < 3600:
        return f'{bn_num(seconds // 60)} মিনিট আগে'
    local = timezone.localtime(moment).date()
    today = timezone.localtime(now).date()
    if local == today:
        return f'{bn_num(seconds // 3600)} ঘণ্টা আগে'
    if local == today - timedelta(days=1):
        return 'গতকাল'
    return bn_date(local, weekday=False)


def greeting(now=None):
    hour = timezone.localtime(now or timezone.now()).hour
    if 5 <= hour < 12:
        return 'শুভ সকাল'
    if 12 <= hour < 16:
        return 'শুভ দুপুর'
    if 16 <= hour < 18:
        return 'শুভ বিকাল'
    if 18 <= hour < 20:
        return 'শুভ সন্ধ্যা'
    return 'স্বাগতম'


def short_taka(value):
    """চার্টের পাশের দাগ: 800, 12 হাজার, 1.5 লাখ, 2 কোটি।"""
    value = float(value or 0)
    for size, word in ((10_000_000, 'কোটি'), (100_000, 'লাখ'), (1_000, 'হাজার')):
        if value >= size:
            number = value / size
            text = f'{number:.1f}'.rstrip('0').rstrip('.')
            return f'{text} {word}'
    return f'{value:.0f}'


def nice_ceiling(value):
    """চার্টের সবচেয়ে উঁচু দাগ: 3,740 → 4,000; 12,300 → 15,000।"""
    value = float(value or 0)
    if value <= 0:
        return 0
    exponent = 10 ** (len(str(int(value))) - 1)
    for step in (1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if value <= step * exponent:
            return step * exponent
    return 10 * exponent


def _change(today_value, yesterday_value):
    """গতকালের তুলনায় কত % বাড়ল/কমল। গতকাল শূন্য হলে তুলনা হয় না।"""
    today_value, yesterday_value = Decimal(today_value or 0), Decimal(yesterday_value or 0)
    if yesterday_value <= 0:
        return None
    pct = int(((today_value - yesterday_value) * 100 / yesterday_value).quantize(Decimal('1')))
    if pct == 0:
        return {'dir': 'flat', 'text': '০%'}
    if pct >= 900:          # ৪৯৭৮৭%-এর চেয়ে "৫০০ গুণ" পড়তে সহজ
        times = (today_value / yesterday_value).quantize(Decimal('1'))
        return {'dir': 'up', 'text': f'{bn_num(f"{times:,}")} গুণ'}
    return {'dir': 'up' if pct > 0 else 'down', 'text': f'{bn_num(abs(pct))}%'}


def _daily_sales(shop, start, end):
    """{date: {'pos', 'online', 'count'}} — দিন অনুযায়ী বিক্রি (ঢাকার সময়ে)।"""
    rows = (Order.objects.filter(shop=shop, created_at__date__gte=start, created_at__date__lte=end)
            .exclude(status__in=NOT_COUNTED)
            .annotate(day=TruncDate('created_at'))
            .values('day')
            .annotate(pos=Sum(SALE_VALUE, filter=Q(source='pos')),
                      online=Sum(SALE_VALUE, filter=~Q(source='pos')),
                      count=Count('id')))
    return {row['day']: {'pos': row['pos'] or ZERO, 'online': row['online'] or ZERO, 'count': row['count']}
            for row in rows}


def sales_chart(shop, today, days):
    start = today - timedelta(days=days - 1)
    daily = _daily_sales(shop, start, today)
    bars = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        row = daily.get(day, {'pos': ZERO, 'online': ZERO, 'count': 0})
        bars.append({'day': day, 'pos': row['pos'], 'online': row['online'], 'count': row['count'],
                     'total': row['pos'] + row['online']})
    peak = max((bar['total'] for bar in bars), default=ZERO)
    ceiling = nice_ceiling(peak)
    every = 1 if days <= 7 else 5
    for index, bar in enumerate(bars):
        is_today = bar['day'] == today
        bar['is_today'] = is_today
        bar['title'] = 'আজ' if is_today else bn_date(bar['day'])
        bar['full_date'] = bn_date(bar['day'])
        if days <= 7:
            bar['label'] = 'আজ' if is_today else BN_WEEKDAYS_SHORT[bar['day'].weekday()]
        else:
            from_end = len(bars) - 1 - index
            bar['label'] = ('আজ' if is_today else
                            f"{bn_num(bar['day'].day)} {BN_MONTHS_SHORT[bar['day'].month - 1]}"
                            if from_end % every == 0 else '')
        for key in ('pos', 'online'):
            pct = float(bar[key]) * 100 / ceiling if ceiling else 0
            # খুব ছোট বিক্রিও যেন চোখে পড়ে
            bar[f'{key}_pct'] = round(max(pct, 1.5), 2) if bar[key] > 0 else 0
        bar['top_pct'] = round(bar['pos_pct'] + bar['online_pct'], 2)
        # কিনারার বারের টুলটিপ যেন চার্টের বাইরে না যায়
        bar['align'] = 'l' if index < len(bars) * 0.2 else ('r' if index >= len(bars) * 0.8 else '')
    return {
        'days': days,
        'bars': bars,
        'total': sum((bar['total'] for bar in bars), ZERO),
        'pos_total': sum((bar['pos'] for bar in bars), ZERO),
        'online_total': sum((bar['online'] for bar in bars), ZERO),
        'orders': sum(bar['count'] for bar in bars),
        'grid': [short_taka(ceiling), short_taka(ceiling / 2), '0'] if ceiling else [],
        'empty': peak <= 0,
        'dense': days > 7,
    }


def today_numbers(shop, today):
    yesterday = today - timedelta(days=1)
    daily = _daily_sales(shop, yesterday, today)
    now_row = daily.get(today, {'pos': ZERO, 'online': ZERO, 'count': 0})
    before_row = daily.get(yesterday, {'pos': ZERO, 'online': ZERO, 'count': 0})
    sales = now_row['pos'] + now_row['online']
    yesterday_sales = before_row['pos'] + before_row['online']

    todays_orders = (Order.objects.filter(shop=shop, created_at__date=today)
                     .exclude(status__in=NOT_COUNTED))
    net = todays_orders.aggregate(v=Sum(NET_OF_VAT))['v'] or ZERO
    items = OrderItem.objects.filter(order__in=todays_orders)
    cost = items.aggregate(v=Sum(ITEM_COST))['v'] or ZERO
    # কেনা দাম না দেওয়া প্রোডাক্ট থাকলে লাভ আসলের চেয়ে বেশি দেখাবে, সেলারকে জানানো হয়
    missing_cost = items.filter(cost_price__lte=0, price__gt=0).exists()

    views_today = PageView.objects.filter(shop=shop, created_at__date=today).count()
    views_yesterday = PageView.objects.filter(shop=shop, created_at__date=yesterday).count()
    return {
        'sales': sales,
        'sales_pos': now_row['pos'],
        'sales_online': now_row['online'],
        'orders': now_row['count'],
        'yesterday_sales': yesterday_sales,
        'sales_change': _change(sales, yesterday_sales),
        'profit': net - cost,
        'profit_negative': net - cost < 0,
        'profit_abs': abs(net - cost),
        'profit_missing_cost': missing_cost,
        'views': views_today,
        'views_yesterday': views_yesterday,
        'views_change': _change(views_today, views_yesterday),
    }


def order_pipeline(shop, today):
    """অনলাইন/ম্যানুয়াল অর্ডার কোন ধাপে কয়টা (POS-এর বিক্রি সাথে সাথেই শেষ, তাই বাদ)।"""
    counts = dict(Order.objects.filter(shop=shop).exclude(source='pos')
                  .filter(status__in=['Pending', 'Confirmed', 'Shipped'])
                  .values_list('status').annotate(n=Count('id')))
    new_today = Order.objects.filter(shop=shop, created_at__date=today).exclude(source='pos').count()
    return {'pending': counts.get('Pending', 0), 'confirmed': counts.get('Confirmed', 0),
            'shipped': counts.get('Shipped', 0), 'new_today': new_today}


def pos_dues(shop):
    due_orders = (Order.objects.filter(shop=shop, source='pos', advance_paid__lt=F('total_amount'))
                  .exclude(status__in=NOT_COUNTED))
    agg = due_orders.aggregate(total=Sum(F('total_amount') - F('advance_paid')),
                               people=Count('customer', distinct=True))
    return {'amount': agg['total'] or ZERO, 'people': agg['people'] or 0}


def stock_alerts(shop, limit=6):
    low = Product.objects.filter(shop=shop, is_active=True, stock_quantity__lt=LOW_STOCK)
    counts = low.aggregate(total=Count('id'), out=Count('id', filter=Q(stock_quantity=0)))
    return {
        'items': list(low.order_by('stock_quantity', 'name')[:limit]),
        'count': counts['total'] or 0,
        'out': counts['out'] or 0,
    }


def recent_orders(shop, limit=6):
    now = timezone.now()
    orders = list(Order.objects.filter(shop=shop).select_related('customer').order_by('-created_at')[:limit])
    for order in orders:
        walk_in = order.customer.phone == WALK_IN_PHONE
        order.display_name = 'দোকানের কাস্টমার' if walk_in else (order.customer.name or order.customer.phone)
        order.initial = (order.display_name or '?')[:1].upper()
        order.source_label = SOURCE_LABELS.get(order.source, order.source)
        label, tone = STATUS_LABELS.get(order.status, (order.status, 'muted'))
        if order.source == 'pos' and order.status == 'Delivered':
            label, tone = ('বাকি আছে', 'confirmed') if order.due_amount > 0 else ('বিক্রি হয়েছে', 'done')
        order.status_label, order.status_tone = label, tone
        order.ago = bn_ago(order.created_at, now)
        order.link = (reverse('pos_receipt', args=[order.id]) if order.source == 'pos'
                      else reverse('invoice', args=[order.id]))
    return orders


def top_sellers(shop, today, days=30, limit=5):
    since = today - timedelta(days=days - 1)
    rows = list(OrderItem.objects.filter(order__shop=shop, order__created_at__date__gte=since)
                .exclude(order__status__in=NOT_COUNTED).filter(quantity__gt=0)
                .values('product_id')
                .annotate(qty=Sum('quantity'),
                          amount=Sum(ExpressionWrapper(F('price') * F('quantity'),
                                                       output_field=DecimalField(max_digits=14, decimal_places=2))))
                .order_by('-qty', '-amount')[:limit])
    products = Product.objects.in_bulk([row['product_id'] for row in rows])
    best = rows[0]['qty'] if rows else 0
    result = []
    for row in rows:
        product = products.get(row['product_id'])
        if product is None:
            continue
        result.append({'product': product, 'qty': row['qty'], 'amount': row['amount'] or ZERO,
                       'pct': round(row['qty'] * 100 / best) if best else 0})
    return result


def setup_steps(shop, plan_has_facebook):
    """নতুন দোকানের জন্য ধাপগুলো; সব হয়ে গেলে ড্যাশবোর্ডে আর দেখায় না।"""
    website = reverse('website_settings')
    has_courier = any(couriers.connected(shop).values())
    steps = [
        ('product', 'bi-box-seam', 'প্রথম প্রোডাক্ট যোগ করুন', 'ছবি, দাম আর স্টক দিলেই ওয়েবসাইট আর POS-এ চলে আসবে',
         Product.objects.filter(shop=shop).exists(), reverse('add_product')),
        ('logo', 'bi-image', 'দোকানের লোগো দিন', 'ওয়েবসাইট আর রসিদে লোগো দেখাবে',
         bool(shop.logo), f'{website}?tab=store'),
        ('contact', 'bi-geo-alt', 'ফোন নম্বর আর ঠিকানা দিন', 'কাস্টমার যেন যোগাযোগ করতে পারে',
         bool(shop.phone and shop.address), f'{website}?tab=store'),
        ('banner', 'bi-images', 'ওয়েবসাইটে ব্যানার দিন', 'অফার বা নতুন কালেকশনের ছবি উপরে দেখাবে',
         Banner.objects.filter(shop=shop, is_active=True).exists(), f'{website}?tab=banners'),
        ('courier', 'bi-truck', 'কুরিয়ার কানেক্ট করুন', 'Steadfast, Pathao বা RedX — এক ক্লিকে পার্সেল বুক',
         has_courier, f"{reverse('settings')}?tab=courier"),
    ]
    if plan_has_facebook:
        steps.append(('facebook', 'bi-facebook', 'Facebook পেইজ কানেক্ট করুন', 'কমেন্ট থেকে অর্ডার নেওয়া যাবে',
                      hasattr(shop, 'fb_page'), reverse('fb_connect')))
    steps.append(('sale', 'bi-bag-check', 'প্রথম বিক্রি করুন', 'POS-এ বিক্রি করুন বা ওয়েবসাইটের লিংক শেয়ার করুন',
                  Order.objects.filter(shop=shop).exists(), reverse('pos')))
    items = [{'key': key, 'icon': icon, 'title': title, 'hint': hint, 'done': done, 'url': url}
             for key, icon, title, hint, done, url in steps]
    done = sum(1 for item in items if item['done'])
    return {'items': items, 'done': done, 'total': len(items), 'complete': done == len(items),
            'pct': round(done * 100 / len(items)) if items else 100,
            'next': next((item for item in items if not item['done']), None)}


def todo_items(can, pipeline, dues, stock):
    """"এখন যা করতে হবে" — জরুরিগুলো আগে। যার অনুমতি নেই তার কাজ দেখায় না।"""
    orders_url = reverse('order_list')
    items = []
    if can['orders'] and pipeline['pending']:
        items.append({'icon': 'bi-bell-fill', 'tone': 'blue', 'url': f'{orders_url}?status=Pending',
                      'title': f"{bn_num(pipeline['pending'])}টা নতুন অর্ডার কনফার্ম করুন",
                      'sub': 'কাস্টমারকে ফোন করে নিশ্চিত হয়ে নিন'})
    if can['orders'] and pipeline['confirmed']:
        items.append({'icon': 'bi-box-seam-fill', 'tone': 'amber', 'url': f'{orders_url}?status=Confirmed',
                      'title': f"{bn_num(pipeline['confirmed'])}টা অর্ডার কুরিয়ারে পাঠানো বাকি",
                      'sub': 'প্যাক করে পার্সেল বুক করুন'})
    if stock['out'] and can['products']:
        items.append({'icon': 'bi-x-octagon-fill', 'tone': 'red', 'url': f"{reverse('product_list')}?status=low",
                      'title': f"{bn_num(stock['out'])}টা প্রোডাক্ট স্টকে নেই",
                      'sub': 'ওয়েবসাইটে "স্টক শেষ" দেখাচ্ছে, নতুন মাল তুলুন'})
    low_only = stock['count'] - stock['out']
    if low_only > 0 and can['products']:
        items.append({'icon': 'bi-exclamation-triangle-fill', 'tone': 'amber',
                      'url': f"{reverse('product_list')}?status=low",
                      'title': f"{bn_num(low_only)}টা প্রোডাক্ট শেষের পথে",
                      'sub': f'{bn_num(LOW_STOCK)}টার কম বাকি আছে'})
    if dues and dues['amount'] > 0 and can['pos']:
        amount = f"{dues['amount']:,.0f}" if dues['amount'] == dues['amount'].to_integral_value() \
            else f"{dues['amount']:,.2f}"
        items.append({'icon': 'bi-wallet2', 'tone': 'violet', 'url': reverse('due_list'),
                      'title': f'৳{amount} বাকি তুলতে হবে',
                      'sub': f"{bn_num(dues['people'])} জন কাস্টমারের কাছে · বাকির খাতায় তাগাদা দিন"})
    if can['orders'] and pipeline['shipped']:
        items.append({'icon': 'bi-truck', 'tone': 'slate', 'url': reverse('courier'),
                      'title': f"{bn_num(pipeline['shipped'])}টা পার্সেল পথে আছে",
                      'sub': 'কুরিয়ারের অবস্থা দেখুন'})
    return items
