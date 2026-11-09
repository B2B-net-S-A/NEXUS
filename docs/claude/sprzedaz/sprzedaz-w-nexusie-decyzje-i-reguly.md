# Sprzedaż w NEXUSIE (Atlas → NEXUS) — decyzje Artura 26–27.10.2026 i reguły modułu
<!-- indeks: sales_view/sales_edit, kartoteka firm osobna od clients, „Kogo znamy” z pełnym profilem, inne nazwy z CV, dziennik odczytu, daty per firma, powiązanie z klientem zamiast automatu, leady bez silnika, import Atlasa, edycja osób na mapie decyzyjnej, cele i KPI tygodniowe (oferty = etap) -->

Sekcja „Sprzedaż” zastępuje CRM Atlasa (D1 = budowa w NEXUSIE od nowa
i import danych). Propozycja z makietami M0–M4:
https://claude.ai/artifact/DwuZg8fxnWRg4NdXVgLTpe.

## Dostęp

- **Dwa uprawnienia, bez roli „Handlowiec”**: „Sprzedaż: podgląd” (`sales_view`)
  i „Sprzedaż: edycja” (`sales_edit`, pociąga podgląd). Domyślnie ma je tylko
  admin; handlowcom nadaje je ekran Osoby i role. Migracja 0600, katalog
  `permission_catalog.py` (na końcu), CHECK w `entrypoint.sh`.
- **Bez sekcji produktu** (jak „Ludzie”): każda trasa `/api/sales/**` ma
  `SalesViewUser` (odczyt) albo `SalesEditUser` (zapis) z
  `api/permission_access.py`. Menu: capability `nav.sales`.
- Edycja jest otwarta dla każdego z `sales_edit` (jak w Atlasie). **Zmianę
  opiekuna** robi obecny opiekun albo admin (`sales_gates.ensure_owner_or_admin`),
  aktywność usuwa jej autor albo admin.

## Kartoteka firm (D2)

- `sales_companies` jest **osobna od `clients`** — 9 tys. firm z Atlasa nie
  zalewa listy klientów. `client_id` łączy firmę z klientem NEXUSA (jeden klient
  = jedna firma sprzedaży, `ux_sales_companies_client`), `parent_company_id`
  to grupa kapitałowa.
- Duplikat (ten sam NIP albo nazwa kanoniczna `normalize_company_name`)
  **ostrzega (409), nie blokuje** — dwie spółki o tej samej nazwie istnieją.
- Szansa zawsze ma firmę (w Atlasie 115 szans było „sierotami” z samą nazwą).

## „Kogo znamy w firmie” (D3, D4)

- Panel liczy to samo co endpoint dla CRM (`integrations_companies.lookup_company_people`),
  prosto w bazie, z nazwą klienta powiązanego i NIP-em; plus liczby dla firmy
  matki i spółek zależnych.
- **D4: handlowiec widzi pełny profil kandydata** (kontakt, link do profilu) —
  decyzja Artura 26.10.2026, bez przełącznika i bez czekania na opinię IOD.
- **D3: daty zatrudnienia per firma.** Pierwsza szansa w firmie (i przycisk
  „Uzupełnij daty”) odpala w tle bieg dla osób „bez dat” z tej firmy
  (`services/sales/company_dates.py`, do 1000 osób, wyłącznik
  `EXPERIENCE_DATES_ON_DEMAND_ENABLED`, powtórka po 30 dniach). Bieg kosztuje
  (model AI) — na stagingu też. **„running” starszy niż 2 h jest porzucony**
  (wdrożenie restartuje kontener w trakcie biegu) — nie usuwaj tej reguły.

### Porządek w panelu, inne nazwy z CV i dziennik odczytu (etap P8, 09.11.2026)

- **Pięć osób na start.** API układa grupy (`priority_order` w
  `lookup_company_people`, przed cięciem do `limit`): najpierw role decyzyjne
  (`services/company_people_rank.py`, bez stażu, praktyk i juniorów), potem
  najświeżej dodani do bazy. Przy osobie dodanej ponad 3 lata temu znacznik
  „CV sprzed 3 lat”. Nowe pola idą tylko do Sprzedaży (`_CRM_EXCLUDE`).
