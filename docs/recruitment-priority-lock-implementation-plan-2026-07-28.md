# Priority Lock + Carry-over Duty — plan implementacji

Data: 2026-07-28

Właściciel implementacji: Codex

Właściciel review i decyzji o wdrożeniu: Claude

Branch roboczy: `codex/recruitment-priority-lock`

Pierwotny bazowy commit worktree:
`85195914f70936a06d8ef23d488b9c7ce2be3232`

Aktualna baza po rebase:
`7c7c2a5bab28fd29ef64f6bfafdea3aa29d02441`

## 1. Granice realizacji

Implementacja powstaje w izolowanym worktree. Pierwotny checkout użytkownika
nie jest modyfikowany. Zakres kończy się na gotowym draft PR do `main`:

- bez merge;
- bez deployu;
- bez migracji produkcyjnej;
- bez zmiany konfiguracji Coolify;
- bez przełączenia flagi na produkcji;
- bez uruchomienia produkcyjnego backfillu/reconciliation;
- bez testów w produkcji;
- bez lokalnego Dockera.

Globalny przełącznik:

```text
RECRUITMENT_PRIORITY_MODE=off|shadow|enforce
```

ma wartość domyślną `off`. Draft PR, CI i finalny SHA są jeszcze `PENDING`.
Pięć commitów implementacji zostało zrebasowanych na aktualny `origin/main`.
Audyt sześciu zmian upstream oraz `range-diff` potwierdziły zachowanie obu
semantyk. Dwa konflikty importów rozwiązano addytywnie, a nowy upstreamowy
`useSearchParams` dopisano do mocka testu listy requestów.

## 2. Cel i definicje

Opublikowany plan Head of Recruitment jest źródłem prawdy dla rozpoczynania
nowej pracy kandydat–request. Delivery Lead zgłasza zapotrzebowanie, HoR
publikuje przydziały A–E, a system blokuje tworzenie nowych par poza planem.

Rozpoczęta praca nigdy nie znika po zmianie planu:

- każdy otwarty `RecruitmentProcess` jest carry-over;
- właściciel nadal obsługuje istniejącą parę, ale nie dodaje nowych osób na
  superseded request;
- zamknięty lub voided proces nie jest kontynuacją; ponowne otwarcie jest nowym
  attemptem i ponownie przechodzi admission policy;
- replay tego samego terminalnego eventu Traffit jest idempotentny i nie
  mutuje zamkniętego attemptu; dopiero nowszy event otwiera attempt `N+1`;
- nieaktywny albo brakujący owner oznacza `unowned carry-over`;
- tylko użytkownik posiadający rolę `head_of_recruitment` może zrobić handoff;
- handoff zmienia odpowiedzialność, ale nie zmienia pierwszego verifiera,
  eligibility ani autorstwa KPI.

Milestone’y biznesowe:

- verification: pierwszy zaakceptowany `verified`;
- recommendation: `cv_sent`;
- client interview: `client_interview`;
- placement: `hired`.

## 3. Reguły biznesowe

### 3.1. Demandy Delivery Lead

- Demand może utworzyć tylko użytkownik z rolą `delivery_lead`, wyłącznie dla
  requestu, którego jest aktualnym `Job.delivery_lead_id`.
- Request musi mieć status `published`.
- `expected_recommendations` ma minimum `3` również na poziomie schematu i
  constraintu bazy.
- Jednocześnie może istnieć jeden aktywny demand na request.
- Udostępnione operacje to listowanie, tworzenie, aktualizacja i zmiana statusu
  przez `PATCH`; nie ma endpointu `DELETE`.
- Aktualny DL może aktualizować swój demand, a HoR każdy demand. Zmiana autora
  historycznego nie daje dostępu po zmianie DL.
- Aktualizacja wymaga `expected_version`.

Przy publikacji planu każdy użyty demand musi mieć pełne pokrycie:

- suma `recommendation_target` wszystkich jego assignmentów jest nie mniejsza
  niż `expected_recommendations`;
- kanał jest zgodny z demandem: `database` może być pokryty przez `database`
  albo `mixed`, `linkedin` przez `linkedin` albo `mixed`, natomiast demand
  `mixed` wymaga assignmentu `mixed`;
- demand musi być aktywny;
- request musi nadal mieć status `published`.

### 3.2. Plan HoR

- Opublikowany plan działa do atomowego opublikowania kolejnej wersji; nie
  wygasa automatycznie.
- Publikacja superseduje poprzednią wersję w tej samej transakcji i używa
  optimistic locking przez `row_version`.
