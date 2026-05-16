# Outlook Actionable Messages — operational setup

Phase 7.5 of the M365 expansion plan. Ships the in-Outlook "Potwierdzam interview"
button that posts straight to `POST /api/public/interview-confirmation` so the
candidate confirms without leaving their inbox.

## Provider registration — DONE (Test Users tier)

Initial registration completed 2026-05-16 by Claude (autonomous). Current state
recorded here so anyone updating it later knows what to preserve.

| Field | Value |
|---|---|
| Provider name (Friendly Name) | `NEXUS ATS` |
| Provider Id (Microsoft-assigned originator) | `baa004f4-db24-4776-9279-c2986e58ed25` |
| Organization | `B2Bnet S.A.` (tenant `e277180c-b58a-418c-b362-bb89ab0b1301`) |
| Auth model | **MsEntra Auth** (Legacy Auth deprecated 2026-05-15) |
| MsEntra Application Id | `b5be7c77-eb7b-46ee-89b3-c6fa0f5ea7d9` (same Azure AD app as `M365_CLIENT_ID`) |
| App Id Uri | `api://auth-am-baa004f4-db24-4776-9279-c2986e58ed25/b5be7c77-eb7b-46ee-89b3-c6fa0f5ea7d9` (Microsoft-generated default — `api://auth-am-<providerId>/<appId>`) |
| Supported Token Type | `AadToken` |
| Sender email address | `artur.twardowski@b2bnetwork.pl` |
| Target URL | `https://api.nexus.dynaminds.pl/api/public/` |
| Scope | `Test Users` (auto-approved, same tenant only) |
| Test user emails | `artur.twardowski@b2bnetwork.pl` |
| Status (panel) | **Approved** |
| Application lag | Up to 1h to propagate per Microsoft note |

Panel: https://outlook.office.com/connectors/oam/publish — visible to the
account that submitted the registration (Artur Twardowski).

## What's still missing (manual TODOs for Artur)

1. **Wait ~1h after registration** for Microsoft to apply the setting, then
   send a test invite from NEXUS to `artur.twardowski@b2bnetwork.pl` and
   verify the "Potwierdzam interview" button renders in Outlook (web / new
   desktop). Click it → response should be the JSON `{success, message,
   confirmed_at}` rendered inline.
2. **Add more recruiter mailboxes to the Sender email list.** Currently only
   `artur.twardowski@b2bnetwork.pl` is registered. Every other M365 mailbox
   that recruiters connect via the NEXUS settings → Integracje → Microsoft 365
   flow needs to be added here too (one line per address). Without that, an
   invite sent from `someone-else@b2bnetwork.pl` will still arrive but Outlook
   will show only the fallback link, not the button.
3. **Promote to Organization scope** once the Test Users tier is verified.
   Same Provider, just edit → change "Who are you enabling this for?" from
   `Test Users` to `Organization`. Rollout 24h after Exchange admin approval.
   The faster-approval helper URL https://outlook.office.com/connectors/oam/admin
   lets an Exchange admin pre-approve the request from inside the tenant.
4. **Global scope** (across tenants beyond `b2bnetwork.pl`) — only needed if
   we eventually send invites from non-B2Bnet mailboxes. 2-week Microsoft
   review. Almost certainly not needed.

## How to edit registration later

1. Go to https://outlook.office.com/connectors/oam/publish — Artur's login.
2. Click the **NEXUSATS** row in the Provider table.
3. Edit fields → re-accept App Developer Agreement → Save.

To add a sender email without touching anything else: edit the provider →
"Sender email address from which actionable emails will originate" → click
"Add another email address" → enter the new mailbox UPN → Save.

## Local sanity check

```bash
# Mint a token + render the card. Keys come from your .env.
DATABASE_URL=... SECRET_KEY=... python3 -c "
from app.services.m365.actionable_messages import build_interview_confirmation_card
html, payload = build_interview_confirmation_card(event_id=1, candidate_id=1)
print(html)
print('---')
print(payload)
"
```

Paste the JSON-LD block into Microsoft's Card Designer
(https://amdesigner.azurewebsites.net/) → "MessageCard playground" to verify
Outlook would parse it.

## Smoke test in real Outlook

Pre-requisites: domain registered (My mailbox tier is enough), at least one
`CalendarEvent` linked to a real `Candidate` with a real Outlook mailbox.

1. Send the invite via the integration test path or the `/api/m365/send` UI
   (when wired) using a recruiter who has connected their M365 mailbox.
2. Open the invite in Outlook (web or new desktop client). The "Potwierdzam
   interview" button must appear above the recruiter's signature.
3. Click it. Outlook shows an inline reply with the JSON `{success, message,
   confirmed_at}` returned by the endpoint.
4. Verify in DB: `SELECT id, candidate_confirmed_at, candidate_confirmation_source
   FROM calendar_events WHERE id = <event_id>;` — `candidate_confirmed_at`
   must be NOT NULL, `source` = `outlook_actionable`.

## Known limitations

- **Outlook iOS / Android** — partial support. Most builds render the fallback
  link, not the action button. That's by design — the link works.
- **Outlook on the web** + **new Outlook desktop** — full support.
- **Classic Outlook 2019 / 2021** — depends on build. Newer cumulative updates
  render the button; older ones show the fallback.
- **Tenant policies** — some tenants disable Actionable Messages by org policy.
  The user just sees the fallback link in that case. No way for us to detect
  this client-side.
- **Provider approval lag** — until Microsoft approves the provider for
  `Organization` scope, only the recruiter's own mailbox can render the
  action.

## Security model

- The "Potwierdzam" button POSTs to a public endpoint authenticated by a
  short-lived JWT (7 days, `purpose=interview_confirmation`,
  `M365_STATE_SIGNING_KEY`).
- Endpoint is rate-limited (`10/hour` per IP via slowapi) — brute-force token
  guessing is impractical against a 7-day HMAC-SHA256 token.
- The handler is idempotent — Outlook will sometimes POST twice
  (network retry); the second click is a no-op that returns the original
  timestamp.
- All token failures return generic `403` so an attacker cannot distinguish
  "bad signature" from "wrong candidate".
