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
    shop = demo.reset_if_stale()
    if shop is None:
        return _not_available(request)
    if request.user.is_authenticated and not demo.is_demo_user(request.user):
        # নিজের অ্যাকাউন্টে লগইন থাকলে এক সেশনে দুজন হওয়া যায় না — জিজ্ঞেস করে লগআউট
        if request.method != 'POST':
            return render(request, 'store/demo_switch.html', {'to': request.GET.get('to', '')})
        logout(request)
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


@require_http_methods(['GET', 'HEAD'])
def demo_check(request):
    """মাস্টারের জন্য: ডেমো এখনই বানিয়ে দেখায় কোথায় আটকায় (/demo/check/)।"""
    import time
    import traceback
    from django.http import HttpResponse
    if not (request.user.is_authenticated and request.user.is_superuser):
        return redirect('login')
    started = time.monotonic()
    try:
        shop = demo.build()
    except Exception:    # noqa: BLE001 — কারণটাই দেখানো উদ্দেশ্য
        body = traceback.format_exc()
        status, title = 500, 'ডেমো বানানো যায়নি'
    else:
        body = (f'দোকান: {shop.name} (/{shop.slug}/)\nপ্রোডাক্ট: {shop.products.count()}\nঅর্ডার: {shop.orders.count()}\n'
                f'কাস্টমার: {shop.customers.count()}\nসময়: {time.monotonic() - started:.1f}s')
        status, title = 200, 'ডেমো ঠিক আছে'
    html = (f'<!doctype html><meta charset="utf-8"><title>{title}</title>'
            f'<body style="font-family:monospace;padding:24px;max-width:960px"><h2>{title}</h2>'
            f'<pre style="white-space:pre-wrap;background:#f4f4f8;padding:16px;border-radius:8px">{body}</pre>'
            f'<p><a href="/demo/">/demo/</a> · <a href="/saas-master/">মাস্টার</a></p></body>')
    return HttpResponse(html, status=status)

