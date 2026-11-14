from pathlib import Path
import os
import sys

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ('1', 'true', 'yes', 'on')


def env_list(name):
    return [item.strip() for item in os.environ.get(name, '').split(',') if item.strip()]


# Render নিজে থেকে RENDER নামে একটা environment variable দেয়
IS_RENDER = 'RENDER' in os.environ
# Cloudflare Containers নিজে থেকে CLOUDFLARE_APPLICATION_ID দেয় (cloudflare/ ফোল্ডার দেখুন)
IS_CLOUDFLARE = 'CLOUDFLARE_APPLICATION_ID' in os.environ
IS_PRODUCTION = IS_RENDER or IS_CLOUDFLARE

# ============================================================
# নিরাপত্তা — সব গোপন জিনিস environment variable থেকে
# ============================================================
DEBUG = env_bool('DEBUG', default=not IS_PRODUCTION)

SECRET_KEY = os.environ.get('SECRET_KEY', '')
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured('SECRET_KEY environment variable সেট করা নেই।')
    SECRET_KEY = 'django-insecure-local-dev-only'

# দোকানের সাবডোমেইন যে ডোমেইনের নিচে বসবে (যেমন sellpunch.com → munnafashion.sellpunch.com)।
# ডোমেইন কিনে Render-এ *.ডোমেইন যোগ করার পর Environment-এ বসাবেন। খালি থাকলে দোকানের লিংক হয় /shop/<নাম>/
STORE_BASE_DOMAIN = os.environ.get('STORE_BASE_DOMAIN', '').strip().lower().strip('.')

ALLOWED_HOSTS = [
    'localhost', '127.0.0.1', '.sellpunch.com',
    '.pythonanywhere.com',  # পুরনো সার্ভার, পুরোপুরি Render-এ গেলে সরিয়ে দিন
] + env_list('ALLOWED_HOSTS')
CSRF_TRUSTED_ORIGINS = ['https://sellpunch.com', 'https://*.sellpunch.com'] + env_list('CSRF_TRUSTED_ORIGINS')
if STORE_BASE_DOMAIN:
    ALLOWED_HOSTS.append(f'.{STORE_BASE_DOMAIN}')
    CSRF_TRUSTED_ORIGINS += [f'https://{STORE_BASE_DOMAIN}', f'https://*.{STORE_BASE_DOMAIN}']

# সেলারের নিজের ডোমেইন: Host যা-ই আসুক Django-কে নিতে দেওয়া হয়; store/middleware.py অজানা ডোমেইন 404 করে
if IS_PRODUCTION:
    ALLOWED_HOSTS.append('*')
# Cloudflare for SaaS (নিজের ডোমেইনে নিজে থেকে SSL): থাকলে সেলারের ডোমেইন "যাচাই"-তেই চালু হয়
CLOUDFLARE_API_TOKEN = os.environ.get('CLOUDFLARE_API_TOKEN', '').strip()
CLOUDFLARE_ZONE_ID = os.environ.get('CLOUDFLARE_ZONE_ID', '').strip()
CUSTOM_DOMAIN_TARGET = os.environ.get('CUSTOM_DOMAIN_TARGET', '').strip().lower()   # সেলার CNAME যেখানে দেবে

RENDER_EXTERNAL_HOSTNAME = os.environ.get('RENDER_EXTERNAL_HOSTNAME')
# মূল সাইটের ঠিকানা (ড্যাশবোর্ড যেখানে খোলে), যেমন cf.sellpunch.com। না দিলে Render-এর ঠিকানা।
PRIMARY_HOST = os.environ.get('PRIMARY_HOST', '').strip().lower() or RENDER_EXTERNAL_HOSTNAME
for _host in {RENDER_EXTERNAL_HOSTNAME, PRIMARY_HOST} - {None, ''}:
    ALLOWED_HOSTS.append(_host)
    CSRF_TRUSTED_ORIGINS.append(f'https://{_host}')

