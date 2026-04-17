# Matching Quality Audit — Phase 0

Generated at: `2026-04-17T11:51:02.637900+00:00`

## Data quality snapshot

- Jobs: 15 total; **missing must_skills**: 3 (20%); missing nice_skills: 14 (93%)
- Candidate skills JSONB format: list-of-dict/str = 30, dict (`technologies`/`stack`) = 20, null = 0 (total=50)
- Voyage API key configured: **no (semantic layer inert — pool falls back to all active candidates)**

## Summary

| Profile | Jobs | Precision@5 | Recall@20 | MRR | nDCG@10 |
|---|---:|---:|---:|---:|---:|
| `default_40_30_15_10_5` | 8 | 0.550 | 0.840 | 1.000 | 0.803 |
| `semantic_only` | 8 | 0.625 | 0.819 | 0.938 | 0.769 |
| `skills_only` | 8 | 0.375 | 0.844 | 0.833 | 0.628 |
| `skills_heavy` | 8 | 0.500 | 0.819 | 1.000 | 0.811 |
| `semantic_heavy` | 8 | 0.600 | 0.819 | 1.000 | 0.789 |
| `balanced` | 8 | 0.550 | 0.819 | 1.000 | 0.817 |

## Go/No-Go verdict

> GO (with caveats) — ship Phase A in parallel with Phase D1/B1. Best profile `skills_only` (Recall@20 = 0.84) beats default (Recall@20 = 0.84) — recommend Phase D1 weight tuning.

## Findings & recommended actions

- **20 candidates** store skills as a dict (`{technologies: [...]}`) — already handled by the patched `_skill_names()` parser, but consider migrating to the canonical `[{name, level, years}]` shape so UI and filters see uniform data.
- **Semantic layer is inert** (no `VOYAGE_API_KEY` in env) — scoring falls back to skills/salary/location/availability only. Configure Voyage + embed existing candidates/jobs before trusting production numbers.

## Profile: `default_40_30_15_10_5`

Weights: semantic=40.0, skills=30.0, salary=15.0, location=10.0, availability=5.0

| Job ID | Title | GT size | Pool | P@5 | R@20 | MRR | nDCG@10 |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | Senior Angular Developer | 4 | 50 | 0.60 | 1.00 | 1.00 | 0.92 |
| 2 | Java Backend Developer | 6 | 50 | 0.60 | 0.83 | 1.00 | 0.85 |
| 3 | DevOps / Cloud Engineer | 6 | 50 | 0.60 | 0.67 | 1.00 | 0.80 |
| 4 | QA Automation Engineer | 4 | 50 | 0.60 | 1.00 | 1.00 | 0.68 |
| 5 | Python Data Engineer | 5 | 50 | 0.60 | 0.80 | 1.00 | 0.93 |
| 6 | React Frontend Developer | 3 | 50 | 0.40 | 0.67 | 1.00 | 0.95 |
| 7 | Scrum Master / Agile Coach | 4 | 50 | 0.60 | 0.75 | 1.00 | 0.65 |
| 13 | Data Engineer | 3 | 50 | 0.40 | 1.00 | 1.00 | 0.63 |

## Profile: `semantic_only`

Weights: semantic=100.0, skills=0.0, salary=0.0, location=0.0, availability=0.0

| Job ID | Title | GT size | Pool | P@5 | R@20 | MRR | nDCG@10 |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | Senior Angular Developer | 4 | 50 | 0.60 | 1.00 | 1.00 | 0.90 |
| 2 | Java Backend Developer | 6 | 50 | 0.80 | 0.67 | 1.00 | 0.82 |
| 3 | DevOps / Cloud Engineer | 6 | 50 | 0.60 | 0.67 | 1.00 | 0.76 |
| 4 | QA Automation Engineer | 4 | 50 | 0.80 | 1.00 | 1.00 | 0.72 |
| 5 | Python Data Engineer | 5 | 50 | 0.60 | 0.80 | 1.00 | 0.87 |
| 6 | React Frontend Developer | 3 | 50 | 0.40 | 0.67 | 1.00 | 0.95 |
| 7 | Scrum Master / Agile Coach | 4 | 50 | 0.60 | 0.75 | 1.00 | 0.53 |
| 13 | Data Engineer | 3 | 50 | 0.60 | 1.00 | 0.50 | 0.60 |

## Profile: `skills_only`

Weights: semantic=0.0, skills=100.0, salary=0.0, location=0.0, availability=0.0

| Job ID | Title | GT size | Pool | P@5 | R@20 | MRR | nDCG@10 |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | Senior Angular Developer | 4 | 50 | 0.60 | 1.00 | 1.00 | 0.82 |
| 2 | Java Backend Developer | 6 | 50 | 0.60 | 0.67 | 1.00 | 0.81 |
| 3 | DevOps / Cloud Engineer | 6 | 50 | 0.60 | 0.83 | 1.00 | 0.80 |
| 4 | QA Automation Engineer | 4 | 50 | 0.20 | 1.00 | 1.00 | 0.75 |
| 5 | Python Data Engineer | 5 | 50 | 0.20 | 1.00 | 0.33 | 0.15 |
| 6 | React Frontend Developer | 3 | 50 | 0.40 | 1.00 | 1.00 | 0.95 |
| 7 | Scrum Master / Agile Coach | 4 | 50 | 0.20 | 0.25 | 1.00 | 0.23 |
| 13 | Data Engineer | 3 | 50 | 0.20 | 1.00 | 0.33 | 0.52 |

