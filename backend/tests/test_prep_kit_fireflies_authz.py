"""Two access guards that every audit keeps re-finding when they silently drop.

1. M1B-SEC-01 — POST /api/prep-kit/generate must gate the client-specific output
   (overview, selling points, Tier-3 interview questions, all derived from the
   caller-supplied job's ClientKnowledge) behind the same per-client containment
   as GET /clients/{id}/knowledge. Without it a recruiter assigned only to client
   A can pass client B's job_id and read B's private knowledge (cross-team BOLA).
   The gate lives in the function body (it needs job.client_id), so it is checked
   structurally with ast — a dropped call is a silent regression.

2. M6-P0.11 — GET /api/fireflies/sync MUTATES (writes meeting notes, calls the
   external Fireflies API). It must not be reachable by the read-only ``user``
   viewer. Asserted by proving the route no longer depends on the permissive
   ``get_current_user`` (which admits every authenticated account); it now uses
   the role-restricted OperationalUser, whose require_roles closure excludes the
   viewer.
"""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def _function_source(module_rel: str, func_name: str) -> str:
    path = BACKEND / module_rel
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            return ast.get_source_segment(path.read_text(encoding="utf-8"), node) or ""
    raise AssertionError(f"{func_name} not found in {module_rel}")


def test_prepkit_gates_client_knowledge_per_client() -> None:
    """generate_prep_kit must resolve per-client access and deny on no knowledge."""
    src = _function_source("app/api/prep_kit.py", "generate_prep_kit")
    tree = ast.parse(src)

    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    attrs = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
    }

    assert "resolve_client_access" in called, (
        "prep-kit no longer resolves per-client access — client B's knowledge is "
        "leakable via a foreign job_id (M1B-SEC-01 regressed)"
    )
    assert "can_view_knowledge" in attrs, (
        "prep-kit resolves access but never checks can_view_knowledge — the gate "
        "is a no-op"
    )
    assert "deny" in called or "HTTPException" in called, (
        "prep-kit checks access but does not raise on denial"
    )


def test_fireflies_sync_not_reachable_by_viewer() -> None:
    """The mutating sync/status routes must not depend on the permissive
    get_current_user (which admits the read-only viewer)."""
    from app.api.deps import get_current_user
    from app.main import app

    guarded_paths = {"/api/fireflies/sync", "/api/fireflies/status"}
    from tests._route_introspection import iter_api_routes

    seen = set()
    for path, route in iter_api_routes(app):
        if path not in guarded_paths:
            continue
        seen.add(path)
        dep_calls = [
            dep.call for dep in getattr(route.dependant, "dependencies", [])
        ]
        assert get_current_user not in dep_calls, (
            f"{path} depends on get_current_user — a read-only viewer can reach a "
            "mutating Fireflies sync (M6-P0.11 regressed). Use OperationalUser."
        )

    assert seen == guarded_paths, f"routes not registered: {guarded_paths - seen}"
