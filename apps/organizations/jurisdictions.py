"""
Règles de facturation par pays : taxe (TVA, VAT, GST, Sales tax), taux, seuil de franchise,
identifiants obligatoires, mentions à imprimer et liste de contrôle, selon le statut.

Pays suivis : les 27 pays de l'UE, le Royaume-Uni, les États-Unis, le Canada, l'Australie et
la Nouvelle-Zélande. Ailleurs (« autre pays »), Billio fait une facturation simple et un export
comptable, sans promettre la conformité fiscale locale.

Le profil de l'organisation tient en trois réponses, rangées dans
`Organization.billing_preferences['compliance']` :
    {'country': 'FR', 'status': 'freelance' | 'pme' | 'entreprise', 'tax_registered': bool,
     'region': 'ON' (province canadienne, facultatif), 'doc_language': 'fr' | 'en' | 'de' | 'es',
     'company_details': 'SAS au capital de…', 'confirmed': bool}
`apply_profile` en déduit la devise, les taux de taxe, la franchise et les mentions imprimées.

Ce module ne remplace pas un conseil fiscal : les textes affichés le disent, et les seuils
cités sont ceux connus en 2026 (à revoir chaque année).
"""
import re
from decimal import Decimal

STATUSES = ('freelance', 'pme', 'entreprise')
STATUS_LABELS = {'freelance': 'Freelance / indépendant', 'pme': 'PME / petite société', 'entreprise': 'Entreprise'}
# Exemples de formes juridiques montrés sous chaque statut, pour que chacun se reconnaisse.
STATUS_EXAMPLES = {
    'FR': ('Micro-entrepreneur, entreprise individuelle', 'SASU, EURL, SARL, SAS', 'SA, grande SAS'),
    'BE': ('Indépendant en personne physique', 'SRL, SC', 'SA'),
    'LU': ('Indépendant', 'SARL, SARL-S', 'SA'),
    'DE': ('Freiberufler, Einzelunternehmer', 'GmbH, UG', 'AG'),
    'AT': ('Einzelunternehmer', 'GmbH', 'AG'),
    'ES': ('Autónomo', 'SL', 'SA'),
    'IT': ('Libero professionista, ditta individuale', 'SRL', 'SPA'),
    'GB': ('Sole trader', 'Limited company (Ltd)', 'PLC'),
    'US': ('Sole proprietor', 'LLC', 'Corporation'),
    'CA': ('Travailleur autonome', 'Société par actions (Inc.)', 'Grande entreprise'),
    'AU': ('Sole trader', 'Pty Ltd', 'Public company'),
    'NZ': ('Sole trader', 'Limited company', 'Large company'),
}
DEFAULT_EXAMPLES = ('Indépendant, auto-entrepreneur', 'Petite société', "Grande entreprise, groupe")
DOC_LANGUAGES = {'fr': 'Français', 'en': 'English', 'de': 'Deutsch', 'es': 'Español'}

# ---------------------------------------------------------------------------
# Union européenne : (nom, taux normal, taux réduits courants, devise, langue des documents,
# mention de franchise dans la langue du pays ou None → mention européenne générique)
# ---------------------------------------------------------------------------
EU = {
    'AT': ('Autriche', '20', ['13', '10'], 'EUR', 'de', 'Umsatzsteuerbefreit – Kleinunternehmer gemäß § 6 Abs. 1 Z 27 UStG.'),
    'BE': ('Belgique', '21', ['12', '6'], 'EUR', 'fr', 'Régime particulier de franchise des petites entreprises.'),
    'BG': ('Bulgarie', '20', ['9'], 'BGN', 'en', None),
    'HR': ('Croatie', '25', ['13', '5'], 'EUR', 'en', None),
    'CY': ('Chypre', '19', ['9', '5'], 'EUR', 'en', None),
    'CZ': ('Tchéquie', '21', ['12'], 'CZK', 'en', None),
    'DK': ('Danemark', '25', [], 'DKK', 'en', None),
    'EE': ('Estonie', '24', ['13', '9'], 'EUR', 'en', None),
    'FI': ('Finlande', '25.5', ['14', '10'], 'EUR', 'en', None),
    'FR': ('France', '20', ['10', '5.5', '2.1'], 'EUR', 'fr', 'TVA non applicable, art. 293 B du CGI.'),
    'DE': ('Allemagne', '19', ['7'], 'EUR', 'de', 'Gemäß § 19 UStG wird keine Umsatzsteuer berechnet.'),
    'GR': ('Grèce', '24', ['13', '6'], 'EUR', 'en', None),
    'HU': ('Hongrie', '27', ['18', '5'], 'HUF', 'en', None),
    'IE': ('Irlande', '23', ['13.5', '9'], 'EUR', 'en', None),
    'IT': ('Italie', '22', ['10', '5', '4'], 'EUR', 'en',
           'Operazione in franchigia da IVA ai sensi dell’art. 1, commi 54-89, L. 190/2014.'),
    'LV': ('Lettonie', '21', ['12', '5'], 'EUR', 'en', None),
    'LT': ('Lituanie', '21', ['9', '5'], 'EUR', 'en', None),
    'LU': ('Luxembourg', '17', ['14', '8', '3'], 'EUR', 'fr', 'Franchise de TVA – article 57 de la loi TVA.'),
    'MT': ('Malte', '18', ['7', '5'], 'EUR', 'en', None),
    'NL': ('Pays-Bas', '21', ['9'], 'EUR', 'en', None),
    'PL': ('Pologne', '23', ['8', '5'], 'PLN', 'en', None),
    'PT': ('Portugal', '23', ['13', '6'], 'EUR', 'en', None),
    'RO': ('Roumanie', '21', ['11'], 'RON', 'en', None),
    'SK': ('Slovaquie', '23', ['19', '5'], 'EUR', 'en', None),
    'SI': ('Slovénie', '22', ['9.5', '5'], 'EUR', 'en', None),
    'ES': ('Espagne', '21', ['10', '4'], 'EUR', 'es', None),
    'SE': ('Suède', '25', ['12', '6'], 'SEK', 'en', None),
}
EU_GENERIC_EXEMPTION = 'VAT exempt – small enterprise scheme (Article 284 of Council Directive 2006/112/EC).'
# Préfixe du numéro de TVA intracommunautaire (la Grèce utilise EL).
EU_VAT_PREFIX = {code: ('EL' if code == 'GR' else code) for code in EU}

