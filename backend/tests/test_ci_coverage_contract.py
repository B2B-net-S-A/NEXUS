"""Every test file must actually run in CI — or be a declared, reasoned exception.

The meta-cause behind this whole hardening effort: CI used to run a
hand-enumerated list of ~285 test filenames, so every quality and security
guardrail was opt-in — it only protected anything if whoever added it also
remembered to append the filename to `.github/workflows/ci.yml`. That is exactly
how a guardrail silently dies: the test exists, passes locally, and never runs.

That list is gone. CI now runs `pytest tests/` and collects everything, minus an
explicit `--ignore=` per exception. Forgetting is no longer possible; only
deliberate exclusion is, and every exclusion has to be argued here.

**The `--ignore` list in ci.yml IS the baseline below.** This file asserts the
two match in both directions, so an exclusion cannot be added to CI without a
written reason, nor linger in the baseline after the debt is paid. Categories:

- COLLECTION_ERRORS — the file cannot even be collected (missing fixture data,
  import-time failure). Wiring it in as-is would break the build.
- LIVE — needs a running server (uses the `client` fixture, skipped unless
  RUN_LIVE_TESTS=1). Genuinely out of scope for the in-process job.
- FAILING — collects fine, but red on its own today. Almost all of these are
  stale: the test never ran, so nobody noticed when a schema column went NOT
  NULL or a request contract gained a required field underneath it.

Status 2026-07-27: 318 test modules on disk, 26 excluded, 292 run.
(An earlier revision said 313 on disk / 281 wired; the real figures were 317 and
285 — 317 = 285 enumerated + the then 32-file baseline. Corrected rather than
carried forward, since the whole point of the number is to be measurable.)

History of the burn-down:
  115 unwired  → measured file-by-file in the prod image against a migrated
                 database; the 89 confirmed-green ones were wired in.
   32 excluded → 2 collection errors + 4 live + 22 failing + 4 suite-interference.
   30 excluded → `test_candidate_stage_cv_branded.py` and
                 `test_engagement_magic_link.py` left FAILING (#941). Both were
                 listed as "expired link answers 200, test expects 410", which
                 read like a live hole in two public, unauthenticated candidate
                 links. It was not: since the hash-at-rest migrations (0176 CV
                 share, 0182 engagement) the raw secret is stored only as a
                 SHA-256, so each test's `UPDATE … WHERE token == <raw secret>`
                 matched zero rows and the link under test was never actually
                 expired. The preconditions now match on the digest and assert
                 their own rowcount, so a setup that silently touches nothing
                 fails loudly instead of masquerading as a product bug.
   26 excluded → the SUITE_INTERFERENCE category is retired. Those four files
                 (test_contract_analytics, test_contracts_expansion,
                 test_contracts_filters_multi, test_contracts_search) were green
                 alone and red inside the full suite because they assumed they
                 owned the database — asserting their own row id appeared in an
                 unpaginated global listing, or mutating an arbitrary borrowed
                 row. Their assertions are now local to rows they create, which
                 is what made auto-discovery possible: with the file list gone,
                 pytest runs them in alphabetical order rather than the order
                 ci.yml happened to list, and order-dependent tests had nowhere
                 left to hide.

Running a test is still not the same as running it the way production runs.
`test_invite_links.py` was wired in and green the whole time — but only because
CI had no `M365_TOKEN_ENCRYPTION_KEY` while production has one, and an invite
link mints the hash-at-rest v2 row only when a cipher is available. CI was
proving the legacy branch. The key is now set on the pytest step, and
`test_ci_token_encryption_parity.py` fails if it is dropped or stops being a
usable key — an unusable value would be worse than none, because
`TokenCipherNotConfigured` is caught and swallowed. That file is one of the 292
picked up by auto-discovery; it needs no entry here, which is the point.
"""

from __future__ import annotations

import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
TESTS = BACKEND / "tests"
CI_YML = BACKEND.parent / ".github" / "workflows" / "ci.yml"

# What counts as a test module, by either naming convention. The CI parser and
# the disk scanner share this so a file cannot be visible to one and invisible
# to the other — that asymmetry is itself a way around the contract.
_MODULE = r"(?:test_[A-Za-z0-9_]+|[A-Za-z0-9_]+_test)\.py"
_IGNORE_RE = re.compile(rf"--ignore=tests/((?:[A-Za-z0-9_]+/)*{_MODULE})")
# A path NOT preceded by `--ignore=` — i.e. a file being enumerated as a target,
# the pattern this contract exists to keep out.
_ENUMERATED_RE = re.compile(rf"(?<!--ignore=)\btests/((?:[A-Za-z0-9_]+/)*{_MODULE})")


