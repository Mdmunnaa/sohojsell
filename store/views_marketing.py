"""
SEO পাতা (store/marketing.py-র লেখা): /features/, /features/<slug>/, /for/<slug>/ আর ইংরেজিতে /en/... ।
প্রতিটা পাতায় নিজের title/description, canonical, hreflang, Open Graph, আর JSON-LD (WebPage, BreadcrumbList, FAQPage)।
"""
import json

from django.http import Http404
from django.shortcuts import render
from django.urls import reverse

from . import marketing, seo

PATH_NAMES = {
    ('feature', 'bn'): 'mk_feature', ('feature', 'en'): 'mk_feature_en',
    ('industry', 'bn'): 'mk_industry', ('industry', 'en'): 'mk_industry_en',
}

UI = {
    'bn': {
        'home': 'হোম', 'features': 'ফিচার', 'industries': 'যে ব্যবসার জন্য', 'all_features': 'সব ফিচার',
        'start': '৩০ দিন ফ্রি শুরু করুন', 'demo': 'লাইভ ডেমো দেখুন', 'login': 'লগইন', 'pricing': 'দাম',
        'free_start': 'ফ্রি শুরু করুন', 'menu': 'মেনু', 'other_lang': 'English', 'other_lang_code': 'en',
        'what_you_get': 'যা যা পাচ্ছেন', 'how': 'কীভাবে শুরু', 'how_title': '১ মিনিটে শুরু, আজই প্রথম অর্ডার',
        'faq': 'প্রশ্নোত্তর', 'faq_title': 'যা জানতে চান', 'related': 'আরও দেখুন', 'related_title': 'এর সাথে যা কাজে লাগে',
        'price_from': 'মাসে', 'price_tail': 'টাকা থেকে · প্রথম ৩০ দিন ফ্রি · কার্ড লাগে না',
        'see_prices': 'সব প্যাকেজের দাম', 'final_title': 'আজই নিজের দোকান খুলুন',
        'final_text': '১ মিনিটে ওয়েবসাইট চালু। ৩০ দিন ফ্রি, কার্ড লাগে না — পছন্দ না হলে কিছু করতে হবে না।',
        'final_demo': 'আগে ডেমো দেখি',
        'notes': ['কার্ড লাগে না', '১ মিনিটে ওয়েবসাইট চালু', 'মোবাইল থেকেই চালানো যায়'],
        'steps': [
            ('দোকানের নাম আর ঠিকানা দিন', 'দোকানের নাম, পছন্দের ওয়েবসাইট ঠিকানা, মোবাইল নম্বর আর পাসওয়ার্ড — ১ মিনিটে ওয়েবসাইট চালু।'),
            ('প্রোডাক্ট আর লোগো তুলুন', 'ছবি, দাম, স্টক; সাইজ-রং থাকলে তা-ও। ব্যানার দিলে ওয়েবসাইট আরও সুন্দর।'),
            ('লিংক শেয়ার করুন, বিক্রি শুরু', 'Facebook পেজে লিংক দিন, দোকানে POS খুলুন — অর্ডার এলেই ড্যাশবোর্ডে।'),
        ],
        'index_title': 'SellPunch-এর সব ফিচার — ওয়েবসাইট, POS, কুরিয়ার, বাকির খাতা',
        'index_description': '১ মিনিটে ই-কমার্স ওয়েবসাইট, দোকানের POS, Steadfast/Pathao/RedX কুরিয়ার, বাকির খাতা, ল্যান্ডিং পেজ আর '
                             'লাভের হিসাব — কোন ব্যবসার জন্য কী, এক জায়গায়। ৩০ দিন ফ্রি।',
        'index_h1': 'ছোট ব্যবসার যা লাগে, <em>সব এক সফটওয়্যারে</em>',
        'index_lead': 'অনলাইন শপ থেকে দোকানের কাউন্টার, কুরিয়ার থেকে বাকির খাতা — প্রতিটা ফিচারের বিস্তারিত, আর আপনার ব্যবসার '
                      'ধরন অনুযায়ী কোনটা কাজে লাগবে।',
        'more': 'বিস্তারিত',
        'footer_about': 'বাংলাদেশের ছোট ব্যবসার জন্য দোকান আর অনলাইন বিক্রির সফটওয়্যার — ওয়েবসাইট, POS, অর্ডার, SMS, বাকির খাতা আর হিসাব।',
        'software': 'সফটওয়্যার', 'contact': 'যোগাযোগ', 'policies': 'নীতিমালা',
        'contact_page': 'যোগাযোগের পাতা', 'about': 'আমাদের সম্পর্কে', 'security': 'নিরাপত্তা ও ডাটা',
        'privacy': 'প্রাইভেসি পলিসি', 'terms': 'ব্যবহারের শর্ত', 'refund': 'রিফান্ড পলিসি',
        'product_of': 'এর একটি পণ্য', 'made_in': 'বাংলাদেশে তৈরি', 'whatsapp': 'WhatsApp-এ লিখুন',
        'licence': 'ট্রেড লাইসেন্স আইডি',
    },
    'en': {
        'home': 'Home', 'features': 'Features', 'industries': 'Who it is for', 'all_features': 'All features',
        'start': 'Start free for 30 days', 'demo': 'See the live demo', 'login': 'Log in', 'pricing': 'Pricing',
        'free_start': 'Start free', 'menu': 'Menu', 'other_lang': 'বাংলা', 'other_lang_code': 'bn',
        'what_you_get': 'What you get', 'how': 'How to start', 'how_title': 'Start in 1 minute, take your first order today',
        'faq': 'FAQ', 'faq_title': 'Questions people ask', 'related': 'See also', 'related_title': 'Works well with',
        'price_from': 'From BDT', 'price_tail': 'a month · first 30 days free · no card needed',
        'see_prices': 'All plan prices', 'final_title': 'Open your shop today',
        'final_text': 'Your website is live in 1 minute. 30 days free, no card — if you do not like it, do nothing.',
        'final_demo': 'See the demo first',
        'notes': ['No card needed', 'Website live in 1 minute', 'Runs on your phone'],
        'steps': [
            ('Enter your shop name and address', 'Shop name, the web address you want, mobile number and password — your website is live in 1 minute.'),
            ('Add products and your logo', 'Photo, price, stock; sizes and colours too. Add a banner to make it shine.'),
            ('Share the link and start selling', 'Post the link on your Facebook page, open the POS in your shop — orders land in your dashboard.'),
        ],
        'index_title': 'SellPunch Features — Website, POS, Courier and Due Book',
        'index_description': 'Ecommerce website in 1 minute, shop POS, Steadfast/Pathao/RedX courier booking, due book, landing '
                             'pages and profit reports — what fits which business, in one place. 30 days free.',
        'index_h1': 'Everything a small business needs, <em>in one software</em>',
        'index_lead': 'From the online store to the shop counter, courier to the due book — details of every feature, and what fits '
                      'your kind of business.',
        'more': 'Details',
        'footer_about': 'Shop and online selling software for small businesses in Bangladesh — website, POS, orders, SMS, dues and accounts.',
        'software': 'Software', 'contact': 'Contact', 'policies': 'Policies',
        'contact_page': 'Contact page', 'about': 'About us', 'security': 'Security & data (Bangla)',
        'privacy': 'Privacy policy', 'terms': 'Terms of use', 'refund': 'Refund policy',
        'product_of': 'a product of', 'made_in': 'Made in Bangladesh', 'whatsapp': 'Message on WhatsApp',
        'licence': 'Trade licence ID',
    },
}


