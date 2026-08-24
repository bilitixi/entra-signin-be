"""Microsoft Graph calls used to *provision* Entra identities from the admin
UI — distinct from the per-user MSAL flow in views.py used for sign-in.

Requires the app registration to have the Graph **application** permission
`User.ReadWrite.All`, with admin consent granted (ENTRA_PORTAL_SETUP.md §A5b).
Without that, create_local_account() raises GraphError with a 403 detail.
"""
import secrets
import string

import msal
import requests
from django.conf import settings

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_PASSWORD_SYMBOLS = "!@#$%^&*-_="


class GraphError(Exception):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


def _confidential_client():
    return msal.ConfidentialClientApplication(
        settings.ENTRA_CLIENT_ID,
        authority=settings.ENTRA_AUTHORITY,
        client_credential=settings.ENTRA_CLIENT_SECRET,
    )


def _graph_token():
    """App-only token via client-credentials flow (no signed-in user)."""
    result = _confidential_client().acquire_token_for_client(
        scopes=["https://graph.microsoft.com/.default"]
    )
    if "access_token" not in result:
        raise GraphError(
            result.get("error_description", "failed to acquire Graph token")
        )
    return result["access_token"]


def generate_temp_password(length=16):
    """Meets Entra's default password complexity (upper+lower+digit+symbol)."""
    alphabet = string.ascii_letters + string.digits + _PASSWORD_SYMBOLS
    while True:
        pwd = "".join(secrets.choice(alphabet) for _ in range(length))
        if (
            any(c.islower() for c in pwd)
            and any(c.isupper() for c in pwd)
            and any(c.isdigit() for c in pwd)
            and any(c in _PASSWORD_SYMBOLS for c in pwd)
        ):
            return pwd


def create_local_account(email, display_name, password):
    """Creates a "local account" identity in an Entra External ID (CIAM)
    tenant — the kind that signs in with email + password, as opposed to a
    work/school account or a B2B guest. `forceChangePasswordNextSignIn`
    means the temp password only gets the person as far as a Microsoft
    "update your password" screen; they choose their real password there.

    Returns the new identity's Entra object id (the value that shows up as
    the `oid` claim on their ID token), so the caller can record it on the
    local User row immediately instead of waiting for first sign-in.
    """
    token = _graph_token()
    mail_nickname = email.split("@", 1)[0]
    body = {
        "accountEnabled": True,
        "displayName": display_name or mail_nickname,
        "mailNickname": mail_nickname,
        "identities": [
            {
                "signInType": "emailAddress",
                "issuer": settings.ENTRA_CIAM_DOMAIN,
                "issuerAssignedId": email,
            }
        ],
        "passwordProfile": {
            "forceChangePasswordNextSignIn": True,
            "password": password,
        },
        "passwordPolicies": "DisablePasswordExpiration",
    }
    resp = requests.post(
        f"{GRAPH_BASE}/users",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    if resp.status_code != 201:
        detail = None
        try:
            detail = resp.json().get("error", {}).get("message")
        except ValueError:
            pass
        raise GraphError(
            detail or f"Graph user creation failed ({resp.status_code})",
            status_code=resp.status_code,
        )
    return resp.json()["id"]
