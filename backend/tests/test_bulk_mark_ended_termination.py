"""Masowe „Oznacz zakończone" zapisuje powód i datę — jak „Zakończ współpracę".

Do 09.2026 bulk szedł przez ``_apply_contract_status_change(..., ended)``, które
ŚWIADOMIE nie dotyka ``terminated_at``/``termination_reason`` (to reguła listy
rozwijanej statusu w rejestrze, nie wypowiedzenia). Skutek: umowa zakończona
zbiorczo nie miała powodu w analityce odejść, nie pokazywała karty „Zakończenie
współpracy" na szczegółach, nie dostawała aneksu ``early_termination`` przy
skróceniu, a datą końca zawsze była data kliknięcia.

Ticket rozstrzygnął, że przycisk znaczy faktyczny koniec projektu, więc obie
dyspozycje dzielą teraz jeden helper (``_apply_termination_to_contract``).
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract, ContractStatus, ContractTerminationReason
from app.models.contract_amendment import ContractAmendment, ContractAmendmentType
from app.core.scheduling import business_today

pytestmark = pytest.mark.asyncio

TODAY = business_today()
WHEN = TODAY - timedelta(days=3)


async def _seed(
    *,
    second_status: ContractStatus = ContractStatus.active,
    lessons: str | None = None,
) -> tuple[int, int, list[int]]:
    """Klient + kandydat + dwie umowy (druga o zadanym statusie) + zamówienie."""
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Bulk End Client {suffix}")
        cand = Candidate(name=f"Bulk {suffix}", lastname=f"End{suffix}")
        db.add_all([client, cand])
        await db.flush()
        first = Contract(
            candidate_id=cand.id,
            client_id=client.id,
            start_date=TODAY - timedelta(days=200),
            end_date=TODAY + timedelta(days=90),
            rate_client=15000,
            rate_candidate=12000,
            status=ContractStatus.active,
        )
        second = Contract(
            candidate_id=cand.id,
            client_id=client.id,
            start_date=TODAY - timedelta(days=150),
            end_date=TODAY + timedelta(days=60),
            rate_client=14000,
            rate_candidate=11000,
            status=second_status,
            termination_lessons=lessons,
        )
        db.add_all([first, second])
        await db.flush()
        db.add(
            ClientOrder(
                client_id=client.id,
                contract_id=first.id,
                title=f"zamowienie-{suffix}",
                status=ClientOrderStatus.active,
                start_date=TODAY - timedelta(days=30),
                end_date=TODAY + timedelta(days=90),
            )
        )
        ids = (client.id, cand.id, [first.id, second.id])
        await db.commit()
        return ids


async def _cleanup(client_id: int, cand_id: int, contract_ids: list[int]) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            Activity.__table__.delete().where(
                Activity.entity_type == "contract",
                Activity.entity_id.in_(contract_ids),
            )
        )
        await db.execute(
            ContractAmendment.__table__.delete().where(
                ContractAmendment.contract_id.in_(contract_ids)
            )
        )
        await db.execute(
            ClientOrder.__table__.delete().where(ClientOrder.client_id == client_id)
        )
        await db.execute(
            Contract.__table__.delete().where(Contract.client_id == client_id)
        )
        await db.execute(Client.__table__.delete().where(Client.id == client_id))
        await db.execute(Candidate.__table__.delete().where(Candidate.id == cand_id))
        await db.commit()


async def _contracts(ids: list[int]) -> dict[int, Contract]:
    async with AsyncSessionLocal() as db:
        rows = (
            (await db.execute(select(Contract).where(Contract.id.in_(ids))))
            .scalars()
            .all()
        )
        return {c.id: c for c in rows}


async def _activities(contract_id: int, action: str) -> list[Activity]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.execute(
                    select(Activity).where(
                        Activity.entity_type == "contract",
                        Activity.entity_id == contract_id,
                        Activity.action == action,
                    )
                )
            )
            .scalars()
            .all()
        )


def _url(ids: list[int]) -> str:
    return "/api/contracts/bulk-mark-ended?" + "&".join(f"ids={i}" for i in ids)


async def test_bulk_writes_reason_and_date_on_every_selected_contract(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    client_id, cand_id, ids = await _seed()
    try:
        resp = await app_client.post(
            _url(ids),
            json={
                "termination_reason": "client_budget_cut",
                "terminated_at": WHEN.isoformat(),
            },
            headers=app_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"requested": 2, "changed": 2}

        rows = await _contracts(ids)
        for contract_id in ids:
            contract = rows[contract_id]
            # Sedno ticketu: powód i data są ZAPISANE, nie tylko status.
            assert contract.termination_reason == (
                ContractTerminationReason.client_budget_cut
            )
            assert contract.terminated_at == WHEN
            assert contract.end_date == WHEN
            assert contract.status == ContractStatus.ended

        # Ten sam offboarding zamówień co przy pojedynczym wypowiedzeniu.
        async with AsyncSessionLocal() as db:
            order = await db.scalar(
                select(ClientOrder).where(ClientOrder.contract_id == ids[0])
            )
        assert order is not None
        assert order.end_date == WHEN
        assert order.status == ClientOrderStatus.completed
    finally:
        await _cleanup(client_id, cand_id, ids)


async def test_audit_entry_keeps_its_action_but_now_carries_reason_and_date(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """`bulk_marked_ended` ma etykiety w logu admina i na osi czasu — zostaje.

    Zmienia się ładunek: do 09.2026 wpis był pusty, więc z audytu nie dało się
    odczytać, z jakim powodem i na jaki dzień zakończono współpracę.
    """
    client_id, cand_id, ids = await _seed()
    try:
        resp = await app_client.post(
            _url(ids),
            json={
                "termination_reason": "project_ended",
                "terminated_at": WHEN.isoformat(),
            },
            headers=app_auth_headers,
        )
        assert resp.status_code == 200, resp.text

        entries = await _activities(ids[0], "bulk_marked_ended")
        assert len(entries) == 1
        details = entries[0].details or {}
        assert details["termination_reason"] == "project_ended"
        assert details["terminated_at"] == WHEN.isoformat()
        assert details["early"] is True
        # Jeden wpis na kontrakt, nie dwa: helper nie dokłada `terminated`.
        assert await _activities(ids[0], "terminated") == []
    finally:
        await _cleanup(client_id, cand_id, ids)


async def test_shortening_a_contract_records_the_early_termination_amendment(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    client_id, cand_id, ids = await _seed()
    try:
        resp = await app_client.post(
            _url(ids),
            json={
                "termination_reason": "consultant_resigned",
                "terminated_at": WHEN.isoformat(),
            },
            headers=app_auth_headers,
        )
        assert resp.status_code == 200, resp.text

        async with AsyncSessionLocal() as db:
            amendments = (
                (
                    await db.execute(
                        select(ContractAmendment).where(
                            ContractAmendment.contract_id == ids[0]
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert [a.amendment_type for a in amendments] == [
            ContractAmendmentType.early_termination
        ]
        assert amendments[0].effective_date == WHEN
        assert amendments[0].reason == "consultant_resigned"
    finally:
        await _cleanup(client_id, cand_id, ids)


async def test_replayed_disposition_does_not_double_the_audit_trail(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    client_id, cand_id, ids = await _seed()
    payload = {
        "termination_reason": "mutual_agreement",
        "terminated_at": WHEN.isoformat(),
    }
    try:
        first = await app_client.post(_url(ids), json=payload, headers=app_auth_headers)
        assert first.status_code == 200, first.text
        replay = await app_client.post(
            _url(ids), json=payload, headers=app_auth_headers
        )
        assert replay.status_code == 200, replay.text

        async with AsyncSessionLocal() as db:
            count = await db.scalar(
                select(func.count())
                .select_from(Activity)
                .where(
                    Activity.entity_type == "contract",
                    Activity.entity_id == ids[0],
                    Activity.action == "bulk_marked_ended",
                )
            )
        assert count == 1
    finally:
        await _cleanup(client_id, cand_id, ids)


async def test_bulk_does_not_wipe_lessons_written_by_a_single_termination(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """Okno zbiorcze nie pyta o wnioski TAC, więc nie ma czym ich zastąpić."""
    client_id, cand_id, ids = await _seed(lessons="Klient — brak budżetu na Q4.")
    try:
        resp = await app_client.post(
            _url(ids),
            json={
                "termination_reason": "client_budget_cut",
                "terminated_at": WHEN.isoformat(),
            },
            headers=app_auth_headers,
        )
        assert resp.status_code == 200, resp.text

        rows = await _contracts(ids)
        assert rows[ids[1]].termination_lessons == "Klient — brak budżetu na Q4."
    finally:
        await _cleanup(client_id, cand_id, ids)


@pytest.mark.parametrize(
    "payload",
    [
        {"terminated_at": WHEN.isoformat()},
        {"termination_reason": "project_ended"},
        {},
    ],
    ids=["bez-powodu", "bez-daty", "puste"],
)
async def test_both_fields_are_required_server_side(
    app_client: AsyncClient, app_auth_headers: dict[str, str], payload: dict
):
    """Kryterium akceptacji: bez obu pól operacji nie da się zatwierdzić.

    Data jest wymagana świadomie — ``/terminate`` podstawia „dzisiaj", gdy pole
    jest puste, a tu ta sama wartość wjeżdża w N umów naraz.
    """
    client_id, cand_id, ids = await _seed()
    try:
        resp = await app_client.post(_url(ids), json=payload, headers=app_auth_headers)
        assert resp.status_code == 422, resp.text

        rows = await _contracts(ids)
        assert all(rows[i].termination_reason is None for i in ids)
        assert all(rows[i].status == ContractStatus.active for i in ids)
    finally:
        await _cleanup(client_id, cand_id, ids)


async def test_a_void_contract_in_the_selection_refuses_the_whole_batch(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """``void`` jest terminalny — partia jest atomowa, nie „częściowo udana".

    Cicha zmiana części zaznaczenia byłaby gorsza niż odmowa: nikt nie wie
    wtedy, których wierszy dyspozycja nie objęła.
    """
    client_id, cand_id, ids = await _seed(second_status=ContractStatus.void)
    try:
        resp = await app_client.post(
            _url(ids),
            json={
                "termination_reason": "project_ended",
                "terminated_at": WHEN.isoformat(),
            },
            headers=app_auth_headers,
        )
        assert resp.status_code == 409, resp.text

        rows = await _contracts(ids)
        # Pierwsza umowa (legalna do zakończenia) też została nietknięta.
        assert rows[ids[0]].termination_reason is None
        assert rows[ids[0]].terminated_at is None
        assert rows[ids[0]].status == ContractStatus.active
        assert await _activities(ids[0], "bulk_marked_ended") == []
    finally:
        await _cleanup(client_id, cand_id, ids)
