# Backend API & Flow

What every endpoint under `/api/v1/` does, and how they fit together end
to end. Companion to `AUTHENTICATION.md` (why the design is shaped this
way) and `ENTRA_PORTAL_SETUP.md` (the portal click-path these endpoints
assume already exists).

---

## 1. The shape of the system

- **Sessions, not tokens.** The React SPA never talks to Entra directly
  and never sees an access/ID token. It only calls this backend's own
  `/api/v1/auth/*` endpoints and carries a Django session cookie
  (`credentials: "include"`).
- **Invite-only.** A person can only ever sign in if a local `User` row
  for their email already exists. Entra sign-in *links* to that row on
  first login — it never creates one. Rows are created by an admin via
  `POST /users`.
- **Two callers hit this backend**: the SPA (session-cookie auth) and
  Entra itself (calling back into the `entra-connector/*` endpoints with
  its own credentials, during sign-up, before an Entra identity exists).

```
 Browser (SPA)                Backend (this repo)                Entra ID
 ─────────────                ────────────────────                ────────
      │  GET /auth/login  ──────────▶
      │                          build MSAL auth URL
      │  302 → Entra ─────────────────────────────────────────────▶
      │                                                     (sign-up/in + MFA)
      │                                        Entra → POST /auth/entra-connector/*
      │                                        (only during sign-up, see §3.4)
      │  ◀───────────────────────────────────────────────── 302 back with ?code
      │  GET /auth/callback?code=...──────────▶
      │                          exchange code, validate,
      │                          link/create session
      │  ◀── 302 to frontend, session cookie set ──
      │  GET /auth/me  ──────────▶  200 {user}
```

---

## 2. Data model

`accounts.User` (`AUTH_USER_MODEL`), UUID-keyed:

| Field | Notes |
|---|---|
| `id` | UUID primary key |
| `email` | unique, the sign-in identity; matched case-insensitively |
| `role` | `icib_admin` \| `employer_admin` \| `employee` (`accounts.models.Role`) |
| `first_name`, `last_name`, `dob`, `phone`, `address` | profile fields |
| `entra_object_id` | `None` until first successful Entra sign-in, then the token's `oid` claim; used afterwards to detect identity mismatch. `default=None` (not `null=True` alone) is required — see the field's docstring in `models.py` for the bug that motivated it |
| `is_active` | soft-disable; checked at `/auth/callback` and re-checked on every request by `AuthenticationMiddleware` (Django's default re-fetches the row each request, so a role change or deactivation takes effect on the user's very next request — no re-login needed) |

---

## 3. Endpoints

All routes are mounted under `/api/v1/` (`config/urls.py` → `accounts/urls.py`).

### 3.1. `GET /auth/login` — start sign-in

