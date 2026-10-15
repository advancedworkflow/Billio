"""Calcul des indicateurs de l'espace d'administration : alertes, trafic, utilisation."""
import os
import shutil
import time
from datetime import timedelta

from django.apps import apps
from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.db.models import Count, Max, Sum
from django.db.models.functions import TruncDate, TruncHour
from django.urls import reverse
from django.utils import timezone

from .models import RequestMetric, ServerError, VisitorDay

# Objets suivis : (libellé, modèle, champ « organisation » ou None)
TRACKED = [
    ('Organisations', 'organizations.Organization', None),
    ('Clients', 'clients.Client', 'organization'),
    ('Factures', 'invoices.Invoice', 'organization'),
    ('Devis', 'invoices.Quote', 'organization'),
    ('Produits', 'invoices.Product', 'organization'),
    ('Projets', 'dashboard.Project', 'organization'),
    ('Tâches', 'dashboard.Task', None),
    ('Documents', 'documents.Document', 'organization'),
    ('Paiements', 'payments.Payment', None),
    ('Automatisations', 'dashboard.AutomationRule', 'organization'),
    ('Temps saisis', 'dashboard.TimeEntry', None),
    ('Rendez-vous', 'dashboard.Appointment', 'organization'),
    ('Formulaires clients', 'dashboard.ClientForm', 'organization'),
    ('Intégrations connectées', 'integrations.ConnectionInstance', 'organization'),
]


def _bars(rows, key, days):
    """Série quotidienne complète (jours sans données à 0) avec hauteur relative pour les barres CSS."""
    today = timezone.localdate()
    by_day = {r['day']: r for r in rows}
    series = []
    for offset in range(days - 1, -1, -1):
        day = today - timedelta(days=offset)
        series.append({'day': day, 'value': (by_day.get(day) or {}).get(key) or 0})
    top = max((s['value'] for s in series), default=0) or 1
    for s in series:
        s['pct'] = round(s['value'] * 100 / top)
    return series


def summary(since):
    agg = RequestMetric.objects.filter(bucket__gte=since).aggregate(
        count=Sum('count'), errors=Sum('errors'), client_errors=Sum('client_errors'),
        total_ms=Sum('total_ms'), slow=Sum('slow'), max_ms=Max('max_ms'))
    count = agg['count'] or 0
    return {
        'count': count, 'errors': agg['errors'] or 0, 'client_errors': agg['client_errors'] or 0,
        'avg_ms': round((agg['total_ms'] or 0) / count) if count else 0, 'max_ms': agg['max_ms'] or 0,
        'slow': agg['slow'] or 0,
        'error_rate': round((agg['errors'] or 0) * 100 / count, 2) if count else 0,
        'slow_rate': round((agg['slow'] or 0) * 100 / count, 1) if count else 0,
    }


def _routes(since):
    rows = RequestMetric.objects.filter(bucket__gte=since).values('route').annotate(
        count=Sum('count'), errors=Sum('errors'), client_errors=Sum('client_errors'),
        total_ms=Sum('total_ms'), max_ms=Max('max_ms'), slow=Sum('slow'))
    rows = [dict(r, avg_ms=round(r['total_ms'] / r['count']) if r['count'] else 0) for r in rows]
    return {
        'top': sorted(rows, key=lambda r: -r['count'])[:12],
        'slowest': sorted([r for r in rows if r['count'] >= 3], key=lambda r: -r['avg_ms'])[:10],
        'failing': sorted([r for r in rows if r['errors']], key=lambda r: -r['errors'])[:10],
    }


