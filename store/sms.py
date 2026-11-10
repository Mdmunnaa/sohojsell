# store/sms.py
"""
দোকানের SMS — এক জায়গায় সব: কয়টা SMS কাটবে, নম্বর ঠিক করা, কাদের পাঠানো হবে, ব্যালেন্স থেকে কাটা,
গেটওয়েতে পাঠানো আর ইতিহাস (SmsLog)। প্যানেলের SMS আর অর্ডারের অটো SMS, দুটোই এখান দিয়ে যায়।

নিয়ম (Edumi-র SMS ব্যবস্থার মতো):
  ১. নম্বর এক রূপে (01XXXXXXXXX) — +880, স্পেস, ড্যাশ, বাংলা অঙ্ক সব চলে; ভুল নম্বর বাদ, একই নম্বর একবার।
  ২. খরচ = মেসেজের ভাগ × প্রাপক। বাংলা (ইউনিকোড) একটা SMS-এ ৭০ অক্ষর, লম্বা হলে প্রতি ভাগে ৬৭;
     শুধু ইংরেজি হলে ১৬০, লম্বা হলে প্রতি ভাগে ১৫৩। আগে প্রতিটা অটো SMS-এ ১টা কাটা হতো, অথচ বাংলা মেসেজ যেতো ২ ভাগে।
  ৩. ব্যালেন্স তালা দিয়ে আগে কাটা (দুইবার চাপলেও মাইনাস হয় না), তারপর পাঠানো; গেটওয়ে যা নেয়নি তার খরচ ফেরত।
  ৪. ব্যালেন্স কম হলে একটাও যায় না।
SellPunch কখনো দোকানের SMS-এর খরচ দেয় না — প্রতিটা SMS দোকানের নিজের ব্যালেন্স থেকে।
"""
import logging
import re
import threading
from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_DOWN, Decimal, InvalidOperation

from django.conf import settings
from django.db import close_old_connections, connection, transaction
from django.db.models import Exists, F, OuterRef, Sum
from django.utils import timezone

logger = logging.getLogger('store.sms')

GATEWAY_URL = 'https://api.smsgateway.com.bd/api/send-message'
GATEWAY_BATCH = 100            # একবারে গেটওয়েতে কতগুলো নম্বর
GATEWAY_TIMEOUT = 20
MAX_MESSAGE_CHARS = 1000       # প্রায় ১৫টা বাংলা SMS — এর বেশি লম্বা মেসেজ ভুল করে পাঠানো ঠেকাতে
MAX_MANUAL_NUMBERS = 500       # হাতে লেখা নম্বর একবারে কতগুলো
STUCK_AFTER = timedelta(minutes=15)

DEFAULT_RATE = Decimal('0.40')
MIN_BUY_TAKA = 50
MAX_BUY_TAKA = 50000

BN_DIGITS = str.maketrans('0123456789', '০১২৩৪৫৬৭৮৯')

# ---------------------------------------------------------------- কয়টা SMS (GSM 03.38)
# শুধু ASCII-র GSM-7 অক্ষর ইংরেজি ধরা হয় — é, £, € পেলে অনেক গেটওয়ে পুরো মেসেজ ইউনিকোডে পাঠায়
GSM7_SAFE = frozenset(
    "@$\n\r_ !\"#%&'()*+,-./0123456789:;<=>?ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")
GSM7_EXT = frozenset("^{}\\[~]|")
SINGLE_GSM7, PART_GSM7 = 160, 153
SINGLE_UNICODE, PART_UNICODE = 70, 67


def bn_num(value):
    return str(value).translate(BN_DIGITS)


def is_gsm7(text):
    return all(ch in GSM7_SAFE or ch in GSM7_EXT for ch in text)


def _units(text, gsm):
    if gsm:
        return [2 if ch in GSM7_EXT else 1 for ch in text]
    return [2 if ord(ch) > 0xFFFF else 1 for ch in text]       # ইমোজি = ২ (UTF-16 জোড়া)


def sms_length(text):
    return sum(_units(text, is_gsm7(text)))


