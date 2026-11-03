from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

User = get_user_model()


class SignupLoginTests(TestCase):
    def test_phone_signup_logs_in_and_goes_to_shop_setup(self):
        # আগে দুটো auth backend থাকায় এখানে 500 error হতো
        response = self.client.post(reverse('signup'), {
            'phone': '01712345678', 'password': 'Strong-pass-1', 'confirm_password': 'Strong-pass-1',
        })
        self.assertRedirects(response, reverse('setup_shop'), fetch_redirect_response=False)
        self.assertTrue(User.objects.filter(phone_number='01712345678').exists())
        self.assertEqual(self.client.get(reverse('setup_shop')).status_code, 200)

    def test_phone_login(self):
        User.objects.create_user(phone_number='01798765432', password='Strong-pass-1')
        response = self.client.post(reverse('login'), {'username': '01798765432', 'password': 'Strong-pass-1'})
        self.assertEqual(response.status_code, 302)
        self.assertIn('_auth_user_id', self.client.session)
