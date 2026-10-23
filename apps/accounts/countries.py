"""Pays proposés à l'inscription : (code ISO, nom, indicatif téléphonique)."""
import re

COUNTRIES = [
    ('FR', 'France', '33'), ('BE', 'Belgique', '32'), ('CH', 'Suisse', '41'), ('LU', 'Luxembourg', '352'),
    ('MC', 'Monaco', '377'), ('CA', 'Canada', '1'), ('MA', 'Maroc', '212'), ('DZ', 'Algérie', '213'),
    ('TN', 'Tunisie', '216'), ('SN', 'Sénégal', '221'), ('CI', "Côte d'Ivoire", '225'), ('CM', 'Cameroun', '237'),
    ('MG', 'Madagascar', '261'), ('MU', 'Maurice', '230'), ('DE', 'Allemagne', '49'), ('ES', 'Espagne', '34'),
    ('IT', 'Italie', '39'), ('PT', 'Portugal', '351'), ('NL', 'Pays-Bas', '31'), ('IE', 'Irlande', '353'),
    ('GB', 'Royaume-Uni', '44'), ('US', 'États-Unis', '1'), ('AU', 'Australie', '61'), ('NZ', 'Nouvelle-Zélande', '64'),
    ('AT', 'Autriche', '43'), ('BG', 'Bulgarie', '359'), ('HR', 'Croatie', '385'), ('CY', 'Chypre', '357'),
    ('CZ', 'Tchéquie', '420'), ('DK', 'Danemark', '45'), ('EE', 'Estonie', '372'), ('FI', 'Finlande', '358'),
    ('GR', 'Grèce', '30'), ('HU', 'Hongrie', '36'), ('LV', 'Lettonie', '371'), ('LT', 'Lituanie', '370'),
    ('MT', 'Malte', '356'), ('PL', 'Pologne', '48'), ('RO', 'Roumanie', '40'), ('SK', 'Slovaquie', '421'),
    ('SI', 'Slovénie', '386'), ('SE', 'Suède', '46'),
]
BY_CODE = {code: (name, dial) for code, name, dial in COUNTRIES}


def normalize_phone(raw, country_code):
    """Numéro au format international « +33 612345678 » ; None s'il n'est pas plausible.

    Un numéro saisi avec son indicatif (+…, 00…) est gardé tel quel ; sinon l'indicatif du pays est ajouté
    et le 0 national retiré (06 12 34 56 78 → +33 612345678).
    """
    raw = (raw or '').strip()
    digits = re.sub(r'\D', '', raw)
    if raw.startswith('+') or digits.startswith('00'):
        digits = digits[2:] if digits.startswith('00') else digits
        for dial in sorted({d for _, _, d in COUNTRIES}, key=len, reverse=True):
            if digits.startswith(dial):
                national = digits[len(dial):]
                break
        else:
            dial, national = digits[:3], digits[3:]
    else:
        dial, national = BY_CODE.get(country_code, ('', ''))[1], digits.lstrip('0')
    if not dial or not 6 <= len(national) <= 13:
        return None
    return f'+{dial} {national}'
