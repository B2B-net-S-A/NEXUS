# Formularz klienta zamiast CV firmowego (0521, 26.10.2026)

Prośba Michała (Delivery Lead, Centrum e-Zdrowia): część klientów nie przyjmuje
CV firmowego, tylko własny formularz CV. CEZ ma go w każdym przetargu osobno
(„Załącznik nr 4a/4b do SWZ — Formularz CV”): ten sam szkielet (dane osoby,
cel zawodowy, tabela doświadczenia, kompetencje, certyfikaty, RODO), inne
wiersze kompetencji per rola. Makiety i pomiar z produkcji:
https://claude.ai/artifact/Rj9dDbmXKvS9tFBAEN5J9v

Decyzje Artura 26.10.2026:

- **Wzór wyłącznie z Plików rekrutacji.** Stałego wzoru w regule klienta nie
  ma — wzór CEZ różni się w każdym przetargu. Brak wzoru w rekrutacji = karta
  osoby prosi DL o dodanie pliku, nie generuje CV firmowego.
- **CV firmowe samo nie powstaje** u klienta z formularzem; rekruter może je
  zrobić ręcznie.
- **Przed „QC CV” tylko przypomnienie** o brakach w formularzu, bez blokady.
  *(Od 23.11.2026 brak wypełnienia blokuje — sekcja „Na »QC CV« dopiero
  z formularzem” niżej; puste pola dalej tylko przypominają.)*
- **Na start tylko CEZ.** Tauron zostaje na CV firmowym, dopóki jego
  „Załącznik nr 3” nie trafi do Plików rekrutacji (w NEXUSIE go nie ma).

Reguły, które łatwo cofnąć:

- **Flaga klienta `clients.cv_client_document`** (`company_cv` | `client_form`)
  idzie przez edytor reguły CV jak `cv_interactive_enabled`
  (`CLIENT_FLAG_FIELDS`, wersja i historia). Usunięcie reguły wraca do
  `company_cv`. CEZ dostał `client_form` RAZ (znacznik `0521_ezdrowie_client_form`
  w `app_settings`) — restart nie może cofać zmiany z edytora.
- **Wzór to `job_files.client_form`, najwyżej jeden na rekrutację**
  (`ux_job_files_client_form`). Nowe oznaczenie zdejmuje poprzednie pod blokadą
  rekrutacji. NEXUS sam oznacza DOCX z „formularz” w nazwie, gdy klient ma
  `client_form` (dodanie pliku i „Utwórz i przekaż” z `/jobs/new`); inny plik DL
  oznacza ręcznie `PATCH /api/jobs/{id}/files/{file_id}` i dostaje powód odmowy
  po polsku. Pliki formularza `/jobs/new` nie są oznaczane — wzór należy do
  rekrutacji.
- **Odczyt pól bez AI** (`services/client_form_structure.py`), zapisany przy
  oznaczeniu w `client_form_structure`. Pole to `line` (etykieta z dwukropkiem),
  `box` (pusta tabela 1×1 pod etykietą) albo `cell` (pusta komórka). Etykieta
  komórki = nagłówek kolumny; gdy liczba komórek wiersza zgadza się z liczbą
  nazwanych nagłówków, po kolei — siatka nagłówka i wierszy w formularzu
  „Analityk” CEZ jest przesunięta i dopasowanie po kolumnach siatki dawało
  „Miejsce pracy” zamiast „Okres pracy”. Wiersz z „…” = tabelę można wydłużać.
  Identyfikator pola (`p3`, `t2.r7.c3`) wskazuje miejsce w dokumencie —
  wypełnianie trafia tam bez ponownego zgadywania. Tekstu i etykiet wzoru kod
  nie zmienia: SWZ zabrania modyfikowania pól formularza.
- **Kontrola paczki jest lżejsza niż przy wzorach protokołów sprzętu** —
  formularze przetargowe mają logo i łącza; zakazane są makra, ponad 1000
  części i ponad 60 MB po rozpakowaniu. Plik czyta tylko python-docx (lxml bez
  encji), nie LibreOffice.
- **Testy na fikcyjnym formularzu** (`tests/_client_form_docx.py`) — prawdziwe
  pliki klienta nie trafiają do publicznego repo.

## Wypełnianie (0522, PR 2)

