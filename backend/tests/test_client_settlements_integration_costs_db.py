"""E5.1 na bazie: koszty integracji ze zgodą DL-a (limit na konsultanta na rok
kalendarzowy) i marża w zł i % dla DL-a swoich klientów. Dane fikcyjne."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import local_now
from app.core.security import hash_password
from app.models.client_settlement import (
    ClientSettlementExtra,
    ClientSettlementRuleSet,
)
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User, UserRole
from app.services.client_settlements import integration_costs, service
from app.services.client_settlements.service import SettlementError
from tests.test_client_settlements_consultant_db import _module, _restore
from tests.test_client_settlements_service_db import (
    ACTOR,
    _cleanup,
    _previous_month,
    _world,
)

pytestmark = pytest.mark.asyncio

PASSWORD = "Rozl_Test!Pass123"


async def _limit(client_id: int, limit: str = "2000", level: str = "warn") -> None:
    async with AsyncSessionLocal() as db:
        found = await db.scalar(
            select(ClientSettlementRuleSet).where(
                ClientSettlementRuleSet.client_id == client_id
            )
        )
        found.rules = {
            **found.rules,
            "cl.integration_costs": {"level": level, "params": {"limit": limit}},
        }
        await db.commit()


async def _user(role: UserRole) -> User:
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"rozl-{role.value}-{suffix}@example.com",
            password_hash=hash_password(PASSWORD),
            name=f"Rozl {role.value} {suffix}",
            role=role,
            roles=[role.value],
            is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


async def _assign(user_id: int, client_id: int) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            DeliveryLeadClientAssignment(
                delivery_lead_user_id=user_id, client_id=client_id, is_head=True
            )
        )
        await db.commit()


async def _drop(client_id: int, users: list[User]) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(ClientSettlementExtra).where(
                ClientSettlementExtra.client_id == client_id
            )
        )
        await db.execute(
            delete(DeliveryLeadClientAssignment).where(
                DeliveryLeadClientAssignment.client_id == client_id
            )
        )
        await db.execute(delete(User).where(User.id.in_([u.id for u in users])))
        await db.commit()
    await _cleanup(client_id)


async def _add(contract_id: int, month: str, amount: str, actor=ACTOR):
    async with AsyncSessionLocal() as db:
        cost = await integration_costs.add(
            db,
            contract_id,
            month,
            amount=Decimal(amount),
            description="Integracja zespołu",
            actor=actor,
        )
        await db.commit()
        return cost.id


async def _decide(cost_id: int, actor: User, approve: bool = True) -> str:
    async with AsyncSessionLocal() as db:
        cost = await integration_costs.decide(
            db, cost_id, approve=approve, actor=actor, now=local_now()
        )
        await db.commit()
        return cost.status


async def test_limit_roku_drugi_koszt_ponad_limit_odmowa() -> None:
    client_id, contract_id, _line = await _world()
    dl = await _user(UserRole.delivery_lead)
    await _assign(dl.id, client_id)
    await _limit(client_id)
    try:
        first = await _add(contract_id, "2026-03", "1500")
        assert await _decide(first, dl) == "approved"
        with pytest.raises(SettlementError) as over:
            await _add(contract_id, "2026-11", "600")
        assert over.value.status == 409
        assert "zostało 500 zł z 2 000 zł" in over.value.message
        # Do limitu równo — przechodzi; czekający koszt też zajmuje limit.
        second = await _add(contract_id, "2026-11", "500")
        async with AsyncSessionLocal() as db:
            pending = await integration_costs.card(db, contract_id, "2026-11")
        assert (pending["usage"]["pending"], pending["usage"]["remaining"]) == (
            "500.00",
            "0.00",
        )
        with pytest.raises(SettlementError):
            await _add(contract_id, "2026-12", "0.01")
        assert await _decide(second, dl) == "approved"
        async with AsyncSessionLocal() as db:
            card = await integration_costs.card(db, contract_id, "2026-11")
        assert card["usage"] == {
            "year": 2026,
            "limit": "2000.00",
            "approved": "2000.00",
            "pending": "0.00",
            "remaining": "0.00",
        }
    finally:
        await _drop(client_id, [dl])


async def test_limit_liczy_rok_kalendarzowy_a_nie_12_miesiecy() -> None:
    client_id, contract_id, _line = await _world()
    dl = await _user(UserRole.delivery_lead)
    await _assign(dl.id, client_id)
    await _limit(client_id)
    try:
        december = await _add(contract_id, "2025-12", "1800")
        assert await _decide(december, dl) == "approved"
        with pytest.raises(SettlementError):
            await _add(contract_id, "2025-12", "300")
        # Styczeń to nowy rok: pełny limit mimo wydatku miesiąc wcześniej.
        january = await _add(contract_id, "2026-01", "2000")
        assert await _decide(january, dl) == "approved"
    finally:
        await _drop(client_id, [dl])


async def test_zgoda_po_obnizeniu_limitu_odmawia() -> None:
    client_id, contract_id, _line = await _world()
    dl = await _user(UserRole.delivery_lead)
    await _assign(dl.id, client_id)
    await _limit(client_id)
    try:
        first = await _add(contract_id, "2026-05", "1200")
        await _limit(client_id, "1000")
        with pytest.raises(SettlementError) as over:
            await _decide(first, dl)
        assert "Ponad limit" in over.value.message
        assert await _decide(first, dl, approve=False) == "rejected"
    finally:
        await _drop(client_id, [dl])


async def test_bez_zgody_dl_klienta_odmowa_i_marza_bez_zmian() -> None:
    client_id, contract_id, _line = await _world()
    finance = await _user(UserRole.finance)
    admin = await _user(UserRole.admin)
    other_dl = await _user(UserRole.delivery_lead)
    dl = await _user(UserRole.delivery_lead)
    await _assign(dl.id, client_id)
    await _limit(client_id)
    month = _previous_month()
    try:
        async with AsyncSessionLocal() as db:
            await service.set_md(
                db,
                contract_id,
                month,
                md_regular=Decimal("10"),
                md_extra=None,
                actor=ACTOR,
            )
            await db.commit()
        cost_id = await _add(contract_id, month, "400", actor=finance)
        for stranger in (finance, admin, other_dl):
            with pytest.raises(SettlementError) as denied:
                await _decide(cost_id, stranger)
            assert denied.value.status == 403
        async with AsyncSessionLocal() as db:
            view = await service.month_view(db, client_id, month, amounts=True)
        row = view["rows"][0]
        # 10 MD × (1100 − 1000): czekający koszt nie obniża marży.
        assert (row["margin"], row["margin_pct"], row["integration_cost"]) == (
            "1000.00",
            "9.1",
            None,
        )
        assert await _decide(cost_id, dl) == "approved"
        async with AsyncSessionLocal() as db:
            view = await service.month_view(db, client_id, month, amounts=True)
            hidden = await service.month_view(db, client_id, month, amounts=False)
        row = view["rows"][0]
        assert (row["margin"], row["margin_pct"], row["integration_cost"]) == (
            "600.00",
            "5.5",
            "400.00",
        )
        assert hidden["rows"][0]["integration_cost"] is None
        assert hidden["rows"][0]["margin"] is None
        async with AsyncSessionLocal() as db:
            seen = await integration_costs.client_month(
                db, client_id, month, amounts=True
            )
            blind = await integration_costs.client_month(
                db, client_id, month, amounts=False
            )
            card = await integration_costs.card(db, contract_id, month, amounts=False)
        assert seen["items"][0]["amount"] == "400.00"
        assert seen["items"][0]["usage"]["approved"] == "400.00"
        # Bez dostępu do kwot klienta (np. TCM): ani kwoty, ani licznika roku.
        assert blind["items"][0]["amount"] is None
        assert blind["items"][0]["usage"] is None and blind["limit"] is None
        assert card["usage"] is None and card["items"][0]["amount"] is None
    finally:
        await _drop(client_id, [finance, admin, other_dl, dl])


async def test_wylaczona_regula_i_zla_kwota_odmawiaja() -> None:
    client_id, contract_id, _line = await _world()
    try:
        with pytest.raises(SettlementError) as off:
            await _add(contract_id, "2026-04", "100")
        assert off.value.status == 422
        await _limit(client_id, "")
        with pytest.raises(SettlementError):
            await _add(contract_id, "2026-04", "0")
        # Pusty limit = bez limitu.
        assert await _add(contract_id, "2026-04", "5000")
    finally:
        await _drop(client_id, [])


async def _login(app_client, user: User) -> dict[str, str]:
    response = await app_client.post(
        "/api/auth/login", json={"email": user.email, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def test_dl_widzi_marze_swojego_klienta_i_rozstrzyga_koszt(app_client) -> None:
    previous = await _module(True)
    client_id, contract_id, _line = await _world()
    dl = await _user(UserRole.delivery_lead)
    other_dl = await _user(UserRole.delivery_lead)
    await _assign(dl.id, client_id)
    await _limit(client_id)
    month = _previous_month()
    try:
        async with AsyncSessionLocal() as db:
            await service.set_md(
                db,
                contract_id,
                month,
                md_regular=Decimal("10"),
                md_extra=None,
                actor=ACTOR,
            )
            await service.accept(db, contract_id, month, actor=ACTOR, now=local_now())
            await db.commit()
        cost_id = await _add(contract_id, month, "400")
        url = f"/api/my-clients/{client_id}/settlements"
        mine = await app_client.get(
            url, params={"month": month}, headers=await _login(app_client, dl)
        )
        assert mine.status_code == 200, mine.text
        body = mine.json()
        assert body["can_see_amounts"] is True and body["can_decide"] is True
        row = body["rows"][0]
        assert (row["net"], row["cost"], row["margin"], row["margin_pct"]) == (
            "11000.00",
            "10000.00",
            "1000.00",
            "9.1",
        )
        assert [i["status"] for i in body["integration"]["items"]] == ["pending"]
        stranger = await app_client.get(
            url, params={"month": month}, headers=await _login(app_client, other_dl)
        )
        assert stranger.status_code == 403
        decided = await app_client.post(
            f"{url}/integration-costs/{cost_id}/approve",
            params={"month": month},
            headers=await _login(app_client, dl),
        )
        assert decided.status_code == 200, decided.text
        row = decided.json()["rows"][0]
        assert (row["integration_cost"], row["margin"], row["margin_pct"]) == (
            "400.00",
            "600.00",
            "5.5",
        )
    finally:
        await _drop(client_id, [dl, other_dl])
        await _restore(previous)


async def test_wydruk_maila_po_rcp_nie_zastepuje_rcp(tmp_path, monkeypatch) -> None:
    """E2.3: PDF z wydrukiem maila dosłany po RCP to dowód zgody, nie RCP."""

    import io

    import openpyxl

    from app.models.consultant_portal import CpDocument
    from app.services import storage_service
    from app.services.consultant_portal import documents
    from tests.test_client_settlements_acceptance_mail import (
        MAIL_PRINTOUT,
        pdf_with_text,
    )
    from tests.test_client_settlements_rcp import _sheet

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    previous = await _module(True)
    client_id, contract_id, _line = await _world()
    month = _previous_month()
    year, mon = (int(x) for x in month.split("-"))
    rows = _sheet([[None, "development", 7, None, None, "EBI", None, "SX03098"]])
    rows[1][2] = rows[1][2].replace(year=year, month=mon, day=1)
    workbook = openpyxl.Workbook()
    for row in rows:
        workbook.active.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    try:
        async with AsyncSessionLocal() as db:
            for content, name in (
                (buffer.getvalue(), "rcp.xlsx"),
                (pdf_with_text(MAIL_PRINTOUT), "akceptacja.pdf"),
            ):
                await documents.store(
                    db,
                    contract_id=contract_id,
                    kind="report",
                    year=year,
                    month=mon,
                    content=content,
                    file_name=name,
                    channel="portal",
                    now=local_now(),
                )
            await db.commit()
            s = await service._settlement(db, contract_id, month)
            report = await db.get(CpDocument, s.report_document_id)
        assert report.file_name == "rcp.xlsx"
        assert s.md_source == "rcp" and s.md_regular == Decimal("7.000")
    finally:
        await _drop(client_id, [])
        await _restore(previous)
