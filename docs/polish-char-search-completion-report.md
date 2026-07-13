# Raport ukończenia — wyszukiwanie kandydatów bez polskich znaków (diakrytyki)

**Data:** 2026-07-13
**Branch:** `claude/polish-char-search-da2618`
**Problem:** Wpisanie w `/candidates?q=` frazy bez polskich znaków — np. `lukasz gradzki`
zamiast „Łukasz Grądzki", `krakow` zamiast „Kraków" — zwracało **0 wyników**.
**Cel:** Można wyszukać osobę (i dowolne pole) także bez wpisywania `ł`, `ą`, `ę`, itd.

## Diagnoza

Wyszukiwarka kandydatów (`app/services/advanced_candidate_search.py`) ma dwie trasy,
**obie wrażliwe na diakrytyki**:

1. **FTS** (`search_fts @@ to_tsquery('simple', 'lukasz:*')`) — konfiguracja `simple`
   tylko lowercase'uje i tokenizuje, **nie składa akcentów**, więc token `łukasz`
   jest nieosiągalny z zapytania `lukasz`.
2. **Substring** (`search_doc ILIKE '%lukasz%'`) — „Łukasz" zawiera `ł` (U+0142),
   osobną literę, więc `%lukasz%` nigdy nie trafia.

Rozszerzenie Postgres `unaccent` **nie jest zainstalowane** na prod (wymaga superusera
+ konfiguracji text-search).

## Rozwiązanie (bez rozszerzenia, IMMUTABLE)

Polskie diakrytyki to pojedyncze prekomponowane (NFC) kodpunkty, więc fałdowanie
`translate()` jest dokładne i length-preserving, a `translate`/`lower` są `IMMUTABLE`
(używalne w generated column).

| Plik | Zmiana |
|---|---|
| `backend/alembic/versions/0159_candidate_search_doc_unaccented.py` | **Nowa migracja.** `candidates.search_doc_unaccented` — STORED generated column = `lower(translate(<te same 16 pól co search_doc>, 'ąćęłńóśźż…', 'acelnoszz…'))` (diakrytyczne lustro `search_doc`), + `ix_candidates_search_doc_unaccent_trgm` (GIN pg_trgm, CONCURRENTLY). Wyklucza `raw_cv_text` jak `search_doc` → rewrite `ADD COLUMN` bez detoastu 171 MB CV (lock kilka sekund). |
| `backend/app/services/advanced_candidate_search.py` | `fold_polish()` składa frazę **tą samą mapą** (NFC → translate → lower) i dokłada gałąź `search_doc_unaccented ILIKE '%<folded>%'` do UNION-a `_phrase_match` na **obu** trasach. Czysto **addytywne** — dokładne gałęzie `search_doc`/`search_fts` zostają → brak regresji dla zapytań z diakrytykami. Folding jest 1:1, więc gałąź folded to nadzbiór dokładnej. |
| `backend/entrypoint.sh` | Kolumna + indeks zmirrorowane w `_COLUMN_STATEMENTS` (`ADD COLUMN IF NOT EXISTS … GENERATED`, `CREATE INDEX IF NOT EXISTS`). Prod alembic jest chronicznie multi-head → bez tego lista kandydatów zwróciłaby **500 UndefinedColumn** gdyby migracja nie wjechała. |
| `backend/tests/test_candidates_advanced_search.py` | `test_fold_polish_helper` (unit) + `test_diacritic_insensitive_name_search` / `…_city_search` (integracja: „Łukasz Grądzki"/„Kraków" po ascii; no-regression dla `?q=Grądzki`). Plik jest już na liście pytest w CI. |

Zasięg: cały `search_doc` (imię, nazwisko, miasto, lokalizacja, tytuł/firma LinkedIn,
ai_summary, kategoria, engagement_notes + bloby JSON skills/tags/education/languages),
czyli wszystkie pola nie-CV — dokładnie tam gdzie są polskie znaki. Fix pokrywa
zarówno proste `?q=` jak i zaawansowane `q_all`/`q_any`/`q_none` oraz `app/api/search.py`
(wspólny `_phrase_match`).

## Weryfikacja

- **PG16 (docker, DDL 1:1 z migracji):** wartości folded poprawne
  (`Łukasz Grądzki`→`lukasz gradzki`, `Kraków`→`krakow`, `Gdańsk`→`gdansk`,
  `Łódź`→`lodz`, JSON `Świnoujście`→`swinoujscie`); **wszystkie** zapytania ascii
  zwracają oczekiwane wiersze.
- **ruff** `check` + `format --check` czyste na `app/services/advanced_candidate_search.py`
  (plik objęty bramką CI `ruff … app/`).
- **py_compile** na 3 plikach `.py`; **bash -n** + kompilacja embedded-Python heredoc
  w `entrypoint.sh`.
- **CI (po pushu):** `alembic upgrade heads` na PG16 + `test_candidates_advanced_search.py`
  w liście pytest.

## Znane ograniczenia / świadomie poza zakresem

- **CV text** (`raw_cv_text`) i **notatki** (`notes.content`) pozostają diakrytyko-wrażliwe
  — to głównie techniczny tekst po angielsku, a fałdowanie ich = kosztowny re-backfill
  tsvectora (0143). Fałdujemy pełny `search_doc` (pola nie-CV), co pokrywa zgłoszoną potrzebę.
- **Hybrid/semantic search** (`hybrid_search.py`, kolumna `fts_doc`) — osobna ścieżka
  (AI-Matching), poza zakresem tego fixu.

## TODO po merge

- [ ] Merge po zielonym CI → Coolify deploy → smoke `/api/health` (nowy `GIT_SHA`).
- [ ] Chrome MCP: `nexus.dynaminds.pl/candidates?q=lukasz gradzki` → „Łukasz Grądzki" widoczny.
