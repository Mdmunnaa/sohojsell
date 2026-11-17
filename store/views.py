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

from django.db import transaction

from . import stock_log
from django.db.models import Count, F, Sum, Q
from django.utils import timezone
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from datetime import timedelta
import random

from .models import (Shop, Product, Category, Order, OrderItem, Customer, MasterSetting, Banner, MessengerContact,
                     SaleReturnItem, StorefrontOrderItem)
from . import backups, retention
from .plans import (
    can_add_staff, has_custom_domain, has_facebook, plan_label, product_limit, products_remaining,
    staff_limit, storefront_closes_on, storefront_is_open, upgrade_message,
)
from .forms import (ShopSetupForm, ProductForm, OrderCreateForm, SteadfastSettingsForm, PathaoSettingsForm,
                    RedxSettingsForm, PosSettingsForm)
from .links import storefront_link
from . import couriers, offers, order_flow, pos, reviews, risk, sf_lang, sms, units, variants
from .themes import THEMES
from django.urls import reverse

BN_TO_EN_DIGITS = str.maketrans('০১২৩৪৫৬৭৮৯', '0123456789')
EN_TO_BN_DIGITS = str.maketrans('0123456789', '০১২৩৪৫৬৭৮৯')


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
    from . import marketing, views_marketing
    try:
        facebook_live = marketing.facebook_live()
    except Exception:    # noqa: BLE001 — ডেটাবেস ছাড়া হোমপেজ আটকাবে না
        facebook_live = False
    from . import shop_payments
    return render(request, template, {
        'plans': plans, 'sms_rate': rate, 'trial_days': 30, 'home_seo': home_seo, 'facebook_live': facebook_live,
        'online_fee': shop_payments.fee_percent().normalize(), 'settle_min': int(shop_payments.SETTLEMENT_MIN),
        'settle_days': shop_payments.SETTLEMENT_HOLD_DAYS,
        # SEO পাতার লিংক (store/marketing.py) — হোমপেজ থেকে প্রতিটায় লিংক থাকলে Google দ্রুত খুঁজে পায়
        'industry_links': views_marketing._cards(marketing.INDUSTRIES, 'industry', lang),
        'features_url': views_marketing._index_url(lang),
    })


def security_txt(request):
    """/.well-known/security.txt — নিরাপত্তার সমস্যা পেলে কাকে জানাবেন (RFC 9116)।"""
    from datetime import timedelta
    from django.conf import settings as dj_settings
    from django.utils import timezone as tz
    from .seo import main_site_url
    base = main_site_url(request)
    expires = (tz.now() + timedelta(days=365)).replace(microsecond=0).strftime('%Y-%m-%dT%H:%M:%SZ')
    body = '\n'.join([
        f'Contact: mailto:{dj_settings.SUPPORT_EMAIL}',
        f'Expires: {expires}',
        'Preferred-Languages: bn, en',
        f'Canonical: {base}/.well-known/security.txt',
        f'Policy: {base}{reverse("security")}',
    ]) + '\n'
    return HttpResponse(body, content_type='text/plain; charset=utf-8')


def indexnow_key(request, key):
    """https://sellpunch.com/<চাবি>.txt — IndexNow-কে দেখানো যে পাতাগুলোর খবর আমরাই পাঠাচ্ছি (store/indexnow.py)।"""
    from . import indexnow
    if key != indexnow.key():
        raise Http404
    return HttpResponse(key, content_type='text/plain; charset=utf-8')


def site_llms(request):
    """/llms.txt — AI সার্চের জন্য SellPunch-এর পরিচয় (store/seo.py)।"""
    from . import seo
    return HttpResponse(seo.main_llms_txt(request), content_type='text/plain; charset=utf-8')


def site_llms_full(request):
    """/llms-full.txt — গাইড সেন্টারের সব গাইডের পুরো লেখা (AI টুল যেন সঠিক নিয়ম বলতে পারে)।"""
    from . import seo
    return HttpResponse(seo.main_llms_full_txt(request), content_type='text/plain; charset=utf-8')


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
    from . import shop_payments
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
        'todo': dash.todo_items(can, pipeline, dues, stock,
                                messenger_waiting=MessengerContact.objects.filter(
                                    shop=shop, waiting_since__isnull=False).count() if limits_for(shop)['facebook'] else 0,
                                money=({**shop_payments.balance_summary(shop),
                                        'refunds_waiting': shop_payments.refunds_waiting(shop)}
                                       if can['settings'] else None)),
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
        # নাম বা বারকোড (সাইজ/রংয়ের বারকোডও) দিয়ে খোঁজা
        code = q.strip().translate(BN_TO_EN_DIGITS)
        products = products.filter(Q(name__icontains=q) | Q(barcode=code) | Q(variants__barcode=code)
                                   | Q(extra_barcodes__code=code)).distinct()
    # Category filter
    cat_id = request.GET.get('cat', '')
    if cat_id.isdigit():
        products = products.filter(category__id=cat_id)
    # Status filter
    status = request.GET.get('status', '')
    if status == 'active':
        products = products.filter(is_active=True)
    elif status == 'inactive':
        products = products.filter(is_active=False)
    elif status == 'low':
        products = products.filter(stock_log.low_stock_q())
    # Pagination
    paginator = Paginator(products, 20)
    page = request.GET.get('page', 1)
    try:
        page_obj = paginator.page(page)
    except (EmptyPage, PageNotAnInteger):
        page_obj = paginator.page(1)
    categories = Category.objects.filter(shop=shop).order_by('name')
    keep = request.GET.copy()
    keep.pop('page', None)
    low_count = Product.objects.filter(stock_log.low_stock_q(), shop=shop, is_active=True).count()
    return render(request, 'store/products.html', {'page_obj': page_obj, 'categories': categories, 'shop': shop,
                                                   'query': keep.urlencode(), 'low_count': low_count,
                                                   'filtered': bool(q or cat_id or status)})


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

        form = ProductForm(request.POST, request.FILES, shop=shop)
        try:
            rows = variants.rows_from_post(request.POST, unit=_posted_unit(request.POST))
        except variants.VariantError as exc:
            rows = None
            messages.error(request, str(exc))
        if rows is not None and form.is_valid():
            with transaction.atomic():
                product = form.save(commit=False)
                product.shop = shop
                product.save()
                form.save_extra_barcodes(product)
                variants.save_rows(product, rows, stock_user=request.user, stock_reason='new')
                if not product.has_variants:
                    stock_log.record(product.pk, None, product.stock_quantity, reason='new', user=request.user)
            messages.success(request, f'"{product.name}" যোগ হয়েছে।')
            if request.POST.get('next') == 'another':
                return redirect('add_product')
            return redirect('product_list')
    else:
        form = ProductForm(shop=shop)
    return render(request, 'store/product_form.html', {'form': form, 'product': None,
                                                       'variant_rows': _variant_rows(request, None)})


