"""
Packs métier : réglages de départ adaptés à l'activité de l'organisation.

Un pack apporte des phases de projet (Kanban), des modèles de projet (jalons,
tâches, livrables, dates relatives au début du projet), des mentions légales
propres au métier et les unités de facturation usuelles. Il est appliqué à
l'inscription (métier demandé) et peut être réappliqué depuis Paramètres › Métier.

Chaque pack nomme aussi son **processus principal** (les phases ci-dessus) et propose
d'autres **processus** courants du métier (ex. BTP : « Dépannage », « Entretien annuel ») :
un processus est une suite d'étapes qu'un projet suit ; les étapes sont partagées entre
processus (« Terminé » sert à tous).

Format d'un jalon de modèle : {'title', 'phase', 'start', 'due' (jours depuis le
début du projet), 'description', 'tasks': [{'title', 'start', 'due'}],
'deliverables': [titre, ...]}.
"""
from django.db import transaction

DONE = ('completed', 'Terminé', '#16a34a')


def _proc(name, description, phases):
    return {'name': name, 'description': description, 'phases': phases}


def _m(title, phase, start, due, tasks=(), deliverables=(), description=''):
    return {
        'title': title, 'phase': phase, 'start': start, 'due': due, 'description': description,
        'tasks': [{'title': t, 'start': start, 'due': due} for t in tasks],
        'deliverables': list(deliverables),
    }


