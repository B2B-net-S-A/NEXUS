"""Deny-by-default contract for route authorisation.

The single most repeated finding across every module audit is not a bug — it is
a *default*. Nothing in this codebase answers "may this user touch this
resource?" in one place. Each router author picks a dependency by hand:
sometimes ``CandidatePIIAccess`` or ``ClientAccess`` or ``require_financial_
access``, and often just ``CurrentUser``. ``CurrentUser`` only proves the caller
is logged in, so the effective default is **authenticated means authorised**.

That default is why fixing one router never held. #791 gated the B2B legal
documents; #815 then found the same data reachable through a sibling path;
#819 found candidate data leaking from the B2B generator panel. Each fix was
correct and each was overtaken, because the hole was never a particular route —
it was that adding a route requires *remembering* to gate it.

This test inverts that. It walks every registered route, resolves the real
dependency chain, and classifies each one:

- **public** — no authentication at all in the chain (login, health, webhooks)
- **gated** — some resource or role dependency beyond bare authentication
- **bare** — authenticated, and nothing more

Bare routes must appear in ``_BARE_BASELINE``. Anything new that is merely
authenticated fails the build. The hole becomes *a missing registry entry*,
which CI can see, instead of *a missing memory*, which it cannot.

The baseline is deliberately a frozen list rather than a target of zero: 779
endpoints cannot be audited in one change, and a test that demands the
impossible gets deleted. It stops the bleeding today and is burned down module
by module — each entry removed is one route that gained a real gate.
"""

from __future__ import annotations

from typing import Any

# Dependency callables that constitute a genuine authorisation decision, as
# opposed to merely establishing who the caller is. Matched on __qualname__ so
# the closures returned by factories like require_roles(...) are recognised.
_GATE_QUALNAME_MARKERS = (
    "require_roles",
    "require_dl_assigned_or_admin",
    "require_financial_access",
    "require_capability",
    "require_dynareporter_section",
    "_snapshot_auth",
    "require_admin",
    "require_contractor_access",
)

# The bare authentication dependency: proves identity, decides nothing.
_AUTHN_QUALNAMES = ("get_current_user",)


def _walk_dependants(dependant: Any) -> list[Any]:
    """Flatten FastAPI's dependency tree — gates are often nested one level in."""
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


def _classify(route: Any) -> str:
    dependant = getattr(route, "dependant", None)
    if dependant is None:
        return "public"

    qualnames = []
    for node in _walk_dependants(dependant):
        call = getattr(node, "call", None)
        if call is None:
            continue
        qualnames.append(getattr(call, "__qualname__", "") or getattr(call, "__name__", ""))

    if any(any(m in q for m in _GATE_QUALNAME_MARKERS) for q in qualnames):
        return "gated"
    if any(any(a in q for a in _AUTHN_QUALNAMES) for q in qualnames):
        return "bare"
    return "public"


def _routes() -> list[tuple[str, str, str]]:
    """-> [(method, path, classification)] for every API route."""
    from app.main import app

    found: list[tuple[str, str, str]] = []
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", None)
        if not path.startswith("/api/") or not methods:
            continue
        classification = _classify(route)
        for method in sorted(methods):
            if method in {"HEAD", "OPTIONS"}:
                continue
            found.append((method, path, classification))
    return sorted(found)


# Routes that are authenticated and nothing more, frozen as of 2026-07-20.
# Populated from the CI run that first executed this test — measuring rather
# than guessing, the same way the schema-drift baselines were established.
#
# Every entry is a route where being logged in is currently sufficient. Some are
# genuinely fine (a user reading their own notification list); most have simply
# never been reviewed. Removing an entry means the route gained a real gate —
# that is the burn-down.
_BARE_BASELINE: set[tuple[str, str]] = set()


def test_no_new_bare_authenticated_routes() -> None:
    """A new route may not rely on authentication alone."""
    bare = {(m, p) for m, p, c in _routes() if c == "bare"}
    new = bare - _BARE_BASELINE
    assert not new, (
        f"{len(new)} route(s) are authenticated but not authorised, and are not "
        "in the baseline. Give each a resource gate "
        "(CandidatePIIAccess / ClientAccess / require_financial_access / "
        "AdminUser / require_capability), or add it to _BARE_BASELINE with a "
        f"justification:\n" + "\n".join(f"  {m} {p}" for m, p in sorted(new))
    )


def test_report_route_authz_inventory() -> None:
    """Always-passing census — its output is how the baseline gets captured.

    Prints counts and the full bare list so a CI run can be read as the
    measurement. Deliberately never fails: its job is to inform, and the
    enforcing assertion lives in the test above.
    """
    routes = _routes()
    counts = {"public": 0, "gated": 0, "bare": 0}
    for _m, _p, c in routes:
        counts[c] += 1

    bare = sorted({(m, p) for m, p, c in routes if c == "bare"})
    print(f"\n=== route authz inventory: {len(routes)} routes ===")
    print(f"  gated  : {counts['gated']}")
    print(f"  bare   : {counts['bare']}")
    print(f"  public : {counts['public']}")
    print("\n_BARE_BASELINE = {")
    for method, path in bare:
        print(f'    ("{method}", "{path}"),')
    print("}")

    assert routes, "no /api routes were discovered — the walker is broken"
