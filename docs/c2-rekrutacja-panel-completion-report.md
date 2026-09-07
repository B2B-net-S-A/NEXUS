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

Edycja **właściciela / terminu / notatki** w tablicy (drugi rząd karty): właściciel — select
z `/api/users` (OperationalUser, ownership-eligible, nie admin-only); termin — `datetime-local`
(zapis ISO, „po terminie" na czerwono); notatka — pole tekstowe z zapisem na blur (uncontrolled,
żeby refetch innego pola nie kasował wpisywanego tekstu). Każda zmiana → PATCH z `version`
(blokada optymistyczna → 409 obsłużone). Widok `readOnly` pokazuje te pola tylko do odczytu.

## Pliki

- `backend/app/api/matching.py` — helpery `_eligibility_annotation`, `_gate_and_dealbreakers`; obie gałęzie.
- `backend/tests/test_ai_matches_eligibility.py`, `test_ai_matches_fallback_eligibility.py` — kontrakt.
- `frontend/src/lib/api.ts` — typ `MatchEligibility` + pole `eligibility`.
- `frontend/src/app/jobs/[id]/page.tsx` — bramka na wierszu + pasek „ukryto N" + przełącznik Ranking/Shortlista + akcja „Na shortlistę".
- `frontend/src/components/v2/jobs/JobShortlist.tsx` — tablica shortlisty (nowy plik).

## Faza 5 — warsztat wizualny C2 (parytet z makietą `warsztat-mockups.html`)

Pierwsze wdrożenie dowiozło **funkcje** (bramka, „ukryto N", shortlista), ale wizualnie
doszyło je do sekcji „Klasyczne AI Matching (legacy) · diagnostyczny (admin)" — a wybrany
mockup C2 to **dedykowany warsztat**. Ta faza odtwarza wygląd makiety.

- **Odsłonięcie:** zdjęta bramka `isAdmin` i ramka „legacy/diagnostyczny" w rodzicu
  (`activeTab === "ai-matching"`). Panel widzi **każda rola**; akcje respektują `readOnly`.
  Narzędzia AI (kryteria/scoring/embedding, `JobAIActions`) zostają, ale **tylko dla admina**
  i zwinięte w `<details>` na dole — nie zaśmiecają warsztatu ani nie odsłaniają globalnych
  akcji („Embed all jobs") nie-adminom.
- **Pasek kontekstu (jobbar):** tytuł · klient · budżet kandydacki (`meta.budget_hourly` =
  `resolve_job_budget_hourly`) · deadline · właściciel + KPI (w rankingu / ≥75 pkt / w
  procesie) + przełącznik Ranking/Shortlista.
- **Lewa kolumna „Wymagania z Championa":** pills must (klik = filtr wiersza), pills nice,
  suwak progu (`min_score`, filtr klientowy), stawka wobec budżetu (mieści/powyżej/brak) i
  etap (w procesie / poza procesem). „Wyczyść filtry". Wszystko po stronie klienta — bez
  ponownego odpytania backendu.
- **Bogate wiersze:** checkbox (multi-select → „Przypisz zaznaczonych", `proposalsBulkApi`),
  pozycja, avatar, „stanowisko · firma · miasto", chip wyniku, **pokrycie X/Y must** (paski),
  **stawka na zielono/czerwono** wobec budżetu, pigułka „w procesie", plakietka
  dopuszczalności. Klik wiersza → dok.
- **Prawy dok „Dopasowanie" (`JobMatchDock`):** gauge wyniku + zdanie „co znaczy wynik",
  linia dopuszczalności, **pokrycie wymagań** (must ✓/✗ + nice ✓/✗ z `nice_matching`/
  `nice_gaps`), **warunki wobec oferty** (stawka vs budżet, lokalizacja, etap), podsumowanie
  AI (jeśli jest), akcje (Dodaj do pipeline / Na shortlistę / Wyślij / Profil) i rozwijane
  **„Pełne uzasadnienie AI"** (leniwie montuje `DopasowanieTab` — LLM liczy się dopiero po
  kliknięciu). Sticky na `xl`; na mniejszych ekranach spływa pod listę (bez poziomego scrolla).

### Backend pod warsztat (`matching.py`)

- `_build_match_info`: nowy param `nice_skills` → `nice_matching`/`nice_gaps` (wyświetlenie,
  **nie** wchodzi do score); candidate dict += `expected_rate_hourly` (Decimal→float),
  `current_title`/`current_company` (z `linkedin_current_*`), przez `getattr` (atrapy testowe
  bez tych pól nie wywalają rankingu).
- `_parse_nice_skills(job)` z `job.nice_skills` (JSON). `nice_skills` w obu zwrotkach.
- `meta.budget_hourly = resolve_job_budget_hourly(job)` — ten sam sufit co `over_budget`.
- Zero dodatkowych zapytań (pola z wczytanego wiersza; „w procesie"/etap z `pipelineScores`,
  już wpiętego kluczem `["pipeline-scores", jobId]`).

## Weryfikacja (lokalnie)

- Backend: `ruff check` + `ruff format --check` czyste (matching.py + test). Nowe testy
  jednostkowe w `test_matching_skill_sources.py` (nice coverage, pola C2, brak pól = None);
  wykonanie w CI (Py 3.12 + deps — system Py 3.9 nie ma `bcrypt`).
- Frontend: `tsc --noEmit` **exit 0**; `eslint` **0 błędów** (13 ostrzeżeń `any`/pre-existing,
  poniżej limitu 300; wszystkie ostrzeżenia z moich zmian usunięte). `next build` — lokalnie.
- Testy integracyjne (Postgres + Py 3.12) — w CI.
