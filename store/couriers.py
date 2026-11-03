# store/couriers.py
"""
কুরিয়ারে পার্সেল পাঠানো: Steadfast, Pathao, RedX।

যে ডকুমেন্টেশন দেখে বানানো (নভেম্বর ২০২৬):
- Steadfast: https://portal.packzy.com/api/v1 (পুরনো portal.steadfast.com.bd আর চলে না)।
  হেডার Api-Key + Secret-Key। create_order-এ invoice, recipient_name, recipient_phone,
  recipient_address, cod_amount লাগে; একই invoice দুবার নেয় না।
- Pathao (Aladdin API v1): /aladdin/api/v1/issue-token থেকে টোকেন (৫ দিন মেয়াদ, refresh_token দিয়ে নবায়ন)।
  অর্ডারে store_id, recipient_name, recipient_phone, recipient_address, delivery_type (48 সাধারণ),
  item_type (2 পার্সেল), item_quantity, item_weight (০.৫–১০ কেজি), amount_to_collect (পূর্ণ টাকা)।
  Pathao-র নিজের ঘোষণা অনুযায়ী এখন পুরো ঠিকানা দিলেই হয়, city/zone/area দিতে হয় না।
- RedX (OpenAPI v1.0.0-beta): হেডার "API-ACCESS-TOKEN: Bearer <token>"। পার্সেলে delivery_area আর
  delivery_area_id লাগে (/areas থেকে), parcel_weight গ্রামে, value আর cash_collection_amount।
"""
import logging
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

import requests
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)

TIMEOUT = 25
STEADFAST_BASE_URL = getattr(settings, 'STEADFAST_BASE_URL', 'https://portal.packzy.com/api/v1')
PATHAO_BASE_URL = getattr(settings, 'PATHAO_BASE_URL', 'https://api-hermes.pathao.com')
REDX_BASE_URL = getattr(settings, 'REDX_BASE_URL', 'https://openapi.redx.com.bd/v1.0.0-beta')

# এগুলোতে কাস্টমার আগেই টাকা দিয়ে দিয়েছে, কুরিয়ার কিছু তুলবে না
PREPAID_METHODS = {'Paid', 'bKash', 'Card'}
COURIERS = ('Steadfast', 'Pathao', 'RedX')


class CourierError(Exception):
    """সেলারকে দেখানোর মতো বাংলা মেসেজসহ।"""


