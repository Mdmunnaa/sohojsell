"""
বাইরের CDN (Google Fonts, jsdelivr, cdnjs, unpkg) বাদ দিয়ে সব নিজের static থেকে দেওয়ার জন্য ফাইল বানানো।
শুধু ডেভেলপারের কাজে — নতুন আইকন বা লাইব্রেরি বদলালে আবার চালান, তারপর তৈরি হওয়া ফাইলগুলো commit করুন।

    cd /tmp/x && npm install bootstrap@5.3.0 bootstrap-icons@1.11.3 @fontsource/hind-siliguri \\
        @fontsource-variable/plus-jakarta-sans @fontsource/syne @fontsource-variable/dm-sans sweetalert2@11 \\
        jsbarcode@3.11.5 html5-qrcode@2.3.8 jspdf@2.5.1 html2canvas@1.4.1 html2pdf.js@0.10.1 purgecss@6
    pip install fonttools brotli
    python tools/build_vendor.py /tmp/x/node_modules

যা বানায়:
  store/static/vendor/...                         লাইব্রেরি, ফন্ট (woff2), আইকন
  store/static/vendor/bootstrap/bootstrap-storefront.min.css   দোকানের পাতায় যতটুকু Bootstrap লাগে (পাতার ভেতরেই বসে)
  store/static/vendor/bootstrap-icons/bi-public.woff2          দোকান/হোমপেজের আইকনগুলো শুধু (পুরো ফন্টের ১০ ভাগের ১ ভাগ)
  store/templates/store/partials/icons_public.html             ওই আইকনের CSS
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / 'store' / 'static' / 'vendor'
TEMPLATES = ROOT / 'store' / 'templates' / 'store'

# কাস্টমার যে পাতাগুলো দেখে (PageSpeed এগুলোই মাপে) — এদের আইকন আলাদা ছোট ফন্টে
PUBLIC_SOURCES = [
    *sorted((TEMPLATES / 'storefront').glob('*.html')),
    TEMPLATES / 'landing.html', TEMPLATES / 'landing_en.html',
    *sorted((TEMPLATES / 'partials').glob('landing_*.html')),
    ROOT / 'store' / 'views.py', ROOT / 'store' / 'views_landing.py',
    *sorted((TEMPLATES / 'marketing').glob('*.html')), TEMPLATES / 'partials' / 'mk_footer.html',
    ROOT / 'store' / 'marketing.py', ROOT / 'store' / 'views_marketing.py',      # SEO পাতা (/features/, /for/)
    *sorted((TEMPLATES / 'guides').glob('*.html')), ROOT / 'store' / 'guides.py',   # গাইড সেন্টার (/guide/)
]

COPY = {
    'bootstrap/dist/css/bootstrap.min.css': 'bootstrap/bootstrap.min.css',
    'bootstrap/dist/js/bootstrap.bundle.min.js': 'bootstrap/bootstrap.bundle.min.js',
    'bootstrap/LICENSE': 'bootstrap/LICENSE.txt',
    'bootstrap-icons/font/bootstrap-icons.min.css': 'bootstrap-icons/bootstrap-icons.min.css',
    'bootstrap-icons/font/fonts/bootstrap-icons.woff2': 'bootstrap-icons/fonts/bootstrap-icons.woff2',
    'bootstrap-icons/font/fonts/bootstrap-icons.woff': 'bootstrap-icons/fonts/bootstrap-icons.woff',
    'bootstrap-icons/LICENSE': 'bootstrap-icons/LICENSE.txt',
    'sweetalert2/dist/sweetalert2.all.min.js': 'sweetalert2/sweetalert2.all.min.js',
    'jsbarcode/dist/JsBarcode.all.min.js': 'jsbarcode/JsBarcode.all.min.js',
    'html5-qrcode/html5-qrcode.min.js': 'html5-qrcode/html5-qrcode.min.js',
    'jspdf/dist/jspdf.umd.min.js': 'jspdf/jspdf.umd.min.js',
    'html2canvas/dist/html2canvas.min.js': 'html2canvas/html2canvas.min.js',
    'html2pdf.js/dist/html2pdf.bundle.min.js': 'html2pdf/html2pdf.bundle.min.js',
}
FONTS = {
    '@fontsource/hind-siliguri/files': [f'hind-siliguri-{s}-{w}-normal.woff2' for s in ('bengali', 'latin')
                                        for w in (400, 700)],
    '@fontsource-variable/plus-jakarta-sans/files': ['plus-jakarta-sans-latin-wght-normal.woff2',
                                                     'plus-jakarta-sans-latin-ext-wght-normal.woff2'],
    '@fontsource/syne/files': [f'syne-latin-{w}-normal.woff2' for w in (600, 700, 800)],
    '@fontsource-variable/dm-sans/files': ['dm-sans-latin-wght-normal.woff2', 'dm-sans-latin-ext-wght-normal.woff2'],
}

ICON_RE = re.compile(r'bi-([a-z0-9]+(?:-[a-z0-9]+)*)')
DYNAMIC_RE = re.compile(r'bi-\{%(.*?)"', re.S)          # bi-{% if x %}check-circle-fill{% else %}dash-circle{% endif %}
TOKEN_RE = re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*')


def public_icon_names(known):
    names = set()
    for path in PUBLIC_SOURCES:
        text = path.read_text(encoding='utf-8')
        names.update(n for n in ICON_RE.findall(text) if n in known)
        for block in DYNAMIC_RE.findall(text):
            names.update(t for t in TOKEN_RE.findall(block) if t in known)
    return sorted(names)


# ড্যাশবোর্ড, HQ, লগইন/নীতিমালার পাতা, ইনভয়েস — পুরো ১২৮ KB আইকন ফন্টের বদলে শুধু যেগুলো কোথাও ব্যবহার হয়
APP_SOURCES = [
    *sorted(path for path in TEMPLATES.rglob('*.html') if not path.name.startswith('icons_')),   # নিজের বানানো ফাইল বাদ
    *sorted((ROOT / 'accounts' / 'templates').rglob('*.html')),
    *sorted(path for folder in ('store', 'accounts', 'sohojsell') for path in (ROOT / folder).rglob('*.py')
            if 'migrations' not in path.parts and path.name != 'tests.py'),
]


def app_icon_names(known):
    names = set()
    for path in APP_SOURCES:
        text = path.read_text(encoding='utf-8')
        names.update(n for n in ICON_RE.findall(text) if n in known)
        for block in DYNAMIC_RE.findall(text):
            names.update(t for t in TOKEN_RE.findall(block) if t in known)
    names.add('chevron-down')       # গাইডের সূচির CSS-এ (content:"\F282")
    return sorted(names)


def _write_subset(node, known, names, font_name, partial_name, note):
    from fontTools import subset
    out = STATIC / 'bootstrap-icons' / font_name
    options = subset.Options()
    options.flavor = 'woff2'
    options.layout_features = []
    options.name_IDs = []
    options.notdef_outline = False
    font = subset.load_font(str(node / 'bootstrap-icons/font/fonts/bootstrap-icons.woff2'), options)
    subsetter = subset.Subsetter(options)
    subsetter.populate(unicodes=[known[n] for n in names])
    subsetter.subset(font)
    subset.save_font(font, str(out), options)
    rules = ''.join(f'.bi-{n}::before{{content:"\\{known[n]:x}"}}' for n in names)
    (TEMPLATES / 'partials' / partial_name).write_text(
        "{% load static %}{# tools/build_vendor.py বানায় — হাতে বদলাবেন না। " + note + ": " + str(len(names)) + "টা #}"
        "<style>@font-face{font-display:block;font-family:\"bootstrap-icons\";"
        "src:url(\"{% static 'vendor/bootstrap-icons/" + font_name + "' %}\") format(\"woff2\")}"
        '.bi::before,[class^="bi-"]::before,[class*=" bi-"]::before{display:inline-block;font-family:bootstrap-icons!important;'
        'font-style:normal;font-weight:normal!important;font-variant:normal;text-transform:none;line-height:1;'
        'vertical-align:-.125em;-webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale}'
        + rules + '</style>\n', encoding='utf-8')
    print(f'{note}: {len(names)} icons → {out.stat().st_size // 1024} KB')


def build_app_icon_subset(node, known):
    _write_subset(node, known, app_icon_names(known), 'bi-app.woff2', 'icons_app.html', 'ড্যাশবোর্ড/HQ/লগইনের আইকন')


def build_icon_subset(node, known):
    from fontTools import subset
    names = public_icon_names(known)
    out = STATIC / 'bootstrap-icons' / 'bi-public.woff2'
    options = subset.Options()
    options.flavor = 'woff2'
    options.layout_features = []
    options.name_IDs = []
    options.notdef_outline = False
    font = subset.load_font(str(node / 'bootstrap-icons/font/fonts/bootstrap-icons.woff2'), options)
    subsetter = subset.Subsetter(options)
    subsetter.populate(unicodes=[known[n] for n in names])
    subsetter.subset(font)
    subset.save_font(font, str(out), options)
    rules = ''.join(f'.bi-{n}::before{{content:"\\{known[n]:x}"}}' for n in names)
    (TEMPLATES / 'partials' / 'icons_public.html').write_text(
        "{% load static %}{# tools/build_vendor.py বানায় — হাতে বদলাবেন না। দোকান/হোমপেজের আইকন: " + str(len(names)) + "টা #}"
        "<style>@font-face{font-display:block;font-family:\"bootstrap-icons\";"
        "src:url(\"{% static 'vendor/bootstrap-icons/bi-public.woff2' %}\") format(\"woff2\")}"
        '.bi::before,[class^="bi-"]::before,[class*=" bi-"]::before{display:inline-block;font-family:bootstrap-icons!important;'
        'font-style:normal;font-weight:normal!important;font-variant:normal;text-transform:none;line-height:1;'
        'vertical-align:-.125em;-webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale}'
        + rules + '</style>\n', encoding='utf-8')
    print(f'icons: {len(names)} → {out.stat().st_size // 1024} KB')


def build_storefront_bootstrap(node):
    out = STATIC / 'bootstrap' / 'bootstrap-storefront.min.css'
    script = node.parent / 'purge.mjs'
    script.write_text("""
