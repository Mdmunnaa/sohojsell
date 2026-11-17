"""
SellPunch অ্যাপ (ফোন/কম্পিউটারে বসানো — PWA)। পুরো সাইট এক অ্যাপ: লগইন, ড্যাশবোর্ড, POS সব অ্যাপের ভেতরে খোলে,
উপরে ব্রাউজারের বার আসে না (manifest-এর scope '/')।

- manifest:        /site.webmanifest — নাম, আইকন, কোন পাতা থেকে শুরু, শর্টকাট
- service_worker:  /sw.js — নেট না থাকলে POS খোলে, অন্য পাতায় "নেট নেই" দেখায় (templates/store/app_sw.js)
- app_start:       /app/ — হোম স্ক্রিনের আইকন চাপলে প্রথমে এখানে: লগইন না থাকলে লগইন, POS-এর লোক হলে POS, নাহলে ড্যাশবোর্ড
- legacy_pos_sw:   /pos/sw.js — আগে শুধু POS-এর আলাদা service worker ছিল; এখন সেটা নিজেকে সরিয়ে নেয়

বসানোর বাটন আর নিয়ম: templates/store/partials/app_install.html (হোমপেজ, ড্যাশবোর্ড, POS)।
"""
import functools
import hashlib
import json

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.template.loader import render_to_string
from django.templatetags.static import static
from django.urls import reverse

# আগে শুধু POS অ্যাপ বসানো যেত, তার id ছিল '/pos/'। একই id রাখায় যাদের ফোনে সেই POS অ্যাপ আছে,
# ব্রাউজার নিজে থেকেই সেটাকে পুরো অ্যাপে বদলে নেয় — নতুন করে বসাতে হয় না। এটা আর কখনো বদলাবেন না।
APP_ID = '/pos/'
SW_VERSION = '2'          # app_sw.js-এর নিয়ম বদলালে বাড়ান
THEME = '#D63A2F'
# অ্যাপ খোলার সময় কোথায় যাবে — অ্যাপের ভেতরে শেষবার কোথায় ছিলেন (base.html লেখে: 'pos' বা 'dash')
START_COOKIE = 'sp_app'


def _static(name):
    try:
        return static(name)
    except ValueError:        # manifest-এ নেই (লোকাল/টেস্ট) — সাধারণ ঠিকানা
        return settings.STATIC_URL + name


def _site():
    return getattr(settings, 'SITE_NAME', 'SellPunch')


def manifest(request):
    site = _site()
    icon = _static('brand/icon-192.png')
    data = {
        'id': APP_ID,
        'name': site,
        'short_name': site,
        'description': 'দোকানের POS, অর্ডার, স্টক, কুরিয়ার, বাকির খাতা আর লাভের হিসাব — নেট না থাকলেও POS-এ বিক্রি চলে।',
        'lang': 'bn',
        'dir': 'ltr',
        'start_url': reverse('app_start'),
        'scope': '/',
        'display': 'standalone',
        'orientation': 'any',
        'background_color': '#FFFFFF',
        'theme_color': THEME,
        'categories': ['business', 'productivity', 'finance'],
        # কম্পিউটারে আইকনে আবার চাপলে নতুন জানালা না খুলে আগেরটাই সামনে আসে (POS-এর কার্ট যেমন ছিল তেমন থাকে)
        'launch_handler': {'client_mode': ['focus-existing', 'auto']},
        'icons': [
            {'src': icon, 'sizes': '192x192', 'type': 'image/png', 'purpose': 'any'},
            {'src': _static('brand/icon-512.png'), 'sizes': '512x512', 'type': 'image/png', 'purpose': 'any'},
            {'src': _static('brand/icon-maskable-192.png'), 'sizes': '192x192', 'type': 'image/png', 'purpose': 'maskable'},
            {'src': _static('brand/icon-maskable-512.png'), 'sizes': '512x512', 'type': 'image/png', 'purpose': 'maskable'},
        ],
        # আইকনে আঙুল চেপে ধরলে (বা কম্পিউটারে ডান-ক্লিক) সরাসরি এই পাতাগুলো
        'shortcuts': [
            {'name': 'POS — দোকানে বিক্রি', 'short_name': 'POS', 'url': reverse('pos'),
             'icons': [{'src': icon, 'sizes': '192x192', 'type': 'image/png'}]},
            {'name': 'নতুন অর্ডার', 'short_name': 'নতুন অর্ডার', 'url': reverse('order_create'),
             'icons': [{'src': icon, 'sizes': '192x192', 'type': 'image/png'}]},
            {'name': 'সব অর্ডার', 'short_name': 'অর্ডার', 'url': reverse('order_list'),
             'icons': [{'src': icon, 'sizes': '192x192', 'type': 'image/png'}]},
            {'name': 'প্রোডাক্ট ও স্টক', 'short_name': 'প্রোডাক্ট', 'url': reverse('product_list'),
             'icons': [{'src': icon, 'sizes': '192x192', 'type': 'image/png'}]},
        ],
        # বসানোর সময় Android আর কম্পিউটারের Chrome এই ছবিগুলো দেখায় (Play Store-এর মতো)
        'screenshots': [
            {'src': _static('landing/pos-phone.webp'), 'sizes': '780x1688', 'type': 'image/webp',
             'form_factor': 'narrow', 'label': 'মোবাইলে POS — বারকোড স্ক্যান করে বিল'},
            {'src': _static('landing/shop-phone.webp'), 'sizes': '780x1688', 'type': 'image/webp',
             'form_factor': 'narrow', 'label': 'দোকানের নিজের ওয়েবসাইট'},
            {'src': _static('landing/dashboard.webp'), 'sizes': '1800x1125', 'type': 'image/webp',
             'form_factor': 'wide', 'label': 'ড্যাশবোর্ড — আজকের বিক্রি, লাভ আর নতুন অর্ডার'},
            {'src': _static('landing/pos.webp'), 'sizes': '1800x1125', 'type': 'image/webp',
             'form_factor': 'wide', 'label': 'কম্পিউটারে POS'},
        ],
    }
    response = JsonResponse(data, json_dumps_params={'ensure_ascii': False})
    response['Content-Type'] = 'application/manifest+json'     # JSON সবসময় UTF-8
    response['Cache-Control'] = 'no-cache'
    return response


