# store/payments.py
"""
অনলাইন পেমেন্টের ব্যবসায়িক নিয়ম: কোন প্যাকেজের দাম কত, পেমেন্ট সফল হলে শপে কী যোগ হবে,
আর একই পেমেন্ট যেন কখনো দুইবার যোগ না হয়।

callback (ব্রাউজার) আর IPN (PayStation সার্ভার) — দুই পথই apply_successful_payment() ডাকে।
এটা সবসময় PayStation-এ যাচাই করে, এমাউন্ট মেলায়, আর ডেটাবেস রো লক করে একবারই যোগ করে।
"""

import logging
import re
import time
import uuid
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import paystation
from .models import OnlinePayment, Shop

logger = logging.getLogger('store.payments')

# দাম শুধু সার্ভারে — billing পেইজের বাটন শুধু প্যাকেজের নাম পাঠায়, টাকার অঙ্ক নয়
PLAN_PRICES = {
    'Basic': Decimal('499'),
    'Standard': Decimal('999'),
    'Premium': Decimal('1999'),
}
PLAN_DAYS = 30

# কোড: (দাম, কতটা SMS) — ০.৪০ টাকা প্রতি SMS
SMS_PACKS = {
    'SMS-500': (Decimal('200'), 500),
    'SMS-1000': (Decimal('400'), 1000),
}

INVOICE_RE = re.compile(r'^SS-\d{1,10}-[0-9A-F]{12}$')
TRX_ID_RE = re.compile(r'^[A-Za-z0-9_-]{4,40}$')
VERIFY_RETRY_WAIT = 2          # টাকা দেওয়ার ঠিক পরপর PayStation অনেক সময় "processing" দেখায়
CALLBACK_VERIFY_TIMEOUT = 8    # ব্রাউজার অপেক্ষা করছে, তাই প্রতিটা জিজ্ঞাসা বেশিক্ষণ ঝুলবে না
AMOUNT_TOLERANCE = Decimal('1.00')


def resolve_item(code):
    """billing পেইজ থেকে আসা কোড (যেমন 'Standard' বা 'SMS-500') থেকে কী কেনা হচ্ছে আর দাম কত।"""
    code = (code or '').strip()
    if code in PLAN_PRICES:
        return {
            'kind': OnlinePayment.KIND_PLAN, 'plan_name': code, 'amount': PLAN_PRICES[code],
            'days': PLAN_DAYS, 'sms_count': 0, 'label': f'{settings.SITE_NAME} {code} Plan (30 days)',
        }
    if code in SMS_PACKS:
        amount, count = SMS_PACKS[code]
        return {
            'kind': OnlinePayment.KIND_SMS, 'plan_name': f'SMS Recharge ({count})', 'amount': amount,
            'days': 0, 'sms_count': count, 'label': f'{count} SMS',
        }
    return None


def online_payment_available(shop):
    """
    অনলাইন পেমেন্ট বাটন দেখাবে কিনা।
    live হলে সবার জন্য। sandbox (টেস্ট) হলে শুধু লোকাল ডেভেলপমেন্টে আর PAYSTATION_TEST_SHOPS-এ
    থাকা শপের জন্য — যাতে টেস্ট মোডে কোনো আসল সেলার বিনা টাকায় প্ল্যান চালু করতে না পারে।
    """
    if not paystation.is_configured() or shop is None:
        return False
    if paystation.current_environment() == 'live':
        return True
    return bool(settings.DEBUG or shop.slug in settings.PAYSTATION_TEST_SHOPS)


def new_invoice_number(shop):
    return f'SS-{shop.id}-{uuid.uuid4().hex[:12].upper()}'


def valid_invoice(value):
    value = (value or '').strip()
    return value if INVOICE_RE.match(value) else None


def valid_trx_id(value):
    value = (value or '').strip()
    return value if TRX_ID_RE.match(value) else None


def remember_claimed_trx(invoice_number, trx_id):
    """callback-এ আসা লেনদেন নম্বর মনে রাখা — পরে v2 দিয়ে আবার যাচাই করতে কাজে লাগে (বিশ্বাস করা হয় না)।"""
    trx_id = valid_trx_id(trx_id)
    if not trx_id:
        return
    OnlinePayment.objects.filter(
        invoice_number=invoice_number, status=OnlinePayment.STATUS_PENDING, trx_id=''
    ).update(trx_id=trx_id)


