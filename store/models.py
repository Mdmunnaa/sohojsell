from django.db import models
from .themes import DEFAULT_DESIGN, DEFAULT_THEME, DESIGN_CHOICES, THEME_CHOICES
from django.conf import settings
from decimal import Decimal
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
    # নিজের ডোমেইনের অবস্থা (store/domains.py): pending → DNS মিললে dns_ok → চালু হলে live
    DOMAIN_PENDING, DOMAIN_DNS_OK, DOMAIN_LIVE = 'pending', 'dns_ok', 'live'
    custom_domain_status = models.CharField(max_length=10, default='pending', blank=True)
    custom_domain_checked_at = models.DateTimeField(null=True, blank=True)
    custom_domain_note = models.CharField(max_length=200, blank=True, default='')
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
    # বাকির তাগাদা নিজে থেকে: ০ = বন্ধ; নাহলে এত দিন পর পর (বাকি থাকা কাস্টমারদের) SMS
    due_reminder_days = models.PositiveSmallIntegerField(default=0)
    # অটো SMS: উপরেরটা মূল সুইচ; নিচেরগুলো কোন কোন সময়ে কাস্টমারকে SMS যাবে (store/order_flow.py)
    sms_on_received = models.BooleanField(default=True)
    sms_on_confirmed = models.BooleanField(default=False)
    sms_on_shipped = models.BooleanField(default=False)
    sms_on_delivered = models.BooleanField(default=False)
    # ওয়েবসাইটে প্রোডাক্টের নিচে আসল বিক্রির সংখ্যা (Shipped/Delivered অর্ডার থেকে) দেখানো হবে কিনা
    show_sold_count = models.BooleanField(default=True, help_text="ওয়েবসাইটে কয়টা বিক্রি হয়েছে দেখান")
    storefront_theme = models.CharField(max_length=20, default=DEFAULT_THEME, choices=THEME_CHOICES,
                                        help_text='ওয়েবসাইটের রঙ')
    # রিভিউ: কাস্টমার রিভিউ দিতে পারবে কিনা, আর নতুন রিভিউ নিজে থেকে দেখাবে নাকি সেলার দেখে অনুমোদন দেবে
    reviews_enabled = models.BooleanField(default=True)
    reviews_auto_approve = models.BooleanField(default=False)
    # ওয়েবসাইটের ডিজাইন (লেআউট) আর নিজের বেছে নেওয়া রঙ (#RRGGBB; ফাঁকা হলে উপরের থিমের রঙ)
    storefront_design = models.CharField(max_length=20, default=DEFAULT_DESIGN, choices=DESIGN_CHOICES)
    storefront_color = models.CharField(max_length=7, blank=True, default='')
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
    # POS (দোকানে বিক্রি) আর রসিদ
    VAT_EXCLUSIVE, VAT_INCLUSIVE = 'exclusive', 'inclusive'
    VAT_MODE_CHOICES = [(VAT_EXCLUSIVE, 'দামের সাথে যোগ হবে'), (VAT_INCLUSIVE, 'দামের মধ্যেই ধরা আছে')]
    pos_vat_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0,
                                          help_text='০ = VAT নেই')
    pos_vat_mode = models.CharField(max_length=10, choices=VAT_MODE_CHOICES, default=VAT_EXCLUSIVE)
    pos_bin = models.CharField('BIN নম্বর', max_length=30, blank=True, default='')
    pos_receipt_width = models.PositiveSmallIntegerField(choices=[(80, '80mm'), (58, '58mm')], default=80)
    pos_receipt_note = models.CharField(max_length=200, blank=True, default='',
                                        help_text='রসিদের নিচে, যেমন: ৭ দিনের মধ্যে বদলানো যাবে')
    pos_auto_print = models.BooleanField(default=False, help_text='বিক্রি শেষ হলেই রসিদ প্রিন্ট')
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
    # কাস্টমার যা দেখে (ওয়েবসাইট, চেকআউট, ট্র্যাকিং, কাস্টমারের SMS) সেটা কোন ভাষায় — store/sf_lang.py
    storefront_language = models.CharField(max_length=2, default='bn',
                                           choices=[('bn', 'বাংলা'), ('en', 'English')])
    # লাইভ ডেমো দোকান (store/demo.py): যে কেউ /demo/ থেকে ঢুকে দেখতে পারে, রোজ নিজে থেকে আগের মতো হয়
    is_demo = models.BooleanField(default=False, editable=False)
    # Master HQ থেকে দোকান বন্ধ করা (প্রতারণা, স্প্যাম ইত্যাদি) — মালিক/স্টাফ ঢুকতে পারে না, ওয়েবসাইটও বন্ধ
    is_suspended = models.BooleanField(default=False)
    hq_note = models.TextField(blank=True, default='', help_text='শুধু Master HQ-তে দেখা যায় — ফোনে কী কথা হলো ইত্যাদি')
    demo_reset_at = models.DateTimeField(null=True, blank=True, editable=False)

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
        from . import images
        if images.is_new_upload(self.logo):
            self.logo = images.logo_version(self.logo) or self.logo
        super().save(*args, **kwargs)

    @property
    def subdomain(self):
        return self.slug

    @property
    def theme(self):
        from .themes import theme_for
        return theme_for(self.storefront_theme, self.storefront_color)

    @property
    def design(self):
        from .themes import DEFAULT_DESIGN, DESIGNS
        return self.storefront_design if self.storefront_design in DESIGNS else DEFAULT_DESIGN

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
        host = getattr(settings, 'PRIMARY_HOST', None) or 'sellpunch.com'
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
    # লিস্ট আর কার্টে দেখানোর ছোট ছবি; মূল ছবি আপলোডের সময় নিজে থেকে বানানো হয় (store/images.py)
    thumbnail = models.ImageField(upload_to='products/thumbs/', blank=True, null=True, editable=False)
    image_width = models.PositiveIntegerField(null=True, blank=True, editable=False)
    image_height = models.PositiveIntegerField(null=True, blank=True, editable=False)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    cost_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    # সেলারের দেওয়া আগের দাম; বিক্রির দামের চেয়ে বেশি হলে ওয়েবসাইটে কেটে দেওয়া দাম আর % ছাড় দেখায়
    compare_price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True,
                                        help_text='আগের দাম (ছাড় দেখাতে)')
    stock_quantity = models.PositiveIntegerField(default=0)
    barcode = models.CharField(max_length=50, blank=True, null=True, unique=True, help_text='Leave blank to auto-generate')
    is_active = models.BooleanField(default=True)
    # সাইজ/রং থাকলে True; তখন stock_quantity = সব ভ্যারিয়েন্টের স্টকের যোগফল (store/variants.py ঠিক রাখে)
    has_variants = models.BooleanField(default=False, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        # Auto-generate barcode if not provided
        if not self.barcode:
            import random, string
            self.barcode = ''.join(random.choices(string.digits, k=12))
        from . import images
        if images.is_new_upload(self.image):
            main, thumb, size = images.product_versions(self.image)
            if main is not None:
                self.image, self.thumbnail = main, thumb
                self.image_width, self.image_height = size
            else:
                self.thumbnail = self.image_width = self.image_height = None
        elif not self.image:
            self.thumbnail = self.image_width = self.image_height = None
        super().save(*args, **kwargs)

    @property
    def thumb_url(self):
        """লিস্টে দেখানোর ছবি: ছোট ছবি থাকলে সেটা, নাহলে মূল ছবি।"""
        if self.thumbnail:
            return self.thumbnail.url
        return self.image.url if self.image else ''

    @property
    def discount_percent(self):
        """আগের দাম থেকে কত % কম (পূর্ণ সংখ্যা)। ছাড় না থাকলে 0।"""
        if self.compare_price and self.price and self.compare_price > self.price:
            return int((self.compare_price - self.price) * 100 / self.compare_price)
        return 0

    def __str__(self):
        return self.name


class ProductVariant(models.Model):
    """
    একটা প্রোডাক্টের সাইজ/রং (যেমন "লাল / XL")। প্রতিটার আলাদা স্টক আর বারকোড;
    দাম ফাঁকা থাকলে প্রোডাক্টের দামই চলে। বিক্রি-ফেরতের স্টক store/variants.py দিয়ে বদলায়।
    """
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='variants')
    name = models.CharField(max_length=80)
    price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    stock_quantity = models.PositiveIntegerField(default=0)
    barcode = models.CharField(max_length=50, unique=True, blank=True)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['position', 'id']
        constraints = [models.UniqueConstraint(fields=['product', 'name'], name='unique_variant_name_per_product')]

    def save(self, *args, **kwargs):
        if not self.barcode:
            import random, string
            self.barcode = ''.join(random.choices(string.digits, k=12))
        super().save(*args, **kwargs)

    @property
    def sell_price(self):
        return self.price if self.price is not None else self.product.price

    def __str__(self):
        return f'{self.product.name} ({self.name})'


