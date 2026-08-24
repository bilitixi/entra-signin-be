# Entra Portal Setup

Everything you need to do in the Entra/Azure portal, in order: tenant,
app registration, self-service sign-up with MFA, and (optional) blocking
sign-up outright for emails that were never invited. Do these in order;
each part depends on the one before it.

This doc supersedes two earlier, separate versions:
- The original portal setup, whose step 6 used Conditional Access (a paid
  feature) — replaced with the free-tier MFA toggle on the user flow.
- The original API-connector doc, which assumed "API connectors" — that
  mechanism doesn't exist on External ID (CIAM) tenants (what this project
  uses). The current equivalent is **Custom authentication extensions**,
  found inside a specific user flow's own left-nav (not a top-level "API
  connectors" page). Different auth method too: Entra authenticates
  *itself* to your backend with a bearer token, not HTTP Basic.

---

## Part A — Core setup (tenant, app registration, self-service sign-up)

### A1. Create (or confirm) an Entra External ID tenant

1. Go to https://portal.azure.com
2. Search **"Microsoft Entra ID"** → if you already have an **External ID**
   tenant for this project, skip to A2. Otherwise:
3. Search **"Create a resource"** → **"Microsoft Entra External ID"** →
   **Create**.
4. Choose organization name and initial domain (e.g. `yourapp.onmicrosoft.com`).
   This is what `ENTRA_CIAM_DOMAIN`/`ENTRA_AUTHORITY` are built from later.
5. Wait for provisioning, then **switch to the new tenant** (top-right
   account menu → "Switch directory").

### A2. Register the application

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

### A3. Add redirect URIs for every environment

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

### A4. Generate a client secret

1. **Certificates & secrets** → **Client secrets** → **New client secret**.
2. Set an expiry per your org's policy.
3. **Copy the secret's Value immediately** — shown once. This is
   `ENTRA_CLIENT_SECRET`. Put it straight into `.env` (gitignored) or a
   secrets manager, never source control.

### A5. Add API permissions

**A5a. Offboarding (Graph, for later — not needed for sign-in itself)**
1. **API permissions** → **Add a permission** → **Microsoft Graph** →
   **Application permissions** → search **`User.ManageIdentities.All`**.
2. **Add permissions** → **Grant admin consent** → confirm the green check.

**A5b. Admin-created identities (only if you use the opt-in `create_entra_identity: true` path)**
1. Same screen → add **`User.ReadWrite.All`** (Application permission).
2. **Grant admin consent**.
Skip this if you're only using self-service sign-up (the default flow) —
it's not needed for that.

### A6. Create the self-service sign-up user flow

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
   select the app registration from A2 → **Select**. (A user flow does
   nothing until an app is attached.)
7. Left sidebar → **Properties** → find **Multifactor authentication** →
   set to **Enforced** (not "Optional"). Method defaults to email
   one-time passcode; you can enable phone/authenticator app too. **Save**.
   This is the free-tier equivalent of a Conditional Access policy — no
   Premium license required.
8. Verify: **Run user flow** (top toolbar) — confirm you see **"No account?
   Sign up now"**, and that completing a test sign-up prompts for the MFA
   method you enabled.

### A7. Bootstrap your first local admin

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
tenant's own built-in admin account (created automatically in A1), or
one you'll self-serve sign up for via A6's flow. After this, that
account can sign in and use the `/admin` UI to provision everyone else —
no more shell access needed.

### A8. Fill in `.env`

```
ENTRA_TENANT_ID=<Directory (tenant) ID from A2>
ENTRA_CLIENT_ID=<Application (client) ID from A2>
ENTRA_CLIENT_SECRET=<value from A4>
ENTRA_AUTHORITY=https://<your-tenant-subdomain>.ciamlogin.com/<tenant-id>
ENTRA_REDIRECT_URI=http://localhost:8000/api/v1/auth/callback
FRONTEND_POST_LOGIN_URL=http://localhost:3000/
FRONTEND_POST_LOGOUT_URL=http://localhost:3000/
BACKEND_BASE_URL=http://localhost:8000

# Only if using the opt-in create_entra_identity: true path (§A5b):
ENTRA_CIAM_DOMAIN=<your-tenant-subdomain>.onmicrosoft.com

# Real SMTP settings so invite emails actually deliver (leave blank
# locally to print emails to the console instead):
EMAIL_HOST=
EMAIL_PORT=587
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=
EMAIL_USE_TLS=True
DEFAULT_FROM_EMAIL=no-reply@yourdomain.com

# Only if wiring Part B below:
ENTRA_CUSTOM_EXTENSION_APP_ID=
```

