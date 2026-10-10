# Nowa rekrutacja = strona `/jobs/new` z requestu klienta (22.09.2026)

Decyzje Artura: tworzenie rekrutacji przenosimy z Traffita do NEXUSA (do
22.09 w NEXUSIE powstały 2 prawdziwe rekrutacje, ~100/mc szło z Traffita),
startem jest mail klienta, AI wypełnia minimum, DL sprawdza i jednym
kliknięciem „Utwórz i przekaż do searchu”. Okno `CreateJobModal` (9 pól)
USUNIĘTE — każde wejście („Dodaj” w pasku, lista, ⌘⇧J, „Skopiuj jako
template” → `/jobs/new?from=<id>`) prowadzi na stronę.

- **Odczyt przed zapisem:** `POST /api/job-intake/read` (tekst) i
  `/read-file` (.docx/.pdf/.txt) — `app/api/job_request_intake.py`,
  `DeliveryLeadPlus`, 20/min per osoba, prompt `JOB_REQUEST_INTAKE`,
  kwota `champion_draft`. Niczego nie zapisuje. Budżet liczy KOD
  (`champion_intake.document_rate` na dosłownym cytacie `rate_quote`), nie
  model; cytat spoza tekstu requestu jest odrzucany (także podświetlenia).
  Stawka dzienna/brutto/obca = `None` + notatka, nigdy przeliczenie.
- **Braki = lustro handoffu** (`job_readiness`): rola, must-have, budżet,
  tryb pracy (+ dni i miasto przy biurze/hybrydzie), opis projektu, 2 pytania
  screeningowe, wymagania do wyszukiwania w bazie (od 25.09.2026). Dwie kopie:
  `services/job_request_intake.missing_fields` i
  `lib/job-request-intake.ts::missingFor` — zmieniając bramkę handoffu,
  zmień obie.
- **Zapis to od 04.10.2026 JEDNO `POST /api/jobs`** (utworzenie + Champion +
  hiring manager + przekazanie + publikacja w jednej transakcji) — sekcja
  „Rekrutacja bez szkiców” niżej. Pole „Rekruter”: „Zaproponuje automat” =
  `assignment_mode: "automatic"` albo „Wybieram sam” z osobą (decyzje 29.09
  i 02.10.2026).
- **„Zaproponuje automat” czyta `GET /api/job-intake/handoff-options`**
  (`automatic_enabled` = `RECRUITMENT_ALLOCATION_ENABLED`, `mode` z
  `recruitment_allocation.effective_allocation_mode` — przy wyłączonej fladze
  `off`, inaczej zapisany tryb; ta sama funkcja liczy gotowość rekrutacji
  i odmowę 409 w handoffie) — rekrutacji jeszcze nie ma, więc
  `…/readiness` odpada. Flaga wyłączona ALBO tryb `off` = opcja widoczna,
  ale nieaktywna ze zdaniem o administratorze (w `off` automat nikogo nie
  zaproponuje). `shadow` tylko proponuje osobę (zatwierdza Head of
  Recruitment), `auto` ją przypisuje. Bez wyboru działa automat, gdy jest
  dostępny (`lib/recruiter-assignment.ts`).
- **Pola usunięte z tworzenia I ustawień** (TAC, szablon procesu,
  Program/Train, typ rekrutacji, widełki PLN/mies.; kategoria kompetencji
  wróciła 02.10.2026 — potwierdza ją Delivery Lead, sekcja „`/jobs/new`
  w sześciu sekcjach”):
  `EditJobModal` ich nie renderuje ani NIE WYSYŁA (PATCH czyta
  `model_fields_set`, więc dane w bazie zostają). Ustawia je backend. Nie
  przywracaj bez decyzji. **Priorytet wrócił 02.10.2026** w trzech poziomach
  (panel „Zespół” i `/jobs/new`) — sekcja „Role przy rekrutacji…”.
- **Wybór klienta w Rekrutacjach i Kontraktach = tylko „Aktywni” i „Relacyjni”**
  (ticket 30.09.2026): `GET /api/clients-lookup?contract_eligible=true`
  (`ClientSinglePicker selectableOnly`, `phase5Api.selectableClientsLookup`).
  Edycja rekrutacji dokłada bieżącego klienta, nawet nieaktywnego
  (`lib/client-selection.withCurrentClient`). Filtry list (`ClientMultiSelect`,
  `ContractsClientPicker`) zostają przy pełnej liście.
- Strona jest dla admina i Delivery Leada (`job.create` + rola), bo odczyt,
  Champion i handoff to `DeliveryLeadPlus`. Harness `/preview/new-job`
  (`?state=request|review|gaps`, zero zapytań).
- **Dni w biurze: „w tygodniu” albo „w miesiącu” (0407, 30.09.2026).**
  `jobs.onsite_days_per_month` i `basics.onsite_days_per_month` (1–22) trzymają
  wpis „raz w miesiącu”; wtedy `onsite_days_per_week` wylicza serwer
  (`services/office_days.py`, lustro `lib/office-days.ts`, wspólne przypadki
  `__fixtures__/office-days-cases.json`) i nigdy nie jest zerem — bramki,
  odcisk requestu i portale czytają WYŁĄCZNIE liczbę tygodniową, a zero
  czytałyby jak „biuro niewymagane”. Wpis tygodniowy czyści miesięczny,
  miesięcznie tylko przy hybrydzie (422 przy innym trybie). Pole miesięczne
  znika z JSONB Championa przy `None` — stare profile nie zmieniają kształtu.
  Kontrolka: `components/jobs/OfficeDaysField.tsx` (`/jobs/new`, edycja
  rekrutacji, sekcja 1 Championa).
- **Odczyt maila v8 (30.09.2026): must 1:1 ze słowami klienta** — ukrywają
  już tylko umiejętności krytyczne (wybiera DL), więc must nie jest okrajane
  do technologii, nie traci wersji i nie przechodzi do „Mile widziane”
  (`job_request_intake.normalize_must`: tylko duplikaty; pozycja językowa
  dodatkowo w polu języka; `MAX_MUST` 25). Pozycja nie jest cięta na 80.
  znaku (do 02.10.2026 zdanie kończyło się w pół słowa) — limit to
  `STACK_ITEM_MAX_CHARS`, cięcie na granicy słowa z „…”. Wersje odcina bramka. (v7 z 27.09
  robiła odwrotnie, bo wtedy każde must ukrywało.) Biuro to lista miast po polsku
  (`office_cities` → `jobs.location` „Warszawa, Gdańsk”; chipy w formularzu,
  `splitCities`/`joinCities`), a Champion nie uznaje listy miast ze słownika za
  „dwuznaczną” ani różnej pisowni tego samego miasta za konflikt z rekrutacją
  (`champion_intake.office_places`). Lata dziedziny większe niż lata ogółem
  (albo > 25) odpadają z uwagą. Portal dostaje pierwsze miasto.
