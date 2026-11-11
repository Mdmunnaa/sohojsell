"""
লাইভ ডেমো দোকান — হোমপেজের "লাইভ ডেমো দেখুন" বাটন থেকে যে কেউ পাসওয়ার্ড ছাড়া ঢুকে
পুরো সফটওয়্যারটা চালিয়ে দেখতে পারে (Edumi-র ডেমোর মতো)।

- build(): "ফ্যাশন পয়েন্ট" নামের একটা সাজানো দোকান বানায় — আসল ছবির ৩০টা প্রোডাক্ট, ৯০ দিনের
  দোকান + ওয়েবসাইটের বিক্রি, কাস্টমার, বাকি, মাল কেনা, খরচ, রিভিউ, কুপন, ল্যান্ডিং পেজ, SMS-এর ইতিহাস।
  বারবার চালালে হিসাবের সবকিছু মুছে আবার বানায়; প্রোডাক্টের ছবি একবার আপলোড হলে আর হয় না।
- reset_if_stale(): কেউ /demo/ খুললে ২৪ ঘণ্টার পুরনো হলে নিজে থেকে আবার আগের মতো করে
  (`manage.py seed_demo` দিয়ে cron থেকেও চালানো যায়)।
- DemoGuardMiddleware: ডেমোতে সেটিংস/বিল/স্টাফ/মুছে ফেলা বন্ধ; SMS "যায়" কিন্তু আসলে কারো কাছে যায় না।
"""
import logging
import os
import random
from datetime import datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import redirect
from django.utils import timezone

logger = logging.getLogger(__name__)

DEMO_SLUG = 'demo'
DEMO_PHONE = '01700000001'
DEMO_STAFF_PHONE = '01700000002'
SHOP_NAME = 'ফ্যাশন পয়েন্ট'
RESET_AFTER = timedelta(hours=24)
HISTORY_DAYS = 90
PHOTO_DIR = Path(__file__).resolve().parent / 'demo' / 'photos'
BLOCKED_MESSAGE = 'ডেমোতে এটা বদলানো যায় না। নিজের দোকান খুললে সবকিছু করতে পারবেন।'
ZERO = Decimal('0')
LAST_ERROR = ''          # শেষবার ডেমো বানাতে গিয়ে কী ভুল হয়েছিল (মাস্টারকে দেখানোর জন্য)

# ডেমোতে POST করা যাবে না এমন জায়গা (যা বদলালে ডেমো ভেঙে যায় বা বাইরে টাকা/SMS যায়)
BLOCKED_PREFIXES = ('/settings/', '/billing/', '/payment/', '/staff/', '/sms/buy/', '/facebook/', '/setup-shop/',
                    '/orders/send-courier/', '/courier/', '/accounts/signup/', '/website/settlement/')
BLOCKED_WEBSITE_SECTIONS = ('store', 'domain', 'payment')