import { PurgeCSS } from 'purgecss';
import fs from 'fs';
const [css, out, ...content] = process.argv.slice(2);
const res = await new PurgeCSS().purge({
  content, css: [css], variables: true, keyframes: true, fontFace: true,
  safelist: { standard: ['show', 'fade', 'modal-open', 'modal-backdrop', 'modal-static', 'collapsing', 'active', 'disabled'],
              greedy: [/^modal/] },
});
fs.writeFileSync(out, res[0].css);
""")
    subprocess.run(['node', str(script), str(node / 'bootstrap/dist/css/bootstrap.min.css'), str(out),
                    *map(str, sorted((TEMPLATES / 'storefront').glob('*.html')))], check=True, cwd=node.parent)
    css = out.read_text(encoding='utf-8')
    css = re.sub(r'/\*#\s*sourceMappingURL=.*?\*/', '', css).strip()
    out.write_text(css + '\n', encoding='utf-8')
    print(f'storefront bootstrap: {len(css) // 1024} KB')


def build_app_bootstrap(node, purge_dir=None):
    """
    ড্যাশবোর্ড/HQ/লগইনের Bootstrap — পুরো ২২৭ KB থেকে শুধু যে ক্লাসগুলো কোথাও লেখা আছে (APP_SOURCES: সব টেমপ্লেট + পাইথন)।
    পাতা খোলার আগে এটা নামতেই হয়, তাই ছোট হলে প্রথম দেখা দ্রুত। Bootstrap-এর JS যেসব ক্লাস নিজে বসায় (পপআপ, ড্রপডাউন,
    collapse, টুলটিপ...) আর টেমপ্লেটে জোড়া লাগানো নাম (alert-{{ message.tags }}) — safelist-এ। নতুন কোথাও
    'bg-' + রং-এর মতো জোড়া লাগানো ক্লাস লিখলে পুরো নামটা কোথাও লিখে রাখুন (মন্তব্যেও চলে), নইলে বাদ পড়বে।
    """
    out = STATIC / 'bootstrap' / 'bootstrap-app.min.css'
    purge_dir = Path(purge_dir or node.parent)
    script = purge_dir / 'purge-app.mjs'
    script.write_text("""
