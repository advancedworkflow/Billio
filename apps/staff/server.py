"""
Santé du serveur (VPS) pour l'espace d'administration : processeur, mémoire, swap, disque, base, workers.

Les conteneurs Docker voient /proc/loadavg, /proc/meminfo et /proc/stat de la machine hôte : les valeurs
sont celles du VPS entier. Le worker des tâches planifiées enregistre à chaque passage un relevé
(record_sample) pour garder les pics des dernières 24 heures, et la durée de son passage.
"""
import os
import shutil
import time

from django.conf import settings
from django.core.cache import cache
from django.db import connection

SAMPLES_KEY = 'billio:server:samples'
WORKER_STATS_KEY = 'billio:worker:stats'
MAX_SAMPLES = 24 * 6  # un relevé par passage du worker (10 min) sur 24 h

# Seuils (orange, rouge)
THRESHOLDS = {
    'cpu': (80, 95),         # % du processeur utilisé
    'load': (1.0, 2.0),      # charge moyenne 5 min par cœur
    'ram': (80, 92),         # % de mémoire utilisée (hors cache récupérable)
    'swap': (25, 60),        # % du swap utilisé
    'disk': (85, 95),        # % du disque utilisé
    'db_conn': (70, 90),     # % des connexions PostgreSQL utilisées
    'web_busy': (70, 90),    # % du temps où les workers web sont occupés (dernière heure)
    'worker_run': (50, 100),  # durée d'un passage du worker en % de son intervalle
}


def level(metric, value):
    if value is None:
        return 'ok'
    warning, critical = THRESHOLDS[metric]
    return 'critical' if value >= critical else 'warning' if value >= warning else 'ok'


def _read(path):
    try:
        with open(path) as handle:
            return handle.read()
    except OSError:
        return None


def _cpu_times():
    raw = _read('/proc/stat')
    if not raw:
        return None
    values = [int(v) for v in raw.splitlines()[0].split()[1:]]
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return sum(values), idle


def cpu_percent(interval=0.25):
    first = _cpu_times()
    if first is None:
        return None
    time.sleep(interval)
    second = _cpu_times()
    total, idle = second[0] - first[0], second[1] - first[1]
    return round((total - idle) * 100 / total) if total else 0


def memory():
    raw = _read('/proc/meminfo')
    if not raw:
        return None
    info = {}
    for line in raw.splitlines():
        key, _, rest = line.partition(':')
        info[key] = int(rest.split()[0]) if rest.split() else 0
    total, available = info.get('MemTotal', 0), info.get('MemAvailable', info.get('MemFree', 0))
    swap_total, swap_free = info.get('SwapTotal', 0), info.get('SwapFree', 0)
    return {
        'total_mb': round(total / 1024), 'used_mb': round((total - available) / 1024),
        'ram': round((total - available) * 100 / total) if total else 0,
        'swap_total_mb': round(swap_total / 1024), 'swap_used_mb': round((swap_total - swap_free) / 1024),
        'swap': round((swap_total - swap_free) * 100 / swap_total) if swap_total else 0,
    }


def load():
    try:
        one, five, fifteen = os.getloadavg()
    except (OSError, AttributeError):
        return None
    cores = os.cpu_count() or 1
    return {'cores': cores, 'one': round(one, 2), 'five': round(five, 2), 'fifteen': round(fifteen, 2),
            'per_core': round(five / cores, 2)}


def disk():
    try:
        usage = shutil.disk_usage(getattr(settings, 'MEDIA_ROOT', None) or '/')
    except OSError:
        return None
    return {'disk': round(usage.used * 100 / usage.total), 'free_gb': round(usage.free / 1024 ** 3, 1),
            'total_gb': round(usage.total / 1024 ** 3)}


def database():
    if connection.vendor != 'postgresql':
        return None
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_database_size(current_database()), "
                       "(SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()), "
                       "current_setting('max_connections')::int")
        size, used, maximum = cursor.fetchone()
    return {'size_mb': round(size / 1024 ** 2), 'connections': used, 'max_connections': maximum,
            'db_conn': round(used * 100 / maximum) if maximum else 0}


def web_busy(summary_hour):
    """Part du temps où les workers gunicorn ont traité des requêtes sur la dernière heure."""
    workers = int(os.getenv('WEB_CONCURRENCY', '3') or 3)
    busy_seconds = summary_hour['count'] * summary_hour['avg_ms'] / 1000
    return {'workers': workers, 'web_busy': min(100, round(busy_seconds * 100 / (3600 * workers)))}


def sample():
    """Relevé instantané (sans mesure CPU, qui demande une attente)."""
    mem, avg = memory() or {}, load() or {}
    return {'at': time.time(), 'ram': mem.get('ram'), 'swap': mem.get('swap'), 'load': avg.get('per_core')}


def record_sample():
    samples = [s for s in (cache.get(SAMPLES_KEY) or []) if s['at'] > time.time() - 86400]
    samples.append(sample())
    cache.set(SAMPLES_KEY, samples[-MAX_SAMPLES:], None)


