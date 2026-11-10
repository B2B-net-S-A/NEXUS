# Sprzedaż w NEXUSIE (Atlas → NEXUS) — decyzje Artura 26–27.10.2026 i reguły modułu
<!-- indeks: sales_view/sales_edit, kartoteka firm osobna od clients, „Kogo znamy” z pełnym profilem, inne nazwy z CV, dziennik odczytu, daty per firma, powiązanie z klientem zamiast automatu, leady bez silnika, import Atlasa, edycja osób na mapie decyzyjnej, cele i KPI tygodniowe (oferty = etap), Oferty: kroki po wysłaniu, „Do decyzji”, „Odłóż do…”, „Przejmij” -->

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
- **„Inne nazwy z CV” na karcie**, tabela `sales_company_aliases` (0671):
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

## Ostatni dotyk i archiwizacja w cieniu (decyzje Artura 09.11.2026)

- **Jedna definicja: `services/sales/touch.py`**, używają jej lista i karta szansy
  (`last_touch_at`), Podsumowanie i automat. Były trzy (`summary.py`, kafelek,
  filtr) i dawały inne liczby dla tej samej szansy, dlatego front niczego już
  nie liczy sam.
- **Dotyk** to najpóźniejsza chwila w przeszłości spośród: aktywność szansy albo
  jej firmy (odbyty telefon, notatka, mail w obie strony, odbyte i nieodwołane
  spotkanie, zrobione zadanie w `done_at`), `last_activity_at` bez śladów joba,
  `created_at` szansy jako dolna granica.
- **Nie są dotykiem:** `updated_at` (zapisuje go import), otwarte zadanie,
  zaplanowany telefon i przyszłe spotkanie: to zamiar, nie praca. Telefon z terminem
  bez `done_at` jest zaplanowany także wtedy, gdy ma `occurred_at`, bo import wpisuje
  tam datę założenia. Telefon bez terminu to wpis historii.
- **Ślad joba Atlasa:** wiersz z importu z `last_activity_at` o 06:20:00 UTC
  (okno jednej sekundy). Zmierzone na kopii z 08.11: 104 z 250 otwartych z importu,
  431 w całej tabeli, 0 o 04:20 i 05:20 UTC ani o 06:20 w Warszawie.
- **Odbiór (kopia 08.11, stan na 09.11 00:00, 320 otwartych):** ponad 30/60/90 dni
  bez dotyku = 223/195/108. Szacunek 231/207/118
  liczono na 08.11 i z `created_at` tylko jako zastępstwem, bez zrobionych zadań.
- **Automat w trybie cienia** (`tasks/sales_archive_shadow.py`, kontener worker,
  raz dziennie o 04:40, wyłącznik `SALES_ARCHIVE_SHADOW_ENABLED`): liczy, co by
  zarchiwizował (otwarta, bez przyszłego kroku, dotyk ponad 90 dni, poza Fabrykami
  IT i Przetargami, bez `top22`, bez `keep_open_until` w przyszłości) i zapisuje
  jedną linię logu z samymi liczbami. Transakcja jest tylko do odczytu, bo progi
  trzeba najpierw zobaczyć na danych, a archiwizacja dotyka pracy handlowców.
  Włączenie prawdziwej archiwizacji to osobna decyzja.
- **Ponowny import** nie nadpisuje `keep_open_until`, `archived_reason` ani
  rodzaju aktywności w wierszu zmienionym w NEXUSIE (`PROTECTED`).

## Wygrana → Delivery (decyzja 27.10.2026)

- **Tylko powiązanie z klientem NEXUSA** (`/api/sales/clients/link/{company_id}`)
  i zakładka „Sprzedaż” w karcie klienta (pod „Więcej”, `sales_view`).
  **Nie** zakładamy klienta, nie przypisujemy DL, nie zakładamy rekrutacji ani
  nie wysyłamy dzwonka — rekrutacje DL zakłada jak dziś (bramka gotowości
  rekrutacji i tak nie przepuściłaby samych ról z szansy).
