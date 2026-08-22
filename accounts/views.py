import json
import secrets

import msal
from django.conf import settings
from django.contrib.auth import login as django_login, logout as django_logout
from django.core.cache import cache
from django.http import (
    HttpResponseBadRequest,
    HttpResponseForbidden,
    HttpResponseNotAllowed,
    JsonResponse,
)
from django.shortcuts import redirect
from django.views.decorators.csrf import csrf_exempt
from urllib.parse import urlencode

from . import emails, graph
from .models import Role, User


def _msal_app():
    return msal.ConfidentialClientApplication(
        settings.ENTRA_CLIENT_ID,
        authority=settings.ENTRA_AUTHORITY,
        client_credential=settings.ENTRA_CLIENT_SECRET,
    )


def login(request):
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    cache.set(f"oidc_state:{state}", nonce, timeout=600)

    auth_url = _msal_app().get_authorization_request_url(
        scopes=settings.ENTRA_SCOPES,
        state=state,
        nonce=nonce,
        redirect_uri=settings.ENTRA_REDIRECT_URI,
    )
    return redirect(auth_url)


def _redirect_with_error(code):
    """Sends the browser back to the SPA with an error code in the query
    string, instead of showing Django's own 403/400 page — the frontend
    reads `auth_error` and renders a real error screen (see
    src/pages/Home.jsx)."""
    sep = "&" if "?" in settings.FRONTEND_POST_LOGIN_URL else "?"
    return redirect(f"{settings.FRONTEND_POST_LOGIN_URL}{sep}auth_error={code}")


def callback(request):
    state = request.GET.get("state")
    nonce = cache.get(f"oidc_state:{state}")
    if not state or nonce is None:
        return _redirect_with_error("invalid_state")
    cache.delete(f"oidc_state:{state}")

    result = _msal_app().acquire_token_by_authorization_code(
        code=request.GET.get("code"),
        scopes=settings.ENTRA_SCOPES,
        redirect_uri=settings.ENTRA_REDIRECT_URI,
    )
    if "error" in result:
        return _redirect_with_error("login_failed")

    claims = result["id_token_claims"]
    if claims.get("nonce") != nonce:
        return _redirect_with_error("invalid_state")

    email = claims.get("email") or claims.get("preferred_username")
    oid = claims["oid"]

    # This is the check the frontend's "email doesn't match" error maps to:
    # the address the person just signed up/in with in Entra must already
    # exist as a locally-provisioned User row (invite-only, ENTRA_SIGNIN_SETUP.md §0).
    try:
        user = User.objects.get(email__iexact=email)
    except User.DoesNotExist:
        return _redirect_with_error("not_provisioned")

    if not user.is_active:
        return _redirect_with_error("deactivated")

    if user.entra_object_id is None:
        user.entra_object_id = oid
        user.save(update_fields=["entra_object_id"])
    elif user.entra_object_id != oid:
        return _redirect_with_error("identity_mismatch")

    django_login(request, user)
    request.session["id_token"] = result["id_token"]  # needed for RP-initiated logout, see logout()
    return redirect(settings.FRONTEND_POST_LOGIN_URL)


def logout(request):
    id_token = request.session.get("id_token")
    django_logout(request)  # clears the local Django session

    if not id_token:
        # Nothing to hand Entra — just confirm local logout
        return JsonResponse({"detail": "logged out"})

    # RP-initiated logout — also ends Entra's own SSO session, so the next
    # /auth/login prompts for credentials + MFA again instead of silently
    # re-authenticating. See AUTHENTICATION.md for why this step exists.
    end_session_endpoint = f"{settings.ENTRA_AUTHORITY}/oauth2/v2.0/logout"
    params = {
        "id_token_hint": id_token,
        "post_logout_redirect_uri": settings.FRONTEND_POST_LOGOUT_URL,
    }
    return redirect(f"{end_session_endpoint}?{urlencode(params)}")


def _serialize_user(u):
    return {
        "id": str(u.id),
        "email": u.email,
        "role": u.role,
        "first_name": u.first_name,
        "last_name": u.last_name,
        "dob": u.dob,
        "phone": u.phone,
        "address": u.address,
        "is_active": u.is_active,
    }


def me(request):
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "not authenticated"}, status=401)
    u = request.user
    return JsonResponse(
        {
            "id": str(u.id),
            "email": u.email,
            "role": u.role,
            "first_name": u.first_name,
            "last_name": u.last_name,
            "dob": u.dob,
            "phone": u.phone,
            "address": u.address,
        }
    )