def segments(text):
    """কয়টা SMS হিসেবে যাবে। একটা অক্ষর দুই ভাগে ভাঙে না — ভাগের শেষে জায়গা না থাকলে পরের ভাগে যায়।"""
    if not text:
        return 0
    gsm = is_gsm7(text)
    units = _units(text, gsm)
    single, part = (SINGLE_GSM7, PART_GSM7) if gsm else (SINGLE_UNICODE, PART_UNICODE)
    if sum(units) <= single:
        return 1
    parts, used = 1, 0
    for size in units:
        if used + size > part:
            parts, used = parts + 1, 0
        used += size
    return parts


def clean_message(message):
    return (message or '').replace('\r\n', '\n').replace('\r', '\n').strip()


# ---------------------------------------------------------------- নম্বর
def normalize(value):
    from accounts.forms import normalize_bd_mobile
    return normalize_bd_mobile(value)


def clean_phones(values):
    """নম্বরগুলো এক রূপে, ভুলগুলো বাদ, একই নম্বর একবার — ক্রম ঠিক রেখে।"""
    out, seen = [], set()
    for value in values:
        phone = normalize(value or '')
        if phone and phone not in seen:
            seen.add(phone)
            out.append(phone)
    return out


def split_phone_text(text):
    """
    হাতে লেখা নম্বর → (ঠিক নম্বর, ভুলগুলো)। কমা, সেমিকোলন, নতুন লাইন বা স্ল্যাশে আলাদা; "01711 111111" বা
    "+880 1711-111111"-এর মতো স্পেসসহ একটা নম্বরও চলে, আর স্পেস দিয়ে আলাদা করা কয়েকটা নম্বরও।
    """
    good, bad = [], []
    for part in re.split(r'[,;\n/،]+', text or ''):
        part = part.strip()
        if not part:
            continue
        phone = normalize(part)
        if phone:
            good.append(phone)
            continue
        pieces = part.split()
        cleaned = [normalize(piece) for piece in pieces]
        if len(pieces) > 1 and all(cleaned):
            good.extend(cleaned)
        else:
            bad.append(part)
    return clean_phones(good), bad


# ---------------------------------------------------------------- দাম
def sms_rate():
    from .models import MasterSetting
    rate = MasterSetting.objects.order_by('pk').values_list('sms_rate', flat=True).first()
    return rate if rate and rate > 0 else DEFAULT_RATE


def count_for_amount(amount, rate=None):
    """কত টাকায় কয়টা SMS (ভগ্নাংশ বাদ)।"""
    try:
        amount = Decimal(str(amount))
    except (InvalidOperation, TypeError, ValueError):
        return 0
    rate = rate or sms_rate()
    if amount <= 0 or rate <= 0:
        return 0
    return int((amount / rate).to_integral_value(rounding=ROUND_DOWN))


def parse_buy_amount(value):
    """SMS কেনার টাকা (পূর্ণ সংখ্যা, বাংলা অঙ্কও চলে) → (টাকা, ভুল)।"""
    text = str(value or '').translate(str.maketrans('০১২৩৪৫৬৭৮৯', '0123456789')).replace(',', '').strip()
    if not text.isdigit():
        return None, 'কত টাকার SMS কিনবেন লিখুন (শুধু সংখ্যা)।'
    amount = int(text)
    if amount < MIN_BUY_TAKA:
        return None, f'সর্বনিম্ন ৳{bn_num(MIN_BUY_TAKA)}-এর SMS কিনতে হবে।'
    if amount > MAX_BUY_TAKA:
        return None, f'একবারে সর্বোচ্চ ৳{bn_num(f"{MAX_BUY_TAKA:,}")}-এর SMS কেনা যায়।'
    return amount, ''


MANUAL_REQUEST_NAME = 'SMS Recharge'      # bKash/Nagad-এ পাঠিয়ে জমা দেওয়া SMS কেনার অনুরোধ (PaymentRequest.plan_name)


def approve_manual_request(payment_request):
    """bKash/Nagad-এর SMS অনুরোধ মেনে নেওয়া: এখনকার রেটে SMS যোগ। ফেরত: কয়টা যোগ হলো।"""
    from .models import Shop
    count = count_for_amount(payment_request.amount)
    Shop.objects.filter(pk=payment_request.shop_id).update(sms_balance=F('sms_balance') + count)
    return count