# (কোড, ক্যাটাগরি, নাম, ছবি, দাম, কেনা দাম, আগের দাম, বিবরণ, ভ্যারিয়েন্ট, স্টক, জনপ্রিয়তা)
PRODUCTS = [
    ('DEMO-01', 'টি-শার্ট', 'প্রিমিয়াম কটন টি-শার্ট (সাদা)', 'tshirt-white', 450, 260, 550,
     '১০০% কম্বড কটন, ১৮০ GSM। ধোয়ার পরেও রং ও সাইজ ঠিক থাকে। রেগুলার ফিট।', ['M', 'L', 'XL'], 34, 10),
    ('DEMO-02', 'টি-শার্ট', 'ব্ল্যাক রাউন্ড নেক টি-শার্ট', 'tshirt-black', 420, 240, None,
     'নরম কটন, ঘামে আরাম। অফিস বা ঘোরাঘুরি সব জায়গায় চলে।', ['M', 'L', 'XL'], 41, 9),
    ('DEMO-03', 'টি-শার্ট', 'প্রিন্টেড হাফ স্লিভ টি-শার্ট', 'tshirt-print', 550, 320, 650,
     'স্ক্রিন প্রিন্ট, রং ওঠে না। সাদা কটন কাপড়।', ['M', 'L', 'XL'], 18, 6),
    ('DEMO-04', 'টি-শার্ট', 'স্ট্রাইপ টি-শার্ট (মেয়েদের)', 'tshirt-stripe', 490, 280, None,
     'নেভি-সাদা স্ট্রাইপ, স্লিম ফিট। ক্যাজুয়াল লুকের জন্য।', ['S', 'M', 'L'], 12, 5),
    ('DEMO-05', 'টি-শার্ট', 'মাস্টার্ড কটন টি-শার্ট', 'tshirt-mustard', 480, 270, None,
     'পকেটসহ মাস্টার্ড রঙের কটন টি-শার্ট।', ['M', 'L', 'XL'], 3, 4),
    ('DEMO-06', 'শার্ট', 'ডেনিম ফুল স্লিভ শার্ট', 'shirt-denim', 1150, 720, 1350,
     'লাইট ব্লু ডেনিম, বাটন-ডাউন কলার। জিন্স বা চিনোর সাথে মানায়।', ['M', 'L', 'XL'], 22, 8),
    ('DEMO-07', 'শার্ট', 'ফরমাল সাদা শার্ট', 'shirt-white', 950, 580, None,
     'অফিস আর অনুষ্ঠানের জন্য। ইস্ত্রি সহজ, কুঁচকায় কম।', ['M', 'L', 'XL', 'XXL'], 27, 7),
    ('DEMO-08', 'শার্ট', 'চেক ক্যাজুয়াল শার্ট', 'shirt-check', 1050, 650, 1250,
     'রঙিন চেক, নরম কটন। ফুল স্লিভ, হাতা গুটিয়েও পরা যায়।', ['M', 'L', 'XL'], 15, 6),
    ('DEMO-09', 'শার্ট', 'লাইট চেক ফুল স্লিভ শার্ট', 'shirt-lightcheck', 980, 600, None,
     'সাদা-সবুজ ছোট চেক। সেমি-ফরমাল।', ['M', 'L', 'XL'], 9, 4),
    ('DEMO-10', 'শার্ট', 'হাফ স্লিভ ক্যাজুয়াল শার্ট', 'shirt-half', 850, 520, None,
     'গরমের জন্য হালকা কাপড়ের হাফ স্লিভ শার্ট।', ['M', 'L', 'XL'], 2, 3),
    ('DEMO-11', 'প্যান্ট ও জিন্স', 'স্লিম ফিট ব্লু জিন্স', 'jeans-blue', 1350, 850, 1600,
     'স্ট্রেচ ডেনিম, স্লিম ফিট। কোমর ৩০–৩৪।', ['30', '32', '34'], 26, 9),
    ('DEMO-12', 'প্যান্ট ও জিন্স', 'ব্ল্যাক স্ট্রেচ জিন্স', 'jeans-black', 1290, 800, None,
     'কালো স্ট্রেচ ডেনিম, কালার ফেড হয় না।', ['30', '32', '34', '36'], 19, 6),
    ('DEMO-13', 'প্যান্ট ও জিন্স', 'কার্গো জগার প্যান্ট (খাকি)', 'jogger-khaki', 1100, 680, None,
     'সাইড পকেট, ইলাস্টিক কোমর। ঘোরাঘুরির জন্য আরামদায়ক।', ['M', 'L', 'XL'], 14, 5),
    ('DEMO-14', 'প্যান্ট ও জিন্স', 'রেগুলার ফিট ডেনিম প্যান্ট', 'jeans-regular', 1250, 780, None,
     'ক্লাসিক ব্লু, রেগুলার ফিট। সব বয়সের জন্য।', ['30', '32', '34', '36'], 11, 4),
    ('DEMO-15', 'মেয়েদের ড্রেস', 'পিংক সামার ফ্রক', 'dress-pink', 1450, 900, 1800,
     'হালকা কটন, ছোট চেক প্রিন্ট। গরমে আরাম।', ['S', 'M', 'L'], 16, 7),
    ('DEMO-16', 'মেয়েদের ড্রেস', 'লেস পার্টি ড্রেস (টারকোয়েজ)', 'dress-lace', 2200, 1400, 2600,
     'লেস ডিজাইন, পার্টি বা বিয়ের দাওয়াতের জন্য।', ['S', 'M', 'L'], 7, 5),
    ('DEMO-17', 'মেয়েদের ড্রেস', 'ফ্লোরাল প্রিন্ট ড্রেস', 'dress-floral', 1650, 1000, None,
     'সাদার ওপর নীল ফুলের প্রিন্ট, স্লিভলেস।', ['S', 'M', 'L'], 13, 6),
    ('DEMO-18', 'মেয়েদের ড্রেস', 'প্রিন্টেড মিডি ড্রেস', 'dress-midi', 1550, 950, None,
     'থ্রি-কোয়ার্টার হাতা, হাঁটু ছাড়ানো লম্বা।', ['M', 'L', 'XL'], 10, 4),
    ('DEMO-19', 'মেয়েদের ড্রেস', 'বাচ্চাদের পিংক পার্টি ফ্রক', 'dress-kids', 890, 520, 1100,
     '৩–৬ বছরের বাচ্চাদের জন্য। নরম কাপড়, ভেতরে লাইনিং।', ['3-4', '5-6'], 20, 6),
    ('DEMO-20', 'জুতা', 'লেদার ক্যাজুয়াল শু (ব্রাউন)', 'shoe-leather', 2450, 1600, 2900,
     'আসল চামড়া, রাবার সোল। অফিস আর ক্যাজুয়াল দুটোতেই।', ['40', '41', '42', '43'], 17, 8),
    ('DEMO-21', 'জুতা', 'স্পোর্টস স্নিকার্স (স্কাই ব্লু)', 'sneaker-blue', 1850, 1200, None,
     'হালকা, হাঁটা-দৌড়ানোর জন্য। ব্রিদেবল মেশ।', ['39', '40', '41', '42'], 12, 6),
    ('DEMO-22', 'জুতা', 'ব্ল্যাক স্নিকার্স', 'sneaker-black', 1950, 1250, 2300,
     'কালো লেদার-লুক, সাদা সোল। যেকোনো পোশাকের সাথে।', ['40', '41', '42', '43', '44'], 23, 9),
    ('DEMO-23', 'জুতা', 'লেডিস ওয়েজ হিল', 'wedge-red', 1750, 1100, None,
     'মেরুন রঙ, ৩ ইঞ্চি ওয়েজ হিল। পার্টির জন্য।', ['36', '37', '38', '39'], 6, 4),
    ('DEMO-24', 'জুতা', 'স্লাইড স্যান্ডেল', 'slide', 650, 380, 800,
     'ঘরে-বাইরে পরার আরামদায়ক স্লাইড।', ['40', '41', '42', '43'], 38, 7),
    ('DEMO-25', 'শীতের পোশাক', 'বোম্বার জ্যাকেট (অলিভ)', 'jacket-bomber', 2850, 1900, 3400,
     'উইন্ডপ্রুফ, ভেতরে নরম লাইনিং। শীতের শুরুর জন্য।', ['M', 'L', 'XL'], 9, 7),
    ('DEMO-26', 'শীতের পোশাক', 'পাফার জ্যাকেট (নেভি)', 'jacket-puffer', 3200, 2150, 3900,
     'হুডসহ মোটা পাফার জ্যাকেট। কনকনে শীতেও গরম।', ['M', 'L', 'XL'], 5, 6),
    ('DEMO-27', 'শীতের পোশাক', 'ফুল স্লিভ সোয়েটার (নেভি)', 'sweater-navy', 1250, 780, None,
     'উলের মিশ্রণ, চুলকায় না। ভি-নেক।', ['M', 'L', 'XL'], 21, 6),
    ('DEMO-28', 'শীতের পোশাক', 'স্ট্রাইপ হাই-নেক সোয়েটার', 'sweater-stripe', 1350, 850, 1600,
     'হাই-নেক, নেভি-সাদা স্ট্রাইপ।', ['M', 'L', 'XL'], 0, 5),
    ('DEMO-29', 'শীতের পোশাক', 'লেডিস কার্ডিগান (লাইম)', 'cardigan-lime', 1150, 700, None,
     'বাটন কার্ডিগান, হালকা শীতের জন্য।', ['S', 'M', 'L'], 8, 3),
    ('DEMO-30', 'এক্সেসরিজ', 'ব্ল্যাক বেসবল ক্যাপ', 'cap-black', 350, 180, 450,
     'অ্যাডজাস্টেবল স্ট্র্যাপ, এক সাইজ সবার।', [], 44, 5),
]
CATEGORIES = ['টি-শার্ট', 'শার্ট', 'প্যান্ট ও জিন্স', 'মেয়েদের ড্রেস', 'জুতা', 'শীতের পোশাক', 'এক্সেসরিজ']
BANNERS = [('banner-1', 'শীতের নতুন কালেকশন'), ('banner-2', '২,০০০ টাকার উপরে ডেলিভারি ফ্রি')]
ZONES = [('ঢাকার ভেতরে', 60), ('ঢাকার বাইরে', 120)]
SUPPLIERS = [('নিউ মার্কেট গার্মেন্টস', '01811111111', 'নিউ মার্কেট, ঢাকা', 0),
             ('বঙ্গবাজার হোলসেল', '01922222222', 'বঙ্গবাজার, ঢাকা', 4500),
             ('কেরানীগঞ্জ জিন্স হাউস', '01733333333', 'কেরানীগঞ্জ, ঢাকা', 0)]

