"""
SellPunch টেস্ট: পাবলিক পেইজ, নীতিমালা, PayStation পেমেন্ট আর Facebook ডিসকানেক্ট।

চালানো: python manage.py test
PayStation-এর নেটওয়ার্ক কল নকল (mock) করা হয়েছে, তাই ইন্টারনেট লাগে না।
"""
import json
import os
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import FacebookPageConnection, OnlinePayment, Order, OrderItem, PaymentRequest, Shop
from .payments import recheck_pending

User = get_user_model()


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)
        self.history = []

    def json(self):
        return self._payload


class FakePayStation:
    """requests.post-এর বদলে বসে: URL দেখে initiate / v1 / v2-এর উত্তর দেয়।"""

    def __init__(self):
        self.v1 = None   # dict(status, amount) অথবা None (= পাওয়া যায়নি)
        self.v2 = None   # dict(status, amount, invoice) অথবা None
        self.calls = []

    def __call__(self, url, *args, **kwargs):
        self.calls.append(url)
        if url.endswith('/initiate-payment'):
            return FakeResponse({'status_code': '200', 'payment_url': 'https://sandbox.paystation.com.bd/checkout/test'})
        if url.endswith('/v2/transaction-status'):
            if not self.v2:
                return FakeResponse({'status_code': '2001', 'message': 'not found'})
            return FakeResponse({'status_code': '200', 'data': {
                'trx_status': self.v2['status'], 'payment_amount': self.v2['amount'],
                'invoice_number': self.v2['invoice'], 'trx_id': 'TRXV2TEST'}})
        if url.endswith('/transaction-status'):
            if not self.v1:
                return FakeResponse({'status_code': '2001', 'message': 'not found'})
            return FakeResponse({'status_code': '200', 'data': {
                'trx_status': self.v1['status'], 'payment_amount': self.v1['amount'],
                'trx_id': 'TRXV1TEST', 'payment_method': 'bKash'}})
        raise AssertionError(f'unexpected URL {url}')


class PublicPagesTests(TestCase):
    PAGES = ['privacy_policy', 'terms', 'refund_policy', 'data_deletion', 'contact']

    def test_policy_pages_open_for_everyone_with_header_and_footer(self):
        for name in self.PAGES:
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200, name)
            html = response.content.decode()
            self.assertIn('Get Started Free', html, name)                      # উপরের বার
            self.assertIn(reverse('privacy_policy'), html, name)               # footer-এর Legal লিংক
            self.assertIn(reverse('data_deletion'), html, name)

    def test_login_and_signup_use_public_base(self):
        for name in ['login', 'signup']:
            html = self.client.get(reverse(name)).content.decode()
            self.assertIn('ss-nav', html, name)
            self.assertIn(reverse('refund_policy'), html, name)
        signup = self.client.get(reverse('signup')).content.decode()
        self.assertIn('৩০ দিন সব ফিচার ফ্রি', signup)
        self.assertIn(reverse('terms'), signup)

    @override_settings(SUPPORT_PHONE='01811111111', SUPPORT_EMAIL='help@example.com')
    def test_contact_details_come_from_settings(self):
        html = self.client.get(reverse('contact')).content.decode()
        self.assertIn('01811111111', html)
        self.assertIn('help@example.com', html)

    def test_landing_footer_links_to_policies(self):
        html = self.client.get(reverse('landing_page')).content.decode()
        self.assertIn(reverse('privacy_policy'), html)
        self.assertIn(reverse('refund_policy'), html)


class ShopTestMixin:
    def make_shop(self, phone='01711111111', **shop_fields):
        user = User.objects.create_user(phone_number=phone, password='Test-pass-123')
        shop = Shop.objects.create(user=user, name=f'Shop {phone}', phone=phone, address='Dhaka', **shop_fields)
        self.client.force_login(user)
        return user, shop


class LockedShopTests(ShopTestMixin, TestCase):
    def test_locked_shop_can_still_read_policies(self):
        _user, shop = self.make_shop(is_locked=True)
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 302)   # লক → billing
        self.assertEqual(self.client.get(reverse('refund_policy')).status_code, 200)


@mock.patch('store.payments.VERIFY_RETRY_WAIT', 0)
class PayStationFlowTests(ShopTestMixin, TestCase):
    def setUp(self):
        self.user, self.shop = self.make_shop()
        self.fake = FakePayStation()
        patcher = mock.patch('store.paystation.requests.post', side_effect=self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)

    def start(self, item, **extra):
        return self.client.post(reverse('paystation_start'), {'item': item, **extra})

    def callback(self, payment, **params):
        return self.client.get(reverse('paystation_callback'), {'inv': payment.invoice_number, **params})

    # ---- কে অনলাইন পেমেন্ট করতে পারবে ----
    def test_sandbox_hidden_for_real_sellers(self):
        response = self.client.get(reverse('billing'))
        self.assertFalse(response.context['online_payment_available'])
        self.start('Standard')
        self.assertFalse(OnlinePayment.objects.exists())

    def test_start_uses_server_price_not_browser_amount(self):
        with override_settings(PAYSTATION_TEST_SHOPS=[self.shop.slug]):
            response = self.start('Standard', amount='1')
        self.assertRedirects(response, 'https://sandbox.paystation.com.bd/checkout/test', fetch_redirect_response=False)
        payment = OnlinePayment.objects.get()
        self.assertEqual(payment.amount, Decimal('999'))
        self.assertEqual(payment.days, 30)
        self.assertEqual(payment.environment, 'sandbox')

    def test_unknown_item_rejected(self):
        with override_settings(PAYSTATION_TEST_SHOPS=[self.shop.slug]):
            self.start('Diamond')
        self.assertFalse(OnlinePayment.objects.exists())

    # ---- সফল পেমেন্ট, আর একই পেমেন্ট দুইবার যোগ না হওয়া ----
    def make_payment(self, item='Standard'):
        with override_settings(PAYSTATION_TEST_SHOPS=[self.shop.slug]):
            self.start(item)
        return OnlinePayment.objects.latest('created_at')

    def test_success_upgrades_once_even_with_callback_and_ipn(self):
        payment = self.make_payment()
        self.fake.v1 = {'status': 'Success', 'amount': '999.00'}
        self.callback(payment, status='Successful', trx_id='ABC123XYZ')
        self.shop.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'Completed')
        self.assertEqual(self.shop.subscription_plan, 'Standard')
        self.assertFalse(self.shop.is_locked)
        expected_until = timezone.localdate() + timedelta(days=30)
        self.assertEqual(self.shop.valid_until, expected_until)

        # একই callback আবার, তারপর IPN — মেয়াদ আর বাড়বে না
        self.callback(payment, status='Successful')
        ipn = self.client.post(reverse('paystation_ipn'), data=f'{{"invoice_number": "{payment.invoice_number}"}}',
                               content_type='application/json')
        self.assertEqual(ipn.status_code, 200)
        self.shop.refresh_from_db()
        self.assertEqual(self.shop.valid_until, expected_until)

    def test_renewal_adds_to_remaining_days(self):
        self.shop.valid_until = timezone.localdate() + timedelta(days=10)
        self.shop.subscription_plan = 'Basic'
        self.shop.save()
        payment = self.make_payment('Basic')
        self.fake.v1 = {'status': 'Success', 'amount': '499'}
        self.callback(payment)
        self.shop.refresh_from_db()
        self.assertEqual(self.shop.valid_until, timezone.localdate() + timedelta(days=40))

    def test_yearly_plan_adds_365_days(self):
        payment = self.make_payment('Basic-YEAR')
        self.assertEqual((payment.amount, payment.days), (Decimal('5000'), 365))
        self.fake.v1 = {'status': 'Success', 'amount': '5000'}
        self.callback(payment)
        self.shop.refresh_from_db()
        self.assertEqual((self.shop.subscription_plan, self.shop.valid_until),
                         ('Basic', timezone.localdate() + timedelta(days=365)))

    def test_sms_pack_adds_sms(self):
        payment = self.make_payment('SMS-500')
        self.assertEqual(payment.amount, Decimal('200'))
        self.fake.v1 = {'status': 'Success', 'amount': '200'}
        self.callback(payment)
        self.shop.refresh_from_db()
        self.assertEqual(self.shop.sms_balance, 500)
        self.assertEqual(self.shop.subscription_plan, 'Free')

    # ---- নকল / ভুল পেমেন্ট ----
    def test_callback_status_alone_never_upgrades(self):
        payment = self.make_payment()
        self.fake.v1 = None   # PayStation বলছে এমন লেনদেন নেই
        self.callback(payment, status='Successful', trx_id='FAKE12345')
        self.shop.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(self.shop.subscription_plan, 'Free')
        self.assertEqual(payment.status, 'Pending')

    def test_amount_mismatch_does_not_upgrade(self):
        payment = self.make_payment('Premium')
        self.fake.v1 = {'status': 'Success', 'amount': '10'}
        self.callback(payment)
        self.shop.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(self.shop.subscription_plan, 'Free')
        self.assertEqual(payment.status, 'Pending')

    def test_someone_elses_trx_id_is_rejected(self):
        payment = self.make_payment('Premium')
        self.fake.v1 = None
        self.fake.v2 = {'status': 'Success', 'amount': '1999', 'invoice': 'SS-999-AAAAAAAAAAAA'}
        self.callback(payment, trx_id='OTHERTRX99')
        self.shop.refresh_from_db()
        self.assertEqual(self.shop.subscription_plan, 'Free')

    def test_trx_id_fallback_works_for_own_invoice(self):
        payment = self.make_payment('Basic')
        self.fake.v1 = None
        self.fake.v2 = {'status': 'Success', 'amount': '499', 'invoice': payment.invoice_number}
        self.callback(payment, trx_id='OWNTRX123')
        self.shop.refresh_from_db()
        self.assertEqual(self.shop.subscription_plan, 'Basic')

    def test_failed_payment_marked_failed(self):
        payment = self.make_payment()
        self.fake.v1 = {'status': 'Failed', 'amount': '999'}
        self.callback(payment)
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'Failed')

    def test_ipn_rejects_unknown_and_junk_invoices(self):
        missing = self.client.post(reverse('paystation_ipn'), data='{"invoice_number": "SS-1-ABCDEFABCDEF"}',
                                   content_type='application/json')
        self.assertEqual(missing.status_code, 404)
        junk = self.client.post(reverse('paystation_ipn'), {'invoice_number': "x' OR 1=1"})
        self.assertEqual(junk.status_code, 400)
        self.assertEqual(self.fake.calls, [])     # PayStation-এ কোনো কল যায়নি

    def test_billing_page_rechecks_lost_callbacks(self):
        payment = self.make_payment()
        OnlinePayment.objects.filter(pk=payment.pk).update(created_at=timezone.now() - timedelta(minutes=5))
        self.fake.v1 = {'status': 'Success', 'amount': '999'}
        self.client.get(reverse('billing'))
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'Completed')

    def test_sandbox_payment_not_verified_in_live_mode(self):
        payment = self.make_payment()
        OnlinePayment.objects.filter(pk=payment.pk).update(created_at=timezone.now() - timedelta(minutes=5))
        self.fake.v1 = {'status': 'Success', 'amount': '999'}
        with override_settings(PAYSTATION_ENVIRONMENT='live'):
            self.assertEqual(recheck_pending(self.shop), [])
            self.callback(payment)
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'Pending')


class FacebookDisconnectTests(ShopTestMixin, TestCase):
    def test_disconnect_needs_post_and_removes_tokens(self):
        from allauth.socialaccount.models import SocialAccount, SocialApp, SocialToken
        user, shop = self.make_shop()
        FacebookPageConnection.objects.create(shop=shop, page_id='1', page_name='Page', page_access_token='t')
        app = SocialApp.objects.create(provider='facebook', name='fb', client_id='1', secret='s')
        account = SocialAccount.objects.create(user=user, provider='facebook', uid='123')
        SocialToken.objects.create(app=app, account=account, token='usertoken')

        self.client.get(reverse('fb_disconnect'))
        self.assertTrue(FacebookPageConnection.objects.filter(shop=shop).exists())

        self.client.post(reverse('fb_disconnect'))
        self.assertFalse(FacebookPageConnection.objects.filter(shop=shop).exists())
        self.assertFalse(SocialToken.objects.filter(account=account).exists())
        self.assertTrue(SocialAccount.objects.filter(pk=account.pk).exists())   # লগইন সংযোগ থাকে


class SubdomainAndStorefrontTests(ShopTestMixin, TestCase):
    def test_shop_without_slug_gets_valid_subdomain_even_with_bengali_name(self):
        user = User.objects.create_user(phone_number='01600000000', password='x123456')
        shop = Shop.objects.create(user=user, name='রহিম ফ্যাশন')
        self.assertRegex(shop.slug, r'^shop\d{6}$')
        other = Shop.objects.create(user=User.objects.create_user(phone_number='01600000001', password='x'),
                                    name='Rahim Fashion')
        self.assertEqual(other.slug, 'rahimfashion')

    def test_setup_shop_for_user_without_shop(self):
        user = User.objects.create_user(phone_number='01600000002', password='x123456')
        self.client.force_login(user)
        response = self.client.post(reverse('setup_shop'), {'shop_name': 'FB Shop', 'subdomain': 'fbshop'})
        self.assertRedirects(response, reverse('dashboard'), fetch_redirect_response=False)
        self.assertEqual(Shop.objects.get(user=user).slug, 'fbshop')

    def test_settings_can_change_subdomain_with_validation(self):
        _user, shop = self.make_shop()
        Shop.objects.create(user=User.objects.create_user(phone_number='01600000003', password='x'),
                            name='Other', slug='takenname')
        base = {'section': 'store', 'name': shop.name, 'phone': shop.phone, 'address': 'Dhaka'}
        response = self.client.post(reverse('website_settings'), {**base, 'subdomain': 'takenname'})
        self.assertEqual(response.status_code, 200)
        shop.refresh_from_db()
        self.assertNotEqual(shop.slug, 'takenname')
        self.client.post(reverse('website_settings'), {**base, 'subdomain': 'New-Name'})
        shop.refresh_from_db()
        self.assertEqual(shop.slug, 'new-name')

    def test_storefront_open_in_trial_and_basic(self):
        for plan in ['Free', 'Basic', 'Standard', 'Premium']:
            _user, shop = self.make_shop(phone=f'0171{len(plan):07d}', subscription_plan=plan,
                                         valid_until=timezone.localdate() + timedelta(days=5))
            response = self.client.get(reverse('storefront_home', args=[shop.slug]))
            self.assertTemplateUsed(response, 'store/storefront/home.html', plan)

    def test_storefront_stays_open_7_days_after_expiry_then_closes(self):
        _user, shop = self.make_shop(subscription_plan='Basic',
                                     valid_until=timezone.localdate() - timedelta(days=7))
        self.assertTemplateUsed(self.client.get(reverse('storefront_home', args=[shop.slug])),
                                'store/storefront/home.html')
        shop.valid_until = timezone.localdate() - timedelta(days=8)
        shop.save()
        self.assertTemplateUsed(self.client.get(reverse('storefront_home', args=[shop.slug])),
                                'store/storefront/offline.html')

    def test_trial_expiry_closes_after_grace(self):
        _user, shop = self.make_shop()
        shop.trial_ends_at = timezone.now() - timedelta(days=10)
        shop.save()
        self.assertTemplateUsed(self.client.get(reverse('storefront_home', args=[shop.slug])),
                                'store/storefront/offline.html')

    def test_trial_can_use_pos(self):
        _user, shop = self.make_shop()
        self.assertEqual(self.client.get(reverse('pos')).status_code, 200)


