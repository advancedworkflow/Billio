"""Icônes Lucide de la landing insérées en SVG par le serveur, sans la bibliothèque JS.

Les tracés viennent de lucide_icons.json (scripts/build_landing_assets.py), et chaque
<i data-lucide="nom" class="…"></i> devient le <svg> que lucide.createIcons() produisait.
"""
import json
import re
from functools import lru_cache
from pathlib import Path

ICON_TAG = re.compile(r'<i data-lucide="([\w-]+)"(?: class="([^"]*)")?></i>')
SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" '
       'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
       'class="lucide lucide-{name} {cls}" aria-hidden="true">{body}</svg>')


@lru_cache(maxsize=1)
def icons():
    return json.loads((Path(__file__).with_name('lucide_icons.json')).read_text(encoding='utf-8'))


def inline_icons(markup):
    def svg(match):
        body = icons().get(match.group(1))
        if body is None:  # icône absente du JSON : relancer scripts/build_landing_assets.py
            return match.group(0)
        return SVG.format(name=match.group(1), cls=match.group(2) or '', body=body)
    return ICON_TAG.sub(svg, markup)


def inline_icons_callback(response):
    """post_render_callback d'une TemplateResponse."""
    response.content = inline_icons(response.content.decode('utf-8')).encode('utf-8')
    return response