CA_PROVINCES = {
    # province : (nom, [(libellé, taux)])
    'AB': ('Alberta', [('GST', '5')]), 'BC': ('Colombie-Britannique', [('GST', '5')]),
    'MB': ('Manitoba', [('GST', '5')]), 'NB': ('Nouveau-Brunswick', [('HST', '15')]),
    'NL': ('Terre-Neuve-et-Labrador', [('HST', '15')]), 'NS': ('Nouvelle-Écosse', [('HST', '14')]),
    'NT': ('Territoires du Nord-Ouest', [('GST', '5')]), 'NU': ('Nunavut', [('GST', '5')]),
    'ON': ('Ontario', [('HST', '13')]), 'PE': ('Île-du-Prince-Édouard', [('HST', '15')]),
    'QC': ('Québec', [('TPS + TVQ', '14.975'), ('TPS', '5')]), 'SK': ('Saskatchewan', [('GST', '5')]),
    'YT': ('Yukon', [('GST', '5')]),
}

OTHER_NOTE = ("Billio ne connaît pas les règles fiscales de ce pays : vos factures restent simples "
              "(numérotation continue, montants, taxe que vous saisissez) et l'export comptable reste disponible. "
              "Faites valider vos mentions par un comptable local.")


# Préposition devant le nom du pays (« en France », « au Canada », « aux États-Unis », « à Malte »).
PREPOSITIONS = {'CA': 'au', 'DK': 'au', 'GB': 'au', 'LU': 'au', 'PT': 'au', 'NL': 'aux', 'US': 'aux', 'CY': 'à', 'MT': 'à'}


def _base(code, name, **extra):
    pack = {
        'code': code, 'name': name, 'prep': PREPOSITIONS.get(code, 'en'), 'supported': True, 'region': code.lower(),
        'tax_name': 'VAT', 'tax_ui': 'la TVA', 'rates': [], 'currency': 'EUR', 'doc_language': 'en',
        'threshold': '', 'tax_id_label': 'Numéro de TVA', 'tax_id_hint': '', 'registration_label': "Numéro d'immatriculation",
        'registration_required': ('pme', 'entreprise'), 'company_details_hint': '',
        'exemption_mention': None, 'tax_invoice_title': False, 'note': '',
    }
    pack.update(extra)
    return pack


