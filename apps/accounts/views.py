"""
Views for accounts app.
"""
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from rest_framework import viewsets, status, generics
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.authtoken.models import Token
from django.contrib.auth import login, logout
from django.utils.translation import gettext_lazy as _
from .models import User, UserProfile
from .serializers import (
    UserSerializer, UserProfileSerializer, RegisterSerializer,
    LoginSerializer, ChangePasswordSerializer, UserProfileUpdateSerializer
)
from .forms import LoginForm, RegisterForm
from django.conf import settings
from django.contrib.auth import views as auth_views
from django.urls import reverse, reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from decimal import Decimal
from apps.organizations.models import Organization, OrganizationMember


def _normalize_iban(value):
    return ''.join((value or '').split()).upper()[:34]


def _normalize_bic(value):
    return ''.join((value or '').split()).upper()[:11]


def list_editable_organizations_for_payment(user):
    """
    Organisations dont l’utilisateur peut modifier les infos de paiement :
    propriétaire, ou admin avec droit d’édition (sans doublon).
    """
    result = []
    seen = set()
    for o in Organization.objects.filter(owner=user).order_by('name'):
        result.append(o)
        seen.add(o.id)
    memberships = OrganizationMember.objects.filter(
        user=user,
        can_edit_organization=True,
        role__in=('owner', 'admin'),
    ).select_related('organization').order_by('organization__name')
    for m in memberships:
        if m.organization_id not in seen:
            result.append(m.organization)
            seen.add(m.organization_id)
    return result


def _org_payment_bootstrap_dict(org):
    return {
        'id': str(org.id),
        'name': org.name,
        'preferred_payment_method': org.preferred_payment_method or 'bank_transfer',
        'bank_name': org.bank_name or '',
        'iban': org.iban or '',
        'bic_swift': org.bic_swift or '',
        'payment_instructions': org.payment_instructions or '',
    }


_PAYMENT_METHOD_KEYS = frozenset(dict(Organization.PAYMENT_METHOD_CHOICES).keys())


def get_editable_organization_for_settings(user):
    """Compat : première organisation éditable (ancien code)."""
    orgs = list_editable_organizations_for_payment(user)
    return orgs[0] if orgs else None


def _safe_next(request):
    """Paramètre ?next= seulement s'il pointe vers Billio (pas de redirection ouverte)."""
    next_url = request.GET.get('next') or request.POST.get('next')
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()},
                                                    require_https=request.is_secure()):
        return next_url
    return None


def login_view(request):
    """HTML view for user login."""
    if request.user.is_authenticated:
        return redirect('dashboard:dashboard-home')

    if request.method == 'POST':
        from .throttle import BLOCKED_MESSAGE, clear_login_failures, login_blocked, record_login_failure
        form = LoginForm(data=request.POST)
        if form.is_valid() and login_blocked(request, form.cleaned_data.get('email')):
            form.add_error(None, BLOCKED_MESSAGE)
        elif form.is_valid():
            user = authenticate(request, username=form.cleaned_data.get('email'),
                                password=form.cleaned_data.get('password'))
            if user is None:
                record_login_failure(request, form.cleaned_data.get('email'))
            else:
                clear_login_failures(request, form.cleaned_data.get('email'))
            if user is not None and user.totp_enabled_at:
                # Mot de passe correct : la session n'est ouverte qu'après le code de double authentification.
                import time
                from . import two_factor
                request.session[two_factor.SESSION_PENDING] = {
                    'user': user.pk, 'backend': user.backend, 'next': _safe_next(request) or '',
                    'at': int(time.time())}
                return redirect('accounts:login-2fa')
            if user is not None:
                auth_login(request, user)
                messages.success(request, f'Bienvenue, {user.get_full_name() or user.email}!')
                return redirect(_safe_next(request) or 'dashboard:dashboard-home')
            # Message unique : ne pas révéler si l'adresse a un compte.
            form.add_error(None, 'Email ou mot de passe incorrect.')
        else:
            messages.error(request, 'Veuillez corriger les erreurs ci-dessous.')
    else:
        form = LoginForm()

    return render(request, 'auth/login.html', {'form': form})


def login_2fa_view(request):
    """Deuxième étape de la connexion : code de l'application d'authentification ou code de secours."""
    import time
    from . import two_factor
    from .throttle import BLOCKED_MESSAGE, login_blocked, record_login_failure
    pending = request.session.get(two_factor.SESSION_PENDING) or {}
    user = User.objects.filter(pk=pending.get('user'), is_active=True).first() if pending else None
    if user is None or not user.totp_enabled_at or time.time() - pending.get('at', 0) > two_factor.PENDING_TTL:
        request.session.pop(two_factor.SESSION_PENDING, None)
        if pending:
            messages.info(request, 'Session expirée : reconnectez-vous.')
        return redirect('accounts:login')

    error = ''
    if request.method == 'POST':
        if login_blocked(request, user.email):
            error = BLOCKED_MESSAGE
        else:
            used = two_factor.check(user, request.POST.get('code'))
            if used:
                request.session.pop(two_factor.SESSION_PENDING, None)
                auth_login(request, user, backend=pending.get('backend'))
                messages.success(request, f'Bienvenue, {user.get_full_name() or user.email}!')
                if used == 'recovery':
                    left = len(user.totp_recovery_codes)
                    messages.warning(request, f'Code de secours utilisé : il vous en reste {left}. Générez-en de nouveaux dans Paramètres › Sécurité.')
                return redirect(pending.get('next') or 'dashboard:dashboard-home')
            record_login_failure(request, user.email)
            error = 'Code incorrect ou expiré.'
    return render(request, 'auth/login_2fa.html', {'error': error})


