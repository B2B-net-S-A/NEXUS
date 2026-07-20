# NEXUS — szczegółowy plan implementacyjny statystyk dla Claude Code

**Data przygotowania:** 2026-07-16  
**Repozytorium:** `/Users/arturtwardowski/NEXUS`  
**Zakres:** bezpieczeństwo statystyk, Analytics v1, KPI Coach v2, finanse i delivery, frontend, migracja DynaReportera, CI oraz rollout produkcyjny  
**Wykonawca:** Claude Code  
**Status dokumentu:** gotowy do realizacji etapami; nie jest zgodą na destrukcyjne operacje produkcyjne ani rotację sekretów

---

## 1. Cel biznesowy

NEXUS ma zostać jedynym, spójnym źródłem bieżących statystyk operacyjnych,
rekrutacyjnych, delivery i finansowych. Wszystkie dashboardy, raporty, KPI,
konkursy oraz alerty mają korzystać z tych samych definicji i tych samych danych
źródłowych.

Docelowo:

- live ATS jest jedynym źródłem bieżących danych;
- DynaReporter jest źródłem wyłącznie nieodtwarzalnej historii sprzed cutoveru;
- InfraReporter nie jest osobnym źródłem danych ani elementem dashboardu;
- `UserActivity` pozostaje logiem pomocniczym, ale nie służy do liczenia
  performance;
- backend jest jedynym źródłem prawdy dla uprawnień analytics;
- `user` widzi wyłącznie bezpieczne agregaty bez PII i danych finansowych;
- finanse widzą wyłącznie `admin` i `delivery_lead`;
- produkcja jest wdrażana małymi PR-ami, każdy z osobnym CI, deployem,
  healthcheckiem SHA oraz weryfikacją Chrome.

---

## 2. Zweryfikowany punkt startowy

Stan poniżej został zweryfikowany 2026-07-16. Claude przed rozpoczęciem musi
wykonać ponowny `git fetch origin`, ponieważ `main` szybko się zmienia.

| Element | Stan podczas audytu |
|---|---|
| `origin/main` | `7aaeb858b43d47dbe130dc7c79a6db98010c54ce` |
| Produkcja | zdrowa na `a301ee433e7e298d16529352590dabea654f3db5` |
| Różnica produkcja → `main` | 13 commitów |
| CI dla `7aaeb85` | zielone |
| Deploy dla `7aaeb85` | nieudany; produkcja pozostała na `a301ee4` |
| PR #702 | scalony jako `37335e7`, następnie wycofany przez PR #713 |
| Revert Analytics v1 | `d507d95` |
| PR #710 | otwarty, przestarzały, nie powinien być mergowany |
| Nightly E2E | czerwone z powodu braku `frontend/e2e/.auth/state.json` |
| `/api/health` | `healthy`; DB healthy, CloudTalk unhealthy, Traffit degraded |

### 2.1. Najważniejszy wniosek

Implementacja Analytics v1 z PR #697, #699 i #702 **nie znajduje się na
aktualnym `main`**. PR #713 usunął między innymi:

- `backend/app/analytics/`;
- `backend/app/api/analytics_v1.py`;
- `backend/app/api/analytics_cutovers.py`;
- `backend/app/services/analytics_v1/`;
- migracje Analytics v1;
- shadow comparison;
- testy analytics/RBAC/OpenAPI;
- frontendowy klient analytics, generowane typy i `StatsBoundary`.

Commity:

- `ae5a300` — pierwsza konsolidacja analytics;
- `7247365` — poprawki okresów i źródeł;
- `37335e7` — finanse i shadow parity;

mogą być używane wyłącznie jako materiał referencyjny. Nie wolno ich zbiorczo
cherry-pickować. Kod musi zostać przeniesiony selektywnie na aktualny `main`,
małymi PR-ami i z ponowną oceną każdej zmiany.

### 2.2. Co można wykorzystać z aktualnego `main`

- Multi-role:
  - `backend/app/models/user.py`: `get_all_roles`, `has_role`, `has_any_role`;
  - `backend/app/api/deps.py`: `require_roles` respektuje role dodatkowe.
- Modele danych:
  - `CandidateStage`;
  - `Call.status` i `Call.started_at`;
  - `CandidateSourceEvent`;
  - `Job.close_reason`;
  - kontrakty i harmonogramy stawek.
- Częściowo poprawne KPI:
  - `backend/app/services/kpi_panel.py`;
  - `backend/app/services/kpi_team.py`.
- Istniejące widoki UI:
  - `frontend/src/components/insights/`;
  - `frontend/src/components/v2/kpi/MojeKpiPanel.tsx`;
  - `frontend/src/components/v2/kpi/TeamKpiPanel.tsx`;
  - `frontend/src/components/v2/dashboard/WidgetState.tsx`.
- Częściowo istniejący guard finansowy:
  - `backend/app/api/financial_access.py`.

Elementy te są bazą do refaktoryzacji, ale nie stanowią gotowego kontraktu
Analytics v1.

---

## 3. Krytyczne problemy stanu obecnego

### 3.1. Bezpieczeństwo i RBAC — P0

1. Sekret InfraReporter znajduje się literalnie w:
   - `backend/app/services/infrareporter.py`.
