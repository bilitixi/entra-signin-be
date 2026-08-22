# Authentication design — Entra ID sign-in

This is the design/rationale companion to `ENTRA_SIGNIN_SETUP.md` (the
task-oriented setup checklist) and `README.md` (API spec). Read this when a
step in the setup doc needs justification.

## §2. Flow

Authorization Code flow via MSAL (`msal.ConfidentialClientApplication`),
run entirely server-side:

1. `GET /auth/login` generates a random `state` + `nonce`, stashes the nonce
   in cache keyed by state (10 min TTL), and redirects the browser to Entra.
2. Entra authenticates the user (prompting for MFA per the Conditional
   Access policy) and redirects back to `/auth/callback` with a `code`.
3. The callback exchanges the code for tokens, validates `state`/`nonce`,
   and reads `email` + `oid` off the validated ID token claims.
4. The app looks up a **pre-existing** local `User` by email — sign-in never
   creates an account. This makes the system invite-only: someone must be
   provisioned locally (roster intake / `POST /users`) before they can ever
   authenticate.
5. On first sign-in the user's `entra_object_id` is recorded; on every
   subsequent sign-in it must match, or the request is rejected
   (§6 below explains why this matters for offboarding).
6. `django_login()` establishes a normal Django session; the ID token is
   kept in the session only for step 7's logout call.

## §3. PKCE / state / nonce

`state` defeats CSRF against the callback; `nonce` defeats ID-token replay.
Both are single-use and expire after 10 minutes (cache TTL). MSAL's
confidential client flow (server holds the client secret) makes PKCE
optional here, but state+nonce validation is still mandatory — see
`accounts/views.py:callback`.

## §4. Session vs. JWT

The SPA holds no token of any kind — only an `HttpOnly` session cookie.
Trade-off: this means same-site (or CORS-with-credentials) deployment, but
it removes an entire class of XSS-token-theft risk and lets us revoke access
instantly by flipping `is_active` (see §6), which a client-held JWT cannot
do without a revocation list.

## §5. Deployment topology

Recommended: frontend and backend served same-origin in production (e.g.
Django serves the SPA's static build, or a reverse proxy fronts both) so
the session cookie just works with no CORS configuration. `CORS_ALLOWED_ORIGINS`
in `config/settings.py` exists only to support local dev, where CRA/Vite's
dev server runs on a different port than Django.

## §6. Offboarding

Deactivating a user is a two-step story:

1. Locally: `is_active = False` (via `PATCH /users/{id}`) — takes effect
   immediately, no logout/login needed, because `AuthenticationMiddleware`
   re-fetches the user row on every request (see §9).
2. In Entra (out of scope for sign-in itself, tracked separately): revoke
   the user's Entra session/credentials via the Graph API
   (`User.ManageIdentities.All` or narrower), so a still-valid Entra SSO
   session can't be used to sign back in elsewhere. This is why the app
   registration needs that Graph permission granted even though sign-in
   doesn't call Graph directly.

## §6b. Provisioning an Entra identity from the admin UI

`POST /users` can optionally create the person's Entra identity at the same
time as the local row (`accounts/graph.py:create_local_account`), instead of
requiring an admin to create it manually in the portal first. It:

1. Generates a random temp password meeting Entra's default complexity.
2. Calls Graph to create a "local account" identity (email + password
   sign-in, as opposed to a work/school or B2B guest account) with
   `forceChangePasswordNextSignIn: true`.
3. Records the returned Entra object id on the local `User` row immediately
   — pre-linking it, rather than waiting for the `entra_object_id is None`
   branch in `callback()` to fire on first sign-in.
4. Emails the temp password + a sign-in link to the person directly
   (`accounts/emails.py:send_account_setup_email`) rather than relying on
   the admin to relay it. If the email fails to send (SMTP unreachable,
   misconfigured, etc.), the password is returned in the API response once
   as a fallback so it isn't lost — `invite_email_sent: false` in the
   response signals this happened.

Because of step 2, the person's very first "Sign in" click lands them on
Microsoft's forced password-change screen rather than a normal login — that
*is* their account setup. When they finish it and land at `/auth/callback`,
the existing invite-only check (§2 step 4 — `User.objects.get(email__iexact=email)`)
is exactly the "does the account email match the User table" verification;
no separate check was needed since the Entra identity's sign-in email *is*
what we provisioned it with.

Requires the Graph application permission `User.ReadWrite.All` with admin
consent (§7), `ENTRA_CIAM_DOMAIN` set, and real SMTP settings (`EMAIL_HOST`
etc.) for the email to actually deliver — without SMTP configured, emails
print to the console instead (fine for local dev, not for real users).
Without `ENTRA_CIAM_DOMAIN`, `POST /users` falls back to local-row-only
provisioning (pass `create_entra_identity: false` to always skip the Entra
call).

## §7. Tenant / App Registration prerequisites

See `ENTRA_SIGNIN_SETUP.md` §0 for the checklist. Summary of what must
exist before Part A of that doc will work:

- An Entra External ID tenant.
- An App Registration with redirect URIs for every environment
  (`.../api/v1/auth/callback`).
- A client secret, stored in a secrets manager — never in source control.
- `Application (client) ID` and `Directory (tenant) ID`.
- A Conditional Access policy requiring MFA for all users.
- Admin-consented Graph permission for offboarding (§6).

## §8. Related endpoints

§8.5 Offboarding endpoint — not implemented by this sign-in slice; tracked
as follow-up work alongside the Graph API call in §6.

## §9. Why role/is_active must never be cached in the session

Stuffing `role` (or `is_active`) into `request.session` at login time would
mean a role change or deactivation only takes effect the next time the user
logs back in — a stale-privilege window. Django's default
`AuthenticationMiddleware` avoids this for free: it loads `request.user`
from the database on every request. Don't shortcut it.

## §11. Security checklist before go-live

- [ ] `SECRET_KEY` set from a real secret, not the dev default
- [ ] `DEBUG=False`
- [ ] `SESSION_COOKIE_SECURE` / `CSRF_COOKIE_SECURE` on (automatic when `DEBUG=False`, see `config/settings.py`)
- [ ] Redirect URIs in the App Registration match the deployed callback URL exactly
- [ ] Client secret rotated on a schedule, never committed
- [ ] Conditional Access MFA policy verified active for all users
- [ ] `/admin` and the `/users` roster-intake endpoints restricted to admins only (already enforced in `accounts/views.py`, re-verify after any change)
