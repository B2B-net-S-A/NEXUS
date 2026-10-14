# Role przy rekrutacji: Delivery Lead · Rekruter · Kategoria; propozycje automatu akceptuje Head of Recruitment (0409, 02.10.2026)

Feedback Olafa (Head of Recruitment) i decyzje Artura 02.10.2026, makiety
https://claude.ai/artifact/Kt5dniKtgBLdryqMfzc122. Do tej daty panel rekrutacji
mówił „Właściciel projektu” i „Współpracownicy” (w 17 z 18 przypadków cała
kategoria dopisana automatycznie), pulpit „Requesty i obłożenie” pokazywał
u każdego 0 (czytał same `job_work_assignments`, a 19 z 20 requestów miało
tylko `recruiter_id`), a Head of Recruitment nie mógł zmienić rekrutera.

- **Trzy role.** Delivery Lead (`jobs.delivery_lead_id`) otwiera request.
  **Rekruter** = osoby, które pracują nad rekrutacją (jedna albo kilka).
  **Kategoria** = ludzie z kategorii kompetencji, informacyjnie: widzą request
  w zakresie „Moja kategoria”, ale nad nim nie pracują, dopóki ktoś ich nie
  przypisze. Nazw „Właściciel projektu”, „Prowadzi”, „Współpracownicy”,
  „Kto pracuje”, „Nikt nie pracuje” w UI już nie ma („Rekruter”, „Kolejne
  osoby”, „Bez rekrutera”).
- **Kto jest Rekruterem — JEDNA reguła, `services/job_team.py`** (lustro frontu
  `lib/job-team.ts`): (1) prowadzący `jobs.recruiter_id` — aktywne konto,
  niezdjęte ręcznie w bieżącym stanie requestu; (2) AKTYWNE przypisanie
  (`job_work_assignments.state = 'active'`, bez wierszy `source = 'owner'` —
  to lustro punktu 1); (3) współpracownik dopisany ręcznie
  (`job_collaborators.source = 'manual'`). **Propozycja automatu
  (`state = 'proposed'`) nie jest pracą.** Loader `recruiters_for_jobs`
  i klauzule SQL (`jobs_worked_by_clause`, `jobs_nobody_working_clause`) muszą
  dawać ten sam zbiór — pilnuje `tests/test_job_team.py`. Czytają ją: lista
  `/jobs` (pole `recruiters`, filtr „Rekruter”, „Bez rekrutera”, zakres
  „Moje”), pulpit „Requesty i obłożenie” (ludzie i obłożenie), panel „Zespół”,
  członkostwo rekrutacji (`job_membership` — odbiorcy powiadomień), kreator
  metryk i widoki osobiste. Wewnątrz automatu (`request_allocation.py`)
  i w „Zmianach od wczoraj” zostaje `state <> 'released'`.
- **„Moje” nie liczy już wierszy `auto_cc`** (cała kategoria) — te rekrutacje
  są w zakresie **„Moja kategoria”** (`my_category`, URL `mycat=1`: GŁÓWNA
  kategoria rekrutacji ∈ kategorie osoby, tylko niezamknięte; osoba bez
  kategorii nie widzi zakresu — `quick-counts.my_category = null`). Wiersze
  `auto_cc` zostają w bazie i w członkostwie rekrutacji, ale od 06.10.2026
  nie są odbiorcami jej dzwonków (sekcja „Przekazanie, propozycje i Champion
  po audycie 06.10.2026”). „Moje
  przypisane” w operacjach rekrutacji też liczy tylko ręcznych
  współpracowników (`manual_collaborator_job_ids`).
