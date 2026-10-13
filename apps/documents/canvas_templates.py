"""
Modèles système du mode canvas : Bienvenue, Contrat, Proposition, Formulaire de
demande. Chaque modèle est une liste de pages A4 (794 × 1123 px CSS) composée
d'éléments positionnés ; `build_system_templates()` renvoie les données prêtes à
être normalisées par canvas_render.clean_canvas_data. Utilisé par la migration
documents.0006 (et réutilisable pour réinitialiser les modèles).
"""
import math
import re

PAGE_W, PAGE_H = 794, 1123
M = 64  # marge
CONTENT_W = PAGE_W - 2 * M

INK = '#111827'
MUTED = '#6b7280'
LINE = '#e5e7eb'
FONT = 'Inter, sans-serif'
SERIF = 'Newsreader, serif'


def var(key):
    from .models import DOCUMENT_VARIABLE_LABELS
    label = DOCUMENT_VARIABLE_LABELS.get(key, key)
    return f'<span class="doc-var-token" data-var="{key}" contenteditable="false">{label}</span>'


def _estimate_height(html, w, size, line_height, padding=0):
    """Hauteur approximative d'un texte (l'éditeur la réajuste à l'ouverture)."""
    text = re.sub(r'<span class="doc-var-token"[^>]*>.*?</span>', 'XXXXXXXXXXXX', html)
    parts = re.split(r'<br\s*/?>|</p>|</li>|</h\d>|</div>', text)
    chars_per_line = max(8, (w - 2 * padding) / (size * 0.5))
    lines = sum(max(1, math.ceil(len(re.sub(r'<[^>]+>', '', p).strip()) / chars_per_line)) for p in parts if p.strip()) or 1
    return math.ceil(lines * size * line_height + 2 * padding + 4)


def text(x, y, w, html, *, size=13, weight=400, color=INK, h=None, line_height=1.55, name='', **style):
    padding = style.get('padding', 0)
    return {
        'type': 'text', 'name': name, 'x': x, 'y': y, 'w': w,
        'h': h or _estimate_height(html, w, size, line_height, padding),
        'html': html,
        'style': dict({'fontFamily': FONT, 'fontSize': size, 'fontWeight': weight, 'color': color, 'lineHeight': line_height}, **style),
    }


def rect(x, y, w, h, fill, *, name='', **style):
    return {'type': 'shape', 'shape': 'rect', 'name': name, 'x': x, 'y': y, 'w': w, 'h': h, 'style': dict({'fill': fill}, **style)}


def ellipse(x, y, w, h, fill, **style):
    return {'type': 'shape', 'shape': 'ellipse', 'x': x, 'y': y, 'w': w, 'h': h, 'style': dict({'fill': fill}, **style)}


def hline(x, y, w, color=LINE, width=1):
    return {'type': 'shape', 'shape': 'line', 'x': x, 'y': y - 8, 'w': w, 'h': 16, 'style': {'strokeColor': color, 'strokeWidth': width, 'fill': 'transparent'}}


def table(x, y, w, rows, widths, *, header_bg=INK, stripe='#f9fafb', size=12, **style):
    return {
        'type': 'table', 'x': x, 'y': y, 'w': w, 'h': 36 * len(rows), 'header': True, 'rows': rows, 'colWidths': widths,
        'style': dict({
            'fontFamily': FONT, 'fontSize': size, 'color': INK, 'headerBg': header_bg, 'headerColor': '#ffffff',
            'cellBorderColor': LINE, 'stripe': stripe, 'cellPadding': 9,
        }, **style),
    }


def footer(page_label, accent):
    return [
        hline(M, PAGE_H - 56, CONTENT_W),
        text(M, PAGE_H - 46, 400, f'{var("organization.name")} · {var("document.number")}', size=9.5, color=MUTED, h=18),
        text(PAGE_W - M - 120, PAGE_H - 46, 120, page_label, size=9.5, color=MUTED, align='right', h=18),
    ]


def page(elements, background='#ffffff'):
    return {'background': background, 'elements': elements}


# --------------------------------------------------------------------------- #
# Bienvenue
# --------------------------------------------------------------------------- #

