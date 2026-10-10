# `/jobs/new` w sześciu sekcjach: wiersze wymagań, deal breaker, kategoria i prowadzący (02.10.2026)

Decyzje Artura 02.10.2026, makiety https://claude.ai/artifact/UPDv1tSQBeo5t9kLW6WJoH,
raport `docs/new-job-panel-redesign-completion-report.md`. Pomiar na 20 najnowszych
rekrutacjach: 53 ze 185 must-have to zdania, krytycznych nie wybrał nikt, 59% słów
z „wymagań do wyszukiwania” powtarzało must, deal breaker miały 3 z 99 pytań.

- **Krok 1 = klient + trzy kafle źródła** (`NewJobSourceStep`: wklej treść, wgraj
  plik, wpisz ręcznie). Bez klienta przycisk zostaje aktywny i po kliknięciu
  pokazuje komunikat przy polu klienta — nie wracaj do nieaktywnego przycisku
  bez wyjaśnienia.
- **Wymagania to JEDNA lista wierszy: `stack.rows = [{words, level}]`** w Profilu
  Championa (JSONB, bez migracji). Wiersz = wymaganie, słowa = warianty, poziom =
  krytyczne / musi mieć / mile widziane. Serwer WYPROWADZA z nich przy zapisie
  pola, które czyta reszta systemu (`services/champion_requirement_rows.expand_patch`
  w `_save_champion_profile`): `stack.must` / `stack.nice` (etykieta = pierwsze
  słowo; „A lub B” tylko dla różnych technologii ze słownika), `stack.critical`,
  `search.requirements` (wiersze krytyczne i „musi mieć”). Scoring, bramka
  krytycznych, QC CV i generator CV czytają te pola jak dotąd.
  - W ZAPISIE poziom wiersza to tylko must / nice; krytyczne ma jedno źródło —
    `stack.critical`. Zapisany profil odesłany bez zmian zachowuje krytyczne
    (etykieta musi mieć swój wiersz), `critical: null` je zdejmuje, `[]` =
    „Brak krytycznych”.
  - Zapis starą drogą (import dokumentu, szkic AI, stary edytor), po którym
    `must` / `nice` / `search.requirements` nie odpowiadają wierszom, kasuje
    `stack.rows` (walidator `ChampionProfile`, `rows_consistent`) — profil wraca
    do starych pól zamiast pokazywać nieprawdziwą listę.
  - `champion_view.requirement_source` pomija `rows` (jak `critical`): zmiana
    samego wariantu słowa nie unieważnia kontraktu wymagań ani odcisku rankingu.
  - Front: `lib/requirement-rows.ts` (czyste reguły), `lib/requirement-rows-api.ts`,
    `components/champion/RequirementRowsEditor.tsx` — ten sam edytor na
    `/jobs/new` i w Profilu Championa. Profil na starych polach ma „Uprość do
    słów kluczowych” (`POST /api/job-intake/requirement-rows`, nic nie zapisuje:
    technologie → wiersze, zdania klienta → `stack.notes`).
- **Odczyt maila v10** (`JOB_REQUEST_INTAKE`): `requirements: [{words, level}]`
  + `descriptive_requirements` (zdania i wersje — dosłowne cytaty, nie filtrują
  kandydatów) + pytania z `deal_breaker`. Słowa przechodzą te same sita co
  wiersze wyszukiwania (`_ground_row`: całe słowo z maila, rdzeń z gwiazdką,
  jeden odpowiednik EN). Odpowiedź modelu w starym kształcie nadal działa.
  „Frazy do LinkedIna” usunięte z formularza, edytora i podglądu (dane w
  profilach zostają).
- **„Szukaj ręcznie” dla profilu z wierszami wymaga tylko wierszy KRYTYCZNYCH**
  (`ManualSearchPanel.championCriticalRowFlags`); pozostałe „musi mieć” idą do
  „Mile widziane”. Profil bez wierszy — jak dotąd (technologie obowiązkowe).
- **Deal breaker przy każdym pytaniu jest wymagany do „Przekaż do searchu”**
  (`job_readiness.MSG_DEAL_BREAKER`, lustro `job-readiness-blockers.json`) —
  ale tylko dla rekrutacji jeszcze nieprzekazanych (`job.is_open == False`)
  i poza bramką briefu, którą czyta automat. Na `/jobs/new` propozycje AI
  (pytanie, dobra odpowiedź, odpowiedź, która odpada) Delivery Lead zatwierdza
  („Zatwierdź wszystkie”; edycja pola też zatwierdza).
- **Numer u klienta nie ma osobnego pola**: `clientReferenceFor` czyta go z nazwy
  od klienta (numer z odczytu, dopóki stoi w nazwie; inaczej jednoznaczny ZOB),
  „To nie ten numer” pozwala wpisać inny albo żaden. `create_job` bez pola
  `client_reference` w żądaniu bierze `reference_from_title`; pole wysłane puste
  to decyzja „bez numeru” i zostaje puste (formularz wysyła je po „To nie ten
  numer”). Tytuł dla zespołu składa się sam (podgląd + „Zmień”).
- **Kategorię kompetencji potwierdza Delivery Lead** (sekcja 6):
  `POST /api/job-intake/category-suggestion` (ta sama reguła co przy zapisie,
  `job_cc.resolve_job_cc_id`; `participants` = liczba osób, bez nazwisk),
  `POST /api/jobs` niesie `competence_category_id`, a wybór inny niż podpowiedź
  zapisuje `cc-override`. W panelu „Zespół” kategorię zmienia osoba z pełną
  edycją rekrutacji (`JobCategoryRow` → „Zmień”).
