# Candidates search latency — investigation & fix (2026-06-22)

> Reported: `/candidates?...&q_any=Java|REST API|Kotlin|microservices|Gitlab` loads too long.
> Goal: search ≤ 5 s.

## Root cause

`GET /api/candidates` free-text search (`q_any`) runs a trigram-indexed filter whose
ILIKE **recheck must detoast every matching `raw_cv_text`** (multi-KB CVs). Two amplifiers:

1. **Double evaluation.** The endpoint ran the filter twice — once for `COUNT(*)`
   ([candidates.py:1407](../backend/app/api/candidates.py)) and again for the paginated
   `SELECT` — each a full detoast pass over all matches.
2. **High match cardinality.** "Java | REST API | Kotlin | microservices | Gitlab" matches
   **20,195 of ~48K** candidates (~42%). Detoasting ~20K multi-KB CVs is inherently heavy
   on the prod ARM box (Hetzner CAX21).

Measured on prod (query only, after fix #1): rare term 330 ms · 1 common term 1.9 s ·
5 common terms ~5 s. So **specific/typical searches were already fine**; only broad
multi-common-keyword queries (huge result sets) were slow.

## Fix shipped — single-pass count+page  ✅ (commit df51c92)

Fold `COUNT(*)` into the page query via `count(*) OVER()` so the search filter executes
**once** instead of twice. Window is computed pre-LIMIT → exact total preserved; rare-term
searches unaffected (still trigram); unfiltered browse stays an index-only scan.

- Verified: result-set + total identical to the old two-query path; `selectinload`
  eager-loading intact under `add_columns` (no `MissingGreenlet`); empty-result handling.
- Effect: roughly halves the heavy-search wall-clock (two detoast passes → one).
  Pathological 5-keyword query ≈ **10 s → ~5 s**; typical searches well under.

## Attempted & REVERTED — column-grouped OR  ❌ (30e7d6c → reverted in 483e9cb)

Idea: OR the phrases inside each column (`search_doc ILIKE p1 OR…OR p5 UNION raw_cv … UNION
notes …`) so each matching row is detoasted once per column, not once per phrase.

- Local benchmark (50K rows, high overlap, **small** `search_doc`): 3× faster (3.4 s → 1.1 s).
- **On prod it regressed badly: ~5 s → ~14 s.** Prod's `search_doc` is large (it concatenates
  `ai_summary` + experience/skills JSON), so `search_doc ILIKE p1 OR…OR p5` over 5 common
  terms is estimated non-selective and the planner **seq-scans + detoasts the big `search_doc`
  for all 48K rows**. The per-phrase shape avoids this (each selective `ILIKE` drives the
  trigram bitmap index).
- Lesson: the local benchmark's `search_doc` was too small to reproduce prod's cost model.
  Reverted to restore the known-good ~5 s state.

## Where it stands

- Net improvement live: **single-pass** (≈ 2× on broad searches; typical searches fast).
- The pathological broad-OR query (~20K results, 42% of the base) remains ~5 s — at the
  target boundary, bounded by unavoidable CV detoast for an exact, substring-correct,
  rare-term-safe search.

## Options to go clearly below 5 s (need prod-DB validation before shipping)

1. **Approximate / deferred total** — render results without blocking on the exact count
   (e.g. "1000+"), and/or load the count lazily. Removes the count from the critical path.
2. **raw_cv_text-only column grouping** — detoast-once *only* on the heavy `raw_cv_text`
   branch while keeping `search_doc`/notes per-phrase (avoids the search_doc seq-scan).
   Must be validated against a prod-sized `search_doc`.
3. **FTS for CV text** — a `tsvector` GIN index is recheck-free (no detoast), but changes
   substring semantics to word/lexeme matching.
4. **Ops** — keep the table hot / larger `shared_buffers`; the ARM box + cold cache inflate
   detoast I/O.

## Verification method

No prod DB/SSH access this session, so the SQL was measured on a throwaway Postgres with a
faithful schema (`search_doc` generated column + GIN trigram indexes, migration 0126/0013
parity), 50K seeded rows with realistic incompressible multi-KB CVs; ORM mechanics validated
via SQLAlchemy against a small instance; final numbers measured live through the authenticated
browser session (`/api/candidates` Resource Timing).
