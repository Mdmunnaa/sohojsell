# store/website_views.py
"""
"ওয়েবসাইট" পেইজ: দোকানের ওয়েবসাইটের সব সেটিং এক জায়গায়, ট্যাবে ভাগ করা (Edumi-র মতো)।
প্রতিটা ট্যাব নিজের ফর্ম পাঠায় (section=...), সেভের পর একই ট্যাবে ফিরে আসে।
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import delivery, shop_payments
from .models import Banner, Category, DeliveryZone, Product, ShopPayout, StorefrontPayment
from .plans import has_custom_domain
from .themes import THEMES
from .website_forms import (BannerUploadForm, CategoryForm, DeliverySettingsForm, DeliveryZoneForm,
                            PaymentSettingsForm, StoreContactForm, StoreDesignForm, StoreProfileForm)

TABS = [
    ('store', 'bi-shop', 'দোকানের তথ্য'),
    ('design', 'bi-palette-fill', 'ডিজাইন'),
    ('banners', 'bi-images', 'ব্যানার'),
    ('categories', 'bi-tags-fill', 'ক্যাটাগরি'),
    ('delivery', 'bi-truck', 'ডেলিভারি'),
    ('payment', 'bi-credit-card-2-front-fill', 'পেমেন্ট'),
    ('contact', 'bi-chat-square-text-fill', 'যোগাযোগ ও পলিসি'),
]
TAB_KEYS = {key for key, _icon, _label in TABS}
MAX_BANNERS = 8
MAX_ZONES = 15


def _back(tab):
    return redirect(f"{reverse('website_settings')}?tab={tab}")


@login_required(login_url='/accounts/login/')
def website_settings(request):
    shop = request.user.shop
    tab = request.GET.get('tab') if request.GET.get('tab') in TAB_KEYS else 'store'
    forms = {
        'profile_form': StoreProfileForm(instance=shop),
        'design_form': StoreDesignForm(instance=shop),
        'contact_form': StoreContactForm(instance=shop),
        'delivery_form': DeliverySettingsForm(instance=shop),
        'payment_form': PaymentSettingsForm(instance=shop),
        'banner_form': BannerUploadForm(),
        'category_form': CategoryForm(),
        'zone_form': DeliveryZoneForm(),
    }

    if request.method == 'POST':
        section = request.POST.get('section', '')
        form_map = {
            'store': ('profile_form', StoreProfileForm, 'দোকানের তথ্য সেভ হয়েছে।'),
            'design': ('design_form', StoreDesignForm, 'ডিজাইন সেভ হয়েছে। ওয়েবসাইট খুলে দেখুন।'),
            'contact': ('contact_form', StoreContactForm, 'যোগাযোগ আর পলিসি সেভ হয়েছে।'),
            'delivery': ('delivery_form', DeliverySettingsForm, 'ফ্রি ডেলিভারির নিয়ম সেভ হয়েছে।'),
            'payment': ('payment_form', PaymentSettingsForm, 'পেমেন্টের নিয়ম সেভ হয়েছে।'),
        }
        if section in form_map:
            key, form_class, ok_message = form_map[section]
            form = form_class(request.POST, request.FILES, instance=shop)
            if form.is_valid():
                form.save()
                messages.success(request, ok_message)
                return _back(section)
            forms[key] = form
            tab = section
            messages.error(request, 'কিছু ঘরে ভুল আছে, লাল লেখা দেখে ঠিক করুন।')
        elif section == 'banner_add':
            tab = 'banners'
            form = BannerUploadForm(request.POST, request.FILES)
            if Banner.objects.filter(shop=shop).count() >= MAX_BANNERS:
                messages.error(request, f'সর্বোচ্চ {MAX_BANNERS}টা ব্যানার রাখা যায়। পুরনো একটা মুছে নতুনটা দিন।')
                return _back(tab)
            if form.is_valid():
                banner = form.save(commit=False)
                banner.shop = shop
                banner.save()
                messages.success(request, 'ব্যানার যোগ হয়েছে।')
                return _back(tab)
            forms['banner_form'] = form
        elif section == 'category_add':
            tab = 'categories'
            form = CategoryForm(request.POST)
            if form.is_valid():
                name = form.cleaned_data['name']
                if Category.objects.filter(shop=shop, name__iexact=name).exists():
                    messages.warning(request, f'"{name}" ক্যাটাগরি আগেই আছে।')
                else:
                    Category.objects.create(shop=shop, name=name)
                    messages.success(request, f'"{name}" ক্যাটাগরি যোগ হয়েছে।')
                return _back(tab)
            forms['category_form'] = form
        elif section == 'zone_add':
            tab = 'delivery'
            form = DeliveryZoneForm(request.POST)
            if DeliveryZone.objects.filter(shop=shop).count() >= MAX_ZONES:
                messages.error(request, f'সর্বোচ্চ {MAX_ZONES}টা এলাকা রাখা যায়।')
                return _back(tab)
            if form.is_valid():
                zone = form.save(commit=False)
                zone.shop = shop
                zone.sort_order = DeliveryZone.objects.filter(shop=shop).count()
                zone.save()
                messages.success(request, f'"{zone.name}" এলাকা যোগ হয়েছে।')
                return _back(tab)
            forms['zone_form'] = form
        else:
            return _back(tab)

    delivery.zones_for(shop)   # নতুন দোকানে সাধারণ দুটো এলাকা বানিয়ে রাখে
    if tab == 'payment':
        shop_payments.recheck_pending(shop)
    context = {
        **forms,
        'shop': shop,
        'tabs': TABS,
        'active_tab': tab,
        'theme_options': list(THEMES.items()),
        'custom_domain_allowed': has_custom_domain(shop),
        'banners': Banner.objects.filter(shop=shop).order_by('-id'),
        'max_banners': MAX_BANNERS,
        'categories': Category.objects.filter(shop=shop).annotate(product_count=Count('product')).order_by('name'),
        'zones': DeliveryZone.objects.filter(shop=shop),
        'online_gateway_ready': shop_payments.online_available(shop),
        'fee_percent': shop_payments.fee_percent(),
        'balance': shop_payments.balance_summary(shop),
        'recent_payments': StorefrontPayment.objects.filter(shop=shop).select_related('order')[:10],
        'payouts': ShopPayout.objects.filter(shop=shop)[:10],
        'product_count': Product.objects.filter(shop=shop).count(),
    }
    return render(request, 'store/website_settings.html', context)


@login_required(login_url='/accounts/login/')
@require_POST
def banner_delete(request, pk):
    banner = get_object_or_404(Banner, pk=pk, shop=request.user.shop)
    banner.image.delete(save=False)
    banner.delete()
    messages.success(request, 'ব্যানার মুছে ফেলা হয়েছে।')
    return _back('banners')


@login_required(login_url='/accounts/login/')
@require_POST
def banner_toggle(request, pk):
    banner = get_object_or_404(Banner, pk=pk, shop=request.user.shop)
    banner.is_active = not banner.is_active
    banner.save(update_fields=['is_active'])
    messages.success(request, 'ব্যানার চালু হয়েছে।' if banner.is_active else 'ব্যানার লুকানো হয়েছে।')
    return _back('banners')


@login_required(login_url='/accounts/login/')
@require_POST
def category_rename(request, pk):
    category = get_object_or_404(Category, pk=pk, shop=request.user.shop)
    form = CategoryForm(request.POST, instance=category)
    if form.is_valid():
        form.save()
        messages.success(request, f'ক্যাটাগরির নাম "{category.name}" করা হয়েছে।')
    else:
        messages.error(request, 'ক্যাটাগরির নাম দিন।')
    return _back('categories')


@login_required(login_url='/accounts/login/')
@require_POST
def category_remove(request, pk):
    category = get_object_or_404(Category, pk=pk, shop=request.user.shop)
    name = category.name
    category.delete()   # প্রোডাক্ট মোছে না, শুধু ক্যাটাগরি খালি হয়
    messages.success(request, f'"{name}" ক্যাটাগরি মুছে ফেলা হয়েছে। প্রোডাক্টগুলো আছে, শুধু ক্যাটাগরি ছাড়া।')
    return _back('categories')


@login_required(login_url='/accounts/login/')
@require_POST
def zone_update(request, pk):
    zone = get_object_or_404(DeliveryZone, pk=pk, shop=request.user.shop)
    form = DeliveryZoneForm(request.POST, instance=zone)
    if form.is_valid():
        form.save()
        messages.success(request, f'"{zone.name}" সেভ হয়েছে।')
    else:
        messages.error(request, 'এলাকার নাম আর চার্জ ঠিকমতো দিন।')
    return _back('delivery')


@login_required(login_url='/accounts/login/')
@require_POST
def zone_delete(request, pk):
    zone = get_object_or_404(DeliveryZone, pk=pk, shop=request.user.shop)
    if DeliveryZone.objects.filter(shop=request.user.shop).count() <= 1:
        messages.error(request, 'কমপক্ষে একটা এলাকা রাখতে হবে। চাইলে চার্জ বদলে দিন।')
        return _back('delivery')
    zone.delete()
    messages.success(request, 'এলাকা মুছে ফেলা হয়েছে।')
    return _back('delivery')


# ---------------------------------------------------------------- মাস্টার: সেলারদের টাকা পাঠানো
@login_required(login_url='/accounts/login/')
def master_settlements(request):
    """কাস্টমারের অনলাইন পেমেন্ট থেকে কোন দোকানের কত পাওনা, আর পাঠানোর রেকর্ড রাখা।"""
    if not request.user.is_superuser:
        return redirect('dashboard')
    from decimal import Decimal, InvalidOperation
    from django.db import transaction
    from .models import Shop

    if request.method == 'POST':
        shop = get_object_or_404(Shop, pk=request.POST.get('shop_id'))
        try:
            amount = Decimal(request.POST.get('amount') or '0')
        except InvalidOperation:
            amount = Decimal('0')
        with transaction.atomic():
            Shop.objects.select_for_update().filter(pk=shop.pk).first()   # একসাথে দুবার পাঠানো আটকাতে
            due = shop_payments.balance_summary(shop)['due']
            if amount <= 0 or amount > due:
                messages.error(request, f'{shop.name}: টাকার পরিমাণ ০-এর বেশি আর পাওনার (৳{due:.0f}) সমান বা কম হতে হবে।')
            else:
                ShopPayout.objects.create(
                    shop=shop, amount=amount, method=shop.payout_method, account=shop.payout_account,
                    reference=(request.POST.get('reference') or '').strip()[:100],
                    note=(request.POST.get('note') or '').strip()[:200], created_by=request.user)
                messages.success(request, f'{shop.name}-কে ৳{amount:.0f} পাঠানো লেখা হয়েছে।')
        return redirect('master_settlements')

    shop_ids = StorefrontPayment.objects.filter(status=StorefrontPayment.STATUS_COMPLETED) \
        .values_list('shop_id', flat=True).distinct()
    rows = []
    for shop in Shop.objects.filter(pk__in=list(shop_ids)).order_by('name'):
        summary = shop_payments.balance_summary(shop)
        rows.append({'shop': shop, **summary})
    rows.sort(key=lambda r: r['due'], reverse=True)
    return render(request, 'store/master_settlements.html', {
        'rows': rows,
        'total_due': sum((r['due'] for r in rows), Decimal('0')),
        'recent_payouts': ShopPayout.objects.select_related('shop')[:20],
    })
