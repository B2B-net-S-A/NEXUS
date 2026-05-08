---
description: Lista 15 background tasks NEXUS lifespan (z app/main.py:230-246)
allowed-tools: Bash(curl:*), Bash(jq:*), Bash(source:*)
---

NEXUS uruchamia 15 background tasks w `lifespan()` (`backend/app/main.py:230-246`):

| # | Task | Plik | Częstość | Cel |
|---|---|---|---|---|
| 1 | `calendar_reminder` | `app/tasks/calendar_reminder.py` | every 60s | Powiadomienia o nadchodzących interview-ach |
| 2 | `match_history_ttl` | `app/tasks/match_history_ttl.py` | every 1h | Czyszczenie starych match scoring snapshots |
| 3 | `slack_sla_alerts` | `app/tasks/slack_sla.py` | every 5min | Alerty Slack gdy kandydat utknął w stage > SLA |
| 4 | `contract_alerts` | `app/tasks/contract_alerts.py` | daily 06:00 | Powiadomienia o wygasających kontraktach (30/14/7 dni) |
| 5 | `fx_refresh` | `app/services/fx_service.py` | daily 03:00 | Refresh kursów walut (NBP/ECB) dla rate cards |
| 6 | `competition_autofreeze` | `app/tasks/competition_autofreeze.py` | every 15min | Auto-freeze Liga Mistrzów po końcu kwartału |
| 7 | `cc_centroid_sync` | `app/tasks/cc_centroid_sync.py` | every 30min | Recompute Competence Category centroids (5 CC) |
| 8 | `kpi_coach_nudger` | `app/tasks/kpi_coach_nudger.py` | every 10min | KPI coach push notifications dla rekruterów |
| 9 | `notification_triggers` | `app/tasks/triggers_loop.py` | every 30s | Stage transition rules → in-app + email |
| 10 | `rejection_email` | `app/tasks/rejection_email_loop.py` | every 5min | Wysyłka odrzuceń kandydatów (configurable templates) |
| 11 | `linkedin_sync` | `app/tasks/linkedin_sync.py` | every 1h | Sync LinkedIn message threads do candidate notes |
| 12 | `microsoft365_sync` | `app/tasks/microsoft365_sync.py` | every 15min | Sync M365 calendar (events + reminders) |
| 13 | `marketplace_sweeper` | `app/tasks/marketplace_sweeper.py` | every 30min | Sweep ofert z Pracuj/JJIT/etc. (read-only via n8n) |
| 14 | `chat_email_fallback` | `app/tasks/chat_email_fallback.py` | every 2min | Fallback email gdy Slack webhook fails |
| 15 | `autenti_sweeper` | `app/tasks/autenti_expiry_sweeper.py` | every 1h | Sweeper umów Autenti expiry status (kill-switch via AUTENTI_ENABLED) |

## Verify all running

Get count from `/api/admin/snapshot` (Phase 2):

```bash
source ~/.claude/secrets/dynaminds-tokens.env
curl -fsSL -H "X-Snapshot-Token: ${NEXUS_SNAPSHOT_TOKEN}" \
  "https://api.nexus.dynaminds.pl/api/admin/snapshot" | \
  jq '.background_tasks'
```

Expect: `{"running": 15, "expected": 15, "tasks": [...]}`.

## Diagnose: which task crashed?

If `running < expected`, find the task in logs:

```bash
ssh root@91.99.199.112 "docker logs backend --tail 1000" | \
  grep -E "Task.*failed|asyncio.exceptions|Traceback" | head -20
```

Common failure modes:
- **DB pool exhausted** → all tasks slow down, eventual restart. Mitigation: tune `pool_size` w `app/core/database.py`.
- **External API timeout** (M365, LinkedIn, Voyage) → task retries exponentially. Check Sentry.
- **Schema migration mismatch** → task references column that doesn't exist after rollback. Fix: `alembic upgrade head` lub rollback całości.

## When to add new task

If you add a new background loop to `app/main.py:lifespan()`, also:
1. Update this list (15 → 16, add row)
2. Update `app.state._running_tasks` registry (Phase 2 introspection)
3. Verify `/api/admin/snapshot.background_tasks.expected` reflects new count