FIRST_NAMES = ['রাকিব', 'সুমাইয়া', 'তানভীর', 'নুসরাত', 'আরিফ', 'ফারজানা', 'সাকিব', 'মিম', 'রাফি', 'জান্নাত',
               'ইমরান', 'তাসনিম', 'মাহমুদ', 'সাদিয়া', 'নাঈম', 'রুমা', 'শাকিল', 'লামিয়া', 'হাসান', 'মারিয়া',
               'সজীব', 'আফরিন', 'রবিউল', 'শারমিন', 'জুবায়ের', 'তানিয়া', 'ফাহিম', 'রিয়া', 'মেহেদী', 'নাবিলা',
               'আসিফ', 'সাবরিনা', 'রনি', 'মৌসুমী', 'শুভ', 'প্রিয়া', 'কামরুল', 'ঐশী', 'সোহেল', 'অর্পিতা']
LAST_NAMES = ['হোসেন', 'আহমেদ', 'ইসলাম', 'রহমান', 'খান', 'আক্তার', 'চৌধুরী', 'সরকার', 'মিয়া', 'হাসান',
              'উদ্দিন', 'বেগম', 'শেখ', 'তালুকদার', 'মজুমদার']
AREAS = ['মিরপুর ১০, ঢাকা', 'উত্তরা সেক্টর ৭, ঢাকা', 'ধানমন্ডি ২৭, ঢাকা', 'মোহাম্মদপুর, ঢাকা', 'বনশ্রী, ঢাকা',
         'বাড্ডা, ঢাকা', 'সাভার বাজার, ঢাকা', 'গাজীপুর চৌরাস্তা', 'নারায়ণগঞ্জ সদর', 'আগ্রাবাদ, চট্টগ্রাম',
         'হালিশহর, চট্টগ্রাম', 'জিন্দাবাজার, সিলেট', 'শিববাড়ি, খুলনা', 'সাহেব বাজার, রাজশাহী', 'বরিশাল সদর',
         'কুমিল্লা কান্দিরপাড়', 'ময়মনসিংহ গাঙ্গিনারপাড়', 'টাঙ্গাইল সদর', 'বগুড়া সাতমাথা', 'রংপুর জাহাজ কোম্পানি মোড়']
REVIEWS = [
    'কাপড়ের মান খুব ভালো, ছবির সাথে হুবহু মিল আছে।', 'সাইজ একদম ঠিক ছিল, ২ দিনেই ডেলিভারি পেয়েছি।',
    'দামের তুলনায় অনেক ভালো। আবার নেব ইনশাআল্লাহ।', 'প্যাকেজিং সুন্দর ছিল, প্রোডাক্ট অরিজিনাল।',
    'একটু দেরিতে পেয়েছি কিন্তু প্রোডাক্ট ভালো।', 'রং ছবির চেয়ে সামান্য হালকা, তবে কোয়ালিটি ঠিক আছে।',
    'ভাইয়ার ব্যবহার খুব ভালো, ফোনে সব বুঝিয়ে দিয়েছেন।', 'গিফট দিয়েছিলাম, সবাই পছন্দ করেছে।',
    'তিনবার অর্ডার করলাম, প্রতিবারই ঠিকঠাক।', 'সেলাই মজবুত, ধোয়ার পরেও কিছু হয়নি।',
    'ডেলিভারি ম্যান ফোন দিয়ে ঠিক সময়ে এসেছে।', 'ফিটিং পারফেক্ট। ধন্যবাদ ফ্যাশন পয়েন্ট।',
]
SMS_CAMPAIGNS = [
    ('সব কাস্টমার', 'ফ্যাশন পয়েন্টে শীতের নতুন কালেকশন এসে গেছে! EID20 কুপনে ২০% ছাড়। অর্ডার: demo.sellpunch.com', 118),
    ('গত ৩০ দিনের ক্রেতা', 'প্রিয় কাস্টমার, ২,০০০ টাকার উপরে অর্ডারে ডেলিভারি ফ্রি - শুধু এই সপ্তাহে। ফ্যাশন পয়েন্ট', 64),
]


def _photo(name):
    """repo-র store/demo/photos থেকে ছবি → ContentFile (নাম দিয়ে চেনা যায়: demo-<name>)।"""
    path = PHOTO_DIR / name
    return ContentFile(path.read_bytes(), name=f'demo-{path.stem}{path.suffix}')


def _has_photo(file_field, stem):
    return bool(file_field) and os.path.basename(file_field.name).startswith(f'demo-{stem}')


def _name(rng):
    return f'{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}'


def _phone(rng):
    return '01' + rng.choice('3456789') + ''.join(rng.choice('0123456789') for _ in range(8))


def _at(day, hour, minute=0):
    tz = timezone.get_current_timezone()
    return timezone.make_aware(datetime.combine(day, time(hour, minute)), tz)


# ============================================================
# খোঁজা
# ============================================================
def demo_shop():
    from .models import Shop
    return Shop.objects.filter(is_demo=True).first()


def is_demo_user(user):
    shop = getattr(user, 'shop', None) if getattr(user, 'is_authenticated', False) else None
    return bool(shop and shop.is_demo)


def demo_login_url():
    from django.urls import reverse
    return reverse('demo_start')


# ============================================================
# বানানো
# ============================================================
def build():
    """ডেমো দোকান বানায় বা আগের মতো করে; দোকানটা ফেরত দেয়।"""
    from .models import Shop
    rng = random.Random(20240)
    with transaction.atomic():
        shop = _shop()
        _wipe_activity(shop)
        categories = _categories(shop)
        products = _products(shop, categories)
        _banners(shop)
        _zones(shop)
        staff_user = _staff(shop)
        state = _history(shop, rng, products, staff_user)
        _reviews(shop, rng, products, state)
        _coupons(shop, products, state['coupons_used'])
        _landing(shop, products, state)
        _sms_history(shop, state)
        Shop.objects.filter(pk=shop.pk).update(demo_reset_at=timezone.now(), sms_balance=437)
    return shop


def reset_if_stale(max_age=RESET_AFTER):
    """
    ২৪ ঘণ্টা পার হলে ডেমো আবার আগের মতো করে। একসাথে দুজন এলে একজনই করে (আগে সময়টা বসিয়ে নেয়)।
    ডেমো দোকান না থাকলে বানায়। ফেরত: দোকান (না বানাতে পারলে None)।
    """
    global LAST_ERROR
    from .models import Shop
    shop = demo_shop()
    if shop is None:
        try:
            shop = build()
            LAST_ERROR = ''
            return shop
        except Exception as exc:    # noqa: BLE001 — ডেমো না থাকলে সাইট আটকাবে না
            logger.exception('Demo shop could not be built')
            LAST_ERROR = f'{type(exc).__name__}: {exc}'
            return None
    now = timezone.now()
    claimed = (Shop.objects.filter(pk=shop.pk)
               .filter(Q(demo_reset_at__isnull=True) | Q(demo_reset_at__lt=now - max_age))
               .update(demo_reset_at=now))
    if claimed:
        try:
            build()
            LAST_ERROR = ''
        except Exception as exc:    # noqa: BLE001
            logger.exception('Demo shop reset failed')
            LAST_ERROR = f'{type(exc).__name__}: {exc}'
            Shop.objects.filter(pk=shop.pk).update(demo_reset_at=None)
    return shop


