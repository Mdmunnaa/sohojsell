"""
Master HQ — পুরো SellPunch প্ল্যাটফর্মের নিয়ন্ত্রণ (শুধু সুপারইউজার)। হিসাব আর নিয়ম store/hq.py-তে।

পুরনো URL-এর নাম (master_dashboard, manage_shops, all_users, master_billing, master_settings) একই আছে,
তাই লগইনের পরের redirect আর পুরনো লিংক কাজ করে।
"""
import datetime
import secrets
import threading
from decimal import Decimal, InvalidOperation

from django.conf import settings as django_settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db import connection, transaction
from django.db.models import Count, OuterRef, Q, Subquery, Sum
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from . import hq
from .hq import superuser_required
from .models import (HQAuditLog, MasterSetting, OnlinePayment, Order, PaymentRequest, PlatformNotice, Product,
                     Shop, SmsLog, StaffProfile)
from .plans import TRIAL_PLAN, storefront_closes_on, subscription_end

User = get_user_model()

PER_PAGE = 25
PLAN_CHOICES = (('Free', 'ফ্রি ট্রায়াল'), ('Basic', 'Basic'), ('Standard', 'Standard'), ('Premium', 'Premium'))
STATUS_FILTERS = (('', 'সব'), ('paid', 'পেইড'), ('trial', 'ফ্রি ট্রায়াল'), ('trial_ending', 'ট্রায়াল শেষ হচ্ছে'),
                  ('expiring', 'মেয়াদ শেষ হচ্ছে'), ('locked', 'মেয়াদ শেষ'), ('suspended', 'বন্ধ করা'), ('demo', 'ডেমো'))


def _page(request, queryset, per_page=PER_PAGE):
    paginator = Paginator(queryset, per_page)
    try:
        return paginator.page(request.GET.get('page', 1))
    except (EmptyPage, PageNotAnInteger):
        return paginator.page(1)


def _query_without_page(request):
    params = request.GET.copy()
    params.pop('page', None)
    return params.urlencode()


def _back(request, fallback):
    target = request.POST.get('next') or request.META.get('HTTP_REFERER') or ''
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()},
                                                  require_https=request.is_secure()):
        return redirect(target)
    return redirect(fallback)


def _int(value, default=0):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _decimal(value):
    try:
        return Decimal(str(value).strip().replace(',', '')) if str(value or '').strip() else Decimal('0')
    except InvalidOperation:
        return None


# ============================================================
# ড্যাশবোর্ড
# ============================================================
@superuser_required
def dashboard(request):
    from . import domains, health
    system_warnings = health.warnings()
    db_latency = health.database_latency_ms()
    if db_latency is not None and db_latency > 25:
        system_warnings.append(f'ডাটাবেস প্রতি প্রশ্নে {db_latency:.0f} ms নিচ্ছে (৫ ms-এর নিচে থাকা উচিত) — একটা পাতায় '
                               '২০–৩০টা প্রশ্ন হয়, তাই পাতা খুলতে সেকেন্ড লেগে যায়। ডাটাবেস আর সার্ভার একই অঞ্চলে '
                               '(সিঙ্গাপুর) আছে কিনা দেখুন।')
    s = hq.stats()
    recent = list(Shop.objects.filter(is_demo=False).select_related('user').order_by('-created_at')[:8])
    for shop in recent:
        shop.hq_status = hq.shop_status(shop)
    return render(request, 'store/hq/dashboard.html', {
        'active': 'dashboard', 's': s, 'a': hq.attention(),
        'system_warnings': system_warnings, 'db_latency': db_latency, 'db_region': health.database_region(),
        'pending_domains': list(domains.pending_for_master()),
        'recent': recent,
        'payments': OnlinePayment.objects.filter(status=OnlinePayment.STATUS_COMPLETED, shop__is_demo=False)
                    .select_related('shop').order_by('-completed_at')[:8],
        'log': HQAuditLog.objects.all()[:8],
        # পুরনো নাম (টেস্ট আর অন্য জায়গা এগুলো দেখে)
        'total_shops': s['total'],
        'total_platform_orders': Order.objects.filter(shop__is_demo=False).count(),
    })


# ============================================================
# দোকানের তালিকা
# ============================================================
def _with_counts(shops):
    orders = Order.objects.filter(shop=OuterRef('pk')).order_by().values('shop').annotate(c=Count('pk')).values('c')
    products = Product.objects.filter(shop=OuterRef('pk')).order_by().values('shop').annotate(c=Count('pk')).values('c')
    return shops.annotate(n_orders=Coalesce(Subquery(orders), 0), n_products=Coalesce(Subquery(products), 0))


def _search_shops(q):
    q = (q or '').strip()
    if not q:
        return Shop.objects.all()
    digits = ''.join(ch for ch in q if ch.isdigit())
    cond = (Q(name__icontains=q) | Q(slug__icontains=q.lower()) | Q(custom_domain__icontains=q.lower())
            | Q(user__name__icontains=q))
    if len(digits) >= 4:
        cond |= Q(phone__contains=digits[-10:]) | Q(user__phone_number__contains=digits[-10:])
    if q.isdigit():
        cond |= Q(pk=int(q))
    return Shop.objects.filter(cond)


