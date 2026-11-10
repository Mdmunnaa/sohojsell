# store/website_forms.py
"""
"ওয়েবসাইট" পেইজের ফর্মগুলো (Edumi-র ওয়েবসাইট সেটিংসের মতো ট্যাবে ভাগ করা)।
প্রতিটা ট্যাব আলাদা ফর্ম, তাই এক ট্যাব সেভ করলে অন্য ট্যাবের কিছু বদলায় না।
"""
import re
from decimal import Decimal

from django import forms
from django.conf import settings

from .models import Banner, Category, DeliveryZone, Shop

TEXT = {'class': 'form-control'}


class StoreProfileForm(forms.ModelForm):
    """দোকানের তথ্য: নাম, ফোন, ঠিকানা, লোগো, ওয়েবসাইটের ঠিকানা (সাবডোমেইন) আর নিজের ডোমেইন।"""
    subdomain = forms.CharField(
        max_length=40,
        widget=forms.TextInput(attrs={'class': 'form-control text-end fw-semibold', 'autocomplete': 'off',
                                      'autocapitalize': 'off', 'spellcheck': 'false', 'id': 'id_subdomain'}),
    )

    class Meta:
        model = Shop
        fields = ['name', 'phone', 'address', 'logo', 'custom_domain']
        widgets = {
            'name': forms.TextInput(attrs=TEXT),
            'phone': forms.TextInput(attrs={**TEXT, 'placeholder': '01XXXXXXXXX', 'inputmode': 'tel'}),
            'address': forms.Textarea(attrs={**TEXT, 'rows': 2, 'placeholder': 'দোকানের ঠিকানা (ইনভয়েস আর ওয়েবসাইটে দেখাবে)'}),
            'logo': forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
            'custom_domain': forms.TextInput(attrs={**TEXT, 'placeholder': 'www.yourshop.com'}),
        }
        labels = {'name': 'দোকানের নাম', 'phone': 'মোবাইল নম্বর', 'address': 'ঠিকানা', 'logo': 'লোগো',
                  'custom_domain': 'নিজের ডোমেইন'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].error_messages['required'] = 'দোকানের নাম দিন।'
        self.fields['subdomain'].error_messages['required'] = 'ওয়েবসাইটের ঠিকানা দিন।'
        if self.instance and self.instance.pk:
            self.fields['subdomain'].initial = self.instance.slug
        # নিজের ডোমেইন শুধু Premium-এ; অন্য প্যাকেজে ফিল্ডটাই থাকে না
        from .plans import has_custom_domain
        if self.instance and self.instance.pk and not has_custom_domain(self.instance):
            self.fields.pop('custom_domain', None)

    def clean_subdomain(self):
        from .subdomains import normalize, validate_subdomain
        value = normalize(self.cleaned_data['subdomain'])
        if self.instance and value == self.instance.slug:
            return value
        return validate_subdomain(value, exclude_shop_id=self.instance.pk if self.instance else None)

    def clean_custom_domain(self):
        # https://, শেষের / বা পথ লিখে ফেললেও শুধু ডোমেইনটা রাখা হয়
        value = (self.cleaned_data.get('custom_domain') or '').strip().lower()
        if not value:
            return None
        value = re.sub(r'^https?://', '', value).split('/')[0].split(':')[0].strip('.')
        if not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}', value):
            raise forms.ValidationError('ডোমেইন ঠিকমতো লিখুন, যেমন www.yourshop.com')
        base = getattr(settings, 'STORE_BASE_DOMAIN', '') or 'sellpunch.com'
        if value == base or value.endswith('.' + base):
            raise forms.ValidationError('এটা নিজের ডোমেইন না; আপনার সাবডোমেইন উপরে আলাদা করে দেওয়া আছে।')
        return value

    def save(self, commit=True):
        self.instance.slug = self.cleaned_data['subdomain']
        return super().save(commit=commit)