class PlanLimitsTests(ShopTestMixin, TestCase):
    def _paid(self, plan):
        return {'subscription_plan': plan, 'valid_until': timezone.localdate() + timedelta(days=20)}

    def test_basic_plan_product_limit(self):
        from .models import Product
        _user, shop = self.make_shop(**self._paid('Basic'))
        Product.objects.bulk_create([Product(shop=shop, name=f'P{i}', price=10, cost_price=5, stock_quantity=1)
                                     for i in range(200)])
        response = self.client.post(reverse('add_product'), {'name': 'One more', 'price': 10, 'cost_price': 5,
                                                             'stock_quantity': 1, 'is_active': 'on'})
        self.assertRedirects(response, reverse('product_list'), fetch_redirect_response=False)
        self.assertEqual(Product.objects.filter(shop=shop).count(), 200)
        html = self.client.get(reverse('product_list')).content.decode()
        self.assertIn('প্যাকেজে সর্বোচ্চ 200টা', html)

    def test_premium_has_no_product_limit(self):
        from .plans import products_remaining
        _user, shop = self.make_shop(**self._paid('Premium'))
        self.assertIsNone(products_remaining(shop))

    def test_basic_plan_allows_only_one_staff(self):
        from .models import StaffProfile
        _user, shop = self.make_shop(**self._paid('Basic'))
        data = {'name': 'Karim', 'phone': '01922222222', 'password': 'Staff-pass-1', 'can_use_pos': 'on'}
        self.client.post(reverse('add_staff'), data)
        self.assertEqual(StaffProfile.objects.filter(shop=shop).count(), 1)
        response = self.client.post(reverse('add_staff'), {**data, 'phone': '01933333333'})
        self.assertRedirects(response, reverse('staff_list'), fetch_redirect_response=False)
        self.assertEqual(StaffProfile.objects.filter(shop=shop).count(), 1)
        # এডিট করা যাবে
        staff = StaffProfile.objects.get(shop=shop)
        self.assertEqual(self.client.get(reverse('edit_staff', args=[staff.id])).status_code, 200)
        self.assertIn('আরও স্টাফের জন্য আপগ্রেড', self.client.get(reverse('staff_list')).content.decode())

    def test_basic_plan_cannot_connect_facebook(self):
        _user, shop = self.make_shop(**self._paid('Basic'))
        for name in ['fb_connect', 'fb_page_select']:
            response = self.client.get(reverse(name))
            self.assertRedirects(response, reverse('billing'), fetch_redirect_response=False)
        html = self.client.get(reverse('settings')).content.decode()
        self.assertNotIn(reverse('fb_connect'), html)
        dashboard = self.client.get(reverse('dashboard'))
        self.assertEqual(dashboard.status_code, 200)
        self.assertNotIn(reverse('fb_connect'), dashboard.content.decode())
        self.assertEqual(self.client.get(reverse('billing')).status_code, 200)

    def test_trial_and_standard_can_open_facebook_connect(self):
        for phone, fields in [('01744444444', {}), ('01755555555', self._paid('Standard'))]:
            self.make_shop(phone=phone, **fields)
            response = self.client.get(reverse('fb_connect'))
            # Facebook App বসানো না থাকায় ড্যাশবোর্ডে ফেরত যায়, কিন্তু billing-এ না
            self.assertNotEqual(response.get('Location'), reverse('billing'))

    def test_custom_domain_only_on_premium(self):
        base = {'section': 'store', 'name': 'Shop', 'phone': '01711111111', 'address': 'Dhaka',
                'subdomain': 'myshop', 'custom_domain': 'www.example.com'}
        _user, shop = self.make_shop(**self._paid('Standard'))
        self.client.post(reverse('website_settings'), base)
        shop.refresh_from_db()
        self.assertEqual(shop.slug, 'myshop')
        self.assertFalse(shop.custom_domain)

        shop.subscription_plan = 'Premium'
        shop.save()
        self.client.post(reverse('website_settings'), base)
        shop.refresh_from_db()
        self.assertEqual(shop.custom_domain, 'www.example.com')


@override_settings(STORE_BASE_DOMAIN='sellpunch.com')
class StorefrontDomainTests(ShopTestMixin, TestCase):
    HOST = 'munna.sellpunch.com'

    def setUp(self):
        from .models import Product
        self.user, self.shop = self.make_shop(slug='munna')
        self.product = Product.objects.create(shop=self.shop, name='T-Shirt', price=500, cost_price=300,
                                              stock_quantity=5)

    def test_subdomain_shows_store_with_short_links(self):
        response = self.client.get('/', HTTP_HOST=self.HOST)
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn(self.shop.name, html)
        self.assertIn(f'/product/{self.product.id}/', html)
        self.assertNotIn('/shop/munna/', html)
        detail = self.client.get(f'/product/{self.product.id}/', HTTP_HOST=self.HOST)
        self.assertEqual(detail.status_code, 200)
        self.assertIn('T-Shirt', detail.content.decode())

    def test_old_links_redirect_to_subdomain(self):
        response = self.client.get(f'/shop/munna/product/{self.product.id}/?ref=fb', HTTP_HOST='sellpunch.com')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], f'https://munna.sellpunch.com/product/{self.product.id}/?ref=fb')
        on_sub = self.client.get('/shop/munna/', HTTP_HOST=self.HOST)
        self.assertEqual(on_sub.status_code, 301)
        self.assertEqual(on_sub['Location'], '/')

    def test_unknown_subdomain_shows_not_found(self):
        response = self.client.get('/', HTTP_HOST='nobody.sellpunch.com')
        self.assertEqual(response.status_code, 404)
        self.assertIn('এই ঠিকানায় কোনো দোকান নেই', response.content.decode())

    def test_main_site_and_dashboard_unchanged(self):
        dashboard = self.client.get(reverse('dashboard'), HTTP_HOST='sellpunch.com')
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn('https://munna.sellpunch.com/', dashboard.content.decode())
        self.assertIn('munna.sellpunch.com', dashboard.content.decode())
        self.assertEqual(self.shop.storefront_url, 'https://munna.sellpunch.com/')
        self.client.logout()
        self.assertEqual(self.client.get('/', HTTP_HOST='sellpunch.com').status_code, 200)
        self.assertEqual(self.client.get('/', HTTP_HOST='www.sellpunch.com').status_code, 200)

    def test_order_on_subdomain_and_success_page_is_private(self):
        import json
        from .delivery import zones_for
        response = self.client.post('/place-order/', data=json.dumps({
            'cart': [{'id': self.product.id, 'qty': 2}], 'name': 'Rahim', 'phone': '01812345678',
            'address': 'Savar', 'zone': zones_for(self.shop)[0].id}), content_type='application/json',
            HTTP_HOST=self.HOST)
        data = response.json()
        self.assertTrue(data['success'], data)
        success = self.client.get(f"/order/{data['order_id']}/success/", HTTP_HOST=self.HOST)
        self.assertEqual(success.status_code, 200)
        self.assertIn('Rahim', success.content.decode())
        # অন্য ব্রাউজার নম্বর বসিয়ে দেখতে পারবে না
        from django.test import Client
        other = Client().get(f"/order/{data['order_id']}/success/", HTTP_HOST=self.HOST)
        self.assertEqual(other.status_code, 302)

    def test_negative_quantity_rejected(self):
        import json
        response = self.client.post('/place-order/', data=json.dumps({
            'cart': [{'id': self.product.id, 'qty': -3}], 'name': 'X', 'phone': '01812345678',
            'address': 'Savar'}), content_type='application/json', HTTP_HOST=self.HOST)
        self.assertFalse(response.json()['success'])
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 5)

    @override_settings(ALLOWED_HOSTS=['.sellpunch.com', 'www.munnashop.com', 'munnashop.com'])
    def test_custom_domain_only_for_premium(self):
        self.shop.custom_domain = 'www.munnashop.com'
        self.shop.save()
        response = self.client.get('/', HTTP_HOST='munnashop.com')
        self.assertEqual(response.status_code, 302)          # Standard না → সাবডোমেইনে
        self.assertEqual(response['Location'], 'https://munna.sellpunch.com/')
        self.shop.subscription_plan = 'Premium'
        self.shop.valid_until = timezone.localdate() + timedelta(days=10)
        self.shop.save()
        self.assertEqual(self.client.get('/', HTTP_HOST='www.munnashop.com').status_code, 200)


