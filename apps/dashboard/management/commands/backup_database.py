"""
Sauvegarde de la base PostgreSQL (pg_dump compressé) dans le stockage des fichiers
(bucket S3 en production), dossier backups/, en gardant BACKUP_RETENTION_DAYS jours (14 par défaut).

    python manage.py backup_database

Le worker la lance une fois par jour si BACKUP_DAILY=1. Restauration :
    gunzip -c billio-AAAAMMJJ-HHMM.sql.gz | psql "$DATABASE_URL"
"""
import gzip
import os
import subprocess
import tempfile
from datetime import timedelta

from django.conf import settings
from django.core.files import File
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

FOLDER = 'backups'


class Command(BaseCommand):
    help = 'Sauvegarde la base PostgreSQL dans le stockage (backups/).'

    def handle(self, *args, **options):
        database = settings.DATABASES['default']
        if 'postgresql' not in database.get('ENGINE', ''):
            raise CommandError('La sauvegarde automatique concerne PostgreSQL (production).')
        url = os.getenv('DATABASE_URL')
        if not url:
            raise CommandError('DATABASE_URL manquante.')
        name = f"{FOLDER}/billio-{timezone.localtime():%Y%m%d-%H%M}.sql.gz"
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'dump.sql.gz')
            dump = subprocess.run(['pg_dump', '--no-owner', '--no-privileges', url],
                                  capture_output=True, check=False, timeout=1800)
            if dump.returncode != 0:
                raise CommandError(f"pg_dump a échoué : {dump.stderr.decode(errors='replace')[:500]}")
            with gzip.open(path, 'wb') as fh:
                fh.write(dump.stdout)
            with open(path, 'rb') as fh:
                saved = default_storage.save(name, File(fh))
        self.stdout.write(self.style.SUCCESS(f'Sauvegarde enregistrée : {saved}'))
        self._purge()

    def _purge(self):
        keep_days = int(os.getenv('BACKUP_RETENTION_DAYS', '14'))
        limit = timezone.now() - timedelta(days=keep_days)
        try:
            _dirs, files = default_storage.listdir(FOLDER)
        except (OSError, NotImplementedError):
            return
        for filename in files:
            path = f'{FOLDER}/{filename}'
            try:
                if default_storage.get_modified_time(path) < limit:
                    default_storage.delete(path)
                    self.stdout.write(f'Ancienne sauvegarde supprimée : {path}')
            except (OSError, NotImplementedError):
                continue
