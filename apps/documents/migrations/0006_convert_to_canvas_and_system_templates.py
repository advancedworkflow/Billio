"""
L'éditeur « texte continu » est retiré : tous les documents et modèles passent en
mode canvas, et les modèles système Bienvenue / Contrat / Proposition sont remplacés
par des versions canvas multi-pages (mêmes lignes en base, pour ne pas casser les
automatisations « Créer un document » qui les référencent). Le modèle « Formulaire
de demande » est ajouté.

Non réversible : le contenu canvas ne se reconvertit pas en sections HTML.
"""
from django.db import migrations


def forwards(apps, schema_editor):
    from apps.documents.canvas_render import clean_canvas_data, flow_to_canvas
    from apps.documents.canvas_templates import build_system_templates

    Document = apps.get_model('documents', 'Document')
    DocumentTemplate = apps.get_model('documents', 'DocumentTemplate')

    def convert(obj):
        style = obj.style_config or {}
        obj.canvas_data = flow_to_canvas(
            obj.header_html, obj.body_html, obj.footer_html, style,
            page_format=style.get('page_format') or 'A4',
            orientation=style.get('page_orientation') or 'portrait',
        )
        obj.layout_mode = 'canvas'
        obj.save(update_fields=['canvas_data', 'layout_mode'])

    for document in Document.objects.exclude(layout_mode='canvas'):
        convert(document)

    for spec in build_system_templates():
        data = clean_canvas_data({'pages': spec['pages']})
        template = None
        if spec['replaces']:
            template = DocumentTemplate.objects.filter(organization__isnull=True, name=spec['replaces']).first()
        if template is None:
            template = DocumentTemplate.objects.filter(organization__isnull=True, name=spec['name']).first()
        if template is None:
            template = DocumentTemplate(organization=None)
        template.name = spec['name']
        template.category = spec['category']
        template.description = spec['description']
        template.layout_mode = 'canvas'
        template.canvas_data = data
        template.style_config = {'page_format': 'A4', 'page_orientation': 'portrait'}
        template.save()

    for template in DocumentTemplate.objects.exclude(layout_mode='canvas'):
        convert(template)


class Migration(migrations.Migration):

    dependencies = [
        ('documents', '0005_canvas_only'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