def welcome():
    accent = '#6d28d9'
    soft = '#f5f3ff'
    steps = [
        ('01', 'Lancement', "Atelier de cadrage pour comprendre vos objectifs, vos contraintes et définir ensemble le périmètre."),
        ('02', 'Production', "Nous avançons par étapes courtes et vous partageons régulièrement l'avancement dans votre portail."),
        ('03', 'Livraison', "Recette, ajustements finaux, remise des livrables et accompagnement à la prise en main."),
    ]
    card_w = (CONTENT_W - 2 * 20) / 3
    cards = []
    for i, (num, title, body) in enumerate(steps):
        x = M + i * (card_w + 20)
        cards += [
            rect(x, 640, card_w, 230, soft, radius=14),
            text(x + 22, 662, 60, num, size=28, weight=700, color=accent, h=40),
            text(x + 22, 712, card_w - 44, title, size=16, weight=700, h=24),
            text(x + 22, 744, card_w - 44, body, size=12, color='#4b5563', line_height=1.55),
        ]
    p1 = page([
        rect(0, 0, PAGE_W, 470, accent, name='Bandeau'),
        ellipse(520, -140, 420, 420, '#8b5cf6', opacity=0.45),
        ellipse(610, 250, 260, 260, '#a78bfa', opacity=0.3),
        text(M, 84, 300, 'Bienvenue', size=12, weight=600, color='#ddd6fe', uppercase=True, letterSpacing=2, h=20),
        text(M, 130, 560, f'Bienvenue {var("client.name")}', size=46, weight=700, color='#ffffff', line_height=1.1, h=110, name='Titre'),
        text(M, 262, 520, 'Nous sommes ravis de démarrer cette collaboration avec vous. Ce document rassemble tout ce qu\'il faut savoir pour bien commencer.', size=16, color='#ede9fe', line_height=1.55),
        text(M, 392, 400, f'{var("organization.name")} · {var("document.date")}', size=12, color='#ddd6fe', h=20),
        text(M, 540, CONTENT_W, 'Comment nous allons travailler ensemble', size=22, weight=700, h=34),
        text(M, 584, CONTENT_W, 'Trois étapes simples, avec un point de contact unique tout au long du projet.', size=13, color=MUTED, h=22),
        *cards,
        *footer('1 / 2', accent),
    ])
    p2 = page([
        rect(0, 0, PAGE_W, 10, accent),
        text(M, 72, CONTENT_W, 'Votre interlocuteur', size=24, weight=700, h=36),
        rect(M, 126, CONTENT_W, 120, soft, radius=14),
        ellipse(M + 24, 156, 60, 60, accent),
        text(M + 24, 172, 60, '✦', size=22, color='#ffffff', align='center', h=30),
        text(M + 104, 150, 420, f'<strong>{var("organization.name")}</strong><br>{var("organization.email")}', size=14, line_height=1.7),
        text(M + 104, 204, 480, 'Réponse sous 24 h ouvrées. Pour toute urgence, précisez « Urgent » dans l\'objet.', size=12, color=MUTED, h=20),
        text(M, 290, CONTENT_W, 'Prochaines étapes', size=20, weight=700, h=30),
        table(M, 334, CONTENT_W, [
            ['Étape', 'Date prévue', 'Responsable'],
            ['Atelier de lancement', 'À définir', var('organization.name')],
            ['Validation du planning', 'À définir', var('client.name')],
            ['Premier point d\'avancement', 'À définir', var('organization.name')],
        ], [46, 24, 30], header_bg=accent, stripe=soft),
        text(M, 520, CONTENT_W, 'Nos engagements', size=20, weight=700, h=30),
        text(M, 562, CONTENT_W,
             '<ul><li>Un point d\'avancement à chaque étape clé</li><li>Des livrables validés avec vous avant toute mise en production</li>'
             '<li>La transparence sur le temps passé et le budget</li><li>Un accès permanent à vos documents dans votre portail client</li></ul>',
             size=13.5, line_height=1.8),
        rect(M, 760, CONTENT_W, 120, '#faf9ff', radius=14, strokeWidth=1, strokeColor='#ddd6fe'),
        text(M + 28, 784, CONTENT_W - 56, f'<strong>Une question ?</strong><br>Écrivez-nous à {var("organization.email")} : nous vous répondons rapidement.', size=13.5, color='#4c1d95', line_height=1.6),
        *footer('2 / 2', accent),
    ])
    return [p1, p2]


