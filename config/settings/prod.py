"""
Réglages de production. Tout vient de variables d'environnement (voir env.example et DEPLOIEMENT.md).

Processus : `web` (gunicorn) et `worker` (python manage.py run_automations --loop 600).
"""
import dj_database_url
from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403
from .base import LOGGING, MIDDLEWARE, SITE_URL, os

DEBUG = False

SECRET_KEY = os.getenv('SECRET_KEY', '')
if len(SECRET_KEY) < 40 or SECRET_KEY.startswith('django-insecure'):
    raise ImproperlyConfigured('SECRET_KEY manquante ou trop courte (50 caractères aléatoires conseillés).')

ALLOWED_HOSTS = [h.strip() for h in os.getenv('ALLOWED_HOSTS', '').split(',') if h.strip()]
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.getenv('CSRF_TRUSTED_ORIGINS', SITE_URL).split(',') if o.strip()]

# ---------- Base de données (PostgreSQL) ----------
DATABASES = {
    'default': dj_database_url.config(
        env='DATABASE_URL', conn_max_age=600, conn_health_checks=True,
        ssl_require=os.getenv('DATABASE_SSL', '1') == '1',
    )
}

# Cache partagé entre les processus (limitation des tentatives de connexion, quotas) :
# Redis si REDIS_URL est fourni, sinon une table de la base (créée par `createcachetable`).
if os.getenv('REDIS_URL'):
    CACHES = {'default': {'BACKEND': 'django_redis.cache.RedisCache', 'LOCATION': os.getenv('REDIS_URL')}}
else:
    CACHES = {'default': {'BACKEND': 'django.core.cache.backends.db.DatabaseCache', 'LOCATION': 'billio_cache'}}

# ---------- HTTPS et en-têtes de sécurité ----------
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')  # derrière le proxy de l'hébergeur
SECURE_SSL_REDIRECT = True
SECURE_REDIRECT_EXEMPT = [r'^healthz/$']
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = int(os.getenv('SECURE_HSTS_SECONDS', '31536000'))
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'
X_FRAME_OPTIONS = 'DENY'

CORS_ALLOWED_ORIGINS = [o.strip() for o in os.getenv('CORS_ALLOWED_ORIGINS', '').split(',') if o.strip()]

# Admin Django à une adresse non devinable (ex. ADMIN_URL=gestion-7f3k2/).
ADMIN_URL = os.getenv('ADMIN_URL', 'admin/')

# ---------- Fichiers ----------
MIDDLEWARE = list(MIDDLEWARE)
MIDDLEWARE.insert(MIDDLEWARE.index('django.middleware.security.SecurityMiddleware') + 1,
                  'whitenoise.middleware.WhiteNoiseMiddleware')

# Fichiers déposés (logos, livrables, pièces jointes) : stockage objet S3-compatible
# (Scaleway Object Storage, OVH, Cloudflare R2, AWS…) si un bucket est configuré, sinon disque local
# (à monter sur un volume persistant).
_media_storage = {'BACKEND': 'django.core.files.storage.FileSystemStorage'}
if os.getenv('AWS_STORAGE_BUCKET_NAME'):
    _media_storage = {'BACKEND': 'storages.backends.s3.S3Storage'}
    AWS_STORAGE_BUCKET_NAME = os.getenv('AWS_STORAGE_BUCKET_NAME')
    AWS_S3_ENDPOINT_URL = os.getenv('AWS_S3_ENDPOINT_URL') or None
    AWS_S3_REGION_NAME = os.getenv('AWS_S3_REGION_NAME') or None
    AWS_DEFAULT_ACL = None            # fichiers privés…
    AWS_QUERYSTRING_AUTH = True       # …servis par des liens signés temporaires
    AWS_QUERYSTRING_EXPIRE = 3600
    AWS_S3_FILE_OVERWRITE = False
STORAGES = {
    'default': _media_storage,
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
}
MEDIA_ROOT = os.getenv('MEDIA_ROOT', '/data/media')

# ---------- Emails (Resend) ----------
# Resend en SMTP : utilisateur « resend », mot de passe = clé API. Le domaine de DEFAULT_FROM_EMAIL
# doit être vérifié dans Resend (enregistrements DNS SPF / DKIM).
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.getenv('EMAIL_HOST', 'smtp.resend.com')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '587'))
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', 'resend')
EMAIL_HOST_PASSWORD = os.getenv('RESEND_API_KEY') or os.getenv('EMAIL_HOST_PASSWORD', '')
EMAIL_TIMEOUT = 20
SERVER_EMAIL = os.getenv('SERVER_EMAIL', os.getenv('DEFAULT_FROM_EMAIL', 'no-reply@billio.fr'))

# ---------- Journaux : sortie standard (lue par l'hébergeur) ----------
LOGGING['handlers'].pop('file', None)
LOGGING['root']['handlers'] = ['console']
LOGGING['loggers']['django']['handlers'] = ['console']
LOGGING['handlers']['console']['formatter'] = 'verbose'

# ---------- Monitoring des erreurs (Sentry) ----------
if os.getenv('SENTRY_DSN'):
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration

    sentry_sdk.init(
        dsn=os.getenv('SENTRY_DSN'),
        integrations=[DjangoIntegration(), LoggingIntegration(event_level='ERROR')],
        environment=os.getenv('SENTRY_ENVIRONMENT', 'production'),
        release=os.getenv('RELEASE', '') or None,
        traces_sample_rate=float(os.getenv('SENTRY_TRACES_SAMPLE_RATE', '0.1')),
        send_default_pii=False,  # pas d'emails ni d'IP envoyés à Sentry (RGPD)
    )
