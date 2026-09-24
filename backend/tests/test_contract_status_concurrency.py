"""F03 (audyt integralności danych, 14.09.2026): równoległa zmiana statusu
kontraktu mogła obejść terminalny ``void``.

Trzy handlery (``update_contract``, ``update_contract_status``,
``void_contract_endpoint``) ładowały kontrakt bez blokady wiersza, a maszyna
stanów (``assert_transition`` / ``revert_contract`` / ``void_contract``) ocenia
``contract.status`` z pamięci. Dwie sesje: pierwsza robi ``void`` i commituje,
druga na starym obiekcie „cofa do szkicu" — jej UPDATE czeka na blokadę
wiersza i po commicie sąsiada przepycha ``active → void → draft``.

Naprawa: ``SELECT … FOR UPDATE`` na wierszu ``contracts`` w tych trzech
zapytaniach. Druga sesja czeka na commit pierwszej, dostaje świeży wiersz
(``void``) i odmawia 409.
"""

from __future__ import annotations

import ast
import asyncio
import pathlib
import uuid
from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.contract import (
    Contract,
    ContractStatus,
    ContractType,
    ContractWorkMode,
)
from app.services.contract_lifecycle import void_contract
from app.core.scheduling import business_today

pytestmark = pytest.mark.asyncio


async def _seed_active_contract(
    status: ContractStatus = ContractStatus.active,
) -> int:
    from app.models.candidate import Candidate
    from app.models.client import Client

    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Race",
            lastname=f"Void{unique}",
            email=f"race-{unique}@example.com",
        )
        cli = Client(name=f"Klient Race {unique}")
        db.add_all([cand, cli])
        await db.flush()
        contract = Contract(
            candidate_id=cand.id,
            client_id=cli.id,
            contract_type=ContractType.b2b,
            status=status,
            start_date=business_today(),
            end_date=business_today() + timedelta(days=90),
            rate_candidate=15000,
            rate_client=20000,
            work_mode=ContractWorkMode.remote,
        )
        db.add(contract)
        await db.commit()
        await db.refresh(contract)
        return contract.id


async def _status_of(contract_id: int) -> ContractStatus:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(Contract.status).where(Contract.id == contract_id)
        )


def _observe_loaded_status(monkeypatch) -> tuple[list[str], asyncio.Event]:
    """Podgląd fazy B: status widziany TUŻ PO załadowaniu kontraktu.

    Wszystkie trzy handlery wołają ``_ensure_delivery_lead_contract_visible``
    zaraz po ``select(Contract)``, więc wrapper widzi dokładnie to, co za
    chwilę oceni maszyna stanów. Bez blokady B dochodzi tu PRZED commitem A
    (widzi ``active``); z blokadą — dopiero po nim (widzi ``void``). Dzięki
    temu test nie zależy od ``sleep``: A commituje, gdy B zgłosi się tutaj
    albo gdy minie limit (czyli B wisi na FOR UPDATE).
    """
    from app.api import contracts as contracts_api

    seen: list[str] = []
    reached = asyncio.Event()
    original = contracts_api._ensure_delivery_lead_contract_visible

    async def _spy(contract, current_user, db):
        seen.append(contract.status.value)
        reached.set()
        return await original(contract, current_user, db)

    monkeypatch.setattr(contracts_api, "_ensure_delivery_lead_contract_visible", _spy)
    return seen, reached


async def _race_against_uncommitted_void(cid: int, request, seen, reached):
    """A: void wykonany (UPDATE), niecommitowany. B: ``request`` równolegle.

    Zwraca odpowiedź B oraz ``voided_at`` zapisane przez A.
    """
    async with AsyncSessionLocal() as session_a:
        contract_a = await session_a.scalar(
            select(Contract).where(Contract.id == cid).with_for_update()
        )
        await void_contract(session_a, contract_a, actor_id=None, reason="wyścig")
        # UPDATE wykonany → wiersz zablokowany do commitu tej sesji.
        await session_a.flush()
        voided_at = contract_a.voided_at

        task = asyncio.create_task(request())
        try:
            # Bez blokady B melduje się natychmiast (ze starym statusem);
            # z blokadą wisi na SELECT … FOR UPDATE i limit mija.
            await asyncio.wait_for(reached.wait(), timeout=1.5)
        except asyncio.TimeoutError:
            pass
        assert not task.done(), "B nie może zakończyć się przed commitem A"
        await session_a.commit()
        resp = await asyncio.wait_for(task, timeout=30)
    return resp, voided_at