@superuser_required
def shops(request):
    status = request.GET.get('status', '')
    plan = request.GET.get('plan', '')
    sort = request.GET.get('sort', 'new')
    q = request.GET.get('q', '').strip()
    base = _search_shops(q)
    keys = [k for k, _ in STATUS_FILTERS if k]
    counts = base.aggregate(all=Count('pk', filter=Q(is_demo=False)),
                            **{k: Count('pk', filter=hq.status_q(k)) for k in keys})
    shops_qs = base.filter(hq.status_q(status)) if status in keys else base.filter(is_demo=False)
    if plan in dict(PLAN_CHOICES):
        shops_qs = shops_qs.filter(subscription_plan=plan)
    order = {'new': '-created_at', 'old': 'created_at', 'name': 'name', 'expiry': 'valid_until',
             'trial': 'trial_ends_at', 'sms': '-sms_balance'}.get(sort, '-created_at')
    page = _page(request, _with_counts(shops_qs.select_related('user')).order_by(order, '-pk'))
    for shop in page.object_list:
        shop.hq_status = hq.shop_status(shop)
        shop.ends_on = subscription_end(shop)
    filters = [{'key': k, 'label': label, 'n': counts['all' if not k else k]} for k, label in STATUS_FILTERS]
    return render(request, 'store/hq/shops.html', {
        'active': 'shops', 'page_obj': page, 'filters': filters, 'status': status, 'plan': plan, 'sort': sort,
        'q': q, 'plan_choices': PLAN_CHOICES, 'query': _query_without_page(request),
    })


# ============================================================
# একটা দোকান — সব তথ্য আর সব কাজ এক পাতায়
# ============================================================
@superuser_required
def shop_detail(request, shop_id):
    shop = get_object_or_404(Shop.objects.select_related('user'), pk=shop_id)
    day = hq.today()
    month = hq.month_start(day)
    orders = Order.objects.filter(shop=shop)
    numbers = orders.aggregate(
        total=Count('pk'), month=Count('pk', filter=Q(created_at__gte=month)),
        sales=Sum('total_amount', filter=Q(created_at__gte=month) & ~Q(status__in=['Cancelled', 'Returned'])),
        all_sales=Sum('total_amount', filter=~Q(status__in=['Cancelled', 'Returned'])))
    staff = StaffProfile.objects.filter(shop=shop).select_related('user')
    end = subscription_end(shop)
    paid_total = OnlinePayment.objects.filter(shop=shop, status=OnlinePayment.STATUS_COMPLETED).aggregate(
        v=Sum('amount'))['v'] or Decimal('0')
    return render(request, 'store/hq/shop_detail.html', {
        'active': 'shops', 'shop': shop, 'owner': shop.user, 'status': hq.shop_status(shop, day),
        'end': end, 'days_left': (end - day).days if end else None,
        'days_over': (day - end).days if end and end < day else 0,
        'closes_on': storefront_closes_on(shop),
        'numbers': numbers, 'paid_total': paid_total,
        'n_products': Product.objects.filter(shop=shop).count(),
        'n_customers': shop.customers.count(),
        'staff': staff,
        'payments': OnlinePayment.objects.filter(shop=shop).order_by('-created_at')[:12],
        'legacy_payments': PaymentRequest.objects.filter(shop=shop).order_by('-created_at')[:5],
        'sms_logs': SmsLog.objects.filter(shop=shop).order_by('-created_at')[:8],
        'log': HQAuditLog.objects.filter(shop=shop)[:10],
        'plan_choices': PLAN_CHOICES[1:], 'all_plans': PLAN_CHOICES,
        'today': day,
    })


def _end_of_day(day):
    return timezone.make_aware(datetime.datetime.combine(day, datetime.time(23, 59)))


