# Opieka, mapa technologii, ATLAS, administracja@ (16.10.2026)

## Przebudowa 22.10.2026 — kanban, karta konsultanta, okno rozmowy, popyt dla DL

Ta sekcja ma pierwszeństwo przed opisami ekranów niżej (dawne zakładki /care, „Oś opieki”, okno „Karta technologiczna” na kontrakcie).

Decyzje Artura 21–22.10.2026 (makiety `2yNppKPWBQcstvBK3YiaxV`): wszystko według rekomendacji,
głównym widokiem pracy jest **kanban Spraw z kartami opieki** (zespół jest do niego przyzwyczajony),
popyt u klienta idzie do **Delivery Leada, nie do ATLAS-a**. Starsze reguły opieki
(`opieka-mapa-technologii-i-sprawy.md`) dalej obowiązują — ten plik mówi, co się zmieniło.

### Układ ekranów

- **/care** ma zakładki: Do zrobienia · Konsultanci · Klienci · Zespół opiekunów (tylko
  `require_hr_care_assigner`: head back office i admin). „Komunikaty” to przycisk w nagłówku
  (ekran bez zmian, `?tab=announcements` działa). Stare `?tab=` (`week`, `contracts`, `mine`,
  `structure`, `redeploy`, `review`) prowadzą w nowe miejsca — dzwonki z linkami dalej działają.
  „Do przepięcia” to karty „Decyzja” na tablicy i filtr w Konsultantach; kolejka nazw technologii
  jest w Ustawienia → Słownik umiejętności („Nazwy z rozmów do przejrzenia”).
- **Profil klienta**: jedna zakładka „Ludzie i technologie” (`?tab=ludzie`, po „Kontaktach
  klienta”) z widokami Działy · Drzewo osób · Mapa; `struktura` i `technologie` przekierowują.
  Rzadkie zakładki (Importy MD, Faktury, Analityka) są pod „Więcej”.
- **Kontrakt → Opieka** = Karta konsultanta na pełną szerokość (ten sam komponent co panel
  `/care?contract=<id>`). Przycisku „Karta technologiczna” nie ma — stan projektu wpisuje się
  w oknie rozmowy; stare karty edytuje się z historii.

### Tablica (`components/work-board/`, `GET /api/care/board`, `PUT /api/care/board/state`)

- Jedna tablica w Opieka → Do zrobienia (`scope="care"`); `scope="cases"` zostaje tylko pod
  `/people/cases` przy wyłączonym module `care` (zakładki „Sprawy” w Ludziach nie ma od 22.10.2026).
  Wszystko z dawnego kanbana spraw zostaje: Moje/Wszystkie, chipy obszarów, Na ten tydzień, Bez
  osoby, szukanie, Nowa sprawa, kolumny Nowa · W toku · Czeka na kogoś · wąskie Zrobione, karta
  sprawy 1:1. Nie usuwaj żadnego z tych elementów przy zmianach — to był warunek Artura.
- Obszar „Opieka” (karty rozmów, opinii menedżerów, decyzji o przepięciu, u DL — popytu), chip
  „Moi podopieczni” (`GET /api/cases?mine_care=true`) i kropka zdrowia widzą tylko osoby
  z dostępem do opieki (moduł `care` + rola opieki, `CARE_ROLES`). Obsługa skrzynki bez opieki
  wchodzi do „Opieki” z menu (`casesInCare`) i widzi samo „Do zrobienia” ze sprawami.
- Rozmowa wchodzi na tablicę tylko z terminem do piątku albo po terminie. „W toku” = umówiona
  (dzień i godzina), „Czeka” = nie odbiera (dzień ponownej próby > dziś; w ten dzień karta wraca do
  „Nowa”). Stan karty opieki żyje w `care_board_states` (0509, kolumna `board_column`); punkt planu
  dalej ma tylko `open/done/skipped`. Upuszczenie rozmowy/opinii na „Zrobione” otwiera okno zapisu —
  stan „zrobione” daje wyłącznie zapis. Sprawa przesuwa się PATCH-em statusu z `expected_updated_at`
  (409 = ktoś zmienił w międzyczasie). Ruch: przeciąganie (`@hello-pangea/dnd`) albo menu „Przenieś do…”.
