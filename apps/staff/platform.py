"""Réglages de la plateforme : variable d'environnement d'abord, sinon valeur saisie dans l'administration."""
import os

from django.core.cache import cache

CACHE_KEY = 'platform-setting:{}'


def get_setting(name):
    value = os.getenv(name, '').strip()
    if value:
        return value
    cached = cache.get(CACHE_KEY.format(name))
    if cached is not None:
        return cached
    from .models import PlatformSetting
    try:
        value = PlatformSetting.objects.filter(key=name).values_list('value', flat=True).first() or ''
    except Exception:  # base pas encore migrée
        return ''
    cache.set(CACHE_KEY.format(name), value, 300)
    return value


def set_setting(name, value, user=None):
    from .models import PlatformSetting
    value = (value or '').strip()
    if value:
        PlatformSetting.objects.update_or_create(key=name, defaults={'value': value, 'updated_by': user})
    else:
        PlatformSetting.objects.filter(key=name).delete()
    cache.delete(CACHE_KEY.format(name))


def source(name):
    """'env' (serveur), 'site' (saisi dans l'administration) ou '' (absent)."""
    if os.getenv(name, '').strip():
        return 'env'
    return 'site' if get_setting(name) else ''
