"""
Modèles de facture / devis « pro » installés dans la galerie (MarketplaceTemplate
système, migration templates_app.0004). Compatibles facture ET devis : les libellés
s'adaptent via `document_kind` / `document_type`.

Conventions :
- Rendu par `django.template.Template` (aperçu de l'éditeur et PDF WeasyPrint) avec le
  contexte plat de InvoiceTemplate._flat_document_context (+ variables du modèle).
- Le CSS n'est PAS rendu par Django dans l'aperçu : toute valeur dynamique (couleur
  d'accent, taille du logo) passe par des variables CSS posées en style inline sur la
  racine (`--accent`, `--logo-h`).
- Classes préfixées par modèle (bp-ess-, bp-mod-…) : le CSS de l'aperçu est injecté
  dans la page de l'éditeur.
- Le bloc logo porte `data-obj="logo"` : un clic dessus dans l'éditeur ouvre la
  gestion du logo.
"""

FONTS_IMPORT = (
    "@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800"
    "&family=Newsreader:opsz,wght@6..72,500;6..72,600&display=swap');\n"
)

COMMON_SCHEMA = [
    {'name': 'accent_color', 'type': 'color', 'label': "Couleur d'accent"},
    {'name': 'logo_height', 'type': 'text', 'label': 'Hauteur du logo (px)'},
    {'name': 'payment_terms', 'type': 'textarea', 'label': 'Conditions de paiement'},
    {'name': 'legal_mentions', 'type': 'textarea', 'label': 'Mentions légales'},
    {'name': 'thank_you', 'type': 'text', 'label': 'Mot de fin'},
]

COMMON_DEFAULTS = {
    'logo_height': '52',
    'payment_terms': 'Paiement à 30 jours à réception de facture, par virement bancaire.',
    'legal_mentions': (
        "En cas de retard de paiement, une pénalité égale à trois fois le taux d'intérêt légal "
        "sera exigible, ainsi qu'une indemnité forfaitaire de 40 € pour frais de recouvrement. "
        "Aucun escompte pour paiement anticipé."
    ),
    'thank_you': 'Merci pour votre confiance.',
}


# --------------------------------------------------------------------------- #
# Blocs communs (préfixe {p} remplacé par celui du modèle)
# --------------------------------------------------------------------------- #

LOGO = """<div class="{p}logo" data-obj="logo">{% if organization_logo_url %}<img src="{{ organization_logo_url }}" alt="{{ organization_name }}" class="{p}logo-img">{% else %}<span class="{p}mark">{{ organization_initial }}</span>{% endif %}</div>"""

ISSUER = """<p class="{p}label">Émetteur</p>
<p class="{p}strong">{{ organization_name }}</p>
{% if organization_address %}<p>{{ organization_address|linebreaksbr }}</p>{% endif %}
{% if organization_postal_code or organization_city %}<p>{{ organization_postal_code }} {{ organization_city }}</p>{% endif %}
{% if organization_email %}<p>{{ organization_email }}</p>{% endif %}
{% if organization_phone %}<p>{{ organization_phone }}</p>{% endif %}
{% if organization_registration_number %}<p class="{p}muted">SIRET {{ organization_registration_number }}</p>{% endif %}
{% if organization_tax_id %}<p class="{p}muted">TVA {{ organization_tax_id }}</p>{% endif %}"""

CLIENT = """<p class="{p}label">{% if document_type == 'quote' %}Destinataire{% else %}Facturé à{% endif %}</p>
<p class="{p}strong">{{ client_name }}</p>
{% if client_address %}<p>{{ client_address|linebreaksbr }}</p>{% endif %}
{% if client_email %}<p>{{ client_email }}</p>{% endif %}
{% if client_phone %}<p>{{ client_phone }}</p>{% endif %}
{% if client_registration_number %}<p class="{p}muted">SIRET {{ client_registration_number }}</p>{% endif %}
{% if client_tax_id %}<p class="{p}muted">TVA {{ client_tax_id }}</p>{% endif %}"""

