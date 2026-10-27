# „Match” — Delivery Lead wysyła osobę od razu do innych swoich rekrutacji (22.10.2026)
<!-- indeks: „Pasuje też do Twoich rekrutacji” w przeglądzie DL, „Wyślij też do…”, portfel DL, połączone zaznaczone, „+ Dodaj inną rekrutację” (cała firma), Nordea → Cpro, „w tym Match” -->

Zgłoszenie Artura 22.10.2026 (rozmowa z Marcinem i Olafem): Delivery Leadzi sami
przepinają polecone osoby do innych requestów swoich klientów, bo rekruterzy tego
nie robią. Pomiar z produkcji (12–22.10): 150 razy osoba wysłana do klienta
w ostatnich 30 dniach trafiła do innej rekrutacji tego klienta, średnio po
11–15 dniach, a tylko 42 doszły tam do „CV wysłane”. Makiety (warianty
rekomendowane przyjęte): https://claude.ai/artifact/HTjysWg2TjaDvxvCtjd1RV.
Fundament: `dl-przesuwa-bez-blokad.md` (#2581) i „Sam przekazał” (#2582).

- **Gdzie.** Sekcja „Pasuje też do Twoich rekrutacji” w przeglądzie DL-a
  (`dl-review/DlMatchSection.tsx` w `DlReviewPanel`) i okno „Wyślij też do…”
  z menu „⋯” panelu osoby na etapach od „CV wysłane” do negocjacji
  (`DlMatchDialog`, `SEND_ALSO_STAGES` w `PipelineCandidateDock`). Widzi je tylko
  osoba z uprawnieniem wysyłki CV (`recruitment_manage`, trasy z
  `RecruitmentManageUser`). Rekruter ma dalej „Pasuje też do → + Dodaj” do „Nowych”.
- **Lista** (`GET /api/dl-match/candidates/{id}?from_job_id=`,
  `services/dl_match.suggestions`): ocena „Pasuje też do” (`also_fits`, ≥ 70,
  zmierzona, dozwolona — weto HM i czarna lista odpadają), najwyżej 5, tylko
  **portfel DL-a**: rekrutacje, w których jest DL-em, i klienci z
  `delivery_lead_client_assignments` (`portfolio_clause`; admin bez roli DL —
  bez zawężenia). **Rekrutacje połączone z A** („Podobne rekrutacje”,
  `job_similar_links`) są zawsze na liście i **zaznaczone** — to wariant
  „Wysyłaj razem = zaznacza w przeglądzie”; nic nie idzie do klienta bez
  kliknięcia DL-a. Reszta czeka niezaznaczona. Awaria Qdranta: `status:
  unavailable`, połączone zostają. Pod listą „już jest: <kolumna>” dla
  rekrutacji z portfela, w których osoba ma kartę w toku. Sekcja jest widoczna
  także przy pustej liście — zawsze ma „+ Dodaj inną rekrutację”.
- **„+ Dodaj inną rekrutację”** (prośba Igora, decyzja Artura 27.10.2026,
  makiety https://claude.ai/artifact/KDADjkrPBTT2ztuybznuJ8): DL sam wskazuje
  rekrutację, której ocena nie podsunęła. `GET /api/dl-match/candidates/{id}/search?from_job_id=&q=`
  (`services/dl_match.search_targets`): **wszystkie otwarte rekrutacje firmy**
  (opublikowane, w pracy, bez wiersza tej osoby), nie tylko portfel; portfel
  na górze, przy cudzej `in_portfolio = false` i imię jej DL-a. Szuka po
  nazwie, numerze u klienta, kliencie (bez polskich znaków) i id, od 2 znaków,
  do 8 wyników, **bez oceny dopasowania** (decyzja: DL wie, czemu dodaje).
  Wiersz wchodzi zaznaczony, z „dodana przez Ciebie” i „× usuń”; reszta jak
  przy podsuniętych. Lista podpowiedzi zostaje w portfelu. Proces w cudzej
  rekrutacji zalicza się **wysyłającemu** DL-owi, nie DL-owi tamtej
  rekrutacji (decyzja Artura 27.10.2026) — ten dostaje dzwonek.
- **Wysyłka** (`POST /api/dl-match/send`, `api/dl_match.py`): osoba musi być
  w A po „Zweryfikowany” (inaczej 422). Rekrutacja B musi być otwarta i bez
  tej osoby — od 27.10.2026 **bez warunku portfela** (rekrutacje są dla DL-a
  org-wide, `uprawnienia/rekrutacje-i-kandydatow-widza-wszyscy-stawki-do.md`).
  Każda rekrutacja B osobno, wynik per rekrutacja (`sent` / `verified_only` / `failed`):
  1. dodanie jako przepięcie z A — `add_candidates_to_job(...,
     reassign_from_job_id=A)`: kopia CV etapu (`stage_cv_copy`), `entry_source
     = reassign`, ślad `entry_meta = {"via": "dl_match", "from_job_id": A}`,
     bez rezerwacji 12 h, z bramkami dodania (weto, czarna lista, off-limits
     pomija przepięcie jak dotąd);
  2. ruch na „Zweryfikowany” przez DL-a ze stawką kandydata z A — DL omija
     bramki pól, więc `credit_user_id` = DL i proces liczy się do „Sam przekazał”;
  3. osobna transakcja: ruch na „CV wysłane”, a u Nordei na etap Cpro (kolejka
     osoby od Cpro, jej dzwonek z `run_move_effects`), ze stawką do klienta
     z wiersza — zwykłe `apply_move`, te same bramki co przegląd;
  4. QC odmawia (`CV_QC_FAILED`) → obejście DL-a jak „Wyślij mimo to”
     (`cv_qc.record_override`, powód „Match z …”), zatwierdzone PRZED drugim
     ruchem — QC liczy przebieg we własnej sesji i nie może czekać na blokady
     dodania. Dlatego kroki 1–2 i 3 to osobne transakcje: gdy wysyłka do B nie
     przejdzie, osoba zostaje w B na „Zweryfikowanym” (`verified_only`).
  Nigdy `db.rollback()` na sesji żądania — kroki w savepointach (rollback
  wygasza `current_user` dla kolejnych rekrutacji).
- **Przegląd DL:** Match rusza dopiero po udanej akceptacji w A (ten sam
  przycisk: „Akceptuj — wysyłam do N rekrutacji”, u Nordei „do Cpro i do N
  innych”). Stawka w wierszu podpowiada się z głównej decyzji; zaznaczona
  rekrutacja bez stawki wstrzymuje przycisk. Komunikat podsumowuje wysłane,
  kolejkę Cpro, przepuszczone QC i każdą odmowę słowami serwera.
- **Dzwonki** (typ `stage_changed`, encja = wiersz etapu, żeby dobowy dedup nie
  zjadał drugiej rekrutacji): prowadzący B i DL rekrutacji B (gdy to nie
  wysyłający — ważne przy cudzej rekrutacji) — „<DL> wysłał(a) <osoba> do
  klienta — Match z <A>”; rekruter z A (pierwszy weryfikujący, bez niego prowadzący A,
  nigdy sam DL) — „Daj znać: … poszła też do N rekrutacji” z listą. To prośba,
  nie blokada (decyzja: zadanie dla rekrutera z A); osobnej tabeli zadań nie ma.
- **Statystyki:** „Sam przekazał” bez zmian w liczeniu; w faktach panelu celów
  DL-a dochodzi „Sam przekazał: w tym Match” (`kpi_panel.month_match_handoffs`:
  procesy z `entry_meta.via = dl_match` zaliczone DL-owi i otwarte w tym
  miesiącu; przy zerze linia znika). Premia — jedna, DL-a (#2581, D4).
- **Czego nie ma:** plakietki „Pasuje też do N” na kartach Tablicy (każda karta
  to zapytanie wektorowe + ocena kilku rekrutacji) i przełącznika trybu
  połączenia — połączenie zawsze tylko zaznacza w przeglądzie.
- Harness: `/preview/dl-review?layout=panel` (lista Match z fikcyjnymi danymi),
  `/preview/pipeline-v4?as=dl` → osoba w „CV wysłane” → „⋯” → „Wyślij też do…”.
