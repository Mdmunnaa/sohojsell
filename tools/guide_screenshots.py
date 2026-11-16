"""
গাইড সেন্টারের স্ক্রিনশট তোলা — store/guide_content/shots_spec.json-এর প্রতিটা ছবি ডেমো দোকান ("ফ্যাশন পয়েন্ট") থেকে তুলে
store/static/guides/<id>.webp-তে রাখে, আর মাপ store/guide_content/shots.json-এ লেখে (গাইডে <img width/height>-এর জন্য)।

শুধু ডেভেলপারের কম্পিউটারে (লাইভ সার্ভারে না) — ডেমো দোকানে কিছু জিনিস বদলায় (বারকোড, ডোমেইন, ডিজাইন):
    1. ডেমো দোকান:  python manage.py seed_demo
    2. সার্ভার:      DEBUG=1 PAYSTATION_MERCHANT_ID=x PAYSTATION_PASSWORD=x python manage.py runserver 8035
                     (PayStation-এর নকল চাবি দিলে অনলাইন পেমেন্টের অংশগুলো ছবিতে চালু দেখায়)
    3. ছবি:         python3 tools/guide_screenshots.py [--only id1,id2] [--port 8035] [--camera barcode.y4m]
       (Playwright যে পাইথনে আছে সেটা দিয়ে; Django-র পাইথন আলাদা হলে DJANGO_PYTHON=/path/to/python দিন।
        --camera: বারকোডের ছবির .y4m ভিডিও — ক্যামেরা-স্ক্যানের ছবিতে নকল ক্যামেরা হিসেবে চলে)

spec-এর প্রতিটা ছবি: id, path ({product} ইত্যাদি ডেমোর আসল আইডি দিয়ে বসে), viewport (desktop/mobile), ঐচ্ছিক:
  anon (লগইন ছাড়া — ক্রেতার চোখে), js_reload (JS চালিয়ে পাতা আবার খোলা), js_before (ক্লিকের আগে JS), click (selector বা তালিকা), fill ({selector: লেখা}),
  click_nav (চেপে নতুন পাতার অপেক্ষা), js (ছবির ঠিক আগে JS), scroll_to (এই লেখা পর্যন্ত নামো), wait (মিলিসেকেন্ড),
  height (জানালার উচ্চতা — element লম্বা হলে পুরোটা ধরতে),
  element (শুধু এই অংশের ছবি), css (বাড়তি CSS), designs: true (চার ডিজাইনের দোকান পাশাপাশি)।
ছবিতে মোবাইল নম্বর ঢেকে দেয় (ডেমোর নম্বরও কারো আসল নম্বর হতে পারে)।
"""
import argparse
import io
import json
import os
import subprocess
import sys
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

BASE_DIR = Path(__file__).resolve().parent.parent
SPEC = BASE_DIR / 'store' / 'guide_content' / 'shots_spec.json'
MANIFEST = BASE_DIR / 'store' / 'guide_content' / 'shots.json'
OUT_DIR = BASE_DIR / 'store' / 'static' / 'guides'
VIEWPORTS = {'desktop': {'width': 1280, 'height': 780, 'scale': 1, 'mobile': False},
             'mobile': {'width': 390, 'height': 844, 'scale': 2, 'mobile': True}}
SCAN_BARCODE = '451141479278'      # tools-এর নকল ক্যামেরার ভিডিওতে এই বারকোড — ডেমোর একটা প্রোডাক্টে বসানো হয়