ITEMS = """{% if subject %}<p class="{p}subject"><span class="{p}muted">Objet :</span> {{ subject }}</p>{% endif %}<table class="{p}items">
  <thead><tr>
    <th class="{p}c-desc">Désignation</th><th class="{p}c-num">Qté</th><th class="{p}c-num">Prix unitaire HT</th><th class="{p}c-num">TVA</th><th class="{p}c-num">Total HT</th>
  </tr></thead>
  <tbody>
  {% for item in items %}
    <tr>
      <td class="{p}c-desc"><span class="{p}item-name">{{ item.name }}</span>{% if item.description %}<span class="{p}item-desc">{{ item.description }}</span>{% endif %}</td>
      <td class="{p}c-num">{{ item.quantity|qty }}</td>
      <td class="{p}c-num">{{ item.unit_price|money:currency }}</td>
      <td class="{p}c-num">{{ item.tax_rate|percent }}</td>
      <td class="{p}c-num {p}c-strong">{{ item.total|money:currency }}</td>
    </tr>
  {% empty %}
    <tr><td colspan="5" class="{p}empty">Aucune ligne</td></tr>
  {% endfor %}
  </tbody>
</table>"""

TOTALS = """<table class="{p}totals">
  <tr><td>Total HT</td><td>{{ subtotal|money:currency }}</td></tr>
  <tr><td>TVA</td><td>{{ tax_amount|money:currency }}</td></tr>
  <tr class="{p}grand"><td>{% if document_type == 'quote' %}Total TTC{% else %}Net à payer{% endif %}</td><td>{{ total_amount|money:currency }}</td></tr>
</table>"""

PAYMENT = """{% if notes %}<div class="{p}notes"><p class="{p}label">Notes</p><p>{{ notes|linebreaksbr }}</p></div>{% endif %}
<div class="{p}payment">
  <div class="{p}payment-terms">
    <p class="{p}label">{% if document_type == 'quote' %}Conditions{% else %}Règlement{% endif %}</p>
    <p>{{ payment_terms|linebreaksbr }}</p>
    {% if organization_payment_instructions %}<p>{{ organization_payment_instructions|linebreaksbr }}</p>{% endif %}
    {% if delivery_terms %}<p class="{p}label {p}label-gap">Délais</p><p>{{ delivery_terms|linebreaksbr }}</p>{% endif %}
  </div>
  {% if organization_iban %}
  <div class="{p}bank">
    <p class="{p}label">Coordonnées bancaires</p>
    {% if organization_bank_name %}<p>{{ organization_bank_name }}</p>{% endif %}
    <p><span class="{p}muted">IBAN</span> {{ organization_iban }}</p>
    {% if organization_bic_swift %}<p><span class="{p}muted">BIC</span> {{ organization_bic_swift }}</p>{% endif %}
  </div>
  {% endif %}
</div>
{% if payment_url %}<div class="{p}paylink"><div class="{p}paylink-qr">{{ payment_qr }}</div><div><p class="{p}label">Payer en ligne</p><p>Scannez le QR code ou ouvrez le lien : {{ payment_url }}</p></div></div>{% endif %}
{% if document_type == 'quote' %}<div class="{p}sign"><p class="{p}label">Bon pour accord</p><p class="{p}muted">Date, signature et mention « Bon pour accord »</p></div>{% endif %}"""

FOOTER = """<div class="{p}footer">
  <p class="{p}thanks">{{ thank_you }}</p>
  <p class="{p}legal">{{ legal_mentions|linebreaksbr }}</p>
  <p class="{p}legal">{{ organization_name }}{% if organization_registration_number %} · SIRET {{ organization_registration_number }}{% endif %}{% if organization_tax_id %} · TVA {{ organization_tax_id }}{% endif %}{% if organization_email %} · {{ organization_email }}{% endif %}</p>
</div>"""

META_ROWS = """<tr><td>{% if document_type == 'quote' %}Devis n°{% else %}Facture n°{% endif %}</td><td>{{ invoice_number }}</td></tr>
<tr><td>Date d'émission</td><td>{{ issue_date }}</td></tr>
<tr><td>{% if document_type == 'quote' %}Valable jusqu'au{% else %}Échéance{% endif %}</td><td>{{ due_date }}</td></tr>"""


