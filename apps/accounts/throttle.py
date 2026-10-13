"""
Limitation des tentatives de connexion (contre le forçage de mot de passe).

- 5 échecs pour une même adresse email en 15 minutes → l'adresse est bloquée 15 minutes ;
- 20 échecs depuis une même adresse IP en 15 minutes → l'IP est bloquée 15 minutes ;
- « mot de passe oublié » : 5 demandes par IP et par heure.

Compteurs dans le cache Django (partagé entre processus en production : Redis ou table de cache).
"""
from django.conf import settings
from django.core.cache import cache

WINDOW = 15 * 60
MAX_PER_EMAIL = 5
MAX_PER_IP = 20
RESET_WINDOW = 60 * 60
MAX_RESETS_PER_IP = 5


def client_ip(request):
    """IP du visiteur ; derrière le proxy de l'hébergeur (NUM_PROXIES), celle qu'il a vue."""
    proxies = int(getattr(settings, 'NUM_PROXIES', 0) or 0)
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if proxies and forwarded:
        hops = [part.strip() for part in forwarded.split(',') if part.strip()]
        if len(hops) >= proxies:
            return hops[-proxies]
    return request.META.get('REMOTE_ADDR', '') or 'inconnue'


def _keys(request, email):
    return f'login-fail:email:{(email or "").strip().lower()}', f'login-fail:ip:{client_ip(request)}'


def login_blocked(request, email):
    email_key, ip_key = _keys(request, email)
    return (cache.get(email_key, 0) >= MAX_PER_EMAIL) or (cache.get(ip_key, 0) >= MAX_PER_IP)


def record_login_failure(request, email):
    for key in _keys(request, email):
        cache.add(key, 0, WINDOW)
        try:
            cache.incr(key)
        except ValueError:  # clé expirée entre-temps
            cache.set(key, 1, WINDOW)


def clear_login_failures(request, email):
    cache.delete(_keys(request, email)[0])


def reset_request_allowed(request):
    key = f'password-reset:ip:{client_ip(request)}'
    cache.add(key, 0, RESET_WINDOW)
    try:
        count = cache.incr(key)
    except ValueError:
        cache.set(key, 1, RESET_WINDOW)
        count = 1
    return count <= MAX_RESETS_PER_IP


BLOCKED_MESSAGE = 'Trop de tentatives de connexion. Réessayez dans 15 minutes ou utilisez « Mot de passe oublié ».'
