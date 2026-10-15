"""
URL configuration for billio project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.shortcuts import render
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView

def dev_tools_view(request):
    """Page de documentation des outils de développement."""
    return render(request, 'dev-tools.html')

urlpatterns = [
    path(getattr(settings, 'ADMIN_URL', 'admin/'), admin.site.urls),

    # API documentation (schema + ReDoc)
    path('api/schema/', SpectacularAPIView.as_view(), name='api-schema'),
    path('api/', SpectacularRedocView.as_view(url_name='api-schema'), name='api-docs'),

    # Landing page (public)
    path('', include('apps.landing.urls')),

    # Authentification
    path('accounts/', include('apps.accounts.urls')),

    # Langue de l'interface (fr / en / de / es)
    path('i18n/', include('apps.translations.urls')),

    # App URLs (protected)
    path('organizations/', include('apps.organizations.urls')),
    path('clients/', include('apps.clients.urls')),
    path('invoices/', include('apps.invoices.urls')),
    path('payments/', include('apps.payments.urls')),
    path('integrations/', include('apps.integrations.urls')),
    path('subscriptions/', include('apps.subscriptions.urls')),
    path('dashboard/', include('apps.dashboard.urls')),
    path('templates/', include('apps.templates_app.urls')),
    path('documents/', include('apps.documents.urls')),
    path('staff/', include('apps.staff.urls')),
]

# Outils de développement : jamais exposés en production.
if settings.DEBUG:
    urlpatterns.append(path('dev-tools/', dev_tools_view, name='dev-tools'))

# Fichiers envoyés (logos, images de documents…) servis par Django en développement
# uniquement ; en production, c'est le serveur web / le stockage qui s'en charge.
if settings.DEBUG:
    from django.conf.urls.static import static
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Django Debug Toolbar URLs (only in DEBUG mode)
# Temporairement désactivé
# if settings.DEBUG:
#     import debug_toolbar
#     urlpatterns += [
#         path('__debug__/', include(debug_toolbar.urls)),
#     ]
