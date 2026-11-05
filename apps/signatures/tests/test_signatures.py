"""Signature électronique : brouillon, envoi, signature, document final avec certificat."""
import base64
import io
import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import Client as HttpClient, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from apps.organizations.models import Organization
from apps.signatures import services
from apps.signatures.models import SignatureRequest
from apps.subscriptions.testing import give_plan


def make_pdf(pages=2, size=(595, 842), rotate=0):
    from pypdf import PdfWriter
    writer = PdfWriter()
    for _ in range(pages):
        page = writer.add_blank_page(*size)
        if rotate:
            page.rotate(rotate)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def signature_png():
    image = Image.new('RGBA', (120, 40), (0, 0, 0, 0))
    for x in range(10, 110):
        image.putpixel((x, 20), (0, 0, 0, 255))
    out = io.BytesIO()
    image.save(out, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(out.getvalue()).decode()


def fake_build(request):
    return b'%PDF-1.7 signed ' + str(request.pk).encode()


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', SITE_URL='https://billio.test')
class SignatureFlowTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='o', email='o@test.fr', password='x-Test-1234')
        self.org = Organization.objects.create(name='Atelier Lumen', owner=self.user)
        give_plan(self.user, 'pro')
        self.http = HttpClient(HTTP_HOST='127.0.0.1')
        self.http.force_login(self.user)
        self.client.cookies['billio_lang'] = 'fr'
        self.mail = mock.patch('apps.signatures.services._org_mail', return_value=(None, 'noreply@billio.test'))
        self.mail.start()
        self.addCleanup(self.mail.stop)

    def _upload(self, data=None, title='Contrat de prestation'):
        from django.core.files.uploadedfile import SimpleUploadedFile
        pdf = SimpleUploadedFile('contrat.pdf', data or make_pdf(), content_type='application/pdf')
        return self.http.post(reverse('signatures:new'), {'source': 'upload', 'title': title, 'pdf': pdf})

    def _draft(self, signers=(('Julie Martin', 'julie@client.fr'),), in_order=False):
        self._upload()
        req = SignatureRequest.objects.get()
        payload = {
            'title': req.title, 'in_order': in_order,
            'signers': [{'key': str(i), 'name': n, 'email': e} for i, (n, e) in enumerate(signers)],
            'fields': [],
        }
        for i, _ in enumerate(signers):
            payload['fields'] += [
                {'signer': str(i), 'kind': 'signature', 'page': 1, 'x': 0.1, 'y': 0.8, 'w': 0.3, 'h': 0.06},
                {'signer': str(i), 'kind': 'date', 'page': 1, 'x': 0.5, 'y': 0.8, 'w': 0.2, 'h': 0.03},
                {'signer': str(i), 'kind': 'checkbox', 'page': 0, 'x': 0.1, 'y': 0.1, 'w': 0.03, 'h': 0.02, 'required': False},
            ]
        return req, payload

    def _save(self, req, payload):
        return self.http.post(reverse('signatures:save', args=[req.pk]), json.dumps(payload), content_type='application/json')

    def _sign(self, signer):
        values = {str(f.pk): signature_png() for f in signer.fields.filter(kind='signature')}
        return self.client.post(reverse('signatures:sign-submit', args=[signer.token]),
                                json.dumps({'consent': True, 'values': values}), content_type='application/json')

    def test_upload_reads_pages(self):
        response = self._upload(make_pdf(3, size=(842, 595)))
        req = SignatureRequest.objects.get()
        self.assertRedirects(response, reverse('signatures:detail', args=[req.pk]), fetch_redirect_response=False)
        self.assertEqual(req.pages, [[842, 595]] * 3)
        self.assertEqual(len(req.original_sha256), 64)
        page = self.http.get(reverse('signatures:detail', args=[req.pk])).content.decode()
        self.assertIn('Envoyer pour signature', page)

    def test_rotated_page_size_is_as_displayed(self):
        self.assertEqual(services.read_pdf(make_pdf(1, rotate=90)), [[842, 595]])

    def test_rejects_non_pdf(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.http.post(reverse('signatures:new'), {'source': 'upload', 'pdf': SimpleUploadedFile('x.pdf', b'hello')})
        self.assertFalse(SignatureRequest.objects.exists())

    def test_free_plan_cannot_create(self):
        give_plan(self.user, 'free')
        self._upload()
        self.assertFalse(SignatureRequest.objects.exists())

    def test_send_requires_a_signature_field(self):
        req, payload = self._draft()
        payload['fields'] = [f for f in payload['fields'] if f['kind'] != 'signature']
        payload['send'] = True
        response = self._save(req, payload)
        self.assertEqual(response.status_code, 400)
        self.assertIn('Signature', response.json()['error'])
        self.assertEqual(SignatureRequest.objects.get().status, 'draft')

    @mock.patch('apps.signatures.services.build_signed_pdf', side_effect=fake_build)
    def test_full_flow_two_signers_in_order(self, _build):
        req, payload = self._draft(signers=(('Julie Martin', 'julie@client.fr'), ('Paul Roy', 'paul@client.fr')), in_order=True)
        payload['send'] = True
        response = self._save(req, payload)
        self.assertTrue(response.json()['ok'])
        req.refresh_from_db()
        self.assertEqual(req.status, 'sent')
        first, second = req.signers.all()
        self.assertEqual((first.status, second.status), ('invited', 'waiting'))
        self.assertEqual([m.to for m in mail.outbox], [['julie@client.fr']])
        self.assertIn(f'/signatures/s/{first.token}/', mail.outbox[0].body)

        page = self.client.get(reverse('signatures:sign', args=[second.token])).content.decode()
        self.assertIn('pas encore à vous', page)
        page = self.client.get(reverse('signatures:sign', args=[first.token])).content.decode()
        self.assertIn('Signer le document', page)
        first.refresh_from_db()
        self.assertEqual(first.status, 'viewed')

        refused = self.client.post(reverse('signatures:sign-submit', args=[first.token]),
                                   json.dumps({'consent': True, 'values': {}}), content_type='application/json')
        self.assertIn('Remplissez', refused.json()['error'])

        self.assertTrue(self._sign(first).json()['ok'])
        second.refresh_from_db()
        self.assertEqual(second.status, 'invited')
        self.assertEqual(mail.outbox[-1].to, ['paul@client.fr'])
        self.assertEqual(first.fields.get(kind='date').value[2], '/')

        self.assertTrue(self._sign(second).json()['ok'])
        req.refresh_from_db()
        self.assertEqual(req.status, 'completed')
        self.assertTrue(req.signed_pdf)
        self.assertEqual(req.signed_sha256, services.sha256(fake_build(req)))
        recipients = sorted(m.to[0] for m in mail.outbox if m.attachments)
        self.assertEqual(recipients, ['julie@client.fr', 'o@test.fr', 'paul@client.fr'])
        download = self.client.get(reverse('signatures:sign-download', args=[first.token]))
        self.assertEqual(b''.join(download.streaming_content), fake_build(req))

        from django.core.files.uploadedfile import SimpleUploadedFile
        verified = self.client.post(reverse('signatures:verify'), {'pdf': SimpleUploadedFile('s.pdf', fake_build(req))})
        self.assertContains(verified, 'Document authentique')
        self.assertEqual(self.user.notifications.filter(notification_type='signature_completed').count(), 1)

    def test_decline_closes_request(self):
        req, payload = self._draft()
        payload['send'] = True
        self._save(req, payload)
        signer = req.signers.get()
        response = self.client.post(reverse('signatures:sign-decline', args=[signer.token]),
                                    json.dumps({'reason': 'Tarif à revoir'}), content_type='application/json')
        self.assertTrue(response.json()['ok'])
        req.refresh_from_db()
        self.assertEqual(req.status, 'declined')
        self.assertEqual(self._sign(signer).status_code, 400)

    def test_cancelled_link_no_longer_serves_pdf(self):
        req, payload = self._draft()
        payload['send'] = True
        self._save(req, payload)
        self.http.post(reverse('signatures:cancel', args=[req.pk]))
        signer = req.signers.get()
        self.assertEqual(self.client.get(reverse('signatures:sign-pdf', args=[signer.token])).status_code, 404)
        self.assertContains(self.client.get(reverse('signatures:sign', args=[signer.token])), 'annulée')

    def test_other_organization_cannot_open(self):
        req, _ = self._draft()
        other = get_user_model().objects.create_user(username='x', email='x@test.fr', password='x-Test-1234')
        Organization.objects.create(name='Autre', owner=other)
        http = HttpClient(HTTP_HOST='127.0.0.1')
        http.force_login(other)
        self.assertEqual(http.get(reverse('signatures:detail', args=[req.pk])).status_code, 404)
        self.assertEqual(http.get(reverse('signatures:pdf', args=[req.pk])).status_code, 404)

    def test_rejects_empty_signature_image(self):
        blank = Image.new('RGBA', (50, 20), (0, 0, 0, 0))
        out = io.BytesIO()
        blank.save(out, format='PNG')
        with self.assertRaises(services.SignatureError):
            services.clean_image('data:image/png;base64,' + base64.b64encode(out.getvalue()).decode())


class SignedPdfTests(TestCase):
    """Rendu réel (WeasyPrint + pypdf) : valeurs apposées et certificat ajouté."""

    def test_signed_pdf_has_overlay_and_certificate(self):
        from pypdf import PdfReader
        from django.utils import timezone

        user = get_user_model().objects.create_user(username='o', email='o@test.fr', password='x-Test-1234')
        org = Organization.objects.create(name='Atelier Lumen', owner=user)
        req = services.create_request(org, user, title='Contrat', data=make_pdf(2))
        signer = req.signers.create(name='Julie Martin', email='julie@client.fr', status='signed',
                                    signed_at=timezone.now(), ip_address='203.0.113.7')
        req.fields.create(signer=signer, kind='signature', page=1, x=.1, y=.8, w=.3, h=.06, value=signature_png())
        req.fields.create(signer=signer, kind='text', page=0, x=.1, y=.1, w=.3, h=.03, value='Lu et approuvé')
        req.status, req.sent_at, req.completed_at = 'completed', timezone.now(), timezone.now()
        req.save()
        data = services.build_signed_pdf(req)
        reader = PdfReader(io.BytesIO(data))
        self.assertGreaterEqual(len(reader.pages), 3)
        self.assertIn('Lu et approuvé', reader.pages[0].extract_text())
        self.assertTrue(list(reader.pages[1].images), "l'image de la signature doit être apposée sur la page")
        certificate = ''.join(page.extract_text() for page in reader.pages[2:])
        self.assertIn('Certificat de signature', certificate)
        self.assertIn('203.0.113.7', certificate)
        self.assertIn(req.original_sha256, certificate.replace('\n', ''))