PREPARE_CODE = r'''
import json, sys
from django.db.models import F
from store.demo import demo_shop
from store.models import Customer, Order, Product, Shop
shop = demo_shop()
plain = Product.objects.filter(shop=shop, has_variants=False, stock_quantity__gt=3).order_by('id').first()
Product.objects.filter(shop=shop, barcode=sys.argv[1]).exclude(pk=plain.pk).update(barcode=None)
if plain.barcode != sys.argv[1]:
    plain.barcode = sys.argv[1]
    plain.save(update_fields=['barcode'])
if not shop.custom_domain:
    Shop.objects.filter(pk=shop.pk).update(custom_domain='www.fashionpoint.com.bd')
product = Product.objects.filter(shop=shop, has_variants=True).order_by('id').first()
web = Order.objects.filter(shop=shop, source='storefront').order_by('-id').first()
track = Order.objects.filter(shop=shop, source='storefront', status='Shipped').order_by('-id').first() or web
pos_order = Order.objects.filter(shop=shop, source='pos', status='Delivered').order_by('-id').first()
due = (Order.objects.filter(shop=shop, source='pos', advance_paid__lt=F('total_amount'))
       .exclude(customer__phone='00000000000').order_by('-id').first())
landing = shop.landing_pages.order_by('id').first()
# "অন্য প্ল্যাটফর্ম থেকে আসা" গাইডের জন্য নমুনা ফাইল — Shopify, অচেনা কলামের Excel, শেষ হওয়া কাজ, কাস্টমার
from store.models import ImportJob
ImportJob.objects.filter(shop=shop).delete()
H = ['Handle', 'Title', 'Body (HTML)', 'Type', 'Published', 'Option1 Name', 'Option1 Value', 'Option2 Name',
     'Option2 Value', 'Variant SKU', 'Variant Inventory Qty', 'Variant Price', 'Variant Compare At Price', 'Image Src',
     'Cost per item', 'Status']
rows = []
for i, (title, kind, price, compare, sizes, colors) in enumerate([
        ('সুতি থ্রি-পিস (ব্লক প্রিন্ট)', 'থ্রি-পিস', 1450, 1800, ['M', 'L', 'XL'], ['নীল', 'মেরুন']),
        ('জামদানি শাড়ি', 'শাড়ি', 4200, 4800, [], []),
        ('লিনেন পাঞ্জাবি', 'পাঞ্জাবি', 1850, None, ['40', '42', '44'], ['সাদা']),
        ('লেদার ওয়ালেট', 'এক্সেসরিজ', 650, 850, [], []),
        ('হিজাব (জর্জেট)', 'হিজাব', 350, None, [], ['কালো', 'বেইজ', 'গোলাপি']),
        ('কটন টি-শার্ট', 'টি-শার্ট', 450, 550, ['M', 'L', 'XL'], []),
        ('কিডস ফ্রক', 'বাচ্চাদের', 780, 950, ['2-3Y', '4-5Y'], []),
        ('সিল্ক ওড়না', 'এক্সেসরিজ', 520, None, [], [])]):
    handle = f'item-{i}'
    combos = [(a, b) for a in (sizes or ['']) for b in (colors or [''])]
    for j, (size, color) in enumerate(combos):
        first = j == 0
        option = 'Default Title' if not size and not color else (size or color)
        rows.append([handle, title if first else '', '<p>নরম কাপড়, ধোয়ার পরেও রং ঠিক থাকে।</p>' if first else '',
                     kind if first else '', 'TRUE' if first else '', ('Size' if size else 'Color') if first and option != 'Default Title' else ('Title' if first else ''),
                     option, 'Color' if first and size and color else '', color if size and color else '',
                     f'SP-IMP-{i}-{j}', str(3 + (i * 7 + j * 3) % 11), str(price), str(compare or ''),
                     f'https://cdn.shopify.com/s/files/demo/{handle}.jpg' if first else '', str(int(price * 0.6)) if first else '',
                     'active' if first else ''])
rows.append(['old-item', 'পুরনো স্যাম্পল', '', '', 'TRUE', 'Title', 'Default Title', '', '', '', '', '', '', '', '', 'active'])
preview = ImportJob.objects.create(shop=shop, kind='products', filename='products_export_1.csv', source='shopify',
                                   headers=H, rows=rows, mapping={})
mapping_job = ImportJob.objects.create(
    shop=shop, kind='products', filename='মালের হিসাব.xlsx', source='generic',
    headers=['ক্রমিক', 'পণ্য', 'রেট (টাকা)', 'মজুত', 'মাপ', 'ছবি'],
    rows=[['1', 'সুতি থ্রি-পিস', '1450', '12', 'M', ''], ['2', 'জামদানি শাড়ি', '4200', '3', '', '']],
    mapping={'name': 1, 'option1': 4, 'image': 5})
from django.utils import timezone
done = ImportJob.objects.create(
    shop=shop, kind='products', filename='wc-product-export.csv', source='woocommerce', status='done',
    result={'created': 86, 'variants': 214, 'over_limit': 0, 'skipped_count': 2,
            'skipped': [[41, 'Gift Card', 'এই ধরনের প্রোডাক্ট (external) আনা যায় না'], [77, 'স্যাম্পল', 'দাম নেই বা দাম সংখ্যায় লেখা নেই']]},
    images_total=86, images_done=86, finished_at=timezone.now())
customers = ImportJob.objects.create(
    shop=shop, kind='customers', filename='customers.xlsx', source='generic',
    headers=['নাম', 'মোবাইল', 'ঠিকানা'],
    rows=[['রাহিমা আক্তার', '+880 1712-345601', 'বাড়ি ১২, রোড ৩, মিরপুর ১০, ঢাকা'],
          ['করিম উদ্দিন', '01812345602', 'জিন্দাবাজার, সিলেট'],
          ['নুসরাত জাহান', '০১৯১২৩৪৫৬০৩', 'আগ্রাবাদ, চট্টগ্রাম'],
          ['সুমাইয়া ইসলাম', '8801612345604', 'সাভার, ঢাকা'],
          ['ভুল নম্বর', '12345', ''],
          ['রাহিমা আক্তার', '01712345601', 'মিরপুর']],
    mapping={'name': 0, 'phone': 1, 'address': 2})
print(json.dumps({
    'slug': shop.slug, 'product': product.id, 'plain_product': plain.id, 'order': web.id,
    'track_order': track.id, 'track_phone': track.customer.phone, 'pos_order': pos_order.id,
    'due_phone': due.customer.phone if due else '', 'landing': landing.id, 'landing_slug': landing.slug,
    'design': shop.storefront_design, 'import_preview': preview.id, 'import_mapping': mapping_job.id,
    'import_done': done.id, 'import_customers': customers.id,
}))
'''