def _eu_pack(code):
    name, standard, reduced, currency, lang, exemption = EU[code]
    tax_name = {'fr': 'TVA', 'de': 'USt.', 'es': 'IVA'}.get(lang, 'VAT')
    pack = _base(
        code, name, region='eu', tax_name=tax_name, currency=currency, doc_language=lang,
        rates=[standard, *reduced],
        threshold=("La franchise des petites entreprises dispense de TVA sous un plafond de chiffre d'affaires "
                   "fixé par chaque pays (régime européen PME, directive 2020/285)."),
        tax_id_label='Numéro de TVA intracommunautaire', tax_id_hint=f'{EU_VAT_PREFIX[code]} suivi de votre numéro',
        exemption_mention=exemption or EU_GENERIC_EXEMPTION,
        company_details_hint='Forme juridique, capital, numéro au registre du commerce',
    )
    if code == 'FR':
        pack.update(
            threshold=("Franchise en base (art. 293 B du CGI) : pas de TVA sous 37 500 € de prestations de services "
                       "ou 85 000 € de ventes par an. Au-delà, vous facturez la TVA."),
            registration_label='SIRET', registration_required=STATUSES, tax_id_hint='FR + 11 chiffres',
            company_details_hint='Ex. SAS au capital de 1 000 € – RCS Paris 123 456 789',
        )
    elif code == 'DE':
        pack.update(threshold="Kleinunternehmerregelung (§ 19 UStG) : pas de TVA sous 25 000 € de chiffre d'affaires l'année précédente.",
                    registration_label='Steuernummer', registration_required=STATUSES, tax_id_label='USt-IdNr.')
    elif code == 'BE':
        pack.update(threshold="Franchise des petites entreprises : pas de TVA sous 25 000 € de chiffre d'affaires par an.",
                    registration_label="Numéro d'entreprise (BCE)", registration_required=STATUSES)
    elif code == 'ES':
        pack.update(registration_label='NIF', registration_required=STATUSES, tax_id_label='NIF-IVA')
    elif code == 'IT':
        pack.update(threshold="Regime forfettario : pas d'IVA sous 85 000 € de chiffre d'affaires par an.",
                    registration_label='Codice fiscale', registration_required=STATUSES, tax_id_label='Partita IVA')
    return pack


PACKS = {code: _eu_pack(code) for code in EU}
PACKS['GB'] = _base(
    'GB', 'Royaume-Uni', currency='GBP', rates=['20', '5', '0'],
    threshold="Inscription à la VAT obligatoire au-delà de 90 000 £ de chiffre d'affaires sur 12 mois glissants.",
    tax_id_label='VAT registration number', tax_id_hint='GB + 9 chiffres', registration_label='Company number',
    company_details_hint='Ex. Registered in England and Wales, company no. 01234567, registered office: …',
)
PACKS['US'] = _base(
    'US', 'États-Unis', tax_name='Sales tax', tax_ui='la sales tax', currency='USD', rates=[],
    threshold=("Pas de TVA fédérale. La sales tax dépend de chaque État (et souvent ne s'applique pas aux "
               "services) : Billio ne la calcule pas pour vous, saisissez le taux de votre État si vous y êtes soumis."),
    tax_id_label='Sales tax permit number', registration_label='EIN (facultatif)', registration_required=(),
    company_details_hint='Ex. Lumen Studio LLC, Delaware',
)
PACKS['CA'] = _base(
    'CA', 'Canada', tax_name='GST/HST', tax_ui='la TPS/TVH', currency='CAD', rates=[],
    threshold=("Petit fournisseur : pas d'inscription à la TPS/TVH obligatoire sous 30 000 $ CA de ventes "
               "sur quatre trimestres. Le taux dépend de la province de votre client."),
    tax_id_label="Numéro d'entreprise (BN) pour la TPS/TVH", tax_id_hint='9 chiffres + RT0001',
    registration_label="Numéro d'entreprise du Québec (NEQ) ou d'immatriculation", registration_required=(),
    company_details_hint='Ex. Studio Lumen Inc., constituée en Ontario',
)
PACKS['AU'] = _base(
    'AU', 'Australie', tax_name='GST', tax_ui='la GST', currency='AUD', rates=['10', '0'],
    threshold="Inscription à la GST obligatoire au-delà de 75 000 A$ de chiffre d'affaires annuel.",
    tax_id_label='ABN', tax_id_hint='11 chiffres', registration_label='ACN (sociétés)', tax_invoice_title=True,
    company_details_hint='Ex. Lumen Studio Pty Ltd, ACN 123 456 789',
)
PACKS['NZ'] = _base(
    'NZ', 'Nouvelle-Zélande', tax_name='GST', tax_ui='la GST', currency='NZD', rates=['15', '0'],
    threshold="Inscription à la GST obligatoire au-delà de 60 000 NZ$ de chiffre d'affaires sur 12 mois.",
    tax_id_label='GST number', tax_id_hint='8 ou 9 chiffres', registration_label='NZBN', tax_invoice_title=True,
    company_details_hint='Ex. Lumen Studio Limited, NZBN 9429…',
)
SUPPORTED = sorted(PACKS, key=lambda c: PACKS[c]['name'])

OTHER = _base('OTHER', 'Autre pays', supported=False, tax_name='Tax', tax_ui='une taxe', currency='', doc_language='',
              registration_required=(), note=OTHER_NOTE)