- Wyszukiwarka klientów dla Sprzedaży zwraca tylko id i nazwę (handlowiec nie
  ma podglądu Delivery) i szuka też po nazwie bez formy prawnej.

## Leady (decyzja 27.10.2026)

> 09.11.2026: research prasy i stron firm robi bot (Grok Bot), a NEXUS przyjmuje jego
> raport: `sygnaly-grok-bot.md`. Skan ogłoszeń i LinkedIna dalej odpada.

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
  przy imporcie i przy zapisie w NEXUSIE, `_default_assignee`). Jawne
  przypisanie wygrywa; bez szansy albo bez aktywnego opiekuna zadanie zostaje
  u autora. Lista „Zadania” obejmuje też telefony z terminem.
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
  Od 10.11.2026 zakładka ma sekcje „W toku” i „Do decyzji” (sekcja na końcu pliku).
- **Spotkania = `GET /api/sales/activities/meetings`**: wszystkie aktywności
  `meeting`, notatka skrócona do 300 znaków, bo transkrypcja bywa bardzo długa.
  Decyzja przy wierszu (przypnij, załóż szansę, klient NEXUSA):
  `outlook-handlowcow-w-sprzedazy.md`.
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

### Podsumowanie na karcie szansy i mail do klienta (decyzje Artura 09.11.2026)

Logika wysyłki: `services/sales/meeting_client_mail.py`, trasy w `api/sales_activities.py`,
kolumny 0677 przy `sales_meeting_transcripts`.

- **Nagrywanie włącza handlowiec sam w Teams.** Bez polityki automatycznego nagrywania
  i bez `NEXUS-Meetings-Scope`; kroki w M365: `docs/teams-prep-setup.md`, sekcja
  „Transkrypty spotkań handlowców”.
- **Oś szansy pokazuje podsumowanie bez rozwijania wiersza** (`MeetingSummary`
  w `OpportunityTimeline.tsx`): spotkanie przypięte do szansy i spotkanie jej firmy.
  Aktywność nie ma powiązania z leadem, więc spotkanie sprzed szansy z leada jest na osi
  jako wpis firmy. `GET …/timeline` dokłada `transcript_activity_id`, `transcript_summary`,
  `can_send_client_summary` i `client_mail_sent_at`; transkrypt szuka po wszystkich
  sklejonych wpisach wiersza, bo wierszem bywa kopia z Fireflies.
- **Szkic dla klienta to osobny wynik modelu (F46, `sales_meeting_client_summary`),**
  nie przeróbka F40: ustalenia i następne kroki w formie „Państwo”, bez kwot, stawek,
  marż, kandydatów i spraw wewnętrznych. Szkic leży przy transkrypcie (`client_summary`),
  więc ponowne otwarcie okna nie woła modelu. Awaria modelu daje puste pole i zwykłą
  wysyłkę, nie błąd. Okno ostrzega przed kwotami i słowami o stawkach w treści,
  ale nie blokuje: decyduje handlowiec.
- **Wysyła organizator spotkania albo admin, za `SalesEditUser`,** z własnej skrzynki
  (`/me/messages` + `/send`, stopka z Outlooka). Organizatora wyznacza
  `sales_meeting_transcripts.organizer_user_id`, bo transkrypt pobieramy tylko dla
  spotkań, których handlowiec jest organizatorem. Skrzynka bez `Mail.Send` w
  `scopes_granted` dostaje 409 z prośbą o ponowne połączenie.
- **Adresaci domyślnie:** uczestnicy z `calendar_events.attendees` bez naszych domen
  i bez właściciela skrzynki (`matcher.external_addresses`); da się ich zmienić.
