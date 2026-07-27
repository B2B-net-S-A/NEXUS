# Moduł 7 — Analytics, KPI, raportowanie zarządcze, dashboardy i wygaszanie DynaReportera

## Audyt powdrożeniowy, rekomendacja docelowa i szczegółowy plan implementacyjny dla Claude Code

- Data audytu: 2026-07-16
- Repozytorium: NEXUS
- Bazowy commit głębokiego audytu: b57dbe7f3728d0e1957e90ad67c58ef4f62f1200
- Końcowy re-anchor kodu: origin/main = 5e680f329753c04ec41bb3fa6ad849e4c15a28f6
- Końcowy stan produkcji: wersja 5e680f329753c04ec41bb3fa6ad849e4c15a28f6,
  HTTP 200, status healthy
- Charakter pracy: read-only audit kodu z czystego eksportu origin/main oraz produkcyjnego UI; bez zmian danych i bez implementowania poprawek
- Adresat: Claude Code / Opus realizujący serię małych, odwracalnych PR-ów
- Status wcześniejszego planu Analytics PR0–PR8: wdrożony, lecz niegotowy do przełączenia Analytics v1 na live

---

## Jak korzystać z dokumentu

- Sekcja 1 — decyzja zarządcza i blokery.
- Sekcje 2–5 — zakres, dowody i obecna architektura.
- Sekcje 6–9 — pełny rejestr usterek oraz scenariusze awarii.
- Sekcje 10–22 — model docelowy: metryki, czas, RBAC, finanse, KPI, frontend,
  Dyna, cutover, API, migracje i CI.
- Sekcja 23 — wykonawczy plan 43 PR-ów z testami, akceptacją i rollback.
- Sekcje 24–29 — zależności, migracja danych, testy, obserwowalność i produkcja.
- Sekcja 30 — Definition of Done.
- Sekcja 31 — decyzje wymagające człowieka.
- Sekcja 32 — rekomendowany pierwszy sprint.
- Sekcja 34 — gotowy brief dla Claude Code.

Claude powinien realizować sekcję 23 kolejno, a nie traktować listy usterek jako
zgody na jeden szeroki refactor.

---

## 1. Streszczenie zarządcze

NEXUS ma już dużo więcej niż prototyp analityki. W origin/main istnieją:

- Analytics v1 z centralną kopertą odpowiedzi i capability model,
- kanoniczne okresy Europe/Warsaw,
- dashboard Analytics v1 pod /dashboard,
- stare dashboardy rolowe pod /,
- rozbudowane /insights,
- raporty klientów, rekrutacji, KPI, finansów i kontraktów,
- KPI Coach i cykliczne nudges,
- snapshoty DynaReportera i mechanizm cutover,
- bezpośrednio dostępne ekrany DynaReportera,
- cache, testy release gates i część telemetrii jakości.

Wcześniejsza seria PR0–PR8 była wartościowa. Zamknęła część IDOR-ów, wprowadziła
połówkowo otwarte granice okresów, poprawiła deduplikację etapów, zachowała
Decimal w nowym API, oddzieliła legacy od live na poziomie wyboru źródła i
dodała podstawowe bramki CI.

Nie oznacza to jednak, że moduł jest gotowy. Dzisiejszy system ma trzy
nakładające się prawdy prezentacyjne:

1. stare dashboardy rolowe,
2. /insights,
3. Analytics v1.

Każda warstwa inaczej rozumie okres, rolę, zespół, aktywny kontrakt, przychód,
marżę, źródło kandydata, credit za milestone i stan błędu. DynaReporter jest
opisany jako read-only archive, ale część jego produkcyjnych ekranów nadal
pozwala wprowadzać dane. Analytics v1 ma tryb shadow, który nie wykonuje
porównania ani nie zapisuje parity evidence. Przełączenie flagi na live byłoby
więc zmianą routingu bez dowodu zgodności.

Najważniejszy wniosek:

> Moduł nie potrzebuje kolejnego dashboardu. Potrzebuje jednego katalogu
> metryk, jednej semantyki czasu, jednego modelu scope, jednego silnika
> ekonomiki kontraktu oraz trwałego procesu shadow → canary → live → retire.
> UI może mieć wiele widoków, ale nie może mieć wielu definicji tej samej
> liczby.

### 1.1. Natychmiastowe blokery

Przed jakimkolwiek ANALYTICS_V1_MODE=live trzeba zamknąć co najmniej:

1. Finance API przyjmuje period, ale zwraca stan dzisiejszy opisany wybranym
   okresem.
2. Silnik finansowy ładuje harmonogramy stawek, ale oblicza kwoty z legacy
   kolumn bazowych.
3. Cutover skleja historyczny recognized revenue z nowym MRR, operating margin
   z direct margin oraz konsultantów z kontraktami.
4. Pending lub rejected verification może zostać policzone jako udana
   weryfikacja i przejąć credit za późniejsze milestone.
5. Source analytics pomija kandydatów bez CandidateSourceEvent, mimo że
   migracja obiecuje fallback do Candidate.source.
6. HoR może otrzymać finanse w legacy Insights/Dyna, mimo że nowa macierz nie
   przyznaje mu view_finance.
7. Zwykły user może bezpośrednio otworzyć DynaReporter Rekrutacja i pobrać
   imienne KPI zespołu.
8. Błąd, 403 lub timeout bywa zamieniany na zero, pustą listę albo komunikat
   „wszystko w normie”.
9. DYNAREPORTER_MODE=read_only nie blokuje centralnie zapisów.
10. Shadow mode nie produkuje żadnego trwałego dowodu parity.

### 1.2. Rekomendowana strategia

Nie robić big-bang rewrite. Wdrażać w siedmiu falach:

- Fala A — containment: uprawnienia, prawdziwe stany błędu, blokada zapisów
  Dyna, zamrożenie niebezpiecznego cutover.
- Fala B — kontrakt metryk: typ metryki, okres/as-of, Warsaw clock, definicje,
  lineage, readiness i coverage.
- Fala C — kanoniczne fakty: milestone, źródła, team scope, KPI i targets.
- Fala D — finanse: effective-dated terms, FX, adjustments, snapshoty i
  porównywalny trend.
- Fala E — API i frontend: typowane DTO, codegen, routing, unified widget state,
  URL filters, accessibility.
- Fala F — KPI Coach i operacje: durable evaluation, decision log, outbox,
  leases, canary i prawdziwe liczniki.
- Fala G — shadow evidence, canary, cutover oraz kontrolowane wygaszenie
  DynaReportera i legacy analytics.

Plan poniżej ma 43 sloty PR. Szeroki slot należy podzielić, jeżeli zmienia
jednocześnie migrację, silnik obliczeniowy, API i UI. Kolejność jest ważniejsza
niż liczba PR-ów.

---

## 2. Zakres i granice Modułu 7

### 2.1. W zakresie

Audyt obejmuje:

- katalog i definicje metryk,
- KPI indywidualne, zespołowe i zarządcze,
- funnel, pipeline, time-to-hire i SLA,
- źródła kandydatów i konwersję kohort,
- kontraktowe MRR, marżę, forecast i P&L,
- FX, korekty finansowe i historyczne snapshoty,
- dashboard główny, dashboardy rolowe, /insights i /dashboard,
- Board, Recruitment, Delivery i Client Analytics,
- KPI Coach, progi, targets, nudges i dry-run,
- cache oraz performance reporting,
- capability, resource scope, team scope i multi-role,
- jakość, freshness, lineage, coverage i source watermarks,
- Analytics v1 off/shadow/live,
- snapshot/cutover DynaReportera,
- read-only archive i docelowe usunięcie legacy writers,
- OpenAPI, generowanie typów, CI release gates i E2E role matrix,
- obserwowalność analityki i reconciliation.

### 2.2. Granica z Modułem 1

Moduł 1 pozostaje właścicielem:

- klienta,
- organizacji i kontaktów,
- zapotrzebowania/job,
- client assignment,
- relacji biznesowej.

Moduł 7 może tworzyć read modele klientów, lecz nie powinien definiować
drugiego statusu klienta ani drugiego modelu assignment.

### 2.3. Granica z Modułem 2

Moduł 2 pozostaje właścicielem:

- kandydata,
- PII,
- consent,
- źródeł pochodzenia w modelu domenowym,
- deduplikacji profilu.

Moduł 7 konsumuje bezpieczne fakty i musi anonimizować lub ograniczać wymiary.
Nie może rozszerzać dostępu do PII tylko dlatego, że dane trafiły do raportu.

### 2.4. Granica z Modułem 3

Moduł 3 pozostaje właścicielem:

- matching,
- scoring,
- rekomendacji,
- ewaluacji jakości modelu.

Moduł 7 raportuje wyniki i efekty rekomendacji, lecz nie zmienia algorytmu
scoringowego.

### 2.5. Granica z Modułem 4

Moduł 4 pozostaje właścicielem:

- kanonicznych etapów procesu,
- transition facts,
- submission,
- interview,
- offer,
- acceptance,
- placement i hire.

Moduł 7 musi konsumować ich stabilne semantic keys oraz outcome facts.
Docelowo nie może sam interpretować dowolnej nazwy stage jako milestone.

### 2.6. Granica z Modułem 5

Moduł 5 pozostaje właścicielem:

- umowy,
- effective-dated warunków ekonomicznych,
- onboardingu i offboardingu,
- billing terms,
- aneksów,
- termination i retencji kontraktów.

Moduł 7 nie powinien posiadać osobnego resolvera stawek. Powinien konsumować
kanoniczny ContractEconomicTerms.as_of(date) dostarczony przez Moduł 5 albo
współdzielony kernel.

### 2.7. Granica z Modułem 6

Moduł 6 pozostaje właścicielem:

- zdarzeń dostarczanych przez outbox,
- zadań,
- komunikacji,
- delivery attempts,
- worker leases, heartbeatów i provider operations.

KPI Coach powinien użyć durable decision/outbox/lease z Modułu 6. Nie należy
tworzyć drugiego, gorszego systemu dystrybucji tylko dla KPI.

---

## 3. Źródła dowodowe i ograniczenia

### 3.1. Kod

Głęboki audyt wykonano na czystym eksporcie:

- origin/main: b57dbe7f3728d0e1957e90ad67c58ef4f62f1200,
- bez polegania na brudnym lokalnym checkout,
- bez modyfikowania istniejących plików aplikacji.

Przed zamknięciem raportu ponownie pobrano origin/main. Repo przesunęło się do
5e680f329753c04ec41bb3fa6ad849e4c15a28f6. Pomiędzy tymi commitami zmieniono
obszar client contract amendments i dodano jeden test do selektywnej listy CI.
Spośród audytowanych plików Modułu 7 zmienił się tylko workflow CI o tę jedną
pozycję; nie zamyka to żadnego opisanego tutaj problemu Analytics.

Najważniejsze obszary kodu:

- backend/app/analytics,
- backend/app/api/analytics_v1.py,
- backend/app/api/kpis.py,
- backend/app/services/kpi_engine.py,
- backend/app/services/kpi_panel.py,
- backend/app/services/kpi_team.py,
- backend/app/services/kpi_coach_service.py,
- backend/app/services/analytics_snapshots.py,
- backend/app/api/contract_analytics.py,
- backend/app/models/contract.py,
- backend/app/models/financial_adjustment.py,
- backend/app/api/dynareporter_*.py,
- frontend/src/lib/stats-api.ts,
- frontend/src/components/v2/pages/AnalyticsDashboard.tsx,
- frontend/src/components/v2/pages/DashboardV2.tsx,
- frontend/src/components/insights,
- frontend/src/app/dynareporter,
- frontend/src/store/auth.ts,
- frontend/src/middleware.ts,
- testy analytics, KPI, finance, Contract Analytics i release gates.

### 3.2. Produkcja

Na początku audytu /api/health zwracał:

- HTTP 200,
- status healthy,
- version b57dbe7f3728d0e1957e90ad67c58ef4f62f1200,
- database healthy,
- M365 healthy,
- CloudTalk unhealthy,
- Traffit degraded.

Końcowy healthcheck po re-anchor zwrócił:

- HTTP 200,
- status healthy,
- version 5e680f329753c04ec41bb3fa6ad849e4c15a28f6,
- deployedAt 2026-07-16T15:07:51Z,
- database healthy,
- CloudTalk unhealthy,
- Traffit degraded.

Kod i produkcja były więc na tym samym końcowym SHA.

To ważne dla interpretacji jakości danych. Zielony ogólny health nie oznacza,
że wszystkie źródła metryk są świeże i kompletne.

### 3.3. Produkcyjne UI

W zalogowanej sesji administratora sprawdzono:

- /,
- /dashboard,
- /insights i jego zakładki,
- /dynareporter,
- /dynareporter/admin/upload,
- /dynareporter/admin-dashboard.

Dowody:

- /dashboard przekierowuje do /, więc Analytics v1 nie jest w produkcji live.
- główny dashboard pokazuje 11 placements w bieżącym miesiącu, a jednocześnie
  sekcja ostatnich zatrudnień pokazuje brak danych;
- leaderboard zespołu obejmuje 38 osób, w tym role administracyjne i viewerów;
- /insights miesza okres 30 dni, lifetime, YTD, 180 dni i osobne lokalne okresy;
- /dynareporter nadal reklamuje trwającą migrację i stary system;
- /dynareporter/admin/upload jest prawidłowo archiwalny/read-only;
- /dynareporter/admin-dashboard nadal pokazuje formularze „Wprowadzanie
  danych”, przyciski masowego uzupełniania i edycję słowników.

### 3.4. Ograniczenia

- Nie pobrano chronionego /api/admin/snapshot, ponieważ w środowisku audytu nie
  było bezpiecznie dostępnego tokenu.
- Audyt nie wykonywał zapisów produkcyjnych.
- Nie testowano aktywnie wszystkich ról przez impersonation.
- Nie zmieniano flag off/shadow/live.
- Nie uruchamiano lokalnego Dockera.

Wnioski dotyczące bezpośrednich luk API wynikają z analizy guardów i kontraktów
na origin/main; należy je odtworzyć w automatycznej macierzy negatywnej przed
merge poprawki.

---

## 4. Co działa i należy zachować

### 4.1. Capability kernel Analytics v1

Centralne capability są lepsze od rozproszonych porównań primary role.
Należy je rozwinąć, a nie wracać do ręcznych allowlist w każdym endpoint.

### 4.2. Granice okresów

Resolver okresów Europe/Warsaw i półotwarte granice [start, end) są dobrym
fundamentem dla flow metrics. Problemem nie jest sam resolver, lecz
przekazywanie period do metryk snapshotowych, które go ignorują.

### 4.3. Decimal w Analytics v1

Nowe API unika float dla głównych kwot. Ten standard należy rozszerzyć na FX,
Contract Analytics, korekty i generowane typy.

### 4.4. Brak nominalnego 1:1 w nowym finance

Analytics v1 słusznie nie udaje, że brak kursu FX oznacza kurs 1. Legacy nadal
to robi i powinno zostać przepięte na ten sam fail-closed kontrakt.

### 4.5. Milestone dedup

Widok first milestones ogranicza wielokrotne liczenie tego samego etapu dla
kandydata i job. Trzeba poprawić kwalifikację statusu oraz credit semantics,
nie usuwać deduplikacji.

### 4.6. Snapshoty jako immutable input

Pomysł zachowania legacy historii jako snapshotów jest dobry. Wadą jest
semantyczne mapowanie nieporównywalnych pól i brak checksum verification.

### 4.7. Feature flags

Off/shadow/live to właściwy kierunek. Muszą jednak stać się prawdziwym
mechanizmem wykonawczym per moduł/rola/cohort, a nie globalną etykietą.

### 4.8. Produkcyjny archive upload

Archiwalny ekran DynaReporter upload już komunikuje read-only. Można go
wykorzystać jako wzorzec tombstone, ale musi być wsparty serwerową blokadą.

---

## 5. Mapa obecnej architektury

### 5.1. Trzy warstwy prezentacyjne

