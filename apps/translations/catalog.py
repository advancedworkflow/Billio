"""
Catalogues de traduction de l'interface : apps/translations/catalog/<langue>.json,
{texte source (tel qu'affiché) : traduction}. Les parties variables s'écrivent « {} »
(dans l'ordre) ou « {0} », « {1} »… dans la traduction si l'ordre des mots change.

Le français est la langue source ; le catalogue « fr » ne contient que les quelques
libellés restés en anglais dans le code (statuts des modèles…).
"""
import json
import re
from functools import lru_cache
from pathlib import Path

CATALOG_DIR = Path(__file__).resolve().parent / 'catalog'
LANGUAGES = [('en', 'English'), ('fr', 'Français'), ('de', 'Deutsch'), ('es', 'Español')]
LANGUAGE_CODES = [code for code, _ in LANGUAGES]
DEFAULT_LANGUAGE = 'fr'  # langue source des gabarits (aucune traduction à appliquer)
# Langue proposée aux visiteurs sans choix ni langue de navigateur prise en charge : marché américain d'abord.
FALLBACK_LANGUAGE = 'en'
COOKIE_NAME = 'billio_lang'

_WS = re.compile(r'\s+')
# « 09/10/2026 à 10:40 », « 10/10 à 10:00 » : le « à » des dates-heures suit la langue.
_DATETIME = re.compile(r'(\d{1,2}/\d{1,2}(?:/\d{2,4})?) à (\d{1,2}[:h]\d{2})')
_DATETIME_JOIN = {'en': r'\1 at \2', 'de': r'\1 um \2', 'es': r'\1 a las \2'}


class Catalog:
    def __init__(self, entries, lang='fr'):
        self.lang = lang
        self.exact = {}
        self.patterns = []  # (ancre littérale, regex, traduction, partie variable en tête, en fin)
        for source, target in entries.items():
            if not target or target == source:
                continue
            if '{}' in source:
                parts = source.split('{}')
                regex = re.compile('^' + '(.*?)'.join(re.escape(p) for p in parts) + '$', re.S)
                anchor = max(parts, key=len)
                # Partie variable collée à un mot (« facture{} », « {}ème ») : simple suffixe court.
                glued = [bool(parts[i][-1:].isalpha() or parts[i + 1][:1].isalpha()) for i in range(len(parts) - 1)]
                self.patterns.append((anchor, regex, target, source.startswith('{}'), source.endswith('{}'), glued, len(''.join(parts))))
            else:
                self.exact[source] = target
        # Les motifs les plus spécifiques (le plus de texte fixe) d'abord :
        # « dans {} jour{} » passe avant « {} jours ».
        self.patterns.sort(key=lambda p: (-p[6], -len(p[0])))
        self.patterns = [p[:6] for p in self.patterns]
        self._cache = {}

    def translate(self, text):
        """Traduit un texte complet (espaces de début/fin conservés), ou None s'il est inconnu."""
        key = _WS.sub(' ', text).strip()
        if not key:
            return None
        if key in self._cache:
            out = self._cache[key]
        else:
            out = self.exact.get(key)
            if out is None and any(c.isalpha() for c in key):
                for anchor, regex, target, lead, trail, glued in self.patterns:
                    if anchor and anchor not in key:
                        continue
                    m = regex.match(key)
                    if not m:
                        continue
                    groups = m.groups()
                    # Une partie variable en début ou fin de phrase reste courte (nombre, nom, pluriel) :
                    # sinon « {} facture{} » avalerait n'importe quelle phrase contenant « facture ».
                    if (lead and len(groups[0].split()) > 3) or (trail and len(groups[-1].split()) > 3):
                        continue
                    if any(g and not re.fullmatch(r'\w{1,3}', g) for g, glue in zip(groups, glued) if glue):
                        continue
                    # Les parties variables connues du catalogue (statuts…) sont traduites aussi.
                    out = _fill(target, [self.exact.get(g.strip(), g) for g in groups])
                    break
            if len(self._cache) < 20000:
                self._cache[key] = out
        join = _DATETIME_JOIN.get(self.lang)
        if join and _DATETIME.search(out if out is not None else key):
            out = _DATETIME.sub(join, out if out is not None else key)
        if out is None:
            return None
        lead = text[:len(text) - len(text.lstrip())]
        trail = text[len(text.rstrip()):]
        return f'{lead}{out}{trail}'

    def as_dict(self):
        """Pour le navigateur : {exact: {...}, patterns: [[source, cible], ...]}."""
        return self.exact, [[r.pattern, t, lead, trail, glued] for _, r, t, lead, trail, glued in self.patterns]


def _fill(template, groups):
    """« {} » dans l'ordre, ou « {0} », « {1} » pour réordonner."""
    if re.search(r'\{\d+\}', template):
        return re.sub(r'\{(\d+)\}', lambda m: groups[int(m.group(1))] if int(m.group(1)) < len(groups) else '', template)
    it = iter(groups)
    return re.sub(r'\{\}', lambda m: next(it, ''), template)


@lru_cache(maxsize=8)
def _load(lang, mtime):
    path = CATALOG_DIR / f'{lang}.json'
    try:
        entries = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        entries = {}
    return Catalog(entries, lang)


def get_catalog(lang):
    """Catalogue d'une langue (rechargé automatiquement si le fichier change)."""
    path = CATALOG_DIR / f'{lang}.json'
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0
    return _load(lang, mtime)


def catalog_version(lang):
    try:
        return str(int((CATALOG_DIR / f'{lang}.json').stat().st_mtime))
    except OSError:
        return '0'
