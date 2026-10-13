"""
Migre les Proposal existantes vers le nouveau modèle générique
apps.documents.Document (document_type='proposal') avant que le module
Proposal ne soit supprimé (voir migration suivante).
"""
from django.db import migrations


STATUS_MAP = {
    'draft': 'draft',
    'sent': 'sent',
    'viewed': 'sent',
    'accepted': 'sent',
    'rejected': 'archived',
}

BLOCK_TYPE_LABELS = {
    'intro': 'Introduction',
    'services': 'Compréhension du besoin & Périmètre',
    'conditions': 'Conditions',
    'cta': "Appel à l'action",
}


def migrate_forward(apps, schema_editor):
    Proposal = apps.get_model('invoices', 'Proposal')
    Document = apps.get_model('documents', 'Document')

    for proposal in Proposal.objects.all():
        blocks = proposal.blocks.order_by('order')
        body_parts = []
        for block in blocks:
            label = BLOCK_TYPE_LABELS.get(block.block_type, block.block_type)
            body_parts.append(f"<h3>{label}</h3>{block.content}")

        Document.objects.create(
            organization_id=proposal.organization_id,
            client_id=proposal.client_id,
            document_type='proposal',
            number=proposal.proposal_number,
            title=proposal.title,
            status=STATUS_MAP.get(proposal.status, 'draft'),
            body_html=''.join(body_parts),
            created_by_id=proposal.created_by_id,
        )


def migrate_backward(apps, schema_editor):
    Document = apps.get_model('documents', 'Document')
    Document.objects.filter(document_type='proposal').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('invoices', '0009_proposal_proposalblock_proposalitem'),
        ('documents', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(migrate_forward, migrate_backward),
    ]