- **Wypełniony formularz jest jeden na parę osoba × rekrutacja**
  (`candidate_client_forms`, `UNIQUE (candidate_id, job_id)`), nie na wiersz
  etapu — para ma kilka wierszy historii etapów. W bazie leżą wartości pól
  (`fields`: wartość, źródło, cytat) i wiersze dopisane ponad wzór, a plik Word
  powstaje przy pobraniu z wzoru (`client_form_render.render`) — edycja
  rekrutera nie rozjedzie się z zapisanym plikiem. `template_sha256` i
  `job_file_id` mówią, że DL podmienił wzór (`template_changed`).
- **Model to F36 `client_form_fill` (Sonnet 5, jak generator CV F4).** Źródła:
  `raw_cv_text` i `collect_screening_notes_text` (screening i notatki tej
  rekrutacji, bez stawek i dostępności). Każda wartość ma cytat; KOD odrzuca
  wartość bez cytatu z CV albo notatek, „TAK/NIE” spoza tych słów, ocenę w skali
  1–10 bez tej liczby w cytacie i wartość z e-mailem albo telefonem (9+ cyfr —
  okres „2019 - 2023” telefonem nie jest). Imię i nazwisko wpisuje kod z profilu.
  Błąd modelu albo brak klucza = formularz z samym imieniem i nazwiskiem do
  uzupełnienia ręcznie, nigdy 5xx.
- **Wartości rekrutera (`source = recruiter`) przeżywają „Wypełnij ponownie”.**
  Pusta wartość w `PUT` = pole do uzupełnienia; nieznane pole = 422.
- **Dopisywanie wierszy tylko w tabelach z „…”**, kopią wiersza wzorcowego
  (ostatni wiersz danych przed „…”, `FormTable.template_row` — w kompetencjach
  CEZ to wolny wiersz, nie „SQL”). Wiersze od modelu najpierw zajmują puste
  wiersze wzoru, dopiero reszta idzie ponad wzór (najwyżej 10 na tabelę).
  Gdy dochodzą wiersze, wiersz z „…” znika (jego numer by się powtórzył); bez
  nich zostaje pusty. Struktura wzoru ma wersję (`STRUCTURE_VERSION`); starsza
  czyta się ponownie z pliku przy pierwszym użyciu.
- **Trasy `…/candidates/stages/{stage_id}/client-form`** mają dostęp jak CV
  etapu: rola czyta albo pisze dokumenty kandydata, a do pary wymagany jest
  dostęp do rekrutacji (`ensure_job_read_access` / `ensure_job_membership`).
  Plik do klienta nie ma żółtych „UZUPEŁNIJ” — puste pole zostaje puste.
- **Daty i certyfikaty kontroluje kod (staging 19.11.2026, „Tester” CEZ).**
  Model wpisał „1,5 roku” w „Data wydania”, certyfikat „preparing for exam”
  jako posiadany i dopisywał miesiąc do okresu „2022 – obecnie”. Pole z „Data”
  w etykiecie przyjmuje tylko „MM.RRRR”/„RRRR”, pole z „Okres” — „data – data”
  albo „data – obecnie”; rok i miesiąc wartości muszą stać w cytacie, „obecnie”
  — gdy cytat mówi, że praca trwa. W wierszu certyfikatu (etykieta albo nazwa
  wiersza z „certyfikat”) wartość z „w trakcie/przygotow/preparing” w wartości
  lub cytacie odpada; „NIE” i 0 pkt zostają. Wielowierszowy cytat pola z datą
  liczy się po liniach — dwukolumnowy PDF stawia kolumnę boczną między
  początkiem a końcem okresu. Prompt F36 od wersji 4 każe wpisać wszystkie
  stanowiska (Asseco jako 4. wiersz wcześniej nie trafiało do `extra_rows`).

## Ekrany i bramki (PR 3)

- **Lista wymagań ruchu:** u klienta z formularzem „QC CV” ma jedną pozycję
  „Formularz CV klienta” (`client_form`, nigdy blokująca; akcja
  `open_client_form` otwiera sekcję CV osoby i okno braków), a „CV wysłane” —
  tę pozycję zamiast „QC CV”. Brak wzoru = „brak wzoru w Plikach rekrutacji —
  dodaje go Delivery Lead”, bez akcji.
- **Serwer nie liczy QC CV firmowego takiej pary** (`pipeline._assert_cv_qc_gate`
  → `client_form_status.client_takes_client_form`): nie ma czego sprawdzać,
  a decyzja D3 mówi „przypomnienie, nie blokada”.
