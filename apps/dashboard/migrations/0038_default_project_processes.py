"""Chaque organisation reçoit son processus principal, avec ses étapes actuelles dans leur ordre."""
from django.db import migrations


def forwards(apps, schema_editor):
    from apps.organizations.trade_packs import main_process_name

    Organization = apps.get_model('organizations', 'Organization')
    ProjectPhase = apps.get_model('dashboard', 'ProjectPhase')
    ProjectProcess = apps.get_model('dashboard', 'ProjectProcess')
    for org in Organization.objects.all():
        if ProjectProcess.objects.filter(organization=org).exists():
            continue
        keys = list(ProjectPhase.objects.filter(organization=org).order_by('order', 'id').values_list('key', flat=True))
        if keys:
            ProjectProcess.objects.create(organization=org, name=main_process_name(getattr(org, 'trade', '')),
                                          phase_keys=keys, is_default=True)


class Migration(migrations.Migration):
    dependencies = [('dashboard', '0037_project_process'), ('organizations', '0013_default_currency_usd')]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
