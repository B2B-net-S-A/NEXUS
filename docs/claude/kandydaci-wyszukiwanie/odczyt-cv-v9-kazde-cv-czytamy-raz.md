# Odczyt CV v9: każde CV czytamy raz, pola zbieramy na zapas

Decyzja Artura z 07.11.2026, przed ponownym odczytem ok. 55 tys. CV starej bazy.
Masowy odczyt z 08.2026 (`cv_enrichment_bulk`) zapisał tylko nazwy firm i jedną
liczbę lat na umiejętność, więc oś technologii i filtr lat wymagały drugiego
odczytu. Żeby to się nie powtórzyło, prompt `CV_ENRICHMENT` v9 zbiera też pola,
których ekrany jeszcze nie czytają.

- **Przy stanowisku** (`experience[]`): `sector` (branża, przy kliencie końcowym
  jego branża), `team_size` (ile osób prowadził, 1–500, tylko gdy CV to podaje),
  `regulations` (PSD2, RODO/GDPR, KNF, DORA, PCI DSS, ISO 27001…). Zawsze są
  w `cv_extracted_data.experience`; do `candidates.experience` (`_RICH_EXPERIENCE_KEYS`)
  trafiają tylko wtedy, gdy historia z CV zastępuje zapisaną. FILL_EMPTY nie nadpisuje
  historii z rolami (np. z importu Traffita): w próbie 20 CV ze stagingu 07.11 żadna
  osoba nie dostała ich w `candidates.experience`, 14 ma branżę w odczycie. Konsument
  czyta więc `cv_extracted_data.experience`.
- **Przy kandydacie** (`cv_extracted_data`): `seniority_level` w kanonie
  `Job.seniority` (junior, mid, senior, lead, architect) i `nationality`.
  Słabszy odczyt przy FILL_EMPTY ich nie kasuje (`rich_keys`).
- **Do 8 sektorów** zamiast 4. Szybki podgląd i tekst wektora dalej biorą 4
  z `cv_highlights`, więc stare profile nie idą do ponownego indeksowania.
- **Strażnik przed zapisem** (`cv_parser.drop_untraced_profile_facts`): regulacja
  bez śladu w tekście CV wypada (RODO i GDPR to ta sama, numer normy wystarcza).
  Obywatelstwo zostaje tylko z CV, które ma słowo „obywatelstwo”, „narodowość”,
  „nationality”, „citizenship” (albo odpowiednik), bo model potrafi je zgadnąć
  z imienia.
- **Karta rekomendacji** bierze obywatelstwo z CV dopiero po poprzedniej karcie
  i `traffit_nationality` (`_nationality_suggestion`).
- **Konsumenci to osobne zmiany**: minimum lat w dziedzinie (`experience_evidence`),
  seniority w scoringu, regulacje w Championie. Nowe pole w prompcie dopisuj tylko
  z powodem i z wersją promptu, bo każda zmiana treści unieważnia cache odczytów.
- Scraper portali nie czyta CV modelem: wysyła plik do `from-cv` albo
  `POST /api/candidates/{id}/cv`, więc v9 obejmuje go sam.
- **Bieg po starej bazie**: `scripts/reparse_cv_batch.py` (`count`, `run`, `collect`),
  Message Batches API (−50%), model `cv_backfill`, zapis przez `finish_cv_ingest`
  z FILL_EMPTY i `enqueue_auto_match=False`. Odczytany tekst dostaje znacznik
  `_cv_reparse` (skrót, wynik, próby), więc bieg sam się wznawia. Wdrożenie
  restartuje kontener i zabija bieg w połowie zapisu paczki: po restarcie zbierz
  paczki jeszcze raz (`collect`), wiersze ze znacznikiem `ok` dla tego samego
  tekstu są pomijane (`already`), a dopiero potem puść `run`, bo inaczej CV z
  niezebranej paczki pójdą do modelu drugi raz. Paczki zbieraj po jednej,
  jednym procesem, a `run` puszczaj najwyżej jeden obok: każdy proces ładuje
  całą aplikację w kontenerze webu (limit 4 GB). 07.11 strażnik po wdrożeniu
  puszczał naraz 13 procesów `collect` i system zabił uvicorn z braku pamięci.
  Paczkę zebraną w całości (`=== KONIEC ===` w logu `collect`) skreśl z listy
  do wznowienia, zamiast zbierać ją po każdym restarcie. Znaczniki biegów
  `_cv_*` (`CV_RUN_MARKER_KEYS`) nie giną przy kolejnych odczytach CV.
- **Faza nocna** `candidates_cv_fields` czyta pełnym promptem i odświeża
  `candidate_skill_usage`, więc nowe osoby z tej ścieżki nie potrzebują drugiego odczytu.
