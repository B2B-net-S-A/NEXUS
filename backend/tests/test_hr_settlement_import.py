"""Rozliczenie premii z arkusza: odczyt pliku, rola wiersza, zapis bez dublowania
automatu i miesiąc wypłaty po starcie. Dane fikcyjne."""

from __future__ import annotations

import io
import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from openpyxl import Workbook
from sqlalchemy import delete, select

import app.models  # noqa: F401  (rejestracja wszystkich mapperów)
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.hr_payroll import HrBonus
from app.models.hr_profile import EmployeeProfile
from app.models.user import User, UserRole
from app.services.hr import placement_bonuses, settlement_import
from app.services.hr.bonus_rules import payout_period
from app.services.hr.payroll_access import PayrollViewer
from app.services.hr.payroll_errors import PayrollForbidden


def _xlsx(rows: list[tuple]) -> bytes:
    book = Workbook()
    sheet = book.active
    sheet.append(("Imię i nazwisko", "Kandydat", "Marża", "Kwota", "Uwagi"))
    for row in rows:
        sheet.append(row)
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def test_parse_fills_person_down_and_skips_rows_without_amount() -> None:
    rows = settlement_import.parse_workbook(
        _xlsx(
            [
                ("Bąk Jan ", "Anna Nowak", 40, 1000, "uwaga"),
                (None, "Piotr Lis", 50, 2528.4, None),
                (None, "Gwarancje:\nKtoś - 100", None, None, None),
                ("Kowal Ewa", "-", None, None, None),
                (None, "Premia uznaniowa za punkty", None, 1495, None),
            ]
        )
    )
    assert [(r.person, r.candidate, r.amount) for r in rows] == [
        ("Bąk Jan", "Anna Nowak", Decimal("1000.00")),
        ("Bąk Jan", "Piotr Lis", Decimal("2528.40")),
        ("Kowal Ewa", "Premia uznaniowa za punkty", Decimal("1495.00")),
    ]


def test_parse_refuses_other_files() -> None:
    with pytest.raises(settlement_import.SettlementFileError):
        settlement_import.parse_workbook(b"to nie jest excel")
    with pytest.raises(settlement_import.SettlementFileError):
        settlement_import.parse_workbook(_xlsx([("Bąk Jan", "-", None, None, None)]))


def test_name_key_ignores_order_case_and_diacritics() -> None:
    assert settlement_import.name_key("Gołąb  Łukasz ") == settlement_import.name_key(
        "lukasz golab"
    )


@pytest.mark.parametrize(
    ("note", "recipient", "dl", "rec", "is_dl", "is_rec", "expected"),
    [
        ("Podpisany premia DL", 1, None, 1, False, True, "dl"),
        ("premia rekruterska", 1, 1, None, True, False, "recruiter"),
        ("", 1, 2, 1, True, True, "recruiter"),
        ("", 1, 1, 2, True, True, "dl"),
        ("", 1, 2, 3, True, False, "dl"),
        ("", 1, 2, 3, True, True, "recruiter"),
    ],
)
def test_role_of_row(note, recipient, dl, rec, is_dl, is_rec, expected) -> None:
    assert (
        settlement_import.resolve_role(
            note,
            recipient_id=recipient,
            automat_dl=dl,
            automat_recruiter=rec,
            is_dl=is_dl,
            is_recruiter=is_rec,
        )
        == expected
    )


@pytest.mark.parametrize(
    ("start", "eligible", "expected"),
    [
        (date(2026, 9, 1), date(2026, 9, 30), (2026, 10)),
        (date(2026, 10, 1), date(2026, 10, 30), (2026, 11)),
        (date(2026, 12, 7), date(2027, 1, 7), (2027, 1)),
        # Święta przesuwają termin za następny miesiąc: nie płacimy przed nim.
        (date(2026, 10, 30), date(2026, 12, 1), (2026, 12)),
    ],
)
def test_payout_is_month_after_start_never_before_deadline(
    start, eligible, expected
) -> None:
    assert payout_period(start, eligible) == expected


def _viewer(user_id: int, *, payroll: bool = True) -> PayrollViewer:
    return PayrollViewer(
        user_id=user_id, payroll=payroll, admin=False, report_ids=frozenset()
    )


