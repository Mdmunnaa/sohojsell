"""
SellPunch টেস্ট: পাবলিক পেইজ, নীতিমালা, PayStation পেমেন্ট আর Facebook ডিসকানেক্ট।

চালানো: python manage.py test
PayStation-এর নেটওয়ার্ক কল নকল (mock) করা হয়েছে, তাই ইন্টারনেট লাগে না।
"""
import json
import re
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
        base = {'section': 'domain', 'custom_domain': 'https://www.Example.com/shop'}
        _user, shop = self.make_shop(**self._paid('Standard'))
        self.client.post(reverse('website_settings'), base)
        shop.refresh_from_db()
        self.assertFalse(shop.custom_domain)
        page = self.client.get(reverse('website_settings') + '?tab=domain').content.decode()
        self.assertIn('Premium প্যাকেজে পাবেন', page)

        shop.subscription_plan = 'Premium'
        shop.save()
        self.client.post(reverse('website_settings'), base)
        shop.refresh_from_db()
        self.assertEqual((shop.custom_domain, shop.custom_domain_status), ('www.example.com', 'pending'))
        page = self.client.get(reverse('website_settings') + '?tab=domain').content.decode()
        for text in ['CNAME', 'shops.sellpunch.com', 'যাচাই করুন', 'DNS এখনো মেলেনি']:
            self.assertIn(text, page)
        # "দোকানের তথ্য" ফর্ম সেভ করলে ডোমেইন মুছে যায় না
        self.client.post(reverse('website_settings'), {'section': 'store', 'name': 'Shop', 'phone': '01711111111',
                                                       'address': 'Dhaka', 'subdomain': shop.slug})
        shop.refresh_from_db()
        self.assertEqual(shop.custom_domain, 'www.example.com')
        bad = self.client.post(reverse('website_settings'), {'section': 'domain', 'custom_domain': 'myshop.sellpunch.com'},
                               follow=True).content.decode()
        self.assertIn('এটা নিজের ডোমেইন না', bad)
        # যাচাই: DNS না মিললে pending; মিললে dns_ok আর মালিকের তালিকায়; মালিক চালু করলে live + SMS
        from . import domains
        with mock.patch('store.domains.dns_points_here', return_value=False):
            self.client.post(reverse('website_settings'), {'section': 'domain', 'action': 'verify'})
        shop.refresh_from_db()
        self.assertEqual(shop.custom_domain_status, 'pending')
        with mock.patch('store.domains.dns_points_here', return_value=True):
            response = self.client.post(reverse('website_settings'), {'section': 'domain', 'action': 'verify'}, follow=True)
        shop.refresh_from_db()
        self.assertEqual(shop.custom_domain_status, 'dns_ok')
        self.assertIn('DNS ঠিক আছে', response.content.decode())
        self.assertEqual(list(domains.pending_for_master()), [shop])
        admin = User.objects.create_superuser(phone_number='01700000001', password='Admin-pass-1', name='Boss')
        self.client.force_login(admin)
        self.assertIn('www.example.com', self.client.get(reverse('master_dashboard')).content.decode())
        with mock.patch('store.sms.notify') as notify:
            self.client.post(reverse('master_domain_live', args=[shop.id]))
        shop.refresh_from_db()
        self.assertEqual(shop.custom_domain_status, 'live')
        self.assertIn('www.example.com চালু', notify.call_args[0][1])
        # Cloudflare টোকেন থাকলে যাচাইতেই live
        self.client.force_login(_user)
        Shop.objects.filter(pk=shop.pk).update(custom_domain_status='pending')
        with self.settings(CLOUDFLARE_API_TOKEN='t', CLOUDFLARE_ZONE_ID='z'), \
                mock.patch('store.domains.dns_points_here', return_value=True), \
                mock.patch('store.domains.cloudflare_add_hostname', return_value=(True, 'ok')):
            self.client.post(reverse('website_settings'), {'section': 'domain', 'action': 'verify'})
        shop.refresh_from_db()
        self.assertEqual(shop.custom_domain_status, 'live')
        self.client.post(reverse('website_settings'), {'section': 'domain', 'action': 'remove'})
        shop.refresh_from_db()
        self.assertIsNone(shop.custom_domain)

    def test_unknown_custom_domain_is_404(self):
        _user, shop = self.make_shop(**self._paid('Premium'))
        Shop.objects.filter(pk=shop.pk).update(custom_domain='www.rahim.com', slug='rahim')
        with self.settings(STORE_BASE_DOMAIN='sellpunch.com', ALLOWED_HOSTS=['*']):
            self.assertEqual(self.client.get('/', HTTP_HOST='www.rahim.com').status_code, 200)
            self.assertEqual(self.client.get('/', HTTP_HOST='rahim.com').status_code, 200)
            missing = self.client.get('/', HTTP_HOST='www.nobody.com')
            self.assertEqual(missing.status_code, 404)
            self.assertIn('এই ঠিকানায় কোনো দোকান নেই', missing.content.decode())


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
        self.assertIn('৩টা বিক্রি হয়েছে', html)          # শুধু Delivered + Shipped
        self.assertNotRegex(html, r'\d(\.\d)?/5(?!\d)')          # বানানো রেটিং নেই (প্রোডাক্ট id-তে /5.. থাকতে পারে)
        self.assertNotIn('-15%', html)
        self.assertEqual(html.count('বিক্রি হয়েছে'), 1)    # Lungi বিক্রি হয়নি, তাই কিছু দেখায় না
        detail = self.client.get(f'/shop/soldshop/product/{self.product.id}/', HTTP_HOST='localhost').content.decode()
        self.assertIn('৩টা বিক্রি হয়েছে', detail)
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
        self.assertIn('data-theme="pink"', page)
        self.client.post(reverse('website_settings'), {'section': 'design', 'storefront_theme': 'pink',
                                                       'color_mode': 'theme', 'show_sold_count': 'on'})
        shop.refresh_from_db()
        self.assertEqual(shop.storefront_theme, 'pink')
        html = self.client.get('/shop/themeshop/', HTTP_HOST='localhost').content.decode()
        self.assertIn('--orange: #DB2777', html)
        self.assertNotIn('#FF8C42', html)

    def test_designs_and_custom_color(self):
        from .themes import palette_from_hex
        _user, shop = self.make_shop(slug='dshop')
        page = self.client.get(reverse('website_settings') + '?tab=design').content.decode()
        for design in ('classic', 'minimal', 'bold', 'soft'):
            self.assertIn(f'value="{design}"', page)
        self.client.post(reverse('website_settings'), {'section': 'design', 'storefront_design': 'bold',
                                                       'storefront_theme': 'blue', 'color_mode': 'custom',
                                                       'storefront_color': '1e88e5', 'show_sold_count': 'on'})
        shop.refresh_from_db()
        self.assertEqual((shop.storefront_design, shop.storefront_color), ('bold', '#1E88E5'))
        html = self.client.get('/shop/dshop/', HTTP_HOST='localhost').content.decode()
        self.assertIn('--orange: #1E88E5', html)
        self.assertIn('বোল্ড', page)
        self.assertIn('.app-top-bar { background: var(--orange)', html)          # বোল্ড ডিজাইনের CSS
        # থিমের রঙে ফিরলে নিজের রঙ মুছে যায়; ভুল কোড নেওয়া হয় না; অজানা ডিজাইন বাদ
        self.client.post(reverse('website_settings'), {'section': 'design', 'storefront_design': 'minimal',
                                                       'storefront_theme': 'green', 'color_mode': 'theme'})
        shop.refresh_from_db()
        self.assertEqual((shop.storefront_design, shop.storefront_color, shop.storefront_theme), ('minimal', '', 'green'))
        response = self.client.post(reverse('website_settings'), {'section': 'design', 'storefront_design': 'fancy',
                                                                  'color_mode': 'custom', 'storefront_color': 'red'})
        shop.refresh_from_db()
        self.assertEqual((shop.storefront_design, shop.storefront_color), ('minimal', ''))
        # খুব হালকা রঙ দিলে বাটনের সাদা লেখা পড়ার মতো গাঢ় হয়
        pale = palette_from_hex('#FFF59D')
        self.assertNotEqual(pale['primary'], '#FFF59D')
        self.assertEqual(len(pale['rgb'].split(',')), 3)
        html = self.client.get('/shop/dshop/', HTTP_HOST='localhost').content.decode()
        self.assertIn('--orange: #16A34A', html)
        self.assertIn('.shop-name-sf { letter-spacing: 0; text-transform: uppercase', html)   # মিনিমাল ডিজাইনের CSS

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
        for text in ['SMS প্যানেল', 'কাকে পাঠাবেন?', 'সব কাস্টমার', 'SMS কিনুন', 'কাস্টমারকে অটো SMS']:
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


class ReportTests(ShopTestMixin, TestCase):
    """রিপোর্ট পেজ: সময় বাছাই আর তুলনা, বিক্রি-লাভের হিসাব, পেমেন্টের ফেরত, বাংলা পেজ, Excel, স্টাফের অনুমতি।"""

    def setUp(self):
        from .models import Customer, Product
        self.user, self.shop = self.make_shop()
        self.shirt = Product.objects.create(shop=self.shop, name='শার্ট', price=Decimal('450'), cost_price=300,
                                            stock_quantity=10)
        self.customer = Customer.objects.create(shop=self.shop, name='রহিম', phone='01812345678', address='Savar')

    def order(self, *, source='storefront', status='Pending', qty=1, delivery=0, discount=0, when=None):
        order = Order.objects.create(shop=self.shop, customer=self.customer, source=source, status=status,
                                     delivery_charge=delivery, discount=discount,
                                     total_amount=Decimal('450') * qty + delivery - discount)
        OrderItem.objects.create(order=order, product=self.shirt, price=Decimal('450'), quantity=qty, cost_price=300)
        if when is not None:
            Order.objects.filter(pk=order.pk).update(created_at=when)
        return order

    def test_periods_and_what_they_compare_with(self):
        from datetime import date
        from . import reports
        today = date(2026, 11, 10)
        cases = {
            'today': (date(2026, 11, 10), date(2026, 11, 10), date(2026, 11, 9), date(2026, 11, 9)),
            'yesterday': (date(2026, 11, 9), date(2026, 11, 9), date(2026, 11, 8), date(2026, 11, 8)),
            '7d': (date(2026, 11, 4), date(2026, 11, 10), date(2026, 10, 28), date(2026, 11, 3)),
            'month': (date(2026, 11, 1), date(2026, 11, 10), date(2026, 10, 1), date(2026, 10, 10)),
            'last_month': (date(2026, 10, 1), date(2026, 10, 31), date(2026, 9, 1), date(2026, 9, 30)),
            'year': (date(2026, 1, 1), date(2026, 11, 10), date(2025, 1, 1), date(2025, 11, 10)),
        }
        for key, expected in cases.items():
            period = reports.resolve_period({'period': key}, today)
            self.assertEqual((period.start, period.end, period.prev_start, period.prev_end), expected, key)
        self.assertEqual(reports.resolve_period({}, today).key, 'month')
        self.assertEqual(reports.resolve_period({'period': 'junk'}, today).key, 'month')
        custom = reports.resolve_period({'start': '2026-11-20', 'end': '2026-12-31'}, today)   # ভবিষ্যৎ কেটে আজ পর্যন্ত
        self.assertEqual((custom.key, custom.start, custom.end), ('custom', today, today))
        custom = reports.resolve_period({'start': '2026-11-01', 'end': 'abc'}, today)
        self.assertEqual((custom.start, custom.end, custom.days), (date(2026, 11, 1), today, 10))
        self.assertEqual(reports.resolve_period({'period': 'month'}, date(2026, 3, 31)).prev_end, date(2026, 2, 28))
        self.assertEqual(reports.range_label(date(2026, 11, 1), date(2026, 11, 10)), '১ নভেম্বর – ১০ নভেম্বর ২০২৬')

    def test_summary_counts_sales_profit_and_channels(self):
        from . import reports
        self.order(source='pos', status='Delivered', qty=2, discount=50)          # ৮৫০, লাভ ২৫০
        self.order(delivery=60)                                                   # ৪৫০ (+৬০), লাভ ১৫০
        self.order(source='dashboard', status='Returned', qty=3)                  # ধরা হবে না, হারানো ১৩৫০
        self.order(source='pos', status='Delivered', when=timezone.now() - timedelta(days=40))  # সময়ের বাইরে
        today = timezone.localdate()
        s = reports.summary(self.shop, today, today)
        self.assertEqual((s['sales'], s['profit'], s['orders'], s['units']), (Decimal('1300'), Decimal('400'), 2, 3))
        self.assertEqual((s['delivery'], s['discount'], s['returned'], s['lost_value']),
                         (Decimal('60'), Decimal('50'), 1, Decimal('1350')))
        self.assertEqual(s['margin'], 30.8)
        channels = {c['key']: (c['sales'], c['orders']) for c in s['channels']}
        self.assertEqual(channels, {'pos': (Decimal('850'), 1), 'storefront': (Decimal('450'), 1),
                                    'dashboard': (Decimal('0'), 0)})
        yesterday = today - timedelta(days=1)
        self.assertIsNone(reports.compare(s, reports.summary(self.shop, yesterday, yesterday))['sales'])  # আগে ০
        self.order(source='pos', status='Delivered', when=timezone.now() - timedelta(days=1))           # গতকাল ৪৫০
        change = reports.compare(s, reports.summary(self.shop, yesterday, yesterday))
        self.assertEqual(change['sales'], {'dir': 'up', 'text': '১৮৯%'})
        rows = reports.product_rows(self.shop, today, today, limit=5)
        self.assertEqual((rows[0]['qty'], rows[0]['sales']), (3, Decimal('1350')))

    def test_payments_add_due_and_subtract_refund(self):
        from .models import SalePayment
        from . import reports
        order = self.order(source='pos', status='Delivered', qty=2)
        SalePayment.objects.create(shop=self.shop, order=order, method='cash', amount=Decimal('500'))
        SalePayment.objects.create(shop=self.shop, order=order, method='cash', amount=Decimal('400'),
                                   kind=SalePayment.DUE_COLLECTION)
        SalePayment.objects.create(shop=self.shop, order=order, method='cash', amount=Decimal('-450'),
                                   kind=SalePayment.REFUND)
        SalePayment.objects.create(shop=self.shop, order=order, method='bkash', amount=Decimal('100'))
        today = timezone.localdate()
        payments = reports.payment_methods(self.shop, today, today)
        cash, bkash = payments['rows']
        self.assertEqual((cash['label'], cash['amount'], cash['refund']), ('নগদ', Decimal('450'), Decimal('450')))
        self.assertEqual(cash['note'], 'বাকি আদায় ৳৪০০ · ফেরত দেওয়া ৳৪৫০')
        self.assertEqual((bkash['amount'], payments['total']), (Decimal('100'), Decimal('550')))

    def test_page_is_bangla_and_every_period_opens(self):
        self.order(source='pos', status='Delivered', qty=2)
        self.order(delivery=60)
        response = self.client.get(reverse('reports'))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        for text in ['মোট বিক্রি', 'লাভ', 'বিক্রির ধারা', 'কোথা থেকে বিক্রি', 'সবচেয়ে বেশি বিক্রি হওয়া প্রোডাক্ট',
                     'সেরা কাস্টমার', 'দিনের কোন সময়ে বেশি বিক্রি', 'Excel ডাউনলোড', '৳১,৩৫০', 'রহিম', 'শার্ট']:
            self.assertIn(text, html)
        for english in ['TOTAL REVENUE', 'REAL NET PROFIT', 'Filter Data', 'Export Excel']:
            self.assertNotIn(english, html)
        for query in ['?period=today', '?period=year', '?period=last_month', '?start=2020-01-01&end=2026-12-31',
                      '?start=bad&end=worse']:
            self.assertEqual(self.client.get(reverse('reports') + query).status_code, 200, query)

    def test_excel_export_has_four_sheets(self):
        from io import BytesIO
        from openpyxl import load_workbook
        self.order(source='pos', status='Delivered', qty=2)
        response = self.client.get(reverse('reports') + '?period=today&export=xlsx')
        self.assertEqual(response.status_code, 200)
        self.assertIn('spreadsheetml', response['Content-Type'])
        self.assertIn('.xlsx', response['Content-Disposition'])
        book = load_workbook(BytesIO(response.content))
        self.assertEqual(book.sheetnames, ['সারাংশ', 'অর্ডার', 'প্রোডাক্ট', 'কাস্টমার', 'খরচ', 'মাল কেনা'])
        self.assertEqual(book['অর্ডার'].max_row, 2)

    def test_staff_without_report_permission_is_sent_back(self):
        from .models import StaffProfile
        staff = User.objects.create_user(phone_number='01922222222', password='Test-pass-123', name='Karim')
        StaffProfile.objects.create(user=staff, shop=self.shop, can_use_pos=True)
        self.client.force_login(staff)
        self.assertRedirects(self.client.get(reverse('reports')), reverse('dashboard'), fetch_redirect_response=False)
        StaffProfile.objects.filter(user=staff).update(can_view_reports=True)
        self.assertEqual(self.client.get(reverse('reports')).status_code, 200)


