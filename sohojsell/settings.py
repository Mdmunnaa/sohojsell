from pathlib import Path
import os

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

# ============================================================
# নিরাপত্তা — সব গোপন জিনিস environment variable থেকে
# ============================================================
DEBUG = env_bool('DEBUG', default=not IS_RENDER)

SECRET_KEY = os.environ.get('SECRET_KEY', '')
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured('SECRET_KEY environment variable সেট করা নেই।')
    SECRET_KEY = 'django-insecure-local-dev-only'

# দোকানের সাবডোমেইন যে ডোমেইনের নিচে বসবে (যেমন sohojsell.com → munnafashion.sohojsell.com)।
# ডোমেইন কিনে Render-এ *.ডোমেইন যোগ করার পর Environment-এ বসাবেন। খালি থাকলে দোকানের লিংক হয় /shop/<নাম>/
STORE_BASE_DOMAIN = os.environ.get('STORE_BASE_DOMAIN', '').strip().lower().strip('.')

ALLOWED_HOSTS = [
    'localhost', '127.0.0.1', '.sohojsell.com',
    '.pythonanywhere.com',  # পুরনো সার্ভার, পুরোপুরি Render-এ গেলে সরিয়ে দিন
] + env_list('ALLOWED_HOSTS')
CSRF_TRUSTED_ORIGINS = ['https://sohojsell.com', 'https://*.sohojsell.com'] + env_list('CSRF_TRUSTED_ORIGINS')
if STORE_BASE_DOMAIN:
    ALLOWED_HOSTS.append(f'.{STORE_BASE_DOMAIN}')
    CSRF_TRUSTED_ORIGINS += [f'https://{STORE_BASE_DOMAIN}', f'https://*.{STORE_BASE_DOMAIN}']

RENDER_EXTERNAL_HOSTNAME = os.environ.get('RENDER_EXTERNAL_HOSTNAME')
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)
    CSRF_TRUSTED_ORIGINS.append(f'https://{RENDER_EXTERNAL_HOSTNAME}')

# Render HTTPS শেষ করে request পাঠায়, তাই এই header দেখে বুঝতে হবে request https কিনা
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

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# R2-এর ৪টা তথ্য দেওয়া থাকলে প্রোডাক্টের ছবি, লোগো, ব্যানার Cloudflare R2-তে যাবে।
# না থাকলে (লোকালে) আগের মতো media/ ফোল্ডারে।
R2_ACCOUNT_ID = os.environ.get('R2_ACCOUNT_ID', '')
R2_ACCESS_KEY_ID = os.environ.get('R2_ACCESS_KEY_ID', '')
R2_SECRET_ACCESS_KEY = os.environ.get('R2_SECRET_ACCESS_KEY', '')
R2_BUCKET_NAME = os.environ.get('R2_BUCKET_NAME', '')
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
SITE_NAME = 'SohojSell'
SUPPORT_PHONE = os.environ.get('SUPPORT_PHONE', '')            # যেমন 01XXXXXXXXX
SUPPORT_EMAIL = os.environ.get('SUPPORT_EMAIL', '')            # যেমন support@yourdomain.com
SUPPORT_WHATSAPP = os.environ.get('SUPPORT_WHATSAPP', '')      # দেশের কোডসহ, যেমন 8801XXXXXXXXX
BUSINESS_LEGAL_NAME = os.environ.get('BUSINESS_LEGAL_NAME', '')  # ট্রেড লাইসেন্সে যে নাম
BUSINESS_ADDRESS = os.environ.get('BUSINESS_ADDRESS', '')
FACEBOOK_PAGE_URL = os.environ.get('FACEBOOK_PAGE_URL', '')
POLICY_UPDATED_ON = '৩ নভেম্বর ২০২৬'

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
            'pages_manage_metadata',    # Phase 2: পেইজে webhook subscribe করার জন্য
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

# Custom Adapters
ACCOUNT_ADAPTER = 'accounts.adapters.AccountAdapter'
SOCIALACCOUNT_ADAPTER = 'accounts.adapters.SocialAccountAdapter'