- **Kolejka Delivery Leada też nie czeka na QC CV firmowego** (decyzja Artura
  23.11.2026, staging: CEZ 789232 z „QC: 1 do poprawy” i formularzem bez braków
  nie trafiał do „Do wysłania do klienta”). Para w „QC CV” jest gotowa od
  wejścia do kolumny (`dl_send_queue.readiness_of(client_form=True)`, front
  `isReadyForDlSend`), dni na karcie i „Twoje CV w drodze” liczą od tej chwili,
  a QC do poprawy nie zamyka przeglądu na Tablicy (`qcBlocksDlReview`). Braki
  formularza to przypomnienie, nie warunek kolejki. Przegląd DL pokazuje karty
  formularza i tabeli punktowej (`ClientFormCard readOnly compact`) zamiast
  „Kontroli CV”, bez luk QC i bez ryzyka „CV nie przeszło QC”; plakietka
  w kolejce (`QcStatusBadge` z `client_form`) mówi o formularzu. Wiersze
  kolejki niosą `client_form = {template, missing}` jak karta Tablicy.
- **Automat CV firmowego pomija klienta z formularzem** (`cv_auto_generate`,
  powód `client_form`, bez dzwonka) — działa tylko przy włączonym
  `CV_AUTO_GENERATE_WITHOUT_CONFIRMATION`.
- **Tablica:** `KanbanEntry.client_form = {template, missing}`; plakietka karty
  (`clientFormBadge`) na „Zweryfikowanym” i „QC CV” mówi o formularzu zamiast
  o CV firmowym. Chipa QC CV firmowego taka karta nie ma (`boardQcChip`),
  a nieudane QC nie robi szarej strzałki (`knownForwardGap`) — staging
  23.11.2026: DL widział „QC: CV sprzed rekrutacji — potwierdź” przy dokumencie,
  którego klient nie bierze. `item.qc` zostaje w payloadzie, bo z niego liczą
  się gotowość do kolejki DL i dni na karcie. Panel osoby: karta `ClientFormCard` na górze sekcji CV
  („Wypełnij z CV i screeningu”, „Uzupełnij braki”, „Pobierz Word”, „Wygeneruj
  też CV firmowe”), okno `ClientFormDialog` z brakami najpierw i źródłem
  każdej wartości; pusty opis w „Wiersz N” pokazuje pierwszą wypełnioną komórkę
  wiersza (firmę). Ta sama karta (i karta tabeli punktowej) stoi na górze
  zakładki „CV” rozwiniętego panelu (`CvHandoffWorkbench`, od 19.11.2026,
  na każdym etapie) — rozwinięty panel to domyślny widok pracy rekrutera,
  a do tej daty pokazywał tam tylko „Jeszcze nie ma CV do klienta”.
  Pliki rekrutacji: plakietka „Wzór formularza”, co NEXUS
  rozpoznał, „Ustaw jako wzór” / „To nie jest wzór”. Edytor reguły CV:
  „Dokument do klienta”.
- **Odczyt cytatów (po próbie na stagingu 26.10.2026):** tekst CV
  z dwukolumnowego PDF-a przeplata punkty z kolumną boczną, więc model sklejał
  cytat z kilku punktów i kod odrzucał opisy projektów. Cytat może być listą
  fragmentów — każdy musi stać w źródle osobno. Miejsce zamieszkania wpisuje
  kod z profilu (`candidates.city`), jak imię i nazwisko.
- **Fragment z nowymi liniami liczy się po liniach, w każdym polu (staging
  19.11.2026, Asseco w „Testerze” CEZ).** Kolumna boczna wchodzi w środek
  punktu (osobną linią albo na początku tej samej: „…based on existing” /
  „Collaboration & Communication specifications,”), a stopka strony z klauzulą
  RODO — między dwie linie punktu. Każda linia musi stać w źródle dosłownie,
  w kolejności cytatu i najwyżej `LINE_GAP_MAX` (400) znaków za poprzednią.
  Zastępuje to dzielenie po liniach tylko w polach z datą.
- **Opis nie może być wielokrotnie dłuższy od swoich cytatów** (`QUOTE_SHARE_MIN`
  = 0,4 dla pól z „Opis” w etykiecie). Opis to przekład, więc kod nie porówna go
  słowo w słowo; na stagingu model wpisał 7 opisów z jednym krótkim cytatem
  (11–18 % długości), a rzetelne odpowiedzi mają 51–197 %. Prompt F36 od
  wersji 5 każe dać fragment na każdą czynność z opisu.

## Tabela punktowa (Excel) obok formularza (0525, 27.10.2026)