def _fill(html, prefix):
    return html.replace('{p}', prefix)


# Base CSS commune (préfixe {p}) : typographie, tableaux, totaux, pied.
BASE_CSS = """
@page { size: A4; margin: 0; }
.{p}doc { --accent: #111827; --logo-h: 52px; font-family: 'Inter', Arial, sans-serif; color: #1f2937; font-size: 12.5px; line-height: 1.5; background: #fff; }
.{p}doc p { margin: 0; }
.{p}label { font-size: 10px; font-weight: 600; letter-spacing: .09em; text-transform: uppercase; color: #6b7280; margin-bottom: 6px !important; }
.{p}strong { font-weight: 600; color: #111827; font-size: 13.5px; }
.{p}muted { color: #6b7280; }
.{p}logo { display: inline-block; }
.{p}logo-img { height: var(--logo-h); max-width: 220px; object-fit: contain; display: block; }
.{p}mark { display: inline-block; width: var(--logo-h); height: var(--logo-h); line-height: var(--logo-h); text-align: center; border-radius: 12px; background: var(--accent); color: #fff; font-weight: 700; font-size: 22px; }
.{p}grid { width: 100%; border-collapse: collapse; }
.{p}grid td { vertical-align: top; padding: 0; }
.{p}items { width: 100%; border-collapse: collapse; margin-top: 28px; }
.{p}items th { font-size: 10px; font-weight: 600; letter-spacing: .07em; text-transform: uppercase; color: #6b7280; text-align: left; padding: 10px 10px; border-bottom: 1.5px solid #111827; }
.{p}items td { padding: 12px 10px; border-bottom: 1px solid #e5e7eb; vertical-align: top; }
.{p}c-num { text-align: right !important; white-space: nowrap; width: 1%; }
.{p}c-strong { font-weight: 600; color: #111827; }
.{p}item-name { display: block; font-weight: 500; color: #111827; }
.{p}item-desc { display: block; color: #6b7280; font-size: 11.5px; margin-top: 2px; }
.{p}empty { text-align: center; color: #9ca3af; }
.{p}totals { margin: 18px 0 0 auto; border-collapse: collapse; min-width: 280px; }
.{p}totals td { padding: 7px 10px; }
.{p}totals td:last-child { text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }
.{p}grand td { font-weight: 700; font-size: 15px; color: #111827; border-top: 1.5px solid #111827; padding-top: 11px; }
.{p}notes { margin-top: 26px; padding: 14px 16px; background: #f9fafb; border-radius: 8px; }
.{p}payment { margin-top: 26px; width: 100%; }
.{p}payment-terms, .{p}bank { display: inline-block; vertical-align: top; width: 48%; }
.{p}bank { margin-left: 3%; }
.{p}paylink { margin-top: 14px; display: flex; align-items: center; gap: 12px; font-size: 11px; }
.{p}paylink-qr svg { display: block; width: 72px; height: 72px; }
.{p}paylink p { margin: 0; word-break: break-all; }
.{p}sign { margin-top: 26px; margin-left: auto; width: 46%; height: 110px; border: 1px dashed #d1d5db; border-radius: 8px; padding: 12px 14px; }
.{p}footer { margin-top: 34px; padding-top: 16px; border-top: 1px solid #e5e7eb; }
.{p}thanks { font-weight: 600; color: var(--accent); margin-bottom: 8px !important; }
.{p}legal { font-size: 9.5px; color: #9ca3af; line-height: 1.5; }
.{p}meta td { white-space: nowrap; }
.{p}subject { margin-top: 26px !important; font-size: 13px; color: #111827; }
.{p}subject + .{p}items { margin-top: 12px; }
.{p}label-gap { margin-top: 12px !important; }
"""


def _css(prefix, extra):
    return FONTS_IMPORT + _fill(BASE_CSS + extra, prefix)