class Customer(models.Model):
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name='customers')
    name = models.CharField(max_length=150)
    phone = models.CharField(max_length=15)
    address = models.TextField()
    # সেলার ব্লক করলে এই নম্বর থেকে ওয়েবসাইটে আর অর্ডার নেওয়া হয় না (ভুয়া অর্ডার ঠেকাতে)
    is_blocked = models.BooleanField(default=False)
    # বাকির খাতা (store/dues.py): কবে দেবে বলেছে, শেষ কবে তাগাদা দেওয়া হলো
    due_promise = models.DateField(null=True, blank=True)
    due_note = models.CharField(max_length=200, blank=True, default='')
    due_reminded_at = models.DateTimeField(null=True, blank=True)
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
        choices=[('COD', 'Cash on Delivery'), ('Paid', 'Full Paid'), ('bKash', 'bKash'), ('Nagad', 'Nagad'),
                 ('Card', 'Card'), ('Mixed', 'Mixed'), ('Credit', 'Credit')],
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
    # POS: VAT, নগদ কত দিয়েছে আর কত ফেরত, কে বিক্রি করেছে। POS-এ advance_paid = এখন পর্যন্ত পাওয়া টাকা
    vat_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    cash_received = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    change_given = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    served_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                  related_name='pos_sales')
    # একই বিক্রি দুবার জমা হওয়া ঠেকাতে POS স্ক্রিনের দেওয়া আইডি (নেট কেটে আবার পাঠালে)
    pos_ref = models.CharField(max_length=40, blank=True, default='', db_index=True)
    coupon_code = models.CharField(max_length=30, blank=True, default='')
    # কোন ল্যান্ডিং পেজ থেকে অর্ডার এসেছে (store/views_landing.py)
    landing = models.ForeignKey('LandingPage', null=True, blank=True, on_delete=models.SET_NULL, related_name='orders')
    # বাতিল/ফেরত হয়ে মাল স্টকে ফিরে গেছে কিনা (store/order_flow.py) — দুবার ফেরত না যায়
    stock_returned = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def due_amount(self):
        """ডেলিভারির সময় কাস্টমারের কাছ থেকে আর কত নিতে হবে।"""
        return max(self.total_amount - self.advance_paid, 0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['shop', 'pos_ref'], condition=~models.Q(pos_ref=''),
                                    name='uniq_pos_ref_per_shop'),
        ]

    @property
    def subtotal(self):
        """ছাড়, VAT আর ডেলিভারির আগে প্রোডাক্টের দাম।"""
        return sum((item.price * item.quantity for item in self.items.all()), 0)

    def __str__(self):
        return f"Order #{self.id} - {self.customer.name}"


