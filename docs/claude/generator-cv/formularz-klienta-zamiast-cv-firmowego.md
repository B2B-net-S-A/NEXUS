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
