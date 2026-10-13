# -*- coding: utf-8 -*-
"""
Gabarits système (marketplace) — devis / facture FR.
Variables « plates » : compatibles avec l’aperçu facture (Alpine) et le PDF (InvoiceTemplate).
"""

SYSTEM_MARKETPLACE_SEEDS = [
    {
        'title': 'Devis grille administratif',
        'description': (
            'Formulaire administratif : cadres, expéditeur / client, tableau, totaux, mentions. '
            'Couleurs, police et textes modifiables dans le schéma.'
        ),
        'demo_html': (
            '<div style="font:12px Arial;border:1px solid #000;padding:8px;max-width:520px;">'
            '<strong>Devis N°</strong> — grille noire, totaux à droite.</div>'
        ),
        'html_structure': '''
<div class="dm-grid-doc" style="font-family: {{ font_family }}; color: {{ text_color }};">
  <div class="dm-grid-head">
    <p><strong>{{ document_label }}</strong> {{ invoice_number }}</p>
    <p><strong>Date d\'émission :</strong> {{ issue_date }}</p>
    <p><strong>Date limite / échéance :</strong> {{ due_date }}</p>
  </div>
  <div class="dm-grid-two">
    <div class="dm-grid-box">
      <p class="dm-strong">{{ organization_name }}</p>
      {% if organization_address %}<p>{{ organization_address|linebreaksbr }}</p>{% endif %}
      {% if organization_postal_code or organization_city %}
      <p>{{ organization_postal_code }} {{ organization_city }}</p>
      {% endif %}
      {% if organization_registration_number %}<p>SIREN : {{ organization_registration_number }}</p>{% endif %}
    </div>
    <div class="dm-grid-box">
      <p class="dm-strong">{{ client_name }}</p>
      {% if client_address %}<p>{{ client_address|linebreaksbr }}</p>{% endif %}
      {% if client_registration_number %}<p>SIREN : {{ client_registration_number }}</p>{% endif %}
    </div>
  </div>
  <table class="dm-grid-table">
    <thead>
      <tr>
        <th>Description</th>
        <th>Qté</th>
        <th>Prix unitaire</th>
        <th>TVA</th>
        <th>Total HT</th>
      </tr>
    </thead>
    <tbody>
      {% for item in items %}
      <tr>
        <td>{% if item.description %}{{ item.description }}{% else %}{{ item.name }}{% endif %}</td>
        <td class="dm-num">{{ item.quantity }}</td>
        <td class="dm-num">{{ item.unit_price }} {{ currency }}</td>
        <td class="dm-num">{{ item.tax_rate }} %</td>
        <td class="dm-num">{{ item.total }} {{ currency }}</td>
      </tr>
      {% empty %}
      <tr><td colspan="5">—</td></tr>
      {% endfor %}
    </tbody>
  </table>
  <div class="dm-grid-totals-wrap">
    <table class="dm-grid-totals">
      <tr><td>Total HT</td><td>{{ subtotal }} {{ currency }}</td></tr>
      <tr><td>TVA</td><td>{{ tax_amount }} {{ currency }}</td></tr>
      <tr><td><strong>Total</strong></td><td><strong>{{ total_amount }} {{ currency }}</strong></td></tr>
    </table>
  </div>
  {% if tax_legal_mention %}<p class="dm-grid-note">{{ tax_legal_mention }}</p>{% endif %}
  {% if payment_footer_text %}<p class="dm-grid-footer">{{ payment_footer_text }}</p>{% endif %}
</div>
        '''.strip(),
        'css_styles': '''
.dm-grid-doc { max-width: 800px; margin: 0 auto; padding: {{ doc_padding }}; font-size: 13px; }
.dm-grid-head { margin-bottom: 16px; }
.dm-grid-head p { margin: 2px 0; }
.dm-grid-two { display: table; width: 100%; border-collapse: collapse; margin-bottom: 16px; }
.dm-grid-box { display: table-cell; width: 50%; border: 1px solid {{ border_color }}; padding: 10px; vertical-align: top; }
.dm-strong { font-weight: 700; margin-bottom: 6px; }
.dm-grid-table { width: 100%; border-collapse: collapse; margin-bottom: 12px; }
.dm-grid-table th, .dm-grid-table td { border: 1px solid {{ border_color }}; padding: 6px 8px; }
.dm-grid-table th { font-weight: 700; background: #f3f3f3; }
.dm-num { text-align: right; }
.dm-grid-totals-wrap { display: flex; justify-content: flex-end; }
.dm-grid-totals { border-collapse: collapse; min-width: 220px; }
.dm-grid-totals td { border: 1px solid {{ border_color }}; padding: 6px 10px; }
.dm-grid-totals td:first-child { font-weight: 600; }
.dm-grid-note { font-size: 11px; margin-top: 8px; }
.dm-grid-footer { font-size: 11px; margin-top: 14px; line-height: 1.45; }
        '''.strip(),
        'layout_config': {
            'variable_schema': {
                'fields': [
                    {'name': 'document_label', 'type': 'text', 'label': 'Libellé document'},
                    {'name': 'font_family', 'type': 'text', 'label': 'Police'},
                    {'name': 'text_color', 'type': 'text', 'label': 'Couleur texte'},
                    {'name': 'border_color', 'type': 'text', 'label': 'Couleur bordures'},
                    {'name': 'doc_padding', 'type': 'text', 'label': 'Marges document'},
                    {'name': 'tax_legal_mention', 'type': 'textarea', 'label': 'Mention TVA / légal'},
                    {'name': 'payment_footer_text', 'type': 'textarea', 'label': 'Conditions de paiement'},
                ]
            }
        },
        'style_config': {
            'variables_defaults': {
                'document_label': 'Facture N°',
                'font_family': 'Arial, Helvetica, sans-serif',
                'text_color': '#111111',
                'border_color': '#000000',
                'doc_padding': '16px',
                'tax_legal_mention': 'TVA non applicable, article 293 B du CGI.',
                'payment_footer_text': (
                    'La facture devra être réglée par virement ou chèque dès réception. '
                    'Conditions de pénalités selon vos CGV.'
                ),
            }
        },
        'tags': ['devis', 'facture', 'grille', 'administratif', 'fr'],
        'compatible_types': ['invoice', 'quote'],
    },
    {
        'title': 'Facture bandeau noir',
        'description': (
            'Bandeau noir type « Messagem » : marque, FACTURE, tableau en-tête noir, totaux, signature.'
        ),
        'demo_html': (
            '<div style="background:#000;color:#fff;padding:12px;font:bold 18px sans-serif;">FACTURE</div>'
        ),
        'html_structure': '''
<div class="dm-band-doc" style="font-family: {{ font_family }}; color: {{ body_text_color }};">
  <header class="dm-band-header" style="background: {{ header_bg }}; color: {{ header_text_color }};">
    <div class="dm-band-brand">
      <div class="dm-band-logo">{{ company_mark }}</div>
      <div>
        <p class="dm-band-org">{{ organization_name }}</p>
        {% if organization_email %}<p>{{ organization_email }}</p>{% endif %}
        {% if organization_address %}<p>{{ organization_address|linebreaksbr }}</p>{% endif %}
      </div>
    </div>
    <div class="dm-band-meta">
      <p class="dm-band-title">{{ document_title }}</p>
      <p>{{ invoice_number }}</p>
      <p><strong>DATE :</strong> {{ issue_date }}</p>
    </div>
  </header>
  <section class="dm-band-client">
    <p class="dm-band-h">Client</p>
    <p class="dm-band-strong">{{ client_name }}</p>
    {% if client_email %}<p>{{ client_email }}</p>{% endif %}
    {% if client_address %}<p>{{ client_address|linebreaksbr }}</p>{% endif %}
  </section>
  <table class="dm-band-items">
    <thead style="background: {{ header_bg }}; color: {{ header_text_color }};">
      <tr>
        <th>Description</th>
        <th>Quantité</th>
        <th>Prix</th>
        <th>Total</th>
      </tr>
    </thead>
    <tbody>
      {% for item in items %}
      <tr>
        <td>{% if item.description %}{{ item.description }}{% else %}{{ item.name }}{% endif %}</td>
        <td class="dm-c">{{ item.quantity }}</td>
        <td class="dm-c">{{ item.unit_price }} {{ currency }}</td>
        <td class="dm-c">{{ item.total }} {{ currency }}</td>
      </tr>
      {% empty %}
      <tr><td colspan="4">—</td></tr>
      {% endfor %}
    </tbody>
  </table>
  <div class="dm-band-totals">
    <p><span>Sous total</span><span>{{ subtotal }} {{ currency }}</span></p>
    <p><span>TVA</span><span>{{ tax_amount }} {{ currency }}</span></p>
    <p class="dm-band-total-row"><span>Total</span><span>{{ total_amount }} {{ currency }}</span></p>
  </div>
  <footer class="dm-band-foot">
    <div>
      <p><strong>Mode de paiement :</strong> {{ payment_mode }}</p>
      <p><strong>Date d\'échéance :</strong> {{ due_date }}</p>
    </div>
    <div class="dm-band-sign">
      <p>{{ signature_label }}</p>
      <div class="dm-band-sign-line"></div>
    </div>
  </footer>
</div>
        '''.strip(),
        'css_styles': '''
.dm-band-doc { max-width: 800px; margin: 0 auto; background: #fff; }
.dm-band-header { display: flex; justify-content: space-between; align-items: flex-start; padding: {{ band_padding }}; gap: 16px; }
.dm-band-brand { display: flex; gap: 14px; align-items: flex-start; }
.dm-band-logo { width: 40px; height: 40px; border-radius: 8px; background: rgba(255,255,255,0.2); display: flex; align-items: center; justify-content: center; font-weight: 800; font-size: 18px; }
.dm-band-org { font-weight: 700; font-size: 16px; margin: 0 0 4px 0; }
.dm-band-meta { text-align: right; }
.dm-band-title { font-size: 26px; font-weight: 800; letter-spacing: 0.06em; margin: 0 0 8px 0; }
.dm-band-client { padding: 18px 20px; }
.dm-band-h { font-weight: 700; margin: 0 0 6px 0; }
.dm-band-strong { font-weight: 700; margin: 0; }
.dm-band-items { width: 100%; border-collapse: collapse; font-size: 13px; }
.dm-band-items th, .dm-band-items td { border: 1px solid #222; padding: 10px 8px; }
.dm-band-items th { text-align: left; }
.dm-c { text-align: center; }
.dm-band-totals { max-width: 280px; margin-left: auto; padding: 16px 20px; font-size: 13px; }
.dm-band-totals p { display: flex; justify-content: space-between; margin: 6px 0; }
.dm-band-total-row { font-weight: 800; font-size: 15px; border-top: 2px solid #000; padding-top: 10px; margin-top: 10px; }
.dm-band-foot { display: flex; justify-content: space-between; padding: 20px; border-top: 1px solid #ddd; font-size: 12px; gap: 24px; }
.dm-band-sign { text-align: center; min-width: 160px; }
.dm-band-sign-line { border-bottom: 1px solid #000; height: 48px; margin-top: 4px; }
        '''.strip(),
        'layout_config': {
            'variable_schema': {
                'fields': [
                    {'name': 'document_title', 'type': 'text', 'label': 'Titre document'},
                    {'name': 'font_family', 'type': 'text', 'label': 'Police'},
                    {'name': 'header_bg', 'type': 'color', 'label': 'Fond bandeau'},
                    {'name': 'header_text_color', 'type': 'color', 'label': 'Texte bandeau'},
                    {'name': 'body_text_color', 'type': 'text', 'label': 'Couleur texte corps'},
                    {'name': 'company_mark', 'type': 'text', 'label': 'Initiale / logo texte'},
                    {'name': 'band_padding', 'type': 'text', 'label': 'Padding bandeau'},
                    {'name': 'payment_mode', 'type': 'text', 'label': 'Mode de paiement'},
                    {'name': 'signature_label', 'type': 'text', 'label': 'Libellé signature'},
                ]
            }
        },
        'style_config': {
            'variables_defaults': {
                'document_title': 'FACTURE',
                'font_family': 'Montserrat, Arial, sans-serif',
                'header_bg': '#000000',
                'header_text_color': '#ffffff',
                'body_text_color': '#111111',
                'company_mark': 'M',
                'band_padding': '20px 24px',
                'payment_mode': 'Virement bancaire',
                'signature_label': 'Signature',
            }
        },
        'tags': ['facture', 'noir', 'moderne', 'bandeau', 'fr'],
        'compatible_types': ['invoice', 'quote'],
    },
    {
        'title': 'Devis moderne accent violet',
        'description': (
            'Devis avec en-têtes violet, zone client encadrée, lignes zébrées. '
            'Couleur d\'accent et textes légaux modifiables.'
        ),
        'demo_html': (
            '<div style="background:#5b2c91;color:#fff;padding:6px 10px;font:bold 14px sans-serif;">Devis</div>'
        ),
        'html_structure': '''
<div class="dm-purp-doc" style="font-family: {{ font_family }}; color: {{ text_color }};">
  <div class="dm-purp-top">
    <div class="dm-purp-logo">{{ logo_placeholder }}</div>
    <div class="dm-purp-title-block">
      <h1 class="dm-purp-title" style="color: {{ accent_color }};">{{ document_title }} {{ invoice_number }}</h1>
      <p>{{ city_date_prefix }} {{ issue_date }}</p>
    </div>
  </div>
  <div class="dm-purp-two">
    <div>
      <p class="dm-purp-strong">{{ organization_name }}</p>
      <p class="dm-purp-muted">{{ legal_form_line }}</p>
      {% if organization_address %}<p>{{ organization_address|linebreaksbr }}</p>{% endif %}
      {% if organization_postal_code or organization_city %}
      <p>{{ organization_postal_code }} {{ organization_city }}</p>
      {% endif %}
      {% if organization_phone %}<p>{{ organization_phone }}</p>{% endif %}
      {% if organization_email %}<p class="dm-purp-ul">{{ organization_email }}</p>{% endif %}
    </div>
    <div class="dm-purp-clientbox">
      <p class="dm-purp-strong">{{ client_name }}</p>
      {% if client_address %}<p>{{ client_address|linebreaksbr }}</p>{% endif %}
      {% if client_phone %}<p>{{ client_phone }}</p>{% endif %}
      {% if client_email %}<p class="dm-purp-ul">{{ client_email }}</p>{% endif %}
    </div>
  </div>
  <table class="dm-purp-table">
    <thead>
      <tr style="background: {{ accent_color }}; color: {{ accent_text_color }};">
        <th>Description</th>
        <th>Prix unitaire HT</th>
        <th>Unité</th>
        <th>Qté</th>
        <th>Montant HT</th>
      </tr>
    </thead>
    <tbody>
      {% for item in items %}
      <tr>
        <td>{% if item.description %}{{ item.description }}{% else %}{{ item.name }}{% endif %}</td>
        <td class="dm-r">{{ item.unit_price }} {{ currency }}</td>
        <td class="dm-c">{{ item.unit }}</td>
        <td class="dm-c">{{ item.quantity }}</td>
        <td class="dm-r">{{ item.total }} {{ currency }}</td>
      </tr>
      {% empty %}
      <tr><td colspan="5">—</td></tr>
      {% endfor %}
    </tbody>
  </table>
  <div class="dm-purp-totalbar" style="background: {{ accent_color }}; color: {{ accent_text_color }};">
    <span>Total HT</span>
    <span>{{ subtotal }} {{ currency }}</span>
  </div>
  <div class="dm-purp-bottom">
    <div class="dm-purp-terms">
      <p><strong>Modalités :</strong></p>
      <p>{{ tax_legal_mention }}</p>
    </div>
    <div>
      <p>{{ offer_valid_text }}</p>
      <p><strong>{{ signature_label }}</strong></p>
      <div class="dm-purp-signbox"></div>
    </div>
  </div>
  <p class="dm-purp-legalfoot">{{ company_legal_footer }}</p>
</div>
        '''.strip(),
        'css_styles': '''
.dm-purp-doc { max-width: 800px; margin: 0 auto; padding: {{ doc_padding }}; font-size: 13px; }
.dm-purp-top { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 20px; }
.dm-purp-logo { border: 1px dashed #999; padding: 16px 24px; color: #999; font-size: 12px; }
.dm-purp-title { margin: 0; font-size: 22px; font-weight: 800; }
.dm-purp-title-block { text-align: right; }
.dm-purp-two { display: table; width: 100%; margin-bottom: 18px; }
.dm-purp-two > div { display: table-cell; width: 50%; vertical-align: top; padding-right: 12px; }
.dm-purp-clientbox { border: 1px solid #111; padding: 12px; }
.dm-purp-strong { font-weight: 700; margin: 0 0 6px 0; }
.dm-purp-muted { color: #555; font-size: 12px; margin: 0 0 6px 0; }
.dm-purp-ul { text-decoration: underline; margin: 4px 0 0 0; }
.dm-purp-table { width: 100%; border-collapse: collapse; margin-bottom: 0; }
.dm-purp-table th, .dm-purp-table td { border: 1px solid #ccc; padding: 8px 10px; }
.dm-purp-table tbody tr:nth-child(even) { background: #f5f5f5; }
.dm-r { text-align: right; }
.dm-c { text-align: center; }
.dm-purp-totalbar { display: flex; justify-content: space-between; padding: 12px 16px; font-weight: 800; margin-top: -1px; }
.dm-purp-bottom { display: flex; justify-content: space-between; gap: 20px; margin-top: 16px; align-items: flex-start; }
.dm-purp-terms { flex: 1; border: 1px solid #111; padding: 10px; font-size: 11px; }
.dm-purp-signbox { border: 1px solid #111; height: 56px; margin-top: 8px; max-width: 200px; }
.dm-purp-legalfoot { text-align: center; font-size: 10px; color: #666; margin-top: 20px; }
        '''.strip(),
        'layout_config': {
            'variable_schema': {
                'fields': [
                    {'name': 'document_title', 'type': 'text', 'label': 'Titre'},
                    {'name': 'font_family', 'type': 'text', 'label': 'Police'},
                    {'name': 'text_color', 'type': 'text', 'label': 'Couleur texte'},
                    {'name': 'accent_color', 'type': 'color', 'label': 'Couleur accent'},
                    {'name': 'accent_text_color', 'type': 'color', 'label': 'Texte sur accent'},
                    {'name': 'doc_padding', 'type': 'text', 'label': 'Marges'},
                    {'name': 'logo_placeholder', 'type': 'text', 'label': 'Texte zone logo'},
                    {'name': 'city_date_prefix', 'type': 'text', 'label': 'Préfixe ville / date'},
                    {'name': 'legal_form_line', 'type': 'text', 'label': 'Forme juridique'},
                    {'name': 'tax_legal_mention', 'type': 'textarea', 'label': 'Mention TVA'},
                    {'name': 'offer_valid_text', 'type': 'text', 'label': 'Validité de l\'offre'},
                    {'name': 'signature_label', 'type': 'text', 'label': 'Libellé signature'},
                    {'name': 'company_legal_footer', 'type': 'textarea', 'label': 'Pied société (SIRET…)'},
                ]
            }
        },
        'style_config': {
            'variables_defaults': {
                'document_title': 'Devis N°',
                'font_family': 'Arial, Helvetica, sans-serif',
                'text_color': '#111111',
                'accent_color': '#5b2c91',
                'accent_text_color': '#ffffff',
                'doc_padding': '20px',
                'logo_placeholder': 'LOGO',
                'city_date_prefix': 'Ville, le',
                'legal_form_line': 'Entrepreneur individuel',
                'tax_legal_mention': 'TVA non applicable, article 293 B du CGI.',
                'offer_valid_text': "Offre valable jusqu'à la date d'échéance indiquée.",
                'signature_label': 'Signature :',
                'company_legal_footer': 'N° SIRET : à compléter — Capital social : à compléter',
            }
        },
        'tags': ['devis', 'violet', 'moderne', 'fr'],
        'compatible_types': ['invoice', 'quote'],
    },
    {
        'title': 'Devis classique noir et blanc',
        'description': (
            'Titre centré, bloc destinataire, tableau en-tête noir, totaux TTC, pied entreprise / banque.'
        ),
        'demo_html': (
            '<p style="text-align:center;font:bold italic 16px Georgia;">Devis # …</p>'
            '<div style="background:#000;height:28px;"></div>'
        ),
        'html_structure': '''
<div class="dm-nb-doc" style="font-family: {{ font_family }}; color: {{ text_color }};">
  <div class="dm-nb-headrow">
    <div>
      <p><strong>Date :</strong> {{ issue_date }}</p>
      <p><strong>Valable jusqu\'au :</strong> {{ due_date }}</p>
    </div>
    <div class="dm-nb-brand">{{ brand_text }}</div>
  </div>
  <h1 class="dm-nb-maintitle" style="font-family: {{ title_font }};">{{ document_title }} {{ invoice_number }}</h1>
  <div class="dm-nb-dest">
    <p class="dm-nb-dest-h">{{ recipient_heading }}</p>
    <p class="dm-nb-strong">{{ client_name }}</p>
    {% if client_address %}<p>{{ client_address|linebreaksbr }}</p>{% endif %}
    {% if client_registration_number %}<p>SIRET : {{ client_registration_number }}</p>{% endif %}
    {% if client_tax_id %}<p>N° TVA : {{ client_tax_id }}</p>{% endif %}
  </div>
  <table class="dm-nb-items">
    <thead>
      <tr>
        <th>Désignation</th>
        <th>Qté</th>
        <th>Prix</th>
        <th>Total</th>
        <th>TVA</th>
      </tr>
    </thead>
    <tbody>
      {% for item in items %}
      <tr>
        <td>{% if item.description %}{{ item.description }}{% else %}{{ item.name }}{% endif %}</td>
        <td class="dm-c">{{ item.quantity }}</td>
        <td class="dm-r">{{ item.unit_price }}</td>
        <td class="dm-r">{{ item.total }}</td>
        <td class="dm-c">{{ item.tax_rate }}%</td>
      </tr>
      {% empty %}
      <tr><td colspan="5">—</td></tr>
      {% endfor %}
    </tbody>
  </table>
  <div class="dm-nb-totals">
    <p><span>TOTAL HT</span><span>{{ subtotal }} {{ currency }}</span></p>
    <p><span>TVA</span><span>{{ tax_amount }} {{ currency }}</span></p>
    <p class="dm-nb-ttc"><span>Total TTC</span><span>{{ total_amount }} {{ currency }}</span></p>
  </div>
  <div class="dm-nb-foot">
    <div>
      <p class="dm-nb-strong">{{ organization_name }}</p>
      {% if organization_address %}<p>{{ organization_address|linebreaksbr }}</p>{% endif %}
      {% if organization_registration_number %}<p>SIRET : {{ organization_registration_number }}</p>{% endif %}
      {% if organization_tax_id %}<p>N° TVA : {{ organization_tax_id }}</p>{% endif %}
      {% if organization_phone %}<p>Tél : {{ organization_phone }}</p>{% endif %}
    </div>
    <div>
      <p class="dm-nb-strong">{{ bank_block_title }}</p>
      <p>{{ bank_name }}</p>
      <p>SWIFT/BIC : {{ bank_bic }}</p>
      <p>IBAN : {{ bank_iban }}</p>
    </div>
  </div>
</div>
        '''.strip(),
        'css_styles': '''
.dm-nb-doc { max-width: 800px; margin: 0 auto; padding: {{ doc_padding }}; font-size: 13px; }
.dm-nb-headrow { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px; }
.dm-nb-brand { font-weight: 700; font-size: 12px; text-align: right; }
.dm-nb-maintitle { text-align: center; font-size: 24px; font-weight: 700; font-style: italic; margin: 12px 0 20px 0; }
.dm-nb-dest { text-align: right; margin-bottom: 18px; max-width: 360px; margin-left: auto; }
.dm-nb-dest-h { text-decoration: underline; font-weight: 600; margin: 0 0 8px 0; }
.dm-nb-strong { font-weight: 700; margin: 0 0 4px 0; }
.dm-nb-items { width: 100%; border-collapse: collapse; margin-bottom: 12px; }
.dm-nb-items thead tr { background: {{ table_header_bg }}; color: {{ table_header_color }}; }
.dm-nb-items th { text-transform: uppercase; font-size: 11px; letter-spacing: 0.04em; padding: 10px 8px; text-align: center; }
.dm-nb-items td { border: 1px solid #ccc; padding: 8px; }
.dm-nb-items th:first-child, .dm-nb-items td:first-child { text-align: left; }
.dm-r { text-align: right; }
.dm-c { text-align: center; }
.dm-nb-totals { max-width: 280px; margin-left: auto; text-align: right; font-size: 13px; }
.dm-nb-totals p { display: flex; justify-content: space-between; gap: 24px; margin: 6px 0; }
.dm-nb-ttc { font-weight: 800; font-size: 15px; margin-top: 10px; }
.dm-nb-foot { display: flex; justify-content: space-between; gap: 24px; border-top: 1px solid #ccc; margin-top: 24px; padding-top: 16px; font-size: 11px; }
        '''.strip(),
        'layout_config': {
            'variable_schema': {
                'fields': [
                    {'name': 'document_title', 'type': 'text', 'label': 'Titre avant n°'},
                    {'name': 'font_family', 'type': 'text', 'label': 'Police corps'},
                    {'name': 'title_font', 'type': 'text', 'label': 'Police titre'},
                    {'name': 'text_color', 'type': 'text', 'label': 'Couleur texte'},
                    {'name': 'table_header_bg', 'type': 'color', 'label': 'Fond en-tête tableau'},
                    {'name': 'table_header_color', 'type': 'color', 'label': 'Texte en-tête tableau'},
                    {'name': 'doc_padding', 'type': 'text', 'label': 'Marges'},
                    {'name': 'brand_text', 'type': 'text', 'label': 'Texte marque (coin)'},
                    {'name': 'recipient_heading', 'type': 'text', 'label': 'Titre bloc client'},
                    {'name': 'bank_block_title', 'type': 'text', 'label': 'Titre bloc banque'},
                    {'name': 'bank_name', 'type': 'text', 'label': 'Nom banque'},
                    {'name': 'bank_bic', 'type': 'text', 'label': 'SWIFT/BIC'},
                    {'name': 'bank_iban', 'type': 'text', 'label': 'IBAN'},
                ]
            }
        },
        'style_config': {
            'variables_defaults': {
                'document_title': 'Devis #',
                'font_family': 'Arial, Helvetica, sans-serif',
                'title_font': 'Georgia, Times New Roman, serif',
                'text_color': '#111111',
                'table_header_bg': '#000000',
                'table_header_color': '#ffffff',
                'doc_padding': '20px',
                'brand_text': 'Votre marque',
                'recipient_heading': 'DESTINATAIRE',
                'bank_block_title': 'Coordonnées bancaires',
                'bank_name': 'Nom de la banque',
                'bank_bic': '—',
                'bank_iban': '—',
            }
        },
        'tags': ['devis', 'facture', 'noir', 'classique', 'fr'],
        'compatible_types': ['invoice', 'quote'],
    },
]
