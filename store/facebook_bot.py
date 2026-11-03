# store/facebook_bot.py
"""
Facebook পেইজের কমেন্ট থেকে অর্ডার।

কীভাবে কাজ করে:
1. সেলার পেইজ কানেক্ট করলে পেইজটা আমাদের অ্যাপের "feed" webhook-এ subscribe হয়।
2. কেউ পোস্টে কমেন্ট করলে Meta /facebook/webhook/-এ খবর পাঠায় (X-Hub-Signature-256 দিয়ে সই করা)।
3. পোস্টের লেখায় বা কমেন্টে প্রোডাক্ট কোড (যেমন #P12) থাকলে সেই প্রোডাক্ট, না থাকলে দোকানের লিংক।
4. কমেন্টকারীর ইনবক্সে Private Reply যায় (প্রতি কমেন্টে একবারই, ৭ দিনের মধ্যে) আর চাইলে
   কমেন্টের নিচে ছোট একটা উত্তর: "ইনবক্স চেক করুন"।

Meta-র নিয়ম: Private Reply — POST /{page-id}/messages, recipient = {"comment_id": ...}।
লাগবে pages_messaging, pages_manage_metadata, pages_read_engagement; কমেন্টে উত্তর দিতে pages_manage_engagement।
"""
import hashlib
import hmac
import logging
import re

import requests
from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError, transaction

logger = logging.getLogger(__name__)

GRAPH_API = f"https://graph.facebook.com/{settings.FACEBOOK_GRAPH_VERSION}"
TIMEOUT = 6
PRODUCT_CODE_RE = re.compile(r'(?<![A-Za-z0-9])#?\s?P[-\s]?(\d{1,7})(?![0-9])', re.IGNORECASE)


def product_code(product):
    return f'#P{product.id}'


# ---------------------------------------------------------------- অ্যাপের গোপন তথ্য
def app_secret():
    secret = getattr(settings, 'FACEBOOK_APP_SECRET', '') or ''
    if secret:
        return secret
    from allauth.socialaccount.models import SocialApp
    app = SocialApp.objects.filter(provider='facebook').only('secret').first()
    return app.secret if app else ''


def signature_ok(raw_body, header):
    secret = app_secret()
    if not secret or not header or not header.startswith('sha256='):
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(header[7:], expected)


# ---------------------------------------------------------------- Graph API
def _post(path, token, **kwargs):
    try:
        response = requests.post(f'{GRAPH_API}/{path}', params={'access_token': token}, timeout=TIMEOUT, **kwargs)
    except requests.RequestException as exc:
        return False, str(exc)
    try:
        data = response.json() or {}
    except ValueError:
        data = {}
    if response.status_code == 200 and 'error' not in data:
        return True, data
    return False, (data.get('error') or {}).get('message') or f'HTTP {response.status_code}'


def subscribe_page(page_id, page_token):
    """পেইজের কমেন্টের খবর যেন আমাদের webhook-এ আসে।"""
    ok, result = _post(f'{page_id}/subscribed_apps', page_token, data={'subscribed_fields': 'feed'})
    if not ok:
        logger.warning('Facebook subscribe failed for page %s: %s', page_id, result)
    return ok


def unsubscribe_page(page_id, page_token):
    try:
        requests.delete(f'{GRAPH_API}/{page_id}/subscribed_apps', params={'access_token': page_token}, timeout=TIMEOUT)
    except requests.RequestException:
        pass


def post_message(post_id, page_token):
    """পোস্টের লেখা (প্রোডাক্ট কোড খোঁজার জন্য), এক ঘণ্টা ক্যাশে।"""
    key = f'fbpost:{post_id}'
    cached = cache.get(key)
    if cached is not None:
        return cached
    try:
        response = requests.get(f'{GRAPH_API}/{post_id}', params={'fields': 'message', 'access_token': page_token},
                                timeout=TIMEOUT)
        message = (response.json() or {}).get('message', '') if response.status_code == 200 else ''
    except (requests.RequestException, ValueError):
        message = ''
    cache.set(key, message, 3600)
    return message


def send_private_reply(page_id, page_token, comment_id, text):
    return _post(f'{page_id}/messages', page_token,
                 json={'recipient': {'comment_id': comment_id}, 'message': {'text': text}})


def send_public_reply(comment_id, page_token, text):
    return _post(f'{comment_id}/comments', page_token, data={'message': text})


# ---------------------------------------------------------------- মেসেজ বানানো
def find_product(shop, *texts):
    from .models import Product
    for text in texts:
        for match in PRODUCT_CODE_RE.finditer(text or ''):
            product = Product.objects.filter(shop=shop, id=int(match.group(1)), is_active=True).first()
            if product:
                return product
    return None


