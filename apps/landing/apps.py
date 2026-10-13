from django.apps import AppConfig


class LandingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.landing'
    verbose_name = 'Landing Page'



    def ready(self):
        from . import legal  # noqa: F401  (vérification « informations légales » de check --deploy)