# Render বা Cloudflare HTTPS শেষ করে request পাঠায়, তাই এই header দেখে বুঝতে হবে request https কিনা
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sites',          # allauth-এর জন্য দরকার
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.facebook',
    'storages',                      # Cloudflare R2-তে ছবি রাখার জন্য
    'accounts',
    'store',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',     # static ফাইল (admin-এর CSS ইত্যাদি)
    'django.middleware.gzip.GZipMiddleware',          # HTML ছোট করে পাঠানো (static ফাইল whitenoise নিজেই দেয়, তাই এর পরে)
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'allauth.account.middleware.AccountMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'store.middleware.ShopSubdomainMiddleware',          # দোকানের সাবডোমেইন → সেই দোকানের ওয়েবসাইট
    'store.subscription_middleware.SubscriptionMiddleware',
    'store.middleware.StaffAccessMiddleware',
    'store.demo.DemoGuardMiddleware',                     # ডেমো দোকানে সেটিংস/বিল/মুছে ফেলা বন্ধ
]

ROOT_URLCONF = 'sohojsell.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'store.context_processors.facebook_login',
                'store.context_processors.site_info',
                'store.context_processors.plan_info',
                'store.context_processors.hq',
            ],
        },
    },
]

WSGI_APPLICATION = 'sohojsell.wsgi.application'

# ============================================================
# ডেটাবেস — DATABASE_URL থাকলে Neon (PostgreSQL), না থাকলে লোকাল SQLite
# ============================================================
DATABASES = {
    'default': dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600,
        conn_health_checks=True,
    )
}
# Neon-এর pooled connection (host-এ "-pooler") হলে server-side cursor বন্ধ রাখতে হয়
if '-pooler.' in os.environ.get('DATABASE_URL', ''):
    DATABASES['default']['DISABLE_SERVER_SIDE_CURSORS'] = True

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Dhaka'
USE_I18N = True
USE_TZ = True

# ============================================================
# Static ও Media ফাইল
# ============================================================
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static'] if (BASE_DIR / 'static').exists() else []
# collectstatic-এর তালিকায় কোনো ফাইল না থাকলে error না দিয়ে সাধারণ নাম ব্যবহার
WHITENOISE_MANIFEST_STRICT = False

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# R2-এর ৪টা তথ্য দেওয়া থাকলে প্রোডাক্টের ছবি, লোগো, ব্যানার Cloudflare R2-তে যাবে।
# না থাকলে (লোকালে) আগের মতো media/ ফোল্ডারে।
# Cloudflare-এর পাতা থেকে পুরো ঠিকানা (https://<account>.r2.cloudflarestorage.com/<bucket>) কপি করে
# বসিয়ে দিলেও যেন চলে — শুধু দরকারি অংশটা নেওয়া হয়
def _r2_account_id(raw):
    import re
    match = re.search(r'([0-9a-f]{32})', raw.strip().lower())
    return match.group(1) if match else raw.strip()


def _r2_bucket(raw):
    raw = raw.strip().replace('https://', '').replace('http://', '').strip('/')
    return raw.split('/')[-1].strip() if '/' in raw else raw


R2_ACCOUNT_ID = _r2_account_id(os.environ.get('R2_ACCOUNT_ID', ''))
R2_ACCESS_KEY_ID = os.environ.get('R2_ACCESS_KEY_ID', '').strip()
R2_SECRET_ACCESS_KEY = os.environ.get('R2_SECRET_ACCESS_KEY', '').strip()
R2_BUCKET_NAME = _r2_bucket(os.environ.get('R2_BUCKET_NAME', ''))
# ছবির পাবলিক ঠিকানা, যেমন media.sohojsell.com বা pub-xxxx.r2.dev (https:// ছাড়া)
R2_PUBLIC_DOMAIN = os.environ.get('R2_PUBLIC_DOMAIN', '').replace('https://', '').strip('/')
USE_R2 = all([R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME])

if USE_R2:
    DEFAULT_STORAGE = {
        'BACKEND': 'storages.backends.s3.S3Storage',
        'OPTIONS': {
            'bucket_name': R2_BUCKET_NAME,
            'access_key': R2_ACCESS_KEY_ID,
            'secret_key': R2_SECRET_ACCESS_KEY,
            'endpoint_url': f'https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com',
            'region_name': 'auto',
            'signature_version': 's3v4',
            'default_acl': None,
            'file_overwrite': False,
            'custom_domain': R2_PUBLIC_DOMAIN or None,
            # পাবলিক ডোমেইন থাকলে সাধারণ লিংক; না থাকলে সাময়িক (signed) লিংক
            'querystring_auth': not R2_PUBLIC_DOMAIN,
        },
    }
