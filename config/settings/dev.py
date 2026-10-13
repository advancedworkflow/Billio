"""
Development settings for billio project.
"""
from .base import *

DEBUG = True

ALLOWED_HOSTS = ['localhost', '127.0.0.1', '0.0.0.0', '.localhost', '192.168.1.195', 'testserver']

# Force HTTP only in development
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_HSTS_SECONDS = 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False

# Disable APPEND_SLASH to prevent 301 redirects
APPEND_SLASH = False

# Force HTTP scheme
SECURE_PROXY_SSL_HEADER = None

# Development database (SQLite for simplicity)
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# Email backend for development
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# CORS for development
CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]

# Django Debug Toolbar (if installed)
# Temporairement désactivé pour éviter les erreurs de dépendances
# if DEBUG:
#     INSTALLED_APPS += [
#         'debug_toolbar',
#     ]
#
#     MIDDLEWARE += [
#         'debug_toolbar.middleware.DebugToolbarMiddleware',
#         'config.middleware.HTTPSRedirectMiddleware',
#     ]
#
#     INTERNAL_IPS = [
#         '127.0.0.1',
#         'localhost',
#         '0.0.0.0',
#     ]
#
#     # Django Debug Toolbar configuration
#     DEBUG_TOOLBAR_CONFIG = {
#         'SHOW_COLLAPSED': True,
#         'SHOW_TOOLBAR_CALLBACK': lambda request: True,
#     }

# Django Extensions runserver_plus configuration for HTTPS
RUNSERVERPLUS_SERVER_ADDRESS_PORT = '127.0.0.1:8000'

# SSL certificate for development (django-extensions will generate self-signed cert)
# RUNSERVERPLUS_POLLER_RELOADER_INTERVAL = 1
