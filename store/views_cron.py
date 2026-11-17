"""
দিনে একবারের কাজ — Cloudflare Worker-এর cron ডাকে (cloudflare/src/index.ts → scheduled, সকাল ১০টা)।
গোপন CRON_SECRET (Worker আর কন্টেইনার দুজনেই একই Secret পায়) না মিললে পাতাটা নেই (404)।
Cloudflare ছাড়া অন্য কোথাও চালাতে: python manage.py due_reminders
"""
import hmac
import logging

from django.conf import settings
from django.http import Http404, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def cron_daily(request):
    secret = getattr(settings, 'CRON_SECRET', '')
    if not secret or not hmac.compare_digest(secret.encode(), request.headers.get('X-Cron-Secret', '').encode()):
        raise Http404
    result = {}
    try:
        from . import dues
        sent = dues.run_auto_reminders()        # বাকির অটো-তাগাদা (যেসব দোকানে চালু)
        result['due_reminders'] = {'shops': len(sent), 'sms': sum(sent.values())}
    except Exception as exc:    # noqa: BLE001 — একটা কাজ আটকালেও উত্তর যাক, লগে কারণ থাকুক
        logger.exception('daily cron: due reminders failed')
        result['due_reminders'] = {'error': str(exc)[:200]}
    try:
        from . import retention
        result['expiry_warnings'] = retention.send_expiry_warnings()    # মেয়াদ শেষে ৭/৩০/৬০/৮০ দিনে মোছার সতর্কবার্তা
    except Exception as exc:    # noqa: BLE001
        logger.exception('daily cron: expiry warnings failed')
        result['expiry_warnings'] = {'error': str(exc)[:200]}
    try:
        from django.core.management import call_command
        call_command('optimize_images', limit=200)   # পুরনো প্রোডাক্টের ছবি ছোট করা (দোকানের পাতা দ্রুত খোলে)
        result['optimize_images'] = 'ok'
    except Exception as exc:    # noqa: BLE001
        logger.exception('daily cron: optimize_images failed')
        result['optimize_images'] = str(exc)[:200]
    try:
        from . import messenger
        result['facebook_pages'] = messenger.refresh_pages()   # webhook-এর ঘটনা আর Messenger-এর সাজ আবার বসানো
    except Exception as exc:    # noqa: BLE001
        logger.exception('daily cron: facebook refresh failed')
        result['facebook_pages'] = str(exc)[:200]
    try:
        from . import views_import
        result['imports'] = views_import.daily_cleanup()      # থেমে যাওয়া ছবি আবার, পুরনো কাজ মোছা
    except Exception as exc:    # noqa: BLE001
        logger.exception('daily cron: import cleanup failed')
        result['imports'] = str(exc)[:200]
    try:
        from . import indexnow
        result['indexnow'] = indexnow.submit(request)   # পাতা বদলালে Bing-কে খবর (ChatGPT/Copilot Bing দেখে)
    except Exception as exc:    # noqa: BLE001
        logger.exception('daily cron: indexnow failed')
        result['indexnow'] = str(exc)[:200]
    try:
        from . import shop_payments
        result['unpaid_orders_cancelled'] = shop_payments.cancel_unpaid_orders()   # টাকা না দেওয়া অনলাইন অর্ডার, স্টক ফেরত
    except Exception as exc:    # noqa: BLE001
        logger.exception('daily cron: unpaid orders failed')
        result['unpaid_orders_cancelled'] = str(exc)[:200]
    try:
        result['cleanup'] = cleanup_old_rows()      # মেয়াদ শেষ সেশন আর পুরনো ভিজিটের সারি — ডাটাবেস যেন না ফোলে
    except Exception as exc:    # noqa: BLE001
        logger.exception('daily cron: cleanup failed')
        result['cleanup'] = str(exc)[:200]
    logger.info('daily cron: %s', result)
    return JsonResponse(result)


PAGE_VIEW_KEEP_DAYS = 90


def cleanup_old_rows():
    """মেয়াদ পেরোনো সেশন (ওয়েবসাইটের প্রতিটা ভিজিটর/বটের একটা করে জমে) আর ৯০ দিনের পুরনো ভিজিটের হিসাব মোছা।"""
    from datetime import timedelta
    from django.contrib.sessions.models import Session
    from django.utils import timezone
    from .models import PageView
    now = timezone.now()
    sessions, _ = Session.objects.filter(expire_date__lt=now).delete()
    views, _ = PageView.objects.filter(created_at__lt=now - timedelta(days=PAGE_VIEW_KEEP_DAYS)).delete()
    return {'sessions': sessions, 'page_views': views}
