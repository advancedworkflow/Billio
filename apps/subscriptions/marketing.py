"""Présentation des forfaits sur le site public, générée depuis la grille (Plan) pour rester à jour."""

# Libellés courts des options, dans l'ordre d'affichage. (clé, niveau, libellé)
FEATURE_LINES = [
    ('recurring', None, 'Factures récurrentes'),
    ('deposits', None, 'Acomptes et échéanciers'),
    ('manual_payments', None, 'Paiements manuels'),
    ('portal', 'basic', 'Portail client'),
    ('reminders', None, 'Relances automatiques'),
    ('quote_signature', None, 'Signature en ligne des devis'),
    ('portal', 'full', 'Portail client complet'),
    ('booking', None, 'Prise de rendez-vous en ligne'),
    ('time_tracking', 'basic', 'Chrono et suivi du temps'),
    ('time_billing', None, 'Facturation du temps passé'),
    ('facturx', None, 'Factur-X'),
    ('api', None, 'API REST'),
    ('inbound_webhooks', None, 'Webhooks entrants'),
    ('multi_org', None, 'Plusieurs organisations'),
]
LEVELS = {'portal': ['basic', 'full'], 'time_tracking': ['none', 'basic', 'full']}


def _has(plan, key, level):
    value = plan.feature(key)
    if key in LEVELS:
        order = LEVELS[key]
        return order.index(value if value in order else order[0]) >= order.index(level)
    return bool(value)


def _count(value, singular, plural=None):
    if value is None:
        return f"{(plural or singular + 's').capitalize()} illimités"
    return f"{value:,}".replace(',', ' ') + ' ' + (singular if value == 1 else (plural or singular + 's'))


def _storage(mb):
    if mb is None:
        return 'Stockage illimité'
    return f"{mb / 1024:g} Go de stockage" if mb >= 1024 else f"{mb} Mo de stockage"


def plan_cards(plans):
    """Pour chaque forfait : limites principales et options ajoutées par rapport au forfait précédent."""
    cards, previous = [], None
    for plan in plans:
        documents = plan.limit('documents_per_month')
        limits = [
            f"{_count(plan.limit('clients'), 'client')} · {_count(plan.limit('projects'), 'projet')}",
            'Factures et devis illimités' if documents is None else f"{documents} factures et devis / mois",
            _storage(plan.limit('storage_mb')),
            _count(plan.limit('users'), 'utilisateur'),
        ]
        included = [label for key, level, label in FEATURE_LINES if _has(plan, key, level)]
        if previous is None:
            highlights = included
        else:
            before = {label for key, level, label in FEATURE_LINES if _has(previous, key, level)}
            highlights = [f"Tout {previous.name}, plus :"] + [label for label in included if label not in before]
        cards.append({'plan': plan, 'limits': limits, 'highlights': highlights})
        previous = plan
    return cards