class StorefrontWithoutDomainTests(ShopTestMixin, TestCase):
    def test_old_path_still_works_before_domain_is_set(self):
        _user, shop = self.make_shop(slug='munna')
        response = self.client.get('/shop/munna/', HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(shop.storefront_url, '/shop/munna/')


class FakeCourierAPI:
    """couriers.requests.request-এর বদলে বসে; URL দেখে আগে থেকে ঠিক করা উত্তর দেয়।"""

    def __init__(self, routes):
        self.routes = routes      # {(method, url-শেষাংশ): (status, json)}
        self.calls = []

    def __call__(self, method, url, timeout=None, **kwargs):
        self.calls.append({'method': method, 'url': url, **kwargs})
        for (m, suffix), (status, payload) in self.routes.items():
            if m == method and url.split('?')[0].endswith(suffix):
                return FakeResponse(payload, status)
        raise AssertionError(f'unexpected {method} {url}')


class CourierTests(ShopTestMixin, TestCase):
    def setUp(self):
        from django.core.cache import cache
        from .models import Customer, Product
        cache.clear()
        self.user, self.shop = self.make_shop()
        customer = Customer.objects.create(shop=self.shop, name='Rahim', phone='+8801712-345678',
                                           address='House 5, Road 2, Mirpur 10, Dhaka')
        product = Product.objects.create(shop=self.shop, name='Panjabi', price=1200, cost_price=800, stock_quantity=5)
        self.order = Order.objects.create(shop=self.shop, customer=customer, total_amount=Decimal('1300.50'),
                                          delivery_charge=100, payment_method='COD', status='Confirmed')
        OrderItem.objects.create(order=self.order, product=product, quantity=2, price=600)

    def _send(self, courier, fake, **extra):
        with mock.patch('store.couriers.requests.request', fake):
            return self.client.post(reverse('send_to_courier'),
                                    {'order_id': self.order.id, 'courier_partner': courier, **extra})

    def test_cod_is_zero_for_prepaid_orders(self):
        from .couriers import cod_amount
        self.assertEqual(cod_amount(self.order), 1301)
        for method in ['Paid', 'bKash', 'Card']:
            self.order.payment_method = method
            self.assertEqual(cod_amount(self.order), 0)
        page = self.client.get(reverse('order_list'))
        self.assertEqual(page.status_code, 200)
        html = page.content.decode()
        self.assertIn('redxAreaBox', html)
        self.assertIn("'1301'", html)                     # COD দেখানো
        self.assertIn('সেটআপ করা নেই', html)

    def test_steadfast_uses_packzy_and_no_cod_on_paid_order(self):
        self.shop.steadfast_api_key, self.shop.steadfast_secret_key = 'KEY', 'SECRET'
        self.shop.save()
        self.order.payment_method = 'bKash'
        self.order.save()
        fake = FakeCourierAPI({('POST', '/create_order'): (200, {
            'status': 200, 'consignment': {'consignment_id': 77, 'tracking_code': 'SF77TRACK'}})})
        self._send('Steadfast', fake)
        call = fake.calls[0]
        self.assertTrue(call['url'].startswith('https://portal.packzy.com/api/v1/'))
        self.assertEqual(call['headers']['Api-Key'], 'KEY')
        self.assertEqual(call['json']['cod_amount'], 0)
        self.assertEqual(call['json']['recipient_phone'], '01712345678')
        self.assertEqual(call['json']['invoice'], f'ORD-{self.order.id}')
        self.order.refresh_from_db()
        self.assertEqual((self.order.status, self.order.steadfast_tracking_code, self.order.courier_partner),
                         ('Shipped', 'SF77TRACK', 'Steadfast'))

    def test_steadfast_wrong_key_leaves_order_unchanged(self):
        self.shop.steadfast_api_key, self.shop.steadfast_secret_key = 'KEY', 'BAD'
        self.shop.save()
        fake = FakeCourierAPI({('POST', '/create_order'): (401, {'message': 'Unauthorized'})})
        response = self._send('Steadfast', fake)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'Confirmed')
        self.assertFalse(self.order.steadfast_tracking_code)
        msgs = [str(m) for m in response.wsgi_request._messages]
        self.assertTrue(any('ভুল' in m for m in msgs), msgs)

    def test_pathao_connect_does_not_store_password_and_sends_without_city(self):
        fake = FakeCourierAPI({
            ('POST', '/aladdin/api/v1/issue-token'): (200, {'access_token': 'ACC', 'refresh_token': 'REF',
                                                           'expires_in': 432000}),
            ('GET', '/aladdin/api/v1/stores'): (200, {'data': {'data': [
                {'store_id': 11, 'store_name': 'Savar', 'is_active': 1, 'is_default_store': 0},
                {'store_id': 12, 'store_name': 'Dhaka', 'is_active': 1, 'is_default_store': 1}]}}),
            ('POST', '/aladdin/api/v1/orders'): (200, {'data': {'consignment_id': 'PT123'}}),
        })
        with mock.patch('store.couriers.requests.request', fake):
            self.client.post(reverse('settings'), {
                'name': self.shop.name, 'phone': self.shop.phone, 'address': 'Dhaka', 'subdomain': self.shop.slug,
                'pathao_client_id': 'CID', 'pathao_client_secret': 'CSECRET', 'pathao_email': 'me@example.com',
                'pathao_password': 'MyPathaoPass', 'courier_action': 'pathao_connect'})
        self.shop.refresh_from_db()
        self.assertEqual((self.shop.pathao_access_token, self.shop.pathao_refresh_token), ('ACC', 'REF'))
        self.assertEqual(self.shop.pathao_store_id, '12')            # default store
        token_call = fake.calls[0]['json']
        self.assertEqual(token_call['grant_type'], 'password')
        from django.forms.models import model_to_dict
        self.assertNotIn('MyPathaoPass', str(model_to_dict(self.shop)))

        self._send('Pathao', fake)
        order_call = fake.calls[-1]['json']
        self.assertEqual(order_call['store_id'], 12)
        self.assertEqual(order_call['amount_to_collect'], 1301)
        self.assertEqual(order_call['item_quantity'], 2)
        self.assertNotIn('recipient_city', order_call)
        self.order.refresh_from_db()
        self.assertEqual(self.order.steadfast_tracking_code, 'PT123')

    def test_pathao_refreshes_expired_token(self):
        self.shop.pathao_access_token, self.shop.pathao_refresh_token = 'OLD', 'REF'
        self.shop.pathao_client_id, self.shop.pathao_client_secret = 'CID', 'CS'
        self.shop.pathao_store_id = '12'
        self.shop.pathao_token_expires_at = timezone.now() - timedelta(hours=1)
        self.shop.save()
        fake = FakeCourierAPI({
            ('POST', '/aladdin/api/v1/issue-token'): (200, {'access_token': 'NEW', 'refresh_token': 'REF2',
                                                           'expires_in': 432000}),
            ('POST', '/aladdin/api/v1/orders'): (200, {'data': {'consignment_id': 'PT9'}}),
        })
        self._send('Pathao', fake)
        self.assertEqual(fake.calls[0]['json']['grant_type'], 'refresh_token')
        self.assertEqual(fake.calls[1]['headers']['Authorization'], 'Bearer NEW')

    def test_redx_needs_area_and_uses_its_header(self):
        self.shop.redx_access_token = 'RXTOKEN'
        self.shop.save()
        fake = FakeCourierAPI({
            ('GET', '/areas'): (200, {'areas': [{'id': 5, 'name': 'Mirpur 10', 'post_code': 1216}]}),
            ('POST', '/parcel'): (200, {'tracking_id': 'RX55'}),
        })
        self._send('RedX', fake)                       # এলাকা ছাড়া
        self.order.refresh_from_db()
        self.assertFalse(self.order.steadfast_tracking_code)

        with mock.patch('store.couriers.requests.request', fake):
            areas = self.client.get(reverse('redx_areas')).json()
        self.assertEqual(areas['areas'][0]['id'], 5)
        self._send('RedX', fake, redx_area_id='5')
        parcel = [c for c in fake.calls if c['url'].endswith('/parcel')][0]
        self.assertEqual(parcel['headers']['API-ACCESS-TOKEN'], 'Bearer RXTOKEN')
        self.assertEqual((parcel['json']['delivery_area'], parcel['json']['delivery_area_id']), ('Mirpur 10', 5))
        self.assertEqual(parcel['json']['parcel_weight'], 500)
        self.order.refresh_from_db()
        self.assertEqual(self.order.steadfast_tracking_code, 'RX55')

    def test_steadfast_webhook_needs_shop_token(self):
        import json
        token = self.shop.ensure_webhook_token()
        body = json.dumps({'notification_type': 'delivery_status', 'invoice': f'ORD-{self.order.id}',
                           'status': 'delivered'})
        url = reverse('steadfast_webhook')
        self.assertEqual(self.client.post(url, body, content_type='application/json').status_code, 401)
        self.assertEqual(self.client.post(url, body, content_type='application/json',
                                          HTTP_AUTHORIZATION='Bearer wrong').status_code, 401)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'Confirmed')
        ok = self.client.post(url, body, content_type='application/json', HTTP_AUTHORIZATION=f'Bearer {token}')
        self.assertEqual(ok.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'Delivered')
        unknown = self.client.post(url, json.dumps({'invoice': 'ORD-999999', 'status': 'delivered'}),
                                   content_type='application/json')
        self.assertEqual(unknown.status_code, 200)

    def test_settings_save_keeps_secret_and_tests_connection(self):
        self.shop.steadfast_api_key, self.shop.steadfast_secret_key = 'KEY', 'SECRET'
        self.shop.save()
        page = self.client.get(reverse('settings')).content.decode()
        self.assertNotIn('SECRET', page)
        fake = FakeCourierAPI({('GET', '/get_balance'): (200, {'status': 200, 'current_balance': 500})})
        with mock.patch('store.couriers.requests.request', fake):
            response = self.client.post(reverse('settings'), {
                'name': self.shop.name, 'phone': self.shop.phone, 'address': 'Dhaka', 'subdomain': self.shop.slug,
                'steadfast_api_key': 'KEY', 'steadfast_secret_key': '', 'courier_action': 'test_Steadfast'})
        self.shop.refresh_from_db()
        self.assertEqual(self.shop.steadfast_secret_key, 'SECRET')
        msgs = [str(m) for m in response.wsgi_request._messages]
        self.assertTrue(any('Steadfast কানেক্ট আছে' in m for m in msgs), msgs)