class StoreDesignForm(forms.ModelForm):
    class Meta:
        model = Shop
        fields = ['storefront_design', 'storefront_theme', 'storefront_color', 'storefront_tagline',
                  'announcement_text', 'show_sold_count']
        widgets = {
            'storefront_design': forms.RadioSelect,
            'storefront_theme': forms.RadioSelect,
            'storefront_color': forms.TextInput,
            'storefront_tagline': forms.TextInput(attrs={**TEXT, 'placeholder': 'যেমন: খাঁটি সুতির শাড়ি, সারা দেশে ডেলিভারি'}),
            'announcement_text': forms.TextInput(attrs={**TEXT, 'placeholder': 'যেমন: ঈদ উপলক্ষে ১০০০ টাকার বেশি অর্ডারে ডেলিভারি ফ্রি'}),
            'show_sold_count': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['storefront_theme'].required = False
        self.fields['storefront_design'].required = False
        self.fields['storefront_color'].required = False

    def clean_storefront_theme(self):
        from .themes import DEFAULT_THEME
        return self.cleaned_data.get('storefront_theme') or self.instance.storefront_theme or DEFAULT_THEME

    def clean_storefront_design(self):
        from .themes import DEFAULT_DESIGN, DESIGNS
        value = self.cleaned_data.get('storefront_design')
        return value if value in DESIGNS else (self.instance.storefront_design or DEFAULT_DESIGN)

    def clean_storefront_color(self):
        """'custom' রঙ বাছলে তবেই নিজের রঙ থাকে; নাহলে ফাঁকা (থিমের রঙ)।"""
        from .themes import clean_hex
        if self.data.get('color_mode') != 'custom':
            return ''
        value = clean_hex(self.cleaned_data.get('storefront_color'))
        if not value:
            raise forms.ValidationError('রঙটা ঠিকমতো দিন, যেমন #1E88E5')
        return value

    def save(self, commit=True):
        # ফর্মে রঙের ঘর না এলেও (থিমের রঙে ফেরা) নিজের রঙটা মুছতে হবে; ModelForm ডিফল্টওয়ালা ফিল্ড বাদ দেয়
        self.instance.storefront_color = self.cleaned_data.get('storefront_color', '')
        return super().save(commit=commit)


class StoreContactForm(forms.ModelForm):
    """পলিসি আর সোশ্যাল লিংক।"""
    class Meta:
        model = Shop
        fields = ['whatsapp_number', 'facebook_page_url', 'instagram_link', 'youtube_link',
                  'return_policy', 'privacy_policy']
        widgets = {
            'whatsapp_number': forms.TextInput(attrs={**TEXT, 'placeholder': '01XXXXXXXXX', 'inputmode': 'tel'}),
            'facebook_page_url': forms.URLInput(attrs={**TEXT, 'placeholder': 'https://facebook.com/yourpage'}),
            'instagram_link': forms.URLInput(attrs={**TEXT, 'placeholder': 'https://instagram.com/yourshop'}),
            'youtube_link': forms.URLInput(attrs={**TEXT, 'placeholder': 'https://youtube.com/@yourshop'}),
            'return_policy': forms.Textarea(attrs={**TEXT, 'rows': 4, 'placeholder': 'যেমন: প্রোডাক্টে সমস্যা থাকলে ৩ দিনের মধ্যে বদলে দেওয়া হয়...'}),
            'privacy_policy': forms.Textarea(attrs={**TEXT, 'rows': 4, 'placeholder': 'কাস্টমারের তথ্য কীভাবে রাখেন...'}),
        }

    def clean_whatsapp_number(self):
        """wa.me লিংকের জন্য 8801XXXXXXXXX রূপে রাখা হয়।"""
        raw = (self.cleaned_data.get('whatsapp_number') or '').strip()
        if not raw:
            return ''
        from accounts.forms import normalize_bd_mobile
        local = normalize_bd_mobile(raw)
        if not local:
            raise forms.ValidationError('বাংলাদেশি মোবাইল নম্বর দিন, যেমন 01712345678')
        return '88' + local


class DeliverySettingsForm(forms.ModelForm):
    class Meta:
        model = Shop
        fields = ['free_delivery_min']
        widgets = {'free_delivery_min': forms.NumberInput(attrs={**TEXT, 'placeholder': 'যেমন 2000 (খালি = কখনো ফ্রি না)', 'min': '0'})}

    def clean_free_delivery_min(self):
        value = self.cleaned_data.get('free_delivery_min')
        if value is not None and value <= 0:
            return None
        return value


class DeliveryZoneForm(forms.ModelForm):
    class Meta:
        model = DeliveryZone
        fields = ['name', 'charge', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={**TEXT, 'placeholder': 'যেমন: সাভার'}),
            'charge': forms.NumberInput(attrs={**TEXT, 'min': '0', 'step': '1', 'placeholder': '৳'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def clean_charge(self):
        value = self.cleaned_data.get('charge')
        if value is None or value < 0:
            raise forms.ValidationError('চার্জ ০ বা তার বেশি দিন।')
        if value > Decimal('5000'):
            raise forms.ValidationError('চার্জ খুব বেশি মনে হচ্ছে।')
        return value


class PaymentSettingsForm(forms.ModelForm):
    """
    Edumi-র Quick Pay-এর মতো একটা সুইচ: বন্ধ = শুধু ক্যাশ অন ডেলিভারি; চালু = কাস্টমার অনলাইনে টাকা দিতে পারবে
    (কীভাবে, সেটা নিচের তিনটা নিয়মের একটা)। সুইচের অবস্থা payment_rule-এই থাকে: 'cod' মানে বন্ধ।
    """
    ONLINE_RULES = [(value, label) for value, label in Shop.PAYMENT_RULE_CHOICES if value != Shop.PAYMENT_COD]

    online_enabled = forms.BooleanField(required=False, widget=forms.CheckboxInput(
        attrs={'class': 'form-check-input', 'role': 'switch'}))
    payment_rule = forms.ChoiceField(choices=ONLINE_RULES, required=False, widget=forms.RadioSelect)

    class Meta:
        model = Shop
        fields = ['payment_rule', 'payout_method', 'payout_account', 'payout_account_name']
        widgets = {
            'payout_method': forms.Select(attrs={'class': 'form-select'}),
            'payout_account': forms.TextInput(attrs={**TEXT, 'placeholder': 'bKash/Nagad নম্বর, বা ব্যাংকের নাম, শাখা আর অ্যাকাউন্ট নম্বর'}),
            'payout_account_name': forms.TextInput(attrs={**TEXT, 'placeholder': 'যার নামে অ্যাকাউন্ট'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        online = self.instance.payment_rule != Shop.PAYMENT_COD
        self.fields['online_enabled'].initial = online
        self.initial['payment_rule'] = self.instance.payment_rule if online else Shop.PAYMENT_COD_OR_ONLINE

    def clean(self):
        data = super().clean()
        if not data.get('online_enabled'):
            data['payment_rule'] = Shop.PAYMENT_COD
            return data
        if data.get('payment_rule') not in dict(self.ONLINE_RULES):
            data['payment_rule'] = Shop.PAYMENT_COD_OR_ONLINE
        if not (data.get('payout_method') and (data.get('payout_account') or '').strip()):
            self.add_error('payout_account', 'অনলাইনে টাকা নিতে চাইলে টাকা পাঠানোর নম্বর বা অ্যাকাউন্ট দিন।')
        return data


class BannerUploadForm(forms.ModelForm):
    class Meta:
        model = Banner
        fields = ['image', 'title']
        widgets = {
            'image': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
            'title': forms.TextInput(attrs={**TEXT, 'placeholder': 'ছবির বর্ণনা (ঐচ্ছিক)'}),
        }

    def clean_image(self):
        image = self.cleaned_data.get('image')
        if image and image.size > 3 * 1024 * 1024:
            raise forms.ValidationError('ছবি ৩ MB-এর ছোট হতে হবে।')
        return image


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ['name']
        widgets = {'name': forms.TextInput(attrs={**TEXT, 'placeholder': 'যেমন: শাড়ি', 'maxlength': '100'})}

    def clean_name(self):
        name = ' '.join((self.cleaned_data.get('name') or '').split())
        if not name:
            raise forms.ValidationError('ক্যাটাগরির নাম দিন।')
        return name
