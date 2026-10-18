# Opieka, mapa technologii, ATLAS, administracja@ (16.10.2026)

## Opieka (`app/services/care/*`, zakładka „Opieka” kontraktu, `/care`)

- Zakres klientów = zakres Delivery (`access_scope.resolve_delivery_lead_client_ids`):
  DL u swoich klientów, admin, Finanse i TCM u wszystkich. Cudzy klient → 403.
- Opiekun kontraktu: pole kontraktu, gdy puste — domyślny opiekun klienta,
  gdy i tego brak — Delivery Lead kontraktu.
- Plan kontaktów od startu kontraktu (etap 3, 17.10.2026): kamienie — dzień 7
  i 30 dni przed końcem zamówienia albo umowy, przy KAŻDYM rytmie, także
  wstrzymanym — i rozmowy według rytmu konsultanta (rodzaj `cadence`, niżej).
  Do 17.10.2026 plan był stały (dzień 7, 30, 90, potem co kwartał) — takie
  punkty zostają w bazie jako historia. Przy pierwszym włączeniu modułu stare
  kontrakty nie dostają zaległości sprzed okna — to historia sprzed modułu.
- Rozmowa zamyka punkt planu. Okno mówi „Bez danych o zdrowiu i bez stawek”
  i tak ma zostać. Sygnały „ryzyko odejścia” i „chce zmiany projektu” trafiają do
  kolejki „Do przepięcia”; „klient zatrudnia” to sygnał popytu.
- Dzienny przebieg (`care/reminders.py`): zaległy albo dzisiejszy kontakt
  (punkt planu albo follow-up z rozmowy) → `care_contact_due` (sekcja Delivery) do
  opiekuna, najwyżej raz na 7 dni na kontrakt; koniec projektu < 60 dni → wpis
  „Do przepięcia”.
- **„Następny kontakt” liczy jedna funkcja** `care/plan.next_contact` (karta
  kontraktu, „Konsultanci”, dzwonek opiekuna): najwcześniejszy otwarty
  punkt planu albo umówiony kontakt z OSTATNIEJ rozmowy, nie starszy niż
  30 dni (`plan.live_follow_up` — tej samej reguły używa „Ten tydzień”); remis
  wygrywa punkt planu. Od 17.10.2026 także karta i lista pomijają follow-up
  sprzed 30 dni (rozmowy z importu niosą terminy sprzed lat). Nie licz go
  w trasie ani w serwisie po swojemu.
- Trasy: `api/contract_care.py` (bramki w `api/care_gates.py`, odczyt zakładki
  i listy w `care/overview.py`), kolejka technologii `api/care_skills.py`,
  ATLAS `api/care_atlas.py` — wszystkie pod `/api/care`.

## Opieka · „Ten tydzień”, oś konsultanta, front office (etap 2, D15, 17.10.2026)

Domyślna zakładka `/care` (`components/care/week/`, `GET /api/care/week`,
serwis `care/week.py`); dawne listy „Moi konsultanci” i „Wszystkie kontrakty”
to od etapu 3 „Konsultanci” (`?tab=consultants`; `?tab=contracts` i `?tab=mine`
prowadzą tam samo).

- **Tydzień** = poniedziałek–piątek kalendarza firmy; w weekend „Ten tydzień”
  to tydzień, który się zaczyna. `?from=` przesuwa tydzień, zakres `mine|all`
  jak lista opieki (DL — swój portfel).
- **Odczyt list niczego nie zapisuje** (audyt wydajności 17.10): plan
  dopisuje dzienny przebieg i zmiana domyślnego opiekuna klienta zbiorczym
  `plan.ensure_plans` (jeden DELETE z `= ANY`, wielowierszowy INSERT).
  Wyjątek: zakładka „Opieka” jednego kontraktu dopisuje jego plan, żeby
  świeży kontrakt nie czekał na noc. Prośby o opinię w tygodniu biorą
  kontrakty i opiekunów policzonych dla kolejki (`feedback_requests_for`).
- **Rozmowa z konsultantem** — jedna pozycja na kontrakt: otwarte punkty
  planu z terminem do piątku (zaległe i z tego tygodnia) i umówiony kontakt
  z OSTATNIEJ rozmowy (nie starszy niż 30 dni, jak w dziennym przebiegu).
  Przy pozycji menedżer u klienta z drzewa (kontakt tego klienta z działem),
  ostatnia rozmowa, aktywne sygnały „Do przepięcia”. „Zapisz rozmowę” zamyka
  wskazany punkt planu.
- **Opinia od menedżera** — `client_people.feedback_requests` (jedna na
  menedżera, liczona na dziś), w `mine` jak `GET /feedback-requests`.
  Finanse widzą tydzień bez próśb i oś bez opinii (D11).
