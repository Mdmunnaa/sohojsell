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
class ShopSettingsForm(forms.ModelForm):
    """Settings পেইজ: কুরিয়ার আর SMS। দোকান আর ওয়েবসাইটের সব তথ্য এখন website_forms.py-তে।"""
    # Pathao কানেক্ট করার সময় একবারই লাগে; সেভ হয় না
    pathao_email = forms.CharField(required=False, max_length=150, widget=forms.EmailInput(
        attrs={'class': 'form-control', 'placeholder': 'Pathao মার্চেন্ট অ্যাকাউন্টের ইমেইল', 'autocomplete': 'off'}))
    pathao_password = forms.CharField(required=False, max_length=150, strip=False, widget=forms.PasswordInput(
        attrs={'class': 'form-control', 'placeholder': 'Pathao পাসওয়ার্ড (সেভ হয় না)', 'autocomplete': 'new-password'}))

    # এগুলো পেইজে দেখানো হয় না; ফাঁকা রেখে সেভ করলে আগেরটাই থাকে
    SECRET_FIELDS = ('steadfast_secret_key', 'pathao_client_secret', 'redx_access_token')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in self.SECRET_FIELDS:
            if self.instance and getattr(self.instance, name, None):
                self.fields[name].widget.attrs['placeholder'] = '•••••••• সেভ করা আছে (বদলাতে নতুনটা দিন)'
        stores = (self.instance.pathao_stores or []) if self.instance and self.instance.pk else []
        if stores:
            self.fields['pathao_store_id'].widget = forms.Select(
                attrs={'class': 'form-select'},
                choices=[(str(st['id']), f"{st['name']} (#{st['id']})") for st in stores])

    def _keep_secret(self, name):
        value = (self.cleaned_data.get(name) or '').strip()
        return value or getattr(self.instance, name, None) or ('' if name == 'pathao_client_secret' else None)

    def clean_steadfast_secret_key(self):
        return self._keep_secret('steadfast_secret_key')

    def clean_pathao_client_secret(self):
        return self._keep_secret('pathao_client_secret')

    def clean_redx_access_token(self):
        return self._keep_secret('redx_access_token')

    def clean(self):
        data = super().clean()
        if data.get('pathao_password') and not data.get('pathao_email'):
            self.add_error('pathao_email', 'Pathao কানেক্ট করতে ইমেইলও দিন।')
        return data

    class Meta:
        model = Shop
        fields = ['steadfast_api_key', 'steadfast_secret_key',
                  'pathao_client_id', 'pathao_client_secret', 'pathao_store_id', 'redx_access_token',
                  'is_sms_active']
        widgets = {
            'steadfast_api_key': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Steadfast API Key'}),
            'steadfast_secret_key': forms.PasswordInput(
                attrs={'class': 'form-control', 'placeholder': 'Steadfast Secret Key', 'autocomplete': 'new-password'}),
            'pathao_client_id': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Client ID', 'autocomplete': 'off'}),
            'pathao_client_secret': forms.PasswordInput(
                attrs={'class': 'form-control', 'placeholder': 'Client Secret', 'autocomplete': 'new-password'}),
            'pathao_store_id': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'কানেক্ট করলে নিজে থেকে আসবে'}),
            'redx_access_token': forms.PasswordInput(
                attrs={'class': 'form-control', 'placeholder': 'RedX API Access Token', 'autocomplete': 'new-password'}),
            'is_sms_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


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