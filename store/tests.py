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

from .models import FacebookPageConnection, OnlinePayment, Shop
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
        self.assertIn('৩০ দিনের ফ্রি ট্রায়াল', signup)
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