class BillioPasswordResetView(auth_views.PasswordResetView):
    """« Mot de passe oublié » : le lien de l'email est construit sur SITE_URL (jamais sur l'en-tête Host)."""
    template_name = 'auth/password_reset/form.html'
    email_template_name = 'auth/password_reset/email.txt'
    html_email_template_name = 'auth/password_reset/email.html'
    subject_template_name = 'auth/password_reset/email_subject.txt'
    success_url = reverse_lazy('accounts:password-reset-done')

    @property
    def extra_email_context(self):
        return {'site_url': settings.SITE_URL}

    def form_valid(self, form):
        from .throttle import reset_request_allowed
        if not reset_request_allowed(self.request):
            # Même page de confirmation : on ne dit pas qu'on a bloqué l'envoi.
            return redirect(self.get_success_url())
        return super().form_valid(form)


def _send_welcome_email(user):
    """Email de bienvenue après l'inscription, avec le lien de confirmation de l'adresse.
    Un échec d'envoi ne bloque jamais la création du compte."""
    import logging

    from django.core.mail import EmailMultiAlternatives
    from django.template.loader import render_to_string
    from .email_verification import needs_verification, verification_url
    context = {'user': user, 'site_url': settings.SITE_URL,
               'verify_url': verification_url(user) if needs_verification(user) else ''}
    message = EmailMultiAlternatives(
        subject='Bienvenue sur Billio', body=render_to_string('auth/welcome_email.txt', context),
        to=[user.email], reply_to=[settings.SUPPORT_EMAIL] if getattr(settings, 'SUPPORT_EMAIL', '') else None)
    message.attach_alternative(render_to_string('auth/welcome_email.html', context), 'text/html')
    try:
        message.send()
    except Exception:  # noqa: BLE001 — SMTP indisponible : le compte reste créé
        logging.getLogger(__name__).exception("Email de bienvenue non envoyé à %s", user.email)


def register_view(request):
    """HTML view for user registration."""
    if request.user.is_authenticated:
        return redirect('dashboard:dashboard-home')

    if request.method == 'POST':
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            from apps.translations.middleware import request_language
            user.language = request_language(request)
            user.terms_accepted_at = timezone.now()
            user.email_verification_required = True
            user.save(update_fields=['language', 'terms_accepted_at', 'email_verification_required'])
            # Create user profile
            from .countries import BY_CODE
            country_name = BY_CODE[form.cleaned_data['country']][0]
            UserProfile.objects.create(user=user, industry=form.cleaned_data['trade'], country=country_name)
            # Entreprise créée d'emblée, préparée pour le métier choisi (phases, modèles de projet, mentions).
            from apps.organizations.trade_packs import apply_trade_pack
            organization = Organization.objects.create(
                owner=user, email=user.email, phone=user.phone, country=country_name,
                name=(user.get_full_name() or user.email).strip()[:200],
            )
            OrganizationMember.objects.create(organization=organization, user=user, role='owner',
                                              **OrganizationMember.ROLE_PERMISSIONS['owner'])
            apply_trade_pack(organization, form.cleaned_data['trade'], user=user)
            # Règles du pays (devise, taux, mentions) ; le statut et la TVA se confirment dans Paramètres.
            from apps.organizations.jurisdictions import apply_profile
            apply_profile(organization, {'country': form.cleaned_data['country'], 'status': 'freelance',
                                         'tax_registered': False, 'confirmed': False})
            auth_login(request, user)
            _send_welcome_email(user)
            messages.success(request, f'Compte créé avec succès ! Bienvenue, {user.get_full_name() or user.email}!')
            return redirect(_safe_next(request) or 'dashboard:dashboard-home')
    else:
        form = RegisterForm(initial={'email': (request.GET.get('email') or '').strip()[:254], 'country': 'FR'})

    from .countries import COUNTRIES
    return render(request, 'auth/register.html', {'form': form, 'countries': COUNTRIES})


def verify_email_view(request, token):
    """Lien de confirmation de l'adresse (email de bienvenue ou renvoyé depuis le bandeau)."""
    from .email_verification import verify_token
    if verify_token(token):
        messages.success(request, 'Adresse email confirmée : vous pouvez envoyer factures et devis à vos clients.')
    else:
        messages.error(request, 'Ce lien de confirmation est invalide ou a expiré. Connectez-vous et renvoyez-en un depuis le bandeau en haut de page.')
    if request.user.is_authenticated:
        return redirect('dashboard:dashboard-home')
    return redirect('accounts:login')


