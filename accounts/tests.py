from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from store.models import Shop

User = get_user_model()


def signup_data(**overrides):
    data = {'shop_name': 'Munna Fashion', 'subdomain': 'munnafashion', 'phone': '01712345678',
            'password': 'secret12', 'password2': 'secret12', 'website': ''}
    data.update(overrides)
    return data


class OnePageSignupTests(TestCase):
    def setUp(self):
        cache.clear()   # সাইনআপের রেট-লিমিট গণনা টেস্টের মধ্যে যেন না জমে

    def test_signup_creates_user_shop_and_trial_in_one_step(self):
        response = self.client.post(reverse('signup'), signup_data())
        self.assertRedirects(response, reverse('dashboard'), fetch_redirect_response=False)
        user = User.objects.get(phone_number='01712345678')
        shop = Shop.objects.get(user=user)
        self.assertEqual(shop.slug, 'munnafashion')
        self.assertEqual(shop.name, 'Munna Fashion')
        self.assertEqual(shop.subscription_plan, 'Free')
        self.assertGreater(shop.trial_ends_at, timezone.now() + timedelta(days=29))
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 200)

    def test_bengali_shop_name_with_own_subdomain(self):
        self.client.post(reverse('signup'), signup_data(shop_name='রহিম ফ্যাশন হাউস', subdomain='Rahim-Fashion'))
        self.assertEqual(Shop.objects.get().slug, 'rahim-fashion')

    def test_phone_formats_are_normalized(self):
        self.client.post(reverse('signup'), signup_data(phone='+880 1712-345678'))
        self.assertTrue(User.objects.filter(phone_number='01712345678').exists())

    def test_invalid_and_reserved_and_taken_subdomains_rejected(self):
        for bad in ['ab', '-shop', 'shop-', 'my shop', 'admin', 'www', 'দোকান']:
            response = self.client.post(reverse('signup'), signup_data(subdomain=bad))
            self.assertEqual(response.status_code, 200, bad)
            self.assertTrue(response.context['form'].errors.get('subdomain'), bad)
        self.client.post(reverse('signup'), signup_data())
        self.client.logout()
        response = self.client.post(reverse('signup'), signup_data(phone='01812345678'))
        self.assertIn('munnafashion2', response.context['form'].errors['subdomain'][0])
        self.assertEqual(Shop.objects.count(), 1)

    def test_duplicate_phone_and_password_mismatch(self):
        User.objects.create_user(phone_number='01712345678', password='x123456')
        response = self.client.post(reverse('signup'), signup_data())
        self.assertIn('phone', response.context['form'].errors)
        response = self.client.post(reverse('signup'), signup_data(phone='01912345678', password2='other123'))
        self.assertIn('password2', response.context['form'].errors)
        self.assertFalse(Shop.objects.exists())

    def test_honeypot_blocks_bots(self):
        self.client.post(reverse('signup'), signup_data(website='http://spam'))
        self.assertFalse(User.objects.exists())

    def test_check_subdomain_endpoint(self):
        Shop.objects.create(user=User.objects.create_user(phone_number='01700000001', password='x123456'),
                            name='Taken', slug='taken')
        ok = self.client.get(reverse('check_subdomain'), {'s': 'freshname'}).json()
        self.assertTrue(ok['ok'])
        taken = self.client.get(reverse('check_subdomain'), {'s': 'taken'}).json()
        self.assertFalse(taken['ok'])
        self.assertEqual(taken['suggestion'], 'taken2')


class LoginTests(TestCase):
    def test_phone_login_accepts_country_code(self):
        User.objects.create_user(phone_number='01798765432', password='Strong-pass-1')
        response = self.client.post(reverse('login'), {'username': '+8801798765432', 'password': 'Strong-pass-1'})
        self.assertEqual(response.status_code, 302)
        self.assertIn('_auth_user_id', self.client.session)