class SalePayment(models.Model):
    """
    POS-এর টাকা লেনদেন: বিক্রির সময় পাওয়া টাকা, পরে বাকি আদায়, বা ফেরতের সময় দেওয়া টাকা (ঋণাত্মক)।
    দিনশেষের হিসাব এখান থেকেই হয় — যেদিন টাকা হাতে এসেছে সেদিনের।
    """
    CASH, BKASH, NAGAD, CARD, BANK = 'cash', 'bkash', 'nagad', 'card', 'bank'
    METHOD_CHOICES = [(CASH, 'নগদ'), (BKASH, 'bKash'), (NAGAD, 'Nagad'), (CARD, 'কার্ড'), (BANK, 'ব্যাংক')]
    SALE, DUE_COLLECTION, REFUND = 'sale', 'due', 'refund'
    KIND_CHOICES = [(SALE, 'বিক্রি'), (DUE_COLLECTION, 'বাকি আদায়'), (REFUND, 'ফেরত')]

    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name='sale_payments')
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='payments')
    method = models.CharField(max_length=10, choices=METHOD_CHOICES)
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default=SALE)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    reference = models.CharField(max_length=60, blank=True, default='', help_text='TrxID / কার্ডের শেষ ৪ সংখ্যা')
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name='+')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['created_at', 'id']

    def __str__(self):
        return f'{self.get_method_display()} ৳{self.amount} — #ORD-{self.order_id}'


