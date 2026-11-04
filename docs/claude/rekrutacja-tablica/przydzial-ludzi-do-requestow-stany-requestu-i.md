# Przydział ludzi do requestów, stany requestu i pulpit „Requesty i obłożenie” (0371, 24.09.2026)

Decyzje Artura 24.09.2026 (makiety: https://claude.ai/artifact/2oeDE266FbUPQd19tybUQ1 —
Main, Portfel, C6). Automat z #1390 nigdy nie ruszył na produkcji (0 osób
z kategorią, brak urlopów z Compassa, jednorazowa kolejka przy handoffie) —
0371 zastąpił go ciągłym przydziałem.

- **Stan requestu `jobs.work_state` należy do NEXUSA** (`NEXUS_OWNED`, Traffit
  go nie pisze): `to_review` („Do przejrzenia”, domyślny) · `searching`
  („Szukamy kandydatów”) · `client_silent` („Klient milczy”) · `finished`
  („Zakończony” — tylko w NEXUSIE, `jobs.status` z Traffita zostaje).
  **„Mamy championa” NIE jest wartością** — to `champion_found_at` przy
  `searching` (`request_work_state.visible_state`, lustro
  `lib/request-work-state.ts` na `__fixtures__/request-work-state-cases.json`).
  Powód: 327 „otwartych” w Traffit przy ~20 w pracy (zmierzone 24.09).
  Handoff i `/jobs/new` → `searching`; zamknięcie → `finished`; terminy od
  klienta albo ruch na `client_interview`/`acceptance` budzą „Klient milczy”
  (`wake_on_client_response`, savepoint, nigdy nie rzuca).
- **„Porządek w requestach”** `/jobs/review-states` (admin/DL/HoR,
  `api/request_work_states.py`): podpowiedź stanu liczona przy odczycie
  (`request_work_state.suggest`); **aplikacje z ogłoszeń (`posting`/`new`)
  NIE są pracą** — 235 z 327 rekrutacji je zbierało bez ruchu rekrutera.
- **Kategorie ludzi**: Ustawienia → Zespół i dostęp → „Zespół rekrutacji”,
  zakładka „Kategorie” (od 20.10.2026; `/settings/team-structure?zakladka=kategorie`,
  stary `/settings/competence-team` przekierowuje; `api/competence_team.py`,
  admin/HoR). Osobny edytor „kompetencja główna + dodatkowe” na tym ekranie
  zniknął — zapisywał te same priorytety 1/2. 1. priorytet jeden na osobę (częściowy UNIQUE), zdjęcie głównej
  jest dozwolone (stare trasy `/api/team-structure/sourcer-categories` tego nie
  pozwalały i zostały nietknięte). `users.allocation_excluded` = „Poza
  przydziałem”. Zasady (od 29.10.2026 dziewięć, zakładka „Automat przydziału” —
  `automat-przydzialu-zasady-w-ustawieniach.md`) w
  `app_settings['request_allocation_rules']`. Przypisania ze screena:
  `scripts/seed_competence_team_2026_09.py` (same id kont).
- **Automat**: czysty planer `services/request_allocation_plan.py` (testy
  bez bazy) + zapis `services/request_allocation.py`, wołany z
  `run_allocation_sweep` w miejsce `allocate_pending`. Pula = published +
  `searching` + bez championa. Kolejność: nikt nie wysłany → 1–2 → 3+, potem
  termin. ≥ próg pasujących w bazie (otwarte propozycje, tylko gdy był nocny
  przegląd) → sourcer, inaczej rekruter. 1. priorytet → 2. → inni; przelew do
  innej kategorii, gdy własna grupa ma o >1 więcej niż minimum zespołu.
  Obłożenie przy wyborze osoby = requesty P1 (od 14.10.2026, ta sama liczba co
  „Obłożenie” na pulpicie — sekcja o obłożeniu P1 niżej).
  **Nie przerzuca działających przypisań**; zwalnia tylko przy wyjściu
  requestu z puli albo niedostępności osoby (auto, bez kandydatów w toku).
  Ręczne przypisania nie są zwalniane za urlop. Tryby
  `recruitment_allocation_state.mode`: `shadow` → `proposed` (pulpit pokazuje
  przerywaną ramką), `auto` → `active` + pierwszy rekruter jako
  `jobs.recruiter_id`, jeśli puste. Bez świeżych urlopów z Compassa `auto`
  nie przydziela nowych (shadow proponuje dalej). Pętla działa dopiero przy
  `RECRUITMENT_ALLOCATION_ENABLED=true`.