- **Zdjęcie osoby = `job_team.remove_recruiter`** — ze wszystkich trzech miejsc
  naraz (prowadzący przez `release_operator`, aktywne przypisanie z powodem
  `manual`, wiersz ręcznego współpracownika). Wołają je `DELETE /api/jobs/{id}/owner`,
  `DELETE /api/request-board/jobs/{id}/people/{user_id}` (każda niezamknięta
  rekrutacja) i PATCH `recruiter_id: null` z okna edycji („— bez rekrutera —”,
  14.10.2026). Zgłoszenie Head of Recruitment: okno wysyłało puste pole jako
  `undefined`, klucz wypadał z PATCH-a i rekruter wracał po odświeżeniu (od
  pierwszej wersji repo); a gdyby nawet doszedł `null`, zwolnienie
  `owner_changed` nie blokowało automatu, który w trybie `auto` mógł wpisać
  tę samą osobę z powrotem. Okno wysyła `null` tylko wtedy, gdy otworzyło się
  z rekruterem; pole puste od otwarcia nie jedzie wcale — formularz powstaje
  raz, a w tym czasie rekrutera mógł wpisać automat albo pulpit, więc `null`
  zdjąłby (i zablokował dla automatu) osobę, której nikt nie zdejmował.
  Pilnuje `test_recruiter_cleared_in_the_edit_window_works_like_release`
  i dwa testy okna w `EditJobModalContentScope.test.tsx`. Prowadzący jest zdejmowany PRZED przypisaniem: `manual_remove`
  czyści `recruiter_id` UPDATE-em, który sesja odbija na obiekcie `job`.
  Prowadzący bez wiersza przypisania (rekrutacja prowadzona przed włączeniem
  automatu) zostawia przy zdjęciu ślad `remember_manual_release`: wiersz
  `source='owner'`, `released`, powód `manual` — tylko gdy request jest w puli,
  a osoba ma rolę roboczą. Czyta go `_blocked`, więc automat nie zaproponuje
  jej ponownie w tym stanie requestu; „Zmiany od wczoraj” i poranny skrót go
  nie widzą (pomijają `source='owner'`). `POST /owner` na zamkniętej
  rekrutacji = 409 (jak `/claim`), zdjęcie osoby zostaje dozwolone; panel
  „Zespół” chowa wtedy „Przypisz…” i „Zmień”.
- **Zmiana rekrutera** (`POST /owner`, `/claim`, PATCH `recruiter_id` z okna
  edycji) przechodzi przez `_sync_work_assignments_with_owner` (`api/jobs.py`):
  poprzednia osoba traci aktywne przypisanie (`owner_changed`), a nowa w puli
  dostaje ręczne (`manual_add`). Puste pole to nie zmiana, tylko zdjęcie —
  idzie przez `remove_recruiter` (punkt wyżej); `owner=None` w tej funkcji
  zostaje dla porządków bez człowieka (otwarcie bez roli rekrutera,
  przeniesienie z Traffita). PATCH bierze `allocation_lock` PRZED wierszem
  rekrutacji, gdy żądanie niesie `recruiter_id` — ta sama kolejność blokad co
  `/owner` i przebieg automatu. Ręczne „Przekaż do searchu” woła tę samą
  funkcję po `set_work_state` — ponowne przekazanie innej osobie zastępuje
  rekrutera, a nie dokłada drugiego.
- **Zmiana roli na Finanse zwalnia przypisania do requestów**
  (`finance_role_cleanup`: aktywne → `excluded`, propozycja →
  `proposal:excluded`), razem z prowadzeniem rekrutacji i współpracą.
- **Ponowne przypisanie przez człowieka znosi wcześniejsze ręczne zdjęcie**
  (`request_allocation.void_manual_release`: powód `manual` → `reassigned`).
  Woła je `manual_add` (pulpit, „Zmień” przy propozycji, nowy rekruter w puli),
  zmiana rekrutera poza pulą i `assign_operator`, gdy wpisuje prowadzącego
  (także z planu priorytetów). Bez tego osoba zdjęta i dodana ponownie w tym
  samym stanie requestu była prowadzącą, której reguła zespołu nie liczyła —
  kolejna dodana osoba wchodziła na jej miejsce. Nowa ścieżka, którą człowiek
  przypisuje osobę do requestu, idzie przez `manual_add` albo woła ten helper.
