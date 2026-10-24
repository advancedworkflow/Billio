"""Pages publiques sans ressources bloquantes : Tailwind compilé, icônes en SVG, polices locales."""
from django.test import TestCase
from django.urls import reverse

from apps.landing.icons import icons, inline_icons


class LandingAssetsTests(TestCase):
    def test_home_has_no_blocking_cdn_and_inlines_icons(self):
        html = self.client.get(reverse('landing:home'), HTTP_HOST='127.0.0.1').content.decode()
        for cdn in ('cdn.tailwindcss.com', 'unpkg.com/lucide', 'fonts.googleapis.com'):
            self.assertNotIn(cdn, html)
        self.assertNotIn('data-lucide=', html)  # toutes les icônes sont dans lucide_icons.json
        self.assertIn('class="lucide lucide-arrow-right w-4 h-4"', html)
        self.assertIn('css/landing-tw.css', html)

    def test_legal_page_uses_compiled_tailwind(self):
        html = self.client.get(reverse('landing:terms'), HTTP_HOST='127.0.0.1').content.decode()
        self.assertNotIn('cdn.tailwindcss.com', html)
        self.assertIn('css/landing-tw.css', html)

    def test_unknown_icon_is_left_untouched(self):
        tag = '<i data-lucide="no-such-icon" class="w-4 h-4"></i>'
        self.assertEqual(inline_icons(tag), tag)
        self.assertIn('<path', inline_icons('<i data-lucide="check"></i>'))
        self.assertIn('check', icons())

    def test_translation_scripts_do_not_block_rendering(self):
        html = self.client.get(reverse('landing:home'), HTTP_HOST='127.0.0.1', HTTP_COOKIE='billio_lang=en').content.decode()
        self.assertRegex(html, r'<script src="/i18n/catalog/en\.js\?v=\d+" defer>')