- **„Inne nazwy z CV” na karcie**, tabela `sales_company_aliases` (0665):
  „Dołącz” (`joined`) dolicza nazwę do osób i szukania klienta, „Nie ta firma”
  (`rejected`) tylko przestaje podpowiadać, „Cofnij” kasuje decyzję. Zapis
  `SalesEditUser`. Nazwy dołączone czyta serwer (`extra_names`), poza limitem
  10 nazw z API dla CRM. Bez modelu AI i bez kolejki. Wariant powstaje na dwa
  sposoby. Pierwszy: nazwa z CV zaczyna się od nazwy karty bez końcówek typu
  „Bank Polska”, „S.A.”; gdy z karty zostaje jeden wyraz („Nordea Bank Abp” →
  „nordea”), dalszy ciąg nazwy z CV może mieć tylko takie końcówki, bo sam
  pierwszy wyraz nie odróżnia firmy („Credit Agricole” to nie „Credit Suisse”,
  „Narodowy Bank Polski” to nie „Narodowy Fundusz Zdrowia”). Wpis z kilkoma
  częściami to lista firm, nie wariant. Drugi: most w jednym wpisie
  („mBank (BRE Bank S.A.)”), od trzech osób i gdy co najmniej połowa osób z takimi
  wpisami przy tej nazwie wskazuje tę kartę, bo pośrednik („7N / mBank”) ma
  wielu klientów.
  Freelance, NDA, szkoły i nasza firma nigdy nie są wariantem. Nazwa z własną
  kartą nie daje się dołączyć (409), bo duplikat to scalenie kart.
- **Klient:** ręczne powiązanie `client_id` ma pierwszeństwo, potem NIP, potem
  nazwa z aliasami klienta i nazwami dołączonymi na karcie.
- **Karta naszej firmy** nie pokazuje listy osób ani wariantów, a spółka z naszą
  nazwą nie wchodzi do liczb grupy (`company_aliases.OWN_COMPANY_NAMES`).
- **Prefiltr po nazwach to jeden `LIKE ANY`** (`_company_prefilter`): osobne
  `EXISTS` na każdą nazwę to 14 wariantów w 38,2 s przy budżecie 8 s. Nie wracaj
  do `OR` po nazwach.
- **Dziennik odczytu** to `activities` przez `record_candidate_audit`, akcja
  `sales_company_people_read`, same identyfikatory. Tylko pełna lista osób;
  liczby grupy i pusta lista nie są odczytem. Napis „Odczyt zapisany w dzienniku”
  wisi na `read_logged` z odpowiedzi, czyli na udanym zapisie. Akcja jest poza
  alarmem o pobieraniu (decyzja z 07.11.2026).

## Szanse

- Reguły cyklu życia z Atlasa (`services/sales/lifecycle.py`): etap z wynikiem
  ustawia status i daty, prawdopodobieństwo idzie za etapem, **kwalifikacja
  ustawia się raz** (cofnięcie jej nie czyści), wartość = MRR + jednorazowa
  (jak w Atlasie — nie mnożymy przez miesiące bez decyzji).
- Ruch po etapach wyłącznie przez `POST /api/sales/opportunities/{id}/move`.
- **Historia zmian** (jak w Atlasie): `sales_opportunity_events` (0618), jeden
  wiersz na zmienione pole — kto, kiedy, stara i nowa wartość jako tekst (id
  etapu/opiekuna/firmy; nazwy dokłada odczyt `GET …/{id}/history`). Każda nowa
  ścieżka, która zmienia szansę, woła `services/sales/history.py`
  (`record_created`, `snapshot` + `record_changes`, `record`); dziś: założenie,
  zamiana leada, `/move`, PATCH, archiwum, przywrócenie, scalenie firm, mapa decyzyjna.
  **Import z Atlasa nie zapisuje zdarzeń** — historia zaczyna się od pracy
  w NEXUSIE. Wejście na etap to `field = 'stage_id'` (także `kind='created'`);
  z tego samego źródła liczy się KPI ofert — nie zakładaj drugiej tabeli etapów.

## Wygrana → Delivery (decyzja 27.10.2026)

- **Tylko powiązanie z klientem NEXUSA** (`/api/sales/clients/link/{company_id}`)
  i zakładka „Sprzedaż” w karcie klienta (pod „Więcej”, `sales_view`).
  **Nie** zakładamy klienta, nie przypisujemy DL, nie zakładamy rekrutacji ani
  nie wysyłamy dzwonka — rekrutacje DL zakłada jak dziś (bramka gotowości
  rekrutacji i tak nie przepuściłaby samych ról z szansy).