Decyzja Artura 27.10.2026: CEZ do formularza CV dokłada Excel z punktacją według
„Szczegółowego opisu oceny” (zał. 5 SWZ) — **jeden na osobę**, wypełniany przez
NEXUS jak formularz.

- **Rodzaj wzoru wynika z pliku:** Word = `form`, Excel = `score`
  (`job_files.client_form_kind`). Najwyżej jeden wzór KAŻDEGO rodzaju na
  rekrutację (`ux_job_files_client_form_kind`); indeks „jeden wzór na
  rekrutację” z 0521 jest zastąpiony i NIE stoi w entrypoincie
  (`SUPERSEDED_DDL`) — przy starcie wywróciłby się na Wordzie i Excelu naraz.
  Wypełniony dokument pary też ma rodzaj (`candidate_client_forms.kind`,
  unikalność `(candidate_id, job_id, kind)`). Trasy `client-form` biorą
  `?kind=score`; bez parametru — formularz, jak dotąd.
- **Odczyt Excela bez AI** (`services/client_score_structure.py`, ten sam
  kształt pól co Word): komórka za etykietą z dwukropkiem, tabele pod nagłówkiem
  z „Lp.”, wiersz z jednym tekstem = sekcja. „Tak/Nie” w wierszu to metoda oceny
  — odpowiedź idzie do pustej kolumny obok („Wynik (Tak/Nie)”). Liczba
  w kolumnie „punkty” = `max_points` wiersza. Wiersze „Razem” i formuły zostają —
  Excel liczy sumy sam. Zapis (`client_form_render.render_score`) wpisuje punkty
  liczbą, żeby formuły sum działały. openpyxl gubi obrazki z arkusza.
- **Maksimum w kolumnie bez nagłówka** (zał. 5 Testera, 19.11.2026): nagłówek
  „Lp · Oceniany element · (pusto) · Liczba punktów · Legenda”, liczby maksimów
  pod pustym nagłówkiem, a pusta „Liczba punktów” to miejsce na wynik (jej
  „Razem” sumuje D). Odczyt v1 brał „Liczbę punktów” za maksimum i nie dał żadnego
  pola punktowanego; od `STRUCTURE_VERSION = 2` pustą kolumnę „punkty” z liczbą
  w kolumnie bez nagłówka czyta się jako pole wyniku z `max_points`. „Razem”
  zamyka tabelę — wiersz testu klienta pod nim (60 pkt) nie jest polem.
- **Punkty liczy model według zasad oceny z Plików** (`job_files.scoring_rules_text`:
  PDF/Word z „ocen”/„kryter”/„punkt” w nazwie, np. zał. 5b). Kod przyjmuje tylko
  liczbę całkowitą od 0 do `max_points` z cytatem ze źródła; bez pliku z zasadami
  pola punktów zostają do wpisania ręcznie. „Firma:” to wykonawca — wpisuje kod
  („B2B.net S.A.”).
- **Model oddaje liczby liczbami** (2, nie "2") — `_short` przyjmuje też liczby;
  na stagingu 27.10.2026 kod odrzucał przez to wszystkie punkty.
- **Ekrany:** w Plikach plakietka „Tabela punktowa” i „Ustaw jako tabelę
  punktową klienta”; w sekcji CV osoby druga karta (tylko gdy jest wzór Excela)
  z „Punkty: X z Y” i „Pobierz Excel”. Lista wymagań i plakietka na Tablicy
  mówią tylko o formularzu.
- **Prawdziwego Excela CEZ w NEXUSIE nie było** (27.10.2026: 0 plików xlsx w
  rekrutacjach i profilach osób CEZ) — odczyt sprawdzony na arkuszu zbudowanym
  według treści zał. 5b (14 pól, maks. 33 pkt jak „Razem” w PDF). Inny układ =
  „nie rozpoznano” przy oznaczeniu, plik zostaje zwykłym plikiem.

## Lata doświadczenia liczy kod ze stanowisk (19.11.2026)

DL CEZ: „nie daje rady odczytać lat doświadczenia w danej technologii i trzeba
ręcznie”. Pomiar na stagingu (rekrutacja „Tester”, trzy osoby): 0 z 9 pól
„Liczba lat doświadczenia” u każdej — model nie liczy dat. Decyzja Artura
(wariant B z makiet + „Dodaj do ściągi screeningu” z wariantu C):

