"""Import zamówień MD Centrum e-Zdrowia z manifestu (Faza C, 09.2026).

Dane ZMYŚLONE — ten sam UKŁAD co w zgłoszeniu: karta MD na umowę wykonawczą,
zakres podstawowy/opcjonalny, stawki PLN/MD, historia miesięczna ze statusem,
zastępstwo jako para linii, unieważnienie starych szkiców. Bramka CeZ jest
monkeypatchowana na świeżego klienta (autouse w conftest pinuje ją na -1).
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_executive_contract import ClientExecutiveContract
from app.models.client_framework_contract import (
    ClientFrameworkContract,
    FrameworkContractStatus,
)
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import ClientOrderGroup
from app.models.contract import Contract, ContractStatus
from app.models.md_consumption import ClientOrderMdConsumption

pytestmark = pytest.mark.asyncio


async def _seed(monkeypatch) -> dict:
    """Klient CeZ (monkeypatch) z dwiema częściami, dwiema umowami wykonawczymi,
    dwoma aktywnymi kontraktami (każdy ze szkicem zamówienia) i jednym kandydatem
    bez kontraktu u klienta."""
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"CeZ seed {suffix}")
        db.add(client)
        await db.flush()
        part1 = ClientFrameworkContract(
            client_id=client.id,
            name=f"RAM/1/{suffix} – cz. I",
            status=FrameworkContractStatus.active,
            project_part="cz1",
        )
        part2 = ClientFrameworkContract(
            client_id=client.id,
            name=f"RAM/2/{suffix} – cz. II",
            status=FrameworkContractStatus.active,
            project_part="cz2",
        )
        db.add_all([part1, part2])
        await db.flush()
        ec_a = ClientExecutiveContract(
            client_id=client.id, framework_contract_id=part2.id, number=f"WYK/A/{suffix}"
        )
        ec_b = ClientExecutiveContract(
            client_id=client.id, framework_contract_id=part1.id, number=f"WYK/B/{suffix}"
        )
        db.add_all([ec_a, ec_b])
        await db.flush()

        people = {}
        for key, first, last in (
            ("alfa", "Anna", f"Testowa{suffix}"),
            ("beta", "Bartosz", f"Próbny{suffix}"),
        ):
            cand = Candidate(name=first, lastname=last, email=f"{key}-{suffix}@example.com")
            db.add(cand)
            await db.flush()
            contract = Contract(
                candidate_id=cand.id,
                client_id=client.id,
                status=ContractStatus.active,
                start_date=date(2025, 12, 1),
                rate_candidate=Decimal("95"),
                rate_client=Decimal("100"),
            )
            db.add(contract)
            await db.flush()
            draft = ClientOrder(
                client_id=client.id,
                contract_id=contract.id,
                title=f"WYK/A/{suffix}",
                status=ClientOrderStatus.draft,
                start_date=date(2025, 12, 1),
                project_part="cz2",
            )
            db.add(draft)
            await db.flush()
            people[key] = {
                "candidate_id": cand.id,
                "contract_id": contract.id,
                "draft_id": draft.id,
                "name": f"{first} {last}",
            }
        loose = Candidate(
            name="Celina", lastname=f"Luźna{suffix}", email=f"gamma-{suffix}@example.com"
        )
        db.add(loose)
        await db.flush()
        # Dwa rekordy kandydata o tym samym nazwisku — niejednoznaczność.
        dup1 = Candidate(name="Dawid", lastname=f"Podwójny{suffix}")
        dup2 = Candidate(name="Dawid", lastname=f"Podwójny{suffix}")
        db.add_all([dup1, dup2])
        await db.commit()
        return {
            "client_id": client.id,
            "suffix": suffix,
            "ec_a": ec_a.number,
            "ec_b": ec_b.number,
            "people": people,
            "loose": {"candidate_id": loose.id, "name": f"Celina Luźna{suffix}"},
            "dup_name": f"Dawid Podwójny{suffix}",
        }


def _manifest(seed: dict, *, extra_lines: list | None = None, supersede=True) -> dict:
    alfa = seed["people"]["alfa"]
    beta = seed["people"]["beta"]
    lines = [
        {
            "key": "alfa",
            "person": {"name": alfa["name"], "contract_id": alfa["contract_id"]},
            "base_md": 190,
            "optional_md": 170,
            "rate_cost": 760,
            "rate_revenue": 800,
            "start_date": "2025-12-01",
            "history": [
                {"month": "2025-12", "md": 20, "status": "protocol"},
                {"month": "2026-01", "md": 22, "status": "accepted"},
            ],
        },
        {
            # Poprzednik: nowa osoba (create_if_missing) z kontraktem zakończonym.
            "key": "odchodzacy",
            "person": {
                "name": f"Edward Odchodzący{seed['suffix']}",
                "create_if_missing": True,
                "contract": {
                    "start_date": "2025-12-01",
                    "end_date": "2025-12-31",
                    "status": "ended",
                },
            },
            "base_md": 190,
            "optional_md": 170,
            "rate_cost": 480,
            "rate_revenue": 600,
            "start_date": "2025-12-01",
            "end_date": "2025-12-31",
            "line_status": "completed",
            "history": [{"month": "2025-12", "md": 4, "status": "protocol"}],
        },
        {
            # Następca po nazwisku (jedno trafienie wśród kontraktów klienta).
            "key": "beta",
            "person": {"name": beta["name"]},
            "base_md": 190,
            "optional_md": 170,
            "rate_cost": 480,
            "rate_revenue": 600,
            "start_date": "2026-01-01",
            "replaces_key": "odchodzacy",
            "history": [],
        },
        {
            # Kandydat bez kontraktu u klienta — kontrakt zakładany z manifestu.
            "key": "gamma",
            "person": {
                "name": seed["loose"]["name"],
                "candidate_id": seed["loose"]["candidate_id"],
                "contract": {"start_date": "2026-02-01", "status": "active"},
            },
            "base_md": 100,
            "optional_md": None,
            "rate_cost": 900,
            "rate_revenue": 1000,
            "start_date": "2026-02-01",
            "history": [{"month": "2026-02", "md": 130.5, "status": "accepted"}],
        },
    ] + (extra_lines or [])
    return {
        "client_id": seed["client_id"],
        "source": "test",
        "supersede_order_ids": (
            [alfa["draft_id"], beta["draft_id"]] if supersede else []
        ),
        "groups": [
            {
                "executive_contract_number": seed["ec_a"],
                "order_number": seed["ec_a"],
                "start_date": "2025-12-01",
                "lines": lines,
            }
        ],
    }


def _patch_gate(monkeypatch, client_id: int) -> None:
    monkeypatch.setattr("app.services.ezdrowie.EZDROWIE_CLIENT_ID", client_id)


async def _post(app_client, headers, client_id, manifest, dry_run):
    return await app_client.post(
        f"/api/admin/clients/{client_id}/ezdrowie-md-orders/import",
        params={"dry_run": "true" if dry_run else "false"},
        json=manifest,
        headers=headers,
    )


async def test_import_is_only_for_ezdrowie(app_client: AsyncClient, app_auth_headers):
    seed = await _seed(None)
    resp = await _post(app_client, app_auth_headers, seed["client_id"], _manifest(seed), True)
    assert resp.status_code == 422
    assert "Centrum e-Zdrowia" in resp.text


async def test_dry_run_reports_without_writing(
    app_client: AsyncClient, app_auth_headers, monkeypatch
):
    seed = await _seed(monkeypatch)
    _patch_gate(monkeypatch, seed["client_id"])
    resp = await _post(app_client, app_auth_headers, seed["client_id"], _manifest(seed), True)
    assert resp.status_code == 200, resp.text
    report = resp.json()
    assert report["dry_run"] is True and report["applied"] is False
    assert report["blockers"] == []
    group = report["groups"][0]
    assert group["status"] == "created"
    by_key = {line["key"]: line for line in group["lines"]}
    assert by_key["alfa"]["person"]["resolution"] == "resolved"
    assert by_key["odchodzacy"]["person"]["resolution"] == "created"
    assert by_key["beta"]["person"]["resolution"] == "resolved"
    assert by_key["gamma"]["person"]["resolution"] == "created"
    assert Decimal(by_key["alfa"]["md_used"]) == Decimal("42")
    assert Decimal(by_key["gamma"]["md_used"]) == Decimal("130.5")
    assert Decimal(by_key["gamma"]["md_base_used"]) == Decimal("100")
    assert Decimal(by_key["gamma"]["md_optional_used"]) == Decimal("30.5")
    # Reguła pozycji: poprzednik wnosi zużycie, nie budżet.
    assert Decimal(group["md_positions_total"]) == Decimal("360") + Decimal("360") + Decimal(
        "100"
    )
    assert Decimal(group["md_used_total"]) == Decimal("42") + Decimal("4") + Decimal("130.5")
    assert Decimal(group["contract_value_pln"]) == Decimal("360") * 800 + Decimal(
        "360"
    ) * 600 + Decimal("100") * 1000
    assert report["totals"]["orders_superseded"] == 2

    async with AsyncSessionLocal() as db:
        groups = (
            await db.execute(
                select(ClientOrderGroup).where(
                    ClientOrderGroup.client_id == seed["client_id"]
                )
            )
        ).scalars().all()
        assert groups == []
        drafts = (
            await db.execute(
                select(ClientOrder.status).where(
                    ClientOrder.id.in_(
                        [seed["people"]["alfa"]["draft_id"], seed["people"]["beta"]["draft_id"]]
                    )
                )
            )
        ).scalars().all()
        assert all(status == ClientOrderStatus.draft for status in drafts)
        stray = await db.scalar(
            select(Candidate.id).where(Candidate.lastname == f"Odchodzący{seed['suffix']}")
        )
        assert stray is None


async def test_ambiguous_person_blocks_apply(
    app_client: AsyncClient, app_auth_headers, monkeypatch
):
    seed = await _seed(monkeypatch)
    _patch_gate(monkeypatch, seed["client_id"])
    manifest = _manifest(
        seed,
        extra_lines=[
            {
                "key": "dup",
                "person": {
                    "name": seed["dup_name"],
                    "contract": {"start_date": "2026-01-01", "status": "active"},
                },
                "base_md": 10,
                "rate_cost": 100,
                "rate_revenue": 200,
                "start_date": "2026-01-01",
                "history": [],
            }
        ],
    )
    preview = await _post(app_client, app_auth_headers, seed["client_id"], manifest, True)
    assert preview.status_code == 200, preview.text
    dup = next(
        line for line in preview.json()["groups"][0]["lines"] if line["key"] == "dup"
    )
    assert dup["person"]["resolution"] == "ambiguous"
    assert len(dup["person"]["candidates"]) == 2
    assert preview.json()["blockers"]

    apply = await _post(app_client, app_auth_headers, seed["client_id"], manifest, False)
    assert apply.status_code == 409, apply.text
    assert apply.json()["detail"]["blockers"]
    async with AsyncSessionLocal() as db:
        count = await db.scalar(
            select(ClientOrderGroup.id).where(ClientOrderGroup.client_id == seed["client_id"])
        )
        assert count is None


async def test_apply_creates_lines_history_and_replacement_link(
    app_client: AsyncClient, app_auth_headers, monkeypatch
):
    seed = await _seed(monkeypatch)
    _patch_gate(monkeypatch, seed["client_id"])
    resp = await _post(app_client, app_auth_headers, seed["client_id"], _manifest(seed), False)
    assert resp.status_code == 200, resp.text
    report = resp.json()
    assert report["applied"] is True and report["receipt_key"].startswith("ezdrowie_md_seed_")
    totals = report["totals"]
    assert Decimal(totals.pop("md_used_sum")) == Decimal("176.5")
    assert totals == {
        "groups_created": 1,
        "lines": 4,
        "consumptions": 4,
        "contracts_created": 2,
        "candidates_created": 1,
        "orders_superseded": 2,
    }

    listing = await app_client.get(
        f"/api/clients/{seed['client_id']}/order-groups", headers=app_auth_headers
    )
    assert listing.status_code == 200, listing.text
    groups = listing.json()["groups"]
    assert len(groups) == 1
    group = groups[0]
    assert group["executive_contract"]["number"] == seed["ec_a"]
    assert group["executive_contract"]["project_part"] == "cz2"
    assert group["status"] == "active"
    lines = {line["consultant_name"]: line for line in group["lines"]}
    alfa = lines[seed["people"]["alfa"]["name"]]
    assert alfa["status"] == "active"
    assert Decimal(str(alfa["md_total"])) == Decimal("190")
    assert Decimal(str(alfa["md_optional_total"])) == Decimal("170")
    assert Decimal(str(alfa["md_used"])) == Decimal("42")
    assert Decimal(str(alfa["md_remaining"])) == Decimal("318")
    predecessor = lines[f"Edward Odchodzący{seed['suffix']}"]
    assert predecessor["status"] == "completed"
    assert Decimal(str(predecessor["md_used"])) == Decimal("4")
    assert predecessor["replaced_by_consultant_name"] == seed["people"]["beta"]["name"]
    successor = lines[seed["people"]["beta"]["name"]]
    assert successor["predecessor_order_id"] == predecessor["id"]
    assert Decimal(str(successor["md_used"] or 0)) == Decimal("0")
    assert Decimal(str(group["md_positions_total"])) == Decimal("820")
    assert Decimal(str(group["md_used_total"])) == Decimal("176.5")

    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(ClientOrderMdConsumption)
                .where(ClientOrderMdConsumption.order_id == alfa["id"])
                .order_by(ClientOrderMdConsumption.period_month)
            )
        ).scalars().all()
        assert [(r.period_month, r.status, r.source) for r in rows] == [
            ("2025-12", "protocol", "manual"),
            ("2026-01", "accepted", "manual"),
        ]
        ended = await db.scalar(
            select(Contract).where(Contract.id == predecessor["contract_id"])
        )
        assert ended.status == ContractStatus.ended
        assert ended.end_date == date(2025, 12, 31)
        for key in ("alfa", "beta"):
            draft = await db.scalar(
                select(ClientOrder).where(ClientOrder.id == seed["people"][key]["draft_id"])
            )
            assert draft.status == ClientOrderStatus.cancelled
            assert "import startowy" in (draft.notes or "")

    # Powtórka: grupa już istnieje — pomijana, szkice już anulowane = bloker.
    again = await _post(app_client, app_auth_headers, seed["client_id"], _manifest(seed), True)
    assert again.status_code == 200, again.text
    assert again.json()["groups"][0]["status"] == "already_exists"
    assert again.json()["superseded"][0]["status"] == "blocked"
    second = _manifest(seed, supersede=False)
    apply_again = await _post(app_client, app_auth_headers, seed["client_id"], second, False)
    assert apply_again.status_code == 200, apply_again.text
    assert apply_again.json()["totals"]["groups_created"] == 0
    listing = await app_client.get(
        f"/api/clients/{seed['client_id']}/order-groups", headers=app_auth_headers
    )
    assert len(listing.json()["groups"]) == 1


async def test_unknown_executive_contract_and_draft_with_file_block(
    app_client: AsyncClient, app_auth_headers, monkeypatch
):
    seed = await _seed(monkeypatch)
    _patch_gate(monkeypatch, seed["client_id"])
    manifest = _manifest(seed)
    manifest["groups"][0]["executive_contract_number"] = "WYK/NIE-MA"
    async with AsyncSessionLocal() as db:
        draft = await db.scalar(
            select(ClientOrder).where(ClientOrder.id == seed["people"]["alfa"]["draft_id"])
        )
        draft.file_path = "orders/fake.pdf"
        draft.filename = "fake.pdf"
        await db.commit()
    resp = await _post(app_client, app_auth_headers, seed["client_id"], manifest, True)
    assert resp.status_code == 200, resp.text
    blockers = resp.json()["blockers"]
    assert any("WYK/NIE-MA" in b for b in blockers)
    assert any("plik PO" in b for b in blockers)
    assert resp.json()["groups"][0]["status"] == "blocked"
