# store/facebook_bot.py
"""
Facebook পেইজের কমেন্ট থেকে অর্ডার।

কীভাবে কাজ করে:
1. সেলার পেইজ কানেক্ট করলে পেইজটা আমাদের অ্যাপের "feed" webhook-এ subscribe হয়।
2. কেউ পোস্টে কমেন্ট করলে Meta /facebook/webhook/-এ খবর পাঠায় (X-Hub-Signature-256 দিয়ে সই করা)।
3. পোস্টের লেখায় বা কমেন্টে প্রোডাক্ট কোড (যেমন #P12) থাকলে সেই প্রোডাক্ট, না থাকলে দোকানের লিংক।
4. কমেন্টকারীর ইনবক্সে Private Reply যায় (প্রতি কমেন্টে একবারই, ৭ দিনের মধ্যে) আর চাইলে
   কমেন্টের নিচে ছোট একটা উত্তর: "ইনবক্স চেক করুন"।

5. সেলার চাইলে: কমেন্টে ফোন নম্বর থাকলে কমেন্টটা লুকায় (অন্য দোকান যেন নম্বর না নেয়, ইনবক্সে উত্তর ঠিকই যায়),
   লিংকওয়ালা বা সেলারের তালিকার শব্দওয়ালা কমেন্ট লুকায় (এগুলোতে ইনবক্সে কিছু যায় না)।
6. ইনবক্সের লিংকে ?fb=c<রেকর্ড> চিহ্ন থাকে (store/fb_ref.py) — সেই লিংক থেকে অর্ডার হলে কোন পোস্ট বিক্রি আনল জানা যায়।
Messenger-এর মেসেজ (একই webhook-এ আসে) store/messenger.py দেখে।

Meta-র নিয়ম: Private Reply — POST /{page-id}/messages, recipient = {"comment_id": ...}।
লাগবে pages_messaging, pages_manage_metadata, pages_read_engagement; কমেন্টে উত্তর দিতে/লুকাতে pages_manage_engagement।
"""
import hashlib
import hmac
import logging
import random
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


def _get(path, token, params=None):
    try:
        response = requests.get(f'{GRAPH_API}/{path}', params={**(params or {}), 'access_token': token}, timeout=TIMEOUT)
        data = response.json()
    except (requests.RequestException, ValueError):
        return None
    return data if response.status_code == 200 and isinstance(data, dict) else None


SUBSCRIBED_FIELDS = 'feed,messages,messaging_postbacks,message_echoes'
BOT_TAG = 'sp-bot'     # আমাদের পাঠানো মেসেজের চিহ্ন — Meta ফেরত দেখালে (echo) বুঝি মানুষ না, বট লিখেছে


def subscribe_page(page_id, page_token):
    """পেইজের কমেন্ট আর Messenger-এর খবর যেন আমাদের webhook-এ আসে।"""
    ok, result = _post(f'{page_id}/subscribed_apps', page_token, data={'subscribed_fields': SUBSCRIBED_FIELDS})
    if not ok:
        # Messenger-এর অনুমতি (pages_messaging) Meta এখনো না দিলে পুরোটা আটকায় — তখন অন্তত কমেন্ট চালু থাকুক
        logger.warning('Facebook subscribe failed for page %s: %s', page_id, result)
        ok, result = _post(f'{page_id}/subscribed_apps', page_token, data={'subscribed_fields': 'feed'})
        if not ok:
            logger.warning('Facebook feed-only subscribe failed for page %s: %s', page_id, result)
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
                 json={'recipient': {'comment_id': comment_id}, 'message': {'text': text, 'metadata': BOT_TAG}})


def hide_comment(comment_id, page_token):
    return _post(comment_id, page_token, data={'is_hidden': 'true'})


BN_DIGITS = str.maketrans('০১২৩৪৫৬৭৮৯', '0123456789')
# মাঝে ফাঁকা/ড্যাশ/ডট থাকলেও (০১৭১২-৩৪৫ ৬৭৮, +88 01712 345678); আগে-পরে অন্য সংখ্যা থাকলেও আলাদা ধরে (123 01712345678)
PHONE_RE = re.compile(r'(?<!\d)(?:\+?88[\s.\-]*)?(0[\s.\-]*1[\s.\-]*[3-9](?:[\s.\-]*\d){8})(?!\d)')