def _root(prefix, inner, extra_style=''):
    return (
        f'{{% load billio_format %}}<div class="{prefix}doc" '
        f'style="--accent: {{{{ accent_color }}}}; --logo-h: {{{{ logo_height }}}}px;{extra_style}">'
        f'{_fill(inner, prefix)}</div>'
    )


# --------------------------------------------------------------------------- #
# 1. Essentiel — noir et blanc, très lisible
# --------------------------------------------------------------------------- #

ESS = 'bp-ess-'
ESSENTIEL_HTML = _root(ESS, f"""
<div class="{{p}}pad">
  <table class="{{p}}grid"><tr>
    <td>{LOGO}</td>
    <td class="{{p}}title-cell"><p class="{{p}}title">{{{{ document_kind }}}}</p><p class="{{p}}number">N° {{{{ invoice_number }}}}</p></td>
  </tr></table>
  <table class="{{p}}grid {{p}}facts"><tr>
    <td><p class="{{p}}label">Date d'émission</p><p class="{{p}}strong">{{{{ issue_date }}}}</p></td>
    <td><p class="{{p}}label">{{% if document_type == 'quote' %}}Valable jusqu'au{{% else %}}Échéance{{% endif %}}</p><p class="{{p}}strong">{{{{ due_date }}}}</p></td>
    <td class="{{p}}fact-total"><p class="{{p}}label">{{% if document_type == 'quote' %}}Total TTC{{% else %}}Net à payer{{% endif %}}</p><p class="{{p}}big">{{{{ total_amount|money:currency }}}}</p></td>
  </tr></table>
  <table class="{{p}}grid {{p}}parties"><tr><td>{ISSUER}</td><td>{CLIENT}</td></tr></table>
  {ITEMS}
  {TOTALS}
  {PAYMENT}
  {FOOTER}
</div>""")
ESSENTIEL_CSS = _css(ESS, """
.{p}pad { padding: 48px 52px; }
.{p}title-cell { text-align: right; }
.{p}title { font-size: 30px; font-weight: 800; letter-spacing: -.02em; color: #111827; text-transform: uppercase; }
.{p}number { color: #6b7280; margin-top: 2px !important; }
.{p}facts { margin-top: 34px; border-top: 1px solid #e5e7eb; border-bottom: 1px solid #e5e7eb; }
.{p}facts td { padding: 14px 0 !important; width: 33%; }
.{p}fact-total { text-align: right; }
.{p}big { font-size: 20px; font-weight: 800; color: var(--accent); }
.{p}parties { margin-top: 28px; }
.{p}parties td { width: 50%; }
""")


# --------------------------------------------------------------------------- #
# 2. Moderne — bandeau couleur, plaque blanche pour le logo
# --------------------------------------------------------------------------- #

MOD = 'bp-mod-'
MODERNE_HTML = _root(MOD, f"""
<div class="{{p}}band">
  <table class="{{p}}grid"><tr>
    <td><div class="{{p}}plate">{LOGO}</div></td>
    <td class="{{p}}band-right"><p class="{{p}}title">{{{{ document_kind }}}}</p><p class="{{p}}number">N° {{{{ invoice_number }}}}</p></td>
  </tr></table>
</div>
<div class="{{p}}pad">
  <table class="{{p}}grid {{p}}parties"><tr>
    <td>{ISSUER}</td>
    <td>{CLIENT}</td>
    <td class="{{p}}meta-cell"><table class="{{p}}meta">{META_ROWS}</table></td>
  </tr></table>
  {ITEMS}
  <table class="{{p}}grid"><tr><td></td><td class="{{p}}totals-cell">{TOTALS}</td></tr></table>
  {PAYMENT}
  {FOOTER}
</div>""")
MODERNE_CSS = _css(MOD, """
.{p}band { background: var(--accent); color: #fff; padding: 34px 52px 30px; }
.{p}plate { display: inline-block; background: #fff; border-radius: 12px; padding: 10px 14px; }
.{p}band-right { text-align: right; vertical-align: middle !important; }
.{p}title { font-size: 28px; font-weight: 800; letter-spacing: -.01em; text-transform: uppercase; }
.{p}number { opacity: .8; margin-top: 2px !important; }
.{p}pad { padding: 34px 52px 44px; }
.{p}parties td { width: 33%; padding-right: 18px !important; }
.{p}meta { border-collapse: collapse; margin-left: auto; }
.{p}meta td { padding: 3px 0 3px 12px; font-size: 12px; }
.{p}meta td:first-child { color: #6b7280; padding-left: 0; }
.{p}meta td:last-child { text-align: right; font-weight: 600; color: #111827; }
.{p}items th { border-bottom-color: var(--accent); color: var(--accent); }
.{p}totals-cell { width: 300px; }
.{p}grand td { background: var(--accent); color: #fff; border-top: none; border-radius: 0; }
""")


