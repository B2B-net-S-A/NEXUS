# Sentry alert rules — runbook (NEXUS prod)

> Setup ~15 min w Sentry UI (https://b2bnet-sa.sentry.io/alerts/rules/).
> Każda rule = early detection dla incident-class problemu. Po wdrożeniu
> kolejny "notifications runaway 137M rows" (2026-05-22, 4 dni od incident
> do detection) zostanie wykryty w 5 minut.

## Prerekwizyt: Slack webhook

1. Sentry → Settings → Integrations → **Slack** → Add Workspace
2. Wybierz Slack workspace (b2bnet.pl) → Authorize
3. Skonfiguruj default channel `#nexus-alerts` (lub utwórz jeśli brak)

Bez tego alerty pójdą tylko na email — Slack widoczność = szybciej.

## Rule 1: 🚨 Notifications insert rate >10k/h (P1 incident)

**Problem**: 2026-05-22 incident — 137M rows w `notifications` table przez
4 dni bo `dl_stage_stale_6h` fan-out 164k/dzień + brak `ix_notif_dedup_daily`
index. Po 45GB DiskFull DB padło na 2h.

**Detection**: liczba `Notification` INSERTs / 1h powinna być <1000 normalnie
(per memory `[[project_notifications_runaway_incident]]` 2026-05-27 stan
to 963/24h, dominuje `dl_stage_stale_6h` 67%). Spike powyżej 10k/h = anomaly.

**Setup w Sentry UI**:
- Navigate: Alerts → Create Alert → **Metric Alert**
- Project: `nexus-be`
- Dataset: `transactions`
- Metric: `count_unique(span)` (lub custom Loki query do PG INSERT count)
- Filter: `transaction:emit_notification OR span.op:db.insert table:notifications`
- Trigger: **Critical** when `>10000 in 1h`
- Action: Slack `#nexus-alerts` + email Artur
- Frequency: every 5 minutes

**Alternative (preferred)**: Grafana Loki alert na `{app="nexus"} |= "Notification(id="`
count >10000 w 1h — to lepsze bo widzi log line, nie sample (Sentry sampluje 10%).

## Rule 2: 🔐 Auth failure burst >50/min (P2 possible attack)

**Problem**: Brute-force / credential stuffing na `/api/auth/login` lub MS SSO
callback failures (np. AAD GroupMember.Read.All consent withdrawn). Bez alertu
możemy mieć account takeover lub broken SSO przez tygodnie.

**Setup**:
- Alerts → Create Alert → **Issue Alert**
- Project: `nexus-be`
- Conditions: `level:error AND (message:"Could not validate credentials" OR culprit:auth_microsoft.*)`
- Trigger: **Warning** when 50+ events in 1 minute
- Action: Slack `#nexus-alerts`

## Rule 3: 💥 5xx error spike >100/h per endpoint (P1)

**Problem**: Pre-2026-05-27 sesja QA — 4 bugs w prod (NEXUS-BE-1N/V/8/D) z
łącznie ~420 unhandled 5xx events / 7d. Każdy z nich indywidualnie >50 events
nie był eskalowany. Z alert rule wykrycie w 1h zamiast 7 dni.

**Setup**:
- Alerts → Create Alert → **Metric Alert**
- Project: `nexus-be`
- Dataset: `errors`
- Metric: `count()`
- Filter: `level:error AND event.type:error`
- Group by: `transaction` (per endpoint)
- Trigger: **Critical** when ANY transaction >100 events in 1h
- Action: Slack `#nexus-alerts` + create Linear issue (jeśli używasz integration)

## Rule 4: 📁 M365 attachment PermissionError (silent failure detection)

**Problem**: 2026-05-25 NEXUS-BE-D — `/tmp/nexus/uploads/microsoft365` brak
write permission, M365 sync loop quietly failed dla **303 events ongoing 11 dni**.
Brak alertu = brak detection.

**Setup**:
- Alerts → Create Alert → **Issue Alert**
- Project: `nexus-be`
- Conditions: `culprit:app.services.m365.* AND (message:"Permission denied" OR message:"FileNotFoundError")`
- Trigger: **Warning** when any new issue or 10+ events / 1h
- Action: Slack `#nexus-alerts`

**Bonus**: dodać podobną rule dla `culprit:app.services.autenti.*` (jeśli/gdy
Autenti aktywowany — obecnie `AUTENTI_ENABLED=false`) i CloudTalk po
aktywacji `[[project_cloudtalk_integration]]`.

## Rule 5: 🐘 SQLAlchemy QueuePool exhausted (cascade prevention)

**Problem**: 2026-05-22 cascade — NEXUS-BE-1B/1C/1D/1F = 1232 events
"QueuePool limit of size 10 overflow 20 reached, timeout 30.00" w trakcie
DiskFull incident. Pool exhausted → backend nieresponsywny → cascade failures.

**Setup**:
- Alerts → Create Alert → **Issue Alert**
- Project: `nexus-be`
- Conditions: `message:"QueuePool limit" OR message:"connection timed out, timeout 30"`
- Trigger: **Critical** when 10+ events in 5 minutes
- Action: Slack `#nexus-alerts` + page on-call

**Również rozważyć follow-up fix**: bump SQLAlchemy `pool_size=15` + `max_overflow=30`
(per spawn task chip "SQLAlchemy pool bump 30→60"). To prevention, alert = detection.

## Rule 6: 🔍 New issue fired (any project)

**Problem**: Niektóre bugi pojawiają się i znikają cicho (rzadkie edge case).
Bez "any new issue" rule można je przegapić.

**Setup**:
- Alerts → Create Alert → **Issue Alert**
- Project: `nexus-be` + `nexus-fe`
- Conditions: `is:new`
- Trigger: Warning na każdy first occurrence
- Action: Slack `#nexus-alerts` (low-priority channel)
- Throttle: 1 alert per issue per 24h (uniknij spam)

## Weryfikacja po setup

Po skonfigurowaniu 6 rules:
1. Sentry → Alerts → Rules → sprawdź że 6 rules aktywnych
2. Test trigger (opcjonalnie):
   - W Coolify Terminal: `python -c "import sentry_sdk; sentry_sdk.capture_exception(RuntimeError('test alert'))"`
   - Expect: Slack notification w `#nexus-alerts` w ~30s
3. Update `[[reference_infrastructure]]` memory z nowym Slack channel + rules count

## Out-of-scope (przyszłe sesje)

- **Grafana alert rules** dla Loki/Prometheus — analogiczne ale w Grafana Cloud
  (auth: dashboard ma już API token zalogowany). 5 rules: log_error_rate,
  notification_growth_per_second, p99_request_duration, http_5xx_per_endpoint,
  container_oom_killed.
- **PagerDuty integration** — jak Slack za mało eskalacji dla P0.
- **Sentry release tracking notification** — auto-Slack po każdym deploy z
  release SHA + summary changes.

## Spawn task chip dla wdrożenia

Jeśli wolisz delegować to junior dev: spawn task chip "Setup Sentry alert
rules per docs/sentry-alerts-runbook.md" — 15 min UI work + 1 PR z dokumentacją
że zrobione.
