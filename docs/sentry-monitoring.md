# Sentry daily monitoring — runbook

> Durable replacement for the session-only Claude `CronCreate` cron
> `393ccf85` (auto-expired after 7 days). Migrated to GitHub Actions
> 2026-05-27 so monitoring survives across Claude sessions and machine restarts.
>
> Companion doc: [sentry-alerts-runbook.md](sentry-alerts-runbook.md) — the
> real-time alert rules. This runbook is the **daily digest** that catches
> trends Sentry's per-rule alerts miss (e.g., growing-but-not-spiking errors).

## What it does

GitHub Actions workflow [.github/workflows/sentry-daily-monitor.yml](../.github/workflows/sentry-daily-monitor.yml)
runs every day at **06:47 UTC** (07:47 / 08:47 Warsaw, off-the-hour to dodge
the cron stampede). For each NEXUS Sentry project (`nexus-be`, `nexus-fe`)
it queries:

- **Top 5 unresolved** issues from the last 24h, sorted by frequency.
- **Top 5 new** issues seen for the first time in the last 24h.

The combined digest is posted to Slack `#nexus-alerts` via incoming webhook.

## One-time setup

### 1. Sentry auth token

1. Open <https://b2bnet-sa.sentry.io/settings/account/api/auth-tokens/>
2. **Create New Token** with these scopes:
   - `project:read`
   - `event:read`
3. Copy the token (`sntrys_...`) — it is shown only once.
4. Store as GH repo secret:

   ```bash
   gh secret set SENTRY_AUTH_TOKEN --repo artur-t-96/Nexus --body "sntrys_..."
   ```

Rotate yearly or whenever the token may have been exposed.

### 2. Slack incoming webhook

Either reuse the existing `#nexus-alerts` webhook (created during the Sentry
alert-rules setup — see [sentry-alerts-runbook.md](sentry-alerts-runbook.md))
or create a dedicated one:

1. Slack → **Apps** → Browse → **Incoming Webhooks** → Add to Slack
2. Choose channel: `#nexus-alerts`
3. Copy the webhook URL (`https://hooks.slack.com/services/T.../B.../...`)
4. Store as GH repo secret:

   ```bash
   gh secret set SLACK_WEBHOOK_URL --repo artur-t-96/Nexus --body "https://hooks.slack.com/services/..."
   ```

Without `SLACK_WEBHOOK_URL` the workflow runs in **dry-run mode**: the
digest is printed to the Actions log, no Slack post. Useful while testing.

### 3. Verify

Trigger a manual run:

```bash
gh workflow run sentry-daily-monitor.yml --repo artur-t-96/Nexus
gh run list --workflow sentry-daily-monitor.yml --repo artur-t-96/Nexus --limit 1
```

Expected:

- Run completes within ~30s.
- Slack `#nexus-alerts` shows the digest.
- If the secret check fails the run emits `::warning::` instead of failing
  red (so the daily schedule doesn't spam the inbox before secrets exist).

## Modifying the digest

The workflow is a thin wrapper around
[.github/scripts/sentry_daily_digest.py](../.github/scripts/sentry_daily_digest.py).
The script uses **stdlib only** (no `pip install`) — `urllib.request` for
Sentry + Slack, `json` for payloads.

Common tweaks:

| Change | Where |
|---|---|
| Add another Sentry project | `SENTRY_PROJECTS` env in workflow yaml |
| Change schedule | `cron:` line in workflow yaml |
| Change channel | Update `SLACK_WEBHOOK_URL` secret (channel is baked into webhook URL) |
| Change top-N | `TOP_N` env in workflow yaml |
| Add severity filtering | Edit `fetch_issues` `query=` in script |

Local dry-run:

```bash
export SENTRY_AUTH_TOKEN="sntrys_..."
export DRY_RUN=1
python3 .github/scripts/sentry_daily_digest.py
```

## Troubleshooting

### Workflow runs but Slack stays silent

1. Check `gh run view <run-id> --log` — the digest is also printed to stdout.
2. Verify `SLACK_WEBHOOK_URL` is set: `gh secret list --repo artur-t-96/Nexus`
3. POST manually with the webhook URL:

   ```bash
   curl -X POST -H "Content-Type: application/json" \
     --data '{"text":"webhook test from CLI"}' \
     "$SLACK_WEBHOOK_URL"
   ```

   If this 404s the webhook is revoked — recreate per setup §2.

### `401 Unauthorized` from Sentry

Token expired or has wrong scopes. Re-create with `project:read` +
`event:read` and update the GH secret.

### `403 Forbidden` from Sentry

Token belongs to a user removed from the b2bnet-sa org, or token scope
missing. Create a new token from the current admin account.

### Empty digest (no issues + no errors) every day

Either NEXUS is genuinely quiet (✅) or the Sentry query is wrong. Test in
the Sentry UI: <https://b2bnet-sa.sentry.io/issues/?project=nexus-be&query=is%3Aunresolved&statsPeriod=24h>.
The script uses the same query string.

## Why GH Actions, not Sentry's native digest?

Sentry does have a built-in weekly digest, but:

- It's **weekly**, not daily — too coarse for "what's burning right now."
- It can't combine `nexus-be` + `nexus-fe` into one Slack message — they
  arrive as separate emails.
- It doesn't show the same `is:new last 24h` cohort that we want to surface.

GH Actions cron also gives us **same place to look** as deploys / uptime
probe / backup drills, which is the standard ops surface for this repo
(see [deployment.md](https://github.com/artur-t-96/Nexus/blob/main/.github/workflows/deploy.yml)).

## See also

- [sentry-alerts-runbook.md](sentry-alerts-runbook.md) — 6 real-time alert rules
- [qa-process-runbook.md](qa-process-runbook.md) — Sentry-first QA pattern
- `~/.claude/rules/observability.md` — full Sentry + Grafana + Cloudflare standard
