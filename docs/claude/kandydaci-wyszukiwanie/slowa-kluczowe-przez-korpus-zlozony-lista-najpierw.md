# Słowa kluczowe przez korpus złożony + lista „najpierw id” (0385, 25.09.2026)

Audyt szybkości (https://claude.ai/artifact/1DKHMLHNc3QKUg4rtf2nei): słowo
kluczowe 0,9–2 s, „c#” 5,9 s; 68% czasu „java” zjadał regex po `keyword_doc`
(rozpakowywanie TOAST), dokładając 2 osoby z 15 710.

- **`candidates.keyword_fold_fts` i `notes.content_fold_fts`** liczą triggery
  z `app/services/keyword_corpus.py` (jedno źródło dla migracji 0385 i
  `entrypoint.sh` — `schema_ddl()`/`schema_index_ddl()`). Tekst przechodzi przez
  SQL-ową `candidate_keyword_fold`: bez polskich znaków, małe litery, `/`, `\`
  i `-` → spacja (myślnik od 0386: „CI/CD-driven” nie łączyło się z „ci/cd”;
  od 0387 NFC i usunięcie znaków łączących — 133 CV miało „o” + osobny akcent —
  oraz `<`/`>` jako spacja: `</script>` po składaniu nie zamykał „skryptu”
  i parser połykał resztę CV), `c++`/`c#`/`f#`/`.net` → `cplusplus`/`csharp`/`fsharp`/`dotnet`
  (`.net` tylko po granicy słowa albo `asp|ado|vb` — „B2B.net” zostaje).
  **Zapytanie składa ta SAMA funkcja** (`advanced_candidate_search.folded_tsquery`),
  więc dokument i zapytanie nie mogą się rozjechać — nie dopisuj składania w Pythonie.
  **Zmieniasz tę funkcję = podbij `keyword_corpus.FOLD_VERSION`**: pętla
  przelicza wtedy wszystkie wiersze obu kolumn (pozycja przeżywa ponowienie),
  a nowa ścieżka czeka na koniec (`app_settings['keyword_fold_fts_version']`).
- **Przełącznik `KEYWORD_SEARCH_FOLDED_FTS` (domyślnie OFF) i gotowość kolumn**
  (`fold_ready()`/`notes_ready()`, pętla `keyword_corpus_backfill` w trzech
  fazach). Przed włączeniem: `python -m scripts.compare_keyword_fold_fts`
  (stara vs nowa ścieżka, tylko odczyt) i zgoda Artura. Gwiazdka z przodu
  zostaje przy regexie. Świadome różnice: „lodz” znajduje „Łódź” w CV,
  „scrum” znajduje „Agile/Scrum”, nazwy znaczników HTML w notatkach nie są słowami.
- **Czasy ścieżek porównuj na ciepłym cache** (pomiar 06.10.2026). Fraza
  (`<->`) na indeksie GIN zawsze sprawdza pozycje w samym tsvectorze wiersza,
  więc pierwsze zapytanie o frazę czyta z dysku tsvector każdego trafienia —
  obie ścieżki, każda swoją kolumnę. Pierwszy bieg skryptu porównującego mierzył
  każdą ścieżkę raz, starą pierwszą: „ci/cd” wyszło 1 047 → 7 811 ms, choć
  EXPLAIN (ANALYZE, BUFFERS) na ciepłym cache daje 1 097 → 379 ms, a na zimnym
  nowa czyta mniej bloków („power bi” 14,1 → 8,2 s). Skrypt mierzy teraz obie
  ścieżki na przemian (`measure_alternating`) i porównuje ciepłą rundę; zimną
  pokazuje osobno. Nie wyciągaj wniosków z jednego pomiaru po kolei.
- **`TRIGGER_FUNCTION_DDL_0350` jest zamrożony** — migracja 0350 nie może
  dotykać kolumny z 0385 (łańcuch migracji na świeżej bazie).
- **Notatki z Traffita zapisane jako JSON** (`{"content":"…\u0144…"}` — Traffit
  wysyła treść jako NAPIS z JSON-em; 38% notatek 25.09): promocja rozpakowuje je
  `note_unwrap_json`, a istniejące rozpakowuje faza notatek pętli (`SET content =
  note_unwrap_json(content)`, **bez zmiany `updated_at`** — odcisk nocnej
  analizy AI). Paragon: `app_settings['0385_traffit_note_content_unwrap']`.
- **Lista `GET /api/candidates` liczy „najpierw id”** (`_list_page_ids_first`,
  wyłącznik `CANDIDATE_LIST_IDS_FIRST`): filtr i sortowanie po samych
  identyfikatorach, liczba z okna `count(*) OVER()` na samych id (filtr raz — osobne `count(*)` liczyłoby regex dwa razy), pełne wiersze z relacjami tylko
  dla strony. Nie wracaj do `count(*) OVER()` na `select(Candidate)` — przepuszczał
  przez sortowanie wszystkie kolumny (bez filtra 385 ms, 170 MB na dysk
  tymczasowy). `skills_manually_curated` zostaje nieodłożone (po zmianie liczy
  się dla 50 osób; odłożenie = `MissingGreenlet` i inny odcisk weryfikacji).