TRADE_PACKS = {
    'audiovisuel': {
        'label': 'Vidéo, photo & création',
        'process': 'Production vidéo',
        'processes': [
            _proc('Shooting photo', 'Mariages, portraits, évènements, packshots.', [
                ('onboarding', 'Brief', '#0ea5e9'), ('shooting', 'Tournage / Prise de vue', '#f59e0b'),
                ('selection', 'Sélection', '#a855f7'), ('retouch', 'Retouches', '#9333ea'), ('delivery', 'Livraison', '#db2777'), DONE]),
            _proc('Réseaux sociaux (mensuel)', 'Abonnement de contenus : un cycle par mois.', [
                ('monthly_plan', 'Planning du mois', '#0ea5e9'), ('creation', 'Création', '#9333ea'),
                ('review', 'Validation client', '#06b6d4'), ('publishing', 'Publication', '#db2777'), ('monthly_report', 'Bilan du mois', '#22c55e'), DONE]),
        ],
        'description': 'Vidéastes, photographes, motion designers, studios de création.',
        'icon': 'clapperboard',
        'phases': [('onboarding', 'Brief', '#0ea5e9'), ('preproduction', 'Pré-production', '#6366f1'),
                   ('shooting', 'Tournage / Prise de vue', '#f59e0b'), ('postproduction', 'Post-production', '#9333ea'),
                   ('review', 'Validation client', '#06b6d4'), ('delivery', 'Livraison', '#db2777'), DONE],
        'units': ['forfait', 'jour', 'demi-journée', 'heure', 'photo'],
        'mentions': ("Cession des droits d'exploitation limitée aux usages, supports et durée prévus au devis ; "
                     "elle prend effet au paiement intégral de la facture."),
        'templates': [
            {'name': 'Clip / film promotionnel', 'description': 'Du brief à la livraison des masters, avec deux allers-retours de montage.',
             'milestones': [
                 _m('Brief validé & acompte', 'onboarding', 0, 3, ['Questionnaire de cadrage', "Facture d'acompte"]),
                 _m('Moodboard & storyboard', 'preproduction', 3, 10, ['Pistes visuelles', 'Storyboard', 'Repérages'], ['Moodboard', 'Storyboard']),
                 _m('Tournage', 'shooting', 10, 14, ['Feuille de service', 'Réservation matériel', 'Sauvegarde des rushes']),
                 _m('Montage V1', 'postproduction', 14, 21, ['Dérushage', 'Montage'], ['Montage V1']),
                 _m('Montage V2 + étalonnage', 'postproduction', 21, 28, ['Intégration des retours', 'Étalonnage', 'Mixage'], ['Montage V2']),
                 _m('Livraison des masters', 'delivery', 28, 30, ['Exports 4K', 'Déclinaisons réseaux sociaux'], ['Master 4K', 'Formats réseaux']),
             ]},
            {'name': 'Reportage photo (mariage, évènement)', 'process': 'Shooting photo',
             'description': "Rendez-vous préparatoire, jour J, tri et retouches, galerie en ligne.",
             'milestones': [
                 _m('Rendez-vous préparatoire', 'onboarding', 0, 7, ['Contrat signé', 'Liste des photos souhaitées']),
                 _m('Jour J', 'shooting', 7, 7, ['Planning de la journée', 'Sauvegarde des cartes']),
                 _m('Tri & sélection', 'selection', 8, 14, ['Sélection'], ['Sélection pour validation']),
                 _m('Retouches', 'retouch', 14, 28, ['Retouches']),
                 _m('Galerie livrée', 'delivery', 28, 30, ['Galerie en ligne', 'Tirages éventuels'], ['Galerie finale']),
             ]},
        ],
    },
    'btp': {
        'label': 'Artisans & BTP',
        'process': 'Chantier',
        'processes': [
            _proc('Dépannage', 'Intervention rapide : appel, diagnostic, réparation, facture.', [
                ('call', 'Appel / demande', '#3b82f6'), ('diagnosis', 'Diagnostic', '#6366f1'),
                ('intervention', 'Intervention', '#ea580c'), ('invoicing', 'Facturation', '#06b6d4'), DONE]),
            _proc('Entretien annuel', 'Contrats d’entretien : chaudière, climatisation, toiture…', [
                ('scheduling', 'Prise de rendez-vous', '#3b82f6'), ('visit', 'Visite d’entretien', '#ea580c'),
                ('service_report', 'Rapport d’intervention', '#06b6d4'), DONE]),
        ],
        'description': 'Plombiers, électriciens, menuisiers, peintres, entreprises générales.',
        'icon': 'hard-hat',
        'phases': [('discovery', 'Visite & métré', '#3b82f6'), ('planning', 'Devis signé', '#6366f1'),
                   ('supply', 'Approvisionnement', '#f59e0b'), ('worksite', 'Chantier', '#ea580c'),
                   ('review', 'Réception des travaux', '#06b6d4'), ('reserves', 'Levée des réserves', '#db2777'), DONE],
        'units': ['m²', 'ml', 'u', 'h', 'forfait', 'jour'],
        'mentions': ("Assurance décennale : [assureur], contrat n° [numéro], couverture géographique : [zone]. "
                     "Travaux de rénovation de logements de plus de deux ans : TVA à 10 % sur attestation du client. "
                     "Sous-traitance BTP : autoliquidation de la TVA (art. 283-2 nonies du CGI)."),
        'templates': [
            {'name': 'Rénovation de salle de bain', 'description': 'Visite, devis, dépose, plomberie, carrelage, réception.',
             'milestones': [
                 _m('Visite & métré', 'discovery', 0, 3, ['Relevé des cotes', 'Photos avant travaux']),
                 _m('Devis signé & acompte', 'planning', 3, 10, ['Envoi du devis', "Facture d'acompte (30 %)"]),
                 _m('Commande des matériaux', 'supply', 10, 20, ['Commande sanitaires', 'Commande carrelage']),
                 _m('Dépose & plomberie', 'worksite', 20, 25, ['Dépose', 'Réseaux eau / évacuation', 'Électricité']),
                 _m('Carrelage & finitions', 'worksite', 25, 32, ['Étanchéité', 'Pose carrelage', 'Pose sanitaires']),
                 _m('Réception des travaux', 'review', 32, 33, ['Procès-verbal de réception', 'Facture de solde'], ['PV de réception']),
             ]},
            {'name': 'Chantier facturé par situations', 'description': 'Gros chantier avec situations mensuelles et retenue de garantie.',
             'milestones': [
                 _m('Ordre de service', 'planning', 0, 5, ['Marché signé', 'Planning de chantier']),
                 _m('Situation n° 1', 'worksite', 5, 35, ['Métré d\'avancement', 'Facture de situation']),
                 _m('Situation n° 2', 'worksite', 35, 65, ['Métré d\'avancement', 'Facture de situation']),
                 _m('Réception', 'review', 65, 70, ['PV de réception', 'Liste des réserves'], ['PV de réception']),
                 _m('Levée des réserves', 'reserves', 70, 100, ['Reprises', 'Libération de la retenue de garantie (1 an)']),
             ]},
        ],
    },
    'conseil': {
        'label': 'Conseil & formation',
        'process': 'Mission de conseil',
        'processes': [
            _proc('Formation', 'Convention, convocations, session, évaluations (Qualiopi).', [
                ('onboarding', 'Cadrage', '#0ea5e9'), ('convocation', 'Convocations', '#6366f1'),
                ('delivery', 'Mise en œuvre / Session', '#f59e0b'), ('evaluation', 'Évaluations & attestations', '#06b6d4'), DONE]),
            _proc('Audit', 'Cadrage, collecte, analyse, restitution.', [
                ('onboarding', 'Cadrage', '#0ea5e9'), ('collect', 'Collecte', '#3b82f6'),
                ('analysis', 'Analyse', '#6366f1'), ('restitution', 'Restitution', '#f59e0b'), DONE]),
        ],
        'description': 'Consultants, coachs, formateurs, organismes de formation.',
        'icon': 'presentation',
        'phases': [('onboarding', 'Cadrage', '#0ea5e9'), ('discovery', 'Diagnostic', '#3b82f6'),
                   ('recommendation', 'Recommandations', '#6366f1'), ('delivery', 'Mise en œuvre / Session', '#f59e0b'),
                   ('review', 'Bilan', '#06b6d4'), DONE],
        'units': ['jour', 'demi-journée', 'heure', 'session', 'participant'],
        'mentions': ("Organisme de formation enregistré sous le n° [numéro] auprès du préfet de région [région] "
                     "(cet enregistrement ne vaut pas agrément de l'État). Formation professionnelle continue : "
                     "exonération de TVA, art. 261-4-4° du CGI, le cas échéant."),
        'templates': [
            {'name': 'Mission de conseil (10 jours)', 'description': 'Cadrage, diagnostic, recommandations, accompagnement, bilan.',
             'milestones': [
                 _m('Réunion de cadrage', 'onboarding', 0, 5, ['Proposition signée', 'Planning des entretiens']),
                 _m('Diagnostic', 'discovery', 5, 20, ['Entretiens', 'Analyse des données'], ['Rapport de diagnostic']),
                 _m('Recommandations', 'recommendation', 20, 30, ['Restitution au comité'], ['Plan d\'action']),
                 _m('Accompagnement', 'delivery', 30, 55, ['Ateliers', 'Points hebdomadaires']),
                 _m('Bilan de mission', 'review', 55, 60, ['Bilan', 'Facture de solde'], ['Rapport final']),
             ]},
            {'name': 'Session de formation', 'process': 'Formation', 'description': 'Convention, convocations, session, évaluations, attestations.',
             'milestones': [
                 _m('Convention de formation', 'onboarding', 0, 7, ['Convention signée', 'Programme et prérequis']),
                 _m('Convocations', 'convocation', 7, 14, ['Convocations envoyées', 'Questionnaire de positionnement']),
                 _m('Session', 'delivery', 14, 16, ['Feuilles d\'émargement', 'Support de formation'], ['Support de formation']),
                 _m('Évaluations & attestations', 'evaluation', 16, 21, ['Évaluation à chaud', 'Attestations de fin de formation'], ['Attestations']),
             ]},
        ],
    },
    'liberal': {
        'label': 'Professions libérales',
        'process': 'Dossier client',
        'processes': [
            _proc('Consultation ponctuelle', 'Un rendez-vous, une note d’honoraires.', [
                ('onboarding', 'Premier rendez-vous', '#0ea5e9'), ('consultation', 'Consultation', '#f59e0b'),
                ('closing', 'Clôture', '#06b6d4'), DONE]),
            _proc('Procédure', 'Contentieux ou procédure longue : audiences et décision.', [
                ('opening', 'Ouverture du dossier', '#6366f1'), ('procedure', 'Procédure', '#3b82f6'),
                ('hearing', 'Audience', '#f59e0b'), ('decision', 'Décision', '#06b6d4'), ('closing', 'Clôture', '#06b6d4'), DONE]),
        ],
        'description': 'Avocats, experts, architectes, psychologues, thérapeutes, paramédical.',
        'icon': 'briefcase',
        'phases': [('onboarding', 'Premier rendez-vous', '#0ea5e9'), ('opening', 'Ouverture du dossier', '#6366f1'),
                   ('followup', 'Suivi', '#f59e0b'), ('closing', 'Clôture', '#06b6d4'), DONE],
        'units': ['séance', 'heure', 'forfait', 'acte'],
        'mentions': ("Membre d'une association de gestion agréée : le règlement des honoraires par chèque est accepté. "
                     "Provision sur honoraires à valoir sur la note d'honoraires définitive, le cas échéant."),
        'templates': [
            {'name': 'Dossier client', 'description': "Rendez-vous initial, convention d'honoraires, suivi, clôture.",
             'milestones': [
                 _m('Premier rendez-vous', 'onboarding', 0, 3, ['Recueil des informations', 'Convention / lettre de mission']),
                 _m('Ouverture du dossier', 'opening', 3, 10, ["Provision sur honoraires", 'Pièces justificatives']),
                 _m('Suivi', 'followup', 10, 60, ['Rendez-vous de suivi', 'Comptes rendus']),
                 _m('Clôture', 'closing', 60, 65, ["Note d'honoraires définitive", 'Archivage']),
             ]},
        ],
    },
    'commerce': {
        'label': 'Commerce & fabrication',
        'process': 'Commande',
        'processes': [
            _proc('Click & collect', 'Préparation et retrait en boutique.', [
                ('order', 'Commande', '#3b82f6'), ('production', 'Fabrication / Préparation', '#f59e0b'),
                ('ready', 'Prêt à retirer', '#06b6d4'), ('delivery', 'Livré', '#db2777'), DONE]),
            _proc('Retour / SAV', 'Demande, contrôle, échange ou remboursement.', [
                ('return_request', 'Demande de retour', '#3b82f6'), ('inspection', 'Contrôle', '#f59e0b'),
                ('refund', 'Échange / remboursement', '#6366f1'), DONE]),
        ],
        'description': 'Boutiques, e-commerce, artisans d\'art, fabrication sur mesure.',
        'icon': 'store',
        'phases': [('order', 'Commande', '#3b82f6'), ('production', 'Fabrication / Préparation', '#f59e0b'),
                   ('shipping', 'Expédition', '#6366f1'), ('delivery', 'Livré', '#db2777'), DONE],
        'units': ['u', 'lot', 'kg', 'm', 'forfait'],
        'mentions': ("Garantie légale de conformité de 2 ans (art. L217-3 et suivants du Code de la consommation) "
                     "et garantie des vices cachés. Réserve de propriété jusqu'au paiement intégral."),
        'templates': [
            {'name': 'Commande sur mesure', 'description': 'Validation, acompte, fabrication, expédition, livraison.',
             'milestones': [
                 _m('Commande validée & acompte', 'order', 0, 3, ['Bon de commande', "Facture d'acompte"]),
                 _m('Fabrication', 'production', 3, 20, ['Approvisionnement', 'Fabrication', 'Contrôle qualité']),
                 _m('Expédition', 'shipping', 20, 23, ['Emballage', 'Numéro de suivi']),
                 _m('Livraison', 'delivery', 23, 26, ['Confirmation de réception', 'Facture de solde']),
             ]},
        ],
    },
    'web': {
        'label': 'Agence web & digital',
        'process': 'Projet web',
        'processes': [
            _proc('Maintenance mensuelle', 'Abonnement : un cycle de maintenance par mois.', [
                ('monthly_plan', 'Planning du mois', '#0ea5e9'), ('development', 'Développement', '#f59e0b'),
                ('review', 'Revue', '#06b6d4'), ('monthly_report', 'Rapport mensuel', '#22c55e'), DONE]),
            _proc('Application / SaaS', 'Produit sur mesure avec phase de tests.', [
                ('onboarding', 'Onboarding', '#0ea5e9'), ('discovery', 'Découverte', '#3b82f6'), ('design', 'Design', '#9333ea'),
                ('development', 'Développement', '#f59e0b'), ('testing', 'Tests', '#06b6d4'), ('delivery', 'Livraison', '#db2777'), DONE]),
        ],
        'description': 'Développeurs, designers UX/UI, agences web et marketing.',
        'icon': 'monitor-smartphone',
        'phases': [('onboarding', 'Onboarding', '#0ea5e9'), ('discovery', 'Découverte', '#3b82f6'),
                   ('planning', 'Planification', '#6366f1'), ('design', 'Design', '#9333ea'),
                   ('development', 'Développement', '#f59e0b'), ('review', 'Revue', '#06b6d4'),
                   ('delivery', 'Livraison', '#db2777'), DONE],
        'units': ['jour', 'heure', 'forfait', 'mois'],
        'mentions': ("Les codes sources et maquettes restent la propriété du prestataire jusqu'au paiement intégral ; "
                     "la cession de droits est précisée au devis."),
        'templates': [
            {'name': 'Site vitrine', 'description': 'Atelier, maquettes, intégration, recette, mise en ligne.',
             'milestones': [
                 _m('Atelier de lancement', 'onboarding', 0, 5, ['Questionnaire', 'Arborescence']),
                 _m('Maquettes', 'design', 5, 15, ['Maquette accueil', 'Maquettes pages internes'], ['Maquettes']),
                 _m('Intégration', 'development', 15, 30, ['Intégration', 'Contenus', 'SEO de base']),
                 _m('Recette', 'review', 30, 35, ['Recette client', 'Corrections'], ['Site de préproduction']),
                 _m('Mise en ligne', 'delivery', 35, 37, ['Mise en production', 'Formation au back-office'], ['Site en ligne']),
             ]},
        ],
    },
    'autre': {
        'label': 'Autre activité',
        'process': 'Projet',
        'processes': [
            _proc('Prestation courte', 'Démarrage, réalisation, livraison.', [
                ('onboarding', 'Démarrage', '#0ea5e9'), ('production', 'Réalisation', '#f59e0b'), ('delivery', 'Livraison', '#db2777'), DONE]),
        ],
        'description': 'Phases génériques, à adapter ensuite.',
        'icon': 'sparkles',
        'phases': [('onboarding', 'Démarrage', '#0ea5e9'), ('planning', 'Préparation', '#6366f1'),
                   ('production', 'Réalisation', '#f59e0b'), ('review', 'Validation', '#06b6d4'),
                   ('delivery', 'Livraison', '#db2777'), DONE],
        'units': ['forfait', 'heure', 'jour', 'u'],
        'mentions': '',
        'templates': [],
    },
}
TRADE_CHOICES = [(key, pack['label']) for key, pack in TRADE_PACKS.items()]