- Singleton state jest blokowany, a `previous_plan_id` draftu działa jako
  compare-and-swap token aktualnego planu. Dwa sibling drafty sklonowane z tej
  samej wersji są serializowane, lecz tylko pierwszy może zostać opublikowany;
  drugi dostaje `PRIORITY_VERSION_CONFLICT` dla `plan_state`.
- Opublikowany plan jest niezmienny. Zmiany powstają w nowym albo sklonowanym
  drafcie.
- `review_due_at` przypada po trzech dniach roboczych poniedziałek–piątek
  liczonych w strefie `Europe/Warsaw`. Overdue tworzy stan ostrzegawczy, ale nie
  odblokowuje pracy poza planem.
- Aktywny członek musi mieć od 3 do 5 assignmentów o ciągłych rangach od `A`.
- Domyślnie są trzy assignmenty A–C. Slot D lub E zawsze wymaga
  `extra_slot_reason`.
- Każdy assignment ma dodatni target weryfikacji i rekomendacji.
- Domyślna pojemność weryfikacji wynosi 12 na okres przeglądu; jej zmiana
  wymaga `capacity_reason`, a suma targetów weryfikacji musi równać się
  pojemności członka.
- Wstrzymany członek wymaga `paused_reason`, nie dostaje nowych assignmentów,
  ale zachowuje carry-over.

### 3.3. Competence Category i kanały

- Dopasowanie podstawowej lub dodatkowej Competence Category requestu do
  kategorii użytkownika jest poprawne.
- Brak dopasowania wymaga jawnego `cc_exception_reason` HoR.
- Sourcer może dostać kanał `database`.
- Recruiter może dostać kanał `linkedin`.
- TAC może dostać `database`, `linkedin` albo `mixed`.
- Dla użytkownika wielorolego dozwolone kanały są sumą ról; obecność roli TAC
  dopuszcza wszystkie trzy.
- Przy każdym ludzkim ingressie command otrzymuje jawny `work_channel`.
  Assignment `mixed` akceptuje operację `database` lub `linkedin`; assignment
  jedno-kanałowy akceptuje tylko swój kanał.

### 3.4. Admission policy i carry-over

- Nową parę można rozpocząć tylko na requestcie `published`. W `shadow`
  zamknięty request zapisuje naruszenie, w `enforce` zwraca
  `409 PRIORITY_WORK_LOCKED/JOB_NOT_OPEN`. Tryb `off` zachowuje dotychczasowe
  zachowanie writerów.
- Istniejący otwarty proces jest zawsze kontynuacją niezależnie od aktualnego
  planu, targetu, statusu członka i kanału.
- Owner requestu, collaborator, self-claim, admin, manager ani samo
  dopasowanie CC nie zastępują assignmentu.
- Aktywny assignment albo ownership otwartego carry-over rozszerza job
  membership, gdy Priority Work jest aktywny. To daje dostęp do zasobu, nie
  zgodę na otwarcie nowej pary; admission policy pozostaje osobną bramką.
- Ten sam zakres assignment/carry obowiązuje na listach jobów. Efektywny tryb
  `off` — wynikający z globalnego sufitu albo per-user osłabienia — wyłącza to
  rozszerzenie i zachowuje legacy scope.
- Wszystkie requesty w planie mogą początkowo działać równolegle.
- Niższy rank zostaje zamknięty na nowe osoby dopiero po osiągnięciu własnego
  targetu weryfikacji, jeżeli wyższy rank nie osiągnął targetu weryfikacji lub
  rekomendacji i nie ma zaakceptowanego, aktywnego blockera.
- Zaakceptowany blocker zwalnia zależność, a jego rozwiązanie przywraca
  normalną ocenę.
- Jednorazowy wyjątek HoR działa tylko w `enforce`, ma maksymalnie siedem dni,
  jest konsumowany atomowo i daje `kpi_eligible=false`.
- W `enforce` zwykły użytkownik nie może usunąć aktywnego procesu, aby
  porzucić carry-over. `off` i `shadow` zachowują dotychczasowy endpoint
  korekcyjny, ale najpierw zapisują trwały kanoniczny void. Fizyczne usunięcie
  historii jest dozwolone dopiero po stanie `voided`.

### 3.5. Role uprzywilejowane

Wszystkie uprzywilejowane endpointy Priority Work używają dokładnie
`HeadOfRecruitmentOnly`, czyli `require_roles(UserRole.head_of_recruitment)`.