def _posted_unit(post):
    unit = post.get('unit')
    return unit if unit in units.LABELS else units.PCS


@login_required(login_url='/accounts/login/')
def edit_product(request, pk):
    product = get_object_or_404(Product, pk=pk, shop=request.user.shop)
    if request.method == 'POST':
        stock_before, had_variants = product.stock_quantity, product.has_variants
        form = ProductForm(request.POST, request.FILES, instance=product)
        try:
            rows = variants.rows_from_post(request.POST, unit=_posted_unit(request.POST))
        except variants.VariantError as exc:
            rows = None
            messages.error(request, str(exc))
        if rows is not None and form.is_valid():
            with transaction.atomic():
                form.save()
                form.save_extra_barcodes(product)
                variants.save_rows(product, rows, stock_user=request.user)
                if not product.has_variants and not had_variants:
                    stock_log.record(product.pk, None, product.stock_quantity - stock_before, reason='manual',
                                     user=request.user)
            messages.success(request, f'"{product.name}" সেভ হয়েছে।')
            return redirect('product_list')
    else:
        form = ProductForm(instance=product)
    return render(request, 'store/product_form.html', {'form': form, 'product': product,
                                                       'variant_rows': _variant_rows(request, product)})


@login_required(login_url='/accounts/login/')
def delete_product(request, pk):
    product = get_object_or_404(Product, pk=pk, shop=request.user.shop)
    # আগে বিক্রি/অর্ডার হয়ে থাকলে মোছা যায় না: মুছলে পুরোনো অর্ডার আর রসিদ থেকে ওই লাইন হারিয়ে যেত (হিসাব ভুল হতো)।
    # তখন শুধু বন্ধ করা হয় — ওয়েবসাইট আর POS-এ দেখায় না, পুরোনো হিসাব ঠিক থাকে।
    used = (OrderItem.objects.filter(product=product).exists()
            or StorefrontOrderItem.objects.filter(product=product).exists()
            or SaleReturnItem.objects.filter(product=product).exists())
    if request.method == 'POST':
        if used:
            if product.is_active:
                product.is_active = False
                product.save(update_fields=['is_active'])
            messages.success(request, f'"{product.name}" বন্ধ করা হলো — আর বিক্রিতে দেখাবে না। আগের অর্ডারে নাম থেকে যাবে।')
        else:
            name = product.name
            product.delete()
            messages.success(request, f'"{name}" মুছে ফেলা হয়েছে।')
        return redirect('product_list')
    return render(request, 'store/delete_product.html', {'product': product, 'used': used})


# ============================================================
# ORDER MANAGEMENT (Multi-Product)
# ============================================================
def _money_field(raw, label):
    """ফর্মের টাকার ঘর → Decimal (ফাঁকা = ০)। অক্ষর বা ঋণাত্মক হলে FlowError।"""
    from decimal import Decimal, InvalidOperation
    text = str(raw or '').strip().translate(BN_TO_EN_DIGITS).replace(',', '')
    if not text:
        return Decimal('0')
    try:
        value = Decimal(text).quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError):
        raise order_flow.FlowError(f'{label} সংখ্যায় লিখুন।')
    if not value.is_finite() or value < 0 or value > Decimal('99999999'):
        raise order_flow.FlowError(f'{label} ঠিক নেই।')
    return value


def _create_manual_order(shop, post, user=None):
    """
    ফোন/ইনবক্সের অর্ডার হাতে তোলা। সব একসাথে (atomic): ভুল হলে কিছুই তৈরি হয় না।
    পরিমাণ ১-এর কম বা স্টকের বেশি হলে আটকায় — আগে ঋণাত্মক পরিমাণে স্টক বেড়ে যেত, আর স্টকের বেশি লিখে
    পরে বাতিল করলে বাড়তি মাল স্টকে ঢুকত।
    """
    name = (post.get('customer_name') or '').strip()[:150]
    address = (post.get('customer_address') or '').strip()[:500]
    phone = _storefront_customer_phone(post.get('customer_phone') or '')
    if not name or not address:
        raise order_flow.FlowError('কাস্টমারের নাম আর ঠিকানা দিন।')
    if not phone:
        raise order_flow.FlowError('সঠিক মোবাইল নম্বর দিন (০১ দিয়ে শুরু, ১১ সংখ্যা)।')
    delivery_charge = _money_field(post.get('delivery_charge'), 'ডেলিভারি চার্জ')
    discount = _money_field(post.get('discount'), 'ছাড়')

    # "Full Paid" = আগে পুরো টাকা নেওয়া (কুরিয়ার ৳০ তুলবে)। আংশিক অগ্রিম হলে COD, অগ্রিমটা advance_paid-এ —
    # কুরিয়ার শুধু বাকিটা তোলে (store/couriers.py cod_amount)
    payment_method, advance = post.get('payment_method', 'COD'), 0
    if payment_method == 'Full Paid':
        payment_method = 'Paid'
    elif payment_method == 'Partial Paid':
        advance = _money_field(post.get('advance_amount'), 'অগ্রিম')
        payment_method = 'COD'
    elif payment_method not in ('COD', 'Paid'):
        payment_method = 'COD'

    lines = {}
    product_ids, prices, quantities = post.getlist('product[]'), post.getlist('price[]'), post.getlist('quantity[]')
    for index, raw_id in enumerate(product_ids):
        if not raw_id:
            continue
        try:
            key = int(raw_id)
        except ValueError:
            raise order_flow.FlowError('প্রোডাক্ট বা পরিমাণ ঠিক নেই।')
        raw_qty = str(quantities[index] if index < len(quantities) else '').strip() or '1'
        try:
            qty = _qty_field(raw_qty, 'পরিমাণ')
        except order_flow.FlowError:
            raise order_flow.FlowError('পরিমাণ কমপক্ষে ১ হতে হবে।')
        price = _money_field(prices[index] if index < len(prices) else '', 'দাম')
        if key in lines:
            lines[key]['qty'] += qty
        else:
            lines[key] = {'qty': qty, 'price': price}
    if not lines:
        raise order_flow.FlowError('অন্তত একটা প্রোডাক্ট বেছে নিন।')

    with transaction.atomic():
        # ড্রপডাউনের মান: প্রোডাক্টের id, আর সাইজ/রং হলে ঋণাত্মক ভ্যারিয়েন্ট id (store/variants.py)
        chosen = variants.resolve(shop, lines.keys(), lock=True)
        subtotal = 0
        for key, line in lines.items():
            item = chosen.get(key)
            if item is None or item.needs_choice:
                raise order_flow.FlowError('একটা প্রোডাক্ট আর পাওয়া যাচ্ছে না। পাতাটা আবার খুলে চেষ্টা করুন।')
            if not units.fits(line['qty'], item.product.unit):
                raise order_flow.FlowError(units.whole_msg(item.name))
            if item.stock < line['qty']:
                raise order_flow.FlowError(f'"{item.name}" স্টকে আছে মাত্র {units.show(item.stock, item.product.unit)}।')
            subtotal += units.money(line['price'] * line['qty'])
        total = max(subtotal + delivery_charge - discount, 0)
        customer, _created = Customer.objects.get_or_create(shop=shop, phone=phone,
                                                            defaults={'name': name, 'address': address})
        if not _created:
            customer.name, customer.address = name, address
            customer.save(update_fields=['name', 'address'])
        order = Order.objects.create(
            shop=shop, customer=customer, delivery_charge=delivery_charge, discount=discount,
            payment_method=payment_method, status='Pending', total_amount=total, advance_paid=min(advance, total))
        for key, line in lines.items():
            item = chosen[key]
            OrderItem.objects.create(order=order, product=item.product, variant=item.variant,
                                     variant_name=item.variant_name, price=line['price'], quantity=line['qty'],
                                     cost_price=item.cost_price)
            variants.take(item, line['qty'], reason='order', order=order, user=user)
    return order


