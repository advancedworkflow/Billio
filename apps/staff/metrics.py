"""Mesure légère du trafic et des performances, pour l'espace d'administration.

MetricsMiddleware chronomètre chaque requête (hors fichiers statiques et /healthz/) et cumule en
mémoire, par heure et par route : nombre, erreurs 4xx/5xx, temps total, temps max, requêtes lentes.
Le cumul est écrit en base au plus toutes les FLUSH_SECONDS (une ligne par heure et par route), pour
ne pas ajouter d'écriture à chaque requête. Les visiteurs uniques sont comptés une fois par jour
(compte connecté, ou empreinte anonyme IP + navigateur hachée avec la clé secrète, jamais stockée en
clair). Les exceptions non gérées sont gardées 30 jours dans ServerError.
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

FLUSH_SECONDS = 60
SLOW_MS = 1000
RETENTION_DAYS = 90
SKIP_PREFIXES = ('/static/', '/media/', '/healthz', '/favicon', '/robots.txt', '/i18n/catalog')
BOT_MARKERS = ('bot', 'crawl', 'spider', 'slurp', 'curl', 'wget', 'python-requests', 'headless', 'monitor', 'uptime')

_lock = threading.Lock()
_buffer = {}
_last_flush = time.monotonic()


def _route(request):
    match = getattr(request, 'resolver_match', None)
    if match and match.view_name:
        return match.view_name[:120]
    return '(non trouvée)'


def _record(bucket, route, status, ms):
    global _last_flush
    with _lock:
        row = _buffer.setdefault((bucket, route), [0, 0, 0, 0, 0, 0])
        row[0] += 1
        row[1] += status >= 500
        row[2] += 400 <= status < 500
        row[3] += ms
        row[4] = max(row[4], ms)
        row[5] += ms >= SLOW_MS
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
    for (bucket, route), (count, errors, client_errors, total_ms, max_ms, slow) in pending.items():
        changes = dict(count=F('count') + count, errors=F('errors') + errors,
                       client_errors=F('client_errors') + client_errors, total_ms=F('total_ms') + total_ms,
                       max_ms=Greatest(F('max_ms'), max_ms), slow=F('slow') + slow)
        try:
            if not RequestMetric.objects.filter(bucket=bucket, route=route).update(**changes):
                try:
                    RequestMetric.objects.create(bucket=bucket, route=route, count=count, errors=errors,
                                                 client_errors=client_errors, total_ms=total_ms, max_ms=max_ms, slow=slow)
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


def _count_visitor(request, response):
    if request.method != 'GET' or response.status_code != 200:
        return
    if 'text/html' not in response.get('Content-Type', ''):
        return
    agent = request.META.get('HTTP_USER_AGENT', '')
    if not agent or any(marker in agent.lower() for marker in BOT_MARKERS):
        return
    from .models import VisitorDay
    day = timezone.localdate()
    user = getattr(request, 'user', None)
    if user is not None and user.is_authenticated:
        visitor, user_id = f'u{user.pk}', user.pk
    else:
        raw = f'{settings.SECRET_KEY}|{day}|{_client_ip(request)}|{agent}'
        visitor, user_id = hashlib.sha256(raw.encode()).hexdigest()[:32], None
    if not cache.add(f'staff-visit:{day}:{visitor}', 1, 26 * 3600):
        return
    try:
        VisitorDay.objects.get_or_create(day=day, visitor=visitor, defaults={
            'user_id': user_id, 'landing': request.path[:200]})
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
            _record(bucket, _route(request), response.status_code, ms)
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