SET_DESIGN_CODE = r'''
import sys
from store.demo import demo_shop
from store.models import Shop
Shop.objects.filter(pk=demo_shop().pk).update(storefront_design=sys.argv[1])
'''

HIDE_CSS = ('.demo-bar,.toast-container,.messages,.alert-dismissible,.pn{display:none!important}'
            '*{animation-duration:0s!important;transition:none!important;caret-color:transparent!important}')

MASK_JS = r"""() => {
  const mask = t => t.replace(/(?:\+?88)?01\d{3}[-\s]?\d{6}/g, '01XXX-XXXXXX');
  const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (walk.nextNode()) { const n = walk.currentNode; if (/01\d{3}[-\s]?\d{6}/.test(n.textContent)) n.textContent = mask(n.textContent); }
  document.querySelectorAll('input, textarea').forEach(i => { if (/01\d{3}[-\s]?\d{6}/.test(i.value)) i.value = mask(i.value); });
}"""


def django(code, *args):
    """Django-র পাইথনে কোড চালানো (Playwright-এর পাইথনে Django না-ও থাকতে পারে)। sys.argv[1:] = args।"""
    python = os.environ.get('DJANGO_PYTHON', sys.executable)
    boot = ('import os, sys, django; os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sohojsell.settings"); '
            'django.setup(); code = sys.argv[1]; sys.argv = sys.argv[1:]; exec(code)')
    out = subprocess.check_output([python, '-c', boot, code, *args], cwd=BASE_DIR,
                                  env=dict(os.environ, PYTHONPATH=str(BASE_DIR)))
    lines = out.decode().strip().splitlines()
    return lines[-1] if lines else ''


SMALL_WIDTHS = (600, 900)   # ফোনে ছোট ছবি নামে (store/templatetags/speed.py-এর <id>-600w.webp নিয়ম)


def save_small(image, shot_id):
    for old in OUT_DIR.glob(f'{shot_id}-*w.webp'):
        old.unlink()
    for width in SMALL_WIDTHS:
        if image.width > width * 1.2:
            small = image.resize((width, round(image.height * width / image.width)), Image.LANCZOS)
            small.save(OUT_DIR / f'{shot_id}-{width}w.webp', 'WEBP', quality=74, method=6)