def traffic():
    now = timezone.now()
    day_rows = RequestMetric.objects.filter(bucket__gte=now - timedelta(days=30)) \
        .annotate(day=TruncDate('bucket')).values('day') \
        .annotate(count=Sum('count'), errors=Sum('errors'), total_ms=Sum('total_ms'))
    day_rows = [dict(r, avg_ms=round(r['total_ms'] / r['count']) if r['count'] else 0) for r in day_rows]
    visitor_rows = VisitorDay.objects.filter(day__gte=timezone.localdate() - timedelta(days=30)) \
        .values('day').annotate(visitors=Count('id'))
    hour_rows = RequestMetric.objects.filter(bucket__gte=now - timedelta(hours=24)) \
        .annotate(hour=TruncHour('bucket')).values('hour').annotate(count=Sum('count')).order_by('hour')
    by_hour = {timezone.localtime(h['hour']).replace(minute=0, second=0, microsecond=0): h['count'] for h in hour_rows}
    current = timezone.localtime(now).replace(minute=0, second=0, microsecond=0)
    hours = [{'hour': current - timedelta(hours=offset), 'count': by_hour.get(current - timedelta(hours=offset), 0)}
             for offset in range(23, -1, -1)]
    top_hour = max(h['count'] for h in hours) or 1
    for h in hours:
        h['pct'] = round(h['count'] * 100 / top_hour)
    today = timezone.localdate()
    visitors = VisitorDay.objects.filter(day=today)
    return {
        'last_24h': summary(now - timedelta(hours=24)),
        'last_7d': summary(now - timedelta(days=7)),
        'visitors_today': visitors.count(),
        'visitors_today_anon': visitors.filter(user__isnull=True).count(),
        'visitors_7d': VisitorDay.objects.filter(day__gt=today - timedelta(days=7)).values('visitor').distinct().count(),
        'requests_series': _bars(day_rows, 'count', 30),
        'visitors_series': _bars(list(visitor_rows), 'visitors', 30),
        'latency_series': _bars(day_rows, 'avg_ms', 30),
        'hours': hours,
        'routes': _routes(now - timedelta(days=7)),
        'errors': ServerError.objects.select_related('user')[:25],
        'error_groups': ServerError.objects.filter(created_at__gte=now - timedelta(days=7))
        .values('exception', 'route').annotate(n=Count('id'), last=Max('created_at')).order_by('-n')[:10],
        'landings': VisitorDay.objects.filter(day__gt=today - timedelta(days=7), user__isnull=True)
        .values('landing').annotate(n=Count('id')).order_by('-n')[:8],
    }


def _distinct_users(since_day):
    return VisitorDay.objects.filter(day__gte=since_day, user__isnull=False).values('user').distinct().count()


def usage():
    from django.contrib.auth import get_user_model
    now = timezone.now()
    today = timezone.localdate()
    User = get_user_model()
    dau, wau, mau = (_distinct_users(today), _distinct_users(today - timedelta(days=6)),
                     _distinct_users(today - timedelta(days=29)))
    org_total = apps.get_model('organizations.Organization').objects.count() or 1

    objects = []
    for label, name, org_field in TRACKED:
        model = apps.get_model(name)
        qs = model.objects.all()
        last_30 = qs.filter(created_at__gte=now - timedelta(days=30)).count()
        prev_30 = qs.filter(created_at__gte=now - timedelta(days=60), created_at__lt=now - timedelta(days=30)).count()
        row = {'label': label, 'total': qs.count(), 'last_7': qs.filter(created_at__gte=now - timedelta(days=7)).count(),
               'last_30': last_30, 'trend': (round((last_30 - prev_30) * 100 / prev_30) if prev_30 else None)}
        if org_field:
            using = qs.values(org_field).distinct().count()
            row['adoption'] = round(using * 100 / org_total)
        objects.append(row)

    signups = User.objects.filter(date_joined__gte=now - timedelta(days=30)) \
        .annotate(day=TruncDate('date_joined')).values('day').annotate(n=Count('id'))
    Invoice = apps.get_model('invoices.Invoice')
    recent_users = User.objects.filter(date_joined__gte=now - timedelta(days=30))
    # Activation : comptes récents dont l'organisation a déjà créé au moins une facture.
    activated = Invoice.objects.filter(organization__owner__in=recent_users) \
        .values('organization__owner').distinct().count()
    top_orgs = Invoice.objects.filter(created_at__gte=now - timedelta(days=30)).values('organization__name') \
        .annotate(n=Count('id'), total=Sum('total_amount')).order_by('-n')[:8]
    return {
        'dau': dau, 'wau': wau, 'mau': mau,
        'stickiness': round(dau * 100 / mau) if mau else 0,
        'users_total': User.objects.count(),
        'signups_30': recent_users.count(), 'activated_30': activated,
        'activation_rate': round(activated * 100 / recent_users.count()) if recent_users.count() else 0,
        'signups_series': _bars(list(signups), 'n', 30),
        'objects': objects,
        'top_orgs': top_orgs,
        'never_logged': User.objects.filter(last_login__isnull=True).count(),
        'dormant': User.objects.filter(last_login__lt=now - timedelta(days=30)).count(),
    }