2. Rola `user` nadal może dotrzeć do danych zabronionych przez:
   - `backend/app/api/activities.py`;
   - `backend/app/api/dashboard.py`;
   - `backend/app/api/contracts.py`;
   - `backend/app/api/invoices.py`;
   - `backend/app/api/client_orders.py`;
   - `backend/app/api/client_framework_contracts.py`;
   - `backend/app/api/rate_benchmarks.py`;
   - `backend/app/api/clients.py`.
3. DynaReporter nie ma centralnego `require_dynareporter_section()`.
4. `allowed_sections` jest używane głównie po stronie UI, a nie jako
   nieprzekraczalny guard backendowy.
5. Szczególnie niebezpieczne legacy reads są chronione tylko przez
   `CurrentUser`:
   - `backend/app/api/dynareporter_clients_mrr.py`;
   - `backend/app/api/dynareporter_przetargi.py`;
   - `backend/app/api/dynareporter_delivery_lead_dashboard.py`.
6. TAC może zobaczyć finanse przez legacy `/reports` i frontend Insights.
7. HoR może otrzymać P&L w części dashboardów Dyna/My Clients.
8. Upload XLSX jest nadal aktywny i zwraca pozorny sukces.
9. `/api/kpis/users/{id}/today` ma IDOR — dostęp jest zbyt szeroki.
10. `/api/admin/snapshot` wywołuje JWT dependency niepoprawną sygnaturą.
11. `backend/tests/test_rbac.py` dopuszcza HTTP 500 jako akceptowalny wynik
    testu odmowy dostępu.

### 3.2. Błędne lub niespójne statystyki — P1

- pipeline funnel liczy historyczne ruchy, a nie ostatni stage;
- `/reports/recruitment` wielokrotnie liczy przejścia tego samego kandydata;
- KPI ma arbitralny lookback 400 dni i może utracić właściwego weryfikatora;
- konkursy mają inne reguły atrybucji niż KPI;
- źródła nie stosują konsekwentnego first-touch;
- numerator źródeł nie zawsze jest distinct, przez co hire rate może
  przekroczyć 100%;
- raporty używają rolling UTC zamiast kalendarzowych okresów Warsaw;
- trend DL nie stosuje poprawnie górnej granicy miesiąca;
- przetargi ignorują `Job.close_reason`;
- dashboard nie rozdziela wszystkich i aktywnych klientów;
- część snapshotów nie zwraca prawdziwego `jobs.total`.

### 3.3. KPI Coach i Power Calling — P1

- stary Coach nadal liczy `UserActivity`;
- stary task wysyłający nudges jest uruchamiany bez właściwego rollout gate;
- „Power Calling” nadal bywa liczone jako weryfikacje;
- rozmowy bywają liczone po `created_at` zamiast
  `COALESCE(started_at, created_at)`;
- wyłączony CloudTalk może wyglądać jak zero wykonanych rozmów;
- brakuje niezależnych targetów rozmów i weryfikacji.

### 3.4. Finanse i delivery — P1/P2

- brak kursu FX może prowadzić do nominalnego przeliczenia 1:1;
- `Decimal` jest miejscami konwertowany do `int`;
- różne waluty mogą być sumowane bez obowiązkowej konwersji;
- bench i utilization są liczone na złych populacjach;
- część raportów używa statusu kontraktu zamiast dat obowiązywania;
- `client_orders.filled_at` nie istnieje;
- czas wypełnienia zamówienia jest estymowany przez proxy udające fakt;
- brak audytowanych `financial_adjustments`;
- brak rozdzielenia DTO operacyjnych i finansowych.

### 3.5. Frontend — P1/P2

- brak `/dashboard?view=operations|recruitment|delivery|executive`;
- brak `analytics_capabilities` i fail-closed query gating;
- TAC widzi komponenty zawierające MRR, marżę i wartości przetargów;
- brak jednego `statsApi` i typów z OpenAPI;
- `WidgetState` nie obsługuje pełnego zestawu stanów jakości;
- okres jest przechowywany lokalnie zamiast w URL;
- selektor okresu wpływa pozornie na widgety o stałym zakresie;
- `DashboardV2` generuje syntetyczne sparklines i trendy;
- health widget ma twardo zdrowe integracje zamiast danych z `/api/health`;
- ostatnie zatrudnienia są filtrowane z luźnego activity feed;
- stary `MyKpiWidget` współistnieje z nowymi panelami KPI;
- pełny stary UI DynaReportera i upload nadal istnieją.

---

## 4. Docelowa architektura

### 4.1. Źródło prawdy

Live ATS jest jedynym źródłem bieżących danych. DynaReporter przechowuje
wyłącznie nieodtwarzalne dane historyczne sprzed jawnego cutoveru.

`UserActivity` może być używane do audytu zachowania użytkownika, ale nie do
liczenia KPI, konkursów, performance lub alertów.

### 4.2. Kanoniczne definicje metryk

