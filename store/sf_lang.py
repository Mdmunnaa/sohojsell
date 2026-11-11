"""
দোকানের ওয়েবসাইটের ভাষা — বাংলা বা English (সেলার "ওয়েবসাইট → ডিজাইন"-এ বাছে)।

কাস্টমার যা যা দেখে সব এই ভাষায়: ওয়েবসাইট, কার্ট-চেকআউট, অর্ডারের পাতা, ট্র্যাকিং, ল্যান্ডিং পেজ,
ভুলের বার্তা আর কাস্টমারের SMS। সেলারের ড্যাশবোর্ড সবসময় বাংলা।

কীভাবে লিখবেন:
- টেমপ্লেটে লেখা বাংলাতেই থাকে: {% load sf_text %} ... {% t "কার্টে যোগ করুন" %}
  সংখ্যা বসাতে: {% t "আর মাত্র {n}টা আছে" n=product.stock_quantity %}
  JS-এর স্ট্রিংয়ের ভেতরে: '{% tjs "কার্ট খালি" %}'   ·   সংখ্যা: {% num value %}
- Python-এ: sf_lang.t('কার্ট খালি!', shop)
- ইংরেজিটা store/sf_en.py-তে। নতুন বাংলা লেখা যোগ করে ইংরেজি দিতে ভুলে গেলে
  StorefrontEnglishTests টেস্ট ফেল করবে (ইংরেজি দোকানের পাতায় বাংলা অক্ষর পেলে)।
"""
import unicodedata
from decimal import Decimal

from .sf_en import EN_TEXT as _EN

# য় একভাবে লেখা (য+়) আর একভাবে (য়) — দুটোই যেন মেলে
EN_TEXT = {unicodedata.normalize('NFC', key): value for key, value in _EN.items()}

BN, EN = 'bn', 'en'
CHOICES = [(BN, 'বাংলা'), (EN, 'English')]
_TO_BN = str.maketrans('0123456789', '০১২৩৪৫৬৭৮৯')
_TO_EN = str.maketrans('০১২৩৪৫৬৭৮৯', '0123456789')


def lang_of(value):
    """দোকান, 'bn'/'en' বা None → 'bn'/'en'।"""
    if value is None:
        return BN
    if isinstance(value, str):
        return EN if value == EN else BN
    return EN if getattr(value, 'storefront_language', BN) == EN else BN


def num(value, lang=BN):
    """সংখ্যা ভাষামতো: বাংলায় ০-৯, ইংরেজিতে 0-9।"""
    text = str(value if value is not None else '')
    return text.translate(_TO_EN) if lang_of(lang) == EN else text.translate(_TO_BN)


def t(text, lang=BN, **values):
    """বাংলা লেখা → দোকানের ভাষায়। values থাকলে {n}-এর মতো জায়গায় বসে (সংখ্যা ভাষামতো)।"""
    lang = lang_of(lang)
    out = EN_TEXT.get(unicodedata.normalize('NFC', text), text) if lang == EN else text
    if values:
        out = out.format(**{key: num(v, lang) if isinstance(v, (int, float, Decimal)) else v
                            for key, v in values.items()})
    return out


def money(value, lang=BN):
    """৳1,250 — টাকার অঙ্ক দুই ভাষাতেই ইংরেজি অঙ্কে (ওয়েবসাইটে দাম এভাবেই দেখানো হয়)।"""
    try:
        return f'৳{Decimal(value):,.0f}'
    except Exception:    # noqa: BLE001
        return f'৳{value}'


def status_label(status, lang=BN):
    from .order_flow import STATUS_BN
    return t(STATUS_BN.get(status, status), lang)
