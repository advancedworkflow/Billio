"""
Celery tasks for the dashboard app, referenced by config/celery.py's beat_schedule.
"""
from celery import shared_task


@shared_task
def generate_monthly_reports():
    """
    Tâche mensuelle : place tenue pour la génération de rapports d'activité
    par organisation. Hors périmètre du module Devis — stub minimal pour que
    la référence dans beat_schedule reste résoluble.
    """
    return 0
