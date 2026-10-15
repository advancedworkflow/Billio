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


class RequestMetric(models.Model):
    """Cumul horaire des requêtes par route (voir apps.staff.metrics)."""

    bucket = models.DateTimeField(db_index=True)
    route = models.CharField(max_length=120)
    count = models.PositiveIntegerField(default=0)
    errors = models.PositiveIntegerField(default=0)
    client_errors = models.PositiveIntegerField(default=0)
    total_ms = models.BigIntegerField(default=0)
    max_ms = models.PositiveIntegerField(default=0)
    slow = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ('bucket', 'route')


class VisitorDay(models.Model):
    """Un visiteur unique par jour (compte connecté ou empreinte anonyme hachée)."""

    day = models.DateField(db_index=True)
    visitor = models.CharField(max_length=40)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE, related_name='+')
    landing = models.CharField(max_length=200, blank=True, default='')

    class Meta:
        unique_together = ('day', 'visitor')


class ServerError(models.Model):
    """Exception non gérée (erreur 500), gardée 30 jours."""

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    path = models.CharField(max_length=255)
    method = models.CharField(max_length=10, default='GET')
    route = models.CharField(max_length=120, blank=True, default='')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    exception = models.CharField(max_length=120)
    message = models.CharField(max_length=500, blank=True, default='')

    class Meta:
        ordering = ['-created_at']
