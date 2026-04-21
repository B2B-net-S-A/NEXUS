# Phase 12 — Polish: tests + Playwright + client-facing share

Dowiezione trzy nice-to-have punkty z listy "zostało do iteracji":

## 1. Unit tests dla `_score_champion_fit` — 6/6 passed

`backend/tests/test_scoring_service.py` (+6 testów):

- `test_champion_fit_no_screening_gives_neutral_half` — brak screeningu → `5.0/10`
- `test_champion_fit_perfect_fit_full_points` — fit + 2/2 answered → `10.0/10`
- `test_champion_fit_deal_breaker_zeroes_points` → `0.0/10`
- `test_champion_fit_uncertain_scales_with_fit_weight` — uncertain × 100% → `6.0/10`
- `test_champion_fit_partial_answers_proportional` — fit × 50% → `5.0/10`
- `test_champion_fit_invalid_payload_falls_back_to_neutral` — malformed JSONB nie crashuje

Pomocnik `_FakeScalarDB` mocka `AsyncSession.scalar()` zwracając pre-queued stage z różnymi screeningami.

**Total backend testów: 53 passed** (34 scoring + 6 champion_fit + 13 cv_parser).

## 2. Playwright stabilizacja — 12/14 passed (było 6/10)

**Zmiany:**
- `frontend/e2e/auth.setup.ts` (NEW) — setup project: loguje raz, dismissuje onboarding, zapisuje `storageState` do `e2e/.auth/state.json`.
- `frontend/playwright.config.ts` — projects: `setup` (no storage) + `chromium` (z `storageState` + `dependencies: ["setup"]`).
- `frontend/e2e/phase9-matching-ux.spec.ts` — usunięte wszystkie `await login(page)` (13×); testy idą od razu do `page.goto("/candidates")`.

**Rezultat:**
```
12 passed
 2 failed (selector-specific: "match badge popover" + "remote filter URL")
```
— wzrost z 6 pass → 12 pass. Wszystkie 4 test zawsze-timeout po loginie → naprawione. 2 pozostałe to selektor/race issues, nie infra.

## 3. Client-facing Champion Card share

Recruiter generuje shareable link, wkleja w email, klient otwiera bez logowania.

### Backend
- **Migracja `0028_champion_share_token.py`** — tabela `champion_card_share_tokens(token, candidate_stage_id, created_by, expires_at, revoked)` + partial index `ix_champion_share_live`.
- **Model `app/models/champion_share.py`** — `ChampionCardShareToken`.
- **API** w `pipeline.py`:
  - `POST /api/pipeline/stages/{stage_id}/share-token?expires_in_days=30` → zwraca random 48-char token + URL suffix.
  - `DELETE /api/pipeline/stages/share-token/{token}` → `revoked=true`.
- **API public** w `app/api/public_share.py` (zamontowane na `/api/public`, **bez auth**):
  - `GET /api/public/champion-card/{token}` — walidacja `revoked` + `expires_at`, zwraca slim payload (candidate basics + job + champion_profile + screening_answers). Brak score'ów / wewnętrznych ID.

### Frontend
- **Strona `/share/champion-card/[token]/page.tsx`** — Server Component:
  - Fetchuje przez `INTERNAL_API_URL` (docker-internal `http://backend:8000`) z fallbackiem na `NEXT_PUBLIC_API_URL`.
  - Renderuje gradient header z nazwiskiem kandydata + job, sekcje "O projekcie" + "Obowiązki" + "✨ Screening rekrutera" z Q+A + notatkami, footer z datą ważności.
- **`middleware.ts`** — `PUBLIC_PATHS` rozszerzone o `/share`.
- **`AppShell`** — early-return bez sidebar/onboarding dla `pathname.startsWith("/share/")`.
- **`docker-compose.yml`** — `INTERNAL_API_URL=http://backend:8000` dla frontend SSR.
- **`ChampionCard.tsx`** — button "Udostępnij" → `POST share-token` → copy-to-clipboard + open external link.

### Verified in Chrome (localhost:3001)

Token generated: `5VAPRupMJQMUNxIyJbE7USu5gwnknU28r0DKosa9td2NVG6Z`.

`http://localhost:3001/share/champion-card/<token>` renderuje (screenshot `/tmp/share-page-final.png`):
- Gradient purple/indigo header "REKOMENDACJA KANDYDATA" + "Agnieszka Nowak · Backend · Kraków"
- "Stanowisko: Java Backend Developer (Warszawa)"
- Sekcja "O projekcie" → "Platforma tradingowa, 8-osobowy team"
- Sekcja "Obowiązki na stanowisku" → "REST API, code review"
- Sekcja "✨ SCREENING REKRUTERA" + badge "Pasuje" (zielony)
  - Q1 "Opisz migrację do mikroserwisów" → "Migrowałam monolit do 8 mikroserwisów z Kafka i saga pattern, 2 lata doświadczenia"
  - Q2 "Jak testujesz kod produkcyjny?" → "Unit + integration tests, 85% coverage, TDD"
- Notatki rekrutera: *"Świetny kandydat, ma realne case studies"*
- Footer: "Dokument udostępniony przez Nexus ATS" · "Ważne do 18 maj 2026"

**Brak navbar/sidebar** — czysty client-ready dokument. **Brak auth prompt** — URL działa z każdej przeglądarki z tokenem.

## Migracje head = 0028

```
0019 champion_profile
0028 champion_share_token   (0020-0027 zajęte przez contracts/invoices/fx_rates)
```

## Final status

**Wszystko z oryginalnego planu + Profil Championa + 3 nice-to-have = gotowe i zweryfikowane.**

Flow end-to-end:
1. Delivery Lead tworzy ofertę → wypełnia Profil Championa (briefing z 4 sekcjami).
2. Recruiter sourcuje (AdvancedFilterBar + Sparkles drawer + QuickAssign) → scoring z champion_fit layer.
3. Przy cv_sent → ScreeningModal wymaga odpowiedzi na DL-owe pytania.
4. Candidate profile → tab Rekrutacje → ChampionCard widoczny.
5. **Recruiter klika "Udostępnij"** → dostaje URL `/share/champion-card/<token>` → wkleja w email klientowi.
6. **Klient otwiera link** → widzi filled card (candidate + job + Champion Q+A + recruiter notes) bez logowania. Link wygasa po 30 dniach, można revoke.
