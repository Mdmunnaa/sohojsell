# store/paystation.py
"""
PayStation (paystation.com.bd) পেমেন্ট গেটওয়ের সাথে কথা বলার একমাত্র জায়গা।

Edumi-তে লাইভ টাকায় পরীক্ষিত কোড থেকে আনা: পেমেন্ট শুরু (initiate) আর যাচাই (verify)।

নিরাপত্তার নিয়ম: ব্রাউজারের callback বা IPN-এর body-তে যা-ই আসুক, কোনো পেমেন্ট সেটার
ভিত্তিতে সফল ধরা হয় না। সবসময় verify_transaction() দিয়ে PayStation-এর সার্ভারকে
সরাসরি জিজ্ঞেস করা হয়। IPN-এ কোনো authentication নেই, তাই এই যাচাইটাই একমাত্র সুরক্ষা।
"""

import logging
from decimal import Decimal, InvalidOperation

import requests
from django.conf import settings

logger = logging.getLogger('store.paystation')

BASE_URLS = {
    'sandbox': 'https://sandbox.paystation.com.bd',
    'live': 'https://api.paystation.com.bd',
}

# গেটওয়ে ঝুলে থাকলে আমাদের worker যেন আটকে না থাকে
TIMEOUT = 20


def current_environment():
    env = (getattr(settings, 'PAYSTATION_ENVIRONMENT', 'sandbox') or 'sandbox').strip().lower()
    return 'live' if env in ('live', 'production', 'prod') else 'sandbox'


def get_base_url(environment=None):
    env = (environment or current_environment()).strip().lower()
    return BASE_URLS['live'] if env in ('live', 'production', 'prod') else BASE_URLS['sandbox']


def is_configured():
    return bool(getattr(settings, 'PAYSTATION_MERCHANT_ID', '') and getattr(settings, 'PAYSTATION_PASSWORD', ''))


def initiate_payment(invoice_number, amount, cust_name, cust_phone, cust_email, callback_url,
                     cust_address=None, reference=None, checkout_items=None):
    """
    PayStation-এ পেমেন্ট শুরু করে হোস্টেড চেকআউট পেজের URL ফেরত দেয়।

    রিটার্ন: {'ok': True, 'payment_url': '...'} অথবা {'ok': False, 'error': 'কারণ'}
    invoice_number অবশ্যই ইউনিক হতে হবে, নইলে PayStation 1008 কোড দেয়।
    """
    merchant_id = getattr(settings, 'PAYSTATION_MERCHANT_ID', '')
    password = getattr(settings, 'PAYSTATION_PASSWORD', '')
    if not merchant_id or not password:
        logger.error('PayStation credentials নেই — PAYSTATION_MERCHANT_ID / PAYSTATION_PASSWORD সেট করুন')
        return {'ok': False, 'error': 'পেমেন্ট গেটওয়ে কনফিগার করা নেই। সাপোর্টে যোগাযোগ করুন।'}

    payload = {
        'merchantId': merchant_id,
        'password': password,
        'invoice_number': str(invoice_number),
        'currency': 'BDT',
        'payment_amount': f'{Decimal(str(amount)):.2f}',
        'pay_with_charge': str(getattr(settings, 'PAYSTATION_PAY_WITH_CHARGE', '0')),
        'cust_name': (cust_name or 'Customer')[:100],
        'cust_phone': (cust_phone or '01700000000')[:20],
        'cust_email': (cust_email or 'billing@example.com')[:100],
        'cust_address': (cust_address or 'Bangladesh')[:255],
        'callback_url': callback_url,
    }
    if reference:
        payload['reference'] = str(reference)[:255]
    if checkout_items:
        payload['checkout_items'] = str(checkout_items)[:255]

    try:
        # PayStation-এর ডক অনুযায়ী form-encoded, JSON নয়
        resp = requests.post(f'{get_base_url()}/initiate-payment', data=payload, timeout=TIMEOUT)
    except requests.RequestException as e:
        logger.exception('PayStation initiate-payment নেটওয়ার্ক এরর: %s', e)
        return {'ok': False, 'error': 'পেমেন্ট গেটওয়ে এই মুহূর্তে সাড়া দিচ্ছে না। একটু পরে চেষ্টা করুন।'}

    try:
        data = resp.json()
    except ValueError:
        logger.error('PayStation initiate-payment JSON নয় (HTTP %s): %s', resp.status_code, resp.text[:300])
        return {'ok': False, 'error': 'পেমেন্ট গেটওয়ে থেকে অপ্রত্যাশিত উত্তর এসেছে।'}

    if str(data.get('status_code')) == '200' and data.get('payment_url'):
        return {'ok': True, 'payment_url': data['payment_url'], 'raw': data}

    logger.error('PayStation initiate-payment ব্যর্থ: %s', data)
    return {'ok': False, 'error': data.get('message') or 'পেমেন্ট শুরু করা যায়নি।', 'raw': data}