# ---------------------------------------------------------------- কাদের পাঠানো হবে
AUDIENCES = [
    # key, নাম, বিবরণ, আইকন
    ('all', 'সব কাস্টমার', 'যারা কখনো কিনেছেন বা অর্ডার করেছেন', 'bi-people-fill'),
    ('recent', 'গত ৩০ দিনের কাস্টমার', 'নতুন অফার বা কালেকশনের খবর দিন', 'bi-lightning-charge-fill'),
    ('inactive', '৩ মাস কেনেননি', 'বিশেষ ছাড় দিয়ে ফিরিয়ে আনুন', 'bi-hourglass-split'),
    ('due', 'যাদের কাছে বাকি আছে', 'বাকি টাকার কথা মনে করিয়ে দিন', 'bi-wallet2'),
]
AUDIENCE_LABELS = {key: label for key, label, _hint, _icon in AUDIENCES}


def _customers(shop):
    from .models import Customer
    from .pos import WALK_IN_PHONE
    return Customer.objects.filter(shop=shop).exclude(phone=WALK_IN_PHONE)


def audience_phones(shop, key, now=None):
    from .models import Order
    from .pos import NOT_COUNTED
    now = now or timezone.now()
    customers = _customers(shop)
    counted = Order.objects.filter(customer=OuterRef('pk')).exclude(status__in=NOT_COUNTED)
    if key == 'all':
        pass
    elif key == 'recent':
        customers = customers.filter(Exists(counted.filter(created_at__gte=now - timedelta(days=30))))
    elif key == 'inactive':
        customers = customers.filter(Exists(counted)).exclude(Exists(counted.filter(created_at__gte=now - timedelta(days=90))))
    elif key == 'due':
        customers = customers.filter(Exists(counted.filter(source='pos', advance_paid__lt=F('total_amount'))))
    else:
        return []
    return clean_phones(customers.order_by('-id').values_list('phone', flat=True))


def audience_counts(shop):
    return {key: len(audience_phones(shop, key)) for key, *_rest in AUDIENCES}


def search_customers(shop, query, limit=8):
    query = (query or '').strip()
    if len(query) < 2:
        return []
    digits = query.translate(str.maketrans('০১২৩৪৫৬৭৮৯', '0123456789'))
    from django.db.models import Q
    rows = (_customers(shop).filter(Q(name__icontains=query) | Q(phone__icontains=digits))
            .order_by('-id').values_list('name', 'phone')[:limit * 3])
    out, seen = [], set()
    for name, phone in rows:
        phone = normalize(phone)
        if phone and phone not in seen:
            seen.add(phone)
            out.append({'name': name, 'phone': phone})
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------- পাঠানো
@dataclass
class SmsResult:
    ok: bool
    recipients: int = 0
    delivered: int = 0
    failed: int = 0
    charged: int = 0           # ব্যালেন্স থেকে কত কাটা হলো
    needed: int = 0            # ব্যালেন্স কম হলে কত লাগতো
    balance: int = 0           # এখন ব্যালেন্স
    queued: bool = False       # অনেক নম্বর — পেছনে পাঠানো হচ্ছে
    error: str = ''
    log_id: int = 0


def gateway_keys():
    """SMS Gateway BD-র চাবি: আগে environment (SMS_GATEWAY_CLIENT_ID / SMS_GATEWAY_API_KEY), না থাকলে Master Settings।"""
    client_id = getattr(settings, 'SMS_GATEWAY_CLIENT_ID', '')
    api_key = getattr(settings, 'SMS_GATEWAY_API_KEY', '')
    if client_id and api_key:
        return client_id, api_key
    from .models import MasterSetting
    setting = MasterSetting.objects.order_by('pk').first()
    return ((getattr(setting, 'sms_client_id', '') or '').strip(), (getattr(setting, 'sms_api_key', '') or '').strip())


def gateway_ready():
    return all(gateway_keys())


