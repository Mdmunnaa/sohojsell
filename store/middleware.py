# ============================================================
# SellPunch — দোকানের সাবডোমেইন / নিজের ডোমেইন
# ============================================================
# কীভাবে কাজ করে (STORE_BASE_DOMAIN = sellpunch.com ধরে):
# 1. munnafashion.sellpunch.com/product/5/ → ভেতরে /shop/munnafashion/product/5/ চালানো হয়,
#    কিন্তু ব্রাউজারে ছোট ঠিকানাটাই থাকে।
# 2. www.munnashop.com (Premium-এর নিজের ডোমেইন) → একইভাবে সেই দোকান।
# 3. মূল সাইটে পুরনো /shop/munnafashion/... লিংকে ঢুকলে সাবডোমেইনে পাঠিয়ে দেয়,
#    তাই আগে Facebook-এ শেয়ার করা লিংকও কাজ করে।
# 4. বাকি সব (ড্যাশবোর্ড, ল্যান্ডিং পেইজ) আগের মতো।
# ============================================================
import re

from django.conf import settings
from django.contrib import messages
from django.http import HttpResponsePermanentRedirect, HttpResponseRedirect
from django.shortcuts import redirect, render

from .models import Shop

# দোকানের সাইটেও এগুলো মূল অ্যাপ থেকে আসবে
PASSTHROUGH_PREFIXES = ('/static/', '/media/', '/favicon.ico', '/robots.txt')
OLD_SHOP_PATH_RE = re.compile(r'^/shop/(?P<slug>[a-z0-9-]+)(?P<rest>/.*)?$')
# এই সাবডোমেইনগুলো দোকান না, মূল সাইট হিসেবেই চলবে
MAIN_SUBDOMAINS = {'www'}


def _with_query(request, path):
    query = request.META.get('QUERY_STRING', '')
    return f'{path}?{query}' if query else path


class ShopSubdomainMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.storefront_shop_id = None
        host = request.get_host().split(':')[0].lower()
        base = getattr(settings, 'STORE_BASE_DOMAIN', '')

        # মূল সাইট (PRIMARY_HOST, যেমন cf.sellpunch.com) কখনো দোকান না
        if base and host.endswith('.' + base) and host != getattr(settings, 'PRIMARY_HOST', None):
            sub = host[:-(len(base) + 1)]
            if sub not in MAIN_SUBDOMAINS and '.' not in sub:
                shop = Shop.objects.filter(slug=sub).only('id', 'slug').first()
                if shop is None:
                    return render(request, 'store/storefront/not_found.html',
                                  {'subdomain': sub, 'main_url': f'https://{base}/'}, status=404)
                return self._serve_shop(request, shop)
        elif self._may_be_custom_domain(host, base):
            bare = host[4:] if host.startswith('www.') else host
            shop = Shop.objects.filter(custom_domain__in=[bare, f'www.{bare}']).first()
            if shop is not None:
                from .plans import has_custom_domain
                if has_custom_domain(shop):
                    return self._serve_shop(request, shop)
                # Premium শেষ হলে নিজের ডোমেইনের কাস্টমারদের সাবডোমেইনে পাঠানো
                return HttpResponseRedirect(shop.storefront_url)
        elif base and request.method in ('GET', 'HEAD'):
            redirect_response = self._redirect_old_shop_link(request, base)
            if redirect_response is not None:
                return redirect_response

        return self.get_response(request)

    @staticmethod
    def _may_be_custom_domain(host, base):
        if '.' not in host or host in ('localhost', '127.0.0.1', 'testserver'):
            return False
        if base and host in (base, f'www.{base}'):
            return False
        if host in (getattr(settings, 'RENDER_EXTERNAL_HOSTNAME', None), getattr(settings, 'PRIMARY_HOST', None)):
            return False
        if host.endswith(('.onrender.com', '.workers.dev')):
            return False
        return not any(host == d or host.endswith('.' + d) for d in ('sellpunch.com', 'sohojsell.com'))

    def _serve_shop(self, request, shop):
        request.storefront_shop_id = shop.pk
        path = request.path_info
        if path.startswith(PASSTHROUGH_PREFIXES):
            return self.get_response(request)

        prefix = f'/shop/{shop.slug}'
        if path == prefix or path.startswith(prefix + '/'):
            if request.method in ('GET', 'HEAD'):
                # সাবডোমেইনেও পুরনো ধাঁচের লিংক এলে ছোট ঠিকানায়
                return HttpResponsePermanentRedirect(_with_query(request, path[len(prefix):] or '/'))
        else:
            new_path = prefix + path
            request.path_info = new_path
            request.META['PATH_INFO'] = new_path
        return self.get_response(request)

    @staticmethod
    def _redirect_old_shop_link(request, base):
        match = OLD_SHOP_PATH_RE.match(request.path_info)
        if not match:
            return None
        slug = match.group('slug')
        if not Shop.objects.filter(slug=slug).exists():
            return None
        # ঠিকানা বদলানো যেতে পারে তাই স্থায়ী (301) না, সাধারণ redirect
        return HttpResponseRedirect(_with_query(request, f"https://{slug}.{base}{match.group('rest') or '/'}"))


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
                    (('/products/', '/categories/', '/barcode/', '/purchases/', '/suppliers/'),
                     staff.can_manage_products, "Product Management"),
                    (('/orders/', '/storefront-orders/', '/courier/'), staff.can_manage_orders, "Order Management"),
                    (('/customers/',), staff.can_manage_customers, "Customer Database"),
                    (('/sms/',), staff.can_send_sms, "SMS Panel"),
                    (('/reports/', '/expenses/'), staff.can_view_reports, "Business Reports"),
                    (('/settings/', '/staff/', '/banners/', '/billing/', '/website/'), staff.can_manage_settings, "Shop Settings"),
                ]

                # যদি লিংকে ঢোকার পারমিশন না থাকে, তবে ড্যাশবোর্ডে পাঠিয়ে দাও
                for paths, has_permission, feature_name in restrictions:
                    if any(path.startswith(p) for p in paths) and not has_permission:
                        messages.error(request, f"Access Denied: You do not have permission for {feature_name}!")
                        return redirect('dashboard')
            else:
                request.user.is_shop_staff = False

        response = self.get_response(request)
        return response
