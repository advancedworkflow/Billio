from .catalog import LANGUAGES
from .middleware import request_language

# Une phrase dans chaque langue, écrite dans cette langue (sélecteur des Paramètres).
LANGUAGE_SAMPLES = {
    'fr': 'Interface en français',
    'en': 'Interface in English',
    'de': 'Oberfläche auf Deutsch',
    'es': 'Interfaz en español',
}


def languages(request):
    """Langue courante et langues proposées (sélecteurs de langue)."""
    return {
        'current_language': request_language(request),
        'available_languages': LANGUAGES,
        'language_options': [(code, label, LANGUAGE_SAMPLES.get(code, '')) for code, label in LANGUAGES],
    }
