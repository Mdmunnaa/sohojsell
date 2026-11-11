# store/views_sms.py
"""SMS প্যানেল: ব্যালেন্স, একজনকে বা অনেক কাস্টমারকে SMS, SMS কেনা, অর্ডারের অটো SMS আর ইতিহাস। হিসাব store/sms.py-তে।"""
import uuid
from types import SimpleNamespace

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import sms
from .models import Customer, OnlinePayment

LOGIN = '/accounts/login/'
DRAFT_KEY = 'sms_draft'
SENT_KEY = 'sms_sent_ids'

# তৈরি মেসেজ — {link} জায়গায় দোকানের ওয়েবসাইট বসে। বাংলা লেখায় সংখ্যা বাংলা অঙ্কে।
MESSAGE_TEMPLATES = [
    ('offer', 'bi-percent', 'অফার', 'ধামাকা অফার! সব পণ্যে ১০% ছাড়, শুধু এই সপ্তাহে। অর্ডার করুন: {link}', ''),
    ('new', 'bi-stars', 'নতুন কালেকশন', 'নতুন কালেকশন চলে এসেছে! দেখুন আর অর্ডার করুন: {link}', ''),
    ('thanks', 'bi-heart', 'ধন্যবাদ', 'আমাদের থেকে কেনাকাটার জন্য অনেক ধন্যবাদ। আবার আসবেন!', ''),
    ('due', 'bi-wallet2', 'বাকি টাকা',
     'সম্মানিত কাস্টমার, আপনার কাছে আমাদের কিছু টাকা বাকি আছে। সুবিধামতো সময়ে পরিশোধের অনুরোধ রইল।', 'due'),
    ('eid', 'bi-moon-stars', 'ঈদ শুভেচ্ছা', 'ঈদ মোবারক! আপনাকে ও আপনার পরিবারকে জানাই আন্তরিক শুভেচ্ছা।', ''),
    ('closed', 'bi-shop', 'দোকান বন্ধ', 'আগামীকাল দোকান বন্ধ থাকবে। পরশু থেকে যথারীতি খোলা থাকবে।', ''),
]
QUICK_AMOUNTS = [100, 200, 500, 1000]


def _profile(request):
    return getattr(request.user, 'staff_profile', None) if getattr(request.user, 'is_shop_staff', False) else None


def _is_owner(request):
    return not getattr(request.user, 'is_shop_staff', False)


def _can_send(request):
    profile = _profile(request)
    return _is_owner(request) or bool(profile and profile.can_send_sms)


def _can_manage(request):
    """SMS কেনা আর অটো SMS চালু/বন্ধ — মালিক বা সেটিংসের অনুমতি থাকা স্টাফ।"""
    profile = _profile(request)
    return _is_owner(request) or bool(profile and profile.can_manage_settings)


def _panel_url(anchor=''):
    return reverse('sms_panel') + (f'#{anchor}' if anchor else '')


def _purchases(shop):
    """SMS কেনার ইতিহাস: অনলাইন (PayStation) আর bKash/Nagad-এ পাঠিয়ে জমা দেওয়া — তারিখ অনুযায়ী একসাথে।"""
    rows = []
    for p in shop.online_payments.filter(kind=OnlinePayment.KIND_SMS)[:10]:
        status = {'Completed': ('যোগ হয়েছে', 'ok'), 'Failed': ('হয়নি', 'bad')}.get(p.status, ('যাচাই চলছে', 'wait'))
        rows.append({'when': p.created_at, 'count': p.sms_count, 'amount': p.amount,
                     'method': f'অনলাইন{" · " + p.payment_method if p.payment_method else ""}',
                     'status': status[0], 'tone': status[1], 'test': p.environment == 'sandbox'})
    for r in shop.payment_requests.filter(plan_name=sms.MANUAL_REQUEST_NAME).order_by('-created_at')[:10]:
        status = {'Approved': ('যোগ হয়েছে', 'ok'), 'Rejected': ('বাতিল', 'bad')}.get(r.status, ('যাচাই চলছে', 'wait'))
        rows.append({'when': r.created_at, 'count': sms.count_for_amount(r.amount), 'amount': r.amount,
                     'method': f'{r.payment_method} · {r.transaction_id}', 'status': status[0], 'tone': status[1],
                     'test': False})
    rows.sort(key=lambda row: row['when'], reverse=True)
    return rows[:12]


