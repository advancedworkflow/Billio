"""
Cycle de vie d'une demande de signature : création depuis un PDF, envoi des invitations,
signature, refus, puis document final (valeurs apposées + certificat) et emails.
"""
import base64
import binascii
import hashlib
import io
import logging
from datetime import timedelta

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape

from .models import SignatureEvent, SignatureField, SignatureRequest, Signer

logger = logging.getLogger(__name__)

MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_PAGES = 100
MAX_IMAGE_BYTES = 400 * 1024
DEFAULT_VALIDITY_DAYS = 30
SIGNING_KINDS = ('signature', 'initials')


class SignatureError(Exception):
    """Erreur montrée telle quelle à l'utilisateur."""


# --------------------------------------------------------------------------- #
# PDF d'origine
# --------------------------------------------------------------------------- #

def sha256(data):
    return hashlib.sha256(data).hexdigest()


def read_pdf(data):
    """Contrôle le PDF et renvoie la taille de ses pages (en points, rotation appliquée)."""
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    if not data or not data.startswith(b'%PDF'):
        raise SignatureError("Ce fichier n'est pas un PDF.")
    if len(data) > MAX_PDF_BYTES:
        raise SignatureError('Le PDF dépasse 20 Mo.')
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise SignatureError('Ce PDF est protégé par un mot de passe : enregistrez-en une copie sans protection.')
        pages = []
        for page in reader.pages:
            box = page.cropbox
            width, height = float(box.width), float(box.height)
            if (page.rotation or 0) % 180:
                width, height = height, width
            pages.append([round(width, 2), round(height, 2)])
    except SignatureError:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError) as exc:
        raise SignatureError('Ce PDF est illisible.') from exc
    if not pages:
        raise SignatureError('Ce PDF ne contient aucune page.')
    if len(pages) > MAX_PAGES:
        raise SignatureError(f'Ce PDF dépasse {MAX_PAGES} pages.')
    return pages


def create_request(organization, user, *, title, data, source='upload', document=None, quote=None, client=None):
    pages = read_pdf(data)
    request = SignatureRequest(
        organization=organization, created_by=user, title=(title or 'Document à signer')[:200],
        source=source, document=document, quote=quote, client=client,
        original_sha256=sha256(data), pages=pages,
    )
    request.original_pdf.save('original.pdf', ContentFile(data), save=False)
    request.save()
    if client and client.email:
        Signer.objects.create(request=request, client=client, name=client.name[:200], email=client.email)
    SignatureEvent.objects.create(request=request, action='created',
                                  detail=f"par {user.get_full_name() or user.email}" if user else '')
    return request


# --------------------------------------------------------------------------- #
# Brouillon : signataires et champs
# --------------------------------------------------------------------------- #

def _number(value, low=0.0, high=1.0):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise SignatureError('Position de champ invalide.')
    return min(max(number, low), high)


def save_draft(request, payload):
    """Remplace signataires et champs du brouillon par ceux envoyés par l'éditeur."""
    from django.core.validators import validate_email
    from django.core.exceptions import ValidationError
    from apps.clients.models import Client

    if request.status != 'draft':
        raise SignatureError('Cette demande a déjà été envoyée : elle ne peut plus être modifiée.')
    signers_in = payload.get('signers') or []
    fields_in = payload.get('fields') or []
    if len(signers_in) > 10:
        raise SignatureError('10 signataires au maximum.')
    if len(fields_in) > 300:
        raise SignatureError('300 champs au maximum.')
    page_count = len(request.pages)
    kinds = dict(SignatureField.KIND_CHOICES)

    with transaction.atomic():
        request.title = (str(payload.get('title') or '').strip() or request.title)[:200]
        request.message = str(payload.get('message') or '')[:2000]
        request.in_order = bool(payload.get('in_order'))
        days = payload.get('valid_days')
        request.expires_at = None
        if days not in (None, '', 0, '0'):
            try:
                request.expires_at = timezone.now() + timedelta(days=min(max(int(days), 1), 365))
            except (TypeError, ValueError):
                pass
        request.save()

        request.fields.all().delete()
        request.signers.all().delete()
        by_key = {}
        for index, raw in enumerate(signers_in):
            name = str(raw.get('name') or '').strip()[:200]
            email = str(raw.get('email') or '').strip().lower()[:254]
            if email:
                try:
                    validate_email(email)
                except ValidationError:
                    raise SignatureError(f"Adresse email invalide : {email}")
            client = None
            if raw.get('client_id'):
                client = Client.objects.filter(organization=request.organization, pk=raw['client_id']).first()
            by_key[str(raw.get('key', index))] = Signer.objects.create(
                request=request, client=client, name=name, email=email, order=index)

        for raw in fields_in:
            signer = by_key.get(str(raw.get('signer')))
            kind = raw.get('kind')
            if signer is None or kind not in kinds:
                continue
            page = int(_number(raw.get('page'), 0, max(page_count - 1, 0)))
            w, h = _number(raw.get('w'), 0.01, 1), _number(raw.get('h'), 0.005, 1)
            SignatureField.objects.create(
                request=request, signer=signer, kind=kind, page=page,
                x=_number(raw.get('x'), 0, 1 - w), y=_number(raw.get('y'), 0, 1 - h), w=w, h=h,
                required=kind not in ('text', 'checkbox') or bool(raw.get('required', kind == 'text')),
                label=str(raw.get('label') or '')[:100],
            )
    return request


