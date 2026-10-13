"""
Informations légales de l'éditeur de Billio (mentions légales, CGU, confidentialité).

Chaque valeur vient d'une variable d'environnement `LEGAL_*`. Tant qu'une valeur manque,
les pages affichent « [À compléter : …] » et `manage.py check --deploy` le signale.
"""
import os
from datetime import date

from django.core.checks import Warning, register

# Dernière mise à jour des textes (à changer à chaque modification des CGU / de la politique).
UPDATED_AT = date(2026, 10, 12)

FIELDS = {
    'company': ('LEGAL_COMPANY_NAME', 'raison sociale'),
    'legal_form': ('LEGAL_FORM', 'forme juridique (SAS, SARL, EI…)'),
    'capital': ('LEGAL_CAPITAL', 'capital social'),
    'address': ('LEGAL_ADDRESS', 'adresse du siège'),
    'siren': ('LEGAL_SIREN', 'numéro SIREN'),
    'rcs': ('LEGAL_RCS', 'ville du RCS'),
    'vat': ('LEGAL_VAT_NUMBER', 'numéro de TVA intracommunautaire'),
    'director': ('LEGAL_DIRECTOR', 'directeur de la publication'),
    'email': ('LEGAL_EMAIL', 'email de contact'),
    'dpo_email': ('LEGAL_PRIVACY_EMAIL', 'email pour les données personnelles'),
    'host_name': ('LEGAL_HOST_NAME', "nom de l'hébergeur"),
    'host_address': ('LEGAL_HOST_ADDRESS', "adresse de l'hébergeur"),
    'host_location': ('LEGAL_HOST_LOCATION', 'pays des serveurs'),
    'court': ('LEGAL_COURT', 'tribunal compétent'),
}


def legal_info():
    info, missing = {}, []
    for key, (env, label) in FIELDS.items():
        value = os.getenv(env, '').strip()
        if not value:
            missing.append(env)
        info[key] = value or f'[À compléter : {label}]'
    if not os.getenv('LEGAL_PRIVACY_EMAIL', '').strip() and os.getenv('LEGAL_EMAIL', '').strip():
        info['dpo_email'] = info['email']
        missing.remove('LEGAL_PRIVACY_EMAIL')
    info['missing'] = missing
    info['updated_at'] = UPDATED_AT
    return info


@register(deploy=True)
def check_legal_info(app_configs, **kwargs):
    missing = legal_info()['missing']
    if not missing:
        return []
    return [Warning(
        'Informations légales incomplètes : les pages Mentions légales / CGU / Confidentialité affichent « À compléter ».',
        hint='Renseignez les variables : ' + ', '.join(missing),
        id='landing.W001',
    )]