- **Licznik zaległych** przy zakładce = zaległe rozmowy + zaległe prośby.
- **Oś konsultanta** (`GET /api/care/contracts/{id}/timeline`, panel boczny,
  `/care?contract=<id>`): rekrutacja z `contracts.job_id`, start, rozmowy
  (z zamkniętym punktem planu), karty, opinie klienta, zamówienia (tytuł,
  status, daty) i ich końce, wpisy „Do przepięcia”, przekazania, najbliższy
  punkt planu. Bez stawek — test pilnuje, że zmyślone kwoty kontraktu
  i zamówienia nie wychodzą.
- **„Przekaż do front office”** (`/api/care/contracts/{id}/front-office`,
  `care/front_office.py`) — konsultant kończy projekt w ciągu 60 dni (koniec
  umowy/zamówienia albo aktywny „koniec projektu”) albo ma aktywne „chce
  zmiany”; inaczej 409. Pasujące rekrutacje liczy silnik „Pasuje też do”
  (`also_fits_for_candidate`, zakres odczytu rekrutacji czytającego);
  `unavailable` ≠ „nic nie pasuje”. Przekazanie: wpis „Do przepięcia”
  (istniejący albo nowy) → „W toku”, zdarzenie `care.front_office_handoff`
  w śladzie HR (same identyfikatory) i powiadomienie
  `care_front_office_handoff` do heada pionu front office
  (`app_settings['hr_divisions']`), Head of Recruitment, DL wybranych
  rekrutacji i głównego DL klienta (encja `care_front_office`, link do profilu
  osoby `/candidates/<id>`; kontrakt bez kandydata → `/care?contract=<id>`).
  Typ jest osobisty (bez sekcji, jak typy „Ludzi”), kategoria „Czas i ludzie”,
  mail „Czas i ludzie”, temat „Rekrutacje” z dymkiem — front office zwykle
  nie ma sekcji Delivery, więc typ opieki `care_contact_due` do niego nie
  docierał (do 17.10.2026). Odpowiedź i toast mówią, kto naprawdę dostał.

## Rytm kontaktu, „Konsultanci” i „Przydział” (etap 3, O7–O10, 17.10.2026)

Zakładki `/care`: Ten tydzień · Konsultanci · Przydział · Komunikaty · Do
przepięcia · Technologie (`components/care/CareScreen.tsx`; dawne
`?tab=contracts` i `?tab=mine` prowadzą do „Konsultantów”). Trasy
w `api/care_consultants.py` (router dołącza `api/contract_care.py`), reguły
w `care/cadence_rules.py` (bez bazy), zapis i sygnały w `care/cadence.py`,
lista w `care/consultants.py`, przydział w `care/assignment.py`.

- **Poziomy rytmu**: co 2 tygodnie, co miesiąc, co kwartał, tylko kamienie,
  wstrzymany. Bez zmiany: pierwsze 90 dni od startu co 2 tygodnie
  (`program`), potem co miesiąc (`default`). Zmiana = wiersz
  `care_cadence_periods` od dnia zmiany z powodem z listy, notatką ≤ 500
  i opcjonalnym „do kiedy”. W danym dniu obowiązuje okres, który go obejmuje
  i zaczął się najpóźniej — po „do kiedy” wraca to, co było przed zmianą, nie
  domyślny rytm. Terminy liczą się od początku odcinka (start, dzień 90, dzień
  zmiany, dzień po „do kiedy”); ten sam poziom obok siebie nie przesuwa
  terminów; rozmowa z rytmu najwyżej 6 dni od kamienia odpada (kamień to ta
  sama rozmowa).
- **Kto zmienia rytm** (O8): opiekun kontraktu (z łańcucha
  `effective_owners`), DL klienta (przypisanie w portfelu), head back office
  (`app_settings['hr_divisions']['back_office']`) i admin; inny TCM i Finanse
  dostają 403. Bez akceptacji. Zapis od razu przelicza plan (`ensure_plan`):
  otwarte PRZYSZŁE rozmowy z rytmu, których nowy rytm nie ma, znikają;
  zaległe zostają. Ślad `care.cadence_set` (kody, bez notatki). Okno „Rytm
  kontaktu” (`CadenceDialog`) liczy podgląd po stronie serwera
  (`GET …/cadence?level=&until_on=` — najbliższe rozmowy i rozmowy opiekuna
  w następnym miesiącu przed i po zmianie) i pokazuje historię rytmu.
- **Sygnały** (O9) tylko podpowiadają („podnieść rytm?” przy rytmie rzadszym
  niż co 2 tygodnie, nie przy wstrzymanym): ostatnia opinia menedżera < 3
  (tylko role z D11 — Finanse nie widzą), koniec zamówienia < 45 dni, „chce
  zmiany projektu” i „ryzyko odejścia” z „Do przepięcia”, zaległa rozmowa.
  Długiej nieobecności konsultanta NEXUS nie zna — konsultant nie ma kartoteki.
- **„Pomiń” punkt planu** wymaga powodu z listy (`skip_reason`, 422 bez
  niego) i notatki opcjonalnie; ślad `care.plan_item_skipped` /
  `care.plan_item_restored`, powód widać przy punkcie.