class VariantTests(ShopTestMixin, TestCase):
    """সাইজ/রং: ফর্ম থেকে সেভ, মোট স্টক মেলানো, POS-ওয়েবসাইটে বিক্রি, ফেরত, বারকোড, বিলে নাম।"""

    def setUp(self):
        from .models import Product
        from . import variants
        self.user, self.shop = self.make_shop()
        Shop.objects.filter(pk=self.shop.pk).update(slug='vshop')
        self.shirt = Product.objects.create(shop=self.shop, name='শার্ট', price=Decimal('450'), cost_price=300,
                                            stock_quantity=99)
        variants.save_rows(self.shirt, [{'id': None, 'name': 'লাল / M', 'price': None, 'stock': 3},
                                        {'id': None, 'name': 'লাল / XL', 'price': Decimal('500'), 'stock': 2}])
        self.m, self.xl = self.shirt.variants.all()

    def sell(self, **payload):
        payload.setdefault('payments', [{'method': 'cash', 'amount': 0, 'full': True}])
        return self.client.post(reverse('pos_checkout'), data=json.dumps(payload), content_type='application/json')

    def test_total_stock_follows_variants(self):
        self.shirt.refresh_from_db()
        self.assertTrue(self.shirt.has_variants)
        self.assertEqual(self.shirt.stock_quantity, 5)                # ফর্মের ৯৯ না, ভ্যারিয়েন্টের যোগফল
        self.assertEqual((self.m.sell_price, self.xl.sell_price), (Decimal('450'), Decimal('500')))
        self.assertTrue(self.m.barcode and self.m.barcode != self.xl.barcode)

    def test_product_form_saves_renames_and_removes(self):
        from .models import ProductVariant
        form = {'name': 'শার্ট', 'price': '450', 'cost_price': '300', 'stock_quantity': '0', 'is_active': 'on',
                'variant_id[]': [str(self.m.id), ''], 'variant_name[]': ['লাল / L', 'নীল / M'],
                'variant_price[]': ['', '৪৮০'], 'variant_stock[]': ['৭', '1']}
        self.assertRedirects(self.client.post(reverse('edit_product', args=[self.shirt.id]), form),
                             reverse('product_list'))
        names = {v.name: (v.stock_quantity, v.price) for v in ProductVariant.objects.filter(product=self.shirt)}
        self.assertEqual(names, {'লাল / L': (7, None), 'নীল / M': (1, Decimal('480'))})      # XL মুছে গেছে
        self.assertEqual(ProductVariant.objects.get(name='লাল / L').id, self.m.id)        # একই ভ্যারিয়েন্ট, নতুন নাম
        self.shirt.refresh_from_db()
        self.assertEqual(self.shirt.stock_quantity, 8)
        form.update({'variant_name[]': ['এক', 'এক']})
        response = self.client.post(reverse('edit_product', args=[self.shirt.id]), form)
        self.assertEqual(response.status_code, 200)
        self.assertIn('দুবার লেখা হয়েছে', response.content.decode())
        form.update({'variant_id[]': [], 'variant_name[]': [], 'variant_price[]': [], 'variant_stock[]': [],
                     'stock_quantity': '12'})
        self.client.post(reverse('edit_product', args=[self.shirt.id]), form)
        self.shirt.refresh_from_db()
        self.assertEqual((self.shirt.has_variants, self.shirt.stock_quantity), (False, 12))
        page = self.client.get(reverse('add_product')).content.decode()
        self.assertIn('সাইজ / রং', page)

    def test_pos_sells_and_returns_a_variant(self):
        data = self.sell(items=[{'id': -self.xl.id, 'qty': 2}]).json()
        self.assertTrue(data['success'], data)
        self.assertEqual(data['sale']['total'], 1000)
        item = OrderItem.objects.get(order_id=data['sale']['id'])
        self.assertEqual((item.variant_id, item.variant_name, item.display_name), (self.xl.id, 'লাল / XL', 'শার্ট (লাল / XL)'))
        self.xl.refresh_from_db(); self.shirt.refresh_from_db()
        self.assertEqual((self.xl.stock_quantity, self.shirt.stock_quantity), (0, 3))
        self.assertIn('শার্ট (লাল / XL)', self.client.get(reverse('pos_receipt', args=[data['sale']['id']])).content.decode())
        self.assertIn('স্টকে আছে মাত্র 0টা', self.sell(items=[{'id': -self.xl.id, 'qty': 1}]).json()['error'])
        self.assertIn('সাইজ/রং', self.sell(items=[{'id': self.shirt.id, 'qty': 1}]).json()['error'])   # কোনটা বলা হয়নি
        back = self.client.post(reverse('pos_return', args=[data['sale']['id']]), data='{}',
                                content_type='application/json').json()
        self.assertTrue(back['success'], back)
        self.assertEqual(back['restocked'], [{'id': -self.xl.id, 'qty': 2}])
        self.xl.refresh_from_db(); self.shirt.refresh_from_db()
        self.assertEqual((self.xl.stock_quantity, self.shirt.stock_quantity), (2, 5))

    def test_pos_screen_and_barcode_know_variants(self):
        response = self.client.get(reverse('pos'))
        product = next(p for p in response.context['pos_config']['products'] if p['id'] == self.shirt.id)
        self.assertEqual([(v['id'], v['name'], v['price'], v['stock']) for v in product['variants']],
                         [(-self.m.id, 'লাল / M', 450, 3), (-self.xl.id, 'লাল / XL', 500, 2)])
        hit = self.client.post(reverse('barcode_lookup'), data=json.dumps({'barcode': self.xl.barcode}),
                               content_type='application/json').json()
        self.assertEqual((hit['hit'], hit['product']['id']), (-self.xl.id, self.shirt.id))
        self.assertIn('শার্ট (লাল / XL)', self.client.get(reverse('barcode_print')).content.decode())

    def test_storefront_order_takes_variant_stock(self):
        self.client.logout()
        page = self.client.get(f'/shop/vshop/product/{self.shirt.id}/').content.decode()
        self.assertIn('সাইজ / রং বেছে নিন', page)
        self.assertIn('লাল / XL', page)

        from .delivery import zones_for

        def place(cart):
            return self.client.post('/shop/vshop/place-order/', json.dumps({
                'cart': cart, 'name': 'রহিম', 'phone': '01812345678', 'address': 'Savar', 'payment': 'cod',
                'zone': zones_for(self.shop)[0].id}),
                content_type='application/json').json()
        self.assertIn('সাইজ/রং', place([{'id': self.shirt.id, 'qty': 1}])['error'])
        self.assertIn('স্টকে আছে মাত্র ২টা', place([{'id': -self.xl.id, 'qty': 3}])['error'])
        done = place([{'id': -self.xl.id, 'qty': 1}, {'id': -self.m.id, 'qty': 2}])
        self.assertTrue(done['success'], done)
        order = Order.objects.get(source='storefront')
        self.assertEqual(order.total_amount - order.delivery_charge, Decimal('1400'))
        self.assertEqual(sorted(i.display_name for i in order.items.all()), ['শার্ট (লাল / M)', 'শার্ট (লাল / XL)'])
        self.xl.refresh_from_db(); self.m.refresh_from_db(); self.shirt.refresh_from_db()
        self.assertEqual((self.xl.stock_quantity, self.m.stock_quantity, self.shirt.stock_quantity), (1, 1, 2))
        self.client.force_login(self.user)
        self.client.post(reverse('order_delete', args=[order.id]))
        self.shirt.refresh_from_db()
        self.assertEqual(self.shirt.stock_quantity, 5)

    def test_other_shops_variant_cannot_be_sold(self):
        from .models import Product
        from . import variants
        _other_user, other = self.make_shop(phone='01722222222')
        theirs = Product.objects.create(shop=other, name='Their', price=10, stock_quantity=0)
        variants.save_rows(theirs, [{'id': None, 'name': 'A', 'price': None, 'stock': 5}])
        self.client.force_login(self.user)
        self.assertFalse(self.sell(items=[{'id': -theirs.variants.get().id, 'qty': 1}]).json()['success'])


