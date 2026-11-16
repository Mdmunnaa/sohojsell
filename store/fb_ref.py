"""
Facebook থেকে কোন অর্ডার এল তার হিসাব।

বটের পাঠানো প্রতিটা লিংকের শেষে ?fb=<চিহ্ন> থাকে: c<কমেন্ট-রেকর্ড> বা m<Messenger-কাস্টমার>, সাথে সই (কেউ বানিয়ে
অন্যের নামে বসাতে পারে না)। কাস্টমার লিংকে ঢুকলে চিহ্নটা তার সেশনে ৭ দিন থাকে; সেই সময়ের মধ্যে ওয়েবসাইটে অর্ডার দিলে
অর্ডারে লেখা থাকে কোথা থেকে এসেছে — "Facebook থেকে বিক্রি"-র হিসাব আর Messenger-এ অর্ডারের খবর পাঠানো এখান থেকেই।
"""
import hashlib
import hmac
import re
import time

from django.conf import settings

PARAM = 'fb'
SESSION_KEY = 'fb_ref'
MAX_AGE = 7 * 24 * 3600
REF_RE = re.compile(r'^([cm])(\d{1,12})\.([0-9a-f]{10})$')


def _sign(value):
    return hmac.new(settings.SECRET_KEY.encode(), f'fbref:{value}'.encode(), hashlib.sha256).hexdigest()[:10]


def make(kind, object_id):
    value = f'{kind}{object_id}'
    return f'{value}.{_sign(value)}'


def tag(url, kind, object_id):
    """লিংকের শেষে চিহ্ন বসায়।"""
    return f"{url}{'&' if '?' in url else '?'}{PARAM}={make(kind, object_id)}"


def parse(raw):
    match = REF_RE.match(str(raw or ''))
    if not match:
        return None
    kind, object_id, signature = match.groups()
    if not hmac.compare_digest(signature, _sign(f'{kind}{object_id}')):
        return None
    return kind, int(object_id)


class FacebookRefMiddleware:
    """লিংকে ?fb= থাকলে সেশনে রাখে (শুধু তখনই সেশন ছোঁয়, অন্য সময় কিছু করে না)।"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        raw = request.GET.get(PARAM)
        if raw and hasattr(request, 'session') and parse(raw):
            request.session[SESSION_KEY] = {'v': raw, 't': int(time.time())}
        return self.get_response(request)


def from_session(request, shop):
    """অর্ডারে বসানোর মতো তথ্য: {'fb_source', 'fb_post_id', 'messenger_contact'} — না থাকলে {}।"""
    from .models import FacebookCommentReply, MessengerContact
    saved = getattr(request, 'session', {}).get(SESSION_KEY) if hasattr(request, 'session') else None
    if not isinstance(saved, dict) or time.time() - int(saved.get('t') or 0) > MAX_AGE:
        return {}
    parsed = parse(saved.get('v'))
    if not parsed:
        return {}
    kind, object_id = parsed
    if kind == 'c':
        record = FacebookCommentReply.objects.filter(pk=object_id, shop=shop).only('post_id').first()
        return {'fb_source': 'comment', 'fb_post_id': record.post_id} if record else {}
    contact = MessengerContact.objects.filter(pk=object_id, shop=shop).first()
    return {'fb_source': 'messenger', 'messenger_contact': contact} if contact else {}