- Sama rola `admin` nie daje prawa do planu zespołu, publikacji, decyzji o
  blockerze, handoffu, wyjątków, rollout mode, statusu, reconciliation, alertów
  ani audytu.
- Admin posiadający również właściwą rolę biznesową działa na podstawie tej
  drugiej roli.
- DL ma wyłącznie zakres demandów opisany wyżej.
- Rekruter, sourcer i TAC widzą własny plan/carry-over oraz obsługują przydzieloną
  pracę.

## 4. Architektura implementacji

### 4.1. Dane i migracja

Migracja `0200_recruitment_priority_work`:

- rozszerza `0199_candidate_stage_removals`;
- tworzy 11 enumów PostgreSQL;
- tworzy 10 tabel Priority Work: plan, demand, member, assignment, blocker,
  exception, user mode, singleton state, alert i audit event;
- dodaje 11 nullable kolumn provenance/ownership/eligibility do
  `recruitment_processes`;
- dodaje do `candidate_invite_links` nullable
  `origin_assignment_id` i `priority_compliant_at_create`;
- dodaje FK, indeksy, partial unique constraints oraz singleton state `id=1`;
- indeksuje także `RecruitmentProcess.origin_assignment_id` i
  `RecruitmentProcess.eligibility_assignment_id`;
- nie wykonuje ciężkiego historycznego backfillu.

`upgrade()` kończy się kontrolą exact schema parity: wymaganych kolumn,
nazwanych constraintów, typów i `ON DELETE` foreign keys oraz unikalności,
kolumn i predykatów indeksów. Predykaty są porównywane jako pełna
znormalizowana semantyka, a nie zbiór tokenów: kontrola rozróżnia `=` od `<>`
oraz `IS NULL` od `IS NOT NULL`. Sprawdza też check minimum trzech rekomendacji.
Dzięki temu częściowy albo semantycznie inny safety-net nie może zostać cicho
ostemplowany jako pełna migracja.

W aktualnym worktree polecenie `alembic ... heads` zwraca jeden head:
`0200_recruitment_priority_work`. To opis wyłącznie bieżącego grafu w tym
worktree, a nie twierdzenie, że repo historycznie zawsze miało jeden head.
Hosted CI ma wykonać `upgrade heads` dwukrotnie, sprawdzając upgrade i
retry-safety.

Startup safety-net odtwarza oba indeksy assignment provenance. Migracja
pozostaje autorytatywnym audytem exact parity i odrzuca istniejący obiekt o
niezgodnej semantyce.

Backfill/reconciliation pozostaje resumowalny i ograniczony batchami. Tworzy
historyczne procesy jako `legacy`, nie przepisuje aktywnej własności i korzysta
z tego samego mapowania custom workflow co live command.

### 4.2. Kanoniczny agregat i command service

`RecruitmentProcess` jest kanonicznym attemptem pary kandydat–request.
`CandidateStage` pozostaje dziennikiem milestone’ów i warstwą kompatybilności.

`backend/app/services/recruitment_process_commands.py` centralizuje:

- `open_process` i `transition_process`;
- zapis stawek: `update_latest_client_rate`,
  `update_latest_expected_rate`;
- akceptację i odrzucenie pending verification:
  `accept_pending_verification`, `reject_pending_verification`;
- zamrożenie pierwszego zaakceptowanego verifiera;
- `void_process` oraz `delete_voided_stage_history`;
- claim/release alertu SLA;
- `handoff_process`;
- synchronizację obserwacji zewnętrznych Traffit.

Command blokuje deterministycznie kandydata, następnie request/proces/stage,
rozstrzyga admission policy i synchronizuje proces z etapem. Dla custom stage
korzysta z opublikowanego `StageRevision` po `source_stage_def_id`; brak mapy
oznacza semantykę `unmapped`, a nie ciche odziedziczenie legacy `new`.

External sync w ścieżce single i batch blokuje `Candidate`, następnie `Job`,
a dopiero potem odczytuje świeży snapshot procesu/stage. Batch sortuje pary
deterministycznie przed pobraniem blokad. Usuwa to race, w którym dwa writery
mogły równolegle wyliczyć i utworzyć attempt `N+1`.

Replay terminalnego zdarzenia Traffit nie przepisuje zamkniętego attemptu.
Identyczny event jest no-op, a nowszy event tworzy kolejny attempt. Seedery
przekazują jawny `work_channel`; `source_authority` opisuje pochodzenie, ale
nie jest mechanizmem omijania Priority Lock.