# Noms de pays (tels que saisis dans Organization.country ou Client.country) → code ISO.
_NAMES = {pack['name'].lower(): code for code, pack in PACKS.items()}
_NAMES.update({
    'austria': 'AT', 'belgium': 'BE', 'bulgaria': 'BG', 'croatia': 'HR', 'cyprus': 'CY', 'czechia': 'CZ',
    'czech republic': 'CZ', 'denmark': 'DK', 'estonia': 'EE', 'finland': 'FI', 'germany': 'DE', 'greece': 'GR',
    'hungary': 'HU', 'ireland': 'IE', 'italy': 'IT', 'latvia': 'LV', 'lithuania': 'LT', 'malta': 'MT',
    'netherlands': 'NL', 'poland': 'PL', 'romania': 'RO', 'slovakia': 'SK', 'slovenia': 'SI', 'spain': 'ES',
    'sweden': 'SE', 'united kingdom': 'GB', 'uk': 'GB', 'royaume uni': 'GB', 'angleterre': 'GB', 'england': 'GB',
    'united states': 'US', 'usa': 'US', 'etats-unis': 'US', 'etats unis': 'US', 'australia': 'AU',
    'new zealand': 'NZ', 'nouvelle zelande': 'NZ', 'république tchèque': 'CZ', 'suede': 'SE', 'grece': 'GR',
})


def country_code(value):
    """Code ISO à partir d'un code ou d'un nom de pays (FR, « France », « United Kingdom »…) ; '' si inconnu."""
    text = (value or '').strip()
    if len(text) == 2 and text.isalpha():
        return text.upper()
    return _NAMES.get(text.lower(), '')


def pack_for(code):
    return PACKS.get((code or '').upper(), OTHER)


def is_eu(code):
    return (code or '').upper() in EU


# ---------------------------------------------------------------------------
# Profil de l'organisation
# ---------------------------------------------------------------------------

def profile(organization):
    """Profil enregistré, complété par ce que l'on sait déjà (pays saisi, franchise de TVA)."""
    prefs = organization.billing_preferences or {}
    saved = dict(prefs.get('compliance') or {})
    # Pays inconnu (comptes créés avant l'assistant, sans pays saisi) : France, l'usage historique de Billio.
    code = saved.get('country') or country_code(organization.country) or ('' if organization.country else 'FR')
    pack = pack_for(code)
    status = saved.get('status') if saved.get('status') in STATUSES else (
        'freelance' if organization.type == 'freelancer' else 'pme')
    registered = saved.get('tax_registered')
    if registered is None:
        registered = not prefs.get('vat_exempt', False) if pack['supported'] else False
    return {
        'country': code if pack['supported'] else (code or ''),
        'status': status,
        'tax_registered': bool(registered),
        'region': saved.get('region', ''),
        'doc_language': saved.get('doc_language') or pack['doc_language'] or (organization.default_language if organization.default_language in DOC_LANGUAGES else 'en'),
        'company_details': saved.get('company_details', ''),
        'confirmed': bool(saved.get('confirmed')),
    }


def tax_rates(pack, prof):
    """[(nom, taux)] à proposer dans l'éditeur de facture."""
    if not prof['tax_registered']:
        return [(_exempt_rate_name(pack, prof), Decimal('0'))]
    if pack['code'] == 'CA':
        province = CA_PROVINCES.get(prof.get('region') or '', ('', [('GST', '5')]))[1]
        rates = province + [('GST', '5'), ('HST 13 %', '13'), ('HST 15 %', '15')]
        seen, result = set(), []
        for label, rate in rates:
            if rate not in seen:
                seen.add(rate)
                result.append((f'{label} {rate.replace(".", ",")} %' if '%' not in label else label, Decimal(rate)))
        return result
    name = pack['tax_name']
    return [(f"{name} {rate.replace('.', ',')} %", Decimal(rate)) for rate in pack['rates']]


def _exempt_rate_name(pack, prof):
    return {'fr': 'Exonéré (0 %)', 'de': 'Steuerfrei (0 %)', 'es': 'Exento (0 %)'}.get(prof['doc_language'], 'No tax (0%)')


def apply_profile(organization, data):
    """Enregistre le profil et règle l'organisation en conséquence. Renvoie le profil."""
    from apps.invoices.models import Tax

    code = (data.get('country') or '').upper()
    pack = pack_for(code)
    status = data.get('status') if data.get('status') in STATUSES else 'freelance'
    prof = {
        'country': code if pack['supported'] else (code or 'OTHER'),
        'status': status,
        'tax_registered': bool(data.get('tax_registered')),
        'region': (data.get('region') or '').upper() if code == 'CA' else '',
        'doc_language': data.get('doc_language') if data.get('doc_language') in DOC_LANGUAGES else (
            pack['doc_language'] or (organization.default_language if organization.default_language in DOC_LANGUAGES else 'en')),
        'company_details': (data.get('company_details') or '').strip()[:300],
        'confirmed': bool(data.get('confirmed', True)),
    }
    prefs = dict(organization.billing_preferences or {})
    prefs['compliance'] = prof
    prefs['vat_exempt'] = not prof['tax_registered']
    organization.billing_preferences = prefs
    fields = ['billing_preferences', 'updated_at']
    if pack['supported']:
        organization.country = pack['name']
        fields.append('country')
        if pack['currency']:
            organization.default_currency = pack['currency']
            fields.append('default_currency')
    organization.save(update_fields=fields)

    rates = tax_rates(pack, prof) if pack['supported'] or not prof['tax_registered'] else []
    existing = {Decimal(t.rate).normalize(): t for t in Tax.objects.filter(organization=organization)}
    for index, (name, rate) in enumerate(rates):
        tax = existing.get(rate.normalize())
        if tax is None:
            tax = Tax.objects.create(organization=organization, name=name, rate=rate, is_active=True)
        elif not tax.is_active:
            tax.is_active = True
            tax.save(update_fields=['is_active'])
        if index == 0:
            Tax.objects.filter(organization=organization, is_default=True).exclude(pk=tax.pk).update(is_default=False)
            if not tax.is_default:
                tax.is_default = True
                tax.save(update_fields=['is_default'])
    return prof


