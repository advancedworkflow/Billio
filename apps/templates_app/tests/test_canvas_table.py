from django.test import SimpleTestCase

from apps.templates_app import canvas, canvas_table
from apps.templates_app.preview import render_preview


class CanvasTableTests(SimpleTestCase):
    def render(self, table):
        layout = canvas.clean({'blocks': [], 'table': table})
        html_source, css = canvas.build(layout)
        return render_preview(html_source, css, {}, None)

    def test_default_table_keeps_classic_columns(self):
        page = self.render(None)
        for label in ('Désignation', 'Qté', 'Prix unitaire HT', 'TVA', 'Total HT'):
            self.assertIn(label, page)

    def test_variable_columns_and_style(self):
        page = self.render({'columns': [{'key': 'numero'}, {'key': 'designation'}, {'key': 'unite'},
                                        {'key': 'montant_tva'}, {'key': 'total_ttc', 'strong': True}],
                            'header': 'accent', 'stripes': True, 'density': 'compact'})
        self.assertIn('Montant TVA', page)
        self.assertIn('forfait', page)            # unité de la ligne d'exemple
        self.assertIn('2,880.00', page)          # 2 400 HT + 20 % (exemple en dollars)
        self.assertIn('tb-h-accent', page)
        self.assertIn('tb-zebra', page)

    def test_custom_column_mixes_text_and_variables(self):
        page = self.render({'columns': [{'key': 'designation'},
                                        {'key': 'perso', 'label': 'Calcul', 'text': '{quantite} × {prix_unitaire}'}]})
        self.assertIn('3 × $350.00', page)

    def test_custom_text_cannot_inject_template_code(self):
        table = canvas_table.clean_table({'columns': [
            {'key': 'perso', 'label': '{{ secret }}', 'text': '{% debug %} {inconnue} <b>x</b>'}]})
        source = canvas_table.build_items(table, 'cv-')
        self.assertNotIn('{% debug', source)
        self.assertNotIn('{{ secret', source)
        self.assertNotIn('<b>x', source)
        self.assertIn('&#123;inconnue&#125;', source)

    def test_unknown_columns_dropped(self):
        table = canvas_table.clean_table({'columns': [{'key': '__class__'}, {'key': 'tva', 'width': 999}]})
        self.assertEqual([c['key'] for c in table['columns']], ['tva'])
        self.assertEqual(table['columns'][0]['width'], 70)


class CanvasShapesTests(SimpleTestCase):
    def test_shapes_colors_and_block_style(self):
        layout = canvas.clean({
            'colors': {'secondary': '#fde68a', 'ink': 'red;}'},
            'blocks': [
                {'type': 'shape', 'shape': 'diagonal', 'x': 0, 'y': 0, 'w': 794, 'h': 180, 'fill': 'secondary', 'opacity': 80},
                {'type': 'shape', 'shape': 'ellipse', 'x': 600, 'y': 10, 'w': 120, 'h': 120, 'fill': '#123456'},
                {'type': 'title', 'band': 'header', 'x': 52, 'y': 40, 'w': 300, 'color': 'white', 'bg': 'accent', 'pad': 12, 'radius': 8},
                {'type': 'client', 'band': 'header', 'x': 52, 'y': 120, 'w': 300, 'color': 'url(x)'},
            ]})
        self.assertEqual(layout['colors'], {'secondary': '#fde68a', 'ink': '#1f2937'})   # couleur invalide écartée
        self.assertEqual(layout['blocks'][3]['color'], '')
        html_source, css = canvas.build(layout)
        page = render_preview(html_source, css, {'accent_color': '#0f766e'}, None)
        self.assertIn('points="0,0 794,0 794,99 0,180" fill="#fde68a" fill-opacity="0.80"', page)
        self.assertIn('<ellipse cx="60.0" cy="60.0" rx="60.0" ry="60.0" fill="#123456"', page)
        self.assertIn('class="cv-box has-color" style="color:#ffffff;background:var(--accent);padding:12px;border-radius:8px"', page)
        self.assertIn('--c2: #fde68a', page)

    def test_missing_mandatory(self):
        empty = canvas.clean({'blocks': [], 'items': False})
        self.assertIn('Tableau des lignes', canvas.missing_mandatory(empty))
        full = canvas.clean({'blocks': [{'type': key} for key in canvas.MANDATORY]})
        self.assertEqual(canvas.missing_mandatory(full), [])
        for spec in canvas.CANVAS_TEMPLATES:   # les modèles fournis sont conformes
            self.assertEqual(canvas.missing_mandatory(canvas.clean(spec['canvas'])), [], spec['slug'])
