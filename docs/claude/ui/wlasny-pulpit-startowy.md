# Własny pulpit startowy (0337, 21.09.2026)

`/dashboard` to od 21.09.2026 pulpit, który każdy układa sam z kafelków
(decyzje Artura: start od PUSTEGO pulpitu z poleceniami dla roli, katalog
gotowych kafelków + kreator własnej metryki, siatka 12 kolumn z przeciąganiem
i zmianą rozmiaru, JEDEN pulpit na osobę, stare presety ról usunięte od razu,
finanse w kreatorze od razu). Raport: `docs/custom-dashboard-completion-report.md`.

- **Układ = `user_dashboards` (0337)**, jeden wiersz na osobę, `layout` JSONB +
  `version`. `GET/PUT /api/users/me/dashboard`; PUT wymaga `expected_version`
  (409 `DASHBOARD_VERSION_CONFLICT` = inna karta zapisała wcześniej). Kształt
  pilnuje `services/dashboard_tiles.py` — ściśle przy zapisie (422 po polsku),
  łagodnie przy odczycie (nieznany typ odpada do `dropped_tiles`, pulpit się
  otwiera). Linki w notatce: tylko `https://` i ścieżki `/…` (XSS).
- **Nowy kafelek = cztery miejsca:** `TileType` (backend), `TILE_TYPES`
  (`lib/api/userDashboard.ts`), definicja w `lib/dashboard-tiles/catalog.ts`
  i `case` w `components/v2/dashboard/custom/TileContent.tsx`. Pierwsze dwa
  pilnuje `test_dashboard_tile_types_mirror.py`.
- **Gotowe kafelki to widżety ze starego pulpitu ról OPAKOWANE, nie przepisane**
  (każdy sam pobiera dane i ma swoje bramki). Dostępność w katalogu jest lustrem
  dawnych bramek `RoleDashboard` (sekcja, nie sama rola). `PriorityWorkIsMounted`
  pilnuje, że Priority Work ma wejście z katalogu.
- **Kreator metryki: `POST /api/dashboard-metrics/evaluate`** (POST tylko do
  odczytu — w `READ_ONLY_POST_ROUTE_TEMPLATES`; limit 60/min per użytkownik;
  katalog źródeł `GET /catalog`). Definicja deklaratywna
  (`services/custom_metrics/definition.py`) — zamknięte słowniki miar,
  podziałów i filtrów per źródło, zero SQL od użytkownika. **Uprawnienia liczone
  przy KAŻDYM zapytaniu** (`engine.py`): sekcja źródła
  (`section_access_for_user`), „czyje dane” z `resolve_dashboard_scope`
  (self → tylko „moje”, recruitment_org → + zespół, delivery_clients/organization
  → + cała firma). Za szeroka prośba = 403 `metric_scope_denied` ze zdaniem —
  kafelek mówi „Brak dostępu”, nigdy nie pokazuje zera.
- **Ruchy w pipeline liczą WYŁĄCZNIE kamienie milowe z
  `analytics_first_milestones`** (reguła D2, jak Insights) — inne etapy świadomie
  poza kreatorem, bo surowe `candidate_stages` dubluje powroty na etap.
- **Kwoty = `insights_board_money.fold_money`** (ta sama funkcja co kafle Rady),
  kontrakty z `RATE_SCHEDULE_LOADS`. Redakcja całościowa: Finanse/admin — wszyscy
  klienci; Delivery Lead — wyłącznie klienci z
  `resolve_delivery_lead_finance_client_ids`; klient spoza portfela w filtrze =
  odmowa całości, nie częściowa suma. Wynik niesie notę o młodszej ewidencji
  kontraktów.
- **Zapis na froncie:** menu kafelka i dodanie z katalogu zapisują od razu;
  przeciąganie/rozmiar pracują na szkicu z „Cofnij” i idą jednym PUT po
  „Zapisz układ”. Na telefonie (< 768 px) lista w kolejności wiersz→kolumna,
  bez edycji układu.
- **`/dashboard#nadzor-kontaktu`** (link alertów SLA z `dashboard_v2.py`)
  pokazuje panel nadzoru tymczasowo, gdy ktoś nie ma tego kafelka, z „Dodaj na
  stałe”. `?preset=` jest ignorowane; `dashboardHref()` zawsze zwraca `/dashboard`.
- **Pulpit według ról (04.10.2026, przegląd: https://claude.ai/artifact/3etak5SPHM2ShQCRCj3e8P).**
  Po dwóch tygodniach 29 z 35 kont miało pusty pulpit, a „Czeka na Ciebie” u
  rekruterów, TCM i DL pokazywało 0 zadań przy ponad tysiącu osób w Ogłoszeniach.
  - **Konto bez zapisanego układu widzi układ roli** (`lib/dashboard-tiles/role-layouts.ts`,
    `ROLE_LAYOUTS`; konto wielorolowe = suma w kolejności admin › finance › HoR ›
    DL › TCM › rekruter, jedna tablica requestów, Head/admin bez kafelków pracy
    rekrutera). Serwer mówi to polem `uses_role_layout` (`GET /users/me/dashboard`).
    Pierwsza zmiana (usuń, dodaj, „Dostosuj pulpit”) zapisuje układ jako własny.
    Zapis PUSTEJ listy stawia `layout.role_layout_off` — wtedy dopiero pusta
    karta z poleceniami. Flaga i `hidden_panels` żyją obok kafelków; zapis kafelków
    nie może ich gubić. „Przywróć układ roli” w trybie edycji.
  - **„Requesty i obłożenie” ma zakres** (`TileConfig.board_scope`: `all` /
    `my_category` / `my_lead`, tylko przy `request_board`): filtry startowe
    z `viewer` odpowiedzi `/api/request-board`, parametry `rb_*` w adresie
    wygrywają. **„Na daily” = `/jobs/daily`** (ten sam `RequestBoardView`,
    wariant `daily`: „Zmiany od wczoraj” na górze, kategorie po kolei). Okno
    zmian liczy się od tej samej godziny poprzedniego DNIA ROBOCZEGO
    (`request_allocation.changed_since` — w poniedziałek od piątku).
  - Nowe kafelki: `today_cycle` „Dziś” (cykl rozmów u klienta), `team_signals`
    „Gdzie stoi” (`/api/insights/team/attention` + `no_one_sent`, `overdue`,
    `stale_postings`), `system_status` (admin, `/api/health`; `unknown` ≠ OK),
    `my_week` (`/api/kpis/me/panel`).
  - **„Moje zadania” liczy tylko powiadomienia z 7 dni**; jednorazowo
    (`services/notification_backlog_repair.py`, blok `repair-notification-backlog`)
    nieprzeczytane „etap stoi 6 h / 7 dni”, „coach KPI” i PowerCalling starsze
    niż 14 dni oznaczono jako przeczytane (decyzja Artura 04.10.2026, nic nie
    skasowano; paragon `notification_backlog_read_2026_10` = liczby per typ).
- Harness: `/preview/custom-dashboard` (pusty i pełny pulpit, zero zapytań).
