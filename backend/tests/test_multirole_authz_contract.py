"""Authorisation decisions must read the whole role set, not just the primary.

Since migration 0110 a user holds a primary role (``users.role``) *and* a set
of secondary roles (``users.roles`` JSONB) — the multi-role schema from PR #207.
``User.has_role`` / ``has_any_role`` evaluate the union; a bare
``current_user.role == UserRole.admin`` sees only the primary.

The difference is not academic. The documented case is a secretary carrying
``primary=recruiter`` with ``secondary=admin`` after an AAD group sync: every
comparison against ``.role`` silently denies her, and the denial looks like a
permissions bug nobody can reproduce because it depends on which role happens
to be primary.

Seven such comparisons were found and fixed on 2026-07-20 (calendar cross-user
lookups, contractor visibility scoping, job ownership and claiming, DL reports,
team structure, interview-question editing). This test stops the eighth.

Not every ``.role`` read is a bug. Selecting *behaviour* by primary role is
legitimate — the onboarding flow branches on it deliberately, because a hybrid
user still has one identity to onboard as. Those live in the allowlist below
with a reason. Authorisation is different: it must ask "does this user hold a
qualifying role", never "is their primary role the qualifying one".
"""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]

# (file, function) pairs where comparing the PRIMARY role is deliberate.
# Each needs a reason — this list is the place where an exception gets argued,
# not the place where it gets hidden.
_ALLOWED_PRIMARY_ROLE_BRANCHES = {
    # Picks WHICH onboarding flow to run, not WHETHER the caller may run one.
    # A hybrid delivery_lead+recruiter onboards as their primary identity; the
    # union would make the branch ambiguous (both arms would match).
    ("onboarding.py", "complete_onboarding"),
}


def _authorisation_role_comparisons() -> list[str]:
    """-> ["file.py:line function — snippet"] for primary-role comparisons."""
    offenders: list[str] = []
    for directory in ("api", "services"):
        for path in sorted((BACKEND / "app" / directory).glob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover
                continue

            # Map each node to its enclosing function so the allowlist can be
            # scoped per handler rather than per file — a blanket file-level
            # exemption would hide new offenders in the same module.
            enclosing: dict[int, str] = {}
            for func in ast.walk(tree):
                if isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for node in ast.walk(func):
                        enclosing.setdefault(id(node), func.name)

            for node in ast.walk(tree):
                if not isinstance(node, ast.Compare):
                    continue
                left = node.left
                # Match `current_user.role` / `user.role` on the left-hand side,
                # but not `.role.value` (a display read, not a decision).
                if not (
                    isinstance(left, ast.Attribute)
                    and left.attr == "role"
                    and isinstance(left.value, ast.Name)
                    and left.value.id in {"current_user", "user"}
                ):
                    continue
                if not any(
                    isinstance(op, (ast.Eq, ast.NotEq, ast.In, ast.NotIn))
                    for op in node.ops
                ):
                    continue
                # `user.role != new_role` compares the OLD role to the NEW one
                # during a role change — that is change detection, not a
                # permission decision, and rewriting it with has_role would be
                # nonsense. Distinguish by what is on the right: a singular
                # `*_role` variable is a role VALUE; a `*_ROLES` set or a
                # `UserRole.x` literal is a permission SET.
                if all(
                    isinstance(c, ast.Name) and c.id.endswith("_role")
                    for c in node.comparators
                ):
                    continue
                func_name = enclosing.get(id(node), "<module>")
                if (path.name, func_name) in _ALLOWED_PRIMARY_ROLE_BRANCHES:
                    continue
                offenders.append(
                    f"{path.name}:{node.lineno} in {func_name}() — "
                    f"compares current_user.role directly"
                )
    return offenders


def test_no_primary_role_only_authorisation() -> None:
    offenders = _authorisation_role_comparisons()
    assert not offenders, (
        f"{len(offenders)} authorisation decision(s) read only the PRIMARY role "
        "and therefore ignore secondary roles from the multi-role schema "
        "(migration 0110). A user with primary=recruiter and secondary=admin "
        "would be wrongly denied.\n\n"
        "Use `current_user.has_role(X)` or `has_any_role(*ROLES)` instead. If "
        "the comparison genuinely selects BEHAVIOUR rather than PERMISSION, add "
        "it to _ALLOWED_PRIMARY_ROLE_BRANCHES with a reason.\n\n"
        + "\n".join(f"    {o}" for o in offenders)
    )