# ---------------------------------------------------------------------------
# Textes imprimés (dans la langue des documents)
# ---------------------------------------------------------------------------

PAYMENT_TERMS = {
    'fr': ("Paiement à {days} jours à réception de facture, par virement bancaire.", "Paiement à réception de facture, par virement bancaire."),
    'en': ("Payment due within {days} days of the invoice date, by bank transfer.", "Payment due on receipt, by bank transfer."),
    'de': ("Zahlbar innerhalb von {days} Tagen nach Rechnungsdatum per Überweisung.", "Zahlbar sofort nach Erhalt per Überweisung."),
    'es': ("Pago a {days} días desde la fecha de factura, por transferencia bancaria.", "Pago a la recepción de la factura, por transferencia bancaria."),
}
NO_TAX_MENTIONS = {
    'GB': 'Not registered for VAT.',
    'AU': 'Not registered for GST – no GST has been charged.',
    'NZ': 'Not registered for GST – no GST has been charged.',
    'CA': "Small supplier – not registered for GST/HST.",
}


def exemption_mention(pack, prof):
    """Mention imprimée quand l'organisation ne facture pas de taxe ('' si le pays n'en prévoit pas)."""
    if pack['region'] == 'eu':
        local = pack['exemption_mention']
        return local if prof['doc_language'] == pack['doc_language'] or local == EU_GENERIC_EXEMPTION else EU_GENERIC_EXEMPTION
    return NO_TAX_MENTIONS.get(pack['code'], '')


def exemption_ui(organization):
    """Libellés de l'option « je ne facture pas de taxe » selon le pays (Paramètres, Ressources)."""
    prof = profile(organization)
    pack = pack_for(prof['country'])
    code = pack['code']
    if code == 'FR':
        label, short = 'Franchise en base de TVA', 'Franchise (293 B)'
    elif pack['region'] == 'eu':
        label, short = 'Franchise de TVA des petites entreprises', 'Franchise de TVA'
    elif code == 'US':
        label, short = 'Je ne facture pas de sales tax', 'Sans sales tax'
    elif pack['supported']:
        label, short = f"Je ne suis pas inscrit à la {pack['tax_name']}", f"Non inscrit ({pack['tax_name']})"
    else:
        label, short = 'Je ne facture pas de taxe', 'Sans taxe'
    mention = exemption_mention(pack, prof)
    detail = (f'Nouvelles lignes à 0 % et mention « {mention} » sur vos factures.' if mention
              else 'Nouvelles lignes à 0 %, sans mention de taxe sur vos factures.')
    return {'label': label, 'short': short, 'detail': detail, 'mention': mention, 'tax_name': pack['tax_name']}


def set_tax_exempt(prefs, exempt):
    """Coche « franchise / pas de taxe » : garde le profil pays d'accord (sinon il l'emporte sur la case)."""
    prefs['vat_exempt'] = bool(exempt)
    if prefs.get('compliance'):
        prefs['compliance'] = dict(prefs['compliance'], tax_registered=not exempt)
    return prefs


def legal_texts(organization, prefs):
    """{'legal_mentions', 'payment_terms'} selon le pays ; None pour la France (textes historiques)."""
    prof = profile(organization)
    code = prof['country']
    if code == 'FR' and prof['doc_language'] == 'fr':
        return None
    pack = pack_for(code)
    lang = prof['doc_language']
    raw_days = prefs.get('payment_days')
    days = int(raw_days if raw_days is not None else (organization.default_payment_terms or 30))
    with_days, on_receipt = PAYMENT_TERMS.get(lang, PAYMENT_TERMS['en'])
    legal = []
    if not prof['tax_registered'] and exemption_mention(pack, prof):
        legal.append(exemption_mention(pack, prof))
    # Indemnité de recouvrement de 40 € (directive 2011/7/UE) : entre professionnels.
    if pack['region'] == 'eu' and (prof['status'] != 'freelance' or code in ('FR', 'BE', 'LU')):
        legal.append({
            'fr': "En cas de retard de paiement, une indemnité forfaitaire de 40 € pour frais de recouvrement sera exigible.",
            'de': 'Bei Zahlungsverzug wird eine Pauschale von 40 € für Beitreibungskosten fällig.',
            'es': 'En caso de demora en el pago, se exigirá una indemnización fija de 40 € por costes de cobro.',
        }.get(lang, 'Late payments incur statutory interest and a fixed €40 recovery fee (Directive 2011/7/EU).'))
    if prof['company_details']:
        legal.append(prof['company_details'])
    if prefs.get('trade_mentions') and lang == 'fr':
        legal.append(prefs['trade_mentions'])
    return {'legal_mentions': ' '.join(legal), 'payment_terms': with_days.format(days=days) if days else on_receipt}


