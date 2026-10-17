# Opieka, mapa technologii, ATLAS, administracja@ (16.10.2026)

## Opieka (`app/services/care/*`, zakładka „Opieka” kontraktu, `/care`)

- Zakres klientów = zakres Delivery (`access_scope.resolve_delivery_lead_client_ids`):
  DL u swoich klientów, admin, Finanse i TCM u wszystkich. Cudzy klient → 403.
- Opiekun kontraktu: pole kontraktu, gdy puste — domyślny opiekun klienta,
  gdy i tego brak — Delivery Lead kontraktu.
- Plan kontaktów od startu kontraktu: dzień 7, 30, 90, potem co kwartał oraz
  30 dni przed końcem zamówienia albo umowy. Przy pierwszym włączeniu modułu
  stare kontrakty nie dostają zaległości sprzed okna — to historia sprzed modułu.
- Rozmowa zamyka punkt planu. Okno mówi „Bez danych o zdrowiu i bez stawek”
  i tak ma zostać. Sygnały „ryzyko odejścia” i „chce zmiany projektu” trafiają do
  kolejki „Do przepięcia”; „klient zatrudnia” to sygnał popytu.
- Dzienny przebieg (`care/reminders.py`): zaległy albo dzisiejszy kontakt
  (punkt planu albo follow-up z rozmowy) → `care_contact_due` (sekcja Delivery) do
  opiekuna, najwyżej raz na 7 dni na kontrakt; koniec projektu < 60 dni → wpis
  „Do przepięcia”.

## Struktura u klienta i opinie klienta (etap 2, D8–D11, 17.10.2026)

Zakładka klienta „Struktura u klienta” (`components/care/ClientPeopleTab.tsx`,
`GET /api/care/clients/{id}/org`, serwis `care/client_people.py`).

- **Drzewo**: działy klienta → osoby klienta z wcięciem po „Podlega pod” → pod
  osobą nasi konsultanci, których jest menedżerem u klienta
  (`contracts.client_pm_contact_id`, reguły pola w
  `docs/claude/kontrakty/kontakt-do-konsultanta-na-umowie.md`): kandydat, rola,
  koniec zamówienia (ta sama data co w planie opieki), ostatnia opinia. Przy
  osobie znaczniki: menedżer naszych, HM (hiring manager w rekrutacjach
  klienta), decydent. Kontakt bez działu → „Bez działu”, konsultant bez
  menedżera → „Bez wskazanego menedżera” z podpowiedzią z tekstu Line Manager/PM
  i „Wskaż menedżera” (prowadzi do kontraktu). Często menedżer to NIE hiring
  manager — dlatego dwa osobne znaczniki.
- **Działy to `client_areas`** („Działy i obszary”, ten sam słownik co mapa
  technologii). Kontakt: `contacts.client_area_id` i
  `contacts.reports_to_contact_id` — kolumny dołożone w `contract_care_schema`,
  czytane przez `CONTACTS_ORG` (nie pola modelu `Contact`: awaria DDL modułu
  kładzie wtedy ekrany opieki, a nie każdy odczyt kontaktu). Tekst
  `contacts.department` zostaje; panel osoby podpowiada „Przypisz: X” albo
  „Dodaj dział „X””, nic nie przypisuje się samo.
- **„Podlega pod” i dział zapisuje** `PATCH /api/care/clients/{id}/contacts/{contact_id}`
  (`reports_to_contact_id`, `client_area_id` albo `new_area_name`) — ta sama
  reguła co edycja kontaktów (`ClientAccess.can_edit_contacts`: uprawnienie
  „Klienci: dodawanie i edycja” w zakresie klienta). Przełożony tylko z tego
  klienta, bez pętli (422 z nazwiskami), zapis pod blokadą doradczą klienta.
  `POST …/areas` zostaje przy bramce opieki (TCM zakłada obszary w kartach).
- **Opinia klienta** = rozmowa z menedżerem zapisana przez opiekuna albo DL
  po telefonie, spotkaniu czy mailu (`POST /api/care/clients/{id}/feedback`,
  tabele `client_feedback_sessions` + `client_feedback_scores`): oceny 1–5
  jakości pracy, komunikacji i samodzielności per konsultant, „pomiń” = brak
  wiersza, „Przedłużenie” (tak / raczej tak / nie wiem / nie), notatka do 2000
  znaków. Kontakt i kontrakty muszą być TEGO klienta (422). Formularza
  wysyłanego do klienta nie ma (D10 — to wysyłka do ludzi z zewnątrz, tylko za
  zgodą Artura). Okno mówi „Konsultant tej opinii nie widzi. Bez danych
  o zdrowiu i bez stawek.” — walidacji treści nie ma, jak w rozmowach opieki.
  Historia opinii o konsultancie: zakładka „Opieka” kontraktu
  (`GET /api/care/contracts/{id}/feedback`).
- **Kto widzi (D11)**: opiekun (DL w swoim portfelu, TCM, admin) i Head of
  Recruitment — bramka `require_hr_client_people_reader` (Delivery albo
  Pozyskiwanie + rola z listy). Finanse i Kadry z samego uprawnienia: 403.
  Konsultant nie. Zapis opinii: piszący opiekę (DL, TCM, admin), HoR tylko czyta.