class LedgerTests(ShopTestMixin, TestCase):
    """কেনা, সাপ্লায়ার, খরচ: স্টক আর গড় কেনা দাম, সাপ্লায়ারের বাকি, মোছা, নিট লাভ, অনুমতি।"""

    def setUp(self):
        from .models import Product, Supplier
        from . import variants
        self.user, self.shop = self.make_shop()
        self.shirt = Product.objects.create(shop=self.shop, name='শার্ট', price=Decimal('450'), cost_price=300,
                                            stock_quantity=10)
        self.cap = Product.objects.create(shop=self.shop, name='Cap', price=Decimal('200'), cost_price=0,
                                          stock_quantity=4)
        self.kurti = Product.objects.create(shop=self.shop, name='কুর্তি', price=Decimal('900'), cost_price=500)
        variants.save_rows(self.kurti, [{'id': None, 'name': 'M', 'price': None, 'stock': 2},
                                        {'id': None, 'name': 'L', 'price': None, 'stock': 0}])
        self.m, self.l = self.kurti.variants.all()
        self.karim = Supplier.objects.create(shop=self.shop, name='করিম ট্রেডার্স', opening_due=Decimal('1000'))

    def buy(self, items, **extra):
        data = {'item_key[]': [str(k) for k, _q, _c in items], 'item_qty[]': [str(q) for _k, q, _c in items],
                'item_cost[]': [str(c) for _k, _q, c in items], 'supplier': '', 'purchased_on': '', **extra}
        return self.client.post(reverse('purchase_new'), data)

    def test_purchase_adds_stock_and_averages_cost(self):
        from .models import Purchase
        response = self.buy([(self.shirt.id, 10, 400), (self.cap.id, 6, 120), (-self.l.id, 3, 600)],
                            supplier=str(self.karim.id), paid='৩০০০', invoice_no='INV-7')
        purchase = Purchase.objects.get()
        self.assertRedirects(response, reverse('purchase_detail', args=[purchase.id]))
        self.assertEqual((purchase.total_amount, purchase.paid_amount, purchase.due_amount),
                         (Decimal('6520'), Decimal('3000'), Decimal('3520')))
        for product in (self.shirt, self.cap, self.kurti):
            product.refresh_from_db()
        self.l.refresh_from_db()
        self.assertEqual((self.shirt.stock_quantity, self.shirt.cost_price), (20, Decimal('350')))   # (১০×৩০০+১০×৪০০)÷২০
        self.assertEqual((self.cap.stock_quantity, self.cap.cost_price), (10, Decimal('120')))      # আগের দাম জানা ছিল না
        self.assertEqual((self.l.stock_quantity, self.kurti.stock_quantity, self.kurti.cost_price),
                         (3, 5, Decimal('560')))                                                    # (২×৫০০+৩×৬০০)÷৫
        from . import ledger
        self.assertEqual(ledger.supplier_due(self.karim), Decimal('4520'))                          # ১০০০ আগের + ৩৫২০
        detail = self.client.get(reverse('purchase_detail', args=[purchase.id])).content.decode()
        for text in ['কুর্তি (L)', 'করিম ট্রেডার্স', '৳৬,৫২০', 'INV-7']:
            self.assertIn(text, detail)
        self.assertIn('করিম ট্রেডার্স', self.client.get(reverse('purchase_list')).content.decode())

    def test_purchase_rules(self):
        from .models import Purchase, Supplier
        page = self.buy([(self.shirt.id, 5, 400)], paid='500').content.decode()        # বাকি অথচ সাপ্লায়ার নেই
        self.assertIn('সাপ্লায়ার বেছে নিন', page)
        self.assertIn('কোন সাইজ/রং', self.buy([(self.kurti.id, 1, 500)]).content.decode())
        self.assertIn('এর বেশি দেওয়া টাকা', self.buy([(self.shirt.id, 1, 400)], paid='900').content.decode())
        self.assertIn('অন্তত একটা প্রোডাক্ট', self.buy([]).content.decode())
        self.assertFalse(Purchase.objects.exists())
        self.shirt.refresh_from_db()
        self.assertEqual(self.shirt.stock_quantity, 10)
        # নগদে কেনা (সাপ্লায়ার ছাড়া) আর ফর্ম থেকেই নতুন সাপ্লায়ার
        self.buy([(self.shirt.id, 2, 300)])
        self.buy([(self.shirt.id, 1, 300)], supplier='new', new_supplier='রহিম স্টোর', new_phone='01700000000', paid='0')
        cash, credit = Purchase.objects.order_by('id')
        self.assertEqual((cash.supplier, cash.paid_amount), (None, Decimal('600')))
        self.assertEqual((credit.supplier.name, credit.due_amount), ('রহিম স্টোর', Decimal('300')))
        self.assertEqual(Supplier.objects.filter(shop=self.shop).count(), 2)

    def test_delete_purchase_restores_stock_and_cost(self):
        from .models import Purchase, SupplierPayment
        self.buy([(self.shirt.id, 10, 400), (-self.l.id, 3, 600)], supplier=str(self.karim.id), paid='1000')
        purchase = Purchase.objects.get()
        self.client.post(reverse('purchase_delete', args=[purchase.id]))
        self.shirt.refresh_from_db(); self.l.refresh_from_db(); self.kurti.refresh_from_db()
        self.assertEqual((self.shirt.stock_quantity, self.shirt.cost_price), (10, Decimal('300')))
        self.assertEqual((self.l.stock_quantity, self.kurti.stock_quantity, self.kurti.cost_price), (0, 2, Decimal('500')))
        self.assertFalse(SupplierPayment.objects.exists())
        # কিছু বিক্রি হয়ে গেলে মোছা যায় না
        self.buy([(self.cap.id, 2, 100)])
        self.cap.refresh_from_db()
        self.cap.stock_quantity = 1
        self.cap.save()
        purchase = Purchase.objects.get()
        response = self.client.post(reverse('purchase_delete', args=[purchase.id]), follow=True)
        self.assertIn('বিক্রি হয়ে গেছে', response.content.decode())
        self.assertTrue(Purchase.objects.filter(pk=purchase.pk).exists())

    def test_supplier_ledger_and_payment(self):
        from . import ledger
        self.buy([(self.shirt.id, 10, 400)], supplier=str(self.karim.id), paid='1500')
        url = reverse('supplier_detail', args=[self.karim.id])
        self.assertEqual(ledger.supplier_due(self.karim), Decimal('3500'))
        too_much = self.client.post(url, {'action': 'pay', 'amount': '4000'}, follow=True)
        self.assertIn('এর বেশি দেওয়া যাবে না', too_much.content.decode())
        self.client.post(url, {'action': 'pay', 'amount': '২,০০০', 'method': 'bkash', 'note': 'TX1'})
        self.assertEqual(ledger.supplier_due(self.karim), Decimal('1500'))
        page = self.client.get(url).content.decode()
        for text in ['৳১,৫০০', 'বাকি পরিশোধ · bKash · TX1', 'কেনার সময় দেওয়া', 'আগের বাকি']:
            self.assertIn(text, page)
        listing = self.client.get(reverse('supplier_list'))
        self.assertEqual(listing.context['total_due'], Decimal('1500'))
        self.assertIn('মোছা যাবে না', self.client.post(url, {'action': 'delete'}, follow=True).content.decode())
        again = self.client.post(reverse('supplier_list'), {'name': 'করিম ট্রেডার্স'}, follow=True)
        self.assertIn('আগে থেকেই আছে', again.content.decode())

    def test_expenses_and_net_profit_in_report(self):
        from .models import Customer, Expense
        from . import reports
        self.client.post(reverse('expense_list'), {'category': 'rent', 'amount': '৫০০', 'title': 'ভাড়া'})
        self.client.post(reverse('expense_list'), {'category': 'ads', 'amount': '120.50'})
        self.client.post(reverse('expense_list'), {'category': 'rent', 'amount': '0'})            # বাদ পড়বে
        self.assertEqual(Expense.objects.count(), 2)
        customer = Customer.objects.create(shop=self.shop, name='রহিম', phone='01812345678', address='Savar')
        order = Order.objects.create(shop=self.shop, customer=customer, source='pos', status='Delivered',
                                     delivery_charge=0, total_amount=Decimal('900'))
        OrderItem.objects.create(order=order, product=self.shirt, price=Decimal('450'), quantity=2, cost_price=300)
        today = timezone.localdate()
        pl = reports.profit_and_loss(self.shop, today, today, reports.summary(self.shop, today, today))
        self.assertEqual((pl['gross'], pl['expenses']['total'], pl['net']),
                         (Decimal('300'), Decimal('620.50'), Decimal('-320.50')))
        self.assertTrue(pl['net_negative'])
        self.assertEqual([r['key'] for r in pl['expenses']['rows']], ['rent', 'ads'])
        report = self.client.get(reverse('reports') + '?period=today').content.decode()
        for text in ['লাভ-ক্ষতির হিসাব', 'নিট লোকসান', 'দোকান ভাড়া']:
            self.assertIn(text, report)
        page = self.client.get(reverse('expense_list')).content.decode()
        for text in ['৳৬২০.৫০', 'দোকান ভাড়া', 'বিজ্ঞাপন / বুস্ট']:
            self.assertIn(text, page)
        self.client.post(reverse('expense_delete', args=[Expense.objects.filter(category='ads').get().id]))
        self.assertEqual(Expense.objects.count(), 1)
        self.assertEqual(self.client.get(reverse('expense_list') + '?m=2020-01').status_code, 200)
        self.assertEqual(self.client.get(reverse('expense_list') + '?m=junk').status_code, 200)
        from io import BytesIO
        from openpyxl import load_workbook
        book = load_workbook(BytesIO(self.client.get(reverse('reports') + '?period=today&export=xlsx').content))
        self.assertEqual(book.sheetnames, ['সারাংশ', 'অর্ডার', 'প্রোডাক্ট', 'কাস্টমার', 'খরচ', 'মাল কেনা'])

    def test_staff_permissions_and_other_shops(self):
        from .models import Expense, Purchase, StaffProfile, Supplier
        staff = User.objects.create_user(phone_number='01922222222', password='Test-pass-123', name='Karim')
        profile = StaffProfile.objects.create(user=staff, shop=self.shop, can_use_pos=True)
        self.client.force_login(staff)
        for name in ['purchase_list', 'purchase_new', 'supplier_list', 'expense_list']:
            self.assertRedirects(self.client.get(reverse(name)), reverse('dashboard'), fetch_redirect_response=False)
        profile.can_manage_products = True
        profile.save()
        self.assertEqual(self.client.get(reverse('purchase_list')).status_code, 200)
        self.assertEqual(self.client.get(reverse('expense_list')).status_code, 302)       # রিপোর্টের অনুমতি লাগে
        # অন্য দোকানের জিনিস দেখা বা মোছা যায় না
        _other_user, other = self.make_shop(phone='01722222222')
        theirs = Supplier.objects.create(shop=other, name='Their')
        their_buy = Purchase.objects.create(shop=other, purchased_on=timezone.localdate())
        their_cost = Expense.objects.create(shop=other, amount=5, spent_on=timezone.localdate())
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('supplier_detail', args=[theirs.id])).status_code, 404)
        self.assertEqual(self.client.get(reverse('purchase_detail', args=[their_buy.id])).status_code, 404)
        self.assertEqual(self.client.post(reverse('expense_delete', args=[their_cost.id])).status_code, 404)
        self.assertIn('সাপ্লায়ার পাওয়া যায়নি', self.buy([(self.shirt.id, 1, 300)], supplier=str(theirs.id)).content.decode())


class OrderFlowTests(ShopTestMixin, TestCase):
    """অর্ডারের অবস্থা বদল: স্টক ফেরত/কাটা, ওয়েবসাইট অর্ডার মিলিয়ে, অটো SMS-এর সুইচ, ট্র্যাকিং পেজ, ভুয়া অর্ডারের হিসাব, ব্লক।"""

    def setUp(self):
        from .models import Customer, Product
        self.user, self.shop = self.make_shop()
        Shop.objects.filter(pk=self.shop.pk).update(slug='flowshop', sms_balance=50)
        self.shop.refresh_from_db()
        self.shirt = Product.objects.create(shop=self.shop, name='শার্ট', price=Decimal('450'), cost_price=300,
                                            stock_quantity=10)
        self.customer = Customer.objects.create(shop=self.shop, name='রহিম', phone='01812345678', address='Savar')

    def order(self, status='Pending', source='storefront', qty=2, shop=None, customer=None):
        shop = shop or self.shop
        order = Order.objects.create(shop=shop, customer=customer or self.customer, source=source, status=status,
                                     delivery_charge=60, total_amount=Decimal('450') * qty + 60)
        OrderItem.objects.create(order=order, product=self.shirt, price=Decimal('450'), quantity=qty, cost_price=300)
        return order

    def test_cancel_returns_stock_once_and_reopen_takes_it_again(self):
        from . import order_flow
        from .models import StorefrontOrder
        order = self.order()
        sf = StorefrontOrder.objects.create(shop=self.shop, customer_name='রহিম', customer_phone='01812345678',
                                            customer_address='Savar', total_amount=960, order=order)
        self.shirt.stock_quantity = 8
        self.shirt.save()
        self.assertTrue(order_flow.set_status(order, 'Cancelled'))
        self.shirt.refresh_from_db(); sf.refresh_from_db()
        self.assertEqual((self.shirt.stock_quantity, order.stock_returned, sf.status), (10, True, 'Cancelled'))
        self.assertFalse(order_flow.set_status(order, 'Cancelled'))                 # দুবার ফেরত না
        order_flow.set_status(order, 'Returned')
        self.shirt.refresh_from_db()
        self.assertEqual(self.shirt.stock_quantity, 10)
        order_flow.set_status(order, 'Confirmed')
        self.shirt.refresh_from_db(); sf.refresh_from_db()
        self.assertEqual((self.shirt.stock_quantity, order.stock_returned, sf.status), (8, False, 'Confirmed'))
        # স্টক না থাকলে আবার চালু করা যায় না
        order_flow.set_status(order, 'Cancelled')
        self.shirt.stock_quantity = 1
        self.shirt.save()
        with self.assertRaises(order_flow.FlowError):
            order_flow.set_status(order, 'Pending')
        order.refresh_from_db()
        self.assertEqual(order.status, 'Cancelled')
        # অর্ডার মুছলে স্টক আর বাড়ে না (আগেই ফেরত গেছে)
        self.client.post(reverse('order_delete', args=[order.id]))
        self.shirt.refresh_from_db()
        self.assertEqual(self.shirt.stock_quantity, 1)

    def test_status_endpoint_and_pos_untouched(self):
        from . import order_flow
        order = self.order()
        response = self.client.post(reverse('update_order_status'), json.dumps({'order_id': order.id, 'status': 'Confirmed'}),
                                    content_type='application/json').json()
        self.assertTrue(response['success'])
        self.assertIn('কনফার্ম', response['message'])
        bad = self.client.post(reverse('update_order_status'), json.dumps({'order_id': order.id, 'status': 'Lost'}),
                               content_type='application/json').json()
        self.assertFalse(bad['success'])
        pos_sale = self.order(status='Delivered', source='pos')
        self.shirt.stock_quantity = 5
        self.shirt.save()
        order_flow.set_status(pos_sale, 'Cancelled')
        self.shirt.refresh_from_db()
        self.assertEqual(self.shirt.stock_quantity, 5)                                # POS-এর স্টক এখান থেকে বদলায় না

    @mock.patch('store.sms.gateway_send', return_value=(True, 'ok'))
    def test_auto_sms_follows_switches(self, gateway):
        from . import order_flow
        from .models import SmsLog
        order = self.order()
        order_flow.set_status(order, 'Confirmed')                                     # সুইচ বন্ধ → কিছু যায় না
        self.assertEqual(SmsLog.objects.count(), 0)
        self.client.post(reverse('sms_auto'), {'is_sms_active': 'on', 'sms_on_confirmed': 'on', 'sms_on_shipped': 'on'})
        self.shop.refresh_from_db()
        self.assertEqual((self.shop.sms_on_received, self.shop.sms_on_confirmed, self.shop.sms_on_shipped,
                          self.shop.sms_on_delivered), (False, True, True, False))
        order = self.order()
        order_flow.set_status(order, 'Confirmed')
        order_flow.set_status(order, 'Shipped')
        order_flow.set_status(order, 'Delivered')
        texts = [log.message for log in SmsLog.objects.order_by('id')]
        self.assertEqual(len(texts), 2)
        self.assertIn('কনফার্ম হয়েছে', texts[0])
        self.assertIn(f'/t/{order_flow.track_code(order)}', texts[1])              # কুরিয়ারের SMS-এ ট্র্যাকিং লিংক
        self.shop.refresh_from_db()
        self.assertEqual(self.shop.sms_balance, 48)
        self.client.post(reverse('sms_auto'), {'sms_on_confirmed': 'on'})           # মূল সুইচ বন্ধ
        self.shop.refresh_from_db()
        order_flow.set_status(self.order(), 'Confirmed')
        self.assertEqual(SmsLog.objects.count(), 2)
        panel = self.client.get(reverse('sms_panel')).content.decode()
        for text in ['অর্ডার পেলে', 'কনফার্ম করলে', 'কুরিয়ারে দিলে', 'ডেলিভারি হলে']:
            self.assertIn(text, panel)

    def test_tracking_page(self):
        from . import order_flow
        order = self.order(status='Shipped')
        Order.objects.filter(pk=order.pk).update(courier_partner='Steadfast', steadfast_tracking_code='SF123')
        self.client.logout()
        code = order_flow.track_code(order)
        page = self.client.get(f'/shop/flowshop/t/{code}/', HTTP_HOST='localhost')
        self.assertEqual(page.status_code, 200)
        html = page.content.decode()
        for text in ['কুরিয়ারে দেওয়া হয়েছে', 'শার্ট × ২', 'SF123', 'steadfast.com.bd/t/SF123', '018*****678', '৳৯৬০']:
            self.assertIn(text, html)
        self.assertNotIn('Savar', html)                                               # ঠিকানা দেখানো হয় না
        wrong = self.client.get(f'/shop/flowshop/t/{order.id}-000000/', HTTP_HOST='localhost')
        self.assertEqual(wrong.status_code, 302)                                      # ভুল কোড → খোঁজার পেজ
        found = self.client.get(f'/shop/flowshop/track/?order=ORD-{order.id}&phone=০১৮১২-৩৪৫৬৭৮', HTTP_HOST='localhost')
        self.assertRedirects(found, f'/shop/flowshop/t/{code}/', fetch_redirect_response=False)
        missed = self.client.get(f'/shop/flowshop/track/?order={order.id}&phone=01700000000', HTTP_HOST='localhost')
        self.assertIn('পাওয়া যায়নি', missed.content.decode())
        pos_sale = self.order(source='pos')
        self.assertEqual(self.client.get(f'/shop/flowshop/t/{order_flow.track_code(pos_sale)}/',
                                         HTTP_HOST='localhost').status_code, 302)
        home = self.client.get('/shop/flowshop/', HTTP_HOST='localhost').content.decode()
        self.assertIn('অর্ডার ট্র্যাক করুন', home)

    def test_risk_counts_own_and_other_shops_and_block(self):
        from . import risk
        from .models import Customer
        _u2, other = self.make_shop(phone='01722222222')
        theirs = Customer.objects.create(shop=other, name='X', phone='01812345678', address='Dhaka')
        for status in ('Delivered', 'Returned', 'Cancelled'):
            self.order(status=status)
        self.order(status='Returned', shop=other, customer=theirs)
        self.order(status='Delivered', source='pos')                                  # POS ধরা হয় না
        self.client.force_login(self.user)
        r = risk.for_phone(self.shop, '01812345678')
        self.assertEqual((r.own_delivered, r.own_failed, r.other_delivered, r.other_failed), (1, 2, 0, 1))
        self.assertEqual((r.level, r.success_rate), ('risk', 25))
        self.assertIn('ঝুঁকি বেশি', r.label)
        self.assertIn('অন্য দোকানে', r.detail)
        self.assertEqual(risk.for_phone(self.shop, '01999999999').level, 'new')
        data = self.client.get(reverse('order_risk') + '?phone=01812345678').json()
        self.assertEqual((data['level'], data['name']), ('risk', 'রহিম'))
        for name in ('order_list', 'customer_list'):
            self.assertIn('ঝুঁকি বেশি', self.client.get(reverse(name)).content.decode())
        # ব্লক করলে ওয়েবসাইট থেকে অর্ডার নেওয়া হয় না
        self.client.post(reverse('customer_block', args=[self.customer.id]), {'block': '1'})
        self.customer.refresh_from_db()
        self.assertTrue(self.customer.is_blocked)
        self.assertEqual(risk.for_phone(self.shop, '01812345678').level, 'blocked')
        self.client.logout()
        from .delivery import zones_for
        response = self.client.post('/shop/flowshop/place-order/', json.dumps({
            'cart': [{'id': self.shirt.id, 'qty': 1}], 'name': 'রহিম', 'phone': '01812345678', 'address': 'Savar',
            'payment': 'cod', 'zone': zones_for(self.shop)[0].id}), content_type='application/json').json()
        self.assertFalse(response['success'])
        self.assertIn('অর্ডার নেওয়া যাচ্ছে না', response['error'])
        self.client.force_login(self.user)
        self.client.post(reverse('customer_block', args=[self.customer.id]), {'block': '0'})
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.is_blocked)