def phone_match(text):
    """লেখার ভেতর প্রথম মোবাইল নম্বর: (01XXXXXXXXX, match) — না পেলে ('', None)।"""
    match = PHONE_RE.search((text or '').translate(BN_DIGITS))
    return (re.sub(r'\D', '', match.group(1)), match) if match else ('', None)


LINK_RE = re.compile(r'https?://|www\.|(?<![@\w])[a-z0-9-]{2,}\.(?:com|net|org|xyz|info|top|me|ly|io|shop|online|site|link|click|bd)'
                     r'(?![a-z0-9])', re.IGNORECASE)


def has_phone(text):
    """বাংলা-ইংরেজি সংখ্যা, মাঝে ফাঁকা বা ড্যাশ থাকলেও (০১৭১২-৩৪৫ ৬৭৮)।"""
    return bool(phone_match(text)[0])


def word_list(raw):
    return [w.strip().lower() for w in re.split(r'[,\n،]', raw or '') if w.strip()]


def hide_reason(connection, text):
    """কমেন্টটা লুকাতে হবে কেন — 'word', 'link', 'phone' বা ''।"""
    lower = (text or '').lower()
    if connection.hide_words and any(word in lower for word in word_list(connection.hide_words)):
        return 'word'
    if connection.hide_link_comments and LINK_RE.search(lower):
        return 'link'
    if connection.hide_phone_comments and has_phone(text):
        return 'phone'
    return ''


def public_reply_text(connection):
    lines = [line.strip() for line in (connection.public_reply_texts or '').splitlines() if line.strip()]
    if lines:
        return random.choice(lines)[:500]
    from . import sf_lang
    return sf_lang.t(PUBLIC_REPLY_TEXT, connection.shop)


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


def build_private_message(shop, product, commenter_name='', *, intro='', ref_id=None, chat_order=False):
    """কমেন্টকারীর ইনবক্সে যা যায় — দোকানের ওয়েবসাইটের ভাষায় (বাংলা বা English)।"""
    from . import fb_ref, sf_lang
    from .links import absolute_storefront_link

    def t(text, **values):
        return sf_lang.t(text, shop, **values)
    first = commenter_name.split()[0] if commenter_name else ''
    if intro:
        hello = intro.replace('{name}', first).strip()
    else:
        hello = t('আসসালামু আলাইকুম{name}! {shop}-এ কমেন্ট করার জন্য ধন্যবাদ।', name=' ' + first if first else '',
                  shop=shop.name)

    def tagged(link):
        return fb_ref.tag(link, 'c', ref_id) if ref_id else link
    ask = t('কোনো প্রশ্ন থাকলে এখানেই লিখুন।')
    if product and product.stock_quantity > 0:
        price = f'৳{product.price:,.0f}'
        if product.discount_percent:
            price += t(' (আগে {old}, {n}% ছাড়)', old=f'৳{product.compare_price:,.0f}', n=str(product.discount_percent))
        link = tagged(absolute_storefront_link(shop, 'storefront_product_detail', product.id))
        chat = '\n' + t('এখানেই অর্ডার করতে লিখুন: অর্ডার P{id}', id=str(product.id)) if chat_order else ''
        return (f'{hello}\n\n{product.name}\n' + t('দাম: {price}', price=price) + '\n\n'
                + t('অর্ডার করতে এই লিংকে চাপুন: {link}', link=link) + f'{chat}\n\n{ask}')
    link = tagged(absolute_storefront_link(shop))
    if product:
        return f'{hello}\n\n' + t('"{name}" এই মুহূর্তে স্টকে নেই। আমাদের অন্য প্রোডাক্ট দেখুন আর অর্ডার করুন {link}',
                                    name=product.name, link=link)
    return f'{hello}\n\n' + t('আমাদের সব প্রোডাক্ট দেখতে আর অর্ডার করতে এই লিংকে চাপুন: {link}', link=link) + f'\n\n{ask}'


PUBLIC_REPLY_TEXT = 'ইনবক্স চেক করুন, বিস্তারিত পাঠানো হয়েছে।'


