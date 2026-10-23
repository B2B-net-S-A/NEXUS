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
- **„W przeglądzie” mówi, czyj jest ruch (13.10.2026):** wiersz niesie stan QC
  i czas od gotowości. Przy QC do poprawy albo niesprawdzonym ruch jest
  rekrutera („… — Twój ruch”); gdy CV jest gotowe i czeka 2+ dni robocze,
  rekruter ma „Przypomnij” (dzwonek do Delivery Leada, raz dziennie). Imię
  Delivery Leada stoi także wtedy, gdy przegląd idzie do portfela klienta —
  `rekrutacja-tablica/do-wyslania-do-klienta-kolejka-delivery-leada.md`.
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
- **Odrzucenie przez DL to informacja, nie CV do poprawy (23.10.2026,
  zgłoszenie rekruterki):** poranny mail wrzucał je do „CV wróciło do poprawy”
  codziennie przez 14 dni, bo zamknięta karta już się nie rusza. Teraz
  `returned_to_fix_total` (`RETURNED_TO_FIX_KINDS`: cofnięte z „QC CV”, zwrot
  z Cpro) liczy sekcję maila, licznik przy nagłówku i „Twój ruch” na pulpicie.
  Wiersz odrzucenia zostaje na liście pod własnym nagłówkiem „Odrzucone przez
  DL”; samo odrzucenie stawia listę w „U innych”.
- Harness: `/preview/custom-dashboard` (stany „CV w drodze: pasek / pusto”).
- **Ikona „CV” w górnym pasku (16.10.2026, bez dzwonka)** czyta tę listę
  bezpośrednio (`load_for_user`, nie `load_safely` — usunięcie panelu
  z pulpitu nie chowa ikony): `GET /api/board-tasks/cv`
  (`services/cv_topic.py`). Rekruter: „do sprawdzenia” (auto-CV z
  `cv_auto_review.needs_review_clause`, zrobione po ruchu tej osoby, karta
  wciąż na etapie, który je zamówił, 14 dni), „do poprawy” (wróciło z „QC CV”
  albo z kolejki Cpro + „QC CV” z niezdanym QC), „u Delivery Leada” (QC
  zdane, przepuszczone albo liczone; kolejka Cpro), „wysłane”. Odrzucenie
  przez DL nie jest CV do poprawy. Delivery Lead: ta sama kolejka co
  `/dl-send` (`_dl_send_payload` — jedna funkcja dla pigułki i ikony),
  „u rekruterów” (sama liczba) i CV wysłane dziś (północ firmy) w jego
  rekrutacjach. Liczba na ikonie = do sprawdzenia + do poprawy + do wysłania.
  Zapytanie listy kosztuje ~50 ms (prod 16.10.2026, 3 481 par z 30 dni).