@superuser_required
@require_POST
def shop_action(request, shop_id):
    shop = get_object_or_404(Shop.objects.select_related('user'), pk=shop_id)
    action = request.POST.get('action', '')
    day = hq.today()
    here = reverse('hq_shop', args=[shop.pk])
    if shop.is_demo and action in ('suspend', 'delete', 'password'):
        messages.error(request, 'ডেমো দোকানে এটা করা যায় না।')
        return redirect(here)

    if action == 'extend':
        plan = request.POST.get('plan', '')
        period = request.POST.get('period', 'month')
        days = {'month': 30, 'year': 365}.get(period) or _int(request.POST.get('days'))
        amount = _decimal(request.POST.get('amount'))
        reference = (request.POST.get('reference') or '').strip()[:64]
        if plan not in dict(PLAN_CHOICES[1:]) or not 1 <= days <= 1100 or amount is None or amount < 0:
            messages.error(request, 'প্যাকেজ, দিন (১–১১০০) আর টাকার পরিমাণ ঠিক করে দিন।')
            return redirect(here)
        with transaction.atomic():
            shop = Shop.objects.select_for_update().get(pk=shop.pk)
            start = shop.valid_until if (shop.subscription_plan != TRIAL_PLAN and shop.valid_until
                                         and shop.valid_until >= day) else day
            shop.valid_until = start + datetime.timedelta(days=days)
            shop.subscription_plan = plan
            shop.is_locked = False
            shop.is_paid = True
            shop.save(update_fields=['valid_until', 'subscription_plan', 'is_locked', 'is_paid'])
            if amount > 0:
                OnlinePayment.objects.create(
                    shop=shop, kind=OnlinePayment.KIND_PLAN, plan_name=plan, days=days, amount=amount,
                    invoice_number=f'HQ-{shop.pk}-{secrets.token_hex(6).upper()}', environment='manual',
                    trx_id=reference, payment_method='হাতে (Master HQ)', status=OnlinePayment.STATUS_COMPLETED,
                    completed_at=timezone.now())
        detail = f'{plan}, {days} দিন — নতুন মেয়াদ {shop.valid_until:%d-%m-%Y}' + (f', ৳{amount:.0f} নেওয়া' if amount else '')
        hq.log_action(request, 'extend', shop, detail)
        messages.success(request, f'{shop.name}: {detail}।')

    elif action == 'trial':
        days = _int(request.POST.get('days'))
        if shop.subscription_plan != TRIAL_PLAN:
            messages.error(request, 'এই দোকান ট্রায়ালে নেই — মেয়াদ বাড়াতে "মেয়াদ বাড়ান" ব্যবহার করুন।')
        elif not 1 <= days <= 90:
            messages.error(request, 'ট্রায়াল ১ থেকে ৯০ দিন বাড়ানো যায়।')
        else:
            base = max(shop.trial_ends_at, timezone.now()) if shop.trial_ends_at else timezone.now()
            shop.trial_ends_at = _end_of_day(timezone.localtime(base).date() + datetime.timedelta(days=days))
            shop.is_locked = False
            shop.save(update_fields=['trial_ends_at', 'is_locked'])
            hq.log_action(request, 'trial', shop, f'{days} দিন — শেষ {timezone.localtime(shop.trial_ends_at):%d-%m-%Y}')
            messages.success(request, f'{shop.name}-এর ট্রায়াল {days} দিন বাড়ানো হয়েছে।')

    elif action == 'set_plan':
        plan = request.POST.get('plan', '')
        if plan not in dict(PLAN_CHOICES[1:]):
            messages.error(request, 'প্যাকেজ বাছুন।')
        elif plan != shop.subscription_plan:
            old = shop.subscription_plan
            if old == TRIAL_PLAN and not shop.valid_until:
                shop.valid_until = subscription_end(shop) or day
            shop.subscription_plan = plan
            shop.save(update_fields=['subscription_plan', 'valid_until'])
            hq.log_action(request, 'set_plan', shop, f'{old} থেকে {plan} (মেয়াদ একই)')
            messages.success(request, f'{shop.name} এখন {plan} প্যাকেজে।')

    elif action == 'set_date':
        try:
            new_day = datetime.date.fromisoformat(request.POST.get('date', ''))
        except ValueError:
            messages.error(request, 'তারিখ ঠিক নেই।')
            return redirect(here)
        if shop.subscription_plan == TRIAL_PLAN:
            shop.trial_ends_at = _end_of_day(new_day)
        else:
            shop.valid_until = new_day
        if new_day >= day:
            shop.is_locked = False
        shop.save(update_fields=['trial_ends_at', 'valid_until', 'is_locked'])
        hq.log_action(request, 'set_date', shop, f'মেয়াদ শেষ {new_day:%d-%m-%Y}')
        messages.success(request, f'{shop.name}-এর মেয়াদ এখন {new_day:%d-%m-%Y} পর্যন্ত।')

    elif action == 'lock':
        shop.is_locked = True
        shop.save(update_fields=['is_locked'])
        hq.log_action(request, 'lock', shop)
        messages.success(request, f'{shop.name} লক করা হয়েছে — সেলার শুধু বিলিং পাতা দেখবে।')

    elif action == 'unlock':
        end = subscription_end(shop)
        if end is not None and end < day:
            messages.error(request, 'মেয়াদ শেষ হয়ে গেছে — লক খুললেও আবার লক হবে। আগে মেয়াদ বাড়ান বা তারিখ ঠিক করুন।')
        else:
            shop.is_locked = False
            shop.save(update_fields=['is_locked'])
            hq.log_action(request, 'unlock', shop)
            messages.success(request, f'{shop.name}-এর লক খোলা হয়েছে।')

    elif action == 'suspend':
        reason = (request.POST.get('reason') or '').strip()[:300]
        with transaction.atomic():
            shop.is_suspended = True
            shop.save(update_fields=['is_suspended'])
            n = hq.shop_users(shop).update(is_active=False)
        hq.log_action(request, 'suspend', shop, reason or 'কারণ লেখা হয়নি')
        messages.success(request, f'{shop.name} বন্ধ করা হয়েছে — ওয়েবসাইট বন্ধ, {n}টা লগইন বন্ধ।')

    elif action == 'unsuspend':
        with transaction.atomic():
            shop.is_suspended = False
            shop.save(update_fields=['is_suspended'])
            n = hq.shop_users(shop).update(is_active=True)
        hq.log_action(request, 'unsuspend', shop)
        messages.success(request, f'{shop.name} আবার চালু — {n}টা লগইন খোলা হয়েছে।')

    elif action == 'sms':
        amount = _int(request.POST.get('amount'))
        note = (request.POST.get('note') or '').strip()[:200]
        with transaction.atomic():
            shop = Shop.objects.select_for_update().get(pk=shop.pk)
            new_balance = (shop.sms_balance or 0) + amount
            if amount == 0 or new_balance < 0 or abs(amount) > 1000000:
                messages.error(request, f'SMS-এর সংখ্যা ঠিক নেই (এখন ব্যালেন্স {shop.sms_balance})।')
                return redirect(here)
            shop.sms_balance = new_balance
            shop.save(update_fields=['sms_balance'])
        hq.log_action(request, 'sms', shop, f'{amount:+d} SMS, এখন {new_balance}' + (f' — {note}' if note else ''))
        messages.success(request, f'{shop.name}: {amount:+d} SMS, এখন ব্যালেন্স {new_balance}।')

    elif action == 'sms_toggle':
        shop.is_sms_active = not shop.is_sms_active
        shop.save(update_fields=['is_sms_active'])
        hq.log_action(request, 'sms_toggle', shop, 'চালু' if shop.is_sms_active else 'বন্ধ')
        messages.success(request, f'{shop.name}-এর SMS এখন {"চালু" if shop.is_sms_active else "বন্ধ"}।')

    elif action == 'password':
        password = hq.make_temp_password()
        shop.user.set_password(password)
        shop.user.save(update_fields=['password'])
        hq.log_action(request, 'password', shop, f'মালিক {shop.user.phone_number}')
        messages.success(request, f'{shop.user.phone_number}-এর নতুন পাসওয়ার্ড: {password} — এখনই সেলারকে জানান '
                                  '(এটা আর দেখানো হবে না), আর লগইনের পর সেটিংস থেকে বদলে নিতে বলুন।')

    elif action == 'note':
        shop.hq_note = (request.POST.get('note') or '').strip()[:4000]
        shop.save(update_fields=['hq_note'])
        hq.log_action(request, 'note', shop, shop.hq_note[:200])
        messages.success(request, 'নোট রাখা হয়েছে।')

    elif action == 'delete':
        if (request.POST.get('confirm') or '').strip().lower() != (shop.slug or '').lower():
            messages.error(request, 'নিশ্চিত করতে দোকানের সাবডোমেইন ঠিকঠাক লিখুন।')
            return redirect(here)
        if shop.user.is_superuser:
            messages.error(request, 'এই দোকান একজন সুপারইউজারের — Django Admin থেকে আলাদা করুন।')
            return redirect(here)
        label = f'{shop.name} ({shop.slug}, {shop.user.phone_number})'
        with transaction.atomic():
            staff_ids = list(StaffProfile.objects.filter(shop=shop).values_list('user_id', flat=True))
            hq.log_action(request, 'delete', shop, label, shop_label=shop.name)
            User.objects.filter(pk__in=staff_ids, is_superuser=False).delete()
            shop.user.delete()                 # দোকান আর তার সব ডাটা CASCADE-এ মুছে যায়
        messages.success(request, f'{label} মুছে ফেলা হয়েছে।')
        return redirect('manage_shops')

    else:
        messages.error(request, 'অজানা কাজ।')
    return redirect(here)


