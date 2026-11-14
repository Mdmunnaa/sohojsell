"""
Master HQ-র হিসাব আর নিয়ম এক জায়গায় (Edumi Master HQ-র মতো)।

- দোকানের অবস্থা: পেইড / ফ্রি ট্রায়াল / মেয়াদ শেষ / বন্ধ করা / ডেমো — তালিকার ফিল্টার আর ড্যাশবোর্ডের গোনা একই নিয়মে
- ড্যাশবোর্ডের সংখ্যা (আয়, সাইনআপ, এখন যা করতে হবে)
- খাতা (HQAuditLog): Master HQ থেকে যা করা হয়, সব লেখা থাকে
- "এই অ্যাকাউন্টে ঢুকুন": সুপারইউজার সেলারের অ্যাকাউন্টে ঢুকে দেখতে পারে, ২ ঘণ্টা পর্যন্ত, তারপর এক চাপে ফেরত
"""
import datetime
import secrets
from decimal import Decimal

from django.contrib.auth import get_user_model, login, logout
from django.contrib.auth.decorators import user_passes_test
from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate, TruncMonth
from django.utils import timezone

from .plans import TRIAL_PLAN, subscription_end

IMPERSONATOR_KEY = '_hq_impersonator'
IMPERSONATION_MAX_SECONDS = 2 * 3600       # একবারে সর্বোচ্চ ২ ঘণ্টা — তারপর ফিরতে হলে আবার লগইন
AUTH_BACKEND = 'django.contrib.auth.backends.ModelBackend'

STATUS_LABELS = {
    'paid': 'পেইড', 'trial': 'ফ্রি ট্রায়াল', 'locked': 'মেয়াদ শেষ', 'suspended': 'বন্ধ করা', 'demo': 'ডেমো',
}
PLAN_NAMES = ('Basic', 'Standard', 'Premium')

# শুধু সক্রিয় সুপারইউজার — বাকিরা লগইন পাতায় যায়
superuser_required = user_passes_test(lambda u: u.is_authenticated and u.is_active and u.is_superuser,
                                      login_url='/accounts/login/')


def today():
    return timezone.localdate()


def day_start(day):
    return timezone.make_aware(datetime.datetime.combine(day, datetime.time.min))


def month_start(day=None):
    return day_start((day or today()).replace(day=1))


