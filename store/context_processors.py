from django.core.cache import cache


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
