"""Audyt 24.09.2026, pakiet C: sprawy offboardingu MD, wyczerpanie, import MD.

Każdy test odtwarza jedno znalezisko (H6–H9, M8, M12, M13, U14): na kodzie
sprzed poprawki pada, po niej przechodzi. Nazwiska i numery są zmyślone,
daty liczone od ``business_today()``.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.scheduling import business_today

pytestmark = pytest.mark.asyncio


def _prev_period() -> str:
    first = business_today().replace(day=1)
    return (first - timedelta(days=1)).strftime("%Y-%m")


async def _admin_id() -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.user import User

    async with AsyncSessionLocal() as db:
        return await db.scalar(select(User.id).order_by(User.id).limit(1))


async def _seed_case_alert(*, case_id: int, client_id: int, group_id: int) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.dl_alert import ALERT_MD_CONSULTANT_ENDED, DlAlert

    user_id = await _admin_id()
    async with AsyncSessionLocal() as db:
        alert = DlAlert(
            alert_type=ALERT_MD_CONSULTANT_ENDED,
            user_id=user_id,
            client_id=client_id,
            order_group_id=group_id,
            offboarding_case_id=case_id,
            title="Decyzja MD po zakończeniu współpracy",
            message="Decyzja MD po zakończeniu współpracy",
            dedupe_key=f"test-pack-c-{uuid.uuid4().hex}",
            event_key=f"{ALERT_MD_CONSULTANT_ENDED}:case:{case_id}:{user_id}",
        )
        db.add(alert)
        await db.commit()
        return alert.id


async def _alert_status(alert_id: int) -> str:
    from app.core.database import AsyncSessionLocal
    from app.models.dl_alert import DlAlert

    async with AsyncSessionLocal() as db:
        return (await db.get(DlAlert, alert_id)).status


async def _case(case_id: int):
    from app.core.database import AsyncSessionLocal
    from app.models.client_order_offboarding import ClientOrderOffboardingCase

    async with AsyncSessionLocal() as db:
        return await db.get(ClientOrderOffboardingCase, case_id)


async def _event_descriptions(app_client, headers, client_id, group_id) -> str:
    events = await app_client.get(
        f"/api/clients/{client_id}/order-groups/{group_id}/events",
        headers=headers,
    )
    assert events.status_code == 200, events.text
    return " | ".join(e["description"] for e in events.json()["events"])


# ── H8: decyzja człowieka nie zamyka sprawy „automatycznie” ────────────────


async def test_dl_transfer_decision_is_not_auto_closed_as_used_up(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from tests.test_order_line_takeover import _add_recipient, _enable_multi, _seed

    seed = await _seed()
    _enable_multi(monkeypatch, seed["client_id"])
    recipient = await _add_recipient(seed)

    resp = await app_client.post(
        f"/api/clients/{seed['client_id']}/order-groups/{seed['group_id']}"
        f"/offboarding-cases/{seed['case_id']}/resolve",
        json={
            "action": "transfer",
            "target_order_id": recipient,
            "md_transfer_method": "one_to_one",
            "expected_version": 1,
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text

    case = await _case(seed["case_id"])
    assert case.resolution == "transfer"
    # Migawka zostaje pulą, o której zdecydował człowiek — nie 0.
    assert Decimal(str(case.remaining_md_snapshot)) == Decimal("187")
    assert not (case.resolution_payload or {}).get("automatic")
    history = await _event_descriptions(
        app_client, app_auth_headers, seed["client_id"], seed["group_id"]
    )
    assert "wykorzystana w całości (0 MD)" not in history, history


async def test_takeover_closes_the_dl_alert_and_is_not_auto_closed(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from tests.test_order_line_takeover import _enable_multi, _seed, _takeover_url

    seed = await _seed()
    _enable_multi(monkeypatch, seed["client_id"])
    alert_id = await _seed_case_alert(
        case_id=seed["case_id"], client_id=seed["client_id"], group_id=seed["group_id"]
    )

    resp = await app_client.post(
        _takeover_url(seed),
        json={
            "contract_id": seed["kamila_contract_id"],
            "departing_order_id": seed["line_id"],
            "entry_date": (seed["departure"] + timedelta(days=1)).isoformat(),
            "rate_cost": 680,
            "rate_revenue": 800,
            "expected_case_version": 1,
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text

    # Przejęcie rozstrzyga sprawę — alert DL jest obsłużony, nie wisi dalej.
    assert await _alert_status(alert_id) == "handled"
    case = await _case(seed["case_id"])
    assert case.resolution == "transfer"
    assert Decimal(str(case.remaining_md_snapshot)) == Decimal("187")
    history = await _event_descriptions(
        app_client, app_auth_headers, seed["client_id"], seed["group_id"]
    )
    assert "wykorzystana w całości (0 MD)" not in history, history


async def test_import_that_uses_up_the_pool_closes_the_case_and_its_alert(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Automatyczne zamknięcie (import wyzerował pulę) zdejmuje też kartę DL."""
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder
    from app.services.client_order_lines import upsert_consumption
    from tests.test_order_line_takeover import _enable_multi, _seed

    seed = await _seed()
    _enable_multi(monkeypatch, seed["client_id"])
    alert_id = await _seed_case_alert(
        case_id=seed["case_id"], client_id=seed["client_id"], group_id=seed["group_id"]
    )
    async with AsyncSessionLocal() as db:
        line = await db.get(ClientOrder, seed["line_id"])
        await upsert_consumption(
            db,
            order=line,
            period_month=seed["departure"].strftime("%Y-%m"),
            md_reported=Decimal("187"),
        )
        await db.commit()

    case = await _case(seed["case_id"])
    assert case.status == "resolved"
    assert (case.resolution_payload or {}).get("automatic") is True
    assert await _alert_status(alert_id) == "resolved"


