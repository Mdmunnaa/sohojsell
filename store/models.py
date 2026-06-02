from django.db import models
from django.conf import settings
from datetime import timedelta
from django.utils import timezone
from django.utils.text import slugify


def get_trial_end_date():
    return timezone.now() + timedelta(days=30)


class Shop(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='shop')
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=100, unique=True, blank=True, null=True)
    custom_domain = models.CharField(max_length=255, blank=True, null=True, unique=True, help_text='e.g. www.myanshop.com')
    facebook_page_url = models.URLField(max_length=255, blank=True, null=True)
    # নিচের ৪টি লাইন অ্যাড করুন
    instagram_link = models.URLField(max_length=255, blank=True, null=True)
    youtube_link = models.URLField(max_length=255, blank=True, null=True)
    privacy_policy = models.TextField(blank=True, null=True, help_text="আপনার স্টোরের প্রাইভেসি পলিসি লিখুন")
    return_policy = models.TextField(blank=True, null=True, help_text="আপনার স্টোরের রিটার্ন পলিসি লিখুন")
    phone = models.CharField(max_length=20, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    logo = models.ImageField(upload_to='shop_logos/', blank=True, null=True)
    # Storefront customization
    store_tagline = models.CharField(max_length=200, blank=True, null=True, help_text='e.g. Fast Delivery | Best Quality')
    store_banner_color = models.CharField(max_length=7, default='#0d6efd', help_text='Hex color for store banner')
    # Courier API Keys
    steadfast_api_key = models.CharField(max_length=255, blank=True, null=True)
    steadfast_secret_key = models.CharField(max_length=255, blank=True, null=True)
    pathao_store_id = models.CharField(max_length=255, blank=True, null=True)
    pathao_access_token = models.TextField(blank=True, null=True)
    redx_access_token = models.TextField(blank=True, null=True)
    # SMS
    sms_api_key = models.CharField(max_length=255, blank=True, null=True)
    sms_balance = models.IntegerField(default=0)
    is_sms_active = models.BooleanField(default=True, help_text="Turn on/off SMS sending")
    # SaaS Plan
    PLAN_CHOICES = (
        ('Free', 'Free (Trial)'),
        ('Basic', 'Basic'),
        ('Standard', 'Standard'),
        ('Premium', 'Premium'),
    )
    subscription_plan = models.CharField(max_length=20, choices=PLAN_CHOICES, default='Free')
    created_at = models.DateTimeField(auto_now_add=True)
    trial_ends_at = models.DateTimeField(default=get_trial_end_date)
    valid_until = models.DateField(null=True, blank=True, help_text='Plan valid until this date')
    is_locked = models.BooleanField(default=False, help_text='Account locked due to expired subscription')
    is_paid = models.BooleanField(default=False)

    def is_subscription_active(self):
        from django.utils import timezone
        today = timezone.now().date()
        # Free trial check
        if self.subscription_plan == 'Free':
            return self.trial_ends_at.date() >= today
        # Paid plan check
        if self.valid_until:
            return self.valid_until >= today
        return False

    def days_remaining(self):
        from django.utils import timezone
        today = timezone.now().date()
        if self.subscription_plan == 'Free':
            diff = (self.trial_ends_at.date() - today).days
        elif self.valid_until:
            diff = (self.valid_until - today).days
        else:
            return 0
        return max(0, diff)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
            original_slug = self.slug
            count = 1
            while Shop.objects.filter(slug=self.slug).exists():
                self.slug = f'{original_slug}-{count}'
                count += 1
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Category(models.Model):
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name='categories')
    name = models.CharField(max_length=100)

    def __str__(self):
        return f"{self.name} - {self.shop.name}"


class Product(models.Model):
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name='products')
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, null=True, help_text='Product description for storefront')
    image = models.ImageField(upload_to='products/', blank=True, null=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    cost_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    stock_quantity = models.PositiveIntegerField(default=0)
    barcode = models.CharField(max_length=50, blank=True, null=True, unique=True, help_text='Leave blank to auto-generate')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        # Auto-generate barcode if not provided
        if not self.barcode:
            import random, string
            self.barcode = ''.join(random.choices(string.digits, k=12))
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Customer(models.Model):
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name='customers')
    name = models.CharField(max_length=150)
    phone = models.CharField(max_length=15)
    address = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} - {self.phone}"