class OffersReviewsSeoTests(ShopTestMixin, TestCase):
    """কুপন (হিসাব, শর্ত, ব্যবহার), অসম্পূর্ণ অর্ডার, রিভিউ (জমা, অনুমোদন, যাচাই), sitemap/robots/JSON-LD।"""

    def setUp(self):
        from .models import Product
        self.user, self.shop = self.make_shop(slug='ofshop', whatsapp_number='8801711111111')
        self.shirt = Product.objects.create(shop=self.shop, name='শার্ট', price=Decimal('500'), cost_price=300,
                                            stock_quantity=10)
        self.cap = Product.objects.create(shop=self.shop, name='Cap', price=Decimal('200'), cost_price=100,
                                          stock_quantity=5)

    def make_coupon(self, **extra):
        data = {'code': 'EID20', 'kind': 'percent', 'value': '20', 'min_order': '', 'max_discount': '',
                'usage_limit': '', 'starts_on': '', 'ends_on': '', **extra}
        return self.client.post(reverse('coupon_list'), data)

    def place(self, cart, **extra):
        from .delivery import zones_for
        body = {'cart': cart, 'name': 'রহিম', 'phone': '01812345678', 'address': 'Savar', 'payment': 'cod',
                'zone': zones_for(self.shop)[0].id, **extra}
        return self.client.post('/shop/ofshop/place-order/', json.dumps(body), content_type='application/json').json()

    def test_coupon_math_and_rules(self):
        from . import offers
        from .models import Coupon
        self.assertRedirects(self.make_coupon(max_discount='150', min_order='৫০০'), reverse('coupon_list'))
        self.make_coupon(code='flat100', kind='amount', value='100')
        self.make_coupon(code='FREESHIP', kind='free_delivery', usage_limit='1')
        self.assertIn('আগে থেকেই আছে', self.make_coupon().content.decode())
        self.assertIn('বেশি হতে পারে না', self.make_coupon(code='BIG', value='150').content.decode())
        self.assertIn('২–৩০ অক্ষরের', self.make_coupon(code='ঈদ').content.decode())
        self.assertEqual(Coupon.objects.filter(shop=self.shop).count(), 3)
        eid = Coupon.objects.get(code='EID20')
        self.assertEqual((eid.kind, eid.value, eid.max_discount, eid.min_order),
                         ('percent', Decimal('20'), Decimal('150'), Decimal('500')))
        # % ছাড়, সর্বোচ্চে আটকানো; কমপক্ষে অর্ডারের শর্ত; ফ্রি ডেলিভারি; টাকা ছাড়
        coupon, discount, delivery_off = offers.find(self.shop, 'eid20', Decimal('1000'), Decimal('60'))
        self.assertEqual((coupon.code, discount, delivery_off), ('EID20', Decimal('150'), Decimal('0')))
        self.assertEqual(offers.find(self.shop, 'EID20', Decimal('500'), 60)[1], Decimal('100'))
        with self.assertRaisesRegex(offers.CouponError, 'কমপক্ষে'):
            offers.find(self.shop, 'EID20', Decimal('400'), 60)
        self.assertEqual(offers.find(self.shop, 'FREESHIP', Decimal('100'), Decimal('60'))[1:], (Decimal('0'), Decimal('60')))
        self.assertEqual(offers.find(self.shop, 'FLAT100', Decimal('80'), 60)[1], Decimal('80'))      # দামের বেশি না
        with self.assertRaisesRegex(offers.CouponError, 'ঠিক নেই'):
            offers.find(self.shop, 'NOPE', Decimal('1000'), 60)
        self.assertEqual(offers.find(self.shop, '', Decimal('1000'), 60), (None, Decimal('0'), Decimal('0')))
        self.assertEqual(offers.describe(eid), '২০% ছাড় (সর্বোচ্চ ৳১৫০) · কমপক্ষে ৳৫০০ অর্ডারে')

    def test_coupon_in_checkout_and_usage_limit(self):
        from .models import Coupon
        from .delivery import zones_for
        self.make_coupon(code='FREESHIP', kind='free_delivery', usage_limit='1')
        self.make_coupon()
        self.client.logout()
        zone = zones_for(self.shop)[0]
        check = self.client.post('/shop/ofshop/coupon/', json.dumps({'code': 'eid20', 'zone': zone.id,
                                 'cart': [{'id': self.shirt.id, 'qty': 2}]}), content_type='application/json').json()
        self.assertEqual((check['ok'], check['code'], check['discount']), (True, 'EID20', 200.0))
        bad = self.client.post('/shop/ofshop/coupon/', json.dumps({'code': 'XX', 'cart': []}),
                               content_type='application/json').json()
        self.assertFalse(bad['ok'])
        done = self.place([{'id': self.shirt.id, 'qty': 2}], coupon='FREESHIP')
        self.assertTrue(done['success'], done)
        order = Order.objects.get(source='storefront')
        self.assertEqual((order.delivery_charge, order.discount, order.total_amount, order.coupon_code),
                         (Decimal('0'), Decimal('0'), Decimal('1000'), 'FREESHIP'))
        self.assertIn('কুপন FREESHIP', order.note)
        self.assertEqual(Coupon.objects.get(code='FREESHIP').used_count, 1)
        again = self.place([{'id': self.cap.id, 'qty': 1}], coupon='FREESHIP')         # সীমা শেষ
        self.assertEqual((again['success'], again.get('coupon_error')), (False, True))
        pct = self.place([{'id': self.shirt.id, 'qty': 2}], coupon='EID20')
        self.assertTrue(pct['success'], pct)
        order = Order.objects.filter(source='storefront').latest('id')
        self.assertEqual((order.discount, order.total_amount), (Decimal('200'), Decimal('800') + zone.charge))
        self.client.force_login(self.user)
        page = self.client.get(reverse('coupon_list')).content.decode()
        self.assertIn('সীমা শেষ', page)
        self.assertIn('EID20', page)
        self.client.post(reverse('coupon_action', args=[Coupon.objects.get(code='EID20').id]), {'action': 'toggle'})
        self.assertFalse(Coupon.objects.get(code='EID20').is_active)

    def test_abandoned_checkout_saved_then_recovered(self):
        from .models import AbandonedCheckout
        self.client.logout()
        draft = {'phone': '০১৮১২৩৪৫৬৭৮', 'name': 'রহিম', 'address': 'Savar', 'cart': [{'id': self.shirt.id, 'qty': 2}]}
        self.assertTrue(self.client.post('/shop/ofshop/checkout-draft/', json.dumps(draft),
                                         content_type='application/json').json()['ok'])
        draft['cart'] = [{'id': self.shirt.id, 'qty': 1}, {'id': self.cap.id, 'qty': 1}]
        self.client.post('/shop/ofshop/checkout-draft/', json.dumps(draft), content_type='application/json')
        row = AbandonedCheckout.objects.get()                                         # একই নম্বর → একটাই
        self.assertEqual((row.phone, row.total, [i['name'] for i in row.cart]), ('01812345678', Decimal('700'), ['শার্ট', 'Cap']))
        self.assertFalse(self.client.post('/shop/ofshop/checkout-draft/', json.dumps({'phone': '123', 'cart': []}),
                                          content_type='application/json').json()['ok'])
        self.client.force_login(self.user)
        page = self.client.get(reverse('abandoned_list')).content.decode()
        for text in ['শার্ট × ১', '01812345678', '৳৭০০', 'অর্ডার করে দিন']:
            self.assertIn(text, page)
        self.client.logout()
        self.assertTrue(self.place([{'id': self.cap.id, 'qty': 1}])['success'])
        row.refresh_from_db()
        self.assertIsNotNone(row.recovered_order)
        self.client.force_login(self.user)
        self.assertNotIn('01812345678', self.client.get(reverse('abandoned_list')).content.decode())

    def test_reviews_flow(self):
        from .models import Customer, ProductReview
        customer = Customer.objects.create(shop=self.shop, name='রহিম', phone='01812345678', address='Savar')
        order = Order.objects.create(shop=self.shop, customer=customer, source='storefront', status='Delivered',
                                     total_amount=500)
        OrderItem.objects.create(order=order, product=self.shirt, price=500, quantity=1, cost_price=300)
        self.client.logout()
        url = f'/shop/ofshop/product/{self.shirt.id}/review/'
        self.client.post(url, {'name': 'রহিম', 'phone': '01812345678', 'rating': '৪', 'text': 'ভালো কাপড়'})
        self.client.post(url, {'name': 'করিম', 'phone': '01999999999', 'rating': '5', 'text': ''})
        self.client.post(url, {'name': 'রহিম', 'phone': '01812345678', 'rating': '1', 'text': 'দুবার'})   # একই নম্বর
        self.client.post(url, {'name': 'X', 'phone': '123', 'rating': '5'})                             # ভুল নম্বর
        rows = {r.phone: r for r in ProductReview.objects.filter(product=self.shirt)}
        self.assertEqual(len(rows), 2)
        self.assertEqual((rows['01812345678'].rating, rows['01812345678'].verified, rows['01812345678'].is_approved),
                         (4, True, False))
        self.assertFalse(rows['01999999999'].verified)
        page = self.client.get(f'/shop/ofshop/product/{self.shirt.id}/', HTTP_HOST='localhost').content.decode()
        self.assertNotIn('ভালো কাপড়', page)                                             # অনুমোদনের আগে দেখায় না
        self.assertIn('আপনার রিভিউ দিন', page)
        self.assertIn('WhatsApp-এ অর্ডার করুন', page)
        self.assertIn('"@type": "Product"', page)
        self.client.force_login(self.user)
        self.assertIn('অপেক্ষায় ২', self.client.get(reverse('review_list')).content.decode())
        self.client.post(reverse('review_action', args=[rows['01812345678'].id]), {'action': 'approve'})
        self.client.post(reverse('review_action', args=[rows['01999999999'].id]), {'action': 'approve'})
        self.client.logout()
        page = self.client.get(f'/shop/ofshop/product/{self.shirt.id}/', HTTP_HOST='localhost').content.decode()
        for text in ['ভালো কাপড়', 'যাচাই করা ক্রেতা', '৪.৫', '"ratingValue": "4.5"', '"reviewCount": 2']:
            self.assertIn(text, page)
        home = self.client.get('/shop/ofshop/', HTTP_HOST='localhost').content.decode()
        self.assertIn('৪.৫ (২)', home)
        self.assertIn('"@type": "OnlineStore"', home)
        # রিভিউ বন্ধ করলে ফর্ম থাকে না; অটো অনুমোদন চালু করলে সাথে সাথে দেখায়
        self.client.force_login(self.user)
        self.client.post(reverse('review_list'), {'section': 'settings', 'reviews_enabled': 'on', 'reviews_auto_approve': 'on'})
        self.client.logout()
        self.client.post(url, {'name': 'সালমা', 'phone': '01777777777', 'rating': '5', 'text': 'অটো'})
        self.assertTrue(ProductReview.objects.get(phone='01777777777').is_approved)
        self.client.force_login(self.user)
        self.client.post(reverse('review_list'), {'section': 'settings'})
        self.client.logout()
        page = self.client.get(f'/shop/ofshop/product/{self.shirt.id}/', HTTP_HOST='localhost').content.decode()
        self.assertNotIn('আপনার রিভিউ দিন', page)
        self.assertIn('অটো', page)

    def test_sitemap_and_robots(self):
        from .models import Category
        cat = Category.objects.create(shop=self.shop, name='জামা')
        self.shirt.category = cat
        self.shirt.save()
        self.client.logout()
        xml = self.client.get('/shop/ofshop/sitemap.xml', HTTP_HOST='localhost')
        self.assertEqual(xml['Content-Type'], 'application/xml')
        body = xml.content.decode()
        for path in ['/shop/ofshop/</loc>', f'/shop/ofshop/product/{self.shirt.id}/', f'/shop/ofshop/category/{cat.id}/', '/shop/ofshop/track/']:
            self.assertIn(path, body)
        robots = self.client.get('/shop/ofshop/robots.txt', HTTP_HOST='localhost')
        self.assertEqual(robots['Content-Type'], 'text/plain')
        self.assertIn('Sitemap: http://localhost/shop/ofshop/sitemap.xml', robots.content.decode())
        self.assertIn('Disallow: /place-order/', robots.content.decode())
        # সাবডোমেইনে /robots.txt দোকানেরটাই
        with self.settings(STORE_BASE_DOMAIN='sellpunch.com', ALLOWED_HOSTS=['*']):
            response = self.client.get('/robots.txt', HTTP_HOST='ofshop.sellpunch.com')
            self.assertIn('://ofshop.sellpunch.com/sitemap.xml', response.content.decode())


