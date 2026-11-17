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
from django.db.models import Sum
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
        return Decimal(str(getattr(settings, 'STOREFRONT_PAYMENT_FEE_PERCENT', '2.5')))
    except Exception:
        return Decimal('2.5')


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
    if order is None:
        return
    from . import sms
    sms.send_auto(shop, order.customer.phone, sms.payment_received_text(shop, order, payment.amount),
                  f'অর্ডার নং {sms.bn_num(order.id)} (পেমেন্ট)')


# ---------------------------------------------------------------- সেলারের হিসাব ও টাকা তোলা
# কাস্টমারের প্রতিটা পেমেন্টের ৭ দিন পর সেই টাকা তোলা যায় (ফেরত/ঝামেলা মেটানোর সময়), কমপক্ষে ৳৫,০০০ জমলে অনুরোধ।
SETTLEMENT_MIN = Decimal('5000')
SETTLEMENT_HOLD_DAYS = 7
ZERO = Decimal('0')


def _completed(shop):
    return StorefrontPayment.objects.filter(shop=shop, status=StorefrontPayment.STATUS_COMPLETED)


def _released_filter(cutoff):
    from django.db.models import Q
    return Q(completed_at__lte=cutoff) | Q(completed_at__isnull=True, created_at__lte=cutoff)


def balance_summary(shop, now=None):
    """
    gross/fee/net: কাস্টমার যা দিয়েছে, ফি, সেলারের অংশ। paid_out: পাঠানো। due: মোট পাওনা।
    available: এখন তোলা যাবে (৭ দিন পার হওয়া টাকা − পাঠানো − যাচাইয়ে থাকা অনুরোধ)। holding: ৭ দিনের অপেক্ষায়।
    """
    from .models import SettlementRequest
    now = now or timezone.now()
    cutoff = now - timedelta(days=SETTLEMENT_HOLD_DAYS)
    completed = _completed(shop)
    received = completed.aggregate(gross=Sum('amount'), fee=Sum('fee_amount'), net=Sum('net_amount'))
    released = completed.filter(_released_filter(cutoff)).aggregate(net=Sum('net_amount'))['net'] or ZERO
    paid_out = ShopPayout.objects.filter(shop=shop).aggregate(total=Sum('amount'))['total'] or ZERO
    open_request = SettlementRequest.objects.filter(shop=shop, status=SettlementRequest.PENDING).first()
    requested = open_request.amount if open_request else ZERO
    net = received['net'] or ZERO
    refunds = platform_refunds(shop)            # কাস্টমারকে ফেরত (SellPunch থেকে) — আগে তোলা যাবে থেকে, না কুলালে অপেক্ষার থেকে
    free = released - paid_out - requested
    available = max(free - refunds, ZERO)
    holding = max(max(net - max(released, paid_out), ZERO) - max(refunds - max(free, ZERO), ZERO), ZERO)
    upcoming = completed.exclude(_released_filter(cutoff)).order_by('completed_at').first()
    next_release = (timezone.localtime(upcoming.completed_at or upcoming.created_at)
                    + timedelta(days=SETTLEMENT_HOLD_DAYS)).date() if upcoming else None
    return {
        'gross': received['gross'] or ZERO,
        'fee': received['fee'] or ZERO,
        'net': net,
        'paid_out': paid_out,
        'refunds': refunds,
        'due': net - paid_out - refunds,
        'available': available,
        'holding': holding,
        'requested': requested,
        'open_request': open_request,
        'next_release': next_release,
        'next_release_label': _bn_date(next_release) if next_release else '',
        'min': SETTLEMENT_MIN,
        'hold_days': SETTLEMENT_HOLD_DAYS,
        'short': max(SETTLEMENT_MIN - available, ZERO),
        'progress': min(int(available * 100 / SETTLEMENT_MIN), 100) if SETTLEMENT_MIN else 100,
        'can_request': available >= SETTLEMENT_MIN and open_request is None and bool(shop.payout_account),
    }


