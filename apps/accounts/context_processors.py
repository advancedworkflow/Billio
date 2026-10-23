"""Bandeau « confirmez votre adresse email » affiché dans toute l'application."""


def email_verification(request):
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return {}
    from .email_verification import needs_verification
    return {'email_unverified': True} if needs_verification(user) else {}