# ── H9: wyczerpanie zamyka zamówienie z dniem przeliczenia ─────────────────


async def test_exhausted_by_a_late_report_the_order_still_settles_this_month(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Raport za poprzedni miesiąc wyczerpał pulę — data zakończenia to dzień
    przeliczenia, więc import za bieżący miesiąc nadal znajduje linię."""
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder
    from app.services.client_order_lines import (
        md_lines_settling_in_month,
        upsert_consumption,
    )
    from tests.test_bik_md_exhaustion_lifecycle import _bik_group, _group_state

    _client_id, group = await _bik_group(app_client, app_auth_headers, monkeypatch)
    async with AsyncSessionLocal() as db:
        for line in group["lines"]:
            order = await db.get(ClientOrder, line["id"])
            await upsert_consumption(
                db,
                order=order,
                period_month=_prev_period(),
                md_reported=Decimal(str(line["md_total"])),
            )
        await db.commit()

    state, _ = await _group_state(group["id"])
    assert state.status == "completed"
    assert state.closure_date == business_today()

    async with AsyncSessionLocal() as db:
        settling = await md_lines_settling_in_month(
            db, business_today().strftime("%Y-%m")
        )
    line_ids = {line["id"] for line in group["lines"]}
    assert line_ids <= {match.order.id for match in settling}


# ── M8: sprawa zamknięta automatycznie nie blokuje „Cofnij zakończenie” ────


async def test_auto_closed_case_does_not_block_termination_reversal(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder
    from app.services.client_order_lines import upsert_consumption
    from tests.test_contract_termination_reversal import (
        _enable_multi,
        _ended_on,
        _pending_cases,
        _seed_active_md_consultant,
        _terminate,
    )

    seed = await _seed_active_md_consultant()
    _enable_multi(monkeypatch, seed["client_id"])
    await _terminate(app_client, app_auth_headers, seed["contract_id"])
    [case_id] = await _pending_cases(seed["contract_id"])

    # Zaległy raport za miesiąc zejścia zjada resztę puli (259 MD) — sprawa
    # zamyka się sama jako „usunięto 0 MD”.
    async with AsyncSessionLocal() as db:
        line = await db.get(ClientOrder, seed["line_id"])
        await upsert_consumption(
            db,
            order=line,
            period_month=_ended_on().strftime("%Y-%m"),
            md_reported=Decimal("259"),
        )
        await db.commit()
    case = await _case(case_id)
    assert case.status == "resolved"
    assert case.resolution_payload.get("automatic") is True

    preview = await app_client.get(
        f"/api/contracts/{seed['contract_id']}/termination-reversal",
        headers=app_auth_headers,
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert [b["code"] for b in body["blockers"]] == [], body["blockers"]
    assert body["decision_cases_removed"] == 1

    done = await app_client.post(
        f"/api/contracts/{seed['contract_id']}/termination-reversal",
        headers=app_auth_headers,
    )
    assert done.status_code == 200, done.text
    assert await _pending_cases(seed["contract_id"]) == []