@login_required(login_url='/accounts/login/')
def order_create(request):
    shop = request.user.shop

    posted = {}
    if request.method == 'POST':
        try:
            order = _create_manual_order(shop, request.POST, request.user)
        except order_flow.FlowError as exc:
            messages.error(request, str(exc))
            # ভুল হলে পুরো ফর্ম আবার খালি না করে যা লেখা ছিল তা রেখে দেখানো হয়
            post = request.POST
            posted = {key: post.get(key, '') for key in ('customer_name', 'customer_phone', 'customer_address',
                                                         'delivery_charge', 'discount', 'payment_method',
                                                         'advance_amount')}
            posted['rows'] = [{'id': i, 'price': pr, 'qty': q} for i, pr, q in zip(
                post.getlist('product[]'), post.getlist('price[]'), post.getlist('quantity[]')) if i][:50]
        else:
            messages.success(request, f'অর্ডার #ORD-{order.id} তৈরি হয়েছে।')
            return redirect('order_list')

    from . import delivery
    zones = [{'name': z.name, 'charge': units.num(z.charge)} for z in delivery.zones_for(shop)]
    return render(request, 'store/order_create.html', {
        'products': _order_product_options(shop), 'posted': posted, 'zones': zones,
        'rows': posted.get('rows', []),
        'phone': posted.get('customer_phone') or request.GET.get('phone', ''),
    })


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
    """অর্ডার এডিট: কাস্টমারের তথ্য, আর (পাঠানোর আগে) প্রোডাক্ট যোগ-বাদ, পরিমাণ, দাম, ডেলিভারি চার্জ, ছাড় — স্টক ঠিক রেখে।"""
    shop = request.user.shop
    order = get_object_or_404(Order.objects.select_related('customer'), id=order_id, shop=shop)
    locked_reason = order_flow.items_locked_reason(order)
    if request.method == 'POST':
        name = (request.POST.get('customer_name') or '').strip()[:150]
        address = (request.POST.get('customer_address') or '').strip()[:500]
        raw_phone = (request.POST.get('customer_phone') or '').strip()
        # নম্বর না বদলালে যেমন আছে তেমন (POS-এর নাম ছাড়া কাস্টমারের নম্বর আসল নম্বর না)
        phone = order.customer.phone if raw_phone == order.customer.phone else _storefront_customer_phone(raw_phone)
        try:
            if not name or not address:
                raise order_flow.FlowError('কাস্টমারের নাম আর ঠিকানা দিন।')
            if not phone:
                raise order_flow.FlowError('সঠিক মোবাইল নম্বর দিন (০১ দিয়ে শুরু, ১১ সংখ্যা)।')
            changes, additions = {}, []
            if not locked_reason:
                for item in order.items.all():
                    qty = _qty_field(request.POST.get(f'item_qty_{item.id}', item.quantity), 'পরিমাণ', allow_zero=True)
                    price = _money_field(request.POST.get(f'item_price_{item.id}', item.price), 'দাম')
                    changes[item.id] = (qty, price)
                keys, qtys, prices = (request.POST.getlist('new_product[]'), request.POST.getlist('new_qty[]'),
                                      request.POST.getlist('new_price[]'))
                for index, raw_key in enumerate(keys):
                    if not raw_key.lstrip('-').isdigit():
                        continue
                    qty = _qty_field(qtys[index] if index < len(qtys) else '1', 'পরিমাণ')
                    price = _money_field(prices[index] if index < len(prices) else '', 'দাম')
                    additions.append((int(raw_key), qty, price))
                delivery_charge = _money_field(request.POST.get('delivery_charge'), 'ডেলিভারি চার্জ')
                discount = _money_field(request.POST.get('discount'), 'ছাড়')
            with transaction.atomic():
                customer = order.customer
                if phone != customer.phone:
                    # নম্বর বদলালে: সেই নম্বরের কাস্টমার আগে থেকে থাকলে অর্ডারটা তার নামে যায় (এক নম্বরে দুজন কাস্টমার
                    # হয় না); না থাকলে নতুন কাস্টমার — পুরনো কাস্টমারের অন্য অর্ডারের নম্বর বদলায় না
                    customer, _created = Customer.objects.get_or_create(shop=shop, phone=phone,
                                                                        defaults={'name': name, 'address': address})
                    Order.objects.filter(pk=order.pk).update(customer=customer)
                customer.name, customer.address = name, address
                customer.save(update_fields=['name', 'address'])
                if not locked_reason:
                    order_flow.edit_items(order, changes, additions, delivery_charge=delivery_charge,
                                          discount=discount, user=request.user)
        except order_flow.FlowError as exc:
            messages.error(request, str(exc))
            return redirect('order_edit', order_id=order.id)
        messages.success(request, f'অর্ডার #ORD-{order.id} বদলানো হয়েছে।')
        return redirect('order_list')
    items = list(order.items.select_related('product'))
    return render(request, 'store/order_edit.html', {
        'order': order, 'items': items, 'locked_reason': locked_reason,
        'status_bn': order_flow.STATUS_BN.get(order.status, order.status),
        **_refund_context(request, order),
        'subtotal': sum((i.price * i.quantity for i in items), 0),
        'products': [] if locked_reason else _order_product_options(shop),
    })