- **Model oddaje stanowiska, kod liczy lata** (`services/client_form_years.py`,
  prompt F36 od wersji 6). Model w `roles` wypisuje stanowiska z cytatem z datami,
  a w `years` przy każdym polu z „Liczba lat”/„lat doświadcz” — które stanowiska
  mają kompetencję: `role` (opis ją nazywa) albo `implied` (praca jej wymagała),
  z cytatem z opisu. Kod przyjmuje stanowisko tylko, gdy rok (i miesiąc, gdy go
  podaje) stoi w cytacie, a „obecnie” — gdy cytat mówi, że praca trwa. Miesiące
  liczy jak `cv_tenure_checks`: nakładki raz, „obecnie” do bieżącego miesiąca
  (`business_today`), rok bez miesiąca od stycznia do grudnia.
- **Domyślnie liczą się role „wprost” i „pośrednio”** (Artur woli wyższą liczbę
  z ról opisujących pracę). Sama lista umiejętności lat nie daje — pole zostaje
  puste z pytaniem. Łączny staż („Łączna liczba lat”) = wszystkie stanowiska.
- **„Ponad minimalne wymagania”**: minimum musi stać w cytacie z zasad oceny,
  w wymaganiach wzoru albo w nazwie wiersza; bez niego pole zostaje puste
  (`minimum_unknown`) — cały staż w tym wierszu zawyżałby ocenę. Zasady oceny
  idą od tego dnia także do wypełnienia formularza Word, nie tylko Excela.
- **Punkty z lat w tabeli punktowej**: model podaje progi (`thresholds`) i cytat
  z zasad; kod bierze tylko próg, którego obie liczby stoją w cytacie, i nigdy
  ponad `max_points`.
- **Siatka zapisuje się w `fields[id]["years"]`** (bez nowej kolumny): stanowiska
  z dowodem, `on`, pytanie, `ask`. Wpis rekrutera w polu nie gubi siatki,
  a „Wypełnij ponownie” zostawia pytania wysłane do screeningu i role zdjęte
  w siatce (`carry_selection`, dopasowanie po okresie i firmie, bo klucze r1/r2
  zmieniają się między biegami modelu) — inaczej zdjęta praca spoza IT wracała
  do przetargu bez sygnału.
- **Odpowiedź ze screeningu wraca do formularza:** stanowisko albo projekt
  z okresem podany w notatce screeningu model wpisuje do `roles` z cytatem
  z notatki (prompt od 20.11.2026).
- **Wiersz testu u klienta i wolne „Wiersz N”** nie są polami lat (`NOT_YEARS_ROW`).
  Okno formularza po „Zapisz lata” nie kasuje niezapisanych wpisów w innych polach.
  `PUT …/client-form/years` (`roles`: id pola → klucze ról, `ask`: pola do ściągi)
  przelicza wartość na serwerze — przeglądarka nie przysyła liczby lat. Gdy kod
  nie policzył nic, a model dał wartość z cytatem (np. „0” z notatki), zostaje
  wartość modelu.
- **Ekrany:** na górze okna formularza siatka „Lata w kompetencjach · z ról w CV”
  (`ClientFormYearsGrid`, kolumny = stanowiska, ● wprost, ◐ pośrednio, ○ zdjęta)
  z „Zapisz lata” i listą „Lat nie ma w CV” → „Dodaj do ściągi screeningu”.
  Wysłane pytania stoją w formularzu screeningu pod pytaniami Profilu Championa
  („Do dopytania pod formularz klienta”, `ClientFormScreeningAsks`); awaria
  odczytu go nie pokazuje, jak innych podpowiedzi formularza. Link dla kandydata
  do samodzielnego uzupełnienia — później (decyzja 19.11.2026).

## Na „QC CV” dopiero z formularzem (23.11.2026)

Prośba Michała (DL CEZ) z 20.11.2026: „na zweryfikowany, żeby można było dać,
ale na QC CV dopiero z formularzami — teraz dostaję ludzi na QC CV bez
formularza, to nie mam czego sprawdzać”. Pomiar na stagingu (kopia z 22.11):
19–20.11 pięć wejść na „QC CV” w rekrutacjach CEZ, dwa bez żadnego formularza
w chwili ruchu, pozostałe z 10–29 pustymi polami. Przyczyna po stronie
ekranu: strzałka ze „Zweryfikowanego” sprawdzała CV firmowe, więc osoba
z CV firmowym i bez formularza przechodziła jednym kliknięciem, a osoba
z formularzem bez CV firmowego miała szarą strzałkę. Makiety i decyzje
Artura (wszystkie rekomendowane):
https://claude.ai/artifact/32hRQWiWa3fVXzVv6bwxNx

