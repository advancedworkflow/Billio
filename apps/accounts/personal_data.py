"""
Données d'un compte, pour le RGPD : export (droits d'accès et de portabilité, art. 15 et 20)
et effacement à la fermeture du compte (art. 17, apps/accounts/closure.py).

Les données à prendre sont trouvées en suivant les clés étrangères en CASCADE : tout ce qui
disparaîtrait avec une organisation (clients, factures, lignes, paiements, projets…) ou avec
le compte (profil, abonnement, notifications, tickets…). Un nouveau modèle relié de la même
façon est donc exporté et effacé sans rien déclarer ici.

L'archive ZIP contient un JSON et un CSV par type de données, plus les fichiers déposés
(PDF, pièces jointes, logos). Secrets et liens d'accès (mots de passe, clés d'API, jetons
de portail) en sont exclus : ils donneraient accès au compte à qui récupère l'archive.
"""
import csv
import io
import json
import re
import tempfile
import zipfile

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core import serializers
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.organizations.models import Organization

SECRET_FIELD = re.compile(r'(password|secret|api_key|token|totp_|credential)', re.I)
EXCLUDED_FIELDS = {
    'integrations.ConnectionInstance': {'config'},  # clés d'API et jetons OAuth des outils connectés
}
MAX_FILES_BYTES = 500 * 1024 * 1024


def _local_models():
    return [m for m in apps.get_models() if m.__module__.startswith('apps.')]


def _cascade_paths(target, stop=()):
    """{modèle: chemin de lookup vers `target`} en ne suivant que des clés étrangères en CASCADE."""
    paths = {target: ''}
    changed = True
    while changed:
        changed = False
        for model in _local_models():
            if model in paths or model in stop:
                continue
            for field in model._meta.concrete_fields:
                if (field.is_relation and field.related_model in paths
                        and field.remote_field.on_delete is models.CASCADE):
                    parent = paths[field.related_model]
                    paths[model] = f'{field.name}__{parent}' if parent else field.name
                    changed = True
                    break
    del paths[target]
    return paths


def owned_querysets(user, organizations):
    """[(modèle, queryset)] des données du compte et des organisations données."""
    user_model = get_user_model()
    org_ids = [o.pk for o in organizations]
    org_paths = _cascade_paths(Organization)
    # Les organisations sont prises via `organizations`, pas via leur propriétaire.
    user_paths = _cascade_paths(user_model, stop=(Organization,))
    result = [
        (user_model, user_model.objects.filter(pk=user.pk)),
        (Organization, Organization.objects.filter(pk__in=org_ids)),
    ]
    for model in _local_models():
        if model in (user_model, Organization):
            continue
        condition = Q()
        if model in org_paths and org_ids:
            condition |= Q(**{f'{org_paths[model]}__in': org_ids})
        if model in user_paths:
            condition |= Q(**{user_paths[model]: user.pk})
        if condition:
            result.append((model, model._default_manager.filter(condition).distinct()))
    return result


def exportable_fields(model):
    excluded = EXCLUDED_FIELDS.get(model._meta.label, set())
    return [f for f in model._meta.concrete_fields
            if not f.primary_key and f.name not in excluded and not SECRET_FIELD.search(f.name)]


def file_fields(model):
    return [f for f in model._meta.concrete_fields if isinstance(f, models.FileField)]


def stored_files(querysets):
    """Noms (dans le stockage) des fichiers rattachés aux objets, sans doublon."""
    names = []
    for model, queryset in querysets:
        fields = file_fields(model)
        if not fields:
            continue
        for row in queryset.values_list(*[f.name for f in fields]):
            names.extend(name for name in row if name)
    return list(dict.fromkeys(names))


def _cell(value):
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, cls=DjangoJSONEncoder)
    return '' if value is None else value


README = """Export de vos données Billio — {date}

Compte : {email}
Organisations : {organizations}

donnees/  un fichier JSON par type de données (format lisible par un programme, pour
          les réimporter ailleurs) ;
csv/      les mêmes données en CSV (séparateur « ; », s'ouvre dans Excel ou LibreOffice) ;
fichiers/ les fichiers déposés : PDF des factures et devis, pièces jointes, logos.

Les liens entre fichiers se font par l'identifiant (« id ») : par exemple, la colonne
« client » d'une facture contient l'id du client dans clients.client.

Mots de passe, clés d'API et liens d'accès secrets ne sont pas inclus.
{omitted}"""


def build_export(user, organizations):
    """Archive ZIP (fichier temporaire, positionné au début) des données du compte."""
    querysets = owned_querysets(user, organizations)
    archive = tempfile.SpooledTemporaryFile(max_size=50 * 1024 * 1024)
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as zf:
        for model, queryset in querysets:
            fields = exportable_fields(model)
            records = serializers.serialize('python', queryset.order_by('pk'), fields=[f.name for f in fields])
            if not records:
                continue
            label = model._meta.label_lower
            data = [{'id': r['pk'], **r['fields']} for r in records]
            zf.writestr(f'donnees/{label}.json', json.dumps(data, ensure_ascii=False, indent=2, cls=DjangoJSONEncoder))
            buffer = io.StringIO()
            writer = csv.writer(buffer, delimiter=';')
            writer.writerow(['id'] + [f.name for f in fields])
            for row in data:
                writer.writerow([_cell(row['id'])] + [_cell(row.get(f.name)) for f in fields])
            zf.writestr(f'csv/{label}.csv', '﻿' + buffer.getvalue())

        omitted = []
        total = 0
        from django.core.files.storage import default_storage
        for name in stored_files(querysets):
            try:
                size = default_storage.size(name)
                if total + size > MAX_FILES_BYTES:
                    omitted.append(name)
                    continue
                with default_storage.open(name, 'rb') as source, zf.open(f'fichiers/{name}', 'w') as target:
                    for chunk in iter(lambda: source.read(1024 * 1024), b''):
                        target.write(chunk)
                total += size
            except OSError:
                omitted.append(name)  # fichier absent du stockage

        note = ''
        if omitted:
            note = ("\nFichiers non inclus (absents ou au-delà de 500 Mo d'export) — demandez-les au support :\n"
                    + '\n'.join(f'  {name}' for name in omitted) + '\n')
        zf.writestr('LISEZMOI.txt', README.format(
            date=timezone.localtime().strftime('%d/%m/%Y %H:%M'), email=user.email,
            organizations=', '.join(o.name for o in organizations) or '—', omitted=note))
    archive.seek(0)
    return archive