- **„Konsultanci”** (M1): jedna odpowiedź `GET /api/care/consultants` dla
  całego zakresu (`is_mine` — „Moi”), filtry i liczniki liczy front; liczba
  rozmów w miesiącu to suma rytmów (`plan.conversations_between`, kamienie
  i rytm). Odczyt niczego nie zapisuje.
- **„Przydział”** (M3, O10): obciążenie opiekuna = osoby i rozmowy
  w NASTĘPNYM miesiącu z rytmów, osoby po poziomach; próg
  (`app_settings['care_load_threshold']`, rozmowy w miesiącu) to
  ostrzeżenie, nie blokada. Zmiana wielu kontraktów naraz
  (`POST /api/care/assignment`, ≤ 500) i próg — tylko head back office
  i admin (`require_hr_care_assigner`); DL zmienia opiekuna pojedynczo
  u swoich klientów w zakładce „Opieka” kontraktu. Każda zmiana opiekuna (też
  pojedyncza, z opcjonalnym powodem) to ślad `care.owner_set` z powodem,
  poprzednim opiekunem wpisanym na kontrakcie i poprzednim faktycznym;
  oś konsultanta pokazuje zmiany opiekuna i rytmu (także powrót po „do
  kiedy”). „Bez opiekuna” = nikt w łańcuchu; podpowiedź mówi, skąd opiekun
  albo czego brakuje. „Domyślni opiekunowie klientów” w tym samym ekranie.
- **Import z Compassa**: `contractor_success_settings` → poziom (wstrzymany;
  program wejścia → co 2 tygodnie do jego końca; ≤ 14 / ≤ 31 / ≤ 93 dni →
  co 2 tygodnie / co miesiąc / co kwartał; dalej tylko kamienie; monitoring
  nieaktywny → rytm domyślny) i `contractors.owner_tcm_id` → opiekun
  kontraktu, tylko przy pewnym kontrakcie (reguła rozmów: kotwica osoby +
  klient z `current_client` + dzień eksportu w okresie umowy). Rytm albo
  opiekun ustawiony już w NEXUSIE zostaje (`conflict` w raporcie). Plan po
  imporcie przelicza nocny przebieg.

## Pula opiekunów i „Przypisz wg obłożenia” (decyzja Artura 18.10.2026)

Serwisy `care/owner_pool.py` (pula) i `care/auto_assign.py` (automat), trasy
`GET /api/care/assignment/auto` (podgląd), `POST /api/care/assignment/auto`
(zapis), `PUT /api/care/assignment/pool` (ustawienie) — `CareAssigner` (head
back office, admin). Karta „Pula opiekunów” na górze zakładki „Przydział”.

- **Pula jest wyliczana z kartoteki, nie wpisana**: bezpośredni podwładni
  przełożonego (`employee_profiles.manager_user_id`), status `onboarding`
  albo `active` (kończący pracę nie dostaje nowych), aktywne konto. Przełożony
  w `app_settings['care_owner_pool'].manager_user_id`; bez klucza — head back
  office z `hr_divisions`, `null` — puli nie ma. Na produkcji przełożonego
  i wykluczonych ustawia się w tej karcie (albo `PUT …/pool`), nie w kodzie.
- **„Nie przypisuj”** (`excluded_user_ids`, np. księgowość): takiej osobie
  nie da się przypisać konsultanta ani automatem, ani ręcznie (422 przy
  zmianie pojedynczej, hurtem i domyślnym opiekunie klienta, brak na liście
  wyboru — także admina), przekazanie pracy przy odejściu odmawia
  (`receiver_excluded`), a import z Compassa zostawia ją jako `conflict`.
- **Członek puli prowadzi opiekę jak TCM** (`care_access.is_care_writer`):
  zapis rozmów, kart, przepięć, zmiana opiekuna — także bez roli DL/TCM/admin
  (np. Finanse). Bramki sekcji zostają: kto nie ma sekcji i podglądu Delivery
  (np. Head of Recruitment), jest w puli z dopiskiem „nie widzi Opieki”
  i nie zostaje opiekunem ani automatem, ani ręcznie (`owner_pool.eligible_ids`). Opinie klienta (D11) dalej tylko DL, TCM, HoR, admin.
- **Automat**: kontrakty aktywne i kończące się BEZ opiekuna wpisanego na
  kontrakcie (także te z opiekunem z łańcucha — domyślnym klienta albo DL) →
  osoba z puli z najmniejszą liczbą aktywnych podopiecznych (faktyczny
  opiekun z łańcucha); remis — kolejność po nazwisku, potem id. Delivery Lead
  w puli dostaje tylko klientów z portfela. Kolejność kontraktów: start, klient, id.
- **Podgląd przed zapisem**: podgląd nic nie zapisuje; zapis bierze DOKŁADNIE
  pary z podglądu, pomija kontrakt, który w międzyczasie dostał opiekuna
  (`skipped`), a parę z osobą spoza puli odrzuca w całości (409 „odśwież
  podgląd”). Ślad `care.owner_set` z powodem `auto_load`. Niezapisana zmiana
  puli blokuje przycisk zapisu przydziału na ekranie.
