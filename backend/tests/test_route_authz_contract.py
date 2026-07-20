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

import ast
import inspect
import textwrap
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

# Many handlers carry no gate in their signature but check imperatively as the
# first statement of the body — e.g. `dynareporter_admin_master_data.py` takes
# `current_user: CurrentUser` and then calls `_require_admin(current_user)`.
# That is genuine authorisation; it is simply invisible to FastAPI's dependency
# graph, and therefore to any structural analysis.
#
# The distinction matters and the two are NOT the same problem:
#
#   bare_unchecked — nothing anywhere. A read-only `user` can do this. A hole.
#   bare_in_body   — enforced, but only by a line somebody has to remember to
#                    write. Invisible in OpenAPI, unenforced for the next
#                    handler added to the file, and silently lost if a refactor
#                    returns early. A robustness problem, not a hole.
#
# Collapsing them would either overstate the danger or hide it. They are
# counted separately.
_IN_BODY_CALL_PREFIXES = ("_require_", "require_", "_assert_", "_ensure_")
_IN_BODY_ATTRIBUTE_MARKERS = ("has_role", "HTTP_403_FORBIDDEN")


def _has_in_body_check(route: Any) -> bool:
    """True when the handler authorises imperatively rather than via Depends."""
    endpoint = getattr(route, "endpoint", None)
    if endpoint is None:
        return False
    try:
        source = textwrap.dedent(inspect.getsource(endpoint))
    except (OSError, TypeError):  # pragma: no cover — builtins, C funcs
        return False
    try:
        tree = ast.parse(source)
    except SyntaxError:  # pragma: no cover — decorators can confuse dedent
        return False

    for node in ast.walk(tree):
        # `_require_admin(current_user)` / `require_client_access(...)`
        if isinstance(node, ast.Call):
            func = node.func
            name = getattr(func, "id", None) or getattr(func, "attr", None) or ""
            if any(name.startswith(p) for p in _IN_BODY_CALL_PREFIXES):
                return True
            if any(m in name for m in _IN_BODY_ATTRIBUTE_MARKERS):
                return True
        # `raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, ...)`
        if isinstance(node, ast.Attribute) and node.attr in _IN_BODY_ATTRIBUTE_MARKERS:
            return True
    return False


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
        return "bare_in_body" if _has_in_body_check(route) else "bare_unchecked"
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
# Populated from the CI run that first executed this test — measured, not
# guessed, the same way the schema-drift baselines were established.
#
# 233 of 779 endpoints. The shape of it matters more than the number:
#
#     GET     147     reads
#     POST     47   ┐
#     DELETE   20   │ 86 routes that CHANGE DATA behind nothing but a login
#     PATCH    11   │
#     PUT       8   ┘
#
# The destructive ones are not obscure: deleting contacts, client knowledge,
# job collaborators, DynaReporter master data. Any authenticated account —
# including the read-only `user` role — reaches them.
#
# Some entries are genuinely fine (a user reading their own notifications);
# most have simply never been reviewed. Removing an entry means that route
# gained a real gate. That is the burn-down, and mutating routes come first.
_BARE_BASELINE: set[tuple[str, str]] = {
    ("DELETE", "/api/candidates/{candidate_id}/chat/messages/{msg_id}"),
    ("DELETE", "/api/candidates/{candidate_id}/chat/messages/{msg_id}/reactions/{emoji}"),
    ("DELETE", "/api/client-knowledge/{knowledge_id}"),
    ("DELETE", "/api/cloudtalk/agents/{agent_id}/assign"),
    ("DELETE", "/api/contacts/{contact_id}"),
    ("DELETE", "/api/dynareporter/admin-hof/winner/{winner_id}"),
    ("DELETE", "/api/dynareporter/admin-master-data/clients/{client_id}"),
    ("DELETE", "/api/dynareporter/admin-master-data/consultants/{consultant_id}"),
    ("DELETE", "/api/dynareporter/admin-users/dl-clients/{assignment_id}"),
    ("DELETE", "/api/dynareporter/admin-users/team/sourcer-categories/{user_id}/{category_id}"),
    ("DELETE", "/api/dynareporter/admin-users/team/tac-dl/{tac_user_id}/{dl_user_id}"),
    ("DELETE", "/api/interview-questions/{question_id}"),
    ("DELETE", "/api/jobs/{job_id}/chat/messages/{msg_id}"),
    ("DELETE", "/api/jobs/{job_id}/chat/messages/{msg_id}/reactions/{emoji}"),
    ("DELETE", "/api/jobs/{job_id}/collaborators/{user_id}"),
    ("DELETE", "/api/jobs/{job_id}/questions/{question_id}"),
    ("DELETE", "/api/microsoft365/connection"),
    ("DELETE", "/api/postings/{posting_id}"),
    ("DELETE", "/api/saved-searches/{search_id}"),
    ("DELETE", "/api/user-email-templates/{template_id}"),
    ("GET", "/api/activities/stats"),
    ("GET", "/api/analytics/v1/me/calls"),
    ("GET", "/api/analytics/v1/me/kpis"),
    ("GET", "/api/analytics/v1/meta/metrics"),
    ("GET", "/api/analytics/v1/recruitment/users/{user_id}"),
    ("GET", "/api/autenti/contracts/{contract_id}/signatures"),
    ("GET", "/api/autenti/health"),
    ("GET", "/api/autenti/signatures/{signature_id}"),
    ("GET", "/api/auth/me"),
    ("GET", "/api/calls/stats"),
    ("GET", "/api/candidates/{candidate_id}/chat/members"),
    ("GET", "/api/candidates/{candidate_id}/chat/messages"),
    ("GET", "/api/candidates/{candidate_id}/chat/messages/{msg_id}/read-by"),
    ("GET", "/api/candidates/{candidate_id}/chat/pinned"),
    ("GET", "/api/candidates/{candidate_id}/chat/unread-count"),
    ("GET", "/api/candidates/{candidate_id}/conflicts"),
    ("GET", "/api/candidates/{candidate_id}/emails"),
    ("GET", "/api/candidates/{candidate_id}/emails/thread/{conversation_id:path}"),
    ("GET", "/api/candidates/{candidate_id}/rate-history"),
    ("GET", "/api/clients-lookup"),
    ("GET", "/api/clients/{client_id}/contacts"),
    ("GET", "/api/clients/{client_id}/contract-terms"),
    ("GET", "/api/clients/{client_id}/framework-contracts"),
    ("GET", "/api/clients/{client_id}/framework-contracts/{fc_id}"),
    ("GET", "/api/clients/{client_id}/framework-contracts/{fc_id}/amendments"),
    ("GET", "/api/clients/{client_id}/framework-contracts/{fc_id}/amendments/{amendment_id}/file"),
    ("GET", "/api/clients/{client_id}/framework-contracts/{fc_id}/file"),
    ("GET", "/api/clients/{client_id}/knowledge"),
    ("GET", "/api/clients/{client_id}/notification-overrides"),
    ("GET", "/api/clients/{client_id}/one-pagers"),
    ("GET", "/api/clients/{client_id}/one-pagers/{one_pager_id}/download"),
    ("GET", "/api/clients/{client_id}/required-documents"),
    ("GET", "/api/clients/{client_id}/required-documents/{doc_id}/download"),
    ("GET", "/api/clients/{client_id}/team"),
    ("GET", "/api/cloudtalk/agents"),
    ("GET", "/api/competence-categories"),
    ("GET", "/api/competence-categories/{cc_id}/recruiters"),
    ("GET", "/api/competitions/current"),
    ("GET", "/api/competitions/history"),
    ("GET", "/api/competitions/monthly-races"),
    ("GET", "/api/competitions/my-position"),
    ("GET", "/api/contacts"),
    ("GET", "/api/contractors"),
    ("GET", "/api/contractors/stats"),
    ("GET", "/api/cv-generator/candidates/{candidate_id}/recruitments"),
    ("GET", "/api/dashboard/kpis"),
    ("GET", "/api/dashboard/pipeline-funnel"),
    ("GET", "/api/dashboard/stats"),
    ("GET", "/api/dictionaries/{slug}/items"),
    ("GET", "/api/dynareporter/admin-dashboard/audit-log"),
    ("GET", "/api/dynareporter/admin-dashboard/upload-history"),
    ("GET", "/api/dynareporter/admin-dashboard/users"),
    ("GET", "/api/dynareporter/admin-users/dl-clients"),
    ("GET", "/api/dynareporter/admin-users/employees"),
    ("GET", "/api/dynareporter/admin-users/team/members"),
    ("GET", "/api/dynareporter/admin-users/team/sourcer-categories"),
    ("GET", "/api/dynareporter/admin-users/team/tac-dl"),
    ("GET", "/api/dynareporter/board-dashboard/monthly"),
    ("GET", "/api/dynareporter/competitions/my-notifications"),
    ("GET", "/api/dynareporter/kpi/body-leasing/my"),
    ("GET", "/api/dynareporter/kpi/body-leasing/ranking"),
    ("GET", "/api/dynareporter/kpi/body-leasing/summary"),
    ("GET", "/api/dynareporter/kpi/delivery-lead/my"),
    ("GET", "/api/dynareporter/kpi/delivery-lead/summary"),
    ("GET", "/api/dynareporter/kpi/sales/my"),
    ("GET", "/api/dynareporter/kpi/sales/summary"),
    ("GET", "/api/dynareporter/placements/my"),
    ("GET", "/api/dynareporter/placements/stats/by-client"),
    ("GET", "/api/dynareporter/placements/stats/by-user"),
    ("GET", "/api/dynareporter/profile/me"),
    ("GET", "/api/dynareporter/upload/history"),
    ("GET", "/api/email-templates"),
    ("GET", "/api/email-templates/{template_id}"),
    ("GET", "/api/emails/{email_id}"),
    ("GET", "/api/emails/{email_id}/attachments/{attachment_id}/download"),
    ("GET", "/api/embed-diagnostics"),
    ("GET", "/api/entity-schema/{entity_type}"),
    ("GET", "/api/fireflies/status"),
    ("GET", "/api/fireflies/sync"),
    ("GET", "/api/fireflies/transcripts"),
    ("GET", "/api/fx"),
    ("GET", "/api/interview-questions"),
    ("GET", "/api/interview-questions/{question_id}"),
    ("GET", "/api/invite-links"),
    ("GET", "/api/jobs"),
    ("GET", "/api/jobs-lookup"),
    ("GET", "/api/jobs/train-names"),
    ("GET", "/api/jobs/{job_id}"),
    ("GET", "/api/jobs/{job_id}/champion-profile"),
    ("GET", "/api/jobs/{job_id}/champion-profile/briefing/audio-url"),
    ("GET", "/api/jobs/{job_id}/champion-profile/consultant-suggestions"),
    ("GET", "/api/jobs/{job_id}/chat/members"),
    ("GET", "/api/jobs/{job_id}/chat/messages"),
    ("GET", "/api/jobs/{job_id}/chat/messages/{msg_id}/read-by"),
    ("GET", "/api/jobs/{job_id}/chat/pinned"),
    ("GET", "/api/jobs/{job_id}/chat/unread-count"),
    ("GET", "/api/jobs/{job_id}/collaborators"),
    ("GET", "/api/jobs/{job_id}/postings"),
    ("GET", "/api/jobs/{job_id}/questions"),
    ("GET", "/api/jobs/{job_id}/suggested-questions"),
    ("GET", "/api/kpis/me/panel"),
    ("GET", "/api/kpis/me/today"),
    ("GET", "/api/linkedin-metrics/my-summary"),
    ("GET", "/api/linkedin-metrics/summary"),
    ("GET", "/api/match-history/{job_id}/{candidate_id}"),
    ("GET", "/api/microsoft365/authorize"),
    ("GET", "/api/microsoft365/connection"),
    ("GET", "/api/microsoft365/emails/search"),
    ("GET", "/api/my-clients"),
    ("GET", "/api/my-relationships"),
    ("GET", "/api/notifications"),
    ("GET", "/api/notifications/count"),
    ("GET", "/api/pipeline-templates"),
    ("GET", "/api/pipeline-templates/{template_id}"),
    ("GET", "/api/pipeline-templates/{template_id}/stages/{stage_def_id}/notification-rules"),
    ("GET", "/api/pipeline/history/{candidate_id}/{job_id}"),
    ("GET", "/api/pipeline/kanban/{job_id}"),
    ("GET", "/api/pipeline/overview"),
    ("GET", "/api/pipeline/stages"),
    ("GET", "/api/pipeline/stages/{stage_id}/screening"),
    ("GET", "/api/postings/stats"),
    ("GET", "/api/procedures"),
    ("GET", "/api/procedures/{id_or_slug}"),
    ("GET", "/api/rate-cards"),
    ("GET", "/api/rate-cards/suggest"),
    ("GET", "/api/rate-cards/{card_id}"),
    ("GET", "/api/reports/my-delivery-lead"),
    ("GET", "/api/required-document-templates"),
    ("GET", "/api/saved-searches"),
    ("GET", "/api/search/"),
    ("GET", "/api/search/global"),
    ("GET", "/api/settings/candidates-columns"),
    ("GET", "/api/signing/contracts/{contract_id}/signatures"),
    ("GET", "/api/signing/health"),
    ("GET", "/api/signing/signatures/{signature_id}"),
    ("GET", "/api/skills"),
    ("GET", "/api/skills/autocomplete"),
    ("GET", "/api/team-structure/dl-clients"),
    ("GET", "/api/team-structure/my-team"),
    ("GET", "/api/team-structure/sourcer-categories"),
    ("GET", "/api/team-structure/summary"),
    ("GET", "/api/team-structure/tac-delivery-leads"),
    ("GET", "/api/user-email-templates"),
    ("GET", "/api/user-email-templates/{template_id}"),
    ("GET", "/api/users"),
    ("GET", "/api/users/me/preferences"),
    ("GET", "/api/users/mentionable"),
    ("PATCH", "/api/candidates/{candidate_id}/chat/messages/{msg_id}"),
    ("PATCH", "/api/dynareporter/admin-master-data/clients/{client_id}"),
    ("PATCH", "/api/dynareporter/admin-master-data/consultants/{consultant_id}"),
    ("PATCH", "/api/dynareporter/admin-users/dl-clients/{assignment_id}"),
    ("PATCH", "/api/dynareporter/competitions/notifications/{notif_id}/read"),
    ("PATCH", "/api/jobs/{job_id}/chat/messages/{msg_id}"),
    ("PATCH", "/api/jobs/{job_id}/questions/reorder"),
    ("PATCH", "/api/notifications/read-all"),
    ("PATCH", "/api/notifications/{notification_id}/read"),
    ("PATCH", "/api/saved-searches/{search_id}"),
    ("PATCH", "/api/users/me/preferences"),
    ("POST", "/api/ai/generate-job"),
    ("POST", "/api/ai/generate-job-description"),
    ("POST", "/api/auth/change-password"),
    ("POST", "/api/candidates/{candidate_id}/chat/messages"),
    ("POST", "/api/candidates/{candidate_id}/chat/messages/{msg_id}/reactions"),
    ("POST", "/api/clients/{client_id}/knowledge"),
    ("POST", "/api/cloudtalk/agents/{agent_id}/assign"),
    ("POST", "/api/cloudtalk/initiate-call"),
    ("POST", "/api/cloudtalk/sync-agents"),
    ("POST", "/api/contacts"),
    ("POST", "/api/cv-generator/classify-technologies"),
    ("POST", "/api/cv-generator/generate"),
    ("POST", "/api/cv-generator/generate-upload"),
    ("POST", "/api/dynareporter/admin-config/scoring"),
    ("POST", "/api/dynareporter/admin-hof/winner"),
    ("POST", "/api/dynareporter/admin-master-data/clients"),
    ("POST", "/api/dynareporter/admin-master-data/consultants"),
    ("POST", "/api/dynareporter/admin-users/dl-clients"),
    ("POST", "/api/dynareporter/admin-users/employees/{user_id}/active"),
    ("POST", "/api/dynareporter/admin-users/employees/{user_id}/allowed-sections"),
    ("POST", "/api/dynareporter/admin-users/employees/{user_id}/seniority"),
    ("POST", "/api/dynareporter/admin-users/team/sourcer-categories"),
    ("POST", "/api/dynareporter/admin-users/team/tac-dl"),
    ("POST", "/api/email-templates/{template_id}/preview"),
    ("POST", "/api/email-templates/{template_id}/send"),
    ("POST", "/api/emails/preview"),
    ("POST", "/api/emails/send"),
    ("POST", "/api/interview-questions"),
    ("POST", "/api/interview-questions/{question_id}/rate"),
    ("POST", "/api/invite-links/{token}/revoke"),
    ("POST", "/api/jobs/{job_id}/cc-override"),
    ("POST", "/api/jobs/{job_id}/chat/messages"),
    ("POST", "/api/jobs/{job_id}/chat/messages/{msg_id}/reactions"),
    ("POST", "/api/jobs/{job_id}/claim"),
    ("POST", "/api/jobs/{job_id}/classify-cc"),
    ("POST", "/api/jobs/{job_id}/collaborators"),
    ("POST", "/api/jobs/{job_id}/postings"),
    ("POST", "/api/jobs/{job_id}/publish-all"),
    ("POST", "/api/jobs/{job_id}/questions/pin"),
    ("POST", "/api/match-history"),
    ("POST", "/api/microsoft365/free-busy"),
    ("POST", "/api/microsoft365/sync/trigger"),
    ("POST", "/api/prep-kit/generate"),
    ("POST", "/api/saved-searches"),
    ("POST", "/api/saved-searches/{search_id}/viewed"),
    ("POST", "/api/user-email-templates"),
    ("POST", "/api/users/me/onboarding"),
    ("PUT", "/api/candidates/{candidate_id}/chat/read"),
    ("PUT", "/api/contacts/{contact_id}"),
    ("PUT", "/api/interview-questions/{question_id}"),
    ("PUT", "/api/jobs/{job_id}/chat/read"),
    ("PUT", "/api/notifications/read-all"),
    ("PUT", "/api/notifications/{notification_id}/read"),
    ("PUT", "/api/postings/{posting_id}"),
    ("PUT", "/api/user-email-templates/{template_id}"),
}