def gateway_send(phones, message):
    """
    SMS Gateway BD-তে non-masking পাঠায় (sender ID ছাড়া), কমা দিয়ে অনেক নম্বর একসাথে। ফেরত (ok, বার্তা):
    True = নিয়েছে, False = নেয়নি (খরচ ফেরত হবে), None = উত্তর আসেনি — হয়তো পাঠিয়েছে, তাই খরচ ফেরত না।
    """
    import requests
    client_id, api_key = gateway_keys()
    if not client_id or not api_key:
        return False, 'SMS সার্ভিস এখনো চালু হয়নি, সাপোর্টে জানান'
    payload = {'client_id': client_id, 'key': api_key, 'recipient': ','.join(phones), 'message': message}
    try:
        response = requests.post(GATEWAY_URL, json=payload, timeout=GATEWAY_TIMEOUT,
                                 headers={'Content-Type': 'application/json', 'Accept': 'application/json'})
    except requests.exceptions.ReadTimeout:
        return None, 'গেটওয়ে সময়মতো উত্তর দেয়নি'
    except requests.RequestException as exc:
        return False, f'গেটওয়েতে যাওয়া যায়নি ({exc.__class__.__name__})'
    try:
        data = response.json()
    except ValueError:
        return False, f'গেটওয়ের উত্তর বোঝা যায়নি (HTTP {response.status_code})'
    if data.get('response_code') == 200:
        return True, str(data.get('message') or 'sent')
    return False, str(data.get('message') or data.get('error') or 'গেটওয়ে মেসেজ নেয়নি')[:150]


def _background_allowed():
    return getattr(settings, 'SMS_BACKGROUND', True)


def send(shop, phones, message, audience, *, user=None, kind='manual', sender=None, background=None):
    """
    দোকানের ব্যালেন্স থেকে কেটে SMS পাঠায়। phones — যেকোনো রূপের নম্বর (এখানেই ঠিক করা হয়)।
    sender(phones, message) -> (ok, বার্তা); না দিলে gateway_send। ১০০-র বেশি নম্বর হলে পেছনে (thread) পাঠানো হয়,
    যাতে পেইজ আটকে না থাকে; ইতিহাসে "পাঠানো হচ্ছে" দেখায়।
    """
    from .models import Shop, SmsLog
    message = clean_message(message)
    if not message:
        return SmsResult(False, error='মেসেজ লিখুন।')
    if len(message) > MAX_MESSAGE_CHARS:
        return SmsResult(False, error=f'মেসেজ অনেক লম্বা ({bn_num(len(message))} অক্ষর) — '
                                      f'{bn_num(MAX_MESSAGE_CHARS)} অক্ষরের মধ্যে রাখুন।')
    phones = clean_phones(phones)
    if not phones:
        return SmsResult(False, error='পাঠানোর মতো কোনো সঠিক মোবাইল নম্বর পাওয়া যায়নি।')
    per_person = segments(message)
    total = per_person * len(phones)

    with transaction.atomic():
        balance = Shop.objects.select_for_update().values_list('sms_balance', flat=True).get(pk=shop.pk) or 0
        if balance < total:
            return SmsResult(False, recipients=len(phones), needed=total, balance=balance,
                             error=f'SMS ব্যালেন্স কম — লাগবে {bn_num(total)}টা, আছে {bn_num(balance)}টা। '
                                   'SMS কিনে আবার পাঠান (কিছু পাঠানো হয়নি)।')
        Shop.objects.filter(pk=shop.pk).update(sms_balance=F('sms_balance') - total)
        log = SmsLog.objects.create(
            shop=shop, kind=kind, audience=str(audience)[:120], message=message, recipients=len(phones),
            sms_used=total, status=SmsLog.SENDING, sent_by=user if getattr(user, 'pk', None) else None)

    if background is None:
        background = len(phones) > GATEWAY_BATCH and _background_allowed()
    if background:
        threading.Thread(target=_deliver_in_background, args=(log.pk, phones, message, per_person, sender),
                         daemon=True).start()
        return SmsResult(True, recipients=len(phones), charged=total, queued=True, log_id=log.pk,
                         balance=balance - total)
    return _deliver(log.pk, phones, message, per_person, sender)