class SettingsPageTests(ShopTestMixin, TestCase):
    """সেটিংস পেইজ: ট্যাব, আলাদা ফর্ম, আর ভুল চাবি দিলে কিছু সেভ না হওয়া।"""

    def setUp(self):
        self.user, self.shop = self.make_shop()

    def test_every_tab_renders_in_bangla(self):
        for tab, text in [('courier', 'Steadfast যুক্ত করুন'), ('facebook', 'Facebook দিয়ে যুক্ত করুন')]:
            response = self.client.get(reverse('settings') + f'?tab={tab}')
            self.assertEqual(response.status_code, 200)
            html = response.content.decode()
            self.assertIn(text, html)
            self.assertIn('<div class="topbar-title">সেটিংস</div>', html)
        self.assertIn('Steadfast যুক্ত করুন', self.client.get(reverse('settings') + '?tab=nope').content.decode())

    def test_wrong_keys_are_not_saved_and_working_keys_stay(self):
        self.shop.steadfast_api_key, self.shop.steadfast_secret_key = 'GOODKEY', 'GOODSECRET'
        self.shop.save()
        fake = FakeCourierAPI({('GET', '/get_balance'): (401, {'message': 'Unauthorized'})})
        with mock.patch('store.couriers.requests.request', fake):
            response = self.client.post(reverse('settings'), {
                'section': 'steadfast', 'steadfast_api_key': 'BADKEY', 'steadfast_secret_key': 'BADSECRET',
                'courier_action': 'test_Steadfast'})
        self.assertEqual(response.status_code, 200)               # ভুল দেখিয়ে একই পেইজ
        self.assertIn('Steadfast API Key বা Secret Key ভুল।', response.content.decode())
        self.shop.refresh_from_db()
        self.assertEqual((self.shop.steadfast_api_key, self.shop.steadfast_secret_key), ('GOODKEY', 'GOODSECRET'))

    def test_new_courier_needs_both_keys(self):
        response = self.client.post(reverse('settings'), {
            'section': 'steadfast', 'steadfast_api_key': 'ONLYKEY', 'courier_action': 'test_Steadfast'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('Steadfast-এর Secret Key দিন।', response.content.decode())
        self.shop.refresh_from_db()
        self.assertFalse(self.shop.steadfast_api_key)

    def test_sms_toggle_does_not_touch_couriers(self):
        self.shop.redx_access_token = 'REDX'
        self.shop.save()
        # SMS এখন আলাদা SMS প্যানেলে; পুরনো সেটিংস লিংক সেখানে নিয়ে যায়
        self.assertRedirects(self.client.get(reverse('settings') + '?tab=sms'), reverse('sms_panel'),
                             fetch_redirect_response=False)
        response = self.client.post(reverse('sms_auto'), {})     # সুইচ বন্ধ
        self.assertRedirects(response, reverse('sms_panel'), fetch_redirect_response=False)
        self.shop.refresh_from_db()
        self.assertFalse(self.shop.is_sms_active)
        self.assertEqual(self.shop.redx_access_token, 'REDX')

    def test_disconnect_and_failed_pathao_connect(self):
        self.shop.redx_access_token = 'REDX'
        self.shop.save()
        self.client.post(reverse('settings'), {'section': 'redx', 'courier_action': 'redx_disconnect'})
        self.shop.refresh_from_db()
        self.assertIsNone(self.shop.redx_access_token)

        fake = FakeCourierAPI({('POST', '/aladdin/api/v1/issue-token'): (401, {'message': 'Invalid credentials'})})
        with mock.patch('store.couriers.requests.request', fake):
            response = self.client.post(reverse('settings'), {
                'section': 'pathao', 'pathao_client_id': 'CID', 'pathao_client_secret': 'CSECRET',
                'pathao_email': 'me@example.com', 'pathao_password': 'x', 'courier_action': 'pathao_connect'})
        self.assertEqual(response.status_code, 200)
        self.shop.refresh_from_db()
        self.assertFalse(self.shop.pathao_client_id)
        self.assertFalse(self.shop.pathao_access_token)


class SoldCountTests(ShopTestMixin, TestCase):
    def setUp(self):
        from .models import Customer, Product
        self.user, self.shop = self.make_shop(slug='soldshop')
        self.product = Product.objects.create(shop=self.shop, name='Saree', price=900, cost_price=600, stock_quantity=9)
        self.other = Product.objects.create(shop=self.shop, name='Lungi', price=300, cost_price=200, stock_quantity=9)
        customer = Customer.objects.create(shop=self.shop, name='Karim', phone='01811111111', address='Savar')
        for status, qty in [('Delivered', 2), ('Shipped', 1), ('Cancelled', 5), ('Pending', 4)]:
            order = Order.objects.create(shop=self.shop, customer=customer, status=status, total_amount=900)
            OrderItem.objects.create(order=order, product=self.product, quantity=qty, price=900)

    def test_shows_only_real_sold_count(self):
        html = self.client.get('/shop/soldshop/', HTTP_HOST='localhost').content.decode()
        self.assertIn('3টা বিক্রি হয়েছে', html)          # শুধু Delivered + Shipped
        self.assertNotIn('/5', html)                        # বানানো রেটিং নেই
        self.assertNotIn('-15%', html)
        self.assertEqual(html.count('বিক্রি হয়েছে'), 1)    # Lungi বিক্রি হয়নি, তাই কিছু দেখায় না
        detail = self.client.get(f'/shop/soldshop/product/{self.product.id}/', HTTP_HOST='localhost').content.decode()
        self.assertIn('3টা বিক্রি হয়েছে', detail)
        self.assertNotIn('4.9/5', detail)

    def test_seller_can_turn_it_off(self):
        self.shop.show_sold_count = False
        self.shop.save()
        html = self.client.get('/shop/soldshop/', HTTP_HOST='localhost').content.decode()
        self.assertNotIn('বিক্রি হয়েছে', html)
        self.assertNotIn('বেশি বিক্রি', html)


class ComparePriceTests(ShopTestMixin, TestCase):
    def test_discount_shows_only_from_seller_old_price(self):
        from .models import Product
        _user, shop = self.make_shop(slug='saleshop')
        base = {'name': 'Kurti', 'price': 800, 'cost_price': 500, 'stock_quantity': 3, 'is_active': 'on'}
        bad = self.client.post(reverse('add_product'), {**base, 'compare_price': 700})
        self.assertEqual(bad.status_code, 200)                       # আগের দাম কম হলে নেয় না
        self.assertFalse(Product.objects.filter(shop=shop).exists())
        self.client.post(reverse('add_product'), {**base, 'compare_price': 1000})
        product = Product.objects.get(shop=shop)
        self.assertEqual(product.discount_percent, 20)
        Product.objects.create(shop=shop, name='Plain', price=500, cost_price=300, stock_quantity=2)
        html = self.client.get('/shop/saleshop/', HTTP_HOST='localhost').content.decode()
        self.assertIn('ছাড় চলছে', html)
        self.assertIn('-20%', html)
        self.assertIn('৳1000', html)
        self.assertEqual(html.count('-20%'), 2)                        # ছাড়ের সারি + প্রোডাক্ট কার্ড
        detail = self.client.get(f'/shop/saleshop/product/{product.id}/', HTTP_HOST='localhost').content.decode()
        self.assertIn('-20%', detail)

    def test_no_sale_row_without_real_discount(self):
        from .models import Product
        _user, shop = self.make_shop(slug='plainshop')
        Product.objects.create(shop=shop, name='Plain', price=500, cost_price=300, stock_quantity=2)
        html = self.client.get('/shop/plainshop/', HTTP_HOST='localhost').content.decode()
        self.assertNotIn('ছাড় চলছে', html)
        self.assertNotIn('%</', html)


def _png_upload(name='photo.png', size=(2400, 1600), alpha=True):
    import io
    from PIL import Image
    from django.core.files.uploadedfile import SimpleUploadedFile
    image = Image.new('RGBA' if alpha else 'RGB', size, (200, 30, 60, 128) if alpha else (200, 30, 60))
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    return SimpleUploadedFile(name, buffer.getvalue(), content_type='image/png')


class StorefrontPolishTests(ShopTestMixin, TestCase):
    """দোকানের ওয়েবসাইট: শেয়ার প্রিভিউ, ছোট ছবি, পেজিং, সাজানো, ক্যাটাগরির লিংক, বাংলা লেখা।"""

    def setUp(self):
        import tempfile
        self.media = tempfile.mkdtemp()
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)
        import shutil
        self.addCleanup(shutil.rmtree, self.media, True)
        self.user, self.shop = self.make_shop(slug='polish')

    def _product(self, **fields):
        from .models import Product
        data = {'shop': self.shop, 'name': 'Saree', 'price': 900, 'cost_price': 500, 'stock_quantity': 9}
        data.update(fields)
        return Product.objects.create(**data)

    def test_uploaded_photo_is_shrunk_with_thumbnail(self):
        from PIL import Image
        product = self._product(image=_png_upload())
        product.refresh_from_db()
        self.assertTrue(product.image.name.endswith('.jpg'))
        self.assertEqual((product.image_width, product.image_height), (1200, 800))
        with Image.open(product.image.path) as main, Image.open(product.thumbnail.path) as thumb:
            self.assertEqual(main.size, (1200, 800))
            self.assertEqual(main.mode, 'RGB')                     # স্বচ্ছ অংশ সাদা, কালো না
            self.assertEqual(max(thumb.size), 480)
        self.assertIn('-thumb', product.thumb_url)

    def test_old_photos_are_fixed_by_command(self):
        from django.core.management import call_command
        from .models import Product
        product = self._product(image=_png_upload())
        Product.objects.filter(pk=product.pk).update(thumbnail=None, image_width=None)
        call_command('optimize_images', stdout=open(os.devnull, 'w'))
        product.refresh_from_db()
        self.assertTrue(product.thumbnail)
        self.assertEqual(product.image_width, 1200)

    def test_product_page_has_facebook_preview_and_bangla(self):
        product = self._product(name='জামদানি শাড়ি', price=2400, compare_price=3000, stock_quantity=3,
                                description='হাতে বোনা খাঁটি জামদানি।', image=_png_upload())
        html = self.client.get(f'/shop/polish/product/{product.id}/', HTTP_HOST='localhost').content.decode()
        self.assertIn('<meta property="og:title" content="জামদানি শাড়ি — Shop 01711111111">', html)
        self.assertIn('<meta property="og:type" content="product">', html)
        self.assertIn('<meta property="og:image" content="http://localhost/media/products/', html)
        self.assertIn('<meta property="og:image:width" content="1200">', html)
        self.assertIn('<meta property="product:price:amount" content="2400.00">', html)
        self.assertIn('৳2400 (20% ছাড়) · হাতে বোনা খাঁটি জামদানি।', html)
        self.assertNotIn('user-scalable=no', html)
        for english in ('In Stock', 'Only ', 'Privacy Policy', 'My Cart', 'Premium E-commerce'):
            self.assertNotIn(english, html)
        self.assertIn('আর মাত্র ৩টা আছে', html)

    def test_home_pages_in_24s_with_load_more(self):
        for i in range(30):
            self._product(name=f'Item {i}', price=100 + i)
        html = self.client.get('/shop/polish/', HTTP_HOST='localhost').content.decode()
        self.assertEqual(html.count('class="prod-card"'), 24)
        self.assertIn('id="loadMore"', html)
        self.assertIn('(৩০টা)', html)
        more = self.client.get('/shop/polish/?page=2&partial=1', HTTP_HOST='localhost')
        self.assertEqual(more.content.decode().count('class="prod-card"'), 6)
        self.assertEqual(more['X-Next-Page'], '')
        cheap = self.client.get('/shop/polish/?sort=price_asc', HTTP_HOST='localhost').content.decode()
        self.assertLess(cheap.index('Item 0<'), cheap.index('Item 1<'))
        dear = self.client.get('/shop/polish/?sort=price_desc', HTTP_HOST='localhost').content.decode()
        self.assertLess(dear.index('Item 29<'), dear.index('Item 28<'))

    def test_category_has_its_own_link(self):
        from .models import Category
        sarees = Category.objects.create(shop=self.shop, name='শাড়ি')
        self._product(name='Katan', category=sarees)
        self._product(name='Lungi')
        page = self.client.get(f'/shop/polish/category/{sarees.id}/', HTTP_HOST='localhost')
        html = page.content.decode()
        self.assertIn('Katan', html)
        self.assertNotIn('Lungi', html)
        self.assertIn('<title>শাড়ি — Shop 01711111111</title>', html)
        self.assertRedirects(self.client.get(f'/shop/polish/?cat={sarees.id}', HTTP_HOST='localhost'),
                             f'/shop/polish/category/{sarees.id}/', fetch_redirect_response=False)
        other = Category.objects.create(shop=Shop.objects.create(user=User.objects.create_user(
            phone_number='01722222222', password='x-Pass-123'), name='Other'), name='X')
        self.assertEqual(self.client.get(f'/shop/polish/category/{other.id}/', HTTP_HOST='localhost').status_code, 404)


class CloudflareHostingTests(TestCase):
    """Cloudflare Containers-এ চালানো: health check আর মূল ঠিকানা (PRIMARY_HOST) যেন দোকান না ভাবে।"""

    def test_health_check(self):
        response = self.client.get('/healthz/', HTTP_HOST='localhost')
        self.assertEqual((response.status_code, response.content), (200, b'ok'))

    @override_settings(STORE_BASE_DOMAIN='sellpunch.com', PRIMARY_HOST='cf.sellpunch.com')
    def test_primary_host_is_the_main_site_not_a_shop(self):
        response = self.client.get('/accounts/login/', HTTP_HOST='cf.sellpunch.com')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateNotUsed(response, 'store/storefront/not_found.html')
        from .subdomains import is_valid_format
        self.assertFalse(is_valid_format('cf'))     # কোনো দোকান 'cf' নাম নিতে পারবে না


class POSTests(ShopTestMixin, TestCase):
    """POS: দাম, স্টক, ছাড়, VAT, ভাগ করে পেমেন্ট, ফেরত টাকা, বাকি, দুবার জমা, বিক্রি ফেরত, দিনশেষ।"""

    def setUp(self):
        from .models import Product
        self.user, self.shop = self.make_shop()
        self.shirt = Product.objects.create(shop=self.shop, name='শার্ট', price=Decimal('450'), cost_price=300,
                                            stock_quantity=10, barcode='111222333')
        self.cap = Product.objects.create(shop=self.shop, name='Cap', price=Decimal('199.50'), cost_price=100,
                                          stock_quantity=2)

    def sell(self, **payload):
        payload.setdefault('payments', [{'method': 'cash', 'amount': 0, 'full': True}])
        return self.client.post(reverse('pos_checkout'), data=json.dumps(payload), content_type='application/json')

    def test_totals_math(self):
        from .pos import compute_totals
        D = Decimal
        self.assertEqual(compute_totals([D('1000')], 'percent', 10, 0, 'exclusive'), (D('1000'), D('100.00'), 0, D('900')))
        self.assertEqual(compute_totals([D('1000')], 'amount', 5000, 0, 'exclusive')[1], D('1000'))   # ছাড় দামের বেশি না
        sub, disc, vat, total = compute_totals([D('1000')], 'amount', 0, D('7.5'), 'exclusive')
        self.assertEqual((vat, total), (D('75.00'), D('1075.00')))
        sub, disc, vat, total = compute_totals([D('1075')], 'amount', 0, D('7.5'), 'inclusive')
        self.assertEqual((vat, total), (D('75.00'), D('1075')))

    def test_sale_uses_server_price_and_gives_change(self):
        response = self.sell(items=[{'id': self.shirt.id, 'qty': 1}, {'id': self.shirt.id, 'qty': 1}],
                             discount={'type': 'amount', 'value': 50},
                             payments=[{'method': 'cash', 'amount': 1000, 'full': True}])
        data = response.json()
        self.assertTrue(data['success'], data)
        self.assertEqual((data['sale']['total'], data['sale']['change'], data['sale']['due']), (850, 150, 0))
        order = Order.objects.get(pk=data['sale']['id'])
        self.assertEqual((order.source, order.status, order.payment_method), ('pos', 'Delivered', 'Paid'))
        self.assertEqual(order.items.get().price, Decimal('450'))
        self.assertEqual(order.payments.get().amount, Decimal('850'))
        self.shirt.refresh_from_db()
        self.assertEqual(self.shirt.stock_quantity, 8)

    def test_out_of_stock_rolls_back_everything(self):
        response = self.sell(items=[{'id': self.shirt.id, 'qty': 1}, {'id': self.cap.id, 'qty': 3}])
        self.assertEqual(response.status_code, 400)
        self.assertIn('স্টকে আছে মাত্র 2টা', response.json()['error'])
        self.shirt.refresh_from_db()
        self.assertEqual(self.shirt.stock_quantity, 10)           # আগের প্রোডাক্টের স্টকও আগের মতো
        self.assertFalse(Order.objects.filter(source='pos').exists())

    def test_split_payment_vat_and_duplicate_submit(self):
        self.shop.pos_vat_percent = Decimal('5')
        self.shop.save()
        payload = dict(ref='abc-123', items=[{'id': self.cap.id, 'qty': 2}],
                       payments=[{'method': 'bkash', 'amount': 200, 'reference': 'TRX1'},
                                 {'method': 'cash', 'amount': 300}])
        first = self.sell(**payload).json()
        self.assertTrue(first['success'], first)
        order = Order.objects.get(pk=first['sale']['id'])
        self.assertEqual((order.vat_amount, order.total_amount), (Decimal('19.95'), Decimal('418.95')))
        self.assertEqual((order.payment_method, order.change_given), ('Mixed', Decimal('81.05')))
        again = self.sell(**payload).json()                        # নেট কেটে আবার পাঠালে
        self.assertEqual(again['sale']['id'], order.id)
        self.assertFalse(again['created'])
        self.cap.refresh_from_db()
        self.assertEqual(self.cap.stock_quantity, 0)

    def test_due_needs_customer_and_can_be_collected(self):
        partial = dict(items=[{'id': self.shirt.id, 'qty': 2}], payments=[{'method': 'cash', 'amount': 500}])
        self.assertIn('বাকি', self.sell(**partial).json()['error'])
        self.assertIn('নাম আর মোবাইল', self.sell(allow_due=True, **partial).json()['error'])
        sale = self.sell(allow_due=True, customer={'name': 'রহিম', 'phone': '০১৭১২৩৪৫৬৭৮'}, **partial).json()
        self.assertEqual((sale['sale']['due'], sale['sale']['customer']), (400, 'রহিম'))
        info = self.client.get(reverse('pos_customer'), {'phone': '01712345678'}).json()['customer']
        self.assertEqual((info['name'], info['due'], info['orders']), ('রহিম', 400, 1))
        too_much = self.client.post(reverse('pos_collect_due'), data=json.dumps(
            {'phone': '01712345678', 'amount': 500, 'method': 'cash'}), content_type='application/json')
        self.assertIn('মাত্র ৳400', too_much.json()['error'])
        paid = self.client.post(reverse('pos_collect_due'), data=json.dumps(
            {'phone': '01712345678', 'amount': 400, 'method': 'bkash'}), content_type='application/json').json()
        self.assertEqual((paid['collected'], paid['due_left']), (400, 0))

    def test_owner_can_change_price_but_staff_cannot(self):
        owner = self.sell(items=[{'id': self.shirt.id, 'qty': 1, 'price': 400}]).json()
        self.assertEqual(owner['sale']['total'], 400)
        from .models import StaffProfile
        staff = User.objects.create_user(phone_number='01733333333', password='Staff-pass-1')
        StaffProfile.objects.create(user=staff, shop=self.shop, can_use_pos=True)
        self.client.force_login(staff)
        cashier = self.sell(items=[{'id': self.shirt.id, 'qty': 1, 'price': 1}]).json()
        self.assertEqual(cashier['sale']['total'], 450)
        self.assertEqual(Order.objects.get(pk=cashier['sale']['id']).served_by, staff)
        blocked = self.client.post(reverse('pos_return', args=[cashier['sale']['id']]), data='{}',
                                   content_type='application/json')
        self.assertEqual(blocked.status_code, 403)                # ফেরতের অনুমতি নেই

    def test_return_restocks_refunds_and_day_close_adds_up(self):
        from django.utils import timezone
        from .pos import day_summary
        sale = self.sell(items=[{'id': self.shirt.id, 'qty': 3}],
                         payments=[{'method': 'cash', 'amount': 2000, 'full': True}]).json()['sale']
        self.sell(items=[{'id': self.cap.id, 'qty': 1}], payments=[{'method': 'card', 'amount': 0, 'full': True}])
        back = self.client.post(reverse('pos_return', args=[sale['id']]), data=json.dumps({'reason': 'সাইজ'}),
                                content_type='application/json').json()
        self.assertEqual(back['refunded'], 1350)
        self.shirt.refresh_from_db()
        self.assertEqual(self.shirt.stock_quantity, 10)
        again = self.client.post(reverse('pos_return', args=[sale['id']]), data='{}', content_type='application/json')
        self.assertEqual(again.status_code, 400)
        summary = day_summary(self.shop, timezone.localdate())
        self.assertEqual((summary['count'], summary['net'], summary['returned_count']), (1, Decimal('199.50'), 1))
        self.assertEqual(summary['cash_in_drawer'], Decimal('0'))        # ১৩৫০ নিয়ে ১৩৫০ ফেরত
        self.assertEqual(summary['total_received'], Decimal('199.50'))   # শুধু কার্ডের বিক্রি রইল
        page = self.client.get(reverse('pos_day_close'))
        self.assertContains(page, 'দিনশেষের হিসাব')

    def give_back(self, sale_id, items=None, method=None):
        body = {'reason': 'সাইজ'}
        if items is not None:
            body['items'] = items
        if method:
            body['method'] = method
        return self.client.post(reverse('pos_return', args=[sale_id]), data=json.dumps(body),
                                content_type='application/json')

    def test_partial_return_keeps_discount_fair(self):
        from django.utils import timezone
        from .pos import day_summary
        sale = self.sell(items=[{'id': self.shirt.id, 'qty': 2}, {'id': self.cap.id, 'qty': 1}],
                         discount={'type': 'percent', 'value': 10}).json()['sale']
        self.assertEqual(sale['total'], 989.55)
        detail = self.client.get(reverse('pos_sale_detail', args=[sale['id']])).json()
        shirt_line = next(i for i in detail['items'] if i['product_id'] == self.shirt.id)
        self.assertEqual((shirt_line['qty'], shirt_line['unit_value']), (2, 405))     # ১০% ছাড় বাদে
        back = self.give_back(sale['id'], [{'item_id': shirt_line['item_id'], 'qty': 1}]).json()
        self.assertEqual((back['value'], back['refunded'], back['full']), (405, 405, False))
        order = Order.objects.get(pk=sale['id'])
        self.assertEqual((order.total_amount, order.discount, order.status), (Decimal('584.55'), Decimal('64.95'), 'Delivered'))
        self.assertEqual(order.items.get(product=self.shirt).quantity, 1)
        self.assertEqual(order.subtotal - order.discount, order.total_amount)
        self.shirt.refresh_from_db()
        self.assertEqual(self.shirt.stock_quantity, 9)
        too_many = self.give_back(sale['id'], [{'item_id': shirt_line['item_id'], 'qty': 2}])
        self.assertIn('সর্বোচ্চ 1টা', too_many.json()['error'])
        summary = day_summary(self.shop, timezone.localdate())
        self.assertEqual((summary['net'], summary['refunded'], summary['returned_count']),
                         (Decimal('584.55'), Decimal('405'), 1))
        receipt = self.client.get(reverse('pos_receipt', args=[sale['id']]))
        self.assertContains(receipt, 'শার্ট × 1')
        rest = self.give_back(sale['id']).json()                       # বাকি সব
        self.assertTrue(rest['full'])
        self.assertEqual(rest['refunded'], 584.55)
        self.assertEqual(Order.objects.get(pk=sale['id']).status, 'Returned')

    def test_return_on_due_sale_reduces_due_first(self):
        sale = self.sell(items=[{'id': self.shirt.id, 'qty': 2}], payments=[{'method': 'cash', 'amount': 500}],
                         allow_due=True, customer={'name': 'করিম', 'phone': '01811111111'}).json()['sale']
        item_id = self.client.get(reverse('pos_sale_detail', args=[sale['id']])).json()['items'][0]['item_id']
        back = self.give_back(sale['id'], [{'item_id': item_id, 'qty': 1}], method='bkash').json()
        self.assertEqual((back['value'], back['refunded']), (450, 50))     # ৪০০ বাকি কাটল, ৫০ ফেরত
        order = Order.objects.get(pk=sale['id'])
        self.assertEqual((order.total_amount, order.advance_paid, order.due_amount),
                         (Decimal('450'), Decimal('450'), Decimal('0')))
        self.assertEqual(order.payments.get(kind='refund').method, 'bkash')

    def test_pages_render(self):
        sale = self.sell(items=[{'id': self.shirt.id, 'qty': 1}],
                         payments=[{'method': 'cash', 'amount': 500, 'full': True}]).json()['sale']
        screen = self.client.get(reverse('pos'))
        self.assertContains(screen, 'id="pos-config"')
        self.assertNotContains(screen, 'cost_price')
        receipt = self.client.get(reverse('pos_receipt', args=[sale['id']]))
        self.assertContains(receipt, 'নগদ দিয়েছেন')
        self.assertContains(receipt, '৳450')
        found = self.client.get(reverse('pos_sales'), {'q': f"ORD-{sale['id']}"}).json()['sales']
        self.assertEqual([s['id'] for s in found], [sale['id']])
        scan = self.client.post(reverse('barcode_lookup'), data=json.dumps({'barcode': '111222333'}),
                                content_type='application/json').json()
        self.assertEqual(scan['product']['id'], self.shirt.id)


class StorefrontThemeTests(ShopTestMixin, TestCase):
    def test_seller_picks_theme_and_storefront_uses_it(self):
        _user, shop = self.make_shop(slug='themeshop')
        html = self.client.get('/shop/themeshop/', HTTP_HOST='localhost').content.decode()
        self.assertIn('--orange: #F57224', html)                     # ডিফল্ট কমলা
        page = self.client.get(reverse('website_settings') + '?tab=design').content.decode()
        self.assertIn('value="pink"', page)
        self.client.post(reverse('website_settings'), {'section': 'design', 'storefront_theme': 'pink',
                                                       'show_sold_count': 'on'})
        shop.refresh_from_db()
        self.assertEqual(shop.storefront_theme, 'pink')
        html = self.client.get('/shop/themeshop/', HTTP_HOST='localhost').content.decode()
        self.assertIn('--orange: #DB2777', html)
        self.assertNotIn('#FF8C42', html)

    def test_unknown_theme_rejected(self):
        _user, shop = self.make_shop(slug='themeshop2')
        self.client.post(reverse('website_settings'), {'section': 'design', 'storefront_theme': 'neon'})
        shop.refresh_from_db()
        self.assertEqual(shop.storefront_theme, 'orange')


@override_settings(FACEBOOK_WEBHOOK_VERIFY_TOKEN='verify-me', FACEBOOK_APP_SECRET='app-secret',
                   SITE_URL='https://sohojsell.onrender.com')
class FacebookCommentBotTests(ShopTestMixin, TestCase):
    PAGE = '111222333'

    def setUp(self):
        from django.core.cache import cache
        from .models import Product
        cache.clear()
        self.user, self.shop = self.make_shop(slug='fbshop')     # ট্রায়াল: Facebook চালু
        self.product = Product.objects.create(shop=self.shop, name='Three Piece', price=1450, compare_price=1800,
                                              cost_price=900, stock_quantity=4)
        self.conn = FacebookPageConnection.objects.create(shop=self.shop, page_id=self.PAGE, page_name='Munna Page',
                                                          page_access_token='PAGE-TOKEN')

    def _event(self, message='price?', comment='C1', sender='999', parent=None):
        post = f'{self.PAGE}_55'
        return {'object': 'page', 'entry': [{'id': self.PAGE, 'changes': [{'field': 'feed', 'value': {
            'item': 'comment', 'verb': 'add', 'comment_id': f'55_{comment}', 'post_id': post,
            'parent_id': parent or post, 'from': {'id': sender, 'name': 'Rahim Uddin'}, 'message': message}}]}]}

    def _post(self, payload, secret='app-secret'):
        import hashlib, hmac, json
        body = json.dumps(payload).encode()
        sig = 'sha256=' + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return self.client.post(reverse('facebook_webhook'), body, content_type='application/json',
                                HTTP_X_HUB_SIGNATURE_256=sig)

    def _fake_graph(self, post_text=''):
        calls = []

        def fake_post(url, params=None, timeout=None, **kwargs):
            calls.append((url, kwargs))
            return FakeResponse({'recipient_id': '1', 'message_id': 'm1'} if url.endswith('/messages') else {'id': 'r1'})

        def fake_get(url, params=None, timeout=None):
            return FakeResponse({'message': post_text})
        return calls, fake_post, fake_get

    def test_webhook_verification(self):
        ok = self.client.get(reverse('facebook_webhook'), {'hub.mode': 'subscribe', 'hub.verify_token': 'verify-me',
                                                           'hub.challenge': '12345'})
        self.assertEqual((ok.status_code, ok.content), (200, b'12345'))
        bad = self.client.get(reverse('facebook_webhook'), {'hub.mode': 'subscribe', 'hub.verify_token': 'nope',
                                                            'hub.challenge': '12345'})
        self.assertEqual(bad.status_code, 403)

    def test_bad_signature_rejected(self):
        self.assertEqual(self._post(self._event(), secret='wrong').status_code, 403)

    def test_comment_gets_private_reply_with_product_from_post_code(self):
        from .models import FacebookCommentReply
        calls, fake_post, fake_get = self._fake_graph(post_text=f'নতুন থ্রি পিস 🔥 কোড #P{self.product.id}')
        with mock.patch('store.facebook_bot.requests.post', fake_post), \
                mock.patch('store.facebook_bot.requests.get', fake_get):
            self.assertEqual(self._post(self._event()).status_code, 200)
            self._post(self._event())                                   # Meta আবার পাঠালেও একবারই
            self._post(self._event(comment='C2'))                       # একই মানুষ, একই পোস্ট, আরেক কমেন্ট
        private = [c for c in calls if c[0].endswith(f'{self.PAGE}/messages')]
        self.assertEqual(len(private), 1)
        payload = private[0][1]['json']
        self.assertEqual(payload['recipient'], {'comment_id': '55_C1'})
        text = payload['message']['text']
        self.assertIn('Three Piece', text)
        self.assertIn('৳1,450', text)
        self.assertIn(f'https://sohojsell.onrender.com/shop/fbshop/product/{self.product.id}/', text)
        self.assertIn('Rahim', text)
        self.assertEqual(len([c for c in calls if c[0].endswith('55_C1/comments')]), 1)    # "ইনবক্স চেক করুন"
        record = FacebookCommentReply.objects.get(comment_id='55_C1')
        self.assertEqual((record.status, record.product), ('sent', self.product))

    def test_without_code_sends_shop_link_and_respects_toggles(self):
        calls, fake_post, fake_get = self._fake_graph(post_text='অফার চলছে!')
        self.conn.public_reply_enabled = False
        self.conn.save()
        with mock.patch('store.facebook_bot.requests.post', fake_post), \
                mock.patch('store.facebook_bot.requests.get', fake_get):
            self._post(self._event(message='dam koto'))
        self.assertIn('https://sohojsell.onrender.com/shop/fbshop/', calls[0][1]['json']['message']['text'])
        self.assertFalse([c for c in calls if c[0].endswith('/comments')])

        self.conn.comment_bot_enabled = False
        self.conn.save()
        calls.clear()
        with mock.patch('store.facebook_bot.requests.post', fake_post), \
                mock.patch('store.facebook_bot.requests.get', fake_get):
            self._post(self._event(comment='C9', sender='777'))
        self.assertEqual(calls, [])

    def test_ignores_page_own_comments_replies_and_basic_plan(self):
        calls, fake_post, fake_get = self._fake_graph()
        with mock.patch('store.facebook_bot.requests.post', fake_post), \
                mock.patch('store.facebook_bot.requests.get', fake_get):
            self._post(self._event(sender=self.PAGE))                          # পেইজের নিজের
            self._post(self._event(comment='C3', parent='55_C1'))              # কারো কমেন্টের রিপ্লাই
            self.shop.subscription_plan = 'Basic'
            self.shop.valid_until = timezone.localdate() + timedelta(days=10)
            self.shop.save()
            self._post(self._event(comment='C4', sender='888'))                # Basic-এ Facebook নেই
        self.assertEqual(calls, [])

    def test_product_code_matching(self):
        from .facebook_bot import find_product
        pid = self.product.id
        self.assertEqual(find_product(self.shop, f'P{pid} er dam?'), self.product)
        self.assertEqual(find_product(self.shop, f'code: #p-{pid}'), self.product)
        self.assertIsNone(find_product(self.shop, 'pp', 'app 12', f'SP{pid}'))


def _png_bytes():
    from io import BytesIO
    from PIL import Image
    buf = BytesIO()
    Image.new('RGB', (40, 20), (200, 80, 40)).save(buf, format='PNG')
    return buf.getvalue()


class StorefrontCheckoutTests(ShopTestMixin, TestCase):
    """আসল ব্রাউজারের মতো CSRF চালু রেখে অর্ডার, ডেলিভারি এলাকা আর চার্জ।"""

    def setUp(self):
        from .models import Product
        self.user, self.shop = self.make_shop(slug='coshop')
        self.product = Product.objects.create(shop=self.shop, name='Kurti', price=850, cost_price=500, stock_quantity=4)
        self.client.logout()

    def _order(self, client, **extra):
        import json
        body = {'cart': [{'id': self.product.id, 'qty': 2}], 'name': 'Rahim', 'phone': '০১৮১২-৩৪৫৬৭৮',
                'address': 'Road 2, Savar', **extra}
        token = client.cookies['csrftoken'].value if 'csrftoken' in client.cookies else ''
        return client.post('/shop/coshop/place-order/', json.dumps(body), content_type='application/json',
                           HTTP_HOST='localhost', HTTP_X_CSRFTOKEN=token)

    def test_real_browser_order_passes_csrf(self):
        from django.test import Client
        from .delivery import zones_for
        browser = Client(enforce_csrf_checks=True)
        home = browser.get('/shop/coshop/', HTTP_HOST='localhost')
        self.assertIn('csrftoken', browser.cookies)               # আগে এটাই ছিল না, তাই সব অর্ডার 403
        html = home.content.decode()
        self.assertIn('ঢাকার বাইরে', html)
        self.assertNotIn('const DELIVERY = 80', html)
        outside = zones_for(self.shop)[1]
        data = self._order(browser, zone=outside.id).json()
        self.assertTrue(data['success'], data)
        from .models import StorefrontOrder
        sf = StorefrontOrder.objects.get(pk=data['order_id'])
        self.assertEqual((sf.delivery_charge, sf.delivery_zone, sf.total_amount), (Decimal('120'), 'ঢাকার বাইরে', Decimal('1820')))
        self.assertEqual(sf.customer_phone, '01812345678')          # বাংলা সংখ্যাও ঠিক হয়ে যায়
        self.assertEqual((sf.order.source, sf.order.total_amount, sf.order.delivery_charge), ('storefront', Decimal('1820'), Decimal('120')))
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 2)
        page = browser.get(data['redirect'], HTTP_HOST='localhost').content.decode()
        self.assertIn(f'ORD-{sf.order.id}', page)
        self.assertIn('ক্যাশ অন ডেলিভারি', page)

    def test_zone_from_another_shop_or_missing_is_rejected(self):
        from .delivery import zones_for
        _u, other = self.make_shop(phone='01799990000', slug='othershop')
        self.client.logout()
        data = self._order(self.client, zone=zones_for(other)[0].id).json()
        self.assertFalse(data['success'])
        self.assertFalse(self._order(self.client).json()['success'])
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 4)

    def test_free_delivery_threshold_and_bad_phone(self):
        from .delivery import zones_for
        self.shop.free_delivery_min = Decimal('1500')
        self.shop.save()
        data = self._order(self.client, zone=zones_for(self.shop)[1].id).json()
        from .models import StorefrontOrder
        self.assertEqual(StorefrontOrder.objects.get(pk=data['order_id']).delivery_charge, Decimal('0'))
        bad = self._order(self.client, zone=zones_for(self.shop)[0].id, phone='12345').json()
        self.assertFalse(bad['success'])

    def test_cannot_pick_online_when_shop_is_cod_only(self):
        from .delivery import zones_for
        data = self._order(self.client, zone=zones_for(self.shop)[0].id, payment='full').json()
        self.assertFalse(data['success'])

    def test_more_than_stock_is_rejected(self):
        import json
        from .delivery import zones_for
        response = self.client.post('/shop/coshop/place-order/', json.dumps({
            'cart': [{'id': self.product.id, 'qty': 9}], 'name': 'X', 'phone': '01812345678', 'address': 'Savar',
            'zone': zones_for(self.shop)[0].id}), content_type='application/json', HTTP_HOST='localhost')
        self.assertFalse(response.json()['success'])


