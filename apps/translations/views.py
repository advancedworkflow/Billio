"""Choix de la langue et catalogue de traduction servi au navigateur."""
import json

from django.http import HttpResponse, HttpResponseRedirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import cache_control

from .catalog import COOKIE_NAME, LANGUAGE_CODES, get_catalog


def set_language(request, lang):
    """
    /i18n/set/<langue>/?next=… : mémorise la langue et revient à la page.
    Connecté : enregistrée sur le compte (tous les appareils) ; dans tous les cas, cookie d'un an.
    """
    target = request.GET.get('next') or request.META.get('HTTP_REFERER') or '/'
    if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        target = '/'
    response = HttpResponseRedirect(target)
    if lang in LANGUAGE_CODES:
        user = getattr(request, 'user', None)
        if user is not None and user.is_authenticated and getattr(user, 'language', None) != lang:
            user.language = lang
            user.save(update_fields=['language'])
        response.set_cookie(COOKIE_NAME, lang, max_age=365 * 24 * 3600, samesite='Lax')
    return response


@cache_control(public=True, max_age=31536000)
def catalog_js(request, lang):
    """Catalogue pour static/js/i18n.js (URL versionnée par la date du fichier)."""
    if lang not in LANGUAGE_CODES:
        lang = 'fr'
    exact, patterns = get_catalog(lang).as_dict()
    payload = json.dumps({'lang': lang, 'exact': exact, 'patterns': patterns}, ensure_ascii=False, separators=(',', ':'))
    payload = payload.replace('</', r'<\/')  # « </script> » neutralisé dans le JS généré
    return HttpResponse(f'window.__billioI18n={payload};', content_type='application/javascript; charset=utf-8')
