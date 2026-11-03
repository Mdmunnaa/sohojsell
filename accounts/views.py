from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET

from store.models import Shop
from store.subdomains import normalize, suggest_available, validate_subdomain

from .forms import ShopSignupForm

User = get_user_model()


def _client_ip(request):
    # Render নিজে শেষে আসল IP যোগ করে; প্রথমটা ব্রাউজার বানিয়ে পাঠাতে পারে, তাই শেষেরটা নেওয়া হয়
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    return forwarded.split(',')[-1].strip() if forwarded else request.META.get('REMOTE_ADDR', '')


def _rate_limited(key, request, limit, window_seconds):
    """একই IP থেকে নির্দিষ্ট সময়ে বেশিবার চেষ্টা আটকানো (সাইনআপ স্প্যাম, সাবডোমেইন খোঁজা)।"""
    cache_key = f'rl:{key}:{_client_ip(request)}'
    count = cache.get(cache_key, 0)
    if count >= limit:
        return True
    cache.set(cache_key, count + 1, window_seconds)
    return False


def signup(request):
    if request.user.is_authenticated:
        if not hasattr(request.user, 'shop'):
            return redirect('setup_shop')
        return redirect('dashboard')

    form = ShopSignupForm(request.POST or None)
    if request.method == 'POST':
        if _rate_limited('signup', request, limit=20, window_seconds=3600):
            messages.error(request, 'অনেকবার চেষ্টা হয়েছে। এক ঘণ্টা পর আবার চেষ্টা করুন।')
            return render(request, 'accounts/signup.html', {'form': form}, status=429)
        if form.is_valid():
            data = form.cleaned_data
            try:
                with transaction.atomic():
                    user = User.objects.create_user(phone_number=data['phone'], password=data['password'])
                    Shop.objects.create(user=user, name=data['shop_name'], slug=data['subdomain'], phone=data['phone'])
            except IntegrityError:
                # একই মুহূর্তে অন্য কেউ একই সাবডোমেইন বা নম্বর নিয়ে ফেললে
                form.add_error(None, 'এই সাবডোমেইন বা নম্বর এইমাত্র অন্য কেউ নিয়েছে, আবার চেষ্টা করুন।')
            else:
                # allauth যোগ হওয়ার পর দুটো auth backend আছে, তাই কোনটা দিয়ে লগইন সেটা বলে দিতে হয়
                login(request, user, backend='django.contrib.auth.backends.ModelBackend')
                messages.success(request, f"🎉 স্বাগতম! {data['shop_name']}-এর অ্যাকাউন্ট তৈরি হয়েছে, "
                                          "৩০ দিন সব ফিচার সম্পূর্ণ ফ্রি।")
                return redirect('dashboard')

    return render(request, 'accounts/signup.html', {'form': form})


@require_GET
def check_subdomain(request):
    """সাইনআপে টাইপ করার সাথে সাথে সাবডোমেইন খালি কিনা দেখানো।"""
    if _rate_limited('subdomain_check', request, limit=60, window_seconds=600):
        return JsonResponse({'ok': False, 'message': 'একটু পরে আবার চেষ্টা করুন।'}, status=429)
    value = normalize(request.GET.get('s', ''))[:40]
    exclude = None
    if request.user.is_authenticated and hasattr(request.user, 'shop'):
        exclude = request.user.shop.pk   # settings থেকে বদলানোর সময় নিজের বর্তমান নাম "নেওয়া" দেখাবে না
    try:
        cleaned = validate_subdomain(value, exclude_shop_id=exclude)
    except Exception as exc:  # ValidationError
        message = exc.messages[0] if hasattr(exc, 'messages') else str(exc)
        return JsonResponse({'ok': False, 'message': message, 'suggestion': suggest_available(value, exclude)})
    return JsonResponse({'ok': True, 'value': cleaned, 'message': 'খালি আছে ✓'})


def user_login(request):
    if request.user.is_authenticated:
        if request.user.is_superuser:
            return redirect('master_dashboard')
        return redirect('dashboard')

    if request.method == 'POST':
        from .forms import normalize_bd_mobile
        raw = request.POST.get('username', '').strip()
        phone = normalize_bd_mobile(raw) or raw      # +880 বা বাংলা সংখ্যায় লিখলেও চলবে
        p_word = request.POST.get('password')

        user = authenticate(request, phone_number=phone, password=p_word)

        if user is not None:
            login(request, user)
            messages.success(request, "Welcome back! 🚀")
            if user.is_superuser:
                return redirect('master_dashboard')
            return redirect('dashboard')
        messages.error(request, "❌ মোবাইল নম্বর বা পাসওয়ার্ড ভুল!")

    return render(request, 'accounts/login.html')


def user_logout(request):
    logout(request)
    messages.info(request, "You have been logged out successfully. 👋")
    return redirect('login')
