"""AAD (Azure Active Directory) group membership lookup + role mapping.

Phase 7.2 of the M365 plan (.claude/plans/elegant-percolating-thimble.md).

Used by the SSO login flow (``app.api.auth_microsoft.callback``) and the
admin resync endpoint to translate "what AAD groups does this user belong to"
into a NEXUS ``UserRole``.

The login flow has a fresh ``access_token`` from the OAuth code exchange but
no ``M365Connection`` row yet, so ``fetch_user_groups`` takes a raw token
string rather than a :class:`GraphClient` — it just runs a single Graph
request with httpx and gets out of the way.

The admin endpoint reuses ``map_groups_to_role`` to re-evaluate already-stored
``aad_group_ids`` after an ``AAD_GROUP_ROLE_MAP_JSON`` change, without needing
the user to log in again.
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Phase 7.2 — `/me/memberOf` returns the union of groups + directory roles.
# We pass `$select=id,displayName` to keep the response small (default payload
# includes ~30 fields per row) and rely on `@odata.type` to filter out
# `#microsoft.graph.directoryRole` entries — only groups can grant NEXUS
# roles, not Azure AD admin roles.
# Runda 7 (R7-N5-7): `transitiveMemberOf` — `memberOf` nie zwraca grup
# zagnieżdżonych, choć ta funkcja obiecywała członkostwo przechodnie.
_GRAPH_MEMBEROF_URL = (
    "https://graph.microsoft.com/v1.0/me/transitiveMemberOf?$select=id,displayName"
)
_GRAPH_ORIGIN = "https://graph.microsoft.com/"
# Graph oddaje po 100 pozycji na stronę. Sufit stron chroni logowanie przed
# pętlą; lista niepełna = błąd (logowanie odmawia), nigdy odebranie ról.
_MAX_PAGES = 50
# Hard ceiling on a single Graph call. Same rationale as graph_client._HARD_TIMEOUT_SECONDS:
# a hung Graph endpoint must not block the SSO redirect indefinitely. Login
# UX tolerates ~15s before the browser feels broken, so 10s leaves headroom
# for the response itself.
_GRAPH_TIMEOUT_SECONDS = 10.0


async def fetch_user_groups(access_token: str) -> list[dict]:
    """Fetch transitive AAD group memberships for the token's user.

    Returns a list of ``{"id": "<guid>", "displayName": "..."}`` dicts.
    Only entries whose ``@odata.type`` is ``#microsoft.graph.group`` are kept
    — directory roles (Global Admin, etc.) live in the same collection but
    don't grant NEXUS roles. Pages are followed via ``@odata.nextLink``
    (runda 7 — Teams/M365 memberships easily exceed one 100-row page).

    Raises:
        httpx.HTTPError: network / timeout / unexpected non-200 response.

    Args:
        access_token: Delegated-permission Microsoft Graph token. Must include
            the ``GroupMember.Read.All`` scope — caller is responsible for
            requesting it during OAuth authorize.
    """
    headers = {"Authorization": f"Bearer {access_token}"}
    raw_rows: list[dict] = []
    url: Optional[str] = _GRAPH_MEMBEROF_URL
    async with httpx.AsyncClient(timeout=_GRAPH_TIMEOUT_SECONDS) as client:
        for _page in range(_MAX_PAGES):
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            payload = resp.json() or {}
            raw_rows.extend(payload.get("value") or [])
            # Runda 7 (R7-N5-7): grupa NEXUS na drugiej stronie wyników
            # (ponad 100 członkostw) oznaczała dezaktywację albo niższe role.
            url = payload.get("@odata.nextLink")
            if not url:
                break
            if not str(url).startswith(_GRAPH_ORIGIN):
                raise ValueError("unexpected Graph nextLink origin")
        else:
            raise ValueError("AAD group membership exceeds page limit")
    groups: list[dict] = []
    for row in raw_rows:
        if row.get("@odata.type") != "#microsoft.graph.group":
            continue
        group_id = row.get("id")
        if not group_id:
            continue
        groups.append(
            {
                "id": group_id,
                "displayName": row.get("displayName") or "",
            }
        )
    return groups


def map_groups_to_role(group_ids: list[str], mapping: dict[str, str]) -> Optional[str]:
    """Return the NEXUS role string for the first matching AAD group, or None.

    Priority is determined by ``mapping`` insertion order — Python ``dict``
    preserves insertion order (3.7+), so admins control precedence by ordering
    the JSON keys in ``AAD_GROUP_ROLE_MAP_JSON``. Example: list admin GUID
    before recruiter GUID so a user in both groups gets ``admin``.

    Args:
        group_ids: Flat list of AAD group GUIDs the user belongs to.
        mapping: ``{<group-guid>: <role-string>}`` — typically loaded from
            ``settings.AAD_GROUP_ROLE_MAP_JSON``.

    Returns:
        The role string from the mapping, or ``None`` if no group matched.
        ``None`` means "user has no NEXUS role" → SSO callback must block
        login (don't issue JWT, set ``is_active=false``).
    """
    if not mapping or not group_ids:
        return None
    group_id_set = set(group_ids)
    for group_id, role in mapping.items():
        if group_id in group_id_set:
            return role
    return None


def map_groups_to_roles(group_ids: list[str], mapping: dict[str, str]) -> list[str]:
    """Return every matching NEXUS role string, in ``mapping`` order.

    Multi-role variant of :func:`map_groups_to_role` (migracja 0110). A
    user in both ``NEXUS-DeliveryLeads`` and ``NEXUS-TACs`` gets
    ``["delivery_lead", "tac"]`` (with ``delivery_lead`` first if it
    precedes ``tac`` in ``AAD_GROUP_ROLE_MAP_JSON``).

    The first element is the **primary** role — written to ``users.role``
    for legacy single-role code paths. The full list is written to
    ``users.roles``.

    Args:
        group_ids: Flat list of AAD group GUIDs the user belongs to.
        mapping: ``{<group-guid>: <role-string>}`` from
            ``settings.AAD_GROUP_ROLE_MAP_JSON``.

    Returns:
        Ordered list of unique role strings, or ``[]`` when no group matched.
        Empty list means the SSO callback must block login.
    """
    if not mapping or not group_ids:
        return []
    group_id_set = set(group_ids)
    out: list[str] = []
    for group_id, role in mapping.items():
        if group_id in group_id_set and role not in out:
            out.append(role)
    return out