- **Automat dobiera i proponuje ludzi tylko do requestów P1** (12.10.2026,
  prośba Head of Recruitment; `RequestInfo.automat_assigns` w planerze, lustro
  frontu `automatAssigns` w `lib/request-priority.ts`). Do tej daty priorytet
  ustawiał tylko kolejność, więc po ręcznym zdjęciu osoby z requestu P2 pętla
  (przebieg co 30 s) brała następną najmniej obłożoną — blokada `_blocked`
  dotyczy pary (request, osoba), nie requestu. Teraz request P2
  i „Przyjmujemy kandydatów” zostaje „Bez rekrutera”, dopóki człowiek kogoś
  nie doda. Osoby już przypisane do P2 zostają (dotyczy rekrutacji, które
  były P2 od początku albo dostały osobę przy P2 — zejście z P1 przenosi zespół
  do „Poprzedni rekruter”, `role-przy-rekrutacji-delivery-lead-rekruter.md`, sekcja „Poprzedni rekruter”): planer nie rusza działających
  przypisań, a **urlop nie zwalnia osoby z requestu innego niż P1** — nikt by
  jej nie zastąpił, a zwolnienie automatu jest trwałe (`_auto_released`), więc
  po jednym dniu urlopu request zostałby bez rekrutera. „Poza przydziałem”,
  brak kategorii i nieaktywne konto zwalniają przypisanie automatu także przy
  P2 (decyzja człowieka o osobie), tylko bez następcy. Żywa propozycja przy P2
  jest zwalniana z powodem `not_p1`, więc tryb `auto` jej nie aktywuje. Zmiana P2 → P1 przy requeście bez rekrutera
  = automat dobierze osobę przy najbliższym przebiegu. Ekrany mówią to samo:
  nagłówek pulpitu, potwierdzenie zdjęcia ostatniej osoby (`refillNote`), pole
  „Rekruter” przy przekazaniu i na `/jobs/new` (`AUTOMATIC_ONLY_P1_NOTE`),
  panel „Zespół”, okno ponownego otwarcia; „Automat przydziela…” w „Nowe
  rekrutacje — kto prowadzi” tylko dla P1. Nowe miejsce, które obiecuje
  przydział albo propozycję automatu, pyta `automatAssigns`.
- **Zwolnienie automatu jest trwałe w bieżącym stanie requestu** (audyt
  24.09.2026): osoba zwolniona przez automat (urlop, „Poza przydziałem”) nie
  wraca adopcją jako `owner` (`_auto_released`), zwolnienie rekrutera automatu
  zdejmuje też prowadzącego, którego automat wpisał, a wiersz `owner`
  nieaktywnego konta jest zwalniany. „Ile pasujących w bazie” = otwarte
  propozycje `full_base`, nie istnienie przeglądu. Ręczne dodanie i zdjęcie
  z pulpitu biorą `allocation_lock` przed blokadą rekrutacji. „Klient milczy”
  przypomina się co 14 dni od ostatniego wysłania (`stats.silent_reminded`).
- **`job_work_assignments` to pamięć automatu** (wiersz nigdy nie jest
  kasowany, zdjęcie = `released` z powodem — z tego liczą się „Zmiany od
  wczoraj”). Kto jest Rekruterem na ekranach (lista, pulpit, panel „Zespół”),
  liczy od 02.10.2026 `services/job_team.py` — sekcja „Role przy rekrutacji…”
  niżej; automat widzi osoby pracujące bez aktywnego wiersza przez
  `_unseen_workers` (`staffed`, `extra_load`).
  Prowadzący rekrutacji (`jobs.recruiter_id` z handoffu, Traffita, ręki) dostaje
  wiersz `source='owner'` przy każdym przebiegu (`_adopt_owners`) — inaczej
  automat dokładałby drugą osobę do requestu, który ktoś już prowadzi; takie
  wiersze nie są „zmianą” ani dzwonkiem. **Zdjęcie ręczne wygrywa:** para
  (request, osoba) zdjęta z pulpitu nie wraca z automatu ani jako prowadzący,
  dopóki request nie zmieni stanu (`_blocked`, po `work_state_changed_at`).
  „Poza przydziałem”/brak kategorii zwalnia od razu; sam urlop — dopiero przy
  świeżych danych z Compassa. Bez nich `auto` nie aktywuje też propozycji.