def _deliver_in_background(log_id, phones, message, per_person, sender):
    close_old_connections()
    try:
        _deliver(log_id, phones, message, per_person, sender)
    except Exception:
        logger.exception('Background SMS failed (log=%s)', log_id)
    finally:
        connection.close()


def _deliver(log_id, phones, message, per_person, sender=None):
    from .models import Shop, SmsLog
    log = SmsLog.objects.get(pk=log_id)
    send_batch = sender or gateway_send
    delivered, last_error, unsure = 0, '', False
    for start in range(0, len(phones), GATEWAY_BATCH):
        batch = phones[start:start + GATEWAY_BATCH]
        try:
            ok, msg = send_batch(batch, message)
        except Exception as exc:     # গেটওয়ের যেকোনো সমস্যায় টাকা যেন আটকে না থাকে
            logger.exception('SMS gateway error (shop=%s)', log.shop_id)
            ok, msg = False, str(exc)[:150]
        if ok is None:
            unsure, ok = True, True
            logger.warning('SMS gateway answer unclear, counted as sent (shop=%s): %s', log.shop_id, msg)
        if ok:
            delivered += len(batch)
        else:
            last_error = msg or 'গেটওয়ে মেসেজ নেয়নি'

    failed = len(phones) - delivered
    refund = per_person * failed
    if refund:
        Shop.objects.filter(pk=log.shop_id).update(sms_balance=F('sms_balance') + refund)
    status = SmsLog.SENT if not failed else (SmsLog.FAILED if not delivered else SmsLog.PARTIAL)
    note = last_error if failed else ''
    if unsure:
        note = (note + ' · ' if note else '') + 'গেটওয়ে দেরিতে উত্তর দিয়েছে, SMS সম্ভবত গেছে'
    SmsLog.objects.filter(pk=log.pk).update(delivered=delivered, failed=failed, sms_used=log.sms_used - refund,
                                            status=status, error=note[:255])
    balance = Shop.objects.filter(pk=log.shop_id).values_list('sms_balance', flat=True).first() or 0
    if not delivered:
        return SmsResult(False, recipients=len(phones), failed=failed, balance=balance, log_id=log.pk,
                         error=f'SMS পাঠানো যায়নি ({last_error}) — ব্যালেন্স থেকে কিছু কাটা হয়নি।')
    return SmsResult(True, recipients=len(phones), delivered=delivered, failed=failed, charged=log.sms_used - refund,
                     balance=balance, log_id=log.pk, error=note)


