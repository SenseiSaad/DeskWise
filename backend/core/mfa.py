"""TOTP two-factor authentication (RFC 6238) — standard library only.

Used to add a second step to platform-admin sign-ins, both on the API
(/api/auth/login returns an mfa_required challenge; /api/auth/mfa/verify
completes it) and on Django /admin/ (core.middleware gates the admin behind a
session check backed by these helpers).

The shared secret is stored on the user row via EncryptedCharField and never
leaves the server after enrollment. Challenge tokens are Django-signed blobs
with a 5-minute life — they only confirm "this person knows the PASSWORD";
they cannot complete a login by themselves.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

from django.core import signing

CHALLENGE_SALT = "openvault.mfa.challenge"
CHALLENGE_MAX_AGE = 300  # seconds to finish the second step


def generate_secret() -> str:
    """A 160-bit base32 secret as accepted by every authenticator app."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def provisioning_uri(secret: str, email: str, issuer: str = "Deskwise") -> str:
    """The otpauth:// URI QR codes and manual entry both consume."""
    label = quote(f"{issuer}:{email}")
    return (
        f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}"
        "&algorithm=SHA1&digits=6&period=30"
    )


def _code_at(secret: str, step: int) -> str:
    key = base64.b32decode(secret + "=" * ((8 - len(secret) % 8) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % 1_000_000
    return f"{value:06d}"


def matching_step(secret: str, code: str, window: int = 1) -> int | None:
    """The 30s time step `code` matches (current or ±window), else None."""
    clean = str(code or "").replace(" ", "").strip()
    if not secret or not clean.isdigit() or len(clean) != 6:
        return None
    current = int(time.time()) // 30
    found = None
    for step in range(current - window, current + window + 1):
        if hmac.compare_digest(_code_at(secret, step), clean):
            found = step
    return found


def verify_code(secret: str, code: str, window: int = 1) -> bool:
    """True when `code` matches the TOTP for the current or ±window 30s steps."""
    return matching_step(secret, code, window) is not None


# Replay protection (AUTHN-04) and per-challenge attempt caps (AUTHN-03) live
# in the shared cache, which production requires (settings guard).
MAX_CHALLENGE_ATTEMPTS = 5
_STEP_TTL = 30 * 4


def verify_user_code(user_pk: int, secret: str, code: str) -> bool:
    """verify_code plus replay protection: a step already used by this user
    (or any earlier step) is refused, and claiming a step is atomic."""
    from django.core.cache import cache

    step = matching_step(secret, code)
    if step is None:
        return False
    last = cache.get(f"mfa:last_step:{user_pk}")
    if last is not None and step <= int(last):
        return False
    if not cache.add(f"mfa:step:{user_pk}:{step}", 1, _STEP_TTL):
        return False
    cache.set(f"mfa:last_step:{user_pk}", step, _STEP_TTL)
    return True


def _challenge_key(token: str) -> str:
    return "mfa:chal:" + hashlib.sha256(str(token or "").encode()).hexdigest()


def challenge_burned(token: str) -> bool:
    from django.core.cache import cache
    return int(cache.get(_challenge_key(token)) or 0) >= MAX_CHALLENGE_ATTEMPTS


def record_challenge_failure(token: str) -> None:
    from django.core.cache import cache
    key = _challenge_key(token)
    cache.add(key, 0, CHALLENGE_MAX_AGE + 60)
    try:
        cache.incr(key)
    except ValueError:
        cache.set(key, 1, CHALLENGE_MAX_AGE + 60)


def burn_challenge(token: str) -> None:
    """A challenge completes one login only."""
    from django.core.cache import cache
    cache.set(_challenge_key(token), MAX_CHALLENGE_ATTEMPTS, CHALLENGE_MAX_AGE + 60)


def issue_challenge(user_pk: int, purpose: str, secret: str = "") -> str:
    """A short-lived signed blob tying a pending second step to one user.
    The nonce makes every challenge distinct, so attempt caps and one-time use
    (keyed on the challenge) never spill over to another login.

    The user's current `token_version` is bound in (`tv`): a password reset,
    logout-all, deactivation or promotion bumps it, which kills every pending
    challenge issued before that event (S7-01)."""
    from .models import User

    tv = User.objects.filter(pk=user_pk).values_list("token_version", flat=True).first()
    signer = signing.TimestampSigner(salt=CHALLENGE_SALT)
    return signer.sign_object({
        "u": user_pk, "p": purpose, "s": secret, "n": secrets.token_hex(8), "tv": tv,
    })


def challenge_is_current(payload: dict, user) -> bool:
    """False when the user's sessions were revoked after this challenge was
    issued (or the challenge predates version binding)."""
    tv = payload.get("tv")
    return tv is not None and int(tv) == int(getattr(user, "token_version", 1))


def read_challenge(token: str, purpose: str) -> dict | None:
    """The challenge payload when valid, unexpired and purpose-matching."""
    try:
        signer = signing.TimestampSigner(salt=CHALLENGE_SALT)
        payload = signer.unsign_object(token, max_age=CHALLENGE_MAX_AGE)
    except (signing.BadSignature, signing.SignatureExpired):
        return None
    if not isinstance(payload, dict) or payload.get("p") != purpose:
        return None
    return payload
