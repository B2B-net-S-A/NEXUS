# Kontrakty — filtrowanie i eksport listy osób zatrudnionych u klienta

> Moduł **Kontrakty → Rejestr kontraktów → wybór klienta** (`ClientContractRegister`).
> Dodano panel filtrów **Status + Okres** oraz przycisk **„Eksportuj do Excela"**.

## Zakres

Po wybraniu klienta w module Kontrakty lista osób zatrudnionych (kontrakty
konsultantów danego klienta) nie miała ani filtrów, ani eksportu. Ten moduł
dokłada:

1. **Filtry (AND, server-side, real-time):**
   - **Status** — multiselect po statusach istniejących w module
     (`draft`/`active`/`ending`/`ended` → Szkic/Aktywny/Kończący się/Zakończony).
     Reuse `CONTRACT_STATUS_OPTIONS` — bez osobnej listy statusów.
   - **Okres** — zakres dat „od–do" jako **overlap**: kontrakt trafia na listę,
     gdy jego okres obowiązywania `[start_date, end_date]` **przecina się** z
     wybranym zakresem (a nie tylko po dacie startu lub tylko końca). Otwarty
     koniec (`end_date IS NULL` = „bezterminowo") i brak startu obsłużone.
2. **Eksport do Excela** — przycisk „Eksportuj do Excela" (widoczny tylko po
   wybraniu klienta, bo komponent renderuje się wyłącznie w kontekście klienta).
   Plik `.xlsx` **zawężony do wybranego klienta** i **honorujący aktywne filtry**
   („eksportuj to, co widzę"). Kolumny w kolejności ze specyfikacji:
   **Nr projektu, Projekt, Konsultant, Model, Okres / Pula godzin, Prolongata, Status.**

## Warunki zamknięcia — mapowanie

| # | Warunek | Realizacja |
|---|---------|-----------|
| 1 | Panel z filtrami Status + Okres po wyborze klienta | `ClientContractRegister` `FilterBar` (slot `filters`) |
| 2 | Zmiana filtrów aktualizuje listę | Filtry w `queryKey` + params `GET /api/contracts` |
| 3 | Widoczny przycisk „Eksportuj do Excela" | `FilterBar` slot `actions` |
| 4 | Eksport = tylko dane wybranego klienta | `client_id` **wymagany** na endpoincie + DL-scope |
| 5 | Aktywne filtry → eksport tylko przefiltrowanych | Endpoint honoruje `q`/`status`/`period_*` (ten sam helper co lista) |
| 6 | Kolejność kolumn (7) | `_REGISTER_EXPORT_COLUMNS` + test kolejności |
| 7 | Brak klienta = brak eksportu | Przycisk tylko w widoku klienta; endpoint bez `client_id` → **422** |

## Zmiany w kodzie

### Backend — `backend/app/api/contracts.py`
- `_apply_contract_list_filters(..., period_from, period_to)` — filtr overlap:
  `OR(end_date IS NULL, end_date ≥ from) AND OR(start_date IS NULL, start_date ≤ to)`.
  Wpięty w `list_contracts` (lista rejestru) oraz istniejący finansowy `/export`
  (parytet — jedno źródło filtrów, „never drift").
- **Nowy** `GET /api/contracts/register/export` → `export_client_register`:
  - Audytorium **TacPlus** (nie Admin — brak stawek/marży), scope Delivery Lead
    jak na liście (`apply_delivery_lead_client_scope`).
  - `client_id` **wymagany**; `q`/`status`/`period_from`/`period_to` opcjonalne.
  - Format `.xlsx`, 7 kolumn = widoczna tabela; helpery `_register_export_row`,
    `_register_period_cell`, `_pl_date`, `_REGISTER_EXPORT_COLUMNS`,
    `_ENGAGEMENT_MODEL_LABELS`, `_REGISTER_PROLONGATION_LABELS`.
  - Route zadeklarowany **przed** `/{contract_id}` (rozstrzyganie tras).

### Frontend — `frontend/src/components/contracts/ClientContractRegister.tsx`
- Stan filtrów: `statusFilter` (`MultiSelectFilter`), `periodFrom`/`periodTo`
  (dwa `Input type="date"`, aria-label „Okres od"/„Okres do").
- Params listy: `status` (repeat, `paramsSerializer: { indexes: null }`),
  `period_from`, `period_to`; reset strony na zmianę filtra; filtry w `queryKey`
  (optimistic update prolongaty dalej trafia w właściwy cache).
- `doExport()` — blob-download z `/api/contracts/register/export` (Bearer z sesji),
  frazą **zdebouncowaną** i bieżącymi filtrami; nazwa pliku
  `rejestr-kontraktow-<klient>-<data>.xlsx`.
- Empty-state rozróżnia „brak wyników dla filtrów" od „klient nie ma kontraktów".

## „Lustro tabeli" — parytet eksportu z ekranem

Eksport czyta się jak tabela (audyt adwersaryjny wychwycił i naprawiono 4 różnice
kosmetyczne):
- **Procent puli godzin**: zaokrąglenie **half-up** (`int(pct+0.5)`, jak JS
  `Math.round`) zamiast bankierskiego `round()` — 12.5% → **13%**, nie 12%.
- **Zerowa/pusta pula**: zawsze pokazuje `(0%)` (jak ekran), nie pomija procentu.
- **Daty**: format PL `d.mm.rrrr` (`1.01.2026`), lustro `Intl.DateTimeFormat('pl-PL')`.
- Puste teksty (np. brak nazwy projektu) → pusta komórka (naturalna reprezentacja
  braku w arkuszu do dalszej analizy), placeholdery `#id`/„—" zachowane jak w UI.

## Weryfikacja (wszystko zielone)

- **Backend:** 17 testów `test_contracts_register_export.py` (overlap incl.
  otwarty koniec/jednostronny zakres; kolumny/etykiety/wartości; `client_id`
  wymagany → 422; parytet status + okres; scope do klienta; half-up %) +
  **195** w pełnym pakiecie `test_contract*` — bez regresji. `ruff check` +
  `ruff format` czyste. (Py3.12 obraz + migrowany Postgres, jak CI.)
- **Frontend:** 3 testy RTL (`ClientContractRegisterFilters.test.tsx` +
  istniejące) — filtr Okres → params listy, eksport → URL `/register/export` z
  `client_id` + filtrami. `tsc` czyste (poza pre-existing `chart.tsx`),
  ESLint czyste.
- **Audyt adwersaryjny** (3 wymiary × verify): 0 findingów correctness/
  security-RBAC/regression; 4 low (parytet) — wszystkie naprawione.

## Znane ograniczenia / świadome decyzje

- Eksport zbiorczy (bez wybranego klienta, wszyscy klienci) — **poza zakresem**
  (możliwa osobna funkcja w przyszłości), zgodnie z doprecyzowaniem.
- Register export to `.xlsx` (bez CSV) — zgodnie z „Eksportuj do Excela".
- Format daty w eksporcie odwzorowuje `Intl.DateTimeFormat('pl-PL')` empirycznie;
  ewentualny dryf ICU pozostaje kosmetyczny (komórka tekstowa, nie natywna data).

## Aktualizacja — filtr Podkategoria (2026-08-05)

Dołożono trzeci filtr rejestru: **Podkategoria** (multi-select), zawężający listę
i eksport po **`Job.subcategory`** powiązanej oferty (każda oferta leży pod jedną
competence category i niesie free-text podkategorię). Decyzja: „wyprowadź z oferty
i wypuść od razu" — bo kandydatowa taksonomia podkategorii CC to niezbudowana Faza 2
(brak modelu/danych), a `Job.subcategory` istnieje i jest wypełniony.

- **Filtr (`_apply_contract_list_filters`)**: `subcategory: list[str]` jako
  **podzapytanie** `Contract.job_id IN (SELECT Job.id WHERE Job.subcategory IN (...))`
  — NIE JOIN, bo helper bywa już (outer)joinowany z Job w bloku `q`; drugi JOIN by
  się zderzał. Wpięte w listę rejestru, eksport rejestru i finansowy `/export`.
  Kontrakty bez oferty (job_id NULL) wypadają przy aktywnym filtrze.
- **Endpoint opcji**: `GET /api/contracts/register/subcategories?client_id=` (TacPlus,
  DL-scope, `client_id` wymagany) → odrębne, niepuste `Job.subcategory` faktycznie
  występujące u klienta (dropdown pokazuje tylko to, co da się odfiltrować; voidy
  pominięte). Zasila multiselect.
- **Frontend**: multiselect renderowany tylko gdy klient ma podkategorie; wpięty w
  zapytanie listy (repeat-param), URL eksportu, `queryKey`, reset strony,
  `hasActiveFilters`, „Wyczyść". **Reset per klient**: podkategorie są specyficzne
  dla klienta, a komponent nie jest remontowany przy zmianie klienta — wybór jest
  więc czyszczony SYNCHRONICZNIE w renderze (wzorzec React „adjust state on prop
  change"), żeby pierwszy fetch nowego klienta nie poleciał ze starym filtrem
  (inaczej lista mignęłaby pusta, a przy błędzie endpointu podkategorii filtr
  zostałby aktywny-niewidoczny). Status/Okres celowo przechodzą między klientami.
- **Testy**: +4 BE (filtr listy z pominięciem job-less/void, filtr eksportu,
  endpoint distinct client-scoped, `client_id`→422) + FE (fetch opcji + wybór do
  listy/eksportu + reset przy zmianie klienta). Audyt adwersaryjny: 0 findingów
  security/regression; 1 low (stale filtr przy zmianie klienta) — naprawiony.

### Aktualizacja — kolumna „Podkategoria" w eksporcie (2026-08-05)

Dołożono **„Podkategoria"** jako kolumnę eksportu rejestru (`Job.subcategory`
powiązanej oferty), tuż po „Projekt" — grupuje deskryptory oferty
(Nr projektu / Projekt / Podkategoria) przed osobą i statusem. To jedyna kolumna
wykraczająca poza widoczną tabelę (na życzenie, do dalszej analizy).

- **Kolumny (8)**: Nr projektu, Projekt, **Podkategoria**, Konsultant, Model,
  Okres / Pula godzin, Prolongata, Status.
- **Wartość**: `c.job.subcategory` gdy jest oferta z podkategorią, inaczej pusta
  komórka (kontrakty bez oferty / bez podkategorii). Endpoint dokłada
  `selectinload(Contract.job)` (poza kolumną nic więcej nie ładuje).
- **Tylko eksport** — lista/tabela na ekranie bez zmian (zgodnie ze zgłoszeniem).
- **Testy**: kolejność 8 kolumn, wartość „Podkategoria" (z ofertą i pusta bez),
  round-trip xlsx (openpyxl czyta pustą komórkę jako `None`). Pełny pakiet
  `test_contract*` zielony (200), bez regresji.
