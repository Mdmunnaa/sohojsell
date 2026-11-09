# store/shop_payments.py
"""
কাস্টমার দোকানের ওয়েবসাইটে অনলাইনে টাকা দিলে (PayStation)।

- টাকা আসে প্ল্যাটফর্মের PayStation অ্যাকাউন্টে। প্রতিটা পেমেন্ট থেকে STOREFRONT_PAYMENT_FEE_PERCENT
  ফি কেটে বাকিটা সেলারের পাওনা হয়। সেলারকে টাকা পাঠালে ShopPayout-এ লেখা হয়।
- প্ল্যান কেনার পেমেন্টের মতো একই নিয়ম: ব্রাউজার বা IPN-এর কথা বিশ্বাস না করে PayStation-এর সার্ভারে
  যাচাই, এমাউন্ট মেলানো, আর রো লক করে একবারই অর্ডারে যোগ।
"""
import logging
import re
import time
import uuid
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone

from . import paystation
from .models import Order, Shop, ShopPayout, StorefrontPayment

logger = logging.getLogger('store.shop_payments')

INVOICE_RE = re.compile(r'^SF-\d{1,10}-[0-9A-F]{12}$')
AMOUNT_TOLERANCE = Decimal('1.00')
VERIFY_RETRY_WAIT = 2
CALLBACK_VERIFY_TIMEOUT = 8
FAILED_WORDS = ('failed', 'refund', 'cancelled', 'canceled')

# কাস্টমার চেকআউটে যা বেছে নেয়
CHOICE_COD, CHOICE_FULL, CHOICE_ADVANCE = 'cod', 'full', 'advance'


def fee_percent():
    try:
        return Decimal(str(getattr(settings, 'STOREFRONT_PAYMENT_FEE_PERCENT', '2')))
    except Exception:
        return Decimal('2')


def online_available(shop):
    """এই দোকানে কাস্টমার অনলাইনে টাকা দিতে পারবে কিনা (গেটওয়ে চালু, আর sandbox-এ শুধু টেস্ট দোকান)।"""
    from .payments import online_payment_available
    return online_payment_available(shop)


def checkout_choices(shop):
    """
    চেকআউটে কাস্টমারকে কোন কোন অপশন দেখানো হবে, প্রথমটা আগে থেকে বাছাই।
    গেটওয়ে বন্ধ থাকলে সব নিয়মেই শুধু ক্যাশ অন ডেলিভারি, যাতে অর্ডার আসা বন্ধ না হয়।
    """
    if not online_available(shop):
        return [CHOICE_COD]
    rule = shop.payment_rule
    if rule == Shop.PAYMENT_COD_OR_ONLINE:
        return [CHOICE_COD, CHOICE_FULL]
    if rule == Shop.PAYMENT_ADVANCE_DELIVERY:
        return [CHOICE_ADVANCE, CHOICE_FULL]
    if rule == Shop.PAYMENT_ONLINE_ONLY:
        return [CHOICE_FULL]
    return [CHOICE_COD]


def amount_now(choice, total, delivery_charge):
    """এখন অনলাইনে কত দিতে হবে।"""
    if choice == CHOICE_FULL:
        return Decimal(total)
    if choice == CHOICE_ADVANCE:
        return Decimal(delivery_charge)
    return Decimal('0')


