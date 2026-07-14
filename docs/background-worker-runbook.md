# NEXUS singleton background worker

## Why this exists

The FastAPI lifespan previously started 23 periodic loops. Every additional web
replica therefore created another scheduler. The `worker` Compose service is now
the exclusive owner; `app/main.py` starts zero periodic loops.

The complete registry is grouped below. Optional loops are omitted from the
active task set when their existing feature switch is off.

| Group | Loops |
|---|---|
| Core maintenance | `calendar_reminder`, `match_history_ttl`, `contract_alerts`, `fx_refresh`, `competition_autofreeze`, `kpi_coach_nudger`, `notification_triggers`, `rejection_email`, `saved_search_alerts`, `chat_email_fallback`, `dl_portal_expiry` |
| Search/indexing | `cc_centroid_sync`, `marketplace_sweeper` |
| Microsoft 365 | `microsoft365_sync`, `m365_rematch`, `m365_webhook_renewal`, `m365_recording_discovery` |
| External integrations | `slack_sla_alerts`, `linkedin_sync`, `autenti_sweeper`, `signing_sweeper`, `cloudtalk_sync`, `traffit_sync` |

## Singleton and fencing contract

1. A worker opens one PostgreSQL session and acquires the namespaced session
   advisory lock.
2. The lock holder increments `fencing_token` in
   `background_worker_heartbeats` before it starts any loop.
3. Every heartbeat update requires the same `instance_id` and `fencing_token`.
   A stale process cannot overwrite a newer leader's state.
4. The heartbeat uses the lock-owning connection. A broken session stops
   heartbeat updates, releases the lock in PostgreSQL and causes the leadership
   term to cancel all loop tasks.
5. The API validates freshness, exact release SHA, fencing token, running count
   and the active task-name set. Any mismatch makes `/api/health` return 503.

The global lock prevents concurrent scheduler ownership. Existing database
constraints and idempotency keys remain the final protection for individual
side effects; future loop changes must preserve those contracts.

## Safe staging rollout

`BACKGROUND_WORKER_ENABLED=false` is the repository and Compose default. In
this state:

- the worker process stays alive but executes no loops;
- web processes also execute no loops;
- readiness reports `background_worker` as critical/unhealthy with
  `state=disabled`, so a paused required scheduler can never be false green.

To test on staging:

1. Deploy the exact SHA with the switch still false. Container liveness may be
   green, but `/api/health` must return 503 until the worker is enabled.
2. Confirm Alembic has exactly one head and migration
   `0163_background_worker_heartbeat` is applied.
3. Set `BACKGROUND_WORKER_ENABLED=true` only on staging and restart the worker
   and backend services; only then may the release readiness gate continue.
4. Require three consecutive `/api/health` responses with a healthy
   `background_worker` check and the same exact SHA.
5. Verify `/api/admin/snapshot`: `background_tasks.expected == 0`, while
   `background_worker.running_tasks == background_worker.expected_tasks`.
6. Scale `worker` to two replicas temporarily. Only one fencing token may be
   active and health must remain green. Scale back to one.
7. Exercise one idempotent job from each enabled group and inspect audit logs.

Do not enable the worker on production until this staging drill is recorded.

## Kill switch and rollback

The immediate kill switch is `BACKGROUND_WORKER_ENABLED=false` followed by a
restart of worker and backend. It intentionally pauses periodic work; it does
not move loops back into the web process. This avoids reintroducing duplicate
side effects while diagnosing an incident.

The schema migration is additive and forward-only. Code rollback can leave the
heartbeat table in place. A previous image is safe only if its web scheduler
behaviour is understood and the production replica count is one; otherwise use
the new image with the kill switch off while preparing a corrected release.
