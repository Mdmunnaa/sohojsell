"""
SellPunch কে চালায় — ট্রেড লাইসেন্সে যেমন লেখা, এক জায়গায় (Edumi-র core/company.py থেকে নেওয়া)।

SellPunch আলাদা কোম্পানি না: আইনি মালিক এডুমি (Edumi), SellPunch তার একটা পণ্য/ব্র্যান্ড।
ফুটার, যোগাযোগ, "আমাদের সম্পর্কে", নীতিমালা, পেমেন্টের রসিদ আর Google-এর schema সবাই এখান থেকে নেয় —
লাইসেন্স নবায়ন হলে শুধু এখানে তারিখ বদলান। Meta-র ব্যবসা যাচাইয়েও এই নাম-ঠিকানা মিলতে হয়।

ইচ্ছা করে নেই: NID, বাবা-মায়ের নাম, ব্যক্তিগত মোবাইল।
"""
import datetime

COMPANY = {
    'name_bn': 'এডুমি (Edumi)',
    'name_en': 'Edumi',
    'kind_bn': 'আইটি ফার্ম — একক মালিকানাধীন প্রতিষ্ঠান (লিমিটেড কোম্পানি নয়)',
    'kind_en': 'IT firm — sole proprietorship (not a limited company)',
    'owner_bn': 'মোঃ মুন্না মিয়া',
    'owner_en': 'Md. Munna Mia',
    'licence_no': '00000048',
    'licence_id': '16-0223-01249-00000048',
    'issuer_bn': '০১ নং বাহাদুরপুর ইউনিয়ন পরিষদ, পাংশা, রাজবাড়ী',
    'issuer_en': 'No. 1 Bahadurpur Union Parishad, Pangsha, Rajbari',
    'valid_until': datetime.date(2027, 6, 30),     # প্রতি বছর ৩০ জুন নবায়ন — নতুন লাইসেন্স পেলে তারিখ বদলান
    'address_bn': 'মেঘনা, বাহাদুরপুর, পাংশা, রাজবাড়ী — ৭৭২১, বাংলাদেশ',
    'address_en': 'Meghna, Bahadurpur, Pangsha, Rajbari 7721, Bangladesh',
    'street_en': 'Meghna, Bahadurpur',
    'locality_en': 'Pangsha, Rajbari',
    'postal_code': '7721',
    'website': 'https://www.edumi.bd',
}

# এডুমির পণ্য — "আমাদের সম্পর্কে" পাতায় মালিকের পরিচয়ের সাথে
PRODUCTS = [
    {'name': 'Edumi', 'host': 'edumi.bd', 'url': 'https://www.edumi.bd',
     'about_bn': 'স্কুল, কোচিং আর মাদ্রাসার সফটওয়্যার', 'about_en': 'software for schools, coaching centres and madrasahs'},
    {'name': 'SellPunch', 'host': 'sellpunch.com', 'url': 'https://sellpunch.com',
     'about_bn': 'ছোট ব্যবসার অনলাইন দোকান, POS আর হিসাব', 'about_en': 'online store, POS and accounts for small businesses'},
]

# মালিকের দেওয়া প্রতিশ্রুতি (১৬ নভেম্বর ২০২৬) — যোগাযোগ, "আমাদের সম্পর্কে", "নিরাপত্তা ও ডাটা", শর্তাবলি আর
# llms.txt সবাই এখান থেকে নেয়। বদলালে settings.POLICY_UPDATED_ON-ও বদলান (শর্তাবলিতে আছে)।
PROMISES = {
    'support_reply_hours': 6,     # ফোন, WhatsApp বা ইমেইলে সমস্যা জানালে সর্বোচ্চ এত ঘণ্টায় উত্তর
    'outage_fix_hours': 6,        # সার্ভার বন্ধ হলে এত ঘণ্টার মধ্যে চালু করার চেষ্টা
    'shutdown_notice_days': 60,   # SellPunch পুরো বন্ধ করতে হলে অন্তত এত দিন আগে জানানো, সব তথ্য নামানোর সুযোগসহ
}

# SellPunch-এর যোগাযোগ (settings / env দিয়ে বদলানো যায়; ফাঁকা env হলে এগুলোই)
DEFAULT_CONTACT = {
    'SUPPORT_PHONE': '+880 9658-614453',          # Edumi-র হেল্পলাইন (একই প্রতিষ্ঠান)
    'SUPPORT_EMAIL': 'support@sellpunch.com',
    'INFO_EMAIL': 'info@sellpunch.com',            # সাধারণ প্রশ্ন, ব্যবসা/পার্টনারশিপ, লাইসেন্সের কপি
    'REFUND_EMAIL': 'refund@sellpunch.com',        # রিফান্ড আর বিল/পেমেন্টের সমস্যা
    'SUPPORT_WHATSAPP': '8801804181010',
}

_BN_DIGITS = str.maketrans('0123456789', '০১২৩৪৫৬৭৮৯')
_BN_MONTHS = ('জানুয়ারি', 'ফেব্রুয়ারি', 'মার্চ', 'এপ্রিল', 'মে', 'জুন', 'জুলাই', 'আগস্ট', 'সেপ্টেম্বর',
              'অক্টোবর', 'নভেম্বর', 'ডিসেম্বর')


def bn_date(day):
    return f'{str(day.day).translate(_BN_DIGITS)} {_BN_MONTHS[day.month - 1]} {str(day.year).translate(_BN_DIGITS)}'


def company_context(today=None):
    """টেমপ্লেটের জন্য — নবায়নের তারিখ পার হয়ে গেলে (বদলানো না হলে) মেয়াদের লাইন আর দেখায় না।"""
    from django.utils import timezone
    data = dict(COMPANY)
    data['products'] = PRODUCTS
    for key, value in PROMISES.items():
        data[key] = value
        data[f'{key}_bn'] = str(value).translate(_BN_DIGITS)
    if data['valid_until'] < (today or timezone.localdate()):
        data['valid_until'] = None
    else:
        data['valid_until_bn'] = bn_date(data['valid_until'])
        data['valid_until_en'] = data['valid_until'].strftime('%d %B %Y')
    return data