# ============================================================
# ইউজার আর "এই অ্যাকাউন্টে ঢুকুন"
# ============================================================
@superuser_required
def users(request):
    q = request.GET.get('q', '').strip()
    role = request.GET.get('role', '')
    qs = User.objects.select_related('shop', 'staff_profile__shop').order_by('-date_joined')
    if q:
        digits = ''.join(ch for ch in q if ch.isdigit())
        cond = Q(name__icontains=q) | Q(phone_number__icontains=q)
        if len(digits) >= 4:
            cond |= Q(phone_number__contains=digits[-10:])
        qs = qs.filter(cond)
    if role == 'owner':
        qs = qs.filter(shop__isnull=False)
    elif role == 'staff':
        qs = qs.filter(staff_profile__isnull=False)
    elif role == 'admin':
        qs = qs.filter(is_superuser=True)
    elif role == 'off':
        qs = qs.filter(is_active=False)
    page = _page(request, qs)
    for user in page.object_list:
        user.hq_shop = getattr(user, 'shop', None) if hasattr(user, 'shop') else None
        if user.hq_shop is None and hasattr(user, 'staff_profile'):
            user.hq_shop = user.staff_profile.shop
            user.hq_role = 'স্টাফ'
        else:
            user.hq_role = 'সুপারইউজার' if user.is_superuser else ('মালিক' if user.hq_shop else 'দোকান নেই')
        user.can_enter = hq.can_impersonate(request.user, user)
    return render(request, 'store/hq/users.html', {
        'active': 'users', 'page_obj': page, 'q': q, 'role': role, 'query': _query_without_page(request),
        'roles': (('', 'সব'), ('owner', 'মালিক'), ('staff', 'স্টাফ'), ('admin', 'সুপারইউজার'), ('off', 'লগইন বন্ধ')),
    })


