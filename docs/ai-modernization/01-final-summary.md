# AI Modernization — Final Summary (2026-05-08)

8 z 8 itemów planu wdrożone na prod. Cały plan: [`00-baseline-summary.md`](./00-baseline-summary.md). Pełny baseline: [`baseline-2026-05-08-default-30jobs.md`](./baseline-2026-05-08-default-30jobs.md). Po-modernizacji eval: [`eval-2026-05-08-voyage3large.md`](./eval-2026-05-08-voyage3large.md).

<<<<<<< HEAD
## Final eval (po wszystkim — Voyage + rerank + Champion + taxonomy + 2x backfill)

| Metric | Baseline (voyage-3, brak aliases, 100% empty must_skills) | Final | Δ relatywne |
|--------|----------|-------|--------------|
| Precision@5 | 0.140 | 0.160 | **+14%** |
| Recall@20 | 0.176 | 0.176 | 0% |
| MRR | 0.253 | **0.351** | **+39%** ⚡ |
| nDCG@10 | 0.187 | **0.205** | **+10%** |
| HistHit@10 | 0.043 | **0.080** | **+86%** ⚡ |
| Jobs missing must_skills | 100% (3839/3840) | **6% (241/3840)** | **-94pp** ⚡ |
| Jobs missing nice_skills | 100% (3837) | 90% (3442) | -10pp |

Trzy etapy backfillu:
1. `backfill_job_criteria.py` (regex TECH_PATTERN, run 1) — 456 jobów, narrow IT-tech only
2. `backfill_job_criteria_taxonomy.py` (regex z 515 aliases, polskie role) — kolejne 1718 jobów
3. `local_claude_backfill.py` (Claude Haiku via OAuth token, async/concurrent ×8) — kolejne 1423 jobów (z 1664 prób, 85% hit rate, 0 failures, ~5 min wall-clock)

**Razem: 3597/3840 jobów ma teraz populated skills.** Skills layer (30% scoring weight) aktywnie różnicuje kandydatów dla 94% jobów (był 12% baseline).
=======
## Final eval (po wszystkim — Voyage + rerank + Champion + taxonomy + backfill)

| Metric | Baseline (voyage-3, brak aliases, 88% empty must_skills) | Final | Δ relatywne |
|--------|----------|-------|--------------|
| Precision@5 | 0.140 | 0.160 | **+14%** |
| Recall@20 | 0.176 | 0.176 | 0% |
| MRR | 0.253 | **0.348** | **+38%** |
| nDCG@10 | 0.187 | 0.203 | **+9%** |
| HistHit@10 | 0.043 | **0.083** | **+93%** ⚡ |
| Jobs missing must_skills | 100% (3839/3840) | 44% (1685/3840) | **-50pp** |
>>>>>>> origin/main