def _refund_context(request, order):
    """অর্ডার এডিট পাতার "টাকা ফেরত" অংশ — কাস্টমার অনলাইনে দিয়ে থাকলে তবেই।"""
    from . import shop_payments
    paid_online = order.customer_payments.filter(status='Completed').exists()
    if not paid_online:
        return {'refund_box': False}
    return {'refund_box': True, 'refund_left': shop_payments.refundable(order),
            'refunds': list(order.refunds.all()), 'refund_methods': shop_payments.REFUND_METHODS,
            'can_refund': _can_handle_money(request.user)}


def _qty_field(raw, label, *, allow_zero=False):
    """
    ফর্মের পরিমাণের ঘর → Decimal (০–৯৯৯৯; allow_zero হলে ০ মানে বাদ)। কেজি/লিটারের প্রোডাক্টে দশমিক চলে (১.৫);
    পিসের প্রোডাক্টে পূর্ণ সংখ্যা কিনা order_flow/অর্ডার তৈরির সময় প্রোডাক্ট দেখে যাচাই হয়।
    """
    from decimal import Decimal
    try:
        return units.parse(raw, 'kg', label=label, allow_zero=allow_zero, maximum=Decimal(9999))
    except units.QtyError as exc:
        raise order_flow.FlowError(str(exc))


def _order_product_options(shop):
    """অর্ডার ফর্মের প্রোডাক্টের তালিকা: স্টকে থাকা প্রোডাক্ট, সাইজ/রং থাকলে প্রতিটা আলাদা (id ঋণাত্মক)।"""
    options = []
    for product in (Product.objects.filter(shop=shop, is_active=True, stock_quantity__gt=0)
                    .prefetch_related('variants').order_by('name')):
        if product.has_variants:
            options += [{'id': -v.id, 'name': f'{product.name} ({v.name})', 'price': v.sell_price,
                         'stock': units.num(v.stock_quantity), 'unit': product.unit,
                         'unit_label': units.LABELS.get(product.unit, '')}
                        for v in product.variants.all() if v.stock_quantity > 0]
        else:
            options.append({'id': product.id, 'name': product.name, 'price': product.price,
                            'stock': units.num(product.stock_quantity), 'unit': product.unit,
                            'unit_label': units.LABELS.get(product.unit, '')})
    return options


def _can_handle_money(user):
    return not getattr(user, 'is_shop_staff', False) or user.staff_profile.can_manage_settings


@login_required(login_url='/accounts/login/')
def order_refund(request, order_id):
    """অনলাইনে টাকা দেওয়া অর্ডারে কাস্টমারকে টাকা ফেরত (shop_payments.create_refund)। মালিক বা সেটিংসের অনুমতিওয়ালা স্টাফ।"""
    from . import shop_payments
    shop = request.user.shop
    order = get_object_or_404(Order, id=order_id, shop=shop)
    if request.method != 'POST':
        return redirect('order_edit', order_id=order.id)
    if not _can_handle_money(request.user):
        messages.error(request, 'টাকা ফেরত শুধু দোকানের মালিক বা সেটিংসের অনুমতিওয়ালা স্টাফ দিতে পারেন।')
        return redirect('order_edit', order_id=order.id)
    way = request.POST.get('way', '')
    try:
        refund = shop_payments.create_refund(
            order, request.POST.get('amount'), way, method=request.POST.get('method', ''),
            account=request.POST.get('account', ''), reference=request.POST.get('reference', ''),
            note=request.POST.get('note', ''), user=request.user)
    except shop_payments.SettlementError as exc:
        messages.error(request, str(exc))
        return redirect(reverse('order_edit', args=[order.id]) + '#refund')
    if refund.way == refund.PLATFORM:
        messages.success(request, f'৳{refund.amount:,.0f} ফেরতের অনুরোধ গেছে — {django_settings.SITE_NAME} কাস্টমারের '
                                  f'{refund.method}-এ পাঠালে কাস্টমার আর আপনি SMS পাবেন।')
    else:
        messages.success(request, f'৳{refund.amount:,.0f} ফেরত দেওয়া লেখা হয়েছে।')
    return redirect(reverse('order_edit', args=[order.id]) + '#refund')


@login_required(login_url='/accounts/login/')
def order_delete(request, order_id):
    """শুধু POST-এ মোছে। POS-এর বিক্রি আর অনলাইনে টাকা পাওয়া অর্ডার মোছা যায় না — হিসাব নষ্ট হয়; সেগুলো ফেরত/বাতিল হয়।"""
    shop = request.user.shop
    if request.method != 'POST':
        return redirect('order_list')
    order = get_object_or_404(Order, id=order_id, shop=shop)
    if order.source == 'pos':
        messages.error(request, 'POS-এর বিক্রি মোছা যায় না। POS-এর "আজকের বিক্রি" থেকে ফেরত নিন।')
        return redirect('order_list')
    if order.online_payment_status == Order.ONLINE_PAID or order.customer_payments.filter(status='Completed').exists():
        messages.error(request, 'এই অর্ডারে কাস্টমার অনলাইনে টাকা দিয়েছে, তাই মোছা যায় না। দরকার হলে অর্ডারটা বাতিল করুন।')
        return redirect('order_list')
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        if not order.stock_returned:        # বাতিল/ফেরত হয়ে মাল আগেই স্টকে ফিরে থাকলে আবার না
            for item in order.items.all():
                variants.give_back(item.product_id, item.variant_id, item.quantity, reason='order_delete',
                                   order=order, user=request.user)
        order.delete()
    messages.success(request, f'অর্ডার #ORD-{order_id} মুছে ফেলা হয়েছে, মাল স্টকে ফিরেছে।')
    return redirect('order_list')


