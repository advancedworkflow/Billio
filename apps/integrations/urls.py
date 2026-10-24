from django.urls import path, include
from rest_framework.routers import DefaultRouter

from . import plugin_views, views

app_name = 'integrations'

router = DefaultRouter()
router.register(r'connectors', views.ConnectorViewSet, basename='connector')
router.register(r'connections', views.ConnectionInstanceViewSet, basename='connection')

urlpatterns = [
    # HTML views
    path('', views.integrations_page, name='integrations-page'),
    path('connect/<slug:connector_key>/', views.connect_connector, name='connect-connector'),
    path('disconnect/<int:instance_id>/', views.disconnect_connector, name='disconnect-connector'),

    # Plugins : configuration + test, Google Drive (OAuth), exports, import Notion
    path('plugins/<slug:connector_key>/save/', plugin_views.plugin_save, name='plugin-save'),
    path('plugins/<slug:connector_key>/test/', plugin_views.plugin_test, name='plugin-test'),
    path('plugins/telegram/chats/', plugin_views.telegram_chats, name='telegram-chats'),
    path('google/connect/', plugin_views.google_connect, name='google-connect'),
    path('oauth/trello/finish/', plugin_views.oauth_trello_finish, name='oauth-trello-finish'),
    path('oauth/<slug:connector_key>/authorize/', plugin_views.oauth_authorize, name='oauth-authorize'),
    path('oauth/<slug:connector_key>/connect/', plugin_views.oauth_connect, name='oauth-connect'),
    path('oauth/<slug:connector_key>/callback/', plugin_views.oauth_callback, name='oauth-callback'),
    path('google/callback/', plugin_views.google_callback, name='google-callback'),
    path('drive/upload/', plugin_views.drive_upload_pdf, name='drive-upload'),
    path('drive/files/', plugin_views.drive_list, name='drive-files'),
    path('drive/import/', plugin_views.drive_import, name='drive-import'),
    path('export/<slug:table>/', plugin_views.export_table, name='export-table'),
    path('notion/search/', plugin_views.notion_search, name='notion-search'),
    path('notion/preview/', plugin_views.notion_preview, name='notion-preview'),
    path('notion/import/', plugin_views.notion_import, name='notion-import'),

    path('', include(router.urls)),
    path('webhooks/<slug:connector_key>/', views.ConnectorWebhookView.as_view(), name='connector-webhook'),
]
