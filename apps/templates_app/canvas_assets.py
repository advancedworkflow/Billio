"""
Images des modèles libres : import (PNG, JPEG, WebP, GIF, SVG), liste, inclusion dans le modèle.

Les images matricielles sont relues par Pillow (fichier réellement image), réduites à 2000 px et
réenregistrées (PNG si transparence, sinon JPEG). Les SVG sont nettoyés par liste blanche
(formes et dégradés uniquement : ni script, ni lien, ni style, ni objet étranger).
"""
import io
import re
import uuid
import xml.etree.ElementTree as ET

from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from .editor_views import _primary_org
from .models import TemplateAsset

MAX_UPLOAD = 4 * 1024 * 1024
MAX_SIDE = 2000
MAX_ASSETS = 60

SVG_NS = 'http://www.w3.org/2000/svg'
SVG_TAGS = {'svg', 'g', 'path', 'rect', 'circle', 'ellipse', 'line', 'polyline', 'polygon', 'defs',
            'linearGradient', 'radialGradient', 'stop', 'title', 'desc', 'clipPath'}
SVG_ATTRS = {'d', 'x', 'y', 'x1', 'x2', 'y1', 'y2', 'cx', 'cy', 'r', 'rx', 'ry', 'fx', 'fy', 'width', 'height',
             'viewBox', 'points', 'fill', 'stroke', 'stroke-width', 'stroke-linecap', 'stroke-linejoin',
             'stroke-miterlimit', 'stroke-dasharray', 'opacity', 'fill-opacity', 'stroke-opacity', 'fill-rule',
             'clip-rule', 'transform', 'id', 'offset', 'stop-color', 'stop-opacity', 'gradientUnits',
             'gradientTransform', 'spreadMethod', 'preserveAspectRatio', 'clip-path', 'clipPathUnits'}
_LOCAL_URL = re.compile(r'^url\(#[\w.-]+\)$')
_SAFE_VALUE = re.compile(r'^[#\w\s.,%()+\-:]*$')


class AssetError(ValueError):
    pass


def sanitize_svg(raw):
    """SVG nettoyé (bytes) ou AssetError."""
    text = raw.decode('utf-8', errors='strict') if isinstance(raw, bytes) else raw
    if re.search(r'<!(DOCTYPE|ENTITY)', text, re.I):
        raise AssetError('SVG refusé : déclarations DOCTYPE/ENTITY interdites.')
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise AssetError('SVG illisible.') from exc

    def local(name):
        return name.rsplit('}', 1)[-1]

    def clean(node):
        out = ET.Element(local(node.tag))
        for key, value in node.attrib.items():
            name = local(key)
            value = value.strip()
            if name not in SVG_ATTRS or len(value) > 20000:
                continue
            if 'url(' in value and not _LOCAL_URL.match(value):
                continue
            if name not in ('d', 'points', 'transform') and not _SAFE_VALUE.match(value):
                continue
            out.set(name, value)
        for child in node:
            if local(child.tag) in SVG_TAGS:
                out.append(clean(child))
        if node.text and local(node.tag) in ('title', 'desc'):
            out.text = node.text[:200]
        return out

    if local(root.tag) != 'svg':
        raise AssetError('Ce fichier n’est pas un SVG.')
    cleaned = clean(root)
    cleaned.set('xmlns', SVG_NS)
    return ET.tostring(cleaned, encoding='utf-8')


def _svg_size(svg_bytes):
    root = ET.fromstring(svg_bytes)
    box = (root.get('viewBox') or '').replace(',', ' ').split()
    try:
        if len(box) == 4:
            return int(float(box[2])), int(float(box[3]))
        return int(float(root.get('width', 0))), int(float(root.get('height', 0)))
    except ValueError:
        return 0, 0


def process_upload(upload):
    """(contenu, extension, mime, largeur, hauteur) d'un fichier importé, ou AssetError."""
    if upload.size > MAX_UPLOAD:
        raise AssetError('Image trop lourde (4 Mo maximum).')
    raw = upload.read()
    name = (upload.name or '').lower()
    if name.endswith('.svg') or raw.lstrip()[:5] in (b'<svg ', b'<?xml') and b'<svg' in raw[:2000]:
        content = sanitize_svg(raw)
        width, height = _svg_size(content)
        return content, 'svg', 'image/svg+xml', width, height
    from PIL import Image, UnidentifiedImageError
    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise AssetError('Format non pris en charge : PNG, JPEG, WebP, GIF ou SVG.') from exc
    image.thumbnail((MAX_SIDE, MAX_SIDE))
    has_alpha = image.mode in ('RGBA', 'LA', 'P') and (image.mode != 'P' or 'transparency' in image.info)
    buffer = io.BytesIO()
    if has_alpha:
        image.convert('RGBA').save(buffer, 'PNG', optimize=True)
        ext, mime = 'png', 'image/png'
    else:
        image.convert('RGB').save(buffer, 'JPEG', quality=88, optimize=True)
        ext, mime = 'jpg', 'image/jpeg'
    return buffer.getvalue(), ext, mime, image.width, image.height


def asset_payload(asset):
    return {'id': asset.id, 'url': asset.file.url, 'name': asset.name, 'w': asset.width, 'h': asset.height}


def assets_for(organization):
    if organization is None:
        return []
    return [asset_payload(a) for a in TemplateAsset.objects.filter(organization=organization)[:MAX_ASSETS]]


def resolve(organization, layout):
    """{id: data URI} des images utilisées par la mise en page (seulement celles de l'organisation)."""
    ids = {b.get('asset') for b in layout.get('blocks', []) if b.get('type') == 'image' and b.get('asset')}
    if not ids or organization is None:
        return {}
    return {a.id: a.data_uri() for a in TemplateAsset.objects.filter(organization=organization, id__in=ids)}


@login_required
@require_POST
def asset_upload(request):
    org = _primary_org(request.user)
    upload = request.FILES.get('file')
    if org is None or upload is None:
        return JsonResponse({'ok': False, 'error': 'Aucun fichier reçu.'}, status=400)
    if TemplateAsset.objects.filter(organization=org).count() >= MAX_ASSETS:
        return JsonResponse({'ok': False, 'error': 'Bibliothèque pleine : supprimez des images inutilisées.'}, status=400)
    try:
        content, ext, mime, width, height = process_upload(upload)
    except AssetError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    asset = TemplateAsset(organization=org, name=(upload.name or 'image')[:120], mime=mime, width=width, height=height)
    asset.file.save(f'{uuid.uuid4().hex}.{ext}', ContentFile(content), save=True)
    return JsonResponse({'ok': True, 'asset': asset_payload(asset)})


@login_required
@require_GET
def asset_list(request):
    return JsonResponse({'ok': True, 'assets': assets_for(_primary_org(request.user))})


@login_required
@require_POST
def asset_delete(request, asset_id):
    asset = TemplateAsset.objects.filter(organization=_primary_org(request.user), id=asset_id).first()
    if asset is None:
        return JsonResponse({'ok': False}, status=404)
    # Les modèles déjà enregistrés gardent leur copie de l'image (incluse dans le modèle).
    asset.file.delete(save=False)
    asset.delete()
    return JsonResponse({'ok': True})