@override_settings(PAYSTATION_TEST_SHOPS=['payshop'], STOREFRONT_PAYMENT_FEE_PERCENT='2')
class StorefrontOnlinePaymentTests(ShopTestMixin, TestCase):
    def setUp(self):
        from .models import Product
        self.user, self.shop = self.make_shop(slug='payshop', payment_rule='advance_delivery',
                                              payout_method='bKash', payout_account='01711111111')
        self.product = Product.objects.create(shop=self.shop, name='Saree', price=1000, cost_price=700, stock_quantity=5)
        self.client.logout()

    def _place(self, payment):
        import json
        from .delivery import zones_for
        with mock.patch('store.paystation.initiate_payment',
                        return_value={'ok': True, 'payment_url': 'https://sandbox.paystation.com.bd/pay/abc'}) as init:
            response = self.client.post('/shop/payshop/place-order/', json.dumps({
                'cart': [{'id': self.product.id, 'qty': 1}], 'name': 'Karim', 'phone': '01811111111',
                'address': 'Savar', 'zone': zones_for(self.shop)[0].id, 'payment': payment}),
                content_type='application/json', HTTP_HOST='localhost')
        return response.json(), init

    def _verify(self, amount, status='success'):
        return mock.patch('store.paystation.verify_transaction', return_value={
            'status': status, 'amount': Decimal(amount), 'trx_id': 'TRX123', 'payment_method': 'bKash'})

    def test_delivery_advance_then_courier_collects_rest(self):
        from .couriers import cod_amount
        from .models import StorefrontPayment
        data, init = self._place('advance')
        self.assertEqual(data['redirect'], 'https://sandbox.paystation.com.bd/pay/abc')
        payment = StorefrontPayment.objects.get()
        self.assertEqual((payment.amount, payment.kind, payment.fee_amount, payment.net_amount),
                         (Decimal('60.00'), 'advance', Decimal('1.20'), Decimal('58.80')))
        self.assertIn('/shop/payshop/payment/return/?inv=SF-', init.call_args.kwargs['callback_url'])
        order = payment.order
        self.assertEqual(order.online_payment_status, 'pending')

        with self._verify('60'):
            back = self.client.get(f'/shop/payshop/payment/return/?inv={payment.invoice_number}&status=Successful',
                                   HTTP_HOST='localhost')
        page = self.client.get(back['Location'], HTTP_HOST='localhost').content.decode()
        self.assertIn('বাকি ৳1000 পণ্য হাতে পেয়ে', page)
        order.refresh_from_db()
        self.assertEqual((order.advance_paid, order.online_payment_status, order.status, order.payment_method),
                         (Decimal('60.00'), 'paid', 'Confirmed', 'COD'))
        self.assertEqual(cod_amount(order), 1000)

    def test_full_payment_via_ipn_makes_order_prepaid(self):
        from .couriers import cod_amount
        from .models import StorefrontPayment
        self._place('full')
        payment = StorefrontPayment.objects.get()
        self.assertEqual(payment.amount, Decimal('1060.00'))
        with self._verify('1060'):
            response = self.client.post(reverse('paystation_ipn'), {'invoice_number': payment.invoice_number})
        self.assertEqual(response.status_code, 200)
        payment.refresh_from_db()
        order = payment.order
        self.assertEqual((payment.status, order.payment_method, cod_amount(order)), ('Completed', 'Paid', 0))
        from .shop_payments import balance_summary
        self.assertEqual(balance_summary(self.shop)['due'], Decimal('1038.80'))

    def test_amount_mismatch_and_failed_payment_can_retry(self):
        from .models import StorefrontPayment
        data, _ = self._place('advance')
        payment = StorefrontPayment.objects.get()
        with self._verify('10'):
            self.client.get(f'/shop/payshop/payment/return/?inv={payment.invoice_number}', HTTP_HOST='localhost')
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'Pending')
        self.client.get(f'/shop/payshop/payment/return/?inv={payment.invoice_number}&status=Cancelled',
                        HTTP_HOST='localhost')
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'Failed')
        with self._verify('0', status='failed'):
            page = self.client.get(f'/shop/payshop/order/{payment.sf_order_id}/success/', HTTP_HOST='localhost')
        self.assertIn('৳60 পেমেন্ট করুন', page.content.decode())
        with mock.patch('store.paystation.initiate_payment',
                        return_value={'ok': True, 'payment_url': 'https://sandbox.paystation.com.bd/pay/again'}):
            retry = self.client.post(f'/shop/payshop/order/{payment.sf_order_id}/pay/', HTTP_HOST='localhost')
        self.assertEqual(retry['Location'], 'https://sandbox.paystation.com.bd/pay/again')
        self.assertEqual(StorefrontPayment.objects.count(), 2)

    def test_gateway_off_means_cash_on_delivery_only(self):
        with override_settings(PAYSTATION_TEST_SHOPS=[]):
            html = self.client.get('/shop/payshop/', HTTP_HOST='localhost').content.decode()
            self.assertNotIn('value="advance"', html)
            data, init = self._place('cod')
            self.assertTrue(data['success'])
            init.assert_not_called()

    def test_master_records_payout_and_seller_sees_balance(self):
        from .models import ShopPayout, StorefrontPayment
        self._place('full')
        payment = StorefrontPayment.objects.get()
        with self._verify('1060'):
            self.client.post(reverse('paystation_ipn'), {'invoice_number': payment.invoice_number})
        admin = User.objects.create_superuser(phone_number='01900000009', password='admin-pass-1')
        self.client.force_login(admin)
        page = self.client.get(reverse('master_settlements')).content.decode()
        self.assertIn('1039', page)
        self.client.post(reverse('master_settlements'), {'shop_id': self.shop.pk, 'amount': '5000'})
        self.assertFalse(ShopPayout.objects.exists())                 # পাওনার বেশি না
        self.client.post(reverse('master_settlements'), {'shop_id': self.shop.pk, 'amount': '1000', 'reference': 'BK1'})
        self.assertEqual(ShopPayout.objects.get().amount, Decimal('1000'))
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('master_settlements')).status_code, 302)
        seller_page = self.client.get(reverse('website_settings') + '?tab=payment').content.decode()
        self.assertIn('৳৩৯', seller_page)                              # বাকি ৩৯ টাকা ৭ দিনের অপেক্ষায়


