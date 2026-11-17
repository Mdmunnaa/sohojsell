"""
পাতা ক্র্যাশ করলে মালিক যেন নিজে থেকে জানতে পারেন (Sentry-র মতো, কিন্তু নিজের ভেতরেই — বাইরের অ্যাকাউন্ট লাগে না)।

ErrorReportMiddleware.process_exception: ভুলের ধরন, পাতা, কোন লাইন, traceback → ErrorEvent। একই ভুল (ধরন + জায়গা)
আবার হলে নতুন সারি না, গোনা বাড়ে। নতুন ভুল বা "ঠিক হয়েছে" চিহ্নের পর আবার ফিরলে superuser-দের ফোনে SMS,
ঘণ্টায় সর্বোচ্চ একটা। কাস্টমারের তথ্য জমা হয় না: ফর্মের মান, কুকি বা প্রশ্ন-অংশ লেখা হয় না — শুধু পাতার পথ।
রিপোর্ট করতে গিয়ে নিজে ভুল করলে চুপ থাকে; আসল ভুলটা Django আগের মতোই সামলায়।
"""
import hashlib
import logging
import traceback as tb

from django.conf import settings
from django.http import Http404
from django.core.exceptions import PermissionDenied, SuspiciousOperation

logger = logging.getLogger(__name__)
SMS_GAP_SECONDS = 60 * 60


def record(request, exc):
    from django.db.models import F
    from django.utils import timezone
    from .models import ErrorEvent
    frames = tb.extract_tb(exc.__traceback__)
    base = str(settings.BASE_DIR)
    ours = [f for f in frames if f.filename.startswith(base)] or frames      # আমাদের নিজের কোডের শেষ লাইন
    last = ours[-1] if ours else None
    where = f'{last.filename.replace(base, "").lstrip("/")}:{last.lineno} ({last.name})' if last else ''
    kind = type(exc).__name__
    fingerprint = hashlib.sha1(f'{kind}|{where}'.encode()).hexdigest()
    shop = getattr(getattr(request, 'user', None), 'shop', None) if getattr(request, 'user', None) is not None \
        and request.user.is_authenticated else None
    text = ''.join(tb.format_exception(type(exc), exc, exc.__traceback__))[-6000:]
    event, created = ErrorEvent.objects.get_or_create(fingerprint=fingerprint, defaults={
        'kind': kind[:120], 'message': str(exc)[:500], 'path': request.path[:300], 'method': request.method[:8],
        'where': where[:300], 'traceback': text, 'shop_label': (shop.name if shop else '')[:200]})
    came_back = False
    if not created:
        came_back = event.resolved
        ErrorEvent.objects.filter(pk=event.pk).update(
            count=F('count') + 1, last_seen=timezone.now(), resolved=False, message=str(exc)[:500],
            path=request.path[:300], method=request.method[:8], traceback=text,
            shop_label=(shop.name if shop else '')[:200])
    if created or came_back:
        _alert(event)
    return event


def _alert(event):
    from accounts.forms import normalize_bd_mobile
    from django.contrib.auth import get_user_model
    from . import ratelimit, sms
    if ratelimit.too_many('error-sms', 'all', 1, SMS_GAP_SECONDS):
        return
    site = getattr(settings, 'SITE_NAME', 'SellPunch')
    text = f'{site}: {event.path} পাতায় ত্রুটি ({event.kind})। Master HQ-র "ত্রুটি" পাতায় দেখুন।'
    for raw in get_user_model().objects.filter(is_superuser=True, is_active=True).values_list('phone_number', flat=True):
        phone = normalize_bd_mobile(raw)
        if phone:
            sms.notify(phone, text)


class ErrorReportMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if isinstance(exception, (Http404, PermissionDenied, SuspiciousOperation)):
            return None
        try:
            record(request, exception)
        except Exception:    # noqa: BLE001 — রিপোর্ট না হলেও আসল ভুলের উত্তর যেন যায়
            logger.exception('error report failed')
        return None