### A9. Verify end-to-end

1. Run the backend, visit `http://localhost:8000/api/v1/auth/login`
   directly in a browser — confirms the Entra redirect and "Sign up now"
   option work before adding the frontend on top.
2. From `/admin` (once you have an admin, A7), create a user by email
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

## Part B — Block sign-up for uninvited emails (custom authentication extension)

Optional next step, on top of Part A. Your backend endpoint for this is
already built and pushed: `POST
/auth/entra-connector/attribute-collection-submit`.

### B0. Prerequisite: your backend must be reachable from the internet

`localhost:8000` isn't reachable from Microsoft's servers. Use `ngrok
http 8000` for testing, and use the resulting `https://...ngrok...` URL
below. Must be HTTPS.

### B1. Register a dedicated app for the extension

This is a **separate** app registration from the sign-in app in A2 — it
exists only so Entra has an audience to issue tokens for when it calls
your backend.

1. Portal → **App registrations** → **New registration**.
2. Name: e.g. `entra-signin-custom-extension`.
3. Supported account types: **Accounts in this organizational directory
   only**.
4. No redirect URI needed. **Register**.
5. On **Overview**, copy **Application (client) ID** — this is
   `ENTRA_CUSTOM_EXTENSION_APP_ID`.
6. **Expose an API** (left sidebar) → **+ Add a scope** → accept the
   default Application ID URI → add any scope name (e.g. `access_as_extension`)
   with **Who can consent: Admins only** → **Add scope**. (Custom
   authentication extensions require the app to have at least one exposed
   scope, even though your backend doesn't validate scopes itself — it
   validates audience/issuer/caller instead, per `accounts/entra_auth.py`.)
7. **API permissions** → **Add a permission** → **APIs my organization
   uses** → search **"Microsoft Graph"** is NOT what you want here — search
   instead for **"Custom Authentication Extension"** or use the option
   presented when you create the extension itself in B3 below (the
   creation wizard can grant this permission automatically — if it does,
   skip this step and let the wizard handle it).

### B2. Set the app ID in `.env`

```
ENTRA_CUSTOM_EXTENSION_APP_ID=<Application (client) ID from B1.5>
```

Restart `manage.py runserver`.

### B3. Create the custom authentication extension

1. **External Identities** → **Custom authentication extensions** (a
   top-level page — this part *is* at the top level) → **+ Create a custom
   extension**.
2. **Type of event**: choose **Attribute collection submit** — this is the
   "before creating the user" equivalent.
3. **Endpoint URL**:
   ```
   https://<your-public-backend-url>/api/v1/auth/entra-connector/attribute-collection-submit
   ```
4. When asked for the app registration this extension calls as, select the
   app you created in B1 (or let the wizard create one for you — if it
   does, go back and update `ENTRA_CUSTOM_EXTENSION_APP_ID` in `.env` to
   match whatever it created, then restart the server).
5. Finish the wizard, granting admin consent if prompted.

### B4. Attach it to your user flow

1. **External Identities** → **User flows** → open your sign-up flow
   (the one created in A6).
2. Left sidebar → **Custom authentication extensions**.
3. Select the extension you created in B3, for the **Attribute
   collection submit** event.
4. **Save**.

### B5. Verify

1. **Run user flow** → **Sign up now** → enter an email with **no** row
   in your `User` table → submit.
2. You should see the block message from your backend rendered directly
   on the sign-up page, and the account should **not** appear afterward in
   **Entra ID → Users**.
3. Try again with a provisioned email — sign-up should proceed normally.
4. Check your backend logs for `POST
   /api/v1/auth/entra-connector/attribute-collection-submit` requests. If
   email parsing ever fails (a `no email found in payload` warning in the
   logs), the exact request shape may differ slightly from what's
   implemented — this is a preview Microsoft API and the full schema isn't
   completely pinned down publicly; share that logged payload and the
   parsing can be adjusted to match.

---

## Quick checklist

**Part A — core setup**
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

**Part B — block uninvited sign-up (optional)**
- [ ] Backend reachable over HTTPS (tunnel or real deployment)
- [ ] Dedicated app registration created for the extension, with an exposed API scope
- [ ] `ENTRA_CUSTOM_EXTENSION_APP_ID` set in `.env`, server restarted
- [ ] Custom authentication extension created (Attribute collection submit event), pointing at your endpoint
- [ ] Extension attached to the user flow's **Custom authentication extensions** page
- [ ] Verified: uninvited email blocked with your message, no account created in Entra
- [ ] Verified: invited email still signs up successfully
