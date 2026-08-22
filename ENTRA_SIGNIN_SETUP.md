# Entra ID Sign-In — Setup Instructions (Django + React)

**Companion to:** `AUTHENTICATION.md` (design/rationale — read that first if anything here is unclear) and `README.md` (canonical API spec). This document is task-oriented: do these steps, in order, to get sign-in actually working. It assumes the Entra tenant + App Registration from `AUTHENTICATION.md` §7 already exist.

---

## 0. Prerequisites checklist

Before touching code, confirm these exist (`AUTHENTICATION.md` §7):

- [ ] Entra External ID tenant created
- [ ] App Registration created, with redirect URIs registered for **every** environment you'll run (local, staging, prod) — `http://localhost:8000/api/v1/auth/callback` for local dev
- [ ] Client secret generated, copied into your secrets store (not source control)
- [ ] `Application (client) ID` and `Directory (tenant) ID` noted
- [ ] Conditional Access MFA policy created and applied to **all users**
- [ ] Graph application permission (`User.ManageIdentities.All` or narrowest equivalent) granted admin consent — needed later for offboarding, not for sign-in itself
- [ ] A test user exists in the tenant, and a matching `User` row already exists locally with that same email (roster intake or `POST /users`) — sign-in will correctly reject the test user otherwise

---

## Part A — Backend (Django)

### A1. Install dependencies
```bash
pip install msal PyJWT cryptography django-environ
```

### A2. Environment variables
Add to `.env` (local) / secrets manager (deployed):
```
ENTRA_TENANT_ID=<directory tenant id>
ENTRA_CLIENT_ID=<application client id>
ENTRA_CLIENT_SECRET=<client secret value>
ENTRA_AUTHORITY=https://<tenant-subdomain>.ciamlogin.com/<tenant-id>
ENTRA_REDIRECT_URI=http://localhost:8000/api/v1/auth/callback
FRONTEND_POST_LOGIN_URL=http://localhost:3000/
FRONTEND_POST_LOGOUT_URL=http://localhost:3000/
```

### A3. `settings.py`
```python
import environ
env = environ.Env()
environ.Env.read_env()

ENTRA_TENANT_ID = env("ENTRA_TENANT_ID")
ENTRA_CLIENT_ID = env("ENTRA_CLIENT_ID")
ENTRA_CLIENT_SECRET = env("ENTRA_CLIENT_SECRET")
ENTRA_AUTHORITY = env("ENTRA_AUTHORITY")
ENTRA_REDIRECT_URI = env("ENTRA_REDIRECT_URI")
ENTRA_SCOPES = ["openid", "profile", "email", "offline_access"]
FRONTEND_POST_LOGIN_URL = env("FRONTEND_POST_LOGIN_URL")
FRONTEND_POST_LOGOUT_URL = env("FRONTEND_POST_LOGOUT_URL")

# Session/cookie config — required for the React SPA to work cross-request
SESSION_COOKIE_SECURE = not DEBUG        # True outside local dev
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = not DEBUG

# React dev server origin — needed only if frontend/backend run on different ports locally
CORS_ALLOWED_ORIGINS = ["http://localhost:3000"]
CORS_ALLOW_CREDENTIALS = True
```
If frontend and backend are same-origin in production (recommended, per `AUTHENTICATION.md` §5), `CORS_ALLOWED_ORIGINS`/`CORS_ALLOW_CREDENTIALS` are only needed for local dev where React runs on a different port.

### A4. `auth/views.py`
```python
import secrets
import msal
from django.conf import settings
from django.core.cache import cache
from django.contrib.auth import login as django_login, logout as django_logout
from django.http import HttpResponseBadRequest, HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect
from urllib.parse import urlencode
from .models import User


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


def callback(request):
    state = request.GET.get("state")
    nonce = cache.get(f"oidc_state:{state}")
    if not state or nonce is None:
        return HttpResponseBadRequest("invalid or expired state")
    cache.delete(f"oidc_state:{state}")

    result = _msal_app().acquire_token_by_authorization_code(
        code=request.GET.get("code"),
        scopes=settings.ENTRA_SCOPES,
        redirect_uri=settings.ENTRA_REDIRECT_URI,
    )
    if "error" in result:
        return HttpResponseForbidden(result.get("error_description"))

    claims = result["id_token_claims"]
    if claims.get("nonce") != nonce:
        return HttpResponseForbidden("nonce mismatch")

    email = claims.get("email") or claims.get("preferred_username")
    oid = claims["oid"]

    try:
        user = User.objects.get(email__iexact=email)
    except User.DoesNotExist:
        return HttpResponseForbidden("no account provisioned for this email")

    if not user.is_active:
        return HttpResponseForbidden("account deactivated")

    if user.entra_object_id is None:
        user.entra_object_id = oid
        user.save(update_fields=["entra_object_id"])
    elif user.entra_object_id != oid:
        return HttpResponseForbidden("identity mismatch")

    django_login(request, user)
    request.session["id_token"] = result["id_token"]  # needed for RP-initiated logout, see A5
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


def me(request):
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "not authenticated"}, status=401)
    u = request.user
    return JsonResponse({
        "id": str(u.id),
        "email": u.email,
        "role": u.role,
        "first_name": u.first_name,
        "last_name": u.last_name,
        "dob": u.dob,
        "phone": u.phone,
        "address": u.address,
    })
```

