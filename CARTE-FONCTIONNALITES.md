# Carte des fonctionnalités Billio

État au 12 octobre 2026 (audit, phases 1 et 2 terminées, 82 tests au vert).

**Statuts** : ✅ disponible · 🆕 ajouté ou corrigé pendant l'audit · 🟠 partiel · ⛔ à faire (avec sa phase)

## Parcours client

Rendez-vous ✅ → Devis ✅ → Signature 🆕 → Acompte 🆕 → Projet ✅ → Temps 🆕 → Facture 🆕 → Paiement ✅ → Relance ✅ → Comptabilité 🟠

## 1. Ventes & facturation

| Fonctionnalité | Statut | Détail |
|---|---|---|
| Clients et contacts | ✅ | Fiche client, contacts, encours, historique |
| Catalogue de prestations | ✅ | Produits et services, TVA, coût et marge |
| Devis | ✅ | Remises par ligne, pièces jointes, aperçu, envoi |
| Signature en ligne du devis | 🆕 | Bon pour accord signé par le client |
| Échéancier et acomptes | 🆕 | TVA ventilée par taux, la facture finale déduit les acomptes |
| Factures conformes | ✅ | Numérotation continue, verrouillage après émission |
| Avoirs | ✅ | Totaux ou partiels, séquence AV- |
| Factures récurrentes | ✅ | Mensuelles, trimestrielles, annuelles |
| Situations BTP | ✅ | Avancement cumulé, retenue de garantie |
| Factur-X (EN 16931) | ✅ | PDF/A-3 avec XML validé |
| Réception des e-factures (PDP) | ⛔ | Phase 3 |
| Dépenses et factures d'achat | 🟠 | Le type existe, pas d'écran (phase 3) |
| Multi-devises | 🟠 | Choix de devise sans taux de change (phase 5) |

## 2. Encaissement

| Fonctionnalité | Statut | Détail |
|---|---|---|
| Paiement en ligne Stripe | ✅ | Clés de l'organisation, webhook signé |
| Paiements manuels | 🆕 | Virement, chèque, espèces… |
| Reçus de paiement | ✅ | Page publique et PDF |
| Relances automatiques | ✅ | J+7, J+14, J+30 |
| Tableau des paiements | 🆕 | Encaissements, prévisions, paiements en échec |
| Rapprochement bancaire | ⛔ | Phase 3 |
| Synchronisation bancaire | ⛔ | Qonto, Bridge… (phase 5) |

## 3. Projets & production

| Fonctionnalité | Statut | Détail |
|---|---|---|
| Tableau des projets | ✅ | Kanban par phases |
| Jalons, tâches, livrables | ✅ | Fichiers, statuts, commentaires |
| Timeline et Gantt | ✅ | Planning et échéances |
| Réunions | ✅ | |
| Modèles de projet | ✅ | |
| Chrono widget | 🆕 | Barre du haut, onglet, fenêtre au premier plan |
| Facturer le temps passé | ✅ | Une ligne par tâche, jamais facturé deux fois |

## 4. Relation client

| Fonctionnalité | Statut | Détail |
|---|---|---|
| Portail client | ✅ | Projets, documents, factures |
| Validation des livrables | ✅ | Approuver ou demander des modifications |
| Questionnaires de cadrage | ✅ | |
| Prise de rendez-vous en ligne | ✅ | Page publique, créneaux, annulation |
| Documents | ✅ | Propositions, contrats, bienvenue |
| Emails au client | ✅ | Via le SMTP de l'organisation |

## 5. Automatisation & intégrations

| Fonctionnalité | Statut | Détail |
|---|---|---|
| Workflows | ✅ | Déclencheurs, conditions, attentes, actions |
| Webhook entrant | ✅ | Formulaire de site → client, tâche, message |
| ~60 intégrations | ✅ | Slack, Telegram, Google Drive, Notion, Trello… |
| API REST | 🆕 | Jeton dans les paramètres |
| Exécution planifiée | 🟠 | À brancher sur un cron (phase 4) |

## 6. Personnalisation

| Fonctionnalité | Statut | Détail |
|---|---|---|
| Éditeur de modèles de facture | ✅ | |
| Marketplace de modèles | 🆕 | Page détail réparée |
| Packs métier | ✅ | Phases, modèles, mentions selon le métier |
| Image de marque | ✅ | Logo et couleurs |
| 4 langues | ✅ | fr, en, de, es |

