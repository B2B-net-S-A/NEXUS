"""Read-only aggregate comparison of archived, unfiltered full-search runs.

No candidate identities or source text leave the report. This checks stored
results; it does not establish which screen started a run, live freshness or
recruiter relevance. An incomplete index cannot pass full ranking parity.
"""

import math

from sqlalchemy import select

from app.models.candidate_search_run import CandidateSearchResult


def compare_runs(left, left_rows, right, right_rows):
    if left.id == right.id:
        raise ValueError("Comparison requires two distinct runs")

    def index(run, rows):
        result = {row.candidate_id: row for row in rows}
        if len(result) != len(rows) or len(rows) != run.population_size:
            raise ValueError("Incomplete or duplicate population snapshot")
        return result

    def measured(row):
        return (
            row.measurement == "measured"
            and type(row.fit_score) in (int, float)
            and math.isfinite(row.fit_score)
            and 0 <= row.fit_score <= 100
        )

    def ranking(run, rows):
        visible = [r for r in rows if r.state == "evaluated" and r.eligible is True]
        complete = (
            run.state == "complete"
            and all(r.state == "evaluated" for r in rows)
            and all(r.eligible is not None for r in rows)
            and all(measured(r) for r in visible)
        )
        # Missing/invalid measurements sort last, never become measured zero.
        visible.sort(
            key=lambda r: (
                not measured(r),
                -r.fit_score if measured(r) else 0,
                r.candidate_id,
            )
        )
        return complete, [r.candidate_id for r in visible]

    a, b = index(left, left_rows), index(right, right_rows)
    common = a.keys() & b.keys()
    version_changes = sum(
        a[c].candidate_version != b[c].candidate_version for c in common
    )
    eligibility_changes = sum(a[c].eligible != b[c].eligible for c in common)
    deltas = [
        abs(a[c].fit_score - b[c].fit_score)
        for c in common
        if a[c].candidate_version == b[c].candidate_version
        and a[c].state == b[c].state == "evaluated"
        and a[c].eligible is True
        and b[c].eligible is True
        and measured(a[c])
        and measured(b[c])
    ]
    left_complete, left_order = ranking(left, left_rows)
    right_complete, right_order = ranking(right, right_rows)
    same_context = (
        left.created_by == right.created_by
        and left.request_fingerprint == right.request_fingerprint
        and left.version_trace == right.version_trace
    )
    same_population = a.keys() == b.keys()
    mismatches = sum(delta > 0.1 + 1e-9 for delta in deltas)
    return {
        "left_run_id": left.id,
        "right_run_id": right.id,
        "same_context": same_context,
        "same_population": same_population,
        "left_population": len(a),
        "right_population": len(b),
        "common_candidates": len(common),
        "changed_candidate_versions": version_changes,
        "eligibility_differences": eligibility_changes,
        "comparable_measured_pairs": len(deltas),
        "max_absolute_score_difference": max(deltas) if deltas else None,
        "score_differences_above_tolerance": mismatches,
        "score_tolerance": 0.1,
        "same_ranked_ids_and_order": left_order == right_order,
        "left_ranking_complete": left_complete,
        "right_ranking_complete": right_complete,
        "archived_parity_complete": (
            same_context
            and same_population
            and not version_changes
            and not eligibility_changes
            and left_complete
            and right_complete
            and not mismatches
            and left_order == right_order
        ),
    }


async def recent_comparisons(db, runs):
    """At most three newest same-actor/context pairs from the bounded run list."""
    if len(runs) > 10:
        raise ValueError("Comparison requires at most ten recent runs")
    pairs, previous = [], {}
    for run in runs:
        if run.state not in {"complete", "partial"}:
            continue
        key = (run.created_by, run.request_fingerprint)
        if key in previous:
            pairs.append((previous.pop(key), run))
            if len(pairs) == 3:
                break
        else:
            previous[key] = run
    reports = []
    for left, right in pairs:
        result = (
            await db.execute(
                select(
                    CandidateSearchResult.run_id,
                    CandidateSearchResult.candidate_id,
                    CandidateSearchResult.candidate_version,
                    CandidateSearchResult.state,
                    CandidateSearchResult.eligible,
                    CandidateSearchResult.fit_score,
                    CandidateSearchResult.measurement,
                ).where(CandidateSearchResult.run_id.in_([left.id, right.id]))
            )
        ).all()
        reports.append(
            compare_runs(
                left,
                [r for r in result if r.run_id == left.id],
                right,
                [r for r in result if r.run_id == right.id],
            )
        )
    return reports