- **Nowy kontrakt** (`auto_new_contracts`; bez zapisanego ustawienia puli
  automat nie rusza, karta zapisuje go domyślnie włączonego): hak
  `contract_hooks.contract_started` (krok `care`, także przy wyłączonym
  module — tryb cienia) i dzienny przebieg opieki (tylko starty z ostatnich
  14 dni; starsze bez opiekuna przydziela człowiek z podglądem).
- **Powiadomienie opiekuna tylko przy włączonym module `care`** (przy
  wyłączonym link prowadziłby na 404). Typ `care_contact_due`: hak — dzwonek
  na kontrakt („Nowy podopieczny”), zapis hurtem — jeden zbiorczy na osobę.
  Przypomnienie o kontakcie dla tego kontraktu wstrzymuje się wtedy na 7 dni
  (ta sama blokada co dla przypomnień; pierwszy punkt planu i tak przypada
  na dzień 7).

## Struktura u klienta i opinie klienta (etap 2, D8–D11, 17.10.2026)

Zakładka klienta „Struktura u klienta” (`components/care/ClientPeopleTab.tsx`,
`GET /api/care/clients/{id}/org`, serwis `care/client_people.py`). Jak ją
zapełnić — sekcja „Struktura u klienta: propozycje automatu i akcept DL” niżej.

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
  Odpowiedź zapisu „Podlega pod” (`PATCH …/contacts/{id}`) podlega tej samej
  regule: edytujący kontakty spoza kręgu D11 dostaje drzewo bez opinii i próśb
  (`feedback_visible: false`, 17.10.2026).
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

## Struktura u klienta: propozycje automatu i akcept DL (18.10.2026)

Decyzja Artura z 18.10.2026: „Propozycja automatu + akcept DL”. Artur chce
widzieć, pod jakim menedżerem u klienta pracuje każdy nasz konsultant i kto komu
podlega, żeby zbierać od menedżerów opinie. Do 18.10 na produkcji żaden kontrakt
nie miał menedżera (`contracts.client_pm_contact_id`), a żaden kontakt —
przełożonego (`reports_to_contact_id`). Drzewo, opinie i prośby o opinię — sekcja wyżej; tu tylko to, jak strukturę
zapełnić.

### Zasady

- **Automat proponuje, zapisuje człowiek.** Odczyt niczego nie zapisuje.
  Delivery Lead klienta (albo admin) zatwierdza propozycję, zmienia ją na inną
  osobę klienta (także nową — `job_hiring_manager.find_or_create_contact`, bez
  duplikatu) albo pomija. Bez kliknięcia nic nie trafia na kontrakt.
- **Do klienta nic nie wychodzi.** Prośby o opinię liczą się przy odczycie
  (D9), formularza do klienta nie ma (D10) — przełącznika wysyłki nie ma, bo
  nie ma wysyłki. Pilnuje tego `test_feedback_requests_and_proposals_have_no_outbound_channel`.
  Wysyłka do menedżerów u klienta = osobna zmiana po zgodzie Artura.
- **Każda propozycja ma źródło i pewność** (`services/care/structure_rules.py`,
  czyste funkcje z testami bez bazy). Pewna = najmocniejszy kandydat ma ≥ 3
  punkty, a żaden inny ich nie ma. Tylko pewne idą do „Zatwierdź pewne”.

### Źródła menedżera konsultanta (punkty)

| Źródło | Punkty |
| --- | --- |
| e-mail PM na kontrakcie (`client_pm_email` = e-mail kontaktu) | 3 |
| „Line Manager” albo „PM po stronie klienta” = pełne imię i nazwisko kontaktu | 3 |
| osoba kontaktowa z zamówienia (`client_orders.invoice_lines.contact`, dziś Nordea) | 2 |
| hiring manager rekrutacji kontraktu | 2 |
| menedżer kolegów z tego samego zespołu (`team_name`) albo tej samej rekrutacji | 2 |
| kierownik działu z karty technologicznej (jedyny 2, kilku — po 1) | 2 / 1 |
| nadawca maila z zamówieniem (`order_mail_documents.sender_email`) | 1 |

- Imię i nazwisko porównujemy jak przy hiring managerze (`name_key`: kolejność,
  wielkość liter i ogonki bez znaczenia). Samo imię albo skrót nie wskazuje
  nikogo — zła osoba zabrałaby opinię innemu menedżerowi.
- Hiring manager sam nie daje pewności (często menedżer to NIE HM). Nadawca
  maila sam też nie — bywa zakupowcem albo wspólną skrzynką.
- Każde źródło liczy się raz na osobę (pięć zamówień z tą samą osobą = jedno źródło).
- Kontakt innego klienta nigdy nie jest propozycją; kontrakt z takim kontaktem
  (dane sprzed walidacji D8) wraca na listę jako „bez menedżera”.
