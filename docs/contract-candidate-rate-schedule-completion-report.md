# Contract candidate-rate schedule — completion report

**Data:** 2026-06-24
**Branch:** `claude/nervous-tu-5a1e46`
**Zgłoszenie:** Kontrakty → Nowy kontrakt — pole „Stawka kandydata" nie obsługiwało
zmiany stawki w trakcie trwania kontraktu. Ma być: możliwość dodania nowej
wartości z polem „Obowiązuje od", tak aby system przechowywał historię zmian i
automatycznie stosował aktualną stawkę od wskazanej daty.

## Decyzje projektowe (potwierdzone z Arturem)

1. **Zakres:** *oba* — harmonogram zakładany w formularzu nowego kontraktu
   **oraz** późniejsze zmiany przez istniejący mechanizm aneksów. Jeden,
   wspólny model historii stawek.
2. **Aktualna stawka:** liczona **przy odczycie** (derived), bez background
   schedulera. Aktualna = wpis o najpóźniejszej dacie `effective_from ≤ dziś`.

## Model danych

Nowa tabela **`contract_candidate_rates`** (migracja `0144`) — harmonogram stawek
kandydata per kontrakt. Każdy wiersz to krok: `rate` obowiązująca od
`effective_from`.

- `id`, `contract_id` (FK → contracts, ON DELETE CASCADE), `rate`,
  `effective_from` (DATE), `note`, `created_by` (FK → users, SET NULL),
  `created_at`, `updated_at`.
- Indeksy: `contract_id`, `effective_from`.

Migracja **scala dwa równoległe heady** (`0143_candidate_search_fts` +
`0143_invalidate_match_score_cache`) — po niej jeden head.

`Contract.rate_candidate` zostaje jako **cache + legacy fallback**: kontrakty
sprzed tej zmiany nie mają harmonogramu, więc resolver zwraca dla nich starą
kolumnę → **pełna wsteczna kompatybilność**.

## Resolver (derived-at-read)

`Contract.effective_candidate_rate(on)`:
- brak harmonogramu → `rate_candidate` (legacy),
- są wpisy `≤ on` → ten o najpóźniejszej dacie,
- same przyszłe wpisy → najwcześniejszy (baseline, żeby świeży kontrakt miał
  sensowną stawkę).

Wszystkie odpowiedzi API (`GET /api/contracts`, `GET /api/contracts/{id}`,
`POST`) liczą `rate_candidate` / `margin` / kwoty miesięczne z harmonogramu w
locie (`_effective_candidate_fields`) — bez polegania na background jobie.

## Przepływ danych (wspólna historia)

- **Tworzenie:** `ContractCreate.candidate_rate_schedule: [{rate, effective_from,
  note?}]`. Endpoint zapisuje wiersze i synchronizuje `rate_candidate` do
  aktualnego kroku.
- **Aneks `rate_change`:** gdy zmienia `new_rate_candidate`, **dopisuje krok** do
  harmonogramu (`effective_from = effective_date`). Dla kontraktów bez
  harmonogramu najpierw zakłada krok bazowy (stara stawka od `start_date`,
  notatka „Stawka początkowa"), żeby historia była kompletna.
  - **Zmiana zachowania (świadoma):** aneks z **przyszłą** datą wejścia w życie
    **nie** zmienia już `rate_candidate` od razu — stawka przełącza się dopiero w
    dniu wejścia w życie (zgodnie z „derived"). Wcześniej ustawiał ją natychmiast.

## Frontend

- **`/contracts/new`** — pole „Stawka kandydata" zamienione na **harmonogram**:
  wiersze `Stawka` + `Obowiązuje od`, przycisk „+ Dodaj zmianę stawki", usuwanie
  dodatkowych wierszy. Pierwszy wiersz bez daty = od daty rozpoczęcia. Walidacja:
  unikalne daty `Obowiązuje od`. Wysyła `candidate_rate_schedule`.
- **`/contracts/[id]`** — w panelu „Stawki finansowe" timeline harmonogramu
  (gdy >1 krok), z oznaczeniem kroku aktualnego. Pole „Stawka kandydata" w
  formularzu edycji jest **wyłączone** gdy istnieje harmonogram (z podpowiedzią:
  zmień przez aneks „Zmień stawkę") — żeby nie kolidowało z derived-at-read.

## Pliki

**Backend**
- `app/models/contract_candidate_rate.py` (nowy)
- `app/models/contract.py` — relacja `candidate_rate_schedule` + `effective_candidate_rate`
- `app/models/__init__.py` — rejestracja
- `app/schemas/contract.py` — `ContractCandidateRateInput` / `…Entry`, pola w Create/Response
- `app/api/contracts.py` — create / list / `_to_detail` derived, aneks zasila harmonogram
- `alembic/versions/0144_contract_candidate_rate_schedule.py` (nowy, merge 2 headów)
- `tests/test_contract_candidate_rate_schedule.py` (nowy) + wpis w `.github/workflows/ci.yml`

**Frontend**
- `src/app/contracts/new/page.tsx`
- `src/app/contracts/[id]/page.tsx`

## Weryfikacja

- ✅ `ruff check` (app + nowe pliki + migracja) — czysto.
- ✅ `py_compile` zmienionych modułów — OK.
- ✅ Frontend `tsc --noEmit` — 0 błędów.
- ✅ `eslint` zmienionych plików — 0 błędów (2 pre-existing warningi: nieużywane
  `Printer`/`Loader2`, nie wprowadzone tą zmianą).
- ✅ Test jednostkowy resolvera + integracyjny (create+harmonogram → derived rate,
  aneks dopisuje krok) — dodany do listy CI.
- ⏳ **pytest backendu** — uruchamiany w CI (lokalnie brak zainstalowanych zależności).
- ⏳ **UI przez Chrome** — do wykonania po merge na prod (ekrany authed wymagają
  pełnego stacku + JWT; lokalnie niedostępne).

## Znane ograniczenia

- `rate_candidate` w kolumnie DB to cache aktualnego kroku „na dziś" liczony przy
  zapisie; konsumenci **SQL-owi** (eksporty/analityka czytające kolumnę wprost)
  mogą nie odzwierciedlać kroku przyszłego, dopóki nie nastąpi zapis. **API**
  zawsze liczy poprawnie przy odczycie.
- Edycja `rate_candidate` przez formularz na karcie kontraktu jest wyłączona, gdy
  istnieje harmonogram — zmiany stawki idą wtedy przez aneks (z datą).
