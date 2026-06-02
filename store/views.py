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
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Count, Sum, Q
from django.utils import timezone
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from datetime import timedelta
from xhtml2pdf import pisa
import random

from .models import Shop, Product, Category, Order, OrderItem, Customer, MasterSetting, Banner
from .forms import ShopSetupForm, ProductForm, OrderCreateForm, ShopSettingsForm


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
    if hasattr(request.user, 'shop'):
        return redirect('dashboard')

    if request.method == 'POST':
        Shop.objects.create(
            user=request.user,
            name=request.POST.get('shop_name'),
            phone=request.user.phone_number,
            address=request.POST.get('address'),
            facebook_page_url=request.POST.get('fb_link')
        )
        messages.success(request, "Shop setup complete! Welcome to your dashboard.")
        return redirect('dashboard')

    return render(request, 'store/setup_shop.html')


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
        product_count = Product.objects.filter(shop=shop).count()
        plan = shop.subscription_plan
        LIMITS = {'Free': 20, 'Basic': 100, 'Standard': 200}
        limit = LIMITS.get(plan)
        if limit and product_count >= limit:
            messages.error(request, f"{plan} Plan limit ({limit} products) reached! Please upgrade.")
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
        # Free plan invoice limit
        if shop.subscription_plan == 'Free':
            order_count = Order.objects.filter(shop=shop).count()
            if order_count >= 30:
                messages.error(request, "Free plan limit (30 invoices) reached! Please upgrade.")
                return redirect('order_list')

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
            form.save()
            messages.success(request, 'Settings updated successfully!')
            return redirect('settings')
    else:
        form = ShopSettingsForm(instance=shop)
    return render(request, 'store/settings.html', {'form': form})


