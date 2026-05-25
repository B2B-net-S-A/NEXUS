# Experience backfill — completion report (2026-05-25)

Commit: `84f2d2b` — `feat(candidates): backfill experience JSONB from cv_extracted_data (30k+ candidates)`

## Problem

48,143 kandydatów w bazie. Tylko 30 (0.06%) miało `experience` JSONB.
0 miało `linkedin_current_company`. Filtry "obecna firma" /
"obecne stanowisko" technicznie poprawne, ale praktycznie nic
nie znajdywały — bo nie było danych.

44,350 kandydatów (92%) miało jakieś dane w `cv_extracted_data`,
ale w 3 niespójnych schematach.

## Audit findings

| Variant | external_source | jsonb_typeof | count | Co zawiera |
|---|---|---|---|---|
| 1 | talent_radar | string | 38 | JSON-encoded string z `work_history`, `current_role` |
| 2 | traffit | array | 267 | Array (39-43 items, ~4 unique) — jeden item z `work_history` |
| 3a | traffit | object (Pos+Emp) | 15,657 | `traffit_Position` + `traffit_previous_employers` |
| 3b | traffit | object (Emp only) | 13,472 | Tylko `traffit_previous_employers` (no role) |
| 3c | traffit | object (Pos only) | 704 | Tylko `traffit_Position` |
| 3d | traffit | object (neither) | 16,094 | Tylko `legacy_source` / inne — skipped |

## Implementation

**Script:** [`backend/scripts/backfill_candidate_experience.py`](../backend/scripts/backfill_candidate_experience.py)
**Tests:** [`backend/tests/test_backfill_candidate_experience.py`](../backend/tests/test_backfill_candidate_experience.py) (34 unit tests, pure-Python, no DB)

### Parser per variant

- **`parse_tr_string`**: `json.loads()` → dict → extract `work_history` → map keys
- **`parse_tr_array`**: iterate array items, find first with `work_history`
- **`parse_traffit_object`**: `traffit_Position.split(',')` → roles, `traffit_previous_employers.split(',')` → past employers

### Schema output

```json
[
  {"company": "Acme", "role": "Senior Dev", "start": "2020-01", "end": null, "desc": "Built X"},
  {"company": "Globex", "role": "Junior", "start": "2018-01", "end": "2019-12", "desc": null}
]
```

- Sort: `end IS NULL` first (current), then by `end DESC`
- Dedupe: by `(company.lower(), role.lower(), start)`

### Variant 3b false-positive guard

Kandydaci z TYLKO past employers (no role) dostają NULL placeholder
jako `experience[0]`. Bez tego `experience[0].company = past_employer`
matchowałoby filter "obecna firma" jako current. Z placeholderem:

```json
[
  {"company": null, "role": null, "start": null, "end": null, "desc": null},
  {"company": "Past Co 1", "role": null, ...},
  {"company": "Past Co 2", "role": null, ...}
]
```

- Filter "obecna firma": `experience[0].company` = NULL → COALESCE('') → no match ✓
- Filter "previous company": `experience[ord > 1].company` → matches past employers ✓

### Frontend update

[`frontend/src/components/v2/pages/CandidateDetailV2.tsx`](../frontend/src/components/v2/pages/CandidateDetailV2.tsx)
filtruje empty placeholders przed renderem sekcji "Doświadczenie zawodowe"
(no empty card).

### Resilience

- Reconnect logic z exponential backoff (`_reconnect()`) — przeżyje Postgres
  restart mid-run (Coolify auto-deploy bouncing the stack)
- Per-batch transaction — crash mid-batch leaves DB consistent
- Idempotent — `WHERE experience IS NULL` filter, safe re-run

### Asyncpg gotcha

asyncpg returns JSONB jako raw JSON text (str), nie auto-deserializes.
Trzeba `json.loads()` w main loop niezależnie od `jsonb_typeof`. Pierwsza
implementacja pominęła to dla `string` variant — fix: zawsze decode.

## Results

| Metric | Before | After | Improvement |
|---|---|---|---|
| With `experience` JSONB | 30 | **30,166** | **1,005×** |
| `current_company_known` (experience[0].company) | ~30 | **332** | 11× |
| `current_role_known` (experience[0].role) | ~30 | **16,694** | 556× |
| `linkedin_current_company` set | 0 | **245** | new |
| Parse errors | — | **0** | — |
| Parsed empty (variant 3d) | — | 14,214 (skipped cleanly) | — |

### Per-variant yields

- `tr_string`: 38 rich (rzeczywiste current company + role + dates + desc)
- `tr_array`: 265 rich (2 lost to JSON parse — ~99% success)
- `traffit_obj`: 29,833 partial (16,361 with role, 29,129 with past employers)

## Filter improvements

- **"obecna firma=Capgemini"**: ~30 → ~332 candidates findable (variant 1+2 only — variant 3 doesn't know current company)
- **"obecne stanowisko=Data Analyst"**: ~30 → ~16,694 findable (407 for "Data Analyst", 314 for "Project Manager", ...)
- **"previous company=Accenture"**: ~30 → ~29,000 findable (440 for "Accenture", 375 for "Capgemini", ...)

## UI verification

Sprawdzone przez Chrome MCP na `nexus.dynaminds.pl`:
- Variant 1+2 (Grzegorz Dajuk #23461): full work history rendered — "DevOps Engineer @ DevOps Bay · 1.04.2022 — obecnie" + complete past jobs with dates + descriptions ✓
- Variant 3b (Andrzej Kowalik #9762): past employers correctly listed (Schneider Electrics, SAS Institute, PKO S.A., Inteligo) WITHOUT being mistaken for current employer ✓
- Candidate list STANOWISKO column populated dla variant 3a/3c candidates ✓

## Known limitations / future work

- Variant 3 (29k candidates) doesn't know current company. Future: parse `raw_cv_text` z LLM (Claude/Voyage) to derive structured employment history. Out of scope here.
- 16,094 variant 3d candidates have only `legacy_source` — nothing extractable, would need raw CV reparse.
- Past employer / role pairing dla variant 3a multi-position is unzipable without dates. Currently roles + employers listed separately.

## Files

- New: `backend/scripts/backfill_candidate_experience.py` (parser + CLI)
- New: `backend/tests/test_backfill_candidate_experience.py` (34 tests)
- Mod: `frontend/src/components/v2/pages/CandidateDetailV2.tsx` (filter placeholders)
- Mod: `frontend/src/components/v2/pages/__tests__/candidate-list-helpers.test.ts` (+2 placeholder tests)
