# accounts/adapters.py
# ============================================================
# Facebook login সফল হওয়ার পর কোথায় যাবে সেটা এখানে ঠিক হয়
# ============================================================
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.account.adapter import DefaultAccountAdapter
from allauth.core.exceptions import ImmediateHttpResponse
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    """
    - Connect (phone দিয়ে লগইন করা সেলার) সফল হলে → fb_page_select
    - Login-এর পরের redirect ঠিক করে AccountAdapter.get_login_redirect_url
    """
    def get_app(self, request, provider, client_id=None):
        """
        Django Admin-এ Facebook Social App যোগ না করা পর্যন্ত কেউ Facebook লগইনে গেলে
        500 error না দেখিয়ে লগইন পেইজে ফেরত পাঠাবে।
        """
        from allauth.socialaccount.models import SocialApp
        try:
            return super().get_app(request, provider, client_id=client_id)
        except SocialApp.DoesNotExist:
            if request is None:
                raise
            messages.warning(request, "Facebook লগইন এখনো চালু হয়নি। আপাতত মোবাইল নম্বর দিয়ে লগইন করুন।")
            raise ImmediateHttpResponse(redirect('login'))

    def is_open_for_signup(self, request, sociallogin):
        """Master HQ থেকে সাইনআপ বন্ধ থাকলে Facebook দিয়েও নতুন অ্যাকাউন্ট না।"""
        from store.models import MasterSetting
        setting = MasterSetting.objects.order_by('pk').only('signups_open').first()
        if setting is not None and not setting.signups_open:
            return False
        return super().is_open_for_signup(request, sociallogin)

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
