# Matching Quality Audit — Phase 0

Generated at: `2026-04-17T10:59:25.432578+00:00`

## Data quality snapshot

- Jobs: 15 total; **missing must_skills**: 3 (20%); missing nice_skills: 14 (93%)
- Candidate skills JSONB format: list-of-dict/str = 30, dict (`technologies`/`stack`) = 20, null = 0 (total=50)
- Voyage API key configured: **no (semantic layer inert — pool falls back to all active candidates)**

## Summary

| Profile | Jobs | Precision@5 | Recall@20 | MRR | nDCG@10 |
|---|---:|---:|---:|---:|---:|
| `default_40_30_15_10_5` | 8 | 0.500 | 0.798 | 0.938 | 0.799 |
| `semantic_only` | 8 | 0.125 | 0.415 | 0.323 | 0.244 |
| `skills_only` | 8 | 0.375 | 0.746 | 0.718 | 0.697 |
| `skills_heavy` | 8 | 0.500 | 0.819 | 0.938 | 0.795 |
| `semantic_heavy` | 8 | 0.500 | 0.819 | 0.854 | 0.748 |
| `balanced` | 8 | 0.500 | 0.798 | 0.938 | 0.800 |

## Go/No-Go verdict

> GO (with caveats) — ship Phase A in parallel with Phase D1/B1. Best profile `skills_heavy` (Recall@20 = 0.82) beats default (Recall@20 = 0.80) — recommend Phase D1 weight tuning.

## Findings & recommended actions

- **20 candidates** store skills as a dict (`{technologies: [...]}`) — already handled by the patched `_skill_names()` parser, but consider migrating to the canonical `[{name, level, years}]` shape so UI and filters see uniform data.
- **Semantic layer is inert** (no `VOYAGE_API_KEY` in env) — scoring falls back to skills/salary/location/availability only. Configure Voyage + embed existing candidates/jobs before trusting production numbers.
- **Profile `skills_heavy`** beats the default on Recall@20 (0.819 vs 0.798). Consider adopting these weights (Phase D1 — weight tuning).

## Profile: `default_40_30_15_10_5`

Weights: semantic=40.0, skills=30.0, salary=15.0, location=10.0, availability=5.0

| Job ID | Title | GT size | Pool | P@5 | R@20 | MRR | nDCG@10 |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | Senior Angular Developer | 4 | 50 | 0.60 | 1.00 | 1.00 | 0.89 |
| 2 | Java Backend Developer | 6 | 50 | 0.60 | 0.50 | 1.00 | 0.85 |
| 3 | DevOps / Cloud Engineer | 6 | 50 | 0.60 | 0.67 | 1.00 | 0.80 |
| 4 | QA Automation Engineer | 4 | 50 | 0.60 | 1.00 | 1.00 | 0.92 |
| 5 | Python Data Engineer | 5 | 50 | 0.60 | 0.80 | 1.00 | 0.93 |
| 6 | React Frontend Developer | 3 | 50 | 0.40 | 0.67 | 1.00 | 0.95 |
| 7 | Scrum Master / Agile Coach | 4 | 50 | 0.40 | 0.75 | 0.50 | 0.48 |
| 13 | Data Engineer | 3 | 50 | 0.20 | 1.00 | 1.00 | 0.57 |

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
| 1 | Senior Angular Developer | 4 | 50 | 0.60 | 1.00 | 1.00 | 0.87 |
| 2 | Java Backend Developer | 6 | 50 | 0.60 | 0.83 | 1.00 | 0.86 |
| 3 | DevOps / Cloud Engineer | 6 | 50 | 0.60 | 0.67 | 1.00 | 0.86 |
| 4 | QA Automation Engineer | 4 | 50 | 0.40 | 0.75 | 1.00 | 0.87 |
| 5 | Python Data Engineer | 5 | 50 | 0.40 | 0.80 | 0.50 | 0.63 |
| 6 | React Frontend Developer | 3 | 50 | 0.40 | 0.67 | 1.00 | 0.95 |
| 7 | Scrum Master / Agile Coach | 4 | 50 | 0.00 | 0.25 | 0.10 | 0.20 |
| 13 | Data Engineer | 3 | 50 | 0.00 | 1.00 | 0.14 | 0.33 |

## Profile: `skills_heavy`

Weights: semantic=20.0, skills=60.0, salary=10.0, location=5.0, availability=5.0

