# Traffit "? ?" candidates — name/contact backfill + prevention

**Date:** 2026-06-23
**Trigger:** ~265 candidates showed as `? ?` on `/candidates` with empty
phone/email/CV-data. All were `external_source=traffit`.

## Root cause

The Traffit importer maps an employee with neither a name nor a usable email to
the literal placeholder `name="?"` / `lastname="?"`
([`mappers.py:338-347`](../backend/app/services/traffit/mappers.py)). It
downloads the candidate's CV to object storage (`cv_storage_key`) but **never
extracts or parses it**, so name/email/phone stay empty even though the data
exists inside the CV (and usually in the filename).

A second, latent bug: `_apply_cv_contact_fields` only treated `"Nieznane"` as a
blank placeholder, **not** Traffit's `"?"` — so a later CV re-parse would have
refused to overwrite a `"?"` name.

## Fix

Two parts, both reusing the existing, battle-tested
`parse_cv` → `_apply_cv_enrichment` path (same one as `/from-cv` upload).

### 1. Prevention — new sync phase `candidates_enrich_names`
- Runs after `candidate_files` in every Traffit sync
  ([`traffit_sync.py`](../backend/app/tasks/traffit_sync.py),
  [`importer.enrich_missing_names`](../backend/app/services/traffit/importer.py)).
- Delta mode scopes to `since=files_since` (only this run's fresh `?` rows);
  full reconcile sweeps all remaining `?`.
- No new daily-sync recurrence of `? ?` rows.

### 2. Backfill of the existing ~265
- Admin endpoint `POST /api/admin/candidates/backfill-names?limit=&prefer_llm=`
  (background, admin-only) + `GET /api/admin/candidates/backfill-names/status`
  ([`admin_candidates.py`](../backend/app/api/admin_candidates.py)).
- Idempotent + resumable: targets `external_source='traffit' AND (name='?' OR
  lastname='?')`, commits per candidate, only fills blank/placeholder fields.

### Shared logic
- [`app/services/cv_backfill.py`](../backend/app/services/cv_backfill.py) —
  CV bytes → text → `parse_cv` → enrich, with a **conservative
  `name_from_filename` fallback** (only guesses when a filename yields exactly
  two clean tokens, or a camelCase blob like `VugarSuleymanov` splits cleanly;
  returns `(None, None)` for `CV_fin.pdf` etc. rather than inventing a name).
- [`app/services/cv_enrichment.py`](../backend/app/services/cv_enrichment.py) —
  `_apply_cv_enrichment` / `_apply_cv_contact_fields` extracted from
  `candidates.py` (re-exported there for existing call-sites + tests). Fixes:
  `"?"` is now a blank placeholder; `traffit_*` custom fields in
  `cv_extracted_data` are preserved across enrichment.

## Safety properties
- Only blank/placeholder fields are written — a real recruiter-typed value is
  never overwritten (`_manual_override_*` flags still honoured).
- No DB schema change (the `name`/`email`/`phone` columns already exist).
- Robust without an LLM: falls back to regex (email/phone/header name) +
  filename-derived name, so candidates get a real name even if Claude/Ollama
  are unavailable on prod.

## Files
- `backend/app/services/cv_enrichment.py` (new)
- `backend/app/services/cv_backfill.py` (new)
- `backend/app/api/admin_candidates.py` (new)
- `backend/tests/test_cv_backfill.py` (new — 17 tests)
- `backend/app/api/candidates.py` (helpers → re-export)
- `backend/app/services/traffit/importer.py` (`enrich_missing_names` phase)
- `backend/app/tasks/traffit_sync.py` (phase plan)
- `backend/app/main.py` (mount admin_candidates router)
- `CLAUDE.md` (Traffit sync section)

## Rollout
1. Merge → Coolify deploy → verify `/api/health` GIT_SHA.
2. `POST /api/admin/candidates/backfill-names?limit=5` → verify a small batch.
3. `POST /api/admin/candidates/backfill-names` (full) → poll
   `GET .../backfill-names/status` until `running=false`.
4. Confirm `/candidates?q=? ?` count drops toward 0.

## Known limitations
- A handful of candidates whose CV text yields no name **and** whose filename is
  generic (e.g. `CV_fin.pdf`) stay as `?` (reported as `unresolved`) rather than
  getting a guessed name — these need manual review.
- Duplicate `? ?` rows exist (same CV filename, e.g. two `VugarSuleymanov_CV.docx`);
  dedup is a separate concern, out of scope here.