else:
    DEFAULT_STORAGE = {'BACKEND': 'django.core.files.storage.FileSystemStorage'}

STORAGES = {
    'default': DEFAULT_STORAGE,
    'staticfiles': {
        'BACKEND': (
            'django.contrib.staticfiles.storage.StaticFilesStorage' if DEBUG
            else 'whitenoise.storage.CompressedManifestStaticFilesStorage'
        ),
    },
}

AUTH_USER_MODEL = 'accounts.User'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

SESSION_COOKIE_AGE = 86400 * 30
SESSION_SAVE_EVERY_REQUEST = True

LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/dashboard/'

# ============================================================
# ব্যবসার তথ্য — পাবলিক পেইজের footer, যোগাযোগ আর নীতিমালায় দেখায়।
# Render-এর Environment-এ বসাবেন; ফাঁকা থাকলে ওই লাইনটা দেখাবে না।
# ============================================================
SITE_NAME = os.environ.get('SITE_NAME', 'SellPunch')
SITE_NAME_BN = os.environ.get('SITE_NAME_BN', 'সেলপাঞ্চ')
# SellPunch চালায় এডুমি (Edumi) — ট্রেড লাইসেন্স, ঠিকানা আর যোগাযোগ store/company.py-তে। env ফাঁকা থাকলে সেগুলোই।
from store.company import COMPANY as _COMPANY, DEFAULT_CONTACT as _CONTACT  # noqa: E402
SUPPORT_PHONE = os.environ.get('SUPPORT_PHONE') or _CONTACT['SUPPORT_PHONE']
SUPPORT_EMAIL = os.environ.get('SUPPORT_EMAIL') or _CONTACT['SUPPORT_EMAIL']
INFO_EMAIL = os.environ.get('INFO_EMAIL') or _CONTACT['INFO_EMAIL']
SUPPORT_WHATSAPP = os.environ.get('SUPPORT_WHATSAPP') or _CONTACT['SUPPORT_WHATSAPP']   # দেশের কোডসহ
BUSINESS_LEGAL_NAME = os.environ.get('BUSINESS_LEGAL_NAME') or _COMPANY['name_bn']     # ট্রেড লাইসেন্সে যে নাম
BUSINESS_ADDRESS = os.environ.get('BUSINESS_ADDRESS') or _COMPANY['address_bn']
FACEBOOK_PAGE_URL = os.environ.get('FACEBOOK_PAGE_URL', '')
STATUS_PAGE_URL = os.environ.get('STATUS_PAGE_URL', '')     # UptimeRobot-এর পাবলিক স্ট্যাটাস পাতা (যেমন https://status.sellpunch.com)
POLICY_UPDATED_ON = '১৪ নভেম্বর ২০২৬'

# ============================================================
# PayStation পেমেন্ট গেটওয়ে (paystation.com.bd)
# ============================================================
# ডিফল্ট মানগুলো PayStation-এর পাবলিক sandbox (টেস্ট) অ্যাকাউন্ট — আসল টাকা কাটে না।
# Merchant অ্যাকাউন্ট পেলে Render-এ এই চারটা বসাবেন:
#   PAYSTATION_MERCHANT_ID, PAYSTATION_PASSWORD, PAYSTATION_ENVIRONMENT=live, PAYSTATION_PAY_WITH_CHARGE=0
PAYSTATION_MERCHANT_ID = os.environ.get('PAYSTATION_MERCHANT_ID', '104-1653730183')
PAYSTATION_PASSWORD = os.environ.get('PAYSTATION_PASSWORD', 'gamecoderstorepass')
PAYSTATION_ENVIRONMENT = os.environ.get('PAYSTATION_ENVIRONMENT', 'sandbox')  # 'sandbox' বা 'live'
# 0 = গেটওয়ে চার্জ আমরা দেব, 1 = কাস্টমার দেবে
PAYSTATION_PAY_WITH_CHARGE = os.environ.get('PAYSTATION_PAY_WITH_CHARGE', '0')
# sandbox চলার সময় শুধু এই শপগুলো (slug, কমা দিয়ে) অনলাইন পেমেন্ট বাটন দেখবে —
# যাতে টেস্ট মোডে কোনো আসল সেলার বিনা টাকায় প্ল্যান চালু করতে না পারে।
PAYSTATION_TEST_SHOPS = env_list('PAYSTATION_TEST_SHOPS')

