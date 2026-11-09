from django.db import models
from .themes import DEFAULT_THEME, THEME_CHOICES
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
    # Pathao: ইমেইল-পাসওয়ার্ড দিয়ে একবার টোকেন নেওয়া হয়, পাসওয়ার্ড সেভ হয় না; refresh_token দিয়ে নবায়ন
    pathao_client_id = models.CharField(max_length=255, blank=True, default='')
    pathao_client_secret = models.CharField(max_length=255, blank=True, default='')
    pathao_refresh_token = models.TextField(blank=True, default='')
    pathao_token_expires_at = models.DateTimeField(blank=True, null=True)
    pathao_stores = models.JSONField(blank=True, default=list)
    redx_access_token = models.TextField(blank=True, null=True)
    # কুরিয়ারের webhook (যেমন Steadfast-এর Auth Token) যাচাইয়ের জন্য দোকানের গোপন টোকেন
    courier_webhook_token = models.CharField(max_length=64, blank=True, default='')
    # SMS
    sms_api_key = models.CharField(max_length=255, blank=True, null=True)
    sms_balance = models.IntegerField(default=0)
    is_sms_active = models.BooleanField(default=True, help_text="Turn on/off SMS sending")
    # ওয়েবসাইটে প্রোডাক্টের নিচে আসল বিক্রির সংখ্যা (Shipped/Delivered অর্ডার থেকে) দেখানো হবে কিনা
    show_sold_count = models.BooleanField(default=True, help_text="ওয়েবসাইটে কয়টা বিক্রি হয়েছে দেখান")
    storefront_theme = models.CharField(max_length=20, default=DEFAULT_THEME, choices=THEME_CHOICES,
                                        help_text='ওয়েবসাইটের রঙ')
    storefront_tagline = models.CharField(max_length=150, blank=True, default='',
                                          help_text='ব্যানার না থাকলে দোকানের নামের নিচে ছোট লাইন')
    announcement_text = models.CharField(max_length=160, blank=True, default='',
                                         help_text='ওয়েবসাইটের একদম উপরে ঘোষণা, যেমন অফার')
    whatsapp_number = models.CharField(max_length=20, blank=True, default='',
                                       help_text='ওয়েবসাইটে WhatsApp বাটন')
    # এর বেশি দামের অর্ডারে ডেলিভারি ফ্রি (খালি = কখনো ফ্রি না)
    free_delivery_min = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)

    PAYMENT_COD = 'cod'
    PAYMENT_COD_OR_ONLINE = 'cod_or_online'
    PAYMENT_ADVANCE_DELIVERY = 'advance_delivery'
    PAYMENT_ONLINE_ONLY = 'online_only'
    PAYMENT_RULE_CHOICES = [
        (PAYMENT_COD, 'শুধু ক্যাশ অন ডেলিভারি'),
        (PAYMENT_COD_OR_ONLINE, 'কাস্টমার বেছে নেবে: ক্যাশ অন ডেলিভারি বা অনলাইনে'),
        (PAYMENT_ADVANCE_DELIVERY, 'ডেলিভারি চার্জ আগে অনলাইনে, বাকি টাকা ডেলিভারির সময়'),
        (PAYMENT_ONLINE_ONLY, 'পুরো টাকা আগে অনলাইনে'),
    ]
    payment_rule = models.CharField(max_length=20, choices=PAYMENT_RULE_CHOICES, default=PAYMENT_COD)
    # অনলাইনে নেওয়া টাকা কোথায় পাঠানো হবে
    PAYOUT_METHOD_CHOICES = [('bKash', 'bKash'), ('Nagad', 'Nagad'), ('Rocket', 'Rocket'), ('Bank', 'ব্যাংক')]
    payout_method = models.CharField(max_length=10, choices=PAYOUT_METHOD_CHOICES, blank=True, default='')
    payout_account = models.CharField(max_length=150, blank=True, default='',
                                      help_text='মোবাইল নম্বর, বা ব্যাংকের নাম-শাখা-অ্যাকাউন্ট নম্বর')
    payout_account_name = models.CharField(max_length=120, blank=True, default='')
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
    def theme(self):
        from .themes import theme_for
        return theme_for(self.storefront_theme)

    def ensure_webhook_token(self):
        """কুরিয়ারের webhook-এর গোপন টোকেন (না থাকলে বানিয়ে সেভ)।"""
        if not self.courier_webhook_token and self.pk:
            import secrets
            self.courier_webhook_token = secrets.token_urlsafe(32)
            Shop.objects.filter(pk=self.pk).update(courier_webhook_token=self.courier_webhook_token)
        return self.courier_webhook_token

    @property
    def storefront_url(self):
        """
        কাস্টমারকে দেওয়ার মতো দোকানের লিংক।
        STORE_BASE_DOMAIN বসানো থাকলে https://<সাবডোমেইন>.<ডোমেইন>/, না থাকলে (ডোমেইন কেনার আগে) /shop/<সাবডোমেইন>/।
        """
        from .links import storefront_link
        return storefront_link(self)

    @property
    def storefront_host_preview(self):
        """দেখানোর মতো ছোট ঠিকানা (https:// ছাড়া)। ডোমেইন বসানোর আগে আসল কাজ করা লিংকটাই দেখায়।"""
        from django.conf import settings
        base = getattr(settings, 'STORE_BASE_DOMAIN', '')
        if base:
            return f'{self.slug}.{base}'
        host = getattr(settings, 'RENDER_EXTERNAL_HOSTNAME', None) or 'sohojsell.com'
        return f'{host}{self.storefront_url}'

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
    # সেলারের দেওয়া আগের দাম; বিক্রির দামের চেয়ে বেশি হলে ওয়েবসাইটে কেটে দেওয়া দাম আর % ছাড় দেখায়
    compare_price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True,
                                        help_text='আগের দাম (ছাড় দেখাতে)')
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

    @property
    def discount_percent(self):
        """আগের দাম থেকে কত % কম (পূর্ণ সংখ্যা)। ছাড় না থাকলে 0।"""
        if self.compare_price and self.price and self.compare_price > self.price:
            return int((self.compare_price - self.price) * 100 / self.compare_price)
        return 0

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
    # কাস্টমার ওয়েবসাইট থেকে অনলাইনে যা দিয়েছে (ডেলিভারি চার্জ আগে বা পুরো টাকা); কুরিয়ার বাকিটা তুলবে
    advance_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    ONLINE_NONE, ONLINE_PENDING, ONLINE_PAID = '', 'pending', 'paid'
    online_payment_status = models.CharField(max_length=10, blank=True, default='',
                                             choices=[('', '—'), ('pending', 'পেমেন্ট বাকি'), ('paid', 'পরিশোধিত')])
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def due_amount(self):
        """ডেলিভারির সময় কাস্টমারের কাছ থেকে আর কত নিতে হবে।"""
        return max(self.total_amount - self.advance_paid, 0)

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
# ডেলিভারি এলাকা ও চার্জ (কাস্টমার চেকআউটে বেছে নেয়)
# ============================================================
class DeliveryZone(models.Model):
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name='delivery_zones')
    name = models.CharField(max_length=60)
    charge = models.DecimalField(max_digits=8, decimal_places=2)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['sort_order', 'id']

    def __str__(self):
        return f'{self.name} (৳{self.charge:.0f})'


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
    delivery_zone = models.CharField(max_length=60, blank=True, default='')
    order = models.OneToOneField('Order', on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name='storefront_order')

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
    # কমেন্ট করলে ইনবক্সে প্রোডাক্টের লিংক যাবে কিনা, আর কমেন্টের নিচে "ইনবক্স চেক করুন" লিখবে কিনা
    comment_bot_enabled = models.BooleanField(default=True)
    public_reply_enabled = models.BooleanField(default=True)
    connected_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.page_name} → {self.shop.name}"

    class Meta:
        verbose_name = 'Facebook Page Connection'
        verbose_name_plural = 'Facebook Page Connections'


