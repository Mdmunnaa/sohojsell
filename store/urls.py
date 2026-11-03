from django.urls import path
from django.views.generic import TemplateView
from . import views
from . import payment_views

urlpatterns = [
    # Landing
    path('', views.landing_page, name='landing_page'),

    # নীতিমালা ও যোগাযোগ (সবার জন্য খোলা — Meta আর PayStation এগুলো দেখতে চায়)
    path('privacy-policy/', TemplateView.as_view(template_name='store/legal/privacy.html'), name='privacy_policy'),
    path('terms/', TemplateView.as_view(template_name='store/legal/terms.html'), name='terms'),
    path('refund-policy/', TemplateView.as_view(template_name='store/legal/refund.html'), name='refund_policy'),
    path('data-deletion/', TemplateView.as_view(template_name='store/legal/data_deletion.html'), name='data_deletion'),
    path('contact/', TemplateView.as_view(template_name='store/legal/contact.html'), name='contact'),

    # Dashboard
    path('dashboard/', views.seller_dashboard, name='dashboard'),
    path('setup-shop/', views.setup_shop, name='setup_shop'),

    # Products
    path('products/', views.product_list, name='product_list'),
    path('products/add/', views.add_product, name='add_product'),
    path('products/edit/<int:pk>/', views.edit_product, name='edit_product'),
    path('products/delete/<int:pk>/', views.delete_product, name='delete_product'),

    # Orders (main)
    path('orders/', views.order_list, name='order_list'),
    path('order/create/', views.order_create, name='order_create'),
    path('order/edit/<int:order_id>/', views.order_edit, name='order_edit'),
    path('order/delete/<int:order_id>/', views.order_delete, name='order_delete'),
    path('order/update-status/', views.update_order_status, name='update_order_status'),

    # Invoice
    path('invoice/<int:order_id>/', views.invoice_view, name='invoice'),

    # Courier
    # আগেরটা মুছে এটা দিন
    path('orders/send-courier/', views.send_to_courier, name='send_to_courier'),
    path('courier/', views.courier_dashboard, name='courier'),

    # POS System
    path('pos/', views.pos_dashboard, name='pos'),
    path('pos/checkout/', views.pos_checkout, name='pos_checkout'),
    path('pos/receipt/<int:order_id>/', views.pos_receipt, name='pos_receipt'),

    # Customers & Reports
    path('customers/', views.customer_list, name='customer_list'),
    path('reports/', views.business_reports, name='reports'),

    # Settings & Billing
    path('settings/', views.shop_settings, name='settings'),
    path('billing/', views.billing_page, name='billing'),
    path('payment/success/<str:plan_name>/', views.payment_success, name='payment_success'),

    # Storefront Orders (seller dashboard)
    path('online-orders/', views.storefront_orders, name='storefront_orders'),
    path('online-orders/<int:order_id>/status/', views.storefront_order_update_status, name='storefront_order_status'),

    # Master HQ (CEO only)
    path('saas-master/', views.master_dashboard, name='master_dashboard'),
    path('saas-master/shops/', views.manage_shops, name='manage_shops'),  # NEW
    path('saas-master/users/', views.all_users, name='all_users'),  # NEW
    path('saas-master/billing/', views.master_billing, name='master_billing'),  # NEW
    path('saas-master/settings/', views.master_settings, name='master_settings'),
    path('saas-master/recharge-sms/', views.recharge_sms, name='recharge_sms'),

    # Barcode System
    path('pos/barcode-lookup/', views.barcode_lookup, name='barcode_lookup'),
    path('barcodes/', views.barcode_print, name='barcode_print'),

    # Banner Management
    path('banners/', views.banner_list, name='banner_list'),
    path('banners/add/', views.add_banner, name='add_banner'),
    path('banners/delete/<int:pk>/', views.delete_banner, name='delete_banner'),

    # PayStation অনলাইন পেমেন্ট (আগের SSLCommerz পথ সরানো হয়েছে — সেখানে যাচাইয়ের ফাঁক ছিল)
    path('payment/paystation/start/', payment_views.paystation_start, name='paystation_start'),
    path('payment/paystation/callback/', payment_views.paystation_callback, name='paystation_callback'),
    # PayStation-কে IPN URL হিসেবে এটা দিতে হবে: https://<domain>/payment/ipn/
    path('payment/ipn/', payment_views.paystation_ipn, name='paystation_ipn'),

    # Webhooks
    path('api/webhook/steadfast/', views.steadfast_webhook, name='steadfast_webhook'),

    # ============================================================
    # PUBLIC E-COMMERCE STOREFRONT (Customer-facing)
    # ============================================================
    path('shop/<slug:shop_slug>/', views.storefront_home, name='storefront_home'),
    path('shop/<slug:shop_slug>/checkout/', views.storefront_checkout, name='storefront_checkout'),
    path('shop/<slug:shop_slug>/place-order/', views.storefront_place_order, name='storefront_place_order'),
    path('shop/<slug:shop_slug>/order/<int:order_id>/success/', views.storefront_order_success, name='storefront_order_success'),

# Categories
    path('categories/', views.category_list, name='category_list'),
    path('categories/delete/<int:pk>/', views.delete_category, name='delete_category'),
    path('shop/<slug:shop_slug>/product/<int:product_id>/', views.storefront_product_detail, name='storefront_product_detail'),
    path('category/edit/<int:pk>/', views.edit_category, name='edit_category'),

    # Staff Management
    path('staff/', views.staff_list, name='staff_list'),
    path('staff/add/', views.add_edit_staff, name='add_staff'),
    path('staff/edit/<int:staff_id>/', views.add_edit_staff, name='edit_staff'),
# Manual Payment Request
    path('payment/submit-request/', views.submit_payment_request, name='submit_payment_request'),
    path('billing/approve/<int:request_id>/', views.approve_payment, name='approve_payment'),
    path('billing/reject/<int:request_id>/', views.reject_payment, name='reject_payment'),
    path('billing/unlock/<int:shop_id>/', views.manual_unlock, name='manual_unlock'),

    path('products/download-template/', views.download_csv_template, name='download_csv_template'),
    path('products/import-csv/', views.import_bulk_products, name='import_bulk_products'),

    # Facebook Integration (নতুন)
    path('facebook/connect/', views.fb_connect, name='fb_connect'),
    path('facebook/pages/', views.fb_page_select, name='fb_page_select'),
    path('facebook/disconnect/', views.fb_disconnect, name='fb_disconnect'),
]
