# store/payment_views.py
"""PayStation দিয়ে প্ল্যান বা SMS কেনা: শুরু, ব্রাউজার callback, আর PayStation-এর IPN।"""

import json
import logging
import re
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from . import paystation
from .models import OnlinePayment
from .payments import (
    CALLBACK_VERIFY_TIMEOUT, apply_successful_payment, new_invoice_number, online_payment_available,
    remember_claimed_trx, resolve_item, valid_invoice, valid_trx_id,
)

logger = logging.getLogger('store.payments')

BD_MOBILE_RE = re.compile(r'^01\d{9}$')


def _customer_phone(shop, user):
    for value in (shop.phone, getattr(user, 'phone_number', '')):
        value = (value or '').strip()
        if BD_MOBILE_RE.match(value):
            return value
    return '01700000000'


def _raw_invoice(request):
    for key in ('inv', 'invoice_number'):
        value = request.POST.get(key) or request.GET.get(key)
        if value:
            return str(value).strip()
    if request.content_type and 'application/json' in request.content_type:
        try:
            payload = json.loads(request.body.decode('utf-8') or '{}')
        except (ValueError, UnicodeDecodeError):
            return ''
        if isinstance(payload, dict):
            return str(payload.get('invoice_number') or '').strip()
    return ''


def _invoice_from_request(request):
    """invoice নম্বর কোথায় আসতে পারে: আমাদের বসানো ?inv=, PayStation-এর invoice_number, বা IPN-এর JSON body।"""
    return valid_invoice(_raw_invoice(request))


@login_required(login_url='/accounts/login/')
def paystation_start(request):
    """Billing পেইজের "অনলাইনে পেমেন্ট" বাটন — রেকর্ড বানিয়ে PayStation-এর পেমেন্ট পেইজে পাঠায়।"""
    if request.method != 'POST':
        return redirect('billing')
    shop = getattr(request.user, 'shop', None)
    if shop is None:
        return redirect('setup_shop')
    item = resolve_item(request.POST.get('item'))
    back = 'sms_panel' if item and item['kind'] == OnlinePayment.KIND_SMS else 'billing'
    if item is None:
        messages.error(request, 'প্যাকেজটা পাওয়া যায়নি, আবার চেষ্টা করুন।')
        return redirect('billing')
    return start_online_payment(request, shop, item, back)


def start_online_payment(request, shop, item, back='billing'):
    """প্ল্যান বা SMS — যেকোনো কেনাকাটার জন্য PayStation-এর পেমেন্ট পেইজে পাঠায়; সমস্যা হলে back পেইজে ফেরত।"""
    if not online_payment_available(shop):
        messages.warning(request, 'অনলাইন পেমেন্ট এখনো চালু হয়নি। আপাতত bKash/Nagad-এ পাঠিয়ে লেনদেন নম্বর জমা দিন।')
        return redirect(back)

    # কেউ যেন বারবার চাপ দিয়ে হাজারটা ইনভয়েস বানাতে না পারে
    recent = shop.online_payments.filter(
        status=OnlinePayment.STATUS_PENDING, created_at__gte=timezone.now() - timedelta(minutes=10)
    ).count()
    if recent >= 5:
        messages.warning(request, 'অনেকবার চেষ্টা হয়েছে। ১০ মিনিট পর আবার চেষ্টা করুন।')
        return redirect(back)

    payment = OnlinePayment.objects.create(
        shop=shop,
        kind=item['kind'],
        plan_name=item['plan_name'],
        days=item['days'],
        sms_count=item['sms_count'],
        amount=item['amount'],
        invoice_number=new_invoice_number(shop),
        environment=paystation.current_environment(),
    )
    callback_url = request.build_absolute_uri(reverse('paystation_callback')) + f'?inv={payment.invoice_number}'

    result = paystation.initiate_payment(
        invoice_number=payment.invoice_number,
        amount=payment.amount,
        cust_name=shop.name,
        cust_phone=_customer_phone(shop, request.user),
        cust_email=settings.SUPPORT_EMAIL or 'billing@example.com',
        cust_address=shop.address,
        callback_url=callback_url,
        reference=f'shop-{shop.id}',
        checkout_items=item['label'],
    )
    if result.get('ok'):
        return redirect(result['payment_url'])

    payment.status = OnlinePayment.STATUS_FAILED
    payment.save(update_fields=['status'])
    messages.error(request, result.get('error') or 'পেমেন্ট শুরু করা যায়নি।')
    return redirect(back)


