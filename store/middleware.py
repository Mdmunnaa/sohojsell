# ============================================================
# SohojSell — Subdomain/Custom Domain Middleware
# ============================================================
# কীভাবে কাজ করে:
# 1. shop.sohojsell.com → সেই shop-এর storefront দেখাবে
# 2. www.moanashop.com (custom domain) → সেই shop-এর storefront দেখাবে
# 3. Normal requests → unchanged
# ============================================================

from django.shortcuts import redirect
from django.http import Http404
from .models import Shop


class ShopSubdomainMiddleware:
    """
    Handles subdomain routing: fashion.sohojsell.com → /shop/fashion/
    """
    MAIN_DOMAINS = ['sohojsell.com', 'www.sohojsell.com', 'localhost', '127.0.0.1']

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = request.get_host().split(':')[0].lower()

        # Check if it's a subdomain of sohojsell.com
        if host.endswith('.sohojsell.com') and host not in self.MAIN_DOMAINS:
            subdomain = host.replace('.sohojsell.com', '')
            # Ignore www, api, admin subdomains
            if subdomain not in ['www', 'api', 'admin', 'mail']:
                try:
                    shop = Shop.objects.get(slug=subdomain)
                    # Rewrite the path to go to the storefront
                    if not request.path.startswith(f'/shop/{subdomain}/'):
                        # Keep query string and path but route to storefront
                        new_path = f'/shop/{subdomain}' + request.path
                        request.path_info = new_path
                        request.META['PATH_INFO'] = new_path
                except Shop.DoesNotExist:
                    pass

        # Check custom domain
        elif host not in self.MAIN_DOMAINS and '.' in host:
            try:
                shop = Shop.objects.get(custom_domain=host)
                if not request.path.startswith(f'/shop/{shop.slug}/'):
                    new_path = f'/shop/{shop.slug}' + request.path
                    request.path_info = new_path
                    request.META['PATH_INFO'] = new_path
            except (Shop.DoesNotExist, AttributeError):
                pass

        response = self.get_response(request)
        return response


from django.shortcuts import redirect
from django.contrib import messages


class StaffAccessMiddleware:
    """
    স্টাফদের ডাইনামিক শপ এক্সেস এবং পারমিশন চেকার (Security Wall)
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if hasattr(request, 'user') and request.user.is_authenticated:
            if not hasattr(request.user, 'shop') and hasattr(request.user, 'staff_profile'):
                # স্টাফের শপকে মেইন শপ হিসেবে সেট করা
                request.user.shop = request.user.staff_profile.shop
                request.user.is_shop_staff = True

                # --- 🛑 PERMISSION SECURITY CHECK ---
                staff = request.user.staff_profile
                path = request.path

                # কোন লিংকে কোন পারমিশন লাগবে তার লিস্ট
                restrictions = [
                    (('/pos/',), staff.can_use_pos, "POS System"),
                    (('/products/', '/categories/', '/barcode/'), staff.can_manage_products, "Product Management"),
                    (('/orders/', '/storefront-orders/', '/courier/'), staff.can_manage_orders, "Order Management"),
                    (('/customers/',), staff.can_manage_customers, "Customer Database"),
                    (('/reports/',), staff.can_view_reports, "Business Reports"),
                    (('/settings/', '/staff/', '/banners/', '/billing/'), staff.can_manage_settings, "Shop Settings"),
                ]

                # যদি লিংকে ঢোকার পারমিশন না থাকে, তবে ড্যাশবোর্ডে পাঠিয়ে দাও
                for paths, has_permission, feature_name in restrictions:
                    if any(path.startswith(p) for p in paths) and not has_permission:
                        messages.error(request, f"Access Denied: You do not have permission for {feature_name}!")
                        return redirect('dashboard')
            else:
                request.user.is_shop_staff = False

        response = self.get_response(request)
        return response