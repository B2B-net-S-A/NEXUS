# Rekrutacja v5 — 8 kolumn, strzałka „Przesuń dalej”, QC CV, firmowa kolejka Cpro (0361, 24.09.2026)

Decyzje Artura 23.09.2026, makiety https://claude.ai/artifact/CG4mBk9xcHZAn3y9jcmMeW,
kontrakt API `docs/recruitment-v5-contract.md`. Zastępuje przegląd DZ (0353),
osobę od Cpro per rekrutacja (0353) i kolejkę „Czeka na DZ” (0348).

- **8 kolumn:** Nowi · Screening · Zweryfikowany · QC CV · CV wysłane · Rozmowa
  u klienta · Umowa · Zatrudniony. Screening (kody `screening`/`prep_call`) to
  kolumna, nie odznaka. Etap „Przepuszczony przez DZ” / „QC CV” jest GOSPODARZEM
  kolumny `cv_qc` (mimo kodu `interview`), „Wysłać do Cpro” wpada do niej ze
  znacznikiem „W kolejce Cpro”. Migracja 0361 zmienia nazwę etapu w szablonach
  spoza Traffita na „QC CV”; szablon Traffita przepisuje nocny sync, więc reguła
  rozpoznaje obie nazwy (`is_qc_stage`, kind `"qc"`). Blokada 12 h i arkusz pytań
  obejmują Nowych i Screening (`CLAIM_COLUMNS`). Lustra: `board-stages.ts` ↔
  `board_stage_badges.py` na `board-stage-cases.json`; statystyki „Lejek po
  etapach” mają wiersze `screening`, `qc`, `cpro`.
- **Strzałka „→” na karcie + okno „Przesuń dalej”** (`MoveNextDialog`): wymagania
  następnej kolumny (i wszystkich pominiętych) liczy JEDNA reguła
  `services/move_requirements.py` (`GET /api/pipeline/move-requirements`), każdy
  brak ma przycisk, który go usuwa. Przeciągnięcie na sąsiednią kolumnę bez braków
  przesuwa od razu; skok, znany brak albo „CV wysłane” otwiera okno. Serwer
  wymusza wyłącznie bramkę QC, stawkę DL i debrief — reszta wymagań to podpowiedź.
- **QC CV zamiast DZ** (`services/cv_qc.py`, `api/cv_qc.py`, tabela `cv_qc_runs`).
  **Od 02.10.2026 blokują CZTERY sprawdzenia** (decyzja Artura; do tej daty
  blokowało siedem i QC przeszła 1 z 8 par, bo „każde must z maila klienta
  w CV” padało w 7 z 8): brak CV firmowego (`cv_present`), umiejętności
  krytyczne (`critical_skills` — w CV i OPISANE zdaniem ≥ 6 słów, nie listą
  technologii, w każdej roli, w której oryginał je wymienia), nic must/nice
  spoza oryginału i notatek (`no_unsupported`), reguły klienta (bez stawek
  i kontaktu, zrzut zgody RODO). Uwagi, które NIE blokują: pozostałe must w CV
  i w rolach, pogrubienia must i nice, lata w nagłówku, daty ról, pisownia,
  tytuł, pogrubienia spoza oryginału (CV EN z oryginału PL pogrubia
  tłumaczenia). Nie przenoś uwag z powrotem do blokad bez decyzji.
  `blocking_failed` liczy RZECZY do poprawy (różne wymagania), lustro
  `blockingTasks` w `lib/cv-qc.ts` — chip na Tablicy, okno i 409 podają tę samą
  liczbę. Wymaganie z wersją („Spring Boot 3.4+”) szuka nazwy bez wersji
  (`dz_review._without_version`), a wersja wpisana wprost w CV bez pokrycia
  w oryginale dalej blokuje. Klauzula RODO to osobny blok (`section: "rodo"`,
  `cv_rodo_clause.is_rodo_text`), nie część ostatniej roli i nie treść CV:
  wymagań w niej nie szukamy, a kropka z przodu nazwy zostaje („.NET” bez
  kropki trafiało w „B2B.net S.A.” z klauzuli — fałszywa blokada i fałszywe
  zaliczenie krytycznej). Krytyczne wymaganie QC czyta nazwami bramki
  wyszukiwania (`gate_requirement(label).options`): „Bazy danych (Oracle,
  PostgreSQL)” spełnia którakolwiek z nazw. Blokujące liczy KOD;
  Luna tylko proponuje zdania z cytatem źródła (serwer odrzuca propozycję bez
  cytatu obecnego w oryginale/notatkach), rekruter klika „Zastosuj”. Poprawki
  edytują szkic CV firmowego pary; CV spoza NEXUSA (Word/PDF „…B2B…”) = 409
  `CV_NOT_EDITABLE`. Okno (`CvQcDialog`): „Co sprawdza QC” z nazwami krytycznych
  i ich źródłem, „Do poprawy przed wysłaniem” (karta na wymaganie z przyciskiem
  naprawy), „Warto poprawić — nie blokuje”, „W porządku”, w stopce „Przesuń
  dalej” (ten sam ruch co strzałka na karcie, `handleQcMoveNext`).
