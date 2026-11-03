import re

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError

from store.subdomains import validate_subdomain

from .models import User

BD_MOBILE_RE = re.compile(r'^01[3-9][0-9]{8}$')
BENGALI_DIGITS = str.maketrans('০১২৩৪৫৬৭৮৯', '0123456789')


def normalize_bd_mobile(text):
    """'+8801712-345678' / '8801712345678' / '০১৭১২৩৪৫৬৭৮' → '01712345678'। ঠিক না হলে None।"""
    if not text:
        return None
    digits = str(text).translate(BENGALI_DIGITS).strip().replace(' ', '').replace('-', '')
    if digits.startswith('+'):
        digits = digits[1:]
    if digits.startswith('880'):
        digits = digits[2:]
    return digits if BD_MOBILE_RE.match(digits) else None


# সেলারদের রেজিস্ট্রেশন করার ফর্ম (পুরনো, Django admin-এর জন্য রাখা)
class SellerSignUpForm(UserCreationForm):
    class Meta:
        model = User
        fields = ('phone_number', 'name')


class ShopSignupForm(forms.Form):
    """
    এক পেইজের সাইনআপ (Edumi-র মতো): দোকানের নাম, নিজের সাবডোমেইন, মোবাইল আর পাসওয়ার্ড।
    সফল হলে একসাথে অ্যাকাউন্ট আর দোকান তৈরি হয়, ৩০ দিনের ফ্রি ট্রায়াল শুরু হয়।
    """
    shop_name = forms.CharField(max_length=200)
    subdomain = forms.CharField(max_length=40)
    phone = forms.CharField(max_length=20)
    password = forms.CharField(min_length=6, strip=False)
    password2 = forms.CharField(strip=False)
    website = forms.CharField(required=False)  # বটের ফাঁদ — মানুষ দেখে না, তাই খালি থাকে

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.error_messages['required'] = 'এই ঘরটা পূরণ করুন।'
        self.fields['password'].error_messages['min_length'] = 'পাসওয়ার্ড কমপক্ষে ৬ অক্ষরের হতে হবে।'

    def clean_shop_name(self):
        name = ' '.join(self.cleaned_data['shop_name'].split())
        if len(name) < 2:
            raise ValidationError('দোকানের নাম লিখুন।')
        return name

    def clean_subdomain(self):
        return validate_subdomain(self.cleaned_data['subdomain'])

    def clean_phone(self):
        phone = normalize_bd_mobile(self.cleaned_data['phone'])
        if not phone:
            raise ValidationError('সঠিক মোবাইল নম্বর দিন (যেমন 01712345678)।')
        if get_user_model().objects.filter(phone_number=phone).exists():
            raise ValidationError('এই নম্বরে আগে থেকেই একটা অ্যাকাউন্ট আছে, লগইন করুন।')
        return phone

    def clean(self):
        data = super().clean()
        if data.get('website'):
            raise ValidationError('ফর্মটা জমা দেওয়া যায়নি। পেইজটা রিফ্রেশ করে আবার চেষ্টা করুন।')
        password, password2 = data.get('password'), data.get('password2')
        if password and password2 and password != password2:
            self.add_error('password2', 'দুটো পাসওয়ার্ড মেলেনি।')
        return data


class ShopDetailsForm(forms.Form):
    """দোকান ছাড়া লগইন করা ইউজারের (যেমন Facebook দিয়ে আসা) জন্য: দোকানের নাম, সাবডোমেইন, ঠিকানা।"""
    shop_name = forms.CharField(max_length=200)
    subdomain = forms.CharField(max_length=40)
    address = forms.CharField(max_length=300, required=False)
    fb_link = forms.URLField(required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.error_messages['required'] = 'এই ঘরটা পূরণ করুন।'
        self.fields['fb_link'].error_messages['invalid'] = 'সঠিক লিংক দিন (https:// দিয়ে শুরু)।'

    def clean_shop_name(self):
        name = ' '.join(self.cleaned_data['shop_name'].split())
        if len(name) < 2:
            raise ValidationError('দোকানের নাম লিখুন।')
        return name

    def clean_subdomain(self):
        return validate_subdomain(self.cleaned_data['subdomain'])
