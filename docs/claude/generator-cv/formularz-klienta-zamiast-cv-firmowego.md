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

## Ekrany i bramki (PR 3)

- **Lista wymagań ruchu:** u klienta z formularzem „QC CV” ma jedną pozycję
  „Formularz CV klienta” (`client_form`, nigdy blokująca; akcja
  `open_client_form` otwiera sekcję CV osoby i okno braków), a „CV wysłane” —
  tę pozycję zamiast „QC CV”. Brak wzoru = „brak wzoru w Plikach rekrutacji —
  dodaje go Delivery Lead”, bez akcji.
- **Serwer nie liczy QC CV firmowego takiej pary** (`pipeline._assert_cv_qc_gate`
  → `client_form_status.client_takes_client_form`): nie ma czego sprawdzać,
  a decyzja D3 mówi „przypomnienie, nie blokada”.
- **Automat CV firmowego pomija klienta z formularzem** (`cv_auto_generate`,
  powód `client_form`, bez dzwonka) — działa tylko przy włączonym
  `CV_AUTO_GENERATE_WITHOUT_CONFIRMATION`.
- **Tablica:** `KanbanEntry.client_form = {template, missing}`; plakietka karty
  (`clientFormBadge`) na „Zweryfikowanym” i „QC CV” mówi o formularzu zamiast
  o CV firmowym. Panel osoby: karta `ClientFormCard` na górze sekcji CV
  („Wypełnij z CV i screeningu”, „Uzupełnij braki”, „Pobierz Word”, „Wygeneruj
  też CV firmowe”), okno `ClientFormDialog` z brakami najpierw i źródłem
  każdej wartości; pusty opis w „Wiersz N” pokazuje pierwszą wypełnioną komórkę
  wiersza (firmę). Pliki rekrutacji: plakietka „Wzór formularza”, co NEXUS
  rozpoznał, „Ustaw jako wzór” / „To nie jest wzór”. Edytor reguły CV:
  „Dokument do klienta”.
- **Odczyt cytatów (po próbie na stagingu 26.10.2026):** tekst CV
  z dwukolumnowego PDF-a przeplata punkty z kolumną boczną, więc model sklejał
  cytat z kilku punktów i kod odrzucał opisy projektów. Cytat może być listą
  fragmentów — każdy musi stać w źródle osobno. Miejsce zamieszkania wpisuje
  kod z profilu (`candidates.city`), jak imię i nazwisko.
