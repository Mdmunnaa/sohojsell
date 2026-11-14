# ============================================================
# SellPunch - Store Views
# ============================================================
import json
from django.db.models import Count
import requests
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import Http404, HttpResponse, JsonResponse
from django.template.loader import get_template
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from decimal import Decimal

from django.db.models import Count, F, Sum, Q
from django.utils import timezone
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from datetime import timedelta
import random

from .models import Shop, Product, Category, Order, OrderItem, Customer, MasterSetting, Banner
from .plans import (
    can_add_staff, has_custom_domain, has_facebook, plan_label, product_limit, products_remaining,
    staff_limit, storefront_closes_on, storefront_is_open, upgrade_message,
)
from .forms import (ShopSetupForm, ProductForm, OrderCreateForm, SteadfastSettingsForm, PathaoSettingsForm,
                    RedxSettingsForm, PosSettingsForm)
from .links import storefront_link
from . import couriers, offers, order_flow, reviews, risk, sf_lang, sms, variants
from .themes import THEMES
from django.urls import reverse

BN_TO_EN_DIGITS = str.maketrans('০১২৩৪৫৬৭৮৯', '0123456789')


# ============================================================
# LANDING PAGE
# ============================================================
HOME_PLAN_TEXT = {      # প্যাকেজের ছোট পরিচয়: বাংলা, ইংরেজি হোমপেজের জন্য
    'Basic': ('একা চালানো ছোট দোকান', 'For a small shop run by one person'),
    'Standard': ('বাড়তে থাকা অনলাইন ব্যবসা', 'For a growing online business'),
    'Premium': ('ব্র্যান্ড আর একাধিক দোকান', 'For brands and bigger shops'),
}


def landing_page(request):
    return _home(request, 'bn')


def landing_page_en(request):
    """ইংরেজি হোমপেজ (/en/) — যারা Google-এ "pos software bangladesh"-এর মতো ইংরেজিতে খোঁজে।"""
    return _home(request, 'en')


def _home(request, lang):
    if request.user.is_authenticated:
        if request.user.is_superuser:
            return redirect('master_dashboard')
        return redirect('dashboard')
    from . import seo
    from .payments import PLAN_PRICES, PLAN_YEAR_PRICES
    from .plans import PLAN_LIMITS
    from .sms import sms_rate
    plans = []
    for key in ('Basic', 'Standard', 'Premium'):
        limits = PLAN_LIMITS[key]
        plans.append({
            'key': key, 'tagline': HOME_PLAN_TEXT[key][1 if lang == 'en' else 0], 'popular': key == 'Standard',
            'month': int(PLAN_PRICES[key]), 'year': int(PLAN_YEAR_PRICES[key]),
            'year_per_month': int(PLAN_YEAR_PRICES[key] / 12),
            'products': limits['products'], 'staff': limits['staff'], 'facebook': limits['facebook'],
            'custom_domain': limits['custom_domain'],
        })
    try:
        rate = sms_rate()
    except Exception:    # noqa: BLE001 — ডেটাবেস ছাড়া হোমপেজ আটকাবে না
        rate = None
    base = seo.main_site_url(request)
    home_seo = {'base': base, 'url_bn': base + '/', 'url_en': base + reverse('landing_page_en'), 'lang': lang}
    home_seo['canonical'] = home_seo['url_en'] if lang == 'en' else home_seo['url_bn']
    template = 'store/landing_en.html' if lang == 'en' else 'store/landing.html'
    return render(request, template, {'plans': plans, 'sms_rate': rate, 'trial_days': 30, 'home_seo': home_seo})


def site_robots(request):
    """মূল সাইটের robots.txt (দোকানগুলোর নিজেরটা আলাদা — store/seo.py)।"""
    from . import seo
    return HttpResponse(seo.main_robots_txt(request), content_type='text/plain')


def site_sitemap(request):
    from . import seo
    return HttpResponse(seo.main_sitemap_xml(request), content_type='application/xml')


# ============================================================
# SELLER DASHBOARD
# ============================================================
@login_required(login_url='/accounts/login/')
def seller_dashboard(request):
    """দোকানের মূল পাতা: আজকের হিসাব, ৭/৩০ দিনের চার্ট, এখন যা করতে হবে। হিসাবগুলো store/dashboard.py-তে।"""
    from . import dashboard as dash
    from .plans import limits_for

    if not hasattr(request.user, 'shop'):
        return redirect('setup_shop')

    shop = request.user.shop
    is_owner = not getattr(request.user, 'is_shop_staff', False)
    profile = None if is_owner else getattr(request.user, 'staff_profile', None)

    def allowed(permission):
        return is_owner or bool(profile and getattr(profile, permission, False))

    can = {
        'money': allowed('can_view_reports'),
        'pos': allowed('can_use_pos'),
        'orders': allowed('can_manage_orders'),
        'products': allowed('can_manage_products'),
        'settings': allowed('can_manage_settings'),
    }
    now = timezone.now()
    today = timezone.localdate()
    try:
        chart_days = int(request.GET.get('days', 7))
    except (TypeError, ValueError):
        chart_days = 7
    if chart_days not in dash.CHART_RANGES:
        chart_days = 7

    full_name = (getattr(request.user, 'name', '') or '').strip()
    store_url = request.build_absolute_uri(shop.storefront_url)
    pipeline = dash.order_pipeline(shop, today)
    dues = dash.pos_dues(shop) if can['pos'] else None
    stock = dash.stock_alerts(shop)
    context = {
        'shop': shop,
        'can': can,
        'is_owner': is_owner,
        'greeting': dash.greeting(now),
        'today_label': dash.bn_date(today),
        'person_name': full_name.split()[0] if full_name else '',
        'store_url': store_url,
        'share_text': f'{shop.name} — অনলাইনে অর্ডার করুন: {store_url}',
        'numbers': dash.today_numbers(shop, today),
        'pipeline': pipeline,
        'stock': stock,
        'todo': dash.todo_items(can, pipeline, dues, stock),
        'recent_orders': dash.recent_orders(shop) if can['orders'] or can['money'] else [],
        'chart': dash.sales_chart(shop, today, chart_days) if can['money'] else None,
        'top_sellers': dash.top_sellers(shop, today) if can['money'] else [],
        'setup': dash.setup_steps(shop, limits_for(shop)['facebook']) if is_owner and not shop.is_demo else None,
        'trial_days': shop.days_remaining(),
        'fb_page': getattr(shop, 'fb_page', None),
    }
    return render(request, 'store/dashboard.html', context)


# ============================================================
# SHOP SETUP
# ============================================================
@login_required(login_url='/accounts/login/')
def setup_shop(request):
    """
    দোকান ছাড়া লগইন করা ইউজার (যেমন Facebook দিয়ে প্রথমবার আসা) এখানে দোকানের নাম আর
    নিজের সাবডোমেইন দেয়। সাধারণ সাইনআপে এই ধাপ লাগে না, সেখানে এক পেইজেই সব হয়।
    """
    from django.db import IntegrityError
    from accounts.forms import ShopDetailsForm, normalize_bd_mobile

    if hasattr(request.user, 'shop'):
        return redirect('dashboard')

    form = ShopDetailsForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data
        try:
            Shop.objects.create(
                user=request.user,
                name=data['shop_name'],
                slug=data['subdomain'],
                phone=normalize_bd_mobile(request.user.phone_number) or None,
                address=data.get('address') or None,
                facebook_page_url=data.get('fb_link') or None,
            )
        except IntegrityError:
            form.add_error('subdomain', 'এই ঠিকানা এইমাত্র অন্য কেউ নিয়েছে, অন্যটা বেছে নিন।')
        else:
            messages.success(request, "দোকান তৈরি হয়েছে! ৩০ দিন সব ফিচার ফ্রি।")
            return redirect('dashboard')

    return render(request, 'store/setup_shop.html', {'form': form})


# ============================================================
# PRODUCT MANAGEMENT
# ============================================================
@login_required(login_url='/accounts/login/')
def product_list(request):
    shop = request.user.shop
    products = Product.objects.filter(shop=shop).select_related('category').order_by('-created_at')
    # Search
    q = request.GET.get('q', '')
    if q:
        products = products.filter(name__icontains=q)
    # Category filter
    cat_id = request.GET.get('cat', '')
    if cat_id:
        products = products.filter(category__id=cat_id)
    # Status filter
    status = request.GET.get('status', '')
    if status == 'active':
        products = products.filter(is_active=True)
    elif status == 'inactive':
        products = products.filter(is_active=False)
    elif status == 'low':
        products = products.filter(stock_quantity__lt=5)
    # Pagination
    paginator = Paginator(products, 20)
    page = request.GET.get('page', 1)
    try:
        page_obj = paginator.page(page)
    except (EmptyPage, PageNotAnInteger):
        page_obj = paginator.page(1)
    categories = Category.objects.filter(shop=shop)
    return render(request, 'store/products.html', {'page_obj': page_obj, 'categories': categories, 'shop': shop})


def _variant_rows(request, product):
    """ফর্মের সাইজ/রং অংশে দেখানোর সারি: ভুল হয়ে ফর্ম ফিরে এলে যা লেখা ছিল, নাহলে সেভ করা ভ্যারিয়েন্ট।"""
    if request.method == 'POST':
        post = request.POST
        return [{'id': i, 'name': n, 'price': p, 'stock': s} for i, n, p, s in zip(
            post.getlist('variant_id[]'), post.getlist('variant_name[]'),
            post.getlist('variant_price[]'), post.getlist('variant_stock[]'))]
    if product is None:
        return []
    return [{'id': v.id, 'name': v.name, 'price': '' if v.price is None else f'{v.price.normalize():f}',
             'stock': v.stock_quantity} for v in product.variants.all()]


@login_required(login_url='/accounts/login/')
def add_product(request):
    shop = request.user.shop
    if request.method == 'POST':
        remaining = products_remaining(shop)
        if remaining == 0:
            messages.error(request, f"আপনার প্যাকেজে সর্বোচ্চ {product_limit(shop)}টা প্রোডাক্ট রাখা যায়। "
                                    "আরও যোগ করতে Billing থেকে প্যাকেজ আপগ্রেড করুন।")
            return redirect('product_list')

        form = ProductForm(request.POST, request.FILES)
        try:
            rows = variants.rows_from_post(request.POST)
        except variants.VariantError as exc:
            rows = None
            messages.error(request, str(exc))
        if rows is not None and form.is_valid():
            product = form.save(commit=False)
            product.shop = shop
            product.save()
            variants.save_rows(product, rows)
            messages.success(request, "প্রোডাক্ট যোগ হয়েছে।")
            return redirect('product_list')
    else:
        form = ProductForm()
    return render(request, 'store/add_product.html', {'form': form, 'variant_rows': _variant_rows(request, None)})


@login_required(login_url='/accounts/login/')
def edit_product(request, pk):
    product = get_object_or_404(Product, pk=pk, shop=request.user.shop)
    if request.method == 'POST':
        form = ProductForm(request.POST, request.FILES, instance=product)
        try:
            rows = variants.rows_from_post(request.POST)
        except variants.VariantError as exc:
            rows = None
            messages.error(request, str(exc))
        if rows is not None and form.is_valid():
            form.save()
            variants.save_rows(product, rows)
            messages.success(request, "প্রোডাক্ট আপডেট হয়েছে।")
            return redirect('product_list')
    else:
        form = ProductForm(instance=product)
    return render(request, 'store/edit_product.html', {'form': form, 'product': product,
                                                       'variant_rows': _variant_rows(request, product)})


@login_required(login_url='/accounts/login/')
def delete_product(request, pk):
    product = get_object_or_404(Product, pk=pk, shop=request.user.shop)
    if request.method == 'POST':
        product.delete()
        messages.success(request, "Product deleted!")
        return redirect('product_list')
    return render(request, 'store/delete_product.html', {'product': product})


