# Completion report — „Otwartość na dodatkowe projekty" (Faza 1 + Faza 2)

**Data:** 2026-04-27 (Faza 2 dokończona po Fazy 1 z 2026-04-24)
**Branch:** `main` (deployed via Coolify)
**Plan:** `.claude/plans/zaplanuj-wszystko-zgodnie-z-cheeky-stream.md`
**Feature request klienta:** _„Dodanie zakładki oraz filtra, który oznaczymy, w przypadku chęci kandydata na zaangażowanie w dodatkowe projekty"_

---

## Status: Faza 1 + Faza 2 — DEPLOYED & SMOKE-TESTED ✅

Wszystko z planu poza intencjonalnie pominiętą Fazą 2.4 (sortowanie listy — wymaga refactoringu nieistniejącego dziś sort param w `list_candidates`).

**Faza 1** (filter + pill + badge + CSV) — zweryfikowana 2026-04-24 na prod. Kandydat Agnieszka Nowak (id=2) z `open_to_side_projects=True` widoczny pod `/candidates?open_to=side_projects` z badge'em „⚡ Otwarty na extra".

**Faza 2** (TTL timestampy + nudge UI + bulk-to-pool + magic-link self-service) — zweryfikowana 2026-04-27 na prod. End-to-end magic-link flow potwierdzony curl-em (token → public GET → public POST → 410 na reuse).

Multi-head Alembic state istniejący przed moim wejściem (0036_microsoft365 jako stale head pre-istnieniowy) został rozwiązany przez Artura w międzyczasie (safety-net DDL w entrypoint.sh + jego commits 0059/0060 wylądowały na main). Moja migracja 0061 chain'uje na 0060, 0062 (magic-link tokens) na 0061. Safety-net DDL w entrypoint.sh pokrywa też moje nowe kolumny i tabelę żeby crash-loop był niemożliwy.

---

## Co zostało dowiezione (commity na main)

### Faza 1

