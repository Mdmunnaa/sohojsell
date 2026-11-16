"""
গাইড সেন্টার (/guide/) — SellPunch-এর প্রতিটা অপশনের ধাপে ধাপে নিয়ম, স্ক্রিনশটসহ (Edumi-র core/guides.py-র মতো)।

লেখা ডাটাবেসে না, সাদা .md ফাইলে (store/guide_content/*.md) — ডেভেলপারই লেখে-বদলায়, ফাইল বদলে deploy করলেই আপডেট।
  - ফাইলের শুরুতে `<!-- meta title: ... description: ... -->` — পাতার <title> আর meta description।
  - `![বর্ণনা](shot:<id>)` — store/static/guides/<id>.webp স্ক্রিনশট (tools/guide_screenshots.py ডেমো দোকান থেকে তোলে;
    মাপ store/guide_content/shots.json-এ)। ছবি না থাকলে লাইনটা বাদ যায় — ভাঙা ছবি কখনো দেখায় না।
  - `> **খেয়াল রাখুন:** ...` — রঙিন বাক্সে দেখায়।
  - "## প্রশ্ন ও উত্তর"-এর নিচের "### প্রশ্ন" + উত্তর — পাতায় দেখায়, আর Google-এর FAQPage structured data হয়।
  - /llms.txt-এ সব গাইডের তালিকা, /llms-full.txt-এ পুরো লেখা (AI টুলের জন্য)।

সতর্কতা: লেখার আগে কোডে মিলিয়ে নিন — বোতামের নাম, মেনুর পথ, কোন প্যাকেজে কী। যা কোডে নেই তা গাইডে লিখবেন না।
"""
import html
import json
import re
from functools import lru_cache
from pathlib import Path

import markdown
from markdown.extensions.toc import slugify_unicode

GUIDES_DIR = Path(__file__).resolve().parent / 'guide_content'
SHOTS_MANIFEST = GUIDES_DIR / 'shots.json'
SHOT_STATIC_DIR = 'guides'           # store/static/guides/<id>.webp
GUIDES_UPDATED = '2026-11-16'        # গাইড বড় করে বদলালে এই তারিখ বদলান (structured data-র dateModified)
FAQ_HEADING = 'প্রশ্ন ও উত্তর'

# ক্রমটাই গাইড সেন্টারের ক্রম। title/summary .md-র meta থেকে আসে।
BUYER_CATEGORY = 'আপনার ক্রেতাদের জন্য'   # গাইড সেন্টারে আলাদা ব্যানারে দেখায়

GUIDE_REGISTRY = [
    {'slug': 'getting-started', 'category': 'শুরু করুন', 'icon': 'bi-rocket-takeoff', 'file': 'getting-started.md'},
    {'slug': 'troubleshooting', 'category': 'শুরু করুন', 'icon': 'bi-life-preserver', 'file': 'troubleshooting.md'},
    {'slug': 'move-to-sellpunch', 'category': 'শুরু করুন', 'icon': 'bi-box-arrow-in-down', 'file': 'move-to-sellpunch.md'},
    {'slug': 'products', 'category': 'প্রোডাক্ট ও স্টক', 'icon': 'bi-box-seam', 'file': 'products.md'},
    {'slug': 'barcode', 'category': 'প্রোডাক্ট ও স্টক', 'icon': 'bi-upc-scan', 'file': 'barcode.md'},
    {'slug': 'pos', 'category': 'বিক্রি ও অর্ডার', 'icon': 'bi-shop', 'file': 'pos.md'},
    {'slug': 'orders', 'category': 'বিক্রি ও অর্ডার', 'icon': 'bi-receipt', 'file': 'orders.md'},
    {'slug': 'courier', 'category': 'বিক্রি ও অর্ডার', 'icon': 'bi-truck', 'file': 'courier.md'},
    {'slug': 'website', 'category': 'ওয়েবসাইট', 'icon': 'bi-globe2', 'file': 'website.md'},
    {'slug': 'online-payment', 'category': 'ওয়েবসাইট', 'icon': 'bi-credit-card', 'file': 'online-payment.md'},
    {'slug': 'custom-domain', 'category': 'ওয়েবসাইট', 'icon': 'bi-link-45deg', 'file': 'custom-domain.md'},
    {'slug': 'facebook-automation', 'category': 'মার্কেটিং', 'icon': 'bi-messenger', 'file': 'facebook-automation.md'},
    {'slug': 'landing-page', 'category': 'মার্কেটিং', 'icon': 'bi-window-stack', 'file': 'landing-page.md'},
    {'slug': 'marketing', 'category': 'মার্কেটিং', 'icon': 'bi-megaphone', 'file': 'marketing.md'},
    {'slug': 'customers-due', 'category': 'কাস্টমার ও হিসাব', 'icon': 'bi-journal-text', 'file': 'customers-due.md'},
    {'slug': 'accounts-reports', 'category': 'কাস্টমার ও হিসাব', 'icon': 'bi-graph-up-arrow', 'file': 'accounts-reports.md'},
    {'slug': 'staff', 'category': 'দোকান চালানো', 'icon': 'bi-people', 'file': 'staff.md'},
    {'slug': 'settings-billing', 'category': 'দোকান চালানো', 'icon': 'bi-gear', 'file': 'settings-billing.md'},
    {'slug': 'buyers', 'category': BUYER_CATEGORY, 'icon': 'bi-bag-heart', 'file': 'buyers.md'},
]