# --------------------------------------------------------------------------- #
# Contrat
# --------------------------------------------------------------------------- #

def contract():
    accent = '#1e3a8a'
    col_w = (CONTENT_W - 24) / 2

    def article(y, num, title, body):
        return [
            text(M, y, CONTENT_W, f'Article {num} — {title}', size=14, weight=700, color=accent, h=22),
            text(M, y + 28, CONTENT_W, body, size=12.5, color='#374151', line_height=1.6),
        ]

    p1 = page([
        rect(0, 0, PAGE_W, 8, accent),
        text(M, 64, CONTENT_W, 'Contrat de prestation de services', size=30, weight=700, h=44, name='Titre'),
        text(M, 114, CONTENT_W, f'N° {var("document.number")} · établi le {var("document.date")}', size=12.5, color=MUTED, h=20),
        hline(M, 154, CONTENT_W),
        text(M, 176, CONTENT_W, 'Entre les soussignés', size=11, weight=600, color=MUTED, uppercase=True, letterSpacing=1, h=18),
        rect(M, 206, col_w, 132, '#f8fafc', radius=10, strokeWidth=1, strokeColor=LINE),
        text(M + 20, 222, col_w - 40, f'<strong>Le Prestataire</strong><br>{var("organization.name")}<br>{var("organization.email")}', size=12.5, line_height=1.7),
        rect(M + col_w + 24, 206, col_w, 132, '#f8fafc', radius=10, strokeWidth=1, strokeColor=LINE),
        text(M + col_w + 44, 222, col_w - 40, f'<strong>Le Client</strong><br>{var("client.name")}<br>{var("client.address")}<br>{var("client.email")}', size=12.5, line_height=1.7),
        text(M, 360, CONTENT_W, 'Il a été convenu ce qui suit.', size=12.5, color=MUTED, h=20),
        *article(404, 1, 'Objet', 'Le présent contrat a pour objet de définir les conditions dans lesquelles le Prestataire réalise pour le Client la mission décrite ci-après : [décrivez la mission, les livrables attendus et leur format].'),
        *article(510, 2, 'Durée', 'Le contrat prend effet à la date de sa signature par les deux parties et se termine à la livraison complète des prestations, prévue au plus tard le [date].'),
        *article(600, 3, 'Obligations du Prestataire', 'Le Prestataire s\'engage à exécuter la mission avec soin et selon les règles de l\'art, à informer régulièrement le Client de l\'avancement et à l\'alerter sans délai de toute difficulté susceptible d\'affecter le planning ou le budget.'),
        *article(726, 4, 'Obligations du Client', 'Le Client s\'engage à fournir au Prestataire l\'ensemble des informations et contenus nécessaires à la mission, à désigner un interlocuteur disponible et à valider les livrables dans un délai de dix jours ouvrés.'),
        *footer('Page 1 / 2', accent),
    ])
    p2 = page([
        rect(0, 0, PAGE_W, 8, accent),
        *article(64, 5, 'Conditions financières', 'En contrepartie de la mission, le Client versera au Prestataire la rémunération détaillée ci-dessous. Les factures sont payables à 30 jours ; tout retard entraîne l\'application des pénalités légales.'),
        table(M, 170, CONTENT_W, [
            ['Prestation', 'Échéance', 'Montant HT'],
            ['Acompte à la signature (30 %)', 'Signature', '0,00 €'],
            ['Livraison intermédiaire (40 %)', 'À définir', '0,00 €'],
            ['Solde à la livraison (30 %)', 'Livraison', '0,00 €'],
        ], [50, 25, 25], header_bg=accent, stripe='#f8fafc'),
        *article(340, 6, 'Propriété intellectuelle', 'Les droits d\'exploitation sur les livrables sont cédés au Client à compter du paiement intégral du prix, pour le monde entier et pour la durée légale des droits.'),
        *article(436, 7, 'Confidentialité', 'Chaque partie s\'engage à garder confidentielles les informations de l\'autre partie dont elle aurait connaissance à l\'occasion du contrat, pendant toute sa durée et deux ans après son terme.'),
        *article(532, 8, 'Résiliation', 'En cas de manquement grave de l\'une des parties, l\'autre pourra résilier le contrat quinze jours après une mise en demeure restée sans effet. Les prestations réalisées restent dues.'),
        text(M, 650, CONTENT_W, f'Fait en deux exemplaires, le {var("document.date")}.', size=12.5, color='#374151', h=20),
        rect(M, 700, col_w, 170, '#ffffff', radius=10, strokeWidth=1, strokeColor='#cbd5e1', strokeStyle='dashed'),
        text(M + 20, 716, col_w - 40, '<strong>Pour le Prestataire</strong><br>Nom, qualité :<br><br>Signature :', size=12.5, line_height=1.7),
        rect(M + col_w + 24, 700, col_w, 170, '#ffffff', radius=10, strokeWidth=1, strokeColor='#cbd5e1', strokeStyle='dashed'),
        text(M + col_w + 44, 716, col_w - 40, '<strong>Pour le Client</strong><br>« Bon pour accord »<br>Nom, qualité :<br><br>Signature :', size=12.5, line_height=1.7),
        *footer('Page 2 / 2', accent),
    ])
    return [p1, p2]