| Metryka | Definicja |
|---|---|
| Aktualny pipeline | ostatni `CandidateStage` dla kandydat × job |
| Weryfikacja | pierwsze osiągnięcie `verified` |
| Rekomendacja | pierwsze osiągnięcie `cv_sent` |
| Interview wewnętrzny | pierwsze osiągnięcie `interview` |
| Interview klienta | pierwsze osiągnięcie `client_interview` |
| Placement | pierwsze osiągnięcie `hired` |
| Atrybucja KPI | osoba pierwszej weryfikacji; bez weryfikacji wykonawca milestone |
| Rozmowa | `Call.status=completed`, data `COALESCE(started_at, created_at)` |
| Źródło | pierwszy `CandidateSourceEvent`; fallback `Candidate.source` |
| Aktywny kontrakt | date-effective `start_date/end_date`, a nie sam status |
| Bench | kandydat miał kontrakt, ale obecnie nie ma aktywnego |
| Wynik przetargu | `Job.close_reason`; brak powodu = `unknown` |
| Finanse | `Decimal`, obowiązkowa konwersja do PLN po kursie raportowym |

Wszystkie okresy używają:

- `Europe/Warsaw`;
- przedziałów `[start, end)`;
- kalendarzowych granic dnia, tygodnia, miesiąca, kwartału i roku;
- custom period maksymalnie 366 dni.

### 4.3. Macierz dostępu

| Zakres | user | recruiter/sourcer | TAC | DL | HoR | admin |
|---|---:|---:|---:|---:|---:|---:|
| Agregaty operacyjne bez PII | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Własne KPI rekrutacyjne | – | ✓ | ✓ | – | – | – |
| Własne KPI delivery | – | – | – | ✓ | – | – |
| Imienny ranking rekrutacji | – | ✓ | ✓ | ✓ | ✓ | ✓ |
| KPI innej osoby | – | self | self | przypisany zespół | recruitment | organizacja |
| Klienci/delivery bez finansów | – | – | ✓ | ✓ | ✓ | ✓ |
| Stawki, MRR, marża, P&L | – | – | – | ✓ | – | ✓ |
| Przetargi bez wartości | – | – | ✓ | ✓ | – | ✓ |
| Administracja i korekty | – | – | – | – | – | ✓ |

Backend definiuje capability enum. `/api/auth/me` zwraca
`analytics_capabilities`. Frontend używa capability do routingu, renderowania i
`enabled` w zapytaniach.

Multi-role oznacza sumę capability przez `has_any_role`, ale nigdy nie poszerza
automatycznie zakresu klienta lub zespołu.

### 4.4. API Analytics v1

Przestrzeń: `/api/analytics/v1`.

Viewer-safe:

- `/overview`;
- `/pipeline/snapshot`;
- `/recruitment/funnel`;
- `/sources`;
- `/calls/aggregate`.

Osobiste:

- `/me/kpis`;
- `/me/calls`.

Managerskie:

- `/team/kpis`;
- `/team/calls`;
- `/delivery-leads/performance`;
- `/recruitment/users/{id}`.

Klienci:

- `/clients/{id}/operations`;
- `/clients/{id}/finance`.

Finanse i zarząd:

- `/finance/summary`;
- `/finance/trend`;
- `/finance/clients`;
- `/executive/board`;
- `/commercial/tenders`.

Definicje:

- `/meta/metrics`.

### 4.5. Wspólna koperta odpowiedzi

```json
{
  "schema_version": "1",
  "metric_version": "...",
  "generated_at": "...",
  "scope": {},
  "period": {
    "kind": "month",
    "start": "...",
    "end": "...",
    "timezone": "Europe/Warsaw"
  },
  "quality": {
    "status": "complete",
    "warnings": [],
    "source_watermarks": {}
  },
  "data": {}
}
```

Dozwolone quality status:

- `complete`;
- `partial`;
- `unavailable`.

Kwoty są zwracane jako decimal string z walutą `PLN`.

### 4.6. Cache

Każdy klucz cache musi zawierać co najmniej:

- metric version;
- endpoint/moduł;
- capability set;
- organization/team/client/user scope;
- period start/end/timezone;
- wszystkie filtry wpływające na wynik.

Nie wolno cache'ować odpowiedzi managerskiej lub finansowej pod globalnym
kluczem współdzielonym z viewer-safe.

---

## 5. Zasady wykonania przez Claude

1. Przeczytać aktualny `AGENTS.md` przed pierwszą zmianą.
2. Wykonać:

   ```bash
   git fetch origin
   git log origin/main..HEAD
   git status --short --branch
   ```

3. Nie pracować w brudnym głównym checkoutcie. Utworzyć osobny worktree i
   branch z aktualnego `origin/main`.
4. Nie używać lokalnego Dockera.
5. Nie wykonywać wielu niezależnych zmian w jednym PR.
6. Każdy PR:
   - focused diff;
   - host-native testy;
   - push task branch;
   - PR;
   - zielone CI;
   - squash merge;
   - deploy;
   - healthcheck z dokładnym SHA;
   - Chrome dla zmian widocznych dla użytkownika.
7. GitHub writes wykonywać przez `codex-gh` jako Dynaminds Codex Bot.
8. Nie zmieniać ochrony `main` i nie wykonywać direct push.
9. Nie cherry-pickować całego `37335e7`.
10. Nie deklarować pełnego zakończenia przed zakończeniem shadow i canary.

---

## 6. Szczegółowy plan PR-ów

## PR 0 — naprawa pipeline deploymentu

**Proponowany branch:** `fix/deploy-coolify-status-gate`

### Cel

Przywrócić gwarancję, że zielony commit `main` faktycznie trafia na produkcję.
Bez tej bramy dalsze prace analytics nie są dostarczalne.

