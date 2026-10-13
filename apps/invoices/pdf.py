"""
Génération PDF pour les documents de facturation (Invoice, Quote) et les documents canvas.

Réutilise le HTML/CSS déjà produit par `document.generate_pdf_html()`, donc le PDF reflète
exactement le thème/personnalisation appliqué au document.

Nécessite WeasyPrint et son runtime natif (Pango/Cairo/GDK-Pixbuf) :
- Windows (dev local) : installer le runtime GTK3, voir la documentation
  officielle WeasyPrint (section "Installation" / Windows).
- Linux (prod) : `apt-get install libpango-1.0-0 libpangocairo-1.0-0
  libgdk-pixbuf2.0-0 libffi-dev` avant `pip install weasyprint`.

Sous Windows, le runtime GTK fait planter le processus au 2ᵉ rendu dans un même processus
(assertions GLib). Chaque rendu y est donc isolé dans un sous-processus court
(`PDF_RENDER_ISOLATED`, activé par défaut sous Windows).
"""
import os
import subprocess
import sys

from django.conf import settings

_RENDER_SCRIPT = (
    "import sys\n"
    "from weasyprint import HTML\n"
    "html = sys.stdin.buffer.read().decode('utf-8')\n"
    "sys.stdout.buffer.write(HTML(string=html, base_url=sys.argv[1] or None).write_pdf())\n"
)


class PDFRenderError(RuntimeError):
    pass


def _isolated():
    return getattr(settings, 'PDF_RENDER_ISOLATED', os.name == 'nt')


def html_to_pdf_bytes(html_content, base_url=None):
    """Rend du HTML en PDF (bytes), dans un sous-processus si l'isolation est active."""
    if not _isolated():
        from weasyprint import HTML
        return HTML(string=html_content, base_url=base_url).write_pdf()
    try:
        result = subprocess.run(
            [sys.executable, '-c', _RENDER_SCRIPT, base_url or ''],
            input=html_content.encode('utf-8'), capture_output=True, timeout=120,
        )
    except subprocess.TimeoutExpired as exc:
        raise PDFRenderError('Le rendu PDF a dépassé le délai.') from exc
    if not result.stdout.startswith(b'%PDF'):
        detail = result.stderr.decode('utf-8', 'replace').strip().splitlines()[-1:] or ['inconnue']
        raise PDFRenderError(f'Rendu PDF impossible : {detail[0][:300]}')
    return result.stdout


def render_document_to_pdf_bytes(document):
    """
    Rend un document de facturation (Invoice, Quote, ou tout objet exposant
    `generate_pdf_html()`) en PDF, sous forme de bytes.
    """
    return html_to_pdf_bytes(document.generate_pdf_html())
