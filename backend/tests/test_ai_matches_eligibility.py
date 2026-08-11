"""`/ai-matches` must contain the same candidates `/recommendations` does.

Both endpoints rank the same corpus for the same job and both are reachable from
the job page. Until 2026-08-11 only `/recommendations` ran the eligibility
filter; `/ai-matches` checked the GLOBAL blacklist and nothing else, so an
active client blacklist, an NDA, a competitor conflict or a standing
hiring-manager veto passed through — into a list rendered with an "add to
pipeline" button on every row.

The frontend calls it unconditionally (`app/jobs/[id]/page.tsx`), with no flag
and no role gate, so this was the default view for every recruiter, not an
admin-only diagnostic.
"""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def _calls_in(module_rel: str, func_name: str) -> set[str]:
    """Calls made by `func_name`, following one level into same-module helpers.

    A route handler often delegates: `/recommendations` calls the filter inside
    `_recommend_candidates_core`, not in the decorated function. Asserting only
    on the handler's direct calls would report a containment gap that does not
    exist — so resolve one hop through local helpers before deciding.
    """
    tree = ast.parse((BACKEND / module_rel).read_text(encoding="utf-8"))
    by_name = {
        n.name: n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    target = by_name.get(func_name)
    assert target is not None, f"{func_name} not found in {module_rel}"

    def direct(node) -> set[str]:
        """Names of functions called directly by `node`, in BOTH call forms.

        `filter_eligible_candidates(...)` and the module-qualified
        `pipeline_eligibility.filter_eligible_candidates(...)` must count the
        same. Matching only the bare name (`ast.Name`) ties this guard to one
        call SYNTAX rather than to the property it exists to protect.

        The failure that buys is a false ALARM, not a false pass: the assertion
        reads "the name appears among the calls", so an unrecognised call form
        makes it fail while the filter is demonstrably still there. That is the
        more corrosive direction. A guard that goes red on a safe refactor gets
        "fixed" by whoever is mid-refactor — and the cheapest fix is to weaken
        or delete the assertion. The guard then dies quietly on a day when
        nothing was actually wrong, and is missing on the day something is.
        """
        names: set[str] = set()
        for n in ast.walk(node):
            if not isinstance(n, ast.Call):
                continue
            if isinstance(n.func, ast.Name):
                names.add(n.func.id)
            elif isinstance(n.func, ast.Attribute):
                names.add(n.func.attr)
        return names

    calls = direct(target)
    for name in list(calls):
        helper = by_name.get(name)
        if helper is not None and helper is not target:
            calls |= direct(helper)
    return calls


def _endpoint_name(module_rel: str, path_fragment: str) -> str:
    """The handler decorated with a route containing `path_fragment`."""
    tree = ast.parse((BACKEND / module_rel).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            src = ast.dump(dec)
            if path_fragment in src:
                return node.name
    raise AssertionError(f"no handler for {path_fragment} in {module_rel}")


def test_ai_matches_runs_the_same_eligibility_filter_as_recommendations():
    handler = _endpoint_name("app/api/matching.py", "ai-matches")
    calls = _calls_in("app/api/matching.py", handler)

    assert "filter_eligible_candidates" in calls, (
        "/ai-matches surfaces candidates the recruiter cannot assign — client "
        "blacklist, NDA, competitor conflict, hiring-manager veto — next to an "
        "add-to-pipeline button"
    )


def test_both_ranking_surfaces_share_the_containment_rule():
    """Guard the guard: neither surface may quietly drop the filter."""
    for module, fragment in (
        ("app/api/matching.py", "ai-matches"),
        ("app/api/recommendations.py", "recommendations"),
    ):
        handler = _endpoint_name(module, fragment)
        assert "filter_eligible_candidates" in _calls_in(module, handler), (
            f"{module}:{handler} no longer enforces assignment eligibility"
        )