- „Menedżer kolegów” rośnie z akceptacjami: każdy wpisany menedżer
  podpowiada menedżera reszcie zespołu. Kolega, którego menedżer to hiring
  manager tej rekrutacji, się nie liczy — od 17.10 automat D8 wpisuje HM jako
  menedżera, więc byłby to ten sam dowód drugi raz (HM nie może dać pewności).

### „Kto komu podlega”

- Z tytułów: szczeble 4 zarząd/C-level, 3 dyrektor/head, 2 kierownik/lead,
  1 reszta; brak tytułu = szczebel nieznany. Osoba z tego samego działu
  (`client_area_id`, a bez niego tekst „Dział”) o najbliższym wyższym szczeblu —
  3 punkty, gdy jedyna i szczebel wyżej o jeden, inaczej 2. Dyrektor bez
  kandydata w dziale dostaje słabą podpowiedź osoby z zarządu (1).
- Hiring manager rekrutacji, z których przyszli konsultanci tej osoby (wyższy
  szczebel albo bez tytułu) — 2.
- Kandydat, który już podlega pod tę osobę, odpada (zatwierdzenie zamknęłoby
  pętlę). Zapis idzie przez `client_people.update_contact_org` — ta sama blokada
  klienta i kontrola pętli co ręczna zmiana w drzewie; pozycja odrzucona wraca
  w `rejected`, reszta się zapisuje.

### Ekran i trasy

- Opieka → zakładka **„Struktura u klientów”** (`/care?tab=structure&client=<id>`,
  `components/care/structure/`): klienci z zakresu z licznikami (do uzupełnienia,
  pewne, do sprawdzenia, bez propozycji) i panel propozycji klienta. Ta sama
  lista zwinięta jako „Propozycje automatu” nad drzewem w zakładce klienta
  „Struktura u klienta”. Harness: `/preview/hr-client-structure`.
- Trasy w `api/care_structure.py` (prefiks `/api/care`, router dołącza
  `contract_care.py`): `GET /structure-proposals`, `GET /clients/{id}/structure-proposals`,
  `POST …/managers`, `POST …/reports-to`, `PUT|DELETE …/managers/{contract_id}/skip`,
  `PUT|DELETE …/reports-to/{contact_id}/skip`.
- **Kto**: czytają ci sami co drzewo (D11: opiekun, DL klienta, HoR, admin;
  Finanse i Kadry — 403). Menedżera konsultanta zatwierdza, zmienia i pomija
  Delivery Lead klienta albo admin z edycją kontraktów u tego klienta
  (`require_hr_client_manager_approver` = `ClientContractsEditUser` + rola DL
  albo admin). TCM czyta, nie zatwierdza. „Podlega pod” z propozycji — krąg
  D11 z edycją kontaktów klienta (`OrgEditor` + `can_edit_contacts`); samo
  „Klienci: edycja” bez roli z D11 dostaje 403, bo odpowiedź niesie konsultantów. Wzorzec bramek:
  `tests/data/authz_golden/care_structure.json`.
- **Zatwierdzenie nie nadpisuje człowieka**: kontrakt, któremu ktoś
  w międzyczasie wpisał menedżera tego klienta, zostaje bez zmian (`conflicts`).
  Ślad: `care.client_manager_set` w `hr_audit_events` (same identyfikatory)
  i `client_managers_set` w Historii zdarzeń klienta.
- **„Pomiń”** (`client_structure_skips`, migracja 0475) pamięta osobę, którą
  automat proponował. Gdy automat wskaże kogoś innego, pozycja wraca;
  „Przywróć” kasuje wiersz; zatwierdzenie też.

### Dzwonek dla Delivery Leada

- `care_client_structure` (sekcja Delivery, kategoria „Kontrakty”, grupa
  „Opieka: struktura u klienta”, bez maila do klienta): „Klient X: N
  konsultantów bez menedżera u klienta, K pewnych propozycji do zatwierdzenia”,
  link do zakładki. Do każdego aktywnego DL przypisanego do klienta, najwyżej
  raz na 7 dni na (DL, klient). Klient bez DL — nikt (`structure_no_lead`
  w licznikach przebiegu).
- Wysyła dzienny przebieg opieki (`care/reminders.run_once`, krok 4). Awaria
  tego kroku nie cofa przypomnień opieki (`structure_failed`). Działa dopiero
  przy włączonym module `care` i pętlach HR — do tego czasu ani ekran, ani
  dzwonek nikomu się nie pokazują.

## Karta technologiczna i słownik (D7)

- Jeden słownik dla wymagań rekrutacji, profili i mapy klienta: tabela `skills`
  z aliasami. Nazwa wpisana tekstem, której słownik nie zna, idzie do
  `skill_review_queue` (jeden wiersz na nazwę), a na karcie zostaje tekstem do
  decyzji: „Zmapuj” (alias), „Dodaj do słownika”, „Odrzuć”. Decyzje zmieniają
  słownik całej aplikacji, więc podejmują je ci, którzy prowadzą „Słownik
  umiejętności”, przez `skill_curation` z tymi samymi kontrolami konfliktów.