@pytest_asyncio.fixture
async def world():
    marker = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        people = {}
        for key, role in (
            ("payroll", "finance"),
            ("dl", "delivery_lead"),
            ("recruiter", "recruiter"),
            ("other", "recruiter"),
        ):
            user = User(
                email=f"imp-{key}-{marker}@example.com",
                name=f"{key.title()} Osoba{marker}",
                role=UserRole(role),
                roles=[role],
                is_active=True,
            )
            db.add(user)
            await db.flush()
            db.add(EmployeeProfile(user_id=user.id, employment_type="b2b"))
            people[key] = user
        client = Client(name=f"Klient {marker}")
        db.add(client)
        await db.flush()
        candidate = Candidate(
            name="Kandydat",
            lastname=f"Nazwisko{marker}",
            email=f"imp-cand-{marker}@example.com",
        )
        db.add(candidate)
        await db.flush()
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client.id,
            start_date=date(2026, 9, 7),
            rate_candidate=Decimal("100"),
            rate_client=Decimal("146"),
            rate_unit=RateUnit.hourly,
            currency="PLN",
            rate_client_currency="PLN",
            rate_candidate_currency="PLN",
            status=ContractStatus.active,
        )
        db.add(contract)
        await db.flush()
        proposal = HrBonus(
            recipient_user_id=people["other"].id,
            amount=Decimal("1500"),
            currency="PLN",
            category="recruiter",
            period_year=2026,
            period_month=10,
            status="proposed",
            source=placement_bonuses.SOURCE,
            source_key=placement_bonuses.source_key(contract.id, "recruiter"),
            contract_id=contract.id,
        )
        db.add(proposal)
        await db.commit()
        ids = {key: user.id for key, user in people.items()}
        data = {
            "ids": ids,
            "names": {key: user.name for key, user in people.items()},
            "contract": contract.id,
            "candidate": f"Kandydat Nazwisko{marker}",
        }
    yield data
    async with AsyncSessionLocal() as db:
        await db.execute(delete(HrBonus).where(HrBonus.contract_id == data["contract"]))
        await db.execute(
            delete(HrBonus).where(HrBonus.recipient_user_id.in_(ids.values()))
        )
        await db.commit()


async def _preview(world, rows):
    async with AsyncSessionLocal() as db:
        return await settlement_import.build_preview(
            db, _viewer(world["ids"]["payroll"]), _xlsx(rows), year=2026, month=11
        )


async def _apply(world, rows):
    async with AsyncSessionLocal() as db:
        counts = await settlement_import.apply_rows(
            db, _viewer(world["ids"]["payroll"]), rows, year=2026, month=11
        )
        await db.commit()
        return counts


@pytest.mark.asyncio
async def test_row_takes_over_automat_proposal_without_duplicate(world) -> None:
    preview = await _preview(
        world, [(world["names"]["recruiter"], world["candidate"], 46, 3000, "x2")]
    )
    row = preview["rows"][0]
    assert row["status"] == "differs"
    assert row["keyed"] is True and row["role"] == "recruiter"

    assert (await _apply(world, [row]))["assigned"] == 1
    async with AsyncSessionLocal() as db:
        bonuses = list(
            await db.scalars(
                select(HrBonus).where(HrBonus.contract_id == world["contract"])
            )
        )
    assert len(bonuses) == 1
    bonus = bonuses[0]
    assert bonus.recipient_user_id == world["ids"]["recruiter"]
    assert bonus.amount == Decimal("3000.00")
    assert (bonus.status, bonus.period_month) == ("assigned", 11)
    assert bonus.assigned_by == world["ids"]["payroll"]
    assert "x2" not in (bonus.description or "")
    assert bonus.rule_snapshot["edited_amount"] is True

    # Powtórka nic nie zmienia, a automat zostawia przyznaną premię.
    assert (await _apply(world, [row]))["skipped"] == 1
    async with AsyncSessionLocal() as db:
        await placement_bonuses.reconcile_contract(db, world["contract"])
        await db.commit()
        again = await db.get(HrBonus, bonus.id)
        assert again.recipient_user_id == world["ids"]["recruiter"]
        assert again.amount == Decimal("3000.00")


@pytest.mark.asyncio
async def test_imported_bonus_gives_no_ended_early_warning(world) -> None:
    preview = await _preview(
        world, [(world["names"]["recruiter"], world["candidate"], 46, 3000, "x2")]
    )
    await _apply(world, [preview["rows"][0]])
    async with AsyncSessionLocal() as db:
        bonus = await db.scalar(
            select(HrBonus).where(HrBonus.contract_id == world["contract"])
        )
        contract = await db.get(Contract, world["contract"])
        bonus.eligible_on = date(2026, 10, 7)
        contract.end_date = date(2026, 9, 20)
        await db.flush()
        assert await placement_bonuses.ended_early_bonus_ids(db, [bonus]) == set()
        await db.rollback()