# ============================================================
# ORDER MANAGEMENT (Multi-Product)
# ============================================================
@login_required(login_url='/accounts/login/')
def order_create(request):
    shop = request.user.shop

    if request.method == 'POST':
        c_name = request.POST.get('customer_name')
        c_phone = request.POST.get('customer_phone')
        c_address = request.POST.get('customer_address')
        delivery_charge = float(request.POST.get('delivery_charge') or 0)
        discount = float(request.POST.get('discount') or 0)
        payment_method = request.POST.get('payment_method', 'COD')

        customer, created = Customer.objects.get_or_create(
            shop=shop, phone=c_phone,
            defaults={'name': c_name, 'address': c_address}
        )
        if not created:
            customer.name = c_name
            customer.address = c_address
            customer.save()

        order = Order.objects.create(
            shop=shop, customer=customer,
            delivery_charge=delivery_charge, discount=discount,
            payment_method=payment_method, status='Pending', total_amount=0
        )

        product_ids = request.POST.getlist('product[]')
        prices = request.POST.getlist('price[]')
        quantities = request.POST.getlist('quantity[]')
        subtotal = 0

        for i in range(len(product_ids)):
            p_id = product_ids[i]
            if p_id:
                price = float(prices[i] or 0)
                qty = int(quantities[i] or 1)
                # ড্রপডাউনের মান: প্রোডাক্টের id, আর সাইজ/রং হলে ঋণাত্মক ভ্যারিয়েন্ট id (store/variants.py)
                try:
                    item = variants.resolve(shop, [int(p_id)]).get(int(p_id))
                except ValueError:
                    item = None
                if item is None or item.needs_choice:
                    continue
                OrderItem.objects.create(
                    order=order, product=item.product, variant=item.variant, variant_name=item.variant_name,
                    price=price, quantity=qty, cost_price=item.cost_price
                )
                if item.stock > 0:
                    variants.take(item, min(qty, item.stock))
                subtotal += price * qty

        order.total_amount = max(0, subtotal + delivery_charge - discount)
        order.save()
        messages.success(request, f"Order #ORD-{order.id} created successfully!")
        return redirect('order_list')

    options = []
    for product in (Product.objects.filter(shop=shop, is_active=True, stock_quantity__gt=0)
                    .prefetch_related('variants').order_by('name')):
        if product.has_variants:
            options += [{'id': -v.id, 'name': f'{product.name} ({v.name})', 'price': v.sell_price,
                         'stock': v.stock_quantity} for v in product.variants.all() if v.stock_quantity > 0]
        else:
            options.append({'id': product.id, 'name': product.name, 'price': product.price,
                            'stock': product.stock_quantity})
    return render(request, 'store/order_create.html', {'products': options})


@login_required(login_url='/accounts/login/')
def order_list(request):
    shop = request.user.shop
    orders = (Order.objects.filter(shop=shop).select_related('customer')
              .prefetch_related('items__product', 'items__variant').order_by('-id'))   # প্রতি অর্ডারে আলাদা query না

    search_query = request.GET.get('q', '').strip()
    if search_query:
        # "#1269", "ORD-1269" বা বাংলা সংখ্যা দিলেও অর্ডার নম্বর ধরে
        number = search_query.lstrip('#').upper().removeprefix('ORD-').translate(BN_TO_EN_DIGITS)
        query = Q(customer__name__icontains=search_query) | Q(customer__phone__icontains=search_query.translate(BN_TO_EN_DIGITS))
        if number.isdigit():
            query |= Q(id=int(number))
        orders = orders.filter(query)

    status_filter = request.GET.get('status', '')
    if status_filter:
        orders = orders.filter(status=status_filter)

    paginator = Paginator(orders, 20)
    page = request.GET.get('page', 1)
    try:
        page_obj = paginator.page(page)
    except (EmptyPage, PageNotAnInteger):
        page_obj = paginator.page(1)
    risk.attach(shop, page_obj.object_list, lambda o: o.customer.phone)
    return render(request, 'store/orders.html', {
        'courier_connected': couriers.connected(request.user.shop),
        'prepaid_methods': sorted(couriers.PREPAID_METHODS),
        'orders': page_obj,        # FIX: page_obj passed as 'orders' so template loop works
        'page_obj': page_obj,      # kept for pagination controls in template
        'search_query': search_query,
        'status_filter': status_filter,
    })


@login_required(login_url='/accounts/login/')
def order_edit(request, order_id):
    shop = request.user.shop
    order = get_object_or_404(Order, id=order_id, shop=shop)
    if request.method == 'POST':
        customer = order.customer
        customer.name = request.POST.get('customer_name')
        customer.phone = request.POST.get('customer_phone')
        customer.address = request.POST.get('customer_address')
        customer.save()
        order.total_amount = request.POST.get('total_amount')
        order.save()
        messages.success(request, f'Order #ORD-{order.id} updated!')
        return redirect('order_list')
    return render(request, 'store/order_edit.html', {'order': order})


@login_required(login_url='/accounts/login/')
def order_delete(request, order_id):
    shop = request.user.shop
    order = get_object_or_404(Order, id=order_id, shop=shop)
    try:
        if not order.stock_returned:        # বাতিল/ফেরত হয়ে মাল আগেই স্টকে ফিরে থাকলে আবার না
            for item in order.items.all():
                variants.give_back(item.product_id, item.variant_id, item.quantity)
        order.delete()
        messages.success(request, f'Order #ORD-{order_id} deleted & stock restored!')
    except Exception as e:
        messages.error(request, f'Delete failed: {str(e)}')
    return redirect('order_list')


# ============================================================
# ORDER STATUS (AJAX)
# ============================================================
@login_required(login_url='/accounts/login/')
def update_order_status(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            shop = request.user.shop
            order = Order.objects.select_related('shop', 'customer').get(id=data.get('order_id'), shop=shop)
            order_flow.set_status(order, data.get('status'))
            return JsonResponse({'success': True,
                                 'message': f'অর্ডার #{order.id} এখন "{order_flow.STATUS_BN[order.status]}"'})
        except order_flow.FlowError as exc:
            return JsonResponse({'success': False, 'error': str(exc)})
        except Order.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'অর্ডারটা পাওয়া যায়নি।'})
        except Exception:
            return JsonResponse({'success': False, 'error': 'অবস্থা বদলানো যায়নি, আবার চেষ্টা করুন।'})
    return JsonResponse({'success': False, 'error': 'POST লাগবে'}, status=405)


# ============================================================
# INVOICE
# ============================================================
@login_required(login_url='/accounts/login/')
def invoice_view(request, order_id):
    shop = request.user.shop
    order = get_object_or_404(Order, id=order_id, shop=shop)
    order_items = order.items.all()
    subtotal = order.total_amount - order.delivery_charge
    return render(request, 'store/invoice.html', {
        'shop': shop, 'order': order,
        'order_items': order_items, 'subtotal': subtotal
    })


# ============================================================
# CUSTOMER LIST
# ============================================================
@login_required(login_url='/accounts/login/')
def customer_list(request):
    shop = request.user.shop
    customers = Customer.objects.filter(shop=shop).annotate(
        total_orders=Count('orders'),
        total_spent=Sum('orders__total_amount'),
        returned_orders=Count('orders', filter=Q(orders__status__in=['Returned', 'Cancelled']))
    ).prefetch_related('orders').order_by('-id')
    q = request.GET.get('q', '')
    if q:
        customers = customers.filter(Q(name__icontains=q) | Q(phone__icontains=q))
    paginator = Paginator(customers, 25)
    page = request.GET.get('page', 1)
    try:
        page_obj = paginator.page(page)
    except (EmptyPage, PageNotAnInteger):
        page_obj = paginator.page(1)
    risk.attach(shop, page_obj.object_list, lambda c: c.phone)
    return render(request, 'store/customers.html', {'page_obj': page_obj})


@login_required(login_url='/accounts/login/')
def customer_block(request, customer_id):
    """ভুয়া অর্ডার দেওয়া নম্বর ব্লক/আনব্লক: ব্লক থাকলে ওয়েবসাইট থেকে সেই নম্বরে অর্ডার নেওয়া হয় না।"""
    customer = get_object_or_404(Customer, pk=customer_id, shop=request.user.shop)
    if request.method == 'POST' and customer.phone != risk.WALK_IN_PHONE:
        customer.is_blocked = request.POST.get('block') == '1'
        customer.save(update_fields=['is_blocked'])
        messages.success(request, f'{customer.phone} ব্লক করা হয়েছে। এই নম্বর থেকে ওয়েবসাইটে আর অর্ডার নেওয়া হবে না।'
                         if customer.is_blocked else f'{customer.phone}-এর ব্লক তুলে দেওয়া হয়েছে।')
    return redirect(request.POST.get('next') or 'customer_list')


@login_required(login_url='/accounts/login/')
def order_risk(request):
    """অর্ডার লেখার সময় মোবাইল নম্বর দিলে তার আগের ডেলিভারি-ফেরতের হিসাব (JSON)।"""
    phone = _storefront_customer_phone(request.GET.get('phone', ''))
    if not phone:
        return JsonResponse({'ok': False})
    shop = request.user.shop
    customer = Customer.objects.filter(shop=shop, phone=phone).order_by('-id').first()
    return JsonResponse({'ok': True, 'phone': phone, **risk.for_phone(shop, phone).as_dict(),
                         'name': customer.name if customer else '',
                         'address': customer.address if customer else ''})


# ============================================================
# REPORTS
# ============================================================
import csv
from django.http import HttpResponse


@login_required(login_url='/accounts/login/')
def business_reports(request):
    """ব্যবসার রিপোর্ট: সময় বেছে বিক্রি, লাভ, কোথা থেকে বিক্রি, সেরা প্রোডাক্ট-কাস্টমার, কখন বেশি বিক্রি। হিসাব store/reports.py-তে।"""
    from . import reports
    shop = request.user.shop
    period = reports.resolve_period(request.GET)

    if request.GET.get('export') in ('excel', 'xlsx'):
        workbook = reports.build_workbook(shop, period)
        response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = (f'attachment; filename="{shop.slug}-report-{period.start:%Y%m%d}-'
                                           f'{period.end:%Y%m%d}.xlsx"')
        workbook.save(response)
        return response

    from . import ledger
    from .dashboard import _change
    current = reports.summary(shop, period.start, period.end)
    previous = reports.summary(shop, period.prev_start, period.prev_end)
    pl = reports.profit_and_loss(shop, period.start, period.end, current)
    prev_pl = reports.profit_and_loss(shop, period.prev_start, period.prev_end, previous)
    query = request.GET.copy()
    query['export'] = 'xlsx'
    return render(request, 'store/reports.html', {
        'shop': shop,
        'period': period,
        'presets': reports.PRESETS,
        'today': timezone.localdate(),
        's': current,
        'prev': previous,
        'change': reports.compare(current, previous),
        'pl': pl,
        'prev_pl': prev_pl,
        'net_change': _change(pl['net'], prev_pl['net']) if prev_pl['net'] > 0 else None,
        'buying': ledger.purchase_summary(shop, period.start, period.end),
        'trend': reports.trend(shop, period.start, period.end),
        'payments': reports.payment_methods(shop, period.start, period.end),
        'products': reports.product_rows(shop, period.start, period.end, limit=10),
        'categories': reports.categories(shop, period.start, period.end),
        'customers': reports.customer_rows(shop, period.start, period.end, limit=8),
        'mix': reports.customer_mix(shop, period.start, period.end),
        'hours': reports.by_hour(shop, period.start, period.end),
        'weekdays': reports.by_weekday(shop, period.start, period.end),
        'delivery': reports.online_delivery(shop, period.start, period.end),
        'stock': reports.stock_value(shop),
        'dues': reports.dues(shop, period.start, period.end),
        'orders': reports.order_rows(shop, period.start, period.end, limit=30),
        'channels': reports.CHANNELS,
        'export_url': f"{reverse('reports')}?{query.urlencode()}",
    })


# ============================================================
# SETTINGS
# ============================================================
SETTINGS_TABS = [
    ('courier', 'bi-truck', 'কুরিয়ার'),
    ('pos', 'bi-printer', 'POS ও রসিদ'),
    ('facebook', 'bi-facebook', 'Facebook'),
]
SETTINGS_FORMS = {
    'steadfast': SteadfastSettingsForm,
    'pathao': PathaoSettingsForm,
    'redx': RedxSettingsForm,
    'pos': PosSettingsForm,
}
SECTION_TABS = {'pos': 'pos'}     # বাকি সব section কুরিয়ার ট্যাবের (SMS এখন আলাদা SMS প্যানেলে)
# পুরনো ফর্ম (বা কোনো বাটন) section না পাঠালে বাটনের নাম দেখে বোঝা হয় কোন ভাগ
COURIER_ACTION_SECTIONS = {
    'test_Steadfast': 'steadfast', 'steadfast_disconnect': 'steadfast',
    'test_Pathao': 'pathao', 'pathao_connect': 'pathao', 'pathao_disconnect': 'pathao',
    'test_RedX': 'redx', 'redx_disconnect': 'redx',
}


def _settings_url(tab, anchor=''):
    return f"{reverse('settings')}?tab={tab}" + (f'#{anchor}' if anchor else '')


