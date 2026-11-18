"""
Messenger বট — দোকানের Facebook পেইজের ইনবক্সে কাস্টমার লিখলে নিজে থেকে উত্তর।

কী কী করে:
- প্রথম মেসেজে স্বাগত জানায়, নিচে বাটন: প্রোডাক্ট দেখুন · দাম জানতে চাই · ডেলিভারি চার্জ · অর্ডার কোথায়? · দোকানে কথা বলুন
- সেলারের নিজের প্রশ্ন-উত্তর (FacebookAutoReply) আগে; না মিললে দোকানের তথ্য থেকে উত্তর: ডেলিভারি চার্জ, পেমেন্ট,
  ঠিকানা, ফোন, রিটার্ন, প্রোডাক্টের দাম (কোড P12 বা আগের আলোচনার প্রোডাক্ট), অর্ডার কোথায় আছে
- চ্যাটেই অর্ডার: কয়টা → নাম → মোবাইল → ঠিকানা → এলাকা → মিলিয়ে কনফার্ম। অর্ডার তৈরি হয় ওয়েবসাইটের চেকআউটের
  একই রাস্তায় (store/storefront_orders.py) — দাম, স্টক, ব্লক করা নম্বর সব একই নিয়মে।
- কাস্টমার "মানুষের সাথে কথা" চাইলে, ছবি পাঠালে বা বট না বুঝলে: দোকানদারের জন্য "উত্তরের অপেক্ষায়" দেখায়।
  দোকানদার নিজে Page Inbox থেকে উত্তর দিলে (Meta echo পাঠায়, আমাদের চিহ্ন ছাড়া) বট ১২ ঘণ্টা চুপ থাকে।
- দোকান বন্ধের সময়ে (সেলার ঠিক করলে) দিনে একবার জানায় কখন উত্তর পাবে।
- অর্ডারের অবস্থা বদলালে (কনফার্ম, কুরিয়ারে, ডেলিভারি, বাতিল) Messenger-এ খবর — কাস্টমারের শেষ মেসেজের
  ২৪ ঘণ্টার মধ্যে হলে। তার পরে আর যায় না (SMS চালু থাকলে SMS যায়)।

Meta-র নিয়ম: কাস্টমারের শেষ মেসেজের ২৪ ঘণ্টার মধ্যে যেকোনো উত্তর দেওয়া যায়; তার পরে কিছু না। আগে
POST_PURCHASE_UPDATE ট্যাগ দিয়ে ২৪ ঘণ্টা পরেও অর্ডারের খবর যেত, কিন্তু Meta ২৭ এপ্রিল ২০২৬ থেকে এই ট্যাগ
(CONFIRMED_EVENT_UPDATE আর ACCOUNT_UPDATE-ও) বন্ধ করেছে — পাঠালে error 100। এর বদলে Meta-র "utility message"
টেমপ্লেট আছে (আগে Meta-র অনুমোদন লাগে), সেটা এখানে নেই। সবাইকে একসাথে প্রচারের মেসেজ (ব্রডকাস্ট) পাঠানো যায়
না — এখানে সেরকম কিছু নেই।
"""
import logging
import re
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from . import facebook_bot, fb_ref, sf_lang

logger = logging.getLogger(__name__)

PAUSE = timedelta(hours=12)            # দোকানদার নিজে কথা বললে বট এতক্ষণ চুপ
FALLBACK_GAP = timedelta(hours=6)      # "বুঝিনি" জাতীয় উত্তর এর চেয়ে ঘনঘন না
STATE_TTL = timedelta(hours=3)         # চ্যাটে অর্ডারের মাঝপথে এতক্ষণ চুপ থাকলে নতুন করে শুরু
WINDOW = timedelta(hours=24)           # Meta-র ২৪ ঘণ্টার নিয়ম
BURST_WINDOW, BURST_MAX = timedelta(minutes=10), 25   # অন্য কোনো বটের সাথে অবিরাম কথা চালাচালি ঠেকাতে
MAX_QR, QR_TITLE = 13, 20              # Meta: সর্বোচ্চ ১৩টা বাটন, প্রতিটার লেখা ২০ অক্ষর
CARD_TEXT, BUTTON_TEXT = 80, 20

P_START, P_MENU, P_PRODUCTS, P_PRICE = 'SP_START', 'SP_MENU', 'SP_PRODUCTS', 'SP_PRICE'
P_DELIVERY, P_TRACK, P_HUMAN, P_CANCEL, P_CONFIRM = 'SP_DELIVERY', 'SP_TRACK', 'SP_HUMAN', 'SP_CANCEL', 'SP_CONFIRM'
P_ORDER, P_VARIANT, P_QTY, P_NAME, P_ZONE = 'SP_ORDER:', 'SP_VAR:', 'SP_QTY:', 'SP_NAME', 'SP_ZONE:'

BN_DIGITS = str.maketrans('০১২৩৪৫৬৭৮৯', '0123456789')

