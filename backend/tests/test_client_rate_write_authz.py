"""P1-11: the client-rate WRITE endpoint must carry the same financial gate as
the READ of the same value.

The client rate („stawka do klienta") lives on ``CandidateStage`` and is served
back through ``GET /api/candidates/{id}/history``. That read redacts the rate
for anyone without :func:`has_financial_access` (admin + delivery_lead) — see
``_candidate_history_response_for_user``.

The matching write, ``PATCH /api/candidates/{candidate_id}/recruitments/{job_id}
/client-rate``, guards only with ``CandidateFinanceAccess`` — a *broader* role
set that also admits ``tac``. So before the fix a ``tac`` account could CHANGE a
rate it is not allowed to even SEE, feeding straight into margin and invoicing
with no old→new trail.

This is a structural/route-inspection test (no DB): it walks the registered
routes, finds the client-rate write route, and asserts its handler enforces
:func:`require_financial_access` — the raising twin of the read gate — either as
a dependency or as an in-body check. It fails on the pre-fix handler (which
enforces neither) and passes once the gate is added.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from typing import Any

WRITE_METHOD = "PATCH"
WRITE_PATH = "/api/candidates/{candidate_id}/recruitments/{job_id}/client-rate"

# The read-parity gate. Both spellings live in app.api.financial_access:
# ``has_financial_access`` (bool, used by the /history redaction) and
# ``require_financial_access`` (raises 403 — the write must use this one).
FINANCIAL_GATE = "require_financial_access"


def _walk_dependants(dependant: Any) -> list[Any]:
    """Flatten FastAPI's dependency tree — gates can be nested one level in."""
    out: list[Any] = []
    stack = [dependant]
    seen: set[int] = set()
    while stack:
        node = stack.pop()
        if node is None or id(node) in seen:
            continue
        seen.add(id(node))
        out.append(node)
        stack.extend(getattr(node, "dependencies", []) or [])
    return out


def _dependency_qualnames(route: Any) -> list[str]:
    dependant = getattr(route, "dependant", None)
    if dependant is None:
        return []
    names: list[str] = []
    for node in _walk_dependants(dependant):
        call = getattr(node, "call", None)
        if call is None:
            continue
        names.append(getattr(call, "__qualname__", "") or getattr(call, "__name__", ""))
    return names


def _body_calls(route: Any) -> set[str]:
    """Names of functions called in the handler body (AST-resolved)."""
    endpoint = getattr(route, "endpoint", None)
    if endpoint is None:
        return set()
    try:
        source = textwrap.dedent(inspect.getsource(endpoint))
        tree = ast.parse(source)
    except (OSError, TypeError, SyntaxError):  # pragma: no cover
        return set()
    calls: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = getattr(func, "id", None) or getattr(func, "attr", None)
            if name:
                calls.add(name)
    return calls


def _find_route(method: str, path: str) -> Any:
    from app.main import app

    for route in app.routes:
        if getattr(route, "path", "") != path:
            continue
        methods = getattr(route, "methods", None) or set()
        if method in methods:
            return route
    raise AssertionError(f"route not registered: {method} {path}")


def test_client_rate_write_enforces_financial_gate() -> None:
    """The write route must enforce require_financial_access (dep or body)."""
    route = _find_route(WRITE_METHOD, WRITE_PATH)

    in_dependencies = any(FINANCIAL_GATE in q for q in _dependency_qualnames(route))
    in_body = FINANCIAL_GATE in _body_calls(route)

    assert in_dependencies or in_body, (
        f"{WRITE_METHOD} {WRITE_PATH} must enforce {FINANCIAL_GATE}() so a role "
        "that cannot read the client rate cannot change it (P1-11). Found neither "
        "a dependency nor an in-body call."
    )


def test_read_path_uses_financial_gate() -> None:
    """Reference: /history redaction is keyed on the same financial gate.

    Pins the parity this fix restores — if the read gate ever changes name,
    this surfaces it rather than silently drifting from the write gate.
    """
    from app.api import candidates

    source = inspect.getsource(candidates._candidate_history_response_for_user)
    assert "has_financial_access" in source