- **Blokuje brak wypełnienia, nie puste pola.** Ruch z Nowych, Screeningu
  albo „Zweryfikowanego” na „QC CV” i dalej wymaga wiersza pary
  w `candidate_client_forms` dla formularza i — gdy rekrutacja ma wzór
  Excela — dla tabeli punktowej (`client_form_status.missing_before_qc`).
  Pola, które słusznie zostają puste (numer certyfikatu, którego osoba nie
  ma), nie trzymają karty; rekruter wpisywałby „-”. Brak wzoru w Plikach nie
  blokuje rekrutera (wzór dodaje DL), lista wymagań mówi o nim osobno.
- **Serwer:** `pipeline_move_rules.assert_client_form_before_qc`, 409
  `CLIENT_FORM_REQUIRED` z `missing` (`client_form`, `client_score`)
  i `stage_id`; `/move` i `/bulk-move`. Delivery Lead przechodzi
  (`skips_fill_gates`, ślad `requirements_skipped`, odznaka „Przesunął DL ·
  bez formularza”, gaśnie po wypełnieniu — `pipeline._still_missing`); ruch
  zbiorczy odmawia każdemu. Wyłącznik `CLIENT_FORM_QC_GATE_ENABLED`.
- **Lista wymagań:** w kolumnie „QC CV” pozycja „Formularz CV klienta” (i „Tabela
  punktowa klienta”, gdy jest wzór Excela) jest blokująca, dopóki para jej nie
  wypełniła; „CV wysłane” dalej tylko przypomina. Klucze w `_FILL_GATE_ITEMS`.
- **Tablica:** `KanbanEntry.client_form` niesie też `score_template`
  i `score_missing`. Strzałka ze „Zweryfikowanego” u klienta z formularzem
  liczy tylko formularz i tabelę (`clientFormForwardGap`), nigdy CV firmowe;
  plakietka „Brak formularza” / „Brak tabeli punktowej”.
- **Wgrywanie wypełnionego pliku z dysku** (prośba z tego samego dnia:
  rekruterzy wgrywali wypełniony Word przez „Wgraj CV”, więc lądował jako CV
  kandydata, u dwóch osób jako główne) idzie osobnym PR-em z migracją razem
  z regułą „doświadczenie = 10/10” w polach „w skali 1–10”.

## Plik wgrany z dysku i „doświadczenie = 10/10” (0756, 23.11.2026)

Druga część prośby DL CEZ z 20.11.2026, decyzje Artura z 23.11.2026
(wszystkie warianty rekomendowane). Na stagingu 22.11.2026 było 6 wypełnionych
formularzy wgranych przez „Wgraj CV” u 3 osób, u 2 jako główne CV. Tych plików
na produkcji ten PR nie przenosi: to osobna decyzja Artura.

- **Wgrany plik należy do pary osoba × rekrutacja**
  (`candidate_client_forms.uploaded_*`: klucz w storage, nazwa, typ, rozmiar,
  kiedy, kto). Plik leży pod `client_forms/{job_id}/` (`storage_service.save_client_form_file`).
  Trasy obok `client-form` mają ten sam dostęp co „Wypełnij”:
  `POST …/client-form/upload?kind=form|score` i `DELETE …/client-form/upload`.
  Formularz przyjmuje Word (`.docx`) albo PDF, tabela punktowa tylko `.xlsx`.
  Wgranie wymaga wzoru w Plikach rekrutacji (409 jak przy „Wypełnij”).
- **Kontrola paczki jak przy wzorze**: limit 20 MB pliku, bez makr
  (`vbaProject.bin`), najwyżej 1000 części i 60 MB po rozpakowaniu. Plik
  otwierają tylko python-docx albo openpyxl. PDF musi zaczynać się od `%PDF-`.
- **Wgrany = gotowy.** Wgranie zakłada wiersz pary, gdy go nie ma, więc
  bramka „QC CV” (`missing_before_qc`, liczy istnienie wiersza) przepuszcza
  kartę bez dalszych zmian. `client_form_status.job_states` podaje przy
  wgranym pliku `missing = 0` i `uploaded`, a lista wymagań pisze „wgrany
  z dysku”. Plakietka Tablicy: „Formularz wgrany”. Brak tabeli punktowej
  dalej trzyma kartę, gdy rekrutacja ma jej wzór.