# --------------------------------------------------------------------------- #
# Proposition commerciale
# --------------------------------------------------------------------------- #

def proposal():
    accent = '#7c3aed'
    dark = '#0f172a'
    cover = page([
        ellipse(430, 640, 560, 560, accent, opacity=0.55),
        ellipse(560, 820, 380, 380, '#a78bfa', opacity=0.35),
        rect(M, 96, 56, 4, accent),
        text(M, 120, 500, 'Proposition commerciale', size=12, weight=600, color='#c4b5fd', uppercase=True, letterSpacing=2, h=20),
        text(M, 170, 560, f'Proposition pour {var("client.name")}', size=50, weight=700, color='#ffffff', line_height=1.08, h=170, name='Titre'),
        text(M, 360, 480, 'Une réponse sur mesure à vos enjeux : contexte, démarche, planning et investissement.', size=17, color='#cbd5e1', line_height=1.55),
        text(M, PAGE_H - 140, 420, f'Préparée par <strong>{var("organization.name")}</strong><br>{var("document.date")} · {var("document.number")}', size=12.5, color='#94a3b8', line_height=1.7),
    ], background=dark)

    col_w = (CONTENT_W - 32) / 2
    step_w = (CONTENT_W - 2 * 18) / 3
    steps = [
        ('Découvrir', 'Entretiens, analyse de l\'existant et des besoins, cadrage des priorités.'),
        ('Concevoir', 'Propositions, maquettes et itérations rapides validées avec vous.'),
        ('Livrer', 'Réalisation, recette, mise en ligne et transfert de compétences.'),
    ]
    step_cards = []
    for i, (title, body) in enumerate(steps):
        x = M + i * (step_w + 18)
        step_cards += [
            rect(x, 610, step_w, 200, '#ffffff', radius=14, strokeWidth=1, strokeColor=LINE, shadow='sm'),
            ellipse(x + 22, 632, 34, 34, '#ede9fe'),
            text(x + 22, 639, 34, str(i + 1), size=14, weight=700, color=accent, align='center', h=20),
            text(x + 22, 684, step_w - 44, title, size=16, weight=700, h=24),
            text(x + 22, 716, step_w - 44, body, size=12, color='#4b5563', line_height=1.55),
        ]
    p2 = page([
        text(M, 72, 300, '01', size=12, weight=700, color=accent, letterSpacing=1, h=18),
        text(M, 96, CONTENT_W, 'Contexte & objectifs', size=28, weight=700, h=40),
        text(M, 160, col_w, '<strong>Le contexte</strong><br>Décrivez en quelques lignes la situation du client, ce qui motive le projet et les contraintes identifiées (délais, budget, équipe, outils existants).', size=13, color='#374151', line_height=1.65),
        text(M + col_w + 32, 160, col_w, '<strong>Vos objectifs</strong><ul><li>Objectif principal mesurable</li><li>Bénéfice attendu pour vos clients</li><li>Indicateur de réussite</li></ul>', size=13, color='#374151', line_height=1.65),
        hline(M, 380, CONTENT_W),
        text(M, 424, 300, '02', size=12, weight=700, color=accent, letterSpacing=1, h=18),
        text(M, 448, CONTENT_W, 'Notre approche', size=28, weight=700, h=40),
        text(M, 506, CONTENT_W, 'Une démarche en trois temps, avec un point de validation à la fin de chaque étape.', size=13, color=MUTED, h=22),
        *step_cards,
        *footer('2 / 3', accent),
    ])
    p3 = page([
        text(M, 72, 300, '03', size=12, weight=700, color=accent, letterSpacing=1, h=18),
        text(M, 96, CONTENT_W, 'Investissement', size=28, weight=700, h=40),
        table(M, 160, CONTENT_W, [
            ['Désignation', 'Qté', 'Prix unitaire', 'Total HT'],
            ['Atelier de cadrage', '1', '0,00 €', '0,00 €'],
            ['Conception', '1', '0,00 €', '0,00 €'],
            ['Réalisation', '1', '0,00 €', '0,00 €'],
            ['', '', '<strong>Total HT</strong>', '<strong>0,00 €</strong>'],
        ], [46, 12, 21, 21], header_bg=dark, stripe='#f8fafc'),
        text(M, 380, CONTENT_W, 'Conditions', size=16, weight=700, h=24),
        text(M, 412, CONTENT_W, '<ul><li>Proposition valable 30 jours à compter de sa date d\'émission</li><li>Acompte de 30 % à la commande, solde à la livraison</li><li>Planning confirmé à la réception de l\'acompte</li></ul>', size=13, color='#374151', line_height=1.75),
        rect(M, 560, CONTENT_W, 110, '#f5f3ff', radius=14),
        text(M + 28, 582, CONTENT_W - 56, '<strong>Prochaine étape</strong><br>Retournez-nous ce document signé : nous planifions l\'atelier de lancement dans la semaine.', size=13.5, color='#4c1d95', line_height=1.6),
        rect(M + CONTENT_W - 300, 720, 300, 160, '#ffffff', radius=12, strokeWidth=1, strokeColor='#cbd5e1', strokeStyle='dashed'),
        text(M + CONTENT_W - 280, 738, 260, f'<strong>Bon pour accord</strong><br>{var("client.name")}<br>Date :<br><br>Signature :', size=12.5, line_height=1.7),
        *footer('3 / 3', accent),
    ])
    return [cover, p2, p3]


