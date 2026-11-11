"""লাইভ ডেমো: হোমপেজের বাটন থেকে পাসওয়ার্ড ছাড়া ডেমো দোকানে ঢোকা (store/demo.py)।"""
from django.contrib import messages
from django.contrib.auth import login, logout
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from . import demo

# /demo/?to=pos → সরাসরি সেই পাতায়
DESTINATIONS = {
    'dashboard': '/dashboard/', 'pos': '/pos/', 'orders': '/orders/', 'products': '/products/',
    'reports': '/reports/', 'dues': '/dues/', 'customers': '/customers/', 'website': '/website/',
    'sms': '/sms/', 'offers': '/offers/', 'landing': '/landing/', 'purchases': '/purchases/',
}


def _not_available(request):
    text = 'ডেমো এখন চালু নেই। একটু পরে আবার চেষ্টা করুন।'
    if request.user.is_authenticated and request.user.is_superuser and demo.LAST_ERROR:
        text += f' (কারণ: {demo.LAST_ERROR})'
    messages.error(request, text)
    return redirect('landing_page')


@require_http_methods(['GET', 'HEAD', 'POST'])
def demo_start(request):
    destination = DESTINATIONS.get(request.GET.get('to', ''), '/dashboard/')
    if request.user.is_authenticated and not demo.is_demo_user(request.user):
        # নিজের অ্যাকাউন্টে লগইন থাকলে এক সেশনে দুজন হওয়া যায় না — জিজ্ঞেস করে লগআউট
        if request.method != 'POST':
            return render(request, 'store/demo_switch.html', {'to': request.GET.get('to', '')})
        logout(request)
    shop = demo.reset_if_stale()
    if shop is None:
        return _not_available(request)
    if not demo.is_demo_user(request.user):
        login(request, shop.user, backend='django.contrib.auth.backends.ModelBackend')
        messages.success(request, f'এটা "{shop.name}" — একটা ডেমো দোকান। যা খুশি করে দেখুন; রোজ রাতে সব আবার আগের মতো হয়ে যায়।')
    return redirect(destination)


@require_http_methods(['GET', 'HEAD'])
def demo_store(request):
    """ডেমো দোকানের কাস্টমার-দিকের ওয়েবসাইট (লগইন লাগে না)।"""
    shop = demo.reset_if_stale()
    if shop is None:
        return _not_available(request)
    return redirect(shop.storefront_url)
