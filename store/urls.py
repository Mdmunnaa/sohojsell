from django.urls import path
from django.views.generic import TemplateView
from django.views.generic import RedirectView

from . import website_views
from . import views
from . import views_cron
from . import payment_views
from . import views_pos
from . import views_sms
from . import views_ledger
from . import views_offers
from . import views_landing
from . import views_dues
from . import views_demo
from . import hq_views

def favicon(request):
    from django.shortcuts import redirect
    from django.templatetags.static import static
    return redirect(static('brand/favicon.ico'))


urlpatterns = [
    path('favicon.ico', favicon),
    path('site.webmanifest', TemplateView.as_view(template_name='store/site.webmanifest',
                                                  content_type='application/manifest+json'), name='webmanifest'),
    # Landing
    path('', views.landing_page, name='landing_page'),
    path('en/', views.landing_page_en, name='landing_page_en'),
    path('robots.txt', views.site_robots, name='site_robots'),
    path('sitemap.xml', views.site_sitemap, name='site_sitemap'),
    path('internal/cron/daily/', views_cron.cron_daily, name='cron_daily'),   # Cloudflare cron, দিনে একবার
    # লাইভ ডেমো (পাসওয়ার্ড ছাড়া ডেমো দোকানে ঢোকা)
    path('demo/', views_demo.demo_start, name='demo_start'),
    path('demo/shop/', views_demo.demo_store, name='demo_store'),
    path('demo/check/', views_demo.demo_check, name='demo_check'),

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
    path('courier/redx/areas/', views.redx_areas, name='redx_areas'),
    path('courier/', views.courier_dashboard, name='courier'),

    # POS System
    # SMS প্যানেল
    path('sms/', views_sms.sms_panel, name='sms_panel'),
    path('sms/send/', views_sms.sms_send, name='sms_send'),
    path('sms/buy/', views_sms.sms_buy, name='sms_buy'),
    path('sms/auto/', views_sms.sms_auto, name='sms_auto'),
    path('sms/customers/', views_sms.sms_customer_search, name='sms_customer_search'),
    path('master/domains/<int:shop_id>/live/', views.master_domain_live, name='master_domain_live'),
    path('landing/', views_landing.landing_list, name='landing_list'),
    path('landing/new/', views_landing.landing_edit, name='landing_new'),
    path('landing/<int:page_id>/', views_landing.landing_edit, name='landing_edit'),
    path('landing/<int:page_id>/action/', views_landing.landing_action, name='landing_action'),
    path('offers/', views_offers.coupon_list, name='coupon_list'),
    path('offers/<int:coupon_id>/', views_offers.coupon_action, name='coupon_action'),
    path('orders/abandoned/', views_offers.abandoned_list, name='abandoned_list'),
    path('orders/abandoned/<int:draft_id>/', views_offers.abandoned_action, name='abandoned_action'),
    path('reviews/', views_offers.review_list, name='review_list'),
    path('reviews/<int:review_id>/', views_offers.review_action, name='review_action'),
    path('orders/risk/', views.order_risk, name='order_risk'),
    path('customers/<int:customer_id>/block/', views.customer_block, name='customer_block'),
    path('dues/', views_dues.due_list, name='due_list'),
    path('dues/remind/', views_dues.due_remind_all, name='due_remind_all'),
    path('dues/auto/', views_dues.due_auto_setting, name='due_auto_setting'),
    path('dues/<str:phone>/', views_dues.due_detail, name='due_detail'),
    path('purchases/', views_ledger.purchase_list, name='purchase_list'),
    path('purchases/new/', views_ledger.purchase_new, name='purchase_new'),
    path('purchases/<int:purchase_id>/', views_ledger.purchase_detail, name='purchase_detail'),
    path('purchases/<int:purchase_id>/delete/', views_ledger.purchase_delete, name='purchase_delete'),
    path('suppliers/', views_ledger.supplier_list, name='supplier_list'),
    path('suppliers/<int:supplier_id>/', views_ledger.supplier_detail, name='supplier_detail'),
    path('expenses/', views_ledger.expense_list, name='expense_list'),
    path('expenses/<int:expense_id>/delete/', views_ledger.expense_delete, name='expense_delete'),
    path('pos/', views_pos.pos_screen, name='pos'),
    path('pos/checkout/', views_pos.pos_checkout, name='pos_checkout'),
    path('pos/receipt/<int:order_id>/', views_pos.pos_receipt, name='pos_receipt'),
    path('pos/customer/', views_pos.pos_customer, name='pos_customer'),
    path('pos/collect-due/', views_pos.pos_collect_due, name='pos_collect_due'),
    path('pos/sales/', views_pos.pos_sales, name='pos_sales'),
    path('pos/sales/<int:order_id>/', views_pos.pos_sale_detail, name='pos_sale_detail'),
    path('pos/sales/<int:order_id>/return/', views_pos.pos_return, name='pos_return'),
    path('pos/day-close/', views_pos.pos_day_close, name='pos_day_close'),

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
    # Master HQ (store/hq_views.py) — শুধু সুপারইউজার
    path('saas-master/', hq_views.dashboard, name='master_dashboard'),
    path('saas-master/shops/', hq_views.shops, name='manage_shops'),
    path('saas-master/shops/<int:shop_id>/', hq_views.shop_detail, name='hq_shop'),
    path('saas-master/shops/<int:shop_id>/action/', hq_views.shop_action, name='hq_shop_action'),
    path('saas-master/users/', hq_views.users, name='all_users'),
    path('saas-master/users/<int:user_id>/action/', hq_views.user_action, name='hq_user_action'),
    path('saas-master/users/<int:user_id>/login/', hq_views.login_as, name='hq_login_as'),
    path('saas-master/return/', hq_views.stop_login_as, name='hq_return'),
    path('saas-master/billing/', hq_views.payments, name='master_billing'),
    path('saas-master/payments/<int:payment_id>/recheck/', hq_views.payment_recheck, name='hq_payment_recheck'),
    path('saas-master/payments/<int:payment_id>/complete/', hq_views.payment_complete, name='hq_payment_complete'),
    path('saas-master/settlements/', website_views.master_settlements, name='master_settlements'),
    path('saas-master/sms/', hq_views.sms_panel, name='hq_sms'),
    path('saas-master/notices/', hq_views.notices, name='hq_notices'),
    path('saas-master/notices/<int:notice_id>/', hq_views.notice_action, name='hq_notice_action'),
    path('saas-master/activity/', hq_views.activity, name='hq_activity'),
    path('saas-master/search/', hq_views.search, name='hq_search'),
    path('saas-master/settings/', hq_views.system_settings, name='master_settings'),
    path('saas-master/recharge-sms/', hq_views.recharge_sms, name='recharge_sms'),

    # Barcode System
    path('pos/barcode-lookup/', views_pos.pos_barcode, name='barcode_lookup'),
    path('barcodes/', views.barcode_print, name='barcode_print'),

    # Banner Management
    # ওয়েবসাইট সেটিংস (Edumi-র মতো এক পেইজে ট্যাব)
    path('website/', website_views.website_settings, name='website_settings'),
    path('website/settlement/request/', website_views.settlement_request, name='settlement_request'),
    path('website/settlement/<int:pk>/cancel/', website_views.settlement_cancel, name='settlement_cancel'),
    path('website/banner/<int:pk>/delete/', website_views.banner_delete, name='website_banner_delete'),
    path('website/banner/<int:pk>/toggle/', website_views.banner_toggle, name='website_banner_toggle'),
    path('website/category/<int:pk>/rename/', website_views.category_rename, name='website_category_rename'),
    path('website/category/<int:pk>/delete/', website_views.category_remove, name='website_category_delete'),
    path('website/zone/<int:pk>/save/', website_views.zone_update, name='website_zone_update'),
    path('website/zone/<int:pk>/delete/', website_views.zone_delete, name='website_zone_delete'),
    # পুরনো ঠিকানাগুলো নতুন ট্যাবে পাঠায়
    path('banners/', RedirectView.as_view(url='/website/?tab=banners'), name='banner_list'),
    path('banners/add/', RedirectView.as_view(url='/website/?tab=banners'), name='add_banner'),

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
    path('shop/<slug:shop_slug>/category/<int:category_id>/', views.storefront_home, name='storefront_category'),
    path('shop/<slug:shop_slug>/checkout/', views.storefront_checkout, name='storefront_checkout'),
    path('shop/<slug:shop_slug>/place-order/', views.storefront_place_order, name='storefront_place_order'),
    path('shop/<slug:shop_slug>/l/<str:slug>/', views_landing.storefront_landing, name='storefront_landing'),
    path('shop/<slug:shop_slug>/coupon/', views.storefront_coupon_check, name='storefront_coupon_check'),
    path('shop/<slug:shop_slug>/checkout-draft/', views.storefront_checkout_draft, name='storefront_checkout_draft'),
    path('shop/<slug:shop_slug>/product/<int:product_id>/review/', views.storefront_review_submit, name='storefront_review'),
    path('shop/<slug:shop_slug>/sitemap.xml', views.storefront_sitemap, name='storefront_sitemap'),
    path('shop/<slug:shop_slug>/robots.txt', views.storefront_robots, name='storefront_robots'),
    path('shop/<slug:shop_slug>/track/', views.storefront_track, name='storefront_track'),
    path('shop/<slug:shop_slug>/t/<str:code>/', views.storefront_track_order, name='storefront_track_order'),
    path('shop/<slug:shop_slug>/order/<int:order_id>/success/', views.storefront_order_success, name='storefront_order_success'),
    path('shop/<slug:shop_slug>/order/<int:order_id>/pay/', views.storefront_payment_retry, name='storefront_payment_retry'),
    path('shop/<slug:shop_slug>/payment/return/', views.storefront_payment_return, name='storefront_payment_return'),

# Categories
    path('categories/', views.category_list, name='category_list'),
    path('shop/<slug:shop_slug>/product/<int:product_id>/', views.storefront_product_detail, name='storefront_product_detail'),
    path('category/edit/<int:pk>/', RedirectView.as_view(url='/website/?tab=categories'), name='edit_category'),

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
    # Meta App-এর Webhooks-এ এই ঠিকানা: https://<ডোমেইন>/facebook/webhook/
    path('facebook/webhook/', views.facebook_webhook, name='facebook_webhook'),
    path('facebook/bot-settings/', views.fb_bot_settings, name='fb_bot_settings'),
    path('facebook/pages/', views.fb_page_select, name='fb_page_select'),
    path('facebook/disconnect/', views.fb_disconnect, name='fb_disconnect'),
]