- **Pulpit**: kafel `request_board` (4 lustra typu kafla, polecany dla
  rekrutera/sourcera/TAC/DL/HoR), `GET /api/request-board`; filtry po stronie
  przeglądarki (`lib/request-board.ts`, adres `rb_*`). Bez podpowiedzi systemu
  — Artur ich tu nie chce. Harness `/preview/request-allocation?screen=`.
- **Filtry pulpitu przyjmują kilka wartości naraz** (27.10.2026, prośba Head
  of Recruitment): Klient, Delivery Lead, Rekruter, Kategoria, Priorytet,
  Termin i Wysłani to listy z checkboxami (`BoardMultiSelect`). W obrębie
  filtra wystarczy dowolna zaznaczona pozycja, między filtrami muszą zgadzać
  się wszystkie. W adresie powtórzony klucz (`rb_cat=1&rb_cat=2`), nie
  przecinek — nazwa klienta może go mieć; stary link z jedną wartością działa.
  „Wysłani” ma też własny przedział od–do (`rb_sent_from`, `rb_sent_to`):
  liczy się razem z zaznaczonymi pozycjami i jak „0 / 1–2 / 3+” pomija
  requesty z championem. Przyciski kategorii na daily znają jedną kategorię —
  przy kilku zaznaczonych żaden nie świeci.
- **Powiadomienia** o `review_time`: `request_assignment_changed` (poranny
  skrót tylko w trybie `auto`, jeden wpis na osobę; od 02.10.2026 także od
  razu po akceptacji propozycji) i `request_review_needed` do DL (nowe do
  przejrzenia, „Klient milczy” co 14 dni, w poniedziałek „Szukamy” bez pracy
  od 30 dni).
  Przegląd wychodzi tylko między `review_time` a 17:00 czasu firmy
  (`_review_due`, `REVIEW_LATEST`) — pierwszy przebieg po wieczornym deployu
  wysłał „poranny” skrót o 20:54; godzina ustawiona przez admina na 17:00
  albo później obowiązuje bez okna. Poranny skrót pomija request, o którym
  osoba dostała już dzwonek przy akceptacji (para osoba × rekrutacja
  z ostatniej doby).
- **„Wysłani” = osoby, których karta stoi dziś u klienta, jak na Tablicy**
  (`job_similarity.at_client_counts`): najnowszy wiersz pary w kolumnach
  `cv_sent`, `client_interview`, `contract`, `hired` przez
  `candidate_stage_column.column_rule` (nazwa etapu szablonu + kod wiersza,
  `board_column_for`). Do 21.10.2026 licznik czytał sam kod etapu, więc
  „Po Interview” (kod `interview`) nie był liczony, a „Rezerwa” (kod
  `cv_sent`) była.