# ---------------------------------------------------------------- webhook ইভেন্ট
def handle_payload(payload):
    """Meta-র পাঠানো পুরো ইভেন্ট। ফেরত দেয় কয়টা কমেন্টে উত্তর গেছে।"""
    if not isinstance(payload, dict) or payload.get('object') != 'page':
        return 0
    from . import messenger
    replied = 0
    for entry in payload.get('entry') or []:
        page_id = str(entry.get('id') or '')
        for change in entry.get('changes') or []:
            if change.get('field') == 'feed':
                replied += int(handle_comment(page_id, change.get('value') or {}))
        for event in entry.get('messaging') or []:
            try:
                replied += int(messenger.handle_event(page_id, event))
            except Exception:     # একটা মেসেজের সমস্যায় বাকিগুলো যেন আটকে না যায়
                logger.exception('Messenger event failed (page %s)', page_id)
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
    # কারো কমেন্টের নিচে রিপ্লাই: ইনবক্সে কিছু যায় না, শুধু লুকানোর নিয়ম খাটে
    is_reply = bool(value.get('parent_id')) and str(value['parent_id']) != post_id

    connection = (FacebookPageConnection.objects.select_related('shop')
                  .filter(page_id=page_id, is_active=True).first())
    if connection is None:
        return False
    shop = connection.shop
    if not has_facebook(shop) or shop.is_locked or not storefront_is_open(shop):
        return False
    message = value.get('message') or ''
    reason = hide_reason(connection, message)
    if (is_reply or not connection.comment_bot_enabled) and not reason:
        return False

    commenter_id = str(sender.get('id') or '')
    already = bool(commenter_id) and FacebookCommentReply.objects.filter(
        page_id=page_id, post_id=post_id, commenter_id=commenter_id, status='sent').exists()
    if already and not reason:
        return False   # একই পোস্টে একই মানুষকে একবারই
    if FacebookCommentReply.objects.filter(comment_id=comment_id).exists():
        return False   # Meta একই ইভেন্ট আবার পাঠিয়েছে
    try:
        with transaction.atomic():
            record = FacebookCommentReply.objects.create(shop=shop, page_id=page_id, post_id=post_id,
                                                         comment_id=comment_id, commenter_id=commenter_id,
                                                         commenter_name=(sender.get('name') or '')[:150],
                                                         message=message[:500])
    except IntegrityError:
        return False   # একই মুহূর্তে দুবার এসেছে

    token = connection.page_access_token
    if reason:
        hidden, result = hide_comment(comment_id, token)
        record.hidden_reason = reason if hidden else ''
        if not hidden:
            record.error = f'লুকানো যায়নি: {result}'[:300]
            logger.warning('Hiding comment failed (page %s, comment %s): %s', page_id, comment_id, result)
    # স্প্যাম/নিষিদ্ধ শব্দ হলে, বট বন্ধ থাকলে বা আগেই উত্তর গেলে ইনবক্সে কিছু যায় না
    if reason in ('word', 'link') or not connection.comment_bot_enabled or already or is_reply:
        record.status = 'skipped'
        record.save(update_fields=['status', 'hidden_reason', 'error'])
        return False

    from . import shop_payments
    product = find_product(shop, message, post_message(post_id, token))
    chat_order = (connection.messenger_bot_enabled and connection.messenger_order_enabled
                  and shop_payments.CHOICE_COD in shop_payments.checkout_choices(shop))
    ok, result = send_private_reply(page_id, token, comment_id,
                                    build_private_message(shop, product, sender.get('name') or '',
                                                          intro=connection.comment_dm_intro, ref_id=record.id,
                                                          chat_order=chat_order))
    record.product = product
    record.status = 'sent' if ok else 'failed'
    if not ok:
        record.error = str(result)[:300]
    record.save(update_fields=['product', 'status', 'error', 'hidden_reason'])
    # লুকানো কমেন্টের নিচে উত্তর দিলে সেটা আবার সবার চোখে পড়ে, তাই তখন না
    if ok and connection.public_reply_enabled and not record.hidden_reason:
        send_public_reply(comment_id, token, public_reply_text(connection))
    if not ok:
        logger.warning('Private reply failed (page %s, comment %s): %s', page_id, comment_id, result)
    return ok