# SMS Gateway BD (smsgateway.com.bd) — Edumi-র মতো চাবি environment থেকে। দোকানের সব SMS non-masking
# (sender ID ছাড়া) যায়, তাই আলাদা অনুমোদন লাগে না আর SMS দেরি করে না।
SMS_GATEWAY_CLIENT_ID = os.environ.get('SMS_GATEWAY_CLIENT_ID', '').strip()
SMS_GATEWAY_API_KEY = os.environ.get('SMS_GATEWAY_API_KEY', '').strip()
# SMS: ১০০-র বেশি নম্বর বা অর্ডারের অটো SMS পেছনে (thread) যায়, যাতে পেইজ আটকে না থাকে। টেস্টে সরাসরি।
SMS_BACKGROUND = env_bool('SMS_BACKGROUND', default=sys.argv[1:2] != ['test'])
# সেলার টাকা তোলার অনুরোধ দিলে এই নম্বরে SMS যায় (non-masking)
ADMIN_ALERT_PHONE = os.environ.get('ADMIN_ALERT_PHONE', '01923513404')
# কাস্টমার দোকানের ওয়েবসাইটে অনলাইনে টাকা দিলে প্ল্যাটফর্ম কত % রাখবে (বাকিটা সেলারের পাওনা)।
# PayStation-এর নিজের চার্জ এর মধ্যেই ধরা।
STOREFRONT_PAYMENT_FEE_PERCENT = os.environ.get('STOREFRONT_PAYMENT_FEE_PERCENT', '2')

# Render-এর Logs-এ error দেখার জন্য
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {'console': {'class': 'logging.StreamHandler'}},
    'root': {'handlers': ['console'], 'level': 'INFO'},
    'loggers': {
        'django': {'handlers': ['console'], 'level': 'INFO', 'propagate': False},
    },
}

# ============================================================
# django-allauth কনফিগ
# ============================================================
SITE_ID = 1

AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',          # Phone/password login
    'allauth.account.auth_backends.AuthenticationBackend', # Facebook login
]

# allauth সেটিংস
ACCOUNT_EMAIL_REQUIRED = False
ACCOUNT_USERNAME_REQUIRED = False
ACCOUNT_AUTHENTICATION_METHOD = 'username'
SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_EMAIL_REQUIRED = False

# আমাদের User model-এ username/email ফিল্ড নেই — allauth-কে জানাতে হবে,
# নইলে `migrate` (account.0006) FieldError দিয়ে ক্র্যাশ করে
ACCOUNT_USER_MODEL_USERNAME_FIELD = 'phone_number'
ACCOUNT_USER_MODEL_EMAIL_FIELD = None

# Facebook token DB-তে রাখো — নইলে fb_page_select-এ SocialToken কখনো পাওয়া যাবে না
SOCIALACCOUNT_STORE_TOKENS = True

# Facebook শুধু https redirect URI মানে
ACCOUNT_DEFAULT_HTTP_PROTOCOL = 'https'

# Facebook login সফল হলে কোথায় যাবে
SOCIALACCOUNT_LOGIN_ON_GET = True

