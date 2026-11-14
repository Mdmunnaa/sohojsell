from django.conf import settings
from django.core.cache import cache


def site_info(request):
    """পাবলিক পেইজের footer, যোগাযোগ আর নীতিমালায় ব্যবসার তথ্য (settings / env থেকে)।"""
    from .company import company_context
    whatsapp = ''.join(ch for ch in settings.SUPPORT_WHATSAPP if ch.isdigit())
    phone = settings.SUPPORT_PHONE
    return {
        'company': company_context(),
        'site': {
            'name': settings.SITE_NAME,
            'name_bn': getattr(settings, 'SITE_NAME_BN', ''),
            'phone': phone,
            'phone_tel': ('+' if phone.strip().startswith('+') else '') + ''.join(ch for ch in phone if ch.isdigit()),
            'email': settings.SUPPORT_EMAIL,
            'info_email': getattr(settings, 'INFO_EMAIL', ''),
            'whatsapp_url': f'https://wa.me/{whatsapp}' if whatsapp else '',
            'legal_name': settings.BUSINESS_LEGAL_NAME,
            'address': settings.BUSINESS_ADDRESS,
            'facebook_url': settings.FACEBOOK_PAGE_URL,
            'policy_updated_on': settings.POLICY_UPDATED_ON,
            'store_domain': settings.STORE_BASE_DOMAIN or 'sellpunch.com',
            'fb_domain_verification': getattr(settings, 'FACEBOOK_DOMAIN_VERIFICATION', ''),
        }
    }


def facebook_login(request):
    """
    Django Admin-এ Facebook Social App যোগ করা থাকলে তবেই
    লগইন/সাইনআপ পেইজে "Facebook দিয়ে লগইন" বাটন দেখাবে।
    প্রতিটা পেইজে ডেটাবেসে না যেতে ফলাফল ১ মিনিট মনে রাখা হয়।
    """
    def _check():
        from allauth.socialaccount.models import SocialApp
        return SocialApp.objects.filter(provider='facebook').exists()

    try:
        enabled = cache.get_or_set('facebook_login_enabled', _check, 60)
    except Exception:
        enabled = False
    return {'facebook_login_enabled': enabled}


def plan_info(request):
    """ড্যাশবোর্ডের পেইজগুলোতে প্যাকেজের লিমিট দেখানোর জন্য: plan.facebook, plan.products, plan.staff ইত্যাদি।"""
    user = getattr(request, 'user', None)
    shop = getattr(user, 'shop', None) if user is not None and user.is_authenticated else None
    if shop is None:
        return {}
    from .plans import limits_for, plan_label
    from .models import Order, ProductReview
    limits = limits_for(shop)
    return {'pending_reviews': ProductReview.objects.filter(shop=shop, is_approved=False).count(),
            # সাইডবারে লাল সংখ্যা: ওয়েবসাইটের যে অর্ডারগুলো এখনো "নতুন" (দেখা/কনফার্ম হয়নি)
            'pending_web_orders': Order.objects.filter(shop=shop, source='storefront', status='Pending').count(),
            'plan': {
        'label': plan_label(shop),
        'is_trial': shop.subscription_plan == 'Free',
        'products': limits['products'],
        'staff': limits['staff'],
        'facebook': limits['facebook'],
        'custom_domain': limits['custom_domain'],
    }}


HQ_ACTIVE = {
    'master_dashboard': 'dashboard', 'manage_shops': 'shops', 'hq_shop': 'shops', 'all_users': 'users',
    'master_billing': 'payments', 'master_settlements': 'settlements', 'hq_sms': 'sms', 'hq_notices': 'notices',
    'hq_activity': 'activity', 'master_settings': 'settings',
}


def hq(request):
    """
    Master HQ-র মেনুর সংখ্যা; সেলারের পাতায় "Master HQ-তে ফিরুন" ব্যানার (সুপারইউজার ঢুকে থাকলে)
    আর প্ল্যাটফর্ম নোটিশ (lazy — যে পাতা দেখায় শুধু সেখানেই ডাটাবেসে যায়)।
    """
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return {}
    from . import hq as rules
    data = {}
    if user.is_superuser:
        if request.path.startswith('/saas-master/'):
            match = getattr(request, 'resolver_match', None)
            data['hq_nav'] = rules.nav_counts
            data['active'] = HQ_ACTIVE.get(getattr(match, 'url_name', ''), '')
        return data
    impersonator = rules.impersonation(request)
    if impersonator:
        data['hq_impersonator'] = impersonator
    shop = getattr(user, 'shop', None)
    if shop is not None:
        data['platform_notices'] = lambda: rules.notices_for(shop)
    return data