async def test_revert_racing_with_void_loses_and_void_stays(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Wyścig na prawdziwym Postgresie: sesja A anuluje (UPDATE wykonany,
    commit jeszcze nie), sesja B (handler HTTP) w tym czasie cofa do szkicu.

    Bez blokady B czyta ``active`` z migawki READ COMMITTED, przechodzi
    ``assert_transition(active → draft)`` i jej UPDATE po commicie A nadpisuje
    ``void`` szkicem (200). Z blokadą B czeka na commit A, widzi ``void``
    i odmawia 409 — ``void`` zostaje.
    """
    cid = await _seed_active_contract()
    seen, reached = _observe_loaded_status(monkeypatch)

    resp, _ = await _race_against_uncommitted_void(
        cid,
        lambda: app_client.patch(
            f"/api/contracts/{cid}/status",
            json={"status": "draft"},
            headers=app_auth_headers,
        ),
        seen,
        reached,
    )

    assert seen == ["void"], f"B oceniał status z pamięci sprzed commitu A: {seen}"
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["from"] == "void"
    assert await _status_of(cid) == ContractStatus.void


async def test_void_racing_with_void_is_refused_not_double_applied(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Dwa równoległe ``/void`` — drugi ma dostać 409, nie drugi stempel."""
    cid = await _seed_active_contract()
    seen, reached = _observe_loaded_status(monkeypatch)

    resp, voided_at = await _race_against_uncommitted_void(
        cid,
        lambda: app_client.post(
            f"/api/contracts/{cid}/void",
            json={"reason": "drugi klik"},
            headers=app_auth_headers,
        ),
        seen,
        reached,
    )

    assert seen == ["void"], f"B oceniał status z pamięci sprzed commitu A: {seen}"
    assert resp.status_code == 409, resp.text
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, cid)
    assert contract.status == ContractStatus.void
    assert contract.voided_at == voided_at, "drugi klik nie może przestemplować"