@pytest.mark.asyncio
async def test_as_proposal_waits_for_payroll_and_survives_automat(world) -> None:
    preview = await _preview(
        world, [(world["names"]["recruiter"], world["candidate"], 46, 3000, "x2")]
    )
    async with AsyncSessionLocal() as db:
        counts = await settlement_import.apply_rows(
            db,
            _viewer(world["ids"]["payroll"]),
            [preview["rows"][0]],
            year=2026,
            month=11,
            as_proposal=True,
        )
        await db.commit()
    assert counts["proposed"] == 1 and counts["assigned"] == 0
    async with AsyncSessionLocal() as db:
        await placement_bonuses.reconcile_contract(db, world["contract"])
        await db.commit()
        bonus = await db.scalar(
            select(HrBonus).where(HrBonus.contract_id == world["contract"])
        )
    assert bonus.status == "proposed" and bonus.assigned_at is None
    assert bonus.recipient_user_id == world["ids"]["recruiter"]
    assert bonus.amount == Decimal("3000.00")
    assert (bonus.period_year, bonus.period_month) == (2026, 11)
    assert bonus.rule_snapshot["settlement_import"] is True


@pytest.mark.asyncio
async def test_zero_rejects_proposal_for_good(world) -> None:
    preview = await _preview(
        world, [(world["names"]["other"], world["candidate"], 46, 0, "brak premii")]
    )
    row = preview["rows"][0]
    assert row["status"] == "zero"
    assert (await _apply(world, [row]))["rejected"] == 1
    async with AsyncSessionLocal() as db:
        await placement_bonuses.reconcile_contract(db, world["contract"])
        await db.commit()
        bonus = await db.scalar(
            select(HrBonus).where(HrBonus.contract_id == world["contract"])
        )
    assert bonus.status == "cancelled"
    assert bonus.cancel_reason == settlement_import.CANCEL_REASON


@pytest.mark.asyncio
async def test_row_without_placement_is_manual_and_once(world) -> None:
    preview = await _preview(
        world,
        [(world["names"]["recruiter"], "Premia uznaniowa za punkty", None, 1495, None)],
    )
    row = preview["rows"][0]
    assert row["status"] == "no_placement"
    assert (await _apply(world, [row]))["assigned"] == 1
    assert (await _apply(world, [row]))["skipped"] == 1
    async with AsyncSessionLocal() as db:
        bonus = await db.scalar(
            select(HrBonus).where(
                HrBonus.recipient_user_id == world["ids"]["recruiter"]
            )
        )
    assert bonus.source == "manual"
    assert bonus.description == "Premia uznaniowa za punkty"


@pytest.mark.asyncio
async def test_inactive_person_is_not_selected_by_default(world) -> None:
    async with AsyncSessionLocal() as db:
        (await db.get(User, world["ids"]["other"])).is_active = False
        await db.commit()
    preview = await _preview(
        world, [(world["names"]["other"], world["candidate"], 46, 1500, None)]
    )
    assert preview["rows"][0]["status"] == "inactive"
    assert preview["rows"][0]["selected"] is False


@pytest.mark.asyncio
async def test_only_payroll_and_never_for_yourself(world) -> None:
    async with AsyncSessionLocal() as db:
        with pytest.raises(PayrollForbidden):
            await settlement_import.build_preview(
                db,
                _viewer(world["ids"]["dl"], payroll=False),
                _xlsx([("A B", "C D", 40, 100, None)]),
                year=2026,
                month=11,
            )
    preview = await _preview(
        world,
        [(world["names"]["payroll"], world["candidate"], 46, 1500, None)],
    )
    assert preview["rows"][0]["status"] == "self"
    assert preview["rows"][0]["selected"] is False
    async with AsyncSessionLocal() as db:
        with pytest.raises(PayrollForbidden):
            await settlement_import.apply_rows(
                db,
                _viewer(world["ids"]["payroll"]),
                [
                    {
                        "index": 2,
                        "candidate": "C D",
                        "amount": "100",
                        "recipient_user_id": world["ids"]["payroll"],
                    }
                ],
                year=2026,
                month=11,
            )
