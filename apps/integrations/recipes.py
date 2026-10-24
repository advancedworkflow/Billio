"""
Intégrations pour les non-techniciens : on part du besoin (« Être payé par carte »), pas de l'outil,
et chaque besoin propose des recettes : des workflows prêts à l'emploi, ouverts pré-remplis dans le
constructeur d'automatisations (/dashboard/automations/builder/?recipe=<clé>) où il ne reste qu'à
vérifier puis enregistrer.

Les graphes suivent le format du constructeur ; les paramètres non précisés reprennent les valeurs
par défaut du bloc côté navigateur.
"""

PAYMENT_TEXT = '💶 Paiement reçu : {{montant}} de {{client}} (facture {{numero}}).'
QUOTE_TEXT = '🎉 Devis {{numero}} accepté par {{client}} ({{montant}}).'


def _node(id_, type_, key, params=None, label=''):
    return {'id': id_, 'type': type_, 'key': key, 'label': label, 'params': params or {}}


def _chain(*nodes):
    """Graphe linéaire : chaque bloc relié au suivant."""
    edges = [{'from': a['id'], 'port': 'out', 'to': b['id']} for a, b in zip(nodes, nodes[1:])]
    return {'nodes': list(nodes), 'edges': edges}


def _message(channel, trigger, text):
    return _chain(_node('t', 'trigger', trigger),
                  _node('m', 'action', 'send_message', {'channel': channel, 'recipient_mode': 'default', 'text': text}))


RECIPES = {
    'payment-email-me': {
        'name': "M'envoyer un email à chaque paiement",
        'desc': 'Un email récapitulatif dès qu’un client vous règle, par carte ou par virement enregistré.',
        'tool': 'email',
        'graph': _chain(_node('t', 'trigger', 'payment_received'),
                        _node('e', 'action', 'send_email', {
                            'recipient': 'owner', 'subject': 'Paiement reçu de {{client}}',
                            'body': 'Bonne nouvelle : {{client}} vient de régler {{montant}} (facture {{numero}}).'})),
    },
    'payment-thanks-client': {
        'name': 'Remercier le client après son paiement',
        'desc': 'Un email de remerciement part tout seul au client quand sa facture est payée.',
        'tool': 'email',
        'graph': _chain(_node('t', 'trigger', 'payment_received'),
                        _node('e', 'action', 'send_email', {
                            'recipient': 'client', 'subject': 'Merci pour votre règlement',
                            'body': 'Bonjour {{client}},\n\nNous avons bien reçu votre paiement de {{montant}} '
                                    '(facture {{numero}}). Merci pour votre confiance !\n\nBien cordialement'})),
    },
    'payment-slack': {
        'name': 'Paiement reçu → message Slack',
        'desc': "Toute l'équipe voit passer les paiements dans votre canal Slack.",
        'tool': 'slack', 'graph': _message('slack', 'payment_received', PAYMENT_TEXT),
    },
    'quote-whatsapp': {
        'name': 'Devis accepté → message WhatsApp',
        'desc': 'Soyez prévenu sur votre téléphone dès qu’un client accepte un devis.',
        'tool': 'whatsapp', 'graph': _message('whatsapp', 'quote_accepted', QUOTE_TEXT),
    },
    'payment-telegram': {
        'name': 'Paiement reçu → message Telegram',
        'desc': 'Une notification Telegram à chaque règlement.',
        'tool': 'telegram', 'graph': _message('telegram', 'payment_received', PAYMENT_TEXT),
    },
    'invoice-drive': {
        'name': 'Ranger chaque facture envoyée dans Google Drive',
        'desc': 'Le PDF de chaque facture envoyée est copié dans votre Drive : idéal pour le comptable.',
        'tool': 'google-drive',
        'graph': _chain(_node('t', 'trigger', 'invoice_sent'), _node('d', 'action', 'drive_upload', {'include_created': False})),
    },
    'quote-drive': {
        'name': 'Ranger les devis acceptés dans Google Drive',
        'desc': 'Le devis signé est archivé dans votre Drive dès son acceptation.',
        'tool': 'google-drive',
        'graph': _chain(_node('t', 'trigger', 'quote_accepted'), _node('d', 'action', 'drive_upload', {'include_created': False})),
    },
    'quote-trello': {
        'name': 'Devis accepté → carte Trello',
        'desc': 'Une carte « À démarrer » est créée dans votre tableau Trello pour chaque nouveau projet signé.',
        'tool': 'trello',
        'graph': _chain(_node('t', 'trigger', 'quote_accepted'),
                        _node('a', 'action', 'app_action', {'app': 'trello', 'operation': 'create_card',
                                                            'values': {'title': 'À démarrer : {{client}} ({{numero}})'}})),
    },
    'client-notion': {
        'name': 'Nouveau client → ligne dans Notion',
        'desc': 'Votre base clients Notion se remplit toute seule.',
        'tool': 'notion',
        'graph': _chain(_node('t', 'trigger', 'client_created'),
                        _node('a', 'action', 'app_action', {'app': 'notion', 'operation': 'create_row',
                                                            'values': {'title': '{{client}}', 'fields': 'Email : {{email_client}}'}})),
    },
    'client-mailchimp': {
        'name': 'Nouveau client → audience Mailchimp',
        'desc': 'Chaque nouveau client rejoint votre liste Mailchimp (newsletter, relances).',
        'tool': 'mailchimp',
        'graph': _chain(_node('t', 'trigger', 'client_created'),
                        _node('a', 'action', 'app_action', {'app': 'mailchimp', 'operation': 'add_member',
                                                            'values': {'status': 'subscribed', 'tags': 'client, billio'}})),
    },
    'invoice-quickbooks': {
        'name': 'Facture envoyée → QuickBooks',
        'desc': 'Chaque facture envoyée est créée dans QuickBooks avec ses lignes et sa TVA, client compris.',
        'tool': 'quickbooks',
        'graph': _chain(_node('t', 'trigger', 'invoice_sent'),
                        _node('a', 'action', 'app_action', {'app': 'quickbooks', 'operation': 'create_invoice',
                                                            'values': {'item': 'Prestations'}})),
    },
    'payment-quickbooks': {
        'name': 'Paiement reçu → QuickBooks',
        'desc': 'Le paiement est enregistré et lettré sur la facture QuickBooks : votre compta reste à jour.',
        'tool': 'quickbooks',
        'graph': _chain(_node('t', 'trigger', 'payment_received'),
                        _node('a', 'action', 'app_action', {'app': 'quickbooks', 'operation': 'record_payment', 'values': {}})),
    },
}