def _user_shop(user):
    shop = getattr(user, 'shop', None) if hasattr(user, 'shop') else None
    if shop is None and hasattr(user, 'staff_profile'):
        shop = user.staff_profile.shop
    return shop


@superuser_required
@require_POST
def user_action(request, user_id):
    target = get_object_or_404(User, pk=user_id)
    action = request.POST.get('action', '')
    shop = _user_shop(target)
    if target.is_superuser:
        messages.error(request, 'সুপারইউজারের অ্যাকাউন্ট এখান থেকে বদলানো যায় না — Django Admin ব্যবহার করুন।')
    elif shop is not None and shop.is_demo:
        messages.error(request, 'ডেমো দোকানের অ্যাকাউন্ট বদলানো যায় না।')
    elif action == 'password':
        password = hq.make_temp_password()
        target.set_password(password)
        target.save(update_fields=['password'])
        hq.log_action(request, 'password', shop, target.phone_number)
        messages.success(request, f'{target.phone_number}-এর নতুন পাসওয়ার্ড: {password} — এখনই জানান, এটা আর দেখানো হবে না।')
    elif action == 'toggle_active':
        target.is_active = not target.is_active
        target.save(update_fields=['is_active'])
        state = 'চালু' if target.is_active else 'বন্ধ'
        hq.log_action(request, 'user_active', shop, f'{target.phone_number} — লগইন {state}')
        messages.success(request, f'{target.phone_number}-এর লগইন এখন {state}।')
    else:
        messages.error(request, 'অজানা কাজ।')
    return _back(request, 'all_users')


@superuser_required
@require_POST
def login_as(request, user_id):
    target = get_object_or_404(User, pk=user_id)
    if not hq.can_impersonate(request.user, target):
        messages.error(request, 'এই অ্যাকাউন্টে ঢোকা যায় না (বন্ধ করা বা সুপারইউজার)।')
        return _back(request, 'all_users')
    shop = _user_shop(target)
    back = reverse('hq_shop', args=[shop.pk]) if shop else reverse('all_users')
    hq.log_action(request, 'login_as', shop, target.phone_number)
    hq.start_impersonation(request, target, back)
    messages.info(request, 'আপনি Master HQ থেকে এই অ্যাকাউন্টে ঢুকেছেন। উপরের "Master HQ-তে ফিরুন" চেপে ফিরে যান।')
    return redirect('dashboard' if shop else 'setup_shop')


@require_POST
def stop_login_as(request):
    actor, target, back = hq.stop_impersonation(request)
    if actor is None:
        if target is not None:
            messages.info(request, 'ফেরার সময় পার হয়ে গেছে (২ ঘণ্টা) — নিজের পাসওয়ার্ড দিয়ে আবার লগইন করুন।')
        return redirect('login')
    messages.success(request, f'Master HQ-তে ফিরেছেন ({target.phone_number} থেকে)।')
    if back and url_has_allowed_host_and_scheme(back, allowed_hosts={request.get_host()}):
        return redirect(back)
    return redirect('master_dashboard')


# ============================================================
# পেমেন্টের খাতা
# ============================================================
@superuser_required
def payments(request):
    status = request.GET.get('status', '')
    kind = request.GET.get('kind', '')
    period = request.GET.get('period', '')
    q = request.GET.get('q', '').strip()
    qs = OnlinePayment.objects.select_related('shop').order_by('-created_at')
    if status in ('Completed', 'Pending', 'Failed'):
        qs = qs.filter(status=status)
    if kind in ('plan', 'sms'):
        qs = qs.filter(kind=kind)
    if period == 'manual':
        qs = qs.filter(environment='manual')
    day = hq.today()
    if period == 'month':
        qs = qs.filter(created_at__gte=hq.month_start(day))
    elif period == 'last':
        start = hq.add_months(day.replace(day=1), -1)
        qs = qs.filter(created_at__gte=hq.day_start(start), created_at__lt=hq.month_start(day))
    if q:
        qs = qs.filter(Q(invoice_number__icontains=q) | Q(trx_id__icontains=q) | Q(shop__name__icontains=q)
                       | Q(shop__slug__icontains=q) | Q(shop__phone__icontains=q))
    totals = qs.aggregate(done=Sum('amount', filter=Q(status='Completed')), n_done=Count('pk', filter=Q(status='Completed')),
                          n=Count('pk'))
    page = _page(request, qs)
    now = timezone.now()
    for p in page.object_list:
        p.stuck = p.status == 'Pending' and p.created_at <= now - datetime.timedelta(minutes=10)
    return render(request, 'store/hq/payments.html', {
        'active': 'payments', 'page_obj': page, 'status': status, 'kind': kind, 'period': period, 'q': q,
        'totals': totals, 'query': _query_without_page(request),
        'legacy': PaymentRequest.objects.filter(status='Pending').select_related('shop').order_by('-created_at'),
    })


