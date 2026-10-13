"""
Le modèle système « Formulaire de demande » dessinait ses champs avec des
rectangles : le client ne pouvait rien saisir. On le reconstruit avec de vrais
champs de formulaire et un bouton d'envoi.
"""
from django.db import migrations


def forwards(apps, schema_editor):
    from apps.documents.canvas_render import clean_canvas_data
    from apps.documents.canvas_templates import inquiry_form

    DocumentTemplate = apps.get_model('documents', 'DocumentTemplate')
    data = clean_canvas_data({'pages': inquiry_form()})
    DocumentTemplate.objects.filter(organization__isnull=True, name='Formulaire de demande').update(
        canvas_data=data,
        description='Formulaire de demande que le client remplit en ligne (2 pages) : coordonnées, projet, budget.',
    )


class Migration(migrations.Migration):

    dependencies = [
        ('documents', '0007_document_responses'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