class SettlementError(Exception):
    pass


def request_settlement(shop, amount, user=None):
    """সেলারের টাকা তোলার অনুরোধ। একবারে একটাই খোলা অনুরোধ; টাকা ৳৫,০০০ থেকে "এখন তোলা যাবে"-এর মধ্যে।"""
    from .models import SettlementRequest
    with transaction.atomic():
        shop = Shop.objects.select_for_update().get(pk=shop.pk)
        if not (shop.payout_method and shop.payout_account):
            raise SettlementError('আগে ওয়েবসাইট → পেমেন্ট ট্যাবে টাকা নেওয়ার মাধ্যম আর নম্বর দিয়ে সেভ করুন।')
        summary = balance_summary(shop)
        if summary['open_request']:
            raise SettlementError('আগের অনুরোধটা এখনো যাচাই হচ্ছে। সেটা হয়ে গেলে আবার অনুরোধ দিন।')
        try:
            amount = Decimal(str(amount).replace(',', '')).quantize(Decimal('1'))
        except (ArithmeticError, ValueError):
            raise SettlementError('কত টাকা তুলবেন লিখুন।')
        if summary['available'] < SETTLEMENT_MIN:
            raise SettlementError(f'কমপক্ষে ৳{SETTLEMENT_MIN:,.0f} জমলে টাকা তোলা যায়। এখন তোলা যাবে ৳{summary["available"]:,.0f}।')
        if amount < SETTLEMENT_MIN or amount > summary['available']:
            raise SettlementError(f'৳{SETTLEMENT_MIN:,.0f} থেকে ৳{summary["available"]:,.0f}-এর মধ্যে লিখুন।')
        return SettlementRequest.objects.create(
            shop=shop, amount=amount, method=shop.payout_method, account=shop.payout_account,
            account_name=shop.payout_account_name, requested_by=user if getattr(user, 'pk', None) else None)


def cancel_settlement(shop, request_id):
    from .models import SettlementRequest
    return SettlementRequest.objects.filter(pk=request_id, shop=shop, status=SettlementRequest.PENDING).update(
        status=SettlementRequest.CANCELLED, decided_at=timezone.now())


def pay_settlement(request_id, reference, user=None):
    """মাস্টার টাকা পাঠিয়েছেন: ShopPayout লেখা, অনুরোধ "পাঠানো হয়েছে"। ফেরত: অনুরোধ।"""
    from .models import SettlementRequest
    reference = (reference or '').strip()[:100]
    if not reference:
        raise SettlementError('লেনদেন নম্বর (TrxID) দিন।')
    with transaction.atomic():
        req = SettlementRequest.objects.select_for_update().select_related('shop').filter(pk=request_id).first()
        if req is None or req.status != SettlementRequest.PENDING:
            raise SettlementError('অনুরোধটা আর খোলা নেই।')
        payout = ShopPayout.objects.create(shop=req.shop, amount=req.amount, method=req.method, account=req.account,
                                           reference=reference, note='টাকা তোলার অনুরোধ থেকে',
                                           created_by=user if getattr(user, 'pk', None) else None)
        req.status, req.payout, req.decided_at = SettlementRequest.PAID, payout, timezone.now()
        req.save(update_fields=['status', 'payout', 'decided_at'])
    _notify_seller(req.shop, f'{settings.SITE_NAME}: ৳{_bn(f"{req.amount:,.0f}")} পাঠানো হয়েছে ({req.method}), '
                             f'TrxID {reference}')
    return req


