"""
Langue de l'interface (cookie « billio_lang », français par défaut) et traduction des pages HTML.

1. LanguageMiddleware active la langue choisie (dates et formats Django suivent).
2. HtmlTranslationMiddleware traduit les textes et libellés (placeholder, title…) des pages
   rendues, hors zones de contenu marquées translate="no" (documents, aperçus de factures…),
   et ajoute le script qui traduit aussi les textes créés ensuite par le JavaScript.
"""
import html
import re

from django.utils import translation

from .catalog import COOKIE_NAME, DEFAULT_LANGUAGE, FALLBACK_LANGUAGE, LANGUAGE_CODES, catalog_version, get_catalog

# Aperçus de modèles de facture / document : c'est du contenu, pas de l'interface.
SKIP_PATHS = re.compile(r'^/(admin|static|media)/|/api/|^/templates/.*preview|/pdf/?$')
_TOKEN = re.compile(r'<!--.*?-->|<(?:"[^"]*"|\'[^\']*\'|[^\'">])*>', re.S)
_TAG_NAME = re.compile(r'^</?\s*([a-zA-Z][\w:-]*)')
_RAW_TAGS = {'script', 'style', 'textarea', 'code', 'pre', 'svg'}
_VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'source', 'track', 'wbr'}
_ATTR = re.compile(r'''(\s(?:placeholder|title|aria-label|alt|data-tip|data-kbd|label))=(["'])(.*?)\2''', re.S)
_VALUE_ATTR = re.compile(r'''(\svalue)=(["'])(.*?)\2''', re.S)
_NO_TRANSLATE = re.compile(r'''\stranslate=["']no["']|\sdata-no-translate\b''')



def _browser_language(request):
    """Première langue prise en charge dans l'en-tête Accept-Language (ex. « de-DE,de;q=0.9,en;q=0.8 »)."""
    for part in (request.META.get('HTTP_ACCEPT_LANGUAGE') or '').split(','):
        code = part.split(';')[0].strip().lower()[:2]
        if code in LANGUAGE_CODES:
            return code
    return None


def request_language(request):
    """
    Utilisateur connecté : la langue enregistrée sur son compte (Paramètres › Langue), sur tous ses appareils.
    Sinon : le cookie du sélecteur, puis la langue du navigateur, puis l'anglais (marché américain d'abord).
    """
    user = getattr(request, 'user', None)
    if user is not None and user.is_authenticated and getattr(user, 'language', '') in LANGUAGE_CODES:
        return user.language
    lang = (request.COOKIES.get(COOKIE_NAME) or '').lower()[:2]
    if lang in LANGUAGE_CODES:
        return lang
    return _browser_language(request) or FALLBACK_LANGUAGE


class LanguageMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        lang = request_language(request)
        translation.activate(lang)
        request.LANGUAGE_CODE = lang
        response = self.get_response(request)
        response.headers.setdefault('Content-Language', lang)
        translation.deactivate()
        return response


def translate_html(markup, catalog):
    """Traduit les nœuds texte et les attributs d'interface d'une page HTML."""
    out = []
    pos = 0
    zone_tag, zone_depth = None, 0
    n = len(markup)

    def tr_text(raw):
        if not raw.strip():
            return raw
        done = catalog.translate(html.unescape(raw))
        return html.escape(done, quote=False) if done is not None else raw

    def tr_attr(m):
        done = catalog.translate(html.unescape(m.group(3)))
        if done is None:
            return m.group(0)
        return f'{m.group(1)}={m.group(2)}{html.escape(done, quote=True)}{m.group(2)}'

    while pos < n:
        m = _TOKEN.search(markup, pos)
        text = markup[pos:m.start()] if m else markup[pos:]
        out.append(text if zone_tag else tr_text(text))
        if not m:
            break
        tag = m.group(0)
        pos = m.end()
        if tag.startswith('<!--'):
            out.append(tag)
            continue
        name_m = _TAG_NAME.match(tag)
        name = name_m.group(1).lower() if name_m else ''
        closing = tag.startswith('</')
        if zone_tag:
            if name == zone_tag and not tag.endswith('/>'):
                zone_depth += -1 if closing else 1
                if zone_depth == 0:
                    zone_tag = None
            out.append(tag)
        elif closing:
            out.append(tag)
        else:
            if _NO_TRANSLATE.search(tag) and name not in _VOID and not tag.endswith('/>'):
                zone_tag, zone_depth = name, 1
                out.append(tag)
            else:
                tag = _ATTR.sub(tr_attr, tag)
                if name in ('input', 'button') and re.search(r'''type=["'](submit|button)["']''', tag):
                    tag = _VALUE_ATTR.sub(tr_attr, tag)
                out.append(tag)
        if name in _RAW_TAGS and not closing and not tag.endswith('/>'):
            end = re.compile(rf'</{name}\s*>', re.I).search(markup, pos)
            stop = end.start() if end else n
            out.append(markup[pos:stop])
            pos = stop
    return ''.join(out)


class HtmlTranslationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        lang = getattr(request, 'LANGUAGE_CODE', DEFAULT_LANGUAGE)
        if (
            response.streaming
            or 'text/html' not in response.get('Content-Type', '')
            or response.status_code >= 300
            or SKIP_PATHS.search(request.path)
            or response.get('Content-Encoding')
        ):
            return response
        catalog = get_catalog(lang)
        markup = response.content.decode(response.charset or 'utf-8', errors='replace')
        is_page = '</head>' in markup
        if catalog.exact or catalog.patterns:
            markup = translate_html(markup, catalog)
        if is_page:
            version = catalog_version(lang)
            # defer : le catalogue (~145 Kio en anglais) ne bloque plus l'affichage. La page est déjà
            # traduite par le serveur ; i18n.js traduit encore tout le body à DOMContentLoaded.
            head = (
                f'<script src="/i18n/catalog/{lang}.js?v={version}" defer></script>'
                f'<script src="/static/js/i18n.js?v=1.2" defer></script>'
            )
            markup = markup.replace('</head>', head + '</head>', 1)
            markup = re.sub(r'<html([^>]*)\slang="[^"]*"', rf'<html\1 lang="{lang}"', markup, count=1)
        response.content = markup.encode(response.charset or 'utf-8')
        if response.has_header('Content-Length'):
            response['Content-Length'] = str(len(response.content))
        return response