@login_required(login_url='/accounts/login/')
def shop_settings(request):
    """
    Settings: কুরিয়ার, POS আর Facebook — প্রতিটা কুরিয়ার আলাদা ফর্ম, তাই একটা সেভ করলে বাকিগুলোর কিছু বদলায় না।
    দোকানের তথ্য, ডেলিভারি, পেমেন্ট "ওয়েবসাইট" পেইজে; SMS আলাদা SMS প্যানেলে।
    """
    shop = request.user.shop
    if request.GET.get('tab') == 'sms':          # পুরনো লিংক
        return redirect('sms_panel')
    tab_keys = [key for key, _icon, _label in SETTINGS_TABS]
    active_tab = request.GET.get('tab') if request.GET.get('tab') in tab_keys else 'courier'
    forms_by_section = {}

    if request.method == 'POST':
        action = request.POST.get('courier_action', '')
        section = request.POST.get('section') or COURIER_ACTION_SECTIONS.get(action, '')
        if section not in SETTINGS_FORMS:
            messages.error(request, 'কিছু সেভ হয়নি, পেইজটা রিফ্রেশ করে আবার চেষ্টা করুন।')
            return redirect('settings')
        tab = SECTION_TABS.get(section, 'courier')
        if action.endswith('_disconnect'):
            _courier_disconnect(request, shop, action, section)
            return redirect(_settings_url(tab, section))
        form = SETTINGS_FORMS[section](request.POST, instance=shop)
        if form.is_valid() and _save_settings_section(request, shop, form, section, action):
            return redirect(_settings_url(tab, section))
        # ফর্ম ভুল বা কুরিয়ার মানেনি: যা টাইপ করেছিলেন তা রেখে ভুলটা দেখানো হয়; দোকানে কিছু সেভ হয়নি
        shop.refresh_from_db()
        if section == 'pathao' and bool(shop.pathao_access_token) != form.connected:
            form = PathaoSettingsForm(instance=shop)    # টোকেন পাওয়া গেছে কিন্তু স্টোর নেই
        forms_by_section[section] = form
        active_tab = tab

    for section, form_class in SETTINGS_FORMS.items():
        forms_by_section.setdefault(section, form_class(instance=shop))
    shop.ensure_webhook_token()
    connected = couriers.connected(shop)
    fb_page = getattr(shop, 'fb_page', None)
    return render(request, 'store/settings.html', {
        'shop': shop,
        'tabs': SETTINGS_TABS,
        'active_tab': active_tab,
        'steadfast_form': forms_by_section['steadfast'],
        'pathao_form': forms_by_section['pathao'],
        'redx_form': forms_by_section['redx'],
        'pos_form': forms_by_section['pos'],
        'courier_connected': connected,
        'courier_count': sum(connected.values()),
        'facebook_allowed': has_facebook(shop),
        'fb_page': fb_page,
        'fb_recent_replies': shop.fb_comment_replies.select_related('product')[:5] if fb_page else [],
        'steadfast_webhook_url': request.build_absolute_uri(reverse('steadfast_webhook')),
        'days_left': shop.days_remaining(),
    })


def _courier_disconnect(request, shop, action, section=''):
    if action == 'steadfast_disconnect':
        shop.steadfast_api_key = None
        shop.steadfast_secret_key = None
        shop.save(update_fields=['steadfast_api_key', 'steadfast_secret_key'])
        messages.info(request, 'Steadfast-এর সংযোগ সরানো হয়েছে।', extra_tags=section)
    elif action == 'redx_disconnect':
        shop.redx_access_token = None
        shop.save(update_fields=['redx_access_token'])
        messages.info(request, 'RedX-এর সংযোগ সরানো হয়েছে।', extra_tags=section)
    elif action == 'pathao_disconnect':
        shop.pathao_access_token = None
        shop.pathao_refresh_token = ''
        shop.pathao_token_expires_at = None
        shop.pathao_client_secret = ''
        shop.pathao_stores = []
        shop.pathao_store_id = None
        shop.save(update_fields=['pathao_access_token', 'pathao_refresh_token', 'pathao_token_expires_at',
                                 'pathao_client_secret', 'pathao_stores', 'pathao_store_id'])
        messages.info(request, 'Pathao-র সংযোগ সরানো হয়েছে।', extra_tags=section)


def _save_settings_section(request, shop, form, section, action):
    """
    ঠিকঠাক ফর্ম সেভ করে। True = সব ঠিক, False = কুরিয়ার চাবি মানেনি (কিছু সেভ হয়নি)।
    "যুক্ত করুন" / "কানেকশন টেস্ট" চাপলে আগে কুরিয়ারের সাথে মিলিয়ে দেখা হয়, তারপর সেভ;
    তাই ভুল চাবি দিয়ে চালু থাকা সংযোগ নষ্ট হয় না।
    """
    if section == 'pos':
        form.save()
        messages.success(request, 'POS আর রসিদের সেটিং সেভ হয়েছে।', extra_tags=section)
        return True

    if section == 'pathao' and not form.connected:
        data = form.cleaned_data
        try:
            stores = couriers.pathao_connect(shop, data['pathao_client_id'], data['pathao_client_secret'],
                                             data['pathao_email'], data['pathao_password'])
        except couriers.CourierError as exc:
            messages.error(request, str(exc), extra_tags=section)
            return False
        messages.success(request, f'Pathao যুক্ত হয়েছে ({len(stores)}টা স্টোর পাওয়া গেছে)। '
                                  'আপনার Pathao পাসওয়ার্ড আমরা সেভ করি না।', extra_tags=section)
        return True

    courier = action[5:] if action.startswith('test_') else ''
    if courier in couriers.COURIERS:
        candidate = form.save(commit=False)      # এখনো ডাটাবেসে যায়নি
        try:
            result = couriers.test_connection(candidate, courier)
        except couriers.CourierError as exc:
            messages.error(request, f'{exc} কিছু সেভ হয়নি।', extra_tags=section)
            return False
        candidate.save(update_fields=[name for name in form._meta.fields if name in form.fields])
        messages.success(request, result, extra_tags=section)
        return True

    form.save()
    messages.success(request, 'সেভ হয়েছে।', extra_tags=section)
    return True


# ============================================================
# COURIER (STEADFAST)
# ============================================================
@login_required(login_url='/accounts/login/')
def send_to_courier(request):
    if request.method != 'POST':
        return redirect('order_list')
    shop = request.user.shop
    order = get_object_or_404(Order.objects.select_related('customer'), id=request.POST.get('order_id'), shop=shop)
    courier = request.POST.get('courier_partner')

    if order.steadfast_tracking_code:
        messages.warning(request, f'এই অর্ডার আগেই {order.courier_partner or "কুরিয়ারে"} পাঠানো হয়েছে।')
        return redirect('order_list')
    if order.status in ('Cancelled', 'Returned', 'Delivered'):
        messages.error(request, f'{order.status} অর্ডার কুরিয়ারে পাঠানো যায় না।')
        return redirect('order_list')

    try:
        result = couriers.send(shop, order, courier, area_id=request.POST.get('redx_area_id'),
                               note=request.POST.get('note', '').strip())
    except couriers.CourierError as exc:
        messages.error(request, str(exc))
        return redirect('order_list')

    # ট্র্যাকিং কোড সব কুরিয়ারের জন্য এই ফিল্ডেই থাকে (নামটা পুরনো)
    order.steadfast_tracking_code = str(result['tracking_code'])[:100]
    order.courier_partner = courier
    order.save(update_fields=['steadfast_tracking_code', 'courier_partner'])
    order_flow.set_status(order, 'Shipped')         # চালু থাকলে কাস্টমারকে ট্র্যাকিং লিংকসহ SMS
    cod = couriers.cod_amount(order)
    messages.success(request, f'{courier}-এ পাঠানো হয়েছে। ট্র্যাকিং: {result["tracking_code"]} · '
                              + (f'কাস্টমারের কাছ থেকে তুলবে ৳{cod}' if cod else 'আগে পরিশোধ, কিছু তুলবে না'))
    return redirect('order_list')


@login_required(login_url='/accounts/login/')
def redx_areas(request):
    """অর্ডার পেইজে RedX-এর এলাকা বাছাইয়ের লিস্ট।"""
    try:
        areas = couriers.redx_areas(request.user.shop)
    except couriers.CourierError as exc:
        return JsonResponse({'ok': False, 'message': str(exc)}, status=400)
    return JsonResponse({'ok': True, 'areas': areas})


@login_required(login_url='/accounts/login/')
def courier_dashboard(request):
    shop = request.user.shop
    courier_orders = Order.objects.filter(shop=shop).exclude(
        steadfast_tracking_code__isnull=True
    ).exclude(steadfast_tracking_code__exact='').order_by('-created_at')
    # Stats
    from django.db.models import Count as DCount
    delivered = courier_orders.filter(status='Delivered').count()
    shipped = courier_orders.filter(status='Shipped').count()
    cancelled = courier_orders.filter(status='Cancelled').count()
    total = courier_orders.count()
    courier_stats = [
        ('Total', total, '#3b82f6', 'truck'),
        ('Shipped', shipped, '#8b5cf6', 'truck-front'),
        ('Delivered', delivered, '#22c55e', 'check-circle'),
        ('Cancelled', cancelled, '#ef4444', 'x-circle'),
    ]
    paginator = Paginator(courier_orders, 20)
    page = request.GET.get('page', 1)
    try:
        page_obj = paginator.page(page)
    except (EmptyPage, PageNotAnInteger):
        page_obj = paginator.page(1)
    return render(request, 'store/courier.html', {'page_obj': page_obj, 'courier_stats': courier_stats})


# ============================================================
# STEADFAST WEBHOOK
# ============================================================
@csrf_exempt
def steadfast_webhook(request):
    """
    Steadfast প্যানেলের Webhook পেইজে Callback URL আর Auth Token (Settings-এ দেখানো) বসাতে হয়।
    Steadfast প্রতিটা request-এ "Authorization: Bearer <token>" পাঠায়; মিললে তবেই অর্ডার বদলায়।
    """
    if request.method != 'POST':
        return JsonResponse({'message': 'Webhook active'}, status=200)
    try:
        data = json.loads(request.body or b'{}')
    except ValueError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    invoice = str(data.get('invoice') or '')
    order_id = invoice[4:] if invoice.startswith('ORD-') else ''
    order = Order.objects.select_related('shop').filter(id=order_id).first() if order_id.isdigit() else None
    if order is None:
        # অন্য সিস্টেমের পার্সেল হতে পারে; Steadfast 4xx পেলে আর পাঠায় না, তাই 200
        return JsonResponse({'message': 'Unknown invoice, ignored'}, status=200)

    import hmac
    auth = request.headers.get('Authorization', '')
    token = auth[7:].strip() if auth.lower().startswith('bearer ') else ''
    expected = order.shop.courier_webhook_token
    if not expected or not token or not hmac.compare_digest(token, expected):
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    notification = data.get('notification_type') or 'delivery_status'
    status = str(data.get('status') or '').lower()
    if notification == 'delivery_status' and status:
        new_status = {'delivered': 'Delivered', 'partial_delivered': 'Delivered', 'cancelled': 'Returned'}.get(status)
        if new_status and order.status != new_status:
            try:
                order_flow.set_status(order, new_status)
            except order_flow.FlowError:
                pass
    return JsonResponse({'message': 'OK'}, status=200)


# ============================================================
# PUBLIC STOREFRONT
# ============================================================
def public_shop(request, shop_slug):
    shop = get_object_or_404(Shop, slug=shop_slug)

    if not storefront_is_open(shop):
        return render(request, 'store/storefront/offline.html', {'shop': shop})

    products = Product.objects.filter(shop=shop, is_active=True, stock_quantity__gt=0)
    return render(request, 'store/public_shop.html', {'shop': shop, 'products': products})


# ============================================================
# BILLING
# ============================================================
# billing_page moved below with full payment request support


@login_required(login_url='/accounts/login/')
def payment_success(request, plan_name):
    shop = request.user.shop

    # ── Step 1: valid plan name check ──
    VALID_PLANS = ['Basic', 'Standard', 'Premium']
    if plan_name not in VALID_PLANS:
        messages.error(request, "Invalid plan.")
        return redirect('billing')

    # ── Step 2: PaymentRequest must exist & be Approved by admin ──
    approved = PaymentRequest.objects.filter(
        shop=shop,
        plan_name=plan_name,
        status='Approved'
    ).order_by('-created_at').first()

    if not approved:
        messages.warning(
            request,
            "আপনার পেমেন্ট এখনো admin verify করেননি। "
            "Approve হলে plan automatically upgrade হবে।"
        )
        return redirect('billing')

    # ── Step 3: upgrade only if not already on this plan ──
    if shop.subscription_plan != plan_name:
        shop.subscription_plan = plan_name
        shop.save(update_fields=['subscription_plan'])

    messages.success(request, f"আপনার দোকান এখন {plan_name} প্ল্যানে।")
    return redirect('dashboard')


