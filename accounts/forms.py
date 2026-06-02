from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import User

# সেলারদের রেজিস্ট্রেশন করার ফর্ম
class SellerSignUpForm(UserCreationForm):
    class Meta:
        model = User
        # ফর্মে আমরা শুধু মোবাইল নম্বর এবং নাম চাইব, পাসওয়ার্ড ফিল্ড ডিফল্টভাবেই থাকবে
        fields = ('phone_number', 'name')