def document_title(organization, credit_note=False):
    """Titre imprimé de la facture : « Tax invoice » en Australie / Nouvelle-Zélande si inscrit à la GST."""
    prof = profile(organization)
    pack = pack_for(prof['country'])
    lang = prof['doc_language']
    if credit_note:
        return {'fr': 'Avoir', 'de': 'Gutschrift', 'es': 'Factura rectificativa'}.get(lang, 'Credit note')
    if pack['tax_invoice_title'] and prof['tax_registered']:
        return 'Tax invoice'
    return {'fr': 'Facture', 'de': 'Rechnung', 'es': 'Factura'}.get(lang, 'Invoice')


# ---------------------------------------------------------------------------
# Identifiants
# ---------------------------------------------------------------------------

def _luhn_ok(digits):
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


def _abn_ok(digits):
    weights = [10, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19]
    values = [int(d) for d in digits]
    values[0] -= 1
    return sum(v * w for v, w in zip(values, weights)) % 89 == 0


def check_tax_id(code, value):
    """'' si le numéro de taxe a une forme plausible pour ce pays, sinon une explication."""
    raw = re.sub(r'[\s.\-]', '', value or '').upper()
    if not raw:
        return 'manquant'
    if code in EU:
        prefix = EU_VAT_PREFIX[code]
        if not raw.startswith(prefix) or not re.fullmatch(r'[A-Z0-9]{2,13}', raw[2:]):
            return f'doit commencer par {prefix}'
        if code == 'FR' and not re.fullmatch(r'FR[0-9A-Z]{2}\d{9}', raw):
            return 'format attendu : FR + 2 caractères + SIREN (9 chiffres)'
        return ''
    if code == 'GB':
        return '' if re.fullmatch(r'(GB)?(\d{9}|\d{12})', raw) else 'format attendu : GB + 9 chiffres'
    if code == 'AU':
        digits = re.sub(r'\D', '', raw)
        return '' if len(digits) == 11 and _abn_ok(digits) else 'un ABN compte 11 chiffres (clé de contrôle invalide)'
    if code == 'NZ':
        return '' if re.fullmatch(r'\d{8,9}', re.sub(r'\D', '', raw)) else 'un numéro de GST compte 8 ou 9 chiffres'
    if code == 'CA':
        return '' if re.fullmatch(r'\d{9}(RT\d{4})?', raw) else 'format attendu : 9 chiffres + RT0001'
    return ''


def check_registration(code, value):
    raw = re.sub(r'\s', '', value or '')
    if not raw:
        return 'manquant'
    if code == 'FR':
        digits = re.sub(r'\D', '', raw)
        if len(digits) != 14 or not _luhn_ok(digits):
            return 'un SIRET compte 14 chiffres'
    if code == 'AU':
        digits = re.sub(r'\D', '', raw)
        if len(digits) not in (9, 11):
            return 'un ACN compte 9 chiffres'
    return ''


# ---------------------------------------------------------------------------
# Liste de contrôle (assistant de conformité)
# ---------------------------------------------------------------------------

def checklist(organization, prof=None):
    """[{'label', 'ok', 'level' ('required' | 'recommended'), 'detail', 'tab'}] pour l'organisation."""
    from apps.invoices.models import Tax

    prof = prof or profile(organization)
    code = prof['country']
    pack = pack_for(code)
    items = []

    def add(label, ok, *, level='required', detail='', tab='entreprise'):
        items.append({'label': label, 'ok': bool(ok), 'level': level, 'detail': '' if ok else detail, 'tab': tab})

    add("Nom de l'entreprise", organization.name, detail='Il apparaît en tête de chaque facture.')
    add('Adresse complète', organization.address and organization.city and organization.postal_code,
        detail='Rue, code postal et ville.')
    if not pack['supported']:
        add('Taux de taxe vérifié par votre comptable', False, level='recommended', detail=OTHER_NOTE, tab='facturation')
        return items

    if prof['status'] in pack['registration_required']:
        problem = check_registration(code, organization.registration_number)
        add(pack['registration_label'], not problem, detail=f"{pack['registration_label']} : {problem}.")
    elif code != 'US':
        add(pack['registration_label'], organization.registration_number, level='recommended',
            detail='Conseillé : il rassure vos clients et facilite leurs paiements.')

    if prof['tax_registered']:
        problem = check_tax_id(code, organization.tax_id)
        add(pack['tax_id_label'], not problem, detail=f"{pack['tax_id_label']} : {problem}.")
        add(f"Taux de {pack['tax_name']} prêts dans l'éditeur", Tax.objects.filter(organization=organization, is_active=True, rate__gt=0).exists(),
            detail='Enregistrez vos réponses ci-dessus : Billio crée les taux du pays.', tab='conformite')
        if code == 'CA' and not prof.get('region'):
            add('Province choisie', False, detail='Le taux de TPS/TVH dépend de la province.', tab='conformite')
    elif code == 'AU':
        add('ABN', organization.tax_id or organization.registration_number, level='recommended',
            detail="Sans ABN sur la facture, votre client doit retenir 47 % du paiement (PAYG withholding).")

    if prof['status'] != 'freelance' and (pack['region'] == 'eu' or code in ('GB', 'AU', 'NZ')):
        add('Mentions de votre société', prof['company_details'], tab='conformite',
            detail=f"Forme juridique et immatriculation, imprimées sur vos factures. {pack['company_details_hint']}")
    add('Coordonnées de paiement', organization.iban or organization.payment_instructions, level='recommended',
        detail='IBAN ou instructions de paiement, pour être payé plus vite.', tab='paiement')
    if pack['currency'] and organization.default_currency != pack['currency']:
        add(f"Devise du pays ({pack['currency']})", False, level='recommended', tab='facturation',
            detail=f"Vos factures sont en {organization.default_currency} par défaut.")
    return items