# ============================================================
# MASTER HQ: store/hq_views.py (ড্যাশবোর্ড, দোকান, ইউজার, পেমেন্ট, SMS, নোটিশ, সেটিংস)
# ============================================================
@login_required(login_url='/accounts/login/')
def master_domain_live(request, shop_id):
    """মালিক হোস্টিংয়ে ডোমেইন যোগ করে SSL হওয়ার পর "চালু" চাপলে: অবস্থা live, সেলারকে SMS।"""
    if not request.user.is_superuser:
        return redirect('dashboard')
    if request.method == 'POST':
        from . import domains
        shop = get_object_or_404(Shop, pk=shop_id)
        domains.mark_live(shop)
        from . import hq
        hq.log_action(request, 'domain_live', shop, shop.custom_domain or '')
        messages.success(request, f'{shop.custom_domain} চালু করা হয়েছে, সেলারকে SMS গেছে।')
    target = request.POST.get('next', '')
    return redirect(target if target.startswith('/saas-master/') else 'master_dashboard')


# POS (দোকানে বিক্রি): store/views_pos.py


# ============================================================
# E-COMMERCE STOREFRONT (Customer-facing)
# ============================================================
from .models import StorefrontOrder, StorefrontOrderItem, StorefrontPayment
from django.utils import timezone
from .models import PageView  # PageView মডেলটা ইম্পোর্ট করবেন

