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


# ---------------------------------------------------------------- পাসওয়ার্ড: নিজে বদলানো, ভুলে গেলে SMS কোড
PASSWORD_MIN = 6
RESET_CODE_MINUTES = 10
RESET_CODE_TRIES = 5              # একটা কোডে এতবার ভুল হলে কোডটা বাতিল
RESET_PER_PHONE, RESET_PER_IP, RESET_WINDOW = 3, 10, 60 * 60      # ঘণ্টায় এক নম্বরে ৩টা, এক IP থেকে ১০টা কোড
RESET_SESSION_KEY = 'pw_reset_phone'


def _password_problem(password, password2):
    if len(password or '') < PASSWORD_MIN:
        return f'পাসওয়ার্ড কমপক্ষে {PASSWORD_MIN} অক্ষরের হতে হবে।'
    if password != password2:
        return 'দুটো পাসওয়ার্ড মেলেনি।'
    return ''


def _code_key(phone):
    return f'pw-reset:{phone}'


def _hash_code(phone, code):
    import hashlib
    from django.conf import settings
    return hashlib.sha256(f'{settings.SECRET_KEY}:{phone}:{code}'.encode()).hexdigest()


def password_forgot(request):
    """
    ধাপ ১: মোবাইল নম্বর দিলে সেই নম্বরে ৬ সংখ্যার কোড যায় (SMS)। নম্বরে অ্যাকাউন্ট থাকুক বা না থাকুক একই উত্তর —
    কে SellPunch ব্যবহার করে তা বাইরে থেকে জানা যায় না। কোড ডাটাবেসের ক্যাশে হ্যাশ হয়ে থাকে, ১০ মিনিট।
    """
    import secrets
    from django.core.cache import caches
    from store import sms
    from .forms import normalize_bd_mobile

    if request.method == 'POST':
        phone = normalize_bd_mobile(request.POST.get('phone') or '')
        if not phone:
            messages.error(request, 'সঠিক মোবাইল নম্বর দিন (যেমন 01712345678)।')
            return render(request, 'accounts/password_forgot.html', status=400)
        ip = ratelimit.client_ip(request)
        if ratelimit.too_many('pw-reset-ip', ip, RESET_PER_IP, RESET_WINDOW) or \
                ratelimit.too_many('pw-reset-phone', phone, RESET_PER_PHONE, RESET_WINDOW):
            messages.error(request, 'অনেকবার কোড চাওয়া হয়েছে। এক ঘণ্টা পর আবার চেষ্টা করুন।')
            return render(request, 'accounts/password_forgot.html', status=429)
        user = User.objects.filter(phone_number=phone, is_active=True).first()
        demo = bool(user and getattr(getattr(user, 'shop', None), 'is_demo', False))
        if user is not None and not user.is_superuser and not demo:      # HQ আর ডেমোর অ্যাকাউন্ট SMS কোডে রিসেট হয় না
            code = f'{secrets.randbelow(1000000):06d}'
            caches['ratelimit'].set(_code_key(phone), {'hash': _hash_code(phone, code), 'tries': 0},
                                    RESET_CODE_MINUTES * 60)
            from django.conf import settings
            sms.notify(phone, f'{settings.SITE_NAME}: পাসওয়ার্ড বদলানোর কোড {code}। {RESET_CODE_MINUTES} মিনিট চলবে। '
                              'কাউকে বলবেন না।')
        request.session[RESET_SESSION_KEY] = phone
        return redirect('password_reset_code')
    return render(request, 'accounts/password_forgot.html')


def password_reset_code(request):
    """ধাপ ২: SMS-এর কোড আর নতুন পাসওয়ার্ড। ঠিক হলে পাসওয়ার্ড বদলে লগইন পাতায়।"""
    from django.core.cache import caches
    phone = request.session.get(RESET_SESSION_KEY)
    if not phone:
        return redirect('password_forgot')
    context = {'masked': f'{phone[:3]}*****{phone[-3:]}', 'minutes': RESET_CODE_MINUTES}
    if request.method == 'POST':
        code = ''.join(ch for ch in (request.POST.get('code') or '').translate(str.maketrans('০১২৩৪৫৬৭৮৯', '0123456789'))
                       if ch.isdigit())
        password, password2 = request.POST.get('password') or '', request.POST.get('password2') or ''
        cache = caches['ratelimit']
        entry = cache.get(_code_key(phone))
        problem = _password_problem(password, password2)
        if entry is None:
            messages.error(request, 'কোডের মেয়াদ শেষ বা অনেকবার ভুল হয়েছে। নতুন কোড নিন।')
            return redirect('password_forgot')
        import hmac
        if len(code) != 6 or not hmac.compare_digest(entry['hash'], _hash_code(phone, code)):
            entry['tries'] += 1
            if entry['tries'] >= RESET_CODE_TRIES:
                cache.delete(_code_key(phone))
                messages.error(request, 'অনেকবার ভুল কোড দেওয়া হয়েছে। নতুন কোড নিন।')
                return redirect('password_forgot')
            cache.set(_code_key(phone), entry, RESET_CODE_MINUTES * 60)
            messages.error(request, 'কোডটা মেলেনি। SMS দেখে আবার লিখুন।')
            return render(request, 'accounts/password_reset_code.html', context, status=400)
        if problem:
            messages.error(request, problem)
            return render(request, 'accounts/password_reset_code.html', {**context, 'code': code}, status=400)
        user = User.objects.filter(phone_number=phone, is_active=True, is_superuser=False).first()
        cache.delete(_code_key(phone))
        request.session.pop(RESET_SESSION_KEY, None)
        if user is None:
            return redirect('password_forgot')
        user.set_password(password)
        user.save(update_fields=['password'])
        ratelimit.clear('login-phone', phone)
        messages.success(request, 'পাসওয়ার্ড বদলে গেছে। নতুন পাসওয়ার্ড দিয়ে লগইন করুন।')
        return redirect('login')
    return render(request, 'accounts/password_reset_code.html', context)


def password_change(request):
    """লগইন থাকা অবস্থায় নিজের পাসওয়ার্ড বদলানো (মালিক বা স্টাফ) — এখনকার পাসওয়ার্ড দিয়ে।"""
    from django.contrib.auth import update_session_auth_hash
    if not request.user.is_authenticated:
        return redirect('login')
    if request.method == 'POST':
        current = request.POST.get('current') or ''
        password, password2 = request.POST.get('password') or '', request.POST.get('password2') or ''
        scope, ident = 'pw-change', request.user.pk
        if ratelimit.blocked(scope, ident, 8):
            messages.error(request, 'অনেকবার ভুল হয়েছে। ১৫ মিনিট পর আবার চেষ্টা করুন।')
        elif not request.user.check_password(current):
            ratelimit.hit(scope, ident, 15 * 60)
            messages.error(request, 'এখনকার পাসওয়ার্ডটা মেলেনি।')
        elif _password_problem(password, password2):
            messages.error(request, _password_problem(password, password2))
        elif password == current:
            messages.error(request, 'নতুন পাসওয়ার্ড আগেরটার থেকে আলাদা দিন।')
        else:
            request.user.set_password(password)
            request.user.save(update_fields=['password'])
            update_session_auth_hash(request, request.user)      # এই ব্রাউজারে লগইন থাকে; অন্য সব জায়গা থেকে লগআউট
            messages.success(request, 'পাসওয়ার্ড বদলে গেছে। অন্য ফোন বা কম্পিউটারে আবার লগইন করতে হবে।')
            return redirect('password_change')
    return render(request, 'accounts/password_change.html')