def _money(value):
    return Decimal(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def create_payment(shop, order, sf_order, choice, amount):
    percent = fee_percent()
    amount = _money(amount)
    fee = _money(amount * percent / 100)
    return StorefrontPayment.objects.create(
        shop=shop, order=order, sf_order=sf_order,
        kind=StorefrontPayment.KIND_FULL if choice == CHOICE_FULL else StorefrontPayment.KIND_ADVANCE,
        amount=amount, fee_percent=percent, fee_amount=fee, net_amount=amount - fee,
        invoice_number=f'SF-{shop.id}-{uuid.uuid4().hex[:12].upper()}',
        environment=paystation.current_environment(),
    )


def start_gateway(payment, callback_url, customer_name, customer_phone, customer_address):
    """PayStation-এর পেমেন্ট পেইজের লিংক, অথবা {'ok': False, 'error': ...}।"""
    return paystation.initiate_payment(
        invoice_number=payment.invoice_number, amount=payment.amount,
        cust_name=customer_name, cust_phone=customer_phone,
        cust_email=getattr(settings, 'SUPPORT_EMAIL', '') or 'customer@example.com',
        cust_address=customer_address, callback_url=callback_url,
        reference=f'{payment.shop.name} #ORD-{payment.order_id}',
        checkout_items=f'Order #ORD-{payment.order_id}',
    )


def valid_invoice(value):
    value = (value or '').strip()
    return value if INVOICE_RE.match(value) else None


def apply_successful(invoice_number, trx_id=None, attempts=1, timeout=None):
    """
    রিটার্ন: (status, payment, message); status ∈ ok, already, not_found, unverified, failed, amount_mismatch
    """
    from .payments import valid_trx_id
    invoice_number = valid_invoice(invoice_number)
    payment = StorefrontPayment.objects.filter(invoice_number=invoice_number).first() if invoice_number else None
    if payment is None:
        return 'not_found', None, 'এই পেমেন্টের কোনো রেকর্ড পাওয়া যায়নি।'
    if payment.status == StorefrontPayment.STATUS_COMPLETED:
        return 'already', payment, 'পেমেন্ট সম্পন্ন হয়েছে।'
    if payment.environment != paystation.current_environment():
        return 'unverified', payment, 'এই পেমেন্টটা এখন যাচাই করা যাচ্ছে না।'

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
        if paystation.is_successful(verify) or (verify and verify.get('status') in FAILED_WORDS):
            break

    if not paystation.is_successful(verify):
        if verify and verify.get('status') in FAILED_WORDS:
            StorefrontPayment.objects.filter(pk=payment.pk, status=StorefrontPayment.STATUS_PENDING).update(
                status=StorefrontPayment.STATUS_FAILED)
            return 'failed', payment, 'পেমেন্ট সম্পন্ন হয়নি। আবার চেষ্টা করতে পারেন।'
        return 'unverified', payment, ('পেমেন্ট এখনো নিশ্চিত হয়নি। টাকা কেটে থাকলে চিন্তা করবেন না, '
                                       'কয়েক মিনিটের মধ্যে নিজে থেকে নিশ্চিত হবে।')
    return complete(invoice_number, verify['amount'], verify.get('trx_id') or trx_id or '',
                    verify.get('payment_method') or '')


def complete(invoice_number, paid_amount, trx_id, method=''):
    with transaction.atomic():
        payment = StorefrontPayment.objects.select_for_update().filter(invoice_number=invoice_number).first()
        if payment is None:
            return 'not_found', None, 'এই পেমেন্টের কোনো রেকর্ড পাওয়া যায়নি।'
        if payment.status == StorefrontPayment.STATUS_COMPLETED:
            return 'already', payment, 'পেমেন্ট সম্পন্ন হয়েছে।'
        if abs(Decimal(str(paid_amount)) - payment.amount) > AMOUNT_TOLERANCE:
            logger.error('Storefront amount mismatch: %s paid=%s expected=%s', invoice_number, paid_amount,
                         payment.amount)
            return 'amount_mismatch', payment, 'পেমেন্টের পরিমাণ মিলছে না। দোকানের সাথে যোগাযোগ করুন।'

        payment.status = StorefrontPayment.STATUS_COMPLETED
        payment.trx_id = (trx_id or payment.trx_id or '')[:64]
        payment.payment_method = (method or '')[:40]
        payment.completed_at = timezone.now()
        payment.save(update_fields=['status', 'trx_id', 'payment_method', 'completed_at'])

        order = Order.objects.select_for_update().filter(pk=payment.order_id).first()
        if order is not None:
            order.advance_paid = min(order.total_amount, order.advance_paid + payment.amount)
            order.online_payment_status = Order.ONLINE_PAID
            fields = ['advance_paid', 'online_payment_status']
            if order.advance_paid >= order.total_amount:
                order.payment_method = 'Paid'      # কুরিয়ার কিছু তুলবে না
                fields.append('payment_method')
            if order.status == 'Pending':
                order.status = 'Confirmed'
                fields.append('status')
            order.save(update_fields=fields)
    logger.info('Storefront payment completed: %s', invoice_number)
    _notify_customer(payment)
    return 'ok', payment, 'পেমেন্ট সফল হয়েছে, ধন্যবাদ!'


def _notify_customer(payment):
    """অনলাইন অর্ডারের "অর্ডার পেয়েছি" SMS পেমেন্টের পরে যায় (দোকানের SMS ব্যালেন্স থেকে)।"""
    order = payment.order
    shop = payment.shop
    if order is None or not shop.is_sms_active or (shop.sms_balance or 0) <= 0:
        return
    try:
        from .views import _send_sms
        _send_sms(order.customer.phone, f'প্রিয় {order.customer.name}, {shop.name}-এ আপনার ৳{payment.amount:.0f} '
                                        f'পেমেন্ট আর অর্ডার (#ORD-{order.id}) পাওয়া গেছে। ধন্যবাদ!')
        Shop.objects.filter(pk=shop.pk, sms_balance__gt=0).update(sms_balance=F('sms_balance') - 1)
    except Exception:
        logger.exception('Payment SMS failed')


# ---------------------------------------------------------------- সেলারের হিসাব
def balance_summary(shop):
    received = (StorefrontPayment.objects.filter(shop=shop, status=StorefrontPayment.STATUS_COMPLETED)
                .aggregate(gross=Sum('amount'), fee=Sum('fee_amount'), net=Sum('net_amount')))
    paid_out = ShopPayout.objects.filter(shop=shop).aggregate(total=Sum('amount'))['total'] or Decimal('0')
    net = received['net'] or Decimal('0')
    return {
        'gross': received['gross'] or Decimal('0'),
        'fee': received['fee'] or Decimal('0'),
        'net': net,
        'paid_out': paid_out,
        'due': net - paid_out,
    }


def recheck_pending(shop, limit=3):
    """গত দুই দিনের "Pending" পেমেন্ট আবার যাচাই (IPN মিস হলে)। পেইজ যেন ধীর না হয়, তাই কয়েকটাই।"""
    now = timezone.now()
    for payment in StorefrontPayment.objects.filter(shop=shop, status=StorefrontPayment.STATUS_PENDING,
                                                    created_at__lte=now - timedelta(minutes=2),
                                                    created_at__gte=now - timedelta(days=2),
                                                    environment=paystation.current_environment())[:limit]:
        try:
            apply_successful(payment.invoice_number, timeout=4)
        except Exception:
            logger.exception('recheck failed for %s', payment.invoice_number)