# Besoins affichés en tête de la page Intégrations : outils proposés et recettes associées.
NEEDS = [
    {'key': 'paid', 'icon': 'credit-card', 'label': 'Être payé par carte',
     'desc': 'Un bouton « Payer » sur vos factures, l’argent arrive sur votre compte.',
     'tools': ['stripe'], 'recipes': ['payment-email-me', 'payment-thanks-client']},
    {'key': 'notified', 'icon': 'bell-ring', 'label': 'Être prévenu sur mon téléphone',
     'desc': 'Paiement reçu, devis accepté : un message là où vous êtes déjà.',
     'tools': ['whatsapp', 'telegram', 'slack'], 'recipes': ['quote-whatsapp', 'payment-telegram', 'payment-slack']},
    {'key': 'emails', 'icon': 'mail', 'label': 'Envoyer les emails avec mon adresse',
     'desc': 'Vos clients reçoivent factures et relances depuis votre propre adresse email.',
     'tools': ['email'], 'recipes': ['payment-thanks-client', 'payment-email-me']},
    {'key': 'archive', 'icon': 'folder-check', 'label': 'Ranger mes factures automatiquement',
     'desc': 'Chaque facture et devis copiés dans un dossier, prêts pour le comptable.',
     'tools': ['google-drive'], 'recipes': ['invoice-drive', 'quote-drive']},
    {'key': 'accounting', 'icon': 'calculator', 'label': 'Tenir ma comptabilité à jour',
     'desc': 'Factures et paiements arrivent tout seuls dans votre logiciel comptable.',
     'tools': ['quickbooks'], 'recipes': ['invoice-quickbooks', 'payment-quickbooks']},
    {'key': 'organize', 'icon': 'kanban-square', 'label': 'Organiser mon travail',
     'desc': 'Les projets signés arrivent dans votre outil de gestion.',
     'tools': ['trello', 'notion'], 'recipes': ['quote-trello', 'client-notion']},
    {'key': 'contacts', 'icon': 'users', 'label': 'Développer ma liste de contacts',
     'desc': 'Vos clients rejoignent votre newsletter sans copier-coller.',
     'tools': ['mailchimp'], 'recipes': ['client-mailchimp']},
]


def needs_for_page(available_tools):
    """Besoins limités aux outils réellement proposés sur la page (et leurs recettes)."""
    out = []
    for need in NEEDS:
        tools = [t for t in need['tools'] if t in available_tools]
        if not tools:
            continue
        recipes = [dict(RECIPES[r], key=r) for r in need['recipes'] if RECIPES[r]['tool'] in available_tools]
        out.append(dict(need, tools=tools, recipes=[{k: v for k, v in r.items() if k != 'graph'} for r in recipes]))
    return out