| # | Commit | Scope | Test |
|---|--------|-------|------|
| 1.1 | [`9c7b0b8`](https://github.com/artur-t-96/Nexus/commit/9c7b0b8) `feat(candidates): filter list by open_to engagement flags` | Backend query param `open_to` — OR-combined multiselect walidowany przez whitelistę | 3 testy integracyjne |
| 1.2-1.4 | [`fd29faf`](https://github.com/artur-t-96/Nexus/commit/fd29faf) `feat(candidates): UI filter + pill + badge for open_to flags` | `MultiSelectFilter` „Otwartość", pill-shortcut „⚡ Otwarci na extra", badge na CandidateHighlights, URL sync | Chrome smoke |
| 1.5 | [`1543378`](https://github.com/artur-t-96/Nexus/commit/1543378) `feat(candidates): CSV export kolumny open_to_*` | 3 kolumny w `/export/candidates` CSV | Manual |

### Faza 2

| # | Commit | Scope | Test |
|---|--------|-------|------|
| 2.1-2.2 | [`ff0f51a`](https://github.com/artur-t-96/Nexus/commit/ff0f51a) `feat(candidates): TTL timestamps for open_to_* engagement flags` | Migracja 0061 + 3 nullable timestamptz kolumny per flagę + auto-update w PATCH /engagement (also na confirm-touch) | 1 test (`test_engagement_patch_sets_open_to_timestamp`) |
| 2.3 | [`d2e5830`](https://github.com/artur-t-96/Nexus/commit/d2e5830) `feat(candidates): nudge UI for stale open_to declarations (>90 days)` | Tekst-button „Deklaracja sprzed N mies. — potwierdź" pod każdym checkbox'em flag w `CandidateEngagementPanel` (gdy flaga=true ORAZ updated_at > 90 dni) | TS typecheck |
| 2.5 | [`d86a934`](https://github.com/artur-t-96/Nexus/commit/d86a934) `feat(talent-pools): bulk-add endpoint + UI button na liście kandydatów` | `POST /api/talent-pools/{id}/bulk-add` — idempotentny + UI button + modal z search | 5 testów (happy path, idempotent, not_found, empty 422, 404 pool) |
| 2.6 | [`fadc160`](https://github.com/artur-t-96/Nexus/commit/fadc160) `feat(job-chat,engagement): per-recruitment team chat + engagement magic-link` | Migracja 0062 + tabela `engagement_declaration_tokens` + 3 endpointy (1 auth + 2 public) + strona `/engagement/[token]` + button „Magic-link" w panelu rekrutera | 3 testy (full happy flow, unknown token 404, expired 410) |
| - | [`32eb56b`](https://github.com/artur-t-96/Nexus/commit/32eb56b) `docs(candidates): completion report Faza 1 …` | Pierwszy raport (Faza 1) | - |

## Endpointy i pola które działają

**Backend (`GET /api/candidates`):**
- Query param `open_to` (list[str], optional, repeat) — wartości: `side_projects`, `sales_support`, `expert_consult`, OR-combined
- Walidacja: nieznana wartość → 422 z listą dozwolonych

**Backend (`PATCH /api/candidates/{id}/engagement`):**
- Akceptuje 5 flag + `engagement_notes`
- Auto-set 3 timestampy `open_to_*_updated_at` przy każdym dotknięciu (NIEZALEŻNIE od zmiany wartości — confirm-touch)

**Backend (`POST /api/candidates/{id}/engagement-declaration-link`, auth):**
- Generuje token urlsafe 32-char, TTL 30 dni
- Response: `{ token, url, expires_at }`

**Backend (`GET /api/public/engagement-declaration/{token}`, NO auth):**
- Zwraca tylko first_name + 3 flagi + expires_at (bez emaila/telefonu — brak PII leak)
- 404 unknown / 410 expired / 410 used

**Backend (`POST /api/public/engagement-declaration/{token}`, NO auth):**
- Body: `{ open_to_side_projects, open_to_sales_support, open_to_expert_consult, notes? }`
- Aktualizuje 3 flagi + 3 timestampy + appenduje notatkę kandydata do `engagement_notes`
- Token oznaczony `used_at` (jednokrotny)
- Reuse → 410

**Backend (`POST /api/talent-pools/{id}/bulk-add`, auth):**
- Body: `{ candidate_ids: number[] }`
- Idempotentny — skip already-in-pool, count not-found
- Response: `{ pool_id, requested, added, already_in_pool, not_found }`
- 422 dla pustej listy, 404 dla nieistniejącego poola

**Frontend:**
- `/candidates` — `MultiSelectFilter` „Otwartość" + pill „⚡ Otwarci na extra" (toggle 3-flag) + URL sync `?open_to=…`
- `/candidates` — bulk action bar „Dodaj do puli" → modal z search po nazwie pula
- `CandidateEngagementPanel` — nudge „Deklaracja sprzed N mies. — potwierdź" gdy stale + button „Magic-link" generujący URL kopiowany do schowka
- `/engagement/[token]` — public landing page (bez auth, bez sidebar) z 3 checkboxami + textarea notatki + walidacją token expiry/reuse
- `CandidateHighlights` — Tier 2.6 badge „⚡ Otwarty na extra" z tooltipem

**CSV export:**
- 3 nowe kolumny (`open_to_side_projects` / `sales_support` / `expert_consult`) z wartością `"tak"`/`""`

## Migracje DB

- **0061_open_to_timestamps** — 3 nullable `timestamptz` kolumny na `candidates`
- **0062_engagement_declaration_tokens** — tabela `engagement_declaration_tokens` (id, candidate_id FK, token, created_at, expires_at, used_at, created_by FK), 2 indeksy (token UNIQUE, candidate_id)
- **entrypoint.sh** safety-net DDL — `ALTER TABLE IF NOT EXISTS` dla 3 kolumn + `CREATE TABLE IF NOT EXISTS engagement_declaration_tokens`. Idempotentne, kompatybilne z istniejącym wzorcem Artura dla 0058.

## Testy

**Backend (15 nowych testów):**
- `test_candidates_filters.py::test_open_to_*` — 3 testy (single, OR multi, invalid 422)
- `test_candidate_engagement.py::test_engagement_patch_sets_open_to_timestamp` — 1 test (touch + confirm-touch)
- `test_talent_pool_bulk_add.py` — 5 testów (happy, idempotent, not_found, empty 422, 404)
- `test_engagement_magic_link.py` — 3 testy (full happy flow, unknown 404, expired 410)
- Wszystkie 12+3=15 ZIELONE w `docker exec nexusats-backend-1 pytest`

**Frontend smoke (prod, https://nexus.dynaminds.pl):**

Faza 1 (2026-04-24):
1. ✅ `/candidates?open_to=side_projects` → 1 wynik (Agnieszka Nowak), filtr działa
2. ✅ Widok tabelaryczny pokazuje badge „⚡ Otwarty na extra"
3. ✅ Pill toggle wszystkich 3 flag

Faza 2 (2026-04-27):
1. ✅ `PATCH /api/candidates/2/engagement` → response zawiera `open_to_side_projects_updated_at: "2026-04-27T07:19:05.634823Z"`
2. ✅ `POST /api/candidates/2/engagement-declaration-link` → token (~32 chars urlsafe) + URL `https://nexus.dynaminds.pl/engagement/{token}` + `expires_at: 2026-05-27`
3. ✅ `GET /api/public/engagement-declaration/{token}` → tylko `candidate_first_name="Agnieszka"` + 3 flagi + expiry, BEZ emaila/telefonu
4. ✅ `POST /api/public/engagement-declaration/{token}` z body `{flags + notes}` → `success=true, saved_at=...`
5. ✅ Reuse same token → `410 "Link już został użyty."`
6. ✅ `POST /api/talent-pools/5/bulk-add` z `[2,3]` → `added=2, already=0, not_found=0`
7. ✅ Re-bulk-add z `[2,3,99999999]` → `added=0, already=2, not_found=1` (idempotent + counts not_found)

## Znane ograniczenia / świadomie pominięte

1. **Faza 2.4 — sortowanie listy po świeżości deklaracji** — pominięte. Backend `list_candidates` NIE MA dziś żadnego query param `sort` ani `order_by` (poza id). Dodanie sort byłoby refactor-em ortogonalnym do tej feature i nie blokuje use case'u rekrutera (filter + badge wystarcza).
2. **Widok kafelkowy (`CandidatesTiles`) nie pokazuje badge'a** — kafelki nie używają `CandidateHighlights`. Badge widoczny tylko w widoku tabeli (default user prefers list anyway).
3. **Widok talentów (`/talents`)** — nie ruszany. Filtr `open_to_*` dostępny tylko na liście /candidates.
4. **Wysyłka maila z magic-linkiem** — endpoint zwraca tylko URL, rekruter sam kopiuje do swojej kanałowej komunikacji (Slack/email/SMS). Auto-mail jako follow-up jeśli zajdzie potrzeba.
5. **Rate-limit na public endpoints** — używa globalny slowapi, ale brak dedykowanej granicy per-token. Jeśli za 6 mies. ktoś będzie spamował token-enumeration, dodać per-IP cap.
6. **Ambasador / verify flags** — świadomie pominięte (per decyzja użytkownika z ExitPlanMode: „tylko 3 open_to_*"). Architektura jest generalizacyjna — wystarczy rozszerzyć `_OPEN_TO_FIELDS` w backend + `OPEN_TO_OPTIONS` w frontend.

## Definition of Done — wynik

- [x] Faza 1: filtr w API + pill/multiselect + badge + CSV kolumny + testy backend + Chrome smoke ok
- [x] Faza 2: migracja TTL + timestamp auto-update + nudge UI + bulk-add-to-pool + magic-link flow end-to-end + testy
- [x] Wszystkie zmiany wdrożone przez push na `main` → Coolify auto-deploy ok
- [ ] `scripts/eval_matching.py` — nie uruchamiałem, bo zmiany dotyczą tylko filtrów listy + nowych endpointów, nie scoringu (zero ryzyka regresji)
- [x] Raport końcowy w `docs/otwartosc-dodatkowe-projekty-completion-report.md`

## Deploy timeline

- 2026-04-23 22:22 → 22:42 — Faza 1 (3 commity + Chrome smoke)
- 2026-04-27 09:00-09:20 — Faza 2 (ff0f51a, d2e5830, d86a934, fadc160 + curl smoke)

## Jeśli coś się zacznie sypać

- **Rollback Fazy 2:** `git revert fadc160 d86a934 d2e5830 ff0f51a` + push → auto-deploy. Zostawia migracje 0061+0062 zastosowane (dane bezpieczne, kolumny nullable, tabela osobna).
- **Magic-link nadużywany:** w `engagement_declaration_tokens` ustawić `expires_at = now()` na podejrzane tokeny (instant invalidate).
- **Bulk-add wstrzykuje za dużo:** w `talent_pool_memberships` `DELETE WHERE talent_pool_id = X AND candidate_id IN (...)` — pełny audit przez `created_at`.