# PayStation-এর বিভিন্ন জায়গায় সফলতার শব্দ আলাদা ("Success", "success", "Successful")
SUCCESS_WORDS = frozenset({'success', 'successful', 'succeeded', 'completed', 'complete', 'paid'})
PROCESSING_WORDS = frozenset({'processing', 'pending', 'initiated', 'in progress', 'inprogress'})


def normalize_status(value):
    text = str(value or '').strip().lower()
    if text in SUCCESS_WORDS:
        return 'success'
    if text in PROCESSING_WORDS:
        return 'processing'
    return text


def _data_of(body):
    data = body.get('data') or {}
    if isinstance(data, list):
        data = data[0] if data and isinstance(data[0], dict) else {}
    return data if isinstance(data, dict) else {}


def _amount(*values):
    for value in values:
        try:
            amount = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            continue
        if amount > 0:
            return amount
    return Decimal('0')


def _result(data, fallback_trx=''):
    return {
        'status': normalize_status(data.get('trx_status')),
        'amount': _amount(data.get('payment_amount'), data.get('request_amount'), data.get('trx_amount')),
        'trx_id': data.get('trx_id') or fallback_trx,
        'payment_method': data.get('payment_method') or '',
        'invoice_number': str(data.get('invoice_number') or ''),
    }


def verify_transaction(invoice_number, timeout=TIMEOUT):
    """
    invoice নম্বর দিয়ে PayStation-এর Transaction Status (v1) API-তে server-to-server যাচাই।
    রিটার্ন: {'status': 'success'|'failed'|'processing'|..., 'amount': Decimal, 'trx_id', 'payment_method'}
    এরর হলে None — তখন কখনোই পেমেন্ট সফল ধরা যাবে না।
    """
    merchant_id = getattr(settings, 'PAYSTATION_MERCHANT_ID', '')
    if not merchant_id:
        return None
    try:
        resp = requests.post(
            f'{get_base_url()}/transaction-status',
            headers={'merchantId': merchant_id},
            data={'invoice_number': str(invoice_number)},
            timeout=timeout,
        )
    except requests.RequestException as e:
        logger.warning('PayStation transaction-status নেটওয়ার্ক এরর: %s', e)
        return None
    if resp.status_code != 200:
        logger.error('PayStation transaction-status HTTP %s: %s', resp.status_code, resp.text[:300])
        return None
    try:
        body = resp.json()
    except ValueError:
        logger.error('PayStation transaction-status JSON নয়: %s', resp.text[:300])
        return None
    if str(body.get('status_code')) != '200':
        logger.warning('PayStation verify ব্যর্থ (%s): %s', invoice_number, body)
        return None
    return _result(_data_of(body))


def verify_by_trx_id(trx_id, invoice_number, timeout=TIMEOUT):
    """
    দ্বিতীয় পথ: লেনদেন নম্বর (trx_id) দিয়ে Transaction Status v2। trx_id ব্রাউজার থেকে আসে, তাই
    PayStation-এর উত্তরের invoice_number আমাদের invoice-এর সাথে না মিললে বাতিল — নইলে অন্যের সফল
    লেনদেন দেখিয়ে কেউ নিজের বিল পরিশোধ দেখাতে পারত।
    """
    merchant_id = getattr(settings, 'PAYSTATION_MERCHANT_ID', '')
    if not merchant_id or not trx_id:
        return None
    try:
        resp = requests.post(
            f'{get_base_url()}/v2/transaction-status',
            headers={'merchantId': merchant_id, 'Content-Type': 'application/json'},
            json={'trxId': str(trx_id)},
            timeout=timeout,
        )
    except requests.RequestException as e:
        logger.warning('PayStation v2 transaction-status নেটওয়ার্ক এরর: %s', e)
        return None
    try:
        body = resp.json()
    except ValueError:
        return None
    if resp.status_code != 200 or str(body.get('status_code')) != '200':
        logger.warning('PayStation v2 verify ব্যর্থ (%s / %s): %s', invoice_number, trx_id, body)
        return None
    data = _data_of(body)
    if str(data.get('invoice_number') or '').strip() != str(invoice_number):
        logger.error('PayStation v2: trx %s অন্য invoice-এর (%s), আমাদের %s — নেওয়া হলো না',
                     trx_id, data.get('invoice_number'), invoice_number)
        return None
    return _result(data, fallback_trx=str(trx_id))


def is_successful(verify_result):
    return bool(verify_result) and verify_result.get('status') == 'success'
