"""
চেষ্টার সীমা (লগইন, চেকআউট, অর্ডার খোঁজা) — সব সার্ভার-প্রসেস মিলিয়ে একটাই গোনা, তাই ডাটাবেসের ক্যাশে
(settings.CACHES['ratelimit'], টেবিল sp_ratelimit — migration 0061 বানায়)। ক্যাশ না চললে কাউকে আটকায় না।
"""
import logging

from django.core.cache import caches

logger = logging.getLogger(__name__)


def client_ip(request):
    """Cloudflare Worker আসল IP-টা X-Forwarded-For-এ বসায় (cloudflare/src/index.ts); একাধিক থাকলে শেষেরটা।"""
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    return (forwarded.split(',')[-1].strip() if forwarded else request.META.get('REMOTE_ADDR', '')) or 'unknown'


def _key(scope, ident):
    return f'rl:{scope}:{str(ident)[:80]}'.replace(' ', '_')


def count(scope, ident):
    try:
        return caches['ratelimit'].get(_key(scope, ident), 0)
    except Exception:    # noqa: BLE001 — সীমা গোনা না গেলে সাইট যেন না থামে
        logger.exception('ratelimit read failed')
        return 0


def blocked(scope, ident, limit):
    return count(scope, ident) >= limit


def hit(scope, ident, window_seconds):
    """একবার গোনা। প্রথমবারের সময় থেকে window_seconds পর আবার শূন্য।"""
    try:
        cache = caches['ratelimit']
        key = _key(scope, ident)
        if not cache.add(key, 1, window_seconds):
            try:
                cache.incr(key)
            except ValueError:
                cache.set(key, 1, window_seconds)
    except Exception:    # noqa: BLE001
        logger.exception('ratelimit write failed')


def too_many(scope, ident, limit, window_seconds):
    """সীমা পার হলে True; না হলে একবার গুনে False।"""
    if blocked(scope, ident, limit):
        return True
    hit(scope, ident, window_seconds)
    return False


def clear(scope, ident):
    try:
        caches['ratelimit'].delete(_key(scope, ident))
    except Exception:    # noqa: BLE001
        logger.exception('ratelimit clear failed')
