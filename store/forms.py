import re
from decimal import Decimal

from django import forms
from . import units
from .models import Shop, Product

class ShopSetupForm(forms.ModelForm):
    class Meta:
        model = Shop
        # সেলারের কাছ থেকে শুধু এই দুটো তথ্য নেব
        fields = ['name', 'facebook_page_url']

# প্রোডাক্ট অ্যাড করার ফর্ম
BN_DIGITS = str.maketrans('০১২৩৪৫৬৭৮৯', '0123456789')
MAX_EXTRA_BARCODES = 50


class ProductForm(forms.ModelForm):
    """প্রোডাক্ট যোগ আর এডিট — একই ফর্ম (store/templates/store/product_form.html)।"""
    extra_barcodes = forms.CharField(
        required=False, label='আরও বারকোড',
        widget=forms.Textarea(attrs={'rows': 3, 'autocomplete': 'off', 'spellcheck': 'false',
                                     'placeholder': 'প্রতি লাইনে একটা বারকোড'}))

    class Meta:
        model = Product
        fields = ['name', 'category', 'description', 'cost_price', 'price', 'compare_price', 'unit',
                  'stock_quantity', 'low_stock_at', 'barcode', 'is_active', 'image']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'যেমন: চিনি, বা ছেলেদের পোলো শার্ট', 'autocomplete': 'off'}),
            'description': forms.Textarea(attrs={'rows': 3, 'placeholder': 'ওয়েবসাইটে কাস্টমার যা দেখবেন: মাপ, কাপড়, ওজন, ওয়ারেন্টি…'}),
            'cost_price': forms.NumberInput(attrs={'step': 'any', 'min': '0', 'inputmode': 'decimal', 'placeholder': '0'}),
            'price': forms.NumberInput(attrs={'step': 'any', 'min': '0', 'inputmode': 'decimal', 'placeholder': '0'}),
            'compare_price': forms.NumberInput(attrs={'step': 'any', 'min': '0', 'inputmode': 'decimal', 'placeholder': 'ফাঁকা রাখা যায়'}),
            'unit': forms.RadioSelect,
            'stock_quantity': forms.NumberInput(attrs={'step': 'any', 'min': '0', 'inputmode': 'decimal', 'placeholder': '0'}),
            'low_stock_at': forms.NumberInput(attrs={'step': 'any', 'min': '0', 'inputmode': 'decimal'}),
            'image': forms.ClearableFileInput(attrs={'accept': 'image/*'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'}),
            'barcode': forms.TextInput(attrs={'autocomplete': 'off', 'spellcheck': 'false',
                                              'placeholder': 'স্ক্যান করুন, লিখুন, বা ফাঁকা রাখুন'}),
        }

    def __init__(self, *args, shop=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.shop = shop or getattr(self.instance, 'shop', None)
        # শুধু নিজের দোকানের ক্যাটাগরি, শুধু নাম। আগে সব দোকানের সব ক্যাটাগরি ("নাম - অন্য দোকান") আসত, আর প্রতিটার
        # জন্য একটা করে ডাটাবেস প্রশ্ন — দোকান বাড়লে প্রোডাক্ট যোগ/এডিটের পাতা ধীর হতো।
        from .models import Category
        category = self.fields['category']
        category.queryset = (Category.objects.filter(shop=self.shop).order_by('name') if self.shop is not None
                             else Category.objects.none())
        category.label_from_instance = lambda obj: obj.name
        category.empty_label = 'ক্যাটাগরি ছাড়া'
        self.fields['unit'].choices = list(units.UNITS)
        self.fields['unit'].required = False          # না পাঠালে (পুরোনো ফর্ম/ইমপোর্ট) আগের মতো পিস
        self.fields['low_stock_at'].required = False
        self.fields['stock_quantity'].required = False
        self.fields['cost_price'].required = False      # ফাঁকা = ০ (লাভের হিসাবে পরে দেওয়া যায়)
        if not self.instance.pk and not self.is_bound:
            self.initial.setdefault('cost_price', '')
            self.initial.setdefault('stock_quantity', '')
        if self.instance.pk and not self.is_bound:
            self.initial['extra_barcodes'] = '\n'.join(
                self.instance.extra_barcodes.filter(variant__isnull=True).values_list('code', flat=True))

    def _code_owner(self, code):
        """এই দোকানে কোডটা অন্য কোন প্রোডাক্ট/সাইজে আছে (নিজেরটা বাদে) — বার্তার জন্য নাম, নাহলে None।"""
        if self.shop is None:
            return None
        from .models import Product, ProductBarcode, ProductVariant
        same = Product.objects.filter(shop=self.shop, barcode=code).exclude(pk=self.instance.pk).first()
        if same:
            return f'"{same.name}"'
        variant = (ProductVariant.objects.filter(product__shop=self.shop, barcode=code)
                   .exclude(product_id=self.instance.pk).select_related('product').first())
        if variant:
            return f'"{variant.product.name}" ({variant.name})'
        extra = (ProductBarcode.objects.filter(shop=self.shop, code=code).exclude(product_id=self.instance.pk)
                 .select_related('product').first())
        if extra:
            return f'"{extra.product.name}"'
        return None

    def clean_barcode(self):
        code = (self.cleaned_data.get('barcode') or '').strip().translate(BN_DIGITS)
        if not code:
            return None                      # ফাঁকা থাকলে Product.save() নিজে একটা বানায়
        owner = self._code_owner(code)
        if owner:
            raise forms.ValidationError(f'এই বারকোড আগে থেকেই {owner} প্রোডাক্টে আছে।')
        return code

    def clean_extra_barcodes(self):
        raw = (self.cleaned_data.get('extra_barcodes') or '').translate(BN_DIGITS)
        codes = []
        for code in re.split(r'[\s,;]+', raw):
            code = code.strip()
            if code and code not in codes:
                codes.append(code)
        if len(codes) > MAX_EXTRA_BARCODES:
            raise forms.ValidationError(f'এক প্রোডাক্টে সর্বোচ্চ {MAX_EXTRA_BARCODES}টা বাড়তি বারকোড রাখা যায়।')
        for code in codes:
            if len(code) > 50:
                raise forms.ValidationError(f'"{code[:20]}…" বারকোডটা অনেক লম্বা (৫০ অক্ষরের বেশি)।')
            if self.instance.pk:
                from .models import ProductVariant
                variant = ProductVariant.objects.filter(product=self.instance, barcode=code).first()
                if variant:
                    raise forms.ValidationError(f'"{code}" এই প্রোডাক্টের "{variant.name}" সাইজ/রংয়ের বারকোড — আলাদা করে দেওয়ার দরকার নেই।')
            owner = self._code_owner(code)
            if owner:
                raise forms.ValidationError(f'"{code}" বারকোড আগে থেকেই {owner} প্রোডাক্টে আছে।')
        return codes

    def _qty(self, name, unit, label):
        value = self.cleaned_data.get(name)
        if value is None:
            return 0
        try:
            return units.parse(value, unit, label=label, allow_zero=True)
        except units.QtyError as exc:
            self.add_error(name, str(exc))
            return value

    def clean(self):
        data = super().clean()
        compare, price = data.get('compare_price'), data.get('price')
        if compare is not None and price is not None and compare <= price:
            self.add_error('compare_price', 'আগের দাম বিক্রির দামের চেয়ে বেশি হতে হবে, নইলে ফাঁকা রাখুন।')
        if 'cost_price' in data and data['cost_price'] is None:
            data['cost_price'] = Decimal('0')
        unit = data.get('unit') or getattr(self.instance, 'unit', None) or units.PCS
        if not data.get('unit'):
            data['unit'] = unit
        if 'stock_quantity' in data:
            data['stock_quantity'] = self._qty('stock_quantity', unit, 'স্টক')
        if 'low_stock_at' in data:
            data['low_stock_at'] = self._qty('low_stock_at', unit, 'সতর্ক করার পরিমাণ')
        main = data.get('barcode')
        if main and main in (data.get('extra_barcodes') or []):
            data['extra_barcodes'].remove(main)              # মূল বারকোডটাই আবার লিখলে চুপচাপ বাদ
        return data

    def save_extra_barcodes(self, product):
        """বাড়তি বারকোড (সাইজ/রং ছাড়া) ফর্মের তালিকার সাথে মেলায়।"""
        from .models import ProductBarcode
        codes = self.cleaned_data.get('extra_barcodes') or []
        product.extra_barcodes.filter(variant__isnull=True).exclude(code__in=codes).delete()
        have = set(product.extra_barcodes.values_list('code', flat=True))
        ProductBarcode.objects.bulk_create([ProductBarcode(shop=product.shop, product=product, code=code)
                                            for code in codes if code not in have])


class OrderCreateForm(forms.Form):
    customer_name = forms.CharField(
        max_length=150, label='Customer Name',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Rahim Uddin'})
    )
    customer_phone = forms.CharField(
        max_length=15, label='Phone Number',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 017XXXXXXXX'})
    )
    customer_address = forms.CharField(
        label='Address',
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Enter full address here...'})
    )

    product = forms.ModelChoiceField(
        queryset=Product.objects.none(), label='Select Product',
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    selling_price = forms.DecimalField(
        max_digits=10, decimal_places=2, label='Selling Price (৳)',
        widget=forms.NumberInput(attrs={'class': 'form-control'})
    )
    quantity = forms.IntegerField(
        min_value=1, initial=1, label='Quantity',
        widget=forms.NumberInput(attrs={'class': 'form-control'})
    )

    delivery_charge = forms.DecimalField(
        max_digits=10, decimal_places=2, initial=100.00, label='Delivery Charge (৳)',
        widget=forms.NumberInput(attrs={'class': 'form-control'})
    )
    payment_method = forms.ChoiceField(
        choices=[('COD', 'Cash on Delivery'), ('Paid', 'Full Paid')], label='Payment Method',
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    def __init__(self, *args, **kwargs):
        shop = kwargs.pop('shop', None)
        super().__init__(*args, **kwargs)
        if shop:
            self.fields['product'].queryset = Product.objects.filter(shop=shop, is_active=True, stock_quantity__gt=0)


SAVED_SECRET_PLACEHOLDER = '•••••••• সেভ করা আছে (বদলাতে নতুনটা দিন)'
INPUT = {'class': 'form-control'}


class _CourierForm(forms.ModelForm):
    """
    Settings পেইজের প্রতিটা কুরিয়ার আলাদা ফর্ম, তাই একটা সেভ করলে অন্যটার কিছু বদলায় না।
    গোপন চাবিগুলো পেইজে দেখানো হয় না; ফাঁকা রেখে সেভ করলে আগেরটাই থাকে।
    """
    SECRET_FIELDS = ('steadfast_secret_key', 'pathao_client_secret', 'redx_access_token')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in self.SECRET_FIELDS:
            if name in self.fields and getattr(self.instance, name, None):
                self.fields[name].widget.attrs['placeholder'] = SAVED_SECRET_PLACEHOLDER

    def _keep_secret(self, name):
        value = (self.cleaned_data.get(name) or '').strip()
        return value or getattr(self.instance, name, None) or ('' if name == 'pathao_client_secret' else None)

    def clean_steadfast_secret_key(self):
        return self._keep_secret('steadfast_secret_key')

    def clean_pathao_client_secret(self):
        return self._keep_secret('pathao_client_secret')

    def clean_redx_access_token(self):
        return self._keep_secret('redx_access_token')


class SteadfastSettingsForm(_CourierForm):
    def clean(self):
        data = super().clean()
        if not (data.get('steadfast_api_key') or '').strip():
            self.add_error('steadfast_api_key', 'Steadfast-এর API Key দিন।')
        if not data.get('steadfast_secret_key'):
            self.add_error('steadfast_secret_key', 'Steadfast-এর Secret Key দিন।')
        return data

    class Meta:
        model = Shop
        fields = ['steadfast_api_key', 'steadfast_secret_key']
        widgets = {
            'steadfast_api_key': forms.TextInput(attrs={**INPUT, 'placeholder': 'API Key', 'autocomplete': 'off',
                                                        'spellcheck': 'false'}),
            'steadfast_secret_key': forms.PasswordInput(attrs={**INPUT, 'placeholder': 'Secret Key',
                                                               'autocomplete': 'new-password'}),
        }


class PathaoSettingsForm(_CourierForm):
    """
    কানেক্ট করার আগে: Client ID, Client Secret, ইমেইল আর পাসওয়ার্ড (পাসওয়ার্ড সেভ হয় না)।
    কানেক্ট হওয়ার পরে: শুধু কোন স্টোর থেকে পার্সেল যাবে।
    """
    pathao_email = forms.CharField(required=False, max_length=150, widget=forms.EmailInput(
        attrs={**INPUT, 'placeholder': 'Pathao-তে লগইনের ইমেইল', 'autocomplete': 'off'}))
    pathao_password = forms.CharField(required=False, max_length=150, strip=False, widget=forms.PasswordInput(
        attrs={**INPUT, 'placeholder': 'Pathao পাসওয়ার্ড', 'autocomplete': 'new-password'}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.connected = bool(self.instance and self.instance.pathao_access_token)
        if self.connected:
            for name in ('pathao_client_id', 'pathao_client_secret', 'pathao_email', 'pathao_password'):
                self.fields.pop(name)
            stores = self.instance.pathao_stores or []
            if stores:
                self.fields['pathao_store_id'].widget = forms.Select(
                    attrs={'class': 'form-select'},
                    choices=[(str(st['id']), f"{st['name']} (#{st['id']})") for st in stores])
        else:
            self.fields.pop('pathao_store_id')

    def clean(self):
        data = super().clean()
        if self.connected:
            if not data.get('pathao_store_id'):
                self.add_error('pathao_store_id', 'কোন স্টোর থেকে পার্সেল যাবে বেছে নিন।')
            return data
        required = {'pathao_client_id': 'Client ID দিন।', 'pathao_client_secret': 'Client Secret দিন।',
                    'pathao_email': 'Pathao-তে লগইনের ইমেইল দিন।', 'pathao_password': 'Pathao-র পাসওয়ার্ড দিন।'}
        for name, message in required.items():
            if not (data.get(name) or '').strip():
                self.add_error(name, message)
        return data

    class Meta:
        model = Shop
        fields = ['pathao_client_id', 'pathao_client_secret', 'pathao_store_id']
        widgets = {
            'pathao_client_id': forms.TextInput(attrs={**INPUT, 'placeholder': 'Client ID', 'autocomplete': 'off',
                                                       'spellcheck': 'false'}),
            'pathao_client_secret': forms.PasswordInput(attrs={**INPUT, 'placeholder': 'Client Secret',
                                                               'autocomplete': 'new-password'}),
            'pathao_store_id': forms.TextInput(attrs={**INPUT, 'placeholder': 'স্টোর আইডি'}),
        }


class RedxSettingsForm(_CourierForm):
    def clean(self):
        data = super().clean()
        if not data.get('redx_access_token'):
            self.add_error('redx_access_token', 'RedX-এর API Access Token দিন।')
        return data

    class Meta:
        model = Shop
        fields = ['redx_access_token']
        widgets = {
            'redx_access_token': forms.PasswordInput(attrs={**INPUT, 'placeholder': 'API Access Token',
                                                            'autocomplete': 'new-password'}),
        }


class PosSettingsForm(forms.ModelForm):
    """POS-এর VAT আর রসিদের সেটিং।"""
    class Meta:
        model = Shop
        fields = ['pos_vat_percent', 'pos_vat_mode', 'pos_bin', 'pos_receipt_width', 'pos_receipt_note', 'pos_auto_print']
        widgets = {
            'pos_vat_percent': forms.NumberInput(attrs={**INPUT, 'min': '0', 'max': '100', 'step': '0.01', 'placeholder': '০'}),
            'pos_vat_mode': forms.RadioSelect,
            'pos_bin': forms.TextInput(attrs={**INPUT, 'placeholder': 'যেমন 000123456-0101', 'autocomplete': 'off'}),
            'pos_receipt_width': forms.RadioSelect,
            'pos_receipt_note': forms.TextInput(attrs={**INPUT, 'placeholder': 'যেমন: ক্যাশ মেমো ছাড়া পণ্য ফেরত নেওয়া হয় না'}),
            'pos_auto_print': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'}),
        }

    def clean_pos_vat_percent(self):
        value = self.cleaned_data.get('pos_vat_percent') or 0
        if value < 0 or value > 100:
            raise forms.ValidationError('VAT ০ থেকে ১০০%-এর মধ্যে দিন।')
        return value


from .models import Banner

class BannerForm(forms.ModelForm):
    class Meta:
        model = Banner
        fields = ['title', 'image', 'is_active']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Banner Title'}),
            'image': forms.FileInput(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'})
        }