import { PurgeCSS } from 'purgecss';
import fs from 'fs';
const [css, out, list] = process.argv.slice(2);
const content = fs.readFileSync(list, 'utf8').split('\\n').filter(Boolean);
const res = await new PurgeCSS().purge({
  content, css: [css], variables: false, keyframes: true, fontFace: true,
  safelist: {
    standard: ['show', 'showing', 'hiding', 'fade', 'collapse', 'collapsing', 'collapse-horizontal', 'active', 'disabled',
               'was-validated', 'is-invalid', 'is-valid', 'invalid-feedback', 'valid-feedback', 'visually-hidden'],
    greedy: [/^modal/, /^dropdown/, /^offcanvas/, /^tooltip/, /^bs-tooltip/, /^popover/, /^bs-popover/, /^toast/,
             /^carousel/, /^alert/, /^nav/, /^tab/, /^accordion/, /^spinner/, /^progress/, /^placeholder/],
  },
});
fs.writeFileSync(out, res[0].css);
""")
    listing = purge_dir / 'app-content.txt'
    listing.write_text('\n'.join(str(path) for path in APP_SOURCES), encoding='utf-8')
    # উৎস: আগে কপি করা পুরো bootstrap.min.css (COPY দেখুন)
    subprocess.run(['node', str(script), str(STATIC / 'bootstrap' / 'bootstrap.min.css'), str(out), str(listing)],
                   check=True, cwd=purge_dir)
    css = out.read_text(encoding='utf-8')
    css = re.sub(r'/\*#\s*sourceMappingURL=.*?\*/', '', css).strip()
    out.write_text(css + '\n', encoding='utf-8')
    print(f'app bootstrap: {len(css) // 1024} KB')


def main():
    node = Path(sys.argv[1]).resolve()
    for src, dst in COPY.items():
        target = STATIC / dst
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(node / src, target)
    for folder, files in FONTS.items():
        for name in files:
            target = STATIC / 'fonts' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(node / folder / name, target)
    for package in ('@fontsource/hind-siliguri', '@fontsource-variable/plus-jakarta-sans', '@fontsource/syne',
                    '@fontsource-variable/dm-sans'):
        licence = node / package / 'LICENSE'
        if licence.exists():
            shutil.copyfile(licence, STATIC / 'fonts' / f'OFL-{package.split("/")[-1]}.txt')
    # sourceMappingURL থাকলে collectstatic সেই .map ফাইল খোঁজে — নেই, তাই মুছে দেওয়া
    for path in STATIC.rglob('*.js'):
        text = path.read_text(encoding='utf-8')
        cleaned = re.sub(r'\n?//# sourceMappingURL=\S+\s*$', '\n', text)
        if cleaned != text:
            path.write_text(cleaned, encoding='utf-8')
    for path in STATIC.rglob('*.css'):
        text = path.read_text(encoding='utf-8')
        cleaned = re.sub(r'/\*#\s*sourceMappingURL=.*?\*/', '', text)
        if cleaned != text:
            path.write_text(cleaned, encoding='utf-8')
    known = json.loads((node / 'bootstrap-icons/font/bootstrap-icons.json').read_text())
    build_icon_subset(node, known)
    build_app_icon_subset(node, known)
    build_storefront_bootstrap(node)
    build_app_bootstrap(node)


if __name__ == '__main__':
    main()