- Wyszukiwarka klientów dla Sprzedaży zwraca tylko id i nazwę (handlowiec nie
  ma podglądu Delivery) i szuka też po nazwie bez formy prawnej.

## Leady (decyzja 27.10.2026)

- **Bez silnika.** Skan ogłoszeń z Atlasa celował w klientów Elevate (firmy
  spoza IT szukające back-office) i odrzucał zatrudniających programistów —
  odwrotnie niż body leasing. Skrzynka = import otwartych leadów z Atlasa
  i wpisy ręczne.
- **Lead z firmy, która jest już klientem NEXUSA, nie powstaje** (409) —
  popyt u klienta idzie do jego DL (decyzja 22.10.2026); dlatego import
  pomija też `compass_signals` („Od konsultantów”).

## Import z Atlasa

- `backend/scripts/import_atlas_sales.py` — połączenie **tylko do odczytu**
  z `ATLAS_DATABASE_URL`, domyślnie na sucho, `--apply` zatwierdza.
  Idempotentny po `external_ref` / `fingerprint`; drugi bieg nie nadpisuje
  opiekuna ani statusu leada zmienionego w NEXUSIE.
- Firmy-nazwiska bez odwołań odpadają, z odwołaniami dostają tag
  „atlas: do przejrzenia”. Raport to same liczby (repo i Actions są publiczne).
- Pliki z Supabase Storage przenosi osobny krok (wymaga klucza storage Atlasa).
- **Produkcja: workflow, nie SSH** (decyzja Artura 27.10.2026). Kolejność:
  1. sekret repo `ATLAS_DATABASE_URL` (Atlas tylko do odczytu; dla plików
     także `ATLAS_SUPABASE_URL` i `ATLAS_SUPABASE_SERVICE_KEY`) — wpisuje Artur;
  2. „Coolify set env” z `value_from_secret` (dla każdej zmiennej), na końcu
     Deploy — w oknie wdrożeń;
  3. „Coolify Ops” → `action=atlas-import`, `atlas_import_mode=dry-run`,
     przegląd liczb, potem `apply`; pliki: `files-dry-run`, potem `files-apply`.
  Zadanie Coolify odpala się co minutę, więc skrypt dostaje `--lock` i drugie
  odpalenie nic nie robi. Przy błędzie log pokazuje tylko typ wyjątku
  (traceback w `<lock>/error.log` w kontenerze). Gdy bieg nie skończy się
  w 65 minut, **nie odpalaj `apply` drugi raz**, zanim nie sprawdzisz panelu
  Coolify — proces w kontenerze może dalej biec.

## Po audycie importu (decyzje Artura 28.10.2026)

- **Uprawnienia handlowcom dopiero po poprawionym imporcie.** Drugi bieg
  importu odświeża wiersze nietknięte w NEXUSIE; wiersz zmieniony po imporcie
  (`updated_at > synced_at`) zachowuje etap, status, tytuł, tagi, wykonanie
  i przypisanie zadania. Opiekun i przypisanie zadania są tylko uzupełniane
  (`COALESCE`), nigdy kasowane.
- **Zadanie przy szansie należy do opiekuna szansy** (reguła Atlasa, liczona
  przy imporcie). Lista „Zadania” obejmuje też telefony z terminem.
- **Opiekun z Atlasa bez konta = `owner_label`.** Etykietę przypisuje do konta
  admin (Firmy → „Opiekunowie z Atlasa”); nazwisk nie ma w kodzie ani w logach.
- **Osoba w kilku firmach**: `sales_company_contacts` (rola, stanowisko,
  obecna/była); `sales_contacts.company_id` to firma główna.
- **Notatki Fireflies z przygotowań kandydatów** („Przygotowanie do spotkania
  z Klientem…”) nie wchodzą do Sprzedaży — to dane kandydatów; import je usuwa.
- **Leady z job boardów** (silnik odrzucony 27.10) nie są importowane.
- **Historia bez utraty**: transkrypcje Fireflies przy szansach jako
  spotkania, oferty jako pliki w folderze „Oferty (Atlas)”, daty plików ze
  źródła. Proces zakupowy i produkty — tylko odczyt na karcie szansy; osoby na
  mapie decyzyjnej edytuje handlowiec (sekcja niżej).
- **Scalanie firm** przenosi wszystko i archiwizuje źródło (nic nie kasuje).

## Mapa decyzyjna: edycja osób (decyzja Artura 02.11.2026)