- Klik w kartę otwiera panel boczny (sprawa albo skrót karty konsultanta); pełny ekran sprawy
  zostaje pod linkiem. Widok Tablica / Lista pamięta się per osoba (localStorage).
- `/care?card=<klucz>` z dzwonka otwiera panel także przy otwartej już tablicy (efekt na
  `initialSelectedKey`), a zamknięcie panelu zdejmuje `card` z adresu (F5 nie otwiera go znowu).
- Karta „Decyzja” w „Czeka” po dniu ponownej próby wraca do „Nowa” także przy wpisie „W toku”
  (`board.decision_column`). Notatka z przeniesienia (`state_note`) stoi w linii „umówione /
  ponowna próba” na karcie i w panelu.
- „Wraca na rynek” przy znaczniku „Pracuje u nas” (`employment_marker.returning_contract_ids`) =
  kontrakt przekazany do front office (ślad `care.front_office_handoff`) z niezamkniętym wpisem
  „Do przepięcia”; sam wpis w toku nie wystarcza, a „ryzyko odejścia” nie liczy się nigdy.
- `/care?tab=review` prowadzi admina i HoR do Słownika umiejętności, a TCM (bez Słownika) do
  `/settings?item=skills-review`.

### Zdrowie relacji (`care/health.py`)

- Dobrze / Uwaga / Ryzyko + powody („dlaczego”), czyste reguły w module z testami brzegów. Widzi
  krąg D11 (opiekun, DL, HoR, admin) — inni dostają `health: null`, bo reguły czytają opinię
  menedżera, której Finanse nie widzą. Zadowolenie bierze się tylko z rozmów opiekuna.
  Także w D11 zdrowie ma tylko kontrakt klienta z zakresu czytającego (`allowed_client_ids`,
  portfel DL) — tablica Spraw pokazuje kontrakty wszystkich, więc spoza zakresu `health: null`.
  „Decyzja” = wpis „Do przepięcia” w toku / przepięty / nie dotyczy z 120 dni albo przekazanie do
  front office. Bez modelu AI.

### Okno „Rozmowa” (`care/conversation_save.py`, `GET …/client-state`)

- Jedna transakcja: rozmowa → karta z „Co u klienta” (ostatni stan + zmiany; tylko gdy przyszedł
  `client_state`) → odpowiedzi na pytania z mapy → sprawy „Coś do załatwienia?” (≤ 5, wymagają
  modułu Spraw, inaczej 409) → dzwonek popytu. „Co u klienta” bez żadnej technologii = rozmowa bez
  karty (nie 422). Sama zmiana menedżera nie robi karty; innego menedżera kontraktu zmienia tylko DL
  klienta albo admin (`manager_kept: true`). Odpowiedź „technologie działu” = notatka o stacku;
  nazwy spoza słownika idą do kolejki przeglądu. Karta wie, z której rozmowy powstała
  (`tech_cards.care_conversation_id`).
- Bez technologii, ale ze zmianą menedżera front wysyła `client_state` z samym
  `manager_contact_id` (menedżer na kontrakt, bez karty). Notatka przy „Komu podlega …?” zapisuje
  się zawsze jako ogólna notatka o kliencie (także bez wybranej osoby); wybór osoby widzi tylko
  ktoś z `can_edit_org` (reszta dostałaby 403 `ORG_DENIED`).
- „Klient zatrudnia”: role i źródło idą na górnym poziomie ciała (`hiring_roles`,
  `hiring_source`) i zapisują się przy rozmowie (`care_conversations.client_hiring_roles/source`,
  0509) — popyt bierze je, gdy rozmowa nie ma karty (albo karta nie ma ról).
