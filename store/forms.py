import re

from django import forms
from .models import Shop
from .models import Shop, Product # Product মডেল ইমপোর্ট করা হলো

class ShopSetupForm(forms.ModelForm):
    class Meta:
        model = Shop
        # সেলারের কাছ থেকে শুধু এই দুটো তথ্য নেব
        fields = ['name', 'facebook_page_url']

# প্রোডাক্ট অ্যাড করার ফর্ম
class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        # এখানে 'description' অ্যাড করা হয়েছে
        fields = ['name', 'category', 'description', 'cost_price', 'price', 'compare_price', 'stock_quantity',
                  'is_active', 'image']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Product name'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            # Description এর জন্য টেক্সট এরিয়া
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Write product details here...'}),
            'cost_price': forms.NumberInput(attrs={'class': 'form-control'}),
            'price': forms.NumberInput(attrs={'class': 'form-control'}),
            'compare_price': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'যেমন 1200'}),
            'stock_quantity': forms.NumberInput(attrs={'class': 'form-control'}),
            'image': forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
        }

    def clean(self):
        data = super().clean()
        compare, price = data.get('compare_price'), data.get('price')
        if compare is not None and price is not None and compare <= price:
            self.add_error('compare_price', 'আগের দাম বিক্রির দামের চেয়ে বেশি হতে হবে, নইলে ফাঁকা রাখুন।')
        return data


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


class SmsSettingsForm(forms.ModelForm):
    class Meta:
        model = Shop
        fields = ['is_sms_active']
        widgets = {'is_sms_active': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'})}


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