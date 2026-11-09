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