- **Bez wysyłki do adresów z bazy kandydatów, także dla admina (422).** Najpierw
  bramka organizatora (403/404), potem adresy, a odmowa ich nie wymienia: inaczej każdy
  z „Sprzedaż: edycja” sprawdzałby wpisywaniem, kto jest w bazie kandydatów. Ta ścieżka
  używa `GraphClient(..., sales_ok=True)`, żeby wysłać ze skrzynki handlowca bez dostępu
  do kandydatów; bramka kandydatów z `m365/sender.py` zostaje nietknięta, a korespondencja
  z kandydatem i tak nie idzie na oś firmy.
- **Jedna wysyłka na klucz:** okno nadaje `request_id`, serwer zapisuje go pod blokadą
  wiersza transkryptu przed wywołaniem Graph. Drugi klik z tym samym kluczem dostaje 409.
  Odmowa Graph (4xx albo brak szkicu) zwalnia klucz (502, nic nie wyszło); błąd po
  utworzeniu szkicu zostawia klucz i mówi „sprawdź Wysłane” (409), bo mail mógł wyjść.
- **Mail ląduje na osi szansy** jako `email`/`out` z `external_source='msgraph-mail'`
  i `internetMessageId`, więc kopia z folderu Wysłane z synchronizacji skleja się z nim
  (ten sam klucz co `ux_sales_activities_outlook`). Spotkanie przypięte idzie do swojej
  szansy, spotkanie firmy do karty, z której wysłano (tylko szansa tej samej firmy).
  Synchronizacja nie skraca treści: podgląd z Graph nie zastępuje dłuższej treści maila
  (`outlook_activities.record`).

## Poza zakresem (świadomie)

Generator ofert, P&L sprzedaży, skan ogłoszeń/LinkedIn/prasy, synchronizacja
poczty i kalendarza M365 na żywo (historia z Atlasa jest), Fireflies na żywo
(nowe nagrania będą z transkryptów Teams),
kanał przetargów, eksport CSV (najpierw limit i dziennik odczytów), „Kogo
możemy dać od ręki” (Talent Radar na rolach), metryka „nowi klienci na
spotkaniach” z KPI Atlasa.

## Krok, zapis rozmowy i przeciąganie (decyzje Artura 09.11.2026)

- **Jedna definicja kroku: `services/sales/next_step.py`**, obok `touch.py`. Krok to
  najbliższe otwarte zadanie albo telefon z terminem od początku dzisiejszego dnia firmy
  (przy szansie albo przy firmie bez szansy) lub przyszłe, nieodwołane spotkanie firmy.
  „Po terminie” jest osobno i liczy tylko zaległości tej szansy. Telefon bez terminu
  (import historii) krokiem nie jest.
- **Ostatni kontakt** bierze chwilę dotyku z `touch.py`, bez zadań i bez wpisów
  systemowych Pipedrive („This deal was converted to a lead”, wizyty na stronie).
- **Czerwień tylko po wdrożeniu:** `SALES_STEP_RULES_SINCE`, lejek Sprzedaż, szansa
  założona albo ruszona (własna aktywność, zdarzenie z historii) od tej daty. Mail do
  samej firmy szansy nie budzi. Reszta zostaje szara, bo bez tego czerwone byłoby
  prawie wszystko.
- **Zapis rozmowy:** `POST /api/sales/opportunities/{id}/calls`, wynik w
  `sales_activities.outcome`, żeby dało się go policzyć. Krok zakłada osobno okno
  „Co dalej i kiedy” zwykłym zadaniem, a zadanie dostaje opiekun szansy.
- **„Nie kontaktować”:** `sales_contacts.do_not_contact_at`; osoba z mapy bez kontaktu
  ma flagę na wpisie mapy, bo mapa nie zakłada kontaktów. Numer i mail przestają być
  klikalne, kolejny wpis rozmowy dostaje 409. Cofnięcia sprzeciwu na ekranie nie ma.
- **Oś firmy i szansy:** `GET /api/sales/activities/timeline`. Jedno zdarzenie jeden
  wiersz (`services/sales/timeline.py`): spotkania firmy do 15 minut od siebie,
  podsumowanie Fireflies do 3 godzin po spotkaniu, ta sama treść tego samego dnia
  (cała, ucięta kopia też się liczy), a dwa maile tylko o tym samym temacie, bo wiele
  zaczyna się tym samym nagłówkiem adresatów.
  Otwartego zadania się nie skleja, bo zniknęłoby „Zrobione”.
