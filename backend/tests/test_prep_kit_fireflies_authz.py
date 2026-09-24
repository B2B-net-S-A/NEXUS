"""Access guard that every audit keeps re-finding when it silently drops.

M1B-SEC-01 — POST /api/prep-kit/generate must gate the client-specific output
   (overview, selling points, Tier-3 interview questions, all derived from the
   caller-supplied job's ClientKnowledge) behind the same per-client containment
   as GET /clients/{id}/knowledge. Without it a recruiter assigned only to client
   A can pass client B's job_id and read B's private knowledge (cross-team BOLA).
   The gate lives in the function body (it needs job.client_id), so it is checked
   structurally with ast — a dropped call is a silent regression.
"""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def _function_source(module_rel: str, func_name: str) -> str:
    path = BACKEND / module_rel
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == func_name
        ):
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
    attrs = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}

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
