"""
Exécute les automatisations planifiées (dates du calendrier, factures/devis/tâches
en retard, attentes écoulées, relances J+7/14/30, factures récurrentes) sans attendre
qu'un utilisateur ouvre le tableau de bord.

Une fois (cron, Planificateur de tâches Windows…), toutes les 5 à 15 minutes :

    python manage.py run_automations

En continu (processus « worker » en production) :

    python manage.py run_automations --loop 600

Chaque passage signale qu'il a tourné (GET /healthz/?worker=1 pour la surveillance) ; une
erreur sur une organisation est journalisée (et remontée à Sentry) sans bloquer les autres.
"""
import logging
import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from apps.organizations.models import Organization

logger = logging.getLogger('billio.worker')


class Command(BaseCommand):
    help = "Déclenche les automatisations dont l'heure est arrivée."

    def add_arguments(self, parser):
        parser.add_argument('--loop', type=int, default=0, metavar='SECONDES',
                            help='Tourne en continu avec cette pause entre deux passages (ex. 600).')

    def handle(self, *args, **options):
        interval = options['loop']
        if not interval:
            self.run_once()
            return
        logger.info('Worker démarré : passage toutes les %s s.', interval)
        while True:
            started = time.monotonic()
            close_old_connections()
            try:
                self.run_once()
            except Exception:  # noqa: BLE001 — le worker ne doit jamais s'arrêter
                logger.exception('Passage des automatisations interrompu.')
            self.daily_backup()
            try:
                from apps.staff import server
                server.record_worker_run(time.monotonic() - started, interval)
                server.record_sample()
            except Exception:  # noqa: BLE001 — les relevés ne doivent jamais arrêter le worker
                logger.exception('Relevé de santé du serveur impossible.')
            time.sleep(max(30, interval - (time.monotonic() - started)))

    def daily_backup(self):
        """Sauvegarde de la base une fois par jour (BACKUP_DAILY=1), vers 3 h du matin."""
        import os

        from django.core.cache import cache
        from django.core.management import call_command
        from django.utils import timezone

        if os.getenv('BACKUP_DAILY') != '1':
            return
        now = timezone.localtime()
        key = f'billio:backup:{now:%Y-%m-%d}'
        if now.hour < 3 or cache.get(key):
            return
        try:
            call_command('backup_database')
            cache.set(key, True, 2 * 86400)
        except Exception:  # noqa: BLE001
            logger.exception('Sauvegarde quotidienne de la base en échec.')

    def run_once(self):
        from apps.dashboard.automation_calendar import sweep_calendar_triggers
        from apps.dashboard.automation_engine import (
            run_pending_waits, sweep_expired_quotes, sweep_overdue_invoices, sweep_overdue_tasks,
        )
        from apps.invoices.scheduled import run_billing_schedule
        from config.health import record_worker_heartbeat

        count = failed = 0
        for organization in Organization.objects.filter(is_active=True):
            try:
                sweep_overdue_invoices(organization)
                sweep_expired_quotes(organization)
                sweep_overdue_tasks(organization)
                sweep_calendar_triggers(organization)
                run_billing_schedule(organization)
                count += 1
            except Exception:  # noqa: BLE001
                failed += 1
                logger.exception('Automatisations en échec pour l’organisation %s.', organization.pk)
        try:
            run_pending_waits()
        except Exception:  # noqa: BLE001
            logger.exception('Attentes de workflow en échec.')
        record_worker_heartbeat()
        message = f"Automatisations vérifiées pour {count} organisation(s)."
        if failed:
            message += f" {failed} en échec (voir les journaux)."
        self.stdout.write(message)
