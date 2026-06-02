from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth import get_user_model
from django.contrib import messages

User = get_user_model()


def signup(request):
    if request.user.is_authenticated:
        if not hasattr(request.user, 'shop'):
            return redirect('setup_shop')
        return redirect('dashboard')

    if request.method == 'POST':
        phone = request.POST.get('phone', '').strip()
        p_word = request.POST.get('password')
        c_word = request.POST.get('confirm_password')

        if not phone:
            messages.error(request, "❌ Phone number is required!")
            return redirect('signup')

        if p_word != c_word:
            messages.error(request, "❌ Passwords do not match!")
            return redirect('signup')

        if User.objects.filter(phone_number=phone).exists():
            messages.error(request, "❌ This phone number is already registered!")
            return redirect('signup')

        user = User.objects.create_user(phone_number=phone, password=p_word)
        login(request, user)
        messages.success(request, "🎉 Account created! Now set up your shop.")
        return redirect('setup_shop')

    return render(request, 'accounts/signup.html')


def user_login(request):
    if request.user.is_authenticated:
        if request.user.is_superuser:
            return redirect('master_dashboard')
        return redirect('dashboard')

    if request.method == 'POST':
        phone = request.POST.get('username', '').strip()
        p_word = request.POST.get('password')

        user = authenticate(request, phone_number=phone, password=p_word)

        if user is not None:
            login(request, user)
            # phone_number দিয়ে welcome — username নয়
            messages.success(request, f"Welcome back! 🚀")
            if user.is_superuser:
                return redirect('master_dashboard')
            else:
                return redirect('dashboard')
        else:
            messages.error(request, "❌ Invalid Phone Number or Password!")

    return render(request, 'accounts/login.html')


def user_logout(request):
    logout(request)
    messages.info(request, "You have been logged out successfully. 👋")
    return redirect('login')