# ============================================================
# COURIER (STEADFAST)
# ============================================================
@login_required(login_url='/accounts/login/')
def send_to_courier(request):
    if request.method == 'POST':
        shop = request.user.shop
        order_id = request.POST.get('order_id')
        courier = request.POST.get('courier_partner')

        order = get_object_or_404(Order, id=order_id, shop=shop)

        if order.steadfast_tracking_code:
            messages.warning(request, 'This order is already sent to a courier!')
            return redirect('order_list')

        # ==========================================
        # 1. STEADFAST COURIER LOGIC
        # ==========================================
        if courier == 'Steadfast':
            if not shop.steadfast_api_key or not shop.steadfast_secret_key:
                messages.error(request, 'Steadfast API keys are missing in Settings!')
                return redirect('order_list')

            url = "https://portal.steadfast.com.bd/api/v1/create_order"
            headers = {
                'Api-Key': shop.steadfast_api_key,
                'Secret-Key': shop.steadfast_secret_key,
                'Content-Type': 'application/json'
            }
            data = {
                'invoice': f'ORD-{order.id}',
                'recipient_name': order.customer.name,
                'recipient_phone': order.customer.phone,
                'recipient_address': order.customer.address,
                'cod_amount': float(order.total_amount),
                'note': 'Sent via SohojSell'
            }

            try:
                response = requests.post(url, headers=headers, json=data)
                result = response.json()
                if response.status_code == 200 and result.get('status') == 200:
                    tracking_code = result.get('consignment', {}).get('tracking_code')
                    order.steadfast_tracking_code = tracking_code
                    order.courier_partner = 'Steadfast'
                    order.status = 'Shipped'
                    order.save()
                    messages.success(request, f'Sent to Steadfast! Tracking: {tracking_code}')
                else:
                    messages.error(request, f"Steadfast Error: {result.get('message')}")
            except Exception as e:
                messages.error(request, f"Failed: {str(e)}")

        # ==========================================
        # 2. PATHAO COURIER LOGIC
        # ==========================================
        elif courier == 'Pathao':
            if not shop.pathao_store_id or not shop.pathao_access_token:
                messages.error(request, 'Pathao API keys are missing in Settings!')
                return redirect('order_list')

            url = "https://api-hermes.pathao.com/aladdin/api/v1/orders"
            headers = {
                'Authorization': f'Bearer {shop.pathao_access_token}',
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            }
            data = {
                "store_id": shop.pathao_store_id,
                "merchant_order_id": f'ORD-{order.id}',
                "recipient_name": order.customer.name,
                "recipient_phone": order.customer.phone,
                "recipient_address": order.customer.address,
                "recipient_city": "1",  # (Dhaka) For production, you'll need City ID mapping
                "recipient_zone": "1",
                "delivery_type": 48,
                "item_type": 2,
                "item_quantity": 1,
                "item_weight": 0.5,
                "amount_to_collect": float(order.total_amount)
            }

            try:
                response = requests.post(url, headers=headers, json=data)
                result = response.json()
                if response.status_code in [200, 201]:
                    tracking_code = result.get('data', {}).get('consignment_id')
                    order.steadfast_tracking_code = tracking_code  # ট্র্যাকিং কোড সেভ
                    order.courier_partner = 'Pathao'
                    order.status = 'Shipped'
                    order.save()
                    messages.success(request, f'Sent to Pathao! Tracking: {tracking_code}')
                else:
                    messages.error(request, "Pathao Error: Check API Token and IDs.")
            except Exception as e:
                messages.error(request, f"Failed: {str(e)}")

        # ==========================================
        # 3. REDX COURIER LOGIC
        # ==========================================
        elif courier == 'RedX':
            if not shop.redx_access_token:
                messages.error(request, 'RedX Access Token is missing!')
                return redirect('order_list')

            url = "https://openapi.redx.com.bd/v1.0.0-beta/parcel"
            headers = {
                'Authorization': f'Bearer {shop.redx_access_token}',
                'Content-Type': 'application/json'
            }
            data = {
                "customer_name": order.customer.name,
                "customer_phone": order.customer.phone,
                "delivery_area": "Dhaka",  # For production, you'll need RedX Area ID mapping
                "customer_address": order.customer.address,
                "merchant_invoice_id": f'ORD-{order.id}',
                "cash_collection_amount": float(order.total_amount),
                "parcel_weight": 500
            }

            try:
                response = requests.post(url, headers=headers, json=data)
                result = response.json()
                if 'tracking_id' in result:
                    tracking_code = result.get('tracking_id')
                    order.steadfast_tracking_code = tracking_code
                    order.courier_partner = 'RedX'
                    order.status = 'Shipped'
                    order.save()
                    messages.success(request, f'Sent to RedX! Tracking: {tracking_code}')
                else:
                    messages.error(request, "RedX Error: Invalid token or area.")
            except Exception as e:
                messages.error(request, f"Failed: {str(e)}")

    return redirect('order_list')

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

        print(f"🔑 Fetched Client ID: '{client_id}'")
        print(f"🔑 Fetched API Key: '{api_key}'")
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
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            invoice = data.get('invoice')
            new_status = data.get('status')
            if invoice and new_status:
                order_id = invoice.replace('ORD-', '')
                order = Order.objects.get(id=order_id)
                if new_status.lower() == 'delivered':
                    order.status = 'Delivered'
                elif new_status.lower() in ['cancelled', 'returned']:
                    order.status = 'Cancelled'
                order.save()
                return JsonResponse({'message': 'Status updated!'}, status=200)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)
    return JsonResponse({'message': 'Webhook active!'}, status=200)