def _demo_user(existing, first_phone, name):
    """
    ডেমোর ইউজার: আগেরটা থাকলে সেটাই; নইলে এমন নম্বরে নতুন বানায় যেটা কোনো আসল মানুষের না
    (01700000001 কেউ টেস্ট করতে নিয়ে থাকলে আসল অ্যাকাউন্ট ছোঁয়া হয় না — পরের খালি নম্বর নেয়)।
    """
    from django.contrib.auth import get_user_model
    User = get_user_model()
    user = existing
    if user is None:
        for step in range(0, 100):
            phone = str(int(first_phone) + step * 10).zfill(11)
            found = User.objects.filter(phone_number=phone).first()
            if found is None:
                user = User(phone_number=phone, name=name)
                break
            if not (found.is_superuser or found.is_staff or hasattr(found, 'shop') or hasattr(found, 'staff_profile')):
                user = found
                break
        else:
            raise RuntimeError('ডেমোর জন্য খালি মোবাইল নম্বর পাওয়া যায়নি')
    user.set_unusable_password()
    user.name, user.is_active, user.is_staff, user.is_superuser = name, True, False, False
    user.save()
    return user


def _shop():
    from .models import Shop
    shop = Shop.objects.filter(is_demo=True).select_related('user').first()
    user = _demo_user(shop.user if shop else None, DEMO_PHONE, 'ডেমো সেলার')
    shop = shop or Shop(user=user)
    other = Shop.objects.filter(slug=DEMO_SLUG).exclude(user=user).first()
    shop.slug = DEMO_SLUG if other is None else 'demo-shop'
    shop.name, shop.is_demo = SHOP_NAME, True
    shop.phone, shop.whatsapp_number = DEMO_PHONE, DEMO_PHONE
    shop.address = 'দোকান নং ১২, লেভেল ২, নিউ মার্কেট, ঢাকা-১২০৫'
    shop.facebook_page_url = 'https://facebook.com/'
    shop.store_tagline = shop.storefront_tagline = 'ট্রেন্ডি পোশাক, সারা দেশে ক্যাশ অন ডেলিভারি'
    shop.announcement_text = '🎉 ২,০০০ টাকার উপরে অর্ডারে ডেলিভারি ফ্রি · কুপন EID20 দিলে ২০% ছাড়'
    shop.storefront_theme, shop.storefront_design, shop.storefront_color = 'pink', 'bold', ''
    shop.free_delivery_min = Decimal('2000')
    shop.payment_rule = Shop.PAYMENT_COD
    shop.return_policy = ('পণ্য হাতে পেয়ে ডেলিভারি ম্যানের সামনে চেক করুন। সাইজ না মিললে বা পণ্যে সমস্যা থাকলে '
                          '৩ দিনের মধ্যে জানালে বদলে দেওয়া হয়।')
    shop.privacy_policy = 'আপনার নাম, ফোন নম্বর আর ঠিকানা শুধু অর্ডার ডেলিভারির কাজে ব্যবহার হয়।'
    shop.pos_receipt_note = '৭ দিনের মধ্যে রসিদসহ বদলানো যাবে'
    shop.pos_vat_percent, shop.pos_auto_print = ZERO, False
    shop.is_sms_active = shop.sms_on_received = shop.sms_on_shipped = True
    shop.sms_on_confirmed = shop.sms_on_delivered = False
    shop.due_reminder_days = 7
    shop.reviews_enabled, shop.reviews_auto_approve, shop.show_sold_count = True, False, True
    shop.subscription_plan, shop.is_paid, shop.is_locked = 'Premium', True, False
    shop.valid_until = timezone.localdate() + timedelta(days=3650)
    shop.custom_domain = None
    # কুরিয়ার "কানেক্ট" দেখায়, কিন্তু ডেমো থেকে পার্সেল পাঠানো বন্ধ (BLOCKED_PREFIXES)
    shop.steadfast_api_key = shop.steadfast_secret_key = 'demo'
    shop.sms_api_key = None
    if not _has_photo(shop.logo, 'logo'):
        shop.logo = _photo('logo.png')
    shop.save()
    return shop


def _wipe_activity(shop):
    """হিসাবের সবকিছু মুছে ফেলা (প্রোডাক্ট, ক্যাটাগরি, ব্যানার থাকে — ওগুলো আলাদাভাবে মেলানো হয়)।"""
    from .models import (AbandonedCheckout, Coupon, Customer, Expense, LandingPage, Order, PageView, ProductReview,
                         Purchase, SmsLog, StorefrontOrder, Supplier)
    for model in (StorefrontOrder, Order, Customer, Purchase, Supplier, Expense, Coupon, AbandonedCheckout,
                  LandingPage, SmsLog, PageView):
        model.objects.filter(shop=shop).delete()
    for review in ProductReview.objects.filter(shop=shop).exclude(image=''):
        review.image.delete(save=False)
    ProductReview.objects.filter(shop=shop).delete()


def _categories(shop):
    from .models import Category
    found = {c.name: c for c in Category.objects.filter(shop=shop)}
    for name in CATEGORIES:
        if name not in found:
            found[name] = Category.objects.create(shop=shop, name=name)
    Category.objects.filter(shop=shop).exclude(name__in=CATEGORIES).delete()
    return found


def _products(shop, categories):
    from .models import Product, ProductVariant
    existing = {p.barcode: p for p in Product.objects.filter(shop=shop)}
    kept = []
    for code, category, name, photo, price, cost, compare, description, variant_names, stock, _pop in PRODUCTS:
        product = existing.pop(code, None) or Product(shop=shop, barcode=code)
        product.name, product.category, product.description = name, categories[category], description
        product.price, product.cost_price = Decimal(price), Decimal(cost)
        product.compare_price = Decimal(compare) if compare else None
        product.is_active, product.has_variants = True, bool(variant_names)
        product.stock_quantity = stock
        if not _has_photo(product.image, photo):
            product.image = _photo(f'{photo}.jpg')
        product.save()
        product.variants.all().delete()
        if variant_names:
            shares = _split(stock, len(variant_names))
            ProductVariant.objects.bulk_create([
                ProductVariant(product=product, name=vname, stock_quantity=share, position=i,
                               barcode=f'{code}-{vname}')
                for i, (vname, share) in enumerate(zip(variant_names, shares))])
        product.variant_list = list(product.variants.all())
        kept.append(product)
    for product in existing.values():      # দর্শক যা বানিয়েছে
        for field in (product.image, product.thumbnail):
            if field:
                field.delete(save=False)
        product.delete()
    return kept