- **Przeciąganie** tylko między etapami bez wyniku, przez `/move`; wygraną i przegraną
  zamyka karta. „Cofnij” tylko, gdy oba etapy, źródłowy i docelowy, leżą przed
  linią `qualifies`, bo powrót na tę linię ustawiłby `qualified_at` i zawyżył KPI.
- **Zmiana opiekuna** wybiera z `GET /api/sales/opportunities/owner-candidates`: aktywne
  konta z „Sprzedaż: edycja”. `GET /api/users` odpada, bo handlowcy bywają „Pracownikami”,
  a ta rola dostaje na niej 403; filtr lejka zna tylko osoby z otwartą szansą.

## Mój dzień (decyzje Artura 09.11.2026)

Pierwsza i domyślna zakładka: `/sales` przekierowuje od razu na `/sales/my-day`, Szanse
mają własny adres `/sales/opportunities`, a `/sales` z parametrami (stare `?bezruchu=1`,
`?opiekun=`) nadal prowadzi do Szans. Logika: `services/sales/my_day.py`, trasa
`GET /api/sales/my-day` (`SalesViewUser`), zawsze dla zalogowanej osoby: przełącznika
osoby, paska postępu i blokady za brak skrzynki celowo nie ma.

- **Spotkania dziś:** spotkania tej osoby z kalendarza firmy, bez odwołanych i automatów.
  Jedno wydarzenie to jeden wiersz po `external_id`; bez `external_id` każde osobno.
- **Odpowiedz:** ostatni mail przychodzący z 21 dni przy firmie z jej otwartą szansą, po
  dwóch dniach roboczych bez reakcji. Reakcją jest mail wychodzący, odbyty telefon,
  spotkanie albo krok zaplanowany po tym mailu, także na drugiej karcie tej samej firmy
  (ten sam mail i to samo pierwsze słowo nazwy). Auto-odpowiedzi i zaproszenia nie liczą
  się ani jako mail, ani nie zasłaniają wcześniejszego prawdziwego (`AUTO_SUBJECT`).
  Listę przedrostków trzymaj przy tym, co jest w `sales_activities` (Outlook pisze
  „Automatyczna odpowiedź:” i „Informacja o nieobecności”). Przedrostki kalendarza wymagają
  dwukropka, bo „Zaproszenie do złożenia ofert” to prawdziwy mail od klienta.
- **Zaległe:** jej zadania i telefony sprzed dziś do 60 dni, starsze jako jeden licznik.
- **Oferty:** etap `offer-sent`, dotyk z `touch.py` starszy niż 14 dni i bez kroku
  z `next_step.py`, od największej; dziesięć i „Pokaż pozostałe”. Zaplanowany krok
  zdejmuje ofertę i wątek z kolejki, bo inaczej „Zaplanuj” nie miałoby widocznego skutku.
- **Osoba w wierszu:** kontakt z aktywności, główny szansy, kontakty szansy, historia
  firmy, potem pozostałe kontakty firmy; pierwsza z numerem. Osoba ze sprzeciwem,
  z archiwum i firma „Nie kontaktować” nie są proponowane. Każdy kandydat musi należeć
  do firmy albo szansy (lustro `calls._contact_in_company`), bo historia niesie też
  naszych pracowników z kalendarza, a zapis rozmowy z taką osobą kończy się 422.
- **„Uzupełnij numer”** nie dopisze numeru osobie ze sprzeciwem, także pod „nową osobą”
  o tej samej nazwie w firmie (409 w `sales_contacts.py`). Ponowny zapis tego samego
  numeru przechodzi, bo formularz kontaktu wysyła wszystkie pola.
- **Zaległy krok przekłada osoba przypisana**, nie tylko autor: po imporcie 118 ze 149
  otwartych zadań ma innego autora niż wykonawcę.
