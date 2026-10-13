# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Billio is a Django 4.2 SaaS invoicing platform for the French market (`LANGUAGE_CODE = 'fr-fr'`, `TIME_ZONE = 'Europe/Paris'`). Users belong to an `Organization` (the tenant), create invoices/quotes for their `Client`s, take Stripe payments, and get dashboard analytics.

## Commands

### Environment

A virtualenv already exists at `.venv`. Activate it (`.venv\Scripts\activate` on Windows, `source .venv/bin/activate` elsewhere), then:

```
pip install -r requirements-dev.txt   # adds testing/linting on top of requirements.txt
```

### Running the dev server

`manage.py` hardcodes `DJANGO_SETTINGS_MODULE=config.settings.dev` as its default, so no env var is required locally:

```
python manage.py runserver 127.0.0.1:8000
```

- The dev DB is SQLite (`db.sqlite3`). `config/settings/base.py` defaults to Postgres, but `config/settings/dev.py` overrides `DATABASES` to SQLite — don't expect a local Postgres to be involved unless you're intentionally testing prod-like settings.
- `dev.py` disables `SECURE_SSL_REDIRECT`. **Always browse via `http://`, never `https://`**, on localhost — the Django dev server can't terminate SSL and will error. If you ever hit `ERR_SSL_PROTOCOL_ERROR`, restart with `python manage.py runserver --noreload --insecure 127.0.0.1:8000`.
- If a `runserver` process has been running for a while and static file (CSS/JS) edits stop showing up even after a hard browser refresh, restart the process — don't assume the edit didn't save. Template edits reload live; this staleness has only been observed with static assets.
- `README.md` references helper scripts (`start_simple.py`, `start_dev.py`, `check_setup.py`) that do not exist in this repo — use `manage.py` directly.
- `APPEND_SLASH = False` in `dev.py`, so don't rely on Django auto-redirecting `/foo` to `/foo/`.

### Database

```
python manage.py migrate
python manage.py createsuperuser
```

### Tests

A first suite exists in `apps/invoices/tests/` (see « Tests » below). `pytest`/`pytest-django` are referenced by `pyproject.toml` but not installed in `.venv`; the configured entry points once installed are:

```
pytest
pytest apps/<app>/tests/test_x.py
python manage.py test
```

### Code quality

Config lives in `pyproject.toml` (line length 88, `known_first_party = ["apps", "config"]`):

```
black .
isort .
flake8 .
mypy .
bandit -r .
```

`.pre-commit-config.yaml` runs the same set (plus eslint on `*.js`/`*.ts`) automatically if `pre-commit install` has been run — it's optional, not enforced by default.

### Tâches planifiées

Celery is scaffolded (`config/celery.py`) but **not wired up**. Scheduled work runs instead through the idempotent `python manage.py run_automations` command (`--loop SECONDS` for the production worker) (and opportunistically on each dashboard home load): overdue invoice/quote/task sweeps, invoice reminders J+7/J+14/J+30 and recurring invoices (`apps/invoices/scheduled.py`), "Date du calendrier" workflow triggers (`apps/dashboard/automation_calendar.py`) and elapsed workflow waits. In production, schedule it every 5–15 minutes (cron, or `scripts/run_automations.cmd` with the Windows Task Scheduler).

### Production, monitoring, CI/CD

See `DEPLOIEMENT.md`. Docker image (`Dockerfile`, `docker/entrypoint.sh`: `web` = migrate + gunicorn, `worker` = `run_automations --loop 600` + nightly `backup_database`), `docker-compose.yml` + Caddy for a VPS, `.github/workflows/ci-cd.yml` (tests, `check --deploy`, image to GHCR, deploy). `config/settings/prod.py` reads everything from env vars (`env.example`): PostgreSQL via `DATABASE_URL`, S3-compatible media if `AWS_STORAGE_BUCKET_NAME`, Resend SMTP (`RESEND_API_KEY`), Sentry (`SENTRY_DSN`), `ADMIN_URL`. `GET /healthz/` (and `?worker=1`) is answered by `config.health.HealthCheckMiddleware` before HTTPS/host checks. `/dev-tools/` only exists when `DEBUG`. Login attempts are throttled in `apps/accounts/throttle.py` (cache-based).

