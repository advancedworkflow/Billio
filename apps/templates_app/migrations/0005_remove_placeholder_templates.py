"""
Supprime les modèles vides créés automatiquement (« Invoice / Default template ») :
les factures et devis qui les utilisaient passent sur un vrai modèle de l'organisation
(ou une copie du modèle pro « Essentiel »), qui devient le modèle par défaut si besoin.
"""
from django.db import migrations

PLACEHOLDER = '<div class="invoice"><h1>Invoice</h1><p>Default template</p></div>'


def _is_placeholder(t):
    html = (t.html_structure or '').strip()
    return not html or html == PLACEHOLDER or 'Default template</p>' in html


def forwards(apps, schema_editor):
    InvoiceTemplate = apps.get_model('templates_app', 'InvoiceTemplate')
    MarketplaceTemplate = apps.get_model('templates_app', 'MarketplaceTemplate')
    Invoice = apps.get_model('invoices', 'Invoice')
    Quote = apps.get_model('invoices', 'Quote')
    pro = MarketplaceTemplate.objects.filter(slug='pro-essentiel').first()

    placeholders = [t for t in InvoiceTemplate.objects.all() if _is_placeholder(t)]
    for org_id in {t.organization_id for t in placeholders if t.organization_id}:
        org_placeholders = [t for t in placeholders if t.organization_id == org_id]
        real = [t for t in InvoiceTemplate.objects.filter(organization_id=org_id, is_active=True).order_by('-is_default', 'name') if not _is_placeholder(t)]
        target = real[0] if real else None
        if target is None and pro is not None:
            target = InvoiceTemplate.objects.create(
                organization_id=org_id, name=(pro.title or 'Essentiel')[:100],
                html_structure=pro.html_structure or '', css_styles=pro.css_styles or '',
                layout_config=pro.layout_config or {}, style_config=pro.style_config or {},
                is_active=True, is_default=False,
            )
        if target is None:
            continue  # rien pour remplacer : on garde le modèle vide
        ids = [t.id for t in org_placeholders]
        Invoice.objects.filter(template_id__in=ids).update(template_id=target.id)
        Quote.objects.filter(template_id__in=ids).update(template_id=target.id)
        if any(t.is_default for t in org_placeholders) or not InvoiceTemplate.objects.filter(organization_id=org_id, is_default=True).exclude(id__in=ids).exists():
            InvoiceTemplate.objects.filter(organization_id=org_id).update(is_default=False)
            InvoiceTemplate.objects.filter(id=target.id).update(is_default=True)
        InvoiceTemplate.objects.filter(id__in=ids).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('templates_app', '0004_pro_invoice_templates'),
        ('invoices', '0012_invoice_last_reminder_at'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
