# Candidate keyword search — hybrid FTS perf fix

**Date:** 2026-06-23
**Symptom:** `GET /candidates?q_all=java|selenium` (and any common keyword) — "Ładowanie
kandydatów…" hung well past 3s. Target: < 3s.

## Diagnosis (measured against prod via authenticated API timing)

| Request (no UI extras unless noted) | Matches | Time |
|---|---|---|
| Unfiltered list + all includes (match-stats, recruitments, activity) | 50,417 | 0.78s |
| `zzqqxx` (zero matches) | 0 | 0.11s |
| `q_all=java\|selenium` — full app request | 3,537 | 3.4–4.2s |
| `q_all=java\|selenium` — `include_match_stats=false` | 3,537 | 3.2–3.6s |
| `q_all=java\|selenium` — no includes at all | 3,537 | 2.9–3.9s |
| `java` alone | 17,133 | 3.8s (warm) |
| `kubernetes` alone (cold) | 4,278 | 7.6s |
| `java` page 50 (cold) | 17,133 | 26.9s |

**Bottleneck = the free-text keyword filter, not the frontend / windowed count /
`include_match_stats`** (those add ≈0.5s; unfiltered loads with all of them are 0.78s).

**Root cause:** keyword buckets (`q`/`q_all`/`q_any`/`q_none`) matched each phrase as a
substring `ILIKE '%phrase%'` against `search_doc`, `raw_cv_text` (≈171MB of CVs) and notes,
backed by `pg_trgm` GIN. **GIN trigram is lossy for `LIKE`**, so Postgres re-reads and
**detoasts every candidate row the index flags** to confirm. A common keyword flags thousands
of rows (`java` = 34% of the base), i.e. thousands of multi-KB CV detoasts per request. Zero
matches and unfiltered loads are fast precisely because they skip that per-row recheck.

## Fix — hybrid FTS + substring fallback

A `tsvector` GIN match evaluates `@@` against the **compact stored tsvector**, never
detoasting the raw CV — strictly cheaper per row than the trigram recheck *regardless of the
plan*.

- **Plain alphanumeric words (≥3 chars)** → word-PREFIX FTS:
  `search_fts @@ to_tsquery('simple', 'phrase:*')` on `ix_candidates_search_fts`.
- **Short / special-char fragments** (`c++`, `c#`, `.net`, `node.js`, multi-word) → existing
  exact trigram substring path (unchanged).
- Notes stay substring (separate smaller table); the fuzzy identity branch for `?q=` is kept.

**Semantics shift (FTS path only):** word-prefix instead of arbitrary substring. `jav` → `java`
(incremental ⌘K typing) and `java` → `javascript` (word-prefix) still match; only rare mid-word
substrings (`ava` → `java`) are dropped. Special-char tech terms keep substring matching.

### Migration `0143_candidate_search_fts` (zero-downtime)

A `GENERATED ... STORED` column would hold `ACCESS EXCLUSIVE` for ≈1 min detoasting all 171MB of
CV text during the `ADD COLUMN` rewrite. Instead:

1. `ADD COLUMN search_fts tsvector` — nullable → instant, no rewrite.
2. `BEFORE INSERT OR UPDATE` trigger keeps it fresh.
3. Batched backfill (2000 rows/batch, autocommit, resumable on `search_fts IS NULL`).
4. `CREATE INDEX CONCURRENTLY` GIN — never blocks writes.

Scope mirrors `search_doc` (migration 0126) field-for-field + `raw_cv_text` capped at 200KB
(guards the 1 MB tsvector limit). `'simple'` config (no stemming/stopwords) → predictable tech
tokens. Trigram `search_doc`/`raw_cv_text` indexes retained for the fallback path.

## Files

- `backend/alembic/versions/0143_candidate_search_fts.py` (new)
- `backend/app/services/advanced_candidate_search.py` (`_fts_eligible` + hybrid `_phrase_match`)
- `backend/tests/test_candidate_search_fts.py` (new — 7 semantic tests)
- `.github/workflows/ci.yml` (added the new test to the pytest list)

## Verification

- **Local (Postgres 16 in Docker):** migration applies cleanly (column + GIN index + trigger
  present); **24 search tests pass** (7 new FTS semantics + 17 existing advanced-search parity);
  27 further candidate-filter tests pass; `ruff check` / `ruff format` clean.
- **Prod timing (post-deploy, version `86d08e1`):** re-ran the authenticated API-timing
  harness — all under 3s:

  | Request | Before | After |
  |---|---|---|
  | `q_all=java\|selenium` full app request (all includes) | 3.4–4.2s | **~2.0s** (4.9s only on the first cold hit) |
  | `q_all=java\|selenium` filter only | 2.9–3.9s | **1.6–1.8s** |
  | `java` alone (≈17K matches) | 3.8s | **1.5–1.7s** |
  | `selenium` alone | — | **0.34s** |
  | `kubernetes` (cold) | 7.6s | **0.4–0.8s** |
  | `java` page 50 (cold) | 26.9s | **2.1s** |

  Result count for `java|selenium` shifted 3537 → 3484 (−1.5%), consistent with word-prefix
  dropping mid-word substring noise. UI verified via Chrome: the `/candidates?q_all=java|selenium`
  list renders 3484 rows with Java/Selenium snippet highlights — no "Ładowanie kandydatów…" hang.

### Deploy note (one-time)

The migration runs synchronously in the container entrypoint (`alembic upgrade head`) before
uvicorn binds. The 50K-row backfill + `CREATE INDEX CONCURRENTLY` took > 6 min, so the new
container wasn't ready in time and the **Deploy smoke-test job failed (502s for ~6 min)** even
though `alembic` completed and prod is now healthy on the new version. This is **one-time** —
0143 never re-runs, so subsequent deploys start normally. Follow-up worth considering: extend the
healthcheck grace / smoke-test window, or move heavy backfills off the synchronous startup path,
so a long migration doesn't show as a failed deploy (or briefly 502 the public URL).

## Known limitations / follow-ups

- Mid-word substring matching is intentionally dropped for plain words (accepted trade-off).
- Notes still use trigram substring; if a common keyword in notes ever dominates, add a notes
  tsvector too.
- The trigger recomputes the CV tsvector on every candidate UPDATE (same as a generated column
  would); negligible for the current write volume, runs off-hours for the Traffit sync.
