from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = 'django-insecure-q11n*d#z()f8tg3*3@9%0m)5o&e#6*bp)*wpbb6!7=1qitsio^'

DEBUG = True

ALLOWED_HOSTS = ['*', 'localhost', '127.0.0.1', '.sohojsell.com', '.pythonanywhere.com']

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sites',          # allauth-এর জন্য দরকার
    'allauth',                        # নতুন
    'allauth.account',                # নতুন
    'allauth.socialaccount',          # নতুন
    'allauth.socialaccount.providers.facebook',  # নতুন - Facebook provider
    'accounts',
    'store',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'allauth.account.middleware.AccountMiddleware',   # নতুন — allauth-এর middleware
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'store.subscription_middleware.SubscriptionMiddleware',
    'store.middleware.ShopSubdomainMiddleware',
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
            ],
        },
    },
]

WSGI_APPLICATION = 'sohojsell.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

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

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static'] if (BASE_DIR / 'static').exists() else []

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

AUTH_USER_MODEL = 'accounts.User'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

SESSION_COOKIE_AGE = 86400 * 30
SESSION_SAVE_EVERY_REQUEST = True

LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/dashboard/'

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

# Facebook login সফল হলে কোথায় যাবে
SOCIALACCOUNT_LOGIN_ON_GET = True

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
        'VERSION': 'v21.0',
        'GRAPH_API_URL': 'https://graph.facebook.com/v21.0',
    }
}

# Custom Adapters
ACCOUNT_ADAPTER = 'accounts.adapters.AccountAdapter'
SOCIALACCOUNT_ADAPTER = 'accounts.adapters.SocialAccountAdapter'