def _back_for(invoice):
    """SMS কেনা হলে SMS প্যানেলে, প্ল্যান হলে billing-এ ফেরত।"""
    kind = OnlinePayment.objects.filter(invoice_number=invoice).values_list('kind', flat=True).first()
    return 'sms_panel' if kind == OnlinePayment.KIND_SMS else 'billing'


@csrf_exempt
def paystation_callback(request):
    """
    টাকা দেওয়ার পর PayStation ব্রাউজারকে এখানে ফেরত পাঠায় (GET, কখনো POST)।
    URL-এর status বা trx_id বিশ্বাস করা হয় না — আসল সিদ্ধান্ত PayStation-এ যাচাই করে।
    """
    invoice = _invoice_from_request(request)
    if not invoice:
        messages.error(request, 'পেমেন্ট নিশ্চিত করা যায়নি।')
        return redirect('billing')

    back = _back_for(invoice)
    gateway_status = (request.GET.get('status') or request.POST.get('status') or '').strip().lower()
    if gateway_status in ('failed', 'canceled', 'cancelled', 'cancel'):
        messages.warning(request, 'পেমেন্ট সম্পন্ন হয়নি (বাতিল বা ব্যর্থ)। চাইলে আবার চেষ্টা করুন।')
        return redirect(back)

    trx_id = valid_trx_id(request.GET.get('trx_id') or request.POST.get('trx_id'))
    if trx_id and trx_id != invoice:
        remember_claimed_trx(invoice, trx_id)
    else:
        trx_id = None

    status, _payment, msg = apply_successful_payment(
        invoice, trx_id=trx_id, attempts=2, timeout=CALLBACK_VERIFY_TIMEOUT)
    if status in ('ok', 'already'):
        messages.success(request, msg)
    elif status in ('unverified', 'failed'):
        messages.warning(request, f'⏳ {msg}' if status == 'unverified' else msg)
    else:
        messages.error(request, msg)
    return redirect(back)


@csrf_exempt
def paystation_ipn(request):
    """
    PayStation-এর IPN (সার্ভার থেকে সার্ভারে খবর)। ব্রাউজার callback না এলেও পেমেন্ট সম্পন্ন হয়।
    PayStation-কে এই URL দিতে হবে: https://<domain>/payment/ipn/
    এখানে কোনো authentication নেই, তাই body-র কিছু বিশ্বাস না করে শুধু invoice নিয়ে PayStation-এ যাচাই।
    """
    raw = _raw_invoice(request)
    logger.info('PayStation IPN: invoice=%s', raw[:40])
    from . import shop_payments
    if shop_payments.valid_invoice(raw):
        # কাস্টমার দোকানের ওয়েবসাইটে টাকা দিয়েছে
        status, _payment, msg = shop_payments.apply_successful(raw)
    else:
        invoice = valid_invoice(raw)
        if not invoice:
            return JsonResponse({'status': 'error', 'message': 'invoice_number missing'}, status=400)
        status, _payment, msg = apply_successful_payment(invoice)
    if status in ('ok', 'already', 'failed'):
        return JsonResponse({'status': 'success' if status != 'failed' else 'failed'})
    if status == 'not_found':
        return JsonResponse({'status': 'error', 'message': 'not found'}, status=404)
    # unverified / amount_mismatch — PayStation আবার পাঠাক
    return JsonResponse({'status': 'error', 'message': 'not verified'}, status=422)
