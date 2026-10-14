from django.test import Client as HttpClient, TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.clients.models import Client
from apps.organizations.models import Organization
from apps.templates_app.models import InvoiceTemplate


class ClientQuickCreateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='camille', email='camille@test.fr', password='x-Test-1234')
        self.org = Organization.objects.create(name='Studio', owner=self.user)
        self.http = HttpClient(HTTP_HOST='127.0.0.1')
        self.http.force_login(self.user)

    def test_address_and_legal_identity_are_saved(self):
        response = self.http.post(reverse('clients:client-quick-create'), {
            'name': 'Atelier', 'email': 'a@atelier.fr', 'address': '12 rue des Arts', 'postal_code': '75011',
            'city': 'Paris', 'country': 'France', 'company_name': 'Atelier SARL', 'registration_number': '987 654 321 00021',
            'tax_id': 'FR12987654321'})
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertEqual((data['postal_code'], data['city']), ('75011', 'Paris'))
        client = Client.objects.get(id=data['id'])
        self.assertEqual((client.address, client.country, client.tax_id), ('12 rue des Arts', 'France', 'FR12987654321'))

    def test_full_address_on_documents(self):
        client = Client(name='A', email='a@a.fr', address='12 rue des Arts', postal_code='75011', city='Paris', country='France')
        self.assertEqual(InvoiceTemplate._client_full_address(client), '12 rue des Arts\n75011 Paris\nFrance')
        legacy = Client(name='B', email='b@b.fr', address='3 place Bellecour\n69002 Lyon', postal_code='69002', city='Lyon')
        self.assertEqual(InvoiceTemplate._client_full_address(legacy), '3 place Bellecour\n69002 Lyon')
