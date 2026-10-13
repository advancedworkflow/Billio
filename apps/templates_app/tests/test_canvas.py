"""Modèles en mise en page libre : nettoyage, génération HTML, éditeur (vierge, enregistrement, conversion)."""
import json

from django.test import Client as HttpClient, TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.organizations.models import Organization
from apps.templates_app import canvas
from apps.templates_app.models import InvoiceTemplate, MarketplaceTemplate
from apps.templates_app.preview import render_preview


class CanvasEngineTests(TestCase):
    def test_clean_rejects_unknown_and_clamps(self):
        layout = canvas.clean({'heights': {'header': 5000}, 'blocks': [
            {'type': 'script', 'x': 1}, {'type': 'logo', 'x': -50, 'y': 99999, 'w': 5000, 'align': 'weird'},
        ]})
        self.assertEqual(len(layout['blocks']), 1)
        logo = layout['blocks'][0]
        self.assertEqual((logo['x'], logo['align'], logo['band']), (0, 'left', 'header'))
        self.assertLessEqual(logo['w'], canvas.PAGE_WIDTH)
        self.assertLess(logo['y'], layout['heights']['header'])
        self.assertEqual(layout['heights']['header'], canvas.MAX_BAND_HEIGHT)

    def test_free_text_cannot_inject_template_code(self):
        layout = canvas.clean({'blocks': [{'type': 'text', 'text': '{{ secret }} {% debug %} <script>x</script>'}]})
        html_source, _css = canvas.build(layout)
        page = render_preview(html_source, '', {}, None)
        self.assertNotIn('<script>x', page)
        self.assertIn('&#123;&#123; secret &#125;&#125;', html_source)

    def test_gallery_templates_render(self):
        for spec in canvas.CANVAS_TEMPLATES:
            fields = canvas.template_fields(spec)
            page = render_preview(fields['html_structure'], fields['css_styles'], fields['style_config']['variables_defaults'], None, 'quote')
            self.assertIn('Atelier Lumière SARL', page, spec['slug'])
            self.assertIn('$4,248.00', page, spec['slug'])  # sans organisation : exemple en dollars
        self.assertEqual(MarketplaceTemplate.objects.filter(slug__startswith='libre-').count(), len(canvas.CANVAS_TEMPLATES))


class CanvasEditorTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='camille', email='camille@test.fr', password='x-Test-1234')
        self.org = Organization.objects.create(name='Studio', owner=self.user)
        self.http = HttpClient(HTTP_HOST='127.0.0.1')
        self.http.force_login(self.user)

    def test_blank_then_save(self):
        response = self.http.get(reverse('templates_app:template-blank'))
        template = InvoiceTemplate.objects.get(organization=self.org)
        self.assertRedirects(response, reverse('templates_app:template-canvas', args=[template.id]))
        self.assertContains(self.http.get(reverse('templates_app:template-canvas', args=[template.id])), 'canvas-editor-config')
        payload = {'name': 'Maison', 'accent': '#0f766e', 'font': 'Lora', 'texts': {'thank_you': 'Merci !'},
                   'canvas': {'heights': {'header': 300, 'footer': 200},
                              'blocks': [{'type': 'title', 'band': 'header', 'x': 400, 'y': 40, 'w': 300, 'align': 'right', 'accent': True},
                                         {'type': 'totals', 'band': 'footer', 'x': 440, 'y': 10, 'w': 300}]}}
        response = self.http.post(reverse('templates_app:template-canvas-save', args=[template.id]), json.dumps(payload), content_type='application/json')
        self.assertTrue(response.json()['ok'])
        template.refresh_from_db()
        self.assertEqual(template.name, 'Maison')
        self.assertEqual(len(template.layout_config['canvas']['blocks']), 2)
        self.assertIn('cv-b-title', template.html_structure)
        self.assertEqual(template.style_config['variables_defaults']['accent_color'], '#0f766e')
        self.assertEqual(template.style_config['font_override'], 'Lora')
        preview = self.http.get(reverse('templates_app:template-preview-frame', args=[template.id])).content.decode()
        self.assertIn('Net à payer', preview)

    def test_gallery_copy_opens_canvas_editor_and_code_templates_convert(self):
        source = MarketplaceTemplate.objects.get(slug='libre-studio')
        response = self.http.get(reverse('templates_app:template-create') + f'?from_marketplace={source.id}')
        template = InvoiceTemplate.objects.get(organization=self.org)
        self.assertIn('canvas', template.layout_config)
        self.assertRedirects(self.http.get(reverse('templates_app:template-edit', args=[template.id])),
                             reverse('templates_app:template-canvas', args=[template.id]))
        coded = InvoiceTemplate.objects.create(organization=self.org, name='Code', html_structure='<p>x</p>', css_styles='')
        self.http.post(reverse('templates_app:template-canvas-convert', args=[coded.id]))
        coded.refresh_from_db()
        self.assertIn('canvas', coded.layout_config)
        self.assertIn('cv-doc', coded.html_structure)
        self.assertEqual(response.status_code, 302)