- Sprawy z okna (audyt bezpieczeństwa 22.10.2026): tytuł 3–200 znaków; bez uprawnienia „Sprawy”
  sprawa tylko bez osoby (trafia do „Bez osoby” u obsługi) albo na siebie i nigdy „Negocjacje”
  (403); `GET /api/care/case-assignees` daje pełną listę tylko obsłudze, reszcie — ją samą.
  Limit: 5 spraw z rozmowy i 20 spraw z rozmów na osobę na dobę (429; liczone po opisie
  „Z rozmowy opiekuna z konsultantem …” i `created_by`).

### Popyt → Delivery Lead (`care/demand.py`)

- Sygnał = rozmowa z „klient zatrudnia” (i karta z `hiring`) z 90 dni. Ten sam klient + dział +
  zbiór ról z 30 dni = jedna karta. Dzwonek `care_demand_signal` (sekcja Delivery, bez maila) do
  aktywnych DL klienta, najwyżej jeden na (DL, klient, dział) w 7 dni. Rozstrzyga DL klienta albo
  admin w oknie „Rozmowa z menedżerem” (`POST /clients/{id}/feedback` z `demand`): potwierdzona →
  `jobs_new_url` (`/jobs/new?client=&hm=&skills=&title=`, odczyt tylko pustych pól), nie teraz →
  wraca za 30 dni, nieaktualne → znika. **ATLAS (`/api/care/atlas/*`) bez rozbudowy.**
- Klucz karty popytu `demand:<klient>:<rozmowa>` — BEZ działu: dział liczy się przy odczycie, więc
  po zmianie działu menedżera rozstrzygnięcie by się zgubiło. Dział łączy tylko karty, a w linku
  dzwonka (`/care?card=<klucz>&area=<dział|0>`) służy do limitu raz na 7 dni.
- `demand.hiring_signal` w „Klientach” widzi tylko ten, kto widzi karty popytu klienta (DL
  klienta, admin — `demand.demand_clients`); reszta dostaje `false`.

### Sprawy przy konsultancie (`admin_cases/contract_links.py`, `queries.py`, `hooks.py`)

- Rejestr spraw zostaje jeden (Opieka → Do zrobienia). Karta konsultanta pokazuje sprawy kontraktu
  (`cases_for_contract`): treść tylko z `may_read`, **negocjacje zawsze bez treści** (opieka „bez
  stawek”). Oś osoby ma zdarzenia spraw bez treści. Bez `may_read` tytuł też jest treścią — w karcie
  i na osi stoi „Sprawa: <obszar>” bez osoby (`queries.redact_case_title`, także negocjacje).
- Obsługa Spraw widzi sprawy wszystkich kontraktów, ale dane opieki (opiekun, rytm, ostatnia
  rozmowa, inne sprawy, zdrowie) tylko dla klientów ze swojego zakresu (`allowed_client_ids`);
  spoza zakresu zostaje osoba i klient (`queries.redact_out_of_scope`).
- Mail z nowej sprawy: nadawca = e-mail konsultanta z kontraktu i dokładnie jeden aktywny lub
  kończący się kontrakt → `contract_id` sam (ślad `case_linked`, `source: mail_sender`) — tylko gdy
  nadawca jest uwierzytelniony: pierwszy (od bramki) nagłówek `Authentication-Results` ma
  `dmarc=pass` dla domeny `From` albo `spf=pass` + `dkim=pass` zgodne z nią
  (`contract_links.sender_authenticated`). Inaczej sam `From` daje tylko propozycję. Kilka
  kontraktów albo mail z firmy klienta z nazwiskiem naszego konsultanta → tylko propozycje „Kogo
  dotyczy?” (klik), nigdy automatycznie. Odmienione nazwiska celowo nie dają propozycji.
- Koniec współpracy konsultanta (`contract_hooks.contract_ended`, krok `cases_end`) zakłada sprawę
  „Koniec współpracy: <osoba> · <klient>” (`contract:<id>:end`, prowadzi efektywny opiekun) z checklistą:
  zwrot sprzętu (tylko sprzęt od nas), dostępy z pakietu klienta, ostatnia opinia menedżera,
  decyzja o przepięciu, rozliczenie ostatniego miesiąca (bez kwot). „Cofnij zakończenie” zamyka
  sprawę; sprawy zamkniętej ręcznie automat nie otwiera ponownie. Void i wyłączony moduł — nic.
