# store/seo.py
"""
দোকানের ওয়েবসাইটের পেইজের শিরোনাম, বিবরণ আর Facebook/WhatsApp-এ লিংক শেয়ার করলে যে ছবি-লেখা আসে
(Open Graph)। টেমপ্লেটে store/storefront/_head.html এগুলো বসায়।
"""
import re
from urllib.parse import quote

from .links import storefront_link
from .sf_lang import t as sf_t


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
                                  or sf_t('{shop}-এর অনলাইন শপ। পছন্দের প্রোডাক্ট বেছে ঘরে বসে অর্ডার করুন।', shop,
                                          shop=shop.name)),
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


# ---------------------------------------------------------------- মূল সাইট (sellpunch.com) — দোকানের না
MAIN_PRIVATE_PATHS = ('/accounts/', '/admin/', '/saas-master/', '/demo/', '/dashboard/', '/setup-shop/', '/pos/',
                      '/orders/', '/products/', '/customers/', '/reports/', '/dues/', '/website/', '/sms/', '/offers/',
                      '/landing/', '/purchases/', '/settings/', '/billing/', '/payment/', '/staff/', '/facebook/',
                      '/internal/')
MAIN_PUBLIC_PAGES = ('about', 'security', 'contact', 'privacy_policy', 'terms', 'refund_policy')


def main_site_url(request):
    """মূল সাইটের আসল ঠিকানা (https://sellpunch.com) — onrender.com থেকে খুললেও Google যেন এটাই ধরে।"""
    from django.conf import settings
    base = getattr(settings, 'STORE_BASE_DOMAIN', '')
    if base:
        return f'https://{base}'
    return (getattr(settings, 'SITE_URL', '') or request.build_absolute_uri('/')).rstrip('/')


def main_robots_txt(request):
    """লগইনের পেছনের পাতা আর ডেমো (ঢুকলেই লগইন হয়) Google ঘুরবে না; সাইনআপ পাতা খোলা।"""
    lines = ['User-agent: *', 'Allow: /', 'Allow: /accounts/signup/']
    lines += [f'Disallow: {path}' for path in MAIN_PRIVATE_PATHS]
    lines.append(f'Sitemap: {main_site_url(request)}/sitemap.xml')
    return '\n'.join(lines) + '\n'


def main_sitemap_xml(request):
    """হোমপেজ, ফিচার আর ব্যবসার ধরনের পাতা (বাংলা + ইংরেজি, একে অপরের hreflang সহ) আর নীতিমালার পাতা।"""
    from django.urls import reverse
    from django.utils.html import escape
    from . import marketing
    base = main_site_url(request)

    def pair(path_bn, path_en, freq, priority):
        url_bn, url_en = base + path_bn, base + path_en
        alternates = ''.join(f'<xhtml:link rel="alternate" hreflang="{lang}" href="{escape(url)}"/>'
                             for lang, url in (('bn', url_bn), ('en', url_en), ('x-default', url_bn)))
        return [f'<url><loc>{escape(url)}</loc>{alternates}<changefreq>{freq}</changefreq><priority>{priority}</priority></url>'
                for url in (url_bn, url_en)]

    rows = pair('/', reverse('landing_page_en'), 'weekly', '1.0')
    rows += pair(reverse('mk_index'), reverse('mk_index_en'), 'weekly', '0.8')
    for kind, page in marketing.all_pages():
        name = 'mk_feature' if kind == 'feature' else 'mk_industry'
        rows += pair(reverse(name, args=[page['slug']]), reverse(name + '_en', args=[page['slug']]), 'monthly', '0.8')
    from . import guides
    rows.append(f'<url><loc>{escape(base + reverse("guide_index"))}</loc><lastmod>{guides.GUIDES_UPDATED}</lastmod>'
                '<changefreq>weekly</changefreq><priority>0.8</priority></url>')
    rows += [f'<url><loc>{escape(base + reverse("guide_detail", args=[g["slug"]]))}</loc><lastmod>{guides.GUIDES_UPDATED}</lastmod>'
             '<changefreq>monthly</changefreq><priority>0.7</priority></url>' for g in guides.all_guides()]
    rows += [f'<url><loc>{escape(base + reverse(name))}</loc><changefreq>monthly</changefreq><priority>0.3</priority></url>'
             for name in MAIN_PUBLIC_PAGES]
    return ('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
            'xmlns:xhtml="http://www.w3.org/1999/xhtml">' + ''.join(rows) + '</urlset>')


