"""Uprawnienie „Moduł Finanse” zamiast listy ról admin · Finanse.

To, co admin zaznaczył na ekranie Osoby i role, decyduje o:

* odhaczaniu „Zrobione” w Zmianach w zamówieniach (flaga ``can_check``),
* kwotach w tabeli rok do roku (Head of Recruitment bez uprawnienia dostaje
  ją bez pieniędzy),
* audycie importu portfela klientów i Historii zdarzeń,
* odbiorcach miesięcznego maila zarządu.

Pierwsza część pliku sprawdza reguły na kontach z dołączoną polityką (bez
bazy), druga — przez trasy i pętlę maila (`app_client`; baza testowa jest
wspólna i nieczyszczona, więc asercje dotyczą własnych kont).
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import get_args, get_type_hints

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from starlette.requests import Request

from app.api import insights_board
from app.core import cache as cache_module
from app.core.database import AsyncSessionLocal
from app.core.rate_limit import limiter
from app.core.security import hash_password
from app.models.user import User, UserRole
from app.services import permission_catalog as catalog
from app.tasks import kpi_email_reports as reports
from tests._permission_grants import grant_permissions, role_permission
from tests.test_finance_order_changes import _far_day
from tests.test_insights_board_yoy import BASE_YEAR, YOY_URL, _metric

FM = "finance_module"
FM_LABEL = "Moduł Finanse"


def _assert_names_the_permission(detail: object) -> None:
    assert isinstance(detail, dict), detail
    assert detail["code"] == "permission_denied"
    assert detail["permission"] == FM
    assert detail["label"] == FM_LABEL
    assert FM_LABEL in detail["message"]


# ── Reguły na kontach z dołączoną polityką (bez bazy) ───────────────────────


def _account(role: UserRole, *permissions: str, insights: str = "read") -> User:
    """Konto z polityką jak po resolverze: uprawnienia i sekcje razem."""

    user = User(
        id=930_000 + len(permissions),
        email=f"{role.value}-{uuid.uuid4().hex[:6]}@permissions-finance.test",
        name=role.value,
        role=role,
        roles=[role.value],
        is_active=True,
        profile_completed=True,
    )
    held = catalog.close(permissions)
    user.effective_action_access = {key: "manage" for key in held}
    user.effective_section_access = {
        **catalog.derive_sections(held),
        "insights": insights,
    }
    return user


def test_board_mail_goes_to_holders_of_the_permission_who_read_insights() -> None:
    admin = _account(UserRole.admin, *catalog.KEYS, insights="write")
    finance = _account(UserRole.finance, FM)
    # Uprawnienie nadane osobie spoza domyślnych ról.
    granted = _account(UserRole.recruiter, FM)
    # Rola Finanse z wyłączonym przełącznikiem „Moduł Finanse”.
    switched_off = _account(UserRole.finance, "amounts_view")
    # Raport niesie liczby z Insights — bez odczytu tej sekcji nie wychodzi.
    without_insights = _account(UserRole.finance, FM, insights="none")
    hor = _account(UserRole.head_of_recruitment, insights="write")

    readers = reports._board_readers(
        [admin, finance, granted, switched_off, without_insights, hor]
    )

    assert readers == [admin, finance, granted]


async def test_year_on_year_admits_the_permission_or_the_hor_role() -> None:
    annotation = get_type_hints(insights_board.insights_board_yoy, include_extras=True)[
        "current_user"
    ]
    gate = get_args(annotation)[1].dependency

    for allowed in (
        _account(UserRole.finance, FM),
        _account(UserRole.recruiter, FM),
        # Head of Recruitment wchodzi rolą — kwoty redaguje dopiero trasa.
        _account(UserRole.head_of_recruitment, insights="write"),
    ):
        assert await gate(allowed) is allowed

    for refused in (
        _account(UserRole.recruiter),
        _account(UserRole.finance, "amounts_view"),
    ):
        with pytest.raises(HTTPException) as denied:
            await gate(refused)
        assert denied.value.status_code == 403
        _assert_names_the_permission(denied.value.detail)


async def test_year_on_year_keeps_the_amounts_only_for_holders(monkeypatch) -> None:
    async def compute(_db, years, _today):
        return {
            "years": years,
            "metrics": [
                {"key": "margin_monthly_pln", "unit": "pln"},
                {"key": "placements", "unit": "count"},
            ],
            "component_series": {"margin_monthly_pln": {}, "closed_jobs_total": {}},
        }

    def request() -> Request:
        return Request(
            {
                "type": "http",
                "method": "GET",
                "path": YOY_URL,
                "headers": [],
                "query_string": b"",
                "client": ("127.0.0.1", 1),
            }
        )

    async def read(user: User) -> dict:
        return await insights_board.insights_board_yoy(request(), user, None, None, 3)

    monkeypatch.setattr(insights_board, "compute_board_yoy", compute)
    cache_module._cache.clear()
    limiter_was_enabled = limiter.enabled
    limiter.enabled = False
    try:
        for holder in (
            _account(UserRole.finance, FM),
            _account(UserRole.recruiter, FM),
            _account(UserRole.head_of_recruitment, FM, insights="write"),
        ):
            full = await read(holder)
            assert "money_redacted" not in full
            assert [m["key"] for m in full["metrics"]] == [
                "margin_monthly_pln",
                "placements",
            ]

        # Head of Recruitment wchodzi rolą — bez uprawnienia dostaje tabelę bez kwot.
        redacted = await read(_account(UserRole.head_of_recruitment, insights="write"))
        assert redacted["money_redacted"] is True
        assert [m["key"] for m in redacted["metrics"]] == ["placements"]
        assert set(redacted["component_series"]) == {"closed_jobs_total"}
    finally:
        limiter.enabled = limiter_was_enabled
        # Wynik atrapy nie może zostać w pamięci dla testów przez trasy.
        cache_module._cache.clear()


# ── Przez trasy i pętlę maila (HTTP + baza) ─────────────────────────────────


async def _seed_user(
    app_client: AsyncClient, role: str, *, is_active: bool = True
) -> tuple[dict[str, str], int]:
    unique = uuid.uuid4().hex[:8]
    email = f"perm-fm-{role}-{unique}@example.com"
    password = f"T3st_{unique}!Perm"
    async with AsyncSessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password(password),
            name=f"Perm FM {role} {unique}",
            role=UserRole(role),
            roles=[role],
            is_active=is_active,
            profile_completed=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        user_id = user.id
    if not is_active:
        return {}, user_id
    resp = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}, user_id


def _assert_named_denial(resp) -> None:
    assert resp.status_code == 403, resp.text
    _assert_names_the_permission(resp.json()["detail"])


CHECKS = "/api/finance/order-changes/checks"


def _module_reads(day: date) -> tuple[str, ...]:
    """Odczyty modułu Finanse; pierwszy to Zmiany w zamówieniach (``can_check``)."""

    return (
        f"/api/finance/order-changes?year={day.year}&month={day.month}",
        "/api/admin/client-portfolio/import-runs",
        "/api/settings/event-history",
    )


def _stale_check(day: date) -> dict:
    """„Zrobione” dla pozycji, której nie ma — za bramkami czeka już tylko 409."""

    return {
        "year": day.year,
        "month": day.month,
        "item_key": "entry:999999999",
        "done": True,
    }


async def test_granted_recruiter_works_in_the_finance_module(
    app_client: AsyncClient,
) -> None:
    headers, user_id = await _seed_user(app_client, "recruiter")
    day = _far_day(2097, 2099)
    reads = _module_reads(day)

    for path in reads:
        _assert_named_denial(await app_client.get(path, headers=headers))
    _assert_named_denial(
        await app_client.post(CHECKS, headers=headers, json=_stale_check(day))
    )

    await grant_permissions(user_id, FM)

    for path in reads:
        resp = await app_client.get(path, headers=headers)
        assert resp.status_code == 200, (path, resp.text)
    month = (await app_client.get(reads[0], headers=headers)).json()
    assert month["can_check"] is True
    stale = await app_client.post(CHECKS, headers=headers, json=_stale_check(day))
    assert stale.status_code == 409, stale.text


async def test_finance_role_without_the_permission_is_refused(
    app_client: AsyncClient,
) -> None:
    headers, _ = await _seed_user(app_client, "finance")
    day = _far_day(2097, 2099)
    reads = _module_reads(day)
    yoy = f"{YOY_URL}?end_year={BASE_YEAR}&years=2"

    before = await app_client.get(reads[0], headers=headers)
    assert before.status_code == 200, before.text
    assert before.json()["can_check"] is True

    async with role_permission("finance", FM, granted=False):
        for path in (*reads, yoy):
            _assert_named_denial(await app_client.get(path, headers=headers))
        _assert_named_denial(
            await app_client.post(CHECKS, headers=headers, json=_stale_check(day))
        )

    # Przełącznik wraca — ta sama sesja znowu czyta moduł.
    after = await app_client.get(reads[0], headers=headers)
    assert after.status_code == 200, after.text


async def test_year_on_year_money_follows_the_permission(
    app_client: AsyncClient,
) -> None:
    params = {"end_year": BASE_YEAR, "years": 2}
    hor_headers, hor_id = await _seed_user(app_client, "head_of_recruitment")
    recruiter_headers, recruiter_id = await _seed_user(app_client, "recruiter")

    # Head of Recruitment wchodzi rolą i dostaje tabelę bez pieniędzy.
    redacted = await app_client.get(YOY_URL, headers=hor_headers, params=params)
    assert redacted.status_code == 200, redacted.text
    assert redacted.json()["money_redacted"] is True
    assert not any(m["unit"] == "pln" for m in redacted.json()["metrics"])
    _assert_named_denial(
        await app_client.get(YOY_URL, headers=recruiter_headers, params=params)
    )

    await grant_permissions(hor_id, FM)
    await grant_permissions(recruiter_id, FM)

    for headers in (hor_headers, recruiter_headers):
        full = await app_client.get(YOY_URL, headers=headers, params=params)
        assert full.status_code == 200, full.text
        assert "money_redacted" not in full.json()
        assert _metric(full.json(), "margin_monthly_pln")["series"] is not None


async def test_board_mail_recipients_come_from_the_saved_policy(
    app_client: AsyncClient,
) -> None:
    _, finance_id = await _seed_user(app_client, "finance")
    _, granted_id = await _seed_user(app_client, "recruiter")
    _, hor_id = await _seed_user(app_client, "head_of_recruitment")
    _, recruiter_id = await _seed_user(app_client, "recruiter")
    _, inactive_id = await _seed_user(app_client, "finance", is_active=False)
    await grant_permissions(granted_id, FM)

    async def recipient_ids() -> set[int]:
        async with AsyncSessionLocal() as db:
            return {user.id for user in await reports._board_recipients(db)}

    ids = await recipient_ids()
    assert {finance_id, granted_id} <= ids
    assert not {hor_id, recruiter_id, inactive_id} & ids

    async with role_permission("finance", FM, granted=False):
        ids = await recipient_ids()
        # Rola traci raport, nadanie osobie zostaje.
        assert finance_id not in ids
        assert granted_id in ids