async def test_patch_racing_with_void_sees_the_committed_void(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """``PATCH /{id}`` (dane, nie status) też ładuje kontrakt pod blokadą —
    inaczej zapis pola w trakcie anulowania oceniałby stary status."""
    cid = await _seed_active_contract()
    seen, reached = _observe_loaded_status(monkeypatch)

    resp, _ = await _race_against_uncommitted_void(
        cid,
        lambda: app_client.patch(
            f"/api/contracts/{cid}",
            json={"project_name": "po anulowaniu"},
            headers=app_auth_headers,
        ),
        seen,
        reached,
    )

    assert seen == ["void"], f"B oceniał status z pamięci sprzed commitu A: {seen}"
    assert resp.status_code in (200, 409), resp.text
    assert await _status_of(cid) == ContractStatus.void


@pytest.mark.parametrize("target", ["draft", "active", "ended"])
async def test_status_change_after_committed_void_is_409(
    app_client: AsyncClient, app_auth_headers: dict, target: str
):
    """Bez wyścigu: zwykły PATCH statusu po anulowaniu = 409, ``void`` zostaje."""
    cid = await _seed_active_contract()
    void = await app_client.post(
        f"/api/contracts/{cid}/void",
        json={"reason": "pytest"},
        headers=app_auth_headers,
    )
    assert void.status_code == 200, void.text

    resp = await app_client.patch(
        f"/api/contracts/{cid}/status",
        json={"status": target},
        headers=app_auth_headers,
    )
    assert resp.status_code == 409, resp.text
    assert await _status_of(cid) == ContractStatus.void


# ── Druga fala (weryfikacja audytu 15.09): pozostałe komendy statusu ─────────


@pytest.mark.parametrize(
    ("seed_status", "method", "suffix", "body"),
    [
        (ContractStatus.active, "post", "reopen", {"reason": "wyścig"}),
        (ContractStatus.draft, "post", "activate", {}),
        (
            ContractStatus.active,
            "post",
            "terminate",
            {"termination_reason": "project_ended"},
        ),
    ],
    ids=["reopen", "activate", "terminate"],
)
async def test_lifecycle_commands_racing_with_void_see_the_committed_void(
    app_client: AsyncClient,
    app_auth_headers: dict,
    monkeypatch,
    seed_status: ContractStatus,
    method: str,
    suffix: str,
    body: dict,
):
    """`/reopen`, `/activate` i `/terminate` ładowały kontrakt bez blokady:
    B czytał status sprzed commitu A i wskrzeszał `void` (odpowiednio na
    `draft`, `active`, `ended`). Z blokadą B czeka, widzi `void` i odmawia."""
    cid = await _seed_active_contract(seed_status)
    seen, reached = _observe_loaded_status(monkeypatch)

    resp, _ = await _race_against_uncommitted_void(
        cid,
        lambda: getattr(app_client, method)(
            f"/api/contracts/{cid}/{suffix}",
            json=body,
            headers=app_auth_headers,
        ),
        seen,
        reached,
    )

    assert seen == ["void"], f"B oceniał status z pamięci sprzed commitu A: {seen}"
    assert resp.status_code == 409, resp.text
    assert await _status_of(cid) == ContractStatus.void


async def _void_now(app_client: AsyncClient, headers: dict, cid: int) -> None:
    resp = await app_client.post(
        f"/api/contracts/{cid}/void", json={"reason": "pytest"}, headers=headers
    )
    assert resp.status_code == 200, resp.text


async def test_terminate_does_not_resurrect_a_void_contract(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Bez wyścigu: „Zakończ współpracę” na unieważnionej umowie liczyło status
    z samej daty i zapisywało `ended` (albo `active` przy przyszłej dacie)."""
    cid = await _seed_active_contract()
    await _void_now(app_client, app_auth_headers, cid)

    for terminated_at in (business_today(), business_today() + timedelta(days=30)):
        resp = await app_client.post(
            f"/api/contracts/{cid}/terminate",
            json={
                "termination_reason": "project_ended",
                "terminated_at": terminated_at.isoformat(),
            },
            headers=app_auth_headers,
        )
        assert resp.status_code == 409, resp.text
        assert resp.json()["detail"]["from"] == "void"

    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, cid)
    assert contract.status == ContractStatus.void
    assert contract.terminated_at is None, "odmowa nie może zostawić śladu zakończenia"


async def test_early_termination_amendment_does_not_resurrect_a_void_contract(
    app_client: AsyncClient, app_auth_headers: dict
):
    cid = await _seed_active_contract()
    await _void_now(app_client, app_auth_headers, cid)
    before = await _end_date_of(cid)

    resp = await app_client.post(
        f"/api/contracts/{cid}/amendments",
        json={
            "amendment_type": "early_termination",
            "effective_date": (business_today() + timedelta(days=10)).isoformat(),
        },
        headers=app_auth_headers,
    )

    assert resp.status_code == 409, resp.text
    assert await _status_of(cid) == ContractStatus.void
    assert await _end_date_of(cid) == before


async def test_future_termination_of_a_draft_does_not_activate_it(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Szkic z przyszłą datą zakończenia dostawał `active` — z pominięciem
    bramki aktywacji. Teraz zostaje szkicem."""
    cid = await _seed_active_contract(ContractStatus.draft)
    future = business_today() + timedelta(days=30)

    resp = await app_client.post(
        f"/api/contracts/{cid}/terminate",
        json={
            "termination_reason": "project_ended",
            "terminated_at": future.isoformat(),
        },
        headers=app_auth_headers,
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "draft"
    assert await _status_of(cid) == ContractStatus.draft

    # Dzień po dacie końca nocny job musi go zakończyć — inaczej szkic
    # z minioną datą i `terminated_at` wisiałby poza „Zakończonymi” na zawsze.
    from sqlalchemy import update

    from app.tasks import contract_alerts

    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Contract)
            .where(Contract.id == cid)
            .values(end_date=business_today() - timedelta(days=1))
        )
        await db.commit()
    async with AsyncSessionLocal() as db:
        await contract_alerts._promote_statuses(db)
        await db.commit()
    assert await _status_of(cid) == ContractStatus.ended


async def test_nightly_job_leaves_untouched_drafts_alone():
    """Szkic bez ręcznego zakończenia z minioną datą NIE jest kończony przez
    job — to nie jest współpraca, którą ktoś zakończył."""
    from sqlalchemy import update

    from app.tasks import contract_alerts

    cid = await _seed_active_contract(ContractStatus.draft)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Contract)
            .where(Contract.id == cid)
            .values(end_date=business_today() - timedelta(days=1))
        )
        await db.commit()
    async with AsyncSessionLocal() as db:
        await contract_alerts._promote_statuses(db)
        await db.commit()
    assert await _status_of(cid) == ContractStatus.draft


