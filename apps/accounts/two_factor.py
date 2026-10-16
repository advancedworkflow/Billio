"""
Double authentification (TOTP, RFC 6238) : code à 6 chiffres d'une application d'authentification
(Google Authenticator, Microsoft Authenticator, 1Password, Authy…) demandé après le mot de passe.

- le secret est généré à l'activation et confirmé par un premier code avant d'être enregistré ;
- un code déjà utilisé n'est plus accepté (User.totp_last_step), tolérance de ±30 secondes ;
- 10 codes de secours à usage unique, conservés hachés, pour le cas où le téléphone est perdu.
"""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

ISSUER = 'Billio'
STEP = 30
DIGITS = 6
RECOVERY_CODES = 10
PENDING_TTL = 5 * 60  # secondes entre le mot de passe et le code
SESSION_PENDING = '2fa_pending'
SESSION_SETUP = '2fa_setup_secret'
SESSION_NEW_CODES = '2fa_new_codes'


def generate_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode()


def _code(secret, step):
    key = base64.b32decode(secret.upper() + '=' * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack('>Q', step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10 ** DIGITS).zfill(DIGITS)


def _clean(code):
    return ''.join(ch for ch in (code or '') if ch.isalnum()).lower()


def matching_step(secret, code, after=0, now=None):
    """Pas de temps correspondant au code (fenêtre ±1), ou None. Les pas <= after sont refusés (rejeu)."""
    code = _clean(code)
    if not secret or len(code) != DIGITS or not code.isdigit():
        return None
    current = int((now or time.time()) // STEP)
    for step in (current, current - 1, current + 1):
        if step > after and hmac.compare_digest(_code(secret, step), code):
            return step
    return None


def provisioning_uri(user, secret):
    label = quote(f'{ISSUER}:{user.email}')
    return f'otpauth://totp/{label}?secret={secret}&issuer={ISSUER}&digits={DIGITS}&period={STEP}'


def qr_svg(uri):
    import segno
    return segno.make(uri, error='m', micro=False).svg_inline(scale=5, border=2, dark='#18181b')


def _hash(code):
    return hashlib.sha256(_clean(code).encode()).hexdigest()


def new_recovery_codes(user):
    """Remplace les codes de secours ; renvoie les codes en clair (affichés une seule fois)."""
    alphabet = 'abcdefghjkmnpqrstuvwxyz23456789'
    codes = ['-'.join(''.join(secrets.choice(alphabet) for _ in range(4)) for _ in range(2))
             for _ in range(RECOVERY_CODES)]
    user.totp_recovery_codes = [_hash(code) for code in codes]
    return codes


def enable(user, secret, step):
    from django.utils import timezone
    user.totp_secret, user.totp_last_step, user.totp_enabled_at = secret, step, timezone.now()
    codes = new_recovery_codes(user)
    user.save(update_fields=['totp_secret', 'totp_last_step', 'totp_enabled_at', 'totp_recovery_codes'])
    return codes


def disable(user):
    user.totp_secret, user.totp_last_step, user.totp_enabled_at, user.totp_recovery_codes = '', 0, None, []
    user.save(update_fields=['totp_secret', 'totp_last_step', 'totp_enabled_at', 'totp_recovery_codes'])


def check(user, code):
    """Vérifie un code de l'application ou un code de secours (consommé). Renvoie 'totp', 'recovery' ou None."""
    if not user.totp_enabled_at:
        return None
    step = matching_step(user.totp_secret, code, after=user.totp_last_step)
    if step is not None:
        user.totp_last_step = step
        user.save(update_fields=['totp_last_step'])
        return 'totp'
    hashed = _hash(code)
    if len(_clean(code)) == 8 and hashed in (user.totp_recovery_codes or []):
        user.totp_recovery_codes = [h for h in user.totp_recovery_codes if h != hashed]
        user.save(update_fields=['totp_recovery_codes'])
        return 'recovery'
    return None
