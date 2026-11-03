"""
SohojSell টেস্ট: পাবলিক পেইজ, নীতিমালা, PayStation পেমেন্ট আর Facebook ডিসকানেক্ট।

চালানো: python manage.py test
PayStation-এর নেটওয়ার্ক কল নকল (mock) করা হয়েছে, তাই ইন্টারনেট লাগে না।
"""
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import FacebookPageConnection, OnlinePayment, Order, OrderItem, Shop
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
        base = {'name': shop.name, 'phone': shop.phone, 'address': 'Dhaka', 'is_sms_active': 'on'}
        response = self.client.post(reverse('settings'), {**base, 'subdomain': 'takenname'})
        self.assertEqual(response.status_code, 200)
        shop.refresh_from_db()
        self.assertNotEqual(shop.slug, 'takenname')
        self.client.post(reverse('settings'), {**base, 'subdomain': 'New-Name'})
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
        base = {'name': 'Shop', 'phone': '01711111111', 'address': 'Dhaka', 'subdomain': 'myshop',
                'custom_domain': 'www.example.com'}
        _user, shop = self.make_shop(**self._paid('Standard'))
        self.client.post(reverse('settings'), base)
        shop.refresh_from_db()
        self.assertEqual(shop.slug, 'myshop')
        self.assertFalse(shop.custom_domain)

        shop.subscription_plan = 'Premium'
        shop.save()
        self.client.post(reverse('settings'), base)
        shop.refresh_from_db()
        self.assertEqual(shop.custom_domain, 'www.example.com')


@override_settings(STORE_BASE_DOMAIN='sohojsell.com')
class StorefrontDomainTests(ShopTestMixin, TestCase):
    HOST = 'munna.sohojsell.com'

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
        response = self.client.get(f'/shop/munna/product/{self.product.id}/?ref=fb', HTTP_HOST='sohojsell.com')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], f'https://munna.sohojsell.com/product/{self.product.id}/?ref=fb')
        on_sub = self.client.get('/shop/munna/', HTTP_HOST=self.HOST)
        self.assertEqual(on_sub.status_code, 301)
        self.assertEqual(on_sub['Location'], '/')

    def test_unknown_subdomain_shows_not_found(self):
        response = self.client.get('/', HTTP_HOST='nobody.sohojsell.com')
        self.assertEqual(response.status_code, 404)
        self.assertIn('এই ঠিকানায় কোনো দোকান নেই', response.content.decode())

    def test_main_site_and_dashboard_unchanged(self):
        dashboard = self.client.get(reverse('dashboard'), HTTP_HOST='sohojsell.com')
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn('https://munna.sohojsell.com/', dashboard.content.decode())
        self.assertIn('munna.sohojsell.com', dashboard.content.decode())
        self.assertEqual(self.shop.storefront_url, 'https://munna.sohojsell.com/')
        self.client.logout()
        self.assertEqual(self.client.get('/', HTTP_HOST='sohojsell.com').status_code, 200)
        self.assertEqual(self.client.get('/', HTTP_HOST='www.sohojsell.com').status_code, 200)

    def test_order_on_subdomain_and_success_page_is_private(self):
        import json
        response = self.client.post('/place-order/', data=json.dumps({
            'cart': [{'id': self.product.id, 'qty': 2}], 'name': 'Rahim', 'phone': '01812345678',
            'address': 'Savar'}), content_type='application/json', HTTP_HOST=self.HOST)
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

    @override_settings(ALLOWED_HOSTS=['.sohojsell.com', 'www.munnashop.com', 'munnashop.com'])
    def test_custom_domain_only_for_premium(self):
        self.shop.custom_domain = 'www.munnashop.com'
        self.shop.save()
        response = self.client.get('/', HTTP_HOST='munnashop.com')
        self.assertEqual(response.status_code, 302)          # Standard না → সাবডোমেইনে
        self.assertEqual(response['Location'], 'https://munna.sohojsell.com/')
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
        self.assertIn('নতুন এসেছে', html)
        self.assertNotIn('ছাড় চলছে', html)
        self.assertNotIn('%</', html)


class StorefrontThemeTests(ShopTestMixin, TestCase):
    def test_seller_picks_theme_and_storefront_uses_it(self):
        _user, shop = self.make_shop(slug='themeshop')
        html = self.client.get('/shop/themeshop/', HTTP_HOST='localhost').content.decode()
        self.assertIn('--orange: #F57224', html)                     # ডিফল্ট কমলা
        settings_page = self.client.get(reverse('settings')).content.decode()
        self.assertIn('value="pink"', settings_page)
        self.client.post(reverse('settings'), {'name': shop.name, 'phone': shop.phone, 'address': 'Dhaka',
                                               'subdomain': 'themeshop', 'storefront_theme': 'pink'})
        shop.refresh_from_db()
        self.assertEqual(shop.storefront_theme, 'pink')
        html = self.client.get('/shop/themeshop/', HTTP_HOST='localhost').content.decode()
        self.assertIn('--orange: #DB2777', html)
        self.assertNotIn('#FF8C42', html)

    def test_unknown_theme_rejected(self):
        _user, shop = self.make_shop(slug='themeshop2')
        self.client.post(reverse('settings'), {'name': shop.name, 'phone': shop.phone, 'address': 'Dhaka',
                                               'subdomain': 'themeshop2', 'storefront_theme': 'neon'})
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