async def test_resync_reads_the_status_committed_after_the_object_was_loaded():
    """`resync_contract` blokował wiersz, ale oceniał obiekt z pamięci — zapis
    zamówienia załadowany przed równoległym `void` mógł autoaktywować szkic."""
    from app.services.contract_order_sync import resync_contract

    cid = await _seed_active_contract(ContractStatus.draft)
    async with AsyncSessionLocal() as session_b:
        stale = await session_b.get(Contract, cid)
        assert stale.status == ContractStatus.draft

        async with AsyncSessionLocal() as session_a:
            locked = await session_a.scalar(
                select(Contract).where(Contract.id == cid).with_for_update()
            )
            await void_contract(session_a, locked, actor_id=None, reason="wyścig")
            await session_a.commit()

        await resync_contract(session_b, stale, actor_id=None)
        assert stale.status == ContractStatus.void
        await session_b.commit()

    assert await _status_of(cid) == ContractStatus.void


async def _end_date_of(contract_id: int):
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(Contract.end_date).where(Contract.id == contract_id)
        )


# ── Strażnik źródłowy: zapytania o kontrakt w komendach statusu mają FOR UPDATE ─

_CONTRACTS_API = (
    pathlib.Path(__file__).resolve().parents[1] / "app" / "api" / "contracts.py"
)
_LOCKED_HANDLERS = (
    "update_contract",
    "update_contract_status",
    "void_contract_endpoint",
    "activate_contract",
    "reopen_contract_endpoint",
    "terminate_contract",
    "create_contract_amendment",
    "bulk_mark_ended",
    "bulk_extend_contracts",
)
# Handlery ładujące przez `_load_contract_with_relations` — muszą podać
# `for_update=True`.
_LOCKED_VIA_LOADER = ("finalize_contract_draft",)


def _call_chain(node: ast.AST) -> list[str]:
    """Nazwy metod łańcucha ``select(...).where(...).options(...).with_for_update()``."""
    names: list[str] = []
    while isinstance(node, ast.Call):
        if isinstance(node.func, ast.Attribute):
            names.append(node.func.attr)
            node = node.func.value
        elif isinstance(node.func, ast.Name):
            names.append(node.func.id)
            if node.args and isinstance(node.args[0], ast.Name):
                names.append(f"arg:{node.args[0].id}")
            break
        else:
            break
    return names


def _contract_select_is_locked(func: ast.AsyncFunctionDef) -> bool:
    for node in ast.walk(func):
        chain = _call_chain(node)
        if "select" in chain and "arg:Contract" in chain:
            # Pierwsze zapytanie o kontrakt w handlerze = ładowanie wiersza.
            return "with_for_update" in chain
    return False


@pytest.mark.parametrize("handler", _LOCKED_HANDLERS)
def test_contract_write_handlers_lock_the_row(handler: str):
    """Cofnięcie ``.with_for_update()`` w którymkolwiek z trzech handlerów
    przywraca wyścig — ten test to najtańszy alarm, zanim padnie wyścigowy."""
    tree = ast.parse(_CONTRACTS_API.read_text(encoding="utf-8"))
    funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)}
    assert handler in funcs, f"handler {handler} zniknął z contracts.py"
    assert _contract_select_is_locked(funcs[handler]), (
        f"{handler}: `select(Contract)` bez `.with_for_update()` — maszyna "
        "stanów ocenia status z pamięci, wyścig z `void` wraca"
    )


@pytest.mark.parametrize("handler", _LOCKED_VIA_LOADER)
def test_loader_based_handlers_request_the_lock(handler: str):
    tree = ast.parse(_CONTRACTS_API.read_text(encoding="utf-8"))
    funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)}
    assert handler in funcs, f"handler {handler} zniknął z contracts.py"
    calls = [
        node
        for node in ast.walk(funcs[handler])
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_load_contract_with_relations"
    ]
    assert calls, f"{handler} nie ładuje już kontraktu przez loader"
    assert any(
        kw.arg == "for_update"
        and isinstance(kw.value, ast.Constant)
        and kw.value.value is True
        for kw in calls[0].keywords
    ), f"{handler}: loader bez `for_update=True` — wyścig z `void` wraca"