class SaleReturn(models.Model):
    """
    POS বিক্রির ফেরত (পুরো বা কয়েকটা প্রোডাক্ট)। value = বিক্রির দাম কতটা কমল (ছাড়-VAT মিলিয়ে),
    refund = কাস্টমারকে কত টাকা ফেরত দেওয়া হলো (বাকি থাকলে আগে বাকি থেকে কাটে)।
    """
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name='sale_returns')
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='returns')
    full = models.BooleanField(default=False)
    value = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    refund = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    refund_method = models.CharField(max_length=10, blank=True, default='', choices=SalePayment.METHOD_CHOICES)
    reason = models.CharField(max_length=200, blank=True, default='')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='+')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['created_at', 'id']

    def __str__(self):
        return f'ফেরত #ORD-{self.order_id} ৳{self.value}'


class SaleReturnItem(models.Model):
    sale_return = models.ForeignKey(SaleReturn, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    product_name = models.CharField(max_length=200)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    value = models.DecimalField(max_digits=10, decimal_places=2)


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    cost_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    # কোন সাইজ/রং বিক্রি হয়েছে; ভ্যারিয়েন্ট পরে মুছে গেলেও নামটা বিলে থেকে যায়
    variant = models.ForeignKey(ProductVariant, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    variant_name = models.CharField(max_length=80, blank=True, default='')

    def __str__(self):
        return f"{self.quantity} x {self.display_name}"

    @property
    def display_name(self):
        return f'{self.product.name} ({self.variant_name})' if self.variant_name else self.product.name

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

    platform_name = models.CharField(max_length=100, default='SellPunch')
    delivery_charge_default = models.DecimalField(max_digits=8, decimal_places=2, default=100.00)
    sms_rate = models.DecimalField(max_digits=6, decimal_places=3, default=Decimal('0.400'),
                                   help_text='সেলাররা প্রতি SMS কত টাকায় কিনবে')
    signups_open = models.BooleanField(default=True, help_text='বন্ধ করলে নতুন কেউ অ্যাকাউন্ট খুলতে পারে না')

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
    variant_name = models.CharField(max_length=80, blank=True, default='')

    def __str__(self):
        return f"{self.quantity} x {self.display_name}"

    @property
    def display_name(self):
        return f'{self.product.name} ({self.variant_name})' if self.variant_name else self.product.name

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

    def save(self, *args, **kwargs):
        from . import images
        if images.is_new_upload(self.image):
            self.image = images.banner_version(self.image) or self.image
        super().save(*args, **kwargs)

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
    can_send_sms = models.BooleanField(default=False, help_text="Can send SMS to customers from the SMS panel")

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


class SettlementRequest(models.Model):
    """
    সেলারের টাকা তোলার অনুরোধ (Edumi-র Quick Pay সেটেলমেন্টের মতো)। পেমেন্টের ৭ দিন পর টাকা তোলা যায়,
    কমপক্ষে ৳৫,০০০ (store/shop_payments.py)। মাস্টার টাকা পাঠিয়ে লেনদেন নম্বর দিলে ShopPayout হয়।
    """
    PENDING, PAID, CANCELLED, REJECTED = 'pending', 'paid', 'cancelled', 'rejected'
    STATUS_CHOICES = ((PENDING, 'যাচাই হচ্ছে'), (PAID, 'পাঠানো হয়েছে'), (CANCELLED, 'বাতিল করেছেন'),
                      (REJECTED, 'ফেরত এসেছে'))

    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name='settlement_requests')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    method = models.CharField(max_length=20, blank=True, default='')
    account = models.CharField(max_length=150, blank=True, default='')
    account_name = models.CharField(max_length=120, blank=True, default='')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=PENDING, db_index=True)
    note = models.CharField(max_length=200, blank=True, default='', help_text='ফেরত দিলে কারণ')
    payout = models.OneToOneField(ShopPayout, on_delete=models.SET_NULL, null=True, blank=True, related_name='request')
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [models.UniqueConstraint(fields=['shop'], condition=models.Q(status='pending'),
                                               name='one_open_settlement_per_shop')]

    def __str__(self):
        return f'{self.shop.name} ৳{self.amount} ({self.status})'


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