- Import spraw z Compassa wiąże kontrakt regułami `care/card_linking.py` (pewny = `contract_id`,
  niepewny = nic); kontraktu ustawionego w NEXUSIE nie nadpisuje.

### Lista klientów w /care (`care/portfolio.py`, `GET /api/care/clients`)

- Liczona hurtem; mapa technologii tylko z cache (`gaps: null` = nie liczone) — nie licz pełnej
  mapy dla wszystkich klientów w jednym żądaniu. `managers_known` = liczba różnych menedżerów,
  `structure_open` = konsultanci bez menedżera.

## Opieka (`app/services/care/*`, zakładka „Opieka” kontraktu, `/care`)

- Zakres klientów = zakres Delivery (`access_scope.resolve_delivery_lead_client_ids`):
  DL u swoich klientów, admin, Finanse i TCM u wszystkich. Cudzy klient → 403.
  Rola „Automatyzacje” (0446) ma podgląd Delivery, ale opieki nie widzi wcale
  (`care_gates.refuse_automation`, decyzja Artura 19.10.2026).
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
- **Zbiorczy dzwonek opiekuna** (decyzja Artura 19.10.2026 po pierwszym
  przebiegu 18.10: 472 dzwonki, jednemu DL 290 — bez zapisanego przydziału
  opiekunem jest DL z łańcucha). Jeden kontrakt do kontaktu = dzwonek jak
  wyżej (link do kontraktu). Kilka = JEDEN dzwonek „Kontakt z konsultantami”
  (`related_entity_type = care_owner_digest`, id opiekuna, link `/care` =
  „Ten tydzień”): liczba, trzy pierwsze osoby po terminie, najstarszy termin.
  Najwyżej raz na 7 dni na opiekuna, wcześniej tylko, gdy któryś kontakt
  wypada dziś. Kontrakty z dzwonkiem pojedynczym w ostatnich 7 dniach się nie
  liczą (`skipped`). Licznik przebiegu `digests`. 472 dzwonki z 18.10
  oznaczone jako przeczytane (ślad w raporcie audytu A3).
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

- **Kolumna dnia pokazuje 8 kart** (`COLUMN_VISIBLE`, `visibleCards`, decyzja
  Artura 20.10.2026): „Zaległe” od najstarszego terminu, pod kartami „Pokaż
  wszystkie (N)”; licznik w nagłówku liczy wszystkie. Otwarta oś osoby spoza
  pierwszych 8 rozwija kolumnę. Powód: prod 20.10 — „Wszyscy w moim zakresie”
  rysowało 482 zaległe karty. Harness `/preview/hr-care?state=list&big=1`.
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
- **Plan dni (makieta 19.10.2026, `week/WeekBoard.tsx`)**: kolumny „Zaległe ·
  pn … pt” liczy `weekColumns` (bez Reacta, z testami). Zaległa rozmowa
  (termin przed dziś) stoi w „Zaległe”, nawet gdy termin wypadł w tym
  tygodniu; dzień, który minął, jest pusty („—”), przyszły — „wolne”, dziś
  wyróżnione. W tygodniu z przyszłości bez zaległych pierwsza kolumna to
  „Wcześniej”. Karta: klient · dział menedżera (bez niego rola), powód jako
  pigułka („3 dni po · dzień 30” — czerwona, umówiony kontakt — niebieska),
  sygnały „Do przepięcia” i front office jako pigułki bez powtórzeń, notatka
  z ostatniej rozmowy w cudzysłowie, ostatnia ocena kropkami. Pod planem pas
  „Opinie od menedżerów u klientów” z terminem („czeka od” / „do”).
