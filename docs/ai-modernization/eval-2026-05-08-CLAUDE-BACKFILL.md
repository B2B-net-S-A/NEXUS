2026-05-08 19:57:42,538 [INFO] httpx: HTTP Request: POST http://qdrant:6333/collections/nexus_jobs/points/search "HTTP/1.1 200 OK"
2026-05-08 19:57:42,593 [INFO] eval_matching: Report written to /tmp/eval-fin.md
# Matching Quality Audit — Phase 0

Generated at: `2026-05-08T19:57:42.593341+00:00`

## Data quality snapshot

- Jobs: 3840 total; **missing must_skills**: 241 (6%); missing nice_skills: 3442 (90%)
- Candidate skills JSONB format: list-of-dict/str = 35470, dict (`technologies`/`stack`) = 20, null = 10470 (total=46265)
- Voyage API key configured: **yes**

## Summary

| Profile | Boost | Jobs | Precision@5 | Recall@20 | MRR | nDCG@10 | HistHit@10 |
|---|:---:|---:|---:|---:|---:|---:|---:|
| `default_40_30_15_10_5` |  | 30 | 0.160 | 0.176 | 0.351 | 0.205 | 0.080 |

## Go/No-Go verdict

> NO-GO — Recall@20 under 50%. Fix scoring (B1 aliases + D1 tuning) or data quality (backfill must/nice skills) before investing in Phase A UX. Re-run this eval.

## Findings & recommended actions

- **20 candidates** store skills as a dict (`{technologies: [...]}`) — already handled by the patched `_skill_names()` parser, but consider migrating to the canonical `[{name, level, years}]` shape so UI and filters see uniform data.

## Profile: `default_40_30_15_10_5`

Weights: semantic=40.0, skills=30.0, salary=15.0, location=10.0, availability=5.0