- W polu technologii lista po odpowiedzi słownika pokazuje „Dodaj „…” · do
  przejrzenia”, gdy nie ma dokładnego trafienia (Enter robi to samo).
- **Propozycje w kolejce (18.10.2026)**: `GET /api/care/skill-review` podaje
  przy otwartej nazwie do 3 umiejętności słownika (`care_skills.suggester`:
  klucz bez wersji, wielkości liter, polskich znaków, spacji, kropek
  i myślników, potem bez końcówki „js”). Kolejka pokazuje „Zmapuj na „X””
  jednym kliknięciem — to zwykłe „Zmapuj” (alias), więc bez duplikatu
  w słowniku. Nic nie mapuje się samo, także w imporcie z Compassa.

## Karty z Compassa i kontrakty (import 18.10.2026)

- Compass nie wie, który kandydat to jego kontraktor (kolejka „Tożsamość
  NEXUS” jest pusta), więc import karty łączy ją z kontraktem po kliencie,
  imieniu i nazwisku i dniu rozmowy — decyzja Artura „Import + automatyczne
  parowanie”, reguły w `care/card_linking.py`: nazwisko bez wielkości liter,
  polskich znaków, kolejności słów i dopisków Traffita; klient po scaleniu;
  umowa bez anulowanych i szkiców. DOKŁADNIE jeden kontrakt z dniem rozmowy
  w okresie umowy = połączenie automatyczne. Kilka albo tylko poza okresem =
  propozycje, brak = bez propozycji — karta czeka przy kliencie z pustym
  `contract_id` i z nazwiskiem z Compassa (`tech_cards.compass_person_name`,
  migracja 0474). Mapa liczy ją od razu (źródło T nie wymaga kontraktu).
- Klient Compassa → klient NEXUSA (karty): nazwa po `normalize_client_name`,
  bez trafienia — po nazwie bez formy prawnej (`loose_client_name`), na końcu
  po zbiorze słów bez „ex” („ERSTE / Santander” = „ERSTE (ex Santander)”).
  Kilku klientów o tej nazwie (duplikat z Traffita, np. dwa „PFRON”) =
  wygrywa ten, u którego osoba ma pewny kontrakt w dniu rozmowy; inaczej karta
  pominięta. NIP-u Compass nie eksportuje.
- **„Karty z Compassa do połączenia”** w zakładce „Technologie” klienta
  (`UnlinkedCardsPanel`, `GET /api/care/clients/{id}/tech-cards/unlinked`,
  serwis `care/card_inbox.py`): propozycje liczone przy odczycie (kontrakt
  dodany po imporcie też się pojawi), wybór „Inny kontrakt klienta” do 500
  kontraktów. Bez kart sekcji nie ma; awaria odczytu mówi o sobie.
- **„Połącz”** (`POST /api/care/tech-cards/{id}/link`, piszący opiekę w
  zakresie klienta): tylko karta bez kontraktu (inaczej 409), tylko kontrakt
  tego samego klienta po scaleniu (422) i nie anulowany ani szkic (422). Ślad
  `care.tech_card_linked` (kontrakt i czy był propozycją). Raz połączonej
  karty ta trasa nie przepina.
- Rozmowy, rytm i opiekun z Compassa łączą się nadal WYŁĄCZNIE po kotwicy —
  parowanie po nazwisku dotyczy tylko kart. Ponowny import łączy kartę, gdy
  w NEXUSIE pojawi się pewny kontrakt, i nie odpina kontraktu wybranego przez DL.

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
- **Działy (D16, 17.10.2026)**: wiersze po `client_areas` (te same co
  w „Strukturze u klienta”). Do działu trafia karta z tym obszarem,
  rekrutacja z hiring managerem z działu i nasz konsultant, którego menedżer
  u klienta jest z działu (wtedy też filtr działu pełnej listy). Notatki
  nie mają działu. Menedżer działu = osoba z działu z naszymi konsultantami
  (brak → „nie wskazano”). „Nasi / w bazie”: konsultanci działu / osoby
  w bazie z DWIEMA najmocniejszymi technologiami działu naraz — ten sam
  predykat co filtr umiejętności listy (`skill_match`, v2), jedno przejście
  po tabeli z limitem 3 s, cache `care:techbase:` na godzinę; awaria = „—”.
  Link prowadzi do `/candidates?skills_q=…`.
- **Luki do dopytania**: dział bez źródła z 18 miesięcy (konsultant
  w projekcie liczy się jako świeże źródło), menedżer naszych konsultantów
  bez „podlega pod”, technologia z jednego źródła (świeża, nie z samych CV
  naszych — CV opisuje człowieka, nie stack; najwyżej 6). Te same pytania
  są w oknie zapisu rozmowy opieki (sekcja zwijana „Do dopytania u
  klienta”, mapa wczytuje się po rozwinięciu, nic się nie zapisuje).
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

