# C2 „Rekrutacja" — panel dopasowania na `/jobs/[id]`

Raport z implementacji kierunku C2 dla ekranu dopasowań kandydatów do jednej rekrutacji.
Decyzja architektoniczna: **rozbudowa istniejącego widoku `ai-matches` na `/jobs/[id]`**,
nie retrofit `/candidates` (ai-matches już tam żył z działającym UI; retrofit 3651-liniowego
`CandidatesListV2` był wysokim ryzykiem).

## Zakres i status

| Faza | Zakres | Status |
|---|---|---|
| 0 | Kontrakt `ai-matches`: anotacja zablokowanych + `hidden_meta` | **Zrobione + testy** |
| 1 | Kontekst rekrutacji | Wrodzony — to strona oferty (`/jobs/[id]`) |
| 2 | Bramka na wierszu + pasek „ukryto N" | **Zrobione** (frontend `/jobs/[id]`) |
| 3 | Zakładka „Dopasowanie" | Już istnieje: `components/v2/pages/DopasowanieTab.tsx` |
| 4 | Tablica shortlisty (ocena → kontakt → promocja) | **Zrobione** (`JobShortlist.tsx` + przełącznik w `AIMatchingSection`) |

## Faza 0 — backend (`backend/app/api/matching.py`)

`GET /jobs/{id}/ai-matches` przestał **wycinać** zablokowanych; teraz **anotuje**:

- `_gate_and_dealbreakers()` (nowy helper) zastąpił `filter_eligible_candidates` w obu gałęziach
  (semantycznej i tag-fallback).
- **Widoczność wg modelu `Visibility`:** `hidden` (globalna blacklista, duplikat w rekrutacji)
  nadal wycinani; `warn` (aktywny konflikt klienta / NDA / konkurent / weto hiring managera)
  **wracają** z polem `eligibility` i `assignment_allowed=false`; miękkie ostrzeżenia
  (`current_employment`, `excluded_client`) wracają jako anotacja bez blokady akcji.
- **Dealbreakery** (`apply_dealbreakers`) wpięte do endpointu (wcześniej ich tu nie było):
  stawka ponad budżet kandydacki (`resolve_job_budget_hourly`) i „tylko zdalnie" dla ofert
  onsite/hybrid; liczniki w `meta.hidden = {over_budget, remote_only}`.
- **Fail-closed zachowany:** bramka (`evaluate_candidates_for_job`) stoi POZA `try` retrievalu,
  więc jej awaria → 500, nie degradacja do listy bez bramki.

### ⚠️ Świadomy override decyzji bezpieczeństwa (2026-08-20)

Poprzednia decyzja trzymała liczbę zablokowanych **poza** odpowiedzią jako ochronę przed
„wyrocznią na NDA". Właściciel produktu (Artur) zdecydował pokazywać zablokowanych z powodem
wprost w rankingu. Realizacja przez trójstanowe `Visibility` ogranicza wyciek: `hidden`
(m.in. globalna blacklista) nadal nie wychodzi i **nie jest liczony**; ujawniane są wyłącznie
`warn` (konflikt per klient/NDA/konkurent/weto). Override jest udokumentowany w kodzie
(`_gate_and_dealbreakers` docstring) z datą i uzasadnieniem.

### Testy (przepisane pod nowy kontrakt)

- `tests/test_ai_matches_eligibility.py` — AST: handler woła `_gate_and_dealbreakers`
  (nie stary `filter_eligible_candidates`); guard fail-open i guard gałęzi fallback
  zaktualizowane na nową nazwę. `/recommendations` nadal pilnowane pod
  `filter_eligible_candidates`.
- `tests/test_ai_matches_fallback_eligibility.py` — HTTP: NDA-kandydat (`warn`) teraz
  **obecny** z `eligibility.assignment_allowed=false` i `reason_code="client_nda"` (dawniej:
  nieobecny). Test fail-closed przekierowany na `evaluate_candidates_for_job` → 500.
