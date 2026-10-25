"""
Assistant de démarrage : configure Billio selon le métier, le pays et les préférences.

Proposé juste après l'inscription (``billing_preferences['onboarding']['state'] == 'pending'``),
chaque étape peut être passée, et l'assistant entier aussi. Il se relance depuis Paramètres › Métier.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.organizations import jurisdictions as j
from apps.organizations.trade_packs import TRADE_PACKS, apply_trade_pack

STEPS = ('activity', 'country', 'preferences')
PAYMENT_DAYS = ((0, 'À réception'), (15, '15 jours'), (30, '30 jours'), (45, '45 jours'), (60, '60 jours'))
# Ce que l'on veut faire avec Billio → prochaines étapes proposées à la fin.
INTERESTS = {
    'invoices': ('Factures & devis', 'receipt', 'Créer votre premier devis', 'invoices:quote-create'),
    'online': ('Paiement en ligne', 'credit-card', 'Activer le paiement en ligne', 'accounts:user-settings', 'paiement'),
    'projects': ('Projets & tâches', 'folder-kanban', 'Ouvrir vos projets', 'dashboard:project-board'),
    'time': ('Suivi du temps', 'timer', 'Suivre le temps passé sur un projet', 'dashboard:project-board'),
    'booking': ('Rendez-vous en ligne', 'calendar-check', 'Ouvrir la prise de rendez-vous', 'accounts:user-settings', 'rdv'),
    'automations': ('Relances & automatisations', 'workflow', 'Automatiser vos relances', 'dashboard:automation-builder'),
}


def _organization(user):
    from .views import get_editable_organization_for_settings
    return get_editable_organization_for_settings(user)


def state(organization):
    return ((organization.billing_preferences or {}).get('onboarding') or {}).get('state', '')


def is_pending(user):
    organization = _organization(user)
    return bool(organization and state(organization) == 'pending')


def mark_pending(organization):
    prefs = dict(organization.billing_preferences or {})
    prefs['onboarding'] = {'state': 'pending'}
    organization.billing_preferences = prefs
    organization.save(update_fields=['billing_preferences', 'updated_at'])


def _mark(organization, new_state, **extra):
    organization.refresh_from_db()
    prefs = dict(organization.billing_preferences or {})
    prefs['onboarding'] = {'state': new_state, 'at': timezone.now().isoformat(timespec='seconds'), **extra}
    organization.billing_preferences = prefs
    organization.save(update_fields=['billing_preferences', 'updated_at'])


def _url(spec):
    url = reverse(spec[3])
    return f'{url}?tab={spec[4]}' if len(spec) > 4 else url


def next_steps(organization):
    """Prochaines étapes d'après les envies cochées (factures d'abord si rien n'est coché)."""
    chosen = ((organization.billing_preferences or {}).get('onboarding') or {}).get('interests') or ['invoices']
    steps = [{'label': 'Ajouter votre premier client', 'icon': 'user-plus', 'url': reverse('clients:client-list')}]
    seen = set()
    for key in chosen:
        spec = INTERESTS.get(key)
        if spec and _url(spec) not in seen:
            seen.add(_url(spec))
            steps.append({'label': spec[2], 'icon': spec[1], 'url': _url(spec)})
    if 'invoices' not in chosen:
        steps.append({'label': 'Créer votre première facture', 'icon': 'receipt', 'url': reverse('invoices:invoice-create')})
    return steps


