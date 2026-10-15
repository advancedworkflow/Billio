"""Mesure légère du trafic et des performances, pour l'espace d'administration.

MetricsMiddleware chronomètre chaque requête (hors fichiers statiques et /healthz/) et cumule en
mémoire, par heure et par route : nombre, pages vues, erreurs 4xx/5xx, temps total, temps max,
requêtes lentes. Le cumul est écrit en base au plus toutes les FLUSH_SECONDS (une ligne par heure et
par route), pour ne pas ajouter d'écriture à chaque requête. Ces cumuls ne contiennent aucune donnée
personnelle.

Visiteurs uniques (un par jour) et présence « en direct » (last_seen, rafraîchi au plus une fois par
minute) :
- compte connecté : compté pour le fonctionnement du service (intérêt légitime, pas de cookie ajouté) ;
- visiteur anonyme : compté seulement s'il a accepté la mesure d'audience dans le bandeau cookies
  (apps.landing.consent) et n'envoie pas de signal Global Privacy Control. L'empreinte (IP +
  navigateur + jour, hachée avec la clé secrète) n'est jamais stockée en clair.
Les exceptions non gérées sont gardées 30 jours dans ServerError.
"""
import hashlib
import random
import threading
import time
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError
from django.db.models import F
from django.db.models.functions import Greatest
from django.utils import timezone

FLUSH_SECONDS = 15
SLOW_MS = 1000
RETENTION_DAYS = 90
SEEN_EVERY = 60  # présence rafraîchie au plus une fois par minute et par visiteur
SKIP_PREFIXES = ('/static/', '/media/', '/healthz', '/favicon', '/robots.txt', '/i18n/catalog')
BOT_MARKERS = ('bot', 'crawl', 'spider', 'slurp', 'curl', 'wget', 'python-requests', 'headless', 'monitor', 'uptime')
FIELDS = ('count', 'pageviews', 'errors', 'client_errors', 'total_ms', 'max_ms', 'slow')

_lock = threading.Lock()
_buffer = {}
_last_flush = time.monotonic()


def _route(request):
    match = getattr(request, 'resolver_match', None)
    if match and match.view_name:
        return match.view_name[:120]
    return '(non trouvée)'


def _is_page(request, response):
    return (request.method == 'GET' and response.status_code == 200
            and 'text/html' in response.get('Content-Type', ''))


def _is_bot(request):
    agent = request.META.get('HTTP_USER_AGENT', '').lower()
    return not agent or any(marker in agent for marker in BOT_MARKERS)


def _record(bucket, route, status, ms, pageview):
    global _last_flush
    with _lock:
        row = _buffer.setdefault((bucket, route), dict.fromkeys(FIELDS, 0))
        row['count'] += 1
        row['pageviews'] += pageview
        row['errors'] += status >= 500
        row['client_errors'] += 400 <= status < 500
        row['total_ms'] += ms
        row['max_ms'] = max(row['max_ms'], ms)
        row['slow'] += ms >= SLOW_MS
        due = time.monotonic() - _last_flush >= FLUSH_SECONDS
        if due:
            _last_flush = time.monotonic()
    if due:
        flush()


def flush():
    """Écrit le cumul en mémoire dans RequestMetric."""
    from .models import RequestMetric
    with _lock:
        pending = dict(_buffer)
        _buffer.clear()
    for (bucket, route), row in pending.items():
        changes = {name: F(name) + row[name] for name in FIELDS if name != 'max_ms'}
        changes['max_ms'] = Greatest(F('max_ms'), row['max_ms'])
        try:
            if not RequestMetric.objects.filter(bucket=bucket, route=route).update(**changes):
                try:
                    RequestMetric.objects.create(bucket=bucket, route=route, **row)
                except IntegrityError:
                    RequestMetric.objects.filter(bucket=bucket, route=route).update(**changes)
        except Exception:  # noqa: BLE001 — la mesure ne doit jamais casser une page
            continue
    if random.random() < 0.02:
        _purge()


def _purge():
    from .models import RequestMetric, ServerError, VisitorDay
    limit = timezone.now() - timedelta(days=RETENTION_DAYS)
    RequestMetric.objects.filter(bucket__lt=limit).delete()
    VisitorDay.objects.filter(day__lt=limit.date()).delete()
    ServerError.objects.filter(created_at__lt=timezone.now() - timedelta(days=30)).delete()


def _client_ip(request):
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    return (forwarded.split(',')[0] if forwarded else request.META.get('REMOTE_ADDR', '')).strip()


def _visitor(request, response):
    """(clé du visiteur, id du compte) ou None si ce visiteur ne doit pas être compté."""
    user = getattr(request, 'user', None)
    if user is not None and user.is_authenticated:
        return (f'u{user.pk}', user.pk) if response.status_code < 500 else None
    from apps.landing.consent import analytics_allowed
    if not _is_page(request, response) or _is_bot(request) or not analytics_allowed(request):
        return None
    raw = f'{settings.SECRET_KEY}|{timezone.localdate()}|{_client_ip(request)}|{request.META.get("HTTP_USER_AGENT", "")}'
    return hashlib.sha256(raw.encode()).hexdigest()[:32], None


def _count_visitor(request, response):
    found = _visitor(request, response)
    if not found:
        return
    visitor, user_id = found
    from .models import VisitorDay
    day = timezone.localdate()
    now = timezone.now()
    try:
        if cache.add(f'staff-visit:{day}:{visitor}', 1, 26 * 3600):
            VisitorDay.objects.get_or_create(day=day, visitor=visitor, defaults={
                'user_id': user_id, 'landing': request.path[:200], 'last_seen': now})
            cache.set(f'staff-seen:{visitor}', 1, SEEN_EVERY)
        elif cache.add(f'staff-seen:{visitor}', 1, SEEN_EVERY):
            VisitorDay.objects.filter(day=day, visitor=visitor).update(last_seen=now)
    except Exception:  # noqa: BLE001
        pass


class MetricsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith(SKIP_PREFIXES):
            return self.get_response(request)
        started = time.perf_counter()
        response = self.get_response(request)
        ms = int((time.perf_counter() - started) * 1000)
        try:
            bucket = timezone.now().replace(minute=0, second=0, microsecond=0)
            pageview = _is_page(request, response) and not _is_bot(request)
            _record(bucket, _route(request), response.status_code, ms, pageview)
            _count_visitor(request, response)
        except Exception:  # noqa: BLE001
            pass
        return response

    def process_exception(self, request, exception):
        from .models import ServerError
        try:
            user = getattr(request, 'user', None)
            ServerError.objects.create(
                path=request.path[:255], method=request.method[:10], route=_route(request),
                user=user if user is not None and user.is_authenticated else None,
                exception=type(exception).__name__[:120], message=str(exception)[:500])
        except Exception:  # noqa: BLE001
            pass
        return None