# ড্যাশবোর্ডের কোন পাতায় কোন গাইড — "AI-কে জিজ্ঞেস করুন" এই পাতার গাইডের লিংক AI-কে দেয়।
# (পথের শুরু, ?tab= লাগলে সেটা, গাইড) — উপর থেকে প্রথম যেটা মেলে; তাই নির্দিষ্টগুলো আগে।
PAGE_GUIDES = [
    ('/products/import/', None, 'move-to-sellpunch'),
    ('/customers/import/', None, 'move-to-sellpunch'),
    ('/orders/abandoned/', None, 'marketing'),
    ('/website/settlement/', None, 'online-payment'),
    ('/website/', 'payment', 'online-payment'),
    ('/website/', 'domain', 'custom-domain'),
    ('/website/', None, 'website'),
    ('/settings/', 'pos', 'pos'),
    ('/settings/', 'facebook', 'facebook-automation'),
    ('/settings/', 'data', 'settings-billing'),
    ('/settings/', None, 'courier'),
    ('/products/', None, 'products'),
    ('/categories/', None, 'products'),
    ('/barcodes/', None, 'barcode'),
    ('/pos/', None, 'pos'),
    ('/orders/', None, 'orders'),
    ('/order/', None, 'orders'),
    ('/online-orders/', None, 'orders'),
    ('/invoice/', None, 'orders'),
    ('/courier/', None, 'courier'),
    ('/offers/', None, 'marketing'),
    ('/reviews/', None, 'marketing'),
    ('/sms/', None, 'marketing'),
    ('/landing/', None, 'landing-page'),
    ('/facebook/', None, 'facebook-automation'),
    ('/messenger/', None, 'facebook-automation'),
    ('/customers/', None, 'customers-due'),
    ('/dues/', None, 'customers-due'),
    ('/purchases/', None, 'accounts-reports'),
    ('/suppliers/', None, 'accounts-reports'),
    ('/expenses/', None, 'accounts-reports'),
    ('/reports/', None, 'accounts-reports'),
    ('/staff/', None, 'staff'),
    ('/billing/', None, 'settings-billing'),
    ('/payment/', None, 'settings-billing'),
    ('/dashboard/', None, 'getting-started'),
    ('/setup-shop/', None, 'getting-started'),
]

_META_RE = re.compile(r'\A\s*<!--\s*meta\s*(.*?)-->\s*', re.S)
_SHOT_RE = re.compile(r'!\[([^\]]*)\]\(shot:([a-z0-9-]+)\)')
_TITLE_SUFFIX_RE = re.compile(r'\s*\|\s*SellPunch\s*$')
_NOTE_RE = re.compile(r'<blockquote>\s*<p><strong>([^<]{2,30}):</strong>')


def _read(guide):
    return (GUIDES_DIR / guide['file']).read_text(encoding='utf-8')


def _split_meta(text):
    meta = {}
    match = _META_RE.match(text)
    if match:
        for line in match.group(1).splitlines():
            key, sep, value = line.partition(':')
            if sep and key.strip():
                meta[key.strip().lower()] = value.strip()
        text = text[match.end():]
    return meta, text