# ============================================================
# PUBLIC STOREFRONT
# ============================================================
def public_shop(request, shop_slug):
    shop = get_object_or_404(Shop, slug=shop_slug)

    if shop.subscription_plan in ['Free', 'Basic']:
        return HttpResponse(
            f"<div style='text-align:center;margin-top:100px;font-family:sans-serif;'>"
            f"<h2>{shop.name} is currently offline.</h2>"
            f"<p>This shop needs to upgrade to Standard or Premium plan.</p>"
            f"</div>"
        )

    products = Product.objects.filter(shop=shop, is_active=True, stock_quantity__gt=0)
    if shop.subscription_plan == 'Standard':
        products = products[:20]

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

    # Plan check - POS is available for Basic and above
    if shop.subscription_plan == 'Free':
        messages.warning(request, "POS System is available on Basic Plan and above. Please upgrade!")
        return redirect('billing')

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
from .models import StorefrontOrder, StorefrontOrderItem
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

def storefront_home(request, shop_slug):
    """Public e-commerce store for customers"""
    shop = get_object_or_404(Shop, slug=shop_slug)

    if shop.subscription_plan in ['Free', 'Basic']:
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

    # ৩. একদম শেষে Standard plan এর জন্য max 20 products লিমিট (Slice) করুন
    if shop.subscription_plan == 'Standard':
        products = products[:20]

    # QuerySet কে List এ কনভার্ট করে নিচ্ছি যেন রেন্ডম ভ্যালুগুলো টেমপ্লেটে ঠিকমতো যায়
    products = list(products)

    # ---- NEW LOGIC: Fake Realistic Ratings & Sold Count ----
    for p in products:
        random.seed(p.id)  # Magic: Product ID-কে সিড হিসেবে দিলে প্রতিবার একই রেন্ডম নাম্বার আসবে!
        p.fake_rating = round(random.uniform(4.1, 5.0), 1)  # ৪.১ থেকে ৫.০ এর মধ্যে রেটিং
        p.fake_sold = random.randint(15, 450)  # ১৫ থেকে ৪৫০ এর মধ্যে সোল্ড আইটেম

    product_data = [{'id': p.id, 'name': p.name, 'price': float(p.price), 'stock': p.stock_quantity} for p in products]

    return render(request, 'store/storefront/home.html', {
        'shop': shop,
        'products': products,
        'categories': categories,
        'banners': banners,
        'product_data_json': json.dumps(product_data),
        'cat_filter': cat_filter,
        'search': search,
    })


def storefront_product_detail(request, shop_slug, product_id):
    """Customer-facing single product details page with related products"""
    shop = get_object_or_404(Shop, slug=shop_slug)

    if shop.subscription_plan in ['Free', 'Basic']:
        return redirect('storefront_home', shop_slug=shop_slug)

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

    # ---- Fake Rating for Main Product ----
    random.seed(product.id)
    product.fake_rating = round(random.uniform(4.1, 5.0), 1)
    product.fake_sold = random.randint(15, 450)

    # ম্যাজিক লজিক: একই ক্যাটাগরির অন্য প্রোডাক্টগুলো খুঁজে বের করা (বর্তমান প্রোডাক্ট বাদে)
    related_products = Product.objects.filter(
        shop=shop,
        category=product.category,
        is_active=True
    ).exclude(id=product.id).order_by('-id')[:4]  # সর্বোচ্চ ৪টা দেখাবে

    # QuerySet কে List এ কনভার্ট করে নিচ্ছি
    related_products = list(related_products)

    # ---- Fake Rating for Related Products ----
    for rp in related_products:
        random.seed(rp.id)
        rp.fake_rating = round(random.uniform(4.1, 5.0), 1)
        rp.fake_sold = random.randint(15, 450)

    return render(request, 'store/storefront/product_detail.html', {
        'shop': shop,
        'product': product,
        'related_products': related_products
    })

def storefront_checkout(request, shop_slug):
    """Customer checkout page"""
    shop = get_object_or_404(Shop, slug=shop_slug)

    # Plan check — Free/Basic shops don't have storefront checkout
    if shop.subscription_plan in ['Free', 'Basic']:
        return redirect('storefront_home', shop_slug=shop_slug)

    # ── BUG FIX: cart validation — cart data comes from JS/localStorage
    # The actual cart is sent via POST in storefront_place_order.
    # Here we just check if the request has any cart data (for direct URL access).
    # If someone hits /checkout/ directly with no POST data, redirect home.
    if request.method == 'GET':
        # Allow GET — cart is handled client-side (localStorage)
        # The place_order view will validate cart items server-side
        pass

    return render(request, 'store/storefront/checkout.html', {'shop': shop})