def main_process_name(trade):
    return (TRADE_PACKS.get(trade) or {}).get('process') or 'Processus principal'


def ensure_process(organization, name, phases, *, description='', is_default=False):
    """
    Crée (ou complète) un processus et les étapes qui lui manquent. Une étape déjà présente dans
    l'organisation (même clé) est réutilisée telle quelle : les étapes sont partagées.
    """
    from apps.dashboard.models import ProjectPhase, ProjectProcess

    existing = {p.key: p for p in ProjectPhase.objects.filter(organization=organization)}
    order = max((p.order for p in existing.values()), default=-1) + 1
    keys = []
    for key, label, color in phases:
        if key not in existing:
            existing[key] = ProjectPhase.objects.create(organization=organization, key=key, label=label, color=color, order=order)
            order += 1
        keys.append(key)
    process, created = ProjectProcess.objects.get_or_create(
        organization=organization, name=name,
        defaults={'description': description, 'phase_keys': keys, 'is_default': is_default,
                  'order': ProjectProcess.objects.filter(organization=organization).count()},
    )
    # « Terminé » reste la dernière étape même si elle a été créée avant les étapes propres au processus.
    completed = ProjectPhase.objects.filter(organization=organization, key='completed').first()
    if completed:
        completed.order = max(p.order for p in existing.values()) + 1
        completed.save(update_fields=['order'])
    return process, created