@login_required(login_url=LOGIN)
def sms_panel(request):
    shop = request.user.shop
    if not _can_send(request):
        messages.error(request, 'SMS পাঠানোর অনুমতি নেই। দোকানের মালিককে বলুন।')
        return redirect('dashboard')

    from .payments import online_payment_available, recheck_pending
    if _can_manage(request):
        # টাকা কেটে যাওয়ার পরও callback না এলে — পেইজ খুললেই আবার যাচাই
        for payment in recheck_pending(shop):
            if payment.kind == OnlinePayment.KIND_SMS:
                messages.success(request, f'পেমেন্ট নিশ্চিত হয়েছে — {sms.bn_num(payment.sms_count)}টা SMS যোগ হলো।')
    sms.expire_stuck(shop)
    shop.refresh_from_db(fields=['sms_balance', 'is_sms_active'])

    counts = sms.audience_counts(shop)
    audiences = [{'key': key, 'label': label, 'hint': hint, 'icon': icon, 'count': counts[key]}
                 for key, label, hint, icon in sms.AUDIENCES]
    draft = request.session.pop(DRAFT_KEY, None) or {}
    prefill = request.GET.get('to', '')
    if prefill and not draft:
        phones, _bad = sms.split_phone_text(prefill)
        if phones:
            draft = {'audience': 'manual', 'numbers': '\n'.join(phones), 'message': '', 'sign': True}

    link = shop.storefront_host_preview
    rate = sms.sms_rate()
    logs = list(shop.sms_logs.select_related('sent_by')[:30])
    from .dashboard import bn_ago
    for log in logs:
        log.ago = bn_ago(log.created_at)
        log.sent_by_name = ((log.sent_by.name or log.sent_by.phone_number) if log.sent_by_id and log.sent_by_id != shop.user_id
                            else '')
    sample_order = SimpleNamespace(id=1024, customer=SimpleNamespace(name=''))
    return render(request, 'store/sms_panel.html', {
        'shop': shop,
        'balance': shop.sms_balance or 0,
        'used_this_month': sms.used_this_month(shop),
        'audiences': audiences,
        'templates': [{'key': key, 'icon': icon, 'label': label, 'text': text.replace('{link}', link), 'audience': aud}
                      for key, icon, label, text, aud in MESSAGE_TEMPLATES],
        'draft': draft,
        'send_id': uuid.uuid4().hex,
        'signature': f'- {shop.name}',
        'logs': logs,
        'sending': any(log.status == log.SENDING for log in logs),
        'purchases': _purchases(shop),
        'can_manage': _can_manage(request),
        'rate': rate,
        'quick_amounts': [{'amount': amount, 'count': sms.count_for_amount(amount, rate)} for amount in QUICK_AMOUNTS],
        'min_buy': sms.MIN_BUY_TAKA,
        'max_buy': sms.MAX_BUY_TAKA,
        'online_payment_available': online_payment_available(shop),
        'max_chars': sms.MAX_MESSAGE_CHARS,
        'max_numbers': sms.MAX_MANUAL_NUMBERS,
        'auto_sample': sms.order_received_text(shop, sample_order),
        'auto_events': _auto_events(shop),
    })


def _single_label(shop, phone):
    """একজনকে পাঠালে ইতিহাসে নাম আর নম্বর।"""
    name = (Customer.objects.filter(shop=shop, phone__endswith=phone[-10:]).order_by('-id')
            .values_list('name', flat=True).first())
    return f'{name} ({phone})' if name else phone


@login_required(login_url=LOGIN)
@require_POST
def sms_send(request):
    shop = request.user.shop
    if not _can_send(request):
        messages.error(request, 'SMS পাঠানোর অনুমতি নেই। দোকানের মালিককে বলুন।')
        return redirect('dashboard')

    audience = request.POST.get('audience', '')
    raw_message = request.POST.get('message', '')
    numbers_text = request.POST.get('numbers', '')
    sign = request.POST.get('sign') == 'on'

    def fail(text):
        request.session[DRAFT_KEY] = {'audience': audience, 'message': raw_message, 'numbers': numbers_text,
                                      'sign': sign}
        messages.error(request, text)
        return redirect(_panel_url('compose'))

    # একই ফর্ম দুইবার জমা পড়লে (দুইবার চাপ, রিফ্রেশ) দ্বিতীয়বার পাঠানো হয় না
    send_id = (request.POST.get('send_id') or '')[:40]
    sent_ids = request.session.get(SENT_KEY, [])
    if send_id and send_id in sent_ids:
        messages.info(request, 'এই SMS আগেই পাঠানো হয়েছে।')
        return redirect(_panel_url('history'))

    message = sms.clean_message(raw_message)
    if not message:
        return fail('মেসেজ লিখুন।')
    if sign:
        message = f'{message}\n- {shop.name}'

    if audience == 'manual':
        phones, bad = sms.split_phone_text(numbers_text)
        if bad:
            shown = '، '.join(bad[:5]) + (' …' if len(bad) > 5 else '')
            return fail(f'এই নম্বরগুলো ঠিক নেই: {shown} — ঠিক করে আবার পাঠান (কিছু পাঠানো হয়নি)।')
        if not phones:
            return fail('মোবাইল নম্বর দিন, যেমন 01712345678।')
        if len(phones) > sms.MAX_MANUAL_NUMBERS:
            return fail(f'একবারে সর্বোচ্চ {sms.bn_num(sms.MAX_MANUAL_NUMBERS)}টা নম্বর লেখা যায়। '
                        'বেশি হলে "সব কাস্টমার" বেছে নিন।')
        label = _single_label(shop, phones[0]) if len(phones) == 1 else f'{sms.bn_num(len(phones))}টা নম্বর'
    elif audience in sms.AUDIENCE_LABELS:
        phones = sms.audience_phones(shop, audience)
        if not phones:
            return fail(f'"{sms.AUDIENCE_LABELS[audience]}"-এ কোনো কাস্টমার নেই।')
        label = sms.AUDIENCE_LABELS[audience]
    else:
        return fail('কাকে পাঠাবেন বেছে নিন।')

    result = sms.send(shop, phones, message, label, user=request.user)
    if not result.ok:
        return fail(sms.describe(result))
    if send_id:
        request.session[SENT_KEY] = (sent_ids + [send_id])[-20:]
    messages.success(request, sms.describe(result))
    return redirect(_panel_url('history'))