# কোন শব্দে কোন বিষয় — আগেরটা আগে দেখা হয় ("ডেলিভারি চার্জ কত টাকা" → ডেলিভারি, দাম না)
TOPICS = [
    ('human', ['মানুষ', 'কথা বলতে', 'কথা বলব', 'কথা বলা', 'এডমিন', 'অ্যাডমিন', 'admin', 'agent', 'human',
               'call me', 'কল দিন', 'ফোন দিন', 'ফোন করুন', 'কল করুন']),
    ('track', ['অর্ডার কোথায়', 'অর্ডারের অবস্থা', 'অর্ডার কই', 'ট্র্যাক', 'ট্রাক', 'track', 'পার্সেল', 'parcel',
               'কবে পাব', 'কবে আসবে', 'এখনো পাইনি', 'পাইনি', 'order status']),
    ('order', ['অর্ডার করতে চাই', 'অর্ডার করব', 'অর্ডার দিব', 'অর্ডার দেব', 'অর্ডার দিতে', 'নিতে চাই', 'নিব', 'নেব',
               'কিনতে চাই', 'কিনব', 'order', 'অর্ডার']),
    ('delivery', ['ডেলিভারি', 'ডেলিভারী', 'delivery', 'চার্জ', 'charge', 'shipping', 'কত দিনে', 'কতদিনে',
                  'হোম ডেলিভারি', 'কুরিয়ার']),
    ('payment', ['পেমেন্ট', 'payment', 'বিকাশ', 'bkash', 'নগদ', 'nagad', 'রকেট', 'rocket', 'ক্যাশ অন', 'cash on',
                 'cod', 'অগ্রিম', 'advance', 'টাকা কিভাবে', 'টাকা কীভাবে']),
    ('location', ['ঠিকানা', 'address', 'location', 'লোকেশন', 'কোথায় আপনারা', 'দোকান কোথায়', 'শোরুম', 'showroom']),
    ('contact', ['ফোন নম্বর', 'ফোন নাম্বার', 'নাম্বার', 'নম্বর দিন', 'number', 'phone', 'whatsapp', 'হোয়াটসঅ্যাপ',
                 'মোবাইল নম্বর']),
    ('return', ['রিটার্ন', 'return', 'ফেরত', 'exchange', 'এক্সচেঞ্জ', 'বদলে', 'পরিবর্তন']),
    ('products', ['প্রোডাক্ট', 'product', 'কালেকশন', 'collection', 'ওয়েবসাইট', 'website', 'লিংক', 'link',
                  'আর কী আছে', 'আর কি আছে', 'ক্যাটালগ', 'catalog']),
    ('price', ['দাম', 'দাম কত', 'price', 'প্রাইস', 'কত টাকা', 'pp', 'dam', 'daam', 'rate', 'রেট']),
    ('thanks', ['ধন্যবাদ', 'thanks', 'thank you', 'thank u', 'থ্যাংকস', 'tnx']),
    ('greeting', ['আসসালামু', 'সালাম', 'assalamu', 'salam', 'হ্যালো', 'hello', 'hi', 'hey', 'হাই']),
]
CANCEL_WORDS = ['বাতিল', 'cancel', 'বাদ দিন', 'লাগবে না', 'থাক', 'না থাক']
YES_WORDS = ['হ্যাঁ', 'হ্যা', 'হা', 'জি', 'yes', 'ha', 'haa', 'ok', 'okay', 'ঠিক আছে', 'কনফার্ম', 'confirm']
NO_WORDS = ['না', 'no', 'বাতিল', 'cancel']


# ---------------------------------------------------------------- লেখা মেলানো
def normalize(text):
    return re.sub(r'\s+', ' ', (text or '').translate(BN_DIGITS).lower()).strip()


def _has(text, word):
    """ইংরেজি ছোট শব্দ (hi, pp, cod) পুরো শব্দ হিসেবে মিলতে হবে; বাংলা লেখার ভেতরে থাকলেই চলে।"""
    if word.isascii():
        return re.search(r'(?<![a-z0-9])' + re.escape(word) + r'(?![a-z0-9])', text) is not None
    return word in text


def topic_of(text):
    for key, words in TOPICS:
        if any(_has(text, word) for word in words):
            return key
    return ''


def match_faq(shop, text):
    """সেলারের প্রশ্ন-উত্তর: সবচেয়ে বেশি (আর লম্বা) শব্দ মেলে যেটায়।"""
    from .models import FacebookAutoReply
    best, score = None, (0, 0)
    for reply in FacebookAutoReply.objects.filter(shop=shop, is_active=True):
        hits = [word for word in reply.keyword_list() if _has(text, normalize(word))]
        if hits and (len(hits), max(map(len, hits))) > score:
            best, score = reply, (len(hits), max(map(len, hits)))
    return best


def find_phone(text):
    from .facebook_bot import phone_match
    return phone_match(text)[0]


def find_number(text, skip=''):
    """অর্ডার নম্বর বা পরিমাণ: মোবাইল নম্বর বাদ দিয়ে প্রথম ১–৯ অঙ্কের সংখ্যা।"""
    from .facebook_bot import phone_match
    plain = (text or '').translate(BN_DIGITS)
    _phone, match = phone_match(plain)
    if match:
        plain = plain[:match.start()] + ' ' + plain[match.end():]
    match = re.search(r'(?<!\d)(\d{1,9})(?!\d)', plain)
    return int(match.group(1)) if match else None


def _money(value):
    value = Decimal(value or 0)
    return f'৳{value:,.0f}' if value == value.to_integral_value() else f'৳{value:,.2f}'


def _short(text, limit):
    text = (text or '').strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '…'


# ---------------------------------------------------------------- Meta-তে পাঠানো
def in_window(contact, now=None):
    now = now or timezone.now()
    return bool(contact.last_in_at) and now - contact.last_in_at < WINDOW


def send(connection, contact, message):
    """
    একটা মেসেজ (dict: text/quick_replies বা attachment) — শুধু কাস্টমারের শেষ মেসেজের ২৪ ঘণ্টার মধ্যে।
    সব মেসেজে আমাদের চিহ্ন (metadata) — Meta ফেরত দেখালে (echo) বুঝি এটা বট, দোকানদার না।
    """
    if not in_window(contact):
        return False
    body = {'recipient': {'id': contact.psid}, 'message': {**message, 'metadata': facebook_bot.BOT_TAG},
            'messaging_type': 'RESPONSE'}
    ok, result = facebook_bot._post(f'{connection.page_id}/messages', connection.page_access_token, json=body)
    if ok:
        contact.last_out_at = timezone.now()
    else:
        logger.warning('Messenger send failed (page %s, psid %s): %s', connection.page_id, contact.psid, result)
    return ok


def text_message(text, quick=None, *, ask_phone=False):
    message = {'text': _short(text, 2000)}
    replies = []
    if ask_phone:
        replies.append({'content_type': 'user_phone_number'})
    for title, payload in (quick or [])[:MAX_QR - len(replies)]:
        replies.append({'content_type': 'text', 'title': _short(title, QR_TITLE), 'payload': payload[:1000]})
    if replies:
        message['quick_replies'] = replies
    return message


def _absolute(shop, url):
    if not url or url.startswith('http'):
        return url
    from .links import absolute_storefront_link
    origin = absolute_storefront_link(shop).split('/', 3)
    return f'{origin[0]}//{origin[2]}{url}' if len(origin) >= 3 else url