class WebsiteSettingsTests(ShopTestMixin, TestCase):
    def setUp(self):
        self.user, self.shop = self.make_shop(slug='webshop')

    def _post(self, data, files=None):
        return self.client.post(reverse('website_settings'), {**data, **(files or {})})

    def test_every_tab_opens(self):
        for tab in ['store', 'design', 'banners', 'categories', 'delivery', 'payment', 'contact']:
            response = self.client.get(reverse('website_settings') + f'?tab={tab}')
            self.assertEqual(response.status_code, 200, tab)
        self.assertRedirects(self.client.get('/banners/'), '/website/?tab=banners', fetch_redirect_response=False)
        self.assertRedirects(self.client.get('/categories/'), '/website/?tab=categories', fetch_redirect_response=False)

    def test_store_design_and_contact_save_separately(self):
        self._post({'section': 'store', 'name': 'Munna Fashion', 'phone': '01711111111', 'address': 'Savar',
                    'subdomain': 'webshop'})
        self._post({'section': 'design', 'storefront_theme': 'green', 'announcement_text': 'ঈদ অফার চলছে',
                    'storefront_tagline': 'খাঁটি সুতি'})
        self._post({'section': 'contact', 'whatsapp_number': '০১৭১২-৩৪৫৬৭৮', 'return_policy': '৩ দিনে বদল'})
        self.shop.refresh_from_db()
        self.assertEqual((self.shop.name, self.shop.storefront_theme, self.shop.whatsapp_number),
                         ('Munna Fashion', 'green', '8801712345678'))
        html = self.client.get('/shop/webshop/', HTTP_HOST='localhost').content.decode()
        for text in ['ঈদ অফার চলছে', 'wa.me/8801712345678', 'রিটার্ন<br>পলিসি']:
            self.assertIn(text, html)
        self.assertNotIn('14 Days', html)
        self.assertNotIn('coming soon', html)
        bad = self._post({'section': 'contact', 'whatsapp_number': '12345'})
        self.assertEqual(bad.status_code, 200)

    def test_banners_upload_toggle_delete(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from .models import Banner
        self._post({'section': 'banner_add', 'title': 'Eid'},
                   {'image': SimpleUploadedFile('b.png', _png_bytes(), content_type='image/png')})
        banner = Banner.objects.get(shop=self.shop)
        self.assertEqual(self.client.get(reverse('website_banner_delete', args=[banner.pk])).status_code, 405)
        self.client.post(reverse('website_banner_toggle', args=[banner.pk]))
        banner.refresh_from_db()
        self.assertFalse(banner.is_active)
        self.client.post(reverse('website_banner_delete', args=[banner.pk]))
        self.assertFalse(Banner.objects.exists())

    def test_categories_add_rename_delete_keeps_products(self):
        from .models import Category, Product
        self._post({'section': 'category_add', 'name': '  শাড়ি  '})
        self._post({'section': 'category_add', 'name': 'শাড়ি'})          # একই নাম দুবার না
        category = Category.objects.get(shop=self.shop)
        product = Product.objects.create(shop=self.shop, category=category, name='P', price=10, cost_price=5)
        self.client.post(reverse('website_category_rename', args=[category.pk]), {'name': 'জামদানি'})
        category.refresh_from_db()
        self.assertEqual(category.name, 'জামদানি')
        self.client.post(reverse('website_category_delete', args=[category.pk]))
        product.refresh_from_db()
        self.assertIsNone(product.category)

    def test_delivery_zones_and_last_zone_cannot_be_deleted(self):
        from .delivery import zones_for
        from .models import DeliveryZone
        zones = zones_for(self.shop)
        self._post({'section': 'zone_add', 'name': 'সাভার', 'charge': '80', 'is_active': 'on'})
        self.client.post(reverse('website_zone_update', args=[zones[0].pk]), {'name': 'ঢাকা সিটি', 'charge': '70', 'is_active': 'on'})
        zones[0].refresh_from_db()
        self.assertEqual((zones[0].name, zones[0].charge), ('ঢাকা সিটি', Decimal('70')))
        for zone in DeliveryZone.objects.filter(shop=self.shop):
            self.client.post(reverse('website_zone_delete', args=[zone.pk]))
        self.assertEqual(DeliveryZone.objects.filter(shop=self.shop).count(), 1)
        self._post({'section': 'delivery', 'free_delivery_min': '2000'})
        self.shop.refresh_from_db()
        self.assertEqual(self.shop.free_delivery_min, Decimal('2000'))

    def test_online_payment_rule_needs_payout_account(self):
        self._post({'section': 'payment', 'online_enabled': 'on', 'payment_rule': 'online_only'})
        self.shop.refresh_from_db()
        self.assertEqual(self.shop.payment_rule, 'cod')
        self._post({'section': 'payment', 'online_enabled': 'on', 'payment_rule': 'online_only', 'payout_method': 'bKash',
                    'payout_account': '01712345678', 'payout_account_name': 'Munna'})
        self.shop.refresh_from_db()
        self.assertEqual(self.shop.payment_rule, 'online_only')

    def test_online_switch_off_means_cash_on_delivery_only(self):
        from . import shop_payments
        Shop.objects.filter(pk=self.shop.pk).update(payment_rule='advance_delivery', payout_method='bKash',
                                                    payout_account='01712345678')
        self.assertIn('অনলাইনে পেমেন্ট নিন', self.client.get(reverse('website_settings') + '?tab=payment').content.decode())
        self._post({'section': 'payment', 'payment_rule': 'advance_delivery', 'payout_method': 'bKash',
                    'payout_account': '01712345678'})                     # সুইচ বন্ধ
        self.shop.refresh_from_db()
        self.assertEqual(self.shop.payment_rule, 'cod')
        with override_settings(PAYSTATION_TEST_SHOPS=[self.shop.slug]):
            self.assertEqual(shop_payments.checkout_choices(self.shop), ['cod'])
            self._post({'section': 'payment', 'online_enabled': 'on', 'payout_method': 'bKash',
                        'payout_account': '01712345678'})                 # চালু, নিয়ম না বাছলে কাস্টমার বেছে নেবে
            self.shop.refresh_from_db()
            self.assertEqual(shop_payments.checkout_choices(self.shop), ['cod', 'full'])

    def test_staff_without_settings_permission_blocked(self):
        from .models import StaffProfile
        staff_user = User.objects.create_user(phone_number='01811112222', password='staff-pass-1')
        StaffProfile.objects.create(user=staff_user, shop=self.shop, can_manage_settings=False)
        self.client.force_login(staff_user)
        self.assertRedirects(self.client.get(reverse('website_settings')), reverse('dashboard'),
                             fetch_redirect_response=False)


@override_settings(PAYSTATION_TEST_SHOPS=['postshop'])
class PaymentReturnByPostTests(ShopTestMixin, TestCase):
    def test_gateway_post_back_is_not_blocked_by_csrf(self):
        import json
        from django.test import Client
        from .delivery import zones_for
        from .models import Product, StorefrontPayment
        _u, shop = self.make_shop(slug='postshop', payment_rule='online_only', payout_method='bKash',
                                  payout_account='01711111111')
        product = Product.objects.create(shop=shop, name='Bag', price=500, cost_price=300, stock_quantity=3)
        browser = Client(enforce_csrf_checks=True)
        browser.get('/shop/postshop/', HTTP_HOST='localhost')
        with mock.patch('store.paystation.initiate_payment', return_value={'ok': True, 'payment_url': 'https://x/pay'}):
            browser.post('/shop/postshop/place-order/', json.dumps({
                'cart': [{'id': product.id, 'qty': 1}], 'name': 'A', 'phone': '01811111111', 'address': 'Savar',
                'zone': zones_for(shop)[0].id, 'payment': 'full'}), content_type='application/json',
                HTTP_HOST='localhost', HTTP_X_CSRFTOKEN=browser.cookies['csrftoken'].value)
        payment = StorefrontPayment.objects.get()
        with mock.patch('store.paystation.verify_transaction', return_value={
                'status': 'success', 'amount': payment.amount, 'trx_id': 'T1', 'payment_method': 'Nagad'}):
            response = browser.post(f'/shop/postshop/payment/return/?inv={payment.invoice_number}',
                                    {'status': 'Successful', 'trx_id': 'T1'}, HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 302)
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'Completed')