| Job ID | Title | GT size | Pool | P@5 | R@20 | MRR | nDCG@10 |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | Senior Angular Developer | 4 | 50 | 0.60 | 1.00 | 1.00 | 0.89 |
| 2 | Java Backend Developer | 6 | 50 | 0.60 | 0.67 | 1.00 | 0.85 |
| 3 | DevOps / Cloud Engineer | 6 | 50 | 0.60 | 0.67 | 1.00 | 0.80 |
| 4 | QA Automation Engineer | 4 | 50 | 0.60 | 1.00 | 1.00 | 0.92 |
| 5 | Python Data Engineer | 5 | 50 | 0.60 | 0.80 | 1.00 | 0.89 |
| 6 | React Frontend Developer | 3 | 50 | 0.40 | 0.67 | 1.00 | 0.95 |
| 7 | Scrum Master / Agile Coach | 4 | 50 | 0.40 | 0.75 | 0.50 | 0.48 |
| 13 | Data Engineer | 3 | 50 | 0.20 | 1.00 | 1.00 | 0.57 |

## Profile: `semantic_heavy`

Weights: semantic=60.0, skills=20.0, salary=10.0, location=5.0, availability=5.0

| Job ID | Title | GT size | Pool | P@5 | R@20 | MRR | nDCG@10 |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | Senior Angular Developer | 4 | 50 | 0.60 | 1.00 | 1.00 | 0.89 |
| 2 | Java Backend Developer | 6 | 50 | 0.60 | 0.67 | 1.00 | 0.85 |
| 3 | DevOps / Cloud Engineer | 6 | 50 | 0.60 | 0.67 | 1.00 | 0.80 |
| 4 | QA Automation Engineer | 4 | 50 | 0.60 | 1.00 | 0.33 | 0.55 |
| 5 | Python Data Engineer | 5 | 50 | 0.60 | 0.80 | 1.00 | 0.89 |
| 6 | React Frontend Developer | 3 | 50 | 0.40 | 0.67 | 1.00 | 0.95 |
| 7 | Scrum Master / Agile Coach | 4 | 50 | 0.40 | 0.75 | 0.50 | 0.48 |
| 13 | Data Engineer | 3 | 50 | 0.20 | 1.00 | 1.00 | 0.57 |

## Profile: `balanced`

Weights: semantic=30.0, skills=30.0, salary=20.0, location=15.0, availability=5.0

| Job ID | Title | GT size | Pool | P@5 | R@20 | MRR | nDCG@10 |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | Senior Angular Developer | 4 | 50 | 0.60 | 1.00 | 1.00 | 0.90 |
| 2 | Java Backend Developer | 6 | 50 | 0.60 | 0.50 | 1.00 | 0.85 |
| 3 | DevOps / Cloud Engineer | 6 | 50 | 0.60 | 0.67 | 1.00 | 0.80 |
| 4 | QA Automation Engineer | 4 | 50 | 0.60 | 1.00 | 1.00 | 0.92 |
| 5 | Python Data Engineer | 5 | 50 | 0.60 | 0.80 | 1.00 | 0.93 |
| 6 | React Frontend Developer | 3 | 50 | 0.40 | 0.67 | 1.00 | 0.95 |
| 7 | Scrum Master / Agile Coach | 4 | 50 | 0.40 | 0.75 | 0.50 | 0.48 |
| 13 | Data Engineer | 3 | 50 | 0.20 | 1.00 | 1.00 | 0.57 |

## Error analysis (worst Recall@20, default profile)

- **Job 2 — Java Backend Developer** — GT=6, R@20=0.50, missed=[8, 18, 50]
- **Job 3 — DevOps / Cloud Engineer** — GT=6, R@20=0.67, missed=[20, 28]
- **Job 6 — React Frontend Developer** — GT=3, R@20=0.67, missed=[29]
- **Job 7 — Scrum Master / Agile Coach** — GT=4, R@20=0.75, missed=[36]
- **Job 5 — Python Data Engineer** — GT=5, R@20=0.80, missed=[23]
- **Job 1 — Senior Angular Developer** — GT=4, R@20=1.00, missed=[]
- **Job 4 — QA Automation Engineer** — GT=4, R@20=1.00, missed=[]
- **Job 13 — Data Engineer** — GT=3, R@20=1.00, missed=[]

## Reproduce

```bash
cd backend && python -m scripts.eval_matching --ablation \
    --output ../docs/matching-eval-$(date +%F).md
```