- **Pobranie (`…/docx`) oddaje wgrany plik**, gdy jest. Nazwa pliku powstaje
  ze wzoru i osoby, z rozszerzeniem wgranego pliku. Wartości wypełnione
  w NEXUSIE zostają w bazie. „Usuń” przywraca pobieranie wypełnienia
  z NEXUSA. Wiersz założony samym wgraniem znika razem z plikiem, więc
  karta znów czeka na formularz. „Zastąp plik” kasuje poprzedni plik z dysku
  dopiero po zapisie nowego w bazie.
- **Reguła klienta `clients.client_form_scale_full_on_experience`**
  („Jeżeli kandydat ma jakieś doświadczenie w czymś, wpisujemy poziom
  10/10”) idzie przez edytor reguły CV jak `cv_client_document`
  (`CLIENT_FLAG_FIELDS`, wersja i historia). Usunięcie reguły ją wyłącza.
  CEZ dostał ją RAZ, znacznikiem `ezdrowie_client_form_scale_full`
  w `app_settings`, żeby restart nie cofał zmiany z edytora. Checkbox stoi
  pod „Formularz klienta”.
- **Liczy kod** (`services/client_form_scale.py`), po „Wypełnij” i po
  „Zapisz lata”. Pole z „skali”/„1–10” w etykiecie, w wierszu tabeli,
  dostaje „10” (źródło `client_rule`), gdy w tym samym wierszu kod policzył
  miesiące > 0 z ról włączonych w siatce lat albo opis ma przyjęty cytat
  z CV lub notatek. Inaczej pole zostaje puste, także gdy model wpisał ocenę.
  Wpis rekrutera (`source = recruiter`) wygrywa. Ręcznie wpisany opis nie ma
  cytatu, więc nie liczy się jako dowód.
- **Opis o braku doświadczenia nie jest dowodem** (`NO_EXPERIENCE`: „Brak…”,
  „Nie posiada…”, „nie pracował…”, „No … experience”). Na stagingu 23.11.2026
  („Tester Automatyczny” CEZ) opis „Brak komercyjnego doświadczenia w sektorze
  healthcare.” miał cytat z CV i dawał 10/10 w wierszu „Staż w projektach
  służby zdrowia”. Ten sam wzór: 7 pól skali, w 6 lata w tym samym wierszu;
  po „Wypełnij” 4 pola dostały 10 z lat z ról, reszta została pusta.

## Rekruter weryfikuje, nie przepisuje (23.11.2026)

Artur chce, żeby formularz wypełniał się sam, a rekruter tylko sprawdzał.
Pomiar na stagingu (CEZ 789225, „Starszy Kierownik Projektu”, kandydaci
21097, 69380, 22314): zapisane wypełnienia miały 29, 25 i 21 braków,
w większości szum. Po zmianie dwa biegi „Wypełnij” dały 1/1, 13/9 i 4/5.
Zostały prawdziwe luki: wydział, rok studiów, data i wystawca certyfikatu.

