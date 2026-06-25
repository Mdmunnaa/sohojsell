# accounts/adapters.py
# ============================================================
# Facebook login সফল হওয়ার পর কোথায় যাবে সেটা এখানে ঠিক হয়
# ============================================================
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.account.adapter import DefaultAccountAdapter
from django.urls import reverse


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    """
    Facebook login সফল হলে:
    - নতুন user হলে → setup_shop পেইজে যাবে
    - পুরনো user হলে → fb_page_select পেইজে যাবে (পেইজ select করতে)
    """
    def get_connect_redirect_url(self, request, socialaccount):
        return reverse('fb_page_select')

    def get_login_redirect_url(self, request):
        # Shop আছে? তাহলে page select করতে যাও
        if hasattr(request.user, 'shop'):
            return reverse('fb_page_select')
        # Shop নেই? তাহলে setup করতে যাও
        return reverse('setup_shop')

    def pre_social_login(self, request, sociallogin):
        """
        Facebook থেকে আসা user-এর phone_number সেট করা
        (আমাদের custom user model phone দিয়ে চলে)
        """
        if sociallogin.is_existing:
            return
        # নতুন user — phone নম্বর না থাকলে FB ID দিয়ে placeholder দাও
        user = sociallogin.user
        if not user.phone_number:
            fb_uid = sociallogin.account.uid
            user.phone_number = f"fb_{fb_uid}"
        if not user.name and sociallogin.account.extra_data:
            user.name = sociallogin.account.extra_data.get('name', '')


class AccountAdapter(DefaultAccountAdapter):
    """Phone-based login এর জন্য adapter"""
    def get_login_redirect_url(self, request):
        if request.user.is_superuser:
            return reverse('master_dashboard')
        return reverse('dashboard')