def draft_problems(request):
    """Ce qui empêche l'envoi (liste vide = prêt)."""
    problems = []
    signers = list(request.signers.prefetch_related('fields'))
    if not signers:
        problems.append('Ajoutez au moins un signataire.')
    emails = [s.email for s in signers]
    for signer in signers:
        label = signer.name or f'Signataire {signer.order + 1}'
        if not signer.name or not signer.email:
            problems.append(f'{label} : nom et adresse email obligatoires.')
        if not any(f.kind in SIGNING_KINDS for f in signer.fields.all()):
            problems.append(f'{label} : placez au moins un champ « Signature » ou « Initiales ».')
    if len(set(emails)) != len(emails):
        problems.append('Chaque signataire doit avoir sa propre adresse email.')
    return problems


# --------------------------------------------------------------------------- #
# Envoi, relance, annulation
# --------------------------------------------------------------------------- #

def sign_url(signer):
    return f"{settings.SITE_URL}{reverse('signatures:sign', args=[signer.token])}"


def _send(request, *, to, subject, body, button=None, attachment=None, connection=None, from_email=None):
    from apps.organizations.branded_email import branded_message
    message = branded_message(request.organization, subject=subject, body=body, to=to, button=button,
                              connection=connection, from_email=from_email)
    if attachment:
        message.attach(*attachment)
    message.send(fail_silently=False)


def invite(signer, *, reminder=False, connection=None, from_email=None):
    request = signer.request
    org = request.organization.name
    if reminder:
        subject = f"Rappel : « {request.title} » attend votre signature"
        intro = f"Bonjour {signer.name},\n\nPetit rappel : {org} attend votre signature sur le document « {request.title} »."
    else:
        subject = f"[{org}] « {request.title} » : document à signer"
        intro = f"Bonjour {signer.name},\n\n{org} vous invite à signer le document « {request.title} »."
    body = intro
    if request.message.strip():
        body += f"\n\n{request.message.strip()}"
    if request.expires_at:
        body += f"\n\nÀ signer avant le {timezone.localtime(request.expires_at):%d/%m/%Y}."
    body += "\n\nLa signature se fait en ligne, en quelques secondes, sans créer de compte."
    _send(request, to=[signer.email], subject=subject, body=body, button=('Consulter et signer', sign_url(signer)),
          connection=connection, from_email=from_email)
    now = timezone.now()
    if reminder:
        signer.last_reminded_at = now
        signer.save(update_fields=['last_reminded_at'])
    else:
        signer.status = 'invited'
        signer.invited_at = now
        signer.save(update_fields=['status', 'invited_at'])
    SignatureEvent.objects.create(request=request, signer=signer, action='reminded' if reminder else 'invited',
                                  detail=signer.email)


def _org_mail(organization):
    from apps.integrations.providers import org_mail
    return org_mail(organization)


def send_request(request, user=None):
    """Envoie la demande : invitations (toutes, ou la première si l'ordre est imposé)."""
    from apps.accounts.email_verification import UnverifiedSender

    problems = draft_problems(request)
    if problems:
        raise SignatureError(problems[0])
    try:
        connection, from_email = _org_mail(request.organization)
    except UnverifiedSender as exc:
        raise SignatureError(str(exc))
    signers = list(request.signers.all())
    to_invite = signers[:1] if request.in_order else signers
    with transaction.atomic():
        request.status = 'sent'
        request.sent_at = timezone.now()
        if request.expires_at is None:
            request.expires_at = request.sent_at + timedelta(days=DEFAULT_VALIDITY_DAYS)
        request.save()
        SignatureEvent.objects.create(request=request, action='sent',
                                      detail=f"par {user.get_full_name() or user.email}" if user else '')
        try:
            for signer in to_invite:
                invite(signer, connection=connection, from_email=from_email)
        except Exception as exc:
            logger.exception("Invitation à signer non envoyée (%s)", request.pk)
            raise SignatureError("L'email d'invitation n'a pas pu partir : vérifiez votre messagerie dans Intégrations › Email.") from exc
    return request


