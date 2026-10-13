"""
Celery configuration for billio project.
"""
import os
from celery import Celery
from celery.schedules import crontab

# Set the default Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.dev')

app = Celery('billio')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django apps.
app.autodiscover_tasks()

# Celery Beat schedule
app.conf.beat_schedule = {
    'send-invoice-reminders': {
        'task': 'apps.invoices.tasks.send_invoice_reminders',
        'schedule': crontab(hour=9, minute=0),  # Every day at 9 AM
    },
    'generate-monthly-reports': {
        'task': 'apps.dashboard.tasks.generate_monthly_reports',
        'schedule': crontab(day_of_month=1, hour=0, minute=0),  # First day of month
    },
    'cleanup-old-files': {
        'task': 'apps.invoices.tasks.cleanup_old_files',
        'schedule': crontab(hour=2, minute=0),  # Every day at 2 AM
    },
    'send-quote-reminders': {
        'task': 'apps.invoices.tasks.send_quote_reminders',
        'schedule': crontab(hour=9, minute=15),  # Every day at 9:15 AM
    },
    'send-scheduled-invoices': {
        'task': 'apps.invoices.tasks.send_scheduled_invoices',
        'schedule': crontab(minute='*/15'),  # Every 15 minutes
    },
}

@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')


