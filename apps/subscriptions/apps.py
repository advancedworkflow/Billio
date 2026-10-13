from django.apps import AppConfig


class SubscriptionsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.subscriptions'
    verbose_name = 'Abonnements'

    def ready(self):
        from . import signals  # noqa: F401  (quotas vérifiés à la création)