def remind(signer):
    from apps.accounts.email_verification import UnverifiedSender

    request = signer.request
    if request.status != 'sent' or signer.status not in ('invited', 'viewed'):
        raise SignatureError("Ce signataire n'a rien à signer pour le moment.")
    if signer.last_reminded_at and signer.last_reminded_at > timezone.now() - timedelta(hours=1):
        raise SignatureError('Une relance vient déjà de partir : réessayez dans une heure.')
    try:
        connection, from_email = _org_mail(request.organization)
        invite(signer, reminder=True, connection=connection, from_email=from_email)
    except UnverifiedSender as exc:
        raise SignatureError(str(exc))
    except SignatureError:
        raise
    except Exception as exc:
        logger.exception("Relance de signature non envoyée (%s)", signer.pk)
        raise SignatureError("La relance n'a pas pu partir.") from exc


def cancel(request, user=None):
    if request.status not in ('draft', 'sent'):
        raise SignatureError('Cette demande ne peut plus être annulée.')
    request.status = 'cancelled'
    request.save(update_fields=['status', 'updated_at'])
    SignatureEvent.objects.create(request=request, action='cancelled',
                                  detail=f"par {user.get_full_name() or user.email}" if user else '')


# --------------------------------------------------------------------------- #
# Côté signataire
# --------------------------------------------------------------------------- #

def _clean_ip(ip):
    import ipaddress
    try:
        return str(ipaddress.ip_address((ip or '').strip()))
    except ValueError:
        return None


def mark_viewed(signer, ip=None, user_agent=''):
    if signer.status == 'invited':
        signer.status = 'viewed'
        signer.viewed_at = timezone.now()
        signer.save(update_fields=['status', 'viewed_at'])
        SignatureEvent.objects.create(request=signer.request, signer=signer, action='viewed',
                                      ip_address=_clean_ip(ip), user_agent=(user_agent or '')[:300])


def can_sign(signer):
    request = signer.request
    return request.status == 'sent' and signer.status in ('invited', 'viewed')


def clean_image(value):
    """Image PNG d'une signature (data URL), contrôlée et ré-encodée."""
    from PIL import Image, UnidentifiedImageError

    prefix = 'data:image/png;base64,'
    if not isinstance(value, str) or not value.startswith(prefix):
        raise SignatureError('Signature manquante.')
    try:
        raw = base64.b64decode(value[len(prefix):], validate=True)
    except (binascii.Error, ValueError):
        raise SignatureError('Signature illisible.')
    if len(raw) > MAX_IMAGE_BYTES:
        raise SignatureError('Signature trop lourde.')
    try:
        image = Image.open(io.BytesIO(raw))
        if image.width * image.height > 4_000_000:
            raise SignatureError('Signature trop grande.')
        image = image.convert('RGBA')
    except (UnidentifiedImageError, OSError):
        raise SignatureError('Signature illisible.')
    if image.getbbox() is None or image.split()[-1].getbbox() is None:
        raise SignatureError('La signature est vide.')
    out = io.BytesIO()
    image.save(out, format='PNG', optimize=True)
    return prefix + base64.b64encode(out.getvalue()).decode('ascii')


def sign(signer, values, *, ip=None, user_agent=''):
    """Enregistre les valeurs du signataire ; termine la demande si c'était le dernier."""
    with transaction.atomic():
        request = SignatureRequest.objects.select_for_update().get(pk=signer.request_id)
        signer = Signer.objects.select_for_update().get(pk=signer.pk)
        request.expire_if_due()
        if not can_sign(signer):
            raise SignatureError("Ce document ne peut plus être signé.")
        today = timezone.localdate().strftime('%d/%m/%Y')
        values = values if isinstance(values, dict) else {}
        for field in signer.fields.all():
            raw = values.get(str(field.pk))
            if field.kind in SIGNING_KINDS:
                value = clean_image(raw) if raw else ''
            elif field.kind == 'date':
                value = today
            elif field.kind == 'checkbox':
                value = 'true' if raw in (True, 'true', '1', 'on') else ''
            else:
                value = ' '.join(str(raw or '').split())[:300]
                if field.kind == 'name' and not value:
                    value = signer.name
            if field.required and not value:
                what = 'la case' if field.kind == 'checkbox' else 'le champ'
                raise SignatureError(f"Remplissez {what} « {field.label or field.get_kind_display()} » (page {field.page + 1}).")
            field.value = value
            field.save(update_fields=['value'])
        signer.status = 'signed'
        signer.signed_at = timezone.now()
        signer.ip_address = _clean_ip(ip)
        signer.user_agent = (user_agent or '')[:300]
        signer.save()
        SignatureEvent.objects.create(request=request, signer=signer, action='signed',
                                      ip_address=signer.ip_address, user_agent=signer.user_agent)
        pending = list(request.signers.exclude(status='signed'))
        next_signer = pending[0] if request.in_order and pending and pending[0].status == 'waiting' else None

    if next_signer:
        try:
            connection, from_email = _org_mail(request.organization)
            invite(next_signer, connection=connection, from_email=from_email)
        except Exception:
            logger.exception("Invitation du signataire suivant non envoyée (%s)", next_signer.pk)
    if not pending:
        complete(request)
    return request


