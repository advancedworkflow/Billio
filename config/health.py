"""
Point de santé pour la surveillance (uptime) : GET /healthz/

- 200 {"status": "ok"} si la base répond ;
- avec ?worker=1, vérifie aussi que le worker des tâches planifiées a tourné il y a moins de
  WORKER_MAX_DELAY secondes (sinon 503) : relances, factures récurrentes, automatisations.

Placé en tête des middlewares : répond avant la redirection HTTPS et la vérification du nom
de domaine, pour que les sondes internes de l'hébergeur puissent l'appeler.
"""
import time

from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse

WORKER_HEARTBEAT_KEY = 'billio:worker:last_run'
WORKER_MAX_DELAY = 30 * 60


def record_worker_heartbeat():
    cache.set(WORKER_HEARTBEAT_KEY, time.time(), None)


class HealthCheckMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path != '/healthz/':
            return self.get_response(request)
        payload, status = {'status': 'ok'}, 200
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1')
        except Exception:  # noqa: BLE001 — toute panne de base doit donner un 503
            return JsonResponse({'status': 'error', 'database': 'unreachable'}, status=503)
        if request.GET.get('worker'):
            last = cache.get(WORKER_HEARTBEAT_KEY)
            age = None if last is None else int(time.time() - last)
            payload['worker_last_run_seconds_ago'] = age
            if age is None or age > WORKER_MAX_DELAY:
                payload['status'], status = 'worker_late', 503
        return JsonResponse(payload, status=status)
