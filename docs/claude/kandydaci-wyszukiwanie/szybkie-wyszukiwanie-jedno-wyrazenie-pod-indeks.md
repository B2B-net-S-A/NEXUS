# Szybkie wyszukiwanie kandydatów: jedno wyrażenie pod indeks GIN
<!-- indeks: `_candidate_quick_match`, `global_search`, `ix_candidates_quick_identity_trgm`, `ix_candidates_phone_digits_trgm`, `PHONE_DIGITS_SQL`, migracja 0662 -->

Audyt 08.11.2026, S4 i W6. Po #3145 `GET /api/search/global` składał polskie
znaki `translate()` na pięciu osobnych wyrażeniach, więc fraza bez trafienia
to był seq scan 68 tys. wierszy.

- **Jedno wyrażenie.** `_CANDIDATE_IDENTITY_FOLDED_SQL` w `api/search.py` to
  `name lastname email lastname name` po foldzie. Powtórzenie imienia i nazwiska
  daje „Imię Nazwisko” i „Nazwisko Imię” w jednym `ILIKE`, a indeksu prawie nie
  powiększa, bo trygramy są zbiorem. Telefon to `PHONE_DIGITS_SQL`.
- **`concat_ws` i `concat` nie wchodzą do indeksu**, bo są STABLE
  („functions in index expression must be marked IMMUTABLE”). Stąd `||` i `coalesce`.
- **Wyrażenia są gotowym SQL-em** (`literal_column`), nie `func.*`. Indeks pasuje
  tylko do identycznego drzewa, a parametry wiązane w miejscu stałych psują to
  w planie ogólnym. `literal_column` nie dokłada tabeli do `FROM`, więc zapytanie
  musi wybierać z `Candidate` jawnie.
- **Zmiana wyrażenia to trzy miejsca co do znaku:** kod, migracja, lustro
  w `_INDEX_STATEMENTS` w `entrypoint.sh`. Pilnuje
  `test_candidate_quick_search_index.py`, także planem zapytania.