class LandingPageTests(ShopTestMixin, TestCase):
    """ল্যান্ডিং পেজ: বানানো, লিংক, পাবলিক পেজ, সেখান থেকে অর্ডার, ভিজিট আর অর্ডার গোনা, বন্ধ করা।"""

    def setUp(self):
        from .models import Product
        from . import variants
        self.user, self.shop = self.make_shop(slug='lpshop')
        self.saree = Product.objects.create(shop=self.shop, name='টাঙ্গাইল শাড়ি', price=Decimal('1800'),
                                            compare_price=Decimal('2400'), cost_price=1200, stock_quantity=7,
                                            description='আসল তাঁতের শাড়ি')
        self.kurti = Product.objects.create(shop=self.shop, name='কুর্তি', price=Decimal('900'), cost_price=500)
        variants.save_rows(self.kurti, [{'id': None, 'name': 'M', 'price': None, 'stock': 2}])

    def create(self, **extra):
        data = {'product': self.saree.id, 'headline': 'ঘরে বসে পান আসল টাঙ্গাইল শাড়ি', 'subheadline': 'ক্যাশ অন ডেলিভারি',
                'bullets': '১০০% সুতি\nরং যায় না\n\n', 'offer_text': 'আজ ফ্রি ডেলিভারি', 'cta_text': '', 'slug': 'Tangail Saree',
                'show_reviews': 'on', 'show_stock': 'on', 'is_active': 'on', **extra}
        return self.client.post(reverse('landing_new'), data)

    def test_create_and_public_page(self):
        from .models import LandingPage
        self.assertRedirects(self.create(), reverse('landing_list'))
        page = LandingPage.objects.get()
        self.assertEqual((page.slug, page.cta_text, page.bullet_list), ('tangail-saree', 'এখনই অর্ডার করুন', ['১০০% সুতি', 'রং যায় না']))
        self.assertIn('নিন', self.create(slug='tangail-saree').content.decode())      # একই লিংক দুবার না
        self.assertIn('প্রোডাক্ট বেছে নিন', self.create(product=999).content.decode())
        listing = self.client.get(reverse('landing_list')).content.decode()
        self.assertIn('/shop/lpshop/l/tangail-saree/', listing)
        self.client.logout()
        response = self.client.get('/shop/lpshop/l/tangail-saree/', HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        for text in ['ঘরে বসে পান আসল টাঙ্গাইল শাড়ি', 'আজ ফ্রি ডেলিভারি', '১০০% সুতি', '৳১,৮০০', '৳২,৪০০', '২৫% ছাড়',
                     'মাত্র ৭টা বাকি', 'অর্ডার করতে ফর্মটা পূরণ করুন', '"@type": "Product"', 'আসল তাঁতের শাড়ি']:
            self.assertIn(text, html)
        self.assertNotIn('সাইজ / রং', html)
        page.refresh_from_db()
        self.assertEqual(page.views, 1)
        self.assertEqual(self.client.get('/shop/lpshop/l/nope/', HTTP_HOST='localhost').status_code, 404)

    def test_order_from_landing_page_is_counted(self):
        from .delivery import zones_for
        from .models import LandingPage
        self.create()
        page = LandingPage.objects.get()
        self.client.logout()
        done = self.client.post('/shop/lpshop/place-order/', json.dumps({
            'cart': [{'id': self.saree.id, 'qty': 2}], 'name': 'রহিম', 'phone': '01812345678', 'address': 'Savar, Dhaka',
            'payment': 'cod', 'zone': zones_for(self.shop)[0].id, 'landing': 'tangail-saree'}),
            content_type='application/json').json()
        self.assertTrue(done['success'], done)
        order = Order.objects.get(source='storefront')
        self.assertEqual(order.landing_id, page.id)
        self.assertIn('ল্যান্ডিং পেজ: ঘরে বসে', order.note)
        self.client.force_login(self.user)
        listing = self.client.get(reverse('landing_list'))
        self.assertEqual(listing.context['total_orders'], 1)
        # বাতিল হলে গোনা হয় না
        from . import order_flow
        order_flow.set_status(order, 'Cancelled')
        self.assertEqual(self.client.get(reverse('landing_list')).context['total_orders'], 0)

    def test_variants_toggle_and_other_shop(self):
        from .models import LandingPage
        self.create(product=self.kurti.id, slug='kurti')
        self.client.logout()
        html = self.client.get('/shop/lpshop/l/kurti/', HTTP_HOST='localhost').content.decode()
        self.assertIn('সাইজ / রং', html)
        self.assertIn('data-id="-', html)
        page = LandingPage.objects.get()
        self.client.force_login(self.user)
        self.client.post(reverse('landing_action', args=[page.id]), {'action': 'toggle'})
        self.client.logout()
        off = self.client.get('/shop/lpshop/l/kurti/', HTTP_HOST='localhost')
        self.assertEqual(off.status_code, 302)                                       # বন্ধ → দোকানের হোম
        _u2, _other = self.make_shop(phone='01722222222')
        self.client.force_login(_u2)
        self.assertEqual(self.client.get(reverse('landing_edit', args=[page.id])).status_code, 404)
        self.assertEqual(self.client.post(reverse('landing_action', args=[page.id]), {'action': 'delete'}).status_code, 404)
        self.assertTrue(LandingPage.objects.filter(pk=page.pk).exists())


class DueBookTests(ShopTestMixin, TestCase):
    """বাকির খাতা: কার কত বাকি, বয়স, খাতা, আদায়, প্রতিশ্রুতি, তাগাদা SMS (হাতে, বাছাই করে, নিজে থেকে)।"""

    def setUp(self):
        from .models import Customer, Product
        self.user, self.shop = self.make_shop()
        Shop.objects.filter(pk=self.shop.pk).update(sms_balance=20)
        self.shop.refresh_from_db()
        self.shirt = Product.objects.create(shop=self.shop, name='শার্ট', price=450, cost_price=300, stock_quantity=50)
        self.rahim = Customer.objects.create(shop=self.shop, name='রহিম উদ্দিন', phone='01812345678', address='Savar')
        self.karim = Customer.objects.create(shop=self.shop, name='করিম', phone='01911111111', address='Dhaka')
        self.walkin = Customer.objects.create(shop=self.shop, name='Walk-in', phone='00000000000', address='')

    def sale(self, customer, total, paid, days_ago=0):
        order = Order.objects.create(shop=self.shop, customer=customer, source='pos', status='Delivered',
                                     delivery_charge=0, total_amount=Decimal(total), advance_paid=Decimal(paid))
        OrderItem.objects.create(order=order, product=self.shirt, price=450, quantity=1, cost_price=300)
        if days_ago:
            Order.objects.filter(pk=order.pk).update(created_at=timezone.now() - timedelta(days=days_ago))
        return order

    def test_rows_and_summary(self):
        from . import dues
        self.sale(self.rahim, 1000, 400, days_ago=40)        # ৬০০ বাকি, পুরনো
        self.sale(self.rahim, 500, 500)                       # শোধ
        self.sale(self.rahim, 300, 0)                         # ৩০০ বাকি
        self.sale(self.karim, 200, 50, days_ago=3)            # ১৫০ বাকি
        self.sale(self.walkin, 100, 0)                        # walk-in ধরা হয় না
        cancelled = self.sale(self.karim, 900, 0)
        Order.objects.filter(pk=cancelled.pk).update(status='Returned')
        rows = dues.rows(self.shop)
        self.assertEqual([(r['phone'], r['due'], r['bills'], r['age']) for r in rows],
                         [('01812345678', Decimal('900'), 2, 'old'), ('01911111111', Decimal('150'), 1, 'new')])
        self.assertEqual(rows[0]['days'], 40)
        summary = dues.summary(self.shop, rows)
        self.assertEqual((summary['total'], summary['people'], summary['old'], summary['old_people']),
                         (Decimal('1050'), 2, Decimal('900'), 1))
        page = self.client.get(reverse('due_list')).content.decode()
        for text in ['রহিম উদ্দিন', '৳৯০০', '৪০ দিন', 'সবাইকে তাগাদা SMS', 'নিজে থেকে তাগাদা']:
            self.assertIn(text, page)
        self.assertNotIn('Walk-in', page)
        self.assertEqual(len(self.client.get(reverse('due_list') + '?show=old').context['rows']), 1)
        self.assertEqual(len(self.client.get(reverse('due_list') + '?q=করিম').context['rows']), 1)

    def test_ledger_collect_and_promise(self):
        from .models import Customer, SalePayment
        self.sale(self.rahim, 1000, 400, days_ago=10)
        self.sale(self.rahim, 300, 0)
        url = reverse('due_detail', args=['01812345678'])
        page = self.client.get(url).content.decode()
        self.assertIn('৳৯০০', page)
        self.assertIn('বাকি আদায়', page)
        too_much = self.client.post(url, {'action': 'collect', 'amount': '2000'}, follow=True).content.decode()
        self.assertIn('বাকি আছে মাত্র', too_much)
        self.client.post(url, {'action': 'collect', 'amount': '৭০০', 'method': 'bkash', 'reference': 'TX9'})
        orders = list(Order.objects.filter(customer=self.rahim).order_by('created_at'))
        self.assertEqual((orders[0].advance_paid, orders[1].advance_paid), (Decimal('1000'), Decimal('100')))   # পুরনোটা আগে
        self.assertEqual(SalePayment.objects.filter(kind=SalePayment.DUE_COLLECTION).count(), 2)
        page = self.client.get(url).content.decode()
        self.assertIn('৳২০০', page)
        self.assertIn('TX9', page)
        self.client.post(url, {'action': 'promise', 'promise': '2026-12-01', 'note': 'বেতন পেলে দেবে'})
        self.rahim.refresh_from_db()
        self.assertEqual((str(self.rahim.due_promise), self.rahim.due_note), ('2026-12-01', 'বেতন পেলে দেবে'))
        self.assertEqual(self.client.get(reverse('due_detail', args=['01700000000'])).status_code, 302)

    @mock.patch('store.sms.gateway_send', return_value=(True, 'ok'))
    def test_reminders_manual_selected_and_auto(self, gateway):
        from types import SimpleNamespace
        from . import dues, sms
        from .models import Customer, SmsLog
        self.sale(self.rahim, 1000, 0)
        self.sale(self.karim, 500, 250)
        # সবাইকে
        response = self.client.post(reverse('due_remind_all'), follow=True)
        self.assertIn('২ জনকে SMS পাঠানো হয়েছে', response.content.decode())
        log = SmsLog.objects.get()
        self.assertEqual((log.recipients, log.sms_used, log.audience), (2, 2, 'বাকির তাগাদা'))
        texts = [call.args[1] for call in gateway.call_args_list]
        self.assertTrue(any('১,০০০' in t for t in texts), texts)
        self.assertTrue(any('২৫০' in t for t in texts), texts)
        self.assertIn('রহিম', sms.due_reminder_text(SimpleNamespace(name='মুন্না ফ্যাশন'), 'রহিম উদ্দিন', Decimal('1000')))
        self.shop.refresh_from_db()
        self.assertEqual(self.shop.sms_balance, 18)
        # একই দিনে আবার না
        again = self.client.post(reverse('due_remind_all'), follow=True)
        self.assertIn('তাগাদা পাঠানোর মতো কেউ নেই', again.content.decode())
        self.assertEqual(SmsLog.objects.count(), 1)
        # একজনকে বাছাই করে (খাতা থেকে, একই দিনে হলেও যায়)
        self.client.post(reverse('due_detail', args=['01911111111']), {'action': 'remind'})
        self.assertEqual(SmsLog.objects.count(), 2)
        # নিজে থেকে: ৭ দিন পর পর
        self.client.post(reverse('due_auto_setting'), {'days': '7'})
        self.shop.refresh_from_db()
        self.assertEqual(self.shop.due_reminder_days, 7)
        self.assertEqual(dues.run_auto_reminders(), {})                                   # আজই তাগাদা গেছে
        Customer.objects.filter(shop=self.shop).update(due_reminded_at=timezone.now() - timedelta(days=8))
        self.assertEqual(dues.run_auto_reminders(), {self.shop.id: 2})
        self.assertEqual(SmsLog.objects.filter(kind='auto').count(), 1)
        # SMS বন্ধ থাকলে তাগাদা যায় না
        Shop.objects.filter(pk=self.shop.pk).update(is_sms_active=False)
        Customer.objects.filter(shop=self.shop).update(due_reminded_at=None)
        self.assertIn('বন্ধ আছে', self.client.post(reverse('due_remind_all'), follow=True).content.decode())
        self.assertEqual(dues.run_auto_reminders(), {})

    def test_staff_needs_pos_permission(self):
        from .models import StaffProfile
        staff = User.objects.create_user(phone_number='01922222222', password='Test-pass-123', name='Karim')
        profile = StaffProfile.objects.create(user=staff, shop=self.shop, can_manage_orders=True, can_use_pos=False)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(reverse('due_list')).status_code, 302)
        profile.can_use_pos = True
        profile.save()
        self.assertEqual(self.client.get(reverse('due_list')).status_code, 200)
        self.assertIn('এটা মালিক বদলাতে পারবেন', self.client.post(reverse('due_auto_setting'), {'days': '7'}, follow=True).content.decode())


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