@superuser_required
@require_POST
def payment_recheck(request, payment_id):
    from . import payments as pay
    payment = get_object_or_404(OnlinePayment, pk=payment_id)
    result, _, message = pay.apply_successful_payment(payment.invoice_number, attempts=1, timeout=10)
    hq.log_action(request, 'payment_recheck', payment.shop, f'{payment.invoice_number}: {result}')
    (messages.success if result in ('ok', 'already') else messages.warning)(request, f'{payment.invoice_number}: {message}')
    return _back(request, 'master_billing')


@superuser_required
@require_POST
def payment_complete(request, payment_id):
    """PayStation-এর প্যানেলে টাকা এসেছে দেখা গেলে, কিন্তু আমাদের এখানে Pending — হাতে সম্পন্ন।"""
    from . import payments as pay
    payment = get_object_or_404(OnlinePayment, pk=payment_id)
    trx = pay.valid_trx_id(request.POST.get('trx_id'))
    if not trx:
        messages.error(request, 'PayStation-এর লেনদেন নম্বর (Trx ID) ঠিকঠাক লিখুন।')
        return _back(request, 'master_billing')
    result, _, message = pay.complete_payment(payment.invoice_number, payment.amount, trx, 'হাতে নিশ্চিত (Master HQ)')
    hq.log_action(request, 'payment_manual', payment.shop, f'{payment.invoice_number} — Trx {trx}: {result}')
    (messages.success if result in ('ok', 'already') else messages.error)(request, f'{payment.shop.name}: {message}')
    return _back(request, 'master_billing')


# ============================================================
# SMS
# ============================================================
def _broadcast(phones, text):
    from . import sms

    def run():
        try:
            for i in range(0, len(phones), 100):
                sms.gateway_send(phones[i:i + 100], text)
        except Exception:                                   # noqa: BLE001 — পেছনের কাজ, পাতা আটকাবে না
            import logging
            logging.getLogger('store.hq').exception('HQ broadcast failed')
        finally:
            if threaded:
                connection.close()
    threaded = sms._background_allowed()
    if threaded:
        threading.Thread(target=run, daemon=True).start()
    else:
        run()


def _find_shop(value):
    value = (value or '').strip()
    if not value:
        return None
    shops = _search_shops(value)
    exact = shops.filter(Q(slug__iexact=value) | Q(pk=int(value)) if value.isdigit() else Q(slug__iexact=value)).first()
    if exact:
        return exact
    return shops.first() if shops.count() == 1 else None


@superuser_required
def sms_panel(request):
    from . import sms
    setting, _ = MasterSetting.objects.get_or_create(id=1)
    if request.method == 'POST':
        action = request.POST.get('action', '')
        if action == 'recharge':
            shop = _find_shop(request.POST.get('shop'))
            amount = _int(request.POST.get('amount'))
            if shop is None:
                messages.error(request, 'দোকান পাওয়া যায়নি — সাবডোমেইন, ফোন নম্বর বা দোকানের নম্বর (ID) লিখুন।')
            elif amount == 0 or (shop.sms_balance or 0) + amount < 0 or abs(amount) > 1000000:
                messages.error(request, 'SMS-এর সংখ্যা ঠিক নেই।')
            else:
                Shop.objects.filter(pk=shop.pk).update(sms_balance=Coalesce('sms_balance', 0) + amount)
                shop.refresh_from_db(fields=['sms_balance'])
                hq.log_action(request, 'sms', shop, f'{amount:+d} SMS, এখন {shop.sms_balance}')
                messages.success(request, f'{shop.name}: {amount:+d} SMS, এখন ব্যালেন্স {shop.sms_balance}।')
        elif action == 'broadcast':
            audience = request.POST.get('audience', 'all')
            text = (request.POST.get('message') or '').strip()
            if not text or len(text) > 480:
                messages.error(request, 'বার্তা লিখুন (৪৮০ অক্ষরের মধ্যে)।')
            elif not sms.gateway_ready():
                messages.error(request, 'SMS গেটওয়ের চাবি বসানো নেই — আগে সিস্টেম সেটিংসে বসান।')
            else:
                shops_qs = hq.notice_audience(audience).select_related('user')
                phones = sms.clean_phones([s.phone or s.user.phone_number for s in shops_qs])
                if not phones:
                    messages.error(request, 'এই দলে কোনো সঠিক নম্বর নেই।')
                else:
                    _broadcast(phones, text)
                    label = dict(PlatformNotice.AUDIENCE_CHOICES).get(audience, audience)
                    hq.log_action(request, 'broadcast', None, f'{label} — {len(phones)} জন: {text[:150]}')
                    messages.success(request, f'{len(phones)} জন সেলারকে SMS পাঠানো শুরু হয়েছে (প্ল্যাটফর্মের খরচে)।')
        return redirect('hq_sms')

    day = hq.today()
    month = hq.month_start(day)
    logs = SmsLog.objects.filter(shop__is_demo=False)
    usage = logs.filter(created_at__gte=month).aggregate(
        used=Sum('sms_used'), sends=Count('pk'), failed=Count('pk', filter=Q(status__in=['failed', 'partial'])))
    revenue = OnlinePayment.objects.filter(kind='sms', status='Completed', completed_at__gte=month,
                                           shop__is_demo=False).aggregate(v=Sum('amount'), n=Count('pk'))
    top = (logs.filter(created_at__gte=month).values('shop_id', 'shop__name').annotate(used=Sum('sms_used'))
           .order_by('-used')[:10])
    low = (Shop.objects.filter(hq.status_q('paid') | hq.status_q('trial')).filter(sms_balance__lt=20, sms_on_received=True)
           .order_by('sms_balance', '-created_at')[:10])
    client_id, api_key = sms.gateway_keys()
    env_keys = bool(getattr(django_settings, 'SMS_GATEWAY_CLIENT_ID', '') and getattr(django_settings, 'SMS_GATEWAY_API_KEY', ''))
    audience_counts = {k: hq.notice_audience(k).count() for k, _ in PlatformNotice.AUDIENCE_CHOICES}
    return render(request, 'store/hq/sms.html', {
        'active': 'sms', 'setting': setting, 'usage': usage, 'revenue': revenue, 'top': top, 'low': low,
        'gateway_ready': bool(client_id and api_key), 'env_keys': env_keys,
        'recent': logs.select_related('shop').order_by('-created_at')[:15],
        'balance_total': Shop.objects.filter(is_demo=False).aggregate(v=Sum('sms_balance'))['v'] or 0,
        'audiences': [(k, label, audience_counts[k]) for k, label in PlatformNotice.AUDIENCE_CHOICES],
    })


