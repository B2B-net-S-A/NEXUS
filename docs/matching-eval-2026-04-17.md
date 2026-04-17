# Matching Quality Audit — Phase 0

Generated at: `2026-04-17T10:45:13.060582+00:00`

## Data quality snapshot

- Jobs: 15 total; **missing must_skills**: 15 (100%); missing nice_skills: 15 (100%)
- Candidate skills JSONB format: list-of-dict/str = 30, dict (`technologies`/`stack`) = 20, null = 0 (total=50)
- Voyage API key configured: **no (semantic layer inert — pool falls back to all active candidates)**

## Summary

| Profile | Jobs | Precision@5 | Recall@20 | MRR | nDCG@10 |
|---|---:|---:|---:|---:|---:|
| `default_40_30_15_10_5` | 8 | 0.200 | 0.554 | 0.447 | 0.329 |
| `semantic_only` | 8 | 0.125 | 0.415 | 0.323 | 0.244 |
| `skills_only` | 8 | 0.125 | 0.415 | 0.323 | 0.244 |
| `skills_heavy` | 8 | 0.200 | 0.606 | 0.447 | 0.329 |
| `semantic_heavy` | 8 | 0.200 | 0.606 | 0.447 | 0.329 |
| `balanced` | 8 | 0.200 | 0.554 | 0.447 | 0.329 |

## Go/No-Go verdict

> GO (with caveats) — ship Phase A in parallel with Phase D1/B1. Best profile `skills_heavy` (Recall@20 = 0.61) beats default (Recall@20 = 0.55) — recommend Phase D1 weight tuning. Note: these numbers are on a dataset where 100% of jobs lack `must_skills`, so the skills layer is effectively disabled — production numbers should be materially higher once must/nice are populated.

## Findings & recommended actions

- **100% jobs lack `must_skills`** — skills layer short-circuits to max for these jobs (see `_score_skills` line 150). Run `POST /api/jobs/{id}/refresh-criteria` or a one-time backfill so skills layer can differentiate candidates.
- **20 candidates** store skills as a dict (`{technologies: [...]}`) — already handled by the patched `_skill_names()` parser, but consider migrating to the canonical `[{name, level, years}]` shape so UI and filters see uniform data.
- **Semantic layer is inert** (no `VOYAGE_API_KEY` in env) — scoring falls back to skills/salary/location/availability only. Configure Voyage + embed existing candidates/jobs before trusting production numbers.
- **Profile `skills_heavy`** beats the default on Recall@20 (0.606 vs 0.554). Consider adopting these weights (Phase D1 — weight tuning).

## Profile: `default_40_30_15_10_5`

Weights: semantic=40.0, skills=30.0, salary=15.0, location=10.0, availability=5.0

| Job ID | Title | GT size | Pool | P@5 | R@20 | MRR | nDCG@10 |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | Senior Angular Developer | 4 | 50 | 0.20 | 0.25 | 1.00 | 0.48 |
| 2 | Java Backend Developer | 6 | 50 | 0.00 | 0.50 | 0.08 | 0.00 |
| 3 | DevOps / Cloud Engineer | 6 | 50 | 0.20 | 0.50 | 0.50 | 0.37 |
| 4 | QA Automation Engineer | 4 | 50 | 0.00 | 0.50 | 0.17 | 0.09 |
| 5 | Python Data Engineer | 5 | 50 | 0.40 | 0.60 | 0.50 | 0.58 |
| 6 | React Frontend Developer | 3 | 50 | 0.20 | 0.67 | 0.33 | 0.47 |
| 7 | Scrum Master / Agile Coach | 4 | 50 | 0.40 | 0.75 | 0.50 | 0.48 |
| 13 | Data Engineer | 3 | 50 | 0.20 | 0.67 | 0.50 | 0.16 |

## Profile: `semantic_only`

Weights: semantic=100.0, skills=0.0, salary=0.0, location=0.0, availability=0.0

| Job ID | Title | GT size | Pool | P@5 | R@20 | MRR | nDCG@10 |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | Senior Angular Developer | 4 | 50 | 0.20 | 0.50 | 1.00 | 0.48 |
| 2 | Java Backend Developer | 6 | 50 | 0.20 | 0.50 | 0.50 | 0.37 |
| 3 | DevOps / Cloud Engineer | 6 | 50 | 0.20 | 0.50 | 0.33 | 0.28 |
| 4 | QA Automation Engineer | 4 | 50 | 0.20 | 0.50 | 0.25 | 0.08 |
| 5 | Python Data Engineer | 5 | 50 | 0.20 | 0.40 | 0.20 | 0.26 |
| 6 | React Frontend Developer | 3 | 50 | 0.00 | 0.67 | 0.17 | 0.29 |
| 7 | Scrum Master / Agile Coach | 4 | 50 | 0.00 | 0.25 | 0.10 | 0.20 |
| 13 | Data Engineer | 3 | 50 | 0.00 | 0.00 | 0.03 | 0.00 |

## Profile: `skills_only`

Weights: semantic=0.0, skills=100.0, salary=0.0, location=0.0, availability=0.0