def _require_admin(request):
    return request.user.is_authenticated and request.user.role == Role.ICIB_ADMIN


@csrf_exempt
def users_collection(request):
    """Roster intake: POST /users (admin-only). GET lists provisioned users.

    Referenced by ENTRA_SIGNIN_SETUP.md §0 — a local User row must exist
    *before* someone can sign in via Entra; the callback view never creates
    one on the fly.
    """
    if request.method == "POST":
        if not _require_admin(request):
            return HttpResponseForbidden("admin role required")
        try:
            payload = json.loads(request.body or "{}")
        except json.JSONDecodeError:
            return HttpResponseBadRequest("invalid JSON")

        email = payload.get("email")
        if not email:
            return HttpResponseBadRequest("email is required")
        if User.objects.filter(email__iexact=email).exists():
            return JsonResponse({"detail": "user already exists"}, status=409)

        display_name = " ".join(
            filter(None, [payload.get("first_name"), payload.get("last_name")])
        )

        # Default flow: only the local row is created here. The invite
        # email points at Entra's self-service sign-up (requires a
        # self-service sign-up user flow enabled and linked to the app
        # registration — AUTHENTICATION.md §6b) — the person sets their own
        # password and MFA there, and /auth/callback links entra_object_id
        # on that first sign-in like any other login.
        #
        # Opt-in alternative: create_entra_identity: true has the backend
        # create the Entra identity itself via Graph, with a temp password
        # the person must change on first sign-in. Useful when self-service
        # sign-up isn't enabled for this tenant.
        entra_object_id = None
        temp_password = None
        if payload.get("create_entra_identity", False):
            if not settings.ENTRA_CIAM_DOMAIN:
                return HttpResponseBadRequest(
                    "ENTRA_CIAM_DOMAIN is not configured; required for create_entra_identity: true"
                )
            temp_password = graph.generate_temp_password()
            try:
                entra_object_id = graph.create_local_account(
                    email, display_name, temp_password
                )
            except graph.GraphError as exc:
                return JsonResponse(
                    {"detail": f"could not create Entra identity: {exc}"},
                    status=502,
                )

        user = User.objects.create_user(
            email=email,
            role=payload.get("role", Role.MEMBER),
            first_name=payload.get("first_name", ""),
            last_name=payload.get("last_name", ""),
            dob=payload.get("dob") or None,
            phone=payload.get("phone", ""),
            address=payload.get("address", ""),
            entra_object_id=entra_object_id,
        )
        body = _serialize_user(user)
        try:
            if temp_password:
                emails.send_account_setup_email(email, display_name, temp_password)
            else:
                emails.send_signup_invite_email(email, display_name)
            body["invite_email_sent"] = True
        except Exception as exc:  # SMTP misconfigured/unreachable, etc.
            # Don't lose the password (if any) just because the email
            # didn't go out — surface it so the admin can relay it.
            body["invite_email_sent"] = False
            body["email_error"] = str(exc)
            if temp_password:
                body["temp_password"] = temp_password
        return JsonResponse(body, status=201)

    if request.method == "GET":
        if not _require_admin(request):
            return HttpResponseForbidden("admin role required")
        return JsonResponse([_serialize_user(u) for u in User.objects.all()], safe=False)

    return HttpResponseNotAllowed(["GET", "POST"])


@csrf_exempt
def user_detail(request, user_id):
    """PATCH /users/{id} — role changes take effect immediately (AuthenticationMiddleware
    re-fetches the user on every request, see ENTRA_SIGNIN_SETUP.md A6)."""
    if not _require_admin(request):
        return HttpResponseForbidden("admin role required")

    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return JsonResponse({"detail": "not found"}, status=404)

    if request.method == "GET":
        return JsonResponse(_serialize_user(user))

    if request.method == "PATCH":
        try:
            payload = json.loads(request.body or "{}")
        except json.JSONDecodeError:
            return HttpResponseBadRequest("invalid JSON")

        editable_fields = [
            "role",
            "first_name",
            "last_name",
            "dob",
            "phone",
            "address",
            "is_active",
        ]
        updated = []
        for field in editable_fields:
            if field in payload:
                setattr(user, field, payload[field])
                updated.append(field)
        if updated:
            user.save(update_fields=updated)
        return JsonResponse(_serialize_user(user))

    return HttpResponseNotAllowed(["GET", "PATCH"])
