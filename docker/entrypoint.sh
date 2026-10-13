#!/bin/sh
# Démarrage du conteneur Billio.
#   web     : migrations + serveur gunicorn (par défaut)
#   worker  : tâches planifiées en continu (relances, factures récurrentes, automatisations, sauvegardes)
#   release : migrations seules (étape « release » de certains hébergeurs)
#   autre   : commande passée telle quelle (ex. python manage.py createsuperuser)
set -e

prepare() {
  python manage.py migrate --noinput
  python manage.py createcachetable
}

case "$1" in
  web)
    if [ "${MIGRATE_ON_START:-1}" = "1" ]; then prepare; fi
    exec gunicorn config.wsgi:application \
      --bind "0.0.0.0:${PORT:-8000}" \
      --workers "${WEB_CONCURRENCY:-3}" \
      --timeout 120 \
      --forwarded-allow-ips="*" \
      --access-logfile - --error-logfile -
    ;;
  worker)
    exec python manage.py run_automations --loop "${WORKER_INTERVAL:-600}"
    ;;
  release)
    prepare
    ;;
  *)
    exec "$@"
    ;;
esac