- **Prośba o opinię (D9)** liczona przy odczycie (`feedback_requests`):
  menedżer ma prośbę, gdy któryś jego konsultant kończy współpracę w ciągu
  30 dni, a od początku tego okna nie było rozmowy z menedżerem, albo gdy od
  ostatniej rozmowy minął kwartał (90 dni; bez rozmowy — od startu pierwszego
  konsultanta). Jedna pozycja na menedżera ze wszystkimi jego konsultantami,
  z `owner_ids` (opiekunowie) dla listy „Opieka · Ten tydzień”;
  `GET /api/care/feedback-requests?scope=mine` daje opiekunowi jego prośby,
  a Delivery Leadowi wszystkie z portfela.
- **Scalanie**: duplikat kontraktu — oceny idą za zachowanym, dwie oceny tej
  samej rozmowy łączą się w jedną (`contract_merge`); duplikat kontaktu —
  podwładni, dział i opinie przechodzą na zachowany, pętla jest przerywana na
  jego „Podlega pod” (`contact_duplicate_merge.merge_org`).

## Karta technologiczna i słownik (D7)

- Jeden słownik dla wymagań rekrutacji, profili i mapy klienta: tabela `skills`
  z aliasami. Nazwa wpisana tekstem, której słownik nie zna, idzie do
  `skill_review_queue` (jeden wiersz na nazwę), a na karcie zostaje tekstem do
  decyzji: „Zmapuj” (alias), „Dodaj do słownika”, „Odrzuć”. Decyzje zmieniają
  słownik całej aplikacji, więc podejmują je ci, którzy prowadzą „Słownik
  umiejętności”, przez `skill_curation` z tymi samymi kontrolami konfliktów.
- W polu technologii lista po odpowiedzi słownika pokazuje „Dodaj „…” · do
  przejrzenia”, gdy nie ma dokładnego trafienia (Enter robi to samo).

## Mapa technologii klienta (zakładka „Technologie”)

- Liczona przy odczycie z czterech źródeł: T — karty technologiczne, R —
  rekrutacje klienta z 12 miesięcy (wymagania „musi” i „mile widziane”), K — nasi
  konsultanci z aktywnymi kontraktami, N — notatki o stacku (`client_knowledge`,
  kategoria `tech_stack`). Wyszarzone = brak źródła z ostatnich 18 miesięcy.
- Mapa niczego nie zgaduje: technologia pojawia się tylko, gdy źródło wskazuje
  umiejętność ze słownika. Cache single-flight `care:techmap:<klient>:`
  unieważniany przy zapisie karty, rozmowy i notatki.
- „Nowa rekrutacja z tej mapy” otwiera `/jobs/new?client=<id>` — ustawia klienta,
  o ile nikt go nie wybrał; `?from=` (kopia rekrutacji) ma pierwszeństwo.
- `clients.default_care_owner_user_id` i `clients.equipment_provider` stoją
  w bocznym panelu zakładki.

## ATLAS (sygnały sprzedażowe)

- `GET /api/care/atlas/sales-signals` i `POST …/status` zastępują
  `/api/internal/sales-signals` Compassa. Zakresy kluczy `sales_signals:read`
  i `sales_signals:write`. Sygnał = sfinalizowana karta z „klient zatrudnia”;
  ATLAS bierze pełny zbiór i uzgadnia u siebie. Bez stawek i bez e-maila
  konsultanta. Przepięcie ATLASA z Compassa na NEXUS to krok przełączenia
  i wymaga zgody Artura.

## Sprawy administracja@ (`app/services/admin_cases/*`, `/people/cases`)

- Czytnik skrzynki: app-only Graph (wzorzec `order_mail_ingest`), wyłączony, gdy
  `ADMIN_CASES_MAILBOX` pusty, `ADMIN_CASES_MAIL_INGEST_ENABLED ≠ true` albo moduł
  `cases` wyłączony. Potrzebuje tokenu rejestracji HR — rejestracja zamówień ma
  politykę tylko na skrzynkę zamówień.
- Nowa wiadomość = nowa sprawa; odpowiedź w wątku = ta sama sprawa (najpierw
  `conversationId`, potem `In-Reply-To`/`References`) i ponowne otwarcie sprawy
  zamkniętej. Compass zakładał sprawę z każdej odpowiedzi — tego nie powtarzamy.
  Idempotentnie po `graph_message_id`; załączniki tylko jako metadane. Po pełnej
  paczce (`MAX_MESSAGES_PER_RUN`) następny przebieg czyta dalej bez nakładki
  (`stats['resume_from']`), żeby zepsuta wiadomość nie zatrzymała nowszych.
- Haki: nowy kontrakt → „Wejście konsultanta: …”, odejście pracownika →
  „Odejście: …”; idempotentne po `source_key`, nie commitują. Przy wyłączonym
  module nic nie zakładają — do przełączenia sprawy prowadzi Compass. Trwałe
  usunięcie kontraktu zamyka jego sprawę wejścia (savepoint — awaria spraw nie
  blokuje usunięcia).
- Zakładkę „Sprawy” widzi uprawnienie „Sprawy”, admin i osoba przypisana do sprawy.
- Przypisanie sprawy innej osobie (`admin_case_assigned`) to dymek i mail „Czas
  i ludzie” z linkiem `/people/cases/{id}`. Tytuł sprawy (temat cudzego maila)
  do maila nie idzie — mail mówi tylko, że sprawa czeka. Zakładka „Sprawy” ma
  licznik otwartych spraw przypisanych do czytającego (`GET /api/hr/counts`).
