# Outlook Actionable Messages — operational setup

Phase 7.5 of the M365 expansion plan. Ships the in-Outlook "Potwierdzam interview"
button that posts straight to `POST /api/public/interview-confirmation` so the
candidate confirms without leaving their inbox.

The code is already deployed; before users see actual buttons in their Outlook,
the sending domain has to be whitelisted by Microsoft via the Actionable Email
Developer Dashboard. Until then Outlook delivers the email but renders only the
fallback `<a>` link.

## One-time registration

1. Go to https://outlook.office.com/connectors/oam/publish — log in with the
   Microsoft account that owns the sender mailbox(es) we'll send invites from
   (e.g. `recruiting@b2bnet.pl`, `noreply@b2bnet.pl`).
2. **New provider** with:
   - **Provider name** — `NEXUS ATS`.
   - **Sender email address from which Actionable Emails will originate** —
     list every mailbox we send invites from. One row per address.
   - **Target URLs** — `https://api.nexus.dynaminds.pl/api/public/`. Microsoft's
     service POSTs to URLs under this prefix on the recipient's behalf.
   - **Scope of submission** — `My mailbox` first to test on yourself. After
     verifying, resubmit with `Organization` (or `Global` if we add tenants
     beyond `b2bnet.pl`).
3. Submit. The "My mailbox" tier auto-approves immediately and lets you test
   end-to-end. Organization scope goes through Microsoft review (a few days).
4. After approval, copy the **Provider ID** GUID from the dashboard. It is not
   currently used by our code — Outlook resolves the provider by sender +
   target URL — but record it for the runbook.

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
