# Observability

Zobacz `~/.claude/rules/observability.md` dla pełnego standardu (Sentry + Grafana Cloud + Cloudflare). Per-NEXUS odstępstwa:

- **Sentry projekty:** `nexus-be` (FastAPI 0.115 + Python 3.12) + `nexus-fe` (Next.js 15 + React 19) — osobne projekty bo dwa stacki w jednym monorepo.
- **Backend SDK:** `sentry-sdk[fastapi]>=2.20.0` z `AsyncioIntegration` (dla 14 background tasks w lifespan: calendar reminder, match TTL, slack SLA, contract alerts, competition autofreeze, cc centroid sync, ...) + `LoggingIntegration` (auto-bridge `logger.error` → Sentry breadcrumb/event) + `FastApiIntegration(transaction_style="endpoint")`. JSON logger już skonfigurowany przez `python-json-logger` w `app/core/logging_config.py`.
- **Frontend SDK:** `@sentry/nextjs ^9` (nie ^8 jak Compass — Next 15 + React 19 wymaga nowszej wersji). `error.tsx` dodany w PR #109 (App Router error boundary, dotąd brak).
- **Ślad przeglądarka → API od pierwszego żądania strony (24.11.2026).** `tracePropagationTargets` to origin z `NEXT_PUBLIC_API_URL` od startu (`lib/telemetry-capability.ts`), nie po sondzie `/api/health/live`. Z celem po sondzie 26 z 37 pierwszych żądań pulpitu szło bez `sentry-trace` (backend próbkował je sam, 10%), a sonda nieudana w zastoju backendu zostawiała kartę bez propagacji na minuty: ponawia ją tylko żądanie axios po minucie, a pulpit odpytuje co 5 min. Sonda bramkuje już tylko `X-Operation-Id` i licznik użycia. Warunek: `sentry-trace` i `baggage` w `allow_headers` CORS (strażnik `tests/test_sentry_traces_sampler.py`), bo bez nich każde żądanie API kończy się „Network Error”.
- **Replay privacy:** `maskAllText: true, blockAllMedia: true` — NEXUS trzyma dane kandydatów (RODO ATS).
- **Compose `logging:`** — `json-file 10MB×5 + tag` na 4 services (postgres, qdrant, backend, frontend) przez YAML anchor (`x-logging`).
- **Alloy sidecar:** profile-gated (`profiles: [observability]`). Bez `COMPOSE_PROFILES=observability` w Coolify nie startuje. Po dodaniu Grafana creds → `{app="nexus"}` zwraca logi z 4 services + structured fields (FastAPI JSON logging od PR #108).
- **Cloudflare:** `api.nexus.dynaminds.pl` — proxy ON, Full strict TLS, OWASP CRS PL2, rate limit `/api/auth/*` 10 req/min/IP. Backend ma już `slowapi` rate limiter — Cloudflare to pierwsza linia, slowapi druga.