## Profile: `skills_heavy`

Weights: semantic=20.0, skills=60.0, salary=10.0, location=5.0, availability=5.0

| Job ID | Title | GT size | Pool | P@5 | R@20 | MRR | nDCG@10 |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | Senior Angular Developer | 4 | 50 | 0.60 | 1.00 | 1.00 | 0.91 |
| 2 | Java Backend Developer | 6 | 50 | 0.60 | 0.67 | 1.00 | 0.85 |
| 3 | DevOps / Cloud Engineer | 6 | 50 | 0.60 | 0.67 | 1.00 | 0.80 |
| 4 | QA Automation Engineer | 4 | 50 | 0.60 | 1.00 | 1.00 | 0.98 |
| 5 | Python Data Engineer | 5 | 50 | 0.60 | 0.80 | 1.00 | 0.89 |
| 6 | React Frontend Developer | 3 | 50 | 0.40 | 0.67 | 1.00 | 0.95 |
| 7 | Scrum Master / Agile Coach | 4 | 50 | 0.40 | 0.75 | 1.00 | 0.53 |
| 13 | Data Engineer | 3 | 50 | 0.20 | 1.00 | 1.00 | 0.58 |

## Profile: `semantic_heavy`

Weights: semantic=60.0, skills=20.0, salary=10.0, location=5.0, availability=5.0

| Job ID | Title | GT size | Pool | P@5 | R@20 | MRR | nDCG@10 |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | Senior Angular Developer | 4 | 50 | 0.60 | 1.00 | 1.00 | 0.92 |
| 2 | Java Backend Developer | 6 | 50 | 0.60 | 0.67 | 1.00 | 0.87 |
| 3 | DevOps / Cloud Engineer | 6 | 50 | 0.60 | 0.67 | 1.00 | 0.79 |
| 4 | QA Automation Engineer | 4 | 50 | 0.80 | 1.00 | 1.00 | 0.69 |
| 5 | Python Data Engineer | 5 | 50 | 0.60 | 0.80 | 1.00 | 0.89 |
| 6 | React Frontend Developer | 3 | 50 | 0.40 | 0.67 | 1.00 | 0.95 |
| 7 | Scrum Master / Agile Coach | 4 | 50 | 0.60 | 0.75 | 1.00 | 0.56 |
| 13 | Data Engineer | 3 | 50 | 0.60 | 1.00 | 1.00 | 0.64 |

## Profile: `balanced`

Weights: semantic=30.0, skills=30.0, salary=20.0, location=15.0, availability=5.0

| Job ID | Title | GT size | Pool | P@5 | R@20 | MRR | nDCG@10 |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | Senior Angular Developer | 4 | 50 | 0.60 | 1.00 | 1.00 | 0.92 |
| 2 | Java Backend Developer | 6 | 50 | 0.60 | 0.67 | 1.00 | 0.85 |
| 3 | DevOps / Cloud Engineer | 6 | 50 | 0.60 | 0.67 | 1.00 | 0.80 |
| 4 | QA Automation Engineer | 4 | 50 | 0.60 | 1.00 | 1.00 | 0.63 |
| 5 | Python Data Engineer | 5 | 50 | 0.60 | 0.80 | 1.00 | 0.93 |
| 6 | React Frontend Developer | 3 | 50 | 0.40 | 0.67 | 1.00 | 0.95 |
| 7 | Scrum Master / Agile Coach | 4 | 50 | 0.60 | 0.75 | 1.00 | 0.85 |
| 13 | Data Engineer | 3 | 50 | 0.40 | 1.00 | 1.00 | 0.60 |

## Error analysis (worst Recall@20, default profile)

- **Job 3 — DevOps / Cloud Engineer** — GT=6, R@20=0.67, missed=[20, 28]
- **Job 6 — React Frontend Developer** — GT=3, R@20=0.67, missed=[29]
- **Job 7 — Scrum Master / Agile Coach** — GT=4, R@20=0.75, missed=[21]
- **Job 5 — Python Data Engineer** — GT=5, R@20=0.80, missed=[23]
- **Job 2 — Java Backend Developer** — GT=6, R@20=0.83, missed=[8]
- **Job 1 — Senior Angular Developer** — GT=4, R@20=1.00, missed=[]
- **Job 4 — QA Automation Engineer** — GT=4, R@20=1.00, missed=[]
- **Job 13 — Data Engineer** — GT=3, R@20=1.00, missed=[]

## Reproduce

```bash
cd backend && python -m scripts.eval_matching --ablation \
    --output ../docs/matching-eval-$(date +%F).md
```
