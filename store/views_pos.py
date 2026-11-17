# store/views_pos.py
"""POS (দোকানে বিক্রি)-র পেইজ আর JSON API। হিসাবের কাজ store/pos.py-তে।"""
import json
from datetime import date

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from . import pos
from .models import Category, Order, Product, ProductVariant

LOGIN = '/accounts/login/'


def _is_owner(request):
    return not getattr(request.user, 'is_shop_staff', False)


def _can_return(request):
    if _is_owner(request):
        return True
    profile = getattr(request.user, 'staff_profile', None)
    return bool(profile and profile.can_manage_orders)


def _json_body(request):
    try:
        data = json.loads(request.body or b'{}')
    except (ValueError, UnicodeDecodeError):
        raise pos.POSError('অনুরোধটা ঠিক নেই, পেইজটা রিফ্রেশ করুন।')
    if not isinstance(data, dict):
        raise pos.POSError('অনুরোধটা ঠিক নেই, পেইজটা রিফ্রেশ করুন।')
    return data


def _error(message, status=400):
    return JsonResponse({'success': False, 'error': message}, status=status)


def _num(value):
    """JSON-এ টাকা: পূর্ণ সংখ্যা হলে int, নাহলে দুই দশমিক।"""
    value = pos.money(value)
    return int(value) if value == value.to_integral_value() else float(value)


def _sale_json(order):
    return {
        'id': order.id,
        'number': f'ORD-{order.id}',
        'time': timezone.localtime(order.created_at).strftime('%I:%M %p'),
        'customer': '' if order.customer.phone == pos.WALK_IN_PHONE else order.customer.name,
        'phone': '' if order.customer.phone == pos.WALK_IN_PHONE else order.customer.phone,
        'total': _num(order.total_amount),
        'paid': _num(min(order.advance_paid, order.total_amount)),
        'due': _num(order.due_amount),
        'change': _num(order.change_given),
        'cash_received': _num(order.cash_received),
        'status': order.status,
        'returned': order.status == 'Returned',
        'partly_returned': order.status != 'Returned' and bool(
            order.return_count if hasattr(order, 'return_count') else order.returns.exists()),
        'payment': order.payment_method,
        'cashier': (order.served_by.name or order.served_by.phone_number) if order.served_by_id else '',
        'receipt_url': reverse('pos_receipt', args=[order.id]),
        'offline_bill': order.offline_bill,
    }


def _product_json(p):
    from . import units
    extra = list(p.extra_barcodes.all())
    data = {'id': p.id, 'name': p.name, 'price': _num(p.price), 'stock': units.num(p.stock_quantity),
            'cat': p.category_id or 0, 'barcode': p.barcode or '', 'img': p.thumb_url,
            # একক: পিস হলে "টা", ওজনের হলে ভাঙা পরিমাণ চলে (store/units.py)
            'unit': p.unit, 'suffix': p.unit_suffix,
            # বাড়তি বারকোড (store/models.ProductBarcode) — যেকোনোটা স্ক্যান করলেই এই প্রোডাক্ট
            'codes': [b.code for b in extra if not b.variant_id]}
    if p.has_variants:
        # সাইজ/রং: কার্টে এদের নম্বর ঋণাত্মক (store/variants.py)
        data['variants'] = [{'id': -v.id, 'name': v.name, 'price': _num(v.sell_price), 'stock': units.num(v.stock_quantity),
                             'barcode': v.barcode, 'codes': [b.code for b in extra if b.variant_id == v.id]}
                            for v in p.variants.all()]
    return data


def _catalog(shop):
    """POS-এর প্রোডাক্ট (দাম, স্টক, বারকোড) — পাতায় বসানো থাকে, আর অফলাইনের পর নেট এলে /pos/catalog/ থেকে নতুন করে।"""
    products = (Product.objects.filter(shop=shop, is_active=True).prefetch_related('variants', 'extra_barcodes')
                .order_by('name'))
    return [_product_json(p) for p in products]


DUE_CUSTOMERS_MAX = 3000


def _due_customers(shop):
    """বাকি থাকা কাস্টমার (মোবাইল, নাম, কত বাকি) — নেট না থাকলেও POS-এ "আগের বাকি" দেখাতে।"""
    from django.db.models import F, Max
    rows = (Order.objects.filter(shop=shop, source='pos', advance_paid__lt=F('total_amount'))
            .exclude(status__in=pos.NOT_COUNTED).values('customer__phone').annotate(due=Sum(F('total_amount') - F('advance_paid')),
                                                name=Max('customer__name'))
            .order_by('-due')[:DUE_CUSTOMERS_MAX])
    return [{'phone': r['customer__phone'], 'name': r['name'] or '', 'due': _num(r['due'] or 0)}
            for r in rows if r['customer__phone'] and r['customer__phone'] != pos.WALK_IN_PHONE]


