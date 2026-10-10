# „Twoje CV w drodze” na pulpicie — domyślnie u każdego, z „Usuń z pulpitu” (02.10.2026)

Druga strona przekazań karty: dzwonek znika po kliknięciu, a rekruter nie miał
na pulpicie nic (panel „Czeka na Ciebie” pokazywał przegląd tylko DL-owi,
kolejkę tylko osobie od Cpro). Makieta: https://claude.ai/artifact/LaqZviMeU41VRcWX71bFMG.

- **Lista jest liczona przy odczycie, bez tabeli** (`services/cv_in_transit.py`,
  pole `cv_in_transit` w `GET /api/board-tasks`): najnowszy wiersz pary na
  opublikowanej rekrutacji + wiersz tuż przed nim, kolumny przez
  `board_column_for`. „Wróciło” (14 dni, znika po kolejnym ruchu): odrzucenie
  z `ended_by='delivery_lead'`, cofnięcie z „QC CV” do wcześniejszej kolumny
  przez kogoś innego, u Nordei zwrot z kolejki Cpro. „W przeglądzie” (30 dni):
  QC CV poza Nordeą albo kolejka Cpro. „Wysłane do klienta”: 7 dni.
- **„Moje” = rekruter kandydata** (`default_recruiter_ids`) **albo autor
  wiersza sprzed ruchu** — ta sama reguła odbiorcy co dzwonki przekazań. Własny
  ruch nie jest „wróciło”; wiersz, który DL ma w „Czeka na Twój przegląd”, nie
  dubluje się tutaj.
- **Nie jest kafelkiem siatki** (decyzja Artura 02.10.2026: każdy ma ją
  domyślnie, komu się nie podoba — usuwa). Stoi w panelu jako kolumna, a gdy
  panel jest pusty i nic nie wróciło — jako wąski pasek, także z pustym stanem
  („Nie masz teraz CV w drodze…”). „Usuń z pulpitu” zapisuje się na koncie:
  `user_dashboards.layout["hidden_panels"]`, `PUT /api/users/me/dashboard/panels/{panel}`
  (bez podbijania `version`); zapis kafelków MUSI ten klucz zachować
  (`save_my_dashboard`). Przywraca wiersz na górze katalogu „Dodaj kafelek”.
  Nowa lista tego rodzaju = wpis w `dashboard_tiles.PANEL_KEYS` i w
  `DashboardPanelKey` we froncie.
- **Awaria liczenia albo lista usunięta = `cv_in_transit: null`** i panel
  działa jak wcześniej (`load_safely`, savepoint). Do porannego dzwonka
  zbiorczego lista nie wchodzi; licznik przy nagłówku to tylko „wróciło”.
- Harness: `/preview/custom-dashboard` (stany „CV w drodze: pasek / pusto”).