def _page_url(kind, slug, lang):
    return reverse(PATH_NAMES[(kind, lang)], args=[slug])


def _index_url(lang):
    return reverse('mk_index_en' if lang == 'en' else 'mk_index')


def _home_url(lang):
    return reverse('landing_page_en') if lang == 'en' else '/'


def _cards(pages, kind, lang):
    return [{'url': _page_url(kind, p['slug'], lang), 'icon': p['icon'], 'nav': p[lang]['nav'],
             'description': p[lang]['description']} for p in pages]


def _min_price():
    from .payments import PLAN_PRICES
    return int(min(PLAN_PRICES[key] for key in ('Basic', 'Standard', 'Premium')))


def _image(page, lang):
    name = page['image_en'] if lang == 'en' else page['image']
    tall = page.get('tall', False)
    width = page.get('image_w') or (780 if tall else 1800)
    height = 1688 if tall else round(width * 1125 / 1800)
    phone = page.get('phone_en' if lang == 'en' else 'phone')
    return {'path': f'landing/{name}.webp', 'width': width, 'height': height, 'tall': tall,
            'phone': f'landing/{phone}.webp' if phone else ''}


def _ld(graph):
    return json.dumps({'@context': 'https://schema.org', '@graph': graph}, ensure_ascii=False)


