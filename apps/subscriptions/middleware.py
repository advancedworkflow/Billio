"""
Applique les forfaits pendant les requêtes des utilisateurs connectés et transforme un
dépassement (FeatureLocked / QuotaExceeded) en message clair :
- action en arrière-plan (fetch, HTMX, API) : JSON 403 {success, message, upgrade_url} ;
- formulaire classique : message + retour à la page précédente.
"""
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme

from .entitlements import Locked, enforce


def _wants_json(request):
    headers = request.headers
    return bool(
        'application/json' in headers.get('Accept', '')
        or headers.get('HX-Request')
        or headers.get('X-Requested-With') == 'XMLHttpRequest'
        or headers.get('Sec-Fetch-Mode', 'navigate') != 'navigate'
        or '/api/' in request.path
        or (headers.get('Content-Type') or '').startswith('application/json')
    )


class EntitlementsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        active = bool(user and user.is_authenticated and not user.is_superuser)
        with enforce(active):
            return self.get_response(request)

    def process_exception(self, request, exception):
        if not isinstance(exception, Locked):
            return None
        if _wants_json(request):
            return JsonResponse({
                'success': False, 'error': exception.message, 'message': exception.message,
                'detail': exception.message, 'upgrade_url': exception.upgrade_url, 'code': 'plan_limit',
            }, status=403)
        messages.warning(request, exception.message)
        back = request.headers.get('Referer')
        if back and url_has_allowed_host_and_scheme(back, allowed_hosts={request.get_host()}):
            return redirect(back)
        return redirect(exception.upgrade_url)