| Job ID | Title | GT size | Pool | P@5 | R@20 | MRR | nDCG@10 |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | Senior Angular Developer | 4 | 200 | 0.60 | 0.75 | 1.00 | 0.87 |
| 2 | Java Backend Developer | 8 | 200 | 0.80 | 0.62 | 1.00 | 0.80 |
| 3 | DevOps / Cloud Engineer | 6 | 200 | 0.60 | 0.50 | 1.00 | 0.66 |
| 4 | QA Automation Engineer | 4 | 200 | 0.20 | 0.25 | 1.00 | 0.19 |
| 5 | Python Data Engineer | 5 | 200 | 0.60 | 0.60 | 1.00 | 0.82 |
| 6 | React Frontend Developer | 3 | 200 | 0.40 | 0.67 | 1.00 | 0.95 |
| 7 | Scrum Master / Agile Coach | 4 | 200 | 0.60 | 0.75 | 1.00 | 0.67 |
| 13 | Data Engineer | 3 | 200 | 0.40 | 0.67 | 1.00 | 0.59 |
| 1391 | PEP4917_Solution Delivery_Senior Analyst_Replacement of Alek | 61 | 200 | 0.00 | 0.02 | 0.17 | 0.04 |
| 1392 | Bank Pocztowy: Kierownik Projektu | 11 | 200 | 0.00 | 0.00 | 0.00 | 0.00 |
| 1393 | Analityk Biznesowo Systemowy x2 CZII Zamówienie 43 | 6 | 200 | 0.00 | 0.00 | 0.00 | 0.00 |
| 1394 | Senior UX/UI Designer (ITVM-6228) | 36 | 200 | 0.20 | 0.06 | 0.50 | 0.08 |
| 1395 | Nordea: PL_Senior- expert _IT Analyst for Data Product Hub-  | 27 | 200 | 0.00 | 0.00 | 0.03 | 0.00 |
| 1396 | PKO BP Programista Python (middle) ZOB-2613 | 10 | 200 | 0.00 | 0.00 | 0.01 | 0.00 |
| 1397 | PKO BP: Programista Java - Nemo BPM (middle/senior) - ZOB-26 | 32 | 200 | 0.00 | 0.00 | 0.01 | 0.00 |
| 1398 | Tester manualny (ZOB-2627) | 15 | 200 | 0.00 | 0.00 | 0.01 | 0.00 |
| 1399 | Analityk biznesowo - systemowy (RFQ_41-2026) | 3 | 200 | 0.00 | 0.00 | 0.00 | 0.00 |
| 1400 | Nordea: PL_IT Developer (Senior) for Data Quality (Platform  | 33 | 200 | 0.00 | 0.00 | 0.00 | 0.00 |
| 1401 | Tester manualny - zastępstwo za: Krzysztof Suwała | 7 | 200 | 0.00 | 0.00 | 0.02 | 0.00 |
| 1402 | 1 X Senior Power Platform Developer (41788) | 22 | 200 | 0.20 | 0.14 | 0.50 | 0.17 |
| 1403 | 1 X Data engineer to support building our Metadata Dataprodu | 41 | 200 | 0.00 | 0.00 | 0.03 | 0.00 |
| 1404 | Java developers for new project called STP for loan system ( | 23 | 200 | 0.00 | 0.00 | 0.01 | 0.00 |
| 1405 | Bank Pocztowy: Kierownik Projektu DKZ | 7 | 200 | 0.00 | 0.00 | 0.00 | 0.00 |
| 1406 | Data Engineer (ZOB-2621) - MID | 24 | 200 | 0.00 | 0.08 | 0.06 | 0.00 |
| 1408 | Nordea: AM Consultant with Mainframe and Midrange knowledge  | 8 | 200 | 0.00 | 0.00 | 0.05 | 0.00 |
| 1409 | PKO BP: Analityk Systemowy (middle) ZOB-2632 | 26 | 200 | 0.00 | 0.00 | 0.04 | 0.00 |
| 1410 | Nordea: Senior Test Automation Engineer D&A Hub (41806) | 32 | 200 | 0.00 | 0.03 | 0.08 | 0.00 |
| 1411 | Nordea: PL - Senior SME – ICT Risk, Resilience & DORA Implem | 7 | 200 | 0.20 | 0.14 | 1.00 | 0.30 |
| 1412 | Orch, SA:FCP SA: IIS Poland Operations specialist WAW/GDA/GD | 45 | 200 | 0.00 | 0.00 | 0.01 | 0.00 |
| 1413 | UX/UI Designer - zastępstwo za: Kosma Ostrowski | 3 | 200 | 0.00 | 0.00 | 0.00 | 0.00 |

## Error analysis (worst Recall@20, default profile)

- **Job 1392 — Bank Pocztowy: Kierownik Projektu** — GT=11, R@20=0.00, missed=[13251, 3529, 72779, 72653, 72050] ...
- **Job 1393 — Analityk Biznesowo Systemowy x2 CZII Zamówienie 43** — GT=6, R@20=0.00, missed=[26209, 33705, 19531, 70704, 13203] ...
- **Job 1395 — Nordea: PL_Senior- expert _IT Analyst for Data Product Hub- replacement (41719)** — GT=27, R@20=0.00, missed=[31874, 20228, 67721, 65940, 66851] ...
- **Job 1396 — PKO BP Programista Python (middle) ZOB-2613** — GT=10, R@20=0.00, missed=[31072, 8708, 72648, 72714, 73163] ...
- **Job 1397 — PKO BP: Programista Java - Nemo BPM (middle/senior) - ZOB-2614** — GT=32, R@20=0.00, missed=[71552, 25479, 37512, 70796, 71699] ...
- **Job 1398 — Tester manualny (ZOB-2627)** — GT=15, R@20=0.00, missed=[3168, 13058, 36420, 33862, 67398] ...
- **Job 1399 — Analityk biznesowo - systemowy (RFQ_41-2026)** — GT=3, R@20=0.00, missed=[25923, 26211, 66884]
- **Job 1400 — Nordea: PL_IT Developer (Senior) for Data Quality (Platform Engineering) - Replacement (41296)** — GT=33, R@20=0.00, missed=[64512, 19597, 6547, 5908, 71324] ...
- **Job 1401 — Tester manualny - zastępstwo za: Krzysztof Suwała** — GT=7, R@20=0.00, missed=[13058, 20166, 20235, 23987, 13269] ...
- **Job 1403 — 1 X Data engineer to support building our Metadata Dataproduct (41787)** — GT=41, R@20=0.00, missed=[25730, 26231, 73231, 7443, 75767] ...

## Reproduce

```bash
cd backend && python -m scripts.eval_matching --ablation \
    --output ../docs/matching-eval-$(date +%F).md
```
