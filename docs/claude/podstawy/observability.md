# Observability

Zobacz `~/.claude/rules/observability.md` dla pełnego standardu (Sentry + Grafana Cloud + Cloudflare). Per-NEXUS odstępstwa:

- **Sentry projekty:** `nexus-be` (FastAPI 0.115 + Python 3.12) + `nexus-fe` (Next.js 15 + React 19) — osobne projekty bo dwa stacki w jednym monorepo.
- **Backend SDK:** `sentry-sdk[fastapi]>=2.20.0` z `AsyncioIntegration` (dla 14 background tasks w lifespan: calendar reminder, match TTL, slack SLA, contract alerts, competition autofreeze, cc centroid sync, ...) + `LoggingIntegration` (auto-bridge `logger.error` → Sentry breadcrumb/event) + `FastApiIntegration(transaction_style="endpoint")`. JSON logger już skonfigurowany przez `python-json-logger` w `app/core/logging_config.py`.
- **Frontend SDK:** `@sentry/nextjs ^9` (nie ^8 jak Compass — Next 15 + React 19 wymaga nowszej wersji). `error.tsx` dodany w PR #109 (App Router error boundary, dotąd brak).
- **Replay privacy:** `maskAllText: true, blockAllMedia: true` — NEXUS trzyma dane kandydatów (RODO ATS).
- **Compose `logging:`** — `json-file 10MB×5 + tag` na 4 services (postgres, qdrant, backend, frontend) przez YAML anchor (`x-logging`).
- **Alloy sidecar:** profile-gated (`profiles: [observability]`). Bez `COMPOSE_PROFILES=observability` w Coolify nie startuje. Po dodaniu Grafana creds → `{app="nexus"}` zwraca logi z 4 services + structured fields (FastAPI JSON logging od PR #108).
- **Cloudflare:** `api.nexus.dynaminds.pl` — proxy ON, Full strict TLS, OWASP CRS PL2, rate limit `/api/auth/*` 10 req/min/IP. Backend ma już `slowapi` rate limiter — Cloudflare to pierwsza linia, slowapi druga.