def _render(request, lang, template, context, *, path_bn, path_en, title, description, crumbs, faq=None):
    base = seo.main_site_url(request)
    canonical = base + (path_en if lang == 'en' else path_bn)
    graph = [
        {'@type': 'WebPage', '@id': canonical + '#page', 'url': canonical, 'name': title, 'description': description,
         'inLanguage': lang, 'isPartOf': {'@id': base + '/#website'}, 'about': {'@id': base + '/#software'},
         'publisher': {'@id': base + '/#org'}},
        {'@type': 'BreadcrumbList', 'itemListElement': [
            {'@type': 'ListItem', 'position': i, 'name': name, 'item': base + url}
            for i, (name, url) in enumerate(crumbs, start=1)]},
    ]
    if faq:
        graph.append({'@type': 'FAQPage', 'mainEntity': [
            {'@type': 'Question', 'name': q, 'acceptedAnswer': {'@type': 'Answer', 'text': a}} for q, a in faq]})
    context.update({
        'lang': lang, 'ui': UI[lang], 'title': title, 'description': description, 'crumbs': crumbs,
        'mk_seo': {'canonical': canonical, 'url_bn': base + path_bn, 'url_en': base + path_en, 'base': base,
                   'other_url': path_bn if lang == 'en' else path_en, 'ld': _ld(graph)},
        'home_url': _home_url(lang), 'index_url': _index_url(lang), 'min_price': _min_price(),
        'feature_links': _cards(marketing.FEATURES, 'feature', lang),
        'industry_links': _cards(marketing.INDUSTRIES, 'industry', lang),
    })
    return render(request, template, context)


def _page(request, kind, slug, lang):
    page = marketing.get(kind, slug)
    if page is None:
        raise Http404
    text, ui = page[lang], UI[lang]
    related = [marketing.get('feature', s) for s in page.get('related', [])]
    crumbs = [(ui['home'], _home_url(lang)), (ui['features'] if kind == 'feature' else ui['industries'], _index_url(lang)),
              (text['nav'], _page_url(kind, slug, lang))]
    pending = text.get('pending', '') if page.get('facebook') and not marketing.facebook_live() else ''
    return _render(request, lang, 'store/marketing/page.html', {
        'page': page, 'text': text, 'kind': kind, 'image': _image(page, lang), 'pending': pending,
        'steps': text.get('steps') or ui['steps'],
        'related': _cards([p for p in related if p], 'feature', lang),
    }, path_bn=_page_url(kind, slug, 'bn'), path_en=_page_url(kind, slug, 'en'),
        title=text['title'], description=text['description'], crumbs=crumbs, faq=text['faq'])


def _index(request, lang):
    ui = UI[lang]
    crumbs = [(ui['home'], _home_url(lang)), (ui['features'], _index_url(lang))]
    return _render(request, lang, 'store/marketing/index.html', {}, path_bn=_index_url('bn'), path_en=_index_url('en'),
                   title=ui['index_title'], description=ui['index_description'], crumbs=crumbs)


def index(request):
    return _index(request, 'bn')


def index_en(request):
    return _index(request, 'en')


def feature(request, slug):
    return _page(request, 'feature', slug, 'bn')


def feature_en(request, slug):
    return _page(request, 'feature', slug, 'en')


def industry(request, slug):
    return _page(request, 'industry', slug, 'bn')


def industry_en(request, slug):
    return _page(request, 'industry', slug, 'en')
