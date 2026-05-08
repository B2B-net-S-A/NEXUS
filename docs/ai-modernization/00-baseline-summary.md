# AI Modernization — Baseline (2026-05-08)

## Run config

- **Date:** 2026-05-08 14:31 UTC
- **Where:** prod backend container (`backend-ocgkwcbovpve9wvf9smxl0kx`)
- **Sample:** 30 jobs with ground truth (CandidateStage ≥ screening), pool of 200 candidates per job
- **Profile:** `default_40_30_15_10_5` (semantic=40, skills=30, salary=15, location=10, availability=5)
- **Model:** `voyage-3` (current — Item 2 will upgrade to voyage-3-large)
- **Full report:** [`baseline-2026-05-08-default-30jobs.md`](./baseline-2026-05-08-default-30jobs.md)

## Headline metrics

| Metric | Value | Threshold | Verdict |
|--------|-------|-----------|---------|
| Precision@5 | 0.140 | — | Low |
| **Recall@20** | **0.176** | 0.50 | **NO-GO** |
| MRR | 0.253 | — | Low |
| nDCG@10 | 0.187 | — | Low |
| Historical hit-rate@10 | 0.043 | — | Phase 15 still warming up |

## ⚠️ Critical finding — data quality

**100% jobów nie ma must_skills (3839/3840), 100% bez nice_skills.**

Skutki:
- Skills layer (30% weight) short-circuit'uje na max dla wszystkich kandydatów → przestaje różnicować
- Praktyczny weight matchingu: 70% semantic + 15% salary + 10% location + 5% availability
- Stare jobs (1-13, ręcznie tworzone) — P@5 0.4-0.6, R@20 0.4-0.75 (z must_skills nawet gdy dziś puste, semantic radzi)
- **Nowe jobs (1391+, importy z Traffit/recent) — P@5=0.00, R@20=0.00** (zero kandydatów GT w top-20)

**Hipotezy dla R@20=0:**
1. Imported candidates nie są zembed-owane w Qdrant (`embedding_id` NULL) → niewidzialne w semantic search
2. Job text imports są bardzo generic / krótkie → embedding niestrukturalny
3. Match descrtption text ↔ candidate CV text jest płytki bez skill signal

**Co eval rekomenduje** (z auto-generated finding):
> Run `POST /api/jobs/{id}/refresh-criteria` or a one-time backfill so skills layer can differentiate candidates.

**Co ja proponuję:**
- **Nie blokuj modernizacji** — Items 2-8 mierzymy jako delta vs ten baseline. Jeśli R@20 idzie z 0.176 → 0.30 to wciąż +71% improvement, mierzalne.
- **Backlog (urgent):** uruchomić `backend/scripts/backfill_job_criteria.py` na wszystkich jobs bez must_skills — to side-task niezwiązany z modernizacją AI ale go umożliwia. Powinien być przed Itemem 6 (skill aliases seed).
- **Po backfill:** re-run baseline, mamy "real" baseline. Wtedy dopiero mierzymy każdy Item z planu.

## Per-job breakdown (top regressions)

Wszystkie nowe jobs (ID 1391+) mają R@20=0.00. Szczegóły:

```
Job 1391 — PEP4917 Senior Analyst (GT=61) — R@20=0.00 ← largest GT, zero recall
Job 1392 — Bank Pocztowy Kierownik (GT=11) — R@20=0.00
...
Job 1412 — Orch SA IIS Operations (GT=45) — R@20=0.00
```

vs starsze jobs (kontrast):

```
Job 1 — Senior Angular Developer (GT=4) — R@20=0.75, P@5=0.60, MRR=1.00
Job 2 — Java Backend Developer (GT=8) — R@20=0.62, P@5=0.60, MRR=1.00
Job 3 — DevOps / Cloud Engineer (GT=6) — R@20=0.67, P@5=0.60, MRR=1.00
```

## Bugfix shipped

`backend/scripts/eval_matching.py` — `_audit_data_quality()` failowało SQL `cannot get array length of a scalar` bo Postgres nie short-circuit-uje WHERE i wykonuje `jsonb_array_length` na rzędach gdzie `must_skills` to scalar. Fix: `case() WHEN jsonb_typeof = 'array' THEN jsonb_array_length ELSE 0`.

## Next eval gates

Każdy Item 2-8 wymaga re-run tego eval na 30 jobs default profile. Akceptujemy item gdy:
- Recall@20 nie spadnie więcej niż 5%
- Któraś z kluczowych metryk (P@5 / R@20 / nDCG@10) wzrośnie o min +2 pkt absolutnych
- Latency p95 nie wzrośnie >800ms (rerank exception)

## Mid-execution updates (2026-05-08)

**Discovery during Item 7 prep:** existing infrastructure already has Postgres FTS for candidates:
- Migration `0083_candidate_fts_index.py` — `candidates.fts_doc` tsvector + GIN index (commit dziś rano)
- `backend/app/api/search.py` — używa `websearch_to_tsquery` + `ts_rank` z weighting A/B/C
- `backend/app/schemas/candidate_search.py` — schema już dokumentowany dla FTS

To zmniejsza scope Item 7 (Hybrid Search):
- ❌ Stara sub-task: napisać tsvector + GIN dla candidates (już zrobione)
- ✅ Pozostaje: analogiczna FTS migracja dla `jobs` table
- ✅ Pozostaje: `hybrid_search.py` orchestrator łączący `search.py` BM25 z Qdrant dense via RRF
- ✅ Pozostaje: integracja z reranker (Item 3)
- ✅ Pozostaje: UI toggle dla recruterów

**Reembed running:** start 14:40 UTC, target jobs (3840) + candidates (50K). Jobs ETA 16 min, candidates ETA ~5h. Push Item 3+ wstrzymany do końca reembed (deploy by zabił proces).

## Eval reproduce command

```bash
ssh root@91.99.199.112 "docker exec backend-ocgkwcbovpve9wvf9smxl0kx-135250389391 \
  bash -c 'cd /app && python -m scripts.eval_matching --jobs 30 --output /tmp/eval.md && cat /tmp/eval.md'" \
  > docs/ai-modernization/eval-$(date +%F-%H%M)-default-30jobs.md
```
