"""Consentement aux cookies (UE : RGPD + ePrivacy ; États-Unis : CCPA/CPRA et lois des États).

On applique partout la règle la plus stricte (consentement préalable, « opt-in ») :
- rien de facultatif n'est déposé ni mesuré avant un choix explicite ;
- « Tout refuser » est aussi visible et aussi simple que « Tout accepter » ;
- le choix est modifiable à tout moment (lien « Gérer les cookies ») et redemandé après 6 mois
  ou quand la liste des finalités change (CONSENT_VERSION) ;
- le signal Global Privacy Control (en-tête Sec-GPC / navigator.globalPrivacyControl) vaut refus,
  comme l'exigent la Californie et plusieurs États américains ; Billio ne vend ni ne partage de
  données personnelles (lien « Ne pas vendre ou partager mes informations ») ;
- chaque choix est journalisé sans donnée identifiante (ConsentRecord) pour pouvoir le prouver.

Le bandeau (static/js/consent.js) est ajouté par ConsentMiddleware aux pages du site public, pour les
visiteurs non connectés. Les utilisateurs de l'application ont accepté les conditions d'utilisation, la
politique de confidentialité et la politique cookies en cochant la case obligatoire de l'inscription
(User.terms_accepted_at) ; ils n'ont donc pas de bandeau dans le tableau de bord. Les
scripts facultatifs se déclarent `<script type="text/plain" data-consent="analytics">` : ils ne
s'exécutent qu'après accord. Côté serveur, `analytics_allowed(request)` conditionne la mesure
d'audience des visiteurs anonymes (apps.staff.metrics).
"""
import json
import re

from django.conf import settings
from django.http import HttpResponseBadRequest, JsonResponse
from django.templatetags.static import static
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

COOKIE_NAME = 'billio_consent'
CONSENT_VERSION = 1
CATEGORIES = ('analytics',)
SKIP_PATHS = re.compile(r'^/(?:static|media|healthz|i18n/catalog)/')
# Espaces d'administration (Administration Billio et admin Django) : pas de bandeau.
ADMIN_PREFIXES = ('/staff/', '/' + getattr(settings, 'ADMIN_URL', 'admin/').lstrip('/'))


def gpc(request):
    return request.META.get('HTTP_SEC_GPC', '').strip() == '1'


def read_choice(request):
    """Choix enregistré dans le cookie ({'analytics': bool}) ou None s'il n'y en a pas (ou plus à jour)."""
    raw = request.COOKIES.get(COOKIE_NAME, '')
    # Format : v<version>.<catégorie>-<0|1>...  ex. « v1.analytics-1 »
    parts = raw.split('.')
    if not parts or parts[0] != f'v{CONSENT_VERSION}':
        return None
    choice = {}
    for part in parts[1:]:
        name, _, value = part.partition('-')
        if name in CATEGORIES:
            choice[name] = value == '1'
    return choice


def analytics_allowed(request):
    if gpc(request):
        return False
    return bool((read_choice(request) or {}).get('analytics'))


class ConsentMiddleware:
    """Ajoute le bandeau de consentement (CSS + script) à chaque page HTML."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.tags = None

    def __call__(self, request):
        response = self.get_response(request)
        if (response.streaming or response.status_code != 200 or SKIP_PATHS.search(request.path)
                or request.path.startswith(ADMIN_PREFIXES)
                or getattr(getattr(request, 'user', None), 'is_authenticated', False)
                or 'text/html' not in response.get('Content-Type', '') or response.get('Content-Encoding')):
            return response
        markup = response.content.decode(response.charset or 'utf-8', errors='replace')
        if '</head>' not in markup or 'data-billio-consent' in markup:
            return response
        if self.tags is None:
            self.tags = (f'<link rel="stylesheet" href="{static("css/consent.css")}?v=1.0" data-billio-consent>'
                         f'<script src="{static("js/consent.js")}?v=1.0" defer></script>')
        response.content = markup.replace('</head>', self.tags + '</head>', 1).encode(response.charset or 'utf-8')
        if response.has_header('Content-Length'):
            response['Content-Length'] = str(len(response.content))
        return response


@csrf_exempt  # simple journal du choix, sans effet sur le compte ; le cookie est posé par le navigateur
@require_POST
def record_consent(request):
    from .models import ConsentRecord
    try:
        data = json.loads(request.body[:2000] or b'{}')
    except ValueError:
        return HttpResponseBadRequest()
    consent_id = str(data.get('id', ''))[:36]
    if not re.fullmatch(r'[0-9a-f-]{8,36}', consent_id):
        return HttpResponseBadRequest()
    choices = {name: bool((data.get('choices') or {}).get(name)) for name in CATEGORIES}
    ConsentRecord.objects.create(
        consent_id=consent_id, version=CONSENT_VERSION, choices=choices,
        action=str(data.get('action', ''))[:20], gpc=bool(data.get('gpc')) or gpc(request),
        user_agent=request.META.get('HTTP_USER_AGENT', '')[:200], page=str(data.get('page', ''))[:200])
    return JsonResponse({'ok': True})
