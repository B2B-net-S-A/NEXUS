# Stawki z umów i aneksów w Dokumentach kontraktu (0739, 18.11.2026)
<!-- indeks: odczyt każdego pliku umowy i aneksu modelem (F52), różnica z harmonogramem stawki kandydata, karta „Dokument zmienia stawkę”, pigułka „Stawka z dokumentu”, wpis automatyczny za flagą z „Cofnij”, `contract_document_rate_reads` -->

Zgłoszenie Artura z 18.11.2026: aneksy ze zmianą stawki leżały w Dokumentach
kontraktu, a stawka w kontrakcie została stara. Ręczny przegląd 1164 plików
kopii produkcji tego dnia znalazł 31 takich różnic. Przyczyny:

1. aneks albo umowa z Worda działu umów trafia do kontraktu tylko jako plik
   z SharePointa, który NEXUS rozpoznaje po nazwie (`contract_folder_docs/classify.py`),
   a treści nie czytał nikt (26 z 31);
2. umowa z Generatora z progresją dopisaną w pliku po pobraniu, przy pustym
   `rate_stages` w formularzu (3);
3. aneks z Generatora aneksów podpisany poza NEXUSEM bez „Oznacz jako
   podpisany” (2).

Artur wybrał z makiet wariant B (odczyt + wpis automatyczny oczywistych
przypadków z „Cofnij”) razem z C (zapora przy podpisie) i D (podział
zamówienia przy zmianie stawki). Ta reguła opisuje B.

- **Każdy plik umowy, aneksu i „inne” żywego kontraktu czyta model** (F52,
  `services/contract_rate_documents/reader.py`): tekst PDF-u, gdy plik go ma
  (≥ 60 znaków na stronę), inaczej skan jako blok `document`; zdjęcia jako
  obraz; DOCX pomijamy (robocza wersja z Generatora). Model nie dostaje
  stawek z NEXUSA. Wiersz `contract_document_rate_reads` na plik i wersję
  czytnika (`READER_VERSION`) — nowa wersja promptu = ponowny odczyt teczek.
- **Prompt v2:** nadgodziny, dyżury, weekendy i stawka klienta idą do
  `other_rates`, nie do kroków (w v1 model dokładał 1,5× stawki jako krok
  tego samego dnia); krok aneksu liczy się od dnia z paragrafu o wejściu
  w życie, nie od daty sporządzenia (data w nazwie pliku to sporządzenie).
- **Różnicę liczy kod** (`compare.py`, czysta funkcja z testami). Okno kroku
  trwa do najbliższego późniejszego kroku z dowolnego dokumentu; nowszy
  dokument wygrywa w okresie swojego kroku. Porównujemy okna sięgające dziś,
  przyszłe i zakończone w ostatnich 180 dniach. „Do sprawdzenia” zamiast
  wpisu: dwa dokumenty z różną stawką od tego samego dnia, kilka stawek
  w jednym dokumencie od tego samego dnia (np. per klient), krok z warunkiem,
  inna waluta albo stawka miesięczna, różnica ponad 30%, późniejsza zmiana
  w harmonogramie niż w dokumencie, krok sprzed startu kontraktu, krok sprzed
  ponad pół roku, który dalej obowiązuje (w teczce brakuje nowszego aneksu).
- **Stawkę zmienia wyłącznie aneks „Zmiana stawki”** — `apply_read` woła
  `apply_contract_amendment` dla każdego kroku, tą samą ścieżką co okno
  kontraktu (harmonogram, synchronizacja zamówień, oś czasu), z plikiem jako
  `document_id`. Odczyt sam niczego w kontrakcie nie zapisuje.
- **Wpis automatyczny** (`CONTRACT_RATE_DOCS_AUTO_APPLY`, domyślnie OFF —
  tydzień w trybie karty, włącza Artur): tylko kategoria `auto` i tylko odczyt
  bez decyzji. `apply_contract_amendment(current_user=None)` to jawna ścieżka
  automatu: wyłącznie aneks stawki i wyłącznie ze zdjętą bramką kwot, autor
  pusty. „Cofnij” przez 7 dni usuwa kroki i aneksy wpisu (`created_step_ids`,
  `decision_amendment_ids`), przelicza stawkę i zamówienia; cofnięty odczyt
  wraca na kartę do decyzji człowieka i automat go już nie rusza.
- **Karta nad zakładkami kontraktu** (`ContractRateDocumentsCard`):
  „Wprowadź do harmonogramu” (edycja kontraktu i zmiana kwot), „Otwórz plik”,
  „To nie stawka Partnera” (edycja kontraktu, `dismissed` — odczyt nie bierze
  już udziału w porównaniu). Kwoty i cytat tylko pod bramką kwot kontraktu
  (`_can_read_contract_finance`); bez niej karta mówi, od kiedy dokument
  zmienia stawkę. Awaria odczytu to komunikat, nie pusta karta.
- **Lista kontraktów:** pigułka „Stawka z dokumentu” = `bucket=rate_document`
  w tym samym zapytaniu co lista (zakres Delivery Leada, liczniki), adres
  `?rate_doc=1`; notka w wierszu z `rate_document_change` (redagowane razem
  z kwotami, `_CONTRACT_FINANCE_SCALARS`).
- **Pętla w workerze** (`tasks/contract_rate_documents.py`, co 10 min): paczka
  25 plików, potem przeliczenie różnic wszystkich kontraktów z odczytami
  (harmonogram zmieniają też ludzie), potem wpis automatyczny za flagą. Każdy
  plik i wpis we własnej transakcji. Na stagingu stoi (koszt modelu).
  Pierwszy bieg na produkcji nadrabia ok. 1200 plików (ok. 30 USD, pomiar
  18.11). `CONTRACT_RATE_DOCS_READ_ENABLED=false` wyłącza całość.
- Testy: `test_contract_rate_documents_compare.py`,
  `test_contract_rate_documents_reader.py` (bez bazy),
  `test_contract_rate_documents_api.py`, `ContractRateDocumentsCard.test.tsx`.
