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
from django.views.decorators.http import require_POST

from . import pos
from .models import Category, Order, Product

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
        'payment': order.payment_method,
        'cashier': (order.served_by.name or order.served_by.phone_number) if order.served_by_id else '',
        'receipt_url': reverse('pos_receipt', args=[order.id]),
    }


def _product_json(p):
    return {'id': p.id, 'name': p.name, 'price': _num(p.price), 'stock': p.stock_quantity,
            'cat': p.category_id or 0, 'barcode': p.barcode or '', 'img': p.thumb_url}


@login_required(login_url=LOGIN)
def pos_screen(request):
    shop = request.user.shop
    products = Product.objects.filter(shop=shop, is_active=True).order_by('name')
    product_data = [_product_json(p) for p in products]
    used_categories = {p['cat'] for p in product_data}
    categories = [c for c in Category.objects.filter(shop=shop).order_by('name') if c.id in used_categories]
    today = pos.sales_on(shop, timezone.localdate()).exclude(status__in=pos.NOT_COUNTED)
    stats = today.aggregate(count=Count('id'), total=Sum('total_amount'))
    return render(request, 'store/pos.html', {
        'shop': shop,
        'categories': categories,
        'pos_config': {
            'products': product_data,
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
                'barcode': reverse('barcode_lookup'),
                'dayClose': reverse('pos_day_close'),
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
    product = (Product.objects.filter(shop=request.user.shop, barcode=barcode, is_active=True).first()
               if barcode else None)
    if product is None:
        return _error(f'এই বারকোডের কোনো প্রোডাক্ট নেই: {barcode}', status=404)
    return JsonResponse({'success': True, 'product': _product_json(product)})


@login_required(login_url=LOGIN)
@require_POST
def pos_checkout(request):
    shop = request.user.shop
    try:
        payload = _json_body(request)
        order, created = pos.create_sale(shop, request.user, payload, can_override_price=_is_owner(request))
    except pos.POSError as exc:
        return _error(str(exc))
    return JsonResponse({'success': True, 'created': created, 'sale': _sale_json(order),
                         'auto_print': shop.pos_auto_print})


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
        if query.upper().startswith('ORD') and 0 < len(digits) <= 9:
            orders = orders.filter(pk=int(digits))
        elif len(digits) >= 6:
            orders = orders.filter(customer__phone__endswith=digits[-10:])
        elif digits:
            orders = orders.filter(pk=int(digits))
        else:
            orders = orders.filter(customer__name__icontains=query)
        orders = orders.order_by('-created_at')[:30]
    else:
        orders = pos.sales_on(shop, day)[:300]
    return JsonResponse({'success': True, 'sales': [_sale_json(o) for o in orders],
                         'can_return': _can_return(request)})


@login_required(login_url=LOGIN)
@require_POST
def pos_return(request, order_id):
    if not _can_return(request):
        return _error('বিক্রি ফেরতের অনুমতি নেই। দোকানের মালিককে বলুন।', status=403)
    try:
        data = _json_body(request)
        order, refunded = pos.return_sale(request.user.shop, request.user, order_id, data.get('reason', ''))
    except pos.POSError as exc:
        return _error(str(exc))
    restocked = [{'id': i.product_id, 'qty': i.quantity} for i in order.items.all()]
    return JsonResponse({'success': True, 'sale': _sale_json(order), 'refunded': _num(refunded),
                         'restocked': restocked})


@login_required(login_url=LOGIN)
def pos_receipt(request, order_id):
    shop = request.user.shop
    order = get_object_or_404(Order.objects.select_related('customer', 'served_by'), id=order_id, shop=shop)
    items = list(order.items.select_related('product'))
    for item in items:
        item.line_total = item.price * item.quantity
    payments = list(order.payments.all())
    return render(request, 'store/pos_receipt.html', {
        'shop': shop, 'order': order, 'items': items,
        'subtotal': sum((i.line_total for i in items), pos.ZERO),
        'sale_payments': [p for p in payments if p.kind == p.SALE],
        'later_payments': [p for p in payments if p.kind != p.SALE],
        'walk_in': order.customer.phone == pos.WALK_IN_PHONE,
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
