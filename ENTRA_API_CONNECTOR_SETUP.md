# Entra Portal Setup — API Connector (block sign-up for uninvited emails)

Companion to `ENTRA_SELF_SERVICE_SIGNUP.md`. This closes the gap where
anyone could complete a real Entra sign-up even for an email never added
via `/admin` — Entra will now call your backend *during* sign-up and refuse
to create the account if the email isn't provisioned.

Your backend endpoint (`POST /auth/entra-connector/presignup`) is already
built and pushed. This doc is the portal-side wiring for it.

---

## 0. Prerequisite: your backend must be reachable from the internet

Entra calls this endpoint directly — `localhost:8000` on your machine is
**not reachable from Microsoft's servers**. For testing, expose it with a
tunnel (e.g. `ngrok http 8000`) and use the resulting `https://...ngrok...`
URL in step 2 below. For a real deployment, use your actual public backend
URL. Either way it must be HTTPS — Entra requires it.

---

## 1. Set connector credentials in `.env`

```
ENTRA_CONNECTOR_USERNAME=<pick a username>
ENTRA_CONNECTOR_PASSWORD=<pick a strong password>
```

Any values work — these aren't tied to anything in Entra, they're a shared
secret only the connector configuration (step 3) and your backend need to
agree on. Restart `manage.py runserver` after setting them.

---

## 2. Create the API connector

1. Portal → **Microsoft Entra ID** → **External Identities** → **API
   connectors** → **+ New API connector**.
2. **Display name**: e.g. `Pre-signup invite check`.
3. **Endpoint URL**:
   ```
   https://<your-public-backend-url>/api/v1/auth/entra-connector/presignup
   ```
4. **Authentication type**: **Basic**.
5. **Username** / **Password**: the exact values you put in
   `ENTRA_CONNECTOR_USERNAME` / `ENTRA_CONNECTOR_PASSWORD`.
6. **Save**.

---

## 3. Attach it to your user flow at the right step

1. **External Identities** → **User flows** → open the sign-up flow you
   created earlier.
2. Left sidebar → **API connectors**.
3. Find the step **Before creating the user** → set it to the connector you
   just created (`Pre-signup invite check`).
4. **Save**.

This step matters — attaching it to the wrong step (e.g. "After federating
with an identity provider") would let Entra create the account before your
check ever runs, defeating the point.

---

## 4. Verify

1. **User flow → Run user flow** → click **Sign up now** → enter an email
   that has **no** row in your `User` table → submit.
2. You should see your backend's message rendered directly on the sign-up
   page: *"This email hasn't been invited. Contact an admin to request
   access before signing up."* — and the account should **not** be created
   (check **Entra ID → Users** to confirm it's not there).
3. Try again with an email that **does** have a `User` row (e.g. one
   created via `/admin`) — sign-up should proceed normally.
4. Check your backend logs — you should see the `POST
   /api/v1/auth/entra-connector/presignup` requests landing for each
   attempt, distinct from `/auth/login`/`/auth/callback` traffic.

If the connector call fails outright (network unreachable, wrong
credentials, backend down), Entra's default behavior is usually to **block
sign-up** rather than silently allow it — but confirm this by checking the
connector's error-handling setting in step 2 if it matters for your case.

---

## Quick checklist

- [ ] Backend reachable over HTTPS from the internet (tunnel or real deployment)
- [ ] `ENTRA_CONNECTOR_USERNAME` / `ENTRA_CONNECTOR_PASSWORD` set in `.env`, server restarted
- [ ] API connector created in the portal, Basic auth configured with matching credentials
- [ ] Connector attached to the **Before creating the user** step of the sign-up user flow
- [ ] Verified: uninvited email is blocked with your custom message, account not created in Entra
- [ ] Verified: invited (provisioned) email still signs up successfully
