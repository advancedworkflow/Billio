from django.db import models


class ConsentRecord(models.Model):
    """Preuve d'un choix de cookies (RGPD art. 7) : identifiant aléatoire du navigateur, sans IP ni compte."""

    consent_id = models.CharField(max_length=36, db_index=True)
    version = models.PositiveSmallIntegerField()
    choices = models.JSONField(default=dict)
    action = models.CharField(max_length=20, blank=True, default='')
    gpc = models.BooleanField(default=False)
    user_agent = models.CharField(max_length=200, blank=True, default='')
    page = models.CharField(max_length=200, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Choix de cookies'
        verbose_name_plural = 'Choix de cookies'

    def __str__(self):
        return f'{self.consent_id} · {self.action} · {self.created_at:%d/%m/%Y %H:%M}'