@login_required(login_url='/accounts/login/')
def order_pulse(request):
    """
    ড্যাশবোর্ডের "নতুন অর্ডার" নোটিফিকেশন (base.html প্রতি ৪৫ সেকেন্ডে জিজ্ঞেস করে; SMS-এর খরচ নেই)।
    after=<শেষ দেখা অর্ডারের id> দিলে তার পরে কাস্টমারের দেওয়া (ওয়েবসাইট/Messenger) অর্ডারগুলো; না দিলে শুধু এখনকার শেষ id।
    """
    shop = request.user.shop
    orders = Order.objects.filter(shop=shop, source='storefront')
    latest = orders.order_by('-id').values_list('id', flat=True).first() or 0
    after = request.GET.get('after', '')
    fresh = []
    if after.isdigit() and int(after) < latest:
        fresh = [{'id': o.id, 'name': o.customer.name, 'total': f'{o.total_amount:,.0f}'.translate(EN_TO_BN_DIGITS)}
                 for o in orders.filter(id__gt=int(after)).exclude(status__in=('Cancelled', 'Returned'))
                 .select_related('customer').order_by('-id')[:5]]
    return JsonResponse({'latest': latest, 'new': fresh,
                         'pending': orders.filter(status='Pending').count()})


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
            order_flow.set_status(order, data.get('status'), user=request.user)
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
    # POS-এর নাম ছাড়া বিলগুলো একটা "Walk-in Customer"-এ জমা হয় — সে আসল কাস্টমার না, তালিকায় দেখানো হয় না
    customers = Customer.objects.filter(shop=shop).exclude(phone=pos.WALK_IN_PHONE).annotate(
        total_orders=Count('orders'),
        # বাতিল আর ফেরত অর্ডারের টাকা "মোট কেনা"-য় ধরা হয় না
        total_spent=Sum('orders__total_amount', filter=~Q(orders__status__in=['Returned', 'Cancelled'])),
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
    ('data', 'bi-database-down', 'ডাটা ও ব্যাকআপ'),
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


def security_page(request):
    """নিরাপত্তা ও ডাটা — ব্যাকআপের কার্ড শুধু টাটকা সফল পরীক্ষা থাকলে, নজরদারির লাইন শুধু STATUS_PAGE_URL থাকলে।"""
    import json
    from django.conf import settings as dj_settings
    from django.utils.html import format_html, strip_tags
    from . import marketing, shop_payments
    from .plans import STOREFRONT_GRACE_DAYS
    bn = str.maketrans('0123456789', '০১২৩৪৫৬৭৮৯')
    site = dj_settings.SITE_NAME
    backup_test = backups.trust_line()
    deletion_days_bn = str(retention.DATA_DELETION_DAYS).translate(bn)
    fee = str(shop_payments.fee_percent().normalize()).translate(bn)
    from .company import PROMISES
    notice_bn, reply_bn, fix_bn = (str(PROMISES[key]).translate(bn) for key in
                                   ('shutdown_notice_days', 'support_reply_hours', 'outage_fix_hours'))
    try:
        facebook_live = marketing.facebook_live()
    except Exception:    # noqa: BLE001
        facebook_live = False
    # কেনার আগে মানুষ (আর AI) যা জানতে চায় — প্রতিটা উত্তরের পেছনে কোড আছে; যা এখনো নেই, তা লেখা হয় না
    faq = [
        (f'{site} কোনোদিন বন্ধ হয়ে গেলে আমার তথ্যের কী হবে?',
         f'বন্ধ করতে হলে অন্তত {notice_bn} দিন আগে SMS দিয়ে আর এই ওয়েবসাইটে জানানো হবে। সেই সময়ে সব তথ্য Excel-এ, আর '
         'প্রোডাক্ট Shopify বা WooCommerce-এর ফাইলে নামিয়ে নিতে পারবেন। এমনিতেও যেকোনো সময় সব তথ্য নামানো যায় — নিয়মিত '
         'নামিয়ে রাখাই সবচেয়ে নিরাপদ।'),
        ('কোনো সমস্যা হলে কত তাড়াতাড়ি সাহায্য পাব?',
         f'ফোন, WhatsApp বা ইমেইলে জানালে সর্বোচ্চ {reply_bn} ঘণ্টার মধ্যে উত্তর দেওয়া হয়। সার্ভার বন্ধ হলে {fix_bn} ঘণ্টার '
         'মধ্যে আবার চালু করার চেষ্টা করা হয়।'),
        ('অন্য প্ল্যাটফর্মে (Shopify, WooCommerce) চলে যেতে চাইলে?',
         'সেটিংস → ডাটা ও ব্যাকআপ থেকে প্রোডাক্টের ফাইল নামান — Shopify আর WooCommerce-এর Import যেভাবে চায় ঠিক সেভাবে: '
         'নাম, বিবরণ, দাম, আগের দাম, স্টক, সাইজ-রং, ক্যাটাগরি আর ছবির লিংক (ছবি ওরা লিংক থেকে নিজেই নামিয়ে নেয়)। কাস্টমার, '
         'অর্ডার আর হিসাবের সব তথ্য আলাদা Excel ফাইলে। প্ল্যাটফর্মের নিজের সফটওয়্যার বা ডিজাইনের কোড এর মধ্যে দেওয়া হয় না।'),
        ('কাস্টমারের অনলাইন পেমেন্টের টাকা কোথায় যায়, কত ফি?',
         f'বিক্রিতে কোনো কমিশন নেই। কাস্টমার ওয়েবসাইটে অনলাইনে টাকা দিলে প্রতিটা পেমেন্টে {fee}% ফি কাটে — পেমেন্ট গেটওয়ের '
         '(PayStation) চার্জ এর মধ্যেই ধরা, কাস্টমারকে দামের বাইরে বাড়তি কিছু দিতে হয় না; ক্যাশ অন ডেলিভারিতে কোনো ফি নেই। টাকা আগে আমাদের PayStation অ্যাকাউন্টে আসে, '
         f'প্রতিটা পেমেন্টের {str(shop_payments.SETTLEMENT_HOLD_DAYS).translate(bn)} দিন পর আর অন্তত '
         f'৳{format(int(shop_payments.SETTLEMENT_MIN), ",").translate(bn)} জমলে আপনার bKash, Nagad, Rocket বা ব্যাংকে তুলে '
         'নিতে পারেন। কত জমা, কত তোলা যাবে আর কবে — সব ওয়েবসাইট → পেমেন্ট পাতায় দেখায়।'),
        ('নিজের ডোমেইন কোন প্যাকেজে পাব?',
         'শুধু Premium প্যাকেজে। ডোমেইনটা (যেমন www.yourshop.com) আপনি যেকোনো ডোমেইন বিক্রেতার কাছ থেকে কিনবেন, তার খরচ '
         'আলাদা; ডোমেইনের DNS-এ একটা CNAME রেকর্ড বসালে দোকান সেই ঠিকানায় খোলে। সব প্যাকেজেই নিজের নামের সাবডোমেইন ঠিকানা ফ্রি।'),
        ('আমার কাস্টমারের নম্বর কি অন্য দোকান বা অন্য কেউ দেখতে পায়?',
         'না। প্রতিটা দোকানের তথ্য আলাদা, শুধু সেই দোকানের মালিক আর যে স্টাফকে কাস্টমার দেখার অনুমতি দেওয়া হয়েছে তারাই দেখেন।'),
        ('স্টাফ কতটুকু দেখতে পায়?',
         'যতটুকু আপনি অনুমতি দেন — POS-এ বিক্রি, প্রোডাক্ট, অর্ডার, কাস্টমার, রিপোর্ট, সেটিংস আর SMS পাঠানো আলাদা করে চালু/বন্ধ '
         'করা যায়। সব ডাটা একসাথে নামানো শুধু মালিক পারেন।'),
        ('Facebook কমেন্ট আর Messenger-এর অটো রিপ্লাই কি চালু?',
         'হ্যাঁ, Standard আর Premium প্যাকেজে আর ফ্রি ট্রায়ালে সব দোকানে চালু।' if facebook_live else
         'সফটওয়্যারে তৈরি আছে। Facebook-এর নিয়মে Meta প্রতিটা অ্যাপ যাচাই করে; সেই যাচাই শেষ হলেই Standard আর Premium '
         'প্যাকেজের সব দোকানে চালু হবে। এই পাতাতেই তখন জানিয়ে দেওয়া হবে।'),
        ('বিকাশ বা কার্ডের তথ্য কি আপনারা রাখেন?',
         'না। পেমেন্ট হয় PayStation-এর পাতায়; আমরা শুধু লেনদেন নম্বর আর পরিমাণ পাই, যা রসিদে দেখায়।'),
        ('বিল না দিলে তথ্য কত দিন থাকে?',
         f'মেয়াদ শেষের পর {deletion_days_bn} দিন। এই সময়ে প্যাকেজ কিনলে কিছুই হারায় না, আর যেকোনো দিন সব ডাটা নামাতে পারেন। '
         'মোছার আগে কয়েকবার SMS যায়।'),
        ('অ্যাকাউন্ট পুরো মুছে ফেলতে চাইলে?',
         format_html('আগে সব ডাটা নামিয়ে নিন, তারপর <a href="{}">মুছে ফেলার নিয়ম</a> অনুযায়ী অনুরোধ করুন।',
                     reverse('data_deletion'))),
    ]
    if backup_test:
        faq.insert(1, ('আপনারা কি ব্যাকআপ রাখেন?',
                       'হ্যাঁ। প্রতি রাতে পুরো ডাটাবেসের এনক্রিপ্ট করা কপি আলাদা, গোপন স্টোরেজে রাখা হয়, ৩০ দিন পর্যন্ত; নিয়মিত '
                       f'সেই ব্যাকআপ থেকে পুরো ফেরত এনে মিলিয়ে দেখা হয় — শেষবার {backup_test["date"]}-এ।'))
    faq_ld = json.dumps({'@context': 'https://schema.org', '@type': 'FAQPage', 'mainEntity': [
        {'@type': 'Question', 'name': q, 'acceptedAnswer': {'@type': 'Answer', 'text': strip_tags(a)}} for q, a in faq]},
        ensure_ascii=False).replace('</', '<\\/')
    return render(request, 'store/security.html', {
        'backup_test': backup_test,
        'status_page': getattr(dj_settings, 'STATUS_PAGE_URL', ''),
        'grace_days_bn': str(STOREFRONT_GRACE_DAYS).translate(bn),
        'deletion_days_bn': deletion_days_bn,
        'faq': faq, 'faq_ld': faq_ld,
    })


@login_required(login_url='/accounts/login/')
def export_platform_csv(request, platform):
    """সেটিংস → ডাটা ও ব্যাকআপ: অন্য প্ল্যাটফর্মে নিতে প্রোডাক্টের CSV (store/platform_export.py)। শুধু মালিক।"""
    from django.utils import timezone as tz
    from . import platform_export
    shop = getattr(request.user, 'shop', None)
    if shop is None or shop.user_id != request.user.id:
        messages.error(request, 'এই ফাইল শুধু দোকানের মালিক নামাতে পারেন।')
        return redirect('dashboard')
    build = platform_export.shopify_csv if platform == 'shopify' else platform_export.woocommerce_csv
    body = build(shop, request.build_absolute_uri)
    response = HttpResponse(body, content_type='text/csv; charset=utf-8')
    name = f'{shop.slug}-{platform}-products-{tz.localdate():%Y-%m-%d}.csv'
    response['Content-Disposition'] = f'attachment; filename="{name}"'
    return response


@login_required(login_url='/accounts/login/')
def export_all_data(request):
    """সেটিংস → ডাটা ও ব্যাকআপ: দোকানের সব তথ্য এক Excel-এ (store/data_export.py)। শুধু মালিক; লক থাকলেও চলে।"""
    from .data_export import build_full_export, export_filename
    shop = getattr(request.user, 'shop', None)
    if shop is None or shop.user_id != request.user.id:
        messages.error(request, 'সব ডাটা শুধু দোকানের মালিক নামাতে পারেন।')
        return redirect('dashboard')
    workbook = build_full_export(shop, absolute=request.build_absolute_uri)
    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="{export_filename(shop)}"'
    workbook.save(response)
    return response


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
        'is_owner': shop.user_id == request.user.id,
        'backup_test': backups.trust_line() if active_tab == 'data' else None,
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
    order_flow.set_status(order, 'Shipped', user=request.user)         # চালু থাকলে কাস্টমারকে ট্র্যাকিং লিংকসহ SMS
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
    ).exclude(steadfast_tracking_code__exact='').select_related('customer').order_by('-created_at')
    # চারটা সংখ্যা একটা প্রশ্নে (আগে চারটা আলাদা), আর তালিকার কাস্টমার একসাথে (আগে প্রতি সারিতে একটা করে)
    stats = courier_orders.order_by().aggregate(
        total=Count('id'), delivered=Count('id', filter=Q(status='Delivered')),
        shipped=Count('id', filter=Q(status='Shipped')),
        failed=Count('id', filter=Q(status__in=('Returned', 'Cancelled'))))
    delivered, shipped, failed, total = stats['delivered'], stats['shipped'], stats['failed'], stats['total']
    courier_stats = [
        ('মোট পার্সেল', total, '#3b82f6', 'bi-truck'),
        ('পথে আছে', shipped, '#8b5cf6', 'bi-truck-front'),
        ('ডেলিভারি হয়েছে', delivered, '#22c55e', 'bi-check-circle'),
        ('ফেরত/বাতিল', failed, '#ef4444', 'bi-x-circle'),
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
                order_flow.set_status(order, new_status, user=request.user)
            except order_flow.FlowError:
                pass
    return JsonResponse({'message': 'OK'}, status=200)


# ============================================================
# PUBLIC STOREFRONT
# ============================================================
# ============================================================
# BILLING
# ============================================================
# billing_page moved below with full payment request support


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
    """যেসব ক্যাটাগরিতে বিক্রির মতো প্রোডাক্ট আছে — ওয়েবসাইটের ক্যাটাগরি বার আর "সব ক্যাটাগরি" তালিকা।
    প্রতিটার .n = কয়টা প্রোডাক্ট কেনা যায় (তালিকায় নামের পাশে দেখায়)।"""
    on_sale = Q(product__is_active=True, product__stock_quantity__gt=0)
    return list(Category.objects.filter(shop=shop).annotate(n=Count('product', filter=on_sale))
                .filter(n__gt=0).order_by('name'))


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

    variant_list = [{'id': -v.id, 'name': v.name, 'price': float(v.sell_price), 'stock': units.num(v.stock_quantity)}
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
    from . import ratelimit
    ip = ratelimit.client_ip(request)
    if (number or phone) and ratelimit.blocked('sf-track', ip, TRACK_LIMIT):
        error = sf_lang.t('অনেকবার চেষ্টা হয়েছে। কিছুক্ষণ পর আবার চেষ্টা করুন।', shop)
    elif number or phone:
        digits = ''.join(ch for ch in number.translate(str.maketrans('০১২৩৪৫৬৭৮৯', '0123456789')) if ch.isdigit())
        clean_phone = _storefront_customer_phone(phone)
        order = (Order.objects.filter(shop=shop, pk=digits, customer__phone=clean_phone).exclude(source='pos').first()
                 if digits and len(digits) < 12 and clean_phone else None)
        if order is not None:
            return redirect(storefront_link(shop, 'storefront_track_order', order_flow.track_code(order),
                                            request=request))
        ratelimit.hit('sf-track', ip, TRACK_WINDOW)
        error = sf_lang.t('এই অর্ডার নম্বর আর মোবাইল নম্বর মিলিয়ে কোনো অর্ডার পাওয়া যায়নি। নম্বর দুটো আবার দেখে নিন।', shop)
    return render(request, 'store/storefront/track.html', {
        'shop': shop, 'order': None, 'error': error, 'number': number, 'phone': phone,
        'meta': seo.storefront_meta(request, shop, title=sf_lang.t('অর্ডার ট্র্যাক করুন — {shop}', shop, shop=shop.name),
                                    description=sf_lang.t('{shop}-এ দেওয়া অর্ডার এখন কোথায় আছে দেখুন।', shop, shop=shop.name),
                                    link_name='storefront_track'),
    })


def storefront_track_order(request, shop_slug, code):
    """SMS-এর লিংক বা খোঁজার পর: অর্ডারের অবস্থা। কোড না মিললে খোঁজার পেজে।"""
    from . import ratelimit
    shop = get_object_or_404(Shop, slug=shop_slug)
    # লিংকের কোড ছোট (SMS-এ জায়গা কম) — তাই আন্দাজ করে অন্যের অর্ডার খোলা ঠেকাতে ভুলের সীমা
    ip = ratelimit.client_ip(request)
    order = None if ratelimit.blocked('sf-track', ip, TRACK_LIMIT) else order_flow.order_from_code(shop, code)
    if order is None:
        ratelimit.hit('sf-track', ip, TRACK_WINDOW)
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
    from . import ratelimit
    ip = ratelimit.client_ip(request)
    if ratelimit.blocked('sf-coupon', ip, COUPON_LIMIT):
        return JsonResponse({'ok': False, 'error': sf_lang.t('অনেকবার চেষ্টা হয়েছে। কিছুক্ষণ পর আবার চেষ্টা করুন।', shop)},
                            status=429)
    try:
        coupon, discount, delivery_off = offers.find(shop, data.get('code'), subtotal, charge or 0)
    except offers.CouponError as exc:
        ratelimit.hit('sf-coupon', ip, COUPON_WINDOW)
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


# ওয়েবসাইটের চেষ্টার সীমা (store/ratelimit.py)
ORDER_IP_LIMIT, ORDER_IP_WINDOW = 12, 10 * 60          # এক IP: ১০ মিনিটে ১২টা অর্ডার
ORDER_PHONE_LIMIT, ORDER_PHONE_WINDOW = 6, 60 * 60     # এক দোকানে এক নম্বর: ঘণ্টায় ৬টা
TRACK_LIMIT, TRACK_WINDOW = 20, 10 * 60                # অর্ডার খোঁজায় ভুল: ১০ মিনিটে ২০ বার
COUPON_LIMIT, COUPON_WINDOW = 30, 10 * 60              # কুপন কোড আন্দাজ: ১০ মিনিটে ৩০ বার ভুল


def storefront_place_order(request, shop_slug):
    """
    দোকানের ওয়েবসাইট থেকে অর্ডার (AJAX POST, JSON)।
    দাম, ডেলিভারি চার্জ আর অনলাইনে কত দিতে হবে, সব সার্ভারে হিসাব হয় (store/storefront_orders.py — Messenger-এর
    চ্যাট-অর্ডারও একই রাস্তায়); ব্রাউজার থেকে শুধু প্রোডাক্ট-পরিমাণ, এলাকার id আর পেমেন্টের ধরন আসে।
    """
    from . import fb_ref, storefront_orders

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

    source = fb_ref.from_session(request, shop)     # Facebook-এর কমেন্ট/Messenger-এর লিংক থেকে এলে
    phone = _storefront_customer_phone(data.get('phone') or '')
    # ভুয়া অর্ডারের বন্যা ঠেকাতে (স্টক আটকে যায়, সেলারের SMS খরচ হয়): এক IP আর এক নম্বর থেকে অল্প সময়ে সীমিত অর্ডার
    from . import ratelimit
    ip = ratelimit.client_ip(request)
    if ratelimit.too_many('sf-order-ip', ip, ORDER_IP_LIMIT, ORDER_IP_WINDOW) or (
            phone and ratelimit.too_many('sf-order-phone', f'{shop.pk}:{phone}', ORDER_PHONE_LIMIT, ORDER_PHONE_WINDOW)):
        return JsonResponse({'success': False, 'error': sf_lang.t(
            'অল্প সময়ে অনেকগুলো অর্ডার দেওয়া হয়েছে। কিছুক্ষণ পর আবার চেষ্টা করুন, বা দোকানে সরাসরি যোগাযোগ করুন।', shop)},
            status=429)
    try:
        placed = storefront_orders.place(
            shop, quantities=quantities, name=data.get('name'), phone=phone, address=data.get('address'),
            note=data.get('note'), zone_id=data.get('zone'), coupon_code=data.get('coupon'),
            payment_choice=data.get('payment'), landing_slug=data.get('landing'), **source)
    except storefront_orders.OrderError as exc:
        reply = {'success': False, 'error': str(exc)}
        if exc.coupon_error:
            reply['coupon_error'] = True
        return JsonResponse(reply)
    main_order, sf_order, pay_now = placed.order, placed.sf_order, placed.pay_now

    # অর্ডার-সফল পেইজে কাস্টমারের নাম-ঠিকানা থাকে; শুধু যে ব্রাউজার থেকে অর্ডার হয়েছে সে-ই দেখতে পাবে
    placed_ids = request.session.get('sf_orders', [])
    request.session['sf_orders'] = (placed_ids + [sf_order.id])[-20:]
    success_url = storefront_link(shop, 'storefront_order_success', sf_order.id, request=request)
    if main_order.messenger_contact_id:
        from . import messenger
        messenger.order_received(main_order)

    if pay_now > 0:
        result = _start_customer_payment(request, shop, main_order, sf_order, placed.choice, pay_now)
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
                    order_flow.set_status(sf_order.order, new_status, user=request.user)
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

    selected_ids = [i for i in request.GET.getlist('ids') if i.lstrip('-').isdigit()]
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


STAFF_PERMISSIONS = ('can_use_pos', 'can_manage_products', 'can_manage_orders', 'can_manage_customers',
                     'can_view_reports', 'can_manage_settings', 'can_send_sms')
STAFF_PASSWORD_MIN = 6


def _owner_only(request):
    """স্টাফ অ্যাকাউন্ট বানানো/বদলানো শুধু দোকানের মালিকের কাজ — "সেটিংস" অনুমতি পাওয়া স্টাফও নিজের বা অন্যের অনুমতি বা
    পাসওয়ার্ড বদলাতে পারে না।"""
    if getattr(request.user, 'is_shop_staff', False):
        messages.error(request, 'স্টাফ অ্যাকাউন্ট শুধু দোকানের মালিক বদলাতে পারেন।')
        return redirect('dashboard')
    return None


@login_required(login_url='/accounts/login/')
def add_edit_staff(request, staff_id=None):
    denied = _owner_only(request)
    if denied:
        return denied
    from accounts.forms import normalize_bd_mobile
    shop = request.user.shop
    staff_profile = get_object_or_404(StaffProfile, id=staff_id, shop=shop) if staff_id else None
    if staff_profile is None and not can_add_staff(shop):
        # নতুন স্টাফ যোগের সময় প্যাকেজের সীমা দেখা হয় (এডিট সবসময় চলবে)
        messages.error(request, f"আপনার প্যাকেজে সর্বোচ্চ {staff_limit(shop)} জন স্টাফ রাখা যায়। "
                                "আরও স্টাফ যোগ করতে Billing থেকে প্যাকেজ আপগ্রেড করুন।")
        return redirect('staff_list')

    if request.method == 'POST':
        name = (request.POST.get('name') or '').strip()[:100]
        phone = normalize_bd_mobile(request.POST.get('phone') or '')
        password = request.POST.get('password') or ''
        permissions = {field: request.POST.get(field) == 'on' for field in STAFF_PERMISSIONS}
        error = ''
        if not name:
            error = 'স্টাফের নাম দিন।'
        elif not phone:
            error = 'সঠিক মোবাইল নম্বর দিন (০১ দিয়ে শুরু, ১১ সংখ্যা)।'
        elif (password or staff_profile is None) and len(password) < STAFF_PASSWORD_MIN:
            error = f'পাসওয়ার্ড কমপক্ষে {STAFF_PASSWORD_MIN} অক্ষরের দিন।'
        elif User.objects.filter(phone_number=phone).exclude(
                pk=staff_profile.user_id if staff_profile else None).exists():
            error = 'এই নম্বরে আগে থেকেই একটা অ্যাকাউন্ট আছে। অন্য নম্বর দিন।'
        if error:
            messages.error(request, error)
            return redirect('edit_staff', staff_id=staff_profile.id) if staff_profile else redirect('add_staff')

        with transaction.atomic():
            if staff_profile:
                staff_user = staff_profile.user
                staff_user.name, staff_user.phone_number = name, phone
                if password:            # নতুন পাসওয়ার্ড দিলে তবেই বদলায়
                    staff_user.set_password(password)
                staff_user.save()
                for field, value in permissions.items():
                    setattr(staff_profile, field, value)
                staff_profile.save()
                messages.success(request, 'স্টাফের তথ্য বদলানো হয়েছে।')
            else:
                new_user = User.objects.create_user(phone_number=phone, password=password, name=name)
                StaffProfile.objects.create(user=new_user, shop=shop, **permissions)
                messages.success(request, 'নতুন স্টাফ অ্যাকাউন্ট তৈরি হয়েছে।')
        return redirect('staff_list')

    return render(request, 'store/add_staff.html', {'staff': staff_profile})


@login_required(login_url='/accounts/login/')
def staff_list(request):
    denied = _owner_only(request)
    if denied:
        return denied
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
        'deletion': retention.deletion_notice(shop),           # মেয়াদ শেষ: কবে সব তথ্য মুছে যাবে (৯০ দিনের নিয়ম)
        'is_owner': shop.user_id == request.user.id,
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
            from . import messenger
            messenger.setup_profile(FacebookPageConnection.objects.select_related('shop').get(shop=shop))
            messages.success(request, f"'{selected_page.get('name')}' পেইজ যুক্ত হয়েছে। "
                                      "এখন পোস্টে কেউ কমেন্ট করলে বা ইনবক্সে লিখলে নিজে থেকে উত্তর যাবে।",
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
