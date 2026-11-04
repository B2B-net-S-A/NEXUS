# Rodzaj notatki — co czyta AI, wyszukiwanie i rekruter (0412, 03.10.2026)

Pomiar 03.10.2026 (75 231 notatek, produkcja): 16% to wpisy automatu
auto-match, 5% wątki mailowe z Traffita, 7% „nie odbiera”, 8% wpisy Delivery
Leada o stawce do klienta, 13% karty rekomendacji według wzoru rekruterów.
Żaden czytelnik nie odróżniał wpisu automatu od notatki z rozmowy:
„Must-have trafione: python” liczyło się w bramce must jako dowód, a
„Wyślijmy za 161 zł/h” trafiało do odczytu faktów. Decyzje Artura 03.10.2026
(makiety: https://claude.ai/artifact/HTWhqfgGh4dr6C7u8Gmwyv).

- **`notes.kind` nadaje JEDNA reguła `services/note_kinds.py`** (czysta, bez
  bazy; pierwsza pasująca reguła wygrywa, kolejność jest znacząca): przy
  zapisie przez ORM nasłuch w `models/note.py`, dla surowego SQL
  (`promote_notes` importu Traffita) `note_kind_backfill.classify_notes`, dla
  wierszy sprzed 0412 pętla startowa `note_kind_backfill`. `UPDATE` rodzaju
  NIE rusza `updated_at` — stoi na nim odcisk nocnego odczytu faktów.
  `kind IS NULL` czyta się jak zwykłą notatkę (poza `external_source='system'`).
- **Notatki dla AI czyta się WYŁĄCZNIE przez `note_kinds.ai_readable_sql()` /
  `ai_readable_clause()`**: nocny odczyt faktów, bramka must i statystyki
  krytycznych (`must_text_evidence`, `critical_skills`), QC CV i generator CV
  (`_not_followup_note`), podsumowanie aktywności, podpowiedzi screeningu przy
  przepięciu. Poza AI są: `automatch`, `application_form`, `email`, `dl_rate`,
  `dl_review` („dopisz do CV” nie jest dowodem), `contact_attempt`,
  `scheduling`, `mention`. Nowy czytelnik notatek dla modelu = ten filtr.
- **Wyszukiwanie słów kluczowych (v2) i wycinki pomijają wpisy automatów
  i notatki ze stawką do klienta** (`searchable_clause`: `automatch`,
  `application_form`, `dl_rate` — inaczej `q=161` w zakresie „notatki”
  zdradzałoby zakrytą kwotę samym trafieniem). v1 (alerty zapisanych
  wyszukiwań) bez zmian. Szybki podgląd i „ostatnia notatka” listy pomijają
  tylko automaty (`not_automat_clause`).
- **Notatka, która mówi coś o kandydacie, nigdy nie jest szumem**
  (`_SUBSTANCE_RE`: „zna”, „doświadczenie”, „pracował”, „komercyjnie”):
  fałszywe wykluczenie kosztuje więcej niż fałszywe włączenie. Przegląd kodu
  03.10 złapał „Rozmowa: zna Pythona 3.11” jako termin (wersja = godzina)
  i „mówi poprawnie” jako uwagę do CV. Uwaga DL do CV wymaga wzmianki @osoba,
  termin — godziny z dwukropkiem, „godz.” albo daty DD.MM.
- **Nocny odczyt faktów: prompt `v6-note-kinds`** — sam prompt bez zmian,
  zmienił się wsad (filtr, karty rekomendacji i fakty ze screeningu przed
  limitem 20 notatek, jedna notatka najwyżej 4000 znaków). Doganianie przeliczy
  kandydatów po 700 na noc (zmierzone 03.10.2026: 0,00048 USD za odczyt na
  GPT-6 Luna, czyli ok. 9 USD za całą bazę). **Nic nie znika (decyzja Artura
  03.10.2026):** kandydat, któremu po odfiltrowaniu nie została żadna czytelna
  notatka, ZACHOWUJE fakty policzone wcześniej (3 013 osób, 2 872 miały
  wyłącznie wpisy scrapera); odczyt faktów nadal czyta odpowiedzi z formularza
  aplikacji (`facts_readable_sql` — oczekiwania i staż podał sam kandydat),
  a notatek automatów nie kasujemy — są pod filtrem.
- **Notatka `dl_rate` jest zakryta dla ról bez wglądu w stawkę do klienta**
  (`candidate_access.note_content_hidden` / `visible_note_content` /
  `note_rate_visibility_clause`; autor zawsze widzi swoją): lista i pojedyncza
  notatka, oś czasu, szybki podgląd, „ostatnia notatka” listy kandydatów,
  wycinki wyszukiwania, ostatnia notatka w follow-upie (tam przez filtr AI).
  Zapisane podsumowania aktywności unieważnia `candidate-summary-scope-v3`.
  `dl_rate` to tylko krótki wpis (< 200 znaków: „Wyślijmy
  za…”, „150/110”, „@osoba 175”); dłuższa notatka z kwotą w treści zostaje
  zwykłą notatką — świadomie, bo niesie fakty o kandydacie. Wyjątek: forma
  Delivery Leada z listą rekrutacji („Pokazujemy za 178 zł na: …”) jest
  `dl_rate` do 400 znaków, o ile nie mówi nic o kandydacie (także
  o dostępności, trybie pracy, lokalizacji — `_FACT_OTHER_RE`) — test na
  produkcji 03.10.2026 znalazł 142 takie wpisy odkryte dla rekrutera
  (jednorazowe przeliczenie: `note_kind_backfill.reclassify_dl_rate_lists`,
  paragon `note_kind_dl_rate_lists_2026_10`). Nowa trasa oddająca
  treść notatki = `visible_note_content`.
- **Wpis „X/Y” Delivery Leada albo admina jest `dl_rate` od zapisu**
  (07.10.2026). Ta sama reguła co plan stawki do klienta
  (`client_rate_notes.parse_dl_pair` + rola autora `DL_PAIR_AUTHOR_SQL`):
  `note_kinds.classify(..., author_is_dl=)` → `with_author`, a autora
  dociąga nasłuch w `models/note.py` (jedno zapytanie, tylko gdy
  `author_matters`), `note_kind_backfill` (JOIN do `users`) i fragment
  dzwonka wzmianki (`_mention_snippet`). Świadomie po AUTORZE, nie po samym
  kształcie: ten sam „135/95” u rekrutera bywa notatką z rozmowy, a
  `dl_rate` zawsze liczy się jako stawka do klienta w planie i „Stawce od”
  — reguła bez autora obeszłaby bramkę z #2062. Pomiar 07.10.2026: 309
  zwykłych notatek DL-a/admina (216 kandydatów) przeliczył jednorazowo
  `note_kind_backfill.reclassify_dl_pair_human_notes` (paragon
  `note_kind_dl_pair_human_2026_10` z id notatek, kandydaci pod
  `repair_details_…`; usuwa zapisane podsumowania aktywności tych
  kandydatów i zakrywa fragment w dzwonkach wzmianek). Poza zakresem: 83
  takie wpisy rekruterów (często dawnych TAC) i HoR zostają widoczne.
- **„Reply” z Traffita to odpowiedź na notatkę, nie mail** (3 955 wierszy):
  import nadaje jej typ `general`, istniejące zmienia jednorazowo
  `note_kind_schema.REPLY_RETYPE`. Jako mail liczyły się w follow-upie za
  kontakt z kandydatem.
- **Notatka zapisana tokenem integracji jest systemowa** (`POST /api/notes`,
  `proposals/bulk` bez blokady): scraper ogłoszeń dopisywał ~250 dziennie jako
  zwykłe notatki.
- Reguła była sprawdzana na całej produkcji (4 s na 75 tys. notatek, tylko
  odczyt). Zmieniasz regex — sprawdź rozkład jeszcze raz i dopisz przypadek do
  `tests/test_note_kinds.py` (same fikcyjne treści).
