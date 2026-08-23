# Entra Portal Setup — Custom Authentication Extension (block sign-up for uninvited emails)

Supersedes the earlier version of this doc, which assumed "API
connectors" — that mechanism doesn't exist on External ID (CIAM) tenants
(what you're using). The current equivalent is **Custom authentication
extensions**, found inside a specific user flow's own left-nav (not a
top-level "API connectors" page). Different auth method too: Entra
authenticates *itself* to your backend with a bearer token, not HTTP Basic.

Your backend endpoint is already built and pushed:
`POST /auth/entra-connector/attribute-collection-submit`.

---

## 0. Prerequisite: your backend must be reachable from the internet

Same as before — `localhost:8000` isn't reachable from Microsoft's
servers. Use `ngrok http 8000` for testing (see earlier message on setting
that up), and use the resulting `https://...ngrok...` URL below. Must be
HTTPS.

---

## 1. Register a dedicated app for the extension

This is a **separate** app registration from your main sign-in app — it
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
   presented when you create the extension itself in step 3 below (the
   creation wizard can grant this permission automatically — if it does,
   skip this step and let the wizard handle it).

---

## 2. Set the app ID in `.env`

```
ENTRA_CUSTOM_EXTENSION_APP_ID=<Application (client) ID from step 1.5>
```

Restart `manage.py runserver`.

---

## 3. Create the custom authentication extension

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
   app you created in step 1 (or let the wizard create one for you — if it
   does, go back and update `ENTRA_CUSTOM_EXTENSION_APP_ID` in `.env` to
   match whatever it created, then restart the server).
5. Finish the wizard, granting admin consent if prompted.

---

## 4. Attach it to your user flow

1. **External Identities** → **User flows** → open your sign-up flow
   (`signupsignindemo` or whatever you named it).
2. Left sidebar → **Custom authentication extensions**.
3. Select the extension you created in step 3, for the **Attribute
   collection submit** event.
4. **Save**.

---

## 5. Verify

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

- [ ] Backend reachable over HTTPS (tunnel or real deployment)
- [ ] Dedicated app registration created for the extension, with an exposed API scope
- [ ] `ENTRA_CUSTOM_EXTENSION_APP_ID` set in `.env`, server restarted
- [ ] Custom authentication extension created (Attribute collection submit event), pointing at your endpoint
- [ ] Extension attached to the user flow's **Custom authentication extensions** page
- [ ] Verified: uninvited email blocked with your message, no account created in Entra
- [ ] Verified: invited email still signs up successfully