# --------------------------------------------------------------------------- #
# 3. Corporate — filet supérieur, en-tête institutionnel, tableau gris
# --------------------------------------------------------------------------- #

COR = 'bp-cor-'
CORPORATE_HTML = _root(COR, f"""
<div class="{{p}}rule"></div>
<div class="{{p}}pad">
  <table class="{{p}}grid"><tr>
    <td class="{{p}}brand">{LOGO}<p class="{{p}}org">{{{{ organization_name }}}}</p></td>
    <td class="{{p}}head-right">
      <p class="{{p}}title">{{{{ document_kind }}}}</p>
      <table class="{{p}}meta">{META_ROWS}</table>
    </td>
  </tr></table>
  <table class="{{p}}grid {{p}}parties"><tr>
    <td><div class="{{p}}box">{ISSUER}</div></td>
    <td><div class="{{p}}box {{p}}box--client">{CLIENT}</div></td>
  </tr></table>
  {ITEMS}
  <table class="{{p}}grid"><tr><td></td><td class="{{p}}totals-cell">{TOTALS}</td></tr></table>
  {PAYMENT}
  {FOOTER}
</div>""")
CORPORATE_CSS = _css(COR, """
.{p}rule { height: 8px; background: var(--accent); }
.{p}pad { padding: 40px 52px 44px; }
.{p}org { font-weight: 700; color: #111827; font-size: 14px; margin-top: 10px !important; }
.{p}head-right { text-align: right; }
.{p}title { font-size: 26px; font-weight: 700; color: var(--accent); text-transform: uppercase; letter-spacing: .06em; margin-bottom: 8px !important; }
.{p}meta { border-collapse: collapse; margin-left: auto; }
.{p}meta td { padding: 2px 0 2px 14px; font-size: 12px; }
.{p}meta td:first-child { color: #6b7280; }
.{p}meta td:last-child { font-weight: 600; color: #111827; text-align: right; }
.{p}parties { margin-top: 30px; }
.{p}parties td { width: 50%; }
.{p}parties td:first-child { padding-right: 10px !important; }
.{p}parties td:last-child { padding-left: 10px !important; }
.{p}box { border: 1px solid #e5e7eb; border-radius: 8px; padding: 14px 16px; min-height: 120px; }
.{p}box--client { border-color: var(--accent); }
.{p}items th { background: #f3f4f6; border-bottom: none; color: #374151; }
.{p}items td { border-bottom-color: #f0f0f0; }
.{p}totals-cell { width: 300px; }
.{p}grand td { color: var(--accent); border-top-color: var(--accent); }
""")


# --------------------------------------------------------------------------- #
# 4. Élégant — titres serif, filets fins, mise en page centrée
# --------------------------------------------------------------------------- #