- `tests/test_ai_matches_degraded_meta.py` — bez zmian, `meta.hidden` jest additywne.

Weryfikacja lokalna: `ruff check` + `ruff format --check` czyste; asercje AST sprawdzone
standalone na realnym pliku (4/4). Testy integracyjne (Postgres + Py 3.12) — w CI.

## Faza 2 — frontend (`frontend/src/app/jobs/[id]/page.tsx`, `lib/api.ts`)

- `lib/api.ts`: dodany typ `MatchEligibility` + pole `eligibility?` w odpowiedzi
  `matchingApi.getMatches`. `meta.hidden` był już otypowany w `RecommendationMeta`.
- Wiersz dopasowania: plakietka dopuszczalności z powodem po polsku; przy
  `assignment_allowed=false` przycisk „Dodaj do pipeline" wyszarzony z tytułem = powód
  („Nie można dodać"), a wiersz dostaje tint `destructive/5`. Miękkie ostrzeżenia:
  plakietka bez blokady akcji.
- Pasek „ukryto N" nad listą z rozbiciem per powód (budżet / zdalnie) + nota o twardym
  suficie budżetu. Renderowany tylko gdy `hiddenTotal > 0`.

Weryfikacja: type-check/build w CI (worktree bez `node_modules` w chwili pisania).

## Faza 4 — shortlista (zrobione)

Nowy komponent `frontend/src/components/v2/jobs/JobShortlist.tsx` + przełącznik
Ranking/Shortlista w `AIMatchingSection` (zgodnie z makietą — dwa stany jednej sekcji,
nie osobna globalna zakładka).

- **Wejście:** akcja „Na shortlistę" na każdym wierszu rankingu (`shortlistApi.add`,
  staged evaluation przed pipeline; zablokowana dla `assignment_allowed=false`).
  Licznik w przełączniku dzieli ten sam `queryKey` co tablica (react-query dedupe).
- **Tablica:** ocena — segment 4 (`evaluation_status`); kontakt — select 5
  (`outreach_status`); snapshot wyniku (`score_snapshot`); termin (`next_action_at`,
  „po terminie" na czerwono); promocja (`promote`) i usunięcie. Etykiety PL zdefiniowane
  w komponencie (model nie ma jeszcze mapy FE).
- **Blokada optymistyczna:** PATCH z `version`; 409 → toast „ktoś zapisał równolegle,
  odśwież" + refetch (bez cichego nadpisania).
- **Promocja przez bramkę:** `promote` przechodzi eligibility; 409 pokazywany z `detail`
  po polsku (ten sam powód co w rankingu).
- **RBAC:** `readOnly` wyłącza wszystkie mutacje. Stany loading/empty/error obsłużone.

Świadomie poza tym przejściem (mniejsze, opcjonalne): edycja notatki/właściciela/terminu
w tablicy (dziś tylko wyświetlane) — API (`shortlistApi.update`) je już przyjmuje.

## Pliki

- `backend/app/api/matching.py` — helpery `_eligibility_annotation`, `_gate_and_dealbreakers`; obie gałęzie.
- `backend/tests/test_ai_matches_eligibility.py`, `test_ai_matches_fallback_eligibility.py` — kontrakt.
- `frontend/src/lib/api.ts` — typ `MatchEligibility` + pole `eligibility`.
- `frontend/src/app/jobs/[id]/page.tsx` — bramka na wierszu + pasek „ukryto N" + przełącznik Ranking/Shortlista + akcja „Na shortlistę".
- `frontend/src/components/v2/jobs/JobShortlist.tsx` — tablica shortlisty (nowy plik).

## Weryfikacja (lokalnie)

- Backend: `ruff check` + `ruff format --check` czyste; asercje AST 4/4 na realnym pliku.
- Frontend: `tsc --noEmit` czyste; `eslint` 0 błędów (8 istniejących ostrzeżeń `any`, nie z tych zmian).
- Testy integracyjne (Postgres + Py 3.12) i pełny `next build` — w CI.
