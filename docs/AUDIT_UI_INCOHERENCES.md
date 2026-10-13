# Audit UI — incohérences & interactions incomplètes (Billio)

> Passage transversal des templates principaux (hors `.venv`).  
> Dernière mise à jour : revue code statique.

---

## 1. Dashboard (`templates/dashboard/`)

| Élément | Problème |
|---------|----------|
| **Notifications** — « Voir toutes les notifications » | `href="#"` — pas de page liste notifications. |
| **Menu profil** — « Community », « Help center » | `href="#"` — pas de destination. |
| **`index.html`** — « Voir le tableau de bord » (KPI) | `href="#"` — redondant sur la page d’accueil dashboard. |
| **`index.html`** — « Voir » (Actions à faire) | `href="#"` — incomplet. |
| **`index.html`** — « Justifier » (non justifiées) | `href="#"` — pas de flux métier branché. |
| **`index.html`** — Bloc « Average salary » / « Employees » | Texte **en anglais** alors que le reste est en français ; `+87` statique (non lié aux données). |
| **`index.html`** — `console.log` nombreux | Bruit en prod ; à retirer ou garder derrière `DEBUG`. |

---

## 2. Factures

| Élément | Problème |
|---------|----------|
| **`_invoice_list.html`** — Télécharger PDF | `downloadPDF()` ne fait qu’un `console.log` — **pas de PDF** (modèle prévoit placeholder côté backend). |
| **`_invoice_list.html`** — Envoyer / Dupliquer | Appels HTMX vers **`/api/invoices/{id}/send/`** etc. — **URLs incorrectes** ; les vues Django sont sous **`/invoices/<uuid>/send/`** et **`duplicate/`** (POST). |
| **`list.html`** — Boutons Table / Board / List | Non branchés (style seulement, pas de changement de vue réel). |
| **`create.html`** | `console.warn` sur JSON / preview — acceptable pour debug. |

---

## 3. Paramètres compte (`templates/accounts/settings.html`)

| Élément | Problème |
|---------|----------|
| **Notifications email** (4 lignes) | Checkboxes **toujours cochées** / pas de `name` ni sauvegarde — **factice**. |
| **Langue / fuseau / devise** | UI présente mais **hors** du formulaire de sauvegarde paiement — **non persistées** (sauf si autre mécanisme absent ici). |
| **Sécurité** — 2FA, MDP, sessions | Boutons sans `type` explicite / **sans action** (pas de vues). |
| **Données** — Télécharger / Supprimer compte | Idem — **non implémentés**. |
| **Bas de page** — Annuler / Sauvegarder | **Hors formulaire** — ne sauvegardent pas les préférences générales (incohérent avec le bloc paiement qui, lui, POST). |

---

## 4. Landing (`templates/landing/home.html`)

| Élément | Problème |
|---------|----------|
| Pied de page — À propos, Blog, Contact, Confidentialité, Conditions, Sécurité | Tous en **`href="#"`**. |
| Réseaux sociaux (bas de page) | **`href="#"`**. |

---

## 5. Auth

| Élément | Problème |
|---------|----------|
| **`login.html`** — lien (ex. mot de passe oublié selon bloc) | `href="#"` si présent. |
| **`register.html`** — CGU / confidentialité | `href="#"` — devrait pointer vers pages légales ou `/legal/`. |

---

## 6. Organisations

| Élément | Problème |
|---------|----------|
| **`organization_card.html`** — « Voir », « Gérer » | **`href="#"`** — pas de vue **détail** org dans `urls.py` (seulement `list`, `create`). Les liens ne peuvent pas cibler une fiche sans nouvelle route. |

---

## 7. Dev-tools (`templates/dev-tools.html`)

| Élément | Problème |
|---------|----------|
| Liens documentation / bug | `href="#"`. |

---

## 8. Backend (rappels)

| Fichier | Problème |
|---------|----------|
| **`apps/invoices/models.py`** | TODO PDF réel (WeasyPrint / ReportLab), envoi email, Stripe. |
| **`views.py`** | Quelques `pass` dans handlers d’erreur. |

---

## 9. Cohérence visuelle (rapide)

- Mélange **jaune** (`bg-yellow-400`) vs **`btn-secondary-yellow`** vs **`btn-primary-black`** sur la même page (ex. paramètres sécurité vs reste du dashboard).
- **Demo** (`demo.html`) : style **indigo** pour boutons articles ; **create** : **jaune/noir** Billio — normal pour démo mais à savoir pour homogénéisation future.

---

## Pistes de correction prioritaires

1. ~~**Factures liste** : corriger URLs **send** / **duplicate**~~ → **Fait** : `fetch` POST vers `/invoices/<uuid>/send/` et `duplicate/` ; entrée menu **Aperçu** ouvre `invoice-preview` (nouvel onglet). Le **PDF binaire** reste à implémenter côté modèle.  
2. **Paramètres** : retirer ou désactiver (disabled + tooltip) les contrôles non branchés ; ou brancher sur modèles/API.  
3. **Dashboard** : remplacer `href="#"` par vraies routes ou supprimer les liens ; traduire le bloc « Average salary ».  
4. **Landing / auth** : pages légales minimales ou ancres `#cgu` sur une même page statique.  
5. **Organisations** : ajouter `organization-detail` / `organization-update` ou lier « Voir » vers liste filtrée.