Command wykonuje `flush`, nie `commit`. Istniejący caller nadal odpowiada za
swoją pełną transakcję, dodatkowe walidacje, activity, snapshot CV,
powiadomienia i inne side effecty. Nie należy opisywać commandu jako właściciela
tych elementów, dopóki nie zostaną rzeczywiście przeniesione.

### 4.3. Writer fence

Test architektoniczny skanuje `backend/app/**/*.py` oraz oba seedery i wymusza:

- jedyny natywny konstruktor/SQLAlchemy insert `CandidateStage` znajduje się w
  command service;
- jedyny raw `INSERT INTO candidate_stages` znajduje się w adapterze Traffit
  i wywołuje synchronizację `RecruitmentProcess`;
- SQLAlchemy `update/delete CandidateStage` i przypisania krytycznych pól
  lifecycle, weryfikacji, stawek, budżetu i SLA występują tylko w commandzie;
- raw `UPDATE candidate_stages` jest dozwolony wyłącznie w idempotentnym
  adapterze metadanych odrzucenia Traffit;
- seedery nie usuwają historii procesu/stage;
- każdy ludzki `open_process`/`transition_process` deklaruje `work_channel`.

Podczas review należy dodatkowo wykonać ręczne `rg`, ponieważ test AST nie
wykryje każdego dynamicznego SQL ani aliasu.

### 4.4. Invite i inbound

- Link można wygenerować tylko dla opublikowanego requestu.
- Przy tworzeniu linku policy ocenia kanał `linkedin`, a link zamraża
  `origin_assignment_id` i `priority_compliant_at_create`.
- Późniejsza zmiana lub supersede planu nie zmienia tej decyzji.
- Nowy kandydat z linku przekazuje zamrożone pola do
  `open_process(external_inbound)`.
- Duplikat e-mail trafia do `ApplicationSubmission.raw_payload`; przy późniejszym
  rozstrzygnięciu te same zamrożone pola są przekazywane do commandu.
- Inbound jest zachowywany, nie tworzy automatycznie autorstwa KPI dla twórcy
  linku, a eligibility/credit zostają rozstrzygnięte przy pierwszej
  zaakceptowanej weryfikacji.

## 5. API i UI

Namespace `/api/priority-work` obejmuje:

- odczyty: current, mine, team, job context, status, reconciliation, alerts,
  audit;
- demand: list, create, update/status; bez DELETE;
- plan: draft, replace, publish;
- blockery: create i lifecycle;
- handoff;
- jednorazowe wyjątki: list, create, revoke;
- per-user mode.

Konflikt wersji zwraca `PRIORITY_VERSION_CONFLICT`. Odmowa admission zwraca
ustrukturyzowane `409` z `code=PRIORITY_WORK_LOCKED`, stabilnym `reason`,
identyfikatorem akcji, kandydata i requestu. UI parsuje kod, nie tekst
tłumaczenia.

Frontend:

- HoR: `TeamAllocationBoard`;
- DL: `PriorityRequestsPanel`;
- recruiter/sourcer/TAC: `MyPriorityQueue` przed KPI i osobne
  `Do dokończenia`;
- job detail: `JobPriorityContext`;
- job list: osobne filtry/badge assignment i carry-over;
- wszystkie zmienione powierzchnie dodawania kandydata pokazują wspólny błąd
  blokady.

Komponenty używają istniejących tokenów design systemu zgodnie z
`frontend/docs/ds/ADDING-BLOCKS.md`.

## 6. KPI, konkursy i Hall of Fame

Wspólny `VERIFIER_ANCHORED_CTE` jest attempt-aware:

- buduje nieprzecinające się okna po `attempt_no`; również voided attempt
  wyznacza granicę czasową;
- liczy tylko zaakceptowany `verified`, z czasem `approved_at` dla pending;
- sklasyfikowany attempt wymaga `kpi_eligible=true`, `credit_user_id` oraz
  milestone’u nie wcześniejszego niż zaakceptowana weryfikacja;
- nowy attempt nie dziedziczy verifiera ani milestone’ów wcześniejszego
  attemptu;
- fallback pozostaje tylko dla legacy sprzed pierwszego sklasyfikowanego
  procesu i respektuje jawne `kpi_eligible=false`.

Ten sam CTE zasila KPI, konkursy rekrutacyjne i Hall of Fame. Konkurs
rekomendacji używa `cv_sent`, nie `interview`.

Progress assignmentu i rank unlock korzystają z tej samej semantyki:
rekomendacja liczy się wyłącznie wtedy, gdy ten sam `RecruitmentProcess`
attempt ma wcześniejszy zaakceptowany `verified`. Milestone z poprzedniego
attemptu nie może odblokować targetu.