def send_each(shop, pairs, audience, *, user=None, kind='manual', sender=None):
    """
    প্রতিজনকে আলাদা লেখা (যেমন বাকির তাগাদা: নাম আর টাকার অঙ্ক সহ)। pairs = [(phone, message), ...]।
    একটাই SmsLog, খরচ আগে কাটে, যেগুলো যায়নি সেগুলোর খরচ ফেরত।
    """
    from .models import Shop, SmsLog
    cleaned = []
    for phone, message in pairs:
        phones = clean_phones([phone])
        message = clean_message(message)
        if phones and message and len(message) <= MAX_MESSAGE_CHARS:
            cleaned.append((phones[0], message, segments(message)))
    if not cleaned:
        return SmsResult(False, error='পাঠানোর মতো কোনো সঠিক মোবাইল নম্বর পাওয়া যায়নি।')
    total = sum(units for _p, _m, units in cleaned)
    with transaction.atomic():
        balance = Shop.objects.select_for_update().values_list('sms_balance', flat=True).get(pk=shop.pk) or 0
        if balance < total:
            return SmsResult(False, recipients=len(cleaned), needed=total, balance=balance,
                             error=f'SMS ব্যালেন্স কম — লাগবে {bn_num(total)}টা, আছে {bn_num(balance)}টা। '
                                   'SMS কিনে আবার পাঠান (কিছু পাঠানো হয়নি)।')
        Shop.objects.filter(pk=shop.pk).update(sms_balance=F('sms_balance') - total)
        log = SmsLog.objects.create(
            shop=shop, kind=kind, audience=str(audience)[:120], message=cleaned[0][1], recipients=len(cleaned),
            sms_used=total, status=SmsLog.SENDING, sent_by=user if getattr(user, 'pk', None) else None)
    send_one = sender or gateway_send
    delivered, refund, last_error = 0, 0, ''
    for phone, message, units in cleaned:
        try:
            ok, msg = send_one([phone], message)
        except Exception as exc:     # noqa: BLE001
            logger.exception('SMS gateway error (shop=%s)', shop.pk)
            ok, msg = False, str(exc)[:150]
        if ok or ok is None:
            delivered += 1
        else:
            refund += units
            last_error = msg or 'গেটওয়ে মেসেজ নেয়নি'
    failed = len(cleaned) - delivered
    if refund:
        Shop.objects.filter(pk=shop.pk).update(sms_balance=F('sms_balance') + refund)
    status = SmsLog.SENT if not failed else (SmsLog.FAILED if not delivered else SmsLog.PARTIAL)
    SmsLog.objects.filter(pk=log.pk).update(delivered=delivered, failed=failed, sms_used=total - refund,
                                            status=status, error=(last_error if failed else '')[:255])
    balance = Shop.objects.filter(pk=shop.pk).values_list('sms_balance', flat=True).first() or 0
    if not delivered:
        return SmsResult(False, recipients=len(cleaned), failed=failed, balance=balance, log_id=log.pk,
                         error=f'SMS পাঠানো যায়নি ({last_error}) — ব্যালেন্স থেকে কিছু কাটা হয়নি।')
    return SmsResult(True, recipients=len(cleaned), delivered=delivered, failed=failed, charged=total - refund,
                     balance=balance, log_id=log.pk)


def due_reminder_text(shop, name, due):
    """বাকির তাগাদা, সম্ভব হলে ১টা SMS-এ।"""
    amount = f'৳{bn_num(f"{due:,.0f}")}'
    first = _first_name(name)
    options = []
    if first:
        options += [f'{first}, {shop.name}-এ আপনার বাকি আছে {amount}। সুবিধামতো পরিশোধ করে দেবেন। ধন্যবাদ।',
                    f'{first}, {shop.name}-এ আপনার বাকি {amount}। পরিশোধ করে দেবেন। ধন্যবাদ।']
    options += [f'{shop.name}-এ আপনার বাকি {amount}। পরিশোধ করে দেবেন। ধন্যবাদ।',
                f'আপনার বাকি {amount}। - {shop.name}']
    return _first_fitting(options)


def describe(result):
    """প্যানেলে দেখানোর জন্য এক লাইন।"""
    if not result.ok:
        return result.error
    if result.queued:
        return (f'{bn_num(result.recipients)} জনকে SMS পাঠানো শুরু হয়েছে ({bn_num(result.charged)}টা SMS কাটা হয়েছে)। '
                'নিচের ইতিহাসে কয়েক মিনিটের মধ্যে ফলাফল দেখাবে।')
    text = (f'{bn_num(result.delivered)} জনকে SMS পাঠানো হয়েছে — {bn_num(result.charged)}টা SMS কাটা হয়েছে, '
            f'বাকি আছে {bn_num(result.balance)}টা।')
    if result.failed:
        text += f' {bn_num(result.failed)}টা নম্বরে যায়নি, সেগুলোর খরচ ফেরত দেওয়া হয়েছে।'
    return text


def expire_stuck(shop):
    """সার্ভার মাঝপথে বন্ধ হলে "পাঠানো হচ্ছে" আটকে থাকে — ১৫ মিনিট পর "অবস্থা জানা যায়নি" (খরচ ফেরত না, হয়তো গেছে)।"""
    from .models import SmsLog
    SmsLog.objects.filter(shop=shop, status=SmsLog.SENDING, created_at__lt=timezone.now() - STUCK_AFTER).update(
        status=SmsLog.UNKNOWN, error='পাঠানোর মাঝপথে সার্ভার থেমে গিয়েছিল, কতজন পেয়েছে জানা যায়নি')