# সব পাতায় যা লাগে — service worker বসার সময় ডিভাইসে রাখা হয়। POS-এর বাড়তি ফাইল (স্ক্যানার, বারকোড)
# POS পাতা নিজে পাঠায়, তাই যারা POS খোলেন না তাদের ফোনে নামে না।
CORE_FILES = ['vendor/bootstrap/bootstrap-app.min.css', 'vendor/bootstrap/bootstrap.bundle.min.js',
              'vendor/sweetalert2/sweetalert2.all.min.js', 'brand/sellpunch-logo.svg', 'brand/sellpunch-mark.svg',
              'brand/icon-192.png']


@functools.lru_cache(maxsize=1)
def _static_fingerprint():
    """সব static ফাইলের (hash-ওয়ালা) নাম মিলিয়ে একটা ছাপ — কোনো ফাইল বদলালেই (নতুন deploy) service worker-এর
    সংস্করণ বদলায়, ডিভাইসে জমা পুরনো ফাইল মুছে যায়। জমা ফাইল তাই কখনো বাড়তে বাড়তে ফোন ভরায় না।"""
    from django.contrib.staticfiles.storage import staticfiles_storage
    names = sorted(getattr(staticfiles_storage, 'hashed_files', {}).values())
    return hashlib.sha1('|'.join(map(str, names)).encode()).hexdigest()


def service_worker(request):
    """লগইন লাগে না, ভেতরে কারো তথ্য নেই। ঠিকানা /sw.js — তাই পুরো সাইট এর আওতায়।"""
    precache = []
    for name in CORE_FILES:
        try:
            precache.append(static(name))
        except ValueError:            # manifest-এ নেই (টেস্ট/লোকাল) — বাদ
            continue
    version = hashlib.sha1('|'.join([SW_VERSION, _static_fingerprint()] + precache).encode()).hexdigest()[:12]
    body = render_to_string('store/app_sw.js', {
        'version': version, 'precache': json.dumps(precache), 'pos_url': reverse('pos'),
        'app_url': reverse('app_start'), 'mark': json.dumps(_static('brand/sellpunch-mark.svg')),
        'network_first': settings.DEBUG,
    })
    response = HttpResponse(body, content_type='application/javascript; charset=utf-8')
    response['Cache-Control'] = 'no-cache'
    return response


LEGACY_POS_SW = """/* আগে POS-এর আলাদা service worker ছিল (/pos/)। এখন পুরো সাইটের /sw.js সব করে — এটা নিজেকে সরিয়ে নেয়। */
self.addEventListener('install', function () { self.skipWaiting(); });
self.addEventListener('activate', function (event) {
  event.waitUntil(caches.keys().then(function (keys) {
    return Promise.all(keys.filter(function (k) { return k.indexOf('sp-pos-static-') === 0; })
      .map(function (k) { return caches.delete(k); }));
  }).then(function () { return self.registration.unregister(); }));
});
"""


def legacy_pos_sw(request):
    response = HttpResponse(LEGACY_POS_SW, content_type='application/javascript; charset=utf-8')
    response['Cache-Control'] = 'no-cache'
    response['Service-Worker-Allowed'] = reverse('pos')
    return response


def pos_first(request):
    """অ্যাপ খুললে বা লগইনের পর সোজা POS-এ যাবে কিনা: শুধু POS-এর অনুমতি থাকা স্টাফ, বা অ্যাপে শেষবার POS-এ ছিলেন।"""
    user = request.user
    wants_pos = request.COOKIES.get(START_COOKIE) == 'pos'
    # স্টাফ: নিজের দোকান নেই, অন্যের দোকানের StaffProfile আছে (store.middleware.StaffAccessMiddleware-এর মতো;
    # লগইনের ঠিক পরে middleware তখনো চলেনি, তাই is_shop_staff না থাকলেও দেখা হয়)
    if getattr(user, 'is_shop_staff', False) or (not hasattr(user, 'shop') and hasattr(user, 'staff_profile')):
        staff = user.staff_profile
        if not staff.can_use_pos:
            return False
        others = (staff.can_manage_orders, staff.can_manage_products, staff.can_manage_customers,
                  staff.can_view_reports, staff.can_manage_settings, staff.can_send_sms)
        return wants_pos or not any(others)
    return wants_pos and hasattr(user, 'shop')


def home_for(request):
    """লগইন করা মানুষটা কোন পাতা থেকে শুরু করবেন (অ্যাপ খোলা, লগইনের পর)।"""
    if request.user.is_superuser:
        return reverse('master_dashboard')
    if pos_first(request):
        return reverse('pos')
    return reverse('dashboard')


def app_start(request):
    if not request.user.is_authenticated:
        return redirect('login')
    return redirect(home_for(request))