def apply_successful_payment(invoice_number, trx_id=None, attempts=1, timeout=None):
    """
    পেমেন্ট "Completed" করার একমাত্র জায়গা।

    ১. আগে নিজের ডেটাবেস দেখা — রেকর্ড না থাকলে বা আগেই Completed হলে PayStation-এ যাওয়াই হয় না
    ২. PayStation-এর সার্ভারে যাচাই (ডেটাবেস লকের বাইরে, যাতে ধীর গেটওয়েতে কানেকশন আটকে না থাকে)
    ৩. complete_payment()-এ রো লক, এমাউন্ট মেলানো, আর একবারই শপে যোগ

    রিটার্ন: (status, payment, message)
      status ∈ {'ok', 'already', 'not_found', 'unverified', 'failed', 'amount_mismatch'}
    """
    invoice_number = valid_invoice(invoice_number)
    payment = OnlinePayment.objects.filter(invoice_number=invoice_number).first() if invoice_number else None
    if payment is None:
        return 'not_found', None, 'এই পেমেন্টের কোনো রেকর্ড পাওয়া যায়নি।'
    if payment.status == OnlinePayment.STATUS_COMPLETED:
        return 'already', payment, 'এই পেমেন্ট আগেই সম্পন্ন হয়েছে।'
    if payment.environment != paystation.current_environment():
        # sandbox-এর পেমেন্ট live-এ (বা উল্টো) যাচাই করা যায় না
        return 'unverified', payment, 'এই পেমেন্টটা অন্য মোডের (sandbox/live), এখন যাচাই করা যাচ্ছে না।'

    timeout = timeout or paystation.TIMEOUT
    trx_id = valid_trx_id(trx_id) or valid_trx_id(payment.trx_id)
    verify = None
    for attempt in range(max(1, attempts)):
        if attempt:
            time.sleep(VERIFY_RETRY_WAIT)
        verify = paystation.verify_transaction(invoice_number, timeout=timeout)
        if not paystation.is_successful(verify) and trx_id:
            by_trx = paystation.verify_by_trx_id(trx_id, invoice_number, timeout=timeout)
            if paystation.is_successful(by_trx) or verify is None:
                verify = by_trx or verify
        if paystation.is_successful(verify) or (verify and verify.get('status') in ('failed', 'refund', 'cancelled', 'canceled')):
            break

    if not paystation.is_successful(verify):
        if verify and verify.get('status') in ('failed', 'refund', 'cancelled', 'canceled'):
            OnlinePayment.objects.filter(pk=payment.pk, status=OnlinePayment.STATUS_PENDING).update(
                status=OnlinePayment.STATUS_FAILED)
            return 'failed', payment, 'পেমেন্ট সম্পন্ন হয়নি (বাতিল বা ব্যর্থ)। চাইলে আবার চেষ্টা করুন।'
        logger.warning('PayStation যাচাই হয়নি: invoice=%s trx=%s result=%s', invoice_number, trx_id, verify)
        return 'unverified', payment, ('পেমেন্টটা PayStation থেকে এখনো নিশ্চিত হয়নি। টাকা কেটে থাকলে চিন্তা করবেন না: '
                                       'কয়েক মিনিট পর Billing পেইজটা আবার খুললে নিজে থেকে আবার যাচাই হবে।')

    return complete_payment(invoice_number, verify['amount'], verify.get('trx_id') or trx_id or '',
                            verify.get('payment_method') or '')


def complete_payment(invoice_number, paid_amount, trx_id, method=''):
    """এক transaction-এ, রো লক করে — callback আর IPN একসাথে এলেও শপে একবারই যোগ হয়।"""
    with transaction.atomic():
        payment = OnlinePayment.objects.select_for_update().filter(invoice_number=invoice_number).first()
        if payment is None:
            return 'not_found', None, 'এই পেমেন্টের কোনো রেকর্ড পাওয়া যায়নি।'
        if payment.status == OnlinePayment.STATUS_COMPLETED:
            return 'already', payment, 'এই পেমেন্ট আগেই সম্পন্ন হয়েছে।'

        if abs(Decimal(str(paid_amount)) - payment.amount) > AMOUNT_TOLERANCE:
            logger.error('Amount mismatch: invoice=%s paid=%s expected=%s', invoice_number, paid_amount, payment.amount)
            return 'amount_mismatch', payment, 'পেমেন্টের পরিমাণ মিলছে না। লেনদেন নম্বরসহ সাপোর্টে যোগাযোগ করুন।'

        shop = Shop.objects.select_for_update().get(pk=payment.shop_id)
        if payment.kind == OnlinePayment.KIND_PLAN:
            today = timezone.localdate()
            start = shop.valid_until if shop.valid_until and shop.valid_until >= today else today
            shop.valid_until = start + timedelta(days=payment.days)
            shop.subscription_plan = payment.plan_name
            shop.is_locked = False
            shop.is_paid = True
            shop.save(update_fields=['valid_until', 'subscription_plan', 'is_locked', 'is_paid'])
            message = f'পেমেন্ট সফল! {payment.plan_name} প্ল্যান চালু হয়েছে, মেয়াদ {shop.valid_until:%d-%m-%Y} পর্যন্ত।'
        else:
            shop.sms_balance = (shop.sms_balance or 0) + payment.sms_count
            shop.save(update_fields=['sms_balance'])
            message = f'পেমেন্ট সফল! {payment.sms_count}টি SMS আপনার ব্যালেন্সে যোগ হয়েছে।'

        payment.status = OnlinePayment.STATUS_COMPLETED
        payment.trx_id = (trx_id or payment.trx_id or '')[:64]
        payment.payment_method = (method or '')[:40]
        payment.completed_at = timezone.now()
        payment.save(update_fields=['status', 'trx_id', 'payment_method', 'completed_at'])

    logger.info('Online payment completed: %s (%s)', invoice_number, payment.plan_name)
    return 'ok', payment, message


def recheck_pending(shop, limit=2, timeout=4):
    """
    Billing পেইজ খুললে এই শপের ঝুলে থাকা পেমেন্ট আবার যাচাই — callback হারিয়ে গেলে (ব্রাউজার বন্ধ,
    নেট চলে যাওয়া) আর IPN না এলেও টাকা কাটা পেমেন্ট হারায় না। রিটার্ন: সম্পন্ন হওয়া পেমেন্টের তালিকা।
    """
    now = timezone.now()
    pending = shop.online_payments.filter(
        status=OnlinePayment.STATUS_PENDING,
        environment=paystation.current_environment(),
        created_at__lte=now - timedelta(seconds=30),
        created_at__gte=now - timedelta(hours=48),
    ).order_by('-created_at')[:limit]
    completed = []
    for payment in pending:
        status, obj, _msg = apply_successful_payment(payment.invoice_number, timeout=timeout)
        if status == 'ok':
            completed.append(obj)
    return completed