def _apply(request, organization):
    """Applique les étapes non passées ; renvoie la liste des étapes appliquées."""
    post = request.POST
    applied = []
    if post.get('skip_activity') != '1':
        name = (post.get('name') or '').strip()[:200]
        if name and name != organization.name:
            organization.name = name
            organization.save(update_fields=['name', 'updated_at'])
        trade = post.get('trade')
        if trade in TRADE_PACKS and trade != organization.trade:
            apply_trade_pack(organization, trade, user=request.user)
            organization.refresh_from_db()
        applied.append('activity')

    prof = j.profile(organization)
    if post.get('skip_country') != '1':
        country = (post.get('country') or '').upper()
        if country == 'OTHER':
            country = prof['country'] if prof['country'] not in j.PACKS else ''
        prof.update({'country': country, 'status': post.get('status'),
                     'tax_registered': post.get('tax_registered') == 'yes', 'confirmed': True})
        if country != 'CA':
            prof['region'] = ''
        prof = j.apply_profile(organization, prof)
        organization.refresh_from_db()
        applied.append('country')

    interests = []
    if post.get('skip_preferences') != '1':
        if post.get('doc_language') in j.DOC_LANGUAGES and post.get('doc_language') != prof['doc_language']:
            j.apply_profile(organization, {**prof, 'doc_language': post.get('doc_language')})
            organization.refresh_from_db()
        prefs = dict(organization.billing_preferences or {})
        fields = ['billing_preferences', 'updated_at']
        try:
            days = int(post.get('payment_days'))
        except (TypeError, ValueError):
            days = None
        if days is not None and 0 <= days <= 60:
            prefs['payment_days'] = days
            organization.default_payment_terms = days
            fields.append('default_payment_terms')
        prefix = ''.join(ch for ch in (post.get('invoice_prefix') or '').upper() if ch.isalnum() or ch in '-_/')[:10]
        if prefix:
            organization.invoice_prefix = prefix
            fields.append('invoice_prefix')
        organization.billing_preferences = prefs
        organization.save(update_fields=fields)
        interests = [key for key in post.getlist('interests') if key in INTERESTS]
        applied.append('preferences')
    _mark(organization, 'done', steps=applied, interests=interests)
    return applied


@login_required
def onboarding_view(request):
    organization = _organization(request.user)
    if organization is None:
        return redirect('organizations:organization-list')
    home = reverse('dashboard:dashboard-home')

    if request.method == 'POST':
        if request.POST.get('form_action') == 'skip':
            _mark(organization, 'skipped')
            messages.info(request, 'Configuration passée : vous la retrouvez à tout moment dans Paramètres › Métier & modèles.')
            return redirect(home)
        _apply(request, organization)
        return redirect(f"{reverse('accounts:onboarding')}?done=1")

    if request.GET.get('done') and state(organization) == 'done':
        return render(request, 'accounts/onboarding.html', {
            'done': True, 'organization': organization, 'next_steps': next_steps(organization), 'home_url': home,
        })

    prof = j.profile(organization)
    prefs = organization.billing_preferences or {}
    saved = prefs.get('onboarding') or {}
    trades = [{'key': key, 'label': p['label'], 'description': p['description'], 'icon': p['icon'],
               'phases': [label for _k, label, _c in p['phases'] if _k != 'completed'],
               'templates': [t['name'] for t in p['templates']]} for key, p in TRADE_PACKS.items()]
    countries = [(code, j.PACKS[code]['name']) for code in j.SUPPORTED]
    return render(request, 'accounts/onboarding.html', {
        'organization': organization,
        'trades': trades,
        'countries': countries,
        'statuses': [(key, j.STATUS_LABELS[key]) for key in j.STATUSES],
        'languages': list(j.DOC_LANGUAGES.items()),
        'payment_days': PAYMENT_DAYS,
        'interests': [(key, spec[0], spec[1]) for key, spec in INTERESTS.items()],
        'home_url': home,
        'initial': {
            'name': organization.name,
            'trade': organization.trade if organization.trade in TRADE_PACKS else '',
            'country': prof['country'] if prof['country'] in j.PACKS else 'OTHER',
            'status': prof['status'],
            'tax': 'yes' if prof['tax_registered'] else 'no',
            'language': prof['doc_language'],
            'days': int(prefs.get('payment_days', organization.default_payment_terms or 30)),
            'prefix': organization.invoice_prefix or 'FAC',
            'interests': saved.get('interests') or ['invoices'],
        },
        'country_data': j.assistant_data(),
        'trade_labels': {t['key']: t['label'] for t in trades},
        'status_labels': j.STATUS_LABELS,
        'days_labels': {str(days): label for days, label in PAYMENT_DAYS},
    })