# ============================================================
# SMS-এর ইতিহাস — প্যানেল থেকে পাঠানো আর অর্ডারের অটো SMS, দুটোই (store/sms.py)
# ============================================================
class SmsLog(models.Model):
    KIND_MANUAL = 'manual'
    KIND_AUTO = 'auto'
    KIND_CHOICES = ((KIND_MANUAL, 'প্যানেল থেকে'), (KIND_AUTO, 'অটো'))

    SENDING, SENT, PARTIAL, FAILED, UNKNOWN = 'sending', 'sent', 'partial', 'failed', 'unknown'
    STATUS_CHOICES = (
        (SENDING, 'পাঠানো হচ্ছে'),
        (SENT, 'গেছে'),
        (PARTIAL, 'কিছু যায়নি'),
        (FAILED, 'যায়নি'),
        (UNKNOWN, 'অবস্থা জানা যায়নি'),
    )

    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name='sms_logs')
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default=KIND_MANUAL)
    audience = models.CharField(max_length=120, help_text='কাদের: "সব কাস্টমার", একটা নম্বর, "অর্ডার নং ১২"')
    message = models.TextField()
    recipients = models.PositiveIntegerField(default=0)
    delivered = models.PositiveIntegerField(default=0, help_text='গেটওয়ে যতজনের SMS নিয়েছে')
    failed = models.PositiveIntegerField(default=0)
    sms_used = models.PositiveIntegerField(default=0, help_text='ব্যালেন্স থেকে কাটা (যা যায়নি তা ফেরত দেওয়ার পরে)')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=SENDING, db_index=True)
    error = models.CharField(max_length=255, blank=True, default='')
    sent_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                related_name='+')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.shop.name} — {self.audience} — {self.sms_used} SMS'


# ============================================================
# কেনা, সাপ্লায়ার আর খরচের খাতা (store/ledger.py)
# ============================================================
PAY_METHOD_CHOICES = [('cash', 'নগদ'), ('bkash', 'bKash'), ('nagad', 'Nagad'), ('bank', 'ব্যাংক'), ('card', 'কার্ড')]


class Supplier(models.Model):
    """যার কাছ থেকে মাল কেনা হয়। বাকি = আগের বাকি + সব কেনা − সব পরিশোধ।"""
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name='suppliers')
    name = models.CharField(max_length=120)
    phone = models.CharField(max_length=20, blank=True, default='')
    address = models.CharField(max_length=200, blank=True, default='')
    note = models.CharField(max_length=300, blank=True, default='')
    opening_due = models.DecimalField(max_digits=12, decimal_places=2, default=0,
                                      help_text='সফটওয়্যারে ওঠানোর আগে থেকে যত বাকি ছিল')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Purchase(models.Model):
    """একবারের মাল কেনা: স্টক বাড়ে, প্রোডাক্টের কেনা দাম গড় করে বসে।"""
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name='purchases')
    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True, blank=True, related_name='purchases')
    purchased_on = models.DateField(db_index=True)
    invoice_no = models.CharField(max_length=40, blank=True, default='')
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text='কেনার সময় যা দেওয়া হয়েছে')
    note = models.CharField(max_length=300, blank=True, default='')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-purchased_on', '-id']

    @property
    def due_amount(self):
        return max(self.total_amount - self.paid_amount, 0)

    def __str__(self):
        return f'Purchase #{self.id}'


class PurchaseItem(models.Model):
    purchase = models.ForeignKey(Purchase, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    variant = models.ForeignKey(ProductVariant, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    name = models.CharField(max_length=290, help_text='কেনার সময়ের নাম; প্রোডাক্ট মুছে গেলেও থাকে')
    quantity = models.PositiveIntegerField()
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2)

    def get_total(self):
        return self.unit_cost * self.quantity


class SupplierPayment(models.Model):
    """সাপ্লায়ারকে দেওয়া টাকা: কেনার সময় (purchase সহ) বা পরে বাকি শোধ।"""
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name='supplier_payments')
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name='payments')
    purchase = models.ForeignKey(Purchase, on_delete=models.CASCADE, null=True, blank=True, related_name='payments')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    method = models.CharField(max_length=10, choices=PAY_METHOD_CHOICES, default='cash')
    paid_on = models.DateField(db_index=True)
    note = models.CharField(max_length=200, blank=True, default='')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-paid_on', '-id']


