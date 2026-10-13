# Déploiement de Billio

Mise en production, monitoring et CI/CD. Tout ce qui est marqué **[à fournir]** reste à renseigner.

## 1. Architecture

| Brique | Rôle | Service retenu |
|---|---|---|
| **web** | Le site (gunicorn), conteneur Docker | Hébergeur **[à choisir]** |
| **worker** | Tâches planifiées toutes les 10 min : relances, factures récurrentes, automatisations, sauvegarde quotidienne | Même image, commande `worker` |
| **PostgreSQL** | Base de données | Base managée ou conteneur (VPS) |
| **Stockage objet** | Logos, livrables, pièces jointes, sauvegardes (liens signés, fichiers privés) | S3-compatible (Scaleway Object Storage conseillé) |
| **Emails** | Mot de passe oublié, notifications, emails aux clients | **Resend** |
| **Erreurs** | Alertes sur les plantages, avec le contexte | **Sentry** |
| **Disponibilité** | Vérifie que le site et le worker tournent | Better Stack ou UptimeRobot |
| **CI/CD** | Tests → image Docker → déploiement à chaque push sur `main` | GitHub Actions + GitHub Container Registry |

Fichiers : `Dockerfile`, `docker/entrypoint.sh`, `docker-compose.yml` + `docker/Caddyfile` (VPS),
`.github/workflows/ci-cd.yml`, `config/settings/prod.py`, `env.example`.

## 2. Informations à me fournir

| Élément | Valeur |
|---|---|
| Hébergeur choisi (VPS OVH / Scaleway, ou Scaleway Serverless Containers…) | **[à fournir]** |
| Nom de domaine | **[à fournir]** |
| Adresse d'expédition des emails (ex. `no-reply@billio.fr`) | **[à fournir]** |
| Adresse de dépôt GitHub (ex. `github.com/billio/billio`) | **[à fournir]** |
| Informations légales (raison sociale, forme, capital, adresse, SIREN, RCS, TVA, directeur de publication, emails de contact) | **[à fournir]** |

Les clés secrètes (API, mots de passe) **ne se donnent pas dans une conversation** : elles se saisissent
directement chez l'hébergeur, dans `.env.production` sur le serveur, ou dans les secrets GitHub.

## 3. Comptes à créer et où trouver chaque clé

### Resend (emails)
1. Créer le compte : https://resend.com/signup
2. Ajouter le domaine et copier les enregistrements DNS (SPF, DKIM, MX de retour) chez le registraire : https://resend.com/domains
   → sans cette vérification, les emails partent en spam ou sont refusés.
