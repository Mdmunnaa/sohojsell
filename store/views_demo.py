"""লাইভ ডেমো: হোমপেজের বাটন থেকে পাসওয়ার্ড ছাড়া ডেমো দোকানে ঢোকা (store/demo.py)।"""
from django.contrib import messages
from django.contrib.auth import login
from django.shortcuts import redirect
from django.views.decorators.http import require_http_methods

from . import demo

# /demo/?to=pos → সরাসরি সেই পাতায়
DESTINATIONS = {
    'dashboard': '/dashboard/', 'pos': '/pos/', 'orders': '/orders/', 'products': '/products/',
    'reports': '/reports/', 'dues': '/dues/', 'customers': '/customers/', 'website': '/website/',
    'sms': '/sms/', 'offers': '/offers/', 'landing': '/landing/', 'purchases': '/purchases/',
}


@require_http_methods(['GET', 'HEAD'])
def demo_start(request):
    shop = demo.reset_if_stale()
    if shop is None:
        messages.error(request, 'ডেমো এখন চালু নেই। একটু পরে আবার চেষ্টা করুন।')
        return redirect('landing_page')
    if request.user.is_authenticated and not demo.is_demo_user(request.user):
        messages.info(request, 'আপনি নিজের অ্যাকাউন্টে লগইন আছেন। ডেমো দেখতে আগে লগআউট করুন।')
        return redirect('master_dashboard' if request.user.is_superuser else 'dashboard')
    if not demo.is_demo_user(request.user):
        login(request, shop.user, backend='django.contrib.auth.backends.ModelBackend')
        messages.success(request, f'এটা "{shop.name}" — একটা ডেমো দোকান। যা খুশি করে দেখুন; রোজ রাতে সব আবার আগের মতো হয়ে যায়।')
    return redirect(DESTINATIONS.get(request.GET.get('to', ''), '/dashboard/'))


@require_http_methods(['GET', 'HEAD'])
def demo_store(request):
    """ডেমো দোকানের কাস্টমার-দিকের ওয়েবসাইট (লগইন লাগে না)।"""
    shop = demo.reset_if_stale()
    if shop is None:
        messages.error(request, 'ডেমো এখন চালু নেই। একটু পরে আবার চেষ্টা করুন।')
        return redirect('landing_page')
    return redirect(shop.storefront_url)
