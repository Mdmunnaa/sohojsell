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
        ('Free', 'Free Trial (30 days)'),
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
        # সাবডোমেইন সাধারণত সাইনআপে সেলার নিজে বাছে। অ্যাডমিন বা পুরনো কোড থেকে খালি এলে
        # নাম থেকে (বাংলা নাম হলে এলোমেলো) একটা বৈধ সাবডোমেইন বসে — আগে বাংলা নামে slug খালি হয়ে যেত।
        from .subdomains import generate_unique, normalize
        if self.slug:
            self.slug = normalize(self.slug)
        if not self.slug:
            self.slug = generate_unique(self.name, exclude_shop_id=self.pk)
        super().save(*args, **kwargs)

    @property
    def subdomain(self):
        return self.slug

    @property
    def storefront_url(self):
        """
        কাস্টমারকে দেওয়ার মতো দোকানের লিংক।
        STORE_BASE_DOMAIN বসানো থাকলে https://<সাবডোমেইন>.<ডোমেইন>/, না থাকলে (ডোমেইন কেনার আগে) /shop/<সাবডোমেইন>/।
        """
        from django.conf import settings
        from django.urls import reverse
        base = getattr(settings, 'STORE_BASE_DOMAIN', '')
        if base:
            return f'https://{self.slug}.{base}/'
        return reverse('storefront_home', args=[self.slug])

    @property
    def storefront_host_preview(self):
        from django.conf import settings
        return f"{self.slug}.{getattr(settings, 'STORE_BASE_DOMAIN', '') or 'sohojsell.com'}"

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

# ============================================================
# FACEBOOK PAGE CONNECTION (নতুন যোগ হয়েছে)
# ============================================================
class FacebookPageConnection(models.Model):
    """
    সেলারের সাথে তার Facebook Page-এর connection সংরক্ষণ করবে।
    একজন সেলার একটাই পেইজ connect করতে পারবে।
    """
    shop = models.OneToOneField(
        Shop,
        on_delete=models.CASCADE,
        related_name='fb_page'
    )
    page_id = models.CharField(max_length=50, verbose_name='Facebook Page ID')
    page_name = models.CharField(max_length=200, verbose_name='Page Name')
    page_access_token = models.TextField(verbose_name='Page Access Token')
    page_picture = models.URLField(blank=True, null=True, verbose_name='Page Profile Picture')
    fan_count = models.PositiveIntegerField(default=0, verbose_name='Page Followers')
    category = models.CharField(max_length=100, blank=True, null=True)

    # User-level token (Page select করার সময় সেভ হবে)
    user_access_token = models.TextField(blank=True, null=True)

    is_active = models.BooleanField(default=True)
    connected_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.page_name} → {self.shop.name}"

    class Meta:
        verbose_name = 'Facebook Page Connection'
        verbose_name_plural = 'Facebook Page Connections'


# ============================================================
# অনলাইন পেমেন্ট (PayStation) — প্ল্যান কেনা বা SMS কেনা
# ============================================================
class OnlinePayment(models.Model):
    """
    প্রতিটা অনলাইন পেমেন্টের চেষ্টা একটা রেকর্ড। invoice_number আমরা নিজে বানাই আর
    PayStation-এ পাঠাই; পরে callback বা IPN এলে ওই নম্বর দিয়েই রেকর্ড খুঁজে PayStation-এর
    সার্ভারে যাচাই করা হয়। কী কেনা হচ্ছে আর কত টাকা — সব এখানে আমাদের দিকেই লেখা থাকে,
    ব্রাউজার থেকে আসা কোনো মান বিশ্বাস করা হয় না।
    """
    KIND_PLAN = 'plan'
    KIND_SMS = 'sms'
    KIND_CHOICES = ((KIND_PLAN, 'Subscription plan'), (KIND_SMS, 'SMS recharge'))

    STATUS_PENDING = 'Pending'
    STATUS_COMPLETED = 'Completed'
    STATUS_FAILED = 'Failed'
    STATUS_CHOICES = (
        (STATUS_PENDING, 'Pending'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_FAILED, 'Failed'),
    )

    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name='online_payments')
    kind = models.CharField(max_length=10, choices=KIND_CHOICES)
    plan_name = models.CharField(max_length=50, help_text='Basic / Standard / Premium, অথবা SMS প্যাকের নাম')
    days = models.PositiveIntegerField(default=0, help_text='প্ল্যান হলে কত দিন যোগ হবে')
    sms_count = models.PositiveIntegerField(default=0, help_text='SMS প্যাক হলে কতটা SMS যোগ হবে')
    amount = models.DecimalField(max_digits=10, decimal_places=2)

    invoice_number = models.CharField(max_length=64, unique=True)
    environment = models.CharField(max_length=10, default='sandbox', help_text='sandbox না live')
    trx_id = models.CharField(max_length=64, blank=True, default='')
    payment_method = models.CharField(max_length=40, blank=True, default='')
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.invoice_number} — {self.shop.name} — {self.plan_name} — {self.status}"
