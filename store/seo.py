# store/seo.py
"""
দোকানের ওয়েবসাইটের পেইজের শিরোনাম, বিবরণ আর Facebook/WhatsApp-এ লিংক শেয়ার করলে যে ছবি-লেখা আসে
(Open Graph)। টেমপ্লেটে store/storefront/_head.html এগুলো বসায়।
"""
import re
from urllib.parse import quote

from .links import storefront_link


def clean_text(text, limit=160):
    text = re.sub(r'\s+', ' ', text or '').strip()
    if len(text) > limit:
        text = text[:limit - 1].rsplit(' ', 1)[0] + '…'
    return text


def file_url(request, field):
    """ছবির পুরো লিংক (R2-তে থাকলে আগে থেকেই https://..., লোকালে /media/... হলে ডোমেইন জুড়ে দেওয়া)।"""
    if not field:
        return ''
    try:
        url = field.url
    except ValueError:
        return ''
    return url if url.startswith('http') else request.build_absolute_uri(url)


def letter_favicon(shop):
    """লোগো না থাকলে দোকানের রঙে নামের প্রথম অক্ষর দিয়ে ফেভিকন।"""
    letter = (shop.name or '?').strip()[:1].upper() or '?'
    svg = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'>"
           f"<rect width='64' height='64' rx='16' fill='{shop.theme['primary']}'/>"
           "<text x='32' y='44' font-size='34' font-family='Arial,sans-serif' font-weight='700' "
           f"text-anchor='middle' fill='#fff'>{letter}</text></svg>")
    return 'data:image/svg+xml,' + quote(svg)


def storefront_meta(request, shop, *, title, description='', image=None, image_size=None,
                    link_name='storefront_home', link_args=(), og_type='website', price=None,
                    noindex=False):
    url = request.build_absolute_uri(storefront_link(shop, link_name, *link_args, request=request))
    image_url = file_url(request, image)
    if not image_url:
        banner = shop.banners.filter(is_active=True).order_by('-id').first()
        image_url = file_url(request, banner.image if banner else None) or file_url(request, shop.logo)
        image_size = None
    logo_url = file_url(request, shop.logo)
    return {
        'title': title,
        'description': clean_text(description or shop.storefront_tagline
                                  or f'{shop.name}-এর অনলাইন শপ। পছন্দের প্রোডাক্ট বেছে ঘরে বসে অর্ডার করুন।'),
        'url': url,
        'image': image_url,
        'image_width': image_size[0] if image_size and all(image_size) else None,
        'image_height': image_size[1] if image_size and all(image_size) else None,
        'type': og_type,
        'price': f'{price:.2f}' if price is not None else '',
        'favicon': logo_url or letter_favicon(shop),
        'touch_icon': logo_url,
        'noindex': noindex,
    }


# ---------------------------------------------------------------- Google-এর জন্য: sitemap, robots, structured data
def sitemap_xml(shop, request):
    """দোকানের সব পাতা: হোম, ক্যাটাগরি, প্রোডাক্ট (স্টকে থাকা, চালু)।"""
    from django.utils.html import escape
    from .models import Category, Product
    base = request.build_absolute_uri('/').rstrip('/')

    def absolute(path):
        return path if path.startswith('http') else base + path

    rows = [(absolute(storefront_link(shop, request=request)), 'daily', '1.0', None)]
    for category in Category.objects.filter(shop=shop, product__is_active=True, product__stock_quantity__gt=0).distinct():
        rows.append((absolute(storefront_link(shop, 'storefront_category', category.id, request=request)), 'weekly', '0.7', None))
    for product in Product.objects.filter(shop=shop, is_active=True, stock_quantity__gt=0).only('id', 'created_at'):
        rows.append((absolute(storefront_link(shop, 'storefront_product_detail', product.id, request=request)),
                     'weekly', '0.8', product.created_at.date().isoformat()))
    rows.append((absolute(storefront_link(shop, 'storefront_track', request=request)), 'monthly', '0.3', None))
    body = ''.join(
        f'<url><loc>{escape(loc)}</loc>' + (f'<lastmod>{mod}</lastmod>' if mod else '')
        + f'<changefreq>{freq}</changefreq><priority>{pri}</priority></url>' for loc, freq, pri, mod in rows)
    return f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>'


def robots_txt(shop, request):
    sitemap = request.build_absolute_uri(storefront_link(shop, 'storefront_sitemap', request=request))
    return ('User-agent: *\nAllow: /\nDisallow: /place-order/\nDisallow: /order/\nDisallow: /t/\n'
            'Disallow: /checkout-draft/\n' + f'Sitemap: {sitemap}\n')


def product_ld(request, shop, product, meta, rating=None):
    """Google-এর প্রোডাক্ট কার্ড (দাম, স্টক, রেটিং) — product_detail পেইজে JSON-LD।"""
    import json
    data = {
        '@context': 'https://schema.org', '@type': 'Product', 'name': product.name,
        'description': meta['description'], 'url': meta['url'],
        'brand': {'@type': 'Brand', 'name': shop.name},
        'offers': {'@type': 'Offer', 'url': meta['url'], 'priceCurrency': 'BDT', 'price': f'{product.price:.2f}',
                   'availability': 'https://schema.org/InStock' if product.stock_quantity > 0
                   else 'https://schema.org/OutOfStock',
                   'seller': {'@type': 'Organization', 'name': shop.name}},
    }
    if meta.get('image'):
        data['image'] = [meta['image']]
    if product.category_id:
        data['category'] = product.category.name
    if rating and rating.get('count'):
        data['aggregateRating'] = {'@type': 'AggregateRating', 'ratingValue': str(rating['avg']),
                                   'reviewCount': rating['count'], 'bestRating': '5', 'worstRating': '1'}
    return json.dumps(data, ensure_ascii=False)


def shop_ld(request, shop, meta):
    """হোম পেইজে দোকানের পরিচয় (Google-এর নলেজ প্যানেল আর সার্চে সাইটের নাম)।"""
    import json
    data = {'@context': 'https://schema.org', '@type': 'OnlineStore', 'name': shop.name, 'url': meta['url'],
            'description': meta['description']}
    if meta.get('favicon') and not meta['favicon'].startswith('data:'):
        data['logo'] = meta['favicon']
    if meta.get('image'):
        data['image'] = meta['image']
    if shop.phone:
        data['telephone'] = shop.phone
    if shop.address:
        data['address'] = {'@type': 'PostalAddress', 'streetAddress': shop.address, 'addressCountry': 'BD'}
    same_as = [link for link in (shop.facebook_page_url, shop.instagram_link, shop.youtube_link) if link]
    if same_as:
        data['sameAs'] = same_as
    return json.dumps(data, ensure_ascii=False)


def breadcrumb_ld(request, shop, crumbs):
    """[(নাম, লিংক), ...] → BreadcrumbList।"""
    import json
    return json.dumps({'@context': 'https://schema.org', '@type': 'BreadcrumbList', 'itemListElement': [
        {'@type': 'ListItem', 'position': index, 'name': name, 'item': request.build_absolute_uri(link)}
        for index, (name, link) in enumerate(crumbs, start=1)]}, ensure_ascii=False)
