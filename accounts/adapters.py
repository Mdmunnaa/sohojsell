# accounts/adapters.py
# ============================================================
# Facebook login সফল হওয়ার পর কোথায় যাবে সেটা এখানে ঠিক হয়
# ============================================================
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.account.adapter import DefaultAccountAdapter
from django.urls import reverse


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    """
    - Connect (phone দিয়ে লগইন করা সেলার) সফল হলে → fb_page_select
    - Login-এর পরের redirect ঠিক করে AccountAdapter.get_login_redirect_url
    """
    def get_connect_redirect_url(self, request, socialaccount):
        return reverse('fb_page_select')

    def save_user(self, request, sociallogin, form=None):
        """
        নতুন Facebook user সেভ হওয়ার ঠিক আগে phone_number placeholder বসানো।
        (pre_social_login-এ বসালে auto-signup ফ্লোতে সেটা হারিয়ে যায়)
        """
        user = sociallogin.user
        if not user.phone_number:
            user.phone_number = f"fb_{sociallogin.account.uid}"
        if not user.name:
            user.name = (sociallogin.account.extra_data or {}).get('name', '')
        return super().save_user(request, sociallogin, form)


class AccountAdapter(DefaultAccountAdapter):
    """Phone-based login এর জন্য adapter"""
    def get_login_redirect_url(self, request):
        if request.user.is_superuser:
            return reverse('master_dashboard')
        return reverse('dashboard')