@login_required(login_url=LOGIN)
@require_POST
def sms_buy(request):
    """Edumi-র মতো: যত টাকার খুশি (সর্বনিম্ন ৳৫০) — PayStation-এ টাকা দিলেই সাথে সাথে SMS যোগ হয়।"""
    shop = request.user.shop
    if not _can_manage(request):
        messages.error(request, 'SMS কিনতে দোকানের মালিককে বলুন।')
        return redirect(_panel_url('buy'))
    amount, error = sms.parse_buy_amount(request.POST.get('amount'))
    if error:
        messages.error(request, error)
        return redirect(_panel_url('buy'))
    from .payment_views import start_online_payment
    from .payments import sms_item
    item = sms_item(amount)
    if item is None:
        messages.error(request, 'এই টাকায় কোনো SMS হচ্ছে না, পরিমাণটা দেখে আবার চেষ্টা করুন।')
        return redirect(_panel_url('buy'))
    return start_online_payment(request, shop, item, back='sms_panel')


@login_required(login_url=LOGIN)
@require_POST
def sms_auto(request):
    """ওয়েবসাইটের অর্ডারে কাস্টমারকে অটো SMS — চালু/বন্ধ।"""
    shop = request.user.shop
    if not _can_manage(request):
        messages.error(request, 'এটা বদলাতে দোকানের মালিককে বলুন।')
        return redirect('sms_panel')
    fields = ['is_sms_active', 'sms_on_received', 'sms_on_confirmed', 'sms_on_shipped', 'sms_on_delivered']
    for field in fields:
        setattr(shop, field, request.POST.get(field) == 'on')
    shop.save(update_fields=fields)
    if not shop.is_sms_active:
        messages.success(request, 'কাস্টমারকে অটো SMS বন্ধ করা হয়েছে।')
    else:
        on = [label for key, label, _h, _s in _auto_events(shop) if getattr(shop, key)]
        messages.success(request, ('অটো SMS যাবে: ' + ', '.join(on) + '।') if on
                         else 'অটো SMS চালু, কিন্তু কোনো সময় বাছা নেই — নিচের সুইচগুলো থেকে বেছে নিন।')
    return redirect('sms_panel')


def _auto_events(shop):
    """অটো SMS-এর সুইচগুলো: (ফিল্ড, নাম, কখন যায়, নমুনা)।"""
    from types import SimpleNamespace
    sample = SimpleNamespace(id=1024, customer=SimpleNamespace(name=''), shop=shop)
    return [
        ('sms_on_received', 'অর্ডার পেলে', 'ওয়েবসাইটে কেউ অর্ডার করলেই',
         {'on': shop.sms_on_received, 'text': sms.order_received_text(shop, sample)}),
        ('sms_on_confirmed', 'কনফার্ম করলে', 'অর্ডারের অবস্থা "কনফার্ম" করলে',
         {'on': shop.sms_on_confirmed, 'text': sms.status_text(shop, sample, 'Confirmed')}),
        ('sms_on_shipped', 'কুরিয়ারে দিলে', 'কুরিয়ারে পাঠালে, সাথে অর্ডার ট্র্যাক করার লিংক',
         {'on': shop.sms_on_shipped, 'text': sms.status_text(shop, sample, 'Shipped', f'{shop.slug}.sellpunch.com/t/1024-a1b2c3')}),
        ('sms_on_delivered', 'ডেলিভারি হলে', 'অবস্থা "ডেলিভারি হয়েছে" করলে, ধন্যবাদ জানিয়ে',
         {'on': shop.sms_on_delivered, 'text': sms.status_text(shop, sample, 'Delivered')}),
    ]


@login_required(login_url=LOGIN)
def sms_customer_search(request):
    if not _can_send(request):
        return JsonResponse({'results': []}, status=403)
    return JsonResponse({'results': sms.search_customers(request.user.shop, request.GET.get('q'))})
