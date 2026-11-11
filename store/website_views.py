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
from .models import Banner, Category, DeliveryZone, Product, Shop, ShopPayout, StorefrontPayment
from .plans import has_custom_domain
from .themes import DESIGNS, THEMES
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
    ('domain', 'bi-globe2', 'নিজের ডোমেইন'),
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
        if section == 'domain':
            # নিজের ডোমেইন: সেভ, যাচাই, বা সরানো (store/domains.py)
            from . import domains
            action = request.POST.get('action')
            if not has_custom_domain(shop):
                messages.error(request, 'নিজের ডোমেইন Premium প্যাকেজে পাবেন।')
            elif action == 'remove':
                Shop.objects.filter(pk=shop.pk).update(custom_domain=None, custom_domain_status=Shop.DOMAIN_PENDING,
                                                       custom_domain_note='')
                messages.success(request, 'নিজের ডোমেইন সরানো হয়েছে; দোকান আগের মতো সাবডোমেইনে চলবে।')
            elif action == 'verify':
                ok, text = domains.verify(shop)
                (messages.success if ok else messages.warning)(request, text)
            else:
                old_domain = shop.custom_domain
                form = StoreProfileForm({'name': shop.name, 'phone': shop.phone, 'address': shop.address,
                                         'subdomain': shop.slug, 'custom_domain': request.POST.get('custom_domain', '')},
                                        instance=shop)
                if form.is_valid():            # (is_valid ইনস্ট্যান্সে নতুন মান বসিয়ে দেয়, তাই আগেরটা আগে রাখা)
                    new_domain = form.cleaned_data.get('custom_domain')
                    if new_domain != old_domain:
                        Shop.objects.filter(pk=shop.pk).update(custom_domain=new_domain, custom_domain_note='',
                                                               custom_domain_status=Shop.DOMAIN_PENDING,
                                                               custom_domain_checked_at=None)
                    messages.success(request, 'ডোমেইন সেভ হয়েছে। এবার DNS দিয়ে নিচের "যাচাই করুন" চাপুন।'
                                     if new_domain else 'ডোমেইন সরানো হয়েছে।')
                else:
                    messages.error(request, form.errors.get('custom_domain', ['ডোমেইন ঠিকমতো লিখুন।'])[0])
            return _back('domain')
        if section in form_map:
            key, form_class, ok_message = form_map[section]
            form = form_class(request.POST, request.FILES, instance=shop)
            if form.is_valid():
                form.save()
                if section == 'design' and 'storefront_language' in form.changed_data:
                    delivery.match_default_zone_names(shop)
                    ok_message = ('ওয়েবসাইট এখন ইংরেজিতে — কাস্টমার সব লেখা ইংরেজিতে দেখবে, অর্ডারের SMS-ও ইংরেজিতে যাবে। '
                                  'প্রোডাক্টের নাম, বিবরণ, ব্যানারের লেখা নিজে ইংরেজিতে লিখে নিন।'
                                  if shop.storefront_language == 'en' else 'ওয়েবসাইট এখন বাংলায়।')
                if section == 'payment':
                    ok_message = ('অনলাইন পেমেন্ট চালু — কাস্টমার এখন অনলাইনে টাকা দিতে পারবে।'
                                  if shop.payment_rule != shop.PAYMENT_COD
                                  else 'অনলাইন পেমেন্ট বন্ধ — কাস্টমার শুধু ক্যাশ অন ডেলিভারিতে অর্ডার দেবে।')
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
        'design_options': list(DESIGNS.items()),
        'custom_domain_allowed': has_custom_domain(shop),
        'cname_target': __import__('store.domains', fromlist=['cname_target']).cname_target(),
        'domain_auto': __import__('store.domains', fromlist=['cloudflare_ready']).cloudflare_ready(),
        'banners': Banner.objects.filter(shop=shop).order_by('-id'),
        'max_banners': MAX_BANNERS,
        'categories': Category.objects.filter(shop=shop).annotate(product_count=Count('product')).order_by('name'),
        'zones': DeliveryZone.objects.filter(shop=shop),
        'online_gateway_ready': shop_payments.online_available(shop),
        'fee_percent': shop_payments.fee_percent(),
        'balance': shop_payments.balance_summary(shop),
        'recent_payments': StorefrontPayment.objects.filter(shop=shop).select_related('order')[:10],
        'payouts': ShopPayout.objects.filter(shop=shop).select_related('request')[:10],
        'settlement_requests': shop.settlement_requests.select_related('payout')[:10],
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