- **Dopisanie osoby = trwały wpis w zespole, niezależnie od miejsca (0429,
  12.10.2026)** — `job_team.add_manual_member`, lustro `remove_recruiter`.
  Zgłoszenie Head of Recruitment: osoba dodana z pulpitu miała samo
  przypisanie, które automat zwalnia przy wyjściu requestu z „Szukamy”, więc
  znikała z filtra „Rekruter”, a prowadzący i osoby z panelu „Zespół”
  zostawały; dopisanie z panelu nie wysyłało dzwonka. Teraz:
  - wołają ją `manual_add` (pulpit, zamiana propozycji), `accept_proposal`,
    `restore_after_champion_removed` i `POST /api/jobs/{id}/collaborators`;
    przypisanie niesie już tylko obłożenie w puli. Nowa droga dopisania osoby
    przez człowieka też ma ją wołać;
  - prowadzący wiersza nie dostaje (jest przy rekrutacji z urzędu), wiersz
    `auto_cc` albo zdjęty staje się `manual`. Sesja nie robi autoflush —
    funkcja sama robi `flush`, zanim odczyta prowadzącego;
  - przypisań automatu (`source = 'auto'`) nie utrwalamy: automat zwalnia je
    za urlop, a trwały wpis trzymałby request „pokryty” przez osobę, której
    nie ma;
  - `POST …/collaborators` dzwoni „Nowy request do pracy” (`_notify_new_owner`)
    — bez dzwonka dla siebie, dla osoby, która już przy rekrutacji pracuje,
    i przy rekrutacji zamkniętej;
  - zastąpiony prowadzący traci też ręczny wiersz współpracownika
    (`_sync_work_assignments_with_owner`), inaczej „Zmień” by go nie zdejmowało.
    Okno edycji dopisuje go ponownie, jeśli po zmianie pierwszego rekrutera
    nadal stoi w polu „Kolejne osoby” (`collaboratorChanges` z
    `previousOwnerId`) — inaczej znikłby po cichu, choć okno go pokazywało;
  - `DELETE …/collaborators/{user_id}` dla osoby z aktywnym przypisaniem woła
    `remove_recruiter` (schodzi z obu miejsc) i wymaga roli przydzielającej
    (`user_can_staff_job`); pozostali redaktorzy dostają 409. Wiersz
    prowadzącego kasuje się jak dotąd, bez ruszania jego przypisania;
  - pilnuje `tests/test_recruiter_role_persists.py`: każda droga dopisania →
    `GET /api/jobs?worked_by=` zwraca rekrutację także po championie,
    „Klient milczy”, powrocie do przejrzenia i zamknięciu.
- **Uprawnienia** (`api/recruitment_access.py`, lustra w `capabilities.test.ts`):
  `/owner` POST/DELETE i edycja pulpitu — `require_job_staffing`: uprawnienie
  „Rekrutacje: zakładanie, zamykanie, wysyłka CV do klienta” (domyślnie admin
  i Delivery Lead) ALBO rola Head of Recruitment (`JOB_STAFFING_EXTRA_ROLES`);
  priorytet — to samo uprawnienie albo TAC i HoR (`JOB_PRIORITY_EXTRA_ROLES`;
  wyjątek w `ensure_job_editor`: HoR ustawia `priority`, innych pól cyklu życia
  nie); `PROPOSAL_DECISION_ROLES` (admin, Head of Recruitment) — decyzje
  o propozycjach, zostają przy roli. `GET /api/jobs/{id}` niesie `can_staff` i `can_set_priority`
  (Delivery Lead tylko w swoim zakresie). Head of Recruitment sam nie może być
  rekruterem (`_OWNERSHIP_ELIGIBLE_ROLES` bez zmian).
- **Rekruterem jest tylko rola rekrutera — główna albo dodatkowa (decyzja
  Artura 14.10.2026).** Zgłoszenie „Delivery Leadzi wpisani jako rekruterzy”:
  `/owner`, `/claim`, `/collaborators`, PATCH `recruiter_id`, `/jobs/new`,
  przekazanie i ponowne otwarcie przyjmowały admina i DL-a (część także
  Finanse i Head of Recruitment), a pole „Rekruter” w oknie edycji pokazywało
  wszystkie konta. Teraz jedna lista `_OWNERSHIP_ELIGIBLE_ROLES` = `job_team.WORK_ROLES`
  (`api/jobs.py`, lustro `COLLABORATOR_ROLES` + `hasRecruiterRole` w
  `lib/job-collaborators.ts`): odmowa 409/403/400/422 z jednym zdaniem
  „Rekruterem rekrutacji może być tylko osoba z rolą rekrutera.”; DL i admin
  bez tej roli nie widzą „Biorę” / „Dołącz”, nie ma ich w „Zmień rekrutera”,
  „+ Dodaj osobę”, „Kolejnych osobach”, polu „Rekruter” okna edycji ani
  w filtrze „Rekruter” listy. DL, który sam rekrutuje, dostaje rekrutera jako
  rolę dodatkową w „Osoby i role” (tak mają konta, którym 0411 zamieniło TAC
  na rekrutera — Artur: „oni są też rekruterami”). Okno edycji zapisuje
  niezmienione pole z dawnym DL-em bez odmowy (walidacja tylko przy zmianie).