class Expense(models.Model):
    """দোকানের খরচ (ভাড়া, বেতন, বিজ্ঞাপন...) — রিপোর্টে পণ্যের লাভ থেকে বাদ গিয়ে নিট লাভ হয়।"""
    CATEGORY_CHOICES = [
        ('rent', 'দোকান ভাড়া'), ('salary', 'বেতন'), ('utility', 'বিদ্যুৎ / পানি / গ্যাস'),
        ('internet', 'ইন্টারনেট / মোবাইল'), ('ads', 'বিজ্ঞাপন / বুস্ট'), ('transport', 'যাতায়াত / পরিবহন'),
        ('packaging', 'প্যাকেজিং'), ('courier', 'কুরিয়ার / ডেলিভারি'), ('repair', 'মেরামত'),
        ('food', 'চা-নাস্তা / আপ্যায়ন'), ('other', 'অন্যান্য'),
    ]
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name='expenses')
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='other')
    title = models.CharField(max_length=120, blank=True, default='')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    spent_on = models.DateField(db_index=True)
    method = models.CharField(max_length=10, choices=PAY_METHOD_CHOICES, default='cash')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-spent_on', '-id']


# ============================================================
# কুপন ও অফার, অসম্পূর্ণ অর্ডার, রিভিউ (store/offers.py, store/reviews.py)
# ============================================================
class Coupon(models.Model):
    """ওয়েবসাইটে চেকআউটে কুপন কোড: % ছাড়, নির্দিষ্ট টাকা ছাড়, বা ফ্রি ডেলিভারি।"""
    PERCENT, AMOUNT, FREE_DELIVERY = 'percent', 'amount', 'free_delivery'
    KIND_CHOICES = [(PERCENT, 'শতাংশ ছাড়'), (AMOUNT, 'টাকা ছাড়'), (FREE_DELIVERY, 'ফ্রি ডেলিভারি')]

    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name='coupons')
    code = models.CharField(max_length=30)
    kind = models.CharField(max_length=15, choices=KIND_CHOICES, default=PERCENT)
    value = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text='% বা টাকা')
    min_order = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text='কমপক্ষে এত টাকার অর্ডারে')
    max_discount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True,
                                       help_text='% ছাড়ে সর্বোচ্চ কত টাকা')
    usage_limit = models.PositiveIntegerField(null=True, blank=True, help_text='মোট কতবার ব্যবহার করা যাবে')
    used_count = models.PositiveIntegerField(default=0)
    starts_on = models.DateField(null=True, blank=True)
    ends_on = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-id']
        constraints = [models.UniqueConstraint(fields=['shop', 'code'], name='unique_coupon_code_per_shop')]

    def __str__(self):
        return self.code


class AbandonedCheckout(models.Model):
    """কাস্টমার চেকআউটে নম্বর দিয়ে অর্ডার না করে চলে গেলে — সেলার দেখে কল বা SMS করতে পারে।"""
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name='abandoned_checkouts')
    phone = models.CharField(max_length=15, db_index=True)
    name = models.CharField(max_length=150, blank=True, default='')
    address = models.CharField(max_length=500, blank=True, default='')
    cart = models.JSONField(default=list)        # [{'key', 'name', 'price', 'qty'}]
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    recovered_order = models.ForeignKey(Order, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    contacted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        ordering = ['-updated_at']


class ProductReview(models.Model):
    """কাস্টমারের রিভিউ: সেলার অনুমোদন দিলে ওয়েবসাইটে দেখায়।"""
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name='reviews')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='reviews')
    name = models.CharField(max_length=80)
    phone = models.CharField(max_length=15, blank=True, default='')
    rating = models.PositiveSmallIntegerField(default=5)
    text = models.TextField(max_length=1000, blank=True, default='')
    image = models.ImageField(upload_to='reviews/', blank=True, null=True)
    verified = models.BooleanField(default=False, help_text='এই নম্বরে এই প্রোডাক্ট ডেলিভারি হয়েছে')
    is_approved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-id']


# ============================================================
# ল্যান্ডিং পেজ: এক প্রোডাক্টের এক পাতার বিক্রির পেজ (store/views_landing.py)
# ============================================================
class LandingPage(models.Model):
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name='landing_pages')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='landing_pages')
    slug = models.SlugField(max_length=60, allow_unicode=True)
    headline = models.CharField(max_length=120)
    subheadline = models.CharField(max_length=200, blank=True, default='')
    bullets = models.TextField(blank=True, default='', help_text='প্রতি লাইনে একটা সুবিধা')
    offer_text = models.CharField(max_length=120, blank=True, default='', help_text='যেমন: আজকের মধ্যে অর্ডারে ফ্রি ডেলিভারি')
    cta_text = models.CharField(max_length=40, default='এখনই অর্ডার করুন')
    show_reviews = models.BooleanField(default=True)
    show_stock = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    views = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-id']
        constraints = [models.UniqueConstraint(fields=['shop', 'slug'], name='unique_landing_slug_per_shop')]

    @property
    def bullet_list(self):
        return [line.strip() for line in self.bullets.splitlines() if line.strip()]

    def __str__(self):
        return self.headline


