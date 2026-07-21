"""Every test file must actually run in CI — or be a declared, reasoned exception.

The meta-cause behind this whole hardening effort: CI runs a hand-enumerated
list of ~137 test files out of 263 on disk. Every quality and security guardrail
is therefore opt-in — it only protects anything if whoever added it also
remembered to append the filename to `.github/workflows/ci.yml`. That is exactly
how a guardrail silently dies: the test exists, passes locally, and never runs.
126 files are already in that limbo.

This contract inverts the default for NEW files: a `test_*.py` that is neither in
the CI list nor in the explicit exception baseline below fails this test. The
hole becomes a visible red build instead of an invisible gap.

The baseline is a burn-down list, not a target. Each category says why the file
is not yet wired in, and the list should only ever shrink:

- COLLECTION_ERRORS — the file cannot even be collected (missing fixture data,
  import-time failure). Wiring it into CI as-is would break the build; it needs
  fixing first.
- LIVE — needs a running server (uses the `client` fixture, skipped unless
  RUN_LIVE_TESTS=1). These are genuinely out of scope for the in-process job.
- UNWIRED — collects fine and is plausibly runnable, but has never been added to
  the CI list. This is the real debt; move files from here into ci.yml as they
  are confirmed green.
"""

from __future__ import annotations

import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CI_YML = BACKEND.parent / ".github" / "workflows" / "ci.yml"


def _ci_listed_files() -> set[str]:
    text = CI_YML.read_text(encoding="utf-8")
    return set(re.findall(r"tests/(test_[a-z0-9_]+\.py)", text))


def _disk_files() -> set[str]:
    return {p.name for p in (BACKEND / "tests").glob("test_*.py")}


# Files not in the CI list, frozen 2026-07-21. Categorised so the reason is
# argued here, not hidden. Burn these down — do not add to them without cause.
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

# The real debt: collects fine, never wired into CI. Frozen list; shrink it by
# moving confirmed-green files into ci.yml's pytest invocation.
#
# Measured 2026-07-21 by running all 120 in the prod image against a test DB:
# ~897 passed, 127 failed, 278 errored. So most work, but ~30% are red — many
# are stale tests from earlier sessions. Do NOT bulk-add this list to ci.yml: a
# file with one failing test turns CI red. Burn down per file, confirming each
# is fully green first.
_UNWIRED: set[str] = {
    "test_admin_clients_overview_head_dl.py",
    "test_admin_snapshot.py",
    "test_ai_health.py",
    "test_ai_provider_health.py",
    "test_ai_settings_schemas.py",
    "test_auto_assign_owners.py",
    "test_auto_cc_collaborators.py",
    "test_backfill_candidate_stage_cv.py",
    "test_backfill_rejection_reasons.py",
    "test_bulk_cv_download.py",
    "test_candidate_engagement.py",
    "test_candidate_risk_service.py",
    "test_candidate_sources_schemas.py",
    "test_candidate_stage_cv_branded.py",
    "test_candidate_stage_cv_model.py",
    "test_candidate_stage_cv_snapshot.py",
    "test_candidates_api_recent_job_change.py",
    "test_candidates_bulk_schemas.py",
    "test_candidates_export_v2.py",
    "test_candidates_from_cv.py",
    "test_candidates_from_linkedin.py",
    "test_candidates_position_filters.py",
    "test_candidates_recruitment_filter.py",
    "test_candidates_sort.py",
    "test_candidates_stage_filter.py",
    "test_cc_classifier.py",
    "test_cc_endpoints.py",
    "test_champion_ai_intake.py",
    "test_champion_historical_jobs.py",
    "test_claude_client.py",
    "test_client_materials.py",
    "test_client_profile.py",
    "test_clients_team.py",
    "test_cloudtalk_api.py",
    "test_cloudtalk_client.py",
    "test_cloudtalk_webhook.py",
    "test_cloudtalk_webhook_verify.py",
    "test_contract_alerts_expansion.py",
    "test_contract_analytics.py",
    "test_contract_analytics_expansion.py",
    "test_contract_templates.py",
    "test_contractors_api.py",
    "test_contracts.py",
    "test_contracts_draft.py",
    "test_contracts_expansion.py",
    "test_contracts_filters_multi.py",
    "test_contracts_search.py",
    "test_cv_backfill.py",
    "test_cv_enrichment.py",
    "test_cv_parser.py",
    "test_cv_parser_linkedin_extraction.py",
    "test_cv_text_extractor.py",
    "test_cv_upload_preview.py",
    "test_dl_portal.py",
    "test_dl_portal_scheduler.py",
    "test_engagement_magic_link.py",
    "test_entity_fields_schemas.py",
    "test_fx.py",
    "test_http_headers.py",
    "test_interview_questions.py",
    "test_invite_links.py",
    "test_invoices.py",
    "test_job_cc.py",
    "test_job_chat.py",
    "test_job_close.py",
    "test_job_to_pool.py",
    "test_jobs_auto_assign.py",
    "test_jobs_client_name.py",
    "test_jobs_filters_multi.py",
    "test_jobs_orphan_guard.py",
    "test_jobs_ownership.py",
    "test_kpi_coach_service.py",
    "test_kpi_engine.py",
    "test_kpi_messages.py",
    "test_logging_redaction.py",
    "test_m365_matcher.py",
    "test_m365_recording_discovery.py",
    "test_marketplace_flow.py",
    "test_marketplace_service.py",
    "test_matching_location.py",
    "test_matching_skills.py",
    "test_new_endpoints.py",
    "test_note_mentions.py",
    "test_notification_triggers.py",
    "test_oauth_clients_schemas.py",
    "test_oauth_token_schemas.py",
    "test_onboarding.py",
    "test_pending_verification.py",
    "test_presence_api.py",
    "test_presence_manager.py",
    "test_procedures.py",
    "test_proposals.py",
    "test_proxycurl_client.py",
    "test_proxycurl_diff.py",
    "test_rate_benchmarks.py",
    "test_rate_cards.py",
    "test_recommendation_competence_category_multi.py",
    "test_recommendation_filters.py",
    "test_rejection_email_integration.py",
    "test_rejection_email_scheduler.py",
    "test_reports_clients.py",
    "test_reports_invite_links.py",
    "test_reports_mrr_snapshot.py",
    "test_request_history.py",
    "test_scheduling.py",
    "test_screening_mentions.py",
    "test_seeking_contractors.py",
    "test_settings_candidates_columns.py",
    "test_shortlist_and_proposal.py",
    "test_similar_job_candidates.py",
    "test_similar_job_notify.py",
    "test_stage_notification_rules.py",
    "test_talent_pool_auto_add.py",
    "test_talent_pool_bulk_add.py",
    "test_talent_pool_cc.py",
    "test_talent_pools_api.py",
    "test_team_structure_dl_clients_dedup.py",
    "test_team_structure_my_team.py",
    "test_teams_notifications.py",
    "test_user_multi_role.py",
}

_BASELINE = _COLLECTION_ERRORS | _LIVE | _UNWIRED


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