@superuser_required
def recharge_sms(request):
    """পুরনো ফর্মের ঠিকানা — এখন SMS পাতা থেকেই।"""
    return redirect('hq_sms')


# ============================================================
# প্ল্যাটফর্ম নোটিশ (সেলারদের ড্যাশবোর্ডে)
# ============================================================
def _notice_from_post(request, notice):
    errors = []
    notice.title = (request.POST.get('title') or '').strip()[:120]
    notice.body = (request.POST.get('body') or '').strip()[:1000]
    notice.level = request.POST.get('level') if request.POST.get('level') in dict(PlatformNotice.LEVEL_CHOICES) else 'info'
    notice.audience = (request.POST.get('audience') if request.POST.get('audience') in dict(PlatformNotice.AUDIENCE_CHOICES)
                       else 'all')
    link = (request.POST.get('link_url') or '').strip()[:300]
    if link and not (link.startswith('/') or link.startswith('https://')):
        errors.append('লিংক "/" বা "https://" দিয়ে শুরু হতে হবে।')
    notice.link_url = link
    notice.link_text = (request.POST.get('link_text') or '').strip()[:40]
    days = _int(request.POST.get('days'), 0)
    if notice.pk is None:
        notice.starts_at = timezone.now()
    notice.ends_at = notice.starts_at + datetime.timedelta(days=days) if days > 0 else None
    notice.is_active = request.POST.get('is_active', 'on') == 'on'
    if not notice.title:
        errors.append('শিরোনাম লিখুন।')
    return errors


@superuser_required
def notices(request):
    notice = PlatformNotice()
    errors = []
    if request.method == 'POST':
        errors = _notice_from_post(request, notice)
        if not errors:
            notice.created_by = request.user
            notice.save()
            hq.log_action(request, 'notice', None, f'নতুন: {notice.title}')
            messages.success(request, 'নোটিশ চালু হয়েছে — সেলাররা ড্যাশবোর্ডের উপরে দেখবে।')
            return redirect('hq_notices')
    now = timezone.now()
    items = list(PlatformNotice.objects.all()[:50])
    for n in items:
        n.live = n.is_active and n.starts_at <= now and (n.ends_at is None or n.ends_at > now)
    return render(request, 'store/hq/notices.html', {
        'active': 'notices', 'items': items, 'form': notice, 'errors': errors,
        'levels': PlatformNotice.LEVEL_CHOICES, 'audiences': PlatformNotice.AUDIENCE_CHOICES,
    })


@superuser_required
@require_POST
def notice_action(request, notice_id):
    notice = get_object_or_404(PlatformNotice, pk=notice_id)
    action = request.POST.get('action', '')
    if action == 'toggle':
        notice.is_active = not notice.is_active
        notice.save(update_fields=['is_active'])
        hq.log_action(request, 'notice', None, f'{"চালু" if notice.is_active else "বন্ধ"}: {notice.title}')
    elif action == 'delete':
        hq.log_action(request, 'notice', None, f'মুছে ফেলা: {notice.title}')
        notice.delete()
    elif action == 'edit':
        errors = _notice_from_post(request, notice)
        if errors:
            messages.error(request, ' '.join(errors))
        else:
            notice.save()
            hq.log_action(request, 'notice', None, f'বদলানো: {notice.title}')
            messages.success(request, 'নোটিশ বদলানো হয়েছে।')
    return redirect('hq_notices')


# ============================================================
# খাতা, খোঁজা, সেটিংস
# ============================================================
@superuser_required
def activity(request):
    action = request.GET.get('action', '')
    q = request.GET.get('q', '').strip()
    qs = HQAuditLog.objects.all()
    if action in HQAuditLog.ACTION_LABELS:
        qs = qs.filter(action=action)
    if q:
        qs = qs.filter(Q(shop_label__icontains=q) | Q(detail__icontains=q) | Q(actor_label__icontains=q))
    return render(request, 'store/hq/activity.html', {
        'active': 'activity', 'page_obj': _page(request, qs, 40), 'action': action, 'q': q,
        'actions': sorted(HQAuditLog.ACTION_LABELS.items(), key=lambda kv: kv[1]),
        'query': _query_without_page(request),
    })


