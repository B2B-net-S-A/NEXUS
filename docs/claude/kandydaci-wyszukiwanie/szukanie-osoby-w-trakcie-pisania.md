# Szukanie osoby w trakcie pisania: v2 z tekstem dosłownym, krótkie słowo bez ILIKE (26.11.2026)
<!-- indeks: `CANDIDATE_LOOKUP_PARAMS`, paleta ⌘K, `ConsultantPicker`, `NewContractorOrderDialog`, `AddCandidateToJobModal`, `EmailBulkActionBar`, `person_token_exists`, `_exact_person_prefilter`, `_has_trigram`, `test_short_text_person_lookup.py` -->

Produkcja 26.11.2026, 09:45–09:48: `GET /api/candidates` z palety ⌘K trwał 90 s
(16 zapytań, prawie cały czas w bazie), a listy innych osób czekały w tym czasie
7–9 s. Paleta pytała w v1 (`q`, `page_size=5`, `sort=relevance`), a v1 szuka
podłańcucha w `search_doc`, `search_doc_unaccented`, `raw_cv_text` i notatkach.
Dla dwóch znaków indeks trygramowy nie działa, więc to trzy pełne skany tabeli
z rozpakowaniem długich kolumn: w `pg_stat_statements` 66,6 s i 946 tys. stron
z bufora (zero z dysku), na kopii produkcji „qa” 112 s, „c#” 74 s, a zapytanie
zajmuje 3 z 8 vCPU serwera.

- **Paleta ⌘K i wybieraki osób** (`ConsultantPicker`, `NewContractorOrderDialog`,
  `AddCandidateToJobModal`, „Połącz z kandydatem” w `EmailBulkActionBar`) dokładają
  `CANDIDATE_LOOKUP_PARAMS`
  (`semantics_version: 2`, `text_mode: "literal"`, `sort: "relevance"`,
  `lib/candidate-search-semantics.ts`). Krótki tekst (≤ 2 znaki) jest wtedy całym
  słowem przez indeks (`short_literal_match`, decyzja z 07.10.2026), a dłuższy daje
  te same osoby co v1. Na kopii: „qa” 0,37 s, „c#” 0,47 s. Nie `auto`, bo tekst,
  który nie wygląda na osobę, idzie wtedy po znaczeniu (wektory) przy każdym
  wpisanym znaku. Nowe pole, które pyta listę w trakcie pisania, dostaje te same
  parametry.
- **Po trafności, nie „najnowsi”:** przy „najnowsi” z `count(*) OVER ()` i `LIMIT`
  Postgres 16 wybiera pętlę zagnieżdżoną po `ix_candidates_added_to_base_id`
  z filtrem złączenia na sumie identyfikatorów (kopia: v2 „qa”, 15 wierszy —
  690 mln odrzuconych porównań, 83 s; po trafności 0,6 s), a dla szukania osoby
  „najnowsi” i tak gubiło szukaną osobę (UAT M00-B01, paleta i `ConsultantPicker`
  już tak miały).
- **v1 zostaje bez zmian** dla alertów zapisanych wyszukiwań
  (`dwa-silniki-wyszukiwania-jedna-semantyka-filtrow.md`).
- **`person_token_exists` sprawdza samą równość imienia i nazwiska**, bez
  `search_doc_unaccented ILIKE '%słowo%'`. Ten warunek niczego nie odsiewał
  (`search_doc` zaczyna się od `name || ' ' || lastname`), a bez trygramu („zx”)
  albo przy częstym trygramie bez dokładnego trafienia („kow”, „mar”) rozpakowywał
  profil każdej osoby: kopia 8 s, 5–31 s, 22–30 s. Sama równość: 17 tys. stron
  tabeli, 0,1–0,17 s. Pyta o to `interpret_text` przy każdym słowie w palecie
  i wybierakach (v2), na liście i w wyszukiwarce, oraz `/keywords/classify?context=top`.
- **`_exact_person_prefilter`** (2–3 wyrazy, tylko `text_mode=auto`) zostawia
  `ILIKE` wyłącznie dla wyrazów z trygramem (`_has_trigram`): przecięcie trygramów
  kilku wyrazów zawęża dobrze, a wyraz bez trygramu („Jo”) czytałby całą tabelę.
- **Gdy się powtórzy:** `pg_stat_statements` od razu po zgłoszeniu (`max_exec_time`,
  `calls`, `shared_blks_hit` dla zapytań z `ILIKE` po `search_doc` albo `raw_cv_text`).
  Wpis z jednym wywołaniem wypada przy `dealloc` (26.11: 692 razy w 19 h przy limicie
  5000) — ten z 66,6 s zniknął w trakcie odczytu. Logi kontenera web rotują po ok. 1 h,
  a `http_outcome` nie ma parametrów zapytania.