### Zadania

1. Sprawdzić status i logi ostatnich deployment UUID w Coolify.
2. Ustalić, dlaczego webhook zwraca `200` i `deployment queued`, ale produkcja
   pozostaje na `a301ee4`.
3. Nie naprawiać problemu wyłącznie przez zwiększenie `sleep` lub liczby prób.
4. Workflow powinien:
   - zapisać deployment UUID;
   - odpytywać status konkretnego deploymentu;
   - przerwać natychmiast przy `failed/cancelled`;
   - wypisać bezpieczny, zredagowany powód błędu;
   - dopiero po sukcesie rozpocząć healthcheck.
5. Dodać `User-Agent: dynaminds-smoke-test/1.0` do każdego smoke curl.
6. Zachować wymaganie exact seven-character SHA.
7. Naprawić tworzenie `frontend/e2e/.auth/state.json` w nightly E2E.
8. PR #710 oznaczyć jako obsolete i zamknąć po sprawdzeniu diffu.

### Testy

- shellcheck/syntax workflow;
- uruchomienie workflow na task commit;
- kontrolowany deploy aktualnego `main`;
- `/api/health` i `/api/health/deep`;
- potwierdzenie, że wersja jest równa oczekiwanemu SHA.

### Kryteria akceptacji

- produkcja nie jest starsza od `main`;
- workflow odróżnia queued/running/success/failed;
- brak fałszywie zielonego deployu;
- nightly E2E nie pada z powodu braku storage state.

### Rollback

Zmiana workflow może zostać wycofana niezależnie od kodu aplikacji. Nie
wycofywać poprawnie wdrożonego kodu tylko dlatego, że monitoring workflow ma
błąd.

---

## PR 1 — R0 security containment

**Proponowany branch:** `fix/analytics-r0-security-containment`

### Cel

Natychmiast zamknąć wycieki danych bez czekania na Analytics v1.

### Backend

1. Dodać capability enum, np.:
   - `VIEW_OPERATIONAL_AGGREGATES`;
   - `VIEW_OWN_RECRUITMENT_KPI`;
   - `VIEW_OWN_DELIVERY_KPI`;
   - `VIEW_RECRUITMENT_RANKING`;
   - `VIEW_TEAM_KPI`;
   - `VIEW_CLIENT_OPERATIONS`;
   - `VIEW_FINANCE`;
   - `VIEW_TENDERS_OPERATIONAL`;
   - `ADMIN_ANALYTICS`.
2. Dodać centralne dependency guards. Nie mogą być wyłączane feature flagem.
3. Rozszerzyć `/api/auth/me` o `analytics_capabilities`.
4. Ograniczyć wszystkie endpointy wymienione w sekcji 3.1.
5. Dodać `require_dynareporter_section(section)`:
   - wynik = capability ∩ `allowed_sections`;
   - sekcja nigdy nie zwiększa prawa wynikającego z roli;
   - puste lub błędne `allowed_sections` oznacza brak dostępu.
6. Wszystkie Dyna writes ograniczyć do admina.
7. XLSX upload zwraca `410 Gone` i nie zapisuje żadnej historii sukcesu.
8. Naprawić IDOR KPI:
   - self;
   - admin/HoR zgodnie z zakresem;
   - DL tylko przypisany zespół.
9. Naprawić JWT auth admin snapshot.
10. Wyłączyć emisję starego KPI Coach, ale nie usuwać historii notyfikacji.
11. Usunąć literal sekretu InfraReporter z kodu.

### Frontend

1. Usunąć TAC dostęp do `SalesOverview`, finansowego Board i kwot przetargów.
2. Wyłączyć upload Dyna i pokazać czytelny stan `Gone/wycofane`.
3. Usunąć:
   - stałe trendy `+8/+5/-2/+12`;
   - syntetyczne sparklines;
   - hardcoded healthy status;
   - liczbowe fallbacki dla błędu API.
4. Nie wykonywać requestów do zabronionych endpointów.

### Testy

- wszystkie role i role hybrydowe;
- secondary admin;
- DL+TAC;
- HoR+Recruiter;
- self/in-team/out-of-team;
- puste, błędne i nieznane `allowed_sections`;
- brak PII/IDs/client names/finance w viewer-safe;
- żadnego testu akceptującego HTTP 500 jako odmowę dostępu;
- frontend: brak zakazanego requestu, nie tylko ukryty komponent.

### Kryteria akceptacji

- zero nieautoryzowanych `2xx`;
- `user` otrzymuje wyłącznie agregaty operacyjne;
- TAC i HoR nie otrzymują finansów;
- upload Dyna zawsze `410`;
- stary nudge task nie emituje nowych powiadomień.

### Operacja wymagająca potwierdzenia

Po usunięciu sekretu z kodu Claude ma zatrzymać się przed właściwą rotacją
InfraReporter i poprosić o jednoznaczne potwierdzenie. Nowy sekret trafia do
Coolify vault, nigdy do repozytorium lub logów.

---

## PR 2 — fundament danych Analytics v1

**Proponowany branch:** `feat/analytics-v1-foundation`

### Cel

Utworzyć bezpieczny, testowalny fundament bez jeszcze pełnej migracji UI.

### Zadania bazodanowe