- **„Otwórz ponownie” z zachowaniem zespołu (14.10.2026,
  `reopen_keep_team_core`).** Przed otwarciem
  `job_team.settle_team_without_recruiter_role` zdejmuje z pola „Rekruter”
  i z „Kolejnych osób” konta bez roli rekrutera (DL idzie na wolne miejsce
  Delivery Leada, wpisanego przez człowieka nie rusza; wpis
  `handed_off_to_search` niesie `owner_without_recruiter_role`
  i `collaborators_without_recruiter_role`). W zamkniętych rekrutacjach
  z Traffita w polu „Rekruter” siedzi „osoba odpowiedzialna” (14.10: 1 017
  z DL-em, 158 z adminem, 53 z Finansami) — 13.10 DL otworzyła tak dwie
  rekrutacje Credit Agricole i stała przy nich jako rekruterka. Okno
  ponownego otwarcia nie obiecuje wtedy „zostaje bez zmian”.
  **Ten sam zespół po otwarciu** (prośba Artura 14.10) daje trwały wpis 0429:
  zamknięcie nie rusza ani prowadzącego, ani ręcznie dopisanych, a automat
  zwalnia tylko przypisania (`finished`). Pomiar 14.10: na otwartych
  rekrutacjach nikt nie pracuje wyłącznie przez przypisanie. Osobnego
  „przywracania” z wierszy `finished` nie ma — wskrzeszało osoby zdjęte po
  zamknięciu i łapało poprzedni cykl. Pilnuje
  `test_reopen_brings_back_the_same_team` (`test_job_no_drafts.py`); nowa
  droga dopisania osoby bez trwałego wpisu złamie ten test.
- **Automat PROPONUJE, człowiek akceptuje.** Tryb `shadow`
  (`recruitment_allocation_state.mode`) zakłada najwyżej jedną propozycję na
  request bez Rekrutera; do akceptacji nikt nie jest przypisany ani
  powiadamiany. Decyzje: `POST /api/request-board/jobs/{job_id}/proposals/{user_id}`
  (`accept` | `reject` | `replace`) i `POST /api/request-board/proposals/accept`
  (hurtem, wynik per pozycja `accepted|gone`). Akceptacja to
  `UPDATE … WHERE state = 'proposed'` → `active`, `source = 'manual'`,
  `assigned_by`, `assigned_at` — **nie `manual_add`** (ten przy nieaktualnej
  propozycji wstawiłby nowy wiersz po cichu); 0 wierszy = 409. Odrzucenie to
  powód `proposal:rejected` — **nie `manual_remove`** (zwykłe `manual` na wierszu
  automatu psuje `_last_assignment_was_auto` i regułę „prowadzący zdjęty
  ręcznie”); odrzucona para nie wraca w tym stanie requestu (blokada tylko dla
  planera). Każda decyzja zostawia `Activity allocation_proposal_decided` (same
  ID) — z tego liczymy trafność automatu przed ewentualnym trybem `auto`.
  Zaakceptowana albo wybrana osoba dostaje dzwonek `request_assignment_changed`
  (kategoria obowiązkowa „Wzmianki”).
- **Planer** (`request_allocation_plan.py`): od 12.10.2026 dobiera
  i proponuje ludzi tylko do P1 (sekcja „Przydział ludzi do requestów…”);
  kolejność = kubełek wysłanych, termin; request P2 i „Przyjmujemy
  kandydatów” (`passive`) zostaje w puli, ale nie dostaje osoby ani
  propozycji; request z osobą pracującą inną drogą
  (`staffed`, np. ręczny współpracownik) jest pokryty, a propozycja przy nim
  jest zwalniana (`superseded`); `extra_load` dolicza takie requesty do
  obłożenia (od 14.10.2026 tylko P1).
- **Pulpit Head of Recruitment:** „Czeka na Ciebie” (`GET /api/board-tasks`)
  niesie `allocation_proposals` (tylko dla decydujących), `can_decide_proposals`,
  `allocation_leave_known`; źródłem jest `request_allocation_proposals.load_pending`
  (propozycja żywa, request w puli i bez Rekrutera, konto aktywne) — ten sam
  zbiór liczy dzwonek `request_allocation_proposals` (jeden wpis na osobę na
  dzień, podbijany przy zmianie liczby; link `/dashboard#czeka-na-ciebie`).
  Podbicie wysyła też zdarzenie WS (`queue_ws_notification`) — `emit` robi to
  tylko przy nowym wpisie, a po odrzuceniu propozycji automat proponuje
  następną osobę tego samego dnia i otwarty pulpit ma ją pokazać od razu.
  Awaria ładowania nie kładzie pulpitu (savepoint + pusta lista).
