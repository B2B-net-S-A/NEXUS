"""Resource-scope contract for the per-recruitment surface.

``test_route_authz_contract.py`` asks "is this route gated at all?" and sorts
every endpoint into public / gated / bare. That question has one blind spot: a
role guard counts as "gated". ``CandidateDocumentAccess`` answers *may this
persona look at CVs*, never *may this persona look at CVs of THIS
recruitment* — so a router can be fully "gated" by that test and still hand
every recruiter every other recruiter's candidates.

That blind spot is why the same finding kept coming back. #791 gated the B2B
legal documents; #815 found the same data through a sibling path; #819 found it
again in the generator panel. Each fix was correct and each was overtaken,
because the hole was never a particular route — it was that resource scope is
invisible to the tooling that checks authorisation.

This contract closes the loop for the surfaces that carry per-recruitment data.
For the modules listed below, EVERY route must resolve the recruitment it is
touching and check membership. A new route added to any of them fails this test
until it does. The hole becomes a red build instead of the next audit finding.

Where the enforcement lives is deliberately flexible — a route may call the
guard directly, delegate to a helper that does (``_load_csv_for_stage``), or
scope a list query (``job_scope_clause``). What is NOT flexible is that some
scope decision must be visible in the handler.

Found by this test on its first run: ``refresh_original_cv`` bypassed the CV
choke point entirely (it builds the snapshot from scratch), so it overwrote the
CV of any stage id a caller cared to name. Reading the router had not surfaced
it; walking the routes did.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from typing import Any

# Modules whose every route touches one specific recruitment. Adding a module
# here is how a surface gets protected; removing one needs a reason.
_SCOPED_MODULES = {
    "app.api.candidate_stage_cv",  # CV snapshot + branded CV + share tokens
    "app.api.interview_feedback",  # candidate assessments per job
    "app.api.application_submissions",  # parked applications w/ candidate PII
}

# Individual routes on shared routers that address one recruitment. Matched as
# exact paths so a sibling route cannot inherit the exemption by accident.
_SCOPED_PATHS = {
    "/api/pipeline/stages/{stage_id}/share-token",
    "/api/pipeline/stages/share-token/{token}",
    "/api/candidates/{candidate_id}/recruitments/{job_id}",
    "/api/candidates/{candidate_id}/recruitments/{job_id}/client-rate",
    "/api/candidates/{candidate_id}/recruitments/{job_id}/expected-rate",
}

# Callables that constitute a resource-scope decision. Helpers are included on
# purpose: enforcing inside one choke point beats repeating the guard in every
# handler, because the repetition is what gets forgotten.
_SCOPE_MARKERS = (
    "ensure_job_membership",
    "ensure_optional_job_membership",
    "job_scope_clause",
    "_ensure_stage_membership",
    "_load_csv_for_stage",
    "require_dl_assigned_or_admin",
)


def _calls_scope_marker(endpoint: Any) -> bool:
    """True when the handler body performs a resource-scope check."""
    try:
        source = textwrap.dedent(inspect.getsource(endpoint))
    except (OSError, TypeError):  # pragma: no cover — builtins, C funcs
        return False
    try:
        tree = ast.parse(source)
    except SyntaxError:  # pragma: no cover — decorators can confuse dedent
        return False

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = getattr(func, "id", None) or getattr(func, "attr", None) or ""
        if name in _SCOPE_MARKERS:
            return True
    return False


def _scoped_routes() -> list[tuple[str, str, bool]]:
    """-> [(method, path, enforces_scope)] for the per-recruitment surface."""
    from app.main import app

    found: list[tuple[str, str, bool]] = []
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", None)
        endpoint = getattr(route, "endpoint", None)
        if not path.startswith("/api/") or not methods or endpoint is None:
            continue

        module = getattr(endpoint, "__module__", "")
        if module not in _SCOPED_MODULES and path not in _SCOPED_PATHS:
            continue

        enforces = _calls_scope_marker(endpoint)
        for method in sorted(methods):
            if method in {"HEAD", "OPTIONS"}:
                continue
            found.append((method, path, enforces))
    return sorted(found)


def test_every_recruitment_route_resolves_its_scope() -> None:
    """No route on the per-recruitment surface may skip the membership check."""
    unscoped = [(m, p) for m, p, ok in _scoped_routes() if not ok]
    assert not unscoped, (
        "These routes touch one specific recruitment but never resolve whose "
        "it is — a role guard alone lets any recruiter reach every other "
        "recruiter's candidates:\n"
        + "\n".join(f"  {m:6s} {p}" for m, p in unscoped)
        + "\n\nCall ensure_job_membership (or ensure_optional_job_membership "
        "when job_id is nullable, or job_scope_clause for list queries)."
    )


def test_surface_is_not_silently_empty() -> None:
    """Guard the guard: a rename must not turn this contract into a no-op.

    Every assertion above is over a filtered list. If the module paths in
    ``_SCOPED_MODULES`` stop matching — a file gets renamed, a router moves —
    the filter yields nothing, every assertion trivially passes, and the
    contract keeps reporting success while checking nothing at all.
    """
    routes = _scoped_routes()
    assert len(routes) >= 15, (
        f"Only {len(routes)} routes matched the per-recruitment surface; "
        "expected at least 15 (11 CV + 5 feedback + 2 submissions + 5 explicit "
        "paths). _SCOPED_MODULES or _SCOPED_PATHS has drifted from the code."
    )

    modules_seen = {p.split("/")[2] for _, p, _ in routes}
    assert modules_seen, "no paths resolved — route walking is broken"


def test_nullable_job_id_helper_is_distinct_from_the_strict_one() -> None:
    """``ensure_optional_job_membership`` must not silently allow everything.

    It exists because ``InterviewFeedback.job_id`` and
    ``ApplicationSubmission.job_id`` are nullable. The risk of such a helper is
    that it degenerates into a no-op and quietly disables the surfaces that use
    it, so pin the two branches: NULL passes, a real job id delegates to the
    strict guard.
    """
    import inspect as _inspect

    from app.api.recruitment_access import (
        ensure_job_membership,
        ensure_optional_job_membership,
    )

    source = _inspect.getsource(ensure_optional_job_membership)
    assert "if job_id is None:" in source, (
        "the NULL branch is gone — either the columns became NOT NULL "
        "(then delete this helper) or the guard was weakened"
    )
    assert ensure_job_membership.__name__ in source, (
        "ensure_optional_job_membership no longer delegates to the strict "
        "guard — a non-null job_id would go unchecked"
    )