def assistant_data():
    """Données des pays pour l'assistant (Paramètres › Pays & conformité)."""
    data = {}
    for code in [*SUPPORTED, 'OTHER']:
        pack = pack_for(code)
        data[code] = {
            'name': pack['name'], 'tax': pack['tax_ui'], 'threshold': pack['threshold'], 'note': pack['note'],
            'supported': pack['supported'], 'language': pack['doc_language'] or 'fr',
            'examples': dict(zip(STATUSES, STATUS_EXAMPLES.get(code, DEFAULT_EXAMPLES))),
            'company_hint': pack['company_details_hint'],
        }
    return data


def readiness(items):
    """'ready' (tout l'obligatoire est fait), 'almost' (il manque du conseillé) ou 'todo'."""
    if any(not i['ok'] and i['level'] == 'required' for i in items):
        return 'todo'
    return 'almost' if any(not i['ok'] for i in items) else 'ready'


# ---------------------------------------------------------------------------
# Une facture précise : mentions automatiques et vérification avant envoi
# ---------------------------------------------------------------------------

REVERSE_CHARGE = {
    'fr': 'Autoliquidation – TVA due par le preneur (art. 196 de la directive 2006/112/CE).',
    'en': 'Reverse charge – VAT to be accounted for by the customer (Article 196, Council Directive 2006/112/EC).',
    'de': 'Steuerschuldnerschaft des Leistungsempfängers (Reverse Charge, Art. 196 MwStSystRL).',
    'es': 'Inversión del sujeto pasivo (art. 196 de la Directiva 2006/112/CE).',
}
REVERSE_CHARGE_FR = 'Autoliquidation – art. 283-2 du CGI et art. 196 de la directive 2006/112/CE.'
EXPORT_EU = {
    'fr': 'TVA non applicable – prestation hors Union européenne (art. 44 de la directive 2006/112/CE).',
    'en': 'VAT not applicable – supply outside the EU (Article 44, Council Directive 2006/112/EC).',
    'de': 'Nicht im Inland steuerbare Leistung (Art. 44 MwStSystRL).',
    'es': 'Operación no sujeta a IVA – servicio fuera de la UE (art. 44 de la Directiva 2006/112/CE).',
}
EXPORT_FR = 'TVA non applicable, art. 259-1 du CGI.'
EXPORT_OTHER = {
    'GB': 'Outside the scope of UK VAT – services supplied to a customer outside the UK.',
    'AU': 'GST-free export (section 38-190, A New Tax System (Goods and Services Tax) Act 1999).',
    'NZ': 'Zero-rated supply – services supplied to a non-resident (section 11A, GST Act 1985).',
    'CA': 'Zero-rated export of services – no GST/HST charged.',
}


def _client_country(client, seller_code):
    """Pays du client : son pays saisi, sinon celui du vendeur ; '?' si saisi mais inconnu."""
    raw = (getattr(client, 'country', '') or '').strip()
    if not raw:
        return seller_code
    return country_code(raw) or '?'


def _is_business(client):
    return bool(client and (client.tax_id or client.company_name or client.registration_number))


def _situation(document):
    """('domestic' | 'eu_b2b' | 'eu_b2c' | 'export', pays du client) pour un vendeur assujetti."""
    seller = profile(document.organization)['country']
    client = document.client
    buyer = _client_country(client, seller) if client else seller
    if buyer == seller:
        return 'domestic', buyer
    if is_eu(seller) and is_eu(buyer):
        return ('eu_b2b' if client and client.tax_id else 'eu_b2c'), buyer
    return 'export', buyer