- **Pasek tygodnia** = `counts.done / (done + contacts)`: `done` to kontrakty
  z zakresu z rozmową zapisaną od poniedziałku do piątku (jedna osoba = jedna
  pozycja). Zapisana rozmowa zamyka punkt planu i znika z `contacts`, więc
  postęp nie może liczyć samych otwartych pozycji.
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
  kontraktu, tylko przy pewnym kontrakcie (tylko kotwica osoby +
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
  Audyt 19.10.2026: osoba z puli pisze tylko z ZAPISEM w sekcji Delivery
  (`is_care_writer` — sam podgląd daje flagi `can_edit: false`, bo bramka
  `CareWriter` i tak odmawia), a `POST /clients/{id}/feedback` sprawdza
  dodatkowo krąg D11 (`reads_client_people`, inaczej 403). DL rekrutacji
  jest opiekunem z łańcucha tylko u klienta z własnego portfela
  (`care_access._named_owner`), jak przy ręcznym przydziale.
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
  nikogo — zła osoba zabrałaby opinię innemu menedżerowi. Imiennicy u klienta
  (dwa kontakty o tym imieniu i nazwisku, różne albo puste e-maile) też
  nikogo — inaczej „Zatwierdź pewne” wpisywał hurtem osobę o niższym id
  (audyt 19.10.2026); ten sam e-mail = ta sama osoba (najniższe id).
- Hiring manager sam nie daje pewności (często menedżer to NIE HM). Nadawca
  maila sam też nie — bywa zakupowcem albo wspólną skrzynką.
- Każde źródło liczy się raz na osobę (pięć zamówień z tą samą osobą = jedno źródło).
- Kontakt innego klienta nigdy nie jest propozycją; kontrakt z takim kontaktem
  (dane sprzed walidacji D8) wraca na listę jako „bez menedżera”.
- „Menedżer kolegów” rośnie z akceptacjami: każdy wpisany menedżer
  podpowiada menedżera reszcie zespołu. Kolega, którego menedżer to hiring
  manager tej rekrutacji, się nie liczy — od 17.10 automat D8 wpisuje HM jako
  menedżera, więc byłby to ten sam dowód drugi raz (HM nie może dać pewności).

- **„Dodaj X jako menedżera”** (18.10.2026, wieczorem): gdy w „Line Manager”
  (a bez niego w „PM po stronie klienta”) stoi imię i nazwisko, którego nie ma
  w kontaktach klienta, pozycja bez pewnej propozycji dostaje przycisk, a sekcja
  — hurtowe „Dodaj z „Line Manager” (N)” z potwierdzeniem. Na produkcji 18.10
  dotyczyło to 207 z 414 konsultantów bez propozycji. Kontakt powstaje dopiero
  po kliknięciu (`find_or_create_contact` — ta sama osoba wpisana inaczej to
  jeden kontakt). Tekst musi wyglądać na osobę (`structure_rules.person_name_from_text`):
  2–4 słowa z liter, każde ≥ 2 litery (przedrostek z apostrofem „O'Neil”
  dozwolony), bez inicjałów, cyfr, ukośników, przecinków, e-maili i słów
  w rodzaju „brak”, „Team”, „Kierownik”, a od audytu 19.10.2026 także nazw
  jednostek i firm („IT Ops”, „Nordea Bank”, „Tribe …”, „Squad …”,
  „Departament …”). Przycisku nie ma też, gdy kontakt klienta może być tą
  osobą wpisaną inaczej (`ContactIndex.name_known`: „Anna Nowak” ~ „Anna Maria
  Nowak”, „Nowak-Kowalska” ~ „Nowak Kowalska”, imiennicy) — porównanie przy
  zakładaniu jest dokładne i powstałby drugi kontakt. Dzwonek struktury
  dostaje też DL przypisany tylko do scalonego duplikatu klienta.

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
  w okresie umowy = połączenie automatyczne, ale tylko gdy pod tym nazwiskiem
  u klienta jest jedna osoba (jeden kandydat). Imiennicy (różni kandydaci,
  audyt 19.10.2026) = zawsze propozycje, bo umowa w NEXUSIE bywa późniejsza
  niż praca i „jedyny w okresie” trafiał na obcą osobę; bliźniak z Traffita
  (dwa rekordy tej samej osoby) też czeka. Kilka albo tylko poza okresem =
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
- Ponowny import łączy kartę, gdy w NEXUSIE pojawi się pewny kontrakt, i nie
  odpina ani nie przepina kontraktu, który karta już ma (wybór DL wygrywa
  z późniejszym „pewnym”, audyt 19.10.2026). Przycisk „Połącz” widzi każdy,
  kogo wpuszcza trasa (`can_link` = `is_care_writer`, także osoba z puli).
- **Rozmowy opiekunów z Compassa** (`contractor_conversations`, decyzja Artura
  z 18.10.2026 „jak karty”): kotwica, gdy jest, ma pierwszeństwo; bez niej
  rozmowa łączy się po kliencie z `client_snapshot` (pusty = `contractors.
  current_client`), imieniu i nazwisku z `contractors.full_name` i dniu rozmowy
  w okresie umowy — te same reguły nazwiska i klienta co karty. Kolejność:
  (1) kontrakt karty tej osoby u tego klienta (połączonej przez import albo
  „Połącz” DL), gdy dzień rozmowy mieści się w umowie — dokładnie jeden;
  (2) dokładnie jeden kontrakt po nazwisku w okresie. Rozmowa musi mieć
  kontrakt (`care_conversations.contract_id NOT NULL`), więc niepewna nie jest
  zapisywana: czeka jako `conflict` w raporcie partii (same liczby, sekcja
  `conversations`), a ponowny import po połączeniu karty przez DL ją dociąga
  („idzie za kartą”). Osobnej listy rozmów do połączenia nie ma. Klient bez
  odpowiednika = `skip`.
- Rytm i opiekun z Compassa łączą się nadal WYŁĄCZNIE po kotwicy (rytmy
  w Compassie mają monitoring „inactive”, opiekunów przydziela pula opiekunów).

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
- **Mapa cieplna (makieta 19.10.2026, `TechHeatmap.tsx`)** zastąpiła tabelę
  działów i listę technologii z filtrem działu. Serwer daje całą macierz
  w `heatmap` tej samej odpowiedzi (`tech_map.heatmap`, czysta funkcja
  z testem): 40 najmocniejszych technologii (ekran pokazuje 12, reszta pod
  „Pokaż wszystkie”) × działy w kolejności `departments`. Komórka = źródła
  technologii w dziale; siła koloru = liczba RODZAJÓW źródeł (1, 2, 3+),
  obramowanie = otwarta rekrutacja działu, która jej wymaga („musi” albo
  „mile widziane”). „Bez działu” = źródła spoza działów (notatki, karty bez
  obszaru, rekrutacje bez HM z działu) — kolumna tylko, gdy coś w niej jest.
  Dymek komórki rozpisuje liczby źródeł. Nagłówek działu: menedżer, „nasi /
  w bazie”, ostrzeżenie „brak źródła 18 mies.”. Otwarte rekrutacje niosą
  dział (`open_jobs[].area`, dział hiring managera).
- **Działy bez sygnału schowane (decyzja Artura 20.10.2026,
  `heatmap-columns.ts`):** domyślnie tylko działy z komórką o źródle albo
  otwartej rekrutacji, albo z naszymi konsultantami; „Pokaż wszystkie działy
  (N)” odsłania resztę. „Bez działu” stoi zaraz po technologii, gdy ma więcej
  komórek z sygnałem niż wszystkie działy razem (remis = na końcu). Liczone
  z całej macierzy, nie z 12 widocznych wierszy. Powód: Nordea na prodzie —
  67 pustych działów i cały sygnał w „bez działu” na końcu tabeli 6350 px.
  Luka „dział bez źródła” dalej stoi w „Luki do dopytania”. Serwer bez zmian.
  Harness `/preview/hr-client-tech?state=many`.
- **Luki do dopytania**: dział bez źródła z 18 miesięcy (konsultant
  w projekcie liczy się jako świeże źródło), menedżer naszych konsultantów
  bez „podlega pod”, technologia z jednego źródła (świeża, nie z samych CV
  naszych — CV opisuje człowieka, nie stack; najwyżej 6). Te same pytania
  są w oknie zapisu rozmowy opieki (sekcja zwijana „Do dopytania u
  klienta”, mapa wczytuje się po rozwinięciu, nic się nie zapisuje). Na
  zakładce luka ma akcję: „komu podlega” → „Struktura u klienta”, reszta →
  „Dopisz notatkę o stacku” (tylko z prawem zapisu).
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
- **Autoodpowiedź** (`mail_ingest._is_auto_reply`: `Auto-Submitted` ≠ `no`,
  `X-Autoreply`/`X-Autorespond`, `Precedence: auto_reply|junk`, temat
  „Automatic reply:”, „Odpowiedź automatyczna:”, „Out of Office:”) traktowana
  jak wiadomość od administracji: w wątku dołącza bez otwierania, poza wątkiem
  pominięta — komunikat do kilkuset konsultantów nie zakłada fali spraw
  „jestem na urlopie” (audyt 19.10.2026). Zwrotki serwera poczty (postmaster,
  mailer-daemon) się nie liczą — zakładają sprawę przypiętą do komunikatu.
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
- Sprawy widzi uprawnienie „Sprawy”, admin i osoba przypisana do sprawy — od 22.10.2026
  w Opieka → „Do zrobienia” (`/people/cases` przekierowuje na `/care`).
- **Tablica (makieta 19.10.2026, `CasesBoard.tsx`)**: chipy obszarów
  z liczbą, „Na ten tydzień” i „Bez osoby” to filtry SERWERA
  (`GET /api/cases?week=true|unassigned=true` — lista ma limit 500, więc
  filtr w przeglądarce gubiłby sprawy). „Na ten tydzień” = otwarta sprawa
  z terminem najpóźniej w piątek tego tygodnia kalendarza firmy (też po
  terminie; w weekend — piątek, który minął), „Bez osoby” = otwarta bez
  przypisanej osoby. Liczniki `counts` liczy jedno zapytanie z grupowaniem
  po obszarze, w zakresie czytającego i wyszukiwania, bez filtrów chipów.
  Odpowiedź niesie `today` i `week_end`, z których ekran koloruje termin:
  po terminie (czerwony, liczy serwer), do piątku („dziś”, „jutro”, „za N
  dni” — żółty), później (szary), „bez terminu”. Karta: ikona źródła,
  kropka priorytetu, pasek listy kontrolnej, awatar osoby. „Zrobione” to
  wąska kolumna z liczbą z miesiąca, „Pokaż zamknięte” w niej.
- **„Weź”** na sprawie bez osoby (tylko obsługa skrzynki) to zwykłe
  `PATCH /api/cases/{id}` z `assignee_user_id` = czytający
  i `expected_updated_at` karty — ktoś wziął ją w międzyczasie = 409, nie
  ciche nadpisanie. Osobnej trasy nie ma; dzwonka do siebie też nie
  (`notify_assignee` pomija autora).
- Przypisanie sprawy innej osobie (`admin_case_assigned`) to dymek i mail „Czas
  i ludzie” z linkiem `/people/cases/{id}`. Tytuł sprawy (temat cudzego maila)
  do maila nie idzie — mail mówi tylko, że sprawa czeka. Licznik otwartych spraw
  przypisanych do czytającego (`GET /api/hr/counts`, `cases`) nie ma już zakładki w Ludziach.

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
  `welcome_mail` (`lifecycle_service.complete_task_by_key`). Ślad jest
  zapisywany (commit, stan `uncertain`) PRZED wysyłką i usuwany tylko przy
  pewnej odmowie — awaria po wysłaniu nie otwiera drugiego „Wyślij”
  (audyt 19.10.2026, jak kolejka komunikatów).
- **Przełącznik** `app_settings['consultant_welcome_mail']` jest domyślnie
  WYŁĄCZONY (brak wiersza = wyłączony): podgląd działa, wysyłka 409. Włącza go
  admin (karta maila, potwierdzenie) — pierwszą wysyłkę uruchamia Artur.