def _split(total, parts):
    base, extra = divmod(total, parts)
    return [base + (1 if i < extra else 0) for i in range(parts)]


def _banners(shop):
    from .models import Banner
    found = {b.title: b for b in Banner.objects.filter(shop=shop)}
    for photo, title in BANNERS:
        banner = found.pop(title, None)
        if banner is None or not _has_photo(banner.image, photo):
            if banner is not None:
                banner.delete()
            Banner.objects.create(shop=shop, image=_photo(f'{photo}.jpg'), title=title, is_active=True)
        elif not banner.is_active:
            banner.is_active = True
            banner.save(update_fields=['is_active'])
    for banner in found.values():
        banner.image.delete(save=False)
        banner.delete()


def _zones(shop):
    from .models import DeliveryZone
    DeliveryZone.objects.filter(shop=shop).delete()
    DeliveryZone.objects.bulk_create([DeliveryZone(shop=shop, name=name, charge=Decimal(charge), sort_order=i)
                                      for i, (name, charge) in enumerate(ZONES)])


def _staff(shop):
    from .models import StaffProfile
    current = StaffProfile.objects.filter(shop=shop).select_related('user').first()
    user = _demo_user(current.user if current else None, DEMO_STAFF_PHONE, 'রাকিব (ক্যাশিয়ার)')
    StaffProfile.objects.filter(shop=shop).exclude(user=user).delete()
    StaffProfile.objects.update_or_create(user=user, defaults={
        'shop': shop, 'can_use_pos': True, 'can_manage_products': False, 'can_manage_orders': True,
        'can_manage_customers': True, 'can_view_reports': False, 'can_manage_settings': False, 'can_send_sms': False})
    return user


