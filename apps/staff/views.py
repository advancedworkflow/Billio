"""Petit espace d'administration de la plateforme (super-administrateurs uniquement).

Vue d'ensemble (inscriptions, abonnements, factures émises), gestion des comptes (activer, offrir un
forfait) et clés des intégrations « Se connecter avec… » saisies sans toucher au serveur.
"""
from datetime import timedelta
from decimal import Decimal
from functools import wraps

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .platform import set_setting, source


def superuser_required(view):
    @login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_superuser:
            raise Http404
        return view(request, *args, **kwargs)
    return wrapper


@superuser_required
def overview(request):
    from apps.dashboard.models import SupportTicket
    from apps.invoices.models import Invoice
    from apps.organizations.models import Organization
    from apps.subscriptions.models import Plan, Subscription

    User = get_user_model()
    now = timezone.now()
    users = User.objects.all()
    issued = Invoice.objects.filter(invoice_type='sale', issue_date__gte=(now - timedelta(days=30)).date()) \
        .exclude(status__in=('draft', 'cancelled'))

    plans = []
    mrr = Decimal('0')
    for plan in Plan.objects.order_by('order', 'price_monthly'):
        subs = [s for s in Subscription.objects.filter(plan=plan) if s.grants_plan]
        paying = sum(1 for s in subs if not s.comped)
        offered = len(subs) - paying
        mrr += plan.price_monthly * paying
        plans.append({'plan': plan, 'paying': paying, 'offered': offered, 'revenue': plan.price_monthly * paying})
    with_plan = sum(p['paying'] + p['offered'] for p in plans if p['plan'].code != 'free')

    return render(request, 'staff/overview.html', {
        'tab': 'overview',
        'stats': {
            'users': users.count(),
            'new_7': users.filter(date_joined__gte=now - timedelta(days=7)).count(),
            'new_30': users.filter(date_joined__gte=now - timedelta(days=30)).count(),
            'active_30': users.filter(last_login__gte=now - timedelta(days=30)).count(),
            'organizations': Organization.objects.count(),
            'invoices_30': issued.count(),
            'invoiced_30': issued.aggregate(total=Sum('total_amount'))['total'] or Decimal('0'),
            'mrr': mrr,
            'tickets_open': SupportTicket.objects.filter(status='open').count(),
            'free_users': max(users.count() - with_plan, 0),
        },
        'plans': [p for p in plans if p['plan'].code != 'free'],
        'recent': users.order_by('-date_joined')[:8],
    })


@superuser_required
def users(request):
    from apps.subscriptions.models import Plan

    User = get_user_model()
    q = request.GET.get('q', '').strip()
    qs = User.objects.select_related('subscription__plan').prefetch_related('owned_organizations').order_by('-date_joined')
    if q:
        qs = qs.filter(Q(email__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q)
                       | Q(owned_organizations__name__icontains=q)).distinct()
    page = Paginator(qs, 40).get_page(request.GET.get('page'))
    rows = []
    for u in page:
        sub = getattr(u, 'subscription', None)
        rows.append({
            'user': u, 'org': u.owned_organizations.all()[:1],
            'plan': sub.plan if sub and sub.grants_plan else None,
            'comped': bool(sub and sub.comped), 'stripe': bool(sub and sub.stripe_subscription_id),
        })
    return render(request, 'staff/users.html', {
        'tab': 'users', 'rows': rows, 'page': page, 'q': q,
        'plans': Plan.objects.filter(is_active=True).exclude(code='free').order_by('order', 'price_monthly'),
    })


@superuser_required
@require_POST
def user_action(request, user_id):
    from apps.subscriptions.entitlements import free_plan
    from apps.subscriptions.models import Plan, Subscription

    User = get_user_model()
    target = get_object_or_404(User, pk=user_id)
    action = request.POST.get('action')
    back = request.POST.get('next') or reverse('staff:users')
    if not back.startswith('/'):
        back = reverse('staff:users')

    if action == 'toggle_active':
        if target == request.user:
            messages.error(request, 'Vous ne pouvez pas désactiver votre propre compte.')
        else:
            target.is_active = not target.is_active
            target.save(update_fields=['is_active'])
            if target.is_active:
                messages.success(request, f'Compte réactivé : {target.email}.')
            else:
                messages.success(request, f'Compte désactivé : {target.email}.')
    elif action == 'offer_plan':
        code = request.POST.get('plan', '')
        sub = Subscription.objects.filter(user=target).first()
        if code:
            plan = get_object_or_404(Plan, code=code)
            if sub and sub.stripe_subscription_id and sub.grants_plan and not sub.comped:
                messages.error(request, 'Ce compte a un abonnement Stripe en cours : modifiez-le depuis Stripe.')
                return redirect(back)
            Subscription.objects.update_or_create(user=target, defaults={'plan': plan, 'status': 'active', 'comped': True})
            messages.success(request, f'Forfait {plan.name} offert à {target.email}.')
        elif sub and sub.comped:
            sub.comped = False
            if not sub.stripe_subscription_id:
                sub.plan, sub.status = free_plan(), 'free'
            sub.save()
            messages.success(request, f'Forfait offert retiré : {target.email}.')
    return redirect(back)


@superuser_required
def keys(request):
    from apps.integrations import oauth

    tools = []
    for key, spec in oauth.OAUTH.items():
        tools.append({
            'key': key, 'name': spec['name'], 'console': spec['console'], 'steps': spec['steps'],
            'ready': oauth.configured(key),
            'redirect': request.build_absolute_uri(reverse('integrations:oauth-callback', args=[key])),
            'origin': request.build_absolute_uri('/').rstrip('/'),
            'fields': [{'name': name, 'source': source(name), 'secret': 'SECRET' in name} for name in spec['env']],
        })

    if request.method == 'POST':
        tool = next((t for t in tools if t['key'] == request.POST.get('tool')), None)
        if tool:
            changed = False
            for field in tool['fields']:
                if field['source'] == 'env':
                    continue
                if request.POST.get(f"clear_{field['name']}"):
                    set_setting(field['name'], '', request.user)
                    changed = True
                elif request.POST.get(field['name'], '').strip():
                    set_setting(field['name'], request.POST[field['name']], request.user)
                    changed = True
            if changed:
                messages.success(request, f"Clés {tool['name']} enregistrées.")
        return redirect(f"{reverse('staff:keys')}#{request.POST.get('tool', '')}")

    return render(request, 'staff/keys.html', {'tab': 'keys', 'tools': tools})
