# Teams notifications setup (Phase 7.6)

Microsoft Teams notifications post Adaptive Cards into selected channels when
key ATS events fire (candidate added, verification decision, contract signed).
Application-only Graph auth (client credentials flow) is used — no per-user
OAuth.

## 1. Azure AD app — `ChannelMessage.Send` Application permission

Reuse the existing NEXUS M365 app registration unless your IT policy forbids
it.

1. Azure portal → **App registrations** → select the NEXUS M365 app.
2. **API permissions** → **Add a permission** → **Microsoft Graph** →
   **Application permissions**.
3. Add `ChannelMessage.Send`.
4. Click **Grant admin consent for `<tenant>`**. Without admin consent Graph
   returns `403 Forbidden` on every send.
5. If your client secret has expired, generate a new one under
   **Certificates & secrets** and update Coolify (see step 2).

Reference: <https://learn.microsoft.com/en-us/graph/api/channel-post-messages>

## 2. Coolify env vault

| Variable | Required | Notes |
|---|---|---|
| `TEAMS_NOTIFICATIONS_ENABLED` | yes | Kill-switch. Default `false`. Flip to `true` after step 1 + step 3 are done. |
| `TEAMS_TENANT_ID` | only if different | Real tenant GUID. Leave blank to reuse `M365_TENANT_ID`. Must NOT be `common` — client credentials flow rejects it. |
| `TEAMS_CLIENT_ID` | only if different | Leave blank to reuse `M365_CLIENT_ID`. |
| `TEAMS_CLIENT_SECRET` | only if different | Leave blank to reuse `M365_CLIENT_SECRET`. Runtime only — not build-time. |

After updating env vars, trigger a redeploy in Coolify so the FastAPI process
re-reads `settings`.

## 3. Register channels in NEXUS

1. In Microsoft Teams, click **...** next to the target channel → **Get link
   to channel**. The URL contains the team and channel IDs:

   ```
   https://teams.microsoft.com/l/channel/19%3Achannel-uuid%40thread.tacv2/General?groupId=<TEAM_GUID>&tenantId=<TENANT>
   ```

   - `team_id` = the `groupId` query param.
   - `channel_id` = the URL-decoded path segment after `/l/channel/`
     (starts with `19:`).

2. Open NEXUS → **Ustawienia** → **Integracje** → **Powiadomienia Microsoft
   Teams**.
3. Paste `workspace_label`, `team_id`, `channel_id`, pick the notification
   types, click **Dodaj kanał**.
4. Click the **paper plane** icon to send a test card. If it lands, the
   channel is wired up. Common errors:
   - `403 Forbidden`: admin consent for `ChannelMessage.Send` missing.
   - `404 Not Found`: wrong `team_id` / `channel_id`.
   - `Integracja Teams jest wyłączona`: `TEAMS_NOTIFICATIONS_ENABLED` is
     still `false`.

## 4. Notification types

| Type | Fired by |
|---|---|
| `candidate_added` | `POST /api/candidates` |
| `decision_accepted` | `POST /api/pipeline/{id}/accept-verification` |
| `decision_rejected` | `POST /api/pipeline/{id}/reject-verification` |
| `contract_signed` | `POST /api/contracts/{id}/activate` and `POST /api/contracts/{id}/draft/finalize` |

A channel only receives cards for the types it subscribes to. Multiple
channels may subscribe to the same type — every match gets a card, in
parallel.

## 5. Failure semantics

All trigger sites call `notify_teams` via `asyncio.create_task(...)` and never
block the user response on a Teams send. Errors are logged at WARN level with
the team + channel id in scope, so they surface in Grafana/Sentry but never
bubble up to the API caller. If the kill-switch is `false`, `notify_teams`
returns 0 immediately without touching the database.