- **Telefon przy firmie bez szansy:** `POST /api/sales/companies/{id}/calls`, ten sam wynik
  i sprzeciw co na karcie szansy; zaległe zadanie zamyka się razem z zapisem rozmowy.
- **Poranny mail:** sekcja dla kont z „Sprzedaż: podgląd” (handlowcy to często „Pracownicy”,
  poza rolami skrótu), bez kwot i numerów. Admin bez ról skrótu dalej go nie dostaje.
  Własny wyłącznik wisi na tej samej regule co wysyłka (`daily_digest_email.receives_digest`),
  bo każdy, kto dostaje mail, ma móc go sobie wyłączyć.
  Pusty skrót nie wychodzi.
- **Rama:** tytuł i zakładki w jednym rzędzie od 1280 px, opis i akcje w niskiej linii
  pod spodem. Karta firmy i szansy bez zakładek zostają przy `PageHeader`.

## Porządek po imporcie: lista Zadania (09.11.2026)

- **Lista „Zadania” nie pokazuje sierot** (`services/sales/task_scope.py`): otwartej
  pozycji przy szansie wygranej, przegranej albo w archiwum. Na kopii z 08.11 to było
  134 ze 174. Pozycja przy firmie bez szansy zostaje. Zakładka „Zrobione” bez zmian.
- **`scripts/sales_cleanup.py`** zamyka pozycje z importu przypisane do wskazanego konta
  i bez przypisania, a szanse po opiekunie, który odszedł, przekazuje przez
  `services/sales/history.py`. Domyślnie na sucho (`READ ONLY`). `--apply` wymaga licznika
  z biegu na sucho (`--expect-close`) i tylko po „tak” Artura. Nie rusza etapu, statusu
  ani archiwum szans. `--pipeline-key` zawęża listę i przekazanie do jednego lejka
  (10.11.2026), bo konta Fabryk IT i stare szanse sprzedażowe po tej samej osobie
  przejmują różne osoby; nieznany klucz kończy bieg odmową.
- **Zamknięcie datą `created_at`, nie „teraz”**, bo zrobione zadanie jest dotykiem szansy
  i firmy (`touch.py`), a sprzątanie nie jest pracą handlowca. Na kopii z 08.11 data „teraz”
  przesunęłaby dotyk 2 otwartych szans. Gdy dotyk miałby się przesunąć, `--apply` odmawia.

## Oferty: kroki po wysłaniu i „Do decyzji” (decyzje Artura 10.11.2026)

Logika: `services/sales/offer_steps.py` i `services/sales/offers.py`, trasy w
`api/sales_offers.py`: `GET /api/sales/offers` (`SalesViewUser`) i
`POST /api/sales/opportunities/{id}/take-over` (`SalesEditUser`). Bez migracji.

- **Trzy kroki po wejściu na `offer-sent`:** dzień 3 potwierdzenie odbioru, dzień 14
  pytanie o decyzję, dzień 30 rozstrzygnięcie. Termin rano w kalendarzu firmy, z weekendu
  i święta na najbliższy dzień roboczy. To zwykłe zadania opiekuna ze znacznikiem
  `external_source = 'offer-step'`: da się je przełożyć, odhaczyć i usunąć, a moduł niczego
  sam nie wysyła. Autorem jest wykonawca, bo zadanie usuwa tylko autor, a krok ma dać się
  usunąć opiekunowi także wtedy, gdy szansę przesunął ktoś inny (kto przesunął, mówi
  historia szansy). Bez aktywnego opiekuna kroki dostaje osoba, która przesunęła.
- **Kroki powstają tylko z wejścia na etap** (`/move` albo założenie szansy od razu na
  etapie). Oferty, które były na etapie wcześniej, nie dostają ich wstecz. Przetarg
  (`tender-submitted`) ma własne terminy i kroków nie dostaje. Powrót na etap nie dubluje
  kroków, dopóki któryś z poprzednich jest otwarty.