1. Odczytać aktualne `alembic heads` po synchronizacji z `origin/main`.
2. Utworzyć addytywną migrację na aktualnym grafie.
3. Dodać indeksy dla:
   - latest stage po candidate/job/date/id;
   - pierwszych milestone;
   - calls status/user/started_at/created_at;
   - source events candidate/captured_at/id;
   - date-effective contracts;
   - job close reason;
   - team/client assignments.
4. Utworzyć zwykłe SQL views:
   - `analytics_current_pipeline`;
   - `analytics_first_milestones`;
   - `analytics_candidate_first_sources`.
5. Nie tworzyć materialized views bez pomiaru query plan i p95.
6. Każdy nowy obiekt odzwierciedlić idempotentnie w
   `backend/entrypoint.sh` zgodnie z migration trap NEXUS.

### Moduły backendowe

Odtworzyć jako nową implementację:

- `backend/app/analytics/capabilities.py`;
- `backend/app/analytics/periods.py`;
- `backend/app/analytics/scope.py`;
- `backend/app/analytics/cache.py`;
- `backend/app/analytics/schemas.py`.

### Flagi

- `ANALYTICS_V1_MODE=off|shadow|live`;
- lista aktywnych modułów;
- `DYNAREPORTER_MODE=read_only|off`;
- `KPI_COACH_V2_NUDGES_ENABLED=false` domyślnie.

### Testy

- DST spring/fall Warsaw;
- leap year;
- granice dnia/tygodnia/miesiąca/kwartału/roku;
- custom bez from/to;
- custom >366 dni;
- dokładnie jeden Alembic head;
- migracja od pustej bazy;
- migracja od prod-like bazy;
- idempotencja entrypoint statements;
- query plan i podstawowe p95 na fixture dataset.

### Kryteria akceptacji

- nowe views zwracają poprawne rekordy na fixture z powtórzonymi stage;
- okresy zawsze są timezone-aware i `[start,end)`;
- cache nie współdzieli odpowiedzi między rolami/scope;
- migracja nie wymaga downgrade ani usuwania danych.

---

## PR 3 — API Analytics v1 i adaptery legacy

**Proponowany branch:** `feat/analytics-v1-api`

### Cel

Dostarczyć wersjonowany kontrakt bez przełączania całego frontendu.

### Backend

1. Dodać router `/api/analytics/v1` z endpointami z sekcji 4.4.
2. Każdy endpoint zwraca wspólną kopertę.
3. `quality` ma propagować:
   - brak CloudTalk;
   - brak kursu FX;
   - niepełną historię `filled_at`;
   - niesynchronizowane źródło;
   - watermark danych.
4. `/meta/metrics` opisuje definicję, jednostkę, source i metric version.
5. Stare `/dashboard`, `/reports`, `/kpis`, `/competitions` stają się
   adapterami do nowego serwisu.
6. Adaptery otrzymują nagłówki:
   - `Deprecation`;
   - `Sunset`;
   - `Link`.
7. Nie zmieniać jeszcze aktywnej odpowiedzi starego frontendu w shadow mode.

### Testy

- kontrakt każdej koperty;
- role/capabilities/scope;
- viewer-safe field denylist;
- cache isolation;
- invalid period;
- brak kursu/CloudTalk/source watermark;
- stare endpointy i nowy serwis zwracają porównywalne wartości.

### Kryteria akceptacji

- OpenAPI zawiera kompletny Analytics v1;
- viewer-safe schemat fizycznie nie ma pól finansowych;
- finanse mają osobne schemas;
- adapter nie implementuje drugiej kopii logiki metryk.

---

## PR 4 — poprawność metryk i KPI Coach v2

**Proponowany branch:** `feat/analytics-canonical-metrics-kpi-v2`

### Cel

Przepiąć wszystkie performance metrics na kanoniczne dane ATS.

### Metryki operacyjne

1. Pipeline = latest stage.
2. Milestone liczony raz dla candidate × job.
3. Ostatnie zatrudnienia z dedykowanego typed endpointu.
4. `jobs.total` jest prawdziwym total.
5. Rozdzielić `clients.total` i `clients.active`.
6. Trend DL stosuje start i end każdego miesiąca.
7. Sources liczą distinct candidates w numerator i denominator.
8. Tenders używają `close_reason`, brak = `unknown`.
9. Konkursy korzystają z tej samej funkcji milestone i attribution co KPI.

### Calls i Power Calling

1. Completed calls tylko `status=completed`.
2. Data rozmowy = `COALESCE(started_at, created_at)`.
3. Uwzględnić primary i secondary operational roles.
4. CloudTalk off/misconfigured = `quality=unavailable`.
5. Domyślny target rozmów = 15/dzień.
6. Domyślny target weryfikacji = 4/dzień.
7. Targety niezależne i konfigurowalne.

### KPI Coach v2

Metryki:

- zakończone rozmowy;
- pierwsze weryfikacje;
- kandydaci dodani;
- pierwsze rekomendacje;
- pierwsze placementy;
- precision 30 dni.

Target resolution:

1. per-user override;
2. primary operational role default;
3. code fallback.

Secondary role daje dostęp do widoku, ale nie zmienia celu bez override.

### Nudge rollout