def _pytest_step() -> str:
    """The executable body of the backend pytest step in ci.yml.

    Scoped to that one step so `--ignore=` flags or paths belonging to other
    jobs (e2e, uptime probes) cannot be mistaken for this job's contract.
    Comment lines are stripped: prose explaining the step is not configuration,
    and a filename mentioned in a comment must not read as either a target or a
    declared exception.
    """
    text = CI_YML.read_text(encoding="utf-8")
    # A bare `.index()` would raise ValueError with no context, and this file's
    # entire job is to fail informatively: whoever renames the step should be
    # told that is what broke, not handed a traceback into a helper.
    step_name = "- name: Pytest (unit + in-process integration)"
    try:
        start = text.index(step_name)
    except ValueError:
        raise AssertionError(
            f"Could not find {step_name!r} in {CI_YML}. If the step was renamed, "
            "update this constant — otherwise the coverage contract silently "
            "stops checking the step it exists to check."
        ) from None
    try:
        nxt = text.index("\n      - name:", start + 1)
    except ValueError:
        raise AssertionError(
            f"Found {step_name!r} in {CI_YML} but no following step at the same "
            "indent, so the step's extent cannot be determined. If it is now the "
            "last step in the job, this helper needs to fall back to end-of-file."
        ) from None
    return "\n".join(
        line
        for line in text[start:nxt].splitlines()
        if not line.lstrip().startswith("#")
    )


def _ci_ignored_files() -> set[str]:
    """Files CI explicitly excludes.

    NOTE the inversion versus the old parser: when ci.yml enumerated targets, a
    matched path meant "covered". Now a matched `--ignore=` path means the exact
    opposite — "NOT covered". Reusing the old regex here would have read the
    exception list as proof of coverage and passed while protecting nothing.
    """
    return set(_IGNORE_RE.findall(_pytest_step()))


def _disk_files() -> set[str]:
    """Every test module under backend/tests/, relative to that directory.

    `rglob` rather than `glob`, and both naming conventions: a non-recursive
    `glob("test_*.py")` could not see a test in a subdirectory nor one named
    `*_test.py`, so either was a free pass around this contract.
    """
    found: set[Path] = set()
    for pattern in ("test_*.py", "*_test.py"):
        found.update(TESTS.rglob(pattern))
    return {
        p.relative_to(TESTS).as_posix() for p in found if "__pycache__" not in p.parts
    }


# Files CI does not run. Categorised so the reason is argued here, not hidden.
# Burn these down — do not add to them without cause.
_COLLECTION_ERRORS = {
    # Cannot be collected without eval/backfill fixture data present. Not yet
    # wired into CI; the three eval/merge siblings ARE in CI (they have the data
    # there) so they are deliberately absent from this list.
    "test_backfill_candidate_experience.py",
    "test_backfill_talent_pools.py",
}

_LIVE = {
    # Uses the live-server `client` fixture (skipped unless RUN_LIVE_TESTS=1).
    "test_auth.py",
    "test_candidates.py",
    "test_jobs.py",
    "test_pipeline.py",
}

