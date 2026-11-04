"""Ręczne uzupełnienie statystyk sprzed 12.10.2026 na żywym Postgresie.

`scripts/import_dr_manual_fill.py` pisze do tych samych tabel `dr_*`, z których
liczą ekrany, więc wpis ma być widoczny tam, gdzie wpis z DynaReportera:
w widoku ``analytics_kpi_milestones`` (od 0472 także przed 2026, Rada przed
2026 = reszta bez osoby), w liczniku celów (``credited``), w portfelu DL
(październik 2026 = 1–11.10), w Lidze i celu DL (bez października — mianownik
hit ratio jest od 12.10, decyzja Artura) i w podziale placementów na klientów.

Miesiąc sprzed 2026 to marzec 2019 — w bazie testowej nikt inny go nie używa,
a wiersz Rady jest wspólny dla przebiegów, więc test po sobie sprząta.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.client import Client
from app.models.user import User, UserRole
from app.services.kpi_catalog import KpiMetric
from app.services.kpi_engine import count_canonical_metric
from scripts.import_dr_manual_fill import InputError, run

WARSAW = ZoneInfo("Europe/Warsaw")
BOARD_MONTH = date(2019, 3, 1)


def _local(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=WARSAW)


def _week(user_id: int, day: str, **counts) -> dict:
    return {"user_id": user_id, "report_date": day, **counts}


@pytest_asyncio.fixture
async def accounts():
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        recruiter = User(
            email=f"drfill-r-{unique}@example.com",
            password_hash=hash_password("x"),
            name="Uzupełnienie R",
            role=UserRole.recruiter,
            is_active=True,
        )
        lead = User(
            email=f"drfill-d-{unique}@example.com",
            password_hash=hash_password("x"),
            name="Uzupełnienie D",
            role=UserRole.delivery_lead,
            is_active=True,
        )
        duplicate = User(
            email=f"drfill-dup-{unique}@example.com",
            password_hash=hash_password("x"),
            name="Uzupełnienie R",
            role=UserRole.recruiter,
            is_active=False,
            dynareporter_legacy_id=1_500_000_000 + int(unique[:7], 16),
        )
        client = Client(name=f"DR Fill Client {unique}")
        db.add_all([recruiter, lead, duplicate, client])
        await db.commit()
        ids = {
            "recruiter": recruiter.id,
            "lead": lead.id,
            "duplicate": duplicate.id,
            "client_id": client.id,
            "client": client.name,
            "receipts": [],
        }
    yield ids
    async with AsyncSessionLocal() as db:
        params = {
            "users": [ids["recruiter"], ids["lead"]],
            "month": BOARD_MONTH,
            "client": ids["client"],
            "receipts": ids["receipts"],
        }
        for sql in (
            "DELETE FROM dr_kpi_body_leasing WHERE user_id = ANY(:users)",
            "DELETE FROM dr_placement_details WHERE user_id = ANY(:users)",
            "DELETE FROM dr_kpi_delivery_lead WHERE user_id = ANY(:users)",
            "DELETE FROM dr_clients WHERE name = :client",
            "DELETE FROM dr_board_monthly_report WHERE report_month = :month",
            "DELETE FROM dr_board_placement_clients WHERE report_month = :month",
            "DELETE FROM app_settings WHERE key = ANY(:receipts)",
        ):
            await db.execute(text(sql), params)
        await db.commit()


async def _apply(accounts: dict, payload: dict) -> dict:
    report = await run(payload, apply=True)
    accounts["receipts"].append(report["receipt"])
    return report


async def _milestones(db, start: date, end: date) -> dict:
    rows = (
        await db.execute(
            text(
                """
                SELECT stage::text AS stage, source, first_moved_by, count(*) AS n
                FROM analytics_kpi_milestones
                WHERE first_reached_at >= :start AND first_reached_at < :end
                GROUP BY 1, 2, 3
                """
            ),
            {"start": _local(start), "end": _local(end)},
        )
    ).all()
    return {(r.stage, r.source, r.first_moved_by): int(r.n) for r in rows}


@pytest.mark.asyncio
async def test_dry_run_writes_nothing_and_apply_counts_where_dynareporter_does(
    accounts,
) -> None:
    from app.services.competitions import dl_portfolio_counts
    from app.services.history_client_placements import client_placements
    from app.services.insights_dl_portfolio import _history_entries

    r, d, client = accounts["recruiter"], accounts["lead"], accounts["client"]
    payload = {
        "weeks": [
            _week(
                r,
                "2019-03-04",
                verifications=3,
                recommendations=2,
                interviews=1,
                placements=2,
            )
        ],
        "placements": [
            {"user_id": r, "placement_date": "2026-03-05", "client": client, "count": 2}
        ],
        "dl_months": [
            {"user_id": d, "report_month": "2026-10", "placements": 4, "requests": 1},
            {"user_id": d, "report_month": "2026-03", "placements": 1},
        ],
        "board_months": [{"report_month": "2019-03", "placements": 5}],
        "board_clients": [
            {"report_month": "2019-03", "client_name": client, "placement_count": 3}
        ],
    }

    dry = await run(payload, apply=False)
    assert dry["applied"] is False
    assert dry["changes"] == {
        "weeks": 1,
        "placements": 1,
        "dl_months": 2,
        "board_months": 1,
        "board_clients": 1,
    }
    # Klient jest tylko w NEXUS-ie — zapis dopisze go do klientów DynaReportera.
    assert dry["new_dr_clients"] == [client]
    assert dry["settled_months_touched"] == ["2026-03"]
    assert dry["months"]["dl_months"]["2026-10"] == {
        "requests": [0, 1],
        "placements": [0, 4],
    }
    async with AsyncSessionLocal() as db:
        written = await db.execute(
            text(
                "SELECT (SELECT count(*) FROM dr_kpi_body_leasing WHERE user_id = :r)"
                " + (SELECT count(*) FROM dr_kpi_delivery_lead WHERE user_id = :d)"
            ),
            {"r": r, "d": d},
        )
        assert written.scalar_one() == 0

    applied = await _apply(accounts, payload)
    assert applied["applied"] is True
    assert applied["receipt"].startswith("dr_manual_fill_")

    october = (_local(date(2026, 10, 1)), _local(date(2026, 11, 1)))
    march = (_local(date(2026, 3, 1)), _local(date(2026, 4, 1)))
    async with AsyncSessionLocal() as db:
        receipt = await db.execute(
            text("SELECT value->>'applied' FROM app_settings WHERE key = :k"),
            {"k": applied["receipt"]},
        )
        assert receipt.scalar_one() == "true"

        milestones = await _milestones(db, date(2019, 3, 1), date(2019, 4, 1))
        assert milestones[("verified", "dynareporter", r)] == 3
        assert milestones[("cv_sent", "dynareporter", r)] == 2
        assert milestones[("client_interview", "dynareporter", r)] == 1
        assert milestones[("hired", "dynareporter", r)] == 2
        # Rada: 5 placementów firmy, 2 mają osobę — bez osoby zostają 3.
        assert milestones[("hired", "dynareporter_board", None)] == 3
        assert (
            await count_canonical_metric(
                db,
                user_id=r,
                metric=KpiMetric.first_placements,
                since=_local(date(2019, 3, 1)),
                until=_local(date(2019, 4, 1)),
            )
            == 2
        )

        # Portfel DL: październik 2026 = 1–11.10 z wpisu (zapytania i placementy
        # z tego samego wpisu); od 12.10 liczy Tablica.
        entries = {e["dl_id"]: e for e in await _history_entries(db, *october)}
        assert int(entries[d]["placements"]) == 4
        after_cutover = (_local(date(2026, 10, 12)), october[1])
        assert d not in {e["dl_id"] for e in await _history_entries(db, *after_cutover)}
        # Liga i cel DL: wpis października nie wchodzi (mianownik hit ratio od
        # 12.10, wypłaty), miesiące 1–9.2026 — tak jak dotąd.
        assert (
            d
            not in (await dl_portfolio_counts(db, start=october[0], end=october[1]))[0]
        )
        assert (await dl_portfolio_counts(db, start=march[0], end=march[1]))[0][d] == 1

        clients_2026 = {
            c.client_id: c.count for c in await client_placements(db, *march)
        }
        assert clients_2026[accounts["client_id"]] == 2
        clients_2019 = {
            c.client_id: c.count
            for c in await client_placements(
                db, _local(date(2019, 3, 1)), _local(date(2019, 4, 1))
            )
        }
        assert clients_2019[accounts["client_id"]] == 3

    # Drugi przebieg: puste pole zostawia zapisaną wartość, liczba ją zastępuje.
    again = await _apply(
        accounts,
        {
            "weeks": [_week(r, "2019-03-04", placements=1)],
            "placements": [
                {
                    "user_id": r,
                    "placement_date": "2026-03-05",
                    "client": client,
                    "count": 1,
                }
            ],
            "dl_months": [
                {
                    "user_id": d,
                    "report_month": "2026-10",
                    "placements": 4,
                    "requests": 1,
                }
            ],
        },
    )
    assert again["changes"]["weeks"] == 1
    assert again["changes"]["placements"] == 1
    assert again["unchanged"]["dl_months"] == 1
    assert again["new_dr_clients"] == []
    async with AsyncSessionLocal() as db:
        week = (
            await db.execute(
                text(
                    "SELECT verifications, placements, days_worked "
                    "FROM dr_kpi_body_leasing WHERE user_id = :r"
                ),
                {"r": r},
            )
        ).one()
        assert tuple(week) == (3, 1, 5)
        placed = await db.execute(
            text("SELECT count(*) FROM dr_placement_details WHERE user_id = :r"),
            {"r": r},
        )
        assert placed.scalar_one() == 1
        milestones = await _milestones(db, date(2019, 3, 1), date(2019, 4, 1))
        assert milestones[("hired", "dynareporter", r)] == 1
        assert milestones[("hired", "dynareporter_board", None)] == 4


@pytest.mark.asyncio
async def test_refuses_accounts_clients_and_a_second_start_of_a_week(accounts) -> None:
    r = accounts["recruiter"]
    with pytest.raises(InputError, match="bez odpowiednika w NEXUS-ie"):
        await run(
            {"weeks": [_week(2_000_000_000, "2019-03-04", placements=1)]}, apply=False
        )
    with pytest.raises(InputError, match="konta-duplikaty"):
        await run(
            {"weeks": [_week(accounts["duplicate"], "2019-03-04", placements=1)]},
            apply=False,
        )
    with pytest.raises(InputError, match="nieznani klienci"):
        await run(
            {
                "placements": [
                    {
                        "user_id": r,
                        "placement_date": "2026-03-05",
                        "client": f"{accounts['client']} literówka",
                    }
                ]
            },
            apply=False,
        )

    await _apply(accounts, {"weeks": [_week(r, "2019-04-02", recommendations=2)]})
    with pytest.raises(InputError, match="ma już wpis od 2019-04-02"):
        await run({"weeks": [_week(r, "2019-04-01", recommendations=2)]}, apply=False)

    # DynaReporter bywa z dwoma wpisami w jednym tygodniu (na produkcji cztery
    # takie tygodnie) — poprawka każdego z nich przechodzi, nowy dzień nie.
    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                "INSERT INTO dr_kpi_body_leasing "
                "(user_id, report_date, week_number, recommendations) "
                "VALUES (:r, DATE '2019-04-03', 14, 1)"
            ),
            {"r": r},
        )
        await db.commit()
    fixed = await run(
        {"weeks": [_week(r, "2019-04-03", recommendations=3)]}, apply=False
    )
    assert fixed["changes"]["weeks"] == 1
    with pytest.raises(InputError, match="od 2019-04-02, 2019-04-03"):
        await run({"weeks": [_week(r, "2019-04-01", recommendations=2)]}, apply=False)