- **Wolny wiersz nie jest brakiem** (`client_form_structure.spare_ids`).
  Wolny jest pusty wiersz bez nazwy ze wzoru („Wiersz N”), który nie jest
  pierwszym takim wierszem tabeli. Przykład: wiersze 2–3 „Wykształcenia”
  przy jednych studiach. Wiersz częściowo wypełniony to brak (firma bez
  okresu). Pierwszy wiersz pustej tabeli też, bo formularz bez stanowiska
  jest niepełny. Wiersze z nazwą (kompetencje, certyfikat wpisany przez
  klienta) nigdy nie są zapasem. Reguła dotyczy `missing`, `missing_count`,
  licznika w oknie i karty Tablicy. Ta ostatnia liczy braki z `fields`
  i struktury wzoru (`client_form_status._missing`), więc wiersze zapisane
  przed zmianą też pokazują nową liczbę bez przeliczania bazy. Okno zwija
  wolne wiersze w „Pokaż wolne wiersze · N” z podpisem „wolny wiersz”.
  Można w nie wpisać, a po zapisie wiersz z wpisem przechodzi do braków.
  Sekcje okna liczy stan z serwera, nie szkic (#3756).
- **Druga tabela doświadczenia bez tytułu to ciąg dalszy sekcji**
  (`continued_tables`, `table_titles`). Formularze CEZ („Starszy Kierownik
  Projektu”, „Analityk”) mają pod „Doświadczenie zawodowe*:” dwie albo trzy
  tabele z tymi samymi kolumnami, oddzielone pustym akapitem. Odczyt dawał
  kolejnym `title: null`, a model raz je pomijał (21097, 69380: 12 pustych
  pól, stanowiska poszły w `extra_rows` pierwszej tabeli), a raz wpisywał do
  nich środek historii, co psuło kolejność w pliku (21654). Taka tabela ma
  teraz w prompcie i w oknie nazwę „<tytuł> — tabela 2”. Model wpisuje do niej
  stanowiska albo projekty najbliższe roli, od najnowszego, z cytatami
  (wolno powtórzyć wiersze z pierwszej tabeli). Tak wygląda ręcznie
  wypełniony „Analityk” w dokumentach osoby 19616: pełna historia w pierwszej
  tabeli, te same trzy projekty w drugiej i trzeciej.
  Kontynuacja nie rośnie (`extendable_tables` ją pomija), bo pełna lista
  stanowisk idzie do pierwszej tabeli. Treści tabeli wzór nie opisuje.
  Jeśli CEZ chce w niej czego innego (np. projektów z wymagania „3 projekty
  powyżej 4 mln zł”), zmienia się tylko zdanie w prompcie F36.
  Tabela z własnym tytułem i tymi samymi kolumnami to inna sekcja.
- **„TAK/NIE” tylko z cytatem** (prompt F36 od wersji 7). Model proponuje
  „TAK”, gdy źródło pokazuje kompetencję wprost albo przez opis pracy, która
  jej wymagała. „NIE” proponuje tylko z faktem, który przeczy wymaganiu
  („zespół 12 osób” przy „> 30 osób”). Bez cytatu z CV albo notatek kod
  odrzuca obie wartości i pole zostaje puste. Okno pokazuje cytat pod
  propozycją, a rekruter ją zatwierdza albo poprawia.
- **Odpowiedź modelu zamknięta za wcześnie** (`parse_answer`). Na stagingu
  2 z 3 odpowiedzi kończyły `extra_rows` nawiasem głównego obiektu i pisały
  dalej (`…]}, "roles": …`). `json.loads` padał na „Extra data”, a formularz
  zostawał z samym imieniem. Kod zdejmuje taki nawias, gdy za nim stoi
  przecinek. Inny błąd składni zostaje błędem (formularz do ręcznego
  uzupełnienia, nigdy 5xx).
- **Staging nie ma pliku wzoru 789225** (uploady sprzed 18.11). „Wypełnij”
  przez API kończy się tam 404 „Pliku nie ma już w magazynie”. Pomiar szedł
  skryptem na strukturze z bazy, bez zapisu.

## Zasady oceny z legendy tabeli punktowej (26.11.2026)

DL CEZ 26.11.2026: „NEXUS nadal wypełnia tylko 50% CV do CEZ”. Pomiar na
stagingu (kopia z 26.11, 5 rekrutacji CEZ, 21 formularzy i 14 tabel): w tabelach
punktowych „Testera ePP” i „Testera Automatycznego” puste zostawały wszystkie
pola punktów (8 i 7), a w formularzu Word pole „ponad minimalne wymagania”
nie miało minimum. Przyczyna: w żadnej z 5 rekrutacji nie ma osobnego PDF-a
ani Worda z zasadami — „Szczegółowy opis oceny” to sam Excel oznaczony jako
wzór tabeli, z zasadami w kolumnie „Legenda (punktacja)”. `scoring_rules_text`
pomijał oznaczone wzory, więc zasady były puste, prompt F36 nie dostawał pól
punktów, a kod odrzucał każdą liczbę.

- **Bez osobnego pliku zasady idą z legendy wzoru**
  (`client_score_structure.rules_text`, `job_files._score_template_legend`):
  wiersz „<oceniany element>: <legenda>” z kolumn, których nagłówek ma
  „legend”, „punktacj”, „zasad” albo „sposób oceny”. Osobny plik z zasadami
  dalej wygrywa. Wzór bez legendy daje pusty tekst — same nazwy wierszy nie
  są zasadami i nie odblokują punktów.
- Te same zasady trafiają do wypełnienia formularza Word, więc minimum do
  „ponad minimalne wymagania” bierze się z legendy („1 pkt – więcej niż 3 lata”).
- **Reszta braków to w większości brak danych w źródłach**, nie błąd modelu:
  lata kompetencji bez roli, która ją opisuje (Xray, rejestry publiczne,
  służba zdrowia), wiersz „Test sprawdzający wiedzę” (wypełnia klient po
  teście), data i wystawca certyfikatu. U jednej osoby z 789225 „CV” w
  profilu to certyfikat PRINCE2 — z niego formularz nic nie wyczyta.
