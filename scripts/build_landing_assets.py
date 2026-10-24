"""Régénère les ressources compilées des pages publiques (landing + pages légales).

    python scripts/build_landing_assets.py

- static/css/landing-tw.css : Tailwind compilé avec les seules classes utilisées
  (remplace le script cdn.tailwindcss.com, ~124 Kio de JS bloquant) ;
- apps/landing/lucide_icons.json : les icônes Lucide de la landing, insérées en SVG
  par le serveur (remplace la bibliothèque lucide complète, ~106 Kio de JS).

À relancer après avoir ajouté des classes Tailwind ou des icônes data-lucide dans
templates/landing/. Demande Node.js (npx) ; le résultat est commité, l'image Docker
n'en a pas besoin.
"""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TAILWIND = 'tailwindcss@3.4.17'
LUCIDE = 'lucide-static@1.61.0'
ICON_SOURCES = ['templates/landing/*.html']
ICONS_JSON = ROOT / 'apps' / 'landing' / 'lucide_icons.json'


def npx(*args, cwd=ROOT):
    subprocess.run(['npx', '--yes', *args], cwd=cwd, check=True, shell=sys.platform == 'win32')


def build_tailwind():
    npx(TAILWIND, '-c', 'tailwind.landing.config.js', '-i', 'static/src/landing-tw.css',
        '-o', 'static/css/landing-tw.css', '--minify')


def build_icons():
    names = set()
    for pattern in ICON_SOURCES:
        for path in ROOT.glob(pattern):
            names.update(re.findall(r'data-lucide="([\w-]+)"', path.read_text(encoding='utf-8')))
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(['npm', 'install', '--no-save', '--ignore-scripts', '--prefix', tmp, LUCIDE],
                       check=True, shell=sys.platform == 'win32')
        folder = Path(tmp) / 'node_modules' / 'lucide-static' / 'icons'
        icons = {}
        for name in sorted(names):
            svg = (folder / f'{name}.svg').read_text(encoding='utf-8')
            inner = re.search(r'<svg[^>]*>(.*)</svg>', svg, re.S).group(1)
            icons[name] = re.sub(r'\s*\n\s*', '', inner)
    ICONS_JSON.write_text(json.dumps(icons, indent=1, sort_keys=True) + '\n', encoding='utf-8')
    print(f'{len(icons)} icônes Lucide -> {ICONS_JSON.relative_to(ROOT)}')


if __name__ == '__main__':
    build_tailwind()
    build_icons()
