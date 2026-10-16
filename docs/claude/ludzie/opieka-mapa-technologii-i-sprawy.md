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
  Idempotentnie po `graph_message_id`; załączniki tylko jako metadane.
- Haki: nowy kontrakt → „Wejście konsultanta: …”, odejście pracownika →
  „Odejście: …”; idempotentne po `source_key`, nie commitują. Przy wyłączonym
  module nic nie zakładają — do przełączenia sprawy prowadzi Compass.
- Zakładkę „Sprawy” widzi uprawnienie „Sprawy”, admin i osoba przypisana do sprawy.