# ---------------------------------------------------------------- সেলারের টাকা তোলা
@login_required(login_url='/accounts/login/')
@require_POST
def settlement_request(request):
    shop = request.user.shop
    try:
        req = shop_payments.request_settlement(shop, request.POST.get('amount') or '0', user=request.user)
    except shop_payments.SettlementError as exc:
        messages.error(request, str(exc))
        return redirect(reverse('website_settings') + '?tab=payment#settlement')
    from . import sms
    from django.conf import settings as dj_settings
    admin_phone = sms.normalize(getattr(dj_settings, 'ADMIN_ALERT_PHONE', ''))
    if admin_phone:
        sms.notify(admin_phone, f'{dj_settings.SITE_NAME}: টাকা তোলার অনুরোধ — {shop.name}, '
                                f'৳{sms.bn_num(f"{req.amount:,.0f}")} ({req.method})')
    messages.success(request, f'৳{req.amount:,.0f} তোলার অনুরোধ জমা হয়েছে। {req.method} {req.account}-এ পাঠানো হলে '
                              'SMS পাবেন আর এখানে লেনদেন নম্বর দেখাবে।')
    return redirect(reverse('website_settings') + '?tab=payment#settlement')


@login_required(login_url='/accounts/login/')
@require_POST
def settlement_cancel(request, pk):
    if shop_payments.cancel_settlement(request.user.shop, pk):
        messages.info(request, 'টাকা তোলার অনুরোধ বাতিল করা হয়েছে।')
    return redirect(reverse('website_settings') + '?tab=payment#settlement')


# ---------------------------------------------------------------- মাস্টার: সেলারদের টাকা পাঠানো
@login_required(login_url='/accounts/login/')
def master_settlements(request):
    """কাস্টমারের অনলাইন পেমেন্ট থেকে কোন দোকানের কত পাওনা, আর পাঠানোর রেকর্ড রাখা।"""
    if not request.user.is_superuser:
        return redirect('dashboard')
    from decimal import Decimal, InvalidOperation
    from django.db import transaction
    from .models import Shop

    action = request.POST.get('action', '') if request.method == 'POST' else ''
    if action in ('request_paid', 'request_reject'):
        try:
            if action == 'request_paid':
                req = shop_payments.pay_settlement(request.POST.get('request_id'), request.POST.get('reference'),
                                                   user=request.user)
                messages.success(request, f'{req.shop.name}-কে ৳{req.amount:.0f} পাঠানো লেখা হয়েছে, সেলারকে SMS গেছে।')
            elif shop_payments.reject_settlement(request.POST.get('request_id'), request.POST.get('reason')):
                messages.success(request, 'অনুরোধ ফেরত দেওয়া হয়েছে।')
        except shop_payments.SettlementError as exc:
            messages.error(request, str(exc))
        return redirect('master_settlements')

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
    from .models import SettlementRequest
    open_requests = list(SettlementRequest.objects.filter(status=SettlementRequest.PENDING).select_related('shop')
                         .order_by('created_at'))
    return render(request, 'store/master_settlements.html', {
        'open_requests': open_requests,
        'rows': rows,
        'total_due': sum((r['due'] for r in rows), Decimal('0')),
        'recent_payouts': ShopPayout.objects.select_related('shop')[:20],
    })
