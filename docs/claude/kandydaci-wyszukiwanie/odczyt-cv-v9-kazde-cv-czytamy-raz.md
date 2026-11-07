# Odczyt CV v9: każde CV czytamy raz, pola zbieramy na zapas

Decyzja Artura z 07.11.2026, przed ponownym odczytem ok. 55 tys. CV starej bazy.
Masowy odczyt z 08.2026 (`cv_enrichment_bulk`) zapisał tylko nazwy firm i jedną
liczbę lat na umiejętność, więc oś technologii i filtr lat wymagały drugiego
odczytu. Żeby to się nie powtórzyło, prompt `CV_ENRICHMENT` v9 zbiera też pola,
których ekrany jeszcze nie czytają.

- **Przy stanowisku** (`experience[]`): `sector` (branża, przy kliencie końcowym
  jego branża), `team_size` (ile osób prowadził, 1–500, tylko gdy CV to podaje),
  `regulations` (PSD2, RODO/GDPR, KNF, DORA, PCI DSS, ISO 27001…). Klucze idą do
  `candidates.experience` przez `_RICH_EXPERIENCE_KEYS`.
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
