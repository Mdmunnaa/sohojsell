# ============================================================
# SohojSell - Store Views (Clean Version)
# ============================================================
import json
from django.db.models import Count
import requests
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.template.loader import get_template
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
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
from .forms import ShopSetupForm, ProductForm, OrderCreateForm, ShopSettingsForm
from .links import storefront_link
from . import couriers
from .themes import THEMES
from django.urls import reverse


# ============================================================
# LANDING PAGE
# ============================================================
def landing_page(request):
    if request.user.is_authenticated:
        if request.user.is_superuser:
            return redirect('master_dashboard')
        return redirect('dashboard')
    return render(request, 'store/landing.html')


# ============================================================
# SELLER DASHBOARD
# ============================================================
# ফাইলের একদম উপরে এই দুইটা ইম্পোর্ট আছে কি না শিওর হয়ে নিন (না থাকলে বসিয়ে দিন):
# from django.db.models import Count
# from .models import Order, OrderItem, Product, PageView

@login_required(login_url='/accounts/login/')
def seller_dashboard(request):
    if not hasattr(request.user, 'shop'):
        return redirect('setup_shop')

    shop = request.user.shop
    today = timezone.now().date()

    # =======================================================
    # 💰 Sales & Revenue Logic
    # =======================================================
    today_orders = Order.objects.filter(
        shop=shop, created_at__date=today
    ).exclude(status__in=['Returned', 'Cancelled'])

    # ✅ Optimized: N+1 → 1 query using aggregate + F expressions
    from django.db.models import F as Fexp
    stats = OrderItem.objects.filter(
        order__in=today_orders
    ).aggregate(
        revenue=Sum(Fexp('price') * Fexp('quantity')),
        profit=Sum((Fexp('price') - Fexp('cost_price')) * Fexp('quantity'))
    )
    today_revenue = stats['revenue'] or 0
    today_profit = stats['profit'] or 0

    low_stock_products = Product.objects.filter(shop=shop, stock_quantity__lt=5, is_active=True)
    recent_orders = Order.objects.filter(shop=shop).select_related('customer').order_by('-created_at')[:5]

    # =======================================================
    # 📊 Analytics: View Tracking (New Addition)
    # =======================================================
    # ১. আজকের মোট ভিজিটর (স্টোরফ্রন্ট + প্রোডাক্ট ভিউ)
    today_views = PageView.objects.filter(shop=shop, created_at__date=today).count()

    # ২. সবচেয়ে জনপ্রিয় (Most Viewed) ৩টি প্রোডাক্ট
    top_products = Product.objects.filter(shop=shop).annotate(
        view_count=Count('views')
    ).filter(view_count__gt=0).order_by('-view_count')[:3]

    context = {
        'shop': shop,
        'today_orders_count': today_orders.count(),
        'today_revenue': today_revenue,
        'today_profit': today_profit,
        'low_stock_products': low_stock_products,
        'recent_orders': recent_orders,
        'today_views': today_views,  # নতুন অ্যাড হলো
        'top_products': top_products,  # নতুন অ্যাড হলো
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
            messages.success(request, "🎉 দোকান তৈরি হয়েছে! ৩০ দিন সব ফিচার ফ্রি।")
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
        if form.is_valid():
            product = form.save(commit=False)
            product.shop = shop
            product.save()
            messages.success(request, "Product added successfully!")
            return redirect('product_list')
    else:
        form = ProductForm()
    return render(request, 'store/add_product.html', {'form': form})


@login_required(login_url='/accounts/login/')
def edit_product(request, pk):
    product = get_object_or_404(Product, pk=pk, shop=request.user.shop)
    if request.method == 'POST':
        form = ProductForm(request.POST, request.FILES, instance=product)
        if form.is_valid():
            form.save()
            messages.success(request, "Product updated!")
            return redirect('product_list')
    else:
        form = ProductForm(instance=product)
    return render(request, 'store/edit_product.html', {'form': form, 'product': product})


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
                product = get_object_or_404(Product, id=p_id, shop=shop)
                OrderItem.objects.create(
                    order=order, product=product, price=price,
                    quantity=qty, cost_price=product.cost_price
                )
                product.stock_quantity = max(0, product.stock_quantity - qty)
                product.save()
                subtotal += price * qty

        order.total_amount = max(0, subtotal + delivery_charge - discount)
        order.save()
        messages.success(request, f"Order #ORD-{order.id} created successfully!")
        return redirect('order_list')

    products = Product.objects.filter(shop=shop, is_active=True, stock_quantity__gt=0)
    return render(request, 'store/order_create.html', {'products': products})


@login_required(login_url='/accounts/login/')
def order_list(request):
    shop = request.user.shop
    orders = Order.objects.filter(shop=shop).select_related('customer').order_by('-id')

    search_query = request.GET.get('q', '')
    if search_query:
        orders = orders.filter(
            Q(id__icontains=search_query) |
            Q(customer__name__icontains=search_query) |
            Q(customer__phone__icontains=search_query)
        )

    status_filter = request.GET.get('status', '')
    if status_filter:
        orders = orders.filter(status=status_filter)

    paginator = Paginator(orders, 20)
    page = request.GET.get('page', 1)
    try:
        page_obj = paginator.page(page)
    except (EmptyPage, PageNotAnInteger):
        page_obj = paginator.page(1)
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
        for item in order.items.all():
            item.product.stock_quantity += item.quantity
            item.product.save()
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
            order = Order.objects.get(id=data.get('order_id'), shop=shop)
            order.status = data.get('status')
            order.save()
            return JsonResponse({'success': True, 'message': f'Order #{order.id} updated!'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})


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
    return render(request, 'store/customers.html', {'page_obj': page_obj})


# ============================================================
# REPORTS
# ============================================================
import csv
from django.http import HttpResponse


@login_required(login_url='/accounts/login/')
def business_reports(request):
    shop = request.user.shop
    today = timezone.now().date()
    valid_orders = Order.objects.filter(shop=shop).exclude(status__in=['Returned', 'Cancelled']).order_by('-created_at')

    # Date Filtering Logic
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    if start_date:
        valid_orders = valid_orders.filter(created_at__date__gte=start_date)
    if end_date:
        valid_orders = valid_orders.filter(created_at__date__lte=end_date)

    # ✅ Optimized: aggregate for revenue & profit (1 query instead of N+1)
    from django.db.models import F as Fexp
    agg = OrderItem.objects.filter(order__in=valid_orders).aggregate(
        profit=Sum((Fexp('price') - Fexp('cost_price')) * Fexp('quantity'))
    )
    net_profit = agg['profit'] or 0
    total_revenue = valid_orders.aggregate(total=Sum('total_amount'))['total'] or 0

    # ✅ Optimized: select_related to avoid per-order customer query
    order_details = []
    for order in valid_orders.select_related('customer').prefetch_related('items'):
        order_profit = sum(
            (item.price - item.cost_price) * item.quantity
            for item in order.items.all()
        )
        order_details.append({
            'id': order.id,
            'date': order.created_at.strftime('%Y-%m-%d %I:%M %p'),
            'customer': order.customer.name,
            'amount': order.total_amount,
            'profit': order_profit,
            'status': order.status
        })

    # Export to Excel (CSV format)
    if request.GET.get('export') == 'excel':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="Business_Report.csv"'
        writer = csv.writer(response)

        # Excel Header
        writer.writerow(['Order ID', 'Date', 'Customer Name', 'Total Amount (Tk)', 'Net Profit (Tk)', 'Status'])
        # Excel Data Rows
        for o in order_details:
            writer.writerow([f"#ORD-{o['id']}", o['date'], o['customer'], o['amount'], o['profit'], o['status']])

        # Summary Row at the bottom of Excel
        writer.writerow([])
        writer.writerow(['', '', 'TOTAL:', f"{total_revenue} Tk", f"{net_profit} Tk", ''])

        return response

    # Default Overall Stats (Unaffected by filter)
    all_valid = Order.objects.filter(shop=shop).exclude(status__in=['Returned', 'Cancelled'])
    start_of_week = today - timedelta(days=7)
    today_sales = all_valid.filter(created_at__date=today).aggregate(total=Sum('total_amount'))['total'] or 0
    weekly_sales = all_valid.filter(created_at__date__gte=start_of_week).aggregate(total=Sum('total_amount'))[
                       'total'] or 0
    monthly_sales = \
    all_valid.filter(created_at__month=today.month, created_at__year=today.year).aggregate(total=Sum('total_amount'))[
        'total'] or 0
    yearly_sales = all_valid.filter(created_at__year=today.year).aggregate(total=Sum('total_amount'))['total'] or 0

    return render(request, 'store/reports.html', {
        'total_revenue': total_revenue,
        'net_profit': net_profit,
        'total_orders': valid_orders.count(),
        'today_sales': today_sales,
        'weekly_sales': weekly_sales,
        'monthly_sales': monthly_sales,
        'yearly_sales': yearly_sales,
        'order_details': order_details,
        'start_date': start_date,
        'end_date': end_date,
    })


# ============================================================
# SETTINGS
# ============================================================
@login_required(login_url='/accounts/login/')
def shop_settings(request):
    shop = request.user.shop
    if request.method == 'POST':
        form = ShopSettingsForm(request.POST, request.FILES, instance=shop)
        if form.is_valid():
            shop = form.save()
            messages.success(request, 'সেটিংস সেভ হয়েছে।')
            _courier_actions_after_save(request, shop, form)
            return redirect(reverse('settings') + ('#couriers' if request.POST.get('courier_action') else ''))
    else:
        form = ShopSettingsForm(instance=shop)
    shop.ensure_webhook_token()
    return render(request, 'store/settings.html', {
        'form': form,
        'facebook_allowed': has_facebook(shop),
        'courier_connected': couriers.connected(shop),
        'fb_recent_replies': shop.fb_comment_replies.select_related('product')[:5],
        'steadfast_webhook_url': request.build_absolute_uri(reverse('steadfast_webhook')),
    })


def _courier_actions_after_save(request, shop, form):
    """সেভের পর: Pathao-র পাসওয়ার্ড দিলে কানেক্ট, আর "কানেকশন টেস্ট" বাটন চাপলে টেস্ট।"""
    password = form.cleaned_data.get('pathao_password')
    if password:
        try:
            stores = couriers.pathao_connect(shop, form.cleaned_data.get('pathao_client_id'),
                                             form.cleaned_data.get('pathao_client_secret'),
                                             form.cleaned_data.get('pathao_email'), password)
            messages.success(request, f'Pathao কানেক্ট হয়েছে ✓ ({len(stores)}টা স্টোর পাওয়া গেছে)। '
                                      'আপনার Pathao পাসওয়ার্ড আমরা সেভ করি না।')
        except couriers.CourierError as exc:
            messages.error(request, str(exc))

    action = request.POST.get('courier_action', '')
    if action.startswith('test_'):
        courier = action[5:]
        if courier in couriers.COURIERS:
            try:
                messages.success(request, couriers.test_connection(shop, courier))
            except couriers.CourierError as exc:
                messages.error(request, str(exc))
    elif action == 'steadfast_disconnect':
        shop.steadfast_api_key = None
        shop.steadfast_secret_key = None
        shop.save(update_fields=['steadfast_api_key', 'steadfast_secret_key'])
        messages.info(request, 'Steadfast-এর চাবি সরানো হয়েছে।')
    elif action == 'redx_disconnect':
        shop.redx_access_token = None
        shop.save(update_fields=['redx_access_token'])
        messages.info(request, 'RedX টোকেন সরানো হয়েছে।')
    elif action == 'pathao_disconnect':
        shop.pathao_access_token = None
        shop.pathao_refresh_token = ''
        shop.pathao_token_expires_at = None
        shop.pathao_client_secret = ''
        shop.pathao_stores = []
        shop.pathao_store_id = None
        shop.save(update_fields=['pathao_access_token', 'pathao_refresh_token', 'pathao_token_expires_at',
                                 'pathao_client_secret', 'pathao_stores', 'pathao_store_id'])
        messages.info(request, 'Pathao-র সংযোগ সরানো হয়েছে।')


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
    order.status = 'Shipped'
    order.save(update_fields=['steadfast_tracking_code', 'courier_partner', 'status'])
    cod = couriers.cod_amount(order)
    messages.success(request, f'{courier}-এ পাঠানো হয়েছে ✓ ট্র্যাকিং: {result["tracking_code"]} · '
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


def _send_sms(phone, text_message):
    print("\n🚀 [DEBUG] _send_sms function called!")
    print(f"📞 Target Phone: {phone}")

    import requests
    from .models import MasterSetting

    base_url = "https://api.smsgateway.com.bd/api/send-message"

    try:
        setting = MasterSetting.objects.get(id=1)
        client_id = setting.sms_client_id
        api_key = setting.sms_api_key
        sender_id = setting.sms_sender_id
    except Exception as e:
        print(f"❌ DB Error: {e}")
        return False

    if not client_id or not api_key:
        print("❌ SMS Cancelled: Client ID or API Key is missing in the database!")
        return False

    headers = {
        'Content-Type': 'application/json'
    }

    payload = {
        "client_id": client_id.strip(),
        "key": api_key.strip(),
        "recipient": phone,
        "message": text_message
    }

    if sender_id:
        payload["sender_id"] = sender_id.strip()

    try:
        print("⏳ Sending request to gateway...")
        response = requests.post(base_url, headers=headers, json=payload, timeout=10)
        result = response.json()
        print(f"📥 Gateway Response: {result}")

        if result.get("response_code") == 200:
            print("✅ SMS Sent Successfully!")
            return True
        else:
            print("❌ Gateway Rejected the SMS!")
            return False
    except Exception as e:
        print(f"❌ Connection Error: {e}")
        return False


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
            order.status = new_status
            order.save(update_fields=['status'])
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
        shop.sms_balance += SMS_BONUS.get(plan_name, 0)
        shop.save(update_fields=['subscription_plan', 'sms_balance'])

    messages.success(request, f"🎉 আপনার shop এখন {plan_name} Plan-এ upgrade হয়েছে!")
    return redirect('dashboard')


# ============================================================
# MASTER DASHBOARD (CEO ONLY)
# ============================================================
@login_required(login_url='/accounts/login/')
def master_dashboard(request):
    if not request.user.is_superuser:
        messages.error(request, "Access Denied!")
        return redirect('order_list')

    from django.contrib.auth import get_user_model
    User = get_user_model()

    total_shops = Shop.objects.count()
    total_users = User.objects.count()
    total_orders = Order.objects.count()
    total_sales = Order.objects.filter(
        status__in=['Delivered', 'Shipped', 'Pending']
    ).aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    recent_shops = Shop.objects.all().order_by('-id')[:10]

    from .models import PaymentRequest
    pending_payments = PaymentRequest.objects.filter(status='Pending').select_related('shop').order_by('-created_at')
    recent_payments = PaymentRequest.objects.filter(status='Approved').select_related('shop').order_by('-created_at')[:10]
    locked_shops = Shop.objects.filter(is_locked=True).order_by('-id')

    return render(request, 'store/master_dashboard.html', {
        'total_shops': total_shops, 'total_users': total_users,
        'total_platform_orders': total_orders, 'total_sales_volume': total_sales,
        'recent_shops': recent_shops,
        'pending_payments': pending_payments,
        'recent_payments': recent_payments,
        'locked_shops': locked_shops,
    })


# ============================================================
# MASTER HQ: MANAGE SHOPS, USERS & BILLING
# ============================================================
@login_required(login_url='/accounts/login/')
def manage_shops(request):
    if not request.user.is_superuser:
        return redirect('dashboard')

    shops = Shop.objects.all().order_by('-created_at')
    search = request.GET.get('q', '')
    if search:
        shops = shops.filter(Q(name__icontains=search) | Q(phone__icontains=search))

    paginator = Paginator(shops, 20)
    page = request.GET.get('page', 1)
    try:
        page_obj = paginator.page(page)
    except (EmptyPage, PageNotAnInteger):
        page_obj = paginator.page(1)

    return render(request, 'store/manage_shops.html', {'page_obj': page_obj, 'search': search})


@login_required(login_url='/accounts/login/')
def all_users(request):
    if not request.user.is_superuser:
        return redirect('dashboard')

    from django.contrib.auth import get_user_model
    User = get_user_model()
    users = User.objects.all().order_by('-date_joined')
    search = request.GET.get('q', '')
    if search:
        users = users.filter(Q(name__icontains=search) | Q(phone_number__icontains=search))

    paginator = Paginator(users, 20)
    page = request.GET.get('page', 1)
    try:
        page_obj = paginator.page(page)
    except (EmptyPage, PageNotAnInteger):
        page_obj = paginator.page(1)

    return render(request, 'store/all_users.html', {'page_obj': page_obj, 'search': search})


@login_required(login_url='/accounts/login/')
def master_billing(request):
    if not request.user.is_superuser:
        return redirect('dashboard')

    from .models import PaymentRequest
    requests = PaymentRequest.objects.all().select_related('shop').order_by('-created_at')

    paginator = Paginator(requests, 20)
    page = request.GET.get('page', 1)
    try:
        page_obj = paginator.page(page)
    except (EmptyPage, PageNotAnInteger):
        page_obj = paginator.page(1)

    return render(request, 'store/master_billing.html', {'page_obj': page_obj})


@login_required(login_url='/accounts/login/')
def recharge_sms(request):
    if not request.user.is_superuser:
        messages.error(request, "Access Denied!")
        return redirect('dashboard')
    if request.method == 'POST':
        try:
            shop = Shop.objects.get(id=request.POST.get('shop_id'))
            amount = int(request.POST.get('amount', 0))
            shop.sms_balance += amount
            shop.save()
            messages.success(request, f"Added {amount} SMS to {shop.name}!")
        except Shop.DoesNotExist:
            messages.error(request, "Shop not found!")
    return redirect('master_dashboard')


@login_required(login_url='/accounts/login/')
def upgrade_shop_plan(request):
    if not request.user.is_superuser:
        messages.error(request, "Access Denied!")
        return redirect('dashboard')
    if request.method == 'POST':
        try:
            shop = Shop.objects.get(id=request.POST.get('shop_id'))
            new_plan = request.POST.get('plan')
            shop.subscription_plan = new_plan
            shop.sms_balance += SMS_BONUS.get(new_plan, 0)
            shop.save()
            messages.success(request, f"{shop.name} upgraded to {new_plan} Plan!")
        except Shop.DoesNotExist:
            messages.error(request, "Shop not found!")
    return redirect('master_dashboard')


@login_required(login_url='/accounts/login/')
def master_settings(request):
    if not request.user.is_superuser:
        return redirect('dashboard')
    setting, _ = MasterSetting.objects.get_or_create(id=1)
    if request.method == 'POST':
        setting.payment_store_id = request.POST.get('payment_store_id')
        setting.payment_secret_key = request.POST.get('payment_secret_key')
        setting.is_payment_live = request.POST.get('is_payment_live') == 'on'

        # SMS ডেটা সেভ করার লজিক
        setting.sms_client_id = request.POST.get('sms_client_id')
        setting.sms_api_key = request.POST.get('sms_api_key')
        setting.sms_sender_id = request.POST.get('sms_sender_id')

        setting.save()
        messages.success(request, "Master Settings Updated!")
        return redirect('master_settings')
    return render(request, 'store/master_settings.html', {'setting': setting})


# ============================================================
# POS SYSTEM (NEW)
# ============================================================
@login_required(login_url='/accounts/login/')
def pos_dashboard(request):
    """Superfast POS interface for offline sales"""
    shop = request.user.shop

    categories = Category.objects.filter(shop=shop)
    products = Product.objects.filter(shop=shop, is_active=True, stock_quantity__gt=0).select_related('category')

    # Build product data for JavaScript
    product_data = []
    for p in products:
        product_data.append({
            'id': p.id,
            'name': p.name,
            'price': float(p.price),
            'cost_price': float(p.cost_price),
            'stock': p.stock_quantity,
            'category': p.category.name if p.category else 'General',
            'category_id': p.category.id if p.category else 0,
        })

    return render(request, 'store/pos.html', {
        'shop': shop,
        'categories': categories,
        'products': products,
        'product_data_json': json.dumps(product_data),
    })


@login_required(login_url='/accounts/login/')
def pos_checkout(request):
    """Process POS sale - creates order directly"""
    if request.method != 'POST':
        return redirect('pos')

    shop = request.user.shop

    try:
        data = json.loads(request.body)
        cart_items = data.get('cart', [])
        payment_method = data.get('payment_method', 'Paid')
        customer_name = data.get('customer_name', 'Walk-in Customer')
        customer_phone = data.get('customer_phone', '00000000000')
        discount = float(data.get('discount', 0))

        if not cart_items:
            return JsonResponse({'success': False, 'error': 'Cart is empty!'})

        # Get or create walk-in customer
        customer, _ = Customer.objects.get_or_create(
            shop=shop, phone=customer_phone,
            defaults={'name': customer_name, 'address': 'POS / In-store'}
        )
        if customer_name != 'Walk-in Customer':
            customer.name = customer_name
            customer.save()

        # Create order (POS = no delivery charge)
        order = Order.objects.create(
            shop=shop, customer=customer,
            delivery_charge=0, discount=discount,
            payment_method=payment_method,
            status='Delivered',  # POS sale = instantly delivered
            total_amount=0
        )

        subtotal = 0
        for item in cart_items:
            product = get_object_or_404(Product, id=item['id'], shop=shop)
            qty = int(item['qty'])
            price = float(item['price'])

            # Stock validation
            if product.stock_quantity < qty:
                order.delete()
                return JsonResponse({
                    'success': False,
                    'error': f"'{product.name}' has only {product.stock_quantity} items in stock!"
                })

            OrderItem.objects.create(
                order=order, product=product,
                price=price, quantity=qty, cost_price=product.cost_price
            )
            product.stock_quantity -= qty
            product.save()
            subtotal += price * qty

        order.total_amount = max(0, subtotal - discount)
        order.save()

        return JsonResponse({
            'success': True,
            'order_id': order.id,
            'total': float(order.total_amount),
            'message': f'Sale complete! Order #ORD-{order.id}'
        })

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required(login_url='/accounts/login/')
def pos_receipt(request, order_id):
    """POS thermal receipt"""
    shop = request.user.shop
    order = get_object_or_404(Order, id=order_id, shop=shop)
    order_items = order.items.all()
    return render(request, 'store/pos_receipt.html', {
        'shop': shop, 'order': order, 'order_items': order_items
    })


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


@ensure_csrf_cookie
def storefront_home(request, shop_slug):
    """Public e-commerce store for customers"""
    shop = get_object_or_404(Shop, slug=shop_slug)

    # ট্রায়ালে আর সব প্ল্যানে চালু; মেয়াদ শেষের পর ৭ দিন পর্যন্ত চালু, তারপর বন্ধ
    if not storefront_is_open(shop):
        return render(request, 'store/storefront/offline.html', {'shop': shop})

    # ==========================================================
    # 🔍 View Tracking Logic (Shop Homepage)
    # ==========================================================
    if not request.session.session_key:
        request.session.create()

    ip = get_client_ip(request)
    session_key = request.session.session_key
    today = timezone.now().date()

    # চেক করছি আজকে এই সেশন থেকে শপের হোমপেজে ভিউ হয়েছে কি না
    view_exists = PageView.objects.filter(
        shop=shop,
        product__isnull=True,  # Product Null মানে এটা হোমপেজ ভিউ
        session_key=session_key,
        created_at__date=today
    ).exists()

    if not view_exists:
        PageView.objects.create(shop=shop, product=None, ip_address=ip, session_key=session_key)
    # ==========================================================

    products = Product.objects.filter(shop=shop, is_active=True, stock_quantity__gt=0).select_related('category')
    categories = Category.objects.filter(shop=shop)

    # --- ডাটাবেস থেকে শপের অ্যাক্টিভ ব্যানারগুলো আনা ---
    banners = Banner.objects.filter(shop=shop, is_active=True).order_by('-id')

    # ১. প্রথমে Category filter করুন
    cat_filter = request.GET.get('cat', '')
    if cat_filter:
        products = products.filter(category__id=cat_filter)

    # ২. এরপর Search filter করুন
    search = request.GET.get('q', '')
    if search:
        products = products.filter(name__icontains=search)

    # QuerySet কে List এ কনভার্ট করে নিচ্ছি যেন রেন্ডম ভ্যালুগুলো টেমপ্লেটে ঠিকমতো যায়
    products = list(products)

    # আসল বিক্রির সংখ্যা (বানানো রেটিং/বিক্রি আর দেখানো হয় না)
    _attach_sold_counts(shop, products)
    top_seller_ids = {p.id for p in sorted((p for p in products if p.sold_count), key=lambda p: -p.sold_count)[:4]}

    product_data = [{'id': p.id, 'name': p.name, 'price': float(p.price), 'stock': p.stock_quantity} for p in products]

    return render(request, 'store/storefront/home.html', {
        'shop': shop,
        'products': products,
        'top_seller_ids': top_seller_ids,
        # ছাড় থাকলে "ছাড় চলছে", না থাকলে নতুন প্রোডাক্ট
        'highlight_products': ([p for p in products if p.discount_percent][:8]
                               or sorted(products, key=lambda p: p.created_at, reverse=True)[:6]),
        'highlight_is_sale': any(p.discount_percent for p in products),
        'categories': categories,
        'banners': banners,
        'product_data_json': json.dumps(product_data),
        'cat_filter': cat_filter,
        'search': search,
        **_checkout_context(shop),
    })


@ensure_csrf_cookie
def storefront_product_detail(request, shop_slug, product_id):
    """Customer-facing single product details page with related products"""
    shop = get_object_or_404(Shop, slug=shop_slug)

    if not storefront_is_open(shop):
        return redirect(storefront_link(shop, request=request))

    product = get_object_or_404(Product, id=product_id, shop=shop, is_active=True)

    # ==========================================================
    # 🔍 View Tracking Logic (Product View)
    # ==========================================================
    if not request.session.session_key:
        request.session.create()

    ip = get_client_ip(request)
    session_key = request.session.session_key
    today = timezone.now().date()

    # চেক করছি আজকে এই সেশন থেকে এই নির্দিষ্ট প্রোডাক্টে ভিউ হয়েছে কি না
    view_exists = PageView.objects.filter(
        shop=shop,
        product=product,
        session_key=session_key,
        created_at__date=today
    ).exists()

    if not view_exists:
        PageView.objects.create(shop=shop, product=product, ip_address=ip, session_key=session_key)
    # ==========================================================


    # ম্যাজিক লজিক: একই ক্যাটাগরির অন্য প্রোডাক্টগুলো খুঁজে বের করা (বর্তমান প্রোডাক্ট বাদে)
    related_products = Product.objects.filter(
        shop=shop,
        category=product.category,
        is_active=True
    ).exclude(id=product.id).order_by('-id')[:4]  # সর্বোচ্চ ৪টা দেখাবে

    # QuerySet কে List এ কনভার্ট করে নিচ্ছি
    related_products = list(related_products)

    _attach_sold_counts(shop, [product] + related_products)

    return render(request, 'store/storefront/product_detail.html', {
        'shop': shop,
        'product': product,
        'related_products': related_products,
        **_checkout_context(shop),
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
        return JsonResponse({'success': False, 'error': 'এই দোকান এখন অর্ডার নিচ্ছে না।'})

    try:
        data = json.loads(request.body or b'{}')
        cart_items = data.get('cart') or []
        quantities = {}
        for item in cart_items:
            product_id, qty = int(item['id']), int(item['qty'])
            if qty < 1 or qty > 999:
                return JsonResponse({'success': False, 'error': 'পরিমাণ ঠিক নেই।'})
            quantities[product_id] = quantities.get(product_id, 0) + qty
    except (ValueError, TypeError, KeyError):
        return JsonResponse({'success': False, 'error': 'অর্ডারের তথ্য ঠিক নেই, পেইজটা আবার খুলুন।'})
    if not quantities:
        return JsonResponse({'success': False, 'error': 'কার্ট খালি!'})

    name = (data.get('name') or '').strip()[:150]
    address = (data.get('address') or '').strip()[:500]
    note = (data.get('note') or '').strip()[:500]
    phone = _storefront_customer_phone(data.get('phone') or '')
    if not name or not address:
        return JsonResponse({'success': False, 'error': 'নাম, মোবাইল নম্বর আর ঠিকানা দিন।'})
    if not phone:
        return JsonResponse({'success': False, 'error': 'সঠিক মোবাইল নম্বর দিন (০১ দিয়ে শুরু, ১১ সংখ্যা)।'})

    choices = shop_payments.checkout_choices(shop)
    choice = data.get('payment') or choices[0]
    if choice not in choices:
        return JsonResponse({'success': False, 'error': 'পেমেন্টের ধরন বেছে নিন।'})

    with transaction.atomic():
        # একসাথে অনেকে অর্ডার দিলেও স্টকের চেয়ে বেশি বিক্রি না হয়
        products = {p.id: p for p in Product.objects.select_for_update()
                    .filter(shop=shop, id__in=quantities.keys(), is_active=True)}
        if len(products) != len(quantities):
            return JsonResponse({'success': False, 'error': 'কার্টের একটা প্রোডাক্ট আর পাওয়া যাচ্ছে না। কার্ট দেখে আবার চেষ্টা করুন।'})
        subtotal = Decimal('0')
        for product_id, qty in quantities.items():
            product = products[product_id]
            if product.stock_quantity < qty:
                return JsonResponse({'success': False,
                                     'error': f"'{product.name}' স্টকে আছে মাত্র {product.stock_quantity}টা।"})
            subtotal += product.price * qty

        zone, delivery_charge = delivery.charge_for(shop, data.get('zone'), subtotal)
        if delivery_charge is None:
            return JsonResponse({'success': False, 'error': 'ডেলিভারির এলাকা বেছে নিন।'})
        total = subtotal + delivery_charge
        pay_now = shop_payments.amount_now(choice, total, delivery_charge)

        sf_order = StorefrontOrder.objects.create(
            shop=shop, customer_name=name, customer_phone=phone, customer_address=address,
            customer_note=note, total_amount=total, delivery_charge=delivery_charge,
            delivery_zone=zone.name if zone else '', status='Pending')
        customer, _ = Customer.objects.get_or_create(shop=shop, phone=phone,
                                                     defaults={'name': name, 'address': address})
        customer.name, customer.address = name, address
        customer.save(update_fields=['name', 'address'])
        order_note = ' · '.join(x for x in [f'এলাকা: {zone.name}' if zone else '', note] if x) or None
        main_order = Order.objects.create(
            shop=shop, customer=customer, source='storefront', delivery_charge=delivery_charge, discount=0,
            payment_method='COD', status='Pending', total_amount=total, note=order_note,
            online_payment_status=Order.ONLINE_PENDING if pay_now > 0 else Order.ONLINE_NONE)
        sf_order.order = main_order
        sf_order.save(update_fields=['order'])
        for product_id, qty in quantities.items():
            product = products[product_id]
            StorefrontOrderItem.objects.create(order=sf_order, product=product, quantity=qty, price=product.price)
            OrderItem.objects.create(order=main_order, product=product, price=product.price, quantity=qty,
                                     cost_price=product.cost_price)
            product.stock_quantity -= qty
            product.save(update_fields=['stock_quantity'])

    # অর্ডার-সফল পেইজে কাস্টমারের নাম-ঠিকানা থাকে; শুধু যে ব্রাউজার থেকে অর্ডার হয়েছে সে-ই দেখতে পাবে
    placed = request.session.get('sf_orders', [])
    request.session['sf_orders'] = (placed + [sf_order.id])[-20:]
    success_url = storefront_link(shop, 'storefront_order_success', sf_order.id, request=request)

    if pay_now > 0:
        result = _start_customer_payment(request, shop, main_order, sf_order, choice, pay_now)
        if not result.get('ok'):
            # গেটওয়ে কাজ না করলে অর্ডারটা বাতিল না করে রেখে দেওয়া হয়; কাস্টমার অর্ডার পেইজ থেকে আবার চেষ্টা করতে পারবে
            return JsonResponse({'success': True, 'order_id': sf_order.id, 'redirect': success_url,
                                 'message': result.get('error')})
        return JsonResponse({'success': True, 'order_id': sf_order.id, 'redirect': result['payment_url']})

    if shop.is_sms_active and (shop.sms_balance or 0) > 0:
        _send_sms(phone, f"প্রিয় {name}, {shop.name} থেকে আপনার অর্ডার (#ORD-{main_order.id}) পাওয়া গেছে। "
                         "আমরা শীঘ্রই যোগাযোগ করব।")
        Shop.objects.filter(pk=shop.pk, sms_balance__gt=0).update(sms_balance=F('sms_balance') - 1)
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
    request.session['sf_payment_msg'] = {'order': payment.sf_order_id, 'status': status, 'message': msg}
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
    request.session['sf_payment_msg'] = {'order': order_id, 'status': 'failed', 'message': result.get('error')}
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
        payment_label = ('অনলাইনে পুরো টাকা পরিশোধিত' if not main.due_amount else
                         f'অনলাইনে ৳{main.advance_paid:.0f} দেওয়া হয়েছে, বাকি ৳{main.due_amount:.0f} পণ্য হাতে পেয়ে')
    elif payment_pending:
        payment_label = 'অনলাইন পেমেন্ট এখনো হয়নি'
    else:
        payment_label = 'ক্যাশ অন ডেলিভারি'
    return render(request, 'store/storefront/order_success.html', {
        'shop': shop, 'order': order, 'main_order': main, 'last_payment': last_payment,
        'payment_msg': payment_msg, 'payment_pending': payment_pending, 'payment_label': payment_label,
        'order_no': f'ORD-{main.id}' if main else f'SF-{order.id}',
    })


# ============================================================
# SELLER: View Storefront Orders in Dashboard
# ============================================================
@login_required(login_url='/accounts/login/')
def storefront_orders(request):
    """Seller sees all online orders from their storefront"""
    shop = request.user.shop
    sf_orders = StorefrontOrder.objects.filter(shop=shop).order_by('-created_at')

    search = request.GET.get('q', '')
    if search:
        sf_orders = sf_orders.filter(
            Q(customer_name__icontains=search) |
            Q(customer_phone__icontains=search)
        )

    status_filter = request.GET.get('status', '')
    if status_filter:
        sf_orders = sf_orders.filter(status=status_filter)

    paginator = Paginator(sf_orders, 20)
    page_number = request.GET.get('page', 1)
    sf_orders = paginator.get_page(page_number)

    return render(request, 'store/storefront_orders.html', {
        'sf_orders': sf_orders,
        'search': search,
        'status_filter': status_filter,
    })


@login_required(login_url='/accounts/login/')
def storefront_order_update_status(request, order_id):
    """Seller updates storefront order status"""
    shop = request.user.shop
    sf_order = get_object_or_404(StorefrontOrder, id=order_id, shop=shop)
    if request.method == 'POST':
        new_status = request.POST.get('status')
        if new_status in ['Pending', 'Confirmed', 'Shipped', 'Delivered', 'Cancelled']:
            sf_order.status = new_status
            sf_order.save()
            messages.success(request, f'Order #{sf_order.id} updated to {new_status}!')
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
@login_required(login_url='/accounts/login/')
def barcode_lookup(request):
    """AJAX: Look up product by barcode — used by POS scanner"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            barcode = data.get('barcode', '').strip()
            shop = request.user.shop

            if not barcode:
                return JsonResponse({'success': False, 'error': 'No barcode provided'})

            product = Product.objects.get(barcode=barcode, shop=shop, is_active=True)

            if product.stock_quantity <= 0:
                return JsonResponse({'success': False, 'error': f'"{product.name}" is out of stock!'})

            return JsonResponse({
                'success': True,
                'product': {
                    'id': product.id,
                    'name': product.name,
                    'price': float(product.price),
                    'cost_price': float(product.cost_price),
                    'stock': product.stock_quantity,
                    'barcode': product.barcode,
                    'category': product.category.name if product.category else 'General',
                    'category_id': product.category.id if product.category else 0,
                }
            })

        except Product.DoesNotExist:
            return JsonResponse({'success': False, 'error': f'No product found for barcode: {data.get("barcode")}'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})

    return JsonResponse({'success': False, 'error': 'Invalid request'})


@login_required(login_url='/accounts/login/')
def barcode_print(request):
    """Bulk barcode print page — seller selects products, prints stickers"""
    shop = request.user.shop
    products = Product.objects.filter(shop=shop, is_active=True).order_by('name')

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
                    can_manage_settings=can_manage_settings
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
# submit_payment_request moved below
@login_required(login_url='/accounts/login/')
def billing_page(request):
    from .payments import online_payment_available, recheck_pending
    from . import paystation

    shop = request.user.shop
    # callback হারিয়ে গেলেও টাকা কাটা পেমেন্ট যেন ঝুলে না থাকে — পেইজ খুললেই আবার যাচাই
    for payment in recheck_pending(shop):
        messages.success(request, f"✅ আপনার {payment.plan_name} পেমেন্ট নিশ্চিত হয়েছে।")
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
    if request.method != 'POST':
        return redirect('billing')

    shop = request.user.shop

    # Already pending request?
    if shop.payment_requests.filter(status='Pending').exists():
        messages.warning(request, "আপনার একটি payment request review-এ আছে। অপেক্ষা করুন।")
        return redirect('billing')

    plan_name = request.POST.get('plan_name')
    payment_method = request.POST.get('payment_method')
    sender_number = request.POST.get('sender_number')
    transaction_id = request.POST.get('transaction_id')
    amount = request.POST.get('amount')
    note = request.POST.get('note', '')

    if not all([plan_name, payment_method, sender_number, transaction_id, amount]):
        messages.error(request, "সব field পূরণ করুন!")
        return redirect('billing')

    # Duplicate transaction check
    from .models import PaymentRequest
    if PaymentRequest.objects.filter(transaction_id=transaction_id).exists():
        messages.error(request, "এই Transaction ID আগে ব্যবহার হয়েছে!")
        return redirect('billing')

    PaymentRequest.objects.create(
        shop=shop,
        plan_name=plan_name,
        payment_method=payment_method,
        sender_number=sender_number,
        transaction_id=transaction_id,
        amount=amount,
        status='Pending',
    )

    messages.success(request, "✅ Payment request submitted! আমরা শীঘ্রই verify করব।")
    return redirect('billing')


@login_required(login_url='/accounts/login/')
def approve_payment(request, request_id):
    if not request.user.is_superuser:
        return redirect('dashboard')
    if request.method != 'POST':
        return redirect('master_dashboard')

    from .models import PaymentRequest
    from django.utils import timezone
    from datetime import timedelta

    pay_req = get_object_or_404(PaymentRequest, id=request_id)
    shop = pay_req.shop
    today = timezone.now().date()

    if pay_req.plan_name == 'SMS Recharge':
        # ০.৪০ টাকা করে SMS হিসাব
        sms_added = int(float(pay_req.amount) / 0.40)
        shop.sms_balance += sms_added
        shop.save(update_fields=['sms_balance'])
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
    return redirect('master_dashboard')


@login_required(login_url='/accounts/login/')
def reject_payment(request, request_id):
    """Admin rejects a payment request"""
    if not request.user.is_superuser:
        messages.error(request, "Access Denied!")
        return redirect('dashboard')

    from .models import PaymentRequest
    pay_req = get_object_or_404(PaymentRequest, id=request_id)
    pay_req.status = 'Rejected'
    pay_req.save()

    messages.warning(request, f"❌ {pay_req.shop.name}-এর payment rejected!")
    return redirect('master_dashboard')


@login_required(login_url='/accounts/login/')
def manual_unlock(request, shop_id):
    """Admin manually unlocks/extends a shop"""
    if not request.user.is_superuser:
        return redirect('dashboard')

    if request.method == 'POST':
        shop = get_object_or_404(Shop, id=shop_id)
        advance_days = int(request.POST.get('advance_days', 30))
        today = date.today()

        if shop.valid_until and shop.valid_until >= today:
            shop.valid_until = shop.valid_until + timedelta(days=advance_days)
        else:
            shop.valid_until = today + timedelta(days=advance_days)

        shop.is_locked = False
        shop.save()
        messages.success(request, f"✅ {shop.name} manually unlocked! Valid until: {shop.valid_until}")

    return redirect('master_dashboard')


import csv
from django.http import HttpResponse


# ============================================================
# CSV TEMPLATE DOWNLOAD
# ============================================================
@login_required(login_url='/accounts/login/')
def download_csv_template(request):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="sohojsell_product_template.csv"'

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

        msg = f'✅ {created_count} products imported successfully!'
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
            messages.success(request, f"✅ '{selected_page.get('name')}' পেইজ কানেক্ট হয়েছে। "
                                      "এখন পোস্টে কেউ কমেন্ট করলে তার ইনবক্সে অর্ডারের লিংক চলে যাবে।")
        else:
            messages.warning(request, f"'{selected_page.get('name')}' পেইজ কানেক্ট হয়েছে, কিন্তু কমেন্টের খবর পাওয়া "
                                      "চালু করা যায়নি। একটু পরে আবার কানেক্ট করে দেখুন।")
        return redirect('dashboard')

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
        return redirect('settings')
    shop = getattr(request.user, 'shop', None)
    if shop:
        from .facebook_bot import unsubscribe_page
        for connection in FacebookPageConnection.objects.filter(shop=shop):
            unsubscribe_page(connection.page_id, connection.page_access_token)
        FacebookPageConnection.objects.filter(shop=shop).delete()
        SocialToken.objects.filter(account__user=request.user, account__provider='facebook').delete()
        messages.success(request, "Facebook Page disconnect করা হয়েছে, আর সেভ করা Facebook টোকেন মুছে ফেলা হয়েছে।")
    return redirect('settings')


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
            messages.success(request, 'কমেন্ট বটের সেটিং সেভ হয়েছে।')
    return redirect(reverse('settings') + '#facebook')


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
