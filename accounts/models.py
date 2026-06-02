from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin

# ইউজার তৈরি করার ম্যানেজার
class UserManager(BaseUserManager):
    def create_user(self, phone_number, password=None, **extra_fields):
        if not phone_number:
            raise ValueError('সেলারদের অবশ্যই একটি মোবাইল নম্বর থাকতে হবে')
        user = self.model(phone_number=phone_number, **extra_fields)
        user.set_password(password) # পাসওয়ার্ড এনক্রিপ্ট করে সেভ করবে
        user.save(using=self._db)
        return user

    def create_superuser(self, phone_number, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)

        return self.create_user(phone_number, password, **extra_fields)

# আমাদের কাস্টম ইউজার মডেল
class User(AbstractBaseUser, PermissionsMixin):
    phone_number = models.CharField(max_length=15, unique=True, verbose_name='Phone Number')
    name = models.CharField(max_length=100, blank=True, null=True, verbose_name='Full Name')
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(auto_now_add=True)

    objects = UserManager()

    # ইউজারনেমের বদলে লগইনের জন্য মোবাইল নম্বর ব্যবহার হবে
    USERNAME_FIELD = 'phone_number'
    REQUIRED_FIELDS = []

    def __str__(self):
        return self.phone_number