~~~text
Sidebar Dashboard ──> / ──> DashboardV2 / dashboard rolowy
Sidebar Insights  ──> /insights ──> legacy sekcje rekrutacja/klienci/zarząd
Direct URL         ──> /dashboard ──> Analytics v1 tylko gdy mode=live
Direct URL         ──> /dynareporter/* ──> legacy raporty i część writerów
~~~

W praktyce użytkownik nie ma jednego analytics home. Przełączenie backendowej
flagi nie zmienia automatycznie wszystkich linków, redirectów i zapytań.

### 5.2. Warstwy obliczeniowe

~~~text
CandidateStage / Contract / Activity / Call / Job / Client
              │
              ├── legacy report endpoints
              ├── KPI panel/team/coach services
              ├── Contract Analytics
              ├── Analytics v1 metrics.py
              └── DynaReporter snapshot/read models
~~~

Ta sama nazwa metryki może być obliczona przez kilka niezależnych zapytań.

### 5.3. Rollout

Obecny kontrakt:

- backend off: v1 niedostępne,
- backend shadow: endpointy odpowiadają tak samo jak live,
- backend live: endpointy odpowiadają,
- frontend odpytuje v1 wyłącznie dla live,
- ANALYTICS_V1_MODULES nie jest faktycznie używane,
- brak trwałego shadow comparator.

Shadow nie jest zatem shadow. To dostępne API, którego główny frontend nie
wywołuje.

---

## 6. Rejestr usterek P0 — blokery bezpieczeństwa i prawdy biznesowej

### P0.1. HoR otrzymuje finanse mimo braku view_finance

Dowody:

- backend/app/analytics/capabilities.py:92-99 nie daje HoR capability finansowej;
- frontend/src/components/insights/InsightsView.tsx:42-45 domyślnie otwiera mu
  Klienci;
- KlienciPanel renderuje ClientsRanking i DLRevenueLeaderboard;
- endpointy admin_clients_overview używają HeadOfRecruitmentPlus;
- Dyna Board dopuszcza HoR do pełnego P&L.

Ryzyko:

- naruszenie zasady najmniejszych uprawnień,
- ujawnienie lifetime revenue, aktywnego revenue, miesięcznej marży i maili DL,
- różne zasady na v1 i legacy.

Naprawa:

1. Wprowadzić capability guard na każdym legacy endpoint zwracającym finanse.
2. Wygenerować mapę endpoint → capability → resource scope.
3. HoR bez view_finance ma otrzymać 403 także przez direct URL.
4. Frontend może ukrywać widok, ale nie jest granicą bezpieczeństwa.
5. Dodać negatywny test pól odpowiedzi, nie tylko statusu.

Kryterium akceptacji:

- HoR bez jawnego grantu nie otrzymuje żadnej kwoty, waluty, marży ani revenue
  przez Analytics v1, Insights, Contract Analytics lub Dyna.

### P0.2. Zwykły user może pobrać imienne KPI Dyna Rekrutacja

Dowody:

- frontend middleware dopuszcza każdego zalogowanego do /dynareporter;
- wspólny layout Dyna nie ma capability guard;
- strona Rekrutacja odpytuje API przy hydrated && user;
- backend używa jedynie CurrentUser;
- odpowiedź zawiera user_name, wyniki, ranking i nagrody.

Ryzyko:

- dane o wydajności pracowników są dostępne roli viewer;
- direct URL omija intencję nowej macierzy;
- ranking i nagrody zwiększają wrażliwość informacji.

Naprawa:

1. Natychmiast dołożyć server-side guard do wszystkich Dyna recruitment routes.
2. Zbudować automatyczny inventory route/method/capability.
3. Jeżeli viewer ma widzieć agregaty, stworzyć osobny response bez nazw, ID,
   emaili, rankingu i nagród.
4. Dodać direct-route E2E dla viewer.

### P0.3. DYNAREPORTER_MODE=read_only nie blokuje write API

Dowody:

- middleware backendu rozróżnia tylko off, które daje 410;
- read_only nie przechwytuje POST/PATCH/PUT/DELETE;
- wiele routerów Dyna nadal ma write methods;
- produkcyjny /dynareporter/admin-dashboard wyświetla formularze zapisu.

Ryzyko:

- użytkownik może nadal tworzyć konkurencyjną prawdę w legacy,
- snapshoty i v1 mogą rozjechać się po cutover,
- „archive” jest wyłącznie deklaracją UI w części ekranów.

Naprawa natychmiastowa:

1. Centralny backendowy deny-by-default dla mutujących metod na legacy Dyna.
2. Wyjątki wyłącznie z jawnej allowlisty i tylko jeśli migracja naprawdę ich
   potrzebuje.
3. Odpowiedź 410 lub 409 z kodem DYNAREPORTER_READ_ONLY.
4. UI usuwa/disable wszystkie kontrolki zapisu.
5. Test enumeruje wszystkie zarejestrowane Dyna write routes i oczekuje blokady.

Nie wolno polegać na next.config redirects ani disabled button.

### P0.4. Okres finansowy jest fałszywy

Dowody:

- analytics_v1.py:375-395 przyjmuje period dla client finance, lecz nie
  przekazuje go do metrics;
- analogicznie finance summary i finance clients;
- executive łączy okresowy funnel z dzisiejszym finance;
- metrics.py implementuje te finanse „na dziś”.

Przykład błędu:

~~~text
GET /api/analytics/v1/finance/summary?date_from=2025-01-01&date_to=2025-01-31
koperta: okres styczeń 2025
data: MRR i kontrakty na dzień dzisiejszy
~~~

Naprawa:

- flow metric przyjmuje period,
- snapshot metric przyjmuje as_of,
- cohort metric przyjmuje cohort period i observation_as_of,
- nieobsługiwany parametr powoduje 422,
- koperta zwraca effective_period albo effective_as_of.

### P0.5. Effective-dated stawki są ignorowane

Dowody:

- metrics.py eager-loaduje candidate/client/framework schedules;
- obliczenia używają monthly_rate_client i monthly_margin;
- properties opierają się na bazowych rate_client/rate_candidate;
- prawidłowe effective_candidate_rate i effective_client_rate istnieją, ale
  nie są używane przez analytics;
- future-dated aneks może od razu zmienić rate_unit lub billing hours.

Ryzyko:

- historia jest przeliczana dzisiejszymi lub cache’owanymi warunkami,
- przyszły aneks zmienia raport przed datą wejścia w życie,
- sell rate, cost rate, unit i hours mogą pochodzić z różnych wersji.

Naprawa:

- jeden atomowy ContractEconomicTerms:
  - valid_from,
  - valid_to,
  - client rate,
  - candidate rate,
  - currency obu stron,
  - rate unit,
  - billing hours,
  - provenance/revision;
- terms_at(contract, as_of) jest jedynym wejściem agregacji.

### P0.6. Cutover łączy nieporównywalne metryki

Obecne mapowanie:

| Legacy | Nazwa live | Dlaczego nieporównywalne |
|---|---|---|
| revenue | mrr | recognized flow w miesiącu to nie recurring snapshot |
| revenue - consultant_costs - other_costs | monthly_margin | operating margin to nie direct contract margin |
| active_consultants | active_contracts | jedna osoba może mieć inny cardinality niż kontrakty |

Skutek:

- trend wygląda ciągle, lecz zmienia definicję w środku serii;
- parity do 1 PLN jest logicznie niemożliwe;
- użytkownik nie widzi granicy metodologii.

Naprawa:

1. Zachować osobne series IDs.
2. Nie przemapowywać nazw.
3. Zdefiniować metric-version compatibility manifest.
4. Pokazać wizualną granicę metodologii, jeżeli serie muszą współistnieć.
5. Live MRR zaczyna się dopiero tam, gdzie można go historycznie odtworzyć.

### P0.7. Analytics źródeł pomija dużą część kandydatów

Dowody:

- migracja obiecuje fallback do Candidate.source;
- view i metrics.sources czytają tylko CandidateSourceEvent;
- event powstaje w niewielu ścieżkach;
- importowane i starsze rekordy mają legacy source/source_enum.

Skutek:

- wynik może mieć rate <=100%, lecz obejmować mały, selektywny podzbiór;
- produkcyjny ekran źródeł może pokazać „brak danych” przy dziesiątkach tysięcy
  kandydatów.

Naprawa:

- jawny coverage denominator,
- idempotentny backfill z provenance legacy,
- do końca migracji fallback w projection,
- osobny unknown bucket,
- quality complete dopiero po uzgodnionym progu coverage.

### P0.8. Pending/rejected verification jest milestone sukcesu

Dowody:

- view first milestones filtruje nazwę stage, ale nie verification_status;
- statusy obejmują active, pending i rejected.

Skutek:

- odrzucona próba może zwiększyć KPI,
- może zostać pierwszą kotwicą credit dla późniejszego placement,
- funnel i KPI Coach mogą motywować do niewłaściwego zachowania.

Naprawa:

- verification_submitted jest osobną metryką flow,
- verification_approved wymaga zatwierdzonego statusu,
- późniejszy credit nie może pochodzić z rejected event,
- testy pending → rejected → active oraz resubmission.

### P0.9. Błąd bywa prezentowany jako zdrowe zero

Przykłady:

- SLA Alerts po błędzie pokazuje „Brak alertów — wszystko w normie”;
- client risk po błędzie wygląda jak brak ryzyka;
- HoR dashboard renderuje pięć zer;
- funnel, TTH i heatmapa zamieniają błąd na empty/zero;
- Board KPI, Champions, Tenders i Invite Links znikają;
- dashboard recruiter/DL ma wymyślone fallback nagród 5000/3000/2000.

Naprawa:

- zakazać error → [], error → 0 i silent return null,
- jeden canonical WidgetBoundary,
- jawne stany: loading, refreshing, forbidden, disabled, unconfigured,
  unavailable, error, empty, partial, stale, ready,
- wartość null przy braku wiarygodnego total,
- fallback finansowy lub nagrodowy nigdy nie może wyglądać jak konfiguracja.

### P0.10. Shadow mode nie tworzy dowodu

Dowody:

- backend shadow i live serwują endpointy identycznie;
- frontend odpytuje v1 wyłącznie w live;
- brak worker comparator, parity table, run history i alertów;
- ANALYTICS_V1_MODULES jest martwą konfiguracją.

Skutek:

- „7 dni shadow” może minąć bez ani jednego porównania;
- nie istnieje lista rozbieżności do zaakceptowania;
- operator nie wie, czy shadow w ogóle działał.

Naprawa:

- durable AnalyticsComparisonRun,
- per metric/grain/scope comparison,
- scheduled sampling i full critical comparisons,
- progi absolute/relative/exact,
- coverage oraz source quality jako precondition,
- trend i alert,
- cutover gate czyta zatwierdzony wynik, nie flagę.

### P0.11. Legacy Contract Analytics miesza waluty

Dowody:

- margin endpoints sumują surowe kwoty bez FX;
- DTO używa int;
- forecast domyślnie nie konwertuje;
- opcjonalna konwersja legacy ma fallback 1:1;
- frontend nie wymusza bezpiecznej konwersji.

Naprawa containment:

- mixed lub unknown currency → amount null + unavailable,
- nigdy nie sumować nominalnie,
- każdy amount ma currency albo reporting_currency,
- później endpointy przepiąć na canonical finance engine.

---

## 7. Rejestr usterek P1 — wysoki priorytet

### P1.1. Credit za milestone ma dwie definicje

Analytics v1 przypisuje milestone użytkownikowi first_moved_by dla danego
milestone. KPI panel, KPI team, Coach i competitions używają kotwicy pierwszego
weryfikatora. Obie definicje mogą dać inne osoby i inne wyniki.

Docelowo potrzebne są co najmniej dwa jawne pola:

- actor_user_id — kto wykonał dane przejście,
- credited_owner_user_id — komu zgodnie z polityką przypisujemy wynik.

Polityka credit musi być wersjonowana i wspólna dla panelu, Coach, konkursu oraz
raportu.

### P1.2. Source conversion miesza cohort i all-time hire

Obecny join może w okresie źródłowym 2025 policzyć hire z 2026. To może być
poprawna metryka kohortowa, ale musi mieć nazwę i observation_as_of.

Do wyboru:

- cohort acquired in period, hired by as-of,
- acquired and hired in the same period.

Nie wolno prezentować ich pod tą samą etykietą.

### P1.3. Brak FX daje częściową liczbę jako total

Nowy engine pomija kontrakt bez kursu, zwraca subtotal pozostałych i quality
unavailable. Konsument ignorujący quality zobaczy zaniżony total.

Kontrakt:

- total = null, jeżeli total nie jest kompletny;
- known_subtotal może istnieć wyłącznie w diagnostics;
- missing amount/count/currencies są jawne;
- pełna liczba pojawia się dopiero po gotowości źródła.

### P1.4. Poprawna konwersja obcej waluty jest oznaczona partial

Każdy warning jest dziś interpretowany jako problem jakości. Informacja
„przeliczono EUR po kursie X” nie jest degradation.

Rozdzielić:

- notices — informacja bez wpływu na jakość,
- issues — brak/starość/niezgodność,
- lineage — provenance kursu.

### P1.5. FX może być stary i pobierany po HTTP

Potrzebne:

- HTTPS,
- idempotentny upsert,
- historyczny fetch po dacie,
- limit wieku kursu zależny od rodzaju raportu,
- table number i effective date,
- jawny weekend/holiday fallback,
- fail-closed po przekroczeniu SLA.

### P1.6. Approved financial adjustments nie wchodzą do raportów

Model obiecuje uwzględnienie zatwierdzonych korekt, ale agregatory ich nie
czytają.

Docelowy ledger:

- draft,
- submitted,
- approved/rejected,
- effective period,
- client,
- contract opcjonalnie,
- currency,
- kind i sign,
- reason,
- created_by/approved_by,
- reversal_of.

Nie edytować zatwierdzonej korekty w miejscu. Storno jest nowym rekordem.

### P1.7. Cutover nie ma readiness gate ani audytu

Obecny endpoint pozwala:

- dowolny module string,
- dowolną datę,
- nadpisanie istniejącej wartości,
- brak created_by/reason/revision,
- brak CAS i invalidacji cache.

Snapshot reader:

- nie filtruje source,
- nie weryfikuje checksumu.

Potrzebny append-only state machine:

proposed → shadow_verified → canary → live → retired

oraz rollback pointer do poprzedniej aktywnej rewizji.

### P1.8. Multi-role może pożyczyć scope od innej roli

Capability jest sumą ról, a resource scope jest wyliczany niezależnie.
Użytkownik DL+TAC może potencjalnie dostać finance z DL i global client scope z
TAC.

Policy decision musi zawierać provenance:

~~~text
allow(
  capability=view_finance,
  resource=client:123,
  granted_by_role=delivery_lead,
  scope=assigned_clients_of_that_role
)
~~~

Nie wystarczy osobno sprawdzić „ma capability” i „ma jakiś globalny scope”.

### P1.9. Team oznacza organizację

VIEW_TEAM_KPI dla DL pozwala zobaczyć organizacyjny zestaw użytkowników.
Brakuje modelu team membership i effective dates.

Potrzebne:

- ReportingTeam,
- ReportingTeamMembership,
- manager_user_id,
- valid_from/valid_to,
- membership_revision,
- jawna polityka secondary/matrix team,
- „unassigned” jako osobny stan operatorski.

### P1.10. HoR jest opisany jako manager, ale część legacy KPI go odrzuca

Endpoint używa RecruiterPlus, którego enum nie obejmuje HoR, mimo docstringu.
To przykład rozjazdu komentarza i realnego guardu. Należy generować tests z
policy matrix i nie duplikować list ról.

### P1.11. KPI target nie respektuje multi-role

get_my_kpis, resolve_target i panel applies opierają się na primary role.
Docelowo policy musi określić:

- które target sets mają zastosowanie przy wielu rolach,
- czy targety sumujemy, wybieramy najwyższy, czy wybieramy operacyjny context,
- kto i kiedy przypisał context,
- jak wersjonujemy target.

### P1.12. KPI Coach nie ma trwałej prawdy wykonania

Problemy:

- dry-run tylko loguje, ale liczniki wyglądają jak wysłane;
- osobna flaga outer worker i osobna flaga v2 komplikują stan;
- brak durable evaluation run;
- brak decision log i powodu skip;
- brak outbox;
- brak widoku attempts i delivery.

Potrzebne:

- AnalyticsEvaluationRun,
- KpiNudgeDecision,
- NudgeMessage,
- Delivery/Outbox z Modułu 6,
- jednoznaczne counters evaluated/eligible/planned/enqueued/sent/failed/skipped.

### P1.13. Dedup KPI Coach blokuje eskalacje

Unique constraint pozwala jeden reminder dla user/kpi/type/bucket, a serwis
obiecuje do trzech przypomnień. Druga próba może kolidować.

Klucz powinien zawierać:

- period bucket,
- policy version,
- sequence number,
- channel,
- recipient,
- logical nudge key.

### P1.14. Okno EOD może zostać pominięte

EOD działa 17:25–17:35, quiet-hours gate zmienia zachowanie o 17:30, worker
budzi się co pięć minut. Jedna niekorzystna granica lub restart może pominąć
całość.

Nie projektować krytycznego run jako „jeżeli obecna minuta jest w oknie”.
Persisted scheduler powinien zapisać należny run i wykonać go po odzyskaniu.

### P1.15. Debug-fire-nudge jest destrukcyjny i ujawnia traceback

Endpoint usuwa wcześniejszy log dedupe, wymusza wysyłkę i może zwrócić traceback.

Naprawa:

- tylko non-production lub break-glass admin,
- nigdy nie usuwa logu,
- tworzy osobny TestDelivery z correlation id,
- nie wysyła do realnego odbiorcy bez jawnego adresu testowego,
- sanitized error.

### P1.16. Tenders nie raportuje przetargów

metrics.tenders filtruje zamknięte Job, a wartość bierze z salary_max.
Salary_max to widełki B2B/miesiąc, nie wartość przetargu.

Do czasu dedykowanej domeny:

- nie pokazywać salary jako tender value,
- filtruj jawne recruitment_type=tender,
- amount może być null,
- dodaj Tender/TenderLot/TenderOutcome dopiero po uzgodnieniu z Modułem 1.

### P1.17. Dashboard ma sprzeczne placement/recent hires

Root dashboard pokazuje placements z jednego endpointu, a recent hires filtruje
activity feed zamiast użyć istniejącego typed hires endpoint.

Naprawa:

- jeden canonical placement fact,
- recent list i counter z tej samej projekcji,
- reconciliation invariant: count > 0 i empty recent wymaga wyjaśnienia okresu,
  paginacji lub uprawnień, a nie cichego „brak”.

### P1.18. Client card myli total z active

UI renderuje clients.total z opisem „aktywne konta”, chociaż backend ma osobne
total/active. Należy użyć właściwego pola i dopisać contract test label ↔ metric
id.

### P1.19. Activity leaderboard total nie odpowiada kolumnom

Total liczy wszystkie UserActivity actions, tabela pokazuje tylko pięć
kategorii. Dlatego użytkownik może mieć total 35 i wszystkie widoczne kolumny
zero.

Rozwiązanie:

- total_displayed = suma widocznych kolumn,
- other_actions osobno,
- total_all z tooltipem i katalogiem,
- nie mieszać activity log z outcome KPI.

### P1.20. Selektor okresu /insights jest dekoracyjny dla części widgetów

Rekrutacja:

- selector steruje heatmapą,
- funnel/TTH/SLA/source używają innych okresów.

Klienci:

- selector steruje hit ratio,
- ranking, DL, Sales, HM ignorują go.

Zarząd:

- selector wpływa tylko na część danych,
- Board KPI jest YTD, trendy 12m.

Każdy widget musi jawnie deklarować:

- uses_global_period,
- fixed_period,
- snapshot_as_of,
- all_time,
- own_period_control.

### P1.21. Partial month porównywany z pełnym miesiącem

Produkcja porównuje część lipca z całym czerwcem i pokazuje spadek placements.
Potrzebne:

- month-to-date vs previous month-to-same-day,
- albo closed month vs previous closed month,
- wyraźne oznaczenie partial period.

### P1.22. Capabilities i flagi mogą być stare przez całą sesję

Auth store hydratuje dane z localStorage, bez centralnego /auth/me bootstrap.
Zmiana roli, sekcji lub analytics mode może nie pojawić się do ponownego
logowania.

Naprawa:

- access context bootstrap,
- access_revision,
- revalidate on focus i po 401/403,
- clear query cache przy zmianie access fingerprint,
- cache key zawiera user/scope/access revision.

### P1.23. Analytics v1 nie jest prawdziwym entrypointem

- sidebar Dashboard prowadzi do /,
- Insights prowadzi do /insights,
- root uruchamia stare flow,
- /dashboard jest direct preview,
- /dashboard nie jest spójnie chronione w middleware,
- redirect bywa wykonany po uruchomieniu legacy queries.

Cutover musi objąć route ownership, navigation, data fetching i telemetrykę, nie
tylko backend mode.

### P1.24. HoR default view może być niedostępny

defaultViewFor wybiera recruitment, ale HoR nie ma capability own recruitment.
Fallback powinien wybrać pierwszy dozwolony view z capability response, nie
primary role.

### P1.25. Awaria CloudTalk ukrywa wszystkie KPI

Jakość calls jest przypisana do całej odpowiedzi /me/kpis lub /team/kpis.
CloudTalk unavailable nie może ukrywać placements, candidates added i
verifications.

Quality musi być per metric albo per dependency group.

### P1.26. Cache jest nieograniczony i per-process

Globalny dictionary:

- usuwa expired tylko przy ponownym trafieniu tego samego klucza,
- rośnie przez custom ranges i user IDs,
- różni się między replikami,
- nie ma singleflight,
- nie ma invalidacji po contract/FX/adjustment/cutover.

Minimalna poprawka:

- bounded LRU/TTL,
- max entries/bytes,
- periodic sweep,
- metrics hit/miss/eviction,
- generation token,
- singleflight.

Docelowo shared cache tylko wtedy, gdy invalidation i scope są poprawne.

### P1.27. Finance ma koszt N×client×currency i M×contract

finance_clients iteruje klientów i osobno sumuje ich kontrakty. FX może być
query per waluta. Trend powtarza skan dla każdego miesiąca.

Potrzebne:

- query-count budget,
- bulk FX map,
- set-based SQL lub precomputed daily/monthly facts,
- EXPLAIN fixtures,
- p95 i payload budgets.

### P1.28. date.today łamie Warsaw contract

Wiele metryk używa procesowego date.today. W nocy UTC dzień może różnić się od
Europe/Warsaw.

Wprowadzić wstrzykiwany AnalyticsClock:

- now_utc,
- today_warsaw,
- resolve_period,
- freeze w testach,
- effective_as_of w odpowiedzi.

### P1.29. Termination retention klasyfikuje unknown jako kept

Brak danych nie spełnia wąskiej reguły early i trafia do „utrzymanych”.
Potrzebne co najmniej:

- kept,
- early,
- normal_end,
- unknown,
- not_yet_ended.

### P1.30. Quality envelope jest deklaratywna, nie źródłowa

source_watermarks ma pusty default i nie jest wypełniane. CloudTalk readiness
sprawdza głównie flagę, nie ostatni sync, credentials, errors i mapping
coverage. Inne metryki dostają complete domyślnie.

Potrzebny MetricReadinessService oparty na faktycznym stanie integracji,
watermarkach i coverage.

---

## 8. Rejestr usterek P2/P3 — jakość kontraktu i UX

### P2.1. API jest tylko pozornie typowane

AnalyticsEnvelope.data jest dict[str, Any]. Endpointy nie generują
bezpiecznych DTO. Frontend ręcznie kopiuje typy.

### P2.2. OpenAPI gate sprawdza tylko paths/methods

Nie wykryje:

- zmiany pola,
- zmiany typu,
- nowego required param,
- Decimal → float,
- finansowego pola w viewer response.

Denylist sprawdza ograniczoną część listy i nie jest rekursywna dla całego
payload.

### P2.3. stats-api nie pokrywa całego backendu

Ręczny klient pomija część finance trend/clients, team calls i meta. To
zwiększa liczbę ad-hoc requestów i dryf typów.

### P2.4. METRIC_DEFINITIONS jest niepełny

Brakuje m.in.:

- grain,
- additivity,
- type flow/snapshot/cohort,
- owner,
- source facts,
- source SLA,
- quality dependencies,
- PII class,
- allowed scopes,
- version compatibility.

### P2.5. METRIC_VERSION jest ręczny bez bramki

Zmiana SQL nie wymusza bumpu wersji ani migracji cache/snapshot. CI powinno
wiązać hash definicji/query z metric version lub wymagać jawnego changelog.

### P2.6. pipeline snapshot przyjmuje okres i go ignoruje

Tworzy osobne cache entries dla identycznego snapshotu. Parametr należy usunąć
albo zastąpić as_of.

### P2.7. Niejasny end_date

Dokumentacja mówi start <= today < end, część kodu używa end_date >= today.
Należy ustalić prawdę domenową z Modułem 5. Nie zmieniać samego operatora bez
analizy produkcyjnych umów i cronów.

### P2.8. Niepoprawny period cicho mapuje się na week

Endpoint KPI powinien używać enum i zwracać 422. Silent fallback ukrywa błąd
klienta.

### P2.9. KPI business deadline jest kalendarzowym 23:59

Jeżeli polityka mówi business deadline, engine musi znać working calendar,
timezone, holidays i cut-off. W przeciwnym razie nazwać metrykę calendar
deadline.

### P2.10. StatsBoundary nie wyprowadza deklarowanych stanów

stale/unconfigured praktycznie nie powstają, disabled miesza flagę z brakiem
capability, empty wymaga ręcznego sygnału.

### P2.11. Dostępność

- Insights używa nav zamiast tab semantics,
- toggles nie mają aria-pressed,
- period control nie ma accessible group name,
- klikane rows nie są osiągalne klawiaturą,
- spinner nie ma role=status,
- heatmapa opiera się na title.

### P2.12. Mobile

- nagłówki i selektory nie zawijają się,
- duże tabele nie zawsze mają overflow container,
- dane mogą wypchnąć stronę na 320 px.

### P2.13. Hardcoded kolory

StatsBoundary i legacy Insights używają hardcoded amber/hex zamiast
semantycznych tokenów.

### P2.14. Hardcoded lata Board

Lista 2024–2026 nie obsłuży 2027. Zakres ma pochodzić z danych lub current year.

### P2.15. Backfill snapshotu skipuje checksum mismatch

Conflict nie powinien cicho kończyć operacji, jeżeli source payload ma inny
checksum. To sygnał naruszenia immutability lub zmiany extraction logic.

### P2.16. FxRateRow serializuje Decimal do float

Kontrakt powinien zachować string Decimal oraz jawny scale.

### P2.17. Równoległy fetch FX może dostać IntegrityError

Select-then-insert trzeba zastąpić idempotentnym upsert albo bezpiecznym
handling unique conflict.

---

## 9. Scenariusze awarii, które projekt musi obsłużyć

### 9.1. Integracja jest włączona, ale niesprawna

Flaga true nie oznacza readiness. Odpowiedź powinna rozróżnić:

- unconfigured,
- disabled,
- syncing,
- stale,
- degraded,
- failed,
- complete.

### 9.2. Jedna zależność KPI jest niedostępna

Calls mogą być null/unavailable, ale placements i verifications pozostają
widoczne jako complete.

### 9.3. Brak kursu jednej waluty

Total jest null. Diagnostics może podać known subtotal i brakujące waluty, ale
UI nie może pokazać subtotal jako total.

### 9.4. Kurs jest starszy niż SLA

Historyczny raport może zaakceptować poprawny kurs historyczny. Dzisiejszy
snapshot nie może użyć arbitralnie starego kursu bez notice/issue według
polityki.

### 9.5. Future-dated aneks

Nie zmienia dnia przed valid_from. Po valid_from sell rate, cost rate, unit i
hours zmieniają się atomowo.

### 9.6. Użytkownik ma dwie role

Nie pożycza capability z jednej i globalnego scope z drugiej. Policy decision
jest deterministyczna i audytowalna.

### 9.7. Użytkownik zmienia zespół

Historyczny raport rozlicza membership effective at event date lub jawnie
wybraną politykę. Dzisiejszy team view używa current membership.

### 9.8. Worker KPI Coach restartuje się w oknie

Persisted due run zostaje wykonany raz. Nie jest pomijany i nie jest zdublowany.

### 9.9. Provider przyjął nudge, commit nie nastąpił

Outbox/operation reconciliation określa unknown i nie wysyła ślepo drugi raz.

### 9.10. Shadow comparator nie działa

Cutover gate jest czerwony z powodu braku fresh comparison runs. Upływ czasu
nie wystarcza.

### 9.11. Legacy snapshot ma zły checksum

Odczyt failuje jako integrity error; nie serwuje danych i nie naprawia ich po
cichu.

### 9.12. Częściowy bieżący miesiąc

Trend porównuje MTD do poprzedniego MTD albo zamknięte okresy. Nie zestawia
części z pełnym miesiącem bez ostrzeżenia.

### 9.13. API zwraca 403

Widget pokazuje brak uprawnień, nie zero i nie „wszystko w normie”.

### 9.14. Traffit jest degraded

Metryki zależne od importu mają watermark/coverage i partial/stale. Niezależne
metryki pozostają complete.

### 9.15. Dyna write request po read-only

Backend zwraca deterministyczny kod, nic nie zapisuje, loguje audyt próby i UI
nie pokazuje sukcesu.

---

## 10. Docelowy model pojęciowy

### 10.1. MetricDefinition

Minimalne pola:

- metric_id — stabilny semantic identifier,
- version,
- display_name,
- description,
- owner_module,
- owner_team,
- kind: flow/snapshot/cohort/ratio/distribution,
- grain,
- unit,
- additive_dimensions,
- non_additive_dimensions,
- event_time_field albo as_of rule,
- numerator/denominator dla ratio,
- fact_sources,
- dimension_sources,
- allowed_capabilities,
- scope_policy_id,
- pii_classification,
- readiness_policy_id,
- freshness_sla,
- late_arrival_policy,
- correction_policy,
- compatibility_with_previous_version,
- deprecation status.

### 10.2. MetricObservation

Nie musi od razu być fizyczną tabelą dla każdej liczby. Kontrakt logiczny:

- metric_id/version,
- grain keys,
- effective period albo as_of,
- value Decimal/int/null,
- unit/currency,
- quality,
- source watermarks,
- coverage,
- generated_at,
- query/run id,
- lineage reference.

### 10.3. AnalyticsEvaluationRun

Prawda o wykonaniu:

- run_id,
- run_type: API/materialization/comparison/coach/snapshot,
- scheduled_for,
- started_at/finished_at,
- status,
- code version,
- metric definition version set,
- input watermarks,
- scope,
- row counts,
- warnings/issues,
- error code,
- retry_of.

### 10.4. AnalyticsComparisonRun

- old metric id/version,
- new metric id/version,
- grain/sample policy,
- compared rows,
- missing on either side,
- exact matches,
- absolute delta,
- relative delta,
- classified differences,
- threshold policy,
- result pass/fail/inconclusive,
- reviewer/approval.

### 10.5. MetricReadiness

- dependency,
- configured,
- enabled,
- last_success_at,
- source_watermark,
- lag_seconds,
- coverage numerator/denominator,
- error rate,
- stale threshold,
- quality result,
- human-readable issue code.

### 10.6. ReportingTeam

- id/name,
- manager,
- type,
- valid dates,
- membership history,
- revision,
- optional parent team,
- source of truth.

### 10.7. ContractEconomicTerms

- contract_id,
- valid_from/valid_to,
- sell rate/currency,
- cost rate/currency,
- rate unit,
- billing hours,
- derived monthly normalization rules,
- schedule/source revision,
- created_by/reason.

### 10.8. FinancialAdjustment

Zatwierdzony ledger wpisuje się do raportu przez effective month, nie przez
updated_at. Edycja po approval jest zabroniona; reversal jest nowym wpisem.

### 10.9. CutoverRevision

- module/metric family,
- from metric version,
- to metric version,
- state,
- proposed_at/by/reason,
- comparison evidence,
- coverage/readiness snapshot,
- canary cohort,
- active_from,
- rollback_to,
- supersedes,
- immutable audit.

### 10.10. DynaArchiveManifest

- export id,
- source tables/time range,
- extraction version,
- row counts,
- checksum,
- storage location,
- encryption/access policy,
- retention date,
- restore drill result.

---

## 11. Kanoniczny kontrakt czasu

### 11.1. Flow

Zdarzenia, które zaszły w [start, end):

- placements_created,
- verifications_approved,
- submissions_sent,
- interviews_scheduled,
- offers_accepted,
- calls_completed.

### 11.2. Snapshot

Stan na konkretny instant/date:

- active_contracts_as_of,
- MRR_as_of,
- direct_margin_as_of,
- open_jobs_as_of,
- active_candidates_as_of.

Parametr: as_of. Nie period.

### 11.3. Cohort

Populacja wejściowa w [cohort_start, cohort_end) obserwowana do
observation_as_of:

- source_to_hire_conversion,
- time_to_hire cohort,
- retention cohort.

UI pokazuje oba zakresy oraz maturity.

### 11.4. Ratio

Każdy ratio musi zwrócić:

- numerator,
- denominator,
- rate albo null,
- denominator coverage,
- rule for zero denominator.

Zero denominator nie oznacza rate 0%.

### 11.5. Timezone

- event storage UTC,
- period resolution Europe/Warsaw,
- odpowiedź zwraca resolved start/end w UTC i lokalną datę,
- jeden wstrzykiwany clock,
- DST testy,
- current date nigdy z process date.today.

### 11.6. Partial period

Koperta:

- complete_period boolean,
- elapsed_fraction opcjonalnie,
- comparison_policy,
- comparable_previous_start/end.

### 11.7. Late arriving facts

Każda metryka definiuje:

- allowed lateness,
- whether historical periods are restated,
- snapshot revision policy,
- user-facing label „dane zaktualizowane”.

---

## 12. Kanoniczny katalog najważniejszych metryk

### 12.1. Rekrutacja

| Metric ID | Kind | Grain | Główna zasada |
|---|---|---|---|
| candidates_added | flow | actor/team | utworzenie kanonicznego kandydata |
| verification_submitted | flow | actor/job | każda kwalifikowana submission do weryfikacji |
| verification_approved | flow | credited owner/job | tylko approved/active |
| candidate_submitted | flow | credited owner/job/client | kanoniczny submission fact |
| interview_scheduled | flow | credited owner/job/client | pierwszy kwalifikowany event lub jawnie all events |
| offer_issued | flow | job/client | outcome fact, nie nazwa dowolnego stage |
| offer_accepted | flow | job/client | acceptance fact |
| placement_created | flow | job/client/team | kanoniczny placement |
| pipeline_stage_snapshot | snapshot | stage/job/team | stan as_of |
| time_to_hire | cohort/distribution | job/client/source | jawna kohorta i observation_as_of |

### 12.2. Źródła

Rozdzielić:

- candidate_origin_first_touch,
- application_acquisition_source,
- campaign attribution,
- referral source,
- unknown/unattributed.

Global first source kandydata nie wystarcza dla wielu aplikacji/jobs.

### 12.3. KPI osób

Każdy KPI ma:

- metric_id/version,
- target policy/version,
- actor versus credited owner,
- applicable role contexts,
- period,
- quality,
- explanation,
- drilldown permission.

### 12.4. Klienci

- open_jobs_as_of,
- submissions_in_period,
- interviews_in_period,
- placements_in_period,
- active_contracts_as_of,
- hit ratio z numerator/denominator,
- aging i SLA,
- revenue/margin wyłącznie dla view_finance.

### 12.5. Finanse

Rozdzielić:

- contracted_mrr_as_of,
- contracted_direct_margin_as_of,
- recognized_revenue_in_period,
- recognized_direct_cost_in_period,
- operating_adjustments_in_period,
- operating_margin_in_period,
- active_contract_count_as_of,
- active_consultant_count_as_of.

Nie aliasować ich między sobą.

### 12.6. Tender

Do czasu dedykowanego modelu:

- tender_count z jawnego recruitment_type,
- tender_value = null, jeżeli brak domenowego pola,
- nie używać salary_max jako wartości przetargu.

### 12.7. Aktywności

Oddzielić:

- action count,
- meaningful recruitment activity,
- outcome KPI,
- audit events,
- communication deliveries.

Total tabeli musi odpowiadać widocznym kategoriom albo pokazywać Other.

---

## 13. Docelowy kontrakt quality i lineage

### 13.1. Statusy

- complete — wszystkie wymagane źródła spełniają kontrakt,
- partial — liczba jest celowo częściowa i zakres jest znany,
- stale — kompletna dla starego watermarku, poza SLA,
- unavailable — total nie może być wiarygodnie policzony,
- unconfigured — zależność nie jest skonfigurowana,
- disabled — feature/source wyłączony polityką,
- forbidden — użytkownik nie ma prawa,
- error — nieoczekiwany błąd obliczenia.

### 13.2. Zasada null

Jeżeli wartość nie jest wiarygodnym totalem:

- value = null,
- nie zero,
- diagnostics mogą zawierać known subtotal,
- UI nie może stylować subtotal jak głównej wartości.

### 13.3. Per-metric quality

Jedna awaria CloudTalk nie obniża wszystkich KPI. Każdy metric observation
niesie własną quality i dependencies.

### 13.4. Watermarks

Minimum:

- source name,
- source event time watermark,
- ingestion time watermark,
- last successful sync,
- lag,
- last error,
- coverage.

### 13.5. Lineage

Dla finansów:

- contract terms revision,
- effective date,
- rate source,
- FX table/effective date,
- adjustment ids,
- reporting currency,
- rounding policy.

Dla KPI:

- milestone fact ids,
- credit policy version,
- target version,
- team membership revision.

### 13.6. Nie eksponować PII

Lineage reference jest technicznym identyfikatorem. Drilldown do osoby lub
kontraktu nadal wymaga capability i resource scope.

---

## 14. Docelowy model autoryzacji i scope

### 14.1. Zasada

Autoryzacja raportu jest iloczynem, nie sumą niezależnych testów:

~~~text
decision =
  capability
  ∩ resource scope związany z rolą, która przyznała capability
  ∩ allowed section
  ∩ field policy
  ∩ row policy
  ∩ purpose/context
~~~

### 14.2. Role i oczekiwany scope

Poniższa tabela jest rekomendacją do zatwierdzenia przez product ownera.

| Rola | Własne KPI | Team KPI | Org KPI | Client finance | Board finance |
|---|---:|---:|---:|---:|---:|
| user/viewer | bezpieczne agregaty albo brak | nie | nie | nie | nie |
| recruiter | tak | nie | nie | nie | nie |
| sourcer | tak | nie | nie | nie | nie |
| talent acquisition coordinator | własne/operacyjne | według assignment | bez PII | nie | nie |
| delivery lead | tak | przypisany zespół | nie | przypisani klienci, jeśli zatwierdzone | nie |
| head of recruitment | tak | podległa organizacja recruitment | agregaty org | nie domyślnie | nie domyślnie |
| admin | tak | tak | tak | tak | tak |

### 14.3. Multi-role

Policy engine nie może:

1. wziąć view_finance z roli DL,
2. wziąć global client scope z roli TAC,
3. złożyć ich w global finance.

Każde allow ma provenance roli i polityki. Jeżeli kilka allow pasuje, wynik jest
sumą konkretnie dozwolonych resource sets, nie globalnym rozszerzeniem.

### 14.4. Field policy

Przykładowe klasy pól:

- public aggregate,
- internal aggregate,
- employee performance identifiable,
- candidate PII,
- client confidential,
- finance confidential,
- executive-only.

Schema serializer powinien tworzyć model odpowiedzi właściwy capability, nie
zwracać pełny dict i usuwać pola post factum.

### 14.5. Team membership

Wymagane operacje:

- assign person to reporting team,
- transfer z effective date,
- secondary team z policy,
- manager change,
- close team,
- audyt historii,
- orphan/unassigned report.

### 14.6. Cache scope

Klucz cache musi zawierać:

- metric version,
- effective period/as_of,
- capability set fingerprint,
- resource scope fingerprint,
- access revision,
- source generation/readiness revision.

Nie wkładać surowej listy PII lub tokenu do klucza.

### 14.7. Dyna legacy

Każdy GET Dyna ma przejść tę samą policy. Nie wystarczy allowed_sections w
frontendzie. Nieznana trasa legacy jest fail-closed.

---

## 15. Docelowy silnik finansowy

### 15.1. Zasada jednego wejścia

Wszystkie powierzchnie:

- Analytics v1,
- Contract Analytics,
- dashboard klientów,
- Board,
- trend,
- export,
- snapshot,

korzystają z jednego FinanceReadService.

### 15.2. Kontrakt wejściowy

~~~text
FinanceQuery:
  metric family
  period albo as_of
  reporting currency
  resource scope
  grouping dimensions
  include adjustments
  comparison policy
~~~

### 15.3. Effective terms

Resolver zwraca dokładnie jedną wersję warunków na instant. Brak lub overlap
jest błędem jakości, nie arbitralnym wyborem.

Inwarianty:

- brak nakładających się intervals,
- valid_from < valid_to,
- unit i hours wersjonowane razem ze stawkami,
- currency jawna po obu stronach,
- historyczne revisions immutable,
- future terms nie wpływają na wcześniejszy as_of.

### 15.4. Normalizacja

Należy jawnie zdefiniować:

- hourly → monthly przez billing hours obowiązujące w danym okresie,
- daily → monthly przez billing days albo kalendarz,
- monthly → monthly bez przeskalowania,
- rounding stage,
- gross/net/VAT boundary.

Nie ukrywać za property, która zależy od dzisiejszego stanu.

### 15.5. FX

FX resolution:

1. ta sama waluta co reporting currency → 1, nie wymaga zewnętrznego kursu;
2. historyczna data → właściwy kurs według zatwierdzonej polityki NBP;
3. weekend/święto → ostatni dopuszczalny dzień roboczy;
4. brak lub stale poza SLA → null/unavailable;
5. provenance zwraca table number, effective date i age.

### 15.6. Różne waluty sell i cost

Direct margin wymaga niezależnej konwersji obu stron na reporting currency.
Nie wolno odejmować nominalnych kwot.

### 15.7. Adjustments

Korekta musi deklarować, do której metryki należy:

- recognized revenue,
- direct cost,
- operating cost,
- bonus,
- one-off correction.

Nie każda korekta wpływa na MRR. Contracted MRR i recognized P&L to różne
rodziny.

### 15.8. Historyczny trend

Trend nie wywołuje dzisiejszej funkcji N razy. Dla każdego punktu:

- as_of albo closed period,
- effective terms w tym czasie,
- właściwy FX,
- korekty tego okresu,
- niezmienna definition version.

### 15.9. Reconciliation

Codziennie:

- count contracts without valid terms,
- overlapping terms,
- missing currency,
- missing/stale FX,
- adjustments without valid target,
- difference vs source ledger,
- history restatement count.

### 15.10. Contract Analytics adapter

Pierwszy etap zachowuje URL dla kompatybilności, ale:

- payload ma Decimal strings,
- jawne currency,
- quality,
- effective_as_of,
- dane z FinanceReadService.

Po telemetrycznym potwierdzeniu braku konsumentów legacy endpoint można usunąć.

---

## 16. Docelowe projekcje KPI i rekrutacji

### 16.1. Fakty zamiast interpretacji nazw

Moduł 7 powinien konsumować canonical facts z Modułu 4:

- VerificationSubmitted,
- VerificationApproved,
- CandidateSubmitted,
- InterviewScheduled,
- OfferIssued,
- OfferAccepted,
- PlacementCreated,
- PlacementCancelled.

Do czasu pełnego cutover projection może czytać CandidateStage, ale mapping:

- jest wersjonowany,
- bazuje na semantic key,
- sprawdza status,
- zapisuje source fact id,
- jest testowany na retry/re-entry.

### 16.2. Actor i credited owner

Każdy fact projection przechowuje:

- actor,
- operational owner at event,
- credited owner by policy,
- team membership at event,
- client/job,
- occurred_at,
- ingested_at,
- policy version.

### 16.3. Credit policy

Rekomendacja biznesowa, zgodna z większą częścią legacy KPI:

- główne outcome KPI rekrutacyjne są verifier-anchored,
- action KPI przypisuje się actorowi,
- source KPI może mieć osobną ownership policy,
- placement attribution pokazuje zarówno credited owner, jak i contributors w
  drilldown.

To jest rekomendacja, nie cicha decyzja techniczna. Product owner powinien ją
zatwierdzić przed PR wdrażającym.

### 16.4. Konkursy

Wszystkie konkursy muszą używać tego samego projection i policy. Surowe liczenie
stage moves nie jest dopuszczalne.

### 16.5. Freeze

Obecny competition autofreeze ma dwa dodatkowe błędy:

- SELECT scalar_one_or_none na zbiorze TOP 3 może rzucić MultipleResultsFound;
- check-then-delete-rewrite jest podatny na concurrency wielu replik.

Docelowo:

- SELECT EXISTS albo operation row,
- advisory lock/lease,
- immutable CompetitionResultRevision,
- jeden active revision,
- korekta przez superseding revision,
- pełny audit.

### 16.6. Źródła

Projection źródła zawiera:

- candidate_id,
- optional application/job id,
- source taxonomy id/version,
- captured_at,
- source event type,
- provenance,
- confidence,
- is_backfilled,
- original legacy value.

### 16.7. KPI targets

Target jest effective-dated:

- target set,
- role context,
- team/user override,
- valid dates,
- metric version,
- period type,
- unit,
- approved_by,
- reason.

Zmiana targetu w połowie okresu wymaga jawnej polityki proracji.

---

## 17. KPI Coach i workery

### 17.1. Coach jako decyzja, nie bezpośrednia wysyłka

~~~text
Metric observations
    ↓
EvaluationRun
    ↓
NudgeDecision: eligible / skip wraz z reason code
    ↓
NudgeMessage planned
    ↓
Moduł 6 Outbox / Delivery
    ↓
sent / failed / unknown
~~~

### 17.2. Truthful counters

Każdy run raportuje osobno:

- users_considered,
- metrics_evaluated,
- decisions_eligible,
- decisions_skipped,
- messages_planned,
- messages_enqueued,
- deliveries_sent,
- deliveries_failed,
- deliveries_unknown.

Dry-run kończy się na planned. Nie zwiększa sent.

### 17.3. Skip reason taxonomy

- feature_disabled,
- dry_run,
- user_ineligible,
- no_target,
- metric_unavailable,
- target_already_met,
- quiet_hours,
- max_frequency,
- duplicate,
- channel_unavailable,
- period_closed,
- stale_source.

### 17.4. Reminder sequence

Sequence 1/2/3 jest częścią logical key. Policy definiuje:

- threshold,
- earliest time,
- required progress,
- channel,
- copy version,
- max per period.

### 17.5. Scheduler

Nie opierać należnej pracy na dziesięciominutowym oknie zegara. Persisted
schedule zapisuje scheduled_for. Worker claimuje due runs.

### 17.6. Lease

Każdy multi-replica worker:

- claim/lease owner,
- heartbeat,
- lease expiry,
- idempotency key,
- last success/error,
- next due,
- counters.

Pierwsze workery do migracji:

1. competition autofreeze,
2. FX sync,
3. LinkedIn/Proxycurl,
4. KPI Coach,
5. analytics shadow comparator.

### 17.7. LinkedIn/Proxycurl

Obecnie process-local semaphore nie chroni wielu replik. Potrzebne:

- DB claim batch z SKIP LOCKED albo durable queue,
- per-candidate operation id,
- provider budget counter,
- lease expiry,
- no duplicate paid call,
- reconciliation.

### 17.8. FX worker

Obecny sleep 24h od startu nie jest harmonogramem biznesowym. Potrzebne:

- persisted watermark,
- scheduled date,
- history backfill,
- idempotent upsert,
- singleton/partition-safe execution,
- alert na brak kursu.

### 17.9. Operational truth

Sam fakt, że asyncio task nie jest done, nie oznacza zdrowia. Snapshot/ops
powinien zwracać dla workera:

- enabled/configured,
- lease owner,
- last_started,
- last_success,
- last_error code/time,
- processed/failed,
- backlog,
- next_due,
- oldest due age.

---

## 18. Frontend i information architecture

### 18.1. Jeden analytics home

Po cutover:

- /dashboard jest canonical analytics home,
- / może przekierować przed renderem do właściwego home,
- sidebar używa jednej trasy,
- /insights staje się zestawem views w canonical shell albo redirectem,
- stare dashboardy rolowe przestają odpalać zapytania.

### 18.2. Cutover routing

Decyzja routingowa następuje przed montażem danych. Tryby:

- off — legacy home,
- shadow — legacy home, server-side comparator działa niezależnie,
- canary — canonical home dla wybranej cohort/role,
- live — canonical home,
- rollback — natychmiastowa zmiana route owner bez zmiany danych.

### 18.3. Access context

Frontend pobiera /auth/me/access-context:

- user,
- all roles,
- capabilities,
- allowed sections,
- scoped resource summary,
- analytics rollout assignment,
- access_revision.

### 18.4. Views

Rekomendowane:

- Mój dzień / moje KPI,
- Zespół,
- Rekrutacja,
- Klienci/Delivery,
- Finanse,
- Zarząd,
- Operacje i jakość danych dla admina.

Widoczność pochodzi z capability response, nie primary role.

### 18.5. Period model

URL jest źródłem prawdy:

- view,
- period preset,
- date_from/date_to,
- as_of,
- comparison.

Nieprawidłowy URL jest canonicalizowany przez replace. Back/forward odtwarza
stan.

### 18.6. Widget boundary

Jeden komponent:

- loading i refreshing oddzielnie,
- forbidden,
- disabled,
- unconfigured,
- unavailable,
- error,
- empty,
- partial,
- stale,
- ready.

Pokazuje:

- resolved period/as-of,
- generated at,
- freshness,
- coverage,
- retry,
- bezpieczny error code,
- diagnostics tylko dla uprawnionych.

### 18.7. Empty versus zero

- empty — brak obserwacji w prawidłowo odczytanym zakresie,
- zero — prawidłowa obserwacja o wartości 0,
- unavailable — brak wiarygodnej obserwacji,
- forbidden — nie wolno pytać.

### 18.8. Label wiąże się z metric id

Każda karta deklaruje metric_id. Test komponentu sprawdza właściwe pole i label.
Zapobiega to sytuacji clients.total opisanej jako aktywne.

### 18.9. Drilldown

Kliknięcie liczby:

- zachowuje period/as_of,
- respektuje row/field scope,
- pokazuje definicję i quality,
- nie pobiera PII, jeżeli użytkownik nie ma capability.

### 18.10. Accessibility

- prawdziwy tablist/tab/tabpanel,
- aria-selected/aria-controls,
- toggle group z accessible name,
- spinner role=status i tekst,
- error role=alert, gdy właściwe,
- keyboard-accessible rows,
- tabela ma caption i headers,
- wykres ma tekstowe podsumowanie,
- heatmapa nie polega wyłącznie na kolorze/title.

### 18.11. Mobile

Testy 320×568:

- header/period wrap,
- karty nie wymagają poziomego scroll całej strony,
- tabele w lokalnym overflow container,
- sticky controls nie zasłaniają treści,
- wartości finansowe zawijają się bez obcięcia jednostki.

### 18.12. Design tokens

Usunąć hardcoded colors z nowych/cutover surfaces. Legacy, które zaraz będzie
usuwane, naprawiać tylko tam, gdzie ekran pozostanie przez rollout.

---

## 19. DynaReporter — plan wygaszenia

### 19.1. Zasada

„Read-only” oznacza:

- backend odrzuca wszystkie mutacje,
- UI nie oferuje mutacji,
- archive data jest immutable,
- każdy odczyt ma capability,
- dostęp jest audytowany,
- znana jest data usunięcia.

### 19.2. Etap 0 — containment

- central block write methods,
- route capability inventory,
- banner z właściwym stanem migracji,
- usunięcie linku do starego reports.dynaminds.pl, jeżeli nie jest zatwierdzonym
  archive,
- wyłączenie admin-dashboard inputs.

### 19.3. Etap 1 — consumer telemetry

Dla każdej trasy:

- request count,
- unique roles/users bez PII w metrykach,
- response status,
- last accessed,
- successor route,
- export/download usage.

### 19.4. Etap 2 — preservation matrix

| Obszar | Właściciel legacy | Następca | Czy historia potrzebna | Forma zachowania |
|---|---|---|---|---|
| recruitment KPI | Dyna tables/views | canonical KPI | tak | immutable export/snapshot |
| Board P&L | Dyna snapshots | canonical finance | tak | oddzielne legacy series |
| placements | Dyna/manual | Moduł 4 | tak | reconciliation + archive |
| master data | Dyna | właściwy moduł | zależnie | migrate or export |
| competitions/HOF | Dyna | canonical competition | tak | immutable result revisions |
| admin configuration | Dyna | canonical config | tak dla audit | config history export |

### 19.5. Etap 3 — archive API

Osobny namespace, np. /api/archive/dynareporter:

- GET only,
- immutable typed schemas,
- jawny source/export id,
- read audit,
- brak zależności od DYNAREPORTER_MODE write routerów.

### 19.6. Etap 4 — redirects/tombstones

- report routes → canonical successor z zachowaniem kontekstu,
- admin writer routes → tombstone,
- archive routes pozostają tylko dla uprawnionych,
- 410 dla nieobsługiwanych direct URLs.

### 19.7. Etap 5 — wyłączenie API

Warunki:

- 30 dni zero ruchu lub zatwierdzony wyjątek,
- wszystkie preservation rows complete,
- reconciliation signed off,
- restore drill archive,
- legal/retention approval.

### 19.8. Etap 6 — usunięcie tabel

To jest osobna, destrukcyjna decyzja wymagająca jawnej zgody. Najpierw:

- backup,
- checksum manifest,
- restore test,
- retention date,
- owner,
- rollback runbook.

Plan implementacyjny nie autoryzuje DROP TABLE.

---

## 20. Snapshoty, cutover i shadow parity

### 20.1. Snapshot integrity

Checksum musi obejmować:

- metric id/version,
- period/as_of,
- dimensions,
- value/unit/currency,
- source,
- extraction version.

Odczyt weryfikuje checksum. Konflikt porównuje istniejącą treść; różnica jest
incidentem.

### 20.2. Source key

Reader zawsze wybiera jawny source. Brak source nie oznacza „pierwszy pasujący”.

### 20.3. Coverage

Backfill ma manifest:

- expected periods,
- expected metric families,
- found snapshots,
- missing,
- checksum status,
- extraction version.

### 20.4. Comparison classes

- exact,
- expected_semantic_difference,
- timing/late-arrival,
- scope mismatch,
- source coverage,
- calculation bug,
- unknown.

### 20.5. Progi

Nie wszystkie metryki mają tolerancję 1 PLN.

- count facts: exact,
- Decimal money z identyczną definicją: exact po ustalonym rounding,
- ratios: numerator/denominator exact, display rate tolerance tylko UI,
- legacy vs nowa semantyka: inconclusive, nie pass.

### 20.6. Canary

Canary może być:

- per role,
- per reporting team,
- per module/view,
- per explicit user allowlist.

Nie może być wyłącznie globalnym boolean.

### 20.7. Rollback

Rollback:

- zmienia active cutover revision,
- nie usuwa nowej historii,
- invaliduje cache,
- zapisuje aktora/reason,
- emituje audit/alert,
- routing wraca do ostatniego stabilnego ownera.

---

## 21. API, codegen, cache i performance

### 21.1. Endpoint-specific DTO

Każdy endpoint ma response model. Przykład:

~~~text
AnalyticsResponse[FinanceSummaryData]
AnalyticsResponse[RecruitmentOverviewData]
AnalyticsResponse[TeamKpiData]
~~~

Jeżeli framework nie generuje dobrze generic schema, użyć jawnych klas.

### 21.2. Decimal

- backend Decimal,
- JSON string,
- frontend Decimal-compatible string,
- formatowanie na końcu,
- brak JS number dla obliczeń finansowych.

### 21.3. OpenAPI codegen

Pipeline:

1. wygeneruj OpenAPI z backendu,
2. waliduj,
3. wygeneruj TypeScript,
4. format,
5. fail CI na diff,
6. frontend importuje tylko generated types/client adapter.

### 21.4. Semantic contract gate

CI wykrywa:

- schema field addition/removal,
- required/optional,
- enum change,
- security/capability metadata,
- query params,
- Decimal representation,
- PII/finance classification,
- metric id/version.

### 21.5. Recursive privacy test

Przechodzi cały payload:

- wszystkie elementy list,
- nested dicts,
- pagination,
- optional variants.

Nie ogranicza się do pierwszych 20 elementów.

### 21.6. Cache hierarchy

Etap 1:

- bounded process cache,
- generation epochs,
- singleflight,
- metrics.

Etap 2, jeżeli potrzebne:

- shared Redis/DB cache,
- encrypted transport,
- scoped key,
- domain invalidation,
- stampede protection.

Materialized facts mogą być lepsze niż cache drogich ad-hoc queries.

### 21.7. Invalidation events

- contract terms changed,
- contract dates/status corrected,
- FX inserted/corrected,
- adjustment approved/reversed,
- placement corrected,
- team membership changed,
- target changed,
- cutover revision activated,
- source sync watermark advanced.

### 21.8. Performance budgets

Przykładowe początkowe cele do zmierzenia:

- overview p95 < 500 ms warm, < 1500 ms cold,
- dashboard critical bundle < 2 s API completion,
- finance trend max 24 points domyślnie,
- no N+1 by client/month,
- bounded response rows,
- cancellable requests,
- query timeout.

Nie przyjmować tych liczb jako SLO bez pomiaru baseline. Claude ma zapisać
baseline i uzgodnić finalny budżet.

### 21.9. Query gates

- SQL count tests,
- EXPLAIN ANALYZE na reprezentatywnym fixture,
- index usage,
- no sequential scan na pełnym CandidateStage w hot path bez uzasadnienia,
- load test przy realistic cardinality,
- memory limit dla export.

---

## 22. Migracje, startup, health i CI

### 22.1. Krytyczny problem startup

Production entrypoint kontynuuje po nieudanym alembic upgrade heads. Safety-net
DDL i create_all również są best-effort. Zielony proces może więc wystartować
bez wymaganych tabel lub views Analytics.

To jest blocker niezależny od samej jakości dashboardu.

### 22.2. Docelowa polityka

Produkcja:

- migration failure = startup failure,
- required schema readiness = false → health unhealthy/503,
- żadnego create_all jako naprawy produkcyjnej,
- safety net tylko jawnie w trybie developerskim albo jako osobna, audytowana
  operacja.

### 22.3. Wiele Alembic heads

Admin snapshot nie może używać scalar_one_or_none dla tabeli z wieloma heads.
Powinien:

- odczytać zestaw applied heads,
- porównać z expected repository heads,
- zwrócić missing/unexpected,
- raportować migration graph version.

### 22.4. Required analytics objects

Readiness sprawdza:

- canonical views/tables,
- snapshot/cutover tables,
- financial adjustments,
- FX tables/indexes,
- KPI nudge/evaluation tables,
- team scope tables po wdrożeniu,
- minimalne query smoke.

### 22.5. Backup drill

Obecny workflow może być zielony bez sekretu i po błędzie restore. Używa też
upgrade head zamiast heads.

Naprawa:

- required secret missing → fail lub jawny skipped status kontrolowany polityką,
- pg_restore error → fail,
- alembic upgrade heads,
- row/count/checksum assertions dla Analytics, snapshots, cutovers, FX,
  adjustments, competitions i critical views,
- test zapytania canonical dashboard,
- raport restore duration i artifact.

### 22.6. Test selection

Hosted CI uruchamia selektywną listę i pomija część istniejących testów:

- FX,
- Proxycurl,
- KPI Coach,
- KPI engine/messages,
- reports clients/MRR,
- competition autofreeze,
- część Contract Analytics.

Moduł potrzebuje jawnego analytics test manifest albo marker, którego nie można
pominąć przy dodaniu nowego testu.

### 22.7. Required test classes

- unit metric semantics,
- integration DB facts,
- migration upgrade heads,
- RBAC/field/row matrix,
- multi-role provenance,
- finance effective-dated,
- FX missing/stale/concurrent,
- adjustment lifecycle,
- shadow parity,
- cutover concurrency/CAS/rollback,
- worker lease/restart,
- frontend states,
- accessibility,
- E2E role/routes,
- production smoke.

### 22.8. Health versus snapshot

/api/health:

- proces/database/schema readiness,
- status źródeł wpływający na ogólną politykę.

/api/admin/snapshot:

- szczegółowe workery,
- source watermarks,
- analytics parity,
- cutover state,
- cache,
- query latency,
- data quality.

Health nie musi być unhealthy przez każdy stale analytics source, ale musi
przekazać degraded i nigdy nie udawać kompletności samej metryki.

---

## 23. Szczegółowy plan implementacyjny dla Claude — 43 sloty PR

### 23.1. Zasady wspólne dla każdego PR

Claude ma przed rozpoczęciem każdego PR:

1. wykonać git fetch origin;
2. potwierdzić git log origin/main..HEAD;
3. pracować na świeżej branchy feat/, fix/ albo chore/;
4. sprawdzić, czy zakres nie został już wdrożony;
5. przeczytać AGENTS.md oraz pliki bezpośrednio dotykane zmianą;
6. zapisać baseline testu lub zachowania, które PR poprawia;
7. nie absorbować lokalnego WIP;
8. nie uruchamiać Dockera lokalnie.

Każdy PR musi mieć:

- jeden problem i mierzalny rezultat,
- jawne out-of-scope,
- migration/backfill/rollback, jeśli dotyczy,
- negatywne testy autoryzacji, jeśli dotyka danych,
- test jakości/error state, jeśli dotyka metryki,
- changelog metryki, jeśli zmienia definicję,
- najmniejszą sensowną weryfikację host-native,
- zielone hosted CI,
- squash merge,
- exact-SHA production health,
- Chrome verification dla UI,
- completion note z dowodami.

### 23.2. Zakazane skróty

- Nie przełączać live tylko dlatego, że endpoint zwraca 200.
- Nie zmieniać definicji metryki bez nowej wersji.
- Nie używać UI hide jako security.
- Nie zwracać zero przy błędzie.
- Nie sumować walut nominalnie.
- Nie używać dzisiejszych stawek dla historii.
- Nie tworzyć nowego local worker framework, jeżeli Moduł 6 dostarczył kernel.
- Nie modyfikować zatwierdzonego snapshotu lub wyniku konkursu w miejscu.
- Nie usuwać Dyna tabel bez osobnej zgody.
- Nie łączyć migracji fail-fast z dużą zmianą obliczeń finansowych.
- Nie włączać canary w tym samym deployu, w którym zmienia się semantyka.

---

### Fala A — containment i prawda operacyjna

#### PR-00 — Baseline, inventory i golden fixtures

Cel:

- zamrozić mierzalny punkt odniesienia przed zmianami.

Zakres:

- inventory wszystkich analytics/report/KPI/Dyna routes:
  - method,
  - response model,
  - capability,
  - allowed section,
  - row scope,
  - consumer frontend,
  - planned successor;
- inventory metric labels → metric IDs → query owners;
- inventory Dyna writers;
- inventory background workers związanych z Modułem 7;
- inventory tables/views/indexes i Alembic heads;
- wybrać zanonimizowany golden dataset obejmujący:
  - multi-role,
  - dwa zespoły,
  - pending/rejected/approved verification,
  - re-entry stage,
  - multi-currency contract,
  - future rate schedule,
  - approved adjustment,
  - legacy-only source,
  - three competition winners.

Artefakty:

- docs/analytics/route-inventory.md,
- docs/analytics/metric-catalog-baseline.md,
- backend/tests/fixtures/analytics_golden.*,
- skrypt read-only baseline export.

Testy:

- inventory test failuje po dodaniu niezmapowanej route w namespace;
- golden fixture ładuje się deterministycznie.

Akceptacja:

- każda istniejąca powierzchnia ma ownera i następcę;
- baseline wartości jest zapisany z definition notes, nie traktowany jako
  automatycznie poprawny.

Rollback:

- brak runtime zmian; usunięcie artefaktów testowych.

#### PR-01 — Centralne RBAC dla wszystkich Dyna GET

Cel:

- zamknąć dostęp viewer/nieuprawnionej roli do poufnych raportów legacy.

Zakres backend:

- centralna deklaratywna mapa Dyna route family → capability/section;
- dependency łączy capability, allowed_sections i resource scope;
- fail-closed dla trasy bez mapowania;
- objąć m.in. sales management, rekrutację, Hall of Fame, KPI, Board,
  delivery, clients MRR i admin configuration;
- bezpieczny viewer aggregate tylko jako osobny schema/endpoint, jeśli
  biznesowo potrzebny.

Zakres frontend:

- guard routingu jako UX, nie źródło prawdy;
- brak requestu do forbidden endpoint;
- ekran 403 z successor/back link.

Testy:

- parametryczna macierz wszystkich ról × route families;
- multi-role;
- direct API i direct URL;
- recursive field denylist;
- zwykły user nie otrzymuje person ID/name/email/ranking/award;
- HoR nie otrzymuje finance.

Akceptacja:

- zero Dyna GET opartych wyłącznie na CurrentUser dla danych poufnych;
- inventory gate failuje przy nowej niezabezpieczonej route.

Rollback:

- feature emergency bypass wyłącznie break-glass admin i audit; nie globalne
  wyłączenie guardów.

#### PR-02 — Prawdziwy Dyna read-only

Cel:

- usunąć legacy split-brain.

Zakres:

- centralny middleware/dependency:
  - read_only przepuszcza GET/HEAD/OPTIONS,
  - blokuje POST/PUT/PATCH/DELETE;
- kod odpowiedzi DYNAREPORTER_READ_ONLY;
- link do canonical successor;
- osobny maintenance mode tylko jeśli zatwierdzony:
  - off by default,
  - admin break-glass,
  - time limited,
  - audit reason;
- UI usuwa/disable writers na wszystkich Dyna pages;
- admin-dashboard staje się tombstone/archive;
- próba write jest logowana bez payload PII.

Testy:

- enumerate all Dyna write routes;
- assert no state change;
- CSRF/direct request;
- UI nie pokazuje aktywnego submit;
- maintenance mode expiry.

Akceptacja:

- produkcyjny admin-dashboard nie pozwala zapisać danych;
- każda mutacja daje deterministyczną odpowiedź i zero DB writes.

Rollback:

- maintenance override, nie powrót do domyślnego writable.

#### PR-03 — Truthful error/empty/zero containment

Cel:

- awaria nie może wyglądać jak dobry wynik.

Zakres:

- wspólny minimalny LegacyWidgetStateAdapter dla obecnych Insights/dashboardów;
- usunąć:
  - error → [],
  - error → 0,
  - silent return null,
  - fallback awards 5000/3000/2000;
- poprawić SLA Alerts, client risk, HoR cards, Funnel, TTH, Heatmap, Board KPI,
  Champions, Tenders, Invite Links;
- rozróżnić 403/404/500/timeout/offline/empty.

Testy:

- mock 403, 500, timeout, empty i valid zero dla każdego critical widget;
- tekst nie zawiera „wszystko w normie” przy błędzie;
- valid zero nadal renderuje 0.

Akceptacja:

- żaden krytyczny widget nie generuje liczby z fallbacku;
- Sentry/error log nie ujawnia surowego backend message użytkownikowi.

Rollback:

- per-widget adapter może być wycofany, ale nie przywracać fałszywych zer.

#### PR-04 — Fail-fast migracje i schema readiness

Cel:

- nie uruchamiać produkcji na niepełnym schemacie.

Zakres:

- production alembic upgrade heads ma failować startup przy błędzie;
- create_all i best-effort analytics DDL wyłączone w prod;
- jawna flaga dev-only dla safety net;
- expected Alembic heads set;
- required analytics object checks;
- /api/health database/schema status;
- admin snapshot zwraca wszystkie applied/missing/unexpected heads;
- ujednolicić entrypoint docs i CI.

Testy:

- migration failure → non-zero process;
- missing view/table → unhealthy/503;
- 25+ heads poprawnie odczytane jako set;
- dev safety net nie aktywuje się w production env;
- upgrade heads od empty i representative prod-like state.

Akceptacja:

- nie można dostać healthy bez wymaganych objects;
- failure reason jest sanitized i widoczny operatorsko.

Rollback:

- rollback kodu tylko po przywróceniu sprawnego schematu; nie włączać
  best-effort w prod jako obejścia.

#### PR-05 — Freeze niebezpiecznych aktywacji i debug endpoint

Cel:

- uniemożliwić przypadkowe live/cutover przed readiness.

Zakres:

- ANALYTICS_V1_MODE=live dla finance/executive wymaga explicit
  temporary_allow tylko w non-prod do czasu PR-39/40;
- cutover write endpoint zwraca precondition failed bez manifestu;
- debug-fire-nudge:
  - non-prod lub break-glass,
  - nie kasuje logu,
  - nie zwraca traceback,
  - test recipient/channel,
  - osobny audit type;
- dodać admin warning „shadow evidence unavailable”.

Testy:

- production live activation bez manifestu odrzucona;
- debug nie modyfikuje dedupe history;
- no real delivery w dry/test mode.

Akceptacja:

- operator nie może jednym dowolnym stringiem przełączyć niezweryfikowanej
  rodziny.

Rollback:

- jawny emergency config z audytem; nigdy silent bypass.

### Gate po Fali A

Fala A jest zakończona, gdy:

- legacy GET i write są centralnie zabezpieczone,
- false-zero przypadki krytyczne są usunięte,
- produkcja nie startuje po nieudanej migracji,
- live/cutover nie da się aktywować bez preconditions,
- wszystkie PR-y są na produkcji i exact SHA jest potwierdzony.

---

### Fala B — kontrakt metryk, czasu i jakości

#### PR-06 — Typed Metric Registry v1

Cel:

- ustanowić jedno źródło definicji.

Zakres:

- modele MetricDefinition i enums:
  - kind,
  - grain,
  - unit,
  - time semantics,
  - owner,
  - dependency,
  - scope,
  - classification,
  - version compatibility;
- zarejestrować wszystkie metryki Analytics v1 oraz krytyczne legacy metrics;
- /analytics/v1/meta/metrics generowane z registry;
- definition changelog;
- unique metric_id/version.

Testy:

- completeness: każdy v1 response field value ma metric definition;
- no duplicate IDs;
- flow musi mieć event time;
- snapshot musi mieć as_of rule;
- cohort musi mieć cohort i observation semantics;
- finance wymaga unit/currency policy.

Akceptacja:

- METRIC_DEFINITIONS nie jest ręczną niepełną listą;
- CI failuje przy niezarejestrowanej nowej metryce.

Rollback:

- registry może początkowo opisywać legacy bez zmiany obliczeń.

#### PR-07 — AnalyticsClock i period/as-of contract

Cel:

- usunąć fałszywe okresy i date.today.

Zakres:

- wstrzykiwany AnalyticsClock Europe/Warsaw;
- typy FlowPeriod, SnapshotAsOf, CohortWindow;
- endpointy odrzucają nieistotne params 422;
- pipeline snapshot przyjmuje as_of albo tylko current snapshot bez period;
- finance endpoints przyjmują as_of;
- executive response ma osobne time_context per section;
- resolved period/as_of w kopercie;
- invalid enum nie mapuje się na week.

Testy:

- UTC/Warsaw midnight;
- DST spring/fall;
- custom max range;
- start/end half-open;
- snapshot does not accept period;
- custom 2025 finance nie zwraca today label;
- frozen clock.

Akceptacja:

- każdy metric field można jednoznacznie przypisać do flow/snapshot/cohort;
- zero procesowego date.today w analytics hot paths.

Rollback:

- kompatybilne query aliases mogą istnieć jeden release z deprecation header,
  lecz nie mogą kłamać w odpowiedzi.

#### PR-08 — MetricReadinessService i source watermarks

Cel:

- quality ma wynikać z realnego stanu źródła.

Zakres:

- readiness adapters dla:
  - database projections,
  - Traffit,
  - CloudTalk,
  - FX,
  - source attribution,
  - snapshots,
  - contract terms;
- source watermark persistence/read;
- coverage numerator/denominator;
- freshness SLA z registry;
- per-metric quality;
- issue versus notice;
- admin readiness endpoint.

Testy:

- enabled but missing credentials;
- last sync failed;
- stale watermark;
- low mapping coverage;
- one dependency unavailable affects only dependent metric;
- converted foreign currency notice remains complete.

Akceptacja:

- source_watermarks nie jest zawsze puste;
- CloudTalk unhealthy nie ukrywa placement KPI;
- complete wymaga spełnienia source contract.

Rollback:

- w razie problemu quality może być bardziej konserwatywne unavailable, nie
  domyślnie complete.

#### PR-09 — Bounded cache, singleflight i generation epochs

Cel:

- zatrzymać wzrost pamięci i cross-replica dryf.

Zakres:

- LRU/TTL z max entries/bytes;
- periodic cleanup;
- singleflight per cache key;
- cache metrics;
- generation epochs per metric family/source;
- scoped keys z access revision;
- invalidation API/event hooks;
- cutover/FX/terms/adjustment/team/target writes bumpują epoch;
- rate limit custom ranges.

Testy:

- capacity/eviction;
- TTL cleanup bez reread samego klucza;
- concurrent requests compute once;
- two simulated replicas observe bumped epoch;
- scope isolation;
- cutover invalidates.

Akceptacja:

- pamięć jest bounded;
- brak serving starej kwoty po zatwierdzonej korekcie ponad zdefiniowany
  invalidation bound.

Rollback:

- bezpiecznym fallbackiem jest cache disabled, nie powrót do unbounded dict.

### Gate po Fali B

- wszystkie v1 metryki są sklasyfikowane,
- API nie kłamie o czasie,
- quality jest per metric i ma watermarks,
- cache jest bounded/scoped,
- nie zmieniono jeszcze produkcyjnej semantyki finansowej bez kolejnych fal.

---

### Fala C — kanoniczne fakty, scope i KPI

#### PR-10 — Kwalifikacja milestone statuses

Cel:

- rejected/pending nie są sukcesem.

Zakres:

- poprawić canonical milestone projection/view;
- verification_submitted i verification_approved jako osobne facts;
- odfiltrować rejected;
- obsłużyć resubmission/re-entry;
- migration replacement view oraz entrypoint mirror zgodnie z repo contract;
- backfill/reconciliation counts.

Testy:

- pending only;
- pending → rejected;
- pending → active;
- rejected → resubmitted → active;
- duplicated stage;
- cancelled placement.

Akceptacja:

- pending/rejected approved count = 0;
- fixture active count zgodny we wszystkich query consumers po przepięciu.

Rollback:

- old view zachowany pod versioned name do końca parity.

#### PR-11 — Jedna credited milestone projection

Cel:

- jedna atrybucja dla Analytics, KPI, Coach, reports i competitions.

Zakres:

- canonical projection z actor i credited owner;
- jawna CreditPolicy version;
- zatwierdzić verifier-anchored dla outcome albo udokumentować inną decyzję;
- przepiąć:
  - Analytics v1,
  - KPI panel,
  - KPI team,
  - KPI Coach engine,
  - quarterly/monthly competitions,
  - Hall of Fame,
  - recruitment report;
- drilldown contributors.

Testy:

- ten sam golden dataset daje identyczne KPI per surface;
- move by different actors after verification;
- verifier inactive/transfer;
- no verifier;
- policy version bump.

Akceptacja:

- jeden placement nie zmienia właściciela zależnie od ekranu;
- monthly competition nie liczy raw duplicate moves.

Rollback:

- dual-read comparison; nie przełączać wszystkich consumers bez parity.

#### PR-12 — Source attribution projection i backfill

Cel:

- objąć całą populację i rozdzielić origin od application acquisition.

Zakres:

- taxonomy mapping/version;
- projection z CandidateSourceEvent i jawnego fallback;
- idempotentny backfill Candidate.source/source_enum;
- provenance is_backfilled/original value;
- unknown bucket;
- coverage;
- osobne metrics candidate origin i application/job source;
- cohort conversion z observation_as_of/maturity.

Testy:

- only legacy source;
- conflicting legacy/event;
- multiple applications/jobs;
- unknown taxonomy;
- later hire after cohort;
- coverage threshold;
- backfill rerun.

Akceptacja:

- denominator odpowiada jawnie określonej populacji;
- 54k-population nie może wyglądać jak zero z powodu braku eventów;
- rate ma numerator/denominator.

Rollback:

- backfill jest additive i oznaczony; można wyłączyć projection version bez
  usuwania provenance.

#### PR-13 — ReportingTeam i membership history

Cel:

- zastąpić organization_scope dla DL.

Zakres:

- tabele ReportingTeam i Membership;
- valid_from/valid_to;
- manager;
- revision;
- admin UI/API assignment;
- bootstrap z istniejących assignmentów po uzgodnieniu źródła;
- unassigned report;
- current i historical scope helpers.

Migration:

- additive tables;
- backfill dry-run;
- collision/orphan report;
- activation dopiero po completeness gate.

Testy:

- transfer;
- overlapping membership rejected;
- secondary team policy;
- inactive user;
- manager change;
- historical event attribution.

Akceptacja:

- wszystkie aktywne osoby operacyjne mają jawny team lub unassigned;
- brak overlap bez zatwierdzonego matrix membership.

Rollback:

- dual-read org scope tylko admin/HoR; DL nie wraca cicho do global.

#### PR-14 — Policy engine z role provenance

Cel:

- poprawić multi-role i assigned-client finance.

Zakres:

- policy decision wiąże capability z granting role i resource scope;
- client/team/user resources;
- field classifications;
- audit decision id;
- zastosować do v1, legacy Insights, Dyna i Contract Analytics;
- DL assigned clients only, jeśli tak zatwierdzono;
- HoR finance deny default.

Testy:

- DL+TAC nie dostaje global finance;
- recruiter+viewer;
- admin multi-role;
- cross-team user id enumeration;
- cross-client finance;
- revoked membership/access revision.

Akceptacja:

- każda wrażliwa odpowiedź ma allow decision z provenance;
- negative tests sprawdzają brak pól, nie tylko status.

Rollback:

- policy canary per endpoint; default deny dla niejednoznacznego przypadku.

#### PR-15 — Effective-dated KPI Target Policy

Cel:

- jeden target dla multi-role i historii.

Zakres:

- TargetSet/TargetRevision;
- metric version;
- role context/team/user override;
- effective dates;
- period type;
- prorating decision;
- resolver zwraca target + provenance;
- przepiąć panel, engine i Coach.

Testy:

- primary/secondary role;
- mid-period target change;
- missing target;
- team override;
- user override;
- expired target;
- incompatible metric version.

Akceptacja:

- panel i Coach pokazują ten sam target;
- brak targetu daje unconfigured, nie zero.

Rollback:

- legacy config adapter może dostarczać revision zero do czasu migracji.

#### PR-16 — Competition freeze correctness

Cel:

- naprawić crash TOP 3 i concurrency.

Zakres:

- frozen check przez EXISTS;
- singleton lease/advisory lock tymczasowo, potem kernel PR-34;
- immutable CompetitionResultRevision;
- zakazać delete+rewrite;
- admin correction tworzy superseding revision;
- audit/reason;
- canonical credited projection z PR-11.

Testy:

- one/two/three winners;
- concurrent replicas;
- rerun idempotent;
- admin correction;
- tie;
- zero eligible.

Akceptacja:

- prawidłowy TOP 3 nie rzuca MultipleResultsFound;
- jeden period ma jedną active revision;
- historia nie jest kasowana.

Rollback:

- active revision pointer może wrócić do poprzedniej revision.

#### PR-17 — Dashboard contradictions hotfix

Cel:

- usunąć widoczne sprzeczności jeszcze przed pełnym UI cutover.

Zakres:

- recent hires z canonical typed hires endpoint/fact;
- count i list wspólne time semantics;
- clients active card używa active;
- activity leaderboard:
  - total_displayed,
  - other_actions,
  - total_all;
- team panel ogranicza query do okresu i uprawnionych osób;
- partial-month comparison.

Testy:

- placements count >0 and recent list;
- pagination explanation;
- clients total vs active;
- activity other actions;
- no historical zero rows outside scope;
- MTD comparison.

Akceptacja:

- produkcja nie pokazuje jednocześnie 11 placements i „brak ostatnich
  zatrudnień” dla tego samego zakresu;
- label odpowiada field.

Rollback:

- canonical endpoint pozostaje; UI może wrócić do poprzedniego layoutu, nie
  poprzedniej fałszywej metryki.

### Gate po Fali C

- milestone jest kwalifikowany statusowo,
- wszystkie KPI i konkursy mają jedną credit policy,
- source coverage jest mierzone,
- DL ma prawdziwy team scope,
- multi-role nie rozszerza scope,
- targets są effective-dated,
- production dashboard nie ma znanych sprzeczności count/list.

---

### Fala D — finanse i historia

#### PR-18 — Atomowy ContractEconomicTerms

Cel:

- jedna effective-dated prawda ekonomiki.

Zależność:

- uzgodnić z Modułem 5; jeżeli Moduł 5 już ją dostarczył, rozszerzyć istniejący
  model zamiast tworzyć duplikat.

Zakres:

- versioned terms obejmujące sell/cost currency/rate/unit/hours;
- no overlaps;
- terms_at(as_of);
- future terms nie mutują base/current fields przed datą;
- current compatibility projection dla istniejącego UI;
- audit reason/source.

Migration:

- backfill legacy/base i schedules;
- dry-run conflicts;
- compare computed current properties;
- entrypoint mirror idempotent dla nowych columns/tables.

Testy:

- future rate;
- sell-only/cost-only amendments;
- unit/hours change;
- overlap;
- missing terms;
- end boundary;
- Decimal precision.

Akceptacja:

- każdy aktywny kontrakt ma dokładnie jeden terms row na testowane as_of albo
  jawny data quality error.

Rollback:

- dual-read flag; nie usuwać legacy columns w tym PR.

#### PR-19 — FX integrity i historyczny resolver

Cel:

- prawidłowe, audytowalne FX.

Zakres:

- HTTPS NBP;
- insert on conflict/upsert;
- bulk resolver;
- table number/effective date;
- history fetch by date;
- persisted watermark;
- freshness policy;
- weekend/holiday rule;
- fail-closed;
- Decimal string API;
- usunąć 1:1 fallback z reporting paths.

Testy:

- PLN;
- EUR/USD history;
- missing rate;
- stale;
- weekend;
- concurrent workers;
- upstream timeout;
- idempotent refetch;
- rate correction policy.

Akceptacja:

- brak kursu nie może zwrócić nominalnej kwoty;
- dwie repliki nie wycofują batcha przez unique conflict.

Rollback:

- foreign-currency totals unavailable; nie fallback 1:1.

#### PR-20 — Canonical FinanceReadService

Cel:

- jedna agregacja dla summary/client/trend.

Zakres:

- FinanceQuery typed;
- uses PR-18 terms i PR-19 FX;
- flow versus snapshot separation;
- reporting currency;
- amount null przy incomplete total;
- known subtotal tylko diagnostics;
- client grouping set-based;
- trend bez N full scans;
- per-row quality/lineage;
- replace metrics.py finance functions za flagą.

Testy:

- historyczny as_of;
- future schedule;
- mixed currencies;
- missing/stale FX;
- two contracts one consultant;
- rounding;
- active boundary;
- query count;
- golden values.

Akceptacja:

- historyczny custom range nie zwraca dzisiejszych kwot;
- MRR/direct margin/contract count są semantycznie stabilne.

Rollback:

- v1 finance unavailable lub previous canonical version; nie legacy nominal
  mixed currency.

#### PR-21 — Financial Adjustment Ledger w agregacji

Cel:

- approved corrections rzeczywiście wpływają na właściwe raporty.

Zakres:

- kind/sign taxonomy;
- effective period;
- reporting target;
- approval immutability;
- reversal_of;
- scope;
- FX by effective date;
- FinanceReadService integration;
- invalidation epoch;
- audit.

Testy:

- draft ignored;
- approved included;
- rejected ignored;
- reversal;
- foreign currency;
- wrong client forbidden;
- month boundary;
- two approvals concurrency;
- modification after approval rejected.

Akceptacja:

- zatwierdzona korekta pojawia się dokładnie raz we właściwej metryce/okresie;
- contracted MRR nie absorbuje operating adjustment bez jawnej reguły.

Rollback:

- feature flag include_adjustments false tylko awaryjnie z degraded banner i
  audytem; ledger pozostaje immutable.

#### PR-22 — Snapshot integrity i rozdzielenie legacy series

Cel:

- historia nie zmienia znaczenia na cutover.

Zakres:

- oddzielne metric IDs dla legacy recognized revenue/operating margin/headcount;
- nie mapować do MRR/direct margin/contracts;
- checksum całego record contract;
- verify on read;
- source required;
- checksum conflict incident;
- coverage manifest;
- immutable snapshot extraction version;
- legacy/live compatibility matrix.

Testy:

- tampered value/dimension;
- two sources;
- conflict same key/different checksum;
- missing month;
- incompatible series cannot pass parity;
- extraction rerun.

Akceptacja:

- trend nie skleja nieporównywalnych serii pod jedną legendą;
- corrupt snapshot nie jest serwowany.

Rollback:

- archive snapshot read can be disabled; raw snapshot records nie są kasowane.

#### PR-23 — Legacy Contract Analytics adapter

Cel:

- aktywne stare ekrany przestają kłamać o walutach i okresach.

Zakres:

- zachować URLs;
- przepiąć margin, client, forecast, utilization-dependent finance na canonical
  services;
- Decimal strings;
- currency/quality/as_of;
- remove default convert_currency=false semantics;
- date-effective active predicate;
- deprecation telemetry/header.

Testy:

- mixed currencies;
- missing FX;
- historical rate;
- inclusive/exclusive end policy;
- frontend generated types;
- compatibility fields.

Akceptacja:

- żadna legacy suma nie miesza nominalnie EUR i PLN;
- brak kursu daje null/unavailable.

Rollback:

- endpoint unavailable z successor link; nie stara 1:1 logika.

#### PR-24 — Tender correctness

Cel:

- nie nazywać salary wartością przetargu.

Zakres:

- filter recruitment_type=tender;
- usuń tender_value z salary_max;
- amount null do czasu pola domenowego;
- jeżeli zatwierdzone, dodać Tender/TenderLot value/currency w Moduł 1;
- UI label/status i quality;
- history/backfill tylko z wiarygodnego źródła.

Testy:

- closed normal job excluded;
- tender with no value;
- tender with currency;
- mixed lots;
- cancelled/won/lost.

Akceptacja:

- wartość przetargu nigdy nie pochodzi z widełek kandydata.

Rollback:

- count-only widget.

#### PR-25 — Finance performance/materialization

Cel:

- spełnić budżety bez N×M.

Zakres:

- baseline EXPLAIN/query counts;
- bulk FX;
- set-based contract terms joins;
- ewentualne daily/monthly facts/materialized projection;
- refresh/run metadata;
- indexes;
- timeouts;
- pagination;
- max trend range.

Testy:

- realistic cardinality fixture;
- query count bounds;
- p95 benchmark in CI nightly;
- refresh concurrency;
- stale materialization quality;
- no full CandidateStage scan in unrelated finance.

Akceptacja:

- uzgodniony p95 i DB cost;
- materialization ma watermark i nie udaje live po failed refresh.

Rollback:

- canonical direct query z ograniczonym range i rate limit.

### Gate po Fali D

- effective terms są atomowe i historyczne,
- FX jest fail-closed i audytowalne,
- adjustments działają,
- wszystkie finance surfaces używają jednego engine,
- legacy history ma osobne metric IDs,
- tender salary bug jest usunięty,
- performance ma zmierzony budget.

---

### Fala E — typowane API i canonical frontend

#### PR-26 — Endpoint-specific Pydantic DTO i generated TypeScript

Cel:

- zamknąć luźny dict[str, Any].

Zakres:

- osobny data schema per endpoint;
- typed quality/watermarks/lineage;
- Decimal strings;
- discriminated response variants, jeśli potrzebne;
- OpenAPI generation;
- TypeScript codegen;
- package scripts;
- CI generated diff;
- usunąć ręczne duplikaty stats-api etapami.

Testy:

- OpenAPI schema snapshot pełny;
- required/optional;
- enums;
- Decimal representation;
- generated file clean;
- breaking-change detector.

Akceptacja:

- frontend nie definiuje ręcznie v1 payload types;
- zmiana pola failuje CI.

Rollback:

- generated client adapter może używać istniejącego HTTP layer; schema nie
  wraca do Any.

#### PR-27 — API compositions i per-metric quality

Cel:

- endpoint może zwrócić część dobrych KPI bez ukrycia ich przez jedno źródło.

Zakres:

- observations per metric;
- composition schemas;
- per-section time context;
- completed calls oddzielone od recruitment facts;
- executive flow/snapshot sections;
- all missing frontend methods;
- meta definitions linked by metric ID;
- safe viewer aggregate model.

Testy:

- CloudTalk down;
- FX down;
- source stale;
- mixed complete/partial/unavailable;
- viewer schema no PII/finance;
- all endpoint methods generated.

Akceptacja:

- awaria jednej dependency nie usuwa niezależnych metryk;
- response wyjaśnia time context każdej sekcji.

Rollback:

- client adapter wspiera przejściowo old envelope; backend zachowuje typed new
  contract.

#### PR-28 — Authoritative access context i cache invalidation

Cel:

- role/capability/cutover nie są stare przez całą sesję.

Zakres:

- /auth/me/access-context;
- bootstrap po hydration;
- revalidate on focus i policy-defined TTL;
- access_revision;
- union roles i role contexts;
- clear query cache po fingerprint change;
- logout/login isolation;
- rollout assignment w context.

Testy:

- grant/revoke w otwartej sesji;
- multi-role;
- mode/cohort change;
- two users same browser;
- stale localStorage;
- 401/403 recovery.

Akceptacja:

- revoke usuwa dostęp i cache bez ponownego logowania;
- primary role nie jest jedynym źródłem guardów.

Rollback:

- force refresh context; nie ufać wyłącznie persisted store.

#### PR-29 — Route ownership i canary-aware navigation

Cel:

- /dashboard staje się prawdziwym flow.

Zakres:

- server/middleware decision przed data fetch;
- protect /dashboard;
- sidebar link zależny od rollout assignment;
- root redirect przed DashboardV2 mount;
- default view = first allowed capability;
- invalid view canonicalization;
- off/shadow/canary/live/rollback;
- no forbidden/legacy requests before redirect.

Testy:

- każda rola;
- multi-role;
- modes;
- direct URL;
- invalid view;
- network assertions;
- back/forward.

Akceptacja:

- canary user trafia do canonical home;
- non-canary do legacy;
- zero niepotrzebnych legacy queries przed redirect.

Rollback:

- zmiana active rollout revision wraca do legacy bez deploy.

#### PR-30 — Jeden URL period/as-of model

Cel:

- selektor steruje faktycznymi danymi.

Zakres:

- hook/router state;
- period presets i custom;
- as_of dla snapshot views;
- cohort observation date;
- resolved labels;
- remove today→week mapping;
- każdy widget deklaruje time behavior;
- partial comparison policy;
- shareable URLs.

Testy:

- today one day;
- week/month/quarter/year;
- custom;
- invalid;
- DST;
- back/forward;
- copied URL;
- widget request params.

Akceptacja:

- zmiana kontrolki zmienia każdy widget oznaczony uses_global_period;
- fixed/all-time widget jawnie pokazuje własny zakres.

Rollback:

- default preset; nie ciche mieszanie okresów.

#### PR-31 — Unified WidgetBoundary

Cel:

- jeden truthful state contract.

Zakres:

- zastąpić StatsBoundary i WidgetState;
- wszystkie statusy;
- refreshing versus loading;
- generated/freshness/coverage;
- retry unavailable/error;
- safe messages;
- role=status/alert;
- token-first styles;
- telemetry state changes.

Testy:

- każda state;
- null versus zero versus empty;
- retry;
- screen reader;
- partial/stale labels;
- raw error hidden.

Akceptacja:

- derive function może wyprowadzić wszystkie deklarowane stany;
- brak hardcoded amber/hex;
- component story/test matrix.

Rollback:

- adapter z old state do new boundary; nie utrzymywać dwóch implementacji
  docelowo.

#### PR-32 — Canonical Analytics Dashboard views

Cel:

- zastąpić trzy sprzeczne warstwy jednym shell i canonical widgets.

Zakres:

- views: own/team/recruitment/clients/finance/executive/ops;
- capability-driven navigation;
- typed queries;
- canonical metric IDs;
- definitions/tooltips;
- drilldowns;
- quality/time context;
- remove duplicate calculations from UI;
- board comparable trend;
- dynamic year ranges.

Testy:

- role/view matrix;
- finance field absence;
- partial metrics;
- deep links;
- labels match IDs;
- count/list invariants;
- screenshot baselines.

Akceptacja:

- canonical dashboard pokrywa zatwierdzony preservation matrix;
- old Insights nie jest potrzebne canary cohort.

Rollback:

- route owner to legacy; canonical remains deployed for debugging.

#### PR-33 — Accessibility, mobile i design token gate

Cel:

- produkcyjna jakość UI przed live.

Zakres:

- tab semantics;
- toggle groups;
- live regions;
- keyboard rows;
- chart text alternatives;
- table captions/headers;
- 320px responsive;
- overflow containment;
- semantic tokens;
- focus management po route/filter.

Testy:

- axe;
- keyboard-only;
- screen reader labels;
- 320×568/tablet/desktop Playwright;
- dark/soft themes;
- zoom 200%;
- no page-level horizontal overflow.

Akceptacja:

- zero critical/serious axe issues w canonical routes;
- token lint nie wykrywa nowych hardcoded colors.

Rollback:

- nie włączać live dla viewport/role niespełniającego gate.

### Gate po Fali E

- API jest typowane i generuje TS,
- access context jest świeży,
- routing obsługuje canary/rollback,
- URL ma prawdziwe time semantics,
- wszystkie widgety są truthful,
- canonical views pokrywają zakres,
- accessibility/mobile gate jest zielony.

---

### Fala F — worker kernel i KPI Coach

#### PR-34 — Worker lease/runtime foundation

Cel:

- multi-replica-safe execution.

Zależność:

- reuse Moduł 6 WorkerLease/JobRun, jeśli już wdrożone.

Zakres:

- lease acquire/renew/release/expiry;
- job run;
- scheduled_for;
- idempotency key;
- heartbeat;
- last success/error;
- counters;
- next due;
- graceful shutdown;
- admin read-only status;
- advisory lock fallback tylko gdy udokumentowany.

Pierwsze migracje:

- competition freeze,
- FX,
- LinkedIn,
- KPI Coach.

Testy:

- two replicas;
- lease expiry;
- crash/reclaim;
- clock skew;
- duplicate scheduled run;
- graceful shutdown;
- disabled job.

Akceptacja:

- jedna logical run wykonuje side effects raz;
- status nie opiera się na task.done.

Rollback:

- kill-switch danego job; nie równoległy legacy scheduler.

#### PR-35 — Durable KPI evaluation i decision log

Cel:

- Coach ma audytowalną prawdę.

Zakres:

- AnalyticsEvaluationRun;
- KpiNudgeDecision;
- reason codes;
- metric observation references;
- target revision;
- policy/copy version;
- dry-run persistence;
- truthful counters;
- admin run view;
- retention/privacy.

Testy:

- target met;
- missing target;
- metric unavailable;
- stale source;
- ineligible user;
- dry-run;
- rerun same period;
- multi-role.

Akceptacja:

- dla każdej rozważanej wiadomości wiadomo, dlaczego wysłano lub pominięto;
- dry-run sent=0.

Rollback:

- disable delivery; evaluation może nadal działać shadow.

#### PR-36 — Reminder sequence, outbox i delivery

Cel:

- trzy remindery są możliwe i niezawodne.

Zakres:

- logical nudge key z sequence;
- frequency policy;
- planned message;
- Moduł 6 outbox/delivery;
- channel readiness;
- idempotency;
- quiet hours;
- persisted due schedule;
- EOD recovery;
- remove direct sends;
- debug TestDelivery.

Testy:

- sequence 1/2/3;
- duplicate run;
- restart in EOD window;
- outbox failure;
- provider unknown;
- quiet hours;
- channel disabled;
- delivery retry;
- test recipient.

Akceptacja:

- no unique constraint collision dla legalnej sekwencji;
- crash/restart nie gubi należnej wiadomości i nie duplikuje delivery.

Rollback:

- delivery kill-switch; decisions/outbox pozostają do reconciliacji.

#### PR-37 — Operations snapshot, alerts i worker docs

Cel:

- operator widzi prawdziwy stan modułu.

Zakres:

- admin snapshot:
  - schema readiness,
  - worker leases/runs,
  - FX age,
  - source watermarks,
  - coverage,
  - cache,
  - shadow parity,
  - cutover revisions,
  - Dyna traffic,
  - backlog;
- alerts;
- runbooks;
- zaktualizować liczbę/listę tasków w skill/docs;
- redact secrets/PII.

Testy:

- kill-switched task;
- alive but every run failing;
- stale lease;
- multiple Alembic heads;
- snapshot permission;
- redaction.

Akceptacja:

- „healthy worker” wymaga świeżego success według SLA, nie tylko żywego task;
- runbook wskazuje ownera i reakcję na alert.

Rollback:

- read-only snapshot może zostać ograniczony adminowi; nie usuwać telemetry
  persistence.

### Gate po Fali F

- wszystkie wskazane workery są singleton/idempotent,
- Coach ma durable evaluation i outbox,
- trzy remindery działają,
- dry-run jest prawdziwy,
- ops widzi freshness, backlog i failures.

---

### Fala G — shadow, cutover i wygaszenie legacy

#### PR-38 — Durable shadow comparator

Cel:

- shadow generuje dowód bez ruchu użytkownika.

Zakres:

- scheduled AnalyticsComparisonRun;
- module/metric sampling;
- critical full comparison;
- compare old/new typed observations;
- classify differences;
- absolute/relative/exact thresholds;
- coverage/readiness preconditions;
- trend;
- operator UI;
- alert on missing/stale run;
- no user-visible cutover.

Testy:

- exact;
- expected semantic incompatibility;
- missing rows;
- scope mismatch;
- stale source;
- comparator crash/restart;
- schedule;
- protected PII in diagnostics.

Akceptacja:

- siedem dni shadow oznacza siedem udanych expected runs z coverage, nie
  upływ kalendarza;
- każdy fail ma sample references i classification.

Rollback:

- comparator kill-switch; cutover gate automatycznie not-ready.

#### PR-39 — Cutover state machine i canary control plane

Cel:

- bezpieczne proposed → shadow_verified → canary → live → retired.

Zakres:

- enum module/metric family;
- immutable CutoverRevision;
- actor/reason;
- CAS;
- readiness manifest;
- evidence links;
- snapshot coverage;
- canary cohort;
- activation time;
- rollback pointer;
- cache invalidation;
- API/UI;
- no overwrite in place.

Testy:

- invalid transition;
- future date;
- missing evidence;
- stale evidence;
- concurrent activation;
- rollback;
- authorization;
- cache epoch;
- audit immutability.

Akceptacja:

- żaden live transition bez fresh pass i zatwierdzonej checklisty;
- rollback to poprzednia revision jest jednym bezpiecznym działaniem.

Rollback:

- wbudowany transition rollback; nie edycja DB ręcznie.

#### PR-40 — Dyna preservation manifest i archive API

Cel:

- zachować potrzebną historię bez utrzymywania writerów.

Zakres:

- preservation matrix jako dane/config;
- immutable exports;
- checksums/row counts;
- encrypted storage;
- typed GET-only archive namespace;
- capability/read audit;
- restore drill;
- mapowanie successor;
- legal retention.

Testy:

- checksum;
- unauthorized archive;
- export completeness;
- restore;
- missing source;
- duplicate extraction;
- no mutations.

Akceptacja:

- każda legacy dataset ma decyzję migrate/archive/delete-later;
- archive jest odtwarzalny;
- API nie zależy od writable Dyna routers.

Rollback:

- re-enable read-only legacy reader na ograniczony czas; writers pozostają off.

#### PR-41 — Redirects, tombstones i wyłączenie legacy per module

Cel:

- usunąć trzy konkurencyjne flow.

Warunki wejścia:

- canonical parity/gates green,
- successor coverage,
- traffic telemetry,
- archive complete,
- product sign-off.

Zakres:

- /insights routes → canonical views;
- legacy role dashboards → canonical;
- Dyna report redirects;
- writer tombstones;
- 410 unknown retired routes;
- remove old navigation;
- remove old queries/components po one-release deprecation;
- zero-traffic gate per module.

Testy:

- redirect context/period;
- direct URLs;
- bookmarks;
- no legacy network calls;
- role access;
- archive exception;
- SEO/cache headers where relevant.

Akceptacja:

- canonical user journey nie wykonuje legacy analytics requests;
- Dyna root nie reklamuje „migracja w toku” po zakończeniu;
- legacy shutdown jest per module, nie globalnym big bang.

Rollback:

- CutoverRevision rollback dla read paths; writers pozostają read-only.

#### PR-42 — Final CI, backup drill, release i production verification

Cel:

- zamknąć cały moduł dowodem, nie deklaracją.

Zakres CI:

- analytics marker/manifest obejmuje wszystkie testy modułu;
- istniejące pominięte testy FX/Proxycurl/KPI/Reports;
- competition concurrency;
- full semantic OpenAPI diff;
- generated TS clean;
- RBAC matrix;
- migration heads/readiness;
- backup restore fail-hard;
- golden parity;
- query budgets;
- axe/mobile E2E;
- canary/live smoke.

Zakres release:

- fresh origin/main re-anchor;
- hosted CI green;
- merge;
- deploy;
- exact-SHA /api/health z wymaganym User-Agent;
- schema readiness;
- shadow/canary evidence;
- Chrome verification wszystkich ról i tras;
- monitor;
- final completion report;
- legacy deletion pozostaje osobną decyzją.

Akceptacja:

- Definition of Done z sekcji 30 spełniona;
- brak znanego P0/P1;
- rollback drill wykonany;
- produkcyjny SHA i screenshots zapisane;
- final report nie nazywa deferred item „done”.

Rollback:

- aktywować poprzednią CutoverRevision;
- zachować nowe fakty/evidence;
- obserwować health i cache epoch;
- nie rollbackować migracji destrukcyjnie bez runbooka.

### Gate końcowy po Fali G

- shadow i canary mają trwały evidence,
- cutover jest wersjonowany i odwracalny,
- canonical UI jest właścicielem flow,
- Dyna jest rzeczywiście read-only/archive/tombstone,
- legacy readers są wyłączane modułami,
- backup restore i production verification są zielone.

---

## 24. Kolejność, zależności i praca równoległa

### 24.1. Krytyczna ścieżka

~~~text
PR-00
 ├─> PR-01 ─> PR-02
 ├─> PR-04
 └─> PR-06 ─> PR-07 ─> PR-08
                      ├─> PR-10 ─> PR-11
                      ├─> PR-12
                      ├─> PR-13 ─> PR-14
                      └─> PR-18 ─> PR-19 ─> PR-20 ─> PR-21/22/23/25

PR-06/07/08 ─> PR-26 ─> PR-27 ─> PR-28/29/30/31 ─> PR-32/33

PR-34 ─> PR-35 ─> PR-36 ─> PR-37

PR-08 + PR-11/12/20/22/27/37 ─> PR-38 ─> PR-39 ─> PR-41 ─> PR-42
PR-02 + PR-22 + PR-40 ────────────────────────────────┘
~~~

### 24.2. Co można robić równolegle

Po PR-00:

- lane Security może robić PR-01/02/05;
- lane Operations może robić PR-04;
- lane UX containment może robić PR-03;
- lane Semantics może zacząć PR-06.

Po PR-07:

- recruitment facts PR-10/11,
- sources PR-12,
- team/scope PR-13/14,
- finance terms PR-18,
- API schemas PR-26,

mogą być rozwijane równolegle na osobnych branchach, ale merge order musi
respektować wspólne DTO/migrations.

Po PR-34:

- competition integration,
- FX worker integration,
- LinkedIn worker integration,
- Coach evaluation,

mogą mieć osobne PR-y, jeżeli PR-34 okaże się zbyt szeroki.

### 24.3. Czego nie łączyć w jeden deploy

- fail-fast migration i nowa duża migracja ekonomiki kontraktu;
- zmiana credit policy i aktywacja konkursu;
- nowy finance engine i live executive dashboard;
- schema/codegen change i route cutover;
- worker lease i rzeczywista emisja Coach;
- archive export i usunięcie legacy API;
- canary activation i semantic definition bump;
- cache invalidation redesign i cutover state activation.

### 24.4. Sugerowane ownership lanes

| Lane | Główne PR-y | Kompetencje |
|---|---|---|
| Security/RBAC | 01, 02, 05, 14 | FastAPI deps, policy, privacy tests |
| Platform/Ops | 04, 09, 34, 37, 42 | Alembic, health, workers, CI |
| Analytics semantics | 06, 07, 08, 10, 11, 12 | SQL, facts, metric design |
| Contracts/Finance | 18–25 | effective dating, Decimal, FX |
| API/Frontend | 03, 26–33 | Pydantic, OpenAPI, React Query, UX |
| Rollout/Legacy | 38–41 | parity, cutover, archive, telemetry |

### 24.5. Wymagane punkty decyzji człowieka

Przed PR-11:

- zatwierdzić credit policy.

Przed PR-13:

- wskazać źródło reporting team membership.

Przed PR-14:

- zatwierdzić, czy DL ma finance tylko przypisanych klientów.

Przed PR-18:

- zatwierdzić inclusive/exclusive end_date i billing normalization.

Przed PR-21:

- zatwierdzić taxonomy korekt oraz które metryki zmieniają.

Przed PR-24:

- zdecydować, czy dedykowana domena Tender powstaje w tym rollout.

Przed PR-39:

- zatwierdzić progi parity i canary cohorts.

Przed PR-41:

- business sign-off successor coverage.

Przed fizycznym usunięciem danych:

- osobna jawna zgoda destrukcyjna.

---

## 25. Plan migracji i reconciliation danych

### 25.1. Zasada

Każda migracja analityczna przechodzi:

1. schema additive,
2. backfill dry-run,
3. backfill z checkpoint,
4. count/checksum reconciliation,
5. dual-read/shadow,
6. activation,
7. observation,
8. dopiero później usunięcie legacy reader.

### 25.2. Checkpoint

Backfill ma:

- run id,
- input watermark,
- batch cursor,
- processed/inserted/skipped/conflict/error,
- last success,
- restart-safe cursor,
- code/extraction version.

### 25.3. Idempotencja

Klucz docelowego fact/projection nie zależy od kolejności batch. Ponowny run:

- nie duplikuje,
- porównuje checksum,
- raportuje konflikt,
- nie nadpisuje ręcznie zatwierdzonej historii.

### 25.4. Milestone backfill

Reconciliation:

- raw candidate stages by semantic key/status,
- qualified facts,
- rejected/pending excluded,
- duplicates/re-entry classified,
- credited owner coverage,
- no-owner bucket.

### 25.5. Source backfill

Reconciliation:

- total candidate population,
- explicit source events,
- legacy-only,
- conflicts,
- unknown,
- invalid taxonomy,
- coverage by creation year/import source.

Nie udawać 100% przez wyłączenie unknown z denominatora.

### 25.6. Team membership backfill

Źródła możliwe:

- obecne client/team assignments,
- users metadata,
- HR/administrator mapping.

Claude nie zgaduje transfer dates. Brak danych trafia do unassigned i wymaga
operator review.

### 25.7. Contract terms backfill

Reconciliation per contract:

- base fields,
- candidate schedule,
- client schedule,
- framework schedule,
- current computed values,
- overlaps,
- gaps,
- future entries,
- unit/hour mismatches.

Konflikt nie jest automatycznie rozwiązywany przez „latest wins”.

### 25.8. FX backfill

- wymagany zakres dat wyznaczony z contract history i snapshots,
- fetch z retry/rate limit,
- table provenance,
- days with no rate explained by calendar,
- gap report,
- checksum/source table.

### 25.9. Adjustment migration

Jeżeli istnieją legacy korekty w Dyna:

- export,
- mapping kinds,
- currency,
- effective period,
- approval evidence,
- unmapped quarantine,
- double-entry/dedup check.

Brak approval provenance nie powinien automatycznie stać się approved.

### 25.10. Snapshot migration

Legacy Dyna values zachowują legacy metric IDs. Nie przeliczać ich w miejscu na
nowe nazwy.

### 25.11. Competition migration

- frozen result rows → immutable revisions,
- ranking checksum,
- period,
- policy version unknown/legacy,
- no delete old winners,
- correction history.

### 25.12. Reconciliation dashboard

Admin widzi:

- population,
- migrated,
- conflicts,
- unknown,
- coverage,
- last run,
- blocked reason,
- sample IDs z ograniczonym dostępem,
- approve readiness.

### 25.13. Stop conditions

Backfill automatycznie zatrzymuje się przy:

- conflict rate ponad próg,
- unexpected null,
- checksum mismatch,
- database lag/timeout,
- source freshness regression,
- disk/storage pressure,
- permission failure.

### 25.14. Usuwanie danych

Żaden z PR-ów tego planu nie powinien:

- DROP legacy table,
- kasować Dyna snapshots,
- usuwać audit/nudge logs,
- przepisywać frozen results,

bez osobnego zatwierdzonego destructive migration plan.

---

## 26. Strategia testów

### 26.1. Piramida

- unit: period, policy, credit, target, FX, normalization;
- integration: Postgres queries/views/migrations;
- contract: OpenAPI/DTO/codegen/privacy;
- component: widget states, labels, accessibility;
- E2E: roles, routes, network, filters;
- shadow parity: production-like facts;
- production smoke: exact SHA i real user flows.

### 26.2. Macierz ról

Minimum:

- unauthenticated,
- viewer/user,
- recruiter,
- sourcer,
- TAC,
- delivery lead,
- head of recruitment,
- admin,
- DL+TAC,
- recruiter+viewer,
- admin z secondary role.

### 26.3. Macierz zasobów

- own user,
- same team,
- other team,
- assigned client,
- unassigned client,
- organization aggregate,
- finance field,
- PII drilldown,
- archive dataset.

### 26.4. Macierz czasu

- today,
- Warsaw midnight,
- UTC/Warsaw different day,
- DST spring/fall,
- week/month/quarter/year,
- custom,
- complete/partial period,
- future as_of invalid,
- contract start/end,
- rate amendment boundary.

### 26.5. Milestone

- pending/rejected/active,
- retry,
- duplicated webhook/import,
- re-entry,
- move by another actor,
- placement cancellation,
- job/client change,
- no verifier,
- deleted/inactive user.

### 26.6. Source

- explicit event,
- legacy fallback,
- conflict,
- multiple applications,
- unknown,
- backfilled,
- late hire,
- zero denominator,
- low coverage.

### 26.7. Finance

- PLN only,
- foreign sell,
- foreign cost,
- both different,
- missing/stale FX,
- future rate,
- overlapping/gap terms,
- unit/hour change,
- approved/rejected/draft/reversal adjustment,
- two contracts one person,
- Decimal/rounding,
- current/history,
- MRR versus recognized revenue.

### 26.8. Cache

- scope isolation,
- role revoke,
- epoch bump,
- TTL,
- capacity,
- eviction,
- stampede,
- multi-replica,
- cutover invalidation,
- no PII in metrics/log keys.

### 26.9. Worker

- two replicas,
- crash after claim,
- lease expiry,
- provider success before local commit,
- retry,
- unknown,
- disabled,
- stale heartbeat,
- overdue schedule,
- EOD recovery,
- sequence reminders.

### 26.10. Snapshot/cutover

- checksum tamper,
- source ambiguity,
- missing period,
- incompatible metric semantics,
- stale comparison,
- concurrent cutover,
- invalid transition,
- rollback,
- canary cohort.

### 26.11. Frontend states

Każdy critical widget:

- loading,
- refreshing with previous data,
- ready zero,
- ready nonzero,
- empty,
- partial,
- stale,
- unavailable,
- unconfigured,
- forbidden,
- error,
- offline,
- retry.

### 26.12. Accessibility

- axe,
- keyboard,
- focus,
- names/roles/values,
- tab semantics,
- chart alternative,
- contrast przez tokeny,
- reduced motion,
- zoom,
- screen reader status.

### 26.13. Performance

- query count assertions,
- EXPLAIN snapshots reviewed świadomie,
- realistic cardinality,
- p95 nightly,
- max memory/payload,
- cancellation,
- slow query alert.

### 26.14. Backup/restore

Po restore:

- expected heads,
- required views,
- snapshot checksums,
- cutover history,
- FX counts/ranges,
- adjustment ledger,
- competition revisions,
- canonical dashboard query,
- worker runtime optional/non-source-of-truth handling.

### 26.15. Produkcyjny smoke

Backend:

- /api/health exact SHA,
- schema ready,
- selected canonical endpoint typed/quality,
- forbidden negative probe na testowej roli, jeśli bezpiecznie dostępne.

Frontend:

- route ownership,
- no legacy requests,
- correct period,
- zero/error distinction,
- screenshot.

---

## 27. Obserwowalność, SLI, SLO i alerty

### 27.1. Zasada

Nie można zarządzać cutoverem za pomocą logów tekstowych. Potrzebne są metryki
oraz durable run state.

### 27.2. Metryki API

- request count/status/latency by endpoint/view,
- query duration,
- response quality status,
- rows/payload bytes,
- timeout/cancel,
- forbidden counts,
- legacy versus canonical traffic.

Bez user email/PII labels.

### 27.3. Metryki danych

- source lag,
- watermark age,
- coverage,
- unknown rate,
- missing credited owner,
- missing team,
- missing terms,
- overlapping terms,
- missing/stale FX,
- adjustment backlog,
- snapshot checksum errors.

### 27.4. Metryki parity

- runs expected/completed/failed,
- rows compared,
- pass/fail/inconclusive,
- max/median delta,
- missing side,
- stale evidence age.

### 27.5. Metryki cache

- hit/miss,
- compute duration,
- entries/bytes,
- eviction,
- singleflight waiters,
- invalidation,
- epoch mismatch.

### 27.6. KPI Coach

- evaluated,
- eligible,
- planned,
- enqueued,
- sent,
- failed,
- unknown,
- skipped by reason,
- duplicate prevented,
- overdue run.

### 27.7. Dyna

- read traffic per module,
- blocked write attempts,
- redirects,
- archive reads,
- last consumer date.

### 27.8. Początkowe SLO do zatwierdzenia po baseline

- critical Analytics API availability: 99.9%;
- schema readiness: 100% dla healthy deploy;
- scheduled shadow runs completed within one interval: 99%;
- critical source freshness within SLA: 99%;
- duplicate Coach delivery: <0.01%, cel zero;
- cutover audit completeness: 100%;
- snapshot checksum failure: zero tolerated;
- finance total with missing FX mislabeled complete: zero tolerated.

### 27.9. Alerty P0

- healthy app + missing required analytics object;
- live cutover bez fresh evidence;
- finance returned complete with missing FX/terms;
- viewer/HoR forbidden-field privacy test regression;
- snapshot checksum failure;
- duplicate competition active revisions;
- Dyna write succeeded in read_only.

### 27.10. Alerty P1

- source stale,
- coverage below threshold,
- parity fail,
- worker overdue/lease stale,
- FX gap,
- cache memory near cap,
- p95 regression,
- unusual legacy traffic after redirect,
- blocked Dyna write spike.

### 27.11. Runbooks

Każdy alert ma:

- owner,
- severity,
- evidence link,
- safe first action,
- rollback action,
- conditions for escalation,
- zakazane działania,
- resolution verification.

---

## 28. Plan rollout i rollback

### 28.1. Fazy rollout per metric family

1. off,
2. internal compute,
3. shadow compare,
4. shadow verified,
5. admin canary,
6. selected team canary,
7. role canary,
8. live,
9. legacy read-only redirect,
10. retired.

### 28.2. Minimalny okres shadow

Nie tylko liczba dni. Wymagane:

- wszystkie expected scheduled runs,
- pełne zakresy dzień/tydzień/miesiąc zależnie od metric,
- coverage threshold,
- zero unresolved security issue,
- classified semantic differences,
- przynajmniej jeden source degraded scenario.

### 28.3. Canary criteria

- cohort jawnie zidentyfikowana przez policy, nie przypadkowy hash bez audytu;
- support/owner wie o canary;
- canonical i legacy link do report problem;
- telemetry role/scope bez PII;
- rollback max kilka minut.

### 28.4. Stop conditions

- P0 privacy,
- complete quality przy niekompletnych danych,
- parity breach critical metric,
- p95 ponad zatwierdzony budżet,
- schema degraded,
- error rate,
- Dyna write split-brain,
- unexplained finance delta.

### 28.5. Rollback

1. aktywuj poprzednią CutoverRevision;
2. bump cache epochs;
3. potwierdź routing;
4. potwierdź legacy reader read-only;
5. sprawdź /api/health exact deployed revision;
6. sprawdź canonical/legacy traffic;
7. zachowaj comparison/evaluation evidence;
8. otwórz incident z reason.

### 28.6. Roll-forward

Preferowany dla:

- data correction,
- missing FX,
- source backfill,
- display bug,
- codegen mismatch.

Nie zmieniać historii snapshotów w miejscu.

---

## 29. Produkcyjna weryfikacja Chrome

### 29.1. Przed wejściem

- CI green,
- merge SHA,
- deploy complete,
- /api/health version zaczyna się exact 7-char SHA,
- required User-Agent,
- status nie unhealthy,
- schema readiness,
- cutover revision oczekiwana.

### 29.2. Role

- unauthenticated,
- user,
- recruiter,
- sourcer,
- TAC,
- DL,
- HoR,
- admin,
- multi-role.

Jeżeli nie ma bezpiecznych kont testowych, nie używać produkcyjnej
impersonacji bez zatwierdzonego flow; brak ma być jawnym blokiem release gate.

### 29.3. Routes

- /,
- /dashboard,
- /dashboard?view=recruitment&period=month,
- /dashboard?view=finance&as_of=...,
- invalid view/period,
- /insights i każda stara zakładka,
- role dashboards,
- /dynareporter,
- /dynareporter/rekrutacja,
- /dynareporter/board-dashboard,
- /dynareporter/admin-dashboard,
- archive route.

### 29.4. Network

- brak forbidden requestów,
- brak legacy requestów w canonical flow,
- HoR response nie ma finance,
- user response nie ma person-identifiable KPI,
- request params odpowiadają kontrolce,
- 403 nie jest retry loop,
- cache nie przecieka między rolami.

### 29.5. Dane

- count/list placement invariant,
- active client label,
- activity total/other,
- period dates,
- as-of label,
- source coverage,
- quality/freshness,
- partial month comparison,
- finance currency/Decimal,
- null przy unavailable.

### 29.6. Failure simulation

W preview/test harness:

- 403,
- 500,
- timeout,
- offline,
- empty,
- zero,
- partial,
- stale,
- unavailable,
- unconfigured.

Nie wyłączać realnej integracji produkcyjnej tylko dla testu UI.

### 29.7. Responsiveness/accessibility

- 320×568,
- tablet,
- desktop,
- zoom 200%,
- keyboard-only,
- focus order,
- screen reader labels,
- dark/soft theme,
- no horizontal page overflow.

### 29.8. Dyna

- writer controls nie istnieją lub są disabled z wyjaśnieniem;
- direct mutation w test harness/API jest odrzucona;
- redirect/tombstone ma successor;
- archive jest tylko dla uprawnionych.

### 29.9. Dowód

Completion report zapisuje:

- SHA,
- timestamp,
- role/context,
- route,
- wynik,
- screenshot dla critical views,
- network observation,
- znane ograniczenia.

---

## 30. Definition of Done całego Modułu 7

### 30.1. Bezpieczeństwo

- wszystkie analytics/legacy routes mają capability i scope;
- allowed_sections jest egzekwowane backendowo;
- multi-role provenance jest testowane;
- DL nie widzi organizacji bez policy;
- HoR nie widzi finance bez jawnego grantu;
- viewer nie widzi identifiable performance;
- archive ma audit;
- Dyna writes są centralnie blokowane.

### 30.2. Prawda metryk

- każda metryka ma ownera, kind, grain, czas, unit i version;
- pending/rejected verification nie jest approved;
- jedna credit policy działa wszędzie;
- source coverage jest jawne;
- zero/empty/unavailable są rozróżnione;
- count/list/label invariants są zielone;
- tender value nie jest salary.

### 30.3. Finanse

- flow i snapshot są oddzielone;
- historical as_of używa historical terms;
- future terms nie zmieniają przeszłości;
- FX fail-closed;
- adjustments działają dokładnie raz;
- legacy revenue nie jest MRR;
- direct margin nie jest operating margin;
- Decimal zachowany;
- Contract Analytics używa canonical engine.

### 30.4. Operacje

- produkcja fail-fast na migracji;
- health sprawdza schema readiness;
- wiele Alembic heads jest prawidłowo raportowane;
- cache bounded/scoped/invalidation;
- workery lease/idempotency;
- Coach ma decision/outbox;
- snapshot checksum verified;
- backup restore fail-hard i obejmuje analytics.

### 30.5. API/Frontend

- endpoint-specific schemas;
- TS generated;
- semantic contract gate;
- jeden canonical analytics home;
- route decision przed fetch;
- capability-driven views;
- URL time model;
- unified WidgetBoundary;
- accessibility/mobile/token gates.

### 30.6. Rollout

- durable shadow evidence;
- canary;
- immutable cutover revisions;
- tested rollback;
- production exact SHA;
- Chrome role/route matrix;
- legacy traffic zmierzone;
- Dyna archive/preservation complete.

### 30.7. Dokumentacja

- metric catalog,
- access matrix,
- source readiness,
- finance methodology,
- runbooks,
- migration/reconciliation reports,
- cutover decision,
- archive manifest,
- final completion report.

### 30.8. Co nie jest Definition of Done

- endpoint 200,
- test shape-only,
- flaga ustawiona na shadow bez comparator,
- UI hidden bez backend guard,
- health green tylko przez SELECT 1,
- jedna udana ręczna kalkulacja,
- brak zgłoszeń użytkowników,
- „known limitation” bez ownera i terminu,
- merged PR bez deployment/production proof.

---

## 31. Decyzje, których Claude nie może podjąć po cichu

1. Czy główna credit policy pozostaje verifier-anchored.
2. Czy actor ma osobne action KPI.
3. Które role widzą identifiable performance.
4. Czy DL widzi finance przypisanych klientów.
5. Czy HoR może dostać odrębny finance grant.
6. Co jest źródłem ReportingTeam.
7. Jak traktować matrix/secondary team.
8. Czy contract end_date jest inkluzywny.
9. Jak normalizować daily/hourly billing.
10. Jaki kurs NBP i dzień obowiązuje dla każdej rodziny raportu.
11. Które adjustments wpływają na MRR, direct margin i operating P&L.
12. Czy legacy historie da się semantycznie porównać, czy tylko wyświetlać jako
    osobne serie.
13. Jaki jest próg source coverage.
14. Jak dojrzała ma być kohorta source conversion.
15. Czy powstaje dedykowany model Tender.
16. Jak długo Dyna archive ma być dostępne.
17. Jaki jest legal retention.
18. Jaki okres zero-traffic wystarcza do retirement.
19. Jakie są progi parity.
20. Kto zatwierdza cutover i rollback.
21. Czy można fizycznie usunąć legacy dane.

Jeżeli decyzja blokuje semantykę, Claude ma zatrzymać odpowiedni PR i poprosić
o rozstrzygnięcie. Nie powinien wstrzymywać niezależnego containment.

---

## 32. Rekomendowany pierwszy sprint

### 32.1. Zakres

Pierwszy sprint powinien zawierać wyłącznie:

- PR-00 baseline/inventory,
- PR-01 Dyna GET RBAC,
- PR-02 true read-only,
- PR-03 truthful states,
- PR-04 fail-fast/readiness,
- PR-05 activation/debug containment,
- przygotowanie decyzji do PR-06/07/11/13/18.

### 32.2. Dlaczego

Ten zestaw:

- zamyka realne wycieki i split-brain,
- usuwa kłamliwe sukcesy UI,
- zapobiega green deploy na złym schemacie,
- uniemożliwia przedwczesny live,
- tworzy inventory potrzebne do dalszych zmian,
- nie wymaga jeszcze rozstrzygnięcia całej ekonomiki.

### 32.3. Mierzalny wynik

- viewer direct Dyna GET odrzucony;
- HoR finance odrzucone;
- każda Dyna mutacja blocked;
- SLA error nie mówi „wszystko w normie”;
- migration failure zatrzymuje startup;
- brak required view daje unhealthy;
- live/cutover bez evidence odrzucone;
- debug nudge nie kasuje historii;
- hosted CI i produkcyjna weryfikacja zielone.

### 32.4. Poza sprintem

- pełny FinanceReadService,
- source backfill,
- team model,
- canonical dashboard,
- Coach outbox,
- Dyna deletion.

---

## 33. Instrukcja wykonawcza dla Claude Code

### 33.1. Start zadania

1. Otwórz ten dokument.
2. Sprawdź status każdego wcześniejszego PR.
3. Re-anchor origin/main.
4. Potwierdź production SHA.
5. Wybierz najwcześniejszy niezrealizowany PR bez niespełnionej zależności.
6. Załóż osobną branch.
7. Zapisz baseline.

### 33.2. Podczas implementacji

- utrzymuj zmianę w granicy PR;
- dodaj test najpierw dla odtwarzanego błędu;
- używaj canonical helpers;
- nie kopiuj query do kolejnego serwisu;
- każdą zmianę metric semantics wpisz do catalog/changelog;
- każdą migrację mirroruj idempotentnie w entrypoint tylko zgodnie z aktualnym
  kontraktem repo, ale po PR-04 production nie może opierać readiness na
  best-effort safety net;
- nie loguj danych kandydatów, emaili ani kwot per client w labels;
- przy scope testuj negatywną rolę i cross-resource;
- przy quality testuj brak źródła;
- przy cache testuj invalidation.

### 33.3. Weryfikacja lokalna

Tylko najmniejsze host-native checks:

- ruff dla zmienionego backendu,
- ruff format check,
- wybrane pytest files,
- frontend type-check/lint/test dla zmienionych komponentów,
- bez Dockera,
- pełne integracje/migrations w hosted CI.

### 33.4. Opis PR

Ma zawierać:

- problem i production/user impact,
- previous behavior,
- new contract,
- files/components,
- migration/backfill,
- security/privacy,
- metric definition/version,
- tests z realnymi wynikami,
- rollout flag,
- observability,
- rollback,
- out-of-scope.

### 33.5. Po merge

1. Obserwuj deploy.
2. Potwierdź exact SHA przez /api/health.
3. Sprawdź schema readiness.
4. Wykonaj backend smoke.
5. Dla UI wykonaj real Chrome flow.
6. Zapisz screenshot/dowód.
7. Monitoruj określony czas.
8. Dopiero wtedy oznacz PR slot complete.

### 33.6. Gdy CI failuje

- otwórz konkretny job/log;
- napraw najwęższy kontrakt;
- nie wyłączaj testu;
- nie zwiększaj tolerancji parity bez decyzji;
- nie zamieniaj unavailable na zero;
- nie używaj no-verify.

---

## 34. Gotowy brief do przekazania Claude

~~~text
Pracujesz w repozytorium NEXUS nad Modułem 7: Analytics, KPI, raportowanie,
dashboardy i wygaszenie DynaReportera.

Źródłem planu jest:
docs/analytics-kpi-reporting-dashboards-dynareporter-module-audit-and-claude-implementation-plan-2026-07-16.md

Nie wdrażaj całego dokumentu w jednym PR. Zacznij od najwcześniejszego
niezrealizowanego slotu z sekcji 23, którego zależności są spełnione.

Najpierw:
1. przeczytaj AGENTS.md,
2. git fetch origin,
3. potwierdź origin/main i produkcyjny SHA,
4. sprawdź czy slot już nie istnieje,
5. załóż osobną branch,
6. odtwórz baseline.

Kluczowe zasady:
- nie przełączaj ANALYTICS_V1_MODE=live bez trwałego parity evidence;
- Dyna read_only ma być egzekwowane backendowo;
- UI hide nie jest security;
- error/403/timeout nigdy nie staje się zerem lub „wszystko w normie”;
- flow używa period, snapshot as_of, cohort dwóch zakresów;
- finanse używają effective-dated terms i fail-closed FX;
- nie mapuj legacy revenue na MRR ani operating margin na direct margin;
- pending/rejected verification nie jest approved;
- jedna credit policy musi działać w Analytics, KPI, Coach, reports i
  competitions;
- multi-role nie może łączyć capability z jednej roli z global scope innej;
- nie używaj local Docker;
- zachowaj unrelated WIP;
- każdy PR: test, CI, merge, deploy, exact-SHA health i produkcyjna weryfikacja.

Jeżeli slot wymaga decyzji z sekcji 31, poproś o nią. Nadal wykonaj niezależny
containment, jeżeli jest bezpieczny.

Po zakończeniu zapisz completion note zawierające commit, PR, CI, deployed SHA,
production checks, screenshots, rollback oraz jawne deferred items.
~~~

---

## 35. Rekomendacja końcowa

Najlepsza kolejna inwestycja nie polega na dodawaniu kolejnych wykresów.
Najpierw trzeba uczynić obecną analitykę bezpieczną i prawdziwą.

Priorytet:

1. zablokować wycieki i legacy writes,
2. zatrzymać false-zero oraz fail-open schema,
3. zdefiniować metryki/czas/readiness,
4. ujednolicić facts, credit i scope,
5. naprawić effective-dated finanse,
6. zbudować typed canonical API/UI,
7. uczynić Coach/workery trwałymi,
8. zebrać shadow evidence,
9. wykonać canary/cutover,
10. dopiero potem wygaszać legacy.

Analytics v1 jest dobrym fundamentem, ale dziś jest jeszcze równoległą warstwą,
nie systemem prawdy. DynaReporter nie jest jeszcze archiwum, ponieważ część
writerów i poufnych readerów pozostaje aktywna. Włączenie live przed wykonaniem
fal A–D i niezbędnych części E/G zwiększyłoby ryzyko decyzji na błędnych danych.

Docelowy sukces to nie jeden ekran. To sytuacja, w której ta sama odpowiedź na
pytanie „ile, komu, kiedy i według jakiej definicji” jest identyczna w
dashboardzie, KPI Coach, konkursie, eksporcie i API — z widocznym zakresem,
jakością, źródłem oraz możliwością bezpiecznego rollback.

---

## 36. Mapa najważniejszych źródeł kodowych

### 36.1. Analytics v1

- backend/app/api/analytics_v1.py
- backend/app/analytics/metrics.py
- backend/app/analytics/periods.py
- backend/app/analytics/schemas.py
- backend/app/analytics/capabilities.py
- backend/app/analytics/scope.py
- backend/app/analytics/cache.py
- backend/app/core/cache.py

### 36.2. Milestones, KPI i Coach

- backend/alembic/versions/0174_analytics_v1_foundation.py
- backend/alembic/versions/0175_analytics_milestones_acceptance.py
- backend/app/services/kpi_engine.py
- backend/app/services/kpi_panel.py
- backend/app/services/kpi_team.py
- backend/app/services/kpi_coach_service.py
- backend/app/tasks/kpi_coach_nudger.py
- backend/app/models/kpi_nudge_log.py
- backend/app/api/kpis.py

### 36.3. Finance

- backend/app/models/contract.py
- backend/app/api/contracts.py
- backend/app/api/contract_analytics.py
- backend/app/models/financial_adjustment.py
- backend/app/api/financial_adjustments.py
- backend/app/services/fx_service.py
- backend/app/api/fx.py

### 36.4. Snapshot/cutover/Dyna

- backend/app/models/analytics_snapshot.py
- backend/app/services/analytics_snapshots.py
- backend/app/api/dynareporter_*.py
- backend/app/main.py
- backend/app/core/config.py
- frontend/src/app/dynareporter
- frontend/next.config.ts

### 36.5. Frontend

- frontend/src/lib/stats-api.ts
- frontend/src/components/v2/pages/AnalyticsDashboard.tsx
- frontend/src/components/v2/pages/DashboardV2.tsx
- frontend/src/components/v2/dashboard/StatsBoundary.tsx
- frontend/src/components/v2/dashboard/WidgetState.tsx
- frontend/src/components/insights
- frontend/src/store/auth.ts
- frontend/src/middleware.ts
- frontend/src/components/v2/layout/SidebarV2.tsx

### 36.6. Operations/CI

- backend/entrypoint.sh
- backend/app/api/admin_snapshot.py
- backend/app/tasks/competition_autofreeze.py
- backend/app/services/competitions.py
- backend/app/tasks/linkedin_sync.py
- backend/app/services/proxycurl
- .github/workflows/ci.yml
- .github/workflows/backup-drill.yml
- backend/tests/test_analytics_release_gates.py
- backend/tests/test_analytics_finance.py
- backend/tests/test_analytics_v1_api.py
- backend/tests/test_kpi_canonical.py
- backend/tests/test_contract_analytics*.py

---

## 37. Stan zastany na dzień audytu

Ten raport jest post-implementation audit wcześniejszego planu PR0–PR8.
Nie należy kopiować starego planu i realizować go drugi raz. Claude ma:

- sprawdzić bieżący origin/main,
- traktować zamknięte elementy jako fundament,
- naprawiać konkretne pozostałe kontrakty opisane tutaj,
- aktualizować raport wykonania dopiero po produkcyjnym dowodzie.

Bazowy production observation:

- /dashboard nie jest live i wraca do legacy root;
- /insights oraz root nadal są realnym flow;
- Dyna admin-dashboard nadal wygląda jak writer;
- ogólny health jest healthy, ale CloudTalk unhealthy i Traffit degraded;
- dashboard zawiera widoczne sprzeczności liczników i list.

Każdy późniejszy wykonawca musi ponownie zweryfikować te fakty. Repozytorium i
produkcja mogą się zmienić po 2026-07-16.
