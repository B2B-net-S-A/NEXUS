# Completion report — „Otwartość na dodatkowe projekty" (Faza 1)

**Data:** 2026-04-24
**Branch:** `main` (deployed via Coolify)
**Plan:** `.claude/plans/zaplanuj-wszystko-zgodnie-z-cheeky-stream.md`
**Feature request klienta:** _„Dodanie zakładki oraz filtra, który oznaczymy, w przypadku chęci kandydata na zaangażowanie w dodatkowe projekty"_

---

## Status: Faza 1 — DEPLOYED & SMOKE-TESTED ✅

Feature dostarczony i zweryfikowany na produkcji (https://nexus.dynaminds.pl/candidates). Kandydat Agnieszka Nowak (id=2) zsetowany z `open_to_side_projects=True`, widoczny w filtrze + badge renderuje się poprawnie.

## Status: Faza 2 — DEFERRED ⏸

Zablokowane przez **Alembic multi-head state** na produkcji (0036_microsoft365 + 0060_client_tac_assignments). Nie dokładam nowych migracji żeby nie pogłębiać drift. Artur równolegle rozwiązuje to safety-net DDL w entrypoint.sh (commit [`95e8236`](https://github.com/artur-t-96/Nexus/commit/95e8236)). Po stabilizacji chain-a migrations Faza 2 wraca do kolejki.

---

## Co zostało dowiezione (commity na main)

| # | Commit | Scope | Test |
|---|--------|-------|------|
| 1.1 | [`9c7b0b8`](https://github.com/artur-t-96/Nexus/commit/9c7b0b8) `feat(candidates): filter list by open_to engagement flags` | Backend query param `open_to` — OR-combined multiselect walidowany przez whitelistę | 3 testy integracyjne |
| 1.2-1.4 | [`fd29faf`](https://github.com/artur-t-96/Nexus/commit/fd29faf) `feat(candidates): UI filter + pill + badge for open_to flags` | `MultiSelectFilter` „Otwartość", pill-shortcut „⚡ Otwarci na extra", badge na CandidateHighlights, URL sync | Chrome smoke |
| 1.5 | [`1543378`](https://github.com/artur-t-96/Nexus/commit/1543378) `feat(candidates): CSV export kolumny open_to_*` | 3 kolumny w `/export/candidates` CSV | Manual |

## Endpointy i pola które działają

**Backend (`GET /api/candidates`):**
- Nowy query param `open_to` (list[str], optional, repeat — np. `?open_to=side_projects&open_to=sales_support`)
- Wartości: `side_projects`, `sales_support`, `expert_consult`
- OR-combined — kandydat musi mieć co najmniej jedną z wybranych flag = True
- Walidacja: nieznana wartość → 422 z listą dozwolonych

**Frontend (`/candidates`):**
- `MultiSelectFilter` „Otwartość" w pasku filtrów (190px)
- Przycisk-pill „⚡ Otwarci na extra" (secondary gdy aktywny) — toggle all-3 flag jednym klikiem
- Badge Tier 2.6 „⚡ Otwarty na extra" (variant=info, z tooltipem wypisującym które flagi są aktywne) w CandidateHighlights
- URL sync: `?open_to=side_projects,sales_support,expert_consult`

**CSV export:**
- 3 nowe kolumny (`open_to_side_projects` / `sales_support` / `expert_consult`) z wartością `"tak"` lub `""`

## Pliki zmodyfikowane

- [backend/app/api/candidates.py](backend/app/api/candidates.py#L431-L453) — query param + filter logic
- [backend/app/api/import_export.py](backend/app/api/import_export.py#L227-L260) — CSV columns
- [backend/tests/test_candidates_filters.py:314-399](backend/tests/test_candidates_filters.py#L314) — 3 nowe async testy
- [frontend/src/lib/filter-options.ts](frontend/src/lib/filter-options.ts#L47-L63) — `OPEN_TO_OPTIONS` + `OpenToValue`
- [frontend/src/components/v2/pages/CandidatesListV2.tsx](frontend/src/components/v2/pages/CandidatesListV2.tsx) — state, URL sync, query, MultiSelectFilter + pill button
- [frontend/src/components/v2/CandidateHighlights.tsx](frontend/src/components/v2/CandidateHighlights.tsx#L110-L129) — Tier 2.6 badge

## Migracje / schema DB

**Brak nowych migracji.** Kolumny `open_to_side_projects` / `sales_support` / `expert_consult` istnieją od migracji [0037_contracts_expansion](backend/alembic/versions/0037_contracts_expansion.py) (Phase „Kontrakty Expansion"). Feature dostarczony czysto warstwą aplikacji.

## Testy

**Backend (docker exec nexusats-backend-1 pytest):**
```
tests/test_candidates_filters.py::test_open_to_single_flag_filters_correctly PASSED
tests/test_candidates_filters.py::test_open_to_multi_value_is_or_combined    PASSED
tests/test_candidates_filters.py::test_open_to_invalid_value_returns_422      PASSED
```

**Regresja:** `test_candidate_engagement.py` (2 testy) — PASS.
**Pre-existing failures** w `test_candidates_filters.py` (`test_status_filter_*`, `test_create_candidate_sets_created_by`) — **nie związane** z moimi zmianami, błędy enum `userrole:"manager"` w dev DB (pochodzą z innej, niezwiązanej migracji Artura).

**Chrome smoke (prod, https://nexus.dynaminds.pl):**
1. ✅ GET `/api/candidates?page_size=1` → 35795 kandydatów w bazie, backend healthy
2. ✅ PATCH `/api/candidates/2/engagement` z `open_to_side_projects:true, open_to_sales_support:true` → 200, response zawiera nowe wartości
3. ✅ `/candidates?open_to=side_projects` → lista redukuje się do 1 wyniku (Agnieszka Nowak, id=2)
4. ✅ Widok tabelaryczny pokazuje badge „⚡ Otwarty na extra" w kolumnie Status
5. ✅ GET `/api/candidates?open_to=bogus` → 422 z komunikatem `Invalid open_to values: ['bogus']. Allowed: ['expert_consult', 'sales_support', 'side_projects']`

## Znane ograniczenia / deferred

1. **Widok kafelkowy (`CandidatesTiles`) nie pokazuje badge'a** — kafelki nie używają `CandidateHighlights`. Jeśli Artur chce badge również tam — dopisać w osobnym commicie (2-3 linie zmian w `CandidatesTiles.tsx`).
2. **Pre-existing: widok domyślny** — widać kafelki, badge widoczny dopiero po przełączeniu na widok tabeli. Jeśli zależy na widocznej-od-razu-widoczności — albo: (a) dopisać badge do tiles, (b) przestawić domyślny widok na `list`.
3. **Widok talentów (`/talents`)** — nie ruszany. Jeśli chcemy filtrować talent-poole po tej flagi, trzeba rozszerzyć też ten widok.
4. **Ambasador / verify flags** — świadomie pominięte (per decyzja użytkownika: „tylko 3 open_to_*"). Architektura jest generalizacyjna — wystarczy rozszerzyć `_OPEN_TO_FIELDS` w backend + `OPEN_TO_OPTIONS` w frontend.

## Faza 2 — deferred (do osobnego planu po stabilizacji migracji)

| # | Scope | Blocker |
|---|-------|---------|
| 2.1-2.2 | TTL timestamps (`open_to_*_updated_at` kolumny + auto-update w PATCH) | Alembic multi-head (0036 + 0060 + new WIP migrations). Dodawanie kolejnej migracji zaostrzy drift. |
| 2.3 | Nudge „odśwież deklarację po 90 dniach" w `CandidateEngagementPanel` | Zależy od 2.1 (bez timestampów nudge nie wie kiedy pokazać alert) |
| 2.4 | Sort „najświeższe deklaracje na górze" w zakładce | Zależy od 2.1 (bez timestampów sort nie ma po czym sortować per-flagę) |
| 2.5 | Bulk-action „Dodaj zaznaczone do Talent Poolu" z listy `/candidates` | BRAK blockera — do zrobienia po stabilizacji głównego pnia, wymaga osobnego endpointu `POST /api/talent-pools/{id}/candidates/bulk` |
| 2.6 | Magic-link self-service dla kandydatów (nowy model `engagement_declaration_tokens` + publiczne endpointy + strona `/engagement/[token]`) | Wymaga nowej migracji + nowego public router — duża powierzchnia zmian. |

### Rekomendacja ordera dla Fazy 2

1. Poczekać aż Artur doczołga Alembic do single-head (zakończy WIP `0059_add_job_tac_id` + `0060_client_tac_assignments`, ewentualnie doda merge-migration).
2. Wrócić z 2.1-2.2 jako pierwsze (timestampy + backfill) → jedna migracja dodająca 3 kolumny NULLABLE DateTime, bezpieczna.
3. Po tym 2.3 (nudge) + 2.4 (sort).
4. 2.5 (bulk-to-pool) — niezależna, może iść wcześniej jeśli priorytet wysoki.
5. 2.6 (magic-link) — największa praca, wymaga brieftu UX dla formularza kandydackiego (czy ma być w języku kandydata? Czy obsługujemy ENG?).

---

## Deploy timeline (timestamps UTC)

- 22:22 — push 1.1 backend → build Coolify
- 22:23 — testy open_to = 3/3 green (local docker)
- 22:26 — push 1.2-1.4 frontend
- 22:28 — push 1.5 CSV export
- 22:37 — prod 503 wykryte (Alembic multi-head → backend crash-loop)
- 22:38 — Artur push safety-net DDL [`95e8236`](https://github.com/artur-t-96/Nexus/commit/95e8236)
- 22:40 — prod recover, login działa, 35795 kandydatów widocznych
- 22:41 — PATCH engagement id=2 → 200
- 22:42 — Chrome smoke ✅, screenshot saved

## Jeśli coś się zacznie sypać

- Rollback: `git revert 1543378 fd29faf 9c7b0b8` + push → Coolify auto-deploy. Dane (flagi już zaznaczone w DB) pozostają — kolumny od 0037 były tam od początku.
- Badge ucieka poza wiersz: zmniejszyć `variant` z `info` na `neutral` w [CandidateHighlights.tsx:122](frontend/src/components/v2/CandidateHighlights.tsx#L122).
- Filtr zwraca za dużo: sprawdzić `or_(...)` w [candidates.py](backend/app/api/candidates.py) — AND-combine wymaga zmiany na `and_()`.