class DashboardTests(ShopTestMixin, TestCase):
    """ড্যাশবোর্ড: আজকের বিক্রি-লাভ (ডেলিভারি চার্জ বাদে), ঢাকার দিন ধরে চার্ট, স্টাফের অনুমতি, সেটআপের ধাপ।"""

    def setUp(self):
        from .models import Customer, Product
        self.user, self.shop = self.make_shop()
        self.shirt = Product.objects.create(shop=self.shop, name='শার্ট', price=Decimal('450'), cost_price=300,
                                            stock_quantity=10)
        self.customer = Customer.objects.create(shop=self.shop, name='রহিম', phone='01812345678', address='Savar')

    def order(self, *, source='storefront', status='Pending', qty=1, delivery=0, discount=0, when=None, cost=300):
        order = Order.objects.create(shop=self.shop, customer=self.customer, source=source, status=status,
                                     delivery_charge=delivery, discount=discount,
                                     total_amount=Decimal('450') * qty + delivery - discount)
        OrderItem.objects.create(order=order, product=self.shirt, price=Decimal('450'), quantity=qty, cost_price=cost)
        if when is not None:
            Order.objects.filter(pk=order.pk).update(created_at=when)
        return order

    def test_today_sales_profit_and_change(self):
        from . import dashboard
        now = timezone.now()
        self.order(source='pos', status='Delivered', qty=2, discount=50)          # ৮৫০, লাভ ২৫০
        self.order(delivery=60)                                                   # ৪৫০ (+৬০ ডেলিভারি), লাভ ১৫০
        self.order(status='Cancelled', qty=5)                                     # ধরা হবে না
        self.order(source='pos', status='Delivered', when=now - timedelta(days=1), qty=2, discount=250)  # গতকাল ৬৫০
        numbers = dashboard.today_numbers(self.shop, timezone.localdate())
        self.assertEqual((numbers['sales'], numbers['sales_pos'], numbers['sales_online']),
                         (Decimal('1300'), Decimal('850'), Decimal('450')))
        self.assertEqual(numbers['profit'], Decimal('400'))
        self.assertEqual(numbers['sales_change'], {'dir': 'up', 'text': '১০০%'})
        self.assertFalse(numbers['profit_missing_cost'])
        self.order(source='pos', status='Delivered', cost=0)
        self.assertTrue(dashboard.today_numbers(self.shop, timezone.localdate())['profit_missing_cost'])

    def test_chart_uses_dhaka_day(self):
        from datetime import date, datetime, timezone as dt_timezone
        from . import dashboard
        # ঢাকায় ১০ নভেম্বর রাত ১:৩০ = UTC-তে ৯ নভেম্বর সন্ধ্যা ৭:৩০
        self.order(source='pos', status='Delivered', when=datetime(2026, 11, 9, 19, 30, tzinfo=dt_timezone.utc))
        self.order(when=datetime(2026, 11, 4, 8, 0, tzinfo=dt_timezone.utc))
        chart = dashboard.sales_chart(self.shop, date(2026, 11, 10), 7)
        self.assertEqual(len(chart['bars']), 7)
        self.assertEqual(chart['bars'][-1]['pos'], Decimal('450'))
        self.assertTrue(chart['bars'][-1]['is_today'])
        self.assertEqual(chart['bars'][0]['online'], Decimal('450'))
        self.assertEqual(chart['total'], Decimal('900'))
        self.assertEqual(chart['bars'][-1]['top_pct'], 90.0)        # সবচেয়ে উঁচু দাগ ৫০০
        self.assertEqual(len(dashboard.sales_chart(self.shop, date(2026, 11, 10), 30)['bars']), 30)

    def test_page_is_bangla_and_lists_work_to_do(self):
        self.order(delivery=60)
        self.order(source='pos', status='Delivered', qty=2)
        self.shirt.stock_quantity = 0
        self.shirt.save()
        html = self.client.get(reverse('dashboard')).content.decode()
        for text in ['আজকের বিক্রি', 'আজকের লাভ', 'এখন যা করতে হবে', '১টা নতুন অর্ডার কনফার্ম করুন',
                     '১টা প্রোডাক্ট স্টকে নেই', 'বিক্রির হিসাব', 'সাম্প্রতিক অর্ডার ও বিক্রি', '৳1,350', 'রহিম']:
            self.assertIn(text, html)
        for english in ['Welcome back', 'Recent Orders', 'No orders yet', "Today's Sales"]:
            self.assertNotIn(english, html)
        self.assertEqual(self.client.get(reverse('dashboard') + '?days=30').status_code, 200)
        self.assertEqual(self.client.get(reverse('dashboard') + '?days=abc').status_code, 200)

    def test_staff_without_report_permission_sees_no_money(self):
        from .models import StaffProfile
        self.order(source='pos', status='Delivered')
        staff = User.objects.create_user(phone_number='01922222222', password='Test-pass-123', name='Karim')
        StaffProfile.objects.create(user=staff, shop=self.shop, can_use_pos=True)
        self.client.force_login(staff)
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('দোকানে বিক্রি', html)
        for hidden in ['আজকের লাভ', 'আজকের বিক্রি', 'বিক্রির হিসাব', 'দোকান পুরোপুরি চালু করুন', reverse('billing')]:
            self.assertNotIn(hidden, html)

    def test_setup_steps_disappear_when_done(self):
        from .models import Banner
        from . import dashboard
        Order.objects.all().delete()
        self.assertIn('দোকান পুরোপুরি চালু করুন', self.client.get(reverse('dashboard')).content.decode())
        Shop.objects.filter(pk=self.shop.pk).update(logo='shop_logos/logo.png', steadfast_api_key='k',
                                                    steadfast_secret_key='s')
        Banner.objects.create(shop=self.shop, image='banners/b.jpg')
        self.order(source='pos', status='Delivered')
        self.shop.refresh_from_db()
        steps = dashboard.setup_steps(self.shop, plan_has_facebook=False)
        self.assertTrue(steps['complete'], steps)
        self.assertEqual(dashboard.setup_steps(self.shop, plan_has_facebook=True)['next']['key'], 'facebook')

    def test_small_helpers(self):
        from . import dashboard
        now = timezone.now()
        self.assertEqual(dashboard.bn_ago(now - timedelta(seconds=20), now), 'এইমাত্র')
        self.assertEqual(dashboard.bn_ago(now - timedelta(minutes=12), now), '১২ মিনিট আগে')
        self.assertEqual(dashboard.short_taka(1500), '1.5 হাজার')
        self.assertEqual(dashboard.short_taka(250000), '2.5 লাখ')
        self.assertEqual(dashboard.nice_ceiling(3740), 4000)
        self.assertEqual(dashboard.nice_ceiling(12300), 15000)