@superuser_required
def search(request):
    q = request.GET.get('q', '').strip()
    shops_found, users_found, payments_found = [], [], []
    if q:
        shops_found = list(_search_shops(q).select_related('user').order_by('-created_at')[:20])
        for shop in shops_found:
            shop.hq_status = hq.shop_status(shop)
        digits = ''.join(ch for ch in q if ch.isdigit())
        ucond = Q(name__icontains=q) | Q(phone_number__icontains=q)
        if len(digits) >= 4:
            ucond |= Q(phone_number__contains=digits[-10:])
        users_found = list(User.objects.filter(ucond).select_related('shop', 'staff_profile__shop')[:20])
        for user in users_found:
            user.hq_shop = _user_shop(user)
        if len(q) >= 4:
            payments_found = list(OnlinePayment.objects.filter(Q(invoice_number__icontains=q) | Q(trx_id__icontains=q))
                                  .select_related('shop')[:10])
        if len(shops_found) == 1 and not payments_found and all(u.hq_shop == shops_found[0] for u in users_found):
            return redirect('hq_shop', shops_found[0].pk)
    return render(request, 'store/hq/search.html', {
        'active': '', 'q': q, 'shops': shops_found, 'users': users_found, 'payments': payments_found,
    })


@superuser_required
def system_settings(request):
    from . import health, paystation, sms
    setting, _ = MasterSetting.objects.get_or_create(id=1)
    if request.method == 'POST':
        changes = []
        signups = request.POST.get('signups_open') == 'on'
        if signups != setting.signups_open:
            changes.append('সাইনআপ ' + ('চালু' if signups else 'বন্ধ'))
        setting.signups_open = signups
        client_id = (request.POST.get('sms_client_id') or '').strip()
        if client_id != (setting.sms_client_id or ''):
            changes.append('SMS Client ID')
        setting.sms_client_id = client_id
        api_key = (request.POST.get('sms_api_key') or '').strip()
        if api_key:                                         # খালি রাখলে আগেরটাই থাকে
            setting.sms_api_key = api_key
            changes.append('SMS API Key')
        elif request.POST.get('clear_sms_api_key') == 'on':
            setting.sms_api_key = ''
            changes.append('SMS API Key মোছা')
        try:
            rate = Decimal(request.POST.get('sms_rate') or setting.sms_rate)
        except (ArithmeticError, ValueError):
            rate = setting.sms_rate
        if not Decimal('0.05') <= rate <= Decimal('5'):
            messages.error(request, 'SMS-এর দাম ০.০৫ থেকে ৫ টাকার মধ্যে হতে হবে।')
            return redirect('master_settings')
        if rate != setting.sms_rate:
            changes.append(f'SMS দাম ৳{rate}')
        setting.sms_rate = rate
        name = (request.POST.get('platform_name') or '').strip()[:100]
        if name:
            setting.platform_name = name
        setting.save()
        hq.log_action(request, 'settings', None, ', '.join(changes) or 'কিছু বদলায়নি')
        messages.success(request, 'সেটিংস রাখা হয়েছে।')
        return redirect('master_settings')
    latency = health.database_latency_ms()
    checks = [
        ('ডাটাবেস', latency is not None and latency <= 25,
         f'{latency:.0f} ms' if latency is not None else 'মাপা যায়নি', health.database_region() or ''),
        ('PayStation (অনলাইন পেমেন্ট)', paystation.is_configured(),
         paystation.current_environment() if paystation.is_configured() else 'চাবি বসানো নেই', ''),
        ('SMS গেটওয়ে', sms.gateway_ready(), 'চালু' if sms.gateway_ready() else 'চাবি বসানো নেই', ''),
        ('ছবি রাখার জায়গা (R2)', bool(getattr(django_settings, 'USE_R2', False)),
         'Cloudflare R2' if getattr(django_settings, 'USE_R2', False) else 'সার্ভারের নিজের ডিস্ক', ''),
        ('প্রতিদিনের কাজ (cron)', bool(getattr(django_settings, 'CRON_SECRET', '')),
         'CRON_SECRET বসানো' if getattr(django_settings, 'CRON_SECRET', '') else 'CRON_SECRET নেই', ''),
        ('DEBUG বন্ধ', not django_settings.DEBUG, 'বন্ধ' if not django_settings.DEBUG else 'চালু — লাইভে বন্ধ রাখুন', ''),
    ]
    return render(request, 'store/hq/settings.html', {
        'active': 'settings', 'setting': setting, 'checks': checks, 'system_warnings': health.warnings(),
        'env_keys': bool(getattr(django_settings, 'SMS_GATEWAY_CLIENT_ID', '')
                         and getattr(django_settings, 'SMS_GATEWAY_API_KEY', '')),
        'django_version': __import__('django').get_version(),
    })