### A5. `auth/urls.py`
```python
from django.urls import path
from . import views

urlpatterns = [
    path("auth/login", views.login, name="auth-login"),
    path("auth/callback", views.callback, name="auth-callback"),
    path("auth/logout", views.logout, name="auth-logout"),
    path("auth/me", views.me, name="auth-me"),
]
```
Mount under `/api/v1/` in the project's root `urls.py`, matching README §4.1's paths exactly (`/auth/login`, `/auth/callback`, `/auth/logout`) plus `/auth/me`.

### A6. Confirm `AuthenticationMiddleware` re-checks `is_active` and role live
No code change needed if you're using Django's default `django.contrib.auth.middleware.AuthenticationMiddleware` — it re-fetches the `User` row from the DB on every request, so `request.user.role` and `request.user.is_active` are always current, never cached from login time. **Do not** shortcut this by stuffing `role` into `request.session` — see `AUTHENTICATION.md` for why that reintroduces staleness.

### A7. Run and test locally
```bash
python manage.py runserver 8000
```
Visit `http://localhost:8000/api/v1/auth/login` directly in a browser first (before wiring the frontend) — confirms the Entra redirect, MFA prompt, and callback resolution work before adding frontend complexity on top.

---

## Part B — Frontend (React)

The SPA never talks to Entra directly and never stores a token — it only calls this app's own `/api/v1/auth/*` endpoints and relies on the session cookie (`AUTHENTICATION.md` §5, §9).

### B1. API client with credentials
```javascript
// src/api/client.js
const BASE_URL = process.env.REACT_APP_API_BASE_URL || "/api/v1";

export async function apiFetch(path, options = {}) {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...options,
    credentials: "include",  // sends the session cookie on every call
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
  });

  if (res.status === 401) {
    window.location.href = `${BASE_URL}/auth/login`;
    return; // navigation is happening; nothing more to do
  }
  return res;
}
```

### B2. Auth context — the `GET /auth/me` check
```jsx
// src/auth/AuthContext.jsx
import { createContext, useContext, useEffect, useState } from "react";
import { apiFetch } from "../api/client";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiFetch("/auth/me")
      .then((res) => (res && res.ok ? res.json() : null))
      .then(setUser)
      .finally(() => setLoading(false));
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
```
Wrap the whole app in `<AuthProvider>` at the top level (`index.jsx`/`App.jsx`). `apiFetch`'s 401 handler (B1) already redirects to `/auth/login` if the session is missing/expired, so `user` staying `null` after the loading state resolves means "redirect is already in flight" — no separate error UI needed for that case.

### B3. Login / logout buttons
```jsx
function LoginButton() {
  return <a href="/api/v1/auth/login">Sign in</a>;
}

function LogoutButton() {
  return <a href="/api/v1/auth/logout">Sign out</a>;
}
```
Plain links, not `fetch` calls — both endpoints redirect the browser (to Entra, then back), which a `fetch()` call can't follow the way a full page navigation can.

### B4. Role-based rendering / route guards
```jsx
import { useAuth } from "./auth/AuthContext";

function RequireRole({ roles, children }) {
  const { user, loading } = useAuth();
  if (loading) return <Spinner />;
  if (!user || !roles.includes(user.role)) return <Navigate to="/" />;
  return children;
}

// usage
<Route
  path="/admin/*"
  element={
    <RequireRole roles={["icib_admin"]}>
      <AdminDashboard />
    </RequireRole>
  }
/>
```
Reminder (`AUTHENTICATION.md` §9): this is UX only. The backend independently enforces role/ownership on every endpoint — `RequireRole` just avoids showing an admin screen to someone who'd get a 403 from the API anyway.

### B5. Handling the post-login redirect
`FRONTEND_POST_LOGIN_URL` (backend env var, A2) should point at a route in the SPA — typically `/` or a dedicated `/post-login` route that immediately re-triggers the `GET /auth/me` check (or just relies on `AuthProvider`'s existing `useEffect`, since a fresh page load re-runs it anyway).

---

## Part C — End-to-end test checklist

- [ ] Unauthenticated user hitting a protected route gets redirected to Entra sign-in, prompted for MFA
- [ ] Successful sign-in with an email that has **no** local `User` row → rejected (403), confirms invite-only guard
- [ ] Successful sign-in with a provisioned email → lands back on the frontend, `GET /auth/me` returns 200 with correct `role`
- [ ] Second login by the same user → `entra_object_id` unchanged, no duplicate linking
- [ ] `POST /auth/logout` (via the Sign out link) → session cookie cleared, subsequent `GET /auth/me` returns 401
- [ ] After logout, clicking Sign in again prompts for **credentials + MFA** (confirms RP-initiated logout actually ended the Entra SSO session, not just the local one — see `AUTHENTICATION.md`)
- [ ] Deactivated user (`is_active = false`) attempting to sign in → rejected at `/auth/callback`
- [ ] Role change via `PATCH /users/{id}` takes effect on the affected user's very next request, without them needing to log out/in

---

## Cross-references

| Topic | Where |
|---|---|
| Why the flow is designed this way (PKCE, state/nonce, session vs JWT tradeoff) | `AUTHENTICATION.md` §2–§5 |
| Entra tenant / App Registration setup | `AUTHENTICATION.md` §7 |
| Offboarding (Graph API deactivation call) | `AUTHENTICATION.md` §6, §8.5 |
| Security checklist before go-live | `AUTHENTICATION.md` §11 |
| Data model fields referenced above (`User.entra_object_id`, `role`, `is_active`) | `README.md` §2.1 |