## 7. Pilotage

| Fonctionnalité | Statut | Détail |
|---|---|---|
| Tableau de bord | ✅ | Indicateurs, trésorerie, actions à faire |
| Statistiques et rapports | ✅ | |
| Recherche rapide ⌘K | ✅ | |
| Export CSV | ✅ | |
| Export FEC | ⛔ | Phase 3 |
| Assistant IA | 🟠 | Raccourcis seulement (phase 5) |

## 8. Compte & sécurité

| Fonctionnalité | Statut | Détail |
|---|---|---|
| Inscription avec métier | ✅ | |
| Connexion Google | ✅ | Nécessite les clés Google |
| Mot de passe oublié | 🆕 | |
| Organisations, rôles, invitations | ✅ | Propriétaire, admin, membre, lecteur |
| Vérification de l'email | ⛔ | Phase 3 |
| Limite des tentatives de connexion | ⛔ | Phase 3 |
| Double authentification | ⛔ | Phase 3 |
| RGPD : export et suppression | ⛔ | Phase 3 |

## 9. Lancement & exploitation

| Fonctionnalité | Statut | Détail |
|---|---|---|
| Site vitrine + démo interactive | 🆕 | |
| Pages légales | 🆕 | Infos société à compléter (`LEGAL_*`) |
| Page tarifs | 🆕 | Générée depuis la grille des forfaits |
| Abonnement Billio | 🆕 | Stripe Checkout, changement au prorata, résiliation, portail de paiement, délai de grâce 7 jours |
| Limites par forfait | 🆕 | Quotas et options appliqués partout (voir grille ci-dessous) |
| Suivi des erreurs (Sentry) | ⛔ | Phase 4 |
| Sauvegardes automatiques | ⛔ | Phase 4 |
| Application mobile (PWA) | ⛔ | Phase 5 |

---

## Grille des forfaits (en place)

| | Free | Starter | Pro | Business | Agency |
|---|---|---|---|---|---|
| Prix HT / mois | 0 € | 9 € | 19 € | 39 € | 79 € |
| Factures et devis / mois | 10 | 50 | Illimités | Illimités | Illimités |
| Clients actifs | 15 | 100 | 300 | 1 000 | Illimités |
| Projets | 3 | 10 | 30 | 100 | Illimités |
| Utilisateurs | 1 | 1 | 1 | 5 | 15 |
| Stockage | 500 Mo | 5 Go | 20 Go | 100 Go | 250 Go |
| Intégrations | 2 | 5 | 10 | 25 | 50 |
| Automatisations actives | 1 | 5 | 15 | 50 | 150 |
| Relances automatiques, signature des devis, rendez-vous | — | ✓ | ✓ | ✓ | ✓ |
| Portail client | Basique | Complet | Complet | Complet | Complet |
| Suivi du temps | — | Basique | Complet | Complet | Complet |
| Facturation du temps, Factur-X | — | — | ✓ | ✓ | ✓ |
| API, webhooks entrants | — | — | — | ✓ | ✓ |
| Plusieurs organisations | — | — | — | — | ✓ |

Prix, limites et options se modifient dans l'admin (Abonnements › Forfaits).

## Pour construire les forfaits

Ce qui peut servir de **limite chiffrée** (facile à faire évoluer d'un forfait à l'autre) :

- nombre de factures / devis par mois
- nombre de clients actifs
- nombre d'utilisateurs (membres de l'organisation)
- nombre de projets actifs
- nombre d'automatisations (workflows) actives
- nombre d'intégrations connectées
- stockage des fichiers (livrables, documents)

Ce qui peut être **réservé** aux forfaits supérieurs (activé / désactivé) :

- paiement en ligne Stripe et relances automatiques
- signature en ligne des devis
- portail client et validation des livrables
- prise de rendez-vous en ligne
- suivi du temps et facturation du temps passé
- situations BTP / retenue de garantie
- facture récurrente
- Factur-X
- workflows, webhook entrant, API
- modèles personnalisés et marketplace
- plusieurs organisations
- suppression de la mention « Envoyé avec Billio » (à créer)

À garder dans **tous** les forfaits (obligations légales ou base du produit) : factures conformes, avoirs, numérotation, mentions légales, export des données.