def record_worker_run(duration, interval):
    try:
        import resource  # absent sous Windows
        rss_mb = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)
    except ImportError:
        rss_mb = 0
    cache.set(WORKER_STATS_KEY, {'at': time.time(), 'duration': round(duration, 1), 'interval': interval,
                                 'rss_mb': rss_mb}, None)


def peaks():
    samples = cache.get(SAMPLES_KEY) or []
    result = {'count': len(samples)}
    for key in ('ram', 'swap', 'load'):
        values = [s[key] for s in samples if s.get(key) is not None]
        result[key] = max(values) if values else None
        result[f'{key}_series'] = values[-48:]
    return result


def snapshot(summary_hour):
    """Toutes les jauges du serveur, chacune avec son niveau (ok / warning / critical)."""
    gauges = []

    def add(key, label, value, display, detail, peak=None, series=None):
        gauges.append({'key': key, 'label': label, 'value': value, 'display': display, 'detail': detail,
                       'level': level(key, value), 'peak': peak, 'peak_level': level(key, peak),
                       'series': series or [], 'bar': max(0, min(100, value if key != 'load' else value * 50))})

    history = peaks()
    cpu = cpu_percent()
    avg = load()
    if cpu is not None:
        add('cpu', 'Processeur', cpu, f'{cpu} %', f"{avg['cores']} cœur(s)" if avg else '')
    if avg:
        add('load', 'Charge (5 min)', avg['per_core'], f"{avg['five']}",
            f"1 min {avg['one']} · 15 min {avg['fifteen']} · {avg['cores']} cœur(s)",
            history['load'], history['load_series'])
    mem = memory()
    if mem:
        add('ram', 'Mémoire', mem['ram'], f"{mem['ram']} %", f"{mem['used_mb']} / {mem['total_mb']} Mo",
            history['ram'], history['ram_series'])
        if mem['swap_total_mb']:
            add('swap', 'Swap', mem['swap'], f"{mem['swap']} %", f"{mem['swap_used_mb']} / {mem['swap_total_mb']} Mo",
                history['swap'], history['swap_series'])
    space = disk()
    if space:
        add('disk', 'Disque', space['disk'], f"{space['disk']} %", f"{space['free_gb']} Go libres sur {space['total_gb']}")
    db = database()
    if db:
        add('db_conn', 'Connexions base', db['db_conn'], f"{db['connections']} / {db['max_connections']}",
            f"Base de données : {db['size_mb']} Mo")
    busy = web_busy(summary_hour)
    add('web_busy', 'Workers web occupés', busy['web_busy'], f"{busy['web_busy']} %",
        f"{busy['workers']} workers gunicorn · {summary_hour['avg_ms']} ms en moyenne (1 h)")
    stats = cache.get(WORKER_STATS_KEY)
    if stats and stats.get('interval'):
        ratio = round(stats['duration'] * 100 / stats['interval'])
        add('worker_run', 'Passage du worker', ratio, f"{stats['duration']} s",
            f"sur {stats['interval']} s d'intervalle · {stats['rss_mb']} Mo de mémoire")
    return {'gauges': gauges, 'history_count': history['count']}


MESSAGES = {
    'cpu': ('Processeur saturé', 'Le VPS calcule en continu : pages lentes. Passez à une offre avec plus de cœurs.'),
    'load': ('Charge du serveur élevée', "Plus de tâches en attente que de cœurs : le serveur n'arrive plus à suivre."),
    'ram': ('Mémoire presque pleine', 'Risque que le système tue un processus (OOM). Ajoutez de la RAM ou baissez WEB_CONCURRENCY.'),
    'swap': ('Le serveur utilise beaucoup le swap', 'La RAM ne suffit plus : tout ralentit. Augmentez la mémoire du VPS.'),
    'disk': ('Disque presque plein', 'Base, sauvegardes et fichiers ne pourront plus être écrits. Nettoyez ou agrandissez le disque.'),
    'db_conn': ('Connexions à la base presque épuisées', 'De nouvelles requêtes risquent d’échouer.'),
    'web_busy': ('Workers web saturés', 'Les requêtes font la queue : augmentez WEB_CONCURRENCY (et la RAM) ou optimisez les pages lentes.'),
    'worker_run': ('Le worker des tâches planifiées est surchargé', 'Un passage dure presque autant que son intervalle : relances et automatisations prennent du retard.'),
}


def alerts(snap):
    """Alertes orange/rouges pour chaque jauge hors seuil, y compris un pic des dernières 24 h."""
    items = []
    for gauge in snap['gauges']:
        title, advice = MESSAGES[gauge['key']]
        if gauge['level'] != 'ok':
            items.append({'level': gauge['level'], 'title': f"{title} : {gauge['display']}",
                          'detail': f"{gauge['detail']}. {advice}", 'link': '#serveur'})
        elif gauge['peak_level'] != 'ok':
            peak = gauge['peak'] if gauge['key'] == 'load' else f"{gauge['peak']} %"
            items.append({'level': 'warning', 'title': f"{title} dans les dernières 24 h (pic : {peak})",
                          'detail': f"Valeur actuelle normale ({gauge['display']}). {advice}", 'link': '#serveur'})
        else:
            items.append({'level': 'ok', 'title': f"{gauge['label']} : {gauge['display']}", 'detail': gauge['detail']})
    return items
