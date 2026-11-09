# store/links.py
"""
দোকানের ওয়েবসাইটের লিংক এক জায়গা থেকে বানানো।

ডেটাবেসের ভেতরের রাস্তা এখনো /shop/<সাবডোমেইন>/... (urls.py), কিন্তু কাস্টমার সেটা দেখবে না:
- STORE_BASE_DOMAIN বসানো থাকলে লিংক হয় https://<সাবডোমেইন>.<ডোমেইন>/product/5/
- দোকানের নিজের সাবডোমেইনে থাকলে শুধু /product/5/ (একই সাইটের ভেতরের লিংক)
- ডোমেইন বসানোর আগে (এখনকার Render ঠিকানায়) /shop/<সাবডোমেইন>/product/5/
"""
from django.conf import settings
from django.urls import reverse


def base_domain():
    return getattr(settings, 'STORE_BASE_DOMAIN', '') or ''


def internal_prefix(slug):
    return f'/shop/{slug}'


def storefront_path(shop, name='storefront_home', *args):
    """দোকানের নিজের সাইটের ভেতরের রাস্তা: '/', '/product/5/', '/place-order/'।"""
    full = reverse(name, args=[shop.slug, *args])
    prefix = internal_prefix(shop.slug)
    if full == prefix + '/' or full.startswith(prefix + '/'):
        return full[len(prefix):] or '/'
    return full


def shop_origin(shop):
    """https://<সাবডোমেইন>.<ডোমেইন> — ডোমেইন বসানো না থাকলে None।"""
    base = base_domain()
    return f'https://{shop.slug}.{base}' if base else None


def storefront_link(shop, name='storefront_home', *args, request=None):
    """
    কাস্টমারকে দেখানোর মতো লিংক। request দিলে আর সেটা দোকানের নিজের সাইট (সাবডোমেইন বা নিজের ডোমেইন)
    থেকে এলে ছোট লিংক ফেরত দেয়।
    """
    if request is not None and getattr(request, 'storefront_shop_id', None) == shop.pk:
        return storefront_path(shop, name, *args)
    origin = shop_origin(shop)
    if origin:
        return origin + storefront_path(shop, name, *args)
    return reverse(name, args=[shop.slug, *args])


def absolute_storefront_link(shop, name='storefront_home', *args):
    """Facebook মেসেজের মতো বাইরে পাঠানোর জন্য পুরো লিংক (https://...)।"""
    link = storefront_link(shop, name, *args)
    if link.startswith('http'):
        return link
    site = getattr(settings, 'SITE_URL', '') or ''
    if not site:
        host = getattr(settings, 'PRIMARY_HOST', None) or 'sellpunch.com'
        site = f'https://{host}'
    return site.rstrip('/') + link