def reject_settlement(request_id, reason):
    """অনুরোধ ফেরত (কারণসহ); সেলার SMS পায়, টাকা আবার "এখন তোলা যাবে"-তে ফেরে।"""
    from .models import SettlementRequest
    reason = (reason or '').strip()[:200] or 'অ্যাকাউন্টের তথ্য মেলেনি'
    req = SettlementRequest.objects.select_related('shop').filter(pk=request_id, status=SettlementRequest.PENDING).first()
    if req is None:
        return 0
    updated = SettlementRequest.objects.filter(pk=req.pk, status=SettlementRequest.PENDING).update(
        status=SettlementRequest.REJECTED, note=reason, decided_at=timezone.now())
    if updated:
        _notify_seller(req.shop, f'{settings.SITE_NAME}: ৳{_bn(f"{req.amount:,.0f}")} তোলার অনুরোধ ফেরত দেওয়া হয়েছে — '
                                 f'{reason}। ঠিক করে আবার অনুরোধ দিন।')
    return updated


def _bn_date(day):
    from .dashboard import bn_date
    return bn_date(day, weekday=False)


def _bn(text):
    return str(text).translate(str.maketrans('0123456789', '০১২৩৪৫৬৭৮৯'))


def _notify_seller(shop, text):
    """প্ল্যাটফর্মের খরচে সেলারকে SMS (দোকানের ব্যালেন্স থেকে না)। কোনো সমস্যায় কাজ আটকায় না।"""
    from . import sms
    phone = sms.normalize(shop.phone) or sms.normalize(getattr(shop.user, 'phone_number', ''))
    if phone:
        sms.notify(phone, text)


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


UNPAID_CANCEL_HOURS = 24


def cancel_unpaid_orders(limit=200):
    """
    কাস্টমার "অনলাইনে দেব" বেছে অর্ডার দিয়ে টাকা না দিলে অর্ডার আর স্টক ঝুলে থাকত। দিনে একবার (views_cron): ২৪ ঘণ্টার বেশি
    পুরনো, এখনো "নতুন" অবস্থায় থাকা এমন অর্ডার বাতিল হয় আর মাল স্টকে ফেরে। বাতিলের আগে গেটওয়েতে আবার যাচাই —
    টাকা এসে থাকলে বাতিল না। সেলার অর্ডারটা কনফার্ম করে ফেললে (ফোনে কথা বলে COD) সেটায় হাত দেওয়া হয় না।
    """
    from datetime import timedelta
    from . import order_flow
    from .models import Order
    cutoff = timezone.now() - timedelta(hours=UNPAID_CANCEL_HOURS)
    orders = (Order.objects.filter(online_payment_status=Order.ONLINE_PENDING, status='Pending', created_at__lt=cutoff,
                                   shop__is_demo=False).select_related('shop', 'customer').order_by('id')[:limit])
    cancelled = 0
    for order in orders:
        keep = False
        for payment in order.customer_payments.filter(status=StorefrontPayment.STATUS_PENDING).order_by('-created_at')[:2]:
            try:
                status, _payment, _msg = apply_successful(payment.invoice_number, timeout=6)
                # "unverified" দুই কারণে হয়: গেটওয়ে উত্তর দেয়নি (তখন বাতিল না), অথবা কাস্টমার টাকাই দেয়নি
                gateway_down = (status == 'unverified' and payment.environment == paystation.current_environment()
                                and paystation.verify_transaction(payment.invoice_number, timeout=6) is None)
            except Exception:    # noqa: BLE001 — নিশ্চিত না হয়ে বাতিল না; কাল আবার দেখা হবে
                logger.exception('unpaid order recheck failed: %s', payment.invoice_number)
                keep = True
                break
            if status in ('ok', 'already') or gateway_down:
                keep = True
                break
        if keep:
            continue
        try:
            order_flow.set_status(order, 'Cancelled', notify=False)
        except order_flow.FlowError:
            continue
        note = 'অনলাইনে টাকা না দেওয়ায় ২৪ ঘণ্টা পর নিজে থেকে বাতিল'
        Order.objects.filter(pk=order.pk).update(note=f'{order.note} · {note}'[:500] if order.note else note)
        order.customer_payments.filter(status=StorefrontPayment.STATUS_PENDING).update(
            status=StorefrontPayment.STATUS_FAILED)
        cancelled += 1
    return cancelled