- **Dwa adresy administracji** (`admin_cases/mailbox.py`, 18.10.2026).
  administracja@b2bnetwork.pl żyje na home.pl (MX domeny wskazuje na home.pl)
  i tam czytają ją ludzie; NEXUS czyta przez Graph tylko skrzynki M365, więc
  dostaje kopię poczty w osobnej skrzynce (wariant B, decyzja Artura):
  - `ADMIN_CASES_MAILBOX` = adres widoczny: autoodpowiedź urlopowa („w pilnych
    sprawach”), Reply-To komunikatów i maila powitalnego, ekrany,
  - `ADMIN_CASES_M365_MAILBOX` = skrzynka M365, którą czyta czytnik i z której
    NEXUS wysyła (pole From).
  Pusta jedna = obie role ma druga (skrzynka przeniesiona do M365 = jedna
  zmienna). Nie wpisuj skrzynki z kopią do autoodpowiedzi ani adresu z home.pl
  jako skrzynki do czytania — Graph go nie zna, a autoodpowiedź pokazałaby
  adres, którego nikt nie czyta. Odpowiedź konsultanta idzie na Reply-To
  (home.pl), a do Spraw trafia jej kopia; zwrotki wracają na From (M365).
- **Wiadomość od administracji** (nadawca = adres widoczny albo skrzynka M365):
  w wątku istniejącej sprawy dołącza do niej BEZ ponownego otwarcia, poza
  wątkiem jest pomijana (to nie zgłoszenie). Tak do Spraw trafia odpowiedź
  wysłana z home.pl, gdy ma administracja@ w kopii (UDW) — sama kopia z home.pl
  niesie tylko pocztę przychodzącą.
- Czytnik skrzynki: app-only Graph (wzorzec `order_mail_ingest`), wyłączony, gdy
  nie ma skrzynki M365 (obie zmienne puste), `ADMIN_CASES_MAIL_INGEST_ENABLED ≠ true`
  albo moduł `cases` wyłączony. Potrzebuje tokenu rejestracji HR — rejestracja zamówień ma
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

## Opieka · Komunikaty do konsultantów (O12, etap 3, 17.10.2026)

Zakładka „Komunikaty” w `/care` (`components/care/announcements/`, trasy
`api/care_announcements.py` pod `/api/care/announcements`, serwisy
`care/announcements.py`, `announcement_audience.py`, `announcement_mail.py`,
`announcement_queue.py`, migracja 0466). Konsultant nie ma konta — komunikat to
wysyłka do ludzi spoza firmy.

- **Wysyłka jest wyłączona, dopóki admin jej nie włączy**
  (`app_settings['care_announcements'] = {"sending_enabled": true}`; brak
  wiersza = wyłączona). Wyłączona: szkic, podgląd odbiorców i próba do siebie
  działają, „Wyślij” i „Zatwierdź” = 409, kolejka stoi. Pierwszą wysyłkę
  uruchamia Artur.
- **Kto**: piszą opiekunowie (TCM) i Delivery Lead u swoich klientów (z dostępem
  do Delivery), head back office (`hr_divisions['back_office']`) i admin.
  Komunikat widzi autor, head back office i admin. Powyżej 20 osób zatwierdza
  head back office albo admin — nigdy autor ani osoba, która wysłała komunikat
  do zatwierdzenia (CHECK `ck_care_announcements_approver` w bazie); do 20 osób
  autor wysyła sam. Lista liczy się zakresem AUTORA także wtedy, gdy „Wyślij”
  klika admin (szkic Delivery Leada = jego klienci).
- **Próba do siebie jest obowiązkowa po każdej zmianie treści** (rodzaj, temat,
  treść podbijają `content_version`; „Wyślij” wymaga `tested_version` równej
  wersji). Zmiana grupy próby nie unieważnia.
- **Grupy**: wszyscy, klient, opiekun (łańcuch `effective_owners`), forma
  (`b2b | uop | zlecenie`), kończący zamówienie w N dni (`CareContract.end_date`),
  wybrane osoby. Jedna osoba = jeden mail (kontrakt z najpóźniejszym startem).
  E-mail jak na karcie kontraktu (`contract_candidate_contact`). Wykluczenia:
  brak poprawnego adresu, wypisani — tylko przy informacyjnym; obowiązkowy idzie
  do wszystkich z grupy. Pola w treści: wyłącznie `{imię}` i `{opiekun}`
  (nieznane pole = 422); temat bez pól.
- **„Wyślij” zamraża listę** (`care_announcement_recipients`, z wykluczeniami):
  zatwierdzający widzi dokładnie tę listę; „Zwróć do poprawy” ją kasuje.