# --------------------------------------------------------------------------- #
# Formulaire de demande
# --------------------------------------------------------------------------- #

def inquiry_form():
    """Vrais champs de formulaire : le client les remplit et les envoie depuis son portail."""
    accent = '#0e7490'
    col_w = (CONTENT_W - 24) / 2

    def section_title(y, num, title):
        return [
            ellipse(M, y, 26, 26, accent),
            text(M, y + 4, 26, str(num), size=12, weight=700, color='#ffffff', align='center', h=18),
            text(M + 38, y + 1, CONTENT_W - 38, title, size=17, weight=700, h=26),
        ]

    def ask(x, y, w, label, field_type='text', *, h=64, options=None, required=False, placeholder='', show_label=True):
        return {
            'type': 'field', 'fieldType': field_type, 'label': label, 'placeholder': placeholder,
            'required': required, 'showLabel': show_label, 'options': options or [],
            'x': x, 'y': y, 'w': w, 'h': h,
            'style': {'fontFamily': FONT, 'fontSize': 13, 'color': INK, 'labelColor': '#374151',
                      'fieldBorder': '#d1d5db', 'fieldRadius': 6, 'accent': accent},
        }

    p1 = page([
        rect(0, 0, PAGE_W, 190, '#ecfeff'),
        rect(0, 186, PAGE_W, 4, accent),
        text(M, 58, CONTENT_W, 'Formulaire de demande', size=32, weight=700, color='#164e63', h=44, name='Titre'),
        text(M, 110, 560, f'Merci de compléter ce formulaire : {var("organization.name")} reviendra vers vous sous 48 h avec une proposition adaptée.', size=13.5, color='#155e75', line_height=1.55),
        *section_title(226, 1, 'Vos coordonnées'),
        ask(M, 270, col_w, 'Nom et prénom', required=True),
        ask(M + col_w + 24, 270, col_w, 'Société'),
        ask(M, 348, col_w, 'Email', 'email', required=True, placeholder='nom@entreprise.fr'),
        ask(M + col_w + 24, 348, col_w, 'Téléphone', 'phone'),
        *section_title(446, 2, 'Votre projet'),
        ask(M, 490, col_w, 'Type de projet', 'checkbox', h=172,
            options=['Site web', 'Identité visuelle', 'Application', 'Conseil', 'Contenus', 'Autre']),
        ask(M + col_w + 24, 490, col_w, 'Budget envisagé', 'radio', h=124,
            options=['< 2 000 €', '2 000 – 5 000 €', '5 000 – 10 000 €', '> 10 000 €']),
        ask(M, 680, CONTENT_W, 'Décrivez votre besoin', 'textarea', h=180, required=True,
            placeholder='Objectifs, public visé, livrables attendus…'),
        ask(M, 880, col_w, 'Date de démarrage souhaitée', 'date'),
        ask(M + col_w + 24, 880, col_w, 'Date limite éventuelle', 'date'),
        *footer('1 / 2', accent),
    ])
    p2 = page([
        rect(0, 0, PAGE_W, 8, accent),
        *section_title(64, 3, 'Informations complémentaires'),
        ask(M, 108, CONTENT_W, 'Exemples, références, contraintes techniques…', 'textarea', h=200),
        ask(M, 330, col_w, 'Comment nous avez-vous connus ?', 'radio', h=124,
            options=['Recommandation', 'Recherche web', 'Réseaux sociaux', 'Autre']),
        *section_title(486, 4, 'Validation'),
        rect(M, 528, CONTENT_W, 64, '#f8fafc', radius=10),
        ask(M + 16, 540, CONTENT_W - 32, 'Consentement', 'checkbox', h=44, required=True, show_label=False,
            options=["J'accepte que ces informations soient utilisées pour me recontacter au sujet de ma demande."]),
        ask(M, 612, col_w, 'Fait le', 'date'),
        ask(M + col_w + 24, 612, col_w, 'Nom du signataire', required=True),
        {'type': 'button', 'text': 'Envoyer le formulaire', 'x': M, 'y': 708, 'w': 240, 'h': 46,
         'style': {'background': accent, 'color': '#ffffff', 'fontFamily': FONT, 'fontSize': 14, 'fontWeight': 600,
                   'radius': 10, 'align': 'center', 'valign': 'middle'}},
        rect(M, 790, CONTENT_W, 84, '#ecfeff', radius=12),
        text(M + 24, 808, CONTENT_W - 48, f'<strong>Et ensuite ?</strong><br>Vos réponses arrivent directement chez {var("organization.name")}. Vous pouvez les modifier tant que la demande n\'est pas traitée.', size=13, color='#155e75', line_height=1.6),
        *footer('2 / 2', accent),
    ])
    return [p1, p2]


SYSTEM_TEMPLATES = [
    # (nom existant à remplacer ou None, nouveau nom, catégorie, description, constructeur)
    ('Document de bienvenue', 'Document de bienvenue', 'welcome', "Kit d'accueil client en 2 pages : étapes, interlocuteur, engagements.", welcome),
    ('Contrat', 'Contrat de prestation', 'contract', 'Contrat de prestation en 2 pages : parties, 8 articles, échéancier, signatures.', contract),
    ('Proposition commerciale', 'Proposition commerciale', 'proposal', 'Proposition en 3 pages : couverture, contexte & approche, investissement.', proposal),
    (None, 'Formulaire de demande', 'inquiry', 'Formulaire de demande que le client remplit en ligne (2 pages) : coordonnées, projet, budget.', inquiry_form),
]


def build_system_templates():
    return [
        {'replaces': old, 'name': name, 'category': category, 'description': description, 'pages': builder()}
        for old, name, category, description, builder in SYSTEM_TEMPLATES
    ]