# ============================================================
# Master HQ — কে কখন কী করলো (store/hq.py log_action)
# ============================================================
class HQAuditLog(models.Model):
    ACTION_LABELS = {
        'extend': 'মেয়াদ বাড়ানো',
        'trial': 'ট্রায়াল বাড়ানো',
        'set_plan': 'প্যাকেজ বদল',
        'set_date': 'মেয়াদের তারিখ বদল',
        'lock': 'লক করা',
        'unlock': 'লক খোলা',
        'suspend': 'দোকান বন্ধ',
        'unsuspend': 'দোকান আবার চালু',
        'sms': 'SMS ব্যালেন্স বদল',
        'sms_toggle': 'SMS চালু/বন্ধ',
        'password': 'পাসওয়ার্ড রিসেট',
        'owner_fix': 'মালিক ঠিক করা',
        'user_active': 'লগইন চালু/বন্ধ',
        'login_as': 'অ্যাকাউন্টে ঢোকা',
        'note': 'নোট লেখা',
        'domain_live': 'ডোমেইন চালু',
        'delete': 'দোকান মুছে ফেলা',
        'payment_recheck': 'পেমেন্ট আবার যাচাই',
        'payment_manual': 'পেমেন্ট হাতে সম্পন্ন',
        'payment_legacy': 'পুরনো পেমেন্ট অনুমোদন/বাতিল',
        'notice': 'প্ল্যাটফর্ম নোটিশ',
        'broadcast': 'সেলারদের SMS',
        'settings': 'সিস্টেম সেটিংস',
    }

    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                              related_name='+')
    actor_label = models.CharField(max_length=64, blank=True, default='')
    action = models.CharField(max_length=40, db_index=True)
    shop = models.ForeignKey(Shop, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    shop_label = models.CharField(max_length=200, blank=True, default='')
    detail = models.TextField(blank=True, default='')
    ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']

    @property
    def action_label(self):
        return self.ACTION_LABELS.get(self.action, self.action)

    def __str__(self):
        return f'{self.action_label} — {self.shop_label}'


# ============================================================
# সব সেলারের ড্যাশবোর্ডে দেখানো নোটিশ (Master HQ থেকে)
# ============================================================
class PlatformNotice(models.Model):
    LEVEL_CHOICES = (('info', 'তথ্য'), ('success', 'সুখবর'), ('warning', 'সতর্কতা'), ('danger', 'জরুরি'))
    AUDIENCE_CHOICES = (('all', 'সব সেলার'), ('trial', 'শুধু ট্রায়ালে যারা'), ('paid', 'শুধু পেইড সেলার'),
                        ('locked', 'যাদের মেয়াদ শেষ'))

    title = models.CharField(max_length=120)
    body = models.TextField(blank=True, default='')
    level = models.CharField(max_length=10, choices=LEVEL_CHOICES, default='info')
    audience = models.CharField(max_length=10, choices=AUDIENCE_CHOICES, default='all')
    link_url = models.CharField(max_length=300, blank=True, default='')
    link_text = models.CharField(max_length=40, blank=True, default='')
    starts_at = models.DateTimeField(default=timezone.now)
    ends_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title


# ============================================================
# সাপ্তাহিক "ব্যাকআপ থেকে ফেরত আনা" পরীক্ষার ফল (scripts/backup_restore_check.py, GitHub Actions থেকে লেখে)
# ============================================================
class BackupCheck(models.Model):
    checked_at = models.DateTimeField(db_index=True)
    backup_key = models.CharField(max_length=200, blank=True, default='')
    backup_date = models.DateField(null=True, blank=True)
    ok = models.BooleanField(default=False)
    restore_seconds = models.IntegerField(null=True, blank=True)
    counts = models.JSONField(default=dict, blank=True)
    problems = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-checked_at']

    def __str__(self):
        return f"{self.checked_at:%Y-%m-%d} {'ok' if self.ok else 'failed'}"
