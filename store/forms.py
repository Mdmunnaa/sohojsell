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
        fields = ['name', 'category', 'description', 'cost_price', 'price', 'stock_quantity', 'is_active', 'image']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Product name'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            # Description এর জন্য টেক্সট এরিয়া
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Write product details here...'}),
            'cost_price': forms.NumberInput(attrs={'class': 'form-control'}),
            'price': forms.NumberInput(attrs={'class': 'form-control'}),
            'stock_quantity': forms.NumberInput(attrs={'class': 'form-control'}),
            'image': forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
        }

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
# Settings Page এর ফর্ম
# Settings Page এর ফর্ম
class ShopSettingsForm(forms.ModelForm):
    class Meta:
        model = Shop
        # fields লিস্টে নতুন ফিল্ডগুলো যুক্ত করা হয়েছে
        fields = ['name', 'phone', 'address', 'facebook_page_url', 'instagram_link', 'youtube_link',
                  'privacy_policy', 'return_policy', 'logo', 'custom_domain',
                  'steadfast_api_key', 'steadfast_secret_key',
                  'pathao_store_id', 'pathao_access_token', 'redx_access_token',
                  'is_sms_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 017XXXXXXXX'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),

            # Social Links
            'facebook_page_url': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'Facebook Page URL'}),
            'instagram_link': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'Instagram URL'}),
            'youtube_link': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'YouTube Channel URL'}),

            # Policies
            'privacy_policy': forms.Textarea(
                attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'এখানে আপনার Privacy Policy লিখুন...'}),
            'return_policy': forms.Textarea(attrs={'class': 'form-control', 'rows': 4,
                                                   'placeholder': 'এখানে আপনার Return & Refund Policy লিখুন...'}),

            'logo': forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
            'custom_domain': forms.TextInput(attrs={'class': 'form-control'}),
            'steadfast_api_key': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Steadfast API Key'}),
            'steadfast_secret_key': forms.PasswordInput(
                attrs={'class': 'form-control', 'placeholder': 'Steadfast Secret Key', 'render_value': True}),
            'pathao_store_id': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Pathao Store ID'}),
            'pathao_access_token': forms.PasswordInput(
                attrs={'class': 'form-control', 'placeholder': 'Pathao Access Token', 'render_value': True}),
            'redx_access_token': forms.PasswordInput(
                attrs={'class': 'form-control', 'placeholder': 'RedX Access Token', 'render_value': True}),
            'is_sms_active': forms.CheckboxInput(attrs={'class': 'form-check-input'})
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