Handlowcy zgłosili po przejściu z Atlasa, że na mapie brakuje notatek i kontaktu
i nie mają jak tego uzupełnić. Propozycja z makietami:
https://claude.ai/artifact/M6mS1dYC9DwcPe3BDBEv7j.

- **Okno, nie wiersz** (`DecisionPersonDialog`, jak „Edytuj kontakt”): kolumna
  osób przy 1280 px ma 280 px i formularz w wierszu obcinał pola.
- **Trasy** za `SalesEditUser`: `POST /api/sales/opportunities/{id}/decision-map`,
  `PATCH` i `DELETE …/decision-map/{key}`. Pola i limity jak w Atlasie
  (`extra=forbid`), LinkedIn tylko http(s). Logika: `services/sales/decision_map.py`.
- **Klucz osoby to skrót treści wpisu** (`motion.entry_keys`), bo wpisy z Atlasa
  nie mają id. Każda zmiana zmienia klucz, więc poprawka ze starego ekranu dostaje
  409 zamiast nadpisać cudzą. Zapis trzyma blokadę wiersza szansy: bez niej dwa
  równoległe zapisy listy w JSON-ie gubią jeden z nich.
- **Poprawka wysyła tylko zmienione pola**, bo część adresów LinkedIn z Atlasa
  nie przechodzi walidacji i nie może blokować dopisania notatki.
- **Mapa uzupełnia puste pola kontaktu** (telefon, mail, LinkedIn, notatka), nigdy
  ich nie nadpisuje i nie zakłada nowego kontaktu; stanowiska nie przenosi.
  Telefon jest pusty dopiero bez komórki. Wartość dłuższa niż kolumna kontaktu
  i kontakt w archiwum: tylko mapa. Uzupełnienie to osobny wiersz historii
  (`decision_map_contact`).
- **Pole z kontaktu to podpowiedź w formularzu** (`from_contact`), nie wartość:
  inaczej każdy zapis kopiowałby je na mapę.
- **Historia**: jeden wiersz na operację, `field = 'decision_map'`, w starej
  i nowej wartości nazwisko i zmienione pola. Dodanie ma pustą starą wartość,
  usunięcie pustą nową.
- **Ponowny import**: `custom_fields` szansy i `linkedin_url` kontaktu są
  w `PROTECTED`. Szansa zmieniona w NEXUSIE z jakiegokolwiek powodu nie dostaje
  więc z Atlasa także MEDDIC ani produktów.
- **Panel w lejku Fabryki IT** (`atlas-it-factories`) pokazuje się też bez danych
  z Atlasa, z „Dodaj osobę”. W innym lejku dodać można tylko, gdy szansa ma już
  mapę (`decision_map_enabled`); nowa osoba w innym lejku to 409.

## Cele i KPI tygodniowe (decyzja Artura 28.10.2026: „Tak, bez Ofert”)

- Zakładka „Podsumowanie”: tabela 8 tygodni na osobę (spotkania, leady,
  „Oferty (etap)”) ze światłami i krzywa WON netto MRR względem celu firmy.
  Liczy `services/sales/kpi.py`, API `GET /api/sales/kpi` (podgląd Sprzedaży).
- **Definicje 1:1 z Atlasa** (`team_kpi.py`, `sales_dashboard_service.py`):
  spotkania = `meeting` przy szansach (z Fireflies) wg opiekuna szansy, bez
  zarchiwizowanych, plus wydarzenia Outlooka (`msgraph-event`) wg osoby, która
  je zsynchronizowała, bez odwołanych; znaczniki ≤ 15 min od poprzedniego
  liczą się raz. Leady = `qualified_at` w tygodniu. Światła: zielone ≥ cel,
  żółte ≥ 50%, czerwone poniżej; **bez celu bez światła** (Atlas dawał zielone).
- **„Oferty” = wejście szansy na etap `offer-sent`**, bo NEXUS nie ma ofert;
  kilka szans jednej firmy w tygodniu liczy się raz (Atlas liczył oferty per
  firma). Źródło: historia zmian szansy (`sales_opportunity_events`,
  `field='stage_id'`: założenie, ruch `/move`, zamiana leada) — jedna tabela
  z historią, bez osobnego dziennika etapów. **Historia zaczyna się od
  wdrożenia 0618**, import z Atlasa jej nie pisze — tygodnie sprzed niej mają 0
  i ekran to mówi.
