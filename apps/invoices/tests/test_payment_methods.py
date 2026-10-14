from django.contrib.auth import get_user_model
from django.test import Client as HttpClient, TestCase
from django.urls import reverse

from apps.organizations.models import Organization, OrganizationMember
from apps.payments.models import PaymentMethod


class PaymentMethodFieldsTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(username='pm', email='pm@test.fr', password='x-Test-1234')
        self.org = Organization.objects.create(name='Studio', owner=user)
        OrganizationMember.objects.get_or_create(organization=self.org, user=user, defaults={'role': 'owner'})
        self.http = HttpClient(HTTP_HOST='127.0.0.1')
        self.http.force_login(user)

    def create(self, **data):
        return self.http.post(reverse('payments:payment-method-quick-create'), dict({'name': 'M'}, **data))

    def test_bank_transfer_requires_valid_iban(self):
        bad = self.create(method_type='bank_transfer', account_holder='Studio', iban='FR76 1234')
        self.assertEqual(bad.status_code, 400)
        ok = self.create(method_type='bank_transfer', account_holder='Studio', iban='fr76 3000 6000 0112 3456 7890 189', bic='bnpafrpp')
        self.assertEqual(ok.status_code, 200)
        method = PaymentMethod.objects.get(id=ok.json()['id'])
        self.assertEqual((method.iban, method.bic), ('FR7630006000011234567890189', 'BNPAFRPP'))

    def test_irrelevant_fields_dropped_and_paypal_checked(self):
        cash = self.create(method_type='cash', iban='FR7630006000011234567890189', account_holder='X')
        method = PaymentMethod.objects.get(id=cash.json()['id'])
        self.assertIsNone(method.iban)
        self.assertIsNone(method.account_holder)
        self.assertEqual(self.create(method_type='paypal', account_holder='pas un email').status_code, 400)
        self.assertEqual(self.create(method_type='paypal', account_holder='paypal.me/studio').status_code, 200)
        self.assertEqual(self.create(method_type='check', account_holder='').status_code, 400)
