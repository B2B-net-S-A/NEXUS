# Autenti e-signature integration

> Status: shipped (Phases 1–5). Kill-switch: `AUTENTI_ENABLED`.
> Plan reference: [`~/.claude/plans/zaplanuj-wszystko-zgodnie-z-tranquil-torvalds.md`](~/.claude/plans/zaplanuj-wszystko-zgodnie-z-tranquil-torvalds.md)

## Overview

Send a finalized contract HTML snapshot to [Autenti](https://autenti.com) for e-signature, receive webhooks back when signers act, store the signed PDF locally. Hooks into the existing Contract Draft pipeline (Phase 16) — the recruiter clicks "Wyślij do podpisu" on an active contract; status updates land in the UI automatically.

## Architecture

```
recruiter UI ──POST send──▶ /api/autenti ──prepare_send──▶ DB row (draft)
                                       │                          │
                                       └─async task──▶ HTML→PDF → Autenti API
                                                                  │
Autenti ──webhook (JWT)──▶ /api/autenti/webhook ──verify──▶ state machine
                                                              │
                                                              ├ download signed PDF
                                                              ├ Notification
                                                              └ Activity audit
```

Files:
- `backend/app/services/autenti/client.py` — REST client (OAuth2, retries).
- `backend/app/services/autenti/pdf_renderer.py` — WeasyPrint HTML→PDF.
- `backend/app/services/autenti/sender.py` — prepare_send + bg send_to_autenti.
- `backend/app/services/autenti/webhook_verify.py` — JWKS cache + verify_jwt.
- `backend/app/services/autenti/webhook_handler.py` — state machine.
- `backend/app/api/autenti.py` — FastAPI router.
- `backend/app/tasks/autenti_expiry_sweeper.py` — hourly belt-and-braces.
- `backend/alembic/versions/0079_autenti_signatures.py` — schema.
- `frontend/src/components/v2/contract/AutentiEnvelopeCard.tsx` — UI card.
- `frontend/src/components/v2/contract/AutentiSendDialog.tsx` — UI modal.

## Configuration

Required Coolify env vars (per `~/.claude/rules/deployment-runbook.md` §3):

| Variable | Purpose |
|---|---|
| `AUTENTI_ENABLED` | Master kill-switch. Default `false`. Set `true` only after creds provisioned. |
| `AUTENTI_BASE_URL` | REST base. Production: `https://api.autenti.com/api/v2`. Sandbox URL from Autenti sales. |
| `AUTENTI_OAUTH_URL` | Token endpoint. Production: `https://api.autenti.com/oauth2/token`. |
| `AUTENTI_CLIENT_ID` | OAuth2 client_credentials grant — provisioned by sales@autenti.com. |
| `AUTENTI_CLIENT_SECRET` | Pair of CLIENT_ID. **Never** commit; rotate via Coolify env vault only. |
| `AUTENTI_OAUTH_SCOPE` | Default `bpa` (sender = organization). Fallback to user-context: change to whatever Autenti returns from the discovery endpoint. |
| `AUTENTI_WEBHOOK_JWKS_URL` | Default `https://autenti.com/developers/keys/webhook.jwks`. |
| `AUTENTI_DEFAULT_SIGNATURE_TYPE` | `SES` / `AdES` / `QES`. Default `SES`. |
| `AUTENTI_WEBHOOK_IAT_MAX_AGE_HOURS` | Replay protection window. Default 24. |
| `AUTENTI_SWEEPER_INTERVAL_SECONDS` | Background loop cadence. Default 3600 (1h). Clamped to ≥300. |

Webhook URL to register in Autenti's admin: `https://api.nexus.dynaminds.pl/api/autenti/webhook`.

## Operating playbook

### Sending a contract for signature

1. Recruiter opens the candidate's profile, "Umowa" tab.
2. Active contract card shows the **Podpisy elektroniczne (Autenti)** section.
3. Click "Wyślij do podpisu" → choose signature type, expiration, optional message.
4. The backend returns 202; UI polls and the row appears in `status=sent` within ~5s.
5. Autenti emails the candidate; the candidate signs in Autenti's portal.
6. Webhook flips status to `completed`; signed PDF appears in Documents list.

### Withdrawing or reminding

In the row card:
- **Wycofaj** — calls Autenti withdraw action; status → `withdrawn`.
- **Przypomnij** — sends reminder email through Autenti. Throttled at 1/hour per signature.
- **Wyślij ponownie** — visible only on `failed` rows. Opens the send dialog to create a new row (no automatic retry on the failed row).

### Health check

`GET /api/autenti/health` (auth required) returns:
```json
{"enabled": true, "has_credentials": true, "jwks_cache_age_seconds": 1234}
```

Empty `has_credentials` ⇒ env vars not propagated (check Coolify vault). High `jwks_cache_age_seconds` ⇒ JWKS endpoint failure; Sentry alert should already be firing.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `POST /send` returns 503 | `AUTENTI_ENABLED=false` | Toggle to `true` in Coolify env, force redeploy. |
| `POST /send` returns 422 with `candidate.email` | Candidate has no email | Edit candidate profile; resend. |
| `POST /send` returns 422 with `candidate.phone` (for AdES) | Phone missing for SMS verification | Either add phone or downgrade to SES. |
| `POST /send` returns 409 "no finalized snapshot" | Draft was never finalized | Open the draft, click Finalizuj, then Wyślij do podpisu. |
| Status stays at `sending` for >1 minute | Background task crashed | Check logs (`coolify logs nexus`), expect Sentry event. Manually flip `status=failed` if stuck. |
| Status flips to `failed` immediately | API credentials wrong, scope missing, or upstream HTTP error | `last_error` column has the upstream message. Verify creds with `curl /oauth2/token`. |
| Webhook returns 401 with "Unknown JWT kid" | Autenti rotated keys; cache stale | Sweeper should self-heal (force refresh on unknown kid); if not, restart container. |
| Status `completed` but `signed_document_id IS NULL` | Download retried 3× and failed | Check logs for the AutentiError. Manually call `GET /api/autenti/health` to confirm creds. |
| Throttle 429 on remind | Spam guard kicked in | Wait 1 hour or look at `Activity(action=signature_remind_sent)` rows. |

## Forensics

Every webhook payload is persisted in `document_signature_events` with the full JWT payload (`payload` JSONB column). Replay-safe: `event_id` is uniquely indexed.

To trace what happened to a signature:
```sql
SELECT
  ds.id, ds.status, ds.last_error, ds.autenti_process_id,
  ev.event_type, ev.status, ev.received_at, ev.processed_at
FROM document_signatures ds
LEFT JOIN document_signature_events ev ON ev.signature_id = ds.id
WHERE ds.id = <id>
ORDER BY ev.received_at;
```

`Activity` rows for `external_source = 'autenti'` contain a parallel audit trail keyed to the contract.

## Out of scope (Phase 6+)

- Multi-signer (client B2BNet co-signs)
- Per-user OAuth (authorization_code grant) — currently uses one master client_credentials
- Templates Autenti-side (currently send raw rendered HTML/PDF every time)
- Auto-advance recruitment stage on `signature_signed`
- Bulk send
- Mirror signed PDF to M365 OneDrive
- 30-day dunning notification on unsigned contracts
- e-Doręczenia (ADE) integration
- BROKER ID (Autenti KYC) before signing
