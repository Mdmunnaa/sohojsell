from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET

from store import ratelimit
from store.models import Shop
from store.subdomains import normalize, suggest_available, validate_subdomain

from .forms import ShopSignupForm

User = get_user_model()


def _rate_limited(key, request, limit, window_seconds):
    """একই IP থেকে নির্দিষ্ট সময়ে বেশিবার চেষ্টা আটকানো (সাইনআপ স্প্যাম, সাবডোমেইন খোঁজা) — store/ratelimit.py।"""
    return ratelimit.too_many(key, ratelimit.client_ip(request), limit, window_seconds)


# লগইন: ভুল পাসওয়ার্ড বারবার দিলে সেই নম্বর আর সেই IP কিছুক্ষণ আটকে থাকে (পাসওয়ার্ড আন্দাজ ঠেকাতে)
LOGIN_WINDOW = 15 * 60
LOGIN_PHONE_LIMIT = 8        # এক নম্বরে ১৫ মিনিটে ৮ বার ভুল
LOGIN_IP_LIMIT = 30          # এক IP থেকে ১৫ মিনিটে ৩০ বার ভুল (এক দোকানের অনেক স্টাফ একই ইন্টারনেটে থাকতে পারে)
LOGIN_BLOCKED = 'অনেকবার ভুল হয়েছে। ১৫ মিনিট পর আবার চেষ্টা করুন।'


def signup(request):
    if request.user.is_authenticated:
        if not hasattr(request.user, 'shop'):
            return redirect('setup_shop')
        return redirect('dashboard')

    from store.models import MasterSetting
    setting = MasterSetting.objects.order_by('pk').only('signups_open').first()
    if setting is not None and not setting.signups_open:       # Master HQ → সিস্টেম সেটিংস থেকে বন্ধ
        return render(request, 'accounts/signup.html', {'signups_closed': True}, status=403 if request.method == 'POST' else 200)

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
                messages.success(request, f"স্বাগতম! {data['shop_name']}-এর অ্যাকাউন্ট তৈরি হয়েছে, "
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
    return JsonResponse({'ok': True, 'value': cleaned, 'message': 'খালি আছে'})


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

        ip = ratelimit.client_ip(request)
        if ratelimit.blocked('login-phone', phone, LOGIN_PHONE_LIMIT) or ratelimit.blocked('login-ip', ip, LOGIN_IP_LIMIT):
            messages.error(request, LOGIN_BLOCKED)
            return render(request, 'accounts/login.html', status=429)

        user = authenticate(request, phone_number=phone, password=p_word)

        if user is not None:
            ratelimit.clear('login-phone', phone)
            login(request, user)
            messages.success(request, "আবার স্বাগতম!")
            if user.is_superuser:
                return redirect('master_dashboard')
            return redirect('dashboard')
        ratelimit.hit('login-phone', phone, LOGIN_WINDOW)
        ratelimit.hit('login-ip', ip, LOGIN_WINDOW)
        messages.error(request, "মোবাইল নম্বর বা পাসওয়ার্ড ভুল।")

    return render(request, 'accounts/login.html')


def user_logout(request):
    """শুধু POST-এ লগআউট — অন্য সাইটের একটা লিংক বা ছবি দিয়ে কাউকে লগআউট করানো যায় না।"""
    if request.method != 'POST':
        return redirect('dashboard' if request.user.is_authenticated else 'login')
    logout(request)
    messages.info(request, "লগআউট হয়েছে।")
    return redirect('login')
