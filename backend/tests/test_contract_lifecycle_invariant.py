"""Contract lifecycle invariant — P1-CONTRACT-01.

Locks the single guarded state machine (``app.services.contract_lifecycle``):

* activation depends only on operational contract fields, never on an
  agreement or qualified-signature state;
* manual create, PATCH and ``/activate`` share that same rule, while
  ``ready_for_signature``/``void`` stay exclusive to lifecycle routes;
* finalizing an unsigned HTML draft ends at ``ready_for_signature`` (never
  ``active``), and emits no ``contract_signed`` side effect;
* a QES lane with ``DSS_VALIDATION_URL`` unset — or a timed-out / INDETERMINATE
  DSS verdict — does NOT complete the document or advance the pipeline;
* DELETE usuwa kontrakt w każdym statusie (decyzja 2026-08-25 — błędny/
  zdublowany wpis musi dać się skasować); blokują wyłącznie PODPISANE dowody
  (ukończony podpis kwalifikowany / umowa B2B ``signed_both``) → 409 + oferta
  ``/void`` (kasowanie zniszczyłoby dowód);
* the legitimate revert flow works via the audited ``/reopen`` transition.

Unit tests exercise the lifecycle service directly; HTTP tests drive the real
endpoints through the in-process ``app_client``.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.contract import (
    Contract,
    ContractStatus,
    ContractType,
    ContractWorkMode,
)
from app.models.document_signature import DocumentSignature, SignatureStatus
from app.services import contract_lifecycle as lifecycle
from app.services.signing import sender as signing_sender
from app.services.signing.provider import ValidationReport
from fastapi import HTTPException
from sqlalchemy import select


# ── Seed helpers ─────────────────────────────────────────────────────────────


async def _seed_user() -> int:
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        u = User(
            email=f"lifecycle-{unique}@example.com",
            password_hash=hash_password("x"),
            name="Lifecycle Sender",
            role=UserRole.admin,
            is_active=True,
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u.id


async def _seed_candidate_and_client() -> tuple[int, int]:
    from app.models.candidate import Candidate
    from app.models.client import Client

    unique = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Life",
            lastname=f"Cycle{unique}",
            email=f"life-{unique}@example.com",
        )
        cli = Client(name=f"Klient LC {unique}")
        db.add_all([cand, cli])
        await db.commit()
        await db.refresh(cand)
        await db.refresh(cli)
        return cand.id, cli.id


async def _seed_contract(
    *,
    status: ContractStatus = ContractStatus.draft,
    complete: bool = True,
    draft_html: str | None = None,
) -> int:
    cand_id, cli_id = await _seed_candidate_and_client()
    async with AsyncSessionLocal() as db:
        kwargs: dict = {
            "candidate_id": cand_id,
            "client_id": cli_id,
            "contract_type": ContractType.b2b,
            "status": status,
        }
        if complete:
            kwargs.update(
                start_date=date.today(),
                end_date=date.today() + timedelta(days=90),
                rate_candidate=15000,
                rate_client=20000,
                work_mode=ContractWorkMode.remote,
            )
        if draft_html is not None:
            kwargs["draft_content_html"] = draft_html
        contract = Contract(**kwargs)
        db.add(contract)
        await db.commit()
        await db.refresh(contract)
        return contract.id


async def _seed_signature(
    contract_id: int, sender_id: int, status: SignatureStatus
) -> int:
    async with AsyncSessionLocal() as db:
        sig = DocumentSignature(
            contract_id=contract_id,
            provider="upload_validate",
            signature_type="QES",
            status=status,
            sender_user_id=sender_id,
            signer_email="signer@example.com",
            signer_first_name="Jan",
            signer_last_name="Podpisujacy",
        )
        db.add(sig)
        await db.commit()
        await db.refresh(sig)
        return sig.id


# ── State machine ────────────────────────────────────────────────────────────


def test_state_machine_allows_and_forbids() -> None:
    # Legal edges
    lifecycle.assert_transition(ContractStatus.draft, ContractStatus.active)
    lifecycle.assert_transition(
        ContractStatus.draft, ContractStatus.ready_for_signature
    )
    lifecycle.assert_transition(
        ContractStatus.ready_for_signature, ContractStatus.active
    )
    lifecycle.assert_transition(ContractStatus.active, ContractStatus.void)
    lifecycle.assert_transition(ContractStatus.ended, ContractStatus.draft)
    # Illegal: void is terminal
    with pytest.raises(HTTPException) as exc:
        lifecycle.assert_transition(ContractStatus.void, ContractStatus.active)
    assert exc.value.status_code == 409


def test_signed_delete_blocker_advertises_admin_confirmation_contract() -> None:
    contract = SimpleNamespace(id=563, status=ContractStatus.active)
    blocked = lifecycle.ContractHardDeleteBlocked(contract, "signed_generated_contract")
    assert blocked.status_code == 409
    assert blocked.detail["requires_admin_confirmation"] is True
    assert blocked.detail["admin_only"] is True
    assert blocked.detail["force_delete_endpoint"] == (
        "/api/contracts/563/force-delete-signed"
    )
    assert blocked.detail["confirmation_options"] == [
        "contractor_name",
        "contract_id",
    ]


@pytest.mark.asyncio
async def test_activate_is_operational_only_and_work_mode_is_optional() -> None:
    """Pure service regression: activation performs no signature DB lookup."""

    class _AuditOnlyDB:
        def __init__(self) -> None:
            self.added: list[object] = []

        def add(self, row: object) -> None:
            self.added.append(row)

    contract = Contract(
        id=900563,
        status=ContractStatus.draft,
        start_date=date.today(),
        rate_candidate=150,
        rate_client=200,
        contract_type=ContractType.b2b,
        work_mode=None,
    )
    db = _AuditOnlyDB()

    await lifecycle.activate_contract(db, contract, actor_id=123)  # type: ignore[arg-type]

    assert contract.status == ContractStatus.active
    assert [row.action for row in db.added] == ["contract_activated"]


@pytest.mark.asyncio
async def test_auto_activate_complete_draft_including_future_start() -> None:
    """Implicit readiness uses the guarded transition, also for future starts."""

    class _AuditOnlyDB:
        def __init__(self) -> None:
            self.added: list[object] = []

        def add(self, row: object) -> None:
            self.added.append(row)

    contract = Contract(
        id=900564,
        status=ContractStatus.draft,
        start_date=date.today() + timedelta(days=30),
        rate_candidate=150,
        rate_client=200,
        contract_type=ContractType.b2b,
    )
    db = _AuditOnlyDB()

    changed = await lifecycle.auto_activate_complete_draft(
        db, contract, actor_id=123, status_explicit=False  # type: ignore[arg-type]
    )

    assert changed is True
    assert contract.status == ContractStatus.active
    assert [row.action for row in db.added] == ["contract_activated"]


@pytest.mark.asyncio
async def test_auto_activate_complete_draft_respects_explicit_status() -> None:
    """A complete record explicitly saved as Draft remains a Draft."""

    contract = Contract(
        id=900565,
        status=ContractStatus.draft,
        start_date=date.today(),
        rate_candidate=150,
        rate_client=200,
        contract_type=ContractType.b2b,
    )
    db = SimpleNamespace(add=lambda _row: None)

    changed = await lifecycle.auto_activate_complete_draft(
        db, contract, actor_id=123, status_explicit=True  # type: ignore[arg-type]
    )

    assert changed is False
    assert contract.status == ContractStatus.draft


@pytest.mark.asyncio
@pytest.mark.parametrize("confirmation", ["563", "#563", "  #563  "])
async def test_signed_delete_confirmation_accepts_exact_contract_number(
    confirmation,
) -> None:
    contract = SimpleNamespace(id=563, candidate_id=None)
    method = await lifecycle._signed_delete_confirmation_method(  # noqa: SLF001
        None, contract, confirmation
    )
    assert method == "contract_id"


@pytest.mark.asyncio
async def test_signed_delete_confirmation_name_is_whitespace_casefold_not_fuzzy() -> (
    None
):
    class _NameResult:
        def one_or_none(self):
            return SimpleNamespace(name="Agnieszka", lastname="Żurawiak")

    class _NameDB:
        async def execute(self, _query):
            return _NameResult()

    contract = SimpleNamespace(id=563, candidate_id=77)
    db = _NameDB()
    assert (
        await lifecycle._signed_delete_confirmation_method(  # noqa: SLF001
            db, contract, "  AGNIESZKA   ŻURAWIAK  "
        )
        == "contractor_name"
    )
    assert (
        await lifecycle._signed_delete_confirmation_method(  # noqa: SLF001
            db, contract, "Agnieszka Zurawiak"
        )
        is None
    )


# ── Activation invariant (service) ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_activate_ignores_inflight_signature() -> None:
    """An unverifiable/in-flight signature cannot block operational activation."""
    uid = await _seed_user()
    cid = await _seed_contract(status=ContractStatus.draft, complete=True)
    await _seed_signature(cid, uid, SignatureStatus.sent)

    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, cid)
        await lifecycle.activate_contract(db, contract, actor_id=uid)
        await db.commit()
        assert contract.status == ContractStatus.active


@pytest.mark.asyncio
async def test_activate_manual_path_when_signing_disabled(monkeypatch) -> None:
    """No signing rail + no signatures → activation proceeds on fields alone."""
    monkeypatch.setattr(settings, "SIGNING_ENABLED", False)
    uid = await _seed_user()
    cid = await _seed_contract(status=ContractStatus.draft, complete=True)

    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, cid)
        await lifecycle.activate_contract(db, contract, actor_id=uid)
        await db.commit()
        assert contract.status == ContractStatus.active


@pytest.mark.asyncio
async def test_create_active_in_manual_register_never_queries_signature_state(
    app_client, app_auth_headers, monkeypatch
) -> None:
    """Manual POST accepts an offline agreement even with signing enabled."""

    async def unexpected_signature_lookup(*_args, **_kwargs):
        raise AssertionError("manual contract create queried DocumentSignature")

    monkeypatch.setattr(
        lifecycle, "_has_completed_signature", unexpected_signature_lookup
    )
    cand_id, cli_id = await _seed_candidate_and_client()
    response = await app_client.post(
        "/api/contracts",
        json={
            "candidate_id": cand_id,
            "client_id": cli_id,
            "start_date": date.today().isoformat(),
            "rate_candidate": 15000,
            "rate_client": 20000,
            "contract_type": "b2b",
            "work_mode": "remote",
            "status": "active",
        },
        headers=app_auth_headers,
    )

    assert response.status_code == 201, response.text
    assert response.json()["status"] == "active"


@pytest.mark.asyncio
async def test_patch_active_does_not_require_qualified_signature(
    app_client, app_auth_headers, monkeypatch
) -> None:
    """PATCH can save Active even when signing is enabled and no proof exists."""

    cand_id, cli_id = await _seed_candidate_and_client()
    created = await app_client.post(
        "/api/contracts",
        json={
            "candidate_id": cand_id,
            "client_id": cli_id,
            "start_date": date.today().isoformat(),
            "rate_candidate": 15000,
            "rate_client": 20000,
            "contract_type": "b2b",
            "work_mode": "remote",
            "status": "draft",
        },
        headers=app_auth_headers,
    )
    assert created.status_code == 201, created.text

    monkeypatch.setattr(settings, "SIGNING_ENABLED", True)
    response = await app_client.patch(
        f"/api/contracts/{created.json()['id']}",
        json={"status": "active"},
        headers=app_auth_headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "active"


@pytest.mark.asyncio
async def test_activate_incomplete_draft_409() -> None:
    uid = await _seed_user()
    cid = await _seed_contract(status=ContractStatus.draft, complete=False)
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, cid)
        with pytest.raises(HTTPException) as exc:
            await lifecycle.activate_contract(db, contract, actor_id=uid)
        assert exc.value.status_code == 409
        assert "missing" in exc.value.detail


# ── Finalize unsigned HTML → ready_for_signature (HTTP) ───────────────────────


@pytest.mark.asyncio
async def test_finalize_unsigned_html_ends_ready_for_signature(
    app_client, app_auth_headers
) -> None:
    cid = await _seed_contract(
        status=ContractStatus.draft,
        complete=True,
        draft_html="<p>Umowa treść</p>",
    )
    resp = await app_client.post(
        f"/api/contracts/{cid}/draft/finalize", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # At most `ready_for_signature` — never `active` for an unsigned document.
    assert body["status"] == "ready_for_signature"
    assert body["document_id"] is not None

    # No `contract_signed` was emitted: the only activity is the finalize/ready
    # transition, not an activation.
    async with AsyncSessionLocal() as db:
        actions = (
            await db.scalars(
                select(Activity.action).where(
                    Activity.entity_type == "contract", Activity.entity_id == cid
                )
            )
        ).all()
    assert "contract_ready_for_signature" in actions
    assert "contract_activated" not in actions


@pytest.mark.asyncio
async def test_activate_finalized_does_not_require_signature_when_signing_on(
    app_client, app_auth_headers, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "SIGNING_ENABLED", True)
    cid = await _seed_contract(status=ContractStatus.ready_for_signature, complete=True)
    resp = await app_client.post(
        f"/api/contracts/{cid}/activate", json={}, headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "active"


# ── Contract register status writes (HTTP) ───────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("selected_status", ["draft", "active", "ending", "ended"])
async def test_create_contract_honours_register_status_body(
    app_client, app_auth_headers, selected_status
) -> None:
    cand_id, cli_id = await _seed_candidate_and_client()
    resp = await app_client.post(
        "/api/contracts",
        json={
            "candidate_id": cand_id,
            "client_id": cli_id,
            "start_date": date.today().isoformat(),
            "end_date": (date.today() + timedelta(days=90)).isoformat(),
            "rate_candidate": 15000,
            "rate_client": 20000,
            "contract_type": "b2b",
            "work_mode": "remote",
            "status": selected_status,
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == selected_status


@pytest.mark.asyncio
async def test_create_complete_contract_without_status_remains_draft(
    app_client, app_auth_headers
) -> None:
    """Write-time promotion changes existing drafts, not POST defaults."""

    cand_id, cli_id = await _seed_candidate_and_client()
    resp = await app_client.post(
        "/api/contracts",
        json={
            "candidate_id": cand_id,
            "client_id": cli_id,
            "start_date": date.today().isoformat(),
            "rate_candidate": 15000,
            "rate_client": 20000,
            "contract_type": "b2b",
        },
        headers=app_auth_headers,
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "draft"


@pytest.mark.asyncio
@pytest.mark.parametrize("selected_status", ["active", "ending"])
async def test_create_contract_active_requires_complete_draft(
    app_client, app_auth_headers, selected_status
) -> None:
    """Rejestr wybiera status, ale nie omija bramek aktywacji.

    ``active`` i ``ending`` są w ``REVENUE_BEARING_STATUSES``, więc wiersz
    założony w jednym z nich od razu liczy się do MRR, do liczników
    konsultantów i do skanera wygasania. Ładunek bez stawek ma
    dostać 409 z listą braków — a nie cichy szkic podany jako sukces ani
    aktywną umowę z pustymi polami, na których stoi liczenie pieniędzy.

    ``end_date`` świadomie NIE jest na tej liście — patrz
    ``test_create_contract_active_accepts_open_ended_period`` niżej.
    """
    cand_id, cli_id = await _seed_candidate_and_client()
    resp = await app_client.post(
        "/api/contracts",
        json={
            "candidate_id": cand_id,
            "client_id": cli_id,
            "start_date": date.today().isoformat(),
            "contract_type": "b2b",
            "status": selected_status,
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert set(detail["missing"]) == {
        "rate_candidate",
        "rate_client",
    }


@pytest.mark.asyncio
async def test_create_contract_active_accepts_open_ended_period(
    app_client, app_auth_headers
) -> None:
    """Umowa bezterminowa i bez trybu pracy aktywuje się normalnie.

    Zgłoszenie: „409 przy każdym zapisie ze statusem Aktywny, zapis działa
    tylko dla Draftu". Data końca w bramce dawała stan bez wyjścia — rejestr
    renderuje brak daty jako „bezterminowo", ``_status_after_end_date_change``
    leczy z niej ``ended`` na ``active``, a aktywować się nie dało.
    """
    cand_id, cli_id = await _seed_candidate_and_client()
    resp = await app_client.post(
        "/api/contracts",
        json={
            "candidate_id": cand_id,
            "client_id": cli_id,
            "start_date": date.today().isoformat(),
            "end_date": None,
            "rate_candidate": 15000,
            "rate_client": 20000,
            "contract_type": "b2b",
            "status": "active",
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["end_date"] is None
    assert body["work_mode"] is None
    assert body["status"] == "active"


@pytest.mark.asyncio
async def test_patch_activates_with_rate_sent_only_as_a_schedule(
    app_client, app_auth_headers
) -> None:
    """Stawka progresywna przysłana W TYM SAMYM żądaniu co status „Aktywny".

    Formularz rejestru wysyła stawkę kandydata ALBO jako ``rate_candidate``,
    ALBO — gdy jest progresywna — WYŁĄCZNIE jako ``candidate_rate_schedule``.
    ``PATCH`` wykonywał przejście stanu PRZED wyprowadzeniem stawki
    z harmonogramu, więc bramka oglądała jeszcze pustą kolumnę cache'u
    i odmawiała ``missing: rate_candidate`` — mimo że stawka przyszła
    w tym samym żądaniu, a linijkę niżej ta sama kolumna była wypełniana.
    ``POST`` miał tę kolejność poprawnie od początku.
    """
    cand_id, cli_id = await _seed_candidate_and_client()
    start = date.today()
    # Szkic BEZ stawki kandydata — dokładnie ten wiersz, który operator
    # uzupełnia harmonogramem i od razu aktywuje.
    resp = await app_client.post(
        "/api/contracts",
        json={
            "candidate_id": cand_id,
            "client_id": cli_id,
            "start_date": start.isoformat(),
            "rate_client": 20000,
            "contract_type": "b2b",
            "work_mode": "remote",
            "status": "draft",
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text
    cid = resp.json()["id"]
    assert resp.json()["rate_candidate"] is None

    resp = await app_client.patch(
        f"/api/contracts/{cid}",
        json={
            "status": "active",
            "candidate_rate_schedule": [
                {"rate": 15000, "effective_from": start.isoformat()},
                {
                    "rate": 16000,
                    "effective_from": (start + timedelta(days=180)).isoformat(),
                },
            ],
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "active"
    # Kolumna cache'u wyprowadzona z kroku obowiązującego dziś.
    assert float(body["rate_candidate"]) == 15000.0


@pytest.mark.asyncio
async def test_open_ended_contract_cannot_be_ending(
    app_client, app_auth_headers
) -> None:
    """„Kończący się" bez daty końca to stan, który sam się kasuje.

    ``_status_after_end_date_change`` (i dzienny cron) cofa taki wiersz na
    ``active``, więc bez tej odmowy zapis zwracałby 200 i nie robił nic.
    Odmowa mówi po polsku, co zrobić — i dotyczy WYŁĄCZNIE ``ending``.
    """
    cand_id, cli_id = await _seed_candidate_and_client()
    resp = await app_client.post(
        "/api/contracts",
        json={
            "candidate_id": cand_id,
            "client_id": cli_id,
            "start_date": date.today().isoformat(),
            "end_date": None,
            "rate_candidate": 15000,
            "rate_client": 20000,
            "contract_type": "b2b",
            "work_mode": "remote",
            "status": "ending",
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["reason"] == "ending_requires_end_date"


@pytest.mark.asyncio
async def test_patch_contract_honours_register_status_body(
    app_client, app_auth_headers
) -> None:
    cid = await _seed_contract(status=ContractStatus.draft, complete=True)
    resp = await app_client.patch(
        f"/api/contracts/{cid}",
        json={"status": "active", "team_name": "X"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "active"
    assert resp.json()["team_name"] == "X"

    for selected_status in ("ending", "ended", "draft"):
        changed = await app_client.patch(
            f"/api/contracts/{cid}",
            json={"status": selected_status},
            headers=app_auth_headers,
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()["status"] == selected_status


@pytest.mark.asyncio
async def test_patch_completing_draft_auto_activates_once(
    app_client, app_auth_headers
) -> None:
    """Saving the required fields removes the separate manual status change."""

    cid = await _seed_contract(status=ContractStatus.draft, complete=False)
    resp = await app_client.patch(
        f"/api/contracts/{cid}",
        json={
            "start_date": (date.today() + timedelta(days=30)).isoformat(),
            "rate_candidate": 15000,
            "rate_client": 20000,
            "contract_type": "b2b",
        },
        headers=app_auth_headers,
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "active"

    async with AsyncSessionLocal() as db:
        actions = list(
            await db.scalars(
                select(Activity.action).where(
                    Activity.entity_type == "contract", Activity.entity_id == cid
                )
            )
        )
    assert actions.count("contract_activated") == 1


@pytest.mark.asyncio
async def test_patch_legacy_complete_draft_does_not_auto_activate_incidentally(
    app_client, app_auth_headers
) -> None:
    """Only a new incomplete→complete edge triggers; there is no retro-sweep."""

    cid = await _seed_contract(status=ContractStatus.draft, complete=True)
    resp = await app_client.patch(
        f"/api/contracts/{cid}",
        # The client-register dialog always echoes start_date, even when the
        # operator only edits a project field. Presence alone must not promote
        # an already-complete legacy draft.
        json={"start_date": date.today().isoformat(), "team_name": "Platform"},
        headers=app_auth_headers,
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "draft"


@pytest.mark.asyncio
async def test_patch_complete_draft_with_explicit_draft_stays_draft(
    app_client, app_auth_headers
) -> None:
    """An explicit lifecycle choice wins over completeness automation."""

    cid = await _seed_contract(status=ContractStatus.draft, complete=False)
    resp = await app_client.patch(
        f"/api/contracts/{cid}",
        json={
            "start_date": date.today().isoformat(),
            "rate_candidate": 15000,
            "rate_client": 20000,
            "contract_type": "b2b",
            "status": "draft",
        },
        headers=app_auth_headers,
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "draft"


@pytest.mark.asyncio
async def test_patch_ready_for_signature_never_auto_activates(
    app_client, app_auth_headers
) -> None:
    """Only Draft participates; finalized contracts keep their explicit gate."""

    cid = await _seed_contract(
        status=ContractStatus.ready_for_signature, complete=True
    )
    resp = await app_client.patch(
        f"/api/contracts/{cid}",
        json={"rate_client": 21000},
        headers=app_auth_headers,
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "ready_for_signature"


@pytest.mark.asyncio
async def test_register_rejects_lifecycle_only_statuses(
    app_client, app_auth_headers
) -> None:
    cid = await _seed_contract(status=ContractStatus.draft, complete=True)
    resp = await app_client.patch(
        f"/api/contracts/{cid}",
        json={"status": "void"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 422, resp.text

    null_status = await app_client.patch(
        f"/api/contracts/{cid}",
        json={"status": None},
        headers=app_auth_headers,
    )
    assert null_status.status_code == 422, null_status.text


@pytest.mark.asyncio
async def test_register_status_updates_client_active_consultants(
    app_client, app_auth_headers
) -> None:
    """Active dodaje konsultanta do profilu klienta, inny status go usuwa."""

    cid = await _seed_contract(status=ContractStatus.draft, complete=True)
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, cid)
        assert contract is not None
        client_id = contract.client_id

    activate = await app_client.patch(
        f"/api/contracts/{cid}",
        json={"status": "active"},
        headers=app_auth_headers,
    )
    assert activate.status_code == 200, activate.text
    profile = await app_client.get(
        f"/api/clients/{client_id}/profile", headers=app_auth_headers
    )
    assert profile.status_code == 200, profile.text
    assert cid in {row["contract_id"] for row in profile.json()["active_consultants"]}

    end = await app_client.patch(
        f"/api/contracts/{cid}",
        json={"status": "ended"},
        headers=app_auth_headers,
    )
    assert end.status_code == 200, end.text
    profile = await app_client.get(
        f"/api/clients/{client_id}/profile", headers=app_auth_headers
    )
    assert profile.status_code == 200, profile.text
    assert cid not in {
        row["contract_id"] for row in profile.json()["active_consultants"]
    }


# ── Delete guard + void + reopen (HTTP) ───────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_draft_allowed(app_client, app_auth_headers) -> None:
    cid = await _seed_contract(status=ContractStatus.draft, complete=True)
    resp = await app_client.delete(f"/api/contracts/{cid}", headers=app_auth_headers)
    assert resp.status_code == 204, resp.text


@pytest.mark.asyncio
async def test_delete_executed_contract_now_removes_row(
    app_client, app_auth_headers
) -> None:
    """Decyzja 2026-08-25 (ticket „Usunięcie kontraktu nie działa"): błędnie
    dodany/zdublowany kontrakt kasuje się niezależnie od statusu — dawne
    blanket-409 dla nie-szkiców czytało się w UI jak „potwierdziłem i nic".
    """
    cid = await _seed_contract(status=ContractStatus.active, complete=True)

    resp = await app_client.delete(f"/api/contracts/{cid}", headers=app_auth_headers)
    assert resp.status_code == 204, resp.text

    async with AsyncSessionLocal() as db:
        assert await db.get(Contract, cid) is None


@pytest.mark.asyncio
async def test_void_remains_available_for_annulment(
    app_client, app_auth_headers
) -> None:
    """Void (anulowanie z zachowaniem historii) zostaje osobną, żywą ścieżką."""
    cid = await _seed_contract(status=ContractStatus.active, complete=True)

    void = await app_client.post(
        f"/api/contracts/{cid}/void",
        json={"reason": "pytest"},
        headers=app_auth_headers,
    )
    assert void.status_code == 200, void.text
    assert void.json()["status"] == "void"

    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, cid)
        assert contract is not None  # not hard-deleted
        assert contract.status == ContractStatus.void
        assert contract.voided_at is not None


@pytest.mark.asyncio
async def test_delete_contract_with_completed_signature_409(
    app_client, app_auth_headers
) -> None:
    uid = await _seed_user()
    cid = await _seed_contract(status=ContractStatus.draft, complete=True)
    await _seed_signature(cid, uid, SignatureStatus.completed)
    resp = await app_client.delete(f"/api/contracts/{cid}", headers=app_auth_headers)
    assert resp.status_code == 409, resp.text
    # Odmowa jest po polsku i wskazuje przyczynę + alternatywę (void).
    detail = resp.json()["detail"]
    assert detail["code"] == "contract_has_completed_signature"
    assert "podpis" in detail["message"]
    assert "void_endpoint" in detail

    forced = await app_client.post(
        f"/api/contracts/{cid}/force-delete-signed",
        json={"confirmation": f"#{cid}"},
        headers=app_auth_headers,
    )
    assert forced.status_code == 409, forced.text
    assert forced.json()["detail"]["code"] == "contract_has_completed_signature"

    async with AsyncSessionLocal() as db:
        assert await db.get(Contract, cid) is not None


@pytest.mark.asyncio
async def test_reopen_reverts_active_to_draft(app_client, app_auth_headers) -> None:
    cid = await _seed_contract(status=ContractStatus.active, complete=True)
    resp = await app_client.post(
        f"/api/contracts/{cid}/reopen",
        json={"reason": "correction"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "draft"


# ── QES fail-closed (service) ─────────────────────────────────────────────────


class _FakeProvider:
    def __init__(self, report: ValidationReport) -> None:
        self._report = report

    async def validate(self, pdf: bytes) -> ValidationReport:
        return self._report


async def _run_finalize(monkeypatch, *, dss_url: str, report: ValidationReport):
    uid = await _seed_user()
    cid = await _seed_contract(status=ContractStatus.ready_for_signature, complete=True)
    sig_id = await _seed_signature(cid, uid, SignatureStatus.sent)
    monkeypatch.setattr(settings, "DSS_VALIDATION_URL", dss_url)
    monkeypatch.setattr(
        signing_sender, "get_provider", lambda name: _FakeProvider(report)
    )
    async with AsyncSessionLocal() as db:
        sig = await db.get(DocumentSignature, sig_id)
        return db, sig


@pytest.mark.asyncio
async def test_qes_failclosed_when_dss_unset(monkeypatch) -> None:
    # DSS unset + non-authoritative fallback report → must NOT complete.
    db, sig = await _run_finalize(
        monkeypatch,
        dss_url="",
        report=ValidationReport(is_qes=False, indication="TOTAL-PASSED"),
    )
    async with db:
        with pytest.raises(HTTPException) as exc:
            await signing_sender.finalize_signed_pdf(
                db, sig, b"%PDF-fake", moved_by=sig.sender_user_id
            )
        assert exc.value.status_code == 422
        assert sig.status == SignatureStatus.sent  # unchanged
        assert sig.signed_document_id is None


@pytest.mark.asyncio
async def test_qes_failclosed_on_indeterminate_dss(monkeypatch) -> None:
    # DSS set but timed-out / INDETERMINATE → must NOT complete.
    db, sig = await _run_finalize(
        monkeypatch,
        dss_url="http://dss.internal/validate",
        report=ValidationReport(
            is_qes=False, indication="INDETERMINATE", sub_indication="DSS_ERROR"
        ),
    )
    async with db:
        with pytest.raises(HTTPException) as exc:
            await signing_sender.finalize_signed_pdf(
                db, sig, b"%PDF-fake", moved_by=sig.sender_user_id
            )
        assert exc.value.status_code == 422
        assert sig.status == SignatureStatus.sent


@pytest.mark.asyncio
async def test_qes_authoritative_pass_completes(monkeypatch) -> None:
    # DSS set + authoritative QES verdict → the document DOES complete.
    monkeypatch.setattr(
        signing_sender.storage_service,
        "save_contract_document",
        lambda *a, **k: ("signed/fake.pdf", 9),
    )
    db, sig = await _run_finalize(
        monkeypatch,
        dss_url="http://dss.internal/validate",
        report=ValidationReport(
            is_qes=True, indication="TOTAL-PASSED", signature_level="QESIG"
        ),
    )
    async with db:
        result = await signing_sender.finalize_signed_pdf(
            db, sig, b"%PDF-fake", moved_by=sig.sender_user_id
        )
        assert result["status"] == "ok"
        assert sig.status == SignatureStatus.completed