- **„Zweryf.” i „QC CV” obok „Wysłani”** (23.10.2026, prośba Head of
  Recruitment, wariant 1A z makiet
  https://claude.ai/artifact/EpgxNpGii158FV3mXdrcVN): `verified` i `cv_qc`
  w `GET /api/request-board` = osoby, których karta stoi TERAZ w kolumnie
  „Zweryfikowany” / „QC CV” (z kolejką Cpro), ta sama reguła co „Wysłani”
  (`job_similarity.board_column_counts`). Nie licznik narastający — po
  wysyłce osoba przechodzi z „QC CV” do „Wysłani”. Kolumny stoją w każdej
  szerokości tabeli, więc progi `rtable` to 820 / 1120 px, a „Obłożenie”
  staje z boku od 1140 px pulpitu.

## „Nowe rekrutacje P1 — kto prowadzi” i obłożenie P1 (D1–D7, 14.10.2026)

Uwagi Head of Recruitment z 14.10.2026: (1) rekrutacje mimo przydzielenia
i potwierdzenia rekrutera wracały na listę „Nowe rekrutacje — kto prowadzi”,
(2) obłożenie ma liczyć wyłącznie rekrutacje P1, w których osoba uczestniczy.
Artur zatwierdził D1–D7 z makiet (https://claude.ai/artifact/5rs8RXokY7n8kKzQma7kVS).

### Dlaczego wiersze wracały (pomiar na produkcji, 14.10.2026)

- Potwierdzenie zapisywały tylko „Potwierdź”/„Zmień” na liście, pierwsza osoba
  przez `POST /api/jobs/{id}/owner` i decyzje o propozycjach. Zespół ustawiony
  na pulpicie „Requesty i obłożenie”, druga osoba, zdjęcie i okno „Edytuj” —
  nie. Trzy z pięciu nierozstrzygniętych P1 miały zespół ustawiony przez Head
  of Recruitment na innym ekranie.
- Zmiana zespołu gdzie indziej zmieniała prowadzącego, więc wiersz wracał
  z nową osobą (12.10 pięć rekrutacji potwierdzonych dwa razy w godzinę).
- „Mamy championa” przesuwa `jobs.work_state_changed_at`, a lista liczyła od
  niej cykl — potwierdzona rekrutacja wracała jako „przekazano dziś”.
- `MAX_ROWS = 100` działało w zapytaniu, przed odrzuceniem potwierdzonych.
  Ponowne otwarcie 185 rekrutacji 12.10 (fala z Traffita, 135 bez priorytetu)
  wypchnęło 4 z 5 nierozstrzygniętych P1 poza listę.

### Reguła listy (`services/new_job_leads.py`)

- **Tylko P1 bez championa** (D3): `published`, `searching`,
  `champion_found_at IS NULL`, priorytet poziomu `p1`. Także wiersze „bez
  przekazania” (H7) — rekrutacja bez priorytetu i „Przyjmujemy” nie czeka na
  decyzję o prowadzącym, bo automat jej nie obsadza.
- **Własny początek cyklu** (D2): późniejsze z ostatniego wejścia do
  „Szukamy” (`Activity work_state_changed`, `to=searching`, `from` różne od
  `client_silent`) i ostatniego wejścia na P1 (`Activity priority_changed`,
  `to=p1`). Rekrutacja bez wpisu wejścia bierze `work_state_changed_at`.
  Okno 7 dni, potwierdzenia i „Przekazano …” liczą się od tej daty;
  `since_reason` mówi, co ją zaczęło (`handoff` / `reopen` / `p1`), a front
  pisze „przekazano” / „otwarta ponownie” / „podniesiona na P1”.
  **Nie wolno** zamiast tego ruszać znaczenia `work_state_changed_at`:
  steruje `owner_is_working_clause`, `released_owners` i blokadą ręcznych
  zdjęć automatu (`_blocked`), a champion przesuwa ją celowo (R8-N7-5).
- **Decyzja Head of Recruitment z każdego ekranu** (D1):
  `new_job_leads.record_team_decision(db, job_id, actor, via)` — gdy aktor
  ma rolę z `PROPOSAL_DECISION_ROLES`, zapisuje potwierdzenie osoby, która
  PO zmianie prowadzi (bez prowadzącego nic). Wołają go: `POST/DELETE
  /api/request-board/jobs/{id}/people`, decyzje o propozycjach (pojedyncza
  i zbiorcza — przy rekrutacji z prowadzącym zaakceptowana osoba dochodzi jako
  druga, więc potwierdzany jest prowadzący, nie ona), `POST/DELETE
  /api/jobs/{id}/owner`, `/claim`, `POST/DELETE /api/jobs/{id}/collaborators`,
  PATCH `recruiter_id`. Nowa ścieżka zmieniająca zespół woła ten helper.
  Przy odczycie wiersz znika też, gdy aktywny wiersz przypisania prowadzącego
  wpisała osoba z rolą decyzyjną w bieżącym cyklu (dane sprzed reguły
  i ścieżki, które ktoś pominie).
- **Powód powrotu**: `returned_from_user_id` / `returned_from_name` = osoba
  z ostatniego potwierdzenia w cyklu, gdy prowadzi dziś ktoś inny; wiersz
  mówi „Wraca, bo prowadzący zmienił się po decyzji Head of Recruitment:
  było X.”.
- `MAX_ROWS` przycina wynik, nie zapytanie.
- Zmiana poziomu priorytetu zapisuje `priority_changed`
  (`job_priority.record_level_change`) w PATCH rekrutacji i w kreatorze
  onboardingu Delivery Leada; wpis `updated` niesie tylko nowe wartości, a okno
  edycji odsyła priorytet przy każdym zapisie.

### „Zmień” zaznacza, zapisuje dopiero „Potwierdź” (20.10.2026)

Prośba Head of Recruitment: wybór innej osoby w „Zmień” zapisywał ją od razu
i zdejmował wiersz, a nie dało się dać kilku osób.

- „Zmień” / „Wybierz” w `NewJobLeadsSection` to lista wielokrotnego wyboru
  (zostaje otwarta). Zaznaczenie to **szkic w przeglądarce** — nic nie idzie
  na serwer, wiersz mówi „niezapisane — zapisze „Potwierdź”” i ma „Cofnij”.
- Zespół ze szkicu (`leadDraftTeam`): obecny prowadzący prowadzi dalej, jeśli
  zostaje zaznaczony; odznaczony — prowadzi pierwsza zaznaczona osoba
  (`POST /api/jobs/{id}/owner`). Pozostali dochodzą jako rekruterzy
  (`POST /api/jobs/{id}/collaborators`).
- **Szkic nie może iść na serwer przed „Potwierdź”**: każda trasa zmiany
  zespołu woła `record_team_decision` (D1), więc pierwszy zapis zdejmuje
  wiersz. Bez zmian „Potwierdź” woła samo `lead-confirmation`.
- Zapis to kilka żądań po kolei; przy błędzie komunikat mówi, co weszło
  („Zapisano: … Reszta nie: …”), a szkic znika, bo wiersz ma pokazać stan
  z serwera.

### Obłożenie P1 (D4–D7)

- `GET /api/request-board` → `load[].count`/`proposed`/`requests` = tylko
  rekrutacje P1 „Szukamy” bez championa, w których osoba jest w roli
  „Rekruter” (prowadzi, przypisana, dopisana) — nie cała kategoria
  („uczestnicy” w znaczeniu NEXUSA). Pozostałe to `outside_p1`. Osoba z samymi
  rekrutacjami spoza P1 zostaje na liście z zerem: z tej listy biorą się filtr
  „Rekruter” i okienka wyboru osoby.
- Ta sama liczba wszędzie: panel „Obłożenie” (pulpit i „Czeka na Ciebie”),
  „Zmień” przy prowadzącym, „Zamień” i powód „ma N rekrutacji P1” przy
  propozycji (`request_allocation_proposals.load_pending`), okienko „Rekruter”
  na liście rekrutacji — „N P1” (`p1LoadLabel`).
- Automat (D5): `plan_assignments` dolicza do obłożenia tylko wiersze przy
  requestach P1, `_unseen_workers` liczy `extra_load` tylko z P1. Ludzi przy
  requestach spoza P1 planer nadal nie rusza.
- Po kliknięciu osoby (D6): jej rekrutacje P1 i linia „Poza P1: N rekrutacji —
  nie liczą się do obłożenia. Pokaż na liście rekrutacji”
  (`/jobs?open=1&stage=searching&who=<id>&prio=p2,accepting`).
- Pasek (D7) względem najbardziej obłożonej osoby na liście (`loadBarScale`,
  liczone z propozycjami), nie stałej 5.
- Poza zakresem: kafel „Obciążenie zespołu” (`recruitment_allocation.load_workloads`,
  inna miara: searche, procesy, kontakty).