def invoice_mentions(document):
    """Mentions à ajouter sur ce document (autoliquidation, export), dans la langue des documents."""
    org = document.organization
    if org is None or getattr(document, 'client', None) is None:
        return []
    prof = profile(org)
    if not prof['tax_registered'] or Decimal(document.tax_amount or 0) != 0:
        return []
    lang, seller = prof['doc_language'], prof['country']
    situation, _buyer = _situation(document)
    if situation == 'eu_b2b':
        return [REVERSE_CHARGE_FR if seller == 'FR' and lang == 'fr' else REVERSE_CHARGE.get(lang, REVERSE_CHARGE['en'])]
    if situation == 'export' and _is_business(document.client):
        if is_eu(seller):
            return [EXPORT_FR if seller == 'FR' and lang == 'fr' else EXPORT_EU.get(lang, EXPORT_EU['en'])]
        if seller in EXPORT_OTHER:
            return [EXPORT_OTHER[seller]]
    return []


def invoice_checks(document):
    """Vérification avant envoi : [{'level': 'error' | 'warning' | 'ok' | 'info', 'message', 'tab'}]."""
    org = document.organization
    prof = profile(org)
    pack = pack_for(prof['country'])
    client = document.client
    checks = []

    def add(level, message, tab=''):
        checks.append({'level': level, 'message': message, 'tab': tab})

    if not pack['supported']:
        add('info', OTHER_NOTE, 'conformite')
        return checks

    missing = [i['label'] for i in checklist(org, prof) if not i['ok'] and i['level'] == 'required']
    if missing:
        add('error', f"Complétez vos informations : {', '.join(missing)}.", 'conformite')

    tax_amount = Decimal(document.tax_amount or 0)
    if not prof['tax_registered'] and tax_amount > 0:
        add('error', f"Vous avez indiqué ne pas facturer {pack['tax_ui']}, mais cette facture en contient : "
                     "passez les lignes à 0 % ou modifiez vos réponses dans Pays & conformité.", 'conformite')

    if client is None:
        add('error', 'Choisissez un client.')
        return checks
    if not (client.address or client.city):
        add('warning', "Adresse du client manquante : elle est obligatoire sur une facture entre professionnels.")

    if prof['tax_registered']:
        situation, buyer = _situation(document)
        buyer_name = PACKS[buyer]['name'] if buyer in PACKS else (client.country or 'un autre pays')
        if situation == 'eu_b2b':
            if tax_amount > 0:
                add('warning', f"Client professionnel ({buyer_name}) avec un numéro de TVA : en général pas de TVA "
                               "(autoliquidation). Passez les lignes à 0 % : Billio ajoute la mention obligatoire.")
            else:
                add('ok', "Autoliquidation : la mention obligatoire est ajoutée automatiquement.")
            if check_tax_id(buyer, client.tax_id):
                add('warning', f"Le numéro de TVA du client ne ressemble pas à un numéro de ce pays ({buyer_name}). "
                               "Vérifiez-le sur le site VIES de la Commission européenne.")
        elif situation == 'eu_b2c':
            add('info', f"Client dans un autre pays de l'UE ({buyer_name}) sans numéro de TVA : s'il est professionnel, "
                        "ajoutez son numéro (autoliquidation) ; s'il est particulier, votre TVA s'applique.")
        elif situation == 'export':
            if tax_amount > 0 and _is_business(client):
                add('info', f"Client à l'étranger ({buyer_name}) : une prestation de services à un professionnel "
                            f"étranger est en général sans {pack['tax_name']}. Passez les lignes à 0 % si c'est votre cas.")
            elif tax_amount == 0 and invoice_mentions(document):
                add('ok', "Client à l'étranger : la mention d'exonération est ajoutée automatiquement.")

        if pack['rates'] and situation == 'domestic':
            known = {Decimal(r).normalize() for r in pack['rates']} | {Decimal('0')}
            odd = sorted({Decimal(i.tax_rate).normalize() for i in document.items.all()} - known)
            if odd:
                add('warning', f"Taux inhabituel pour ce pays ({pack['name']}) : {', '.join(f'{r:f} %' for r in odd)} "
                               f"(taux connus : {', '.join(r + ' %' for r in pack['rates'])}).")

        total = Decimal(document.total_amount or 0)
        if prof['country'] == 'AU' and total >= 1000 and not (client.tax_id or client.address):
            add('warning', "Tax invoice de 1 000 A$ ou plus : indiquez l'ABN ou l'adresse du client.")
        if prof['country'] == 'NZ' and total > 1000 and not client.address:
            add('warning', "Au-delà de 1 000 NZ$ : l'adresse du client doit figurer sur la facture.")

    if all(c['level'] in ('ok', 'info') for c in checks):
        checks.insert(0, {'level': 'ok', 'message': f"Facture conforme aux règles courantes ({pack['name']}).", 'tab': ''})
    return checks