def _now_ms():
    return int(timezone.now().timestamp() * 1000)


# POS-এর বিক্রি JS থেকে যায়, csrftoken কুকি লাগে — কুকি মুছে গেলে বা অন্যভাবে লগইন হলেও যেন থাকে
@ensure_csrf_cookie
@login_required(login_url=LOGIN)
def pos_screen(request):
    from django.templatetags.static import static
    shop = request.user.shop
    product_data = _catalog(shop)
    used_categories = {p['cat'] for p in product_data}
    categories = [c for c in Category.objects.filter(shop=shop).order_by('name') if c.id in used_categories]
    today = pos.sales_on(shop, timezone.localdate()).exclude(status__in=pos.NOT_COUNTED)
    stats = today.aggregate(count=Count('id'), total=Sum('total_amount'))
    user = request.user
    return render(request, 'store/pos.html', {
        'shop': shop,
        'categories': categories,
        'pos_manifest': True,
        'pos_config': {
            'products': product_data,
            # অফলাইন POS: কখনকার তথ্য, কে বিক্রি করছে, রসিদে কী ছাপা হবে, আর বাকি থাকা কাস্টমার
            'generatedAt': _now_ms(),
            'user': {'id': user.pk, 'name': user.name or user.phone_number},
            'dueCustomers': _due_customers(shop),
            'receipt': {'name': shop.name, 'address': shop.address or '', 'phone': shop.phone or '',
                        'bin': getattr(shop, 'pos_bin', '') or '', 'note': getattr(shop, 'pos_receipt_note', '') or '',
                        'logo': shop.logo.url if shop.logo else '', 'width': shop.pos_receipt_width},
            'precache': [static('vendor/html5-qrcode/html5-qrcode.min.js'),
                         static('vendor/jsbarcode/JsBarcode.all.min.js')],
            'vatPercent': _num(shop.pos_vat_percent),
            'vatMode': shop.pos_vat_mode,
            'canEditPrice': _is_owner(request),
            'canReturn': _can_return(request),
            'autoPrint': shop.pos_auto_print,
            'shopId': shop.id,
            'todayCount': stats['count'] or 0,
            'todayTotal': _num(stats['total'] or 0),
            'urls': {
                'checkout': reverse('pos_checkout'),
                'customer': reverse('pos_customer'),
                'collect': reverse('pos_collect_due'),
                'sales': reverse('pos_sales'),
                'returnBase': reverse('pos_return', args=[0]).replace('/0/', '/{id}/'),
                'saleBase': reverse('pos_sale_detail', args=[0]).replace('/0/', '/{id}/'),
                'barcode': reverse('barcode_lookup'),
                'dayClose': reverse('pos_day_close'),
                'catalog': reverse('pos_catalog'),
                'ping': reverse('pos_ping'),
                'sw': reverse('pos_sw'),
                'pos': reverse('pos'),
            },
        },
    })


@login_required(login_url=LOGIN)
@require_POST
def pos_barcode(request):
    """স্ক্যানারের বারকোড পেইজে না থাকলে (পরে যোগ হওয়া প্রোডাক্ট) এখানে খোঁজা হয়।"""
    try:
        barcode = str(_json_body(request).get('barcode') or '').strip()[:64]
    except pos.POSError as exc:
        return _error(str(exc))
    shop = request.user.shop
    product = Product.objects.filter(shop=shop, barcode=barcode, is_active=True).first() if barcode else None
    hit = product.id if product else None
    if product is None and barcode:
        variant = (ProductVariant.objects.filter(product__shop=shop, product__is_active=True, barcode=barcode)
                   .select_related('product').first())
        if variant:
            product, hit = variant.product, -variant.id
    if product is None and barcode:
        from .models import ProductBarcode
        extra = (ProductBarcode.objects.filter(shop=shop, code=barcode, product__is_active=True)
                 .select_related('product').first())
        if extra:
            product, hit = extra.product, (-extra.variant_id if extra.variant_id else extra.product_id)
    if product is None:
        return _error(f'এই বারকোডের কোনো প্রোডাক্ট নেই: {barcode}', status=404)
    return JsonResponse({'success': True, 'product': _product_json(product), 'hit': hit})


@login_required(login_url=LOGIN)
@require_POST
def pos_checkout(request):
    shop = request.user.shop
    try:
        payload = _json_body(request)
        order, created = pos.create_sale(shop, request.user, payload, can_override_price=_is_owner(request))
    except pos.POSError as exc:
        return _error(str(exc))
    # synced_at: সার্ভারের সময় — নেট ছাড়া খোলা পুরনো পাতার স্টক থেকে কোন বিক্রি বাদ দিতে হবে বোঝা যায়
    return JsonResponse({'success': True, 'created': created, 'sale': {**_sale_json(order), 'synced_at': _now_ms()},
                         'auto_print': shop.pos_auto_print})