**Najmocniejsze wzrosty:** HistHit@10 (Phase 15 historical retrieval) prawie podwoiło się (+93%); MRR (#1 trafność na top-K) +38%. Re-embed + backfill sprawia że Champion historical retrieval znajduje znacznie więcej trafnych historycznych dopasowań.

**R@20 niezmienione** — sufit narzucony przez retrieval pool: 1685 jobów ma puste tytuły bez wzmianki o jakimkolwiek skillu (głównie polskie tytuły narratywne / numeryczne refy), 10 470 z 46 265 kandydatów ma puste raw_cv_text (niewidzialni w Qdrant). Te dwa braki danych są poza zasięgiem backfillu z naszych źródeł — Traffit b2bnetwork API NIE eksponuje description ani plików dla recruitments.

## Eval — przed vs po (30 jobs default profile)

| Metric | Baseline (voyage-3) | Po Item 2 (voyage-3-large) | Po Item 9 (Champion + backfill + rerank ON) | Δ total absolutne | Δ total relatywne |
|--------|---------------------|---------------------------|---------------------------------------------|-------------------|-------------------|
| Precision@5 | 0.140 | 0.160 | **0.160** | +0.020 | **+14%** |
| Recall@20 | 0.176 | 0.182 | **0.182** | +0.006 | **+3%** |
| MRR | 0.253 | 0.321 | **0.337** | +0.084 | **+33%** |
| nDCG@10 | 0.187 | 0.189 | **0.203** | +0.016 | **+9%** |
| HistHit@10 | 0.043 | 0.057 | **0.057** | +0.014 | **+33%** |

**Item 9 dodatkowy delta** (vs Item 2): MRR +5%, nDCG@10 +7%. Pozostałe nie zmienione bo 30 eval-jobs to głównie stare ogłoszenia bez Champion Profile populated (efekt Champion-aware embedding ujawni się gdy DL zacznie wypełniać Champion Profile dla nowych ról).

**Co eval mierzy:** scoring_service.rank_candidates_for_job (offline). **Czego eval NIE mierzy:**
- Rerank/hybrid są w `/api/jobs/{id}/ai-matches` + `/api/recommendations/cv-upload-preview` + `hybrid_search.py` — eval bypassuje API. Te ulepszenia mierzymy w prod traffic + manualnie.
- Improvement Recall@20 ograniczony przez 100% jobów bez `must_skills` (skills layer short-circuit'uje). Backfill criteria to side-task na backlog.

**Najsilniejsze wzrosty po samym Item 2 (voyage-3-large):** MRR +27%, HistHit@10 +33%, P@5 +14% — model lepiej rankuje top-K i częściej trafia historycznymi-podobnymi rolami.

## Items wdrożone

| # | Item | Status | Co dokładnie |
|---|------|--------|--------------|
| 1 | Baseline metrics | ✅ Done | 30 jobs eval → baseline-2026-05-08-default-30jobs.md |
| 2 | voyage-3 → voyage-3-large | ✅ Done | Model swap + reembed 46K kandydatów + 3840 jobów (~6 min z batchingiem 128/req) |
| 3 | Voyage Rerank 2.5 | ✅ Code shipped | `reranker_service.py` + hooks w `matching.py` + `cv_match_preview.py`. Flag `RERANKER_ENABLED` default OFF (canary) |
| 4 | Embedding cache | ✅ Done | Tabela `embedding_cache` (SHA-256 keyed), `embedding_cache.py` service, hook w `generate_embedding` dla input_type="document" |
| 5 | OCR + pdfplumber | ✅ Done | `cv_text_extractor.py` używa pdfplumber → tesseract OCR fallback dla skanów. Dockerfile + tesseract-pol/eng + poppler-utils |
| 6 | Skill aliases seed | ✅ Done | 153 skills + 277 aliases inserted via `seed_skill_aliases.py` |
| 7 | Hybrid BM25 + dense + RRF | ✅ Done | Migracja 0086 (jobs FTS) + `hybrid_search.py` z RRF k=60. Candidates FTS już istniał (PR #117) |
| 8 | Champion transcript chunking | ✅ Done | Map-reduce (Haiku per chunk → Opus merge) zamiast 40K hard truncate. Wired do enrich_from_meeting + enrich_from_call |

**Bonus:** `reembed_collections.py` z batch=128 (5h sequential → ~6 min batched, ~390 API calls dla 50K).

## Bugfixy obok scope'u

- `eval_matching.py _audit_data_quality`: `cannot get array length of a scalar` (Postgres nie short-circuit-uje `AND jsonb_array_length`). Fix: CASE WHEN jsonb_typeof.
- Migracja `0086_jobs_fts_index`: subquery w GENERATED column nie jest dozwolone w Postgres → uproszczone (FTS zawiera title + requirements + description, bez unpackingu must_skills JSON).
- Coolify alembic drift: po deploy migracja 0085 zderzyła się z `Base.metadata.create_all` (lifespan tworzy tabelę już bez alembic). Fix: `alembic stamp 0085` → `upgrade heads`.

## Pozostałe odkrycia

### Krytyczne data quality (nie naprawione w tym planie)

**100% jobów (3839/3840) nie ma `must_skills` ani `nice_skills`.** To dominujący czynnik niskiego Recall@20 — skills layer short-circuit'uje na max → semantic decyduje sam. Na nowych importach z Traffit (jobs 1391+) Recall@20 = 0.00.

**Rekomendacja (poza scope tego PR):** odpalić `backend/scripts/backfill_job_criteria.py` (regex + Ollama fallback). UWAGA: ma ten sam SQL bug co eval — wymaga tej samej naprawki CASE WHEN przed odpaleniem. Po backfill re-run baseline → spodziewam się R@20 wskoczy z 0.18 → 0.40+.

### Plan Champion Profile-driven matching (z rozmowy)

Long-term: matching kandydat ↔ stanowisko opieramy na Champion Profile (już istnieje, Phase 15: 4 źródła generacji). Scoring layer powinien czytać Champion Profile zamiast plain `must_skills/nice_skills`. Ten plan **nie objął tej zmiany** (Champion infrastructure już jest, ale `scoring_service` używa tylko must/nice_skills).

**Follow-up sugerowany:** dodać do `scoring_service.score_candidate_job` ścieżkę "jeśli `job.champion_profile` istnieje — użyj go zamiast must/nice_skills". Wtedy backfill criteria nie jest tak krytyczny — nowe joby od razu mają Champion Profile generowany z opisu (Item 8 chunking pomaga długim transkryptom).

## Co jeszcze do zrobienia po MVP

✅ ~~Włączyć RERANKER_ENABLED=true~~ — done (default true w config.py, [PR #122](https://github.com/artur-t-96/Nexus/pull/122))
✅ ~~Backfill must_skills~~ — done (fix + run, 456 jobs backfilled regex-only; 3384 nadal puste — większość z brakującym `description`/`requirements` text)
✅ ~~Champion-driven scoring (semantic side)~~ — done przez `_build_job_text` z champion_profile narrative
✅ ~~Champion-driven scoring (skills layer)~~ — done [PR #125](https://github.com/artur-t-96/Nexus/pull/125) + [#126](https://github.com/artur-t-96/Nexus/pull/126). `_score_skills` ma 3-tier fallback: Champion Profile → JD text → title. Word-boundary regex match na seed taxonomy (153 + 277 aliases).

**Eval po Champion-driven scoring:** brak dodatkowego improvement vs poprzedni run. Powód: 0 jobów ma `champion_profile` populated (feature unused przez DLs). Importowane joby (1391+) mają puste `description`/`requirements` AND title to głównie polskie role biznesowe ("Tester Manualny", "Analityk Biznesowy", "Kierownik Projektu") — nie pokryte naszą IT-skills taxonomią. **Architektura jest poprawna i zacznie działać gdy:** (a) DLs wypełnią Champion Profile dla nowych jobów, lub (b) rozszerzymy taxonomy o polskie role biznesowe (Tester, Analityk, Programista, etc).

✅ ~~Wire hybrid_search.py do UI~~ — done [PR #129](https://github.com/artur-t-96/Nexus/pull/129). `/api/search/candidates` przyjmuje `search_mode=hybrid` → BM25+dense+RRF+rerank pipeline. Toggle "Semantycznie" w `FiltersPanel` listy kandydatów.

✅ ~~Polskie role biznesowe w taxonomy~~ — done [PR #129](https://github.com/artur-t-96/Nexus/pull/129). 41 nowych canonical roles + 156 aliases (Tester Manualny, Analityk Biznesowy, Kierownik Projektu, Architekt, DevOps, SAP Consultant, etc). Łącznie taxonomy: **194 canonical + 433 aliases**.

Pozostają (poza scope tego sprintu — wymagają zewnętrznych danych / pracy ludzkiej):

1. **Backfill descriptions z Traffit** — 88% jobów ma empty `description`/`requirements`. Pull oryginalnych JD z Traffit API jeśli dostępne. **Bez tego R@20 capped przez retrieval pool quality** (kandydaci GT nie trafiają do top-200).
2. **CV upload dla 10 470 kandydatów z null skills + null raw_cv_text** — niewidzialni w Qdrant search. Wymaga manual CV upload przez recruterów lub batch import z innego źródła.
3. **Champion Profile dla istniejących jobów** — auto-generation by Claude Opus z opisu (~$200 jednorazowo) lub manual fill przez DL. Po tym Champion-driven scoring zacznie aktywnie działać.
4. **Re-run backfill_job_criteria z Ollama** — current run używał regex fallback (456/3839 trafień). Ollama-driven extraction dałoby lepsze pokrycie. Wymaga aktywnego Ollama na serwerze.
5. **Rerank w eval_matching** — eval bypasses API endpoints. Refactor żeby szedł przez `hybrid_candidates()` da nam offline measurable rerank delta.

## PR-y zamergowane

- [#119](https://github.com/artur-t-96/Nexus/pull/119) — Items 1-2 (eval bugfix + voyage-3-large)
- [#120](https://github.com/artur-t-96/Nexus/pull/120) — Items 3-8 (rerank, cache, OCR, skills, hybrid, chunking) + batching + jobs FTS migration
- [#122](https://github.com/artur-t-96/Nexus/pull/122) — Item 9 (Champion-driven embeddings + rerank default ON + backfill SQL fix)
- [#125](https://github.com/artur-t-96/Nexus/pull/125) — Champion Profile / JD-text fallback w skills scoring layer
- [#126](https://github.com/artur-t-96/Nexus/pull/126) — Title-only fallback (3-tier extraction chain)
- [#129](https://github.com/artur-t-96/Nexus/pull/129) — Hybrid mode wiring (BE+FE) + Polish business roles taxonomy

## Verification (E2E)

- ✅ Coolify deploy SHA `1678316`, smoke `/api/health` pass
- ✅ Alembic at 0086 head (jobs FTS index created CONCURRENTLY)
- ✅ Reembed 46265/46265 candidates + 3840/3840 jobs, 0 failures
- ✅ Skill aliases 153 skills + 277 aliases inserted
- ✅ Eval ran successfully na nowych voyage-3-large embedding
- ⏳ Chrome MCP smoke (CV upload, AI matches, Champion gen) — TODO follow-up
- ⏳ Włączenie RERANKER_ENABLED=true via Coolify + canary monitoring — TODO follow-up