# ---------------------------------------------------------------- কাস্টমারকে টাকা ফেরত
REFUND_METHODS = ('bKash', 'Nagad', 'Rocket')


def platform_refunds(shop):
    """SellPunch থেকে কাস্টমারকে পাঠানো (বা পাঠানো বাকি) ফেরত — সেলারের জমা থেকে কাটা।"""
    from .models import CustomerRefund
    return CustomerRefund.objects.filter(shop=shop, way=CustomerRefund.PLATFORM).exclude(
        status=CustomerRefund.REJECTED).aggregate(total=Sum('amount'))['total'] or ZERO


def refundable(order):
    """এই অর্ডারে কাস্টমার অনলাইনে যা দিয়েছে তার মধ্যে এখনো কত ফেরত দেওয়া যায়।"""
    from .models import CustomerRefund
    paid = order.customer_payments.filter(status=StorefrontPayment.STATUS_COMPLETED).aggregate(
        total=Sum('amount'))['total'] or ZERO
    given = CustomerRefund.objects.filter(order=order).exclude(status=CustomerRefund.REJECTED).aggregate(
        total=Sum('amount'))['total'] or ZERO
    return max(paid - given, ZERO)


def create_refund(order, amount, way, *, method='', account='', reference='', note='', user=None):
    """
    সেলার "টাকা ফেরত" দিলে। way=seller: নিজে দিয়েছেন (সাথে সাথে "ফেরত দেওয়া হয়েছে")। way=platform: SellPunch পাঠাবে —
    সেলারের জমায় (তোলা হয়নি এমন টাকা) যথেষ্ট থাকতে হবে। অর্ডারে কাস্টমারের দেওয়া টাকা সেই পরিমাণ কমে।
    """
    from accounts.forms import normalize_bd_mobile
    from .models import CustomerRefund
    with transaction.atomic():
        shop = Shop.objects.select_for_update().get(pk=order.shop_id)
        order = Order.objects.select_for_update().get(pk=order.pk)
        try:
            amount = Decimal(str(amount).replace(',', '').strip()).quantize(Decimal('0.01'))
        except (ArithmeticError, ValueError):
            raise SettlementError('কত টাকা ফেরত দেবেন লিখুন।')
        left = refundable(order)
        if amount <= 0 or amount > left:
            raise SettlementError(f'৳১ থেকে ৳{left:,.0f}-এর মধ্যে লিখুন — কাস্টমার অনলাইনে এর বেশি দেয়নি।'
                                  if left else 'এই অর্ডারে ফেরত দেওয়ার মতো অনলাইনের টাকা নেই।')
        if way == CustomerRefund.PLATFORM:
            phone = normalize_bd_mobile(account)
            if method not in REFUND_METHODS or not phone:
                raise SettlementError('কাস্টমারের bKash, Nagad বা Rocket নম্বর ঠিকমতো দিন।')
            summary = balance_summary(shop)
            room = summary['available'] + summary['holding']
            if amount > room:
                raise SettlementError(f'আপনার জমায় আছে ৳{room:,.0f}, তাই {settings.SITE_NAME} থেকে ৳{amount:,.0f} '
                                      'পাঠানো যাচ্ছে না। নিজে ফেরত দিয়ে "আমি নিজে ফেরত দিয়েছি" বেছে নিন।')
            account, status = phone, CustomerRefund.PENDING
        elif way == CustomerRefund.SELLER:
            status = CustomerRefund.DONE
        else:
            raise SettlementError('কীভাবে ফেরত দেবেন বেছে নিন।')
        actor = user if getattr(user, 'is_authenticated', False) else None
        refund = CustomerRefund.objects.create(
            shop=shop, order=order, order_ref=order.pk, amount=amount, way=way, status=status,
            method=method if way == CustomerRefund.PLATFORM else str(method or '')[:20],
            account=str(account or '')[:40], reference=str(reference or '').strip()[:100],
            note=str(note or '').strip()[:200], created_by=actor,
            decided_at=timezone.now() if status == CustomerRefund.DONE else None)
        order.advance_paid = max(order.advance_paid - amount, ZERO)
        fields = ['advance_paid']
        if order.advance_paid == 0 and order.online_payment_status == Order.ONLINE_PAID:
            order.online_payment_status = Order.ONLINE_NONE
            fields.append('online_payment_status')
        order.save(update_fields=fields)
    return refund