def product_cards(connection, contact, products):
    """ছবিসহ প্রোডাক্টের কার্ড (একসাথে সর্বোচ্চ ১০টা): দাম, "ওয়েবসাইটে দেখুন", চাইলে "এখানেই অর্ডার"।"""
    from .links import absolute_storefront_link
    shop = connection.shop
    chat_order = can_chat_order(connection)
    elements = []
    for product in products[:10]:
        link = fb_ref.tag(absolute_storefront_link(shop, 'storefront_product_detail', product.id), 'm', contact.id)
        price = _money(product.price)
        if product.discount_percent:
            price += sf_lang.t(' ({n}% ছাড়)', shop, n=product.discount_percent)
        stock = sf_lang.t('স্টকে আছে', shop) if product.stock_quantity > 0 else sf_lang.t('স্টক শেষ', shop)
        element = {'title': _short(product.name, CARD_TEXT), 'subtitle': _short(f'{price} · {stock} · P{product.id}', CARD_TEXT),
                   'default_action': {'type': 'web_url', 'url': link},
                   'buttons': [{'type': 'web_url', 'url': link, 'title': _short(sf_lang.t('ওয়েবসাইটে দেখুন', shop), BUTTON_TEXT)}]}
        image = _absolute(shop, product.thumb_url)
        if image:
            element['image_url'] = image
        if chat_order and product.stock_quantity > 0:
            element['buttons'].append({'type': 'postback', 'title': _short(sf_lang.t('এখানেই অর্ডার করুন', shop), BUTTON_TEXT),
                                       'payload': f'{P_ORDER}{product.id}'})
        elements.append(element)
    if not elements:
        return None
    return {'attachment': {'type': 'template', 'payload': {'template_type': 'generic', 'elements': elements}}}


def can_chat_order(connection):
    from . import shop_payments
    return (connection.messenger_order_enabled
            and shop_payments.CHOICE_COD in shop_payments.checkout_choices(connection.shop))


def is_open(connection, now=None):
    """দোকান খোলা কিনা (সেলার সময় না দিলে সবসময় খোলা)।"""
    start, end = connection.open_time, connection.close_time
    if not start or not end or start == end:
        return True
    current = timezone.localtime(now or timezone.now()).time()
    return start <= current < end if start < end else current >= start or current < end


def _clock(value, shop):
    """১০:০০ → "সকাল ১০টা", ২০:৩০ → "রাত ৮:৩০" (ইংরেজি দোকানে 8:30 PM)।"""
    if sf_lang.lang_of(shop) == sf_lang.EN:
        return value.strftime('%I:%M %p').lstrip('0')
    hour = value.hour % 12 or 12
    part = 'রাত' if value.hour < 5 or value.hour >= 20 else 'সকাল' if value.hour < 12 else 'দুপুর' if value.hour < 15 \
        else 'বিকেল' if value.hour < 18 else 'সন্ধ্যা'
    time = f'{hour}:{value.minute:02d}' if value.minute else f'{hour}টা'
    return f'{part} {sf_lang.num(time)}'


def hours_text(connection):
    shop = connection.shop
    if connection.offhours_text:
        return connection.offhours_text
    if connection.open_time and connection.close_time:
        return sf_lang.t('আমরা প্রতিদিন {start} থেকে {end} পর্যন্ত উত্তর দিই। আপনার মেসেজ পেয়েছি, খোলার পর উত্তর পাবেন।', shop,
                         start=_clock(connection.open_time, shop), end=_clock(connection.close_time, shop))
    return ''


# ---------------------------------------------------------------- ইভেন্ট
def handle_event(page_id, event):
    """webhook-এর entry.messaging[]-এর একটা ঘটনা। কিছু পাঠালে True।"""
    from .models import FacebookPageConnection, MessengerContact
    from .plans import has_facebook, storefront_is_open

    message = event.get('message') or {}
    if message.get('is_echo'):
        return handle_echo(page_id, event)
    postback = event.get('postback') or {}
    if not message and not postback:
        return False          # পড়া হয়েছে, পৌঁছেছে, রিঅ্যাকশন — এগুলোতে কিছু করার নেই
    psid = str((event.get('sender') or {}).get('id') or '')
    if not psid or psid == page_id:
        return False
    connection = (FacebookPageConnection.objects.select_related('shop')
                  .filter(page_id=page_id, is_active=True).first())
    if connection is None:
        return False
    shop = connection.shop
    if not has_facebook(shop) or shop.is_locked or not storefront_is_open(shop):
        return False
    mid = str(message.get('mid') or postback.get('mid') or '')
    now = timezone.now()
    with transaction.atomic():
        # একই কাস্টমারের দুটো মেসেজ একসাথে এলেও একটার পর একটা (চ্যাট-অর্ডারের ধাপ গোলমাল না হয়)
        contact, _ = MessengerContact.objects.select_for_update().get_or_create(
            page_id=page_id, psid=psid, defaults={'shop': shop})
        seen = [m for m in contact.recent_mids.split(',') if m]
        if mid and mid in seen:
            return False          # Meta একই মেসেজ আবার পাঠিয়েছে
        if mid:
            contact.recent_mids = ','.join((seen + [mid])[-8:])[-600:]
        contact.shop = shop
        contact.last_in_at = now
        incoming = message.get('text') or postback.get('title') or ('[ছবি/ফাইল]' if message.get('attachments') else '')
        contact.last_text = _short(incoming, 300)
        if not contact.name:
            profile = facebook_bot._get(psid, connection.page_access_token, {'fields': 'first_name,last_name'})
            if profile:
                contact.name = _short(' '.join(x for x in (profile.get('first_name'), profile.get('last_name')) if x), 150)
        sent = Bot(connection, contact, now).respond(message, postback)
        contact.save()
    return sent


def handle_echo(page_id, event):
    """পেইজ থেকে যাওয়া মেসেজ। আমাদের চিহ্ন না থাকলে দোকানদার নিজে লিখেছে → বট চুপ, "অপেক্ষায়" তালিকা থেকে বাদ।"""
    from .models import MessengerContact
    message = event.get('message') or {}
    if message.get('metadata') == facebook_bot.BOT_TAG:
        return False
    psid = str((event.get('recipient') or {}).get('id') or '')
    if not psid:
        return False
    now = timezone.now()
    MessengerContact.objects.filter(page_id=page_id, psid=psid).update(
        bot_paused_until=now + PAUSE, waiting_since=None, last_out_at=now, state='', state_data={})
    return False


