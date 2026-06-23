# Self-service registration (email/password) — completion report

> Domain-gated email/password sign-up as an alternative to Microsoft SSO. New
> accounts are read-only viewers, email-verified before first login; an admin
> elevates the role afterwards in the existing panel. PR 2026-06-23.

## Goal

Let people register to NEXUS **without** Microsoft login, while keeping the
constraint that **only `@b2bnetwork.pl` (whitelisted) addresses** can sign up.
New users land as a **read-only viewer**; an admin changes their role later in
the panel (that admin flow already existed — `PUT /api/admin/users/{id}` via
Settings → Admin → Users).

## Flow

1. `/register` → name + email + password. Backend gates on domain whitelist,
   forces role `user`, creates the account `email_verified=False`, emails an
   activation link.
2. User clicks link → `/register/verify?token=…` → `POST /api/auth/verify-email`
   flips `email_verified=True`.
3. User logs in (`/login`) as a read-only viewer. Login is **blocked with a
   clear message until the email is verified**.
4. Admin elevates the role in Settings → Admin → Users.

## What changed

### Backend
- **`POST /api/auth/register`** ([app/api/auth.py](../backend/app/api/auth.py)) —
  rewritten. Previously it was publicly mounted, unauthenticated, **accepted an
  arbitrary `role`, and had no domain check** → anyone could self-provision an
  `admin`. Now:
  - Gated by `SELF_REGISTRATION_ENABLED` (503 when off).
  - Email domain must be in `settings.sso_allowed_domains_list` (shared with
    SSO; empty list = fail-closed reject-all).
  - Role is **forced to `user`** server-side — the request schema
    (`SelfRegisterRequest`) has no `role` field.
  - Account created `email_verified=False`, `is_active=True`, `roles=["user"]`.
  - **Anti-enumeration**: always returns the same generic `201` (never `409`),
    and the bcrypt hash is computed on both the new and existing paths so timing
    does not leak whether an email is registered. A duplicate registration for
    an *unverified* account re-sends the link (legit recovery); for a *verified*
    one it silently no-ops.
- **`POST /api/auth/verify-email`** — single-use 64-hex token (SHA-256 hashed,
  24 h TTL); sets `email_verified=True`.
- **`POST /api/auth/resend-verification`** — anti-enumeration (always 200);
  re-sends a link only for an existing unverified account.
- **`login`** — blocks accounts with `email_verified=False`. Existing
  email/password users and Microsoft SSO users are `email_verified=True`
  (migration backfill + SSO sets it), so they are **not** affected.
- New `email_verified` column on `users`; new `email_verification_tokens` table
  (mirrors `password_reset_tokens`). Token service
  ([app/services/email_verification.py](../backend/app/services/email_verification.py))
  and email sender (`send_email_verification_email`) mirror the password-reset
  infrastructure.
- New config flag `SELF_REGISTRATION_ENABLED` (default **off**).

### Frontend
- New **`/register`** page and **`/register/verify`** page (auto-verifies the
  token on mount), a "Zarejestruj się" link on `/login`, `authApi` helpers, and
  `/register` added to `PUBLIC_PATHS` in `middleware.ts`.

### Migration
- [`0139_email_verification`](../backend/alembic/versions/0139_email_verification.py)
  — idempotent. `email_verified BOOLEAN NOT NULL DEFAULT true` backfills every
  existing/SSO/admin account to verified (no lockout). Chained off the
  `0138_candidate_expected_hourly_rate` head; applied by the entrypoint's
  `alembic upgrade heads` (the repo intentionally tolerates multiple heads).

## Security review

Ran an adversarial multi-lens review (privilege-escalation, token-flow &
login-gate, enumeration/rate-limit, migration integrity, frontend/injection)
with independent skeptic verification of each finding.

- **Confirmed (1, medium):** account enumeration via `409` on `/register`.
  **Fixed** — endpoint is now anti-enumeration (see above).
- **Refuted (2):** no privilege escalation (role forced server-side, Pydantic
  ignores extra `role`), no lockout of existing/SSO users, migration backfill
  correct, token flow sound.

## Activation (when ready to go live)

Self-registration ships **dormant**. To enable on prod:

1. Coolify env vault → ensure `SSO_ALLOWED_DOMAINS` contains `b2bnetwork.pl`
   (already set for SSO).
2. Enable email so the activation link sends: `SMTP_ENABLED=true` + SMTP creds
   (`SMTP_HOST/PORT/USER/PASSWORD/FROM_EMAIL`).
3. Set `SELF_REGISTRATION_ENABLED=true`.
4. Smoke-test: `/register` with an `@b2bnetwork.pl` address → activation email →
   `/register/verify` → login as viewer → admin elevates role in the panel.

## DB

- `users.email_verified` (BOOLEAN NOT NULL DEFAULT true).
- `email_verification_tokens` (id, user_id FK CASCADE, token_hash UNIQUE,
  expires_at, used_at, requested_ip, created_at, updated_at).
- Migration `0139_email_verification` (down_revision
  `0138_candidate_expected_hourly_rate`).

## Tests

[backend/tests/test_auth_register.py](../backend/tests/test_auth_register.py)
(wired into CI `ci.yml`): gate-off 503, foreign-domain 403, viewer+unverified
creation, **caller-supplied `role` ignored**, email lowercasing, anti-enum
duplicate 201, short-password 422, login blocked until verified, verify→login
success, invalid-token 400, resend anti-enumeration.

## Known limitations / follow-ups

- Pushing `.github/workflows/ci.yml` needs a `workflow`-scoped git token (the
  local token lacks it — see project memory).
- No CAPTCHA on `/register`; protection is the domain whitelist + 3/min IP rate
  limit + Cloudflare. Adequate for an internal tool; revisit if abused.