def build_private_message(shop, product, commenter_name=''):
    from .links import absolute_storefront_link
    hello = f'আসসালামু আলাইকুম{" " + commenter_name.split()[0] if commenter_name else ""}! '
    hello += f'{shop.name}-এ কমেন্ট করার জন্য ধন্যবাদ 😊'
    if product and product.stock_quantity > 0:
        price = f'৳{product.price:,.0f}'
        if product.discount_percent:
            price += f' (আগে ৳{product.compare_price:,.0f}, {product.discount_percent}% ছাড়)'
        link = absolute_storefront_link(shop, 'storefront_product_detail', product.id)
        return (f'{hello}\n\n{product.name}\nদাম: {price}\n\n'
                f'অর্ডার করতে এখানে চাপুন 👉 {link}\n\nকোনো প্রশ্ন থাকলে এখানেই লিখুন।')
    link = absolute_storefront_link(shop)
    if product:
        return (f'{hello}\n\n"{product.name}" এই মুহূর্তে স্টকে নেই। আমাদের অন্য প্রোডাক্ট দেখুন আর অর্ডার করুন '
                f'👉 {link}')
    return f'{hello}\n\nআমাদের সব প্রোডাক্ট দেখতে আর অর্ডার করতে এখানে চাপুন 👉 {link}\n\nকোনো প্রশ্ন থাকলে এখানেই লিখুন।'


PUBLIC_REPLY_TEXT = 'ইনবক্স চেক করুন, বিস্তারিত পাঠানো হয়েছে ✅'


# ---------------------------------------------------------------- webhook ইভেন্ট
def handle_payload(payload):
    """Meta-র পাঠানো পুরো ইভেন্ট। ফেরত দেয় কয়টা কমেন্টে উত্তর গেছে।"""
    if not isinstance(payload, dict) or payload.get('object') != 'page':
        return 0
    replied = 0
    for entry in payload.get('entry') or []:
        page_id = str(entry.get('id') or '')
        for change in entry.get('changes') or []:
            if change.get('field') == 'feed':
                replied += int(handle_comment(page_id, change.get('value') or {}))
    return replied


def handle_comment(page_id, value):
    from .models import FacebookCommentReply, FacebookPageConnection
    from .plans import has_facebook, storefront_is_open

    if value.get('item') != 'comment' or value.get('verb') != 'add':
        return False
    comment_id, post_id = str(value.get('comment_id') or ''), str(value.get('post_id') or '')
    sender = value.get('from') or {}
    if not comment_id or not post_id:
        return False
    if str(sender.get('id') or '') == page_id:        # পেইজের নিজের কমেন্ট (আমাদের উত্তরও)
        return False
    if value.get('parent_id') and str(value['parent_id']) != post_id:   # শুধু মূল কমেন্ট, রিপ্লাই না
        return False

    connection = (FacebookPageConnection.objects.select_related('shop')
                  .filter(page_id=page_id, is_active=True).first())
    if connection is None or not connection.comment_bot_enabled:
        return False
    shop = connection.shop
    if not has_facebook(shop) or shop.is_locked or not storefront_is_open(shop):
        return False

    commenter_id = str(sender.get('id') or '')
    if commenter_id and FacebookCommentReply.objects.filter(page_id=page_id, post_id=post_id,
                                                            commenter_id=commenter_id, status='sent').exists():
        return False   # একই পোস্টে একই মানুষকে একবারই
    if FacebookCommentReply.objects.filter(comment_id=comment_id).exists():
        return False   # Meta একই ইভেন্ট আবার পাঠিয়েছে
    try:
        with transaction.atomic():
            record = FacebookCommentReply.objects.create(shop=shop, page_id=page_id, post_id=post_id,
                                                         comment_id=comment_id, commenter_id=commenter_id,
                                                         commenter_name=(sender.get('name') or '')[:150],
                                                         message=(value.get('message') or '')[:500])
    except IntegrityError:
        return False   # একই মুহূর্তে দুবার এসেছে

    token = connection.page_access_token
    product = find_product(shop, value.get('message'), post_message(post_id, token))
    ok, result = send_private_reply(page_id, token, comment_id,
                                    build_private_message(shop, product, sender.get('name') or ''))
    record.product = product
    record.status = 'sent' if ok else 'failed'
    record.error = '' if ok else str(result)[:300]
    record.save(update_fields=['product', 'status', 'error'])
    if ok and connection.public_reply_enabled:
        send_public_reply(comment_id, token, PUBLIC_REPLY_TEXT)
    if not ok:
        logger.warning('Private reply failed (page %s, comment %s): %s', page_id, comment_id, result)
    return ok
