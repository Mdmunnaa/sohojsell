"""
IndexNow — নতুন বা বদলানো পাতার খবর Bing (আর Yandex, Seznam, Naver)-কে সাথে সাথে দেওয়া।
ChatGPT আর Copilot-এর ওয়েব সার্চ Bing-এর ফল দেখে উত্তর দেয়, তাই নতুন পাতা তাড়াতাড়ি সেখানে পৌঁছানো দরকার।

- চাবি: INDEXNOW_KEY (env) বা SECRET_KEY থেকে বানানো ৩২ অক্ষর; https://<ডোমেইন>/<চাবি>.txt-এ থাকে (views.indexnow_key)।
- রোজ cron (views_cron) ডাকে: sitemap আর llms.txt-এর ছাপ আগেরবারের থেকে বদলালে তবেই সব পাতার ঠিকানা পাঠায়।
- শুধু আসল ডোমেইনে (STORE_BASE_DOMAIN বসানো থাকলে) চলে।
"""
import hashlib
import logging
import re
from html import unescape

import requests
from django.conf import settings

logger = logging.getLogger(__name__)
ENDPOINT = 'https://api.indexnow.org/indexnow'
TIMEOUT = 15


def key():
    configured = (getattr(settings, 'INDEXNOW_KEY', '') or '').strip().lower()
    if re.fullmatch(r'[0-9a-f]{32}', configured):
        return configured
    return hashlib.sha256(('indexnow:' + settings.SECRET_KEY).encode()).hexdigest()[:32]


def submit(request):
    """পাতাগুলো বদলে থাকলে IndexNow-এ পাঠায়। ফেরত: cron-এর ফলাফলে লেখার মতো ছোট dict।"""
    from . import seo
    from .models import MasterSetting
    domain = (getattr(settings, 'STORE_BASE_DOMAIN', '') or '').strip().lower()
    if not domain:
        return {'skipped': 'no domain'}
    sitemap = seo.main_sitemap_xml(request)
    fingerprint = hashlib.sha256((sitemap + seo.main_llms_txt(request)).encode()).hexdigest()
    setting, _ = MasterSetting.objects.get_or_create(id=1)
    urls = [unescape(url) for url in re.findall(r'<loc>([^<]+)</loc>', sitemap)][:10000]
    if setting.indexnow_fingerprint == fingerprint:
        return {'unchanged': len(urls)}
    body = {'host': domain, 'key': key(), 'keyLocation': f'https://{domain}/{key()}.txt', 'urlList': urls}
    try:
        response = requests.post(ENDPOINT, json=body, timeout=TIMEOUT,
                                 headers={'Content-Type': 'application/json; charset=utf-8'})
    except requests.RequestException as exc:
        logger.warning('IndexNow failed: %s', exc)
        return {'error': str(exc)[:120]}
    if response.status_code not in (200, 202):
        logger.warning('IndexNow refused (%s): %s', response.status_code, response.text[:200])
        return {'error': response.status_code}
    MasterSetting.objects.filter(pk=setting.pk).update(indexnow_fingerprint=fingerprint)
    return {'sent': len(urls)}