class DemoShopTests(TestCase):
    """লাইভ ডেমো: সাজানো দোকান, পাসওয়ার্ড ছাড়া ঢোকা, রোজ রিসেট, ক্ষতিকর কাজ বন্ধ।"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import tempfile
        cls.media = tempfile.mkdtemp()
        cls._override = override_settings(MEDIA_ROOT=cls.media)
        cls._override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._override.disable()
        import shutil
        shutil.rmtree(cls.media, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        from store import demo
        self.shop = demo.build()

    def test_seed_builds_a_full_shop(self):
        from store import demo, dues
        from .models import Coupon, Customer, Expense, LandingPage, ProductReview, Purchase, SmsLog, StaffProfile
        shop = self.shop
        self.assertTrue(shop.is_demo)
        self.assertEqual(shop.slug, demo.DEMO_SLUG)
        self.assertEqual(shop.products.count(), len(demo.PRODUCTS))
        self.assertTrue(all(p.image and p.thumbnail for p in shop.products.all()))
        self.assertEqual(shop.banners.count(), 2)
        self.assertGreater(shop.orders.filter(source='pos').count(), 150)
        self.assertGreater(shop.orders.filter(source='storefront', status='Delivered').count(), 80)
        self.assertGreater(shop.orders.filter(status='Pending').count(), 0)
        self.assertGreater(Customer.objects.filter(shop=shop).count(), 50)
        self.assertGreater(len(dues.rows(shop)), 3)
        self.assertEqual(Purchase.objects.filter(shop=shop).count(), 7)
        self.assertGreater(Expense.objects.filter(shop=shop).count(), 20)
        self.assertGreater(ProductReview.objects.filter(shop=shop, is_approved=True).count(), 10)
        self.assertEqual(Coupon.objects.filter(shop=shop).count(), 4)
        self.assertEqual(LandingPage.objects.filter(shop=shop).count(), 1)
        self.assertGreater(SmsLog.objects.filter(shop=shop).count(), 5)
        self.assertEqual(StaffProfile.objects.filter(shop=shop).count(), 1)
        self.assertFalse(shop.user.has_usable_password())
        # হিসাব মেলে: অর্ডারের তারিখ ৯০ দিনে ছড়ানো
        oldest = shop.orders.order_by('created_at').first().created_at
        self.assertLess(oldest, timezone.now() - timedelta(days=80))

    def test_rebuild_keeps_images_and_resets_activity(self):
        from store import demo
        from .models import Order, Product
        shop = self.shop
        names = sorted(shop.products.values_list('image', flat=True))
        product = shop.products.first()
        product.name = 'দর্শকের বদলানো নাম'
        product.save()
        extra = Product.objects.create(shop=shop, name='দর্শকের প্রোডাক্ট', price=10, barcode='VISITOR-1')
        Order.objects.filter(shop=shop).delete()
        demo.build()
        self.assertEqual(sorted(shop.products.values_list('image', flat=True)), names)   # ছবি আবার আপলোড হয় না
        self.assertFalse(Product.objects.filter(pk=extra.pk).exists())
        self.assertNotEqual(Product.objects.get(pk=product.pk).name, 'দর্শকের বদলানো নাম')
        self.assertGreater(shop.orders.count(), 300)

    def test_demo_login_without_password(self):
        response = self.client.get(reverse('demo_start'))
        self.assertRedirects(response, '/dashboard/', fetch_redirect_response=False)
        html = self.client.get(reverse('dashboard')).content.decode()
        self.assertIn('লাইভ ডেমো', html)
        self.assertIn('নিজের দোকান খুলুন', html)
        self.assertEqual(self.client.get(reverse('demo_start') + '?to=pos').url, '/pos/')
        self.assertEqual(self.client.get(reverse('pos')).status_code, 200)
        self.assertEqual(self.client.get(reverse('reports')).status_code, 200)
        self.assertEqual(self.client.get(reverse('due_list')).status_code, 200)
        self.assertEqual(self.client.get(reverse('demo_store')).url, self.shop.storefront_url)
        self.assertEqual(self.client.get(self.shop.storefront_url).status_code, 200)

    def test_logged_in_seller_is_asked_before_switching(self):
        user = User.objects.create_user(phone_number='01755555555', password='Test-pass-123')
        Shop.objects.create(user=user, name='Real', phone='01755555555', address='Dhaka')
        self.client.force_login(user)
        response = self.client.get(reverse('demo_start') + '?to=pos')
        self.assertEqual(response.status_code, 200)
        self.assertIn('লগআউট করে ডেমোতে ঢুকুন', response.content.decode())
        self.assertEqual(int(self.client.session['_auth_user_id']), user.pk)      # এখনো নিজের অ্যাকাউন্টে
        response = self.client.post(reverse('demo_start') + '?to=pos')
        self.assertRedirects(response, '/pos/', fetch_redirect_response=False)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.shop.user.pk)

    def test_demo_never_takes_over_a_real_account(self):
        from store import demo
        # কেউ 01700000001 নম্বরে আসল দোকান খুলে রেখেছে — ডেমো অন্য নম্বর নেয়, ওই দোকানে হাত দেয় না
        Shop.objects.filter(is_demo=True).delete()
        User.objects.filter(phone_number__in=[demo.DEMO_PHONE, demo.DEMO_STAFF_PHONE]).delete()
        real = User.objects.create_user(phone_number=demo.DEMO_PHONE, password='Test-pass-123', name='আসল মানুষ')
        real_shop = Shop.objects.create(user=real, name='আসল দোকান', phone=demo.DEMO_PHONE, address='Dhaka')
        shop = demo.build()
        self.assertNotEqual(shop.pk, real_shop.pk)
        self.assertNotEqual(shop.user.phone_number, demo.DEMO_PHONE)
        real.refresh_from_db()
        real_shop.refresh_from_db()
        self.assertEqual((real.name, real_shop.name, real_shop.is_demo), ('আসল মানুষ', 'আসল দোকান', False))
        self.assertTrue(real.check_password('Test-pass-123'))

    def test_homepage_shows_demo_error_message(self):
        from store import demo
        with mock.patch('store.demo.build', side_effect=RuntimeError('boom')):
            Shop.objects.filter(is_demo=True).delete()
            response = self.client.get(reverse('demo_start'), follow=True)
        self.assertIn('ডেমো এখন চালু নেই', response.content.decode())

    def test_demo_blocks_settings_billing_and_deletes(self):
        from store import demo
        self.client.get(reverse('demo_start'))
        product = self.shop.products.first()
        response = self.client.post(reverse('settings'), {'name': 'হ্যাক'}, HTTP_REFERER='http://testserver/settings/')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Shop.objects.get(pk=self.shop.pk).name, demo.SHOP_NAME)
        self.assertEqual(self.client.post(reverse('billing'), {'plan': 'Premium'}).status_code, 302)
        self.assertEqual(self.client.post(reverse('website_settings'), {'section': 'domain', 'custom_domain': 'x.com'}).status_code, 302)
        self.client.post(reverse('delete_product', args=[product.pk]))
        self.assertTrue(self.shop.products.filter(pk=product.pk).exists())
        # JSON চাওয়া হলে JSON-এ "না"
        response = self.client.post(reverse('billing'), {'plan': 'Premium'}, HTTP_ACCEPT='application/json')
        self.assertEqual(response.status_code, 403)
        self.assertIn('ডেমো', response.json()['error'])
        # সাধারণ কাজ চলে: প্রোডাক্ট বদলানো, ডিজাইন বদলানো
        response = self.client.post(reverse('website_settings'), {'section': 'design', 'storefront_theme': 'blue',
                                                                  'storefront_design': 'minimal', 'color_mode': 'theme'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Shop.objects.get(pk=self.shop.pk).storefront_theme, 'blue')

    def test_demo_sms_never_reaches_gateway(self):
        from store import sms
        with mock.patch('store.sms.gateway_send') as gateway:
            result = sms.send(self.shop, ['01811111111'], 'ডেমো থেকে টেস্ট', 'test')
            self.assertTrue(result.ok)
            gateway.assert_not_called()
        self.assertEqual(Shop.objects.get(pk=self.shop.pk).sms_balance, 436)

    def test_stale_demo_is_rebuilt_once(self):
        from store import demo
        from .models import Order
        Shop.objects.filter(pk=self.shop.pk).update(demo_reset_at=timezone.now() - timedelta(hours=30))
        Order.objects.filter(shop=self.shop).delete()
        with mock.patch('store.demo.build', wraps=demo.build) as build:
            demo.reset_if_stale()
            demo.reset_if_stale()
            self.assertEqual(build.call_count, 1)
        self.assertGreater(Order.objects.filter(shop=self.shop).count(), 300)

    def test_demo_excluded_from_master_numbers_and_risk(self):
        from store import risk
        admin = User.objects.create_superuser(phone_number='01799999990', password='Test-pass-123')
        self.client.force_login(admin)
        context = self.client.get(reverse('master_dashboard')).context
        self.assertEqual(context['total_shops'], 0)
        self.assertEqual(context['total_platform_orders'], 0)
        # ডেমোর ফেরত-আসা কাস্টমারের নম্বর আসল দোকানে "ঝুঁকি" হিসেবে দেখায় না
        returned = Order.objects.filter(shop=self.shop, status='Returned').first()
        real_user = User.objects.create_user(phone_number='01755555556', password='Test-pass-123')
        real_shop = Shop.objects.create(user=real_user, name='Real', phone='01755555556', address='Dhaka')
        self.assertEqual(risk.for_phones(real_shop, [returned.customer.phone])[returned.customer.phone].level, 'new')

    def test_demo_check_page_for_master(self):
        self.assertEqual(self.client.get(reverse('demo_check')).status_code, 302)        # মাস্টার ছাড়া না
        admin = User.objects.create_superuser(phone_number='01799999991', password='Test-pass-123')
        self.client.force_login(admin)
        response = self.client.get(reverse('demo_check'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('ডেমো ঠিক আছে', response.content.decode())
        with mock.patch('store.demo.build', side_effect=RuntimeError('boom')):
            response = self.client.get(reverse('demo_check'))
        self.assertEqual(response.status_code, 500)
        self.assertIn('RuntimeError: boom', response.content.decode())


class HealthWarningTests(TestCase):
    def test_bad_bucket_name_is_reported(self):
        from store import health
        account = '0c5dc12c8f2cb73f93d85be7d218f5c7'
        with override_settings(USE_R2=True, R2_BUCKET_NAME='Sohojsell api', R2_PUBLIC_DOMAIN='pub.r2.dev', R2_ACCOUNT_ID=account):
            texts = health.warnings()
        self.assertEqual(len(texts), 1)
        self.assertIn('R2_BUCKET_NAME', texts[0])
        with override_settings(USE_R2=True, R2_BUCKET_NAME='sohojsell-media', R2_PUBLIC_DOMAIN='pub.r2.dev', R2_ACCOUNT_ID=account):
            self.assertEqual(health.warnings(), [])

    def test_pasted_urls_are_normalized(self):
        from sohojsell.settings import _r2_account_id, _r2_bucket
        self.assertEqual(_r2_account_id('https://0c5dc12c8f2cb73f93d85be7d218f5c7.r2.cloudflarestorage.com/sohojsell-media'),
                         '0c5dc12c8f2cb73f93d85be7d218f5c7')
        self.assertEqual(_r2_account_id(' 0c5dc12c8f2cb73f93d85be7d218f5c7 '), '0c5dc12c8f2cb73f93d85be7d218f5c7')
        self.assertEqual(_r2_bucket('https://0c5dc12c8f2cb73f93d85be7d218f5c7.r2.cloudflarestorage.com/sohojsell-media'),
                         'sohojsell-media')
        self.assertEqual(_r2_bucket('sohojsell-media'), 'sohojsell-media')
        from store import health
        with override_settings(USE_R2=True, R2_BUCKET_NAME='sohojsell-media', R2_PUBLIC_DOMAIN='pub.r2.dev',
                               R2_ACCOUNT_ID='https://x.r2.cloudflarestorage.com'):
            self.assertIn('R2_ACCOUNT_ID', health.warnings()[0])

    def test_master_dashboard_shows_warning(self):
        admin = User.objects.create_superuser(phone_number='01799999992', password='Test-pass-123')
        self.client.force_login(admin)
        with override_settings(USE_R2=True, R2_BUCKET_NAME='Sohojsell api', R2_PUBLIC_DOMAIN='pub.r2.dev',
                               R2_ACCOUNT_ID='0c5dc12c8f2cb73f93d85be7d218f5c7'):
            html = self.client.get(reverse('master_dashboard')).content.decode()
        self.assertIn('সার্ভারের সেটিংসে সমস্যা', html)
        self.assertIn('Sohojsell api', html)


class HealthzTests(TestCase):
    def test_healthz_is_instant_and_public(self):
        response = self.client.get('/healthz/')
        self.assertEqual((response.status_code, response.content), (200, b'ok'))


class WebOrderNumberTests(ShopTestMixin, TestCase):
    """ওয়েবসাইটের অর্ডার আর সব অর্ডার — এক অর্ডার, এক নম্বর; সাইডবারে নতুন অর্ডারের সংখ্যা।"""

    def setUp(self):
        from store.models import Customer, StorefrontOrder
        self.user, self.shop = self.make_shop()
        self.customer = Customer.objects.create(shop=self.shop, name='কাস্টমার', phone='01811111111', address='ঢাকা')
        self.order = Order.objects.create(shop=self.shop, customer=self.customer, source='storefront', status='Pending',
                                          total_amount=470, delivery_charge=0)
        self.sf = StorefrontOrder.objects.create(shop=self.shop, customer_name='কাস্টমার', customer_phone='01811111111',
                                                 customer_address='ঢাকা', total_amount=470, order=self.order)
        self.client.force_login(self.user)

    def test_web_orders_page_shows_main_order_number(self):
        html = self.client.get(reverse('storefront_orders')).content.decode()
        self.assertIn(f'#{self.order.id}', html)
        self.assertNotIn(f'#SF-{self.sf.id}', html)
        self.assertIn('নতুন', html)
        for q in (f'#{self.order.id}', f'ORD-{self.order.id}', str(self.order.id)):
            self.assertIn(f'#{self.order.id}', self.client.get(reverse('storefront_orders') + f'?q={q}').content.decode())
        self.assertNotIn('<td>', self.client.get(reverse('storefront_orders') + '?q=999999').content.decode().split('<tbody>')[1].split('</tr>')[0].replace('<td colspan', ''))

    def test_all_orders_search_accepts_hash_and_bangla_digits(self):
        bn = str(self.order.id).translate(str.maketrans('0123456789', '০১২৩৪৫৬৭৮৯'))
        for q in (f'#{self.order.id}', f'ord-{self.order.id}', bn):
            html = self.client.get(reverse('order_list') + f'?q={q}').content.decode()
            self.assertIn(f'#{self.order.id}', html)

    def test_sidebar_counts_pending_web_orders(self):
        badge = 'class="badge ms-auto sb-new-badge"'
        html = self.client.get(reverse('dashboard')).content.decode()
        self.assertEqual(html.count(badge), 2)          # "সব অর্ডার" আর "ওয়েবসাইটের অর্ডার" দুটোতেই
        self.assertIn('sb-new-badge" title="ওয়েবসাইটের নতুন অর্ডার">1</span>', html)
        Order.objects.filter(pk=self.order.pk).update(status='Confirmed')
        self.assertNotIn(badge, self.client.get(reverse('dashboard')).content.decode())


class StorefrontOrderUiTests(TestCase):
    """ওয়েবসাইট: পরিমাণ বাছাই, চেকআউটে অর্ডারের তালিকা, লোগো চাপলে হোম, ব্যানার না কাটা।"""

    def setUp(self):
        from .models import Product
        user = User.objects.create_user(phone_number='01788888881', password='Test-pass-123')
        self.shop = Shop.objects.create(user=user, name='টেস্ট দোকান', phone='01788888881', address='ঢাকা', slug='testsf')
        self.product = Product.objects.create(shop=self.shop, name='টি-শার্ট', price=450, stock_quantity=10)

    def test_product_page_has_quantity_and_checkout_items(self):
        html = self.client.get(reverse('storefront_product_detail', args=[self.shop.slug, self.product.id])).content.decode()
        self.assertIn('id="qty-val"', html)
        self.assertIn('id="co-items"', html)
        self.assertIn('buyNow(i.id, i.name, i.price, i.stock, i.image, chosenQty)', html)

    def test_home_logo_links_home_and_bar_is_not_fixed(self):
        html = self.client.get(reverse('storefront_home', args=[self.shop.slug])).content.decode()
        self.assertIn('class="shop-home-link"', html)
        self.assertIn('.app-top-bar { position: sticky;', html)
        self.assertNotIn('padding-top: 135px', html)

    def test_two_orders_with_quantity(self):
        from store import delivery
        url = reverse('storefront_place_order', args=[self.shop.slug])
        zone = delivery.zones_for(self.shop)[0].id
        for qty in (3, 2):
            response = self.client.post(url, json.dumps({'cart': [{'id': self.product.id, 'qty': qty}], 'name': 'ক',
                                                         'phone': '01812345678', 'address': 'ঢাকা', 'payment': 'cod',
                                                         'zone': zone}),
                                        content_type='application/json')
            self.assertTrue(response.json()['success'], response.json())
        self.assertEqual(sorted(OrderItem.objects.filter(order__shop=self.shop).values_list('quantity', flat=True)), [2, 3])
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 5)


class StorefrontEnglishTests(TestCase):
    """
    ইংরেজি দোকান: কাস্টমার যা যা দেখে তার কোথাও বাংলা অক্ষর থাকা চলবে না (সেলারের নিজের লেখা এখানে ইংরেজি)।
    নতুন বাংলা লেখা যোগ করে store/sf_en.py-তে ইংরেজি দিতে ভুলে গেলে এই টেস্ট কোন পাতায় কী বাকি দেখিয়ে দেয়।
    """
    BN_RUN = re.compile(r'[\u0980-\u09F2\u09F4-\u09FF][\u0980-\u09FF\s,।?!\-–—:;"\'()/]*')   # ৳ (টাকার চিহ্ন) বাদে

    def setUp(self):
        from .models import Category, Coupon, LandingPage, Product, ProductReview, ProductVariant
        user = User.objects.create_user(phone_number='01788800001', password='Test-pass-123')
        self.shop = Shop.objects.create(
            user=user, name='Urban Threads', phone='01788800001', address='Gulshan 1, Dhaka', slug='urban',
            storefront_language='en', announcement_text='Free delivery over 2000 Tk', storefront_tagline='Everyday cotton',
            return_policy='Exchange within 3 days.', privacy_policy='We only use your phone for delivery.',
            free_delivery_min=2000, reviews_enabled=True, reviews_auto_approve=True, show_sold_count=True,
            whatsapp_number='01788800001', facebook_page_url='https://facebook.com/urban')
        cat = Category.objects.create(shop=self.shop, name='T-Shirts')
        self.tee = Product.objects.create(shop=self.shop, category=cat, name='Cotton Tee', price=450, compare_price=550,
                                          cost_price=250, stock_quantity=4, description='Soft cotton.', has_variants=True)
        ProductVariant.objects.create(product=self.tee, name='M', stock_quantity=1)
        ProductVariant.objects.create(product=self.tee, name='L', stock_quantity=3)
        self.cap = Product.objects.create(shop=self.shop, category=cat, name='Black Cap', price=350, stock_quantity=20)
        self.gone = Product.objects.create(shop=self.shop, category=cat, name='Old Jacket', price=900, stock_quantity=0)
        ProductReview.objects.create(shop=self.shop, product=self.cap, name='Rafi', phone='01811112222', rating=5,
                                     text='Great cap', verified=True, is_approved=True)
        Coupon.objects.create(shop=self.shop, code='SAVE10', kind=Coupon.PERCENT, value=10, min_order=1000)
        self.landing = LandingPage.objects.create(shop=self.shop, product=self.cap, slug='cap', headline='The cap',
                                                  bullets='Cash on delivery\nFast shipping', cta_text='Order now')

    # ---------------------------------------------------------------- সাহায্যকারী
    def _bangla(self, text):
        text = re.sub(r'<!--.*?-->', ' ', text, flags=re.S)                      # HTML মন্তব্য কাস্টমার দেখে না
        text = re.sub(r'/\*.*?\*/', ' ', text, flags=re.S)
        text = re.sub(r'(?m)^\s*//.*$|\s//\s.*$', ' ', text)                     # JS মন্তব্য
        return sorted({m.group(0).strip() for m in self.BN_RUN.finditer(text)} - {''})

    def _check(self, label, text, found):
        runs = self._bangla(text)
        if runs:
            found.append(f'{label}: ' + ' | '.join(runs[:40]))

    def _post_json(self, url, data):
        return self.client.post(url, json.dumps(data), content_type='application/json')

    def _order(self, **extra):
        from store import delivery
        zone = delivery.zones_for(self.shop)[0].id
        data = {'cart': [{'id': self.cap.id, 'qty': 1}], 'name': 'Nadia', 'phone': '01812345678',
                'address': 'Banani, Dhaka', 'payment': 'cod', 'zone': zone} | extra
        return self._post_json(reverse('storefront_place_order', args=[self.shop.slug]), data)

    # ---------------------------------------------------------------- টেস্ট
    def test_every_customer_page_is_english(self):
        from store.models import StorefrontOrder
        slug, found = self.shop.slug, []
        pages = [
            ('home', reverse('storefront_home', args=[slug])),
            ('category', reverse('storefront_category', args=[slug, self.tee.category_id])),
            ('search', reverse('storefront_home', args=[slug]) + '?q=zzz'),
            ('product variants', reverse('storefront_product_detail', args=[slug, self.tee.id])),
            ('product', reverse('storefront_product_detail', args=[slug, self.cap.id])),
            ('product out of stock', reverse('storefront_product_detail', args=[slug, self.gone.id])),
            ('landing', reverse('storefront_landing', args=[slug, 'cap'])),
            ('track', reverse('storefront_track', args=[slug])),
            ('track not found', reverse('storefront_track', args=[slug]) + '?order=999&phone=01812345678'),
        ]
        for label, url in pages:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, label)
            self._check(label, response.content.decode(), found)
            self.assertIn('lang="en"', response.content.decode(), label)

        response = self._order()
        self.assertTrue(response.json()['success'], response.json())
        sf = StorefrontOrder.objects.get(shop=self.shop)
        self._check('order success', self.client.get(reverse('storefront_order_success', args=[slug, sf.id])).content.decode(), found)
        from store import order_flow
        for status in ('Pending', 'Confirmed', 'Shipped', 'Delivered', 'Cancelled'):
            order_flow.set_status(sf.order, status) if status != 'Pending' else None
            code = order_flow.track_code(sf.order)
            self._check(f'tracking {status}', self.client.get(reverse('storefront_track_order', args=[slug, code])).content.decode(), found)

        # দোকান বন্ধ থাকলে
        Shop.objects.filter(pk=self.shop.pk).update(is_locked=True, valid_until=timezone.localdate() - timedelta(days=30))
        self._check('offline', self.client.get(reverse('storefront_home', args=[slug])).content.decode(), found)
        self.assertFalse(found, '\n' + '\n'.join(found))

    def test_messages_are_english(self):
        slug, found = self.shop.slug, []
        coupon = reverse('storefront_coupon_check', args=[slug])
        small, big = [{'id': self.cap.id, 'qty': 1}], [{'id': self.cap.id, 'qty': 3}]
        for label, data in (('coupon empty', {'code': '', 'cart': small}), ('coupon wrong', {'code': 'NOPE', 'cart': small}),
                            ('coupon min', {'code': 'SAVE10', 'cart': small}), ('coupon ok', {'code': 'SAVE10', 'cart': big})):
            body = self._post_json(coupon, data).json()
            self.assertEqual(body['ok'], label == 'coupon ok', (label, body))
            self._check(label, json.dumps(body, ensure_ascii=False), found)
        for label, extra in (('no name', {'name': ''}), ('bad phone', {'phone': '123'}), ('no zone', {'zone': None}),
                             ('empty cart', {'cart': []}), ('too many', {'cart': [{'id': self.cap.id, 'qty': 99}]}),
                             ('no variant', {'cart': [{'id': self.tee.id, 'qty': 1}]}), ('bad payment', {'payment': 'x'})):
            body = self._order(**extra).json()
            self.assertFalse(body['success'], label)
            self._check(f'order {label}', body['error'], found)
        review = reverse('storefront_review', args=[slug, self.cap.id])
        for label, data in (('review no name', {'name': '', 'phone': '01812345678', 'rating': 5}),
                            ('review bad phone', {'name': 'A', 'phone': '1', 'rating': 5}),
                            ('review no stars', {'name': 'A', 'phone': '01812345678', 'rating': 0}),
                            ('review ok', {'name': 'A', 'phone': '01812345679', 'rating': 5, 'text': 'Nice'})):
            response = self.client.post(review, data, follow=True)       # বার্তাটা ফিরে প্রোডাক্ট পেইজে দেখায়
            self._check(label, response.content.decode(), found)
        self.assertFalse(found, '\n' + '\n'.join(found))

    def test_every_template_text_has_english(self):
        """টেমপ্লেটে {% t "..." %} দিয়ে নতুন বাংলা লেখা যোগ হলে store/sf_en.py-তে ইংরেজিও থাকতে হবে।"""
        import unicodedata
        from pathlib import Path
        from store.sf_lang import EN_TEXT
        tag = re.compile(r"""\{%\s*(?:t|tjs)\s+(?:"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)')""")
        missing = []
        for path in sorted((Path(__file__).parent / 'templates' / 'store' / 'storefront').glob('*.html')):
            for match in tag.finditer(path.read_text(encoding='utf-8')):
                text = unicodedata.normalize('NFC', match.group(1) if match.group(1) is not None else match.group(2))
                if re.search('[\u0980-\u09FF]', text) and text not in EN_TEXT:
                    missing.append(f'{path.name}: {text}')
        self.assertFalse(missing, '\nstore/sf_en.py-তে ইংরেজি নেই:\n' + '\n'.join(missing))

    def test_customer_sms_are_english(self):
        from store import sms
        from store.models import Customer
        customer = Customer.objects.create(shop=self.shop, name='Nadia Islam', phone='01812345678', address='Dhaka')
        order = Order.objects.create(shop=self.shop, customer=customer, source='storefront', total_amount=450,
                                     delivery_charge=60, advance_paid=450)
        texts = [sms.order_received_text(self.shop, order), sms.due_reminder_text(self.shop, 'Nadia Islam', 1200)]
        texts += [sms.status_text(self.shop, order, status) for status in ('Confirmed', 'Shipped', 'Delivered')]
        if hasattr(sms, 'payment_received_text'):
            texts.append(sms.payment_received_text(self.shop, order, 450))
        for text in texts:
            self.assertFalse(self._bangla(text), text)
            self.assertEqual(sms.segments(text), 1, text)          # ইংরেজি SMS এক ভাগে (১৬০ অক্ষর)

    def test_language_switch_in_website_settings(self):
        """ওয়েবসাইট → ডিজাইনে ভাষা বদলালে: দোকানের ভাষা বদলায়, সাধারণ ডেলিভারি এলাকার নামও।"""
        from store import delivery
        from store.models import DeliveryZone
        Shop.objects.filter(pk=self.shop.pk).update(storefront_language='bn')
        self.shop.refresh_from_db()
        delivery.zones_for(self.shop)
        DeliveryZone.objects.create(shop=self.shop, name='সাভার', charge=80)
        self.client.force_login(self.shop.user)
        design = {'section': 'design', 'storefront_design': 'classic', 'storefront_theme': 'orange', 'color_mode': 'theme'}
        response = self.client.post(reverse('website_settings'), design | {'storefront_language': 'en'}, follow=True)
        self.assertContains(response, 'ওয়েবসাইট এখন ইংরেজিতে')                    # সেলারের দিক বাংলাই
        self.shop.refresh_from_db()
        self.assertEqual(self.shop.storefront_language, 'en')
        names = set(DeliveryZone.objects.filter(shop=self.shop).values_list('name', flat=True))
        self.assertEqual(names, {'Inside Dhaka', 'Outside Dhaka', 'সাভার'})      # সেলারের নিজের নাম যেমন ছিল
        self.client.post(reverse('website_settings'), design | {'storefront_language': 'bn'})
        self.shop.refresh_from_db()
        self.assertEqual(self.shop.storefront_language, 'bn')
        self.assertIn('ঢাকা সিটির ভিতরে', set(DeliveryZone.objects.filter(shop=self.shop).values_list('name', flat=True)))
        self.client.post(reverse('website_settings'), design)                    # ভাষা না পাঠালে আগেরটাই থাকে
        self.shop.refresh_from_db()
        self.assertEqual(self.shop.storefront_language, 'bn')

    def test_bangla_shop_unchanged(self):
        Shop.objects.filter(pk=self.shop.pk).update(storefront_language='bn')
        html = self.client.get(reverse('storefront_home', args=[self.shop.slug])).content.decode()
        self.assertIn('lang="bn"', html)
        self.assertIn('সব প্রোডাক্ট', html)


class HomepageSeoTests(TestCase):
    """SellPunch-এর নিজের হোমপেজ: বাংলা (/) আর ইংরেজি (/en/), hreflang, canonical, robots.txt, sitemap.xml।"""
    BN = re.compile(r'[ঀ-৲৴-৿][ঀ-৿\s]*')

    def test_english_homepage(self):
        response = self.client.get(reverse('landing_page_en'))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('<html lang="en">', html)
        self.assertIn('POS Software &amp; Online Store Builder for Bangladesh', html)
        self.assertIn('<link rel="canonical" href="http://testserver/en/">', html)
        self.assertIn('hreflang="bn" href="http://testserver/"', html)
        self.assertIn('hreflang="x-default" href="http://testserver/"', html)
        self.assertIn('<meta property="og:locale" content="en_US">', html)
        # বাংলা শুধু "বাংলা" লিংকে (বাংলা হোমপেজে ফেরার জন্য)
        visible = re.sub(r'<!--.*?-->', ' ', html, flags=re.S)
        self.assertEqual({m.group(0).strip() for m in self.BN.finditer(visible)}, {'বাংলা'})
        # যে ছবিগুলো দেখায় সব আছে (না থাকলে প্রোডাকশনে collectstatic-এর পর পাতা ভাঙবে)
        from django.contrib.staticfiles import finders
        for path in set(re.findall(r'/static/(landing/[\w.-]+)', html)):
            self.assertTrue(finders.find(path), path)

    def test_bangla_homepage_links_to_english(self):
        html = self.client.get(reverse('landing_page')).content.decode()
        self.assertIn('<link rel="canonical" href="http://testserver/">', html)
        self.assertIn('hreflang="en" href="http://testserver/en/"', html)
        self.assertIn(f'href="{reverse("landing_page_en")}"', html)
        for page in ('/', '/en/'):
            data = re.search(r'<script type="application/ld\+json">(.*?)</script>', self.client.get(page).content.decode(), re.S)
            graph = json.loads(data.group(1))['@graph']
            self.assertEqual([item['@type'] for item in graph], ['Organization', 'WebSite', 'SoftwareApplication'])

    @override_settings(STORE_BASE_DOMAIN='sellpunch.com', ALLOWED_HOSTS=['sohojsell.onrender.com', 'sellpunch.com'])
    def test_canonical_is_main_domain_even_on_render_host(self):
        html = self.client.get('/en/', HTTP_HOST='sohojsell.onrender.com').content.decode()
        self.assertIn('<link rel="canonical" href="https://sellpunch.com/en/">', html)
        self.assertIn('Sitemap: https://sellpunch.com/sitemap.xml', self.client.get('/robots.txt', HTTP_HOST='sellpunch.com').content.decode())

    @override_settings(STORE_BASE_DOMAIN='sellpunch.com', PRIMARY_HOST='sellpunch.com')
    def test_cf_subdomain_is_always_main_site(self):
        """cf.sellpunch.com = Cloudflare-এ সরাসরি ঢোকার ঠিকানা; কখনো "দোকান পাওয়া যায়নি" না।"""
        response = self.client.get('/', HTTP_HOST='cf.sellpunch.com')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'hreflang="en"')
        self.assertEqual(self.client.get('/', HTTP_HOST='nosuchshop.sellpunch.com').status_code, 404)

    def test_robots_and_sitemap(self):
        robots = self.client.get('/robots.txt')
        self.assertEqual(robots['Content-Type'], 'text/plain')
        text = robots.content.decode()
        for line in ('Allow: /', 'Allow: /accounts/signup/', 'Disallow: /demo/', 'Disallow: /dashboard/',
                     'Sitemap: http://testserver/sitemap.xml'):
            self.assertIn(line, text)
        response = self.client.get('/sitemap.xml')
        self.assertEqual(response['Content-Type'], 'application/xml')
        from xml.etree import ElementTree
        root = ElementTree.fromstring(response.content)
        ns = {'s': 'http://www.sitemaps.org/schemas/sitemap/0.9', 'x': 'http://www.w3.org/1999/xhtml'}
        locs = [el.text for el in root.findall('s:url/s:loc', ns)]
        self.assertEqual(locs[:2], ['http://testserver/', 'http://testserver/en/'])
        self.assertIn('http://testserver/privacy-policy/', locs)
        first = root.find('s:url', ns)
        self.assertEqual({link.get('hreflang') for link in first.findall('x:link', ns)}, {'bn', 'en', 'x-default'})
        for path in locs:                                      # sitemap-এর সব পাতা খোলে
            self.assertEqual(self.client.get(path.replace('http://testserver', '')).status_code, 200, path)

    def test_logged_in_seller_goes_to_dashboard(self):
        user = User.objects.create_user(phone_number='01799900001', password='Test-pass-123')
        Shop.objects.create(user=user, name='S', phone='01799900001', address='Dhaka')
        self.client.force_login(user)
        self.assertRedirects(self.client.get('/en/'), reverse('dashboard'), fetch_redirect_response=False)