def used_this_month(shop):
    from .models import SmsLog
    start = timezone.localtime().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return SmsLog.objects.filter(shop=shop, created_at__gte=start).aggregate(n=Sum('sms_used'))['n'] or 0


def notify(phone, message):
    """প্ল্যাটফর্মের নিজের SMS (সেলারকে খবর, আপনাকে খবর) — কোনো দোকানের ব্যালেন্স কাটে না, পেছনে যায়।"""
    def run():
        try:
            gateway_send([phone], message)
        except Exception:
            logger.exception('Platform SMS failed')
        finally:
            if threaded:
                connection.close()
    threaded = _background_allowed()
    if threaded:
        threading.Thread(target=run, daemon=True).start()
    else:
        run()


# ---------------------------------------------------------------- অটো SMS (অর্ডার, পেমেন্ট)
def _first_fitting(options):
    """যে লেখাটা ১টা SMS-এ ধরে সেটা; কোনোটাই না ধরলে শেষেরটা (খরচ ঠিকঠাক কাটা হয়)।"""
    for text in options:
        if segments(text) == 1:
            return text
    return options[-1]


def _first_name(name):
    name = ' '.join((name or '').split())
    return name.split(' ')[0] if name else ''


def order_received_text(shop, order):
    number = bn_num(order.id)
    name = _first_name(order.customer.name)
    options = [f'আপনার অর্ডার নং {number} পেয়েছি, শীঘ্রই যোগাযোগ করব। - {shop.name}',
               f'অর্ডার নং {number} পেয়েছি, শীঘ্রই যোগাযোগ করব। - {shop.name}']
    if name:
        options.insert(0, f'প্রিয় {name}, আপনার অর্ডার নং {number} পেয়েছি, শীঘ্রই যোগাযোগ করব। - {shop.name}')
    return _first_fitting(options)


def payment_received_text(shop, order, amount):
    taka = bn_num(f'{Decimal(amount):,.0f}')
    number = bn_num(order.id)
    return _first_fitting([f'৳{taka} পেমেন্ট আর অর্ডার নং {number} পেয়েছি। ধন্যবাদ! - {shop.name}',
                           f'৳{taka} পেমেন্ট ও অর্ডার {number} পেয়েছি - {shop.name}'])


def status_text(shop, order, status, link=None):
    """অর্ডারের অবস্থা বদলালে কাস্টমারকে যা যায় (কনফার্ম / কুরিয়ারে / ডেলিভারি)। সম্ভব হলে ১টা SMS-এ।"""
    number = bn_num(order.id)
    if status == 'Confirmed':
        return _first_fitting([f'আপনার অর্ডার নং {number} কনফার্ম হয়েছে, শীঘ্রই পাঠানো হবে। - {shop.name}',
                               f'অর্ডার নং {number} কনফার্ম হয়েছে। - {shop.name}'])
    if status == 'Shipped':
        options = [f'অর্ডার নং {number} কুরিয়ারে দেওয়া হয়েছে। - {shop.name}']
        if link:
            options = [f'অর্ডার {number} কুরিয়ারে দেওয়া হয়েছে। দেখুন: {link}',
                       f'অর্ডার {number} কুরিয়ারে গেছে: {link}'] + options
        return _first_fitting(options)
    if status == 'Delivered':
        return _first_fitting([f'অর্ডার নং {number} ডেলিভারি হয়েছে। আমাদের সাথে থাকার জন্য ধন্যবাদ! - {shop.name}',
                               f'অর্ডার নং {number} ডেলিভারি হয়েছে। ধন্যবাদ! - {shop.name}'])
    return ''


def send_auto(shop, phone, message, audience):
    """অর্ডারের অটো SMS: চালু থাকলে আর ব্যালেন্স থাকলে যায়; কোনো সমস্যায় অর্ডার আটকায় না।"""
    if not shop.is_sms_active:
        return None
    try:
        return send(shop, [phone], message, audience, kind='auto',
                    background=_background_allowed())
    except Exception:
        logger.exception('Auto SMS failed (shop=%s)', shop.pk)
        return None