def decline(signer, reason='', *, ip=None, user_agent=''):
    with transaction.atomic():
        request = SignatureRequest.objects.select_for_update().get(pk=signer.request_id)
        signer = Signer.objects.select_for_update().get(pk=signer.pk)
        if not can_sign(signer):
            raise SignatureError("Ce document ne peut plus être refusé.")
        signer.status = 'declined'
        signer.declined_at = timezone.now()
        signer.decline_reason = (reason or '').strip()[:1000]
        signer.ip_address = _clean_ip(ip)
        signer.user_agent = (user_agent or '')[:300]
        signer.save()
        request.status = 'declined'
        request.save(update_fields=['status', 'updated_at'])
        SignatureEvent.objects.create(request=request, signer=signer, action='declined',
                                      ip_address=signer.ip_address, user_agent=signer.user_agent,
                                      detail=signer.decline_reason[:300])
    _notify(request, 'signature_declined', f"Signature refusée : {request.title}",
            f"{signer.name} a refusé de signer « {request.title} »."
            + (f" Motif : {signer.decline_reason}" if signer.decline_reason else ''), priority='high')
    return request


# --------------------------------------------------------------------------- #
# Document final
# --------------------------------------------------------------------------- #

def _pt(value):
    return f"{value:.2f}pt"


def overlay_html(request, fields):
    """HTML (une page par page du PDF, même taille) qui place les valeurs saisies."""
    css = ['*{margin:0;padding:0;box-sizing:border-box}',
           "body{font-family:'Helvetica','Arial','DejaVu Sans',sans-serif;color:#111}",
           '.f{position:absolute;display:flex;align-items:center;overflow:hidden;white-space:nowrap}',
           '.f.i{display:block}',
           '.f.i img{display:block;width:100%;height:100%;object-fit:contain;object-position:left center}']
    pages = []
    for index, (width, height) in enumerate(request.pages):
        css.append(f'@page p{index}{{size:{_pt(width)} {_pt(height)};margin:0}}')
        items = []
        for field in fields.get(index, ()):
            if not field.value:
                continue
            box = (f"left:{_pt(field.x * width)};top:{_pt(field.y * height)};"
                   f"width:{_pt(field.w * width)};height:{_pt(field.h * height)};")
            if field.kind in SIGNING_KINDS:
                items.append(f'<div class="f i" style="{box}"><img src="{field.value}" alt=""></div>')
            elif field.kind == 'checkbox':
                size = min(field.w * width, field.h * height)
                items.append(
                    f'<div class="f" style="{box}justify-content:center"><svg width="{_pt(size)}" height="{_pt(size)}" '
                    'viewBox="0 0 24 24" fill="none" stroke="#111" stroke-width="3" stroke-linecap="round" '
                    'stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg></div>')
            else:
                font = min(max(field.h * height * 0.62, 6), 14)
                items.append(f'<div class="f" style="{box}font-size:{_pt(font)}">{escape(field.value)}</div>')
        pages.append(f'<div style="page:p{index};position:relative;width:{_pt(width)};height:{_pt(height)};'
                     f'break-after:page">{"".join(items)}</div>')
    return f'<!doctype html><html><head><meta charset="utf-8"><style>{"".join(css)}</style></head><body>{"".join(pages)}</body></html>'


def certificate_html(request):
    signers = list(request.signers.all())
    signatures = {}
    for field in request.fields.filter(kind='signature').exclude(value=''):
        signatures.setdefault(field.signer_id, field.value)
    for signer in signers:
        signer.signature_image = signatures.get(signer.pk, '')
    return render_to_string('signatures/certificate.html', {
        'req': request, 'signers': signers, 'events': request.events.select_related('signer'),
        'verify_url': f"{settings.SITE_URL}{reverse('signatures:verify')}",
    })