- **Priorytet wrócił w trzech poziomach** (`services/job_priority.py`, lustro
  `lib/request-priority.ts`): P1 Pilne (`urgent`, historyczne `high`) · Bez
  priorytetu (`medium`) · Przyjmujemy kandydatów (`low`). **Poziom środkowy
  nazywa się „Bez priorytetu”** (decyzja Artura 12.10.2026, do tej daty „P2
  Standard”): Delivery Lead nie miał jak zdjąć priorytetu z rekrutacji po
  terminie, choć ten poziom działał już jak jego brak (bez plakietki, bez
  przydziału automatu, bez podbicia w sortowaniu) — w Traffit priorytet był
  tagiem, który się zdejmowało. Zmieniła się tylko nazwa na ekranach: klucz
  `p2`, wartość `medium` i adres `prio=p2` zostają, a w kodzie i regułach
  poziom nadal bywa nazywany P2. Czwartego poziomu („Brak”) nie dodajemy —
  działałby dokładnie jak `p2`. Kolumna zostaje przy
  czterech wartościach; filtr listy `priority_level` (URL `prio`; klucz
  `priority` to stary, zdejmowany klucz adresu), sort „Wymaga uwagi” stawia P1
  na górze, pole „Priorytet” jest w panelu „Zespół”, na `/jobs/new` i od
  14.10.2026 jako plakietka przed tytułem rekrutacji (`JobPriorityMenu`: ten sam
  zapis i te same prawa — `prostszy-ekran-…`, sekcja „Nagłówek w trzech
  cienkich liniach”).
  **Nowa rekrutacja zaczyna od P1** (decyzja Artura 08.10.2026, do tej daty
  P2): `job_priority.default_priority_for_new_job` jest domyślną wartością
  `POST /api/jobs`, a `/jobs/new` zaznacza `NEW_JOB_PRIORITY_LEVEL` (lustro
  pilnuje `test_new_job_default_priority.py`). Priorytet nie spada sam.
  Domyślna kolumny w modelu zostaje `medium` (import Traffita = archiwum).
- **Lista i pulpit mają te same dane i filtry:** Delivery Lead · Klient ·
  Rekruter · Kategoria · Priorytet · Termin · Data otwarcia
  (`opened_effective_at` = `COALESCE(opened_at, created_at)`, filtr
  `opened_from`/`opened_to` w dobie Europe/Warsaw). Obłożenie = liczba
  requestów P1, przy których osoba jest Rekruterem (od 14.10.2026; reszta
  jako `outside_p1`, `przydzial-ludzi-do-requestow-stany-requestu-i.md`); propozycje
  osobno („2 + 1”).
  Układ szerokości bez zmian względem #1967 (`lib/wide-table.ts`): Delivery
  Lead i priorytet nie mają własnych kolumn (priorytet = plakietka przy
  tytule, Delivery Lead = druga linia komórki „Rekruter”).
- **Przekazanie do searchu:** domyślnie „Zaproponuje automat” (gdy flaga
  włączona i tryb ≠ `off`), inaczej „Wybieram sam”
  (`lib/recruiter-assignment.ts` — jedno pole na `/jobs/new` i w oknie
  „Przekaż do searchu”). Gałąź `automatic` zakłada migawkę dopasowań
  i `Activity handed_off_to_search` jak ręczna; przy trybie `off` odmawia 409.
- **Flaga `RECRUITMENT_ALLOCATION_ENABLED` nie dokłada już bramki ani ciężkich
  zapytań:** gałąź `sourcing_paused` w `priority_work_policy` stoi pod powrotem
  `mode off` („Kanban bez bramek”); przebieg bez Compassa pomija
  `load_workloads`/`allocation_issues` i alert `availability_stale`,
  z Compassem liczy je najwyżej co 10 min; przetworzone zdarzenia starsze niż
  doba są kasowane.
- **Start bez urlopów (decyzja Artura 02.10.2026):** `COMPASS_AVAILABILITY_ENABLED`
  nie jest ustawione, więc automat może zaproponować osobę na urlopie — panel
  mówi „Brak danych o urlopach — propozycje ich nie uwzględniają”, a każdą
  propozycję i tak zatwierdza człowiek. Włączenie urlopów = wspólny sekret
  w Compassie i NEXUSIE (osobny krok).
- **Poza zakresem:** podkategorie. Tryb `auto` (automat przydziela sam, bez
  akceptacji) to decyzja Artura z wieczora 02.10.2026 — sekcja „`/jobs/new`
  w sześciu sekcjach”; opis propozycji wyżej dotyczy trybu `shadow`.