class DailyCronTests(TestCase):
    """Cloudflare-এর দৈনিক cron → /internal/cron/daily/ (বাকির অটো-তাগাদা)। গোপন চাবি ছাড়া কেউ চালাতে পারে না।"""
    url = '/internal/cron/daily/'

    def test_hidden_without_secret(self):
        with override_settings(CRON_SECRET=''):
            self.assertEqual(self.client.post(self.url, HTTP_X_CRON_SECRET='').status_code, 404)
        with override_settings(CRON_SECRET='s3cret-value'):
            self.assertEqual(self.client.post(self.url).status_code, 404)
            self.assertEqual(self.client.post(self.url, HTTP_X_CRON_SECRET='wrong').status_code, 404)
            self.assertEqual(self.client.get(self.url, HTTP_X_CRON_SECRET='s3cret-value').status_code, 405)

    @override_settings(CRON_SECRET='s3cret-value')
    def test_runs_due_reminders(self):
        from unittest import mock
        with mock.patch('store.dues.run_auto_reminders', return_value={7: 3, 9: 2}) as run:
            response = self.client.post(self.url, HTTP_X_CRON_SECRET='s3cret-value')
        run.assert_called_once()
        self.assertEqual(response.json()['due_reminders'], {'shops': 2, 'sms': 5})
        self.assertEqual(response.json()['optimize_images'], 'ok')
        with mock.patch('store.dues.run_auto_reminders', side_effect=RuntimeError('gateway down')):
            response = self.client.post(self.url, HTTP_X_CRON_SECRET='s3cret-value')
        self.assertEqual(response.status_code, 200)
        self.assertIn('gateway down', response.json()['due_reminders']['error'])

    def test_robots_hides_internal(self):
        self.assertIn('Disallow: /internal/', self.client.get('/robots.txt').content.decode())


