"""
Recense les textes de l'interface et liste ceux qui manquent dans les catalogues.

    python manage.py i18n_extract              # résumé par langue
    python manage.py i18n_extract --missing en # textes sans traduction anglaise (TSV)
"""
import json

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.translations.catalog import CATALOG_DIR, LANGUAGE_CODES
from apps.translations.extract import collect


class Command(BaseCommand):
    help = "Recense les textes de l'interface et indique les traductions manquantes."

    def add_arguments(self, parser):
        parser.add_argument('--missing', choices=LANGUAGE_CODES, help='Affiche les textes à traduire pour cette langue.')
        parser.add_argument('--dump', help='Écrit tous les textes (TSV id, texte, fichier) dans ce fichier.')

    def handle(self, *args, **options):
        found = collect(settings.BASE_DIR)
        ordered = sorted(found, key=lambda t: (sorted(found[t])[0], t))
        if options.get('dump'):
            with open(options['dump'], 'w', encoding='utf-8') as fh:
                for i, text in enumerate(ordered):
                    fh.write(f"{i}\t{text}\t{sorted(found[text])[0]}\n")
            self.stdout.write(f'{len(ordered)} textes écrits dans {options["dump"]}')
            return
        for lang in LANGUAGE_CODES:
            if lang == 'fr':
                continue
            try:
                catalog = json.loads((CATALOG_DIR / f'{lang}.json').read_text(encoding='utf-8'))
            except (OSError, ValueError):
                catalog = {}
            missing = [t for t in ordered if t not in catalog]
            if options.get('missing') == lang:
                for text in missing:
                    self.stdout.write(f"{text}\t{sorted(found[text])[0]}")
                return
            self.stdout.write(f'{lang} : {len(ordered) - len(missing)}/{len(ordered)} textes traduits')