def get_client_ip(request):
    """ভিজিটরের আসল IP Address বের করার ফাংশন"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip

import random

SOLD_STATUSES = ('Shipped', 'Delivered')


def _attach_sold_counts(shop, products):
    """প্রতিটা প্রোডাক্টে product.sold_count: পাঠানো বা ডেলিভারি হওয়া অর্ডারে মোট কয়টা গেছে।"""
    ids = [p.id for p in products]
    counts = {}
    if ids and shop.show_sold_count:
        counts = dict(OrderItem.objects.filter(order__shop=shop, order__status__in=SOLD_STATUSES, product_id__in=ids)
                      .values('product_id').annotate(total=Sum('quantity')).values_list('product_id', 'total'))
    for p in products:
        p.sold_count = counts.get(p.id, 0)


STOREFRONT_PAGE_SIZE = 24
STOREFRONT_SORTS = [
    ('new', 'নতুন আগে'),
    ('popular', 'জনপ্রিয়'),
    ('price_asc', 'কম দাম আগে'),
    ('price_desc', 'বেশি দাম আগে'),
    ('discount', 'বেশি ছাড়'),
]


def _track_storefront_view(request, shop, product=None):
    """দিনে একই ব্রাউজার থেকে একবার গোনা হয় (ড্যাশবোর্ডের ভিজিটর হিসাব)।"""
    if not request.session.session_key:
        request.session.create()
    session_key = request.session.session_key
    seen = PageView.objects.filter(shop=shop, product=product, session_key=session_key,
                                   created_at__date=timezone.now().date()).exists()
    if not seen:
        PageView.objects.create(shop=shop, product=product, ip_address=get_client_ip(request),
                                session_key=session_key)


def _visible_products(shop):
    return Product.objects.filter(shop=shop, is_active=True, stock_quantity__gt=0)


def _sorted_products(products, sort):
    from django.db.models import Case, DecimalField, ExpressionWrapper, Value, When
    if sort == 'price_asc':
        return products.order_by('price', '-id')
    if sort == 'price_desc':
        return products.order_by('-price', '-id')
    if sort == 'popular':
        return products.annotate(
            sold=Sum('orderitem__quantity', filter=Q(orderitem__order__status__in=SOLD_STATUSES))
        ).order_by(F('sold').desc(nulls_last=True), '-id')
    if sort == 'discount':
        saving = ExpressionWrapper(F('compare_price') - F('price'), output_field=DecimalField())
        return products.annotate(
            saving=Case(When(compare_price__gt=F('price'), then=saving), default=Value(0),
                        output_field=DecimalField())
        ).order_by('-saving', '-id')
    return products.order_by('-created_at', '-id')


def _top_seller_ids(shop):
    """সবচেয়ে বেশি বিক্রি হওয়া ৪টা প্রোডাক্ট ("বেশি বিক্রি" ব্যাজের জন্য)।"""
    if not shop.show_sold_count:
        return set()
    rows = (OrderItem.objects.filter(order__shop=shop, order__status__in=SOLD_STATUSES, product__is_active=True)
            .values('product_id').annotate(total=Sum('quantity')).order_by('-total')[:4])
    return {row['product_id'] for row in rows}


@ensure_csrf_cookie
def storefront_home(request, shop_slug, category_id=None):
    """দোকানের ওয়েবসাইটের হোম আর ক্যাটাগরি পেইজ: ২৪টা করে প্রোডাক্ট, "আরও দেখুন" চাপলে পরেরগুলো।"""
    from urllib.parse import urlencode
    from . import seo
    shop = get_object_or_404(Shop, slug=shop_slug)

    # ট্রায়ালে আর সব প্ল্যানে চালু; মেয়াদ শেষের পর ৭ দিন পর্যন্ত চালু, তারপর বন্ধ
    if not storefront_is_open(shop):
        return render(request, 'store/storefront/offline.html', {'shop': shop})

    search = (request.GET.get('q') or '').strip()[:100]
    sort = request.GET.get('sort') if request.GET.get('sort') in dict(STOREFRONT_SORTS) else 'new'

    # পুরনো ?cat=5 লিংক → /category/5/
    old_cat = request.GET.get('cat', '')
    if category_id is None and old_cat.isdigit() and Category.objects.filter(shop=shop, pk=old_cat).exists():
        query = {k: v for k, v in (('q', search), ('sort', sort if sort != 'new' else '')) if v}
        link = storefront_link(shop, 'storefront_category', int(old_cat), request=request)
        return redirect(link + (f'?{urlencode(query)}' if query else ''))

    category = get_object_or_404(Category, shop=shop, pk=category_id) if category_id is not None else None
    partial = request.GET.get('partial') == '1'
    if not partial:
        _track_storefront_view(request, shop)

    products = _visible_products(shop).select_related('category')
    if category:
        products = products.filter(category=category)
    if search:
        products = products.filter(Q(name__icontains=search) | Q(description__icontains=search))
    page_obj = Paginator(_sorted_products(products, sort), STOREFRONT_PAGE_SIZE).get_page(request.GET.get('page'))
    page_products = list(page_obj.object_list)
    _attach_sold_counts(shop, page_products)
    reviews.attach(page_products)

    next_url = ''
    if page_obj.has_next():
        query = {k: v for k, v in (('q', search), ('sort', sort if sort != 'new' else ''),
                                   ('page', page_obj.next_page_number())) if v}
        next_url = f'?{urlencode(query)}'
    card_context = {'shop': shop, 'products': page_products, 'top_seller_ids': _top_seller_ids(shop)}

    if partial:   # "আরও দেখুন": শুধু পরের কার্ডগুলো
        response = render(request, 'store/storefront/_product_cards.html', card_context)
        response['X-Next-Page'] = next_url
        return response

    is_landing = not category and not search and page_obj.number == 1
    sale_products = []
    if is_landing:
        sale_products = list(_visible_products(shop).filter(compare_price__gt=F('price'))
                             .order_by('-created_at')[:10])

    if category:
        title = f'{category.name} — {shop.name}'
        description = sf_lang.t('{shop}-এ {category}: {n}টা প্রোডাক্ট। ঘরে বসে অর্ডার করুন।', shop, shop=shop.name,
                                category=category.name, n=page_obj.paginator.count)
        meta = seo.storefront_meta(request, shop, title=title, description=description,
                                   link_name='storefront_category', link_args=(category.id,), noindex=bool(search))
    else:
        title = shop.name + (f' — {shop.storefront_tagline}' if shop.storefront_tagline else '')
        meta = seo.storefront_meta(request, shop, title=title, noindex=bool(search or page_obj.number > 1))

    categories = _storefront_categories(shop)

    return render(request, 'store/storefront/home.html', {
        **card_context,
        'meta': meta,
        'shop_ld': seo.shop_ld(request, shop, meta) if is_landing else '',
        'page_obj': page_obj,
        'total_count': page_obj.paginator.count,
        'next_url': next_url,
        'sale_products': sale_products,
        'categories': categories,
        'category': category,
        'banners': Banner.objects.filter(shop=shop, is_active=True).order_by('-id') if is_landing else [],
        'search': search,
        'sort': sort,
        'sorts': STOREFRONT_SORTS,
        'is_landing': is_landing,
        **_checkout_context(shop),
    })


def _storefront_categories(shop):
    """যেসব ক্যাটাগরিতে বিক্রির মতো প্রোডাক্ট আছে — ওয়েবসাইটের ক্যাটাগরি বার আর নিচের মেনুর তালিকা।"""
    return list(Category.objects.filter(shop=shop, product__is_active=True, product__stock_quantity__gt=0)
                .distinct().order_by('name'))


@ensure_csrf_cookie
def storefront_product_detail(request, shop_slug, product_id):
    """কাস্টমারের দেখার প্রোডাক্ট পেইজ, সাথে একই ক্যাটাগরির আরও প্রোডাক্ট।"""
    from . import seo
    shop = get_object_or_404(Shop, slug=shop_slug)

    if not storefront_is_open(shop):
        return redirect(storefront_link(shop, request=request))

    product = get_object_or_404(Product.objects.select_related('category'), id=product_id, shop=shop,
                                is_active=True)
    _track_storefront_view(request, shop, product)

    related_products = list(_visible_products(shop).filter(category=product.category)
                            .exclude(id=product.id).order_by('-id')[:4])
    _attach_sold_counts(shop, [product] + related_products)

    price = f'৳{product.price:.0f}'
    if product.discount_percent:
        price += sf_lang.t(' ({p}% ছাড়)', shop, p=str(product.discount_percent))   # দামের মতো ইংরেজি অঙ্ক
    checkout = _checkout_context(shop)
    extra = sf_lang.t('ক্যাশ অন ডেলিভারি।' if checkout['cod_allowed'] else 'ঘরে বসে অর্ডার করুন।', shop)
    description = (f'{price} · ' + (product.description or '') if product.description
                   else sf_lang.t('{price} · {shop} থেকে অর্ডার করুন। {extra}', shop, price=price, shop=shop.name, extra=extra))
    meta = seo.storefront_meta(
        request, shop, title=f'{product.name} — {shop.name}', description=description,
        image=product.image, image_size=(product.image_width, product.image_height),
        link_name='storefront_product_detail', link_args=(product.id,), og_type='product',
        price=product.price)

    variant_list = [{'id': -v.id, 'name': v.name, 'price': float(v.sell_price), 'stock': v.stock_quantity}
                    for v in product.variants.all()] if product.has_variants else []
    reviews.attach([product] + related_products)
    review_msg = request.session.pop('review_msg', None)
    if review_msg and review_msg.get('product') != product.id:
        review_msg = None
    product_url = request.build_absolute_uri(storefront_link(shop, 'storefront_product_detail', product.id,
                                                             request=request))
    wa_text = sf_lang.t('আসসালামু আলাইকুম, আমি "{name}" ({price}) অর্ডার করতে চাই।', shop, name=product.name,
                        price=f'৳{product.price:.0f}') + f'\n{product_url}'
    return render(request, 'store/storefront/product_detail.html', {
        'shop': shop,
        'meta': meta,
        'product': product,
        'variant_list': variant_list,
        'review_list': reviews.approved_for(product, limit=20),
        'review_bars': reviews.stars_breakdown(product) if product.rating else [],
        'review_msg': review_msg,
        'product_ld': seo.product_ld(request, shop, product, meta, product.rating),
        'breadcrumb_ld': seo.breadcrumb_ld(request, shop, [
            (shop.name, storefront_link(shop, request=request))]
            + ([(product.category.name, storefront_link(shop, 'storefront_category', product.category_id, request=request))]
               if product.category_id else [])
            + [(product.name, storefront_link(shop, 'storefront_product_detail', product.id, request=request))]),
        'wa_text': wa_text,
        'related_products': related_products,
        'categories': _storefront_categories(shop),
        **checkout,
    })


def storefront_checkout(request, shop_slug):
    """চেকআউট এখন হোম পেইজের ভেতরেই (পপআপ); পুরনো লিংকে এলে হোম পেইজে পাঠানো হয়।"""
    shop = get_object_or_404(Shop, slug=shop_slug)
    return redirect(storefront_link(shop, request=request) + '#checkout')


def _checkout_context(shop):
    """চেকআউটের পপআপে লাগে: ডেলিভারি এলাকা আর পেমেন্টের অপশন।"""
    from . import delivery, shop_payments
    zones = delivery.zones_for(shop)
    choices = shop_payments.checkout_choices(shop)
    return {
        'delivery_zones': zones,
        'fallback_delivery': shop.delivery_charge if not zones else 0,
        'payment_choices': choices,
        'cod_allowed': shop_payments.CHOICE_COD in choices,
        'online_allowed': any(c != shop_payments.CHOICE_COD for c in choices),
    }


# ============================================================
# কাস্টমারের অর্ডার ট্র্যাক করা
# ============================================================
TRACK_STEPS = [('Pending', 'অর্ডার পেয়েছি', 'bi-bag-check-fill'), ('Confirmed', 'কনফার্ম হয়েছে', 'bi-patch-check-fill'),
               ('Shipped', 'কুরিয়ারে দেওয়া হয়েছে', 'bi-truck'), ('Delivered', 'ডেলিভারি হয়েছে', 'bi-house-heart-fill')]
COURIER_TRACK_URLS = {'steadfast': 'https://steadfast.com.bd/t/{code}',
                      'redx': 'https://redx.com.bd/track-parcel/?trackingId={code}'}


def _track_context(request, shop, order):
    from . import seo
    reached = [key for key, _l, _i in TRACK_STEPS].index(order.status) if order.status in (
        'Pending', 'Confirmed', 'Shipped', 'Delivered') else -1
    steps = [{'label': sf_lang.t(label, shop), 'icon': icon,
              'state': 'done' if index < reached or (index == reached == 3) else 'now' if index == reached else 'wait'}
             for index, (_key, label, icon) in enumerate(TRACK_STEPS)]
    courier = (order.courier_partner or '').strip()
    template = COURIER_TRACK_URLS.get(courier.lower())
    phone = order.customer.phone or ''
    return {
        'shop': shop, 'order': order, 'steps': steps, 'cancelled': order.status in order_flow.NOT_COUNTED,
        'status_label': sf_lang.status_label(order.status, shop),
        'items': list(order.items.select_related('product')),
        'courier': courier, 'tracking_code': order.steadfast_tracking_code or '',
        'courier_url': template.format(code=order.steadfast_tracking_code) if template and order.steadfast_tracking_code else '',
        'masked_phone': f'{phone[:3]}*****{phone[-3:]}' if len(phone) >= 8 else '',
        'order_day': timezone.localtime(order.created_at).date(),
        'wa_text': sf_lang.t('আমার অর্ডার নং {n}', shop, n=str(order.id)),
        'meta': seo.storefront_meta(request, shop, title=sf_lang.t('অর্ডার ট্র্যাক করুন — {shop}', shop, shop=shop.name), noindex=True,
                                    link_name='storefront_track'),
    }


def storefront_track(request, shop_slug):
    """কাস্টমার অর্ডার নম্বর আর মোবাইল নম্বর দিয়ে নিজের অর্ডারের অবস্থা দেখে।"""
    from . import seo
    shop = get_object_or_404(Shop, slug=shop_slug)
    number = request.GET.get('order', '').strip()
    phone = request.GET.get('phone', '').strip()
    error = ''
    if number or phone:
        digits = ''.join(ch for ch in number.translate(str.maketrans('০১২৩৪৫৬৭৮৯', '0123456789')) if ch.isdigit())
        clean_phone = _storefront_customer_phone(phone)
        order = (Order.objects.filter(shop=shop, pk=digits, customer__phone=clean_phone).exclude(source='pos').first()
                 if digits and len(digits) < 12 and clean_phone else None)
        if order is not None:
            return redirect(storefront_link(shop, 'storefront_track_order', order_flow.track_code(order),
                                            request=request))
        error = sf_lang.t('এই অর্ডার নম্বর আর মোবাইল নম্বর মিলিয়ে কোনো অর্ডার পাওয়া যায়নি। নম্বর দুটো আবার দেখে নিন।', shop)
    return render(request, 'store/storefront/track.html', {
        'shop': shop, 'order': None, 'error': error, 'number': number, 'phone': phone,
        'meta': seo.storefront_meta(request, shop, title=sf_lang.t('অর্ডার ট্র্যাক করুন — {shop}', shop, shop=shop.name),
                                    description=sf_lang.t('{shop}-এ দেওয়া অর্ডার এখন কোথায় আছে দেখুন।', shop, shop=shop.name),
                                    link_name='storefront_track'),
    })


def storefront_track_order(request, shop_slug, code):
    """SMS-এর লিংক বা খোঁজার পর: অর্ডারের অবস্থা। কোড না মিললে খোঁজার পেজে।"""
    shop = get_object_or_404(Shop, slug=shop_slug)
    order = order_flow.order_from_code(shop, code)
    if order is None:
        return redirect(storefront_link(shop, 'storefront_track', request=request))
    return render(request, 'store/storefront/track.html', _track_context(request, shop, order))


def _cart_subtotal(shop, cart):
    """কুপন যাচাই আর ড্রাফটের জন্য কার্টের দাম (সার্ভারের দামে)।"""
    from decimal import Decimal
    quantities = {}
    for item in cart or []:
        try:
            key, qty = int(item['id']), int(item['qty'])
        except (ValueError, TypeError, KeyError):
            continue
        if 0 < qty <= 999 and key:
            quantities[key] = quantities.get(key, 0) + qty
    chosen = variants.resolve(shop, quantities.keys())
    return sum((chosen[k].price * q for k, q in quantities.items() if k in chosen), Decimal('0')), chosen, quantities


def storefront_coupon_check(request, shop_slug):
    """চেকআউটে কুপন কোড লিখলে: কত ছাড় হবে (JSON)। আসল হিসাব অর্ডারের সময় আবার হয়।"""
    from . import delivery
    shop = get_object_or_404(Shop, slug=shop_slug)
    if request.method != 'POST':
        return JsonResponse({'ok': False}, status=405)
    try:
        data = json.loads(request.body or b'{}')
    except ValueError:
        return JsonResponse({'ok': False, 'error': sf_lang.t('তথ্য ঠিক নেই।', shop)})
    subtotal, _chosen, _q = _cart_subtotal(shop, data.get('cart'))
    _zone, charge = delivery.charge_for(shop, data.get('zone'), subtotal)
    try:
        coupon, discount, delivery_off = offers.find(shop, data.get('code'), subtotal, charge or 0)
    except offers.CouponError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)})
    if coupon is None:
        return JsonResponse({'ok': False, 'error': sf_lang.t('কুপন কোড লিখুন।', shop)})
    return JsonResponse({'ok': True, 'code': coupon.code, 'discount': float(discount),
                         'delivery_off': float(delivery_off), 'text': offers.describe(coupon, lang=shop)})


def storefront_checkout_draft(request, shop_slug):
    """কাস্টমার চেকআউটে নম্বর লিখলেই কার্টটা জমা থাকে — অর্ডার না করলে সেলার পরে দেখতে পায়।"""
    shop = get_object_or_404(Shop, slug=shop_slug)
    if request.method != 'POST':
        return JsonResponse({'ok': False}, status=405)
    try:
        data = json.loads(request.body or b'{}')
    except ValueError:
        return JsonResponse({'ok': False})
    phone = _storefront_customer_phone(data.get('phone') or '')
    if not phone:
        return JsonResponse({'ok': False})
    subtotal, chosen, quantities = _cart_subtotal(shop, data.get('cart'))
    cart = [{'key': k, 'name': chosen[k].name, 'price': float(chosen[k].price), 'qty': q}
            for k, q in quantities.items() if k in chosen]
    offers.save_draft(shop, phone, data.get('name'), data.get('address'), cart, subtotal)
    return JsonResponse({'ok': True})


def storefront_review_submit(request, shop_slug, product_id):
    """প্রোডাক্ট পেইজের রিভিউ ফর্ম (multipart, ছবি থাকতে পারে)।"""
    shop = get_object_or_404(Shop, slug=shop_slug)
    product = get_object_or_404(Product, id=product_id, shop=shop, is_active=True)
    back = storefront_link(shop, 'storefront_product_detail', product.id, request=request)
    if request.method != 'POST':
        return redirect(back)
    try:
        review = reviews.submit(shop, product, name=request.POST.get('name'), phone=request.POST.get('phone'),
                                rating=request.POST.get('rating'), text=request.POST.get('text'),
                                image=request.FILES.get('image'))
    except reviews.ReviewError as exc:
        request.session['review_msg'] = {'product': product.id, 'ok': False, 'text': str(exc)}
    else:
        request.session['review_msg'] = {'product': product.id, 'ok': True, 'text':
                                         sf_lang.t('ধন্যবাদ! আপনার রিভিউ ওয়েবসাইটে দেখানো হচ্ছে।' if review.is_approved
                                                   else 'ধন্যবাদ! দোকান দেখে নেওয়ার পর আপনার রিভিউ ওয়েবসাইটে দেখানো হবে।', shop)}
    return redirect(back + '#reviews')


def storefront_sitemap(request, shop_slug):
    from . import seo
    shop = get_object_or_404(Shop, slug=shop_slug)
    return HttpResponse(seo.sitemap_xml(shop, request), content_type='application/xml')


def storefront_robots(request, shop_slug):
    from . import seo
    shop = get_object_or_404(Shop, slug=shop_slug)
    return HttpResponse(seo.robots_txt(shop, request), content_type='text/plain')


def _storefront_customer_phone(raw):
    from accounts.forms import normalize_bd_mobile
    return normalize_bd_mobile(raw)


def storefront_place_order(request, shop_slug):
    """
    দোকানের ওয়েবসাইট থেকে অর্ডার (AJAX POST, JSON)।
    দাম, ডেলিভারি চার্জ আর অনলাইনে কত দিতে হবে, সব সার্ভারে হিসাব হয়; ব্রাউজার থেকে শুধু
    প্রোডাক্ট-পরিমাণ, এলাকার id আর পেমেন্টের ধরন আসে।
    """
    from decimal import Decimal
    from django.db import transaction
    from . import delivery, shop_payments

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request'}, status=405)
    shop = get_object_or_404(Shop, slug=shop_slug)
    if not storefront_is_open(shop):
        return JsonResponse({'success': False, 'error': sf_lang.t('এই দোকান এখন অর্ডার নিচ্ছে না।', shop)})

    try:
        data = json.loads(request.body or b'{}')
        cart_items = data.get('cart') or []
        quantities = {}
        for item in cart_items:
            product_id, qty = int(item['id']), int(item['qty'])
            if qty < 1 or qty > 999 or product_id == 0:
                return JsonResponse({'success': False, 'error': sf_lang.t('পরিমাণ ঠিক নেই।', shop)})
            quantities[product_id] = quantities.get(product_id, 0) + qty
    except (ValueError, TypeError, KeyError):
        return JsonResponse({'success': False, 'error': sf_lang.t('অর্ডারের তথ্য ঠিক নেই, পেইজটা আবার খুলুন।', shop)})
    if not quantities:
        return JsonResponse({'success': False, 'error': sf_lang.t('কার্ট খালি!', shop)})

    name = (data.get('name') or '').strip()[:150]
    address = (data.get('address') or '').strip()[:500]
    note = (data.get('note') or '').strip()[:500]
    phone = _storefront_customer_phone(data.get('phone') or '')
    if not name or not address:
        return JsonResponse({'success': False, 'error': sf_lang.t('নাম, মোবাইল নম্বর আর ঠিকানা দিন।', shop)})
    if not phone:
        return JsonResponse({'success': False, 'error': sf_lang.t('সঠিক মোবাইল নম্বর দিন (০১ দিয়ে শুরু, ১১ সংখ্যা)।', shop)})

    if risk.is_blocked(shop, phone):
        return JsonResponse({'success': False,
                             'error': sf_lang.t('এই নম্বর থেকে এখন অর্ডার নেওয়া যাচ্ছে না। দোকানে সরাসরি যোগাযোগ করুন।', shop)})

    choices = shop_payments.checkout_choices(shop)
    choice = data.get('payment') or choices[0]
    if choice not in choices:
        return JsonResponse({'success': False, 'error': sf_lang.t('পেমেন্টের ধরন বেছে নিন।', shop)})

    with transaction.atomic():
        # একসাথে অনেকে অর্ডার দিলেও স্টকের চেয়ে বেশি বিক্রি না হয়
        chosen = variants.resolve(shop, quantities.keys(), lock=True)
        if len(chosen) != len(quantities) or any(not item.product.is_active for item in chosen.values()):
            return JsonResponse({'success': False, 'error': sf_lang.t('কার্টের একটা প্রোডাক্ট আর পাওয়া যাচ্ছে না। কার্ট দেখে আবার চেষ্টা করুন।', shop)})
        subtotal = Decimal('0')
        for key, qty in quantities.items():
            item = chosen[key]
            if item.needs_choice:
                return JsonResponse({'success': False,
                                     'error': sf_lang.t("'{name}'-এর সাইজ/রং বেছে নিয়ে আবার কার্টে যোগ করুন।", shop, name=item.name)})
            if item.stock < qty:
                return JsonResponse({'success': False,
                                     'error': sf_lang.t("'{name}' স্টকে আছে মাত্র {n}টা।", shop, name=item.name, n=item.stock)})
            subtotal += item.price * qty

        zone, delivery_charge = delivery.charge_for(shop, data.get('zone'), subtotal)
        if delivery_charge is None:
            return JsonResponse({'success': False, 'error': sf_lang.t('ডেলিভারির এলাকা বেছে নিন।', shop)})
        try:
            coupon, discount, delivery_off = offers.find(shop, data.get('coupon'), subtotal, delivery_charge)
        except offers.CouponError as exc:
            return JsonResponse({'success': False, 'error': str(exc), 'coupon_error': True})
        delivery_charge = delivery_charge - delivery_off
        total = subtotal - discount + delivery_charge
        pay_now = shop_payments.amount_now(choice, total, delivery_charge)

        sf_order = StorefrontOrder.objects.create(
            shop=shop, customer_name=name, customer_phone=phone, customer_address=address,
            customer_note=note, total_amount=total, delivery_charge=delivery_charge,
            delivery_zone=zone.name if zone else '', status='Pending')
        customer, _ = Customer.objects.get_or_create(shop=shop, phone=phone,
                                                     defaults={'name': name, 'address': address})
        customer.name, customer.address = name, address
        customer.save(update_fields=['name', 'address'])
        landing = None
        if data.get('landing'):
            from .models import LandingPage
            landing = LandingPage.objects.filter(shop=shop, slug=str(data['landing'])[:60]).first()
        order_note = ' · '.join(x for x in [f'এলাকা: {zone.name}' if zone else '',
                                            f'কুপন {coupon.code}' if coupon else '',
                                            f'ল্যান্ডিং পেজ: {landing.headline}' if landing else '', note] if x) or None
        main_order = Order.objects.create(
            shop=shop, customer=customer, source='storefront', delivery_charge=delivery_charge, discount=discount,
            payment_method='COD', status='Pending', total_amount=total, note=order_note,
            coupon_code=coupon.code if coupon else '', landing=landing,
            online_payment_status=Order.ONLINE_PENDING if pay_now > 0 else Order.ONLINE_NONE)
        sf_order.order = main_order
        sf_order.save(update_fields=['order'])
        if coupon:
            offers.mark_used(coupon)
        offers.mark_recovered(shop, phone, main_order)
        for key, qty in quantities.items():
            item = chosen[key]
            StorefrontOrderItem.objects.create(order=sf_order, product=item.product, quantity=qty, price=item.price,
                                               variant_name=item.variant_name)
            OrderItem.objects.create(order=main_order, product=item.product, variant=item.variant,
                                     variant_name=item.variant_name, price=item.price, quantity=qty,
                                     cost_price=item.cost_price)
            variants.take(item, qty)

    # অর্ডার-সফল পেইজে কাস্টমারের নাম-ঠিকানা থাকে; শুধু যে ব্রাউজার থেকে অর্ডার হয়েছে সে-ই দেখতে পাবে
    placed = request.session.get('sf_orders', [])
    request.session['sf_orders'] = (placed + [sf_order.id])[-20:]
    success_url = storefront_link(shop, 'storefront_order_success', sf_order.id, request=request)

    if pay_now > 0:
        result = _start_customer_payment(request, shop, main_order, sf_order, choice, pay_now)
        if not result.get('ok'):
            # গেটওয়ে কাজ না করলে অর্ডারটা বাতিল না করে রেখে দেওয়া হয়; কাস্টমার অর্ডার পেইজ থেকে আবার চেষ্টা করতে পারবে
            return JsonResponse({'success': True, 'order_id': sf_order.id, 'redirect': success_url,
                                 'message': sf_lang.t(result.get('error') or '', shop)})
        return JsonResponse({'success': True, 'order_id': sf_order.id, 'redirect': result['payment_url']})

    if shop.sms_on_received:
        sms.send_auto(shop, phone, sms.order_received_text(shop, main_order), f'অর্ডার নং {sms.bn_num(main_order.id)}')
    return JsonResponse({'success': True, 'order_id': sf_order.id, 'redirect': success_url})


def _start_customer_payment(request, shop, order, sf_order, choice, amount):
    from . import shop_payments
    payment = shop_payments.create_payment(shop, order, sf_order, choice, amount)
    callback = request.build_absolute_uri(storefront_link(shop, 'storefront_payment_return', request=request))
    return shop_payments.start_gateway(payment, f'{callback}?inv={payment.invoice_number}',
                                       sf_order.customer_name, sf_order.customer_phone, sf_order.customer_address)


@csrf_exempt   # PayStation কখনো POST করে ফেরত পাঠায়; সিদ্ধান্ত হয় PayStation-এ যাচাই করে
def storefront_payment_return(request, shop_slug):
    """PayStation থেকে ফেরার পর (দোকানের নিজের ঠিকানায়)। আসল সিদ্ধান্ত PayStation-এ যাচাই করে।"""
    from . import shop_payments
    from .payments import valid_trx_id
    shop = get_object_or_404(Shop, slug=shop_slug)
    invoice = shop_payments.valid_invoice(request.GET.get('inv') or request.POST.get('invoice_number'))
    payment = StorefrontPayment.objects.filter(invoice_number=invoice, shop=shop).first() if invoice else None
    if payment is None or payment.sf_order_id is None:
        return redirect(storefront_link(shop, request=request))

    gateway_status = (request.GET.get('status') or request.POST.get('status') or '').strip().lower()
    if gateway_status in ('failed', 'canceled', 'cancelled', 'cancel'):
        StorefrontPayment.objects.filter(pk=payment.pk, status=StorefrontPayment.STATUS_PENDING).update(
            status=StorefrontPayment.STATUS_FAILED)
        status, msg = 'failed', 'পেমেন্ট সম্পন্ন হয়নি। চাইলে আবার চেষ্টা করুন।'
    else:
        trx_id = valid_trx_id(request.GET.get('trx_id') or request.POST.get('trx_id'))
        status, _payment, msg = shop_payments.apply_successful(
            invoice, trx_id=trx_id, attempts=2, timeout=shop_payments.CALLBACK_VERIFY_TIMEOUT)
    request.session['sf_payment_msg'] = {'order': payment.sf_order_id, 'status': status, 'message': sf_lang.t(msg, shop)}
    return redirect(storefront_link(shop, 'storefront_order_success', payment.sf_order_id, request=request))


def storefront_payment_retry(request, shop_slug, order_id):
    """অর্ডার পেইজ থেকে "আবার পেমেন্ট করুন"।"""
    from . import shop_payments
    shop = get_object_or_404(Shop, slug=shop_slug)
    if request.method != 'POST' or order_id not in request.session.get('sf_orders', []):
        return redirect(storefront_link(shop, request=request))
    sf_order = get_object_or_404(StorefrontOrder.objects.select_related('order'), id=order_id, shop=shop)
    order = sf_order.order
    last = sf_order.payments.order_by('-created_at').first()
    if order is None or last is None or order.online_payment_status == Order.ONLINE_PAID \
            or order.status in ('Cancelled', 'Returned'):
        return redirect(storefront_link(shop, 'storefront_order_success', order_id, request=request))
    if last.status == StorefrontPayment.STATUS_PENDING:
        # আগের চেষ্টায় টাকা কেটে থাকলে আবার কাটার আগে সেটা ধরা পড়ুক
        status, _p, _m = shop_payments.apply_successful(last.invoice_number, timeout=6)
        if status in ('ok', 'already'):
            return redirect(storefront_link(shop, 'storefront_order_success', order_id, request=request))
    choice = shop_payments.CHOICE_FULL if last.kind == StorefrontPayment.KIND_FULL else shop_payments.CHOICE_ADVANCE
    result = _start_customer_payment(request, shop, order, sf_order, choice, last.amount)
    if result.get('ok'):
        return redirect(result['payment_url'])
    request.session['sf_payment_msg'] = {'order': order_id, 'status': 'failed', 'message': sf_lang.t(result.get('error') or '', shop)}
    return redirect(storefront_link(shop, 'storefront_order_success', order_id, request=request))


@ensure_csrf_cookie
def storefront_order_success(request, shop_slug, order_id):
    """Order success page"""
    shop = get_object_or_404(Shop, slug=shop_slug)
    # অন্য কেউ নম্বর বদলে অন্যের অর্ডারের তথ্য দেখতে না পারে
    if order_id not in request.session.get('sf_orders', []):
        return redirect(storefront_link(shop, request=request))
    order = get_object_or_404(StorefrontOrder.objects.select_related('order'), id=order_id, shop=shop)
    payment_msg = request.session.pop('sf_payment_msg', None)
    if payment_msg and payment_msg.get('order') != order_id:
        payment_msg = None
    last_payment = order.payments.order_by('-created_at').first()
    if last_payment and last_payment.status == StorefrontPayment.STATUS_PENDING and not payment_msg:
        # IPN আগে এসে গেলে বা কাস্টমার পরে পেইজ খুললে আবার যাচাই
        from . import shop_payments
        shop_payments.apply_successful(last_payment.invoice_number, timeout=5)
        last_payment.refresh_from_db()
        order.order.refresh_from_db() if order.order_id else None
    main = order.order
    payment_pending = bool(main and main.online_payment_status == Order.ONLINE_PENDING
                           and main.status not in ('Cancelled', 'Returned'))
    if main and main.online_payment_status == Order.ONLINE_PAID:
        payment_label = (sf_lang.t('অনলাইনে পুরো টাকা পরিশোধিত', shop) if not main.due_amount else
                         sf_lang.t('অনলাইনে {paid} দেওয়া হয়েছে, বাকি {due} পণ্য হাতে পেয়ে', shop,
                                   paid=f'৳{main.advance_paid:.0f}', due=f'৳{main.due_amount:.0f}'))
    elif payment_pending:
        payment_label = sf_lang.t('অনলাইন পেমেন্ট এখনো হয়নি', shop)
    else:
        payment_label = sf_lang.t('ক্যাশ অন ডেলিভারি', shop)
    return render(request, 'store/storefront/order_success.html', {
        'shop': shop, 'order': order, 'main_order': main, 'last_payment': last_payment,
        'payment_msg': payment_msg, 'payment_pending': payment_pending, 'payment_label': payment_label,
        'order_no': f'ORD-{main.id}' if main else f'SF-{order.id}',
        'track_url': storefront_link(shop, 'storefront_track_order', order_flow.track_code(main), request=request)
                     if main else '',
    })


# ============================================================
# SELLER: View Storefront Orders in Dashboard
# ============================================================
@login_required(login_url='/accounts/login/')
def storefront_orders(request):
    """Seller sees all online orders from their storefront"""
    shop = request.user.shop
    sf_orders = StorefrontOrder.objects.filter(shop=shop).order_by('-created_at')

    search = request.GET.get('q', '').strip()
    if search:
        query = Q(customer_name__icontains=search) | Q(customer_phone__icontains=search)
        # অর্ডার নম্বর দিয়েও খোঁজা যায় (#1269, SF-539 বা শুধু 1269) — মূল অর্ডারের নম্বরই দেখানো হয়
        number = search.lstrip('#').upper().removeprefix('ORD-').removeprefix('SF-').translate(BN_TO_EN_DIGITS)
        if number.isdigit():
            query |= Q(order_id=int(number)) | Q(id=int(number))
        sf_orders = sf_orders.filter(query)

    status_filter = request.GET.get('status', '')
    if status_filter:
        sf_orders = sf_orders.filter(status=status_filter)

    paginator = Paginator(sf_orders, 20)
    page_number = request.GET.get('page', 1)
    sf_orders = paginator.get_page(page_number)
    risk.attach(shop, sf_orders.object_list, lambda o: o.customer_phone)

    return render(request, 'store/storefront_orders.html', {
        'sf_orders': sf_orders,
        'search': search,
        'status_filter': status_filter,
        'pending_count': StorefrontOrder.objects.filter(shop=shop, status='Pending').count(),
        'status_bn': order_flow.STATUS_BN,
    })


@login_required(login_url='/accounts/login/')
def storefront_order_update_status(request, order_id):
    """Seller updates storefront order status"""
    shop = request.user.shop
    sf_order = get_object_or_404(StorefrontOrder, id=order_id, shop=shop)
    if request.method == 'POST':
        new_status = request.POST.get('status')
        if new_status in ['Pending', 'Confirmed', 'Shipped', 'Delivered', 'Cancelled']:
            try:
                if sf_order.order_id:
                    # মূল অর্ডারের সাথে একসাথে বদলায় (স্টক ফেরত, কাস্টমারকে SMS)
                    order_flow.set_status(sf_order.order, new_status)
                else:
                    sf_order.status = new_status
                    sf_order.save(update_fields=['status'])
            except order_flow.FlowError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(request, f'অর্ডার #{sf_order.order_id or f"SF-{sf_order.id}"} এখন "{order_flow.STATUS_BN[new_status]}"।')
    return redirect('storefront_orders')


# ============================================================
# CATEGORY MANAGEMENT
# ============================================================
@login_required(login_url='/accounts/login/')
def category_list(request):
    """ক্যাটাগরি এখন "ওয়েবসাইট" পেইজের ট্যাবে। পুরনো ফর্ম থেকে POST এলে যোগ করে সেখানে পাঠায়।"""
    shop = request.user.shop
    if request.method == 'POST':
        name = ' '.join((request.POST.get('name') or '').split())[:100]
        if name and not Category.objects.filter(shop=shop, name__iexact=name).exists():
            Category.objects.create(shop=shop, name=name)
            messages.success(request, f'"{name}" ক্যাটাগরি যোগ হয়েছে।')
    return redirect(reverse('website_settings') + '?tab=categories')



# ============================================================
# BARCODE SYSTEM
# ============================================================
# বারকোড দিয়ে প্রোডাক্ট খোঁজা (POS স্ক্যানার): store/views_pos.py → pos_barcode


@login_required(login_url='/accounts/login/')
def barcode_print(request):
    """Bulk barcode print page — seller selects products, prints stickers"""
    shop = request.user.shop
    # সাইজ/রং থাকলে প্রতিটার আলাদা স্টিকার (আলাদা বারকোড); id ঋণাত্মক রাখা যাতে প্রোডাক্টের সাথে না মেলে
    products = []
    for product in Product.objects.filter(shop=shop, is_active=True).prefetch_related('variants').order_by('name'):
        if product.has_variants:
            products += [{'id': -v.id, 'name': f'{product.name} ({v.name})', 'price': v.sell_price,
                          'barcode': v.barcode} for v in product.variants.all()]
        else:
            products.append({'id': product.id, 'name': product.name, 'price': product.price,
                             'barcode': product.barcode})

    selected_ids = request.GET.getlist('ids')
    selected_products = []
    if selected_ids:
        selected_products = Product.objects.filter(id__in=selected_ids, shop=shop)

    return render(request, 'store/barcode_print.html', {
        'shop': shop,
        'products': products,
        'selected_products': selected_products,
        'selected_ids': selected_ids,
    })
# ============================================================
# অনলাইন পেমেন্ট এখন PayStation দিয়ে: store/payment_views.py আর store/payments.py
# (আগের SSLCommerz কোড সরানো হয়েছে — success URL-এর প্ল্যান/শপ যাচাই না করেই আপগ্রেড করত)
# ============================================================


from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from .models import StaffProfile

User = get_user_model()


@login_required(login_url='/accounts/login/')
def add_edit_staff(request, staff_id=None):
    shop = request.user.shop
    staff_profile = None

    # যদি এডিট মোড হয়
    if staff_id:
        staff_profile = get_object_or_404(StaffProfile, id=staff_id, shop=shop)
    elif not can_add_staff(shop):
        # নতুন স্টাফ যোগের সময় প্যাকেজের সীমা দেখা হয় (এডিট সবসময় চলবে)
        messages.error(request, f"আপনার প্যাকেজে সর্বোচ্চ {staff_limit(shop)} জন স্টাফ রাখা যায়। "
                                "আরও স্টাফ যোগ করতে Billing থেকে প্যাকেজ আপগ্রেড করুন।")
        return redirect('staff_list')

    if request.method == 'POST':
        name = request.POST.get('name')
        phone = request.POST.get('phone')
        password = request.POST.get('password')

        # Permissions (চেকবক্স থেকে ডেটা নেওয়া)
        can_use_pos = request.POST.get('can_use_pos') == 'on'
        can_manage_products = request.POST.get('can_manage_products') == 'on'
        can_manage_orders = request.POST.get('can_manage_orders') == 'on'
        can_manage_customers = request.POST.get('can_manage_customers') == 'on'
        can_view_reports = request.POST.get('can_view_reports') == 'on'
        can_manage_settings = request.POST.get('can_manage_settings') == 'on'
        can_send_sms = request.POST.get('can_send_sms') == 'on'

        try:
            if staff_profile:
                # --- স্টাফ এডিট & পাসওয়ার্ড রিসেট ---
                staff_user = staff_profile.user
                staff_user.name = name
                staff_user.phone_number = phone
                # যদি নতুন পাসওয়ার্ড দেয়, তবেই আপডেট হবে
                if password:
                    staff_user.password = make_password(password)
                staff_user.save()

                # পারমিশন আপডেট
                staff_profile.can_use_pos = can_use_pos
                staff_profile.can_manage_products = can_manage_products
                staff_profile.can_manage_orders = can_manage_orders
                staff_profile.can_manage_customers = can_manage_customers
                staff_profile.can_view_reports = can_view_reports
                staff_profile.can_manage_settings = can_manage_settings
                staff_profile.can_send_sms = can_send_sms
                staff_profile.save()

                messages.success(request, "Staff account updated successfully!")
            else:
                # --- নতুন স্টাফ ক্রিয়েট ---
                if User.objects.filter(phone_number=phone).exists():
                    messages.error(request, "This phone number is already registered!")
                    return redirect('add_staff')

                # নতুন ইউজার তৈরি
                new_user = User.objects.create(
                    phone_number=phone,
                    name=name,
                    password=make_password(password),
                    is_staff=False,
                    is_active=True
                )

                # স্টাফ প্রোফাইল তৈরি
                StaffProfile.objects.create(
                    user=new_user,
                    shop=shop,
                    can_use_pos=can_use_pos,
                    can_manage_products=can_manage_products,
                    can_manage_orders=can_manage_orders,
                    can_manage_customers=can_manage_customers,
                    can_view_reports=can_view_reports,
                    can_manage_settings=can_manage_settings,
                    can_send_sms=can_send_sms,
                )
                messages.success(request, "New staff account created!")

            return redirect('dashboard')  # পরে এটাকে 'staff_list' পেজে পাঠাতে পারেন

        except Exception as e:
            messages.error(request, f"Error: {str(e)}")

    return render(request, 'store/add_staff.html', {'staff': staff_profile})

@login_required(login_url='/accounts/login/')
def staff_list(request):
    shop = request.user.shop
    # শুধু এই শপের স্টাফদের লিস্ট আনবে
    staff_members = StaffProfile.objects.filter(shop=shop).order_by('-created_at')
    return render(request, 'store/staff_list.html', {'staff_members': staff_members})


from .models import PaymentRequest


@login_required(login_url='/accounts/login/')
def billing_receipt(request, invoice):
    """প্যাকেজ বা SMS কেনার রসিদ — প্রদানকারী এডুমি (Edumi), SellPunch নামে (store/company.py)। প্রিন্ট বা PDF করা যায়।"""
    from .models import OnlinePayment
    shop = getattr(request.user, 'shop', None)
    if shop is None:
        raise Http404
    payment = get_object_or_404(OnlinePayment, shop=shop, invoice_number=invoice, status=OnlinePayment.STATUS_COMPLETED)
    return render(request, 'store/billing_receipt.html', {'payment': payment, 'shop': shop})


@login_required(login_url='/accounts/login/')
# submit_payment_request moved below
@login_required(login_url='/accounts/login/')
def billing_page(request):
    from .payments import online_payment_available, recheck_pending
    from . import paystation

    shop = request.user.shop
    # callback হারিয়ে গেলেও টাকা কাটা পেমেন্ট যেন ঝুলে না থাকে — পেইজ খুললেই আবার যাচাই
    for payment in recheck_pending(shop):
        messages.success(request, f"আপনার {payment.plan_name} পেমেন্ট নিশ্চিত হয়েছে।")
        shop.refresh_from_db()

    pending_request = shop.payment_requests.filter(status='Pending').first()
    payment_history = shop.payment_requests.all().order_by('-created_at')[:10]
    return render(request, 'store/billing.html', {
        'shop': shop,
        'pending_request': pending_request,
        'payment_history': payment_history,
        'online_payment_available': online_payment_available(shop),
        'storefront_open': storefront_is_open(shop),
        'storefront_closes_on': storefront_closes_on(shop),
        'paystation_sandbox': paystation.current_environment() == 'sandbox',
        'online_payments': shop.online_payments.all()[:10],
    })


@login_required(login_url='/accounts/login/')
def submit_payment_request(request):
    """আগে bKash/Nagad-এ হাতে টাকা পাঠিয়ে লেনদেন নম্বর জমা দেওয়া যেতো — এখন সব পেমেন্ট PayStation-এ।"""
    messages.info(request, 'এখন সব পেমেন্ট অনলাইনে (PayStation) নেওয়া হয় — প্যাকেজ বেছে "কিনুন" চাপুন, সাথে সাথে চালু হবে।')
    return redirect('billing')


@login_required(login_url='/accounts/login/')
def approve_payment(request, request_id):
    if not request.user.is_superuser:
        return redirect('dashboard')
    if request.method != 'POST':
        return redirect('master_billing')

    from .models import PaymentRequest
    from django.utils import timezone
    from datetime import timedelta

    pay_req = get_object_or_404(PaymentRequest, id=request_id)
    shop = pay_req.shop
    today = timezone.now().date()

    if pay_req.plan_name == sms.MANUAL_REQUEST_NAME:
        sms_added = sms.approve_manual_request(pay_req)      # এখনকার রেটে
        messages.success(request, f"Added {sms_added} SMS to {shop.name}!")
    else:
        advance_days = int(request.POST.get('advance_days', 30))
        if shop.valid_until and shop.valid_until >= today:
            shop.valid_until = shop.valid_until + timedelta(days=advance_days)
        else:
            shop.valid_until = today + timedelta(days=advance_days)

        shop.subscription_plan = pay_req.plan_name
        shop.is_locked = False
        shop.is_paid = True
        shop.save()  # ফ্রি SMS রিমুভ করা হয়েছে
        messages.success(request, f"{shop.name} payment approved! Valid until: {shop.valid_until}")

    pay_req.status = 'Approved'
    pay_req.save()
    from . import hq
    hq.log_action(request, 'payment_legacy', shop, f'অনুমোদন: {pay_req.plan_name} ৳{pay_req.amount:.0f} ({pay_req.transaction_id})')
    return redirect('master_billing')


@login_required(login_url='/accounts/login/')
def reject_payment(request, request_id):
    """Admin rejects a payment request"""
    if not request.user.is_superuser:
        messages.error(request, "Access Denied!")
        return redirect('dashboard')

    if request.method != 'POST':
        return redirect('master_billing')
    from .models import PaymentRequest
    pay_req = get_object_or_404(PaymentRequest, id=request_id)
    pay_req.status = 'Rejected'
    pay_req.save()
    from . import hq
    hq.log_action(request, 'payment_legacy', pay_req.shop, f'বাতিল: {pay_req.plan_name} ({pay_req.transaction_id})')
    messages.warning(request, f"{pay_req.shop.name}-এর পেমেন্ট বাতিল করা হয়েছে।")
    return redirect('master_billing')


@login_required(login_url='/accounts/login/')
def manual_unlock(request, shop_id):
    """Admin manually unlocks/extends a shop"""
    if not request.user.is_superuser:
        return redirect('dashboard')

    if request.method == 'POST':
        shop = get_object_or_404(Shop, id=shop_id)
        advance_days = int(request.POST.get('advance_days', 30))
        today = timezone.localdate()

        if shop.valid_until and shop.valid_until >= today:
            shop.valid_until = shop.valid_until + timedelta(days=advance_days)
        else:
            shop.valid_until = today + timedelta(days=advance_days)

        shop.is_locked = False
        shop.save()
        from . import hq
        hq.log_action(request, 'extend', shop, f'{advance_days} দিন (পুরনো বাটন) — মেয়াদ {shop.valid_until:%d-%m-%Y}')
        messages.success(request, f"{shop.name}-এর লক খোলা হয়েছে, মেয়াদ {shop.valid_until:%d-%m-%Y} পর্যন্ত।")
        return redirect('hq_shop', shop.pk)

    return redirect('master_dashboard')


import csv
from django.http import HttpResponse


# ============================================================
# CSV TEMPLATE DOWNLOAD
# ============================================================
@login_required(login_url='/accounts/login/')
def download_csv_template(request):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="sellpunch_product_template.csv"'

    writer = csv.writer(response)
    # Header Row
    writer.writerow(['Name', 'Category', 'Description', 'Cost Price', 'Selling Price', 'Stock Quantity', 'Barcode'])
    # Example Row
    writer.writerow(['Lux Soap 100g', 'Cosmetics', 'Beauty soap', '40', '50', '100', '894112345678'])
    writer.writerow(['Pran Noodles', 'Grocery', '', '18', '20', '50', ''])

    return response


# ============================================================
# IMPORT BULK PRODUCTS VIA CSV
# ============================================================
@login_required(login_url='/accounts/login/')
def import_bulk_products(request):
    if request.method == 'POST' and request.FILES.get('csv_file'):
        csv_file = request.FILES['csv_file']

        if not csv_file.name.endswith('.csv'):
            messages.error(request, 'Please upload a valid .csv file!')
            return redirect('product_list')

        shop = request.user.shop
        decoded_file = csv_file.read().decode('utf-8').splitlines()
        reader = csv.DictReader(decoded_file)

        # প্যাকেজের লিমিট
        product_count = Product.objects.filter(shop=shop).count()
        limit = product_limit(shop)

        created_count = 0
        skipped_count = 0

        for row in reader:
            if limit and (product_count + created_count) >= limit:
                messages.warning(request,
                                 f'প্যাকেজের লিমিট ({limit}টা প্রোডাক্ট) পূর্ণ, তাই {created_count}টা যোগ হয়েছে। '
                                 'বাকিগুলো যোগ করতে প্যাকেজ আপগ্রেড করুন।')
                break

            name = row.get('Name', '').strip()
            if not name:
                skipped_count += 1
                continue  # Skip empty rows

            # Auto-create category if not exists
            category_name = row.get('Category', '').strip()
            category = None
            if category_name:
                category, _ = Category.objects.get_or_create(shop=shop, name=category_name)

            # ── BUG FIX: try/except for invalid number values ──
            try:
                cost_price = float(row.get('Cost Price', 0) or 0)
                price      = float(row.get('Selling Price', 0) or 0)
                stock      = int(float(row.get('Stock Quantity', 0) or 0))
            except (ValueError, TypeError):
                skipped_count += 1
                continue  # Skip rows with invalid number format

            barcode = row.get('Barcode', '').strip() or None

            Product.objects.create(
                shop=shop,
                name=name,
                category=category,
                description=row.get('Description', ''),
                cost_price=cost_price,
                price=price,
                stock_quantity=stock,
                barcode=barcode,
            )
            created_count += 1

        msg = f'{created_count}টা প্রোডাক্ট যোগ হয়েছে।'
        if skipped_count:
            msg += f' ({skipped_count} rows skipped due to invalid data)'
        if created_count > 0:
            messages.success(request, msg)
        elif skipped_count:
            messages.error(request, f'Import failed — {skipped_count} rows had invalid data. Please check your CSV format.')

    return redirect('product_list')

# ============================================================
# FACEBOOK LOGIN & PAGE SELECTION (নতুন যোগ হয়েছে)
# ============================================================
from allauth.socialaccount.models import SocialToken, SocialAccount
from .facebook_helpers import get_user_pages, get_long_lived_token, get_page_long_lived_token
from .models import FacebookPageConnection
from django.conf import settings as django_settings


@login_required(login_url='/accounts/login/')
def fb_page_select(request):
    """
    Facebook Login সফল হওয়ার পর এই page-এ আসবে।
    ইউজারের সব Facebook Page দেখাবে। সে একটা select করবে।
    """
    shop = getattr(request.user, 'shop', None)
    if not shop:
        messages.error(request, "আগে আপনার শপ সেটআপ করুন!")
        return redirect('setup_shop')
    if not has_facebook(shop):
        messages.warning(request, upgrade_message("Facebook কানেক্ট আর অটোমেশন (Standard ও Premium প্যাকেজে আছে)"))
        return redirect('billing')

    # ইতিমধ্যে কোনো পেইজ connect আছে কিনা
    existing_connection = FacebookPageConnection.objects.filter(shop=shop).first()

    # allauth থেকে Facebook access token নেওয়া
    try:
        social_account = SocialAccount.objects.get(user=request.user, provider='facebook')
        social_token = SocialToken.objects.get(account=social_account)
        short_token = social_token.token
    except (SocialAccount.DoesNotExist, SocialToken.DoesNotExist):
        messages.error(request, "Facebook login পাওয়া যায়নি। আবার Facebook দিয়ে লগইন করুন।")
        return redirect('fb_connect')

    # Short token → Long-lived token বানাও
    fb_provider = django_settings.SOCIALACCOUNT_PROVIDERS.get('facebook', {})
    app_id = ''
    app_secret = ''
    try:
        from allauth.socialaccount.models import SocialApp
        fb_app = SocialApp.objects.get(provider='facebook')
        app_id = fb_app.client_id
        app_secret = fb_app.secret
    except Exception:
        pass

    long_token = get_long_lived_token(short_token, app_id, app_secret)

    # ইউজারের সব পেইজ লিস্ট আনো
    pages = get_user_pages(long_token)

    if request.method == 'POST':
        selected_page_id = request.POST.get('page_id')
        if not selected_page_id:
            messages.error(request, "একটি পেইজ সিলেক্ট করুন!")
            return redirect('fb_page_select')

        # সিলেক্ট করা পেইজের তথ্য খোঁজো
        selected_page = next((p for p in pages if p['id'] == selected_page_id), None)
        if not selected_page:
            messages.error(request, "পেইজটি পাওয়া যায়নি!")
            return redirect('fb_page_select')

        # পেইজের permanent access token নাও
        page_token = get_page_long_lived_token(selected_page_id, long_token)
        if not page_token:
            # fallback: পেইজ থেকে সরাসরি নেওয়া token
            page_token = selected_page.get('access_token', '')

        # Picture URL বের করো
        picture_url = ''
        if 'picture' in selected_page:
            pic_data = selected_page.get('picture', {})
            if isinstance(pic_data, dict):
                picture_url = pic_data.get('data', {}).get('url', '')
            elif isinstance(pic_data, str):
                picture_url = pic_data

        # DB-তে save করো (আগেরটা replace করবে)
        FacebookPageConnection.objects.update_or_create(
            shop=shop,
            defaults={
                'page_id': selected_page_id,
                'page_name': selected_page.get('name', ''),
                'page_access_token': page_token,
                'page_picture': picture_url,
                'fan_count': selected_page.get('fan_count', 0),
                'category': selected_page.get('category', ''),
                'user_access_token': long_token,
                'is_active': True,
            }
        )

        from .facebook_bot import subscribe_page
        if subscribe_page(selected_page_id, page_token):
            messages.success(request, f"'{selected_page.get('name')}' পেইজ যুক্ত হয়েছে। "
                                      "এখন পোস্টে কেউ কমেন্ট করলে তার ইনবক্সে অর্ডারের লিংক চলে যাবে।",
                             extra_tags='facebook')
        else:
            messages.warning(request, f"'{selected_page.get('name')}' পেইজ যুক্ত হয়েছে, কিন্তু কমেন্টের খবর পাওয়া "
                                      "চালু করা যায়নি। একটু পরে আবার যুক্ত করে দেখুন।", extra_tags='facebook')
        return redirect(_settings_url('facebook'))

    context = {
        'pages': pages,
        'shop': shop,
        'existing_connection': existing_connection,
    }
    return render(request, 'store/fb_page_select.html', context)


@login_required(login_url='/accounts/login/')
def fb_disconnect(request):
    """
    Facebook Page disconnect — পেইজের সংযোগ আর সেভ করা Facebook টোকেন মুছে দেয়।
    (Data Deletion পেইজে এটাই লেখা আছে।) শুধু POST, যাতে কোনো লিংকে ক্লিক করিয়ে
    কেউ ডিসকানেক্ট করাতে না পারে।
    """
    if request.method != 'POST':
        return redirect(_settings_url('facebook'))
    shop = getattr(request.user, 'shop', None)
    if shop:
        from .facebook_bot import unsubscribe_page
        for connection in FacebookPageConnection.objects.filter(shop=shop):
            unsubscribe_page(connection.page_id, connection.page_access_token)
        FacebookPageConnection.objects.filter(shop=shop).delete()
        SocialToken.objects.filter(account__user=request.user, account__provider='facebook').delete()
        messages.success(request, 'Facebook পেইজের সংযোগ সরানো হয়েছে, আর সেভ করা Facebook টোকেন মুছে ফেলা হয়েছে।',
                         extra_tags='facebook')
    return redirect(_settings_url('facebook'))


@csrf_exempt
def facebook_webhook(request):
    """
    Meta App → Webhooks → Page → "feed"-এর Callback URL।
    GET: Meta যাচাই করে (hub.verify_token মিললে hub.challenge ফেরত)।
    POST: কমেন্টের খবর; X-Hub-Signature-256 App Secret দিয়ে মিলিয়ে তবেই কাজ।
    """
    from django.conf import settings as dj_settings
    from . import facebook_bot
    if request.method == 'GET':
        expected = getattr(dj_settings, 'FACEBOOK_WEBHOOK_VERIFY_TOKEN', '')
        if (request.GET.get('hub.mode') == 'subscribe' and expected
                and request.GET.get('hub.verify_token') == expected):
            return HttpResponse(request.GET.get('hub.challenge', ''), content_type='text/plain')
        return HttpResponse('Forbidden', status=403)
    if request.method != 'POST':
        return HttpResponse(status=405)
    if not facebook_bot.signature_ok(request.body, request.headers.get('X-Hub-Signature-256', '')):
        return HttpResponse('Bad signature', status=403)
    try:
        payload = json.loads(request.body or b'{}')
    except ValueError:
        return HttpResponse('Bad JSON', status=400)
    try:
        facebook_bot.handle_payload(payload)
    except Exception:   # Meta বারবার পাঠাতে না থাকে, তাই সবসময় 200
        import logging
        logging.getLogger(__name__).exception('Facebook webhook handling failed')
    return HttpResponse('EVENT_RECEIVED')


@login_required(login_url='/accounts/login/')
def fb_bot_settings(request):
    """Settings থেকে কমেন্ট বট চালু/বন্ধ।"""
    if request.method == 'POST':
        connection = FacebookPageConnection.objects.filter(shop=request.user.shop).first()
        if connection:
            connection.comment_bot_enabled = request.POST.get('comment_bot_enabled') == 'on'
            connection.public_reply_enabled = request.POST.get('public_reply_enabled') == 'on'
            connection.save(update_fields=['comment_bot_enabled', 'public_reply_enabled', 'updated_at'])
            messages.success(request, 'কমেন্ট থেকে অর্ডারের সেটিং সেভ হয়েছে।', extra_tags='facebook')
    return redirect(_settings_url('facebook'))


@login_required(login_url='/accounts/login/')
def fb_connect(request):
    """Facebook এর সাথে connect করার redirect page"""
    from allauth.socialaccount.models import SocialApp
    shop = getattr(request.user, 'shop', None)
    if shop and not has_facebook(shop):
        messages.warning(request, upgrade_message("Facebook কানেক্ট আর অটোমেশন (Standard ও Premium প্যাকেজে আছে)"))
        return redirect('billing')
    # Django Admin-এ Facebook Social App যোগ না করা পর্যন্ত পেইজটা ক্র্যাশ না করে ড্যাশবোর্ডে ফেরত পাঠাবে
    if not SocialApp.objects.filter(provider='facebook').exists():
        messages.warning(request, "Facebook কানেক্ট এখনো চালু হয়নি, শিগগিরই আসছে।")
        return redirect('dashboard')
    return render(request, 'store/fb_connect.html', {
        'shop': getattr(request.user, 'shop', None)
    })
