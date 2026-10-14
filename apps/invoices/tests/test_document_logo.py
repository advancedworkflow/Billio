import io
import shutil
import tempfile

from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from PIL import Image

from apps.accounts.models import User
from apps.clients.models import Client
from apps.invoices.models import Invoice
from apps.invoices.views import apply_document_logo
from apps.organizations.models import Organization
from apps.templates_app.models import InvoiceTemplate, TemplateAsset

MEDIA = tempfile.mkdtemp(prefix='billio-test-logo-')


@override_settings(MEDIA_ROOT=MEDIA)
class DocumentLogoTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        self.user = User.objects.create_user(username='c', email='c@test.fr', password='x-Test-1234')
        self.org = Organization.objects.create(name='Studio', owner=self.user)
        self.client_obj = Client.objects.create(organization=self.org, name='A', email='a@a.fr')
        buffer = io.BytesIO()
        Image.new('RGB', (10, 10), 'red').save(buffer, 'PNG')
        self.asset = TemplateAsset(organization=self.org, name='Autre logo', mime='image/png', width=10, height=10)
        self.asset.file.save('logo.png', ContentFile(buffer.getvalue()), save=True)

    def test_document_logo_overrides_company_logo_only_for_that_document(self):
        invoice = Invoice(organization=self.org, client=self.client_obj)
        self.assertEqual(InvoiceTemplate._document_logo_uri(invoice, self.org), '')   # pas de logo d'entreprise
        apply_document_logo(invoice, self.org, str(self.asset.id))
        self.assertEqual(invoice.logo_asset_id, self.asset.id)
        self.assertTrue(InvoiceTemplate._document_logo_uri(invoice, self.org).startswith('data:image/png;base64,'))
        self.org.refresh_from_db()
        self.assertFalse(self.org.logo)   # le logo de l'entreprise n'a pas changé
        apply_document_logo(invoice, self.org, '')
        self.assertIsNone(invoice.logo_asset)

    def test_foreign_asset_is_ignored(self):
        other = Organization.objects.create(name='Autre', owner=User.objects.create_user(username='o', email='o@test.fr', password='x-Test-1234'))
        invoice = Invoice(organization=other, client=self.client_obj)
        apply_document_logo(invoice, other, str(self.asset.id))
        self.assertIsNone(invoice.logo_asset)
