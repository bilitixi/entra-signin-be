"""Validates the bearer token Microsoft Entra attaches to its own calls
into this backend for a custom authentication extension event (e.g.
OnAttributeCollectionSubmit) — a different mechanism from the API
connector's HTTP Basic auth used in the older Azure AD B2C / workforce
tenant "External Identities" experience. See ENTRA_API_CONNECTOR_SETUP.md.
"""
import jwt
from django.conf import settings
from jwt import PyJWKClient

# Well-known first-party service principal Entra uses to call custom
# authentication extensions, the same across every tenant — this is what
# distinguishes "Entra itself called this" from anyone else holding a
# validly-signed token for the target audience.
MS_CUSTOM_EXTENSION_CALLER_APPID = "99045fe1-7639-4a75-9d4a-577b6ca3810f"

_jwks_client = None


class TokenInvalid(Exception):
    pass


def _get_jwks_client():
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = PyJWKClient(f"{settings.ENTRA_AUTHORITY}/discovery/v2.0/keys")
    return _jwks_client


def validate_custom_extension_token(auth_header):
    """Raises TokenInvalid unless auth_header is a valid Bearer token that
    Entra issued specifically for calling this extension: signed by the
    tenant, audience-scoped to ENTRA_CUSTOM_EXTENSION_APP_ID, and actually
    sent by Entra's own service principal (not just anyone who got hold of
    a token for that audience some other way)."""
    if not auth_header.startswith("Bearer "):
        raise TokenInvalid("missing bearer token")
    token = auth_header[len("Bearer ") :]

    if not settings.ENTRA_CUSTOM_EXTENSION_APP_ID:
        raise TokenInvalid("ENTRA_CUSTOM_EXTENSION_APP_ID not configured")

    expected_issuer = f"{settings.ENTRA_AUTHORITY}/v2.0"
    try:
        signing_key = _get_jwks_client().get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            audience=settings.ENTRA_CUSTOM_EXTENSION_APP_ID,
            issuer=expected_issuer,
        )
    except jwt.PyJWTError as exc:
        # Decode without verifying (purely for logging what actually
        # mismatched — never trust these claims for authorization) so the
        # log line shows both sides instead of just "invalid".
        try:
            unverified = jwt.decode(token, options={"verify_signature": False})
        except jwt.PyJWTError:
            unverified = {}
        raise TokenInvalid(
            f"token validation failed: {exc} | expected iss={expected_issuer!r} "
            f"aud={settings.ENTRA_CUSTOM_EXTENSION_APP_ID!r} | "
            f"got iss={unverified.get('iss')!r} aud={unverified.get('aud')!r}"
        ) from exc

    caller = claims.get("azp") or claims.get("appid")
    if caller != MS_CUSTOM_EXTENSION_CALLER_APPID:
        raise TokenInvalid("token was not issued to Entra's extension caller")

    return claims