- **Uczestnicy = wszyscy z kategorii, w tle** (`services/auto_cc_collaborators.py`):
  `sync_cc_participants` utrzymuje wiersze `job_collaborators.source='auto_cc'`
  dla aktywnych rekruterów / sourcerów / TAC z kategorią rekrutacji (1. i 2.
  priorytet) — przy tworzeniu, zmianie kategorii rekrutacji, zmianie składu
  kategorii i co godzinę (`tasks/cc_participants_sync.py`, heartbeat). Zakres:
  rekrutacje niezamknięte i nie „Zakończone”. Nie rusza wierszy `manual`;
  osoba zdjęta przez człowieka zostaje zdjęta (`removed_from_auto_cc`).
  Uczestnik widzi rekrutację w „Moja kategoria”, ale NIE jest „Rekruterem”
  (`job_team` bez zmian) i od 06.10.2026 NIE dostaje dzwonków rekrutacji (D7:
  `list_job_member_ids(..., include_category_participants=False)` w
  producentach dzwonków — zmiana Championa, alerty terminu, „komplet obsady”).
  Członkostwo (dostęp, czat) nadal go liczy. Pole „Kolejne osoby”
  zniknęło z `/jobs/new` (osobę dopisuje się w panelu „Zespół”).
- **Rekruter prowadzący: automat przydziela OD RAZU** (tryb `auto`), bez
  akceptacji Head of Recruitment i bez danych o urlopach. Planer blokuje tryb
  `auto` tylko, gdy Compass jest WŁĄCZONY i nieświeży (`PlanInput.leave_blocks_auto`);
  `PUT /mode` pozwala na `auto` przy wyłączonym Compassie. Przypisana osoba
  dostaje dzwonek `request_assignment_changed` od razu
  (`request_allocation_notices.notify_assigned`), poranny skrót w `auto` niesie
  już tylko zwolnienia. Tryb `shadow` (propozycja do akceptacji) zostaje w kodzie;
  etykieta opcji zależy od trybu („Przydzieli automat” / „Zaproponuje automat”).
- **Head of Recruitment widzi „Nowe rekrutacje — kto prowadzi”** w „Czeka na
  Ciebie” (`services/new_job_leads.py`, pole `new_job_leads` w
  `GET /api/board-tasks`, tylko `PROPOSAL_DECISION_ROLES`): rekrutacje przekazane
  do searchu w 7 dniach, prowadzący, źródło (automat / wskazany ręcznie),
  kategoria, liczba uczestników. Lista informacyjna — nie wchodzi do licznika;
  „Zmień” zapisuje przez `POST /api/jobs/{id}/owner`. Filtry (09.10.2026:
  klient, kategoria, Delivery Lead, prowadzący, priorytet) działają
  w przeglądarce na wierszach z odpowiedzi (`lib/new-job-leads-filters.ts`),
  więc `MAX_ROWS` (100) jest bezpiecznikiem, nie stroną — wiersz ucięty limitem
  byłby dla filtrów niewidoczny. Wybór jest zapamiętany w przeglądarce per
  konto (`nexus:new-job-leads-filters:<id>`) i wylogowanie go nie czyści;
  filtr, którego wartości nie ma dziś na liście, nie działa, ale wraca, gdy
  taka rekrutacja znowu się pojawi. Ten sam pasek (`LeadFiltersBar`,
  `useLeadFilters`) stoi nad „Propozycjami automatu do akceptacji” z własną
  pamięcią (`nexus:allocation-proposals-filters:<id>`); osobą jest tam
  proponowana osoba, a przy ustawionych filtrach przycisk zbiorczy nazywa się
  „Akceptuj pokazane (N)” i wysyła tylko pokazane propozycje.
- **„Obłożenie” stoi w „Czeka na Ciebie” pod listami przydziału** (09.10.2026,
  prośba Head of Recruitment; `dashboard/TeamLoadSection.tsx`): te same dane
  i reguła co na pulpicie „Requesty i obłożenie” (`GET /api/request-board`,
  `LoadPeople` z `request-board/LoadPanel.tsx` w wariancie `columns` — osoby
  w kolumnach, requesty klikniętej osoby pod listą). Widać je tylko osobie
  decydującej o przydziale (`can_decide_proposals`) i tylko, gdy „Propozycje
  automatu” albo „Nowe rekrutacje — kto prowadzi” mają wiersze; bez tego panel
  nie pyta o tablicę requestów. Do liczników zadań się nie liczy. Odznacza się
  je w „Listy nad pulpitem” (klucz `team_load` — jedyny, którego nie ma
  w odpowiedzi `/api/board-tasks`, więc sprawdza go sam panel).
- **Podpowiedź kategorii pyta tylko o rolę, która stoi w polu**
  (`categoryInputCurrent` w `NewJobPage`): zapytanie idzie po chwili ciszy,
  a zaraz po odczycie requestu opóźniona wartość to jeszcze puste pole —
  podpowiedź dla pustej roli migała i znikała, razem z przyciskiem „Potwierdzam”.
- Harness `/preview/new-job?state=request|noclient|manual|review|gaps|shadow|passive|off`;
  profil z wierszami: przypadek 4 w `/preview/champion-profile`.