@login_required
@require_POST
def resend_verification_view(request):
    from django.core.cache import cache
    from .email_verification import needs_verification, send_verification_email
    back = request.POST.get('next') or ''
    if not url_has_allowed_host_and_scheme(back, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        back = reverse('dashboard:dashboard-home')
    if not needs_verification(request.user):
        return redirect(back)
    key = f'verify-email-resend:{request.user.pk}'
    cache.add(key, 0, 3600)
    if cache.incr(key) > 3:
        messages.error(request, "Plusieurs emails de confirmation sont déjà partis cette heure-ci : vérifiez vos courriers indésirables.")
    elif send_verification_email(request.user):
        messages.success(request, f'Email de confirmation envoyé à {request.user.email}.')
    else:
        messages.error(request, "L'email n'a pas pu partir. Réessayez dans quelques minutes.")
    return redirect(back)


@login_required
def logout_view(request):
    """HTML view for user logout."""
    auth_logout(request)
    messages.info(request, 'Vous avez été déconnecté.')
    return redirect('landing:home')


@login_required
def profile_view(request):
    """HTML view for user profile."""
    try:
        profile = request.user.profile
    except UserProfile.DoesNotExist:
        profile = UserProfile.objects.create(user=request.user)

    return render(request, 'accounts/profile.html', {'profile': profile})


def _compliance_context(organization):
    """Assistant de conformité : profil, liste de contrôle et données des pays (Pays & conformité)."""
    if organization is None:
        return {}
    import json
    from apps.organizations import jurisdictions as j
    prof = j.profile(organization)
    pack = j.pack_for(prof['country'])
    items = j.checklist(organization, prof)
    return {
        'compliance': prof,
        'compliance_pack': pack,
        'compliance_country_value': prof['country'] if prof['country'] in j.PACKS else 'OTHER',
        'compliance_items': items,
        'compliance_readiness': j.readiness(items),
        'compliance_countries': [(code, j.PACKS[code]['name']) for code in j.SUPPORTED],
        'compliance_data_json': json.dumps(j.assistant_data(), ensure_ascii=False),
        'compliance_provinces': sorted(((code, name) for code, (name, _r) in j.CA_PROVINCES.items()), key=lambda p: p[1]),
        'compliance_languages': list(j.DOC_LANGUAGES.items()),
        'compliance_rates': j.tax_rates(pack, prof) if pack['supported'] else [],
        'compliance_title': j.document_title(organization),
        'exemption_ui': j.exemption_ui(organization),
        'online_methods': __import__('apps.payments.local_methods', fromlist=['recommended']).recommended(prof['country']),
        'stripe_settings_url': 'https://dashboard.stripe.com/settings/payment_methods',
    }


@login_required
def settings_view(request):
    """HTML view for user settings."""
    try:
        profile = request.user.profile
    except UserProfile.DoesNotExist:
        profile = UserProfile.objects.create(user=request.user)

    payment_organizations = list_editable_organizations_for_payment(request.user)
    allowed_ids = {str(o.id) for o in payment_organizations}

    def resolve_payment_org(from_get=False):
        if not payment_organizations:
            return None
        raw = (
            request.GET.get('payment_org') if from_get else None
        )
        if from_get and raw and str(raw) in allowed_ids:
            return next(o for o in payment_organizations if str(o.id) == str(raw))
        if from_get:
            return payment_organizations[0]
        return None

    payment_org = resolve_payment_org(from_get=True) if payment_organizations else None

    if request.method == 'POST' and request.POST.get('form_action') == 'save_payment_info':
        oid = (request.POST.get('payment_organization_id') or '').strip()
        if not payment_organizations:
            messages.error(
                request,
                'Aucune organisation modifiable. Créez une organisation ou demandez les droits d’administration.',
            )
        elif oid not in allowed_ids:
            messages.error(request, 'Organisation invalide.')
        else:
            target = next(o for o in payment_organizations if str(o.id) == oid)
            pm = (request.POST.get('preferred_payment_method') or 'bank_transfer').strip()
            if pm not in _PAYMENT_METHOD_KEYS:
                pm = 'bank_transfer'
            target.preferred_payment_method = pm
            target.bank_name = (request.POST.get('bank_name') or '').strip()[:200]
            target.iban = _normalize_iban(request.POST.get('iban'))
            target.bic_swift = _normalize_bic(request.POST.get('bic_swift'))
            target.payment_instructions = (request.POST.get('payment_instructions') or '').strip()
            target.save(update_fields=[
                'preferred_payment_method',
                'bank_name', 'iban', 'bic_swift', 'payment_instructions', 'updated_at',
            ])
            messages.success(
                request,
                f'Informations de paiement enregistrées pour « {target.name} ».',
            )
        return redirect(f"{reverse('accounts:user-settings')}?tab=paiement")

    if request.method == 'POST' and request.POST.get('form_action') == 'save_entreprise_info':
        oid = (request.POST.get('entreprise_organization_id') or '').strip()
        if not payment_organizations:
            messages.error(
                request,
                'Aucune organisation modifiable. Créez une organisation ou demandez les droits d’administration.',
            )
        elif oid not in allowed_ids:
            messages.error(request, 'Organisation invalide.')
        else:
            target = next(o for o in payment_organizations if str(o.id) == oid)
            target.name = (request.POST.get('name') or target.name).strip()[:200]
            target.email = (request.POST.get('email') or '').strip()[:254]
            target.phone = (request.POST.get('phone') or '').strip()[:30]
            target.website = (request.POST.get('website') or '').strip()[:200]
            target.address = (request.POST.get('address') or '').strip()
            target.city = (request.POST.get('city') or '').strip()[:100]
            target.postal_code = (request.POST.get('postal_code') or '').strip()[:20]
            target.country = (request.POST.get('country') or '').strip()[:100]
            target.tax_id = (request.POST.get('tax_id') or '').strip()[:50]
            target.registration_number = (request.POST.get('registration_number') or '').strip()[:50]
            target.primary_color = (request.POST.get('primary_color') or target.primary_color or '#6d28d9').strip()[:7]
            target.secondary_color = (request.POST.get('secondary_color') or target.secondary_color or '#f59e0b').strip()[:7]
            target.save(update_fields=[
                'name', 'email', 'phone', 'website', 'address', 'city', 'postal_code',
                'country', 'tax_id', 'registration_number', 'primary_color', 'secondary_color', 'updated_at',
            ])
            messages.success(request, f'Informations de « {target.name} » enregistrées.')
        base = reverse('accounts:user-settings')
        return redirect(f'{base}?tab=entreprise')

    if request.method == 'POST' and request.POST.get('form_action') == 'save_tax_rate':
        from apps.invoices.models import Tax
        oid = (request.POST.get('tax_organization_id') or '').strip()
        if oid not in allowed_ids:
            messages.error(request, 'Organisation invalide.')
        else:
            target = next(o for o in payment_organizations if str(o.id) == oid)
            name = (request.POST.get('tax_name') or '').strip()[:100]
            rate_raw = (request.POST.get('tax_rate') or '').strip()
            try:
                rate = Decimal(rate_raw.replace(',', '.'))
            except Exception:
                rate = None
            if not name or rate is None:
                messages.error(request, 'Nom et taux de TVA requis.')
            else:
                Tax.objects.create(organization=target, name=name, rate=rate)
                messages.success(request, f'Taux de TVA « {name} » ajouté.')
        base = reverse('accounts:user-settings')
        return redirect(f'{base}?tab=facturation')

    action = request.POST.get('form_action') if request.method == 'POST' else None
    settings_url = reverse('accounts:user-settings')

    if action == 'save_profile':
        user = request.user
        user.first_name = (request.POST.get('first_name') or '').strip()[:150]
        user.last_name = (request.POST.get('last_name') or '').strip()[:150]
        user.phone = (request.POST.get('phone') or '').strip()[:20] or None
        user.save(update_fields=['first_name', 'last_name', 'phone', 'updated_at'])
        messages.success(request, 'Profil enregistré.')
        return redirect(f'{settings_url}?tab=profil')

    if action == 'save_booking' and payment_organizations:
        from apps.dashboard.booking import clean_settings
        target = payment_organizations[0]
        try:
            target.booking_settings = clean_settings(request.POST)
            if target.booking_settings['enabled']:
                from apps.subscriptions.entitlements import require_feature
                require_feature(target, 'booking')
        except ValueError as exc:
            messages.error(request, str(exc))
        else:
            target.save(update_fields=['booking_settings', 'updated_at'])
            messages.success(request, 'Prise de rendez-vous enregistrée.' if target.booking_settings['enabled']
                             else 'Réglages enregistrés (page de réservation désactivée).')
        return redirect(f'{settings_url}?tab=rdv')

    if action == 'apply_trade' and payment_organizations:
        from apps.organizations.trade_packs import TRADE_PACKS, apply_trade_pack
        trade = request.POST.get('trade')
        if trade not in TRADE_PACKS:
            messages.error(request, 'Métier inconnu.')
        else:
            result = apply_trade_pack(payment_organizations[0], trade, user=request.user)
            parts = [f"{result['phases_added']} phase(s) ajoutée(s)"]
            if result.get('processes_added'):
                parts.append(f"{result['processes_added']} processus suggéré(s)")
            if result['templates_added']:
                parts.append(f"{result['templates_added']} modèle(s) de projet")
            messages.success(request, f"Pack « {TRADE_PACKS[trade]['label']} » appliqué : {', '.join(parts)}, mentions légales mises à jour.")
        return redirect(f'{settings_url}?tab=metier')

    if action == 'save_client_notifications' and payment_organizations:
        from apps.dashboard.client_notifications import CLIENT_EVENTS
        target = payment_organizations[0]
        target.client_notification_settings = {
            key: {
                'enabled': request.POST.get(f'{key}__enabled') == 'on',
                'email': request.POST.get(f'{key}__enabled') == 'on' and request.POST.get(f'{key}__email') == 'on',
            }
            for key, *_rest in CLIENT_EVENTS
        }
        target.save(update_fields=['client_notification_settings', 'updated_at'])
        messages.success(request, 'Notifications client enregistrées.')
        return redirect(f'{settings_url}?tab=notifications')

    if action == 'save_avatar':
        from django import forms as django_forms
        upload = request.FILES.get('avatar')
        if not upload:
            messages.error(request, 'Choisissez une image.')
        elif upload.size > 2 * 1024 * 1024:
            messages.error(request, 'Image trop lourde (2 Mo maximum).')
        else:
            try:
                django_forms.ImageField().clean(upload)
            except django_forms.ValidationError:
                messages.error(request, "Ce fichier n'est pas une image valide (JPG, PNG ou WebP).")
            else:
                user = request.user
                if user.avatar:
                    user.avatar.delete(save=False)
                user.avatar = upload
                user.save(update_fields=['avatar', 'updated_at'])
                messages.success(request, 'Photo de profil mise à jour.')
        return redirect(f'{settings_url}?tab=profil')

    if action == 'remove_avatar':
        if request.user.avatar:
            request.user.avatar.delete(save=False)
            request.user.avatar = None
            request.user.save(update_fields=['avatar', 'updated_at'])
            messages.success(request, 'Photo de profil supprimée.')
        return redirect(f'{settings_url}?tab=profil')

    if action and action.startswith('2fa_'):
        from . import two_factor
        user = request.user
        if action == '2fa_start' and not user.totp_enabled_at:
            request.session[two_factor.SESSION_SETUP] = two_factor.generate_secret()
        elif action == '2fa_cancel':
            request.session.pop(two_factor.SESSION_SETUP, None)
        elif action == '2fa_confirm' and not user.totp_enabled_at:
            secret = request.session.get(two_factor.SESSION_SETUP)
            step = two_factor.matching_step(secret, request.POST.get('code'))
            if step is None:
                messages.error(request, "Code incorrect : vérifiez l'heure de votre téléphone et saisissez le code affiché.")
            else:
                request.session.pop(two_factor.SESSION_SETUP, None)
                request.session[two_factor.SESSION_NEW_CODES] = two_factor.enable(user, secret, step)
                messages.success(request, 'Double authentification activée.')
        elif action in ('2fa_disable', '2fa_new_codes') and user.totp_enabled_at:
            if not two_factor.check(user, request.POST.get('code')):
                messages.error(request, 'Code incorrect ou expiré.')
            elif action == '2fa_disable':
                two_factor.disable(user)
                messages.success(request, 'Double authentification désactivée.')
            else:
                request.session[two_factor.SESSION_NEW_CODES] = two_factor.new_recovery_codes(user)
                user.save(update_fields=['totp_recovery_codes'])
                messages.success(request, 'Nouveaux codes de secours générés : les anciens ne fonctionnent plus.')
        return redirect(f'{settings_url}?tab=securite')

    if action == 'export_data':
        from django.core.cache import cache
        from django.http import FileResponse
        from .personal_data import build_export
        key = f'data-export:{request.user.pk}'
        cache.add(key, 0, 3600)
        if cache.incr(key) > 5:
            messages.error(request, "Vous avez déjà demandé plusieurs exports cette heure-ci : réessayez un peu plus tard.")
            return redirect(f'{settings_url}?tab=donnees')
        archive = build_export(request.user, payment_organizations)
        return FileResponse(archive, as_attachment=True, content_type='application/zip',
                            filename=f'billio-export-{timezone.localdate():%Y-%m-%d}.zip')

    if action == 'close_account':
        from . import closure, two_factor
        from apps.subscriptions.billing import BillingError
        user = request.user
        if user.has_usable_password():
            identity_ok = user.check_password(request.POST.get('password') or '')
        else:
            identity_ok = (request.POST.get('email') or '').strip().lower() == user.email.lower()
        if not identity_ok:
            messages.error(request, 'Mot de passe incorrect.' if user.has_usable_password() else 'Adresse email incorrecte.')
        elif user.totp_enabled_at and not two_factor.check(user, request.POST.get('code')):
            messages.error(request, 'Code de double authentification incorrect ou expiré.')
        elif (request.POST.get('confirm') or '').strip().upper() != 'FERMER':
            messages.error(request, 'Écrivez FERMER pour confirmer.')
        else:
            try:
                closure.close_account(user)
            except BillingError as exc:
                messages.error(request, f"Votre abonnement n'a pas pu être résilié, le compte reste ouvert : {exc}")
            else:
                auth_logout(request)
                messages.success(request, f"Votre compte est fermé. Vos données seront effacées le {closure.deletion_date(user):%d/%m/%Y}.")
                return redirect('accounts:login')
        return redirect(f'{settings_url}?tab=donnees')

    if action == 'change_password':
        from django.contrib.auth import update_session_auth_hash
        from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm
        # Compte créé via Google : pas d'ancien mot de passe à vérifier.
        form_class = PasswordChangeForm if request.user.has_usable_password() else SetPasswordForm
        form = form_class(request.user, request.POST)
        if form.is_valid():
            update_session_auth_hash(request, form.save())
            messages.success(request, 'Mot de passe modifié.')
        else:
            for errors in form.errors.values():
                for error in errors:
                    messages.error(request, error)
        return redirect(f'{settings_url}?tab=securite')

    if action == 'save_compliance' and payment_organizations:
        from apps.organizations import jurisdictions
        target = payment_organizations[0]
        country = (request.POST.get('country') or '').upper()
        if country == 'OTHER':
            country = jurisdictions.profile(target)['country'] if jurisdictions.profile(target)['country'] not in jurisdictions.PACKS else ''
        jurisdictions.apply_profile(target, {
            'country': country, 'status': request.POST.get('status'),
            'tax_registered': request.POST.get('tax_registered') == 'yes', 'region': request.POST.get('region'),
            'doc_language': request.POST.get('doc_language'), 'company_details': request.POST.get('company_details'),
        })
        messages.success(request, 'Règles de facturation enregistrées : taux, mentions et devise sont à jour.')
        return redirect(f'{settings_url}?tab=conformite')

    if action == 'save_billing' and payment_organizations:
        target = payment_organizations[0]
        errors = []
        invoice_prefix = (request.POST.get('invoice_prefix') or '').strip().upper()[:10]
        quote_prefix = (request.POST.get('quote_prefix') or '').strip().upper()[:10]
        if not invoice_prefix or not quote_prefix:
            errors.append('Les préfixes de numérotation sont obligatoires.')
        try:
            next_invoice = max(1, int(request.POST.get('next_invoice_number') or target.next_invoice_number))
            next_quote = max(1, int(request.POST.get('next_quote_number') or target.next_quote_number))
            payment_days = int(request.POST.get('payment_days') or 30)
            if not 0 <= payment_days <= 60:
                raise ValueError
        except ValueError:
            errors.append('Numéros et délai de paiement (0 à 60 jours) doivent être des nombres valides.')
        penalty = (request.POST.get('penalty_rate') or '').replace(',', '.').strip()
        try:
            penalty = str(Decimal(penalty).quantize(Decimal('0.01'))) if penalty else ''
        except Exception:
            errors.append('Taux de pénalités invalide.')
        if errors:
            for error in errors:
                messages.error(request, error)
        else:
            prefs = dict(target.billing_preferences or {})
            prefs.update({'payment_days': payment_days,
                          'early_discount': (request.POST.get('early_discount') or '').strip()[:300]})
            from apps.organizations.jurisdictions import set_tax_exempt
            set_tax_exempt(prefs, request.POST.get('vat_exempt') == 'on')
            if penalty:
                prefs['penalty_rate'] = penalty
            else:
                prefs.pop('penalty_rate', None)
            target.invoice_prefix, target.quote_prefix = invoice_prefix, quote_prefix
            target.next_invoice_number, target.next_quote_number = next_invoice, next_quote
            target.default_payment_terms = payment_days
            # Devise personnalisée (ex. FCFA) : ajoutée à la liste et choisie par défaut.
            customs = [c for c in prefs.get('custom_currencies') or []
                       if c.get('code') not in request.POST.getlist('remove_currency')]
            custom_code = ''.join(ch for ch in (request.POST.get('custom_code') or '').upper() if ch.isalpha())[:3]
            if len(custom_code) == 3:
                customs = [c for c in customs if c.get('code') != custom_code] + [{
                    'code': custom_code,
                    'name': (request.POST.get('custom_name') or custom_code).strip()[:40],
                    'symbol': (request.POST.get('custom_symbol') or custom_code).strip()[:6],
                    'position': 'before' if request.POST.get('custom_position') == 'before' else 'after',
                    'decimals': {'0': 0, '3': 3}.get(request.POST.get('custom_decimals'), 2),
                    'style': 'en' if request.POST.get('custom_style') == 'en' else 'fr',
                }]
            prefs['custom_currencies'] = customs
            target.billing_preferences = prefs
            chosen = (custom_code if len(custom_code) == 3 else request.POST.get('default_currency') or 'USD')[:3].upper()
            from apps.organizations.currencies import choices as currency_choices
            target.default_currency = chosen if chosen in {code for code, _ in currency_choices(target)} else 'USD'
            target.billing_preferences = prefs
            target.save(update_fields=['invoice_prefix', 'quote_prefix', 'next_invoice_number', 'next_quote_number',
                                       'default_payment_terms', 'default_currency', 'billing_preferences', 'updated_at'])
            messages.success(request, 'Réglages de facturation enregistrés.')
        return redirect(f'{settings_url}?tab=facturation')

    if action in ('tax_delete', 'tax_default') and payment_organizations:
        from apps.invoices.models import Tax
        tax = Tax.objects.filter(organization=payment_organizations[0], id=request.POST.get('tax_id')).first()
        if tax and action == 'tax_delete':
            tax.delete()
            messages.success(request, f'Taux « {tax.name} » supprimé.')
        elif tax:
            Tax.objects.filter(organization=tax.organization).update(is_default=False)
            tax.is_default = True
            tax.save(update_fields=['is_default'])
            messages.success(request, f'« {tax.name} » est maintenant le taux par défaut.')
        return redirect(f'{settings_url}?tab=facturation')

    payment_orgs_bootstrap = [_org_payment_bootstrap_dict(o) for o in payment_organizations]

    entreprise_organization = payment_organizations[0] if payment_organizations else None
    tax_rates = []
    team_members = []
    pending_invites = []
    if entreprise_organization:
        from apps.invoices.models import Tax
        from apps.organizations.models import OrganizationInvite
        tax_rates = list(Tax.objects.filter(organization=entreprise_organization).order_by('-is_default', 'name'))
        team_members = list(
            OrganizationMember.objects.filter(organization=entreprise_organization)
            .select_related('user')
            .order_by('role', 'user__email')
        )
        for member in team_members:
            member.is_owner = member.role == 'owner' or member.user_id == entreprise_organization.owner_id
            member.is_self = member.user_id == request.user.id
        pending_invites = list(
            OrganizationInvite.objects.filter(organization=entreprise_organization, accepted_at__isnull=True)
            .order_by('-created_at')
        )

    from apps.organizations.views import _can_manage_team
    from apps.dashboard.client_notifications import event_settings

    from . import two_factor
    setup_secret = request.session.get(two_factor.SESSION_SETUP) if not request.user.totp_enabled_at else None
    context = {
        'two_factor_setup': {
            'secret': ' '.join(setup_secret[i:i + 4] for i in range(0, len(setup_secret), 4)),
            'qr': two_factor.qr_svg(two_factor.provisioning_uri(request.user, setup_secret)),
        } if setup_secret else None,
        'two_factor_new_codes': request.session.pop(two_factor.SESSION_NEW_CODES, None),
        'recovery_codes_left': len(request.user.totp_recovery_codes or []),
        'profile': profile,
        'page_title': 'Paramètres',
        'page_subtitle': 'Gérez vos préférences et paramètres de compte',
        'payment_organization': payment_org,
        'payment_organizations': payment_organizations,
        'payment_orgs_bootstrap': payment_orgs_bootstrap,
        'api_token': Token.objects.filter(user=request.user).first(),
        'stripe_connected': bool(entreprise_organization) and bool(
            __import__('apps.payments.stripe_checkout', fromlist=['stripe_instance']).stripe_instance(entreprise_organization)),
        'api_allowed': request.user.is_superuser or __import__('apps.subscriptions.authentication', fromlist=['user_has_api']).user_has_api(request.user),
        'api_plan': getattr(__import__('apps.subscriptions.entitlements', fromlist=['plan_with_feature']).plan_with_feature('api'), 'name', ''),
        'entreprise_organization': entreprise_organization,
        'tax_rates': tax_rates,
        'team_members': team_members,
        'client_notification_events': event_settings(entreprise_organization) if entreprise_organization else [],
        'trade_packs': _trade_cards(),
        **_booking_context(entreprise_organization),
        'project_templates': list(entreprise_organization.project_templates.all()) if entreprise_organization else [],
        'can_manage_team': _can_manage_team(request.user, entreprise_organization),
        'role_choices': [(k, v) for k, v in OrganizationMember.ROLE_CHOICES if k != 'owner'],
        'pending_invites': pending_invites,
        'payment_method_choices': Organization.PAYMENT_METHOD_CHOICES,
        'payment_day_choices': [(0, 'À réception'), (15, '15 jours'), (30, '30 jours'), (45, '45 jours'), (60, '60 jours')],
        'current_payment_days': int((entreprise_organization.billing_preferences or {}).get('payment_days')
                                    or entreprise_organization.default_payment_terms) if entreprise_organization else 30,
        'currency_choices': __import__('apps.organizations.currencies', fromlist=['choices']).choices(entreprise_organization),
        'custom_currencies': ((entreprise_organization.billing_preferences or {}).get('custom_currencies') or []) if entreprise_organization else [],
        'billing_texts': entreprise_organization.billing_texts() if entreprise_organization else {},
        'closure_shared_organizations': __import__('apps.accounts.closure', fromlist=['shared_organizations']).shared_organizations(request.user),
        **_compliance_context(entreprise_organization),
        'fec_start': timezone.localdate().replace(month=1, day=1),
        'fec_end': timezone.localdate().replace(month=12, day=31),
        'closure_grace_days': __import__('apps.accounts.closure', fromlist=['grace_days']).grace_days(),
    }

    return render(request, 'accounts/settings.html', context)


def _booking_context(organization):
    if not organization:
        return {}
    from django.conf import settings as dj_settings
    from apps.dashboard.booking import booking_config
    from apps.dashboard.models import Appointment
    from apps.subscriptions.entitlements import has_feature, plan_with_feature
    return {
        'booking_allowed': has_feature(organization, 'booking'),
        'booking_plan': getattr(plan_with_feature('booking'), 'name', ''),
        'booking': booking_config(organization),
        'booking_types_json': __import__('json').dumps(booking_config(organization)['types']),
        'booking_url': f"{dj_settings.SITE_URL}{reverse('dashboard:public-booking', args=[organization.booking_token])}",
        'upcoming_appointments': Appointment.objects.filter(organization=organization, status='confirmed',
                                                            end__gte=timezone.now()).order_by('start')[:20],
        'weekday_choices': [(1, 'Lun'), (2, 'Mar'), (3, 'Mer'), (4, 'Jeu'), (5, 'Ven'), (6, 'Sam'), (7, 'Dim')],
    }


def _trade_cards():
    from apps.organizations.trade_packs import TRADE_PACKS
    return [{'key': key, 'label': p['label'], 'description': p['description'], 'icon': p['icon'],
             'phases': [label for _k, label, _c in p['phases']], 'templates': [t['name'] for t in p['templates']],
             'units': p['units']} for key, p in TRADE_PACKS.items()]


@login_required
@require_POST
def generate_api_token(request):
    """(Re)generate the current user's API token, replacing any existing one."""
    from apps.subscriptions.authentication import user_has_api
    from apps.subscriptions.entitlements import plan_with_feature
    if not request.user.is_superuser and not user_has_api(request.user):
        plan = plan_with_feature('api')
        messages.warning(request, f"L'API est disponible à partir du forfait {plan.name if plan else 'Business'}.")
        return redirect(f"{reverse('accounts:user-settings')}?tab=dev")
    Token.objects.filter(user=request.user).delete()
    Token.objects.create(user=request.user)
    messages.success(request, 'Nouveau token API généré.')
    return redirect(f"{reverse('accounts:user-settings')}?tab=dev")


@login_required
@require_POST
def revoke_api_token(request):
    """Revoke the current user's API token."""
    Token.objects.filter(user=request.user).delete()
    messages.success(request, 'Token API révoqué.')
    return redirect(f"{reverse('accounts:user-settings')}?tab=dev")


class UserViewSet(viewsets.ModelViewSet):
    """ViewSet for User model."""
    queryset = User.objects.all()
    serializer_class = UserSerializer

    def get_queryset(self):
        """Filter users based on permissions."""
        if self.request.user.is_staff:
            return User.objects.all()
        return User.objects.filter(id=self.request.user.id)

    @action(detail=False, methods=['get'])
    def me(self, request):
        """Get current user information."""
        serializer = self.get_serializer(request.user)
        return Response(serializer.data)


class UserProfileViewSet(viewsets.ModelViewSet):
    """ViewSet for UserProfile model."""
    queryset = UserProfile.objects.all()
    serializer_class = UserProfileSerializer

    def get_queryset(self):
        """Filter profiles based on user."""
        return UserProfile.objects.filter(user=self.request.user)


class RegisterView(generics.CreateAPIView):
    """User registration view."""
    queryset = User.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        # Create user profile
        UserProfile.objects.create(user=user)

        # Create auth token
        token, created = Token.objects.get_or_create(user=user)

        return Response({
            'user': UserSerializer(user).data,
            'token': token.key,
            'message': _('User registered successfully')
        }, status=status.HTTP_201_CREATED)


class LoginView(generics.GenericAPIView):
    """User login view."""
    serializer_class = LoginSerializer
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        from .throttle import BLOCKED_MESSAGE, clear_login_failures, login_blocked, record_login_failure
        email = request.data.get('email', '')
        if login_blocked(request, email):
            return Response({'detail': BLOCKED_MESSAGE}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            record_login_failure(request, email)
            serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']
        if user.totp_enabled_at:
            from . import two_factor
            if not request.data.get('otp'):
                return Response({'otp_required': True, 'detail': 'Code de double authentification requis (champ « otp »).'},
                                status=status.HTTP_401_UNAUTHORIZED)
            if not two_factor.check(user, request.data.get('otp')):
                record_login_failure(request, email)
                return Response({'otp_required': True, 'detail': 'Code incorrect ou expiré.'},
                                status=status.HTTP_401_UNAUTHORIZED)
        clear_login_failures(request, email)

        login(request, user)
        token, created = Token.objects.get_or_create(user=user)

        return Response({
            'user': UserSerializer(user).data,
            'token': token.key,
            'message': _('Login successful')
        })


class LogoutView(generics.GenericAPIView):
    """User logout view."""
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        logout(request)
        # Delete token if using token auth
        try:
            request.user.auth_token.delete()
        except:
            pass

        return Response({'message': _('Logout successful')})


class GoogleLoginView(generics.GenericAPIView):
    """Google OAuth login view."""
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        # This would integrate with Google OAuth
        # Implementation depends on the OAuth library used
        return Response({'message': _('Google login not implemented yet')})


class UserProfileView(generics.RetrieveUpdateAPIView):
    """User profile view."""
    serializer_class = UserProfileSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        profile, created = UserProfile.objects.get_or_create(user=self.request.user)
        return profile

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()

        # Allow profile popup to also update basic user fields.
        user = request.user
        first_name = (request.data.get('first_name') or '').strip()
        last_name = (request.data.get('last_name') or '').strip()
        phone = (request.data.get('phone') or '').strip()
        user_changed = False
        if user.first_name != first_name:
            user.first_name = first_name
            user_changed = True
        if user.last_name != last_name:
            user.last_name = last_name
            user_changed = True
        if user.phone != phone:
            user.phone = phone
            user_changed = True
        if user_changed:
            user.save(update_fields=['first_name', 'last_name', 'phone'])

        serializer = UserProfileUpdateSerializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)

        return Response(serializer.data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def change_password(request):
    """Change user password."""
    serializer = ChangePasswordSerializer(data=request.data)
    if serializer.is_valid():
        user = request.user
        if not user.check_password(serializer.data.get('old_password')):
            return Response(
                {'old_password': [_('Wrong password.')]},
                status=status.HTTP_400_BAD_REQUEST
            )

        user.set_password(serializer.data.get('new_password'))
        user.save()
        return Response({'message': _('Password updated successfully')})

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
