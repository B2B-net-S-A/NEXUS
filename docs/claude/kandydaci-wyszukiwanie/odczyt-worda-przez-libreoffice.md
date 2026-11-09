# Odczyt Worda bez tekstu: LibreOffice w procesie odczytu, linki z pliku zablokowane (03.11.2026)

`extract_text` czyta Worda przez python-docx. Binarnego `.doc` python-docx nie otwiera
(`PackageNotFoundError`), a w `.docx` pomija pola tekstowe i kontrolki, więc takie CV
miało pusty tekst. `POST /api/candidates/from-cv` odpowiadał wtedy 400 „Nie udało się
odczytać tekstu z pliku CV.” i zgłoszenie z portalu przepadało.

- **Ścieżka:** poniżej 100 znaków z python-docx plik idzie przez LibreOffice do PDF-a,
  a PDF zwykłym odczytem z OCR (`_extract_word` → `_worker_word`). Wygrywa dłuższy tekst.
  Pomiar na kopii produkcji: odczytane 65 z 65 `.doc` i 29 z 29 `.docx`, które miały
  pusty tekst; mediana 0,9 s, najdłużej 4,4 s.
- **Limit pamięci jest wyższy niż dla PDF-a** (`WORD_WORKER_MEMORY_BYTES`, 2,5 GB
  przestrzeni adresowej): przy 1,5 GB prawdziwe CV kończyło się sygnałem 11 LibreOffice'a.
  Sygnał nie wychodzi poza proces odczytu, plik po prostu zostaje bez tekstu.
- **Plik jest niezaufany, a LibreOffice sam pobiera obraz podlinkowany w dokumencie**
  (pomiar: 2 żądania HTTP, czyli SSRF z formularza kariery). Dlatego `cv_pdf_preview._run`
  zakłada każdej zamianie profil z `BlockUntrustedRefererLinks`, `DisableActiveContent`
  i `DisableMacrosExecution`. Nie przenoś zamiany na profil domyślny. Pilnują tego
  `test_profile_blocks_links_from_the_document` i `test_real_conversion_does_not_fetch_links_from_the_file`.
- **Tylko prawdziwy Word, z wymuszonym filtrem importu.** Format wybrany po bajtach
  (`sniff_extension`) daje `--infilter`, a plik bez sygnatury Worda do LibreOffice'a
  nie idzie. Bez tego plik pod nazwą `.doc` sam wybierał parser, a HTML z arkuszem stylów
  wykonywał żądanie mimo blokady obrazów. RTF i HTML pod nazwą `.doc` zostają więc
  bez tekstu (400 jak dotąd).
- **Bomba ZIP:** `_extract_docx` połyka odmowę strażnika, więc `_worker_word` woła
  `assert_safe_ooxml` drugi raz, zanim plik dojdzie do LibreOffice'a.
- **Jedna zamiana naraz** na proces webowy (`_word_slot`, czekanie do 60 s). Gdy miejsce
  zajęte, plik zostaje bez tekstu i `/from-cv` odpowiada 400 jak dotąd.
- **Brak LibreOffice'a** (lokalnie, w CI) nie uruchamia procesu odczytu: wynik jak przed
  zmianą. Testy z prawdziwym LibreOffice'em są w `test_pdf_extraction_sandbox.py`
  i bez niego się pomijają, więc CI sprawdza tylko logikę; przebieg z LibreOffice'em
  puszczaj w obrazie backendu.
- **Odmowa `/from-cv` ma ślad w logu:** `[from-cv] brak tekstu: <plik .doc, 26 zn.>, format .doc, 90112 B`.
  Tylko kształt nazwy, format z bajtów i rozmiar, bo nazwa pliku CV to zwykle imię i nazwisko.

## CV już leżące w bazie (`cv_text_backfill`, 04.11.2026)

Do tej zmiany backfill oznaczał binarny Word jako końcowy `legacy_doc`, a `.docx`
bez tekstu jako końcowy `empty`, więc takie CV nie wracały do odczytu.

- **`legacy_doc` już nie powstaje i nie jest końcowy.** Wiersze ze starym znacznikiem
  same wracają do zakresu backfillu. `empty` zostaje końcowy, więc te `.docx` wymagają
  biegu z `--retry-outcomes empty`.
- **Word bez tekstu po odczycie dostaje `error`, nie `empty`.** `extract_text` oddaje `""`
  także wtedy, gdy LibreOffice'a nie ma, był zajęty albo padł, a `error` wraca po odroczeniu.
  RTF i HTML pod nazwą `.doc` (`sniff_extension` daje `None`) dostają końcowe `empty`.
- **Sam kod niczego nie czyta.** Fazę `candidates_cv_text` wołał sync Traffita, a ten nie
  działa od 14.10.2026, więc odczyt to ręczny bieg `scripts/backfill_cv_text` z obrazu
  z LibreOffice'em (bez niego Word dostanie `error`).
- **Koszt biegu:** tekst trafia do kolejki indeksu (`record_bulk_reindex`), czyli do Voyage,
  gdy działa worker. Bieg nie uruchamia parsowania pól LLM ani zdarzeń auto-dopasowania.
