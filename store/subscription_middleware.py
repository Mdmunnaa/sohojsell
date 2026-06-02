# ============================================================
# SohojSell — Subscription Lock Middleware
# ============================================================
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta

ALLOWED_URLS = [
    '/accounts/login/',
    '/accounts/logout/',
    '/accounts/signup/',
    '/billing/',
    '/payment/',
    '/saas-master/',
    '/admin/',
    '/static/',
    '/media/',
    '/shop/',
    '/api/',
]


class SubscriptionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and not request.user.is_superuser:
            if hasattr(request.user, 'shop') and request.user.shop:
                shop = request.user.shop
                path = request.path

                allowed = any(path.startswith(url) for url in ALLOWED_URLS)
                if not allowed:
                    today = timezone.now().date()

                    if not shop.is_locked:
                        if shop.subscription_plan == 'Free':
                            # Dynamic trial: created_at + 30 days
                            # trial_ends_at field থাকলে সেটা use করো, না থাকলে created_at থেকে calculate করো
                            try:
                                trial_end = shop.trial_ends_at.date()
                            except AttributeError:
                                trial_end = shop.created_at.date() + timedelta(days=30)

                            if trial_end < today:
                                shop.is_locked = True
                                shop.save(update_fields=['is_locked'])
                        else:
                            if shop.valid_until and shop.valid_until < today:
                                shop.is_locked = True
                                shop.save(update_fields=['is_locked'])

                    if shop.is_locked:
                        billing_url = reverse('billing')
                        if path != billing_url:
                            return redirect(f'{billing_url}?locked=1')

        response = self.get_response(request)
        return response