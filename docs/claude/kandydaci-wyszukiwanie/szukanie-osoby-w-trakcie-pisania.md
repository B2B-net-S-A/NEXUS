# Szukanie osoby w trakcie pisania: v2 z tekstem dosłownym, krótkie słowo bez ILIKE (26.11.2026)
<!-- indeks: `CANDIDATE_LOOKUP_PARAMS`, paleta ⌘K, `ConsultantPicker`, `NewContractorOrderDialog`, `AddCandidateToJobModal`, `person_token_exists`, `_exact_person_prefilter`, `_has_trigram`, `test_short_text_person_lookup.py` -->

Produkcja 26.11.2026, 09:45–09:48: `GET /api/candidates` z palety ⌘K trwał 90 s
(16 zapytań, prawie cały czas w bazie), a listy innych osób czekały w tym czasie
7–9 s. Paleta pytała w v1 (`q`, `page_size=5`, `sort=relevance`), a v1 szuka
podłańcucha w `search_doc`, `search_doc_unaccented`, `raw_cv_text` i notatkach.
Dla dwóch znaków indeks trygramowy nie działa, więc to trzy pełne skany tabeli
z rozpakowaniem długich kolumn: w `pg_stat_statements` 66,6 s i 946 tys. stron
z bufora (zero z dysku), na kopii produkcji „qa” 112 s, „c#” 74 s, a zapytanie
zajmuje 3 z 8 vCPU serwera.

- **Paleta ⌘K i wybieraki osób** (`ConsultantPicker`, `NewContractorOrderDialog`,
  `AddCandidateToJobModal`) dokładają `CANDIDATE_LOOKUP_PARAMS`
  (`semantics_version: 2`, `text_mode: "literal"`, `lib/candidate-search-semantics.ts`).
  Krótki tekst (≤ 2 znaki) jest wtedy całym słowem przez indeks
  (`short_literal_match`, decyzja z 07.10.2026), a dłuższy daje te same osoby co v1.
  Na kopii: „qa” 0,37 s, „c#” 0,47 s. Nie `auto`, bo tekst, który nie wygląda na
  osobę, idzie wtedy po znaczeniu (wektory) przy każdym wpisanym znaku. Nowe pole,
  które pyta listę w trakcie pisania, dostaje te same parametry.
- **v1 zostaje bez zmian** dla alertów zapisanych wyszukiwań
  (`dwa-silniki-wyszukiwania-jedna-semantyka-filtrow.md`).
- **`person_token_exists` i `_exact_person_prefilter` filtrują `search_doc_unaccented
  ILIKE` tylko słowa z trygramem** (`_has_trigram`: trzy litery lub cyfry z rzędu).
  Dla „zx” `ILIKE` bez indeksu rozpakowywał profil każdej osoby (kopia: 283 tys.
  stron, od 8 s do ponad 120 s pod obciążeniem), a wynik i tak rozstrzyga równość
  imienia i nazwiska: `search_doc` zaczyna się od `name || ' ' || lastname`.
  Teraz 17 tys. stron samej tabeli, 0,1–0,15 s. Z tej funkcji korzysta
  `interpret_text` (lista i wyszukiwarka w v2) i `/keywords/classify?context=top`
  (słowa „go”, „c#” z górnego pola).
- **Gdy się powtórzy:** `pg_stat_statements` od razu po zgłoszeniu (`max_exec_time`,
  `calls`, `shared_blks_hit` dla zapytań z `ILIKE` po `search_doc` albo `raw_cv_text`).
  Wpis z jednym wywołaniem wypada przy `dealloc` (26.11: 692 razy w 19 h przy limicie
  5000) — ten z 66,6 s zniknął w trakcie odczytu. Logi kontenera web rotują po ok. 1 h,
  a `http_outcome` nie ma parametrów zapytania.
