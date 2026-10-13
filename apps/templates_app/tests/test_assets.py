import io
import json
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client as HttpClient, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from apps.accounts.models import User
from apps.organizations.models import Organization
from apps.templates_app.models import InvoiceTemplate, TemplateAsset

MEDIA = tempfile.mkdtemp(prefix='billio-test-media-')


def png_bytes(size=(40, 20)):
    buffer = io.BytesIO()
    Image.new('RGBA', size, (255, 0, 0, 128)).save(buffer, 'PNG')
    return buffer.getvalue()


@override_settings(MEDIA_ROOT=MEDIA)
class TemplateAssetTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        self.user = User.objects.create_user(username='camille', email='camille@test.fr', password='x-Test-1234')
        self.org = Organization.objects.create(name='Studio', owner=self.user)
        self.http = HttpClient(HTTP_HOST='127.0.0.1')
        self.http.force_login(self.user)

    def upload(self, name, content, mime):
        return self.http.post(reverse('templates_app:template-asset-upload'), {'file': SimpleUploadedFile(name, content, content_type=mime)})

    def test_upload_png_and_embed_on_save(self):
        response = self.upload('tampon.png', png_bytes(), 'image/png')
        asset = response.json()['asset']
        self.assertEqual((asset['w'], asset['h']), (40, 20))
        self.http.get(reverse('templates_app:template-blank'))
        template = InvoiceTemplate.objects.get(organization=self.org)
        other_org = Organization.objects.create(name='Autre', owner=User.objects.create_user(username='x', email='x@test.fr', password='x-Test-1234'))
        foreign = TemplateAsset.objects.create(organization=other_org, name='x', mime='image/png', file='template_assets/x.png')
        payload = {'name': 'Avec image', 'accent': '#111827', 'texts': {}, 'canvas': {'blocks': [
            {'type': 'image', 'asset': asset['id'], 'x': 52, 'y': 20, 'w': 120, 'h': 60},
            {'type': 'image', 'asset': foreign.id, 'x': 300, 'y': 20, 'w': 120, 'h': 60},
        ]}}
        response = self.http.post(reverse('templates_app:template-canvas-save', args=[template.id]), json.dumps(payload), content_type='application/json')
        self.assertTrue(response.json()['ok'])
        template.refresh_from_db()
        self.assertEqual(template.html_structure.count('src="data:image/png;base64,'), 1)   # l'image d'une autre organisation n'est pas incluse

    def test_svg_is_sanitized_and_bad_files_refused(self):
        svg = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50" onload="alert(1)"><script>x</script><rect width="10" height="10"/></svg>'
        asset = self.upload('motif.svg', svg, 'image/svg+xml').json()['asset']
        stored = TemplateAsset.objects.get(id=asset['id'])
        content = stored.file.read()
        self.assertNotIn(b'script', content)
        self.assertNotIn(b'onload', content)
        self.assertEqual((asset['w'], asset['h']), (100, 50))
        response = self.upload('faux.png', b'not an image', 'image/png')
        self.assertEqual(response.status_code, 400)

    def test_delete_only_own_assets(self):
        asset = self.upload('a.png', png_bytes(), 'image/png').json()['asset']
        other = User.objects.create_user(username='y', email='y@test.fr', password='x-Test-1234')
        Organization.objects.create(name='Y', owner=other)
        intruder = HttpClient(HTTP_HOST='127.0.0.1')
        intruder.force_login(other)
        self.assertEqual(intruder.post(reverse('templates_app:template-asset-delete', args=[asset['id']])).status_code, 404)
        self.assertTrue(self.http.post(reverse('templates_app:template-asset-delete', args=[asset['id']])).json()['ok'])
        self.assertFalse(TemplateAsset.objects.filter(id=asset['id']).exists())
