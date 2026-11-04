# Firmowe CV ustępuje CV kandydata jako źródło generatora (02.11.2026)
<!-- indeks: `current_cv_ordering`, `client_cv_file_clause`, `isClientCvWordFile`, domyślny plik w `…/cv/ai-sources`, kopia „Oryginał CV” z firmowego pliku, jedyny plik „B2B_…” -->

Zgłoszenie rekruterki: po wgraniu firmowego CV jako głównego następna generacja
czytała je jak oryginał, więc błędy i skróty firmowego CV szły dalej.

- **Co jest firmowym CV:** Word „…B2B…” (`client_cv_file_clause`, lustro
  `looks_like_client_cv` bez wzoru klienta; na froncie `isClientCvWordFile`).
  PDF z „B2B” w nazwie zostaje CV kandydata: ze 109 odczytanych PDF-ów 15 miało
  układ szablonu, a 5 PDF-ów użytych jako źródło w 30 dni nie miało go wcale.
- **Kolejność (`current_cv_ordering`):** główne CV kandydata → plik rodzaju „cv”
  niefirmowy → główne → rodzaj „cv” → najnowsze. Trafia do generatora, kopii
  „Oryginał CV”, paczki CV, `cv-sources` i listy w karcie.
- **Nie odsiewamy po nazwie.** 1280 osób ma firmowy Word jako jedyne CV i generuje
  dalej jak dotąd.
- **„Other” nie zastępuje firmowego CV.** 171 osób ma obok niego tylko „other”:
  import Traffita nie klasyfikuje plików, a z 235 takich plików Word 50 miało układ
  szablonu i 4 wyglądały na umowę. Nieaktualny, usunięty i z kwarantanny też nie.
- **Wybór rekrutera wygrywa.** `cv_document_id` idzie jak dotąd, także dla pliku
  firmowego i dla „Wygeneruj z tego pliku”. Lista w kroku „Plik CV” mówi „CV dla
  klienta, nie CV kandydata”, bo 12 z 14 takich CV powstało z pliku wybranego ręcznie.
- **Kopia etapu sprzed zmiany:** gdy „Oryginał CV” to firmowy plik, a osoba ma CV
  kandydata, karta domyślnie bierze CV kandydata, a plik firmowy zostaje na liście.
  Ramka „a nie z Oryginału CV” wtedy milczy, bo taka kopia nie jest wzorem.

Pomiar (kopia produkcji 02.11.2026, tylko odczyt): 1544 osoby z firmowym Wordem jako
bieżącym CV, 264 z innym plikiem, 93 z plikiem rodzaju „cv”. Generacje z 30 dni: 318
ze znanym źródłem, 15 z firmowego Worda, z tego 14 przy dostępnym innym pliku
(12 wybranych ręcznie, 2 domyślnie). Kopie „Oryginał CV” z 30 dni: 426 z firmowego
Worda u 129 osób, 245 przy dostępnym pliku rodzaju „cv”.

## Naprawa starych danych: `app.cli.client_cv_flag_repair` (04.11.2026)

Kolejność z #2926 nie zdjęła flagi „główne” z firmowego Worda ani nie zmieniła
kopii „Oryginał CV”, z którą porównuje QC. Skrypt ma `--dry-run`, `--commit`
i `--rollback`, niczego nie kasuje, a paragon
`app_settings['client_cv_flag_repair_2026_11']` niesie same id i liczby. Przebieg
przećwiczony na kopii produkcji; bieg na produkcji wymaga zgody Artura.

- **„93 osoby” z pomiaru 02.11 to nie to samo co flaga.** Na kopii z 04.11 #2926 zmienia
  plik domyślny 110 osobom: 77 ma flagę na firmowym Wordzie, 33 nie ma używalnego
  głównego CV. Flagę na firmowym Wordzie ma 1517 osób, ale 1440 nie ma pliku rodzaju
  „cv” bez cech firmowego i zostaje jak jest.
- **Paczka CV:** od #2926 te osoby dostają w ZIP-ie plik kandydata i tak ma zostać,
  bo firmowe CV powstaje na osobę i nie nadaje się do hurtu
  (`oryginal-cv-tylko-po-generatorze.md`). Trasy nie zmieniamy. Sama zmiana flagi
  podmienia plik w paczce tylko tam, gdzie dziś wygrywał plik bez daty albo wybór
  między plikami bez daty był przypadkowy (10 osób na kopii).
- **Kopia etapu** dostaje plik tylko bez CV do klienta. Szkic i zatwierdzone CV mają
  swój wzór, plik wgrany ręcznie to wybór rekrutera, a kopia z bajtami w bazie nie
  dałaby się cofnąć.
- **Treść pliku jest sprawdzana, nie sama nazwa.** Odpada plik bez nazwiska osoby,
  nieczytelny, z układem szablonu albo o bajtach firmowego CV. Takie osoby zostają
  bez zmian i idą do przeglądu po id (10 na kopii).
- **Plik DOC jako główne CV** (20 osób) nie ma podglądu w przeglądarce, a generator
  go nie czyta i zostaje przy firmowym Wordzie. `--exclude-doc` je pomija.
- **`--rollback` nie cofa odczytu AI** (`--reread`): profil osoby zostaje z nowego pliku.