# --------------------------------------------------------------------------- alertes

def _disk():
    try:
        usage_ = shutil.disk_usage(getattr(settings, 'MEDIA_ROOT', None) or '/')
    except OSError:
        return None
    return round(usage_.used * 100 / usage_.total), round(usage_.free / 1024 ** 3, 1)


def _db_size_mb():
    if connection.vendor != 'postgresql':
        return None
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_database_size(current_database())')
        return round(cursor.fetchone()[0] / 1024 ** 2)


def alerts():
    from config.health import WORKER_HEARTBEAT_KEY, WORKER_MAX_DELAY
    now = timezone.now()
    items = []

    def add(level, title, detail='', link=''):
        items.append({'level': level, 'title': title, 'detail': detail, 'link': link})

    last = cache.get(WORKER_HEARTBEAT_KEY)
    if last is None:
        add('critical' if not settings.DEBUG else 'warning', "Le worker des tâches planifiées n'a jamais tourné",
            'Relances, factures récurrentes et automatisations ne partent pas.')
    elif time.time() - last > WORKER_MAX_DELAY:
        add('critical', 'Worker en retard', f'Dernier passage il y a {int((time.time() - last) // 60)} min.')
    else:
        add('ok', 'Worker des tâches planifiées', f'Dernier passage il y a {int((time.time() - last) // 60)} min.')

    day = summary(now - timedelta(hours=24))
    if day['errors']:
        level = 'critical' if day['error_rate'] >= 1 else 'warning'
        add(level, f"{day['errors']} erreur(s) serveur en 24 h", f"{day['error_rate']} % des requêtes.",
            reverse('staff:traffic') + '#errors')
    else:
        add('ok', 'Aucune erreur serveur en 24 h')
    if day['count'] and day['slow_rate'] >= 5:
        add('warning', 'Requêtes lentes', f"{day['slow_rate']} % au-dessus d'1 seconde en 24 h.", reverse('staff:traffic') + '#slow')

    disk = _disk()
    if disk:
        used, free = disk
        add('critical' if used >= 95 else 'warning' if used >= 85 else 'ok', f'Disque utilisé à {used} %', f'{free} Go libres.')
    size = _db_size_mb()
    if size is not None:
        add('ok', f'Base de données : {size} Mo')

    if not settings.DEBUG:
        if not getattr(settings, 'EMAIL_HOST_PASSWORD', ''):
            add('critical', "Les emails ne partent pas", 'RESEND_API_KEY est vide dans .env.production.')
        if not os.getenv('BACKUP_DAILY'):
            add('warning', 'Sauvegarde quotidienne désactivée', 'Mettez BACKUP_DAILY=1 dans .env.production.')
        if not os.getenv('SENTRY_DSN'):
            add('info', 'Suivi des erreurs Sentry non configuré', 'SENTRY_DSN est vide.')

    Subscription = apps.get_model('subscriptions.Subscription')
    past_due = Subscription.objects.filter(status__in=('past_due', 'unpaid')).count()
    if past_due:
        add('warning', f'{past_due} abonnement(s) en défaut de paiement', '', reverse('staff:users'))
    broken = apps.get_model('integrations.ConnectionInstance').objects.filter(status='error').count()
    if broken:
        add('warning', f'{broken} intégration(s) en erreur', 'Connexions à un outil qui échouent chez des clients.')
    AutomationRun = apps.get_model('dashboard.AutomationRun')
    failed = AutomationRun.objects.filter(success=False, ran_at__gte=now - timedelta(hours=24)).count()
    if failed:
        add('warning', f'{failed} automatisation(s) échouée(s) en 24 h')
    Ticket = apps.get_model('dashboard.SupportTicket')
    waiting = Ticket.objects.filter(status='open', created_at__lt=now - timedelta(hours=48)).count()
    if waiting:
        add('warning', f'{waiting} ticket(s) sans réponse depuis plus de 48 h', '', reverse('dashboard:support'))
    urgent = Ticket.objects.filter(status='open', priority='urgent').count()
    if urgent:
        add('critical', f'{urgent} ticket(s) urgent(s) ouvert(s)', '', reverse('dashboard:support'))

    order = {'critical': 0, 'warning': 1, 'info': 2, 'ok': 3}
    return sorted(items, key=lambda i: order[i['level']])