class Bot:
    def __init__(self, connection, contact, now):
        self.connection, self.contact, self.now = connection, contact, now
        self.shop = connection.shop

    def t(self, text, **values):
        return sf_lang.t(text, self.shop, **values)

    # ---------------------------------------------------------- পাঠানো
    def say(self, text, quick=None, *, ask_phone=False):
        return self.send(text_message(text, quick, ask_phone=ask_phone))

    def send(self, message):
        contact = self.contact
        if contact.burst_start is None or self.now - contact.burst_start > BURST_WINDOW:
            contact.burst_start, contact.burst_count = self.now, 0
        if contact.burst_count >= BURST_MAX:
            return False
        contact.burst_count += 1
        return send(self.connection, contact, message)

    def menu(self):
        items = [(self.t('প্রোডাক্ট দেখুন'), P_PRODUCTS), (self.t('দাম জানতে চাই'), P_PRICE),
                 (self.t('ডেলিভারি চার্জ'), P_DELIVERY), (self.t('অর্ডার কোথায়?'), P_TRACK),
                 (self.t('দোকানে কথা বলুন'), P_HUMAN)]
        return items

    def wait_for_human(self):
        if self.contact.waiting_since is None:
            self.contact.waiting_since = self.now

    # ---------------------------------------------------------- মূল সিদ্ধান্ত
    def respond(self, message, postback):
        connection, contact = self.connection, self.contact
        if not connection.messenger_bot_enabled:
            self.wait_for_human()
            return False
        if contact.state and (contact.state_at is None or self.now - contact.state_at > STATE_TTL):
            self.clear_state()
        quick = (message.get('quick_reply') or {}).get('payload') or ''
        payload = postback.get('payload') or quick
        text = message.get('text') or ''
        if payload.startswith('SP_'):
            return self.on_payload(payload)          # কাস্টমার নিজে বাটন চাপলে বট থামানো থাকলেও উত্তর
        if payload and not text:
            text = payload                           # ফোন নম্বরের বাটন: payload-এই নম্বর
        if contact.bot_paused_until and contact.bot_paused_until > self.now:
            self.wait_for_human()
            return False
        if message.get('attachments') and not text:
            return self.on_attachment(message['attachments'])
        if not text.strip():
            return False
        if contact.state:
            return self.on_step(text)
        return self.on_text(text)

    def on_text(self, raw):
        from .facebook_bot import find_product
        text = normalize(raw)
        first = self.contact.welcomed_at is None
        reply = match_faq(self.shop, text)
        if reply:
            type(reply).objects.filter(pk=reply.pk).update(hits=reply.hits + 1)
            self.contact.welcomed_at = self.contact.welcomed_at or self.now
            return self.say(reply.answer, self.menu() if first else None)
        product = find_product(self.shop, raw)
        if product:
            self.contact.last_product = product
        topic = topic_of(text)
        if topic == 'human':
            return self.handoff()
        if topic == 'track' or (find_phone(raw) and find_number(raw, find_phone(raw)) and not product):
            return self.track(raw)
        if topic == 'order':
            return self.start_order(product or self.contact.last_product)
        if product:
            return self.show_product(product)
        handler = getattr(self, f'topic_{topic}', None) if topic else None
        if handler:
            self.contact.welcomed_at = self.contact.welcomed_at or self.now
            return handler()
        if first:
            return self.welcome()
        return self.fallback()

    def on_payload(self, payload):
        if payload in (P_START, P_MENU):
            return self.welcome()
        if payload == P_PRODUCTS:
            return self.topic_products()
        if payload == P_PRICE:
            return self.topic_price()
        if payload == P_DELIVERY:
            return self.topic_delivery()
        if payload == P_TRACK:
            return self.track('')
        if payload == P_HUMAN:
            return self.handoff()
        if payload == P_CANCEL:
            return self.cancel_order()
        if payload.startswith(P_ORDER):
            from .models import Product
            product = Product.objects.filter(shop=self.shop, pk=_int(payload[len(P_ORDER):]), is_active=True).first()
            return self.start_order(product)
        if self.contact.state:
            return self.on_step('', payload)
        return self.welcome()

    def on_attachment(self, attachments):
        if all((a.get('payload') or {}).get('sticker_id') for a in attachments):
            return False          # লাইক/স্টিকার
        self.wait_for_human()
        if not is_open(self.connection, self.now):
            return self.offhours()
        if self.contact.fallback_sent_at and self.now - self.contact.fallback_sent_at < FALLBACK_GAP:
            return False          # কয়েকটা ছবি একসাথে পাঠালে প্রতিটায় একই উত্তর না
        self.contact.fallback_sent_at = self.now
        return self.say(self.t('পেয়েছি! দোকানের একজন দেখে শীঘ্রই উত্তর দেবেন। দাম জানতে প্রোডাক্টের কোড (যেমন P12) লিখতে পারেন।'),
                        self.menu())

    # ---------------------------------------------------------- সাধারণ উত্তর
    def welcome(self):
        self.contact.welcomed_at = self.contact.welcomed_at or self.now
        name = (self.contact.name or '').split(' ')[0]
        text = self.connection.welcome_text.replace('{name}', name).strip() if self.connection.welcome_text else \
            self.t('আসসালামু আলাইকুম{name}! {shop}-এ স্বাগতম। কী জানতে চান, নিচে থেকে বেছে নিন বা লিখুন।',
                   name=f' {name}' if name else '', shop=self.shop.name)
        if not is_open(self.connection, self.now) and hours_text(self.connection):
            text += '\n\n' + hours_text(self.connection)
            self.contact.offhours_sent_on = timezone.localdate(self.now)
        return self.say(text, self.menu())

    def fallback(self):
        self.wait_for_human()
        if not is_open(self.connection, self.now):
            return self.offhours()
        if self.contact.fallback_sent_at and self.now - self.contact.fallback_sent_at < FALLBACK_GAP:
            return False          # একই কথা বারবার না — দোকানদার দেখে উত্তর দেবেন
        self.contact.fallback_sent_at = self.now
        return self.say(self.t('আপনার মেসেজ পেয়েছি, দোকানের একজন শীঘ্রই উত্তর দেবেন। এর মধ্যে নিচের থেকে বেছে নিতে পারেন।'),
                        self.menu())

    def offhours(self):
        text = hours_text(self.connection)
        today = timezone.localdate(self.now)
        if not text or self.contact.offhours_sent_on == today:
            return False
        self.contact.offhours_sent_on = today
        return self.say(text, self.menu())

    def handoff(self):
        self.clear_state()
        self.wait_for_human()
        self.contact.bot_paused_until = self.now + PAUSE
        text = self.t('ঠিক আছে, দোকানের একজন শীঘ্রই আপনার সাথে কথা বলবেন।')
        if not is_open(self.connection, self.now) and hours_text(self.connection):
            text += '\n\n' + hours_text(self.connection)
        if self.shop.phone:
            text += '\n' + self.t('জরুরি হলে ফোন করুন: {phone}', phone=self.shop.phone)
        return self.say(text)

    def topic_thanks(self):
        return self.say(self.t('আপনাকেও ধন্যবাদ! আর কিছু জানতে চাইলে লিখুন।'))

    def topic_greeting(self):
        return self.welcome()

    def topic_delivery(self):
        from . import delivery
        shop = self.shop
        zones = delivery.zones_for(shop)
        if zones:
            lines = [f'• {zone.name}: {_money(zone.charge)}' for zone in zones]
        else:
            lines = [self.t('• সারা দেশে: {charge}', charge=_money(shop.delivery_charge or 0))]
        text = self.t('ডেলিভারি চার্জ:') + '\n' + '\n'.join(lines)
        if shop.free_delivery_min:
            text += '\n\n' + self.t('{amount} বা তার বেশি অর্ডারে ডেলিভারি ফ্রি।', amount=_money(shop.free_delivery_min))
        return self.say(text, self.menu())

    def topic_payment(self):
        from . import shop_payments
        choices = shop_payments.checkout_choices(self.shop)
        lines = []
        if shop_payments.CHOICE_COD in choices:
            lines.append(self.t('• ক্যাশ অন ডেলিভারি: পণ্য হাতে পেয়ে টাকা দেবেন'))
        if shop_payments.CHOICE_ADVANCE in choices:
            lines.append(self.t('• ডেলিভারি চার্জ আগে অনলাইনে (bKash, Nagad, Rocket বা কার্ড), বাকিটা পণ্য হাতে পেয়ে'))
        if shop_payments.CHOICE_FULL in choices:
            lines.append(self.t('• পুরো টাকা আগে অনলাইনে: bKash, Nagad, Rocket বা কার্ড'))
        return self.say(self.t('যেভাবে টাকা দিতে পারবেন:') + '\n' + '\n'.join(lines), self.menu())

    def topic_location(self):
        shop = self.shop
        if not shop.address:
            return self.topic_contact()
        text = self.t('আমাদের ঠিকানা: {address}', address=shop.address.strip())
        if shop.phone:
            text += '\n' + self.t('ফোন: {phone}', phone=shop.phone)
        return self.say(text, self.menu())

    def topic_contact(self):
        shop = self.shop
        lines = []
        if shop.phone:
            lines.append(self.t('ফোন: {phone}', phone=shop.phone))
        if shop.whatsapp_number:
            lines.append(f'WhatsApp: {shop.whatsapp_number}')
        if not lines:
            return self.handoff()
        return self.say('\n'.join(lines), self.menu())

    def topic_return(self):
        policy = (self.shop.return_policy or '').strip()
        if not policy:
            return self.handoff()
        text = self.t('রিটার্ন পলিসি:') + '\n' + _short(policy, 900)
        return self.say(text, self.menu())

    def featured(self):
        from .models import Product
        return list(Product.objects.filter(shop=self.shop, is_active=True, stock_quantity__gt=0)
                    .order_by('-id')[:10])

    def topic_products(self):
        from .links import absolute_storefront_link
        link = fb_ref.tag(absolute_storefront_link(self.shop), 'm', self.contact.id)
        cards = product_cards(self.connection, self.contact, self.featured())
        sent = self.send(cards) if cards else False
        return self.say(self.t('সব প্রোডাক্ট দেখতে আর অর্ডার করতে: {link}', link=link), self.menu()) or sent

    def topic_price(self):
        if self.contact.last_product:
            return self.show_product(self.contact.last_product)
        cards = product_cards(self.connection, self.contact, self.featured())
        sent = self.send(cards) if cards else False
        return self.say(self.t('যে প্রোডাক্টের দাম জানতে চান তার কোড লিখুন (যেমন P12) — পোস্টে বা ওয়েবসাইটে কোড দেওয়া থাকে। '
                               'অথবা প্রোডাক্টের ছবি পাঠান, দোকানের একজন জানিয়ে দেবেন।')) or sent

    def show_product(self, product):
        self.contact.last_product = product
        self.contact.welcomed_at = self.contact.welcomed_at or self.now
        cards = product_cards(self.connection, self.contact, [product])
        sent = self.send(cards) if cards else False
        if product.stock_quantity <= 0:
            return self.say(self.t('"{name}" এই মুহূর্তে স্টকে নেই। অন্য প্রোডাক্ট দেখতে "প্রোডাক্ট দেখুন" চাপুন।', name=product.name),
                            self.menu()) or sent
        price = _money(product.price)
        if product.discount_percent:
            price += self.t(' (আগে {old}, {n}% ছাড়)', old=_money(product.compare_price), n=product.discount_percent)
        text = self.t('{name}\nদাম: {price}', name=product.name, price=price)
        quick = [(self.t('এখানেই অর্ডার করুন'), f'{P_ORDER}{product.id}')] if can_chat_order(self.connection) else []
        return self.say(text, quick + self.menu()[:3]) or sent

    # ---------------------------------------------------------- অর্ডার কোথায়
    def track(self, raw):
        from .models import Order
        from . import order_flow
        from .links import absolute_storefront_link
        phone = find_phone(raw)
        number = find_number(raw, phone) if raw else None
        if number and phone:
            self.clear_state()
            order = (Order.objects.filter(shop=self.shop, pk=number, customer__phone=phone).exclude(source='pos')
                     .select_related('customer').first())
            if order is None:
                return self.say(self.t('এই অর্ডার নম্বর আর মোবাইল নম্বর মিলিয়ে কোনো অর্ডার পাওয়া যায়নি। নম্বর দুটো আবার দেখে নিন।'),
                                [(self.t('আবার চেষ্টা'), P_TRACK), (self.t('দোকানে কথা বলুন'), P_HUMAN)])
            return self.say(self.status_text(order), self.menu())
        latest = (Order.objects.filter(shop=self.shop, messenger_contact=self.contact).exclude(source='pos')
                  .order_by('-id').first())
        if latest and not (number or phone):       # Messenger থেকে অর্ডার করে থাকলে নম্বর লাগে না
            return self.say(self.status_text(latest), self.menu())
        self.set_state('track', {})
        link = absolute_storefront_link(self.shop, 'storefront_track')
        return self.say(self.t('অর্ডার নম্বর আর যে মোবাইল নম্বরে অর্ডার করেছেন, দুটোই লিখুন। যেমন: 123 01712345678\n'
                               'অথবা এখানে দেখুন: {link}', link=link))

    def status_text(self, order):
        from . import order_flow
        shop = self.shop
        text = self.t('অর্ডার নং {n}: {status}', n=str(order.id), status=sf_lang.status_label(order.status, shop))
        if order.status == 'Shipped' and order.steadfast_tracking_code:
            courier = (order.courier_partner or '').strip()
            text += '\n' + (self.t('কুরিয়ার: {c}, ট্র্যাকিং কোড: {code}', c=courier, code=order.steadfast_tracking_code)
                            if courier else self.t('ট্র্যাকিং কোড: {code}', code=order.steadfast_tracking_code))
        text += '\n' + self.t('মোট: {total}', total=_money(order.total_amount))
        text += '\n' + self.t('বিস্তারিত: {link}', link=order_flow.track_link(shop, order))
        return text

    # ---------------------------------------------------------- চ্যাটে অর্ডার
    def set_state(self, state, data):
        self.contact.state, self.contact.state_data, self.contact.state_at = state, data, self.now

    def clear_state(self):
        self.contact.state, self.contact.state_data, self.contact.state_at = '', {}, None

    def cancel_order(self):
        had = self.contact.state.startswith('o_')
        self.clear_state()
        return self.say(self.t('ঠিক আছে, অর্ডারটা বাতিল করা হলো।') if had else self.t('ঠিক আছে।'), self.menu())

    def start_order(self, product):
        from .links import absolute_storefront_link
        if product is None or not product.is_active:
            cards = product_cards(self.connection, self.contact, self.featured())
            sent = self.send(cards) if cards else False
            return self.say(self.t('কোন প্রোডাক্টটা নিতে চান? নিচের কার্ডে "এখানেই অর্ডার করুন" চাপুন, '
                                   'বা প্রোডাক্টের কোড লিখুন (যেমন: অর্ডার P12)।')) or sent
        self.contact.last_product = product
        if not can_chat_order(self.connection):
            link = fb_ref.tag(absolute_storefront_link(self.shop, 'storefront_product_detail', product.id), 'm', self.contact.id)
            return self.say(self.t('অর্ডার করতে এই লিংকে চাপুন: {link}', link=link))
        if product.stock_quantity <= 0:
            return self.say(self.t('"{name}" এই মুহূর্তে স্টকে নেই।', name=product.name), self.menu())
        data = {'pid': product.id}
        if product.has_variants:
            options = [v for v in product.variants.all() if v.stock_quantity > 0][:MAX_QR - 1]
            if not options:
                return self.say(self.t('"{name}" এই মুহূর্তে স্টকে নেই।', name=product.name), self.menu())
            self.set_state('o_variant', data)
            return self.say(self.t('"{name}" — কোনটা নেবেন?', name=product.name),
                            [(v.name, f'{P_VARIANT}{v.id}') for v in options] + [(self.t('বাতিল'), P_CANCEL)])
        return self.ask_qty(data)

    def _sellable(self, data):
        from . import variants
        key = -data['vid'] if data.get('vid') else data.get('pid')
        return variants.resolve(self.shop, [key]).get(key) if key else None

    def ask_qty(self, data):
        item = self._sellable(data)
        if item is None or item.stock <= 0:
            self.clear_state()
            return self.say(self.t('প্রোডাক্টটা এখন আর পাওয়া যাচ্ছে না।'), self.menu())
        self.set_state('o_qty', data)
        return self.say(self.t('{name} — {price}\nকয়টা নেবেন?', name=item.name, price=_money(item.price)),
                        [(str(n), f'{P_QTY}{n}') for n in range(1, min(5, int(item.stock)) + 1)] + [(self.t('বাতিল'), P_CANCEL)])

    def ask_name(self, data):
        self.set_state('o_name', data)
        quick = [(self.contact.name, P_NAME)] if self.contact.name else []
        return self.say(self.t('আপনার নাম লিখুন।'), quick + [(self.t('বাতিল'), P_CANCEL)])

    def ask_phone(self, data):
        self.set_state('o_phone', data)
        return self.say(self.t('মোবাইল নম্বর লিখুন (০১ দিয়ে শুরু, ১১ সংখ্যা)।'), [(self.t('বাতিল'), P_CANCEL)], ask_phone=True)

    def ask_address(self, data):
        self.set_state('o_address', data)
        return self.say(self.t('পুরো ঠিকানা লিখুন — বাসা, রোড, এলাকা, থানা, জেলা।'), [(self.t('বাতিল'), P_CANCEL)])

    def ask_zone(self, data):
        from . import delivery
        zones = delivery.zones_for(self.shop)
        if len(zones) <= 1:
            data['zone'] = zones[0].id if zones else None
            return self.summary(data)
        self.set_state('o_zone', data)
        lines = '\n'.join(f'• {zone.name}: {_money(zone.charge)}' for zone in zones)
        return self.say(self.t('ডেলিভারি কোন এলাকায়?') + '\n' + lines,
                        [(zone.name, f'{P_ZONE}{zone.id}') for zone in zones[:MAX_QR - 1]] + [(self.t('বাতিল'), P_CANCEL)])

    def summary(self, data):
        from . import delivery
        item = self._sellable(data)
        if item is None:
            self.clear_state()
            return self.say(self.t('প্রোডাক্টটা এখন আর পাওয়া যাচ্ছে না।'), self.menu())
        qty = int(data['qty'])
        subtotal = item.price * qty
        zone, charge = delivery.charge_for(self.shop, data.get('zone'), subtotal)
        if charge is None:
            return self.ask_zone(data)
        total = subtotal + charge
        self.set_state('o_confirm', data)
        text = '\n'.join([
            self.t('অর্ডারটা মিলিয়ে নিন:'),
            f'{item.name} × {qty} = {_money(subtotal)}',
            self.t('ডেলিভারি{zone}: {charge}', zone=f' ({zone.name})' if zone else '', charge=_money(charge)),
            self.t('মোট: {total} — পণ্য হাতে পেয়ে দেবেন', total=_money(total)),
            '',
            self.t('নাম: {v}', v=data['name']), self.t('মোবাইল: {v}', v=data['phone']), self.t('ঠিকানা: {v}', v=data['address']),
        ])
        return self.say(text, [(self.t('কনফার্ম করুন'), P_CONFIRM), (self.t('বাতিল'), P_CANCEL)])

    def on_step(self, raw, payload=''):
        """চ্যাট-অর্ডারের মাঝে কাস্টমারের উত্তর (লেখা বা বাটন)।"""
        from accounts.forms import normalize_bd_mobile
        from . import delivery, risk
        state, data = self.contact.state, dict(self.contact.state_data or {})
        text = normalize(raw)
        if text and any(_has(text, w) for w in CANCEL_WORDS) and state != 'o_address':
            return self.cancel_order()
        if text and topic_of(text) == 'human':
            return self.handoff()

        if state == 'track':
            if find_phone(raw) and find_number(raw, find_phone(raw)):
                return self.track(raw)
            self.clear_state()
            return self.on_text(raw) if raw else False

        if state == 'o_variant':
            from .models import ProductVariant
            vid = _int(payload[len(P_VARIANT):]) if payload.startswith(P_VARIANT) else None
            variants_qs = ProductVariant.objects.filter(product_id=data.get('pid'), product__shop=self.shop,
                                                        stock_quantity__gt=0)
            variant = variants_qs.filter(pk=vid).first() if vid else next(
                (v for v in variants_qs if normalize(v.name) and normalize(v.name) in text), None)
            if variant is None:
                return self.say(self.t('নিচের থেকে একটা বেছে নিন।'),
                                [(v.name, f'{P_VARIANT}{v.id}') for v in variants_qs[:MAX_QR - 1]] + [(self.t('বাতিল'), P_CANCEL)])
            data['vid'] = variant.id
            return self.ask_qty(data)

        if state == 'o_qty':
            qty = _int(payload[len(P_QTY):]) if payload.startswith(P_QTY) else find_number(raw)
            item = self._sellable(data)
            if item is None:
                self.clear_state()
                return self.say(self.t('প্রোডাক্টটা এখন আর পাওয়া যাচ্ছে না।'), self.menu())
            if not qty or qty < 1 or qty > 99:
                return self.ask_qty(data)
            if qty > item.stock:
                return self.say(self.t('স্টকে আছে মাত্র {n}টা। কয়টা নেবেন?', n=item.stock),
                                [(str(n), f'{P_QTY}{n}') for n in range(1, min(5, int(item.stock)) + 1)])
            data['qty'] = qty
            return self.ask_name(data)

        if state == 'o_name':
            name = self.contact.name if payload == P_NAME else (raw or '').strip()
            if not (2 <= len(name) <= 60) or find_phone(name):
                return self.ask_name(data)
            data['name'] = name[:60]
            return self.ask_phone(data)

        if state == 'o_phone':
            phone = normalize_bd_mobile(find_phone(raw) or raw)
            if not phone:
                return self.say(self.t('নম্বরটা ঠিক নেই। ০১ দিয়ে শুরু ১১ সংখ্যার মোবাইল নম্বর লিখুন।'),
                                [(self.t('বাতিল'), P_CANCEL)], ask_phone=True)
            if risk.is_blocked(self.shop, phone):
                self.clear_state()
                return self.say(self.t('এই নম্বর থেকে এখন অর্ডার নেওয়া যাচ্ছে না। দোকানে সরাসরি যোগাযোগ করুন।'))
            data['phone'] = phone
            return self.ask_address(data)

        if state == 'o_address':
            address = (raw or '').strip()
            if text in [normalize(w) for w in CANCEL_WORDS]:
                return self.cancel_order()
            if len(address) < 8:
                return self.say(self.t('ঠিকানাটা আরেকটু বিস্তারিত লিখুন — বাসা, রোড, এলাকা, থানা, জেলা।'), [(self.t('বাতিল'), P_CANCEL)])
            data['address'] = address[:300]
            return self.ask_zone(data)

        if state == 'o_zone':
            zones = delivery.zones_for(self.shop)
            zone_id = _int(payload[len(P_ZONE):]) if payload.startswith(P_ZONE) else None
            zone = next((z for z in zones if z.id == zone_id), None) or next(
                (z for z in zones if text and (normalize(z.name) in text or text in normalize(z.name))), None)
            if zone is None:
                return self.ask_zone(data)
            data['zone'] = zone.id
            return self.summary(data)

        if state == 'o_confirm':
            if payload == P_CONFIRM or (text and any(_has(text, w) for w in YES_WORDS)):
                return self.place(data)
            if payload == P_CANCEL or (text and any(_has(text, w) for w in NO_WORDS)):
                return self.cancel_order()
            return self.summary(data)

        self.clear_state()
        return self.on_text(raw) if raw else False

    def place(self, data):
        from . import shop_payments, sms, storefront_orders
        key = -data['vid'] if data.get('vid') else data['pid']
        try:
            placed = storefront_orders.place(
                self.shop, quantities={key: int(data['qty'])}, name=data['name'], phone=data['phone'],
                address=data['address'], note=self.t('Messenger-এ চ্যাট করে অর্ডার'), zone_id=data.get('zone'),
                payment_choice=shop_payments.CHOICE_COD, fb_source='chat', messenger_contact=self.contact)
        except storefront_orders.OrderError as exc:
            self.clear_state()
            return self.say(str(exc), self.menu())
        self.clear_state()
        order = placed.order
        if self.shop.sms_on_received:
            sms.send_auto(self.shop, data['phone'], sms.order_received_text(self.shop, order),
                          f'অর্ডার নং {sms.bn_num(order.id)}')
        from . import order_flow
        return self.say(self.t('অর্ডার হয়েছে! অর্ডার নং {n}, মোট {total}। দোকান থেকে শীঘ্রই কনফার্ম করা হবে।\n'
                               'অর্ডারের অবস্থা দেখতে: {link}', n=str(order.id), total=_money(order.total_amount),
                               link=order_flow.track_link(self.shop, order)))


