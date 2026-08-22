# Entra Portal Setup — What You Need To Do (updated)

Supersedes the earlier version of this doc — step 6 no longer uses
Conditional Access (a paid feature); it's replaced with the free-tier MFA
toggle on the user flow, and the self-service sign-up steps are folded in.
Do these in order; each depends on the one before it.

---

## 1. Create (or confirm) an Entra External ID tenant

1. Go to https://portal.azure.com
2. Search **"Microsoft Entra ID"** → if you already have an **External ID**
   tenant for this project, skip to step 2. Otherwise:
3. Search **"Create a resource"** → **"Microsoft Entra External ID"** →
   **Create**.
4. Choose organization name and initial domain (e.g. `yourapp.onmicrosoft.com`).
   This is what `ENTRA_CIAM_DOMAIN`/`ENTRA_AUTHORITY` are built from later.
5. Wait for provisioning, then **switch to the new tenant** (top-right
   account menu → "Switch directory").

---

## 2. Register the application

1. **App registrations** → **New registration**.
2. Name it (e.g. `entra-signin`).
3. Supported account types: **Accounts in this organizational directory
   only**.
4. Redirect URI: **Web** →
   ```
   http://localhost:8000/api/v1/auth/callback
   ```
5. **Register**.
6. On **Overview**, copy and save:
   - **Application (client) ID** → `ENTRA_CLIENT_ID`
   - **Directory (tenant) ID** → `ENTRA_TENANT_ID`

---

## 3. Add redirect URIs for every environment

1. App registration → **Authentication**.
2. Under **Web → Redirect URIs**, add one per environment:
   ```
   http://localhost:8000/api/v1/auth/callback
   https://staging.yourdomain.com/api/v1/auth/callback
   https://yourdomain.com/api/v1/auth/callback
   ```
3. Leave **Implicit grant and hybrid flows** unchecked (this app uses the
   authorization code flow server-side).
4. **Save**.

---

## 4. Generate a client secret

1. **Certificates & secrets** → **Client secrets** → **New client secret**.
2. Set an expiry per your org's policy.
3. **Copy the secret's Value immediately** — shown once. This is
   `ENTRA_CLIENT_SECRET`. Put it straight into `.env` (gitignored) or a
   secrets manager, never source control.

---

## 5. Add API permissions

### 5a. Offboarding (Graph, for later — not needed for sign-in itself)
1. **API permissions** → **Add a permission** → **Microsoft Graph** →
   **Application permissions** → search **`User.ManageIdentities.All`**.
2. **Add permissions** → **Grant admin consent** → confirm the green check.

### 5b. Admin-created identities (only if you use the opt-in `create_entra_identity: true` path)
1. Same screen → add **`User.ReadWrite.All`** (Application permission).
2. **Grant admin consent**.
Skip this if you're only using self-service sign-up (the default flow) —
it's not needed for that.

---

## 6. Create the self-service sign-up user flow

This is what lets an invited person set up their own account — and where
MFA gets enforced, without needing Conditional Access.

1. **External Identities** → **User flows** → **+ New user flow**.
2. Name it (e.g. `signupsignin`).
3. **Identity providers**: check **Email accounts** → **Email with
   password**.
4. **User attributes**: keep **Email Address** checked (required — this is
   what `/auth/callback` matches against your `User` table). Add
   Given Name / Surname if you want them collected, though this app
   doesn't currently read them back from the token.
5. **Create**.
6. Open the new user flow → **Applications** → **+ Add application** →
   select the app registration from step 2 → **Select**. (A user flow does
   nothing until an app is attached.)
7. Left sidebar → **Properties** → find **Multifactor authentication** →
   set to **Enforced** (not "Optional"). Method defaults to email
   one-time passcode; you can enable phone/authenticator app too. **Save**.
   This is the free-tier equivalent of the Conditional Access policy in the
   old version of this doc — no Premium license required.
8. Verify: **Run user flow** (top toolbar) — confirm you see **"No account?
   Sign up now"**, and that completing a test sign-up prompts for the MFA
   method you enabled.

---

## 7. Bootstrap your first local admin

`/users` (the roster-intake endpoint) requires an admin to already exist,
and Entra sign-in never creates a `User` row on its own — so the first
admin has to be created directly against the database:

```bash
cd entra-signin-be
python manage.py shell -c "
from accounts.models import User, Role
User.objects.create_user(email='you@yourdomain.com', role=Role.ICIB_ADMIN)
"
```

Use an email that can actually sign in to your tenant — either the
tenant's own built-in admin account (created automatically in step 1), or
one you'll self-serve sign up for via step 6's flow. After this, that
account can sign in and use the `/admin` UI to provision everyone else —
no more shell access needed.

---

## 8. Fill in `.env`

```
ENTRA_TENANT_ID=<Directory (tenant) ID from step 2>
ENTRA_CLIENT_ID=<Application (client) ID from step 2>
ENTRA_CLIENT_SECRET=<value from step 4>
ENTRA_AUTHORITY=https://<your-tenant-subdomain>.ciamlogin.com/<tenant-id>
ENTRA_REDIRECT_URI=http://localhost:8000/api/v1/auth/callback
FRONTEND_POST_LOGIN_URL=http://localhost:3000/
FRONTEND_POST_LOGOUT_URL=http://localhost:3000/
BACKEND_BASE_URL=http://localhost:8000

# Only if using the opt-in create_entra_identity: true path (§5b):
ENTRA_CIAM_DOMAIN=<your-tenant-subdomain>.onmicrosoft.com

# Real SMTP settings so invite emails actually deliver (leave blank
# locally to print emails to the console instead):
EMAIL_HOST=
EMAIL_PORT=587
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=
EMAIL_USE_TLS=True
DEFAULT_FROM_EMAIL=no-reply@yourdomain.com
```

---

## 9. Verify end-to-end

1. Run the backend, visit `http://localhost:8000/api/v1/auth/login`
   directly in a browser — confirms the Entra redirect and "Sign up now"
   option work before adding the frontend on top.
2. From `/admin` (once you have an admin, step 7), create a user by email
   → confirm the invite email arrives (or prints to console if `EMAIL_HOST`
   is unset).
3. Click the sign-in link in that email → **Sign up now** → set a
   password → complete MFA → should land back on the frontend, signed in.
4. Try signing up with an email that has **no** local `User` row → should
   land back on the frontend showing the error screen (`auth_error=not_provisioned`),
   not a raw Django error page.
5. Sign out, sign in again → should re-prompt for the MFA method, not
   silently succeed (confirms RP-initiated logout ended the Entra session).
6. Deactivate a user (`is_active=false` via `/admin` or `PATCH /users/{id}`)
   → their next sign-in attempt should land on the error screen with
   "account deactivated".

---

## Quick checklist

- [ ] Entra External ID tenant exists
- [ ] App registration created, redirect URIs added for every environment
- [ ] Client secret generated and stored in a secrets manager
- [ ] `ENTRA_TENANT_ID` / `ENTRA_CLIENT_ID` noted
- [ ] Graph `User.ManageIdentities.All` added + admin consent granted (offboarding, later)
- [ ] Self-service sign-up user flow created, linked to the app registration
- [ ] MFA set to **Enforced** on that user flow's Properties (not Conditional Access)
- [ ] First local admin bootstrapped via `manage.py shell`
- [ ] `.env` filled in, including `EMAIL_*` settings
- [ ] End-to-end: invite → sign up → MFA → land signed in, verified in a browser
- [ ] Error screen verified for an unprovisioned email