- **Bramka:** `/move` i `/bulk-move` na „CV wysłane” albo etap Cpro z kolumn
  przed wysłaniem → 409 `CV_QC_FAILED` (z `stage_id` do otwarcia QC), chyba że QC
  przechodzi albo Delivery Lead/admin przepuścił parę z powodem
  (`QcOverrideDialog`: cztery gotowe powody, opis wymagany tylko przy „Inny
  powód”, bez minimum znaków — przy minimum 10 znaków powodem bywał ciąg
  losowych liter; lustro `cv_qc.OVERRIDE_REASONS` ↔ `QC_OVERRIDE_REASONS`;
  `Activity cv_qc_override` z `reason_code`, ważne dla pary także po zmianie
  CV). Wyłącznik
  `CV_QC_GATE_ENABLED`; w testach wyłączony autouse-fixturą (dziesiątki testów
  przesuwa na „CV wysłane” bez CV firmowego). U Nordei ta sama bramka pilnuje, że
  na „Wysłane do Cpro” przesuwa osoba od Cpro, admin, DL albo HoR.
- **Osoba od Cpro = jedna na firmę** (`services/cpro_sender.py`,
  `app_settings['cpro_sender']`): ustawia WYŁĄCZNIE admin albo Delivery Lead
  przypisany do klienta Nordei (`cpro_sender.can_set_sender`, decyzja Artura
  25.09.2026 — do tego dnia zmieniał każdy, a osoba od Cpro widzi stawki do
  klienta w kolejce, więc rekruter mógł sam się ustawić i je zobaczyć),
  opcjonalnie z datą „do kiedy” — po niej wraca poprzednia osoba. Nieaktywne
  konto (także po zastępstwie) liczy się jak „nikt nie ustawiony”.
  `GET/PUT /api/board-tasks/cpro/sender`, kolejka pogrupowana po rekrutacji
  `GET /api/board-tasks/cpro/queue` (`CproQueueDialog` na pulpicie: rekrutacja po
  rekrutacji, „✓ Wrzucone” = zwykły `/move`). `jobs.cpro_sender_id` zostaje w bazie
  jako zapas, pasek „Do Cpro wysyła” nad Tablicą usunięty.
- **Przegląd DL** = osoby w kolumnie QC CV u klientów innych niż Nordea (z wynikiem
  QC), nie osoby w „Zweryfikowanym”.
- **Kto widzi „Czeka na Ciebie” (decyzja Artura 24.09.2026, `board_tasks._sees_*`):**
  obie listy Cpro — wyłącznie osoba od Cpro (gdy nikt nie jest ustawiony: listę
  „do wrzucenia” widzi admin i HoR, bo tylko tam da się kogoś ustawić; DL nigdy);
  przegląd DL — wyłącznie Delivery Lead rekrutacji (`jobs.delivery_lead_id`
  wygrywa, bez niego portfel klienta); admin i HoR go nie widzą. Poranny skrót
  liczy tą samą regułą.
- **Rekrutacja bez DL-a dostaje głównego DL-a klienta**
  (`services/job_delivery_lead_fill.py`, 24.09.2026): tylko `draft`/`published`,
  główny DL (`is_head`, aktywny). DL wpisany ręcznie nigdy nie jest nadpisywany;
  DL wpisany przez automat (`jobs.delivery_lead_auto_filled`, 0376 — fill i POST
  z głównym DL-em klienta) idzie za zmianą głównego DL-a, a ręczna zmiana
  w PATCH zeruje znacznik. Nieaktywny DL rekrutacji = brak DL-a: przegląd DL idzie
  do portfela klienta, alert DL-owy do HoR. Woła ją start
  aplikacji, faza `jobs` importu Traffita i przypisanie/zmiana głównego DL-a
  klienta. Zamkniętych nie rusza — statystyki DL liczą je przez tego samego
  głównego DL-a. Skutek: alerty DL-owe tych rekrutacji idą do DL-a, nie do HoR.
- **„Dodaj kandydatów”** (`AddCandidatesPanel`): jedno wejście z nagłówka i z kolumny
  Nowi, zakładki wyszukiwanie AI z Championa · propozycje · Moi ludzie · ręcznie.
  *(Od 02.10.2026 okno „Kandydaci do dodania” z czterema źródłami, otwierane
  z kafli nad Tablicą — sekcja „Prostszy ekran rekrutacji”.)*
