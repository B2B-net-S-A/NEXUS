# Manual candidate search rebuild — completion report

**Data:** 2026-07-16
**Źródło programu:** `docs/manual-candidate-search-audit-and-implementation-plan-2026-07-15.md` (audyt Codexa, 20 PR / 5 faz)
**Status:** cały bezpieczny/addytywny zakres **DOSTARCZONY i ZWERYFIKOWANY NA PRODZIE** — 19 PR zmergowanych. Pozycje pozostałe = zablokowane z definicji planu (migracje prod / decyzje biznesowe / dedykowane sesje).

## Zakres dostarczony (19 PR, wszystkie zmergowane do `main`)

| PR | Zakres |
|---|---|
| #730 | Phase 0: golden-eval harness (`backend/scripts/eval_candidate_search.py` + fixture + 15 testów) |
| #731 | Phase 1 containment: stawka godzinowa → `expected_rate_hourly` (missing=included), parsowanie lokalizacji + kanoniczny `remote_policy`, strip numeru referencyjnego z zapytania, `nice_skills` nie jest twardą bramką, stale-response race + czyszczenie selekcji |
| #735 | Eligibility CORE: czysty `evaluate_eligibility()` (`candidate_job_eligibility.py`), 16 testów |
| #737 | Eligibility → bulk-add: konflikty klienta blokują, `warnings[]` w odpowiedzi, nowe skip reasons |
| #738 | Eligibility → single-assign (409 na zablokowanych) |
| #739 | Search w kontekście joba ukrywa globalny blacklist (`exclude_blacklisted` wymuszany server-side) |
| #743 | `build_filter_groups()` refaktor + `POST /api/search/candidates/diagnostics` (waterfall wykluczeń) |
| #745 | UI waterfall przy 0 wyników (`ExclusionWaterfall`) |
| #746 | Bulk-add: notatka + tagi w pasku selekcji (`parseTagInput`) |
| #749 | Bulk-add: wybór etapu docelowego (`GET /api/jobs/{id}/assignable-stages`) |
| #750 | Baner wyniku bulk-add: prawdziwe powody skip + warningi (`bulk-result-summary.ts`) |
| #752 | Read-only match-score badges (`POST /api/search/candidates/scores`; celowo NIE compute — ochrona cache) |
| #753 | Explainability: breakdown (matched/gap chips, punkty per warstwa) |
| #754 | Shortlista BACKEND: tabela `job_shortlist_entries` (migracja 0172), CRUD z optimistic lock |
| #755 | Promote shortlisty → pipeline (idempotentny, eligibility-gated) |
| #756 | Shortlista UI: `JobShortlistPanel` (statusy oceny/kontaktu, promote, usuń) |
| #757 | Request-aware compare: `CandidateCompareModal` (macierz kandydat × wymaganie) |
| #760 | Saved-search containment: detekcja formatu + guard przed utratą danych na bell-toggle |
| #762 | Phase 2 core: `CandidateSearchQueryV3` DSL + bezstratne adaptery legacy↔V3 (9 testów kontraktowych) |

Dodatkowo poza planem:
- **#763** `coolify-queue-maintenance.yml` (inspect/cancel/redeploy przez API — odblokowanie zaciętej kolejki deployów po serii merge'ów; workflow NIE loguje surowych payloadów, bo `logs` deploymentu zawiera deploy key).
- **#766** fix kontrastu przycisków paska selekcji (ghost variant był ciemny-na-ciemnym).

## Weryfikacja prod (Chrome, deploy `124a04e`, 2026-07-16)

Na przykładowej ofercie z audytu **ZOB-2846**:
- prefill bez numeru referencyjnego; boolean search **1 wynik** (w audycie: 0), semantyczny 191;
- waterfall wykluczeń: 54 096 → „Zapytanie tekstowe: 1" → „Umiejętności: 0 ← tutaj" — potwierdza root-cause (FTS pełnym tytułem + substring skills), czyli dokładnie to, co adresują odłożone P0-03/P1-02.

Na ofercie testowej **306732** („TEST Claude smoke shortlisty do usuniecia (XYZ-9999)", klient B2B.NET, draft) — pełny łuk:
1. Prefill: ref usunięty, chip „Warszawa" z „Warszawa / Remote", stawka 90–150 NIE trafiła do pól miesięcznych ✓
2. Wyszukiwanie: 924 wyniki / 172 ms ✓
3. Diagnostyka: 54 096 → 8 286 (kategoria) → 924 (lokalizacja) → 924 (eligibility) → **924 (stawka godzinowa — missing=included działa)** ✓
4. Zaznaczenie 2 → pasek selekcji czytelny (#766) → „Do shortlisty" → panel **Shortlista (2)** ✓
5. Zmiany statusów (Zatwierdzony / Zainteresowany) — 2× PATCH z optimistic lock, bez 409 ✓
6. „Porównaj" — modal z poprawnym empty-state (świeża oferta bez cached scores) ✓
7. „Do rekrutacji" — badge „w rekrutacji", kandydat auto-wykluczony z wyników (924→923), kanban „Nowi / Analiza CV: 1" ✓

Zaobserwowane drobiazgi (nie-blokery):
- Baner „Network Error" w trakcie weryfikacji był **przejściowy** (restart kontenera przy deployu) — wszystkie endpointy 200 po ustabilizowaniu.
- Kanban nie odświeża liczników po promote bez przeładowania strony (cache klienta) — kosmetyka do ogarnięcia przy okazji.

## Sprzątanie / follow-upy

- **Oferta testowa 306732 do usunięcia** — jobs mają `DELETE /api/jobs/{id}`, ale brak UI usuwania; skasować przez authed API.
- **Rotacja git deploy key Coolify** — klucz pojawił się raz w logu CI (run skasowany, workflow załatany), rekomendowana rotacja.
- Integration test na 409 przy assign-to-job; toast z powodem w widgetach assign (obecnie połykają błędy).

## Pozostałe pozycje planu (zablokowane z definicji)

- **P0-03 + P1-02 + P1-07:** kanoniczne skills (Cortex resolver) + filter-first hybrid retrieval + **reindeks 54k w Qdrant** (resumable worker, osobna sesja — patrz waterfall ZOB-2846: to jest realny root-cause zerowych wyników).
- **P0-05 tail:** pełna unifikacja saved-search (dual-read/write, splątane z alert executorem — ryzyko alert-storm).
- **Phase 2 tail:** kolumna `dsl_version`, facade, migracja konsumentów na V3.
- **Phase 4/5:** unified scoring + Recruiter Workspace + migracja 4 powierzchni wyszukiwania.
- **Decyzje biznesowe (Artur):** semantyka `Job.salary_min/max` w istniejących rekordach; które typy konfliktów są PRAWNYM hard-blockiem vs ostrzeżeniem.