def apply_trade_pack(organization, trade, *, user=None):
    """
    Applique le pack : phases (remplacées si aucun projet ne les utilise, sinon ajoutées),
    modèles de projet (ajoutés s'ils n'existent pas), mentions et unités dans les préférences.
    Retourne un court résumé de ce qui a changé.
    """
    from apps.dashboard.models import Project, ProjectPhase, ProjectTemplate

    pack = TRADE_PACKS.get(trade) or TRADE_PACKS['autre']
    summary = {'phases_added': 0, 'phases_replaced': False, 'templates_added': 0}
    with transaction.atomic():
        existing = {p.key: p for p in ProjectPhase.objects.filter(organization=organization)}
        used = set(Project.objects.filter(organization=organization).values_list('status', flat=True))
        unused = [p for key, p in existing.items() if key not in used]
        # Les phases jamais utilisées sont retirées ; celles qui portent des projets restent.
        for phase in unused:
            phase.delete()
        if unused and not used:
            summary['phases_replaced'] = True
        kept = {key for key in existing if key in used}
        # Anciennes phases encore utilisées : gardées juste avant « Terminé » (à retirer à la main ensuite).
        legacy = [existing[k] for k in sorted(kept - {k for k, *_ in pack['phases']}, key=lambda k: existing[k].order)]
        order = 0
        for key, label, color in pack['phases']:
            if key == 'completed':
                for phase in legacy:
                    phase.order = order
                    phase.save(update_fields=['order'])
                    order += 1
            if key in kept:
                ProjectPhase.objects.filter(organization=organization, key=key).update(order=order)
            else:
                ProjectPhase.objects.create(organization=organization, key=key, label=label, color=color, order=order)
                summary['phases_added'] += 1
            order += 1

        # Processus principal = les phases du métier (+ anciennes phases encore utilisées) ; il devient le défaut.
        from apps.dashboard.models import ProjectProcess
        main_keys = [p.key for p in ProjectPhase.objects.filter(organization=organization).order_by('order', 'id')]
        main_keys = [k for k in main_keys if k in {key for key, *_ in pack['phases']} or k in kept]
        processes = list(ProjectProcess.objects.filter(organization=organization, is_private=False))
        main = next((p for p in processes if p.name == pack.get('process')), None)
        if main is None and len(processes) == 1 and not Project.objects.filter(process__isnull=False, organization=organization).exists():
            main = processes[0]  # processus créé automatiquement : renommé d'après le métier
        if main is None:
            main = ProjectProcess(organization=organization, order=len(processes))
        main.name, main.phase_keys = pack.get('process') or 'Processus principal', main_keys
        main.save()
        ProjectProcess.objects.filter(organization=organization).exclude(id=main.id).update(is_default=False)
        ProjectProcess.objects.filter(id=main.id).update(is_default=True)
        summary['processes_added'] = 0
        for proc in pack.get('processes', []):
            _, created = ensure_process(organization, proc['name'], proc['phases'], description=proc['description'])
            summary['processes_added'] += int(created)

        for spec in pack['templates']:
            data = {'milestones': spec['milestones']}
            if spec.get('process'):
                data['process'] = spec['process']
            _, created = ProjectTemplate.objects.get_or_create(
                organization=organization, name=spec['name'],
                defaults={'description': spec['description'], 'trade': trade, 'data': data, 'created_by': user},
            )
            summary['templates_added'] += int(created)

        prefs = dict(organization.billing_preferences or {})
        prefs['trade_mentions'] = pack['mentions']
        prefs['units'] = pack['units']
        organization.billing_preferences = prefs
        organization.trade = trade
        organization.save(update_fields=['billing_preferences', 'trade', 'updated_at'])
    return summary
