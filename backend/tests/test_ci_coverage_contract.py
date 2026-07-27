"""Every test file must actually run in CI — or be a declared, reasoned exception.

The meta-cause behind this whole hardening effort: CI runs a hand-enumerated
list of test files, so every quality and security guardrail is opt-in — it only
protects anything if whoever added it also remembered to append the filename to
`.github/workflows/ci.yml`. That is exactly how a guardrail silently dies: the
test exists, passes locally, and never runs.

This contract inverts the default for NEW files: a test module that is neither
in the CI list nor in the explicit exception baseline below fails this test. The
hole becomes a visible red build instead of an invisible gap.

The baseline is a burn-down list, not a target. Each category says why the file
is not yet wired in, and the list should only ever shrink:

- COLLECTION_ERRORS — the file cannot even be collected (missing fixture data,
  import-time failure). Wiring it into CI as-is would break the build; it needs
  fixing first.
- LIVE — needs a running server (uses the `client` fixture, skipped unless
  RUN_LIVE_TESTS=1). These are genuinely out of scope for the in-process job.
- FAILING — collects fine, but red on its own today. Almost all of these are
  stale: the test never ran, so nobody noticed when a schema column went NOT
  NULL or a request contract gained a required field underneath it.
- SUITE_INTERFERENCE — green in isolation, red inside the full suite. These
  assume they own the database (e.g. asserting their own row id appears in an
  unpaginated global listing), which stops holding once sibling tests populate
  it. Fixing them means making the assertions local, not re-ordering CI.

Status 2026-07-27: 313 test modules on disk, 281 wired into ci.yml, 32 in the
baseline below (2 + 4 + 22 + 4). The previous 115-file UNWIRED backlog was
measured file-by-file in the prod image against a migrated database, and the 89
confirmed-green ones were wired into ci.yml — first as single files, then
re-confirmed in one combined 281-file invocation so cross-file interference
could not hide.
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
_CI_PATH_RE = re.compile(rf"tests/((?:[A-Za-z0-9_]+/)*{_MODULE})")


def _ci_listed_files() -> set[str]:
    return set(_CI_PATH_RE.findall(CI_YML.read_text(encoding="utf-8")))


def _disk_files() -> set[str]:
    """Every test module under backend/tests/, relative to that directory.

    `rglob` rather than `glob`, and both naming conventions: the previous
    non-recursive `glob("test_*.py")` could not see a test in a subdirectory nor
    one named `*_test.py`, so either was a free pass around this contract.
    """
    found: set[Path] = set()
    for pattern in ("test_*.py", "*_test.py"):
        found.update(TESTS.rglob(pattern))
    return {
        p.relative_to(TESTS).as_posix() for p in found if "__pycache__" not in p.parts
    }


# Files not in the CI list. Categorised so the reason is argued here, not
# hidden. Burn these down — do not add to them without cause.
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
    # 1 fail — expired public CV link answers 200, test expects 410.
    "test_candidate_stage_cv_branded.py",
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
    # 7 fails — fixture inserts candidates without lastname, now NOT NULL.
    "test_dl_portal.py",
    # 1 fail — fixture inserts client_orders without contract_id, now NOT NULL.
    "test_dl_portal_scheduler.py",
    # 1 fail — expired magic link answers 200, test expects 410.
    "test_engagement_magic_link.py",
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
    # 1 fail — test_search_matches_title_and_content finds no match.
    "test_procedures.py",
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

# Green alone, red in the full suite — measured in the same combined run. These
# assume an empty or exclusively-theirs database. Wiring them in as-is would
# make CI red for reasons unrelated to whatever a PR changed.
_SUITE_INTERFERENCE = {
    # test_revenue_forecast_shape: TypeError "'<' not supported between instances
    # of 'NoneType' and 'datetime.date'" once a sibling test leaves a contract
    # with a null date behind — arguably a real robustness gap in the forecast.
    "test_contract_analytics.py",
    # test_terminate_sets_reason_and_amendment: assert 'active' == 'ended'.
    "test_contracts_expansion.py",
    # asserts its own contract id is present in a global listing
    # (assert 145 in {1, 2, 4, ...}) — false as soon as the list is longer.
    "test_contracts_filters_multi.py",
    # same global-listing assumption (assert 154 in {...}).
    "test_contracts_search.py",
}

_BASELINE = _COLLECTION_ERRORS | _LIVE | _FAILING | _SUITE_INTERFERENCE


def test_no_new_test_file_escapes_ci() -> None:
    disk = _disk_files()
    ci = _ci_listed_files()
    uncovered = disk - ci - _BASELINE
    assert not uncovered, (
        f"{len(uncovered)} test file(s) are on disk but neither run in CI nor "
        "listed as a known exception. A test that does not run protects nothing.\n"
        "Add each to the pytest invocation in .github/workflows/ci.yml, or — if "
        "it genuinely cannot run in-process yet — to the categorised baseline in "
        "this file with a reason:\n" + "\n".join(f"    {f}" for f in sorted(uncovered))
    )


def test_baseline_has_no_stale_entries() -> None:
    """A file that got wired into CI (or deleted) must leave the baseline.

    Otherwise the burn-down cannot be measured: entries linger after the debt is
    paid and the number stops meaning anything. Failing here is progress.
    """
    disk = _disk_files()
    ci = _ci_listed_files()
    stale = {f for f in _BASELINE if f not in disk or f in ci}
    assert not stale, (
        f"{len(stale)} baseline entry/entries are no longer uncovered (wired into "
        "CI, or deleted). Remove them from the baseline in this file:\n"
        + "\n".join(f"    {f}" for f in sorted(stale))
    )