# ---------------------------------------------------------------- সাধারণ
def cod_amount(order):
    """কুরিয়ার কাস্টমারের কাছ থেকে কত টাকা তুলবে (পূর্ণ টাকা)। আগে পরিশোধ হলে ০।"""
    if order.payment_method in PREPAID_METHODS:
        return 0
    return int(Decimal(order.total_amount or 0).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def invoice_for(order):
    # অর্ডার নম্বর সব দোকান মিলিয়ে আলাদা, তাই কুরিয়ারের কাছে ডুপ্লিকেট হয় না
    return f'ORD-{order.id}'


def recipient_phone(order):
    from accounts.forms import normalize_bd_mobile
    raw = (order.customer.phone or '').strip()
    phone = normalize_bd_mobile(raw)
    if not phone:
        raise CourierError(f'কাস্টমারের মোবাইল নম্বর ঠিক নেই ({raw})। ১১ সংখ্যার নম্বর দিন, যেমন 017XXXXXXXX।')
    return phone


def recipient_address(order, minimum=0):
    address = ' '.join((order.customer.address or '').split())
    if not address:
        raise CourierError('কাস্টমারের ঠিকানা দেওয়া নেই। অর্ডার এডিট করে ঠিকানা দিন।')
    if minimum and len(address) < minimum:
        raise CourierError(f'ঠিকানা খুব ছোট। রোড, এলাকা/থানা আর জেলাসহ কমপক্ষে {minimum} অক্ষরে লিখুন।')
    return address


def item_summary(order):
    items = list(order.items.select_related('product'))
    quantity = sum(item.quantity for item in items) or 1
    description = ', '.join(f'{item.product.name} x{item.quantity}' for item in items)[:200]
    return quantity, description


def _json(response):
    try:
        return response.json()
    except ValueError:
        return {}


def _first_error(result, fallback):
    """কুরিয়ারের ভুলের উত্তর থেকে পড়ার মতো একটা লাইন।"""
    if not isinstance(result, dict):
        return fallback
    errors = result.get('errors')
    if isinstance(errors, dict):
        for value in errors.values():
            if isinstance(value, list) and value:
                return str(value[0])
            if value:
                return str(value)
    for key in ('message', 'error', 'validation_errors'):
        if result.get(key):
            return str(result[key])
    return fallback


def _request(method, url, *, courier, **kwargs):
    try:
        return requests.request(method, url, timeout=TIMEOUT, **kwargs)
    except requests.Timeout:
        raise CourierError(f'{courier} সময়মতো উত্তর দেয়নি। একটু পর আবার চেষ্টা করুন '
                           f'(একই অর্ডার দুবার পাঠালেও {courier} ডুপ্লিকেট পার্সেল বানাবে না)।')
    except requests.RequestException as exc:
        logger.warning('%s request failed: %s', courier, exc)
        raise CourierError(f'{courier}-এর সার্ভারে পৌঁছানো যায়নি। একটু পর আবার চেষ্টা করুন।')


# ---------------------------------------------------------------- Steadfast
def _steadfast_headers(shop):
    if not shop.steadfast_api_key or not shop.steadfast_secret_key:
        raise CourierError('Settings-এ Steadfast-এর API Key আর Secret Key দিন।')
    return {'Api-Key': shop.steadfast_api_key.strip(), 'Secret-Key': shop.steadfast_secret_key.strip(),
            'Content-Type': 'application/json', 'Accept': 'application/json'}


def steadfast_create(shop, order, note=''):
    quantity, description = item_summary(order)
    payload = {
        'invoice': invoice_for(order),
        'recipient_name': order.customer.name[:100],
        'recipient_phone': recipient_phone(order),
        'recipient_address': recipient_address(order)[:490],
        'cod_amount': cod_amount(order),
        'note': (note or order.note or '')[:480],
        'item_description': description,
        'total_lot': quantity,
        'delivery_type': 0,   # ০ = বাসায় ডেলিভারি
    }
    response = _request('POST', f'{STEADFAST_BASE_URL}/create_order', courier='Steadfast',
                        headers=_steadfast_headers(shop), json=payload)
    result = _json(response)
    if response.status_code == 401:
        raise CourierError('Steadfast API Key বা Secret Key ভুল। Settings থেকে ঠিক করুন '
                           '(বারবার ভুল চাবি দিয়ে চেষ্টা করলে Steadfast এক ঘণ্টা আটকে রাখে)।')
    consignment = result.get('consignment') if isinstance(result, dict) else None
    if response.status_code == 200 and result.get('status') == 200 and consignment:
        return {'tracking_code': consignment.get('tracking_code') or str(consignment.get('consignment_id')),
                'consignment_id': consignment.get('consignment_id')}
    raise CourierError('Steadfast: ' + _first_error(result, f'পার্সেল নেয়নি (HTTP {response.status_code})।'))


def steadfast_test(shop):
    response = _request('GET', f'{STEADFAST_BASE_URL}/get_balance', courier='Steadfast',
                        headers=_steadfast_headers(shop))
    result = _json(response)
    if response.status_code == 200 and result.get('status') == 200:
        return f"Steadfast কানেক্ট আছে ✓ (ব্যালান্স ৳{result.get('current_balance', 0)})"
    if response.status_code == 401:
        raise CourierError('Steadfast API Key বা Secret Key ভুল।')
    raise CourierError('Steadfast: ' + _first_error(result, f'যাচাই হয়নি (HTTP {response.status_code})।'))


# ---------------------------------------------------------------- Pathao
def pathao_connect(shop, client_id, client_secret, username, password):
    """
    ইমেইল-পাসওয়ার্ড দিয়ে একবার টোকেন নেওয়া হয়; পাসওয়ার্ড কোথাও সেভ হয় না।
    এরপর refresh_token দিয়ে নিজে থেকে নবায়ন হয়।
    """
    client_id, client_secret = (client_id or '').strip(), (client_secret or '').strip()
    if not (client_id and client_secret and username and password):
        raise CourierError('Pathao-র Client ID, Client Secret, ইমেইল আর পাসওয়ার্ড চারটাই দিন।')
    _issue_token(shop, client_id, client_secret,
                 {'grant_type': 'password', 'username': username.strip(), 'password': password})
    stores = pathao_fetch_stores(shop)
    if not stores:
        raise CourierError('Pathao কানেক্ট হয়েছে, কিন্তু কোনো চালু স্টোর পাওয়া যায়নি। '
                           'merchant.pathao.com-এ একটা স্টোর বানিয়ে আবার কানেক্ট করুন।')
    return stores


def _issue_token(shop, client_id, client_secret, grant):
    response = _request('POST', f'{PATHAO_BASE_URL}/aladdin/api/v1/issue-token', courier='Pathao',
                        json={'client_id': client_id, 'client_secret': client_secret, **grant},
                        headers={'Accept': 'application/json'})
    result = _json(response)
    token = result.get('access_token') if isinstance(result, dict) else None
    if response.status_code != 200 or not token:
        if grant.get('grant_type') == 'refresh_token':
            raise CourierError('Pathao-র সংযোগের মেয়াদ শেষ। Settings থেকে Pathao আবার কানেক্ট করুন।')
        raise CourierError('Pathao: ' + _first_error(result, 'Client ID, Secret, ইমেইল বা পাসওয়ার্ড ভুল।'))
    shop.pathao_client_id = client_id
    shop.pathao_client_secret = client_secret
    shop.pathao_access_token = token
    shop.pathao_refresh_token = result.get('refresh_token') or shop.pathao_refresh_token
    shop.pathao_token_expires_at = timezone.now() + timedelta(seconds=int(result.get('expires_in') or 432000))
    shop.save(update_fields=['pathao_client_id', 'pathao_client_secret', 'pathao_access_token',
                             'pathao_refresh_token', 'pathao_token_expires_at'])
    return token


def pathao_token(shop):
    if not shop.pathao_access_token:
        raise CourierError('Settings থেকে Pathao কানেক্ট করুন।')
    expires = shop.pathao_token_expires_at
    if expires and expires - timezone.now() < timedelta(minutes=10):
        if not (shop.pathao_refresh_token and shop.pathao_client_id and shop.pathao_client_secret):
            raise CourierError('Pathao-র সংযোগের মেয়াদ শেষ। Settings থেকে Pathao আবার কানেক্ট করুন।')
        return _issue_token(shop, shop.pathao_client_id, shop.pathao_client_secret,
                            {'grant_type': 'refresh_token', 'refresh_token': shop.pathao_refresh_token})
    return shop.pathao_access_token


def _pathao_headers(shop):
    return {'Authorization': f'Bearer {pathao_token(shop)}', 'Content-Type': 'application/json',
            'Accept': 'application/json'}


def pathao_fetch_stores(shop):
    response = _request('GET', f'{PATHAO_BASE_URL}/aladdin/api/v1/stores', courier='Pathao',
                        headers=_pathao_headers(shop))
    result = _json(response)
    if response.status_code == 401:
        raise CourierError('Pathao-র সংযোগ কাজ করছে না। Settings থেকে আবার কানেক্ট করুন।')
    if response.status_code != 200:
        raise CourierError('Pathao: ' + _first_error(result, f'স্টোর লিস্ট আসেনি (HTTP {response.status_code})।'))
    rows = ((result.get('data') or {}).get('data') or []) if isinstance(result, dict) else []
    stores = [{'id': row.get('store_id'), 'name': row.get('store_name') or str(row.get('store_id')),
               'default': bool(row.get('is_default_store'))}
              for row in rows if row.get('store_id') and row.get('is_active', 1)]
    shop.pathao_stores = stores
    ids = {str(store['id']) for store in stores}
    if stores and str(shop.pathao_store_id or '') not in ids:
        chosen = next((s for s in stores if s['default']), stores[0])
        shop.pathao_store_id = str(chosen['id'])
    shop.save(update_fields=['pathao_stores', 'pathao_store_id'])
    return stores


def pathao_create(shop, order, note=''):
    if not shop.pathao_store_id:
        raise CourierError('Settings-এ Pathao-র কোন স্টোর থেকে পার্সেল যাবে সেটা বেছে নিন।')
    quantity, description = item_summary(order)
    payload = {
        'store_id': int(shop.pathao_store_id),
        'merchant_order_id': invoice_for(order),
        'recipient_name': order.customer.name[:100],
        'recipient_phone': recipient_phone(order),
        'recipient_address': recipient_address(order, minimum=10)[:220],
        'delivery_type': 48,      # সাধারণ ডেলিভারি
        'item_type': 2,           # পার্সেল
        'item_quantity': quantity,
        'item_weight': 0.5,
        'item_description': description,
        'special_instruction': (note or order.note or '')[:250],
        'amount_to_collect': cod_amount(order),
    }
    response = _request('POST', f'{PATHAO_BASE_URL}/aladdin/api/v1/orders', courier='Pathao',
                        headers=_pathao_headers(shop), json=payload)
    result = _json(response)
    data = result.get('data') if isinstance(result, dict) else None
    if response.status_code in (200, 201) and isinstance(data, dict) and data.get('consignment_id'):
        return {'tracking_code': data['consignment_id'], 'consignment_id': data['consignment_id']}
    if response.status_code == 401:
        raise CourierError('Pathao-র সংযোগ কাজ করছে না। Settings থেকে আবার কানেক্ট করুন।')
    raise CourierError('Pathao: ' + _first_error(result, f'পার্সেল নেয়নি (HTTP {response.status_code})।'))


def pathao_test(shop):
    stores = pathao_fetch_stores(shop)
    if not stores:
        raise CourierError('Pathao কানেক্ট আছে, কিন্তু কোনো চালু স্টোর নেই।')
    return f'Pathao কানেক্ট আছে ✓ ({len(stores)}টা স্টোর পাওয়া গেছে)'


# ---------------------------------------------------------------- RedX
def _redx_headers(shop):
    token = (shop.redx_access_token or '').strip()
    if token.lower().startswith('bearer '):
        token = token[7:].strip()
    if not token:
        raise CourierError('Settings-এ RedX-এর API Access Token দিন।')
    return {'API-ACCESS-TOKEN': f'Bearer {token}', 'Content-Type': 'application/json', 'Accept': 'application/json'}


REDX_AREAS_CACHE_KEY = 'redx_areas_v1'


def redx_areas(shop):
    """RedX-এর সব ডেলিভারি এলাকা (id, name, post_code)। সবার জন্য একই, তাই ২৪ ঘণ্টা ক্যাশে রাখা হয়।"""
    areas = cache.get(REDX_AREAS_CACHE_KEY)
    if areas:
        return areas
    response = _request('GET', f'{REDX_BASE_URL}/areas', courier='RedX', headers=_redx_headers(shop))
    result = _json(response)
    if response.status_code == 401:
        raise CourierError('RedX টোকেন ভুল বা মেয়াদ শেষ। Settings থেকে ঠিক করুন।')
    rows = result.get('areas') if isinstance(result, dict) else None
    if response.status_code != 200 or not rows:
        raise CourierError('RedX: ' + _first_error(result, f'এলাকার লিস্ট আসেনি (HTTP {response.status_code})।'))
    areas = sorted(({'id': row['id'], 'name': row.get('name', ''), 'post_code': row.get('post_code')}
                    for row in rows if row.get('id')), key=lambda a: a['name'])
    cache.set(REDX_AREAS_CACHE_KEY, areas, 24 * 3600)
    return areas


def redx_create(shop, order, area_id, note=''):
    try:
        area_id = int(area_id)
    except (TypeError, ValueError):
        raise CourierError('RedX-এর জন্য ডেলিভারি এলাকা বেছে নিন।')
    area = next((a for a in redx_areas(shop) if a['id'] == area_id), None)
    if area is None:
        raise CourierError('বেছে নেওয়া এলাকাটা RedX-এর লিস্টে নেই। আবার বেছে নিন।')
    _quantity, description = item_summary(order)
    payload = {
        'customer_name': order.customer.name[:100],
        'customer_phone': recipient_phone(order),
        'delivery_area': area['name'],
        'delivery_area_id': area['id'],
        'customer_address': recipient_address(order),
        'merchant_invoice_id': invoice_for(order),
        'cash_collection_amount': str(cod_amount(order)),
        'parcel_weight': 500,     # গ্রাম
        'value': int(Decimal(order.total_amount or 0).quantize(Decimal('1'), rounding=ROUND_HALF_UP)),
        'instruction': (note or order.note or description)[:250],
    }
    response = _request('POST', f'{REDX_BASE_URL}/parcel', courier='RedX', headers=_redx_headers(shop), json=payload)
    result = _json(response)
    if response.status_code in (200, 201) and isinstance(result, dict) and result.get('tracking_id'):
        return {'tracking_code': result['tracking_id'], 'consignment_id': result['tracking_id']}
    if response.status_code == 401:
        raise CourierError('RedX টোকেন ভুল বা মেয়াদ শেষ। Settings থেকে ঠিক করুন।')
    raise CourierError('RedX: ' + _first_error(result, f'পার্সেল নেয়নি (HTTP {response.status_code})।'))


def redx_test(shop):
    response = _request('GET', f'{REDX_BASE_URL}/pickup/stores', courier='RedX', headers=_redx_headers(shop))
    result = _json(response)
    if response.status_code == 200:
        count = len(result.get('pickup_stores') or []) if isinstance(result, dict) else 0
        return f'RedX কানেক্ট আছে ✓ ({count}টা পিকআপ স্টোর)'
    if response.status_code == 401:
        raise CourierError('RedX টোকেন ভুল বা মেয়াদ শেষ।')
    raise CourierError('RedX: ' + _first_error(result, f'যাচাই হয়নি (HTTP {response.status_code})।'))


# ---------------------------------------------------------------- এক জায়গা থেকে
def send(shop, order, courier, area_id=None, note=''):
    if courier == 'Steadfast':
        return steadfast_create(shop, order, note)
    if courier == 'Pathao':
        return pathao_create(shop, order, note)
    if courier == 'RedX':
        return redx_create(shop, order, area_id, note)
    raise CourierError('কুরিয়ার বেছে নিন।')


def test_connection(shop, courier):
    return {'Steadfast': steadfast_test, 'Pathao': pathao_test, 'RedX': redx_test}[courier](shop)


def connected(shop):
    """কোন কোন কুরিয়ার সেটআপ করা আছে (অর্ডার পেইজে দেখানোর জন্য)।"""
    return {
        'Steadfast': bool(shop.steadfast_api_key and shop.steadfast_secret_key),
        'Pathao': bool(shop.pathao_access_token and shop.pathao_store_id),
        'RedX': bool(shop.redx_access_token),
    }
