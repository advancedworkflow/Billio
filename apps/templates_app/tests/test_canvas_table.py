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
            'colors': {'secondary': '#fde68a', 'ink': 'red;}', 'page': '#fbf1dc'},
            'blocks': [
                {'type': 'shape', 'shape': 'diagonal', 'x': 0, 'y': 0, 'w': 794, 'h': 180, 'fill': 'secondary', 'opacity': 80},
                {'type': 'shape', 'shape': 'ellipse', 'x': 600, 'y': 10, 'w': 120, 'h': 120, 'fill': '#123456'},
                {'type': 'shape', 'shape': 'wave', 'band': 'page', 'anchor': 'bottom', 'x': 0, 'y': 0, 'w': 794, 'h': 90,
                 'gradient': True, 'fill': 'accent', 'fill2': 'secondary', 'flip_y': True},
                {'type': 'title', 'band': 'header', 'x': 52, 'y': 40, 'w': 300, 'color': 'white', 'bg': 'accent', 'pad': 12,
                 'radius': 8, 'font': 'Oswald', 'upper': True, 'tracking': 10, 'size': 'xxl'},
                {'type': 'client', 'band': 'header', 'x': 52, 'y': 120, 'w': 300, 'color': 'url(x)', 'font': 'Comic'},
                {'type': 'title', 'band': 'page'},   # un bloc de contenu ne peut pas aller sur le plan « page »
            ]})
        self.assertEqual(layout['colors'], {'secondary': '#fde68a', 'ink': '#1f2937', 'page': '#fbf1dc'})
        client = layout['blocks'][4]
        self.assertEqual((client['color'], client['font']), ('', ''))
        self.assertEqual(layout['blocks'][5]['band'], 'header')
        html_source, css = canvas.build(layout)
        page = render_preview(html_source, css, {'accent_color': '#0f766e'}, None)
        self.assertIn('d="M0,0 H100 V55 L0,100 Z" fill="#fde68a" fill-opacity="0.80"', page)
        self.assertIn('<ellipse cx="60.0" cy="60.0" rx="60.0" ry="60.0" fill="#123456"', page)
        self.assertIn('top:1032px', page)                                  # décor accroché en bas : 1122 - 0 - 90
        self.assertIn('<stop offset="0" stop-color="#0f766e"/>', page)     # dégradé accent → secondaire
        self.assertIn('scale(1,-1)', page)                                 # retournement vertical
        self.assertIn("font-family:'Oswald'", page)
        self.assertIn('class="cv-box has-color upper"', page)
        self.assertIn('family=Oswald', css)
        self.assertIn('@page { background: #fbf1dc; }', css)

    def test_text_variables(self):
        layout = canvas.clean({'blocks': [{'type': 'text', 'text': 'Facture {numero} pour {client} — {inconnue} {{ x }}'}]})
        html_source, css = canvas.build(layout)
        self.assertIn('{{ invoice_number }}', html_source)
        self.assertNotIn('{{ x }}', html_source)
        page = render_preview(html_source, css, {}, None)
        self.assertIn('Atelier Lumière SARL', page)
        self.assertIn('&#123;inconnue&#125;', page)

    def test_images_are_embedded_only_when_resolved(self):
        layout = canvas.clean({'blocks': [
            {'type': 'image', 'asset': 7, 'x': 52, 'y': 20, 'w': 200, 'h': 80, 'radius': 6},
            {'type': 'image', 'asset': 8, 'band': 'page', 'x': 0, 'y': 0, 'w': 794, 'h': 200, 'opacity': 30},
        ]})
        self.assertTrue(layout['blocks'][1]['behind'])
        html_source, _css = canvas.build(layout, {7: 'data:image/png;base64,AAAA'})
        self.assertIn('src="data:image/png;base64,AAAA"', html_source)
        self.assertEqual(html_source.count('<img class="cv-img"'), 1)   # l'image 8 n'appartient pas à l'organisation

    def test_missing_mandatory(self):
        empty = canvas.clean({'blocks': [], 'items': False})
        self.assertIn('Tableau des lignes', canvas.missing_mandatory(empty))
        full = canvas.clean({'blocks': [{'type': key} for key in canvas.MANDATORY]})
        self.assertEqual(canvas.missing_mandatory(full), [])

    def test_gallery_templates_are_compliant_and_render(self):
        for spec in canvas.CANVAS_TEMPLATES:
            self.assertEqual(canvas.missing_mandatory(spec['canvas']), [], spec['slug'])
            html_source, css = canvas.build(spec['canvas'])
            page = render_preview(html_source, css, {'accent_color': spec['accent']}, None)
            self.assertIn('Atelier Lumière SARL', page, spec['slug'])
            self.assertIn('Création du site vitrine', page, spec['slug'])


class SvgSanitizeTests(SimpleTestCase):
    def test_strips_scripts_links_and_handlers(self):
        from apps.templates_app.canvas_assets import AssetError, sanitize_svg
        dirty = (b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 10 10" onload="alert(1)">'
                 b'<script>alert(1)</script><a xlink:href="javascript:alert(1)"><rect width="5" height="5"/></a>'
                 b'<circle r="3" fill="url(http://evil/x)" style="x"/><path d="M0 0L10 10" fill="url(#g)"/>'
                 b'<foreignObject><div>x</div></foreignObject></svg>')
        clean = sanitize_svg(dirty).decode()
        for bad in ('script', 'onload', 'javascript', 'foreignObject', 'evil', 'style', '<a'):
            self.assertNotIn(bad, clean)
        self.assertIn('fill="url(#g)"', clean)
        with self.assertRaises(AssetError):
            sanitize_svg(b'<!DOCTYPE svg [<!ENTITY a "x">]><svg/>')


class TableAdvancedFormattingTests(SimpleTestCase):
    def test_column_and_table_formatting(self):
        layout = canvas.clean({'blocks': [], 'table': {
            'columns': [{'key': 'designation', 'color': 'accent', 'bg': 'secondary', 'italic': True},
                        {'key': 'total_ht', 'color': 'url(x)', 'bg': '#ff0000'}],
            'outer': 'box', 'line_style': 'dashed', 'valign': 'middle', 'head_size': 'l', 'body_color': 'muted', 'pad_x': 18}})
        cols = layout['table']['columns']
        self.assertEqual((cols[1]['color'], cols[1]['bg']), ('', '#ff0000'))
        html_source, css = canvas.build(layout)
        page = render_preview(html_source, css, {}, None)
        self.assertIn('style="color:var(--accent);background:var(--c2);font-style:italic"', page)
        for flag in ('tb-box', 'tb-ls-dashed', 'tb-mid', 'tb-hs-l', 'tb-tc', 'tb-px'):
            self.assertIn(flag, page)
        self.assertIn('--px:18px', page)