| Job ID | Title | GT size | Pool | P@5 | R@20 | MRR | nDCG@10 |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | Senior Angular Developer | 4 | 50 | 0.20 | 0.50 | 1.00 | 0.48 |
| 2 | Java Backend Developer | 6 | 50 | 0.20 | 0.50 | 0.50 | 0.37 |
| 3 | DevOps / Cloud Engineer | 6 | 50 | 0.20 | 0.50 | 0.33 | 0.28 |
| 4 | QA Automation Engineer | 4 | 50 | 0.20 | 0.50 | 0.25 | 0.08 |
| 5 | Python Data Engineer | 5 | 50 | 0.20 | 0.40 | 0.20 | 0.26 |
| 6 | React Frontend Developer | 3 | 50 | 0.00 | 0.67 | 0.17 | 0.29 |
| 7 | Scrum Master / Agile Coach | 4 | 50 | 0.00 | 0.25 | 0.10 | 0.20 |
| 13 | Data Engineer | 3 | 50 | 0.00 | 0.00 | 0.03 | 0.00 |

## Profile: `skills_heavy`

Weights: semantic=20.0, skills=60.0, salary=10.0, location=5.0, availability=5.0

| Job ID | Title | GT size | Pool | P@5 | R@20 | MRR | nDCG@10 |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | Senior Angular Developer | 4 | 50 | 0.20 | 0.50 | 1.00 | 0.48 |
| 2 | Java Backend Developer | 6 | 50 | 0.00 | 0.50 | 0.08 | 0.00 |
| 3 | DevOps / Cloud Engineer | 6 | 50 | 0.20 | 0.67 | 0.50 | 0.37 |
| 4 | QA Automation Engineer | 4 | 50 | 0.00 | 0.50 | 0.17 | 0.09 |
| 5 | Python Data Engineer | 5 | 50 | 0.40 | 0.60 | 0.50 | 0.58 |
| 6 | React Frontend Developer | 3 | 50 | 0.20 | 0.67 | 0.33 | 0.47 |
| 7 | Scrum Master / Agile Coach | 4 | 50 | 0.40 | 0.75 | 0.50 | 0.48 |
| 13 | Data Engineer | 3 | 50 | 0.20 | 0.67 | 0.50 | 0.16 |

## Profile: `semantic_heavy`

Weights: semantic=60.0, skills=20.0, salary=10.0, location=5.0, availability=5.0

| Job ID | Title | GT size | Pool | P@5 | R@20 | MRR | nDCG@10 |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | Senior Angular Developer | 4 | 50 | 0.20 | 0.50 | 1.00 | 0.48 |
| 2 | Java Backend Developer | 6 | 50 | 0.00 | 0.50 | 0.08 | 0.00 |
| 3 | DevOps / Cloud Engineer | 6 | 50 | 0.20 | 0.67 | 0.50 | 0.37 |
| 4 | QA Automation Engineer | 4 | 50 | 0.00 | 0.50 | 0.17 | 0.09 |
| 5 | Python Data Engineer | 5 | 50 | 0.40 | 0.60 | 0.50 | 0.58 |
| 6 | React Frontend Developer | 3 | 50 | 0.20 | 0.67 | 0.33 | 0.47 |
| 7 | Scrum Master / Agile Coach | 4 | 50 | 0.40 | 0.75 | 0.50 | 0.48 |
| 13 | Data Engineer | 3 | 50 | 0.20 | 0.67 | 0.50 | 0.16 |

## Profile: `balanced`

Weights: semantic=30.0, skills=30.0, salary=20.0, location=15.0, availability=5.0

| Job ID | Title | GT size | Pool | P@5 | R@20 | MRR | nDCG@10 |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | Senior Angular Developer | 4 | 50 | 0.20 | 0.25 | 1.00 | 0.48 |
| 2 | Java Backend Developer | 6 | 50 | 0.00 | 0.50 | 0.08 | 0.00 |
| 3 | DevOps / Cloud Engineer | 6 | 50 | 0.20 | 0.50 | 0.50 | 0.37 |
| 4 | QA Automation Engineer | 4 | 50 | 0.00 | 0.50 | 0.17 | 0.09 |
| 5 | Python Data Engineer | 5 | 50 | 0.40 | 0.60 | 0.50 | 0.58 |
| 6 | React Frontend Developer | 3 | 50 | 0.20 | 0.67 | 0.33 | 0.47 |
| 7 | Scrum Master / Agile Coach | 4 | 50 | 0.40 | 0.75 | 0.50 | 0.48 |
| 13 | Data Engineer | 3 | 50 | 0.20 | 0.67 | 0.50 | 0.16 |

## Error analysis (worst Recall@20, default profile)

- **Job 1 — Senior Angular Developer** — GT=4, R@20=0.25, missed=[42, 12, 39]
- **Job 2 — Java Backend Developer** — GT=6, R@20=0.50, missed=[32, 37, 50]
- **Job 3 — DevOps / Cloud Engineer** — GT=6, R@20=0.50, missed=[13, 20, 28]
- **Job 4 — QA Automation Engineer** — GT=4, R@20=0.50, missed=[34, 45]
- **Job 5 — Python Data Engineer** — GT=5, R@20=0.60, missed=[40, 23]
- **Job 6 — React Frontend Developer** — GT=3, R@20=0.67, missed=[29]
- **Job 13 — Data Engineer** — GT=3, R@20=0.67, missed=[48]
- **Job 7 — Scrum Master / Agile Coach** — GT=4, R@20=0.75, missed=[36]

## Reproduce

```bash
cd backend && python -m scripts.eval_matching --ablation \
    --output ../docs/matching-eval-$(date +%F).md
```