@login_required(login_url=LOGIN)
def pos_catalog(request):
    """অফলাইনের বিক্রি পাঠানোর পর POS-এর স্টক-দাম নতুন করে (পাতা রিফ্রেশ না করেই)।"""
    shop = request.user.shop
    return JsonResponse({'success': True, 'products': _catalog(shop), 'generatedAt': _now_ms(),
                         'dueCustomers': _due_customers(shop)})


@login_required(login_url=LOGIN)
def pos_ping(request):
    """নেট আর লগইন ঠিক আছে কিনা (অফলাইন থেকে ফেরার সময় POS ছোট করে জিজ্ঞেস করে)।"""
    return JsonResponse({'success': True, 'shop': request.user.shop.id})


POS_SW_VERSION = '1'      # pos_sw.js-এর নিয়ম বদলালে বাড়ান


def pos_sw(request):
    """
    অফলাইন POS-এর service worker (/pos/sw.js — তাই শুধু /pos/ পাতাগুলো এর আওতায়)। লগইন লাগে না, ভেতরে কারো তথ্য নেই।
    আগে থেকে রাখা ফাইলের তালিকা static() থেকে, তাই নতুন deploy-এ ফাইলের নাম বদলালে নতুন সংস্করণ নিজে নামে।
    """
    import hashlib
    from django.http import HttpResponse
    from django.template.loader import render_to_string
    from django.templatetags.static import static
    files = ['vendor/bootstrap/bootstrap-app.min.css', 'vendor/bootstrap/bootstrap.bundle.min.js',
             'vendor/sweetalert2/sweetalert2.all.min.js', 'vendor/html5-qrcode/html5-qrcode.min.js',
             'vendor/jsbarcode/JsBarcode.all.min.js', 'brand/sellpunch-logo.svg', 'brand/sellpunch-mark.svg',
             'brand/icon-192.png']
    precache = []
    for name in files:
        try:
            precache.append(static(name))
        except ValueError:          # manifest-এ নেই (টেস্ট/লোকাল) — বাদ
            continue
    version = hashlib.sha1((POS_SW_VERSION + '|' + '|'.join(precache)).encode()).hexdigest()[:12]
    from django.conf import settings
    body = render_to_string('store/pos_sw.js', {'version': version, 'precache': json.dumps(precache),
                                                 'pos_url': reverse('pos'), 'network_first': settings.DEBUG})
    response = HttpResponse(body, content_type='application/javascript; charset=utf-8')
    response['Cache-Control'] = 'no-cache'
    response['Service-Worker-Allowed'] = reverse('pos')
    return response


def pos_manifest(request):
    """POS-কে আলাদা অ্যাপ হিসেবে বসানোর manifest (হোম স্ক্রিন/ডেস্কটপে "SellPunch POS")।"""
    from django.conf import settings
    from django.templatetags.static import static
    site = getattr(settings, 'SITE_NAME', 'SellPunch')
    data = {
        'name': f'{site} POS', 'short_name': 'POS', 'id': reverse('pos'), 'start_url': reverse('pos'),
        'scope': reverse('pos'), 'display': 'standalone', 'background_color': '#F8FAFC', 'theme_color': '#059669',
        'lang': 'bn', 'description': 'দোকানে বিক্রি — নেট না থাকলেও চলে, নেট এলে নিজে থেকে জমা হয়।',
        'icons': [{'src': static('brand/icon-192.png'), 'sizes': '192x192', 'type': 'image/png'},
                  {'src': static('brand/icon-512.png'), 'sizes': '512x512', 'type': 'image/png',
                   'purpose': 'any maskable'}],
    }
    response = JsonResponse(data, json_dumps_params={'ensure_ascii': False})
    response['Content-Type'] = 'application/manifest+json; charset=utf-8'
    return response


@login_required(login_url=LOGIN)
def pos_customer(request):
    summary = pos.customer_summary(request.user.shop, request.GET.get('phone', ''))
    if summary is None:
        return _error('১১ সংখ্যার মোবাইল নম্বর দিন, যেমন 01712345678')
    if summary['found']:
        summary.update(spent=_num(summary['spent']), due=_num(summary['due']),
                       last_visit=timezone.localtime(summary['last_visit']).strftime('%d %b %Y')
                       if summary['last_visit'] else '')
    return JsonResponse({'success': True, 'customer': summary})


