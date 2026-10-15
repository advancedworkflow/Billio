from django.conf import settings
from django.db import models


class PlatformSetting(models.Model):
    """Réglage de la plateforme saisi depuis l'espace d'administration (ex. clés OAuth des intégrations).

    Une variable d'environnement du même nom reste prioritaire : voir apps.staff.platform.get_setting.
    """

    key = models.CharField(max_length=80, unique=True)
    value = models.TextField(blank=True, default='')
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='+')

    class Meta:
        verbose_name = 'Réglage de la plateforme'
        verbose_name_plural = 'Réglages de la plateforme'

    def __str__(self):
        return self.key