def test_no_new_bare_authenticated_routes() -> None:
    """A new route may not rely on authentication alone.

    Both flavours are held to the baseline. `bare_in_body` is not a security
    hole, but it must not GROW either: every new imperative check is another
    place where the next handler in that file starts unprotected by default,
    which is the mechanism this whole contract exists to stop.
    """
    routes = _routes()
    bare = {(m, p) for m, p, c in routes if c.startswith("bare")}
    new = bare - _BARE_BASELINE
    if not new:
        return

    unchecked = {(m, p) for m, p, c in routes if c == "bare_unchecked"} & new
    in_body = new - unchecked
    lines = []
    if unchecked:
        lines.append(
            f"  NO AUTHORISATION AT ALL ({len(unchecked)}) — a read-only `user` can call these:"
        )
        lines += [f"    {m} {p}" for m, p in sorted(unchecked)]
    if in_body:
        lines.append(
            f"  authorised only by an in-body check ({len(in_body)}) — works, but is"
            " invisible to OpenAPI and unenforced for the next handler added:"
        )
        lines += [f"    {m} {p}" for m, p in sorted(in_body)]

    raise AssertionError(
        f"{len(new)} route(s) are authenticated but not gated by a dependency, and "
        "are not in the baseline. Give each a resource gate (CandidatePIIAccess / "
        "ClientAccess / require_financial_access / AdminUser / require_capability), "
        "or add it to _BARE_BASELINE with a justification:\n" + "\n".join(lines)
    )


def test_report_route_authz_inventory() -> None:
    """Always-passing census — its output is how the baseline gets captured.

    Prints counts and the full bare list so a CI run can be read as the
    measurement. Deliberately never fails: its job is to inform, and the
    enforcing assertion lives in the test above.
    """
    routes = _routes()
    counts: dict[str, int] = {}
    for _m, _p, c in routes:
        counts[c] = counts.get(c, 0) + 1

    bare = sorted({(m, p) for m, p, c in routes if c.startswith("bare")})
    print(f"\n=== route authz inventory: {len(routes)} routes ===")
    for name in ("gated", "bare_unchecked", "bare_in_body", "public"):
        print(f"  {name:15s}: {counts.get(name, 0)}")
    print("\n_BARE_BASELINE = {")
    for method, path in bare:
        print(f'    ("{method}", "{path}"),')
    print("}")

    assert routes, "no /api routes were discovered — the walker is broken"
