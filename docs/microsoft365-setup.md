# Microsoft 365 — setup runbook

Step-by-step setup of NEXUS's Microsoft 365 integration: per-user mailbox sync (emails + calendar + send) **and** "Sign in with Microsoft" SSO login. Both share **one** Azure AD app registration with two redirect URIs.

## What this enables

| Feature | Where in NEXUS | Status after setup |
|---|---|---|
| Per-user mailbox sync (emails → candidate threads) | Settings → Microsoft 365 Card | each user clicks "Połącz Microsoft 365" once |
| Send mail through Outlook | EmailCompose, ReEngageButton, threads | works after connect |
| Calendar event create (interview invites) | ScheduleInterviewModal | works after connect |
| Auto-parse CV from email attachments | background (`M365_AUTO_PARSE_CV=true`) | runs in sync loop |
| "Sign in with Microsoft" SSO | `/login` page | new users with whitelisted email domain auto-provisioned as `recruiter` |

## 1. Azure AD app registration (one-time)

Sign in to [portal.azure.com](https://portal.azure.com) as a **Global Administrator** of the Microsoft 365 tenant you want NEXUS bound to (here: `b2bnetwork.pl`).

### 1.1 Create the app

Microsoft Entra ID → **App registrations** → **New registration**:

- **Name**: `NEXUS ATS - Mailbox and Login` (Azure rejects `&`, `<`, `>`, `;`, `%` — use `-` or `and`)
- **Supported account types**: **Accounts in this organizational directory only — Single tenant**
- **Redirect URI**: select **Web**, value `https://api.nexus.dynaminds.pl/api/microsoft365/callback`

After creation, copy from the Overview page:
- **Application (client) ID** → goes into `M365_CLIENT_ID`
- **Directory (tenant) ID** → goes into `M365_TENANT_ID`

### 1.2 Add the second redirect URI (for SSO login)

**Authentication** → **Add Redirect URI** → Web → `https://api.nexus.dynaminds.pl/api/auth/microsoft/callback` → Save.

The mailbox sync uses the first URI, SSO login the second. One app, two callback paths.

### 1.3 API permissions (Delegated)

**API permissions** → **Add a permission** → **Microsoft Graph** → **Delegated permissions**, add:

| Permission | Why |
|---|---|
| `offline_access` | refresh tokens (long-lived sync) |
| `openid` | OIDC sign-in |
| `profile` | basic profile claims (name, etc.) |
| `email` | UPN claim used for domain whitelist + display |
| `User.Read` | `/me` lookup |
| `Mail.ReadWrite` | sync inbox + sent items |
| `Mail.Send` | send via `/me/sendMail` |
| `Calendars.ReadWrite` | sync events + create interview invites |

Then click **Grant admin consent for `<tenant>`** so the whole organisation accepts at once.

> Tip: Azure search box for permissions is case-sensitive in surprising ways — search `OpenId` (not `openid`) and the OpenId permissions group expands.

### 1.4 Create the client secret

**Certificates & secrets** → **Client secrets** → **New client secret**:

- Description: `NEXUS production`
- Expires: **730 days (24 months)** — longest supported, schedule rotation reminder for ~22 months later

**Copy the `Value` immediately** (it is shown only once) → goes into `M365_CLIENT_SECRET`. The Secret ID column is not what you want.

## 2. Generate local secrets (laptop)

```bash
# Token-at-rest encryption key (Fernet)
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# OAuth state JWT signing key (separate from main SECRET_KEY)
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

## 3. Configure Coolify env vars

Set the following in the NEXUS application's env vault (PATCH `/api/v1/applications/<app_uuid>/envs/bulk` per `~/.claude/rules/deployment-runbook.md` §3, or via the Coolify UI):

| Variable | Value | Buildtime? |
|---|---|---|
| `M365_INTEGRATION_ENABLED` | `true` | runtime |
| `M365_CLIENT_ID` | from §1.1 | runtime |
| `M365_CLIENT_SECRET` | from §1.4 | runtime |
| `M365_TENANT_ID` | from §1.1 | runtime |
| `M365_REDIRECT_URI` | `https://api.nexus.dynaminds.pl/api/microsoft365/callback` | runtime |
| `M365_TOKEN_ENCRYPTION_KEY` | Fernet key from §2 | runtime |
| `M365_STATE_SIGNING_KEY` | URL-safe key from §2 | runtime |
| `M365_SYNC_LOOP_ENABLED` | `true` | runtime |
| `M365_SYNC_INTERVAL_SECONDS` | `300` | runtime |
| `M365_BACKFILL_MONTHS` | `12` | runtime |
| `M365_IGNORE_CATEGORY` | `ATS:ignore` | runtime |
| `M365_AUTO_PARSE_CV` | `true` | runtime |
| `MICROSOFT_LOGIN_REDIRECT_URI` | `https://api.nexus.dynaminds.pl/api/auth/microsoft/callback` | runtime |
| `SSO_ALLOWED_DOMAINS` | `b2bnetwork.pl` (CSV — extend with `,foo.com,bar.com` later) | runtime |

Trigger a redeploy after the bulk PATCH.

## 4. Smoke test

### 4.1 Healthcheck

```bash
curl -fsSL https://api.nexus.dynaminds.pl/api/health | jq '.checks'
```

Expected:
- `database: "healthy"`
- `m365: "degraded"` (no connections yet) → flips to `"healthy"` after first user connects.

If `m365` is `"disabled"` — `M365_INTEGRATION_ENABLED` is false. If `"degraded"` and you have connections — check that `M365_SYNC_LOOP_ENABLED=true`.

### 4.2 Connect first mailbox

1. Sign in through Microsoft SSO as an individually assigned administrator.
   Never use a shared or synthetic production admin account.
2. **Settings → Microsoft 365** → click **Połącz Microsoft 365**.
3. Microsoft consent screen → choose your `@b2bnetwork.pl` account → Approve.
4. You return to NEXUS with **Połączony** badge.
5. Wait ~60s for backfill to start; refresh — `Synced through` field starts moving back ~12 months.

### 4.3 Send a test email

In any candidate profile → click **Wyślij email** → compose → **Wyślij**. The email arrives in the candidate's inbox; check your **Sent items** in Outlook to confirm the From address was your mailbox.

### 4.4 Schedule a test interview

Candidate profile → **Schedule Interview** → fill date/attendees → **Save**. The event appears in your Outlook calendar with the candidate as attendee. Cancel the test event in Outlook afterwards.

### 4.5 SSO login

1. Sign out.
2. On `/login` → click **Zaloguj się przez Microsoft** → consent → land on `/onboarding/welcome` (new user) or `/dashboard` (returning).
3. Try a non-whitelisted email (e.g. `@gmail.com`) → toast `Domena nieautoryzowana`, redirect back to `/login`.

## 5. Operations

### 5.1 Privacy opt-out

Users who want a specific email NOT synced into NEXUS apply the Outlook category `ATS:ignore` to that message. The body and attachments are skipped; a stub row stays in `emails` so the matcher does not re-fetch it.

To change the category name globally, set `M365_IGNORE_CATEGORY=Some:Other:Label` in Coolify.

### 5.2 Re-issue a leaked client secret

1. Azure portal → app → **Certificates & secrets** → **New client secret** (next to the old one) → save.
2. Coolify: PATCH `M365_CLIENT_SECRET` to the new value → redeploy.
3. Once deployed cleanly, return to Azure → delete the old secret.

### 5.3 Rotate `M365_TOKEN_ENCRYPTION_KEY`

This invalidates **every** stored OAuth token — all users must click Disconnect → Connect again. Plan for off-hours and broadcast in advance.

```bash
NEW_KEY=$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')
# Update Coolify env, redeploy, then in DB:
docker exec nexus-db-1 psql -U nexus -d nexus -c "DELETE FROM m365_connections;"
```

### 5.4 Add another whitelisted domain

In Coolify env vault, append to `SSO_ALLOWED_DOMAINS`:
```
SSO_ALLOWED_DOMAINS=b2bnetwork.pl,clientcorp.com
```
Redeploy. Existing users' sessions are unaffected.

## 6. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `503 Service Unavailable` on `/api/microsoft365/authorize` | `M365_CLIENT_ID` empty | set Coolify env, redeploy |
| `AADSTS50011: redirect URI mismatch` | Redirect URI in Azure differs from `M365_REDIRECT_URI` | exact-match (trailing slash, http vs https, port) |
| `AADSTS501481: code_challenge missing` | MSAL silently dropped PKCE — should not happen, the app uses raw httpx (see `app/services/m365/oauth.py` docstring) | reinstall deps; verify `app/services/m365/oauth.py` is unchanged |
| `Token cipher not configured` in logs | `M365_TOKEN_ENCRYPTION_KEY` empty | set, redeploy |
| Sync loop doesn't run | `M365_SYNC_LOOP_ENABLED=false` | set true, redeploy |
| `m365: "degraded"` in healthcheck despite connections | sync loop disabled or connection rows have `is_active=false` | check `m365_connections.is_active` |
| `domain_forbidden` after SSO callback | email domain not in `SSO_ALLOWED_DOMAINS` | add domain (CSV), redeploy |

## 7. Out of scope

- **App-only / admin-consent flow** that would access every mailbox without per-user click. Not enabled — staffing context where each recruiter consents to their own mailbox keeps the trust boundary clean.
- **Shared mailboxes** (`kontakt@b2bnetwork.pl`). Phase 3 in service comments.
- **Webhook subscriptions** (real-time Graph push). Polling at 5min is enough for ~10-person team.
- **httpOnly cookie auth**. Token still in `localStorage` for parity with email+password flow.