# Red on their own. Measured 2026-07-27 in the prod image against a freshly
# migrated database, with the same environment CI uses (DATABASE_URL, SECRET_KEY,
# RUN_LIVE_TESTS=0 and nothing else). Each line is the actual failure, so the
# next person can pick one up without re-running the whole sweep. Fixing these
# is deliberately NOT part of the wiring change — a test that has been wrong for
# months deserves its own diff.
_FAILING = {
    # 1 fail — writes its path-traversal probe outside the upload dir:
    # FileNotFoundError '/tmp/nexus/uploads/candidate_N_../../etc/passwd.pdf'.
    "test_bulk_cv_download.py",
    # 1 fail — hardcoded force.test@example.com collides with candidates_email_key
    # on any re-run; the test never cleans up after itself.
    "test_candidates_from_cv.py",
    # 2 fails — endpoint answers {"status":"dry-run","enabled":false}; the test
    # assumes the Champion AI intake flag is on.
    "test_champion_ai_intake.py",
    # 2 fails — summary is now concatenated with extra fields, expected strings stale.
    "test_cv_enrichment.py",
    # 1 fail — parsed-CV dict gained current_position_started_at_precision.
    "test_cv_parser.py",
    # 1 fail — fixture inserts client_orders without contract_id, now NOT NULL.
    "test_dl_portal_scheduler.py",
    # 1 fail — client_id is now required, so the invalid payload 422s where the
    # test expects 400.
    "test_jobs_auto_assign.py",
    # 2 fails — name folding returns 'aka zow kowalski' where the test expects
    # 'laka zolw kowalski' (leading character dropped).
    "test_m365_matcher.py",
    # 3 fails — two same-day notifications of one type hit ix_notif_dedup_daily.
    "test_marketplace_flow.py",
    # 1 fail — is_significant_job_update({'must_skills': None}, {'must_skills': []})
    # is now True, the test expects False.
    "test_marketplace_service.py",
    # 2 fails — endpoint now validates and answers 422 where the test expects 201.
    "test_new_endpoints.py",
    # 1 fail — trigger set gained post_interview_t15.
    "test_notification_triggers.py",
    # 10 fails (whole file) — the job team-membership gate answers 403; the
    # fixture user is not on the recruitment's team.
    "test_pending_verification.py",
    # 3 fails — production calls accept(subprotocol=...), the test's
    # FakeWebSocket.accept() takes no such keyword.
    "test_presence_manager.py",
    # 6 fails — must_skills.level is now an enum ('junior'..'expert'), the test
    # still sends the integer 4 and gets 422.
    "test_proposals.py",
    # 1 fail — _competence_category_matches is now True for a case the test
    # expects False.
    "test_recommendation_filters.py",
    # 7 fails (whole file) — fixture inserts jobs without client_id, now NOT NULL.
    "test_shortlist_and_proposal.py",
    # 1 fail — diacritic dedup returns 2 rows, the test expects 1.
    "test_team_structure_dl_clients_dedup.py",
}

_BASELINE = _COLLECTION_ERRORS | _LIVE | _FAILING


def test_ci_collects_the_whole_tests_directory() -> None:
    """CI must run `pytest tests/`, never a hand-enumerated file list.

    This is the load-bearing guard now. With auto-discovery a new test file is
    picked up automatically, so the old "did you remember to add it?" gap cannot
    reopen — unless someone reverts to enumerating targets, which is exactly
    what this catches.
    """
    step = _pytest_step()
    assert "pytest tests/" in step, (
        "The backend pytest step no longer runs `pytest tests/`. CI must collect "
        "the whole directory; excluding a file is done with --ignore=, so that "
        "the exception is visible and has to be justified in this file."
    )
    enumerated = set(_ENUMERATED_RE.findall(step))
    assert not enumerated, (
        f"{len(enumerated)} test file(s) are named as explicit pytest targets in "
        "ci.yml. That reintroduces the opt-in coverage hole this contract "
        "exists to prevent — every new file would again need remembering.\n"
        "Drop them; `pytest tests/` already collects them:\n"
        + "\n".join(f"    {f}" for f in sorted(enumerated))
    )


def test_every_ci_ignore_is_a_declared_exception() -> None:
    """Nothing is excluded from CI without a reason recorded here."""
    undeclared = _ci_ignored_files() - _BASELINE
    assert not undeclared, (
        f"{len(undeclared)} file(s) are --ignore'd in ci.yml but not declared in "
        "the categorised baseline in this file. An excluded test protects "
        "nothing, so the exclusion needs a written reason and a category "
        "(COLLECTION_ERRORS / LIVE / FAILING):\n"
        + "\n".join(f"    {f}" for f in sorted(undeclared))
    )


def test_baseline_matches_ci_and_has_no_stale_entries() -> None:
    """A file that got fixed (or deleted) must leave the baseline.

    Otherwise the burn-down cannot be measured: entries linger after the debt is
    paid and the number stops meaning anything. Failing here is progress.
    """
    disk = _disk_files()
    ignored = _ci_ignored_files()

    gone = {f for f in _BASELINE if f not in disk}
    assert not gone, (
        f"{len(gone)} baseline entry/entries no longer exist on disk. Remove "
        "them from the baseline in this file:\n"
        + "\n".join(f"    {f}" for f in sorted(gone))
    )

    not_ignored = _BASELINE - ignored
    assert not not_ignored, (
        f"{len(not_ignored)} baseline entry/entries are not --ignore'd in "
        "ci.yml, so they DO run. If they now pass, delete them from the "
        "baseline; if they still fail, CI is about to go red:\n"
        + "\n".join(f"    {f}" for f in sorted(not_ignored))
    )