**Auth:** none. **Caller:** SPA (as a plain link/navigation, not `fetch` —
it needs to follow a redirect chain a browser can, an XHR can't).

1. Generates a random `state` and `nonce`, stashes `nonce` in the cache
   keyed by `state` (`oidc_state:<state>`, 10 min TTL).
2. Builds an MSAL authorization-code-flow URL (`ENTRA_SCOPES`:
   `openid profile email offline_access`) and 302s the browser to Entra.

Entra then runs its own sign-in/sign-up + MFA UI; the backend has no part
in that until Entra redirects back.

### 3.2. `GET /auth/callback` — finish sign-in

**Auth:** none (this *is* the auth check). **Caller:** Entra, redirecting
the browser back with `?code=...&state=...`.

1. Look up `nonce` by `state` in the cache; missing/expired →
   `auth_error=invalid_state` (common causes: server restarted between
   `/auth/login` and here since the default cache is in-process and wiped
   on restart, the link was opened twice, or >10 minutes elapsed).
2. Exchange `code` for tokens via MSAL (`acquire_token_by_authorization_code`).
   Failure → logged server-side (not sent to the browser, to avoid leaking
   config details) → `auth_error=login_failed`.
3. Verify the ID token's `nonce` claim matches → else `invalid_state`.
4. Pull `email` (from `email` or `preferred_username` claim) and `oid`
   from the token.
5. **Invite-only check:** `User.objects.get(email__iexact=email)` — no
   matching row → `auth_error=not_provisioned`. This is the core guard:
   Entra sign-in never creates a row, it only links to one that
   `POST /users` already created.
6. `is_active` is `False` → `auth_error=deactivated`.
7. Link identity: if `entra_object_id` is unset, save the token's `oid`
   onto it now (first sign-in). If it's already set and doesn't match →
   `auth_error=identity_mismatch` (someone/something is presenting a
   different Entra identity for this email than the one already linked).
8. `django_login()` (sets the session cookie), stash the raw `id_token` in
   the session (needed for RP-initiated logout, §3.3), 302 to
   `FRONTEND_POST_LOGIN_URL`.

Every rejection path 302s to the frontend with `?auth_error=<code>`
instead of showing Django's own error page — the SPA reads that query
param and renders a real error screen (`_redirect_with_error`, mirrored in
`entra-signin-fe`'s `src/pages/Home.jsx`). Codes: `invalid_state`,
`login_failed`, `not_provisioned`, `deactivated`, `identity_mismatch`.

### 3.3. `GET /auth/logout` — end the session

**Auth:** session. **Caller:** SPA (plain link, same reasoning as
`/auth/login`).

1. `django_logout()` — clears the local Django session immediately.
2. No `id_token` in the session (e.g. logout called twice) → just returns
   `{"detail": "logged out"}`.
3. Otherwise, 302s to Entra's own end-session endpoint
   (`{ENTRA_AUTHORITY}/oauth2/v2.0/logout`) with `id_token_hint` and
   `post_logout_redirect_uri=FRONTEND_POST_LOGOUT_URL`. This is
   **RP-initiated logout** — it also ends Entra's own SSO session, so the
   next `/auth/login` prompts for credentials + MFA again instead of
   silently re-authenticating off Entra's cookie. Skipping this step would
   make logout local-only and misleading.

### 3.4. `POST /auth/entra-connector/attribute-collection-submit` — CIAM pre-signup block

**Auth:** Entra-issued bearer token, validated by
`entra_auth.validate_custom_extension_token`: signature verified against
the tenant's JWKS, issuer must be the tenant-GUID `ciamlogin.com` form
(not the human-friendly `ENTRA_AUTHORITY` name — see the docstring in
`entra_auth.py` for why those differ), audience must be
`ENTRA_CUSTOM_EXTENSION_APP_ID`, and the token's caller (`azp`/`appid`)
must be Entra's own well-known extension-caller service principal
(`99045fe1-7639-4a75-9d4a-577b6ca3810f`) — not just anyone holding a
validly-signed token for that audience. Fails closed if
`ENTRA_CUSTOM_EXTENSION_APP_ID` is unset. **Caller:** Entra's **custom
authentication extension** mechanism (`OnAttributeCollectionSubmit`
event), wired up under a user flow's own "Custom authentication
extensions" page (see `ENTRA_PORTAL_SETUP.md` Part B).

Purpose: reject sign-up outright for an email never provisioned via
`POST /users`, closing the gap where anyone could otherwise complete a
real Entra sign-up even though they'd fail the invite-only check at
`/auth/callback` — without this endpoint, `/auth/callback`'s check
(§3.2 step 5) still protects sign-*in*, but an uninvited person could
still complete Entra sign-*up* and end up with a real (if useless) Entra
account.

1. Validate the bearer token (above); invalid → 403, logged server-side
   (never sent back to Entra/the browser).
2. Parse the request body. For a local (email+password) identity, the
   email is under `data.userSignUpInfo.identities[]` where
   `signInType == "emailAddress"` (its `issuerAssignedId`) — **not**
   `userSignUpInfo.attributes.email`, which is empty for the sign-in
   identity even though `attributes` holds other collected form fields.
   Falls back to `attributes.email.value` in case a different identity
   provider ever puts it there. Handles both a top-level `data` wrapper
   and a flat body (this is a preview Microsoft API, so the exact shape
   isn't fully pinned down).
3. Look up an active `User` row for that email.
   - **Found** → self-heal: clear any `entra_object_id` already saved on
     that row. Reaching this event at all means Entra is about to create a
     *brand-new* identity for this email (Entra enforces unique emails for
     local accounts, so this event only fires when no existing identity
     has it) — so any `entra_object_id` still on the row necessarily
     points at a deleted/replaced identity. Clearing it now avoids that
     surfacing later as a confusing `identity_mismatch` rejection at
     `/auth/callback` (§3.2 step 7).
   - Either way, respond with Microsoft's Graph-style action shape:
     found → `microsoft.graph.attributeCollectionSubmit.continueWithDefaultBehavior`;
     not found → `microsoft.graph.attributeCollectionSubmit.showBlockPage`
     with a `message`, rendered on the sign-up page, and no Entra account
     gets created.

### 3.5. `GET /auth/me` — who am I

**Auth:** session. **Caller:** SPA, on load (`AuthContext`'s effect) and
after every `/auth/login` round trip.

- Not authenticated → `401 {"detail": "not authenticated"}`.
- Authenticated → `200` with `id`, `email`, `role`, `first_name`,
  `last_name`, `dob`, `phone`, `address`. This is the source of truth the
  SPA uses for role-based rendering/route guards — always live (see
  `AuthenticationMiddleware` note in §2), never cached client-side beyond
  the current page load.

### 3.6. `POST /users` and `GET /users` — roster intake

**Auth:** admin (`role == icib_admin`) session. **Caller:** SPA admin UI.

**POST** (create):
1. Reject non-admin (403), invalid JSON (400), missing `email` (400),
   already-existing email (409).
2. Default flow: create the local `User` row only —
   `entra_object_id=None`. Send `send_signup_invite_email` (§4), pointing
   the person at `/auth/login` → Entra's self-service "Sign up now". They
   set their own password + MFA there; `/auth/callback` links
   `entra_object_id` on that first sign-in like any other login.
3. **Opt-in** (`create_entra_identity: true` in the request body): instead
   have the backend create the Entra identity itself via Graph
   (`graph.create_local_account`, app-only client-credentials token,
   requires `ENTRA_CIAM_DOMAIN` and the `User.ReadWrite.All` Graph
   application permission — `ENTRA_PORTAL_SETUP.md` §A5b). Generates a
   temp password (`forceChangePasswordNextSignIn=True`), stores the
   returned Entra object id on the row immediately (no need to wait for
   first sign-in), and emails it via `send_account_setup_email` (§4).
   Useful when self-service sign-up isn't enabled for the tenant.
4. Response body is the serialized user (§5) plus `invite_email_sent`
   (bool). If sending failed (e.g. SMTP misconfigured) the error is
   surfaced in `email_error`, and — only for the opt-in path — the temp
   password is included in the response body too, so it isn't lost just
   because the email didn't go out.

**GET** (list): admin-only, returns every provisioned user.

### 3.7. `GET/PATCH /users/{id}` — inspect / update

**Auth:** admin session. **Caller:** SPA admin UI.

- `GET` → serialized user (§5) or 404.
- `PATCH` → updates any of `role`, `first_name`, `last_name`, `dob`,
  `phone`, `address`, `is_active` present in the body; only those fields
  are written (`update_fields`). Takes effect on the affected user's very
  next request — no re-login needed (§2).

---

## 4. Email side-effects

`accounts/emails.py`, both via Django's `send_mail` (SMTP if `EMAIL_HOST`
is set, otherwise prints to console — see `.env.example`):

- `send_signup_invite_email` — default `POST /users` flow: points at
  `/auth/login`, tells the person to use **"Sign up now"** with this exact
  email.
- `send_account_setup_email` — opt-in `create_entra_identity: true` flow:
  includes the one-time temp password and points at `/auth/login`; Entra
  forces a password change on that first sign-in.

---

## 5. Serialized user shape

Returned by `/auth/me`, `POST /users`, `GET /users`, `GET/PATCH /users/{id}`
(the last three also include `is_active`, which `/auth/me` omits since a
deactivated user can never reach it):

```json
{
  "id": "uuid",
  "email": "person@example.com",
  "role": "employee",
  "first_name": "",
  "last_name": "",
  "dob": null,
  "phone": "",
  "address": "",
  "is_active": true
}
```

---

## 6. End-to-end flows

**A. Invite → self-service sign-up → sign-in (default)**
`POST /users` (no `create_entra_identity`) → invite email → person opens
`/auth/login` → Entra "Sign up now" → sets password + MFA → (if wired,
§3.4 checks the email is provisioned) → Entra creates the identity →
redirects to `/auth/callback` → row found, `entra_object_id` linked →
session cookie set → SPA lands signed in.

**B. Admin-created identity**
`POST /users` with `create_entra_identity: true` → Graph creates the
identity + temp password up front, `entra_object_id` saved immediately →
setup email sent → person opens `/auth/login` → signs in with the temp
password → Entra forces a password change → `/auth/callback` finds the
row, `entra_object_id` already matches → signed in.

**C. Uninvited email tries to sign up**
Entra "Sign up now" → §3.4 rejects before the identity is created
(block page shown, no Entra account created) → *or*, if neither connector
is wired up, the identity gets created anyway but `/auth/callback` still
rejects at sign-in time (`not_provisioned`) — the account just sits in
Entra unused.

**D. Deactivation**
Admin `PATCH /users/{id}` with `is_active: false` → next sign-in attempt
hits `/auth/callback` step 6 → `auth_error=deactivated`. Already-active
sessions are cut off on their very next request too, since
`AuthenticationMiddleware` re-fetches `is_active` every time (§2) —
Django doesn't check it automatically, but every view path here reads
`request.user`, which triggers that re-fetch.

**E. Sign-out and back in**
`/auth/logout` clears the local session *and* ends Entra's SSO session
(RP-initiated logout, §3.3) → next `/auth/login` prompts for credentials +
MFA again, not a silent re-auth.

---

## Cross-references

| Topic | Where |
|---|---|
| Why the flow is designed this way (PKCE, state/nonce, session vs JWT tradeoff) | `AUTHENTICATION.md` |
| Entra tenant / app registration / user flow / custom extension portal setup | `ENTRA_PORTAL_SETUP.md` |
| Frontend error-code handling (`auth_error=...`) | `entra-signin-fe`'s `src/pages/Home.jsx` |