# ---------------------------------------------------------------- ৯০ দিনের ইতিহাস
def _history(shop, rng, products, staff_user):
    """অর্ডার, কাস্টমার, পেমেন্ট, বাকি, মাল কেনা, খরচ — সব একসাথে (bulk) যাতে রিসেট দ্রুত হয়।"""
    from .models import (Customer, Expense, Order, OrderItem, Purchase, PurchaseItem, SalePayment, StorefrontOrder,
                         StorefrontOrderItem, Supplier, SupplierPayment)
    from .pos import POS_ADDRESS, WALK_IN_NAME, WALK_IN_PHONE
    today = timezone.localdate()
    first_day = today - timedelta(days=HISTORY_DAYS)
    weights = [spec[10] for spec in PRODUCTS]

    # কাস্টমার: ওয়েবসাইটের ৪৮ জন (কয়েকজন বারবার কেনে), দোকানের নামে-লেখা ১৫ জন, আর walk-in
    web_customers = [Customer(shop=shop, name=_name(rng), phone=_phone(rng), address=f'{rng.choice(AREAS)}')
                     for _ in range(48)]
    pos_customers = [Customer(shop=shop, name=_name(rng), phone=_phone(rng), address=POS_ADDRESS) for _ in range(15)]
    walk_in = Customer(shop=shop, name=WALK_IN_NAME, phone=WALK_IN_PHONE, address=POS_ADDRESS)
    Customer.objects.bulk_create(web_customers + pos_customers + [walk_in])
    for customer in web_customers + pos_customers:
        customer.created_at = _at(first_day + timedelta(days=rng.randint(0, HISTORY_DAYS)), rng.randint(9, 21))
    Customer.objects.bulk_update(web_customers + pos_customers, ['created_at'])
    loyal = web_customers[:10]
    risky = web_customers[-3:]          # যাদের অর্ডার ফেরত আসে

    orders, items, sf_orders, sf_items, payments = [], [], [], [], []
    due_plan = []          # (order, paid অংশ) — বাকির খাতা
    web_pick = lambda: rng.choice(loyal) if rng.random() < 0.35 else rng.choice(web_customers)   # noqa: E731
    coupons_used = {'EID20': 0, 'FREEDEL': 0, 'NEW100': 0}
    landing_orders = []
    zones = ZONES

    for back in range(HISTORY_DAYS, -1, -1):
        day = today - timedelta(days=back)
        growth = 0.8 + 0.45 * (HISTORY_DAYS - back) / HISTORY_DAYS
        weekday = {4: 1.35, 5: 1.3, 6: 1.05}.get(day.weekday(), 0.9)
        n_web = max(0, round(rng.gauss(2.6 * growth * weekday, 1.1)))
        n_pos = max(0, round(rng.gauss(3.8 * growth * weekday, 1.4)))
        if back <= 1:          # আজ-কালকের নতুন অর্ডার যেন ড্যাশবোর্ডে চোখে পড়ে
            n_web = max(4, n_web)
        if back == 0:
            n_pos = max(3, n_pos // 2)

        for _ in range(n_web):
            when = _clock(rng, day, 9, 23, back)
            customer = rng.choice(risky) if rng.random() < 0.06 else web_pick()
            lines = _lines(rng, products, weights, max_lines=3)
            subtotal = sum(price * qty for _p, _v, price, qty in lines)
            zone_name, charge = zones[0] if rng.random() < 0.6 else zones[1]
            delivery = ZERO if subtotal >= 2000 else Decimal(charge)
            discount, coupon = ZERO, ''
            roll = rng.random()
            if roll < 0.12 and subtotal >= 999:
                coupon, discount = 'EID20', min((subtotal * Decimal('0.2')).quantize(Decimal('1')), Decimal(300))
            elif roll < 0.17 and subtotal >= 1500 and delivery:
                coupon, delivery = 'FREEDEL', ZERO
            elif roll < 0.20 and subtotal >= 800:
                coupon, discount = 'NEW100', Decimal(100)
            if coupon:
                coupons_used[coupon] += 1
            total = subtotal - discount + delivery
            status = _web_status(rng, back, customer in risky)
            note = ' · '.join(x for x in [f'এলাকা: {zone_name}', f'কুপন {coupon}' if coupon else ''] if x)
            order = Order(shop=shop, customer=customer, source='storefront', delivery_charge=delivery,
                          discount=discount, payment_method='COD', status=status, total_amount=total,
                          note=note, coupon_code=coupon, stock_returned=status in ('Returned', 'Cancelled'),
                          steadfast_tracking_code=f'SF{rng.randint(10000000, 99999999)}' if status in ('Shipped', 'Delivered', 'Returned') and rng.random() < 0.7 else None,
                          courier_partner='Steadfast' if status in ('Shipped', 'Delivered', 'Returned') else None)
            order.when = when
            order.lines = lines
            order.zone_name = zone_name
            orders.append(order)
            if lines[0][0].barcode == 'DEMO-01' and rng.random() < 0.5:
                landing_orders.append(order)

        for _ in range(n_pos):
            when = _clock(rng, day, 10, 21, back)
            lines = _lines(rng, products, weights, max_lines=4)
            subtotal = sum(price * qty for _p, _v, price, qty in lines)
            discount = ZERO
            if rng.random() < 0.25:
                discount = Decimal(rng.choice([50, 100, 150, 200]))
                discount = min(discount, subtotal)
            total = subtotal - discount
            named = rng.random() < 0.3
            customer = rng.choice(pos_customers) if named else walk_in
            paid = total
            due_sale = named and back <= 40 and rng.random() < 0.35
            if due_sale:
                paid = (total * Decimal(rng.choice(['0', '0.3', '0.5', '0.6']))).quantize(Decimal('1'))
            method = rng.choices([SalePayment.CASH, SalePayment.BKASH, SalePayment.NAGAD, SalePayment.CARD],
                                 [70, 18, 8, 4])[0]
            label = 'Credit' if paid < total else {SalePayment.CASH: 'Paid', SalePayment.BKASH: 'bKash',
                                                   SalePayment.NAGAD: 'Nagad', SalePayment.CARD: 'Card'}[method]
            cash_given = paid if method != SalePayment.CASH else (paid + Decimal(rng.choice([0, 0, 0, 20, 50, 100]))
                                                                  if paid else ZERO)
            order = Order(shop=shop, customer=customer, source='pos', status='Delivered', delivery_charge=ZERO,
                          discount=discount, vat_amount=ZERO, total_amount=total, advance_paid=paid,
                          payment_method=label, cash_received=cash_given, change_given=cash_given - paid,
                          served_by=staff_user if rng.random() < 0.55 else shop.user,
                          pos_ref=f'demo-{day:%Y%m%d}-{rng.randint(1000, 9999)}-{len(orders)}')
            order.when, order.lines, order.pay = when, lines, (method, paid)
            orders.append(order)
            if due_sale:
                due_plan.append(order)

    Order.objects.bulk_create(orders)
    for order in orders:
        order.created_at = order.when
        for product, variant, price, qty in order.lines:
            items.append(OrderItem(order=order, product=product, variant=variant,
                                   variant_name=variant.name if variant else '', quantity=qty, price=price,
                                   cost_price=product.cost_price))
        if order.source == 'storefront':
            sf = StorefrontOrder(shop=shop, customer_name=order.customer.name, customer_phone=order.customer.phone,
                                 customer_address=order.customer.address, total_amount=order.total_amount,
                                 delivery_charge=order.delivery_charge, delivery_zone=order.zone_name, order=order,
                                 status=order.status if order.status != 'Returned' else 'Delivered')
            sf.when = order.when
            sf_orders.append(sf)
        else:
            method, paid = order.pay
            if paid > 0:
                payment = SalePayment(shop=shop, order=order, method=method, amount=paid, kind=SalePayment.SALE,
                                      received_by=order.served_by,
                                      reference=f'TRX{rng.randint(100000, 999999)}' if method != SalePayment.CASH else '')
                payment.when = order.when
                payments.append(payment)
    Order.objects.bulk_update(orders, ['created_at'], batch_size=300)
    OrderItem.objects.bulk_create(items, batch_size=500)
    StorefrontOrder.objects.bulk_create(sf_orders, batch_size=300)
    for sf in sf_orders:
        sf.created_at = sf.when
        sf_items.extend(StorefrontOrderItem(order=sf, product=product, quantity=qty, price=price,
                                            variant_name=variant.name if variant else '')
                        for product, variant, price, qty in sf.order.lines)
    StorefrontOrder.objects.bulk_update(sf_orders, ['created_at'], batch_size=300)
    StorefrontOrderItem.objects.bulk_create(sf_items, batch_size=500)

    # বাকির খাতা: কিছু পুরনো বাকি আংশিক আদায় হয়েছে; কেউ কবে দেবে বলেছে
    for i, order in enumerate(due_plan):
        if i % 3 == 0 and order.total_amount - order.advance_paid > 300:
            part = Decimal(200)
            order.advance_paid += part
            payment = SalePayment(shop=shop, order=order, method=SalePayment.CASH, amount=part,
                                  kind=SalePayment.DUE_COLLECTION, received_by=shop.user)
            payment.when = order.when + timedelta(days=rng.randint(2, 9), hours=3)
            payments.append(payment)
    Order.objects.bulk_update(due_plan, ['advance_paid'])
    SalePayment.objects.bulk_create(payments, batch_size=500)
    for payment in payments:
        payment.created_at = payment.when
    SalePayment.objects.bulk_update(payments, ['created_at'], batch_size=500)
    promises = [(c, today + timedelta(days=d), note) for c, d, note in
                zip({o.customer.pk: o.customer for o in due_plan}.values(), (3, 7, -2, 5, 10, 1),
                    ('বেতন পেলে দেবে', 'ঈদের আগে', 'ফোন ধরে না', 'bKash-এ পাঠাবে', '', 'দোকানে এসে দেবে'))]
    for customer, promise, note in promises:
        customer.due_promise, customer.due_note = promise, note
    Customer.objects.bulk_update([c for c, _p, _n in promises], ['due_promise', 'due_note'])
    if risky:
        risky[-1].is_blocked = True
        risky[-1].save(update_fields=['is_blocked'])

    # মাল কেনা ও সাপ্লায়ারের বাকি
    suppliers = [Supplier(shop=shop, name=n, phone=p, address=a, opening_due=Decimal(d)) for n, p, a, d in SUPPLIERS]
    Supplier.objects.bulk_create(suppliers)
    by_cat = {}
    for product in products:
        by_cat.setdefault(product.category.name, []).append(product)
    purchase_plan = [
        (88, 0, ['টি-শার্ট', 'শার্ট'], 1.0), (74, 2, ['প্যান্ট ও জিন্স'], 1.0), (61, 1, ['মেয়েদের ড্রেস', 'এক্সেসরিজ'], 0.6),
        (45, 0, ['জুতা'], 1.0), (31, 1, ['শীতের পোশাক'], 0.5), (17, 2, ['প্যান্ট ও জিন্স', 'টি-শার্ট'], 0.7),
        (6, 0, ['শার্ট', 'জুতা'], 0.0),
    ]
    for back, supplier_index, cats, paid_share in purchase_plan:
        day = today - timedelta(days=back)
        supplier = suppliers[supplier_index]
        chosen = [p for cat in cats for p in by_cat.get(cat, [])]
        lines = []
        for product in chosen:
            qty = rng.randint(6, 24)
            if product.variant_list:
                for variant, share in zip(product.variant_list, _split(qty, len(product.variant_list))):
                    if share:
                        lines.append((product, variant, share))
            else:
                lines.append((product, None, qty))
        total = sum(product.cost_price * qty for product, _v, qty in lines)
        paid = (total * Decimal(str(paid_share))).quantize(Decimal('1'))
        purchase = Purchase.objects.create(shop=shop, supplier=supplier, purchased_on=day,
                                           invoice_no=f'INV-{day:%y%m}-{rng.randint(100, 999)}', total_amount=total,
                                           paid_amount=paid, created_by=shop.user,
                                           note='' if paid_share else 'পুরোটা বাকিতে, ১৫ দিনের মধ্যে দেওয়ার কথা')
        PurchaseItem.objects.bulk_create([
            PurchaseItem(purchase=purchase, product=product, variant=variant,
                         name=f'{product.name} ({variant.name})' if variant else product.name, quantity=qty,
                         unit_cost=product.cost_price) for product, variant, qty in lines])
        if paid > 0:
            SupplierPayment.objects.create(shop=shop, supplier=supplier, purchase=purchase, amount=paid,
                                           method=rng.choice(['cash', 'bkash', 'bank']), paid_on=day, created_by=shop.user)
    SupplierPayment.objects.create(shop=shop, supplier=suppliers[1], amount=Decimal(3000), method='bkash',
                                   paid_on=today - timedelta(days=12), note='আগের বাকি থেকে', created_by=shop.user)

    # খরচ: মাসের শুরুতে ভাড়া-বেতন, মাঝে মাঝে বুস্ট, প্যাকেজিং, কুরিয়ার
    expenses = []
    month_firsts = sorted({(first_day + timedelta(days=d)).replace(day=1) for d in range(HISTORY_DAYS + 1)})
    for first in month_firsts:
        if first < first_day:
            continue
        expenses += [Expense(shop=shop, category='rent', title='দোকান ভাড়া', amount=Decimal(15000), spent_on=first + timedelta(days=2), method='cash'),
                     Expense(shop=shop, category='salary', title='রাকিবের বেতন', amount=Decimal(12000), spent_on=first + timedelta(days=4), method='bkash'),
                     Expense(shop=shop, category='utility', title='বিদ্যুৎ বিল', amount=Decimal(rng.randint(1800, 2600)), spent_on=first + timedelta(days=9), method='cash'),
                     Expense(shop=shop, category='internet', title='ইন্টারনেট ও মোবাইল', amount=Decimal(1200), spent_on=first + timedelta(days=6), method='bkash')]
    for back in range(HISTORY_DAYS, -1, -1):
        day = today - timedelta(days=back)
        if rng.random() < 0.18:
            expenses.append(Expense(shop=shop, category='ads', title='Facebook বুস্ট', amount=Decimal(rng.choice([500, 800, 1000, 1500, 2000])), spent_on=day, method='card'))
        if rng.random() < 0.12:
            expenses.append(Expense(shop=shop, category='packaging', title='পলি ব্যাগ ও বক্স', amount=Decimal(rng.randint(300, 900)), spent_on=day, method='cash'))
        if rng.random() < 0.10:
            expenses.append(Expense(shop=shop, category='courier', title='কুরিয়ার চার্জ', amount=Decimal(rng.randint(400, 1400)), spent_on=day, method='cash'))
        if rng.random() < 0.08:
            expenses.append(Expense(shop=shop, category='food', title='চা-নাস্তা', amount=Decimal(rng.randint(80, 250)), spent_on=day, method='cash'))
    for expense in expenses:
        expense.created_by = shop.user
    Expense.objects.bulk_create([e for e in expenses if e.spent_on <= today], batch_size=300)

    return {'orders': orders, 'web_customers': web_customers, 'coupons_used': coupons_used,
            'landing_orders': landing_orders, 'walk_in': walk_in}


def _clock(rng, day, first_hour, last_hour, days_ago):
    """দিনের একটা সময়; আজকের অর্ডার কখনো "ভবিষ্যতে" (এখনকার পরে) পড়ে না।"""
    if days_ago == 0:
        now = timezone.localtime()
        last_hour = min(last_hour, max(first_hour, now.hour))
        hour = rng.randint(first_hour, last_hour)
        minute = rng.randint(0, max(0, now.minute - 1)) if hour == now.hour else rng.randint(0, 59)
        return _at(day, hour, minute)
    return _at(day, rng.randint(first_hour, last_hour), rng.randint(0, 59))


def _lines(rng, products, weights, max_lines):
    """একটা বিলের লাইন: (প্রোডাক্ট, ভ্যারিয়েন্ট বা None, দাম, পরিমাণ)।"""
    count = rng.choices([1, 2, 3, 4][:max_lines], [62, 26, 9, 3][:max_lines])[0]
    chosen, lines = set(), []
    while len(lines) < count:
        product = rng.choices(products, weights)[0]
        if product.pk in chosen:
            continue
        chosen.add(product.pk)
        variant = rng.choice(product.variant_list) if product.variant_list else None
        qty = rng.choices([1, 2, 3], [84, 13, 3])[0]
        lines.append((product, variant, product.price, qty))
    return lines


def _web_status(rng, days_ago, risky):
    if days_ago == 0:
        return rng.choices(['Pending', 'Confirmed'], [70, 30])[0]
    if days_ago <= 2:
        return rng.choices(['Pending', 'Confirmed', 'Shipped', 'Cancelled'], [30, 40, 25, 5])[0]
    if days_ago <= 5:
        return rng.choices(['Shipped', 'Delivered', 'Cancelled'], [45, 48, 7])[0]
    if risky:
        return rng.choices(['Delivered', 'Returned', 'Cancelled'], [30, 55, 15])[0]
    return rng.choices(['Delivered', 'Returned', 'Cancelled'], [88, 6, 6])[0]


# ---------------------------------------------------------------- রিভিউ, কুপন, ল্যান্ডিং, SMS
def _reviews(shop, rng, products, state):
    from .models import ProductReview
    delivered = [o for o in state['orders'] if o.source == 'storefront' and o.status == 'Delivered']
    rows, seen = [], set()
    for order in delivered:
        product = order.lines[0][0]
        key = (product.pk, order.customer.phone)
        if key in seen or rng.random() > 0.16:
            continue
        seen.add(key)
        rating = rng.choices([5, 4, 3], [68, 26, 6])[0]
        review = ProductReview(shop=shop, product=product, name=order.customer.name, phone=order.customer.phone,
                               rating=rating, text=rng.choice(REVIEWS), verified=True,
                               is_approved=rng.random() > 0.12)
        review.when = order.when + timedelta(days=rng.randint(2, 6), hours=rng.randint(1, 10))
        rows.append(review)
    ProductReview.objects.bulk_create(rows)
    for review in rows:
        review.created_at = review.when
    ProductReview.objects.bulk_update(rows, ['created_at'])


def _coupons(shop, products, used):
    from .models import AbandonedCheckout, Coupon
    today = timezone.localdate()
    Coupon.objects.bulk_create([
        Coupon(shop=shop, code='EID20', kind=Coupon.PERCENT, value=Decimal(20), min_order=Decimal(999),
               max_discount=Decimal(300), usage_limit=200, used_count=used['EID20'],
               starts_on=today - timedelta(days=20), ends_on=today + timedelta(days=12)),
        Coupon(shop=shop, code='FREEDEL', kind=Coupon.FREE_DELIVERY, min_order=Decimal(1500), used_count=used['FREEDEL']),
        Coupon(shop=shop, code='NEW100', kind=Coupon.AMOUNT, value=Decimal(100), min_order=Decimal(800),
               usage_limit=50, used_count=used['NEW100'], ends_on=today + timedelta(days=5)),
        Coupon(shop=shop, code='SUMMER10', kind=Coupon.PERCENT, value=Decimal(10), min_order=Decimal(500),
               used_count=31, ends_on=today - timedelta(days=15), is_active=False),
    ])
    by_code = {p.barcode: p for p in products}
    drafts = [
        ('01712345678', 'শাহরিয়ার কবির', 'মিরপুর ১, ঢাকা', [('DEMO-22', '42', 1950, 1)], 2),
        ('01898765432', 'নাজমুন নাহার', '', [('DEMO-15', 'M', 1450, 1), ('DEMO-30', '', 350, 2)], 5),
        ('01956781234', '', '', [('DEMO-06', 'L', 1150, 1)], 9),
        ('01634567890', 'তৌহিদ হাসান', 'সিলেট', [('DEMO-26', 'XL', 3200, 1)], 26),
    ]
    rows = []
    for phone, name, address, cart, hours_ago in drafts:
        lines = []
        for code, vname, price, qty in cart:
            product = by_code[code]
            variant = next((v for v in product.variant_list if v.name == vname), None)
            lines.append({'key': -variant.id if variant else product.pk,
                          'name': product.name + (f' ({vname})' if variant else ''), 'price': price, 'qty': qty})
        rows.append(AbandonedCheckout(shop=shop, phone=phone, name=name, address=address, cart=lines,
                                      total=Decimal(sum(l['price'] * l['qty'] for l in lines))))
    AbandonedCheckout.objects.bulk_create(rows)
    for row, (_p, _n, _a, _c, hours_ago) in zip(rows, drafts):
        AbandonedCheckout.objects.filter(pk=row.pk).update(updated_at=timezone.now() - timedelta(hours=hours_ago),
                                                           created_at=timezone.now() - timedelta(hours=hours_ago + 1))


def _landing(shop, products, state):
    from .models import LandingPage, Order
    product = next(p for p in products if p.barcode == 'DEMO-01')
    page = LandingPage.objects.create(
        shop=shop, product=product, slug='premium-tshirt', headline='ঘরে বসে পান প্রিমিয়াম কটন টি-শার্ট — মাত্র ৪৫০ টাকায়',
        subheadline='১৮০ GSM কম্বড কটন, ধোয়ার পরেও রং-সাইজ ঠিক থাকে। ক্যাশ অন ডেলিভারিতে সারা দেশে।',
        bullets='ক্যাশ অন ডেলিভারি — পণ্য হাতে পেয়ে টাকা দিন\nসারা বাংলাদেশে ২–৩ দিনে ডেলিভারি\n'
                'সাইজ না মিললে ৩ দিনের মধ্যে বদলে দেওয়া হয়\n১০০% কম্বড কটন, ১৮০ GSM',
        offer_text='আজ অর্ডার করলে ডেলিভারি চার্জ ফ্রি', cta_text='এখনই অর্ডার করুন', views=1240)
    Order.objects.filter(pk__in=[o.pk for o in state['landing_orders']]).update(landing=page)


def _sms_history(shop, state):
    from .models import SmsLog
    from . import sms as sms_mod
    rows = []
    recent_web = [o for o in state['orders'] if o.source == 'storefront'][-14:]
    for order in recent_web:
        rows.append((order.when + timedelta(seconds=20), SmsLog.KIND_AUTO, f'অর্ডার নং {sms_mod.bn_num(order.pk)}',
                     sms_mod.order_received_text(shop, order), 1))
    now = timezone.now()
    for (audience, message, recipients), days in zip(SMS_CAMPAIGNS, (9, 23)):
        rows.append((now - timedelta(days=days, hours=5), SmsLog.KIND_MANUAL, audience, message, recipients))
    logs = [SmsLog(shop=shop, kind=kind, audience=audience, message=message, recipients=n, delivered=n,
                   sms_used=n * sms_mod.segments(message), status=SmsLog.SENT, sent_by=shop.user)
            for _when, kind, audience, message, n in rows]
    SmsLog.objects.bulk_create(logs)
    for log, (when, *_rest) in zip(logs, rows):
        log.created_at = when
    SmsLog.objects.bulk_update(logs, ['created_at'])


# ============================================================
# ডেমোতে কী করা যাবে না
# ============================================================
def demo_sender(phones, message):
    """ডেমোর SMS: গেটওয়েতে যায় না, কিন্তু প্যানেলে "গেছে" দেখায়।"""
    return True, 'demo'


def _wants_json(request):
    return ('application/json' in request.headers.get('Accept', '')
            or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            or request.content_type == 'application/json')


def is_blocked(request):
    if request.method != 'POST':
        return False
    path = request.path
    if path.startswith(BLOCKED_PREFIXES) or '/delete/' in path:
        return True
    if path == '/website/' and request.POST.get('section') in BLOCKED_WEBSITE_SECTIONS:
        return True
    return request.POST.get('action') == 'delete'


class DemoGuardMiddleware:
    """ডেমো সেলার হিসেবে ঢুকে থাকলে ক্ষতিকর বা ডেমো-ভাঙা কাজগুলো আটকে দেয়।"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if is_demo_user(getattr(request, 'user', None)) and is_blocked(request):
            if _wants_json(request):
                return JsonResponse({'success': False, 'ok': False, 'error': BLOCKED_MESSAGE}, status=403)
            messages.warning(request, BLOCKED_MESSAGE)
            back = request.headers.get('Referer', '')
            return redirect(back if back and _same_site(request, back) else '/dashboard/')
        return self.get_response(request)


def _same_site(request, url):
    from urllib.parse import urlparse
    host = urlparse(url).netloc.split(':')[0]
    return host == request.get_host().split(':')[0]