### Plans (forfaits)

`apps/subscriptions`: plans with JSON limits/features editable in the admin, one `Subscription` per account owner synced from Stripe (platform keys, distinct from organizations' own Stripe). Gate features with `require_feature` / `require_quota` from `apps/subscriptions/entitlements.py`; checks only apply during logged-in requests (`EntitlementsMiddleware`), never to public pages or scheduled jobs. Tests that exercise paid features call `apps.subscriptions.testing.give_plan(user, code)`.

### Tests

`python manage.py test apps` (Django test runner; pytest is not installed in `.venv`). Covers legal numbering, invoice locking, credit notes, Stripe Checkout/webhook and the billing schedule.

### Interface multilingue (fr / en / de / es)

The UI is written in French directly in templates, JS and views (no `{% translate %}` tags). `apps/translations` translates it at render time:

- `LanguageMiddleware` reads the `billio_lang` cookie (default `fr`, set via `/i18n/set/<lang>/`, see `templates/components/language_switcher.html`) and activates Django's locale.
- `HtmlTranslationMiddleware` translates text nodes and UI attributes (`placeholder`, `title`, `aria-label`, `data-tip`…) of HTML responses using `apps/translations/catalog/<lang>.json` (`{"French source": "translation"}`, variable parts written `{}` or `{0}`), then injects `static/js/i18n.js`, which translates text created later by JavaScript/Alpine with the same catalog.
- Anything inside `translate="no"` (document canvas, invoice previews, portal documents) is never translated: user/document content stays in its own language. Add `translate="no"` to any new container that displays user content.
- New UI strings: write them in French as usual, then run `python manage.py i18n_extract --missing en` (same for `de`, `es`) and add the translations to the catalogs. Keep each sentence in a single text node — a sentence split by `{% if %}` or inline tags is extracted as separate fragments.

## Architecture

### Apps (`apps/`)

Every local app under `apps/` mixes two audiences in one `urls.py`:

- A DRF API under `<app>/api/...` (`DefaultRouter` + `ViewSet`s). Default auth is session or token; default permission is `IsAuthenticated` (see `REST_FRAMEWORK` in `config/settings/base.py`).
- Server-rendered HTML views (mostly function-based, some HTMX-driven, some Alpine.js-enhanced) for the pages users actually see.

App responsibilities:

- **`landing`** — public marketing site (`templates/landing/home.html`), no models.
- **`accounts`** — custom `User` (`AUTH_USER_MODEL = 'accounts.User'`, email as `USERNAME_FIELD`) + `UserProfile`. Handles both classic login/register and Google OAuth (`GoogleLoginView`).
- **`organizations`** — `Organization` (the tenant) + `OrganizationMember` (roles: owner/admin/member/viewer, with per-permission booleans). Also holds branding (logo/colors), invoice numbering state, and bank/payment details that get printed on invoice PDFs.
- **`clients`** — `Client` + `ClientContact`, scoped to an organization.
- **`invoices`** — the core domain. `Invoice` (UUID pk, `sale`/`purchase` type, status lifecycle `draft → sent → viewed → paid/overdue/cancelled`), `InvoiceItem`, `Quote`, `Tax`. Also serves **public, unauthenticated** invoice-payment pages (`public/<uuid>/pay/`, `.../receipt/`) since the person paying an invoice isn't a Billio account holder. Legal rules enforced in the model: numbering is continuous **per organization** (drafts carry a provisional `BROUILLON-…` number; the final one is assigned when the invoice leaves `draft`), issued sale invoices are locked (`Invoice.is_locked`; corrections go through credit notes, `invoice_type='credit_note'`, own `AV-` sequence) and the amount due is `Invoice.amount_due()` (payments and issued credit notes deducted). Online payment is Stripe Checkout with the organization's own keys (Intégrations › Stripe, `apps/payments/stripe_checkout.py`): an invoice/milestone becomes paid only once Stripe confirms it (server-side session read or signed webhook).
- **`payments`** — `PaymentMethod`, `Payment`, `Transaction` (Stripe integration).
- **`subscriptions`** — `Plan`, `Subscription`, `InvoiceLimit`: Billio's own SaaS billing tiers for its users, distinct from the invoices those users send to their clients.
- **`dashboard`** — `DashboardMetric`, `Report`, `Notification`, `ActivityLog` for the authenticated app shell. Also projects (phases, milestones, tasks, deliverables, meetings), the automation engine, client notifications (`client_notifications.py`), project templates (`ProjectTemplate`, `project_templates.py`), time tracking (`TimeEntry`, `time_views.py`) and public online booking (`Appointment`, `booking.py`, `/dashboard/book/<token>/`).
- **`integrations`** — connectors catalog (`providers.py` + `catalog.py`: config form, guide, connection test per tool; outbound calls only to whitelisted hosts via `providers.http`). Automations use connected tools through `messaging.py` (action « Envoyer un message ») and `app_actions.py` (action « Envoyer vers une app »: declare an operation in `APP_ACTIONS` and the board, graph validation and engine pick it up). Inbound: trigger « Webhook entrant » (`apps/dashboard/automation_webhooks.py`, secret URL per workflow, payload flattened into `{{variables}}`).
- **Trade packs** — `apps/organizations/trade_packs.py`: per-trade phases, project templates, legal notices and units, applied at signup (trade is asked in the register form, which also creates the organization) or from Settings › Métier.
- **E-invoicing** — `apps/invoices/facturx.py` builds Factur-X / EN 16931 CII XML (validated against the official XSD with the `factur-x` library; schematron needs a Saxon server, `FACTURX_SAXON_SERVER`) and embeds it in a PDF/A-3. BTP progress invoices and retention: `Quote.create_situation_invoice`.
- **`templates_app`** — `InvoiceTemplate` plus a template marketplace (`MarketplaceTemplate`, `OrganizationTemplate`, `TemplatePurchase`, `TemplateReview`).

Cross-app foreign keys use string references (e.g. `'organizations.Organization'`, `'clients.Client'`) rather than imports, so apps stay loosely coupled.

### Frontend — CDN-based, no build step

Every template pulls Tailwind, fonts, and JS libraries straight from CDNs (`cdn.tailwindcss.com`; `unpkg.com` for Alpine.js and Lucide icons; Google Fonts) instead of going through a bundler. `CSP_SCRIPT_SRC` / `CSP_STYLE_SRC` / `CSP_FONT_SRC` in `config/settings/security.py` explicitly whitelist these hosts — adding a new CDN dependency means updating the CSP there too, or the browser will silently block it once CSP is enforced.

- `static/css/landing.css` + `static/css/landing-motion.css` are the landing page's design system: CSS custom properties on `:root` (`--billio-primary`, `--billio-cta`, `--billio-gradient*`, `--billio-border`, etc.) define the brand palette, and component classes (`.bento-item`, `.pricing-card-premium`, `.landing-btn-primary`, `.schema`, ...) are hand-written rather than Tailwind-generated. `static/js/landing.js` drives scroll-reveal (`IntersectionObserver` toggling `.reveal`/`.reveal-stagger`/`[data-stagger]`/`.is-visible` classes), animated counters (`[data-count]`), and interactive bits like the product-showcase tabs and the "workflow schema" hover states.
- `static/css/app.css` / `dashboard-premium.css` + `static/js/app.js` / `dashboard.js` / `charts.js` are the authenticated dashboard shell — they reuse the same `--billio-*` variables (defined again in `app.css`) so the public and authenticated halves of the product stay visually consistent.
- `templates/auth/login.html` and `templates/auth/register.html` are standalone documents (they don't `{% extends %}` a base template), styled directly against the `--billio-*` variables. Alpine.js handles the password show/hide toggle and the live password-requirements popover.
- `templates/components/` holds a handful of reusable includes (`page_header.html`, `client_card.html`, `organization_card.html`, `invoice_editor_icons.html`).
- Static assets are cache-busted manually via a `?v=X.Y` query string on `<link>`/`<script>` tags in templates (e.g. `landing.css?v=2.0`) — bump it to force browsers that already loaded the old file to fetch the new one.