- **WON MRR bez body leasingu** (`service_line` albo tag „Body leasing”), netto
  = MRR × marża / 100, jak w Atlasie; wygrana bez marży liczy się jako 0
  i ekran podaje ich liczbę. Postęp celu marży osoby to ta sama suma dla jej
  szans, bez okresu.
- **Cele ustawia admin** (przycisk „Cele”, `PUT /api/sales/kpi/targets/…`,
  bramka „Sprzedaż: edycja” + sprawdzenie admina). Tabela `sales_targets`:
  wiersz bez `user_id` to cel firmy (w Atlasie stała w kodzie). Kwot celów nie
  ma w kodzie ani w testach.
- Tygodnie (od poniedziałku) i miesiące w kalendarzu firmy, nie w UTC.

## Uwagi handlowców (decyzje Artura 02.11.2026)

- **Tablica szans ma wszystkie etapy**, zamknięte na końcu (`boardStages`), jak
  w Atlasie. Liczby nad tablicą dalej liczą tylko otwarte. Fabryki IT nie mają
  etapu „Niezakwalifikowany” — w Atlasie też go nie było.
- **Oferty = lista szans na etapach `offer-sent` i `tender-submitted`**
  (`offers_only`), bez nowej tabeli. Generator ofert dalej jest poza zakresem.
- **Spotkania = `GET /api/sales/activities/meetings`**: wszystkie aktywności
  `meeting`, notatka skrócona do 300 znaków, bo transkrypcja bywa bardzo długa.
  Nowe nagrania przychodzą z transkryptów Teams, nie z Fireflies (niżej).
- **Filtry szans:** Model (`service_line`) i data utworzenia w kalendarzu firmy,
  pod przyciskiem „Filtry”, bo przy 1280 × 720 kolejny rząd pól zabiera miejsce
  tablicy. Szukanie po NIP tylko dla frazy z samych cyfr: „10CLOUDS” nie może
  szukać po „10”.
- **Mapa decyzyjna:** puste pola osoby uzupełnia jej kontakt, wpis z Atlasa ma
  pierwszeństwo. Dalej tylko do odczytu; edytor to osobne zadanie.
- **Kontakt z zakładki Kontakty:** firma obowiązkowa, jak w Atlasie.

## Transkrypty Teams przy spotkaniach (decyzje Artura 02.11.2026)

`services/sales/meeting_transcripts.py`, tabela `sales_meeting_transcripts` (0628),
wyłącznik `SALES_TEAMS_TRANSCRIPTS_ENABLED`. Konfiguracja Microsoft:
`docs/teams-prep-setup.md`.

- **Osobna grupa handlowców, bez automatycznego nagrywania.** Nie dopisuj ich do
  `NEXUS-Meetings-Scope`: tamta grupa nagrywa każde spotkanie i daje zapis do
  kalendarza. Handlowiec sam włącza transkrypcję, więc brak transkryptu jest normą.
- **Tylko spotkania, których handlowiec jest organizatorem,** i tylko nowe: bez
  pobierania historii. Klucz to `iCalUId`, bo jedno spotkanie bywa przy kilku firmach.
- **Adres spotkania czyta token handlowca podczas synchronizacji**, osobnym GET-em
  dla wiersza z kolejki. Nie dokładaj `onlineMeeting` do `EVENT_SELECT`: nie jest
  potrzebny do reszty, a zmiana wymusza pełny odczyt kalendarzy wszystkich skrzynek.
- **Spotkanie cykliczne ma wspólną listę transkryptów**, więc do wystąpienia należą
  tylko te utworzone w jego czasie (`within_meeting`).
- **Spotkanie odwołane albo oznaczone jako prywatne** zabiera też transkrypt.
- **Podsumowanie (F40) jest dodatkiem:** lista czyta je z wiersza, awaria modelu
  zostawia sam transkrypt, najwyżej 3 próby na spotkanie.

## Poza zakresem (świadomie)

Generator ofert, P&L sprzedaży, skan ogłoszeń/LinkedIn/prasy, synchronizacja
poczty i kalendarza M365 na żywo (historia z Atlasa jest), Fireflies na żywo
(nowe nagrania będą z transkryptów Teams),
kanał przetargów, eksport CSV (najpierw limit i dziennik odczytów), „Kogo
możemy dać od ręki” (Talent Radar na rolach), metryka „nowi klienci na
spotkaniach” z KPI Atlasa.