@login_required(login_url=LOGIN)
@require_POST
def pos_collect_due(request):
    shop = request.user.shop
    try:
        data = _json_body(request)
        collected, left = pos.collect_due(shop, request.user, data.get('phone'), data.get('amount'),
                                          (data.get('method') or '').lower(), data.get('reference', ''))
    except pos.POSError as exc:
        return _error(str(exc))
    return JsonResponse({'success': True, 'collected': _num(collected), 'due_left': _num(left)})


@login_required(login_url=LOGIN)
def pos_sales(request):
    """আজকের (বা ?date=) বিক্রি; ?q= দিলে রসিদ নম্বর/মোবাইল দিয়ে খোঁজা।"""
    shop = request.user.shop
    day = _parse_day(request.GET.get('date'))
    query = (request.GET.get('q') or '').strip()
    if query:
        digits = ''.join(ch for ch in query if ch.isdigit())
        orders = Order.objects.filter(shop=shop, source='pos').select_related('customer', 'served_by')
        if orders.filter(offline_bill__iexact=query).exists():
            orders = orders.filter(offline_bill__iexact=query)          # অফলাইনের বিল নম্বর (যেমন K7-12)
        elif query.upper().startswith('ORD') and 0 < len(digits) <= 9:
            orders = orders.filter(pk=int(digits))
        elif len(digits) >= 6:
            orders = orders.filter(customer__phone__endswith=digits[-10:])
        elif digits:
            orders = orders.filter(pk=int(digits))
        else:
            orders = orders.filter(customer__name__icontains=query)
        orders = orders.annotate(return_count=Count('returns')).order_by('-created_at')[:30]
    else:
        orders = pos.sales_on(shop, day).annotate(return_count=Count('returns'))[:300]
    return JsonResponse({'success': True, 'sales': [_sale_json(o) for o in orders],
                         'can_return': _can_return(request)})


@login_required(login_url=LOGIN)
@require_POST
def pos_return(request, order_id):
    """কয়েকটা প্রোডাক্ট ফেরত ({"items": [{"item_id", "qty"}], "method", "reason"}); items না দিলে পুরো বিল।"""
    if not _can_return(request):
        return _error('বিক্রি ফেরতের অনুমতি নেই। দোকানের মালিককে বলুন।', status=403)
    try:
        data = _json_body(request)
        order, sale_return, restocked = pos.return_items(
            request.user.shop, request.user, order_id, data.get('items'), data.get('method'), data.get('reason', ''))
    except pos.POSError as exc:
        return _error(str(exc))
    return JsonResponse({'success': True, 'sale': _sale_json(order), 'refunded': _num(sale_return.refund),
                         'value': _num(sale_return.value), 'full': sale_return.full, 'restocked': restocked})


@login_required(login_url=LOGIN)
def pos_sale_detail(request, order_id):
    """ফেরতের পপআপ: বিলের প্রোডাক্ট, কয়টা ফেরতযোগ্য, একটা ফেরত দিলে বিল কত কমে।"""
    try:
        order, items, method = pos.sale_detail(request.user.shop, order_id)
    except pos.POSError as exc:
        return _error(str(exc), status=404)
    for item in items:
        item.update(price=_num(item['price']), unit_value=_num(item['unit_value']))
    return JsonResponse({'success': True, 'sale': _sale_json(order), 'items': items, 'refund_method': method,
                         'can_return': _can_return(request)})


@login_required(login_url=LOGIN)
def pos_receipt(request, order_id):
    shop = request.user.shop
    order = get_object_or_404(Order.objects.select_related('customer', 'served_by'), id=order_id, shop=shop)
    items = [i for i in order.items.select_related('product') if i.quantity > 0 or order.status == 'Returned']
    for item in items:
        item.line_total = item.price * item.quantity
    payments = list(order.payments.all())
    return render(request, 'store/pos_receipt.html', {
        'shop': shop, 'order': order, 'items': items,
        'subtotal': sum((i.line_total for i in items), pos.ZERO),
        'sale_payments': [p for p in payments if p.kind == p.SALE],
        'later_payments': [p for p in payments if p.kind != p.SALE],
        'walk_in': order.customer.phone == pos.WALK_IN_PHONE,
        'sale_returns': order.returns.prefetch_related('items'),
        'width': 58 if request.GET.get('w') == '58' else (80 if request.GET.get('w') == '80' else shop.pos_receipt_width),
        'auto_print': request.GET.get('print') == '1',
    })


def _parse_day(value):
    try:
        return date.fromisoformat(value) if value else timezone.localdate()
    except ValueError:
        return timezone.localdate()


@login_required(login_url=LOGIN)
def pos_day_close(request):
    shop = request.user.shop
    day = _parse_day(request.GET.get('date'))
    return render(request, 'store/pos_day_close.html', {
        'shop': shop, 'summary': pos.day_summary(shop, day), 'today': timezone.localdate(),
        'printed_at': timezone.localtime(),
    })