def main_llms_txt(request):
    """
    /llms.txt — ChatGPT, Claude, Perplexity-র মতো AI যেন SellPunch কী, দাম কত, কোন পাতায় কী আছে পরিষ্কার বোঝে
    (Edumi-তে একটা কোচিং সেন্টার ChatGPT দেখে এসেছিল)। দাম আর লিমিট কোড থেকে, তাই কখনো পুরনো হয় না।
    """
    from django.conf import settings
    from django.urls import reverse
    from . import marketing
    from .company import COMPANY
    from .payments import PLAN_PRICES, PLAN_YEAR_PRICES
    from .plans import PLAN_LIMITS
    base = main_site_url(request)
    site = getattr(settings, 'SITE_NAME', 'SellPunch')
    lines = [
        f'# {site}',
        '',
        f'> {site} is an all-in-one ecommerce website builder and POS software for small businesses and Facebook (F-commerce) '
        'sellers in Bangladesh. A seller gets their own online store website in about 1 minute (shop name + web address + '
        'mobile number + password, no code, no hosting), plus in-store POS billing, one-click Steadfast/Pathao/RedX courier '
        'booking, customer SMS, a digital due book (baki khata) and profit reports. The seller dashboard is in Bangla; each '
        'store can be shown to customers in Bangla or English.',
        '',
        f'{site} is a product of {COMPANY["name_en"]}, a registered business in Bangladesh '
        f'(trade licence ID {COMPANY["licence_id"]}).',
        '',
        '## Key facts',
        '- Website live in about 1 minute after sign-up, at yourshop.' + (getattr(settings, 'STORE_BASE_DOMAIN', '') or 'sellpunch.com')
        + '; own domain (www.yourshop.com) on Premium.',
        '- 30-day free trial with every feature; no card needed.',
        '- Payments: cash on delivery, or bKash / Nagad / card advance through the PayStation gateway (optional per store).',
        '- Couriers: Steadfast, Pathao and RedX — tested on live merchant accounts.',
        '- Works in the phone browser; no app to install.',
        '',
        '## Pricing (BDT)',
    ]
    for key in ('Basic', 'Standard', 'Premium'):
        limits = PLAN_LIMITS[key]
        products = 'unlimited products' if limits['products'] is None else f"{limits['products']} products"
        extras = [products, f"{limits['staff']} staff"]
        if limits['facebook']:
            extras.append('Facebook page connect')
        if limits['custom_domain']:
            extras.append('own domain')
        lines.append(f"- {key}: {int(PLAN_PRICES[key])}/month or {int(PLAN_YEAR_PRICES[key])}/year — {', '.join(extras)}")
    lines += ['', '## Features']
    for page in marketing.FEATURES:
        lines.append(f"- [{page['en']['nav']}]({base}{reverse('mk_feature_en', args=[page['slug']])}): {page['en']['description']}"
                     f" (Bangla: {base}{reverse('mk_feature', args=[page['slug']])})")
    lines += ['', '## Who it is for']
    for page in marketing.INDUSTRIES:
        lines.append(f"- [{page['en']['nav']}]({base}{reverse('mk_industry_en', args=[page['slug']])}): {page['en']['description']}")
    from . import guides
    lines += ['', '## Guide center (step-by-step how-to, in Bangla, with screenshots)',
              f"- [Guide center]({base}{reverse('guide_index')}) — full text of every guide: {base}{reverse('site_llms_full')}"]
    for guide in guides.all_guides():
        lines.append(f"- [{guide['title']}]({base}{reverse('guide_detail', args=[guide['slug']])}): {guide['summary']}")
    lines += [
        '', '## Pages',
        f'- [Home (Bangla)]({base}/)', f"- [Home (English)]({base}{reverse('landing_page_en')})",
        f"- [All features]({base}{reverse('mk_index_en')})", f"- [Sign up — 30 days free]({base}{reverse('signup')})",
        f"- [About and trade licence]({base}{reverse('about')})", f"- [Security and data]({base}{reverse('security')})",
        f"- [Terms]({base}{reverse('terms')})", f"- [Privacy policy]({base}{reverse('privacy_policy')})",
        f"- [Refund policy]({base}{reverse('refund_policy')})",
        '', '## Contact',
    ]
    for label, value in (('Phone', getattr(settings, 'SUPPORT_PHONE', '')), ('Email', getattr(settings, 'SUPPORT_EMAIL', '')),
                         ('Address', COMPANY.get('address_en', ''))):
        if value:
            lines.append(f'- {label}: {value}')
    return '\n'.join(lines) + '\n'


def main_llms_full_txt(request):
    """/llms-full.txt — গাইড সেন্টারের প্রতিটা গাইডের পুরো লেখা, ছবির পূর্ণ ঠিকানাসহ।"""
    from django.conf import settings
    from django.urls import reverse
    from . import guides
    base = main_site_url(request)
    site = getattr(settings, 'SITE_NAME', 'SellPunch')
    parts = [f'# {site} — guide center (full text, Bangla)', '',
             f'> Step-by-step guides for every {site} feature. Source: {base}{reverse("guide_index")}', '']
    for guide in guides.all_guides():
        parts += ['---', '', f"Source: {base}{reverse('guide_detail', args=[guide['slug']])}", '',
                  guides.guide_plain_markdown(guide, base), '']
    return '\n'.join(parts) + '\n'


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