class FacebookCommentReply(models.Model):
    """কোন কমেন্টে উত্তর গেছে (একই কমেন্টে দুবার না, আর সেলার দেখতে পারে কী হচ্ছে)।"""
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name='fb_comment_replies')
    page_id = models.CharField(max_length=50)
    post_id = models.CharField(max_length=100)
    comment_id = models.CharField(max_length=100, unique=True)
    commenter_id = models.CharField(max_length=50, blank=True, default='')
    commenter_name = models.CharField(max_length=150, blank=True, default='')
    message = models.TextField(blank=True, default='')
    product = models.ForeignKey('Product', on_delete=models.SET_NULL, null=True, blank=True)
    status = models.CharField(max_length=10, default='pending')   # pending / sent / failed
    error = models.CharField(max_length=300, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['page_id', 'post_id', 'commenter_id'])]

    def __str__(self):
        return f'{self.commenter_name or self.commenter_id} → {self.status}'


# ============================================================
# কাস্টমার দোকানের ওয়েবসাইটে অনলাইনে টাকা দিলে (টাকা আসে প্ল্যাটফর্মের PayStation-এ,
# ফি কেটে বাকিটা সেলারের পাওনা; ShopPayout দিয়ে পাঠানো হিসাব রাখা হয়)
# ============================================================
class StorefrontPayment(models.Model):
    KIND_FULL, KIND_ADVANCE = 'full', 'advance'
    STATUS_PENDING, STATUS_COMPLETED, STATUS_FAILED = 'Pending', 'Completed', 'Failed'

    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name='customer_payments')
    order = models.ForeignKey('Order', on_delete=models.SET_NULL, null=True, blank=True,
                              related_name='customer_payments')
    sf_order = models.ForeignKey('StorefrontOrder', on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name='payments')
    kind = models.CharField(max_length=10, choices=[(KIND_FULL, 'পুরো টাকা'), (KIND_ADVANCE, 'ডেলিভারি চার্জ আগে')])
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    fee_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    fee_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    net_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    invoice_number = models.CharField(max_length=40, unique=True)
    environment = models.CharField(max_length=10, default='sandbox')
    trx_id = models.CharField(max_length=64, blank=True, default='')
    payment_method = models.CharField(max_length=40, blank=True, default='')
    status = models.CharField(max_length=10, default=STATUS_PENDING,
                              choices=[(STATUS_PENDING, 'Pending'), (STATUS_COMPLETED, 'Completed'),
                                       (STATUS_FAILED, 'Failed')])
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.invoice_number} ৳{self.amount} ({self.status})'


class ShopPayout(models.Model):
    """সেলারকে তার অনলাইন বিক্রির টাকা পাঠানোর রেকর্ড।"""
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name='payouts')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    method = models.CharField(max_length=20, blank=True, default='')
    account = models.CharField(max_length=150, blank=True, default='')
    reference = models.CharField(max_length=100, blank=True, default='', help_text='লেনদেন নম্বর')
    note = models.CharField(max_length=200, blank=True, default='')
    paid_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ['-paid_at']

    def __str__(self):
        return f'{self.shop.name} ← ৳{self.amount}'


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