ELE = 'bp-ele-'
ELEGANT_HTML = _root(ELE, f"""
<div class="{{p}}pad">
  <div class="{{p}}center">{LOGO}<p class="{{p}}org">{{{{ organization_name }}}}</p></div>
  <div class="{{p}}title-wrap"><span class="{{p}}line"></span><span class="{{p}}title">{{{{ document_kind }}}}</span><span class="{{p}}line"></span></div>
  <p class="{{p}}sub">N° {{{{ invoice_number }}}} · {{{{ issue_date }}}} · {{% if document_type == 'quote' %}}valable jusqu'au{{% else %}}échéance{{% endif %}} {{{{ due_date }}}}</p>
  <table class="{{p}}grid {{p}}parties"><tr><td>{ISSUER}</td><td class="{{p}}right">{CLIENT}</td></tr></table>
  {ITEMS}
  <table class="{{p}}grid"><tr><td></td><td class="{{p}}totals-cell">{TOTALS}</td></tr></table>
  {PAYMENT}
  {FOOTER}
</div>""")
ELEGANT_CSS = _css(ELE, """
.{p}pad { padding: 52px 60px; }
.{p}center { text-align: center; }
.{p}org { font-family: 'Newsreader', Georgia, serif; font-size: 17px; color: #111827; margin-top: 10px !important; }
.{p}title-wrap { text-align: center; margin-top: 26px; }
.{p}line { display: inline-block; width: 70px; height: 1px; background: var(--accent); vertical-align: middle; }
.{p}title { display: inline-block; font-family: 'Newsreader', Georgia, serif; font-size: 30px; font-weight: 500; color: #111827; padding: 0 18px; vertical-align: middle; letter-spacing: .02em; }
.{p}sub { text-align: center; color: #6b7280; margin-top: 6px !important; letter-spacing: .02em; }
.{p}parties { margin-top: 36px; }
.{p}parties td { width: 50%; }
.{p}right { text-align: right; }
.{p}label { color: var(--accent); }
.{p}items th { border-bottom: 1px solid var(--accent); color: var(--accent); font-weight: 500; }
.{p}items td { border-bottom-color: #f1ede6; }
.{p}totals-cell { width: 300px; }
.{p}grand td { font-family: 'Newsreader', Georgia, serif; font-size: 18px; font-weight: 600; border-top: 1px solid var(--accent); }
.{p}mark { border-radius: 50%; font-family: 'Newsreader', Georgia, serif; }
.{p}notes { background: #faf8f4; }
""")


# --------------------------------------------------------------------------- #
# 5. Épuré — colonne d'informations à gauche, carte de total
# --------------------------------------------------------------------------- #

EPU = 'bp-epu-'
EPURE_HTML = _root(EPU, f"""
<div class="{{p}}pad">
  <table class="{{p}}grid"><tr>
    <td>{LOGO}</td>
    <td class="{{p}}head-right"><span class="{{p}}pill">{{{{ document_kind }}}} n° {{{{ invoice_number }}}}</span></td>
  </tr></table>
  <table class="{{p}}grid {{p}}hero"><tr>
    <td class="{{p}}hero-left">
      <p class="{{p}}hello">{{% if document_type == 'quote' %}}Proposition pour{{% else %}}Facture pour{{% endif %}}</p>
      <p class="{{p}}client-big">{{{{ client_name }}}}</p>
      <table class="{{p}}meta">{META_ROWS}</table>
    </td>
    <td class="{{p}}hero-right"><div class="{{p}}card"><p class="{{p}}card-label">{{% if document_type == 'quote' %}}Total TTC{{% else %}}Montant à régler{{% endif %}}</p><p class="{{p}}card-amount">{{{{ total_amount|money:currency }}}}</p><p class="{{p}}card-due">{{% if document_type == 'quote' %}}Valable jusqu'au{{% else %}}Avant le{{% endif %}} {{{{ due_date }}}}</p></div></td>
  </tr></table>
  <table class="{{p}}grid {{p}}parties"><tr><td>{ISSUER}</td><td>{CLIENT}</td></tr></table>
  {ITEMS}
  <table class="{{p}}grid"><tr><td></td><td class="{{p}}totals-cell">{TOTALS}</td></tr></table>
  {PAYMENT}
  {FOOTER}
</div>""")
EPURE_CSS = _css(EPU, """
.{p}pad { padding: 46px 52px; }
.{p}head-right { text-align: right; vertical-align: middle !important; }
.{p}pill { display: inline-block; padding: 6px 12px; border-radius: 999px; background: #f3f4f6; font-size: 11.5px; font-weight: 600; color: #374151; }
.{p}hero { margin-top: 34px; }
.{p}hero-left { width: 58%; }
.{p}hello { color: #6b7280; }
.{p}client-big { font-size: 24px; font-weight: 700; color: #111827; letter-spacing: -.01em; margin: 2px 0 14px !important; }
.{p}meta { border-collapse: collapse; }
.{p}meta td { padding: 2px 16px 2px 0; font-size: 12px; }
.{p}meta td:first-child { color: #6b7280; }
.{p}meta td:last-child { font-weight: 600; color: #111827; }
.{p}card { background: var(--accent); color: #fff; border-radius: 14px; padding: 20px 22px; }
.{p}card-label { font-size: 11px; opacity: .85; text-transform: uppercase; letter-spacing: .08em; }
.{p}card-amount { font-size: 26px; font-weight: 800; letter-spacing: -.01em; margin: 4px 0 !important; }
.{p}card-due { font-size: 12px; opacity: .85; }
.{p}parties { margin-top: 30px; }
.{p}parties > tbody > tr > td, .{p}parties > tr > td { padding-top: 22px !important; border-top: 1px solid #e5e7eb; }
.{p}parties td { width: 50%; }
.{p}items th { border-bottom: 1px solid #e5e7eb; }
.{p}totals-cell { width: 300px; }
.{p}grand td { color: var(--accent); border-top: 1px solid #e5e7eb; }
.{p}notes { border-left: 3px solid var(--accent); background: #fafafa; border-radius: 0 8px 8px 0; }
""")