def save(image, shot_id, mobile, manifest):
    if mobile:
        image = image.resize((image.width * 2 // 3, image.height * 2 // 3), Image.LANCZOS)   # 780→520px
    image.save(OUT_DIR / f'{shot_id}.webp', 'WEBP', quality=74, method=6)
    save_small(image, shot_id)
    manifest[shot_id] = {'w': image.width, 'h': image.height}
    print(f'ok {shot_id} ({image.width}x{image.height})')


def designs_shot(browser, host, ids, shot, manifest):
    """চার ডিজাইনে একই দোকান — মোবাইলের উপরের অংশ পাশাপাশি।"""
    parts = []
    for design in ('classic', 'minimal', 'bold', 'soft'):
        django(SET_DESIGN_CODE, design)
        ctx = browser.new_context(viewport={'width': 390, 'height': 760}, device_scale_factor=2, is_mobile=True, has_touch=True)
        page = ctx.new_page()
        page.goto(f"{host}/shop/{ids['slug']}/", wait_until='networkidle')
        page.add_style_tag(content=HIDE_CSS)
        page.evaluate(MASK_JS)
        page.wait_for_timeout(300)
        parts.append(Image.open(io.BytesIO(page.screenshot())).convert('RGB'))
        ctx.close()
    django(SET_DESIGN_CODE, ids['design'])
    gap = 24
    width = sum(p.width for p in parts) + gap * (len(parts) - 1)
    canvas = Image.new('RGB', (width, parts[0].height), (247, 247, 251))
    x = 0
    for part in parts:
        canvas.paste(part, (x, 0))
        x += part.width + gap
    canvas = canvas.resize((1400, round(canvas.height * 1400 / canvas.width)), Image.LANCZOS)
    save(canvas, shot['id'], False, manifest)


def capture(spec, ids, port, only, camera):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8')) if MANIFEST.exists() else {}
    host = f'http://127.0.0.1:{port}'
    args = ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream']
    if camera:
        args.append(f'--use-file-for-fake-video-capture={camera}')
    with sync_playwright() as p:
        browser = p.chromium.launch(args=args)
        contexts = {}
        for shot in spec:
            if only and shot['id'] not in only:
                continue
            if shot.get('designs'):
                designs_shot(browser, host, ids, shot, manifest)
                continue
            key = (shot['viewport'], bool(shot.get('anon')))
            if key not in contexts:
                vp = VIEWPORTS[shot['viewport']]
                ctx = browser.new_context(viewport={'width': vp['width'], 'height': vp['height']},
                                          device_scale_factor=vp['scale'], is_mobile=vp['mobile'], has_touch=vp['mobile'],
                                          locale='bn-BD', color_scheme='light', permissions=['camera'])
                page = ctx.new_page()
                page.on('dialog', lambda d: d.dismiss())
                if not shot.get('anon'):
                    page.goto(f'{host}/demo/', wait_until='networkidle')     # ডেমো দোকানে পাসওয়ার্ড ছাড়া লগইন
                contexts[key] = page
            page = contexts[key]
            vp = VIEWPORTS[shot['viewport']]
            page.set_viewport_size({'width': vp['width'], 'height': shot.get('height', vp['height'])})   # লম্বা অংশ পুরোটা
            url = host + shot['path'].format(**ids)
            try:
                page.goto('about:blank')
                page.goto(url, wait_until='networkidle', timeout=30000)
                page.add_style_tag(content=HIDE_CSS + shot.get('css', ''))
                if shot.get('js_reload'):     # যেমন localStorage-এ POS-এর বিল বসিয়ে পাতা আবার খোলা
                    page.evaluate(shot['js_reload'])
                    page.reload(wait_until='networkidle')
                    page.add_style_tag(content=HIDE_CSS + shot.get('css', ''))
                if shot.get('js_before'):
                    page.evaluate(shot['js_before'])
                for selector in ([shot['click']] if isinstance(shot.get('click'), str) else shot.get('click') or []):
                    page.locator(selector).first.click()
                    page.wait_for_timeout(400)
                for selector, text in (shot.get('fill') or {}).items():
                    page.fill(selector, text.format(**ids))
                if shot.get('click_nav'):
                    with page.expect_navigation(timeout=20000):
                        page.locator(shot['click_nav']).first.click()
                    page.wait_for_load_state('networkidle')
                    page.add_style_tag(content=HIDE_CSS + shot.get('css', ''))
                if shot.get('js'):
                    page.evaluate(shot['js'])
                    page.wait_for_timeout(400)
                if shot.get('scroll_to'):
                    for target in page.get_by_text(shot['scroll_to'], exact=False).all():
                        if target.is_visible():
                            target.scroll_into_view_if_needed()
                            page.evaluate('window.scrollBy(0, -90)')
                            break
                page.wait_for_timeout(shot.get('wait', 300))
                page.evaluate(MASK_JS)
                if shot.get('element'):
                    png = page.locator(shot['element']).first.screenshot()
                else:
                    png = page.screenshot(full_page=False)
            except Exception as error:   # একটা ছবি না উঠলে বাকিগুলো চলুক
                print(f'x {shot["id"]}: {str(error).splitlines()[0]}')
                continue
            save(Image.open(io.BytesIO(png)).convert('RGB'), shot['id'], shot['viewport'] == 'mobile', manifest)
        browser.close()
    MANIFEST.write_text(json.dumps(dict(sorted(manifest.items())), ensure_ascii=False, indent=1) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', default='8035')
    parser.add_argument('--only', default='')
    parser.add_argument('--camera', default=os.environ.get('GUIDE_FAKE_CAMERA', ''))
    args = parser.parse_args()
    spec = json.loads(SPEC.read_text(encoding='utf-8'))
    ids = json.loads(django(PREPARE_CODE, SCAN_BARCODE))
    print('ids', ids)
    capture(spec, ids, args.port, {s for s in args.only.split(',') if s}, args.camera)


if __name__ == '__main__':
    main()