1. Dry-run przez siedem pełnych dni.
2. Porównanie dry-run z UI i canonical API.
3. Włączenie wysyłki dopiero po parity.
4. Wyłączenie starego taska po potwierdzeniu v2.

### Testy

- powtórne przejście przez stage;
- cofnięcie stage;
- kandydat bez verified;
- attribution po pierwszym verifier;
- source rate ≤100%;
- completed vs initiated/failed calls;
- started_at null fallback;
- CloudTalk unavailable;
- target override i secondary role;
- precision zero denominator.

---

## PR 5 — frontend Analytics v1

**Proponowany branch:** `feat/analytics-v1-frontend`

### Cel

Zastąpić rozproszone legacy queries jednym, capability-aware frontendem.

### Kontrakt i klient

1. Dodać `frontend/src/lib/stats-api.ts`.
2. Generować typy z backendowego OpenAPI.
3. Dodać skrypty generate/check i blocking CI.
4. Rozszerzyć auth store o `analytics_capabilities`.
5. Dodać `hasAnalyticsCapability()`.
6. Auth hydration jest fail-closed.
7. Query `enabled` dopiero po potwierdzeniu capability.

### StatsBoundary

Obsłużyć:

- loading;
- refreshing;
- error;
- forbidden;
- empty;
- stale;
- partial;
- disabled;
- unconfigured;
- unavailable.

Nie wolno zamieniać error/unavailable na `0`.

### Routing

- `/dashboard?view=operations|recruitment|delivery|executive`;
- `/insights?tab=rekrutacja|klienci|zarzad&period=...`;
- priorytet default view:
  `admin → HoR → DL → TAC → recruiter/sourcer → user`;
- przełącznik tylko dla kont wielorolowych;
- nie renderować ani nie pobierać panelu bez capability.

### KPI UI

Zastąpić:

- `MyKpiWidget`;
- `MojeKpiPanel`;
- `TeamKpiPanel`;

przez:

- `PersonalKpiCoach`;
- `TeamKpiCoachSummary`.

### Okresy

1. URL jest jedynym źródłem prawdy.
2. Back/forward odtwarza okres.
3. Widget o stałym zakresie ma badge `YTD`, `30 dni`, `180 dni`.
4. Globalny selector nie może zmieniać pozornie widgetu, który nie wspiera
   wybranego okresu.

### Dashboardy

- Operations: viewer-safe agregaty.
- Recruitment: funnel, sources, KPI, recent hires.
- Delivery: dane klientów bez kwot dla TAC/HoR.
- Executive: admin/DL, finanse PLN.
- Health: wyłącznie `/api/health`.

### Testy

- Vitest/MSW wszystkie boundary states;
- invalid contract;
- stale/partial/unavailable;
- brak requestu bez capability;
- konta hybrydowe;
- URL period/back-forward;
- brak syntetycznych danych;
- screenshot głównych widoków.

---

## PR 6 — finanse, delivery i klient

**Proponowany branch:** `feat/analytics-finance-delivery`

### Cel

Zapewnić matematycznie poprawne i bezpieczne raporty finansowe.

### Zadania

1. Wszystkie obliczenia jako `Decimal`.
2. Wszystkie odpowiedzi finansowe jako decimal strings + `PLN`.
3. Brak kursu NBP = `quality=unavailable`.
4. Zakaz nominalnego sumowania walut.
5. Date-effective MRR.
6. Prawdziwa arytmetyka miesięcy.
7. Utilization denominator = właściwa populacja konsultantów.
8. Bench = historyczny kontraktor bez aktywnego kontraktu dziś.
9. Expiring = `[today,today+30d]`.
10. Rzeczywiste `COUNT(order.id)`.
11. Margin percentage = miesięczna marża / miesięczny przychód.
12. Dodać `client_orders.filled_at`:
    - ustawiane przy pierwszej aktywacji;
    - historyczne braki pozostają `NULL` i `partial`;
    - zakaz estymatu przedstawianego jako fakt.
13. Dodać `financial_adjustments`:
    - immutable audit trail;
    - `draft/approved`;
    - admin-only write;
    - admin/DL read.
14. Osobne DTO operations i finance.

### Testy

- PLN/EUR/USD;
- brak kursu;
- grosze i rounding;
- miesiące 28/29/30/31 dni;
- kontrakt przyszły/wygasły/bez end date;
- bench historyczny;
- zero revenue;
- adjustment draft/approved;
- TAC/HoR nie otrzymują żadnego pola finansowego.

### Kryteria akceptacji

- różnica finansowa shadow ≤1 PLN;
- brak `float` i `int` w agregacji pieniężnej;
- finance schemas są niemożliwe do użycia przez viewer-safe router.

---

## PR 7 — snapshoty, cutover i wygaszenie DynaReportera

**Proponowany branch:** `feat/analytics-dynareporter-cutover`

### Cel

Przenieść nieodtwarzalną historię i wygasić stary system bez overlapu danych.

### Modele

- `analytics_metric_snapshots` — immutable;
- `analytics_cutovers` — moduł, cutover date, legacy/live metadata.

### Backfill

1. Migrować tylko historię nieodtwarzalną z ATS, głównie stare Board/P&L.
2. Dane odtwarzalne pozostają live.
3. Backfill:
   - idempotentny;
   - batchowany;
   - checksum per batch/metric/period;
   - raport pominiętych rekordów;
   - bez nadpisywania snapshotów.