def _int(value):
    try:
        return int(str(value).translate(BN_DIGITS))
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- অর্ডারের খবর
UPDATE_TEXT = {
    'Confirmed': 'আপনার অর্ডার নং {n} কনফার্ম হয়েছে। শীঘ্রই পাঠানো হবে।',
    'Shipped': 'আপনার অর্ডার নং {n} কুরিয়ারে দেওয়া হয়েছে।',
    'Delivered': 'আপনার অর্ডার নং {n} ডেলিভারি হয়েছে। কেনার জন্য ধন্যবাদ!',
    'Cancelled': 'আপনার অর্ডার নং {n} বাতিল করা হয়েছে। কোনো প্রশ্ন থাকলে এখানে লিখুন।',
}


def _connection_for(order):
    from .models import FacebookPageConnection
    from .plans import has_facebook
    contact = order.messenger_contact
    if contact is None:
        return None, None
    connection = FacebookPageConnection.objects.filter(shop_id=order.shop_id, page_id=contact.page_id,
                                                       is_active=True).select_related('shop').first()
    if connection is None or not has_facebook(connection.shop) or connection.shop.is_locked:
        return None, None
    return connection, contact


def order_update(order, status):
    """অর্ডারের অবস্থা বদলালে Messenger-এ খবর (সেলার বন্ধ না রাখলে)। কোনো সমস্যায় অর্ডার আটকায় না।"""
    try:
        template = UPDATE_TEXT.get(status)
        if not template or not order.messenger_contact_id:
            return False
        connection, contact = _connection_for(order)
        if connection is None or not connection.order_updates_enabled:
            return False
        from . import order_flow
        shop = connection.shop
        text = sf_lang.t(template, shop, n=str(order.id))
        if status == 'Shipped':
            if order.steadfast_tracking_code:
                text += '\n' + sf_lang.t('ট্র্যাকিং কোড: {code}', shop, code=order.steadfast_tracking_code)
            text += '\n' + sf_lang.t('কোথায় আছে দেখুন: {link}', shop, link=order_flow.track_link(shop, order))
        ok = send(connection, contact, text_message(text))
        if ok:
            type(contact).objects.filter(pk=contact.pk).update(last_out_at=contact.last_out_at)
        return ok
    except Exception:
        logger.exception('Messenger order update failed (order %s)', getattr(order, 'id', None))
        return False


