# AI Modernization — Final Summary (2026-05-08)

8 z 8 itemów planu wdrożone na prod. Cały plan: [`00-baseline-summary.md`](./00-baseline-summary.md). Pełny baseline: [`baseline-2026-05-08-default-30jobs.md`](./baseline-2026-05-08-default-30jobs.md). Po-modernizacji eval: [`eval-2026-05-08-voyage3large.md`](./eval-2026-05-08-voyage3large.md).

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

Pozostały:

1. **Wire hybrid_search.py do UI** — backend gotowy (`/api/candidates?search_type=hybrid` można dodać), toggle w listy kandydatów to osobny FE PR.
2. **Champion-driven scoring (skills layer)** — gdy `job.champion_profile` istnieje, ekstraktować implied skills z `screening_questions.ideal_answer` + `sourcing.keywords` zamiast polegać na must_skills/nice_skills. Wymaga LLM call lub keyword extraction w `scoring_service`.
3. **Rerank w eval_matching** — eval bypasses API endpoints. Refactor żeby szedł przez `hybrid_candidates()` z `hybrid_search.py` da nam offline measurable rerank delta.
4. **Re-run backfill z Ollama** — current run używał regex fallback. Ollama-driven extraction dałby lepszej jakości must_skills. Wymaga włączonego Ollama na serwerze.
5. **Champion Profile dla starych jobów** — ale to praca DL (manual review), nie automatyzacja.

## PR-y zamergowane

- [#119](https://github.com/artur-t-96/Nexus/pull/119) — Items 1-2 (eval bugfix + voyage-3-large)
- [#120](https://github.com/artur-t-96/Nexus/pull/120) — Items 3-8 (rerank, cache, OCR, skills, hybrid, chunking) + batching + jobs FTS migration

## Verification (E2E)

- ✅ Coolify deploy SHA `1678316`, smoke `/api/health` pass
- ✅ Alembic at 0086 head (jobs FTS index created CONCURRENTLY)
- ✅ Reembed 46265/46265 candidates + 3840/3840 jobs, 0 failures
- ✅ Skill aliases 153 skills + 277 aliases inserted
- ✅ Eval ran successfully na nowych voyage-3-large embedding
- ⏳ Chrome MCP smoke (CV upload, AI matches, Champion gen) — TODO follow-up
- ⏳ Włączenie RERANKER_ENABLED=true via Coolify + canary monitoring — TODO follow-up
