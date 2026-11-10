"""
নিজের ডোমেইন (যেমন www.rahimfashion.com) দোকানের ওয়েবসাইটে লাগানো।

সেলার ডোমেইনের DNS-এ CNAME দেয় → এখান থেকে "যাচাই" করলে DNS মিলেছে কিনা দেখা হয়।
Cloudflare for SaaS-এর টোকেন (CLOUDFLARE_API_TOKEN + CLOUDFLARE_ZONE_ID) থাকলে
হোস্টনেমটা নিজে থেকে Cloudflare-এ যোগ হয় আর SSL চালু হয়; না থাকলে (Render) মালিক হাতে যোগ করে "চালু" করেন।
"""
import logging
import socket

from django.conf import settings
from django.utils import timezone

from .models import Shop

log = logging.getLogger(__name__)


def cname_target():
    """সেলার তার ডোমেইনের CNAME যেখানে পয়েন্ট করবে।"""
    base = getattr(settings, 'STORE_BASE_DOMAIN', '') or 'sellpunch.com'
    return getattr(settings, 'CUSTOM_DOMAIN_TARGET', '') or f'shops.{base}'


def _ips(host):
    try:
        return {info[4][0] for info in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)}
    except (socket.gaierror, OSError, UnicodeError):
        return set()


def dns_points_here(domain, target=None):
    """
    ডোমেইনটা আমাদের দিকে আসছে কিনা: ডোমেইনের IP আর CNAME target-এর IP মিললে True।
    (CNAME সরাসরি পড়তে dnspython লাগে; IP মেলানোই যথেষ্ট — Cloudflare-এর proxy হলে IP এক থাকে।)
    """
    target_ips = _ips(target or cname_target())
    if not target_ips:
        primary = getattr(settings, 'PRIMARY_HOST', None) or getattr(settings, 'RENDER_EXTERNAL_HOSTNAME', None)
        target_ips = _ips(primary) if primary else set()
    domain_ips = _ips(domain)
    return bool(domain_ips) and bool(domain_ips & target_ips)


def cloudflare_ready():
    return bool(getattr(settings, 'CLOUDFLARE_API_TOKEN', '') and getattr(settings, 'CLOUDFLARE_ZONE_ID', ''))


def cloudflare_add_hostname(domain):
    """Cloudflare for SaaS: custom hostname যোগ (SSL নিজে হয়)। ফেরত: (সফল, বার্তা)।"""
    import requests
    zone, token = settings.CLOUDFLARE_ZONE_ID, settings.CLOUDFLARE_API_TOKEN
    try:
        response = requests.post(
            f'https://api.cloudflare.com/client/v4/zones/{zone}/custom_hostnames',
            json={'hostname': domain, 'ssl': {'method': 'http', 'type': 'dv', 'settings': {'min_tls_version': '1.2'}}},
            headers={'Authorization': f'Bearer {token}'}, timeout=15)
        data = response.json()
    except Exception as exc:                      # noqa: BLE001 — নেটওয়ার্ক/JSON যাই হোক, সেলারকে একটা বার্তা
        log.warning('cloudflare custom hostname failed for %s: %s', domain, exc)
        return False, 'Cloudflare-এর সাথে যোগাযোগ করা যায়নি, একটু পরে আবার চেষ্টা করুন।'
    if data.get('success'):
        return True, 'ডোমেইন যোগ হয়েছে, কয়েক মিনিটের মধ্যে SSL চালু হয়ে যাবে।'
    errors = data.get('errors') or []
    if any(e.get('code') == 1406 for e in errors):   # already exists
        return True, 'ডোমেইনটা আগেই যোগ করা আছে।'
    text = '; '.join(e.get('message', '') for e in errors) or 'অজানা সমস্যা'
    log.warning('cloudflare custom hostname error for %s: %s', domain, text)
    return False, f'Cloudflare: {text}'


def verify(shop):
    """সেলার "যাচাই করুন" চাপলে। অবস্থা বদলে সেভ করে; ফেরত: (ঠিক আছে কিনা, বার্তা)।"""
    domain = (shop.custom_domain or '').strip().lower()
    now = timezone.now()
    if not domain:
        return False, 'আগে ডোমেইনটা লিখে সেভ করুন।'
    if not dns_points_here(domain):
        Shop.objects.filter(pk=shop.pk).update(custom_domain_status=Shop.DOMAIN_PENDING, custom_domain_checked_at=now,
                                               custom_domain_note='')
        return False, (f'{domain} এখনো আমাদের দিকে আসছে না। DNS-এ CNAME ঠিকমতো দিয়েছেন কিনা দেখুন; '
                       'DNS বদলাতে কখনো ১–২ ঘণ্টা লাগে।')
    status, note = Shop.DOMAIN_DNS_OK, ''
    if cloudflare_ready():
        ok, note = cloudflare_add_hostname(domain)
        if ok:
            status = Shop.DOMAIN_LIVE
    Shop.objects.filter(pk=shop.pk).update(custom_domain_status=status, custom_domain_checked_at=now,
                                           custom_domain_note=note[:200])
    shop.custom_domain_status, shop.custom_domain_note = status, note
    if status == Shop.DOMAIN_LIVE:
        return True, f'{domain} চালু হয়ে গেছে। ' + note
    return True, (f'DNS ঠিক আছে। {domain} চালু করতে আমরা SSL বসিয়ে দিচ্ছি, সাধারণত ২৪ ঘণ্টার মধ্যে হয়ে যায়। '
                  'হয়ে গেলে SMS পাবেন।')


def pending_for_master():
    """মালিকের প্যানেলে: DNS মিলেছে কিন্তু এখনো চালু করা হয়নি এমন ডোমেইন।"""
    return Shop.objects.filter(custom_domain__isnull=False, custom_domain_status=Shop.DOMAIN_DNS_OK).exclude(custom_domain='')


def mark_live(shop):
    Shop.objects.filter(pk=shop.pk).update(custom_domain_status=Shop.DOMAIN_LIVE, custom_domain_checked_at=timezone.now())
    from .shop_payments import _notify_seller
    _notify_seller(shop, f'আপনার ডোমেইন {shop.custom_domain} চালু হয়ে গেছে। এখন কাস্টমাররা এই ঠিকানায় আপনার দোকান পাবে। - SellPunch')