def order_received(order):
    """Messenger-এর লিংক থেকে ওয়েবসাইটে অর্ডার হলে সাথে সাথে চ্যাটেও জানানো।"""
    try:
        connection, contact = _connection_for(order)
        if connection is None or not connection.order_updates_enabled:
            return False
        from . import order_flow
        shop = connection.shop
        text = sf_lang.t('অর্ডার পেয়েছি! অর্ডার নং {n}, মোট {total}।\nঅর্ডারের অবস্থা দেখতে: {link}', shop,
                         n=str(order.id), total=_money(order.total_amount), link=order_flow.track_link(shop, order))
        ok = send(connection, contact, text_message(text))
        if ok:
            type(contact).objects.filter(pk=contact.pk).update(last_out_at=contact.last_out_at)
        return ok
    except Exception:
        logger.exception('Messenger order received failed (order %s)', getattr(order, 'id', None))
        return False


# ---------------------------------------------------------------- পেইজের Messenger সাজানো
def setup_profile(connection):
    """"শুরু করুন" বাটন, স্বাগত লেখা আর প্রথমবার চ্যাট খুললে দেখানো প্রশ্নগুলো (Ice Breakers)।"""
    shop = connection.shop
    body = {
        'get_started': {'payload': P_START},
        'greeting': [{'locale': 'default', 'text': _short(sf_lang.t(
            '{shop}-এ স্বাগতম! দাম, ডেলিভারি বা অর্ডারের খবর — যা জানতে চান লিখুন।', shop, shop=shop.name), 160)}],
        'ice_breakers': [{'locale': 'default', 'call_to_actions': [
            {'question': sf_lang.t('প্রোডাক্টগুলো দেখতে চাই', shop), 'payload': P_PRODUCTS},
            {'question': sf_lang.t('ডেলিভারি চার্জ কত?', shop), 'payload': P_DELIVERY},
            {'question': sf_lang.t('আমার অর্ডার কোথায়?', shop), 'payload': P_TRACK},
            {'question': sf_lang.t('দোকানের কারো সাথে কথা বলতে চাই', shop), 'payload': P_HUMAN},
        ]}],
    }
    ok, result = facebook_bot._post('me/messenger_profile', connection.page_access_token, json=body)
    if not ok:
        logger.warning('Messenger profile setup failed (page %s): %s', connection.page_id, result)
    return ok


def refresh_pages(limit=300):
    """রোজ একবার (cron): সব চালু পেইজে webhook-এর ঘটনা আর Messenger-এর সাজ ঠিক আছে কিনা — কিছু হারালে আবার বসে।"""
    from .models import FacebookPageConnection
    from .plans import has_facebook
    done = 0
    pages = FacebookPageConnection.objects.filter(is_active=True).exclude(shop__is_demo=True).select_related('shop')
    for connection in pages[:limit]:
        if not has_facebook(connection.shop):
            continue
        facebook_bot.subscribe_page(connection.page_id, connection.page_access_token)
        if connection.messenger_bot_enabled:
            setup_profile(connection)
        done += 1
    return done
