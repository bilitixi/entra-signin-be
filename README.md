# entra-signin-be

Django backend for Entra ID (Azure AD External ID) sign-in. Sessions are
cookie-based; the SPA never sees a token (see `AUTHENTICATION.md`).

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in ENTRA_* values, see AUTHENTICATION.md §7
python manage.py migrate
python manage.py createsuperuser   # local admin for /admin and the users API
python manage.py runserver 8000
```

Follow `ENTRA_SIGNIN_SETUP.md` for the full, ordered setup checklist and
`ENTRA_PORTAL_SETUP.md` for the exact Entra/Azure portal click-path
(tenant, app registration, self-service sign-up user flow, MFA) that
checklist assumes. `ENTRA_API_CONNECTOR_SETUP.md` covers the optional next
step — blocking sign-up outright for emails that were never invited.

## §2.1 Data model

`accounts.User` (`AUTH_USER_MODEL`):

| Field | Notes |
|---|---|
| `id` | UUID primary key |
| `email` | unique, sign-in identity |
| `role` | `icib_admin` \| `staff` \| `member` |
| `first_name`, `last_name`, `dob`, `phone`, `address` | profile fields |
| `entra_object_id` | set on first successful Entra sign-in; used to detect identity mismatch on subsequent logins |
| `is_active` | soft-disable; checked on every sign-in and on every request via `AuthenticationMiddleware` |

## §4.1 API

All routes are mounted under `/api/v1/`.

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/auth/login` | — | redirects to Entra |
| GET | `/auth/callback` | — | Entra redirects back here |
| GET | `/auth/logout` | session | ends local + Entra SSO session |
| GET | `/auth/me` | session | current user, 401 if not signed in |
| POST | `/auth/entra-connector/presignup` | connector Basic auth | called by Entra during sign-up, not the SPA — see AUTHENTICATION.md §6c |
| POST | `/users` | admin | roster intake (provision before first sign-in) |
| GET | `/users` | admin | list provisioned users |
| GET/PATCH | `/users/{id}` | admin | inspect / update role, profile, `is_active` |

See `AUTHENTICATION.md` for the full design rationale.