- **To nie są sekwencje do zimnego kontaktu** (odłożone 09.11.2026 do opinii prawnej).
  Dotyczą oferty wysłanej osobie, z którą trwa rozmowa. Nie rozszerzaj ich na leady ani
  na pierwszy kontakt.
- **„Do decyzji”** to pozycja bez ruchu ponad 30 dni (dokładnie 30 dni to jeszcze „W toku”)
  albo pozycja opiekuna, który nie pracuje już w Sprzedaży: konto nieaktywne albo bez
  „Sprzedaż: podgląd” i „Sprzedaż: edycja”. Ta druga reguła obejmuje trwające szanse
  z każdego etapu i lejka, nie tylko oferty. Sekcja niczego sama nie zamyka ani nie
  archiwizuje i nie jest bramką etapu.
- **Kto nie pracuje w Sprzedaży, wynika z ekranu „Osoby i role”,** nie z listy kont
  w kodzie. Konto, które zmieniło zajęcie, ale ma jeszcze uprawnienie Sprzedaży, trafi do
  „Do decyzji” dopiero, gdy Artur to uprawnienie odbierze.
- **„Bez ruchu”** liczy się od późniejszej z dwóch chwil: dotyku z `touch.py` i wejścia na
  obecny etap z historii szansy. `/move` dotyku nie zapisuje, więc bez tego oferta wysłana
  dziś przy szansie sprzed kwartału od razu czekałaby na decyzję. Definicji dotyku to nie
  zmienia; dla ofert z importu, które historii etapów nie mają, liczy się sam dotyk.
- **„Odłóż do…”** zapisuje `keep_open_until` zwykłym `PATCH` szansy i zmiana idzie do
  historii. Data w przyszłości trzyma ofertę w „W toku”, w dniu daty oferta wraca. To samo
  pole chroni szansę przed automatem archiwizacji, bo oba znaczą „zostaw otwartą do dnia”.
  Odłożenie nie jest ruchem i nie zdejmuje z „Do decyzji” pozycji bez opiekuna w Sprzedaży.
- **„Zamknij z powodem”** to `/move` na etap przegranej wybrany w oknie, domyślnie
  „Przegrana”. Powód jest opcjonalny, bo moduł podpowiada, a nie blokuje.
- **„Przejmij”** działa tylko, gdy opiekuna nie ma albo nie pracuje on w Sprzedaży.
  W innym przypadku 409, a opiekuna zmienia jak dotąd on sam albo admin. Klikający zostaje
  opiekunem, zmiana idzie do historii jak `_transfer` w `scripts/sales_cleanup.py`,
  a otwarte zadania poprzedniego opiekuna przy tej szansie przechodzą razem z nią, bo na
  koncie spoza Sprzedaży nikt by ich nie zobaczył. Szansa spoza etapu oferty po przejęciu
  znika z zakładki i wraca do zwykłej pracy.
- **„Co dalej”** pokazuje najpierw zaległość, potem krok z `next_step.py`. „Zrobione”
  odhacza zadanie albo telefon, spotkania z kalendarza nie. Odhaczony krok jest dotykiem,
  sam zaplanowany nie.
- **Zakresy „Moje / Bez opiekuna / Wszystkie”:** „Bez opiekuna” to brak opiekuna albo
  opiekun spoza Sprzedaży. Liczniki i sumy MRR sekcji liczy backend, front ich nie
  przelicza. Przy wejściu osoba, która prowadzi jakąś ofertę, dostaje „Moje”, pozostali
  „Wszystkie”. Ten wybór zostaje na całą wizytę i nie zależy od wyszukiwania: ekran pyta
  bez zakresu tylko raz, bo inaczej po pierwszym „Przejmij” osoba bez własnych ofert
  lądowałaby w „Moje” i traciła z oczu resztę „Do decyzji”.
  To lista spraw do rozstrzygnięcia: bez rankingu osób, celu i paska postępu.