4. Cutover na początek pełnego miesiąca Warsaw.
5. Resolver:
   - przed cutoverem → legacy snapshot;
   - od cutoveru → live ATS;
   - bez sumowania obu źródeł.

### Redirecty

Najpierw `307`:

- recruitment/body-leasing/placements/competitions →
  `/insights?tab=rekrutacja`;
- delivery/clients/sales → `/insights?tab=klienci`;
- board/przetargi → `/insights?tab=zarzad`;
- admin/upload → `/settings/data-imports`;
- Mindy → `/assistant`.

Po potwierdzonej parity zmiana na `308`.

### Legacy lifecycle

1. Legacy reads przez dwa wydania jako zabezpieczone adaptery.
2. Legacy writes po freeze zawsze `410`.
3. Telemetria ruchu legacy bez PII.
4. InfraReporter usunąć z dashboardu natychmiast.
5. Routery i komponenty usunąć po 30 dniach bez istotnego ruchu.
6. `dr_*` i `allowed_sections` usunąć dopiero po:
   - 90 dniach stabilności;
   - backupie;
   - udanym restore drill;
   - osobnej zgodzie na destrukcyjną migrację.

### Testy

- idempotentny backfill;
- checksum mismatch;
- skipped record report;
- brak overlap legacy/live;
- granica cutover Warsaw;
- redirect 307/308;
- write 410;
- adapter RBAC;
- brak podwójnego liczenia.

---

## PR 8 — pełne CI i obserwowalność analytics

**Proponowany branch:** `test/analytics-release-gates`

### CI blocking job

Python 3.12 + Postgres:

- analytics unit/integration;
- RBAC matrix;
- migracje;
- dokładnie jeden Alembic head;
- OpenAPI;
- viewer-safe schemas;
- cache isolation;
- idempotentny backfill.

Frontend:

- wygenerowane typy zgodne z OpenAPI;
- MSW states;
- invalid contract;
- brak forbidden requests;
- token guard i standardowe lint/type-check/test/build.

Playwright PR smoke:

- siedem ról;
- bezpośrednie URL;
- dashboard default view;
- podstawowa redakcja finansów;
- Dyna redirects.

Nightly:

- konta hybrydowe;
- impersonation;
- self/in-team/out-of-team;
- okres URL/back-forward;
- pełna macierz dashboardów;
- legacy adapters;
- screenshoty i trace.

CI musi blokować:

- więcej niż jeden Alembic head;
- nieautoryzowane `2xx`;
- HTTP 500 zaakceptowane jako odmowa;
- zmianę OpenAPI bez aktualizacji typów;
- CurrentUser-only mutation w analytics/Dyna;
- viewer-safe DTO z zakazanym polem.

### Obserwowalność

Monitorować:

- latency p50/p95/p99;
- 5xx;
- cache hit/miss;
- data freshness;
- source watermarks;
- shadow diff;
- 401/403;
- legacy traffic;
- nudge dry-run/send;
- unavailable/partial per module;
- deployment SHA drift.

---

## 7. Shadow comparison

Shadow nie może zależeć wyłącznie od ruchu użytkowników.

Należy zapisać dzienne dowody porównania przynajmniej dla:

- candidates total/active;
- jobs total/open;
- clients total/active;
- current pipeline;
- funnel milestones;
- placements;
- sources;
- calls;
- contracts active/expiring;
- MRR/revenue/margin;
- tenders outcomes;
- team row sum vs total.

Status per metryka:

- `identical`;
- `within_tolerance`;
- `mismatch`;
- `unavailable`.

Każdy rekord zawiera:

- observed Warsaw day;
- metric version;
- legacy/live values;
- absolute i relative diff;
- source watermarks;
- warnings;
- first/last observed timestamp.

Shadow trwa minimum siedem pełnych dni. Restart aplikacji nie może wyzerować
historii dowodowej.

---

## 8. Rollout produkcyjny

### Etap 1 — R0

Security containment, redakcja i usunięcie sekretu z kodu trafiają od razu po
zielonym CI. Rollback nie może przywrócić starego RBAC ani dostępu `user`.

### Etap 2 — shadow

- `ANALYTICS_V1_MODE=shadow`;
- minimum siedem pełnych dni;
- brak zmiany odpowiedzi starego frontendu;
- codzienny raport parity.

### Etap 3 — canary

1. admin — 48 godzin;
2. DL/HoR — 48 godzin;
3. TAC/recruitment — 72 godziny;
4. `user` dopiero po pełnych testach redakcji.

### Etap 4 — cutover gates

Cutover wyłącznie gdy:

- zero nieautoryzowanych `2xx`;
- liczniki krytyczne są identyczne;
- różnica ratio ≤0,1 pp;
- różnica finansowa ≤1 PLN;
- team totals = suma wierszy;
- p95 viewer-safe <300 ms przy cache;
- p95 manager/finance <500 ms przy cache;
- brak aktywnego sekretu w repo;
- brak czerwonego deploy/health/E2E gate;
- Chrome potwierdza brak forbidden requests.

### Rollback

Rollback modułowy `live → shadow`, wyłącznie do zabezpieczonych legacy reads.

Rollback nigdy nie przywraca:

- starego RBAC;
- dostępu `user` do danych szczegółowych;
- finansów dla TAC/HoR;
- Dyna writes;
- starego KPI Coach nudger.

---

## 9. Produkcyjna weryfikacja Chrome

Po każdym user-visible deploy użyć zalogowanego profilu Chrome.

### Role

- user;
- recruiter;
- sourcer;
- TAC;
- delivery lead;
- head of recruitment;
- admin;
- co najmniej DL+TAC i HoR+Recruiter.

### Scenariusze

1. Bezpośrednie otwarcie każdego dashboard view.
2. Default view zgodny z priorytetem roli.
3. Przełącznik konta wielorolowego.
4. Zmiana okresu i kontrola URL.
5. Browser back/forward.
6. Loading/refreshing/error/empty/stale/unavailable.
7. CloudTalk off nie pokazuje zera.
8. `user` nie widzi PII, klientów, rankingów lub finansów.
9. TAC nie widzi MRR, stawek, marży, P&L i wartości przetargów.
10. HoR nie widzi finansów.
11. DL widzi finance zgodnie z docelową capability.
12. Admin widzi pełen zakres.
13. Network: brak requestów do endpointów bez capability.
14. Dyna routes przekierowują do właściwych Insights/Settings/Assistant.
15. Health widget zgadza się z `/api/health`.
16. Screenshot kluczowych widoków i stanów błędu.

---

## 10. Wymagane testy domenowe

### Unit

- Warsaw periods;
- DST;
- leap year;
- latest stage;
- first milestone;
- verifier attribution;
- source first-touch;
- tender close reason;
- Decimal/FX;
- zero denominator;
- target resolution.

### Integracyjne Postgres

- dwa pełne miesiące fixture;
- powtórzone stage transitions;
- role i assignments;
- migracja empty/prod-like;
- backfill idempotency;
- cutover boundary;
- brak legacy/live overlap.

### RBAC

- siedem ról;
- role dodatkowe;
- self/team/org;
- client assignment;
- bad/puste sections;
- cache isolation;
- viewer-safe field denylist.

### Frontend

- wszystkie StatsBoundary states;
- invalid response;
- forbidden request suppression;
- capability hydration;
- period URL;
- multi-role routing;
- no fake numeric fallback.

### Snapshot/admin

- snapshot token;
- admin JWT;
- non-admin JWT;
- malformed token;
- brak uznawania 500 za poprawny 403.

---

## 11. Operator actions wymagające osobnego potwierdzenia

Claude nie wykonuje automatycznie bez dodatkowej zgody:

- rotacji sekretu InfraReporter;
- usunięcia danych lub tabel `dr_*`;
- usunięcia `allowed_sections`;
- destrukcyjnej migracji;
- wyłączenia publicznej usługi;
- force-push;
- zmiany ochrony `main`;
- zmian billing/access-control policy poza opisanym kodem RBAC.

---

## 12. Definition of Done

Projekt jest zakończony dopiero, gdy:

- wszystkie PR-y mają focused diff i zielone CI;
- produkcja działa na dokładnym końcowym SHA;
- health i deep health są zielone;
- Analytics v1 jest jedynym źródłem aktywnego UI;
- viewer-safe nie zawiera zakazanych danych;
- canonical metrics są współdzielone przez API/KPI/konkursy/alerty;
- shadow ma siedem pełnych dni dowodów;
- canary zakończyło się dla wszystkich ról;
- finanse spełniają tolerancję ≤1 PLN;
- ratio spełniają tolerancję ≤0,1 pp;
- Chrome został sprawdzony dla siedmiu ról i kont hybrydowych;
- Dyna writes zwracają `410`;
- legacy traffic jest monitorowany;
- nie ma aktywnego sekretu w repo;
- istnieje udokumentowany rollback;
- rozpoczęte są wymagane 30/90-dniowe okna decommission.

Okien 7/30/90 dni nie wolno zastępować jednorazowym testem lub deklaracją.

---

## 13. Instrukcja startowa do wklejenia Claude Code

```text
Zrealizuj plan z:
docs/analytics-statistics-claude-implementation-plan-2026-07-16.md

Zacznij od ponownej weryfikacji origin/main, produkcyjnego /api/health,
/api/admin/snapshot, statusu CI/deploy i aktualnego Alembic graph. Pracuj w
izolowanym worktree utworzonym z aktualnego origin/main. Nie używaj lokalnego
Dockera.

Najpierw wykonaj PR 0 i przywróć pewny deploy exact SHA. Następnie realizuj
PR 1–PR 8 po kolei. Nie merguj PR #710 i nie cherry-pickuj zbiorczo PR #702.
Commity ae5a300, 7247365 i 37335e7 traktuj wyłącznie jako materiał
referencyjny.

Każdy PR: host-native checks, push jako Dynaminds Codex Bot, PR przez codex-gh,
zielone hosted CI, squash merge, deploy, health SHA i produkcyjny Chrome dla
zmian widocznych. Nie kończ pracy po samym merge. Nie deklaruj pełnego
zakończenia przed wymaganym shadow, canary i oknami retencji.

Nie dotykaj niepowiązanych lokalnych plików użytkownika. Nie zmieniaj ochrony
main, nie wykonuj force-push i nie wykonuj destrukcyjnych operacji bez osobnej
zgody.
```