def build_signed_pdf(request):
    from pypdf import PdfReader, PdfWriter
    from apps.invoices.pdf import html_to_pdf_bytes

    fields = {}
    for field in request.fields.all():
        fields.setdefault(field.page, []).append(field)
    request.original_pdf.open('rb')
    try:
        original = request.original_pdf.read()
    finally:
        request.original_pdf.close()
    overlay = PdfReader(io.BytesIO(html_to_pdf_bytes(overlay_html(request, fields))))
    certificate = PdfReader(io.BytesIO(html_to_pdf_bytes(certificate_html(request))))
    reader = PdfReader(io.BytesIO(original))
    writer = PdfWriter()
    for index, page in enumerate(reader.pages):
        if index in fields:
            if (page.rotation or 0) % 360:
                page.transfer_rotation_to_content()
            box = page.cropbox
            page.merge_translated_page(overlay.pages[index], float(box.left), float(box.bottom))
        writer.add_page(page)
    for page in certificate.pages:
        writer.add_page(page)
    writer.add_metadata({'/Title': request.title, '/Producer': 'Billio — signature électronique'})
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def finalize(request):
    """Génère et enregistre le PDF signé (avec certificat)."""
    data = build_signed_pdf(request)
    request.signed_pdf.save('signe.pdf', ContentFile(data), save=False)
    request.signed_sha256 = sha256(data)
    request.save(update_fields=['signed_pdf', 'signed_sha256', 'updated_at'])
    return data


def complete(request):
    """Toutes les signatures sont là : statut, document final, emails, devis accepté."""
    request.status = 'completed'
    request.completed_at = timezone.now()
    request.save(update_fields=['status', 'completed_at', 'updated_at'])
    SignatureEvent.objects.create(request=request, action='completed')
    try:
        data = finalize(request)
    except Exception:
        logger.exception("Document signé non généré (%s)", request.pk)
        data = None
    _notify(request, 'signature_completed', f"Document signé : {request.title}",
            f"Tous les signataires ont signé « {request.title} ».")
    if data:
        send_completed(request, data)
    _accept_quote(request)


def send_completed(request, data):
    org = request.organization.name
    filename = f"{request.title[:80]} - signé.pdf".replace('/', '-')
    try:
        connection, from_email = _org_mail(request.organization)
    except Exception:
        logger.exception("Email du document signé non envoyé (%s)", request.pk)
        return
    for signer in request.signers.all():
        try:
            _send(request, to=[signer.email], subject=f"[{org}] « {request.title} » est signé",
                  body=(f"Bonjour {signer.name},\n\nTous les signataires ont signé le document « {request.title} ». "
                        "Vous le trouverez en pièce jointe, avec son certificat de signature."),
                  button=('Télécharger le document signé',
                          f"{settings.SITE_URL}{reverse('signatures:sign-download', args=[signer.token])}"),
                  attachment=(filename, data, 'application/pdf'), connection=connection, from_email=from_email)
        except Exception:
            logger.exception("Email du document signé non envoyé à %s", signer.pk)
    owner = request.created_by or request.organization.owner
    if owner and owner.email and owner.email not in {s.email for s in request.signers.all()}:
        try:
            _send(request, to=[owner.email], subject=f"« {request.title} » est signé par tous",
                  body=f"Bonjour,\n\nTous les signataires ont signé « {request.title} ». Le document signé est en pièce jointe.",
                  button=('Voir dans Billio', f"{settings.SITE_URL}{reverse('signatures:detail', args=[request.pk])}"),
                  attachment=(filename, data, 'application/pdf'), connection=connection, from_email=from_email)
        except Exception:
            logger.exception("Email du document signé non envoyé au propriétaire (%s)", request.pk)


def _accept_quote(request):
    quote = request.quote
    if quote is None or quote.status in ('accepted', 'rejected', 'converted'):
        return
    signer = request.signers.order_by('order').first()
    signature = request.fields.filter(signer=signer, kind='signature').exclude(value='').values_list('value', flat=True).first()
    try:
        quote.mark_as_accepted(name=signer.name, email=signer.email, signature_data=signature or '',
                               ip=signer.ip_address, user_agent=signer.user_agent)
    except Exception:
        logger.exception("Devis non passé en accepté après signature (%s)", request.pk)


def _notify(request, kind, title, message, priority='medium'):
    from apps.dashboard.models import Notification
    users = {request.organization.owner, request.created_by} - {None}
    for user in users:
        Notification.objects.create(user=user, notification_type=kind, title=title[:200], message=message,
                                    priority=priority)