- **Kolejka** (`announcement_queue.run_once`, pętla co 60 s): rezerwacja
  MINUTY w `hr_job_runs` i najwyżej 30 osób na minutę; osoba „w wysyłce” jest
  commitowana przed mailem, a przerwana wysyłka to „niepewny” bez ponowienia.
  Odłożona (429, 5xx, token) wraca do 3 prób, odrzucona (np. 400) = „błąd”.
  Osobny mail do każdego, jeden adresat, nadawca = skrzynka M365 administracji
  z Reply-To na adres widoczny (dwa adresy wyżej), przez rejestrację „NEXUS Kadry”, tryb z `HR_M365_MODE` (`simulate` = nic nie
  wychodzi, wiersz ma `simulated`).
- **Wypis** (informacyjne): token z linku `/wypis/<token>` (w bazie tylko
  SHA-256), publiczne `GET/POST /api/public/consultant-mail/unsubscribe/{token}`
  z limiterem, odpowiedź bez danych osobowych, zły token = to samo 404. GET nic
  nie zmienia (skanery linków w poczcie), wypisuje POST.
- **Odpowiedzi**: temat niesie `[Komunikat <id>/<kod>]` (kod losowy — sam numer
  niczego nie przypina). Czytnik administracja@ przy NOWEJ sprawie woła
  `link_mail_case`: odnośnik w `care_announcement_replies`, a gdy nadawca jest
  odbiorcą — `admin_cases.contract_id` jego kontraktu. Zwrotka serwera (WYŁĄCZNIE
  nadawca postmaster@ / mailer-daemon@ / MicrosoftExchange… — temat
  „Undeliverable” od człowieka to zwykła odpowiedź) z adresem odbiorcy
  w treści = osoba „odbity” i powiadomienie `care_announcement` do opiekuna
  („popraw e-mail”, link do kontraktu, bez adresu w treści).
- **Powiadomienie `care_announcement`** (osobiste, „Czas i ludzie”, mail):
  do zatwierdzenia → head back office (bez niego aktywni admini), decyzja →
  autor, odbity mail → opiekun. NEXUS nie śledzi otwarć maili.

## Wejście u klienta: pakiet klienta i mail powitalny (O2, O3, O6, etap 3, 17.10.2026)

- **Pakiet klienta** (zakładka klienta „Wejście u klienta”,
  `services/hr/client_pack.py`, trasy `/api/client-onboarding/clients/{id}/pack`,
  moduł „Wejście i odejście”): rzeczy od nas i od klienta, wzory protokołu
  wydania i zwrotu, pierwszy dzień (gdzie, o której, co zabrać, zapasowa
  osoba odbierająca), dokumenty od konsultanta (termin w dniach roboczych
  względem startu, wymagane, z plikiem) i dostępy (kto po naszej stronie
  pilnuje). Flaga „sprzęt od nas / od klienta” zostaje na kliencie (D7).
- **Kto**: czyta podgląd Delivery (DL u swoich klientów) i recepcja; zapisuje
  „Klienci: dodawanie i edycja” (DL u swoich), część sprzętową także „Sprzęt”.
  Zapis wysyła `expected_version` — cudza zmiana w międzyczasie = 409, nie
  ciche nadpisanie. Ślad `onboarding_pack_updated` w Historii zdarzeń klienta.
- **Ścieżka wejścia dokłada pakiet** (`pack_tasks`): dokumenty (wykonawca
  opiekun — konsultant nie ma konta), dostępy (wykonawca z wiersza) i „Odbiór
  od klienta: …”. „Przygotuj zestaw” i „Wydanie sprzętu i protokół” to pozycje
  ścieżki z warunkiem „sprzęt od nas” — pakiet ich NIE zwraca (dubel z zadaniem
  recepcji); lista rzeczy od nas idzie do opisu pozycji (`load_pack().equipment_ours`).
- **Pierwszy dzień** (`first_day`): odbiera menedżer z kontraktu
  (`client_pm_contact_id`, osoba z drzewa klienta), zapasowo kontakt z pakietu;
  kontakt innego klienta się nie liczy.
- **Mail powitalny** (karta w zakładce „Wejście” kontraktu,
  `services/hr/welcome_mail.py`): treść z kontraktu i pakietu, podgląd,
  poprawka, potwierdzenie, „Wyślij” — wysyła opiekun (DL, TCM, admin) w zakresie
  klienta. Jeden mail na kontrakt (`consultant_welcome_mails`), nadawca
  administracja@ kanałem komunikatów (`care.announcement_mail.default_mailer`,
  `HR_M365_MODE`: `off` = 409, `simulate` = nic nie wychodzi i ślad to mówi).
  Odłożona albo odrzucona wysyłka nic nie zapisuje (502, można ponowić),
  niepewna zostaje zapisana bez ponowienia. Wysłanie odhacza pozycję ścieżki
  `welcome_mail` (`lifecycle_service.complete_task_by_key`).
- **Przełącznik** `app_settings['consultant_welcome_mail']` jest domyślnie
  WYŁĄCZONY (brak wiersza = wyłączony): podgląd działa, wysyłka 409. Włącza go
  admin (karta maila, potwierdzenie) — pierwszą wysyłkę uruchamia Artur.