class Order(models.Model):
    SOURCE_CHOICES = [
        ('dashboard', 'Dashboard'),
        ('pos', 'POS'),
        ('storefront', 'Online Store'),
    ]
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name='orders')
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='orders')
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='dashboard')
    delivery_charge = models.DecimalField(max_digits=10, decimal_places=2, default=100.00)
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    payment_method = models.CharField(
        max_length=20,
        choices=[('COD', 'Cash on Delivery'), ('Paid', 'Full Paid'), ('bKash', 'bKash'), ('Card', 'Card'), ('Credit', 'Credit')],
        default='COD'
    )
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    steadfast_tracking_code = models.CharField(max_length=100, blank=True, null=True)
    courier_partner = models.CharField(max_length=50, blank=True, null=True, help_text="e.g., Steadfast, Pathao, RedX")
    STATUS_CHOICES = [
        ('Pending', 'Pending'),
        ('Confirmed', 'Confirmed'),
        ('Shipped', 'Shipped'),
        ('Delivered', 'Delivered'),
        ('Returned', 'Returned'),
        ('Cancelled', 'Cancelled'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')
    note = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Order #{self.id} - {self.customer.name}"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    cost_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    def __str__(self):
        return f"{self.quantity} x {self.product.name}"

    def get_total(self):
        return self.price * self.quantity


class MasterSetting(models.Model):
    payment_store_id = models.CharField(max_length=255, blank=True, null=True)
    payment_secret_key = models.CharField(max_length=255, blank=True, null=True)
    is_payment_live = models.BooleanField(default=False)

    # SMS এর জন্য নতুন ফিল্ড
    sms_client_id = models.CharField(max_length=255, blank=True, null=True)  # এই লাইনটা অ্যাড করুন
    sms_api_key = models.CharField(max_length=255, blank=True, null=True)
    sms_sender_id = models.CharField(max_length=255, blank=True, null=True)

    platform_name = models.CharField(max_length=100, default='SohojSell')
    delivery_charge_default = models.DecimalField(max_digits=8, decimal_places=2, default=100.00)

    def __str__(self):
        return "SaaS Master Settings"


# ============================================================
# STOREFRONT ORDER (Customer-facing orders from public shop)
# ============================================================
class StorefrontOrder(models.Model):
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name='storefront_orders')
    customer_name = models.CharField(max_length=150)
    customer_phone = models.CharField(max_length=15)
    customer_address = models.TextField()
    customer_note = models.TextField(blank=True, null=True)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    delivery_charge = models.DecimalField(max_digits=10, decimal_places=2, default=80)

    STATUS_CHOICES = [
        ('Pending', 'Pending'),
        ('Confirmed', 'Confirmed'),
        ('Shipped', 'Shipped'),
        ('Delivered', 'Delivered'),
        ('Cancelled', 'Cancelled'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"SF-Order #{self.id} — {self.customer_name}"


class StorefrontOrderItem(models.Model):
    order = models.ForeignKey(StorefrontOrder, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)
    price = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"{self.quantity} x {self.product.name}"

    def get_total(self):
        return self.price * self.quantity


# ============================================================
# BANNER (Storefront Hero Images)
# ============================================================
class Banner(models.Model):
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name='banners')
    image = models.ImageField(upload_to='banners/')
    title = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Banner — {self.shop.name}"


# ============================================================
# STAFF ACCOUNTS & PERMISSIONS
# ============================================================
class StaffProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='staff_profile')
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name='staff_members')

    # Permissions (টগল সুইচগুলোর জন্য)
    can_use_pos = models.BooleanField(default=True, help_text="Can process sales in POS")
    can_manage_products = models.BooleanField(default=False, help_text="Can add, edit or delete products")
    can_manage_orders = models.BooleanField(default=False, help_text="Can change order status & delete")
    can_manage_customers = models.BooleanField(default=False, help_text="Can view customer details")
    can_view_reports = models.BooleanField(default=False, help_text="Can view revenue & profit reports")
    can_manage_settings = models.BooleanField(default=False, help_text="Can access shop settings")

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Staff: {self.user.name} - Shop: {self.shop.name}"


# ============================================================
# MANUAL PAYMENT REQUEST (bKash/Nagad)
# ============================================================
class PaymentRequest(models.Model):
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name='payment_requests')
    plan_name = models.CharField(max_length=50)  # Basic, Standard, Premium
    payment_method = models.CharField(max_length=20, choices=[('bKash', 'bKash'), ('Nagad', 'Nagad')])
    sender_number = models.CharField(max_length=15)
    transaction_id = models.CharField(max_length=100, unique=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)

    STATUS_CHOICES = [
        ('Pending', 'Pending'),
        ('Approved', 'Approved'),
        ('Rejected', 'Rejected'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.shop.name} - {self.plan_name} - {self.transaction_id}"


class PageView(models.Model):
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name='page_views')
    # Product null থাকলে বুঝবো এটা শপের হোমপেজ ভিউ, আর product থাকলে বুঝবো প্রোডাক্ট ভিউ
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True, related_name='views')

    ip_address = models.GenericIPAddressField(null=True, blank=True)
    session_key = models.CharField(max_length=40, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.shop.name} - {'Product: ' + self.product.name if self.product else 'Storefront'}"