3. Créer une clé API (permission « Sending access ») : https://resend.com/api-keys → `RESEND_API_KEY`
4. Doc SMTP (Billio l'utilise en SMTP : hôte `smtp.resend.com`, utilisateur `resend`) : https://resend.com/docs/send-with-smtp

### Sentry (erreurs)
1. Créer le compte, de préférence en **région UE** (données en Europe) : https://sentry.io/signup/
2. Créer un projet « Django », copier le DSN → `SENTRY_DSN`
3. Doc : https://docs.sentry.io/platforms/python/integrations/django/
4. Facultatif, pour voir les versions déployées : jeton https://sentry.io/settings/account/api/auth-tokens/ → secret GitHub `SENTRY_AUTH_TOKEN`

### Surveillance de disponibilité (uptime)
Créer **deux** sondes, alerte par email/SMS :
- `https://VOTRE-DOMAINE/healthz/` → le site et la base répondent ;
- `https://VOTRE-DOMAINE/healthz/?worker=1` → le worker a tourné il y a moins de 30 min.

Better Stack : https://betterstack.com/uptime — ou UptimeRobot : https://uptimerobot.com

### Stripe (abonnements Billio)
- Clés API (commencer en **mode test**) : https://dashboard.stripe.com/test/apikeys → `STRIPE_SECRET_KEY`
- Webhook : https://dashboard.stripe.com/test/webhooks → URL `https://VOTRE-DOMAINE/subscriptions/webhooks/stripe/`,
  évènements `checkout.session.completed`, `customer.subscription.created`, `customer.subscription.updated`,
  `customer.subscription.deleted`, `invoice.paid`, `invoice.payment_failed` → secret `STRIPE_WEBHOOK_SECRET`
- Portail client (à enregistrer une fois) : https://dashboard.stripe.com/test/settings/billing/portal
- TVA 20 % : https://dashboard.stripe.com/test/tax-rates → `STRIPE_TAX_RATE_ID` (ou Stripe Tax : https://dashboard.stripe.com/settings/tax)

### Stockage objet (fichiers et sauvegardes)
- Scaleway Object Storage : https://www.scaleway.com/fr/object-storage/ — créer un bucket **privé** en `fr-par`
- Clés d'API : https://console.scaleway.com/iam/api-keys → `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`
- `AWS_S3_ENDPOINT_URL=https://s3.fr-par.scw.cloud`, `AWS_S3_REGION_NAME=fr-par`

### Google (facultatif : connexion Google, Google Drive)
https://console.cloud.google.com/apis/credentials — URI de redirection : `https://VOTRE-DOMAINE/integrations/google/callback/`

### GitHub (code et CI/CD)
- Nouveau dépôt **privé** : https://github.com/new
- Secrets du dépôt (Settings › Secrets and variables › Actions) : https://docs.github.com/actions/security-guides/using-secrets-in-github-actions
- Registre d'images : https://docs.github.com/packages/working-with-a-github-packages-registry/working-with-the-container-registry

## 4. Option A — Serveur VPS (OVH, Scaleway Instances)
Le plus économique, données en France, tout sur une machine. VPS conseillé : 2 vCPU, 4 Go RAM, Ubuntu 24.04.
- OVH VPS : https://www.ovhcloud.com/fr/vps/ — Scaleway Instances : https://www.scaleway.com/fr/instances/

1. Installer Docker : https://docs.docker.com/engine/install/ubuntu/
2. DNS : enregistrement **A** du domaine (et de `www`) vers l'IP du serveur.
3. Sur le serveur :
   ```
   git clone <dépôt> /opt/billio && cd /opt/billio
   cp env.example .env.production   # puis le remplir (DOMAIN, SECRET_KEY, POSTGRES_PASSWORD, RESEND_API_KEY…)
   docker compose --env-file .env.production up -d --build
   docker compose exec web python manage.py createsuperuser
   ```
4. HTTPS : automatique (Caddy obtient le certificat Let's Encrypt au premier accès).
5. Déploiements suivants : automatiques par la CI (secrets `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`).

Sans bucket S3, les fichiers restent sur le volume `media` du serveur : pensez alors aux sauvegardes de la machine.

## 5. Option B — Plateforme managée (Scaleway Serverless Containers + base managée)
Pas de serveur à maintenir ; un peu plus cher.
- Conteneurs : https://www.scaleway.com/fr/serverless-containers/ — PostgreSQL managé : https://www.scaleway.com/fr/database/

1. Base PostgreSQL managée (sauvegardes automatiques incluses) → `DATABASE_URL`.
2. Deux conteneurs depuis l'image `ghcr.io/<compte>/<dépôt>:latest` :
   - **web** : commande par défaut, port 8000, au moins 1 instance toujours active ;
   - **worker** : commande `worker`, 1 instance, sans port public.
3. Mêmes variables d'environnement sur les deux (voir `env.example`).
4. Domaine personnalisé dans la console, puis CNAME chez le registraire.
5. CI : secret `DEPLOY_HOOK_URL` si l'hébergeur fournit un lien de redéploiement, sinon redéploiement depuis la console.

## 6. CI/CD (GitHub Actions)
À chaque push ou pull request :
1. tests (`manage.py test apps`) et migrations à jour ;
2. contrôle de la configuration de production (`check --deploy`) ;
3. construction de l'image Docker.

Sur `main`, en plus : publication de l'image sur `ghcr.io`, déploiement (VPS par SSH ou hook),
version envoyée à Sentry, puis vérification de `/healthz/` (variable de dépôt `SITE_URL`).

Protéger la branche `main` (merge seulement si la CI passe) : Settings › Branches.

## 7. Monitoring au quotidien
- **Erreurs** : Sentry envoie un email à la première occurrence ; pas d'emails ni d'IP des utilisateurs transmis (RGPD).
- **Disponibilité** : les deux sondes `/healthz/` (site + worker).
- **Journaux** : sortie standard des conteneurs (`docker compose logs -f web worker` sur VPS, console de l'hébergeur sinon).
- **Paiements** : tableau de bord Stripe ; un paiement d'abonnement refusé crée aussi une notification dans Billio.

## 8. Sauvegardes et restauration
- Le worker sauvegarde la base chaque nuit (vers 3 h) dans `backups/` du stockage, 14 jours gardés
  (`BACKUP_DAILY=1`, `BACKUP_RETENTION_DAYS`). Sauvegarde à la main : `python manage.py backup_database`.
- Restauration : `gunzip -c billio-AAAAMMJJ-HHMM.sql.gz | psql "$DATABASE_URL"`
- **Tester une restauration une fois avant l'ouverture.**

## 9. Première mise en ligne — liste de contrôle
- [ ] Domaine pointé, HTTPS actif (cadenas)
- [ ] Domaine vérifié dans Resend ; test « Mot de passe oublié » reçu (pas en spam)
- [ ] `createsuperuser` fait ; admin accessible à `ADMIN_URL` seulement
- [ ] `python manage.py stripe_sync_plans` ; webhook Stripe déclaré ; portail client enregistré
- [ ] Abonnement test (carte `4242 4242 4242 4242`) : le forfait s'active, la résiliation fonctionne
- [ ] Variables `LEGAL_*` remplies (plus de « À compléter » sur `/mentions-legales/`)
- [ ] Sentry reçoit une erreur de test ; les deux sondes uptime sont vertes
- [ ] Une sauvegarde apparaît dans `backups/` le lendemain ; restauration testée
- [ ] Passage de Stripe en mode réel (nouvelles clés + nouveau webhook)

## 10. Commandes utiles
```
python manage.py run_automations            # un passage des tâches planifiées
python manage.py run_automations --loop 600 # worker en continu
python manage.py backup_database            # sauvegarde immédiate
python manage.py stripe_sync_plans          # produits/prix Stripe des forfaits
python manage.py check --deploy             # contrôle de la configuration de production
```