PRO_TEMPLATES = [
    {
        'slug': 'pro-essentiel', 'title': 'Essentiel',
        'description': 'Noir et blanc, très lisible : chiffres clés en tête, parties côte à côte.',
        'html': ESSENTIEL_HTML, 'css': ESSENTIEL_CSS, 'accent': '#111827',
        'tags': ['pro', 'minimal', 'noir', 'facture', 'devis'],
    },
    {
        'slug': 'pro-moderne', 'title': 'Moderne',
        'description': 'Bandeau de couleur avec logo sur plaque blanche, total mis en avant.',
        'html': MODERNE_HTML, 'css': MODERNE_CSS, 'accent': '#6d28d9',
        'tags': ['pro', 'moderne', 'couleur', 'facture', 'devis'],
    },
    {
        'slug': 'pro-corporate', 'title': 'Corporate',
        'description': 'Filet de couleur, en-tête institutionnel et encadrés pour les parties.',
        'html': CORPORATE_HTML, 'css': CORPORATE_CSS, 'accent': '#1e3a8a',
        'tags': ['pro', 'corporate', 'entreprise', 'facture', 'devis'],
    },
    {
        'slug': 'pro-elegant', 'title': 'Élégant',
        'description': 'Titres serif, filets fins et mise en page centrée.',
        'html': ELEGANT_HTML, 'css': ELEGANT_CSS, 'accent': '#a16207',
        'tags': ['pro', 'élégant', 'serif', 'facture', 'devis'],
    },
    {
        'slug': 'pro-epure', 'title': 'Épuré',
        'description': 'Le client et le montant à régler en premier, carte de total colorée.',
        'html': EPURE_HTML, 'css': EPURE_CSS, 'accent': '#0f766e',
        'tags': ['pro', 'épuré', 'carte', 'facture', 'devis'],
    },
]


def template_fields(spec):
    """Champs MarketplaceTemplate pour un modèle pro."""
    defaults = dict(COMMON_DEFAULTS, accent_color=spec['accent'])
    return {
        'title': spec['title'],
        'description': spec['description'],
        'demo_html': spec['html'],
        'html_structure': spec['html'],
        'css_styles': spec['css'],
        'layout_config': {'variable_schema': {'fields': COMMON_SCHEMA}},
        'style_config': {'variables_defaults': defaults},
        'tags': spec['tags'],
        'compatible_types': ['invoice', 'quote'],
        'template_type': 'system',
        'is_free': True,
        'is_active': True,
        'is_approved': True,
        'price': 0,
    }