# Graph API ভার্সন এক জায়গায় — v21.0-এর মেয়াদ শেষ ২১ জানুয়ারি ২০২৭
FACEBOOK_GRAPH_VERSION = 'v25.0'
# Facebook webhook: Meta App → Webhooks-এ Callback URL https://<ডোমেইন>/facebook/webhook/ আর এই Verify Token বসাবেন।
# App Secret না দিলে Django Admin-এর Facebook Social App থেকে নেওয়া হয়।
FACEBOOK_WEBHOOK_VERIFY_TOKEN = os.environ.get('FACEBOOK_WEBHOOK_VERIFY_TOKEN', '')
FACEBOOK_APP_SECRET = os.environ.get('FACEBOOK_APP_SECRET', '')
# Meta Business portfolio (Edumi) → Brand safety → Domains → sellpunch.com → "Add a meta-tag"-এর content।
# হোমপেজের <head>-এ বসে (partials/landing_seo.html)। ডোমেইন আবার যোগ করলে নতুন কোড env-এ দিন।
FACEBOOK_DOMAIN_VERIFICATION = (os.environ.get('FACEBOOK_DOMAIN_VERIFICATION') or '7rh5vwevehlcj3rluhleivo9nd4n83').strip()
# বাইরে পাঠানো লিংকের জন্য সাইটের ঠিকানা (খালি থাকলে Render-এর ঠিকানা)
SITE_URL = os.environ.get('SITE_URL', '').rstrip('/')
# দিনে একবারের কাজের (বাকির অটো-তাগাদা) গোপন চাবি — Cloudflare-এর Secrets-এ CRON_SECRET (store/views_cron.py)
CRON_SECRET = os.environ.get('CRON_SECRET', '').strip()

# কুরিয়ারের API ঠিকানা। টেস্টের সময় sandbox বসানো যায়:
# PATHAO_BASE_URL=https://courier-api-sandbox.pathao.com, REDX_BASE_URL=https://sandbox.redx.com.bd/v1.0.0-beta
STEADFAST_BASE_URL = os.environ.get('STEADFAST_BASE_URL', 'https://portal.packzy.com/api/v1').rstrip('/')
PATHAO_BASE_URL = os.environ.get('PATHAO_BASE_URL', 'https://api-hermes.pathao.com').rstrip('/')
REDX_BASE_URL = os.environ.get('REDX_BASE_URL', 'https://openapi.redx.com.bd/v1.0.0-beta').rstrip('/')

# Facebook App — Meta Developer Console থেকে নেবে
SOCIALACCOUNT_PROVIDERS = {
    'facebook': {
        'METHOD': 'oauth2',
        'SDK_URL': '//connect.facebook.net/{locale}/sdk.js',
        'SCOPE': [
            'email',
            'public_profile',
            'pages_show_list',          # পেইজ লিস্ট দেখার জন্য
            'pages_read_engagement',    # পোস্টে কমেন্ট পড়ার জন্য
            'pages_manage_posts',       # পোস্ট করার জন্য
            'pages_messaging',          # ইনবক্সে মেসেজ পাঠানোর জন্য
            'pages_manage_metadata',    # পেইজে webhook subscribe করার জন্য
            'pages_manage_engagement',  # কমেন্টের নিচে "ইনবক্স চেক করুন" লেখার জন্য
            'pages_read_user_engagement',  # কে কমেন্ট করেছে পড়ার জন্য
        ],
        'AUTH_PARAMS': {
            'auth_type': 'reauthenticate',
        },
        'INIT_PARAMS': {'cookie': True},
        'FIELDS': [
            'id',
            'name',
            'email',
            'picture',
        ],
        'EXCHANGE_TOKEN': True,
        'LOCALE_FUNC': 'store.facebook_helpers.get_fb_locale',
        'VERIFIED_EMAIL': False,
        'VERSION': FACEBOOK_GRAPH_VERSION,
        'GRAPH_API_URL': f'https://graph.facebook.com/{FACEBOOK_GRAPH_VERSION}',
    }
}

# Business ধরনের Meta App-এ "Facebook Login for Business" থাকে: সেখানে permission-গুলো একটা Configuration-এ
# বাছাই করা হয় আর লগইনে scope-এর বদলে config_id পাঠাতে হয়। Configuration ID Environment-এ বসালে সেটাই ব্যবহার হবে।
FACEBOOK_LOGIN_CONFIG_ID = os.environ.get('FACEBOOK_LOGIN_CONFIG_ID', '').strip()
if FACEBOOK_LOGIN_CONFIG_ID:
    SOCIALACCOUNT_PROVIDERS['facebook']['AUTH_PARAMS']['config_id'] = FACEBOOK_LOGIN_CONFIG_ID
    SOCIALACCOUNT_PROVIDERS['facebook']['SCOPE'] = []

# Custom Adapters
ACCOUNT_ADAPTER = 'accounts.adapters.AccountAdapter'
SOCIALACCOUNT_ADAPTER = 'accounts.adapters.SocialAccountAdapter'