Miesięczna nagroda rekomendacji wymaga:

- `4 × liczba minionych dni roboczych poniedziałek–piątek` zaakceptowanych
  weryfikacji;
- `cv_sent / verified >= 75%`.

Oba warunki kwalifikacji są stosowane w zapytaniu przed sortowaniem i
`LIMIT 10`, dzięki czemu zakwalifikowana osoba z pozycji 11+ wchodzi do
rankingu po odrzuceniu niekwalifikujących się wyników.

Punkty kwartalne 5/15/150, nagrody i trzy miejsca podium pozostają bez zmian.
`freeze_competition(type, period)` używa advisory lock; jeżeli snapshot dla
typu i okresu już istnieje, zwraca go bez przeliczenia i zapisu. Zamrożone
historyczne podium jest write-once.

Korekta KPI jest niezależna od flagi Priority Lock. `off` wyłącza odmowę
admission, ale nie przywraca starej definicji konkursów.

## 7. Worker i health

Restart-safe worker:

- utrzymuje heartbeat, reconciliation timestamps, metrics i ostatni błąd w
  singleton state;
- wygasza niewykorzystane wyjątki;
- upsertuje alerty po trwałym `dedupe_key` i zwiększa occurrence count;
- rozwiązuje alerty, które przestały obowiązywać;
- raportuje plan/review overdue, brak coverage, brak ownera carry-over,
  coverage eligibility, shadow violations i aktywne alerty.

W `off` health oznacza funkcję jako wyłączoną. W `shadow/enforce` brak albo
stary heartbeat degraduje subcheck, ale nie zmienia istniejącej bramki uptime
opartej o bazę. Deep health sprawdza nowe tabele oraz rozszerzony proces.

## 8. Weryfikacja

Zakres testów jest celowo opisany dokładnie:

- 8 modułów backendowych `test_priority_work*.py`;
- 110 funkcji testowych w tych modułach;
- parametryzacja daje 147 wykonanych przypadków;
- 9 skupionych plików frontendowych i 39 testów.

Wyniki lokalne:

| Kontrola | Wynik |
|---|---|
| backend Priority Work | **147 passed** |
| frontend focused Vitest | **9 plików / 39 passed** |
| Ruff check i format: app, migracja, testy | **pass** |
| Python compile | **pass** |
| `bash -n backend/entrypoint.sh` | **pass** |
| `alembic ... heads` | **pass**, aktualnie jeden head `0200` |
| frontend typecheck | **pass** |
| frontend lint | **pass** |
| token guard | **pass** |
| rebase / range-diff / audyt zmian upstream | **pass**, baza `7c7c2a5b` |
| lokalny Docker | nie uruchamiano |
| draft PR / hosted CI / finalny SHA | **PENDING** |

Lokalne wyniki nie dowodzą PostgreSQL upgrade/retry, pełnego CI, buildu ani
produkcyjnego E2E. Te bramki pozostają do wykonania w hosted CI i po
autoryzowanym deployu.

## 9. Pozostałe kroki do draft PR

1. Przejrzeć dokładny diff, CAS lineage publikacji, safety-net, exact schema
   parity, migrację, downgrade i writer fence.
2. Dołączyć poprawkę mocka po rebase do commita testowego.
3. Wypchnąć `codex/recruitment-priority-lock`.
4. Utworzyć draft PR
   `[DRAFT][NO DEPLOY] Recruitment Priority Lock + Carry-over Duty`.
5. Poczekać na wszystkie wymagane checks i naprawiać wyłącznie regresje tego
   PR.
6. Uzupełnić handoff o URL PR, finalny SHA i dokładny wynik CI.
7. Nie merge’ować i nie wdrażać; przekazać decyzję Claude’owi.

## 10. Definicja ukończenia części Codex

- kompletny draft PR oparty o aktualny `main`;
- wszystkie wymagane checks zielone na finalnym SHA;
- CAS lineage równoległych sibling draftów przechodzi test lokalny i hosted CI;
- brak nieautoryzowanych writerów `CandidateStage`;
- wszystkie ludzkie ingressy mają jawny kanał;
- funkcja domyślnie `off`;
- dokumentacja review zawiera architekturę, role, endpointy, testy, ryzyka,
  rollout, rollback, scenariusze Chrome i GO/NO-GO;
- brak merge, deployu, migracji i konfiguracji produkcji.

Do spełnienia tych warunków stan pozostaje: **lokalnie gotowe do review,
NO-GO dla produkcyjnego enforce**.