class SpeedTests(ShopTestMixin, TestCase):
    """PageSpeed ১০০-এর পাহারা: বাইরের CDN নেই, দোকানের পাতায় CSS ভেতরেই, আইকন আছে, HTML gzip, অর্ডার লিস্টে N+1 নেই।"""
    CDN = re.compile(r'(fonts\.googleapis\.com|fonts\.gstatic\.com|cdn\.jsdelivr\.net|cdnjs\.cloudflare\.com|unpkg\.com)')

    def test_no_third_party_cdn_in_templates(self):
        from pathlib import Path
        found = []
        for path in (Path(__file__).parent / 'templates').rglob('*.html'):
            for n, line in enumerate(path.read_text(encoding='utf-8').splitlines(), start=1):
                if self.CDN.search(line):
                    found.append(f'{path.name}:{n}: {line.strip()[:100]}')
        self.assertFalse(found, '\nবাইরের CDN — store/static/vendor থেকে দিন (tools/build_vendor.py):\n' + '\n'.join(found))

    def test_public_icons_are_in_the_small_icon_font(self):
        """দোকান/হোমপেজে নতুন আইকন যোগ হলে tools/build_vendor.py আবার চালাতে হবে, নাহলে ফাঁকা ঘর দেখাবে।"""
        import importlib.util
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        spec = importlib.util.spec_from_file_location('build_vendor', root / 'tools' / 'build_vendor.py')
        build_vendor = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(build_vendor)
        partial = (Path(__file__).parent / 'templates' / 'store' / 'partials' / 'icons_public.html').read_text(encoding='utf-8')
        have = set(re.findall(r'\.bi-([a-z0-9-]+)::before', partial))
        css = (Path(__file__).parent / 'static' / 'vendor' / 'bootstrap-icons' / 'bootstrap-icons.min.css').read_text()
        known = {name: 0 for name in re.findall(r'\.bi-([a-z0-9-]+)::before', css)}
        missing = sorted(set(build_vendor.public_icon_names(known)) - have)
        self.assertFalse(missing, f'icons_public.html-এ নেই: {missing} — python tools/build_vendor.py <node_modules> চালান')

    def test_storefront_has_inline_css_and_no_bootstrap_js(self):
        _user, shop = self.make_shop()
        self.client.logout()
        html = self.client.get(reverse('storefront_home', args=[shop.slug])).content.decode()
        self.assertIn('.modal-dialog', html)                         # Bootstrap-এর দরকারি অংশ পাতার ভেতরেই
        self.assertNotIn('bootstrap.min.css', html)
        self.assertNotIn('bootstrap.bundle', html)
        self.assertIn("data-bs-toggle=\"modal\"]", html)               # নিজের ছোট modal স্ক্রিপ্ট
        self.assertIn('hind-siliguri-bengali-400', html)
        self.assertNotIn('hind-siliguri-bengali-500', html)          # বাংলা ফন্টের দুটো ফাইলই

    def test_homepage_images_are_responsive(self):
        html = self.client.get('/').content.decode()
        self.assertIn('dashboard-390w', html)
        self.assertIn('sizes="(max-width: 900px) 92vw, 640px"', html)

    def test_html_is_gzipped(self):
        response = self.client.get('/', HTTP_ACCEPT_ENCODING='gzip')
        self.assertEqual(response['Content-Encoding'], 'gzip')

    def test_orders_page_has_no_query_per_order(self):
        from store.models import Customer, Order, OrderItem, Product
        _user, shop = self.make_shop()
        customer = Customer.objects.create(shop=shop, name='Rahim', phone='01712345678', address='Savar')
        product = Product.objects.create(shop=shop, name='Tee', price=500, stock_quantity=50)
        for _ in range(20):
            order = Order.objects.create(shop=shop, customer=customer, total_amount=500)
            OrderItem.objects.create(order=order, product=product, quantity=1, price=500)
        self.client.get(reverse('order_list'))
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as queries:
            self.assertEqual(self.client.get(reverse('order_list')).status_code, 200)
        self.assertLess(len(queries), 25, '\n'.join(q['sql'][:120] for q in queries.captured_queries))

    def test_far_database_region_is_flagged(self):
        from store import health
        with mock.patch.dict('django.conf.settings.DATABASES',
                             {'default': {'HOST': 'ep-x-123.us-east-2.aws.neon.tech'}}):
            self.assertEqual(health.database_region(), 'us-east-2')
            self.assertTrue(any('us-east-2' in text for text in health.warnings()))
        with mock.patch.dict('django.conf.settings.DATABASES',
                             {'default': {'HOST': 'ep-x-123-pooler.ap-southeast-1.aws.neon.tech'}}):
            self.assertFalse(any('অঞ্চলে' in text for text in health.warnings()))
