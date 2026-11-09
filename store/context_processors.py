from django.conf import settings
from django.core.cache import cache


def site_info(request):
    """পাবলিক পেইজের footer, যোগাযোগ আর নীতিমালায় ব্যবসার তথ্য (settings / env থেকে)।"""
    whatsapp = ''.join(ch for ch in settings.SUPPORT_WHATSAPP if ch.isdigit())
    return {
        'site': {
            'name': settings.SITE_NAME,
            'name_bn': getattr(settings, 'SITE_NAME_BN', ''),
            'phone': settings.SUPPORT_PHONE,
            'email': settings.SUPPORT_EMAIL,
            'whatsapp_url': f'https://wa.me/{whatsapp}' if whatsapp else '',
            'legal_name': settings.BUSINESS_LEGAL_NAME,
            'address': settings.BUSINESS_ADDRESS,
            'facebook_url': settings.FACEBOOK_PAGE_URL,
            'policy_updated_on': settings.POLICY_UPDATED_ON,
            'store_domain': settings.STORE_BASE_DOMAIN or 'sellpunch.com',
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
    limits = limits_for(shop)
    return {'plan': {
        'label': plan_label(shop),
        'is_trial': shop.subscription_plan == 'Free',
        'products': limits['products'],
        'staff': limits['staff'],
        'facebook': limits['facebook'],
        'custom_domain': limits['custom_domain'],
    }}