@lru_cache(maxsize=1)
def shot_manifest():
    """{id: {'w': প্রস্থ, 'h': উচ্চতা}} — কোন স্ক্রিনশট আসলে আছে।"""
    try:
        return json.loads(SHOTS_MANIFEST.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def shot_url(shot_id):
    from django.templatetags.static import static
    return static(f'{SHOT_STATIC_DIR}/{shot_id}.webp')


@lru_cache(maxsize=None)
def _guide_entry(slug):
    base = next((g for g in GUIDE_REGISTRY if g['slug'] == slug), None)
    if base is None:
        return None
    meta, text = _split_meta(_read(base))
    entry = dict(base)
    h1 = re.search(r'^# (.+)$', text, re.M).group(1).strip()
    seo = _TITLE_SUFFIX_RE.sub('', meta.get('title') or h1)
    entry['title'] = entry['h1'] = h1                     # কার্ড, লিংক আর পাতার শিরোনামে (ছোট)
    entry['seo_title'] = seo if 'SellPunch' in seo else f'{seo} | SellPunch'   # <title> আর Google-এ (খোঁজার শব্দসহ)
    entry['summary'] = meta.get('description', '')
    entry['shots'] = len([1 for m in _SHOT_RE.finditer(text) if m.group(2) in shot_manifest()])
    words = len(re.sub(r'!\[[^\]]*\]\([^)]*\)', '', text).split())
    entry['minutes'] = max(2, round(words / 180))
    return entry


def all_guides():
    return [_guide_entry(g['slug']) for g in GUIDE_REGISTRY]


def get_guide(slug):
    """slug দিয়ে গাইড (meta-সহ), না থাকলে None (view-তে 404)।"""
    return _guide_entry(slug)


def guide_for_page(path, tab=''):
    """ড্যাশবোর্ডের এই পাতার গাইড (PAGE_GUIDES), না মিললে None।"""
    for prefix, need_tab, slug in PAGE_GUIDES:
        if path.startswith(prefix) and (need_tab is None or need_tab == tab):
            return _guide_entry(slug)
    return None


def _body_markdown(guide):
    """meta আর প্রথম H1 বাদ দিয়ে মূল লেখা (H1 পাতার উপরে আলাদা দেখানো হয়)।"""
    _, text = _split_meta(_read(guide))
    return re.sub(r'\A\s*# [^\n]*\n', '', text, count=1)


def _figure_html(alt, shot_id):
    size = shot_manifest().get(shot_id)
    if not size:
        return ''
    alt_attr = html.escape(alt, quote=True)
    phone = ' g-phone' if size['w'] < size['h'] else ''   # '.phone' নয় — ওটা হোমপেজের ফোন-ফ্রেমের ক্লাস
    srcset = ''
    if not phone:
        # ফোনে ছোট ছবি নামে (tools/guide_screenshots.py বানায় <id>-600w/-900w.webp); লেখার ঘর কম্পিউটারে ৭৮০px চওড়া
        from .templatetags.speed import _srcset
        candidates = _srcset(f'{SHOT_STATIC_DIR}/{shot_id}.webp', size['w'])
        if ',' in candidates:
            srcset = f' srcset="{candidates}" sizes="(max-width: 979px) calc(100vw - 48px), 780px"'
    return (f'\n<figure class="g-shot{phone}"><img src="{shot_url(shot_id)}"{srcset} alt="{alt_attr}" width="{size["w"]}" '
            f'height="{size["h"]}" loading="lazy" decoding="async"><figcaption>{html.escape(alt)}</figcaption></figure>\n')


@lru_cache(maxsize=None)
def _rendered(slug):
    guide = _guide_entry(slug)
    text = _SHOT_RE.sub(lambda m: _figure_html(m.group(1), m.group(2)), _body_markdown(guide))
    # "**কোথায় পাবেন:** …" / "**কী কাজে লাগে:** …" লাইনগুলো আলাদা অনুচ্ছেদ — নাহলে Markdown এক লাইনে জুড়ে দেয়
    text = re.sub(r'(?<=\S)\n(\*\*[^*\n]{2,40}:\*\*)', r'\n\n\1', text)
    md = markdown.Markdown(extensions=['tables', 'sane_lists', 'toc', 'md_in_html'],
                           extension_configs={'toc': {'slugify': slugify_unicode, 'toc_depth': '2'}})
    body = md.convert(text)
    # প্রথম ছবিটা প্রায়ই পাতার সবচেয়ে বড় জিনিস (LCP) — ওটা দেরিতে লোড হলে পাতা ধীর দেখায়
    body = body.replace('loading="lazy"', 'loading="eager"', 1)
    # "> **খেয়াল রাখুন:**" → হলুদ বাক্স, "> **টিপস:**" → সবুজ বাক্স
    body = _NOTE_RE.sub(lambda m: f'<blockquote class="g-note{" tip" if "টিপস" in m.group(1) else ""}"><p><strong>{m.group(1)}:</strong>', body)
    toc = [{'id': t['id'], 'name': t['name']} for t in md.toc_tokens if t['name'] != FAQ_HEADING]
    return body, toc


def render_guide_html(guide):
    """গাইডের .md থেকে HTML। সোর্স রিপোর টেক্সট ফাইল (ইউজার-ইনপুট না), তাই টেমপ্লেটে |safe নিরাপদ।"""
    return _rendered(guide['slug'])[0]


def guide_toc(guide):
    """"এই গাইডে যা আছে" তালিকা: [{'id', 'name'}] (H2 শিরোনামগুলো, প্রশ্ন-উত্তর বাদে)।"""
    return _rendered(guide['slug'])[1]


def guide_faq(guide):
    """"## প্রশ্ন ও উত্তর"-এর নিচের [(প্রশ্ন, উত্তর)] — FAQPage structured data-র জন্য।"""
    body = _body_markdown(guide)
    match = re.search(rf'^## {FAQ_HEADING}\s*$(.*?)(?=^## |\Z)', body, re.S | re.M)
    if not match:
        return []
    items = []
    for block in re.split(r'^### ', match.group(1), flags=re.M)[1:]:
        question, _, answer = block.partition('\n')
        answer = re.sub(r'\*\*|`|\[([^\]]*)\]\([^)]*\)', lambda m: m.group(1) or '', answer).strip()
        if question.strip() and answer:
            items.append((question.strip(), ' '.join(answer.split())))
    return items


def guide_images(guide):
    """এই গাইডের যেসব স্ক্রিনশট আসলেই আছে: [(id, alt)]।"""
    manifest = shot_manifest()
    return [(m.group(2), m.group(1)) for m in _SHOT_RE.finditer(_read(guide)) if m.group(2) in manifest]


def guide_plain_markdown(guide, base_url=''):
    """AI টুলের জন্য (/llms-full.txt): meta ছাড়া Markdown, স্ক্রিনশট পূর্ণ URL-এ; ছবি না থাকলে শুধু বর্ণনা।"""
    manifest = shot_manifest()

    def image(match):
        alt, shot_id = match.group(1), match.group(2)
        return f'![{alt}]({base_url}{shot_url(shot_id)})' if shot_id in manifest else f'(ছবি: {alt})'
    _, text = _split_meta(_read(guide))
    text = re.sub(r'\]\(/(?!/)', f']({base_url}/', text)          # সাইটের ভেতরের সব লিংক পূর্ণ ঠিকানায়
    return _SHOT_RE.sub(image, text).strip()


def guides_by_category():
    """{category: [guide, ...]} — রেজিস্ট্রির ক্রম বজায় থাকে।"""
    grouped = {}
    for guide in all_guides():
        grouped.setdefault(guide['category'], []).append(guide)
    return grouped


def search_index():
    """গাইড সেন্টারের খোঁজার ঘরের জন্য প্রতিটা অংশ: [{'g': গাইড, 's': অংশ, 'u': লিংক}]।"""
    from django.urls import reverse
    rows = []
    for guide in all_guides():
        url = reverse('guide_detail', args=[guide['slug']])
        rows.append({'g': guide['title'], 's': '', 'u': url, 'd': guide['summary']})
        rows += [{'g': guide['title'], 's': item['name'], 'u': f"{url}#{item['id']}"} for item in guide_toc(guide)]
    return rows