def finish_refund(refund_id, reference, user=None):
    """HQ: কাস্টমারকে পাঠিয়ে TrxID দিলে — কাস্টমার আর সেলার SMS পায়।"""
    from .models import CustomerRefund
    reference = str(reference or '').strip()[:100]
    if not reference:
        raise SettlementError('লেনদেন নম্বর (TrxID) দিন।')
    with transaction.atomic():
        refund = CustomerRefund.objects.select_for_update().select_related('shop').filter(
            pk=refund_id, way=CustomerRefund.PLATFORM, status=CustomerRefund.PENDING).first()
        if refund is None:
            raise SettlementError('এই ফেরতটা আর বাকি নেই।')
        refund.status, refund.reference, refund.decided_at = CustomerRefund.DONE, reference, timezone.now()
        refund.save(update_fields=['status', 'reference', 'decided_at'])
    amount = _bn(f'{refund.amount:,.0f}')
    from . import sms
    sms.notify(refund.account, f'{refund.shop.name}: অর্ডার #{_bn(str(refund.order_ref))}-এর ৳{amount} আপনার '
                               f'{refund.method}-এ ফেরত পাঠানো হয়েছে। TrxID {reference}')
    _notify_seller(refund.shop, f'{settings.SITE_NAME}: অর্ডার #{_bn(str(refund.order_ref))}-এর ৳{amount} কাস্টমারকে '
                                f'ফেরত পাঠানো হয়েছে (TrxID {reference})।')
    return refund


def reject_refund(refund_id, reason):
    """HQ: পাঠানো যায়নি (ভুল নম্বর ইত্যাদি) — টাকা সেলারের জমায় আর অর্ডারে ফেরে, সেলার SMS পায়।"""
    from .models import CustomerRefund
    reason = (reason or '').strip()[:200] or 'কাস্টমারের নম্বর মেলেনি'
    with transaction.atomic():
        refund = CustomerRefund.objects.select_for_update(of=('self',)).select_related('shop').filter(
            pk=refund_id, way=CustomerRefund.PLATFORM, status=CustomerRefund.PENDING).first()
        if refund is None:
            return 0
        refund.status, refund.note, refund.decided_at = CustomerRefund.REJECTED, reason, timezone.now()
        refund.save(update_fields=['status', 'note', 'decided_at'])
        if refund.order_id:
            from django.db.models import F
            Order.objects.filter(pk=refund.order_id).update(advance_paid=F('advance_paid') + refund.amount)
    _notify_seller(refund.shop, f'{settings.SITE_NAME}: অর্ডার #{_bn(str(refund.order_ref))}-এর ৳{_bn(f"{refund.amount:,.0f}")} '
                                f'ফেরত পাঠানো যায়নি — {reason}। নম্বর ঠিক করে আবার দিন।')
    return 1


def refunds_waiting(shop):
    """বাতিল/ফেরত হওয়া অর্ডার, যেখানে কাস্টমার অনলাইনে টাকা দিয়েছিল আর এখনো পুরো ফেরত দেওয়া হয়নি।"""
    from .models import CustomerRefund
    orders = (Order.objects.filter(shop=shop, status__in=('Cancelled', 'Returned'),
                                   customer_payments__status=StorefrontPayment.STATUS_COMPLETED)
              .distinct().select_related('customer').order_by('-id')[:50])
    out = []
    for order in orders:
        left = refundable(order)
        if left > 0:
            order.refund_left = left
            out.append(order)
    return out
