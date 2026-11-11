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
    logger.info('daily cron: %s', result)
    return JsonResponse(result)