def add_months(day, months):
    month = day.month - 1 + months
    return day.replace(year=day.year + month // 12, month=month % 12 + 1, day=1)


# ---------------------------------------------------------------------------------------------
# দোকানের অবস্থা
# ---------------------------------------------------------------------------------------------
def _expired_q(day):
    return (Q(is_locked=True) | Q(subscription_plan=TRIAL_PLAN, trial_ends_at__lt=day_start(day))
            | (~Q(subscription_plan=TRIAL_PLAN) & Q(valid_until__lt=day)))


def status_q(key, day=None):
    """Shop queryset-এর filter।"""
    day = day or today()
    if key == 'demo':
        return Q(is_demo=True)
    real = Q(is_demo=False)
    if key == 'suspended':
        return real & Q(is_suspended=True)
    live = real & Q(is_suspended=False)
    if key == 'locked':
        return live & _expired_q(day)
    if key == 'trial':
        return live & ~_expired_q(day) & Q(subscription_plan=TRIAL_PLAN)
    if key == 'paid':
        return live & ~_expired_q(day) & ~Q(subscription_plan=TRIAL_PLAN)
    if key == 'trial_ending':          # ট্রায়াল ৭ দিনের মধ্যে শেষ — ফোন করার সেরা সময়
        return status_q('trial', day) & Q(trial_ends_at__lt=day_start(day + datetime.timedelta(days=8)))
    if key == 'expiring':              # পেইড, মেয়াদ ৭ দিনের মধ্যে শেষ
        return status_q('paid', day) & Q(valid_until__lte=day + datetime.timedelta(days=7))
    return real


def shop_status(shop, day=None):
    if shop.is_demo:
        return 'demo'
    if shop.is_suspended:
        return 'suspended'
    end = subscription_end(shop)
    if shop.is_locked or (end is not None and end < (day or today())):
        return 'locked'
    return 'trial' if shop.subscription_plan == TRIAL_PLAN else 'paid'


def status_counts(day=None):
    from .models import Shop
    day = day or today()
    keys = ('paid', 'trial', 'locked', 'suspended')
    row = Shop.objects.aggregate(total=Count('pk', filter=Q(is_demo=False)),
                                 **{k: Count('pk', filter=status_q(k, day)) for k in keys})
    return row


# ---------------------------------------------------------------------------------------------
# ড্যাশবোর্ডের সংখ্যা
# ---------------------------------------------------------------------------------------------
def monthly_price(plan):
    from .payments import PLAN_PRICES
    return PLAN_PRICES.get(plan, Decimal('0'))


def stats():
    from .models import OnlinePayment, Order, Shop, SmsLog
    day = today()
    start = month_start(day)
    status = status_counts(day)

    paid = OnlinePayment.objects.filter(status=OnlinePayment.STATUS_COMPLETED, shop__is_demo=False)
    month_paid = paid.filter(completed_at__gte=start).aggregate(
        plans=Sum('amount', filter=Q(kind=OnlinePayment.KIND_PLAN)),
        sms=Sum('amount', filter=Q(kind=OnlinePayment.KIND_SMS)),
        count=Count('pk'))
    revenue = {'plans': month_paid['plans'] or Decimal('0'), 'sms': month_paid['sms'] or Decimal('0'),
               'count': month_paid['count']}
    revenue['total'] = revenue['plans'] + revenue['sms']

    plan_rows = Shop.objects.filter(status_q('paid', day)).values('subscription_plan').annotate(n=Count('pk'))
    plans = {row['subscription_plan']: row['n'] for row in plan_rows}
    mrr = sum((monthly_price(p) * n for p, n in plans.items()), Decimal('0'))

    # গত ৩০ দিনের সাইনআপ, দিন ধরে
    first = day - datetime.timedelta(days=29)
    by_day = dict(Shop.objects.filter(is_demo=False, created_at__gte=day_start(first))
                  .annotate(d=TruncDate('created_at', tzinfo=timezone.get_current_timezone()))
                  .values_list('d').annotate(n=Count('pk')).values_list('d', 'n'))
    top = max(by_day.values(), default=0) or 1
    signups = []
    for i in range(30):
        d = first + datetime.timedelta(days=i)
        n = by_day.get(d, 0)
        signups.append({'day': d, 'n': n, 'pct': round(n * 100 / top) if n else 0})
    new = {'today': by_day.get(day, 0), 'week': sum(s['n'] for s in signups[-7:]),
           'month': Shop.objects.filter(is_demo=False, created_at__gte=start).count()}

    # গত ৬ মাসের আয়
    six = add_months(day.replace(day=1), -5)
    by_month = {m.date() if hasattr(m, 'date') else m: v for m, v in
                paid.filter(completed_at__gte=day_start(six))
                .annotate(m=TruncMonth('completed_at', tzinfo=timezone.get_current_timezone()))
                .values_list('m').annotate(v=Sum('amount')).values_list('m', 'v')}
    top = max(by_month.values(), default=0) or 1
    months = []
    for i in range(6):
        m = add_months(six, i)
        v = by_month.get(m, Decimal('0'))
        months.append({'month': m, 'value': v, 'pct': round(v * 100 / top) if v else 0})

    orders = Order.objects.filter(shop__is_demo=False, created_at__gte=start).aggregate(
        n=Count('pk'), value=Sum('total_amount', filter=~Q(status__in=['Cancelled', 'Returned'])))
    sms_month = SmsLog.objects.filter(shop__is_demo=False, created_at__gte=start).aggregate(n=Sum('sms_used'))['n'] or 0

    return {
        'generated_at': timezone.now(), 'status': status, 'total': status['total'], 'revenue': revenue,
        'mrr': mrr, 'plans': plans, 'signups': signups, 'new': new, 'months': months,
        'orders_month': orders['n'], 'sales_month': orders['value'] or Decimal('0'),
        'sms_month': sms_month,
        'trial_value': status['trial'] * monthly_price('Standard'),
    }


def attention():
    """ড্যাশবোর্ডের "এখন যা করতে হবে" — প্রতিটা একটা সংখ্যা, শূন্য হলে দেখায় না।"""
    from . import domains
    from .models import MasterSetting, OnlinePayment, PaymentRequest, SettlementRequest, Shop
    day = today()
    now = timezone.now()
    settle = SettlementRequest.objects.filter(status=SettlementRequest.PENDING).aggregate(
        n=Count('pk'), amount=Sum('amount'))
    setting = MasterSetting.objects.order_by('pk').first()
    from . import backups
    mixups = list(Shop.objects.filter(user__staff_profile__isnull=False).values_list('pk', flat=True)[:50])
    return {
        'backup': backups.hq_status()['warning'],
        # পুরনো একটা বাগে স্টাফ সেটিংস সেভ করলে দোকানের মালিকানা স্টাফের নামে চলে যেত — এমন দোকান ঠিক করতে হবে
        'owner_mixups': len(mixups), 'owner_mixup_first': mixups[0] if mixups else None,
        'signups_closed': bool(setting and not setting.signups_open),
        'domains': domains.pending_for_master().count(),
        'settlements': settle['n'], 'settlements_amount': settle['amount'] or Decimal('0'),
        'legacy_payments': PaymentRequest.objects.filter(status='Pending').count(),
        'stuck_payments': OnlinePayment.objects.filter(
            status=OnlinePayment.STATUS_PENDING, created_at__lte=now - datetime.timedelta(minutes=30),
            created_at__gte=now - datetime.timedelta(days=7)).count(),
        'trial_ending': Shop.objects.filter(status_q('trial_ending', day)).count(),
        'expiring': Shop.objects.filter(status_q('expiring', day)).count(),
        'locked': Shop.objects.filter(status_q('locked', day)).count(),
    }


def nav_counts():
    """বাঁ পাশের মেনুর হলুদ সংখ্যা — যেখানে কাজ জমে আছে।"""
    from . import domains
    from .models import PaymentRequest, SettlementRequest
    return {
        'settle': SettlementRequest.objects.filter(status=SettlementRequest.PENDING).count(),
        'domains': domains.pending_for_master().count(),
        'legacy': PaymentRequest.objects.filter(status='Pending').count(),
    }


# ---------------------------------------------------------------------------------------------
# খাতা
# ---------------------------------------------------------------------------------------------
def client_ip(request):
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    ip = forwarded.split(',')[-1].strip() if forwarded else request.META.get('REMOTE_ADDR', '')
    return ip or None


def log_action(request, action, shop=None, detail='', shop_label=None):
    from .models import HQAuditLog
    user = request.user if getattr(request, 'user', None) is not None and request.user.is_authenticated else None
    label = shop_label if shop_label is not None else (shop.name if shop else '')
    try:
        ip = client_ip(request)
        import ipaddress
        ipaddress.ip_address(ip or '')
    except ValueError:
        ip = None
    HQAuditLog.objects.create(actor=user, actor_label=(getattr(user, 'phone_number', '') or '')[:64], action=action,
                              shop=shop, shop_label=(label or '')[:200], detail=(detail or '')[:2000], ip=ip)


# ---------------------------------------------------------------------------------------------
# "এই অ্যাকাউন্টে ঢুকুন"
# ---------------------------------------------------------------------------------------------
def can_impersonate(actor, target):
    return (actor.is_authenticated and actor.is_superuser and actor.is_active and target.is_active
            and not target.is_superuser and target.pk != actor.pk)


def start_impersonation(request, target, back_url):
    """Django লগইনের সময় সেশন নতুন করে — তাই ফেরার তথ্য লগইনের পরে রাখা হয়।"""
    actor = request.user
    actor_hash = actor.get_session_auth_hash()
    previous_login = target.last_login
    login(request, target, backend=AUTH_BACKEND)
    # সেলারের "শেষ লগইন" যেন আমাদের দেখার কারণে বদলে না যায়
    get_user_model().objects.filter(pk=target.pk).update(last_login=previous_login)
    # ফেরার টিকিট সুপারইউজারের পাসওয়ার্ডের সাথে বাঁধা (পাসওয়ার্ড বদলালে অচল) আর ২ ঘণ্টা মেয়াদি
    request.session[IMPERSONATOR_KEY] = {'id': actor.pk, 'phone': actor.phone_number, 'back': back_url,
                                         'since': timezone.now().timestamp(), 'hash': actor_hash}
    request.session.set_expiry(IMPERSONATION_MAX_SECONDS)


def impersonation(request):
    session = getattr(request, 'session', None)
    user = getattr(request, 'user', None)
    if session is None or user is None or not user.is_authenticated:
        return None
    data = session.get(IMPERSONATOR_KEY)
    return data if isinstance(data, dict) and data.get('id') else None


def stop_impersonation(request):
    """নিজের অ্যাকাউন্টে ফেরায়। রিটার্ন: (সুপারইউজার বা None, যে অ্যাকাউন্ট থেকে ফিরলো, ফেরার পাতা)।"""
    from django.utils.crypto import constant_time_compare
    data = impersonation(request)
    if not data:
        return None, None, None
    target = request.user
    actor = get_user_model().objects.filter(pk=data['id'], is_superuser=True, is_active=True).first()
    fresh = (isinstance(data.get('since'), (int, float))
             and timezone.now().timestamp() - data['since'] <= IMPERSONATION_MAX_SECONDS)
    if actor is None or not fresh or not constant_time_compare(str(data.get('hash', '')), actor.get_session_auth_hash()):
        logout(request)      # টিকিট পুরনো/অচল — নিজের পাসওয়ার্ড দিয়ে আবার ঢুকতে হবে
        return None, target, None
    login(request, actor, backend=AUTH_BACKEND)
    request.session.set_expiry(None)
    return actor, target, data.get('back')


def make_temp_password():
    """পড়তে সহজ সাময়িক পাসওয়ার্ড (০/O, ১/l বাদ)।"""
    letters = 'abcdefghjkmnpqrstuvwxyz'
    digits = '23456789'
    return 'Sell-' + ''.join(secrets.choice(letters) for _ in range(4)) + '-' + ''.join(
        secrets.choice(digits) for _ in range(4))


def shop_users(shop):
    """মালিক আর স্টাফ — দোকান বন্ধ/চালুর সময় সবার লগইন একসাথে।"""
    from .models import StaffProfile
    ids = [shop.user_id] + list(StaffProfile.objects.filter(shop=shop).values_list('user_id', flat=True))
    return get_user_model().objects.filter(pk__in=ids, is_superuser=False)


# ---------------------------------------------------------------------------------------------
# সেলারদের নোটিশ
# ---------------------------------------------------------------------------------------------
def notices_for(shop):
    """এখন চালু নোটিশ, এই দোকানের অবস্থা অনুযায়ী (সেলারের ড্যাশবোর্ডের উপরে দেখায়)।"""
    from .models import PlatformNotice
    if shop is None or getattr(shop, 'is_demo', False):
        return []
    now = timezone.now()
    status = shop_status(shop)
    audiences = ['all', status] if status in ('trial', 'paid', 'locked') else ['all']
    return list(PlatformNotice.objects.filter(is_active=True, starts_at__lte=now, audience__in=audiences)
                .filter(Q(ends_at__isnull=True) | Q(ends_at__gt=now))[:3])


def notice_audience(audience):
    """নোটিশ বা SMS কতগুলো দোকানে যাবে।"""
    from .models import Shop
    if audience in ('trial', 'paid', 'locked'):
        return Shop.objects.filter(status_q(audience))
    return Shop.objects.filter(is_demo=False, is_suspended=False)