class SmsPanelTests(ShopTestMixin, TestCase):
    """SMS প্যানেল: ঠিক খরচ (বাংলা ৭০/৬৭), ব্যালেন্স আগে কাটা আর যা যায়নি তা ফেরত, কাদের পাঠানো হবে, কেনা, অনুমতি।"""

    def setUp(self):
        from .models import Customer
        self.user, self.shop = self.make_shop()
        Shop.objects.filter(pk=self.shop.pk).update(sms_balance=100)
        self.rahim = Customer.objects.create(shop=self.shop, name='রহিম', phone='01812345678', address='Savar')

    def balance(self):
        return Shop.objects.values_list('sms_balance', flat=True).get(pk=self.shop.pk)

    def order(self, customer, days_ago=0, **extra):
        order = Order.objects.create(shop=self.shop, customer=customer, total_amount=Decimal('500'), **extra)
        Order.objects.filter(pk=order.pk).update(created_at=timezone.now() - timedelta(days=days_ago))
        return order

    def test_cost_and_numbers(self):
        from . import sms
        self.assertEqual([sms.segments('a' * n) for n in (1, 160, 161, 306, 307)], [1, 1, 2, 2, 3])
        self.assertEqual([sms.segments('অ' * n) for n in (70, 71, 134, 135)], [1, 2, 2, 3])
        self.assertEqual(sms.segments('Hi €'), 1)                     # ইউনিকোড ধরা হয় (সাবধানী হিসাব)
        self.assertEqual(sms.segments('a' * 159 + '€'), 3)
        good, bad = sms.split_phone_text('01712345678, +880 1812-345678\n০১৯১২৩৪৫৬৭৮ 01712345678; 12345')
        self.assertEqual(good, ['01712345678', '01812345678', '01912345678'])
        self.assertEqual(bad, ['12345'])
        self.assertEqual(sms.count_for_amount(200), 500)
        self.assertEqual(sms.parse_buy_amount('১,০০০'), (1000, ''))
        self.assertIsNone(sms.parse_buy_amount('20')[0])

    def test_charges_first_and_refunds_what_failed(self):
        from . import sms
        from .models import SmsLog
        calls = []

        def gateway(batch, message):
            calls.append(list(batch))
            return (False, 'বন্ধ নম্বর') if len(calls) == 2 else (True, 'ok')

        with mock.patch.object(sms, 'GATEWAY_BATCH', 2):
            result = sms.send(self.shop, ['01711111111', '01722222222', '01733333333', '01711111111'],
                              'অ' * 80, 'test', sender=gateway, background=False)
        self.assertTrue(result.ok)
        self.assertEqual((result.recipients, result.delivered, result.failed, result.charged), (3, 2, 1, 4))
        self.assertEqual(self.balance(), 96)
        log = SmsLog.objects.get()
        self.assertEqual((log.status, log.sms_used, log.delivered, log.failed), (SmsLog.PARTIAL, 4, 2, 1))
        self.assertEqual(calls, [['01711111111', '01722222222'], ['01733333333']])

    def test_not_enough_balance_sends_nothing(self):
        from . import sms
        from .models import SmsLog
        Shop.objects.filter(pk=self.shop.pk).update(sms_balance=1)
        gateway = mock.Mock(return_value=(True, 'ok'))
        result = sms.send(self.shop, ['01711111111', '01722222222'], 'hello', 'test', sender=gateway)
        self.assertFalse(result.ok)
        self.assertEqual(result.needed, 2)
        self.assertEqual(self.balance(), 1)
        gateway.assert_not_called()
        self.assertFalse(SmsLog.objects.exists())

    def test_gateway_down_refunds_everything(self):
        from . import sms
        result = sms.send(self.shop, ['01711111111'], 'hello', 'test', sender=lambda b, m: (False, 'down'))
        self.assertFalse(result.ok)
        self.assertEqual(self.balance(), 100)

    def test_audiences(self):
        from . import sms
        from .models import Customer
        from .pos import WALK_IN_PHONE
        old = Customer.objects.create(shop=self.shop, name='Old', phone='01911111111', address='-')
        due = Customer.objects.create(shop=self.shop, name='Due', phone='01611111111', address='-')
        walk_in = Customer.objects.create(shop=self.shop, name='Walk-in', phone=WALK_IN_PHONE, address='-')
        Customer.objects.create(shop=self.shop, name='রহিম আবার', phone='+8801812345678', address='-')   # একই নম্বর
        self.order(self.rahim, days_ago=3)
        self.order(old, days_ago=120)
        self.order(due, days_ago=40, source='pos', status='Delivered', advance_paid=Decimal('300'))
        self.order(walk_in, days_ago=1, source='pos', status='Delivered', advance_paid=Decimal('500'))
        self.assertEqual(sorted(sms.audience_phones(self.shop, 'all')), ['01611111111', '01812345678', '01911111111'])
        self.assertEqual(sms.audience_phones(self.shop, 'recent'), ['01812345678'])
        self.assertEqual(sms.audience_phones(self.shop, 'inactive'), ['01911111111'])
        self.assertEqual(sms.audience_phones(self.shop, 'due'), ['01611111111'])
        self.assertEqual(sms.search_customers(self.shop, 'রহি'), [{'name': 'রহিম আবার', 'phone': '01812345678'}])

    def test_panel_send_and_double_submit(self):
        page = self.client.get(reverse('sms_panel'))
        self.assertEqual(page.status_code, 200)
        html = page.content.decode()
        for text in ['SMS প্যানেল', 'কাকে পাঠাবেন?', 'সব কাস্টমার', 'SMS কিনুন', 'ওয়েবসাইটের অর্ডারে অটো SMS']:
            self.assertIn(text, html)
        data = {'audience': 'all', 'message': 'নতুন কালেকশন এসেছে!', 'sign': 'on', 'send_id': 'abc123'}
        with mock.patch('store.sms.gateway_send', return_value=(True, 'ok')) as gateway:
            response = self.client.post(reverse('sms_send'), data)
            self.client.post(reverse('sms_send'), data)                        # দুইবার চাপ
        self.assertRedirects(response, reverse('sms_panel') + '#history', fetch_redirect_response=False)
        self.assertEqual(gateway.call_count, 1)
        self.assertEqual(gateway.call_args[0], (['01812345678'], f'নতুন কালেকশন এসেছে!\n- {self.shop.name}'))
        self.assertEqual(self.balance(), 99)
        self.assertIn('১ জনকে SMS পাঠানো হয়েছে', self.client.get(reverse('sms_panel')).content.decode())

    def test_wrong_number_sends_nothing_and_keeps_draft(self):
        with mock.patch('store.sms.gateway_send') as gateway:
            response = self.client.post(reverse('sms_send'), {
                'audience': 'manual', 'numbers': '01712345678, 0171234', 'message': 'আসসালামু আলাইকুম'})
        gateway.assert_not_called()
        self.assertEqual(self.balance(), 100)
        html = self.client.get(response.url).content.decode()
        self.assertIn('এই নম্বরগুলো ঠিক নেই: 0171234', html)
        self.assertIn('আসসালামু আলাইকুম</textarea>', html)

    def test_customer_link_prefills_number(self):
        html = self.client.get(reverse('sms_panel') + '?to=01812345678').content.decode()
        self.assertIn('>01812345678</textarea>', html)

    def test_staff_needs_sms_permission(self):
        from .models import StaffProfile
        staff = User.objects.create_user(phone_number='01922222222', password='Test-pass-123', name='Karim')
        profile = StaffProfile.objects.create(user=staff, shop=self.shop, can_use_pos=True)
        self.client.force_login(staff)
        self.assertRedirects(self.client.get(reverse('sms_panel')), reverse('dashboard'), fetch_redirect_response=False)
        profile.can_send_sms = True
        profile.save()
        html = self.client.get(reverse('sms_panel')).content.decode()
        self.assertIn('SMS কিনতে দোকানের মালিককে বলুন', html)
        self.client.post(reverse('sms_buy'), {'amount': '200'})
        self.assertFalse(OnlinePayment.objects.exists())

    def test_buy_online_like_edumi(self):
        from . import sms
        from .models import MasterSetting
        fake = FakePayStation()
        with mock.patch('store.paystation.requests.post', side_effect=fake), \
                override_settings(PAYSTATION_TEST_SHOPS=[self.shop.slug]):
            response = self.client.post(reverse('sms_buy'), {'amount': '20'})
            self.assertRedirects(response, reverse('sms_panel') + '#buy', fetch_redirect_response=False)
            self.assertFalse(OnlinePayment.objects.exists())
            response = self.client.post(reverse('sms_buy'), {'amount': '300'})
            self.assertRedirects(response, 'https://sandbox.paystation.com.bd/checkout/test', fetch_redirect_response=False)
            payment = OnlinePayment.objects.get()
            self.assertEqual((payment.kind, payment.amount, payment.sms_count), ('sms', Decimal('300'), 750))
            fake.v1 = {'status': 'Success', 'amount': '300'}
            back = self.client.get(reverse('paystation_callback'), {'inv': payment.invoice_number})
        self.assertRedirects(back, reverse('sms_panel'), fetch_redirect_response=False)
        self.assertEqual(self.balance(), 850)
        # আগে bKash-এ জমা দেওয়া পুরনো অনুরোধ মানলে এখনকার রেটে যোগ হয়
        MasterSetting.objects.create(sms_rate=Decimal('0.35'))
        old = PaymentRequest.objects.create(shop=self.shop, plan_name=sms.MANUAL_REQUEST_NAME, payment_method='bKash',
                                            sender_number='01799999999', transaction_id='OLD123', amount=Decimal('300'))
        self.assertEqual(sms.approve_manual_request(old), 857)

    def test_gateway_uses_env_keys_and_non_masking(self):
        from . import sms
        from .models import MasterSetting
        MasterSetting.objects.create(sms_client_id='old', sms_api_key='old', sms_sender_id='BRAND')
        response = mock.Mock()
        response.json.return_value = {'response_code': 200, 'message': 'ok'}
        with override_settings(SMS_GATEWAY_CLIENT_ID='env-client', SMS_GATEWAY_API_KEY='env-key'), \
                mock.patch('requests.post', return_value=response) as post:
            self.assertEqual(sms.gateway_send(['01711111111', '01722222222'], 'hi'), (True, 'ok'))
        payload = post.call_args.kwargs['json']
        self.assertEqual(payload, {'client_id': 'env-client', 'key': 'env-key',
                                   'recipient': '01711111111,01722222222', 'message': 'hi'})   # sender_id নেই
        with override_settings(SMS_GATEWAY_CLIENT_ID='', SMS_GATEWAY_API_KEY=''):
            self.assertEqual(sms.gateway_keys(), ('old', 'old'))

    def test_online_sms_codes(self):
        from .payments import resolve_item
        self.assertEqual(resolve_item('SMS-TK-350')['sms_count'], 875)
        self.assertEqual(resolve_item('SMS-500')['sms_count'], 500)
        self.assertIsNone(resolve_item('SMS-TK-20'))

    def test_auto_order_sms_costs_real_parts(self):
        from . import sms
        from .models import SmsLog
        order = self.order(self.rahim)
        text = sms.order_received_text(self.shop, order)
        self.assertEqual(sms.segments(text), 1)
        self.assertIn(sms.bn_num(order.id), text)
        with mock.patch('store.sms.gateway_send', return_value=(True, 'ok')):
            sms.send_auto(self.shop, self.rahim.phone, 'অ' * 100, 'অর্ডার')
        self.assertEqual(self.balance(), 98)
        self.assertEqual(SmsLog.objects.get().kind, SmsLog.KIND_AUTO)
        self.shop.is_sms_active = False
        self.assertIsNone(sms.send_auto(self.shop, self.rahim.phone, 'hello', 'অর্ডার'))


class SettlementAndBillingTests(ShopTestMixin, TestCase):
    """সেলারের টাকা তোলা: পেমেন্টের ৭ দিন পর, কমপক্ষে ৳৫,০০০; বিলিং শুধু PayStation (মাসিক/বছর)।"""

    def setUp(self):
        self.user, self.shop = self.make_shop(payout_method='bKash', payout_account='01712345678',
                                              payout_account_name='Munna')
        self.count = 0

    def paid(self, net, days_ago):
        from .models import StorefrontPayment
        self.count += 1
        when = timezone.now() - timedelta(days=days_ago)
        return StorefrontPayment.objects.create(
            shop=self.shop, kind='full', amount=net, fee_percent=0, fee_amount=0, net_amount=net,
            invoice_number=f'SF-{self.shop.id}-{self.count:012d}', status='Completed', completed_at=when)

    def test_hold_minimum_request_cancel_and_pay(self):
        from . import shop_payments as sp
        from .models import SettlementRequest, ShopPayout
        self.paid(Decimal('4000'), days_ago=8)
        self.paid(Decimal('3000'), days_ago=2)
        summary = sp.balance_summary(self.shop)
        self.assertEqual((summary['available'], summary['holding'], summary['short']),
                         (Decimal('4000'), Decimal('3000'), Decimal('1000')))
        self.assertFalse(summary['can_request'])
        self.assertEqual(summary['next_release'], timezone.localdate() + timedelta(days=5))
        with self.assertRaises(sp.SettlementError):
            sp.request_settlement(self.shop, 4000)                       # ৳৫,০০০-এর কম
        self.paid(Decimal('1500'), days_ago=10)
        self.assertTrue(sp.balance_summary(self.shop)['can_request'])
        with self.assertRaises(sp.SettlementError):
            sp.request_settlement(self.shop, 6000)                       # তোলা যাবে ৫,৫০০
        req = sp.request_settlement(self.shop, 5200, user=self.user)
        self.assertEqual((req.method, req.account), ('bKash', '01712345678'))
        summary = sp.balance_summary(self.shop)
        self.assertEqual((summary['available'], summary['requested']), (Decimal('300'), Decimal('5200')))
        with self.assertRaises(sp.SettlementError):
            sp.request_settlement(self.shop, 5000)                       # একটাই খোলা অনুরোধ
        self.assertEqual(sp.cancel_settlement(self.shop, req.pk), 1)
        req = sp.request_settlement(self.shop, 5500)
        sp.pay_settlement(req.pk, 'TRX777', user=self.user)
        req.refresh_from_db()
        self.assertEqual((req.status, req.payout.amount, req.payout.reference), (SettlementRequest.PAID, Decimal('5500'), 'TRX777'))
        summary = sp.balance_summary(self.shop)
        self.assertEqual((summary['available'], summary['due'], summary['holding']), (0, Decimal('3000'), Decimal('3000')))
        with self.assertRaises(sp.SettlementError):
            sp.pay_settlement(req.pk, 'TRX777')                          # দুইবার না
        self.assertEqual(ShopPayout.objects.count(), 1)

    def test_seller_page_and_master_flow(self):
        from .models import SettlementRequest
        self.paid(Decimal('6000'), days_ago=9)
        page = self.client.get(reverse('website_settings') + '?tab=payment').content.decode()
        self.assertIn('টাকা তুলুন', page)
        self.assertIn('৳৬,০০০', page)
        self.client.post(reverse('settlement_request'), {'amount': '6000'})
        req = SettlementRequest.objects.get()
        self.assertIn('তোলার অনুরোধ যাচাই হচ্ছে', self.client.get(reverse('website_settings') + '?tab=payment').content.decode())
        admin = User.objects.create_superuser(phone_number='01900000000', password='Admin-pass-1')
        self.client.force_login(admin)
        self.assertIn('টাকা তোলার অনুরোধ (1)', self.client.get(reverse('master_settlements')).content.decode())
        self.client.post(reverse('master_settlements'), {'action': 'request_paid', 'request_id': req.pk, 'reference': 'BK123'})
        req.refresh_from_db()
        self.assertEqual(req.status, SettlementRequest.PAID)

    def test_billing_is_paystation_only_with_yearly_plans(self):
        from .payments import resolve_item
        item = resolve_item('Standard-YEAR')
        self.assertEqual((item['plan_name'], item['amount'], item['days']), ('Standard', Decimal('10000'), 365))
        self.assertIsNone(resolve_item('Gold-YEAR'))
        with override_settings(PAYSTATION_TEST_SHOPS=[self.shop.slug]):
            html = self.client.get(reverse('billing')).content.decode()
        self.assertIn('value="Basic-YEAR"', html)
        self.assertNotIn('transaction_id', html)
        self.client.post(reverse('submit_payment_request'), {'plan_name': 'Basic', 'payment_method': 'bKash',
                                                             'sender_number': '017', 'transaction_id': 'X1', 'amount': '499'})
        self.assertFalse(PaymentRequest.objects.exists())


class BanglaDigitFontTests(ShopTestMixin, TestCase):
    """Hind Siliguri-র ভাঙা "১" — প্রতিটা পেইজে Google Fonts-এর পরে Noto-র "১" বসানো আছে কিনা।"""

    FIX = 'fonts/bn-digit-one-400.woff2'

    def assertFixed(self, html):
        self.assertIn(self.FIX, html)
        self.assertIn('unicode-range:U+09E7', html)
        # Google Fonts-এর লিংকের পরে থাকতে হবে, নাহলে ব্রাউজার Hind-এর ভাঙা "১"-ই নেয়
        self.assertLess(html.index('family=Hind+Siliguri') if 'family=Hind+Siliguri' in html else -1, html.index(self.FIX))

    def test_every_page_type_has_the_fix(self):
        from django.test import Client
        _user, shop = self.make_shop(slug='digitshop')
        self.assertFixed(self.client.get(reverse('dashboard')).content.decode())        # প্যানেল
        self.assertFixed(self.client.get(reverse('pos_day_close')).content.decode())    # দিনশেষের হিসাব
        guest = Client()
        self.assertFixed(guest.get(reverse('login')).content.decode())                  # লগইন/সাইনআপ
        self.assertFixed(guest.get('/shop/digitshop/', HTTP_HOST='localhost').content.decode())   # ওয়েবসাইট
        with override_settings(STORE_BASE_DOMAIN='sellpunch.com', ALLOWED_HOSTS=['.sellpunch.com', 'localhost', 'testserver']):
            self.assertFixed(guest.get('/', HTTP_HOST='nosuchshop.sellpunch.com').content.decode())   # ভুল সাবডোমেইন
        self.assertFixed(guest.get(reverse('landing_page')).content.decode())          # হোমপেইজ

    def test_fix_font_files_exist(self):
        from pathlib import Path
        folder = Path(__file__).resolve().parent / 'static' / 'fonts'
        for weight in (400, 500, 600):
            self.assertGreater((folder / f'bn-digit-one-{weight}.woff2').stat().st_size, 300)


class BrandTests(TestCase):
    def test_new_name_logo_and_icons(self):
        import json
        html = self.client.get('/').content.decode()
        self.assertIn('SellPunch', html)
        self.assertNotIn('SohojSell', html)
        self.assertIn('brand/sellpunch-logo.svg', html)
        self.assertIn('rel="apple-touch-icon"', html)
        login = self.client.get(reverse('login')).content.decode()
        self.assertIn('brand/sellpunch-logo.svg', login)
        manifest = self.client.get('/site.webmanifest')
        self.assertEqual(manifest['Content-Type'], 'application/manifest+json')
        self.assertEqual(json.loads(manifest.content)['name'], 'SellPunch')
        self.assertEqual(self.client.get('/favicon.ico').status_code, 302)
