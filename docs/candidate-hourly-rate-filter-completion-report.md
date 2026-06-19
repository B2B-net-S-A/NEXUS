# Filtr „Stawka godzinowa" na /candidates + edycja w profilu — raport

**Data:** 2026-06-19
**Branch:** `claude/confident-fermi-37c499`
**Zgłoszenie:** „Brak możliwości przefiltrowania kandydatów po oczekiwanym wynagrodzeniu.
Dodaj filtr z zakresem stawek (np. od 120 do 200) — przefiltruj kandydatów, których
oczekiwania mieszczą się w przedziale." (źródło: `/candidates`)

## Decyzja produktowa (ważne)

Przykład „od 120 do 200" to **stawka godzinowa B2B (PLN/h)**, nie miesięczne wynagrodzenie.
Audyt danych przed implementacją:

| Źródło danych | Pokrycie |
|---|---|
| `candidates.salary_expectation` | **50 / 49 802** (0,1 %), wartości 12 000–33 000 = **miesięczne PLN** |
| `candidates.preferences.rate_min/max` | 0 |
| `cv_extracted_data` (Traffit) | brak jakiegokolwiek pola stawki/pensji |
| `candidate_rate_history` | 2 wiersze |

Wniosek: NEXUS **nie przechowywał** oczekiwanej stawki godzinowej. Po potwierdzeniu z
Arturem wybrano: **(1) nowe pole stawki godzinowej B2B (PLN/h)** + **(2) edycja w profilu**
(żeby rekruterzy uzupełniali). Filtr na istniejącym `salary_expectation` (miesięcznym,
99,9 % pustym) zostałby semantycznie błędny i praktycznie pusty.

## Co zostało zrobione

### Backend
- **Migracja `0138_candidate_expected_hourly_rate`** (down_revision `0137_talent_pool_is_personal`,
  jedyny head): kolumny `candidates.expected_rate_hourly` (INTEGER) + `expected_rate_currency`
  (VARCHAR(3)), indeks częściowy `ix_candidates_expected_rate_hourly WHERE NOT NULL`. Idempotentna
  (IF NOT EXISTS) — zgodna z entrypoint safety-net.
- **Model** `Candidate`: 2 kolumny obok `salary_expectation`.
- **Schematy** `CandidateCreate` / `CandidateUpdate` / `CandidateResponse`: oba pola.
- **`GET /api/candidates`**: parametry `min_rate` / `max_rate` (filtr `expected_rate_hourly`,
  „exclusive of nulls" — lustro `min_salary`/`max_salary`).
- **Edycja:** istniejące `PATCH /api/candidates/{id}` (przez `CandidateUpdate`).
- **Eksport CSV:** kolumny `expected_rate_hourly` + `expected_rate_currency`.
- **Testy** (`tests/test_candidates_filters.py`, dodane do CI): zakres, tylko-min,
  PATCH round-trip — w tym kontrakt „exclusive of nulls".

### Frontend
- **`/candidates` modal filtrów** (`CandidatesListV2.tsx`): pole „Stawka godzinowa (PLN/h)"
  (od–do) tuż pod „Lata doświadczenia". Pełne okablowanie: stan, URL (`rate_min`/`rate_max`),
  query (`min_rate`/`max_rate`), queryKey, licznik aktywnych filtrów, „Wyczyść wszystko",
  snapshot + zastosowanie zapisanego wyszukiwania.
- **`url-filters.ts`**: `rateMin`/`rateMax` w `CandidateFilters`, `DEFAULT_FILTERS`,
  `parseRateBound` (clamp [0, 100 000]), `encodeFilters`, `decodeFilters`, `filtersToApiParams`.
- **`ActiveFilterChips.tsx`**: chip „Stawka: X–Y PLN/h" z czyszczeniem.
- **`AppShell.tsx` (EditCandidateModal)**: pola „Stawka godzinowa B2B (PLN/h)" + „Waluta stawki"
  obok „Oczekiwań finansowych" (miesięcznych) — dla edycji w profilu.

## Weryfikacja
- Backend: `py_compile` ✓, `ruff` ✓, **alembic single head `0138`** ✓ (potwierdzone `ScriptDirectory`),
  import aplikacji + obecność pól na 3 schematach i modelu ✓.
- Frontend: `tsc --noEmit` czysty dla zmienionych plików ✓ (jedyne błędy = środowiskowe `docx-preview`
  w niezwiązanych plikach przez stary symlink node_modules), **30/30 testów `url-filters`** ✓
  (z round-tripem stawki), **ESLint 0 błędów** ✓.
- Adversarialny przegląd wieloagentowy (workflow) — patrz sekcja niżej.
- Testy backendu (`app_client`, Postgres) waliduje CI (lokalnie brak Postgresa/dockera).

## Znane ograniczenia
- **Dane startowo puste.** Kolumna `expected_rate_hourly` jest nowa → filtr zwraca wyniki dopiero
  gdy rekruterzy zaczną uzupełniać stawki w profilu (Edytuj → „Stawka godzinowa B2B"). To świadoma
  decyzja (Artur wybrał „filtr + edycja"). Brak backfillu — źródła Traffita nie mają stawek.
- Filtr porównuje wartość liczbową; waluta jest przechowywana/edytowalna, ale predykat jej nie
  rozróżnia (jak `min_salary`/`max_salary`). 99 %+ to PLN.
- Profil (`CandidateDetailV2`) na razie nie pokazuje stawki jako „fact" (osobny, zaaliasowany DTO
  `expected_salary`) — możliwy szybki follow-up; wartość jest widoczna/edytowalna przez modal Edytuj.

## Aktywacja / użycie
1. Deploy (merge → Coolify) → migracja 0138 dodaje kolumny automatycznie (entrypoint).
2. Rekruter: profil kandydata → Edytuj → „Stawka godzinowa B2B (PLN/h)" → zapis.
3. `/candidates` → Filtry → „Stawka godzinowa (PLN/h)" → od/do → „Pokaż wyniki".
