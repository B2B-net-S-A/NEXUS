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
- **Kategorie ludzi**: Ustawienia → Zespół i dostęp → „Kategorie
  kompetencji” (`/settings/competence-team`, `api/competence_team.py`,
  admin/HoR). 1. priorytet jeden na osobę (częściowy UNIQUE), zdjęcie głównej
  jest dozwolone (stare trasy `/api/team-structure/sourcer-categories` tego nie
  pozwalały i zostały nietknięte). `users.allocation_excluded` = „Poza
  przydziałem”. Zasady (próg bazy dla sourcera, godzina przeglądu) w
  `app_settings['request_allocation_rules']`. Przypisania ze screena:
  `scripts/seed_competence_team_2026_09.py` (same id kont).
- **Automat**: czysty planer `services/request_allocation_plan.py` (testy
  bez bazy) + zapis `services/request_allocation.py`, wołany z
  `run_allocation_sweep` w miejsce `allocate_pending`. Pula = published +
  `searching` + bez championa. Kolejność: nikt nie wysłany → 1–2 → 3+, potem
  termin. ≥ próg pasujących w bazie (otwarte propozycje, tylko gdy był nocny
  przegląd) → sourcer, inaczej rekruter. 1. priorytet → 2. → inni; przelew do
  innej kategorii, gdy własna grupa ma o >1 więcej niż minimum zespołu.
  **Nie przerzuca działających przypisań**; zwalnia tylko przy wyjściu
  requestu z puli albo niedostępności osoby (auto, bez kandydatów w toku).
  Ręczne przypisania nie są zwalniane za urlop. Tryby
  `recruitment_allocation_state.mode`: `shadow` → `proposed` (pulpit pokazuje
  przerywaną ramką), `auto` → `active` + pierwszy rekruter jako
  `jobs.recruiter_id`, jeśli puste. Bez świeżych urlopów z Compassa `auto`
  nie przydziela nowych (shadow proponuje dalej). Pętla działa dopiero przy
  `RECRUITMENT_ALLOCATION_ENABLED=true`.
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