def storefront_place_order(request, shop_slug):
    """Place order from storefront (AJAX POST)"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request'})

    shop = get_object_or_404(Shop, slug=shop_slug)
    if shop.subscription_plan in ['Free', 'Basic']:
        return JsonResponse({'success': False, 'error': 'Shop not active'})

    try:
        data = json.loads(request.body)
        cart_items = data.get('cart', [])
        if not cart_items:
            return JsonResponse({'success': False, 'error': 'Cart is empty!'})

        name = data.get('name', '').strip()
        phone = data.get('phone', '').strip()
        address = data.get('address', '').strip()
        note = data.get('note', '')

        if not name or not phone or not address:
            return JsonResponse({'success': False, 'error': 'Name, phone and address are required!'})

        delivery_charge = float(shop.delivery_charge) if hasattr(shop, 'delivery_charge') else 80.0
        subtotal = 0

        # Validate stock first
        for item in cart_items:
            product = get_object_or_404(Product, id=item['id'], shop=shop)
            if product.stock_quantity < int(item['qty']):
                return JsonResponse({'success': False, 'error': f"'{product.name}' has only {product.stock_quantity} items left!"})
            subtotal += float(product.price) * int(item['qty'])

        total = subtotal + delivery_charge

        # Create storefront order
        sf_order = StorefrontOrder.objects.create(
            shop=shop,
            customer_name=name,
            customer_phone=phone,
            customer_address=address,
            customer_note=note,
            total_amount=total,
            delivery_charge=delivery_charge,
            status='Pending'
        )

        # Create items and deduct stock
        for item in cart_items:
            product = Product.objects.get(id=item['id'], shop=shop)
            qty = int(item['qty'])
            StorefrontOrderItem.objects.create(
                order=sf_order, product=product,
                quantity=qty, price=product.price
            )
            product.stock_quantity -= qty
            product.save()

        # Also create in main Order system (so seller sees it in dashboard)
        customer, _ = Customer.objects.get_or_create(
            shop=shop, phone=phone,
            defaults={'name': name, 'address': address}
        )
        customer.name = name
        customer.address = address
        customer.save()

        main_order = Order.objects.create(
            shop=shop, customer=customer,
            delivery_charge=delivery_charge, discount=0,
            payment_method='COD', status='Pending',
            total_amount=total
        )

        for item in sf_order.items.all():
            OrderItem.objects.create(
                order=main_order, product=item.product,
                price=item.price, quantity=item.quantity,
                cost_price=item.product.cost_price
            )

        # SMS to customer
        if shop.is_sms_active and shop.sms_balance > 0:
            sms_text = f"প্রিয় {name}, {shop.name} থেকে আপনার অর্ডার (#ORD-{main_order.id}) পাওয়া গেছে। আমরা শীঘ্রই যোগাযোগ করব।"
            _send_sms(phone, sms_text)
            shop.sms_balance -= 1
            shop.save()

        return JsonResponse({
            'success': True,
            'order_id': sf_order.id,
            'main_order_id': main_order.id,
            'message': f'Order placed successfully!'
        })

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


def storefront_order_success(request, shop_slug, order_id):
    """Order success page"""
    shop = get_object_or_404(Shop, slug=shop_slug)
    order = get_object_or_404(StorefrontOrder, id=order_id, shop=shop)
    return render(request, 'store/storefront/order_success.html', {'shop': shop, 'order': order})


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
    shop = request.user.shop
    if request.method == 'POST':
        cat_name = request.POST.get('name')
        if cat_name:
            Category.objects.create(shop=shop, name=cat_name)
            messages.success(request, f"Category '{cat_name}' added successfully!")
        return redirect('category_list')

    categories = Category.objects.filter(shop=shop).order_by('-id')
    return render(request, 'store/categories.html', {'categories': categories})


@login_required(login_url='/accounts/login/')
def delete_category(request, pk):
    shop = request.user.shop
    category = get_object_or_404(Category, pk=pk, shop=shop)
    category.delete()
    messages.success(request, "Category deleted successfully!")
    return redirect('category_list')

@login_required(login_url='/accounts/login/')
def edit_category(request, pk):
    shop = request.user.shop
    category = get_object_or_404(Category, pk=pk, shop=shop)

    if request.method == 'POST':
        new_name = request.POST.get('name')
        if new_name:
            category.name = new_name
            category.save()
            messages.success(request, f"Category updated to '{new_name}'!")
            return redirect('category_list')

    return render(request, 'store/edit_category.html', {'category': category})



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
from .forms import BannerForm

# ============================================================
# BANNER MANAGEMENT
# ============================================================
@login_required(login_url='/accounts/login/')
def banner_list(request):
    shop = request.user.shop
    banners = Banner.objects.filter(shop=shop).order_by('-id')
    return render(request, 'store/banners.html', {'banners': banners})

@login_required(login_url='/accounts/login/')
def add_banner(request):
    shop = request.user.shop
    if request.method == 'POST':
        form = BannerForm(request.POST, request.FILES)
        if form.is_valid():
            banner = form.save(commit=False)
            banner.shop = shop
            banner.save()
            messages.success(request, "Banner uploaded successfully!")
            return redirect('banner_list')
    else:
        form = BannerForm()
    return render(request, 'store/add_banner.html', {'form': form})

@login_required(login_url='/accounts/login/')
def delete_banner(request, pk):
    shop = request.user.shop
    banner = get_object_or_404(Banner, pk=pk, shop=shop)
    banner.delete()
    messages.success(request, "Banner deleted successfully!")
    return redirect('banner_list')

# ============================================================
# SSLCOMMERZ PAYMENT GATEWAY
# ============================================================
import uuid

@login_required(login_url='/accounts/login/')
def initiate_payment(request, plan_name):
    """Initiate SSLCommerz payment for plan upgrade"""
    shop = request.user.shop

    PLAN_PRICES = {
        'Basic': 499,
        'Standard': 999,
        'Premium': 1999,
    }

    amount = PLAN_PRICES.get(plan_name)
    if not amount:
        messages.error(request, "Invalid plan!")
        return redirect('billing')

    try:
        setting = MasterSetting.objects.get(id=1)
        store_id = setting.payment_store_id
        store_passwd = setting.payment_secret_key
        is_live = setting.is_payment_live
    except MasterSetting.DoesNotExist:
        messages.error(request, "Payment gateway not configured!")
        return redirect('billing')

    if not store_id or not store_passwd:
        messages.error(request, "Payment gateway not configured! Contact admin.")
        return redirect('billing')

    tran_id = f"SS-{shop.id}-{plan_name[:3].upper()}-{uuid.uuid4().hex[:8].upper()}"
    base_url = request.build_absolute_uri('/').rstrip('/')

    post_data = {
        'store_id': store_id,
        'store_passwd': store_passwd,
        'total_amount': amount,
        'currency': 'BDT',
        'tran_id': tran_id,
        'success_url': f'{base_url}/payment/success/{plan_name}/{tran_id}/',
        'fail_url': f'{base_url}/payment/fail/',
        'cancel_url': f'{base_url}/billing/',
        'ipn_url': f'{base_url}/payment/ipn/',
        'cus_name': shop.name,
        'cus_email': f'{shop.slug}@sohojsell.com',
        'cus_add1': shop.address or 'Bangladesh',
        'cus_city': 'Dhaka',
        'cus_country': 'Bangladesh',
        'cus_phone': shop.phone or '01700000000',
        'product_name': f'SohojSell {plan_name} Plan',
        'product_category': 'SaaS Subscription',
        'product_profile': 'non-physical-goods',
        'shipping_method': 'NO',
        'num_of_item': 1,
        'emi_option': 0,
    }

    ssl_url = 'https://securepay.sslcommerz.com/gwprocess/v4/api.php' if is_live else 'https://sandbox.sslcommerz.com/gwprocess/v4/api.php'

    try:
        response = requests.post(ssl_url, data=post_data, timeout=30)
        result = response.json()

        if result.get('status') == 'SUCCESS':
            return redirect(result.get('GatewayPageURL'))
        else:
            messages.error(request, f"Payment gateway error: {result.get('failedreason', 'Unknown error')}")
            return redirect('billing')
    except Exception as e:
        messages.error(request, f"Payment failed: {str(e)}")
        return redirect('billing')


@csrf_exempt
def payment_success_ssl(request, plan_name, tran_id):
    """SSLCommerz success callback"""
    val_id = request.POST.get('val_id') or request.GET.get('val_id')

    if not val_id:
        messages.error(request, "Payment validation failed!")
        return redirect('billing')

    # Validate transaction
    try:
        setting = MasterSetting.objects.get(id=1)
        store_id = setting.payment_store_id
        store_passwd = setting.payment_secret_key
        is_live = setting.is_payment_live
    except MasterSetting.DoesNotExist:
        messages.error(request, "Configuration error!")
        return redirect('billing')

    validate_url = (
        f'https://securepay.sslcommerz.com/validator/api/validationserverAPI.php'
        if is_live else
        f'https://sandbox.sslcommerz.com/validator/api/validationserverAPI.php'
    )

    try:
        resp = requests.get(validate_url, params={
            'val_id': val_id,
            'store_id': store_id,
            'store_passwd': store_passwd,
            'format': 'json',
        }, timeout=30)
        result = resp.json()

        if result.get('status') == 'VALID' or result.get('status') == 'VALIDATED':
            # Find shop by tran_id pattern SS-{shop_id}-...
            parts = tran_id.split('-')
            shop_id = parts[1] if len(parts) > 1 else None
            if shop_id:
                shop = Shop.objects.get(id=shop_id)
                shop.subscription_plan = plan_name
                shop.is_paid = True
                SMS_BONUS = {'Basic': 120, 'Standard': 250, 'Premium': 600}
                shop.sms_balance += SMS_BONUS.get(plan_name, 0)
                shop.save()
                messages.success(request, f"🎉 Payment successful! Upgraded to {plan_name} Plan!")
                return redirect('dashboard')
        else:
            messages.error(request, "Payment validation failed! Contact support.")
            return redirect('billing')
    except Exception as e:
        messages.error(request, f"Validation error: {str(e)}")
        return redirect('billing')


@csrf_exempt
def payment_fail(request):
    messages.error(request, "❌ Payment failed! Please try again.")
    return redirect('billing')


@csrf_exempt
def payment_ipn(request):
    """IPN handler for SSLCommerz"""
    return JsonResponse({'status': 'ok'})


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
    shop = request.user.shop
    pending_request = shop.payment_requests.filter(status='Pending').first()
    payment_history = shop.payment_requests.all().order_by('-created_at')[:10]
    return render(request, 'store/billing.html', {
        'shop': shop,
        'pending_request': pending_request,
        'payment_history': payment_history,
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

        # Plan Limits Check
        product_count = Product.objects.filter(shop=shop).count()
        plan = shop.subscription_plan
        LIMITS = {'Free': 20, 'Basic': 100, 'Standard': 200}
        limit = LIMITS.get(plan)

        created_count = 0
        skipped_count = 0

        for row in reader:
            if limit and (product_count + created_count) >= limit:
                messages.warning(request,
                                 f'Plan limit reached! Only {created_count} products imported. Please upgrade your plan.')
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