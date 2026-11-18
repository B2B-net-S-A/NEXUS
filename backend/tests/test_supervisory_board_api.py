"""Rada (R1) z bazą: odpis KRS, wiersze z wzmianek, dzwonek, dokumenty i bramki ról."""

from __future__ import annotations

import pytest
from sqlalchemy import delete, func, select

from app.core.database import AsyncSessionLocal
from app.models.board_document import BoardDocument, BoardKrsSnapshot
from app.models.notification import Notification, NotificationType
from app.services.board import krs as krs_service
from tests.test_sales_companies_api import _headers, _user
from tests.test_supervisory_board_unit import _odpis

API = "/api/supervisory-board"


@pytest.fixture(autouse=True)
async def _clean_board_tables():
    async with AsyncSessionLocal() as db:
        await db.execute(delete(BoardDocument))
        await db.execute(delete(BoardKrsSnapshot))
        await db.commit()
    yield


async def _bells(user_id: int) -> int:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.notification_type == NotificationType.board_krs_entry,
            )
        )


async def test_refresh_stores_once_seeds_documents_and_bells_only_new_entries(
    app_client, monkeypatch
) -> None:
    admin = await _user(role="admin")
    board = await _user(role="board")
    payloads = [_odpis(entries=3), _odpis(entries=3), _odpis(entries=4)]

    async def fake_fetch(_krs: str) -> dict:
        return payloads.pop(0)

    monkeypatch.setattr(krs_service, "fetch_full_extract", fake_fetch)

    first = await app_client.post(f"{API}/krs/refresh", headers=_headers(admin))
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["changed"] is True and body["new_entries"] == 0
    assert body["documents_created"] == len(
        krs_service.document_seeds(krs_service.parse_odpis(_odpis()))
    )
    assert await _bells(board.id) == 0  # pierwszy odpis to stan zastany

    again = (
        await app_client.post(f"{API}/krs/refresh", headers=_headers(admin))
    ).json()
    assert again["changed"] is False and again["documents_created"] == 0

    third = (
        await app_client.post(f"{API}/krs/refresh", headers=_headers(admin))
    ).json()
    assert third["changed"] is True and third["new_entries"] == 1
    assert await _bells(board.id) == 1

    view = (await app_client.get(f"{API}/krs", headers=_headers(board))).json()[
        "snapshot"
    ]
    assert view["entries_count"] == 4
    assert view["management"]["functions"] == ["PREZES ZARZĄDU"]
    assert view["missing_filings"][0]["year"] == 2025


async def test_board_reads_admin_writes_others_are_denied(app_client) -> None:
    admin = await _user(role="admin")
    board = await _user(role="board")
    finance = await _user("finance_module", role="finance")
    recruiter = await _user()

    created = await app_client.post(
        f"{API}/documents",
        headers=_headers(admin),
        data={
            "category": "resolution_supervisory",
            "organ": "supervisory",
            "number": "1/2026",
            "title": "Uchwała RN — budżet 2027",
            "doc_date": "2026-11-30",
        },
        files={"file": ("uchwala.pdf", b"%PDF-1.4 test", "application/pdf")},
    )
    assert created.status_code == 201, created.text
    doc = created.json()
    assert doc["has_file"] is True and doc["source"] == "upload"

    listed = await app_client.get(
        f"{API}/documents",
        params={"category": "resolution_supervisory"},
        headers=_headers(board),
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [doc["id"]]
    counts = {c["key"]: c for c in listed.json()["categories"]}
    assert counts["resolution_supervisory"] == {
        "key": "resolution_supervisory",
        "total": 1,
        "without_file": 0,
    }

    file_resp = await app_client.get(
        f"{API}/documents/{doc['id']}/file", headers=_headers(board)
    )
    assert file_resp.status_code == 200 and file_resp.content.startswith(b"%PDF")

    for user in (finance, recruiter):
        assert (
            await app_client.get(f"{API}/documents", headers=_headers(user))
        ).status_code == 403
    assert (
        await app_client.patch(
            f"{API}/documents/{doc['id']}", json={"title": "x"}, headers=_headers(board)
        )
    ).status_code == 403
    assert (
        await app_client.delete(f"{API}/documents/{doc['id']}", headers=_headers(board))
    ).status_code == 403

    patched = await app_client.patch(
        f"{API}/documents/{doc['id']}",
        json={"subject": "przyjęcie budżetu na 2027", "organ": None},
        headers=_headers(admin),
    )
    assert patched.status_code == 200 and patched.json()["organ"] is None

    bad = await app_client.post(
        f"{API}/documents",
        headers=_headers(admin),
        data={"category": "nieznana", "title": "x"},
    )
    assert bad.status_code == 422

    wrong_type = await app_client.post(
        f"{API}/documents/{doc['id']}/file",
        headers=_headers(admin),
        files={"file": ("skrypt.exe", b"MZ", "application/octet-stream")},
    )
    assert wrong_type.status_code == 422

    assert (
        await app_client.delete(f"{API}/documents/{doc['id']}", headers=_headers(admin))
    ).status_code == 204


async def test_krs_row_cannot_be_deleted_but_takes_a_scan(
    app_client, monkeypatch
) -> None:
    admin = await _user(role="admin")

    async def fake_fetch(_krs: str) -> dict:
        return _odpis()

    monkeypatch.setattr(krs_service, "fetch_full_extract", fake_fetch)
    assert (
        await app_client.post(f"{API}/krs/refresh", headers=_headers(admin))
    ).status_code == 200
    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(
                select(BoardDocument).where(BoardDocument.krs_key == "approval:2025")
            )
        ).scalar_one()
    assert (
        await app_client.delete(f"{API}/documents/{row.id}", headers=_headers(admin))
    ).status_code == 409
    attached = await app_client.post(
        f"{API}/documents/{row.id}/file",
        headers=_headers(admin),
        files={"file": ("zwz-2026.pdf", b"%PDF-1.4 zwz", "application/pdf")},
    )
    assert attached.status_code == 200 and attached.json()["has_file"] is True
    assert attached.json()["source"] == "krs"


async def test_krs_before_first_fetch_is_empty_not_error(app_client) -> None:
    board = await _user(role="board")
    resp = await app_client.get(f"{API}/krs", headers=_headers(board))
    assert resp.status_code == 200 and resp.json() == {"snapshot": None}


async def test_summary_sums_archive_and_is_board_only(app_client) -> None:
    from datetime import date
    from decimal import Decimal
    import uuid

    from app.core.scheduling import business_today
    from app.models.finance_archive import FinanceArchiveDocument

    board = await _user(role="board")
    finance = await _user("finance_module", role="finance")
    year = business_today().year - 1
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        await db.execute(delete(FinanceArchiveDocument))
        for i, (kind, net, gross, gross_pln, currency, partner) in enumerate(
            [
                ("sale", "1000000.00", "1230000.00", "1230000.00", "PLN", "Klient A"),
                ("sale", "200000.00", "200000.00", "850000.00", "EUR", "Klient B"),
                ("cost", "800000.00", "984000.00", "984000.00", "PLN", "Dostawca"),
            ]
        ):
            db.add(
                FinanceArchiveDocument(
                    source_id=f"{tag}-{i}",
                    schema_name="t",
                    kind=kind,
                    issue_date=date(year, 3, 15),
                    partner_name=partner,
                    currency=currency,
                    net_amount=Decimal(net),
                    gross_amount=Decimal(gross),
                    gross_pln=Decimal(gross_pln),
                    file_type="pdf",
                    file_path=f"x/{tag}-{i}.pdf",
                    file_sha256="0" * 64,
                )
            )
        await db.commit()

    assert (
        await app_client.get(f"{API}/summary", headers=_headers(finance))
    ).status_code == 403
    resp = await app_client.get(f"{API}/summary", headers=_headers(board))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    row = next(y for y in body["years"] if y["year"] == year)
    # 1 mln PLN + 200 tys. EUR × 4,25 = 1,85 mln sprzedaży, 0,8 mln kosztów.
    assert row["sales"] == 1.85 and row["costs"] == 0.8 and row["result"] == 1.05
    assert [c["name"] for c in body["top_clients"]["items"]] == ["Klient A", "Klient B"]
    assert body["top_clients"]["items"][0]["share"] == 54.1
    assert set(body["orders"]) >= {"active", "ending", "potential_month", "year_end"}


async def test_budget_plan_admin_writes_board_reads(app_client) -> None:
    from app.core.scheduling import business_today
    from app.models.board_document import BoardBudget

    admin = await _user(role="admin")
    board = await _user(role="board")
    finance = await _user("finance_module", role="finance")
    year = business_today().year
    async with AsyncSessionLocal() as db:
        await db.execute(delete(BoardBudget))
        await db.commit()

    body = {
        "status": "draft",
        "months": [{"month": 1, "sales": "9850000", "costs": "9000000"}],
    }
    assert (
        await app_client.put(f"{API}/budget/{year}", json=body, headers=_headers(board))
    ).status_code == 403
    assert (
        await app_client.get(f"{API}/budget/{year}", headers=_headers(finance))
    ).status_code == 403
    saved = await app_client.put(
        f"{API}/budget/{year}", json=body, headers=_headers(admin)
    )
    assert saved.status_code == 200, saved.text
    january = saved.json()["months"][0]
    assert january["plan_sales"] == 9.85 and january["plan_costs"] == 9.0

    view = (
        await app_client.get(f"{API}/budget/{year}", headers=_headers(board))
    ).json()
    assert view["budget"]["status"] == "draft" and len(view["months"]) == 12

    cleared = await app_client.put(
        f"{API}/budget/{year}",
        json={
            "status": "draft",
            "months": [{"month": 1, "sales": None, "costs": None}],
        },
        headers=_headers(admin),
    )
    assert cleared.json()["months"][0]["plan_sales"] is None

    assert (
        await app_client.put(
            f"{API}/budget/{year + 5}", json=body, headers=_headers(admin)
        )
    ).status_code == 422
    assert (
        await app_client.put(
            f"{API}/budget/{year}",
            json={"status": "draft", "months": [{"month": 1}, {"month": 1}]},
            headers=_headers(admin),
        )
    ).status_code == 422
    assert (
        await app_client.put(
            f"{API}/budget/{year}",
            json={"status": "adopted", "resolution_document_id": 999999, "months": []},
            headers=_headers(admin),
        )
    ).status_code == 422


async def test_summary_months_by_sale_date_and_contractor_costs_split(
    app_client,
) -> None:
    """Faktura za kwiecień wystawiona 7 maja liczy się w kwietniu (data
    sprzedaży z eBI24), a koszty dzielą się na kontraktorów i biuro po folderze."""
    from datetime import date
    from decimal import Decimal
    import uuid

    from app.core.scheduling import business_today
    from app.models.board_document import BoardBudget, BoardBudgetLine
    from app.models.finance_archive import FinanceArchiveDocument

    board = await _user(role="board")
    year = business_today().year - 1
    tag = uuid.uuid4().hex[:8]
    rows = [
        # kind, issued, transactionDate, net, folder
        ("sale", date(year, 5, 7), f"{year}-04-30T00:00:00.000", "1000000.00", None),
        ("sale", date(year, 5, 8), "zła data", "500000.00", None),
        # Data sprzedaży sprzed ponad kwartału (korekta starej faktury) — data wystawienia.
        ("sale", date(year, 6, 2), f"{year - 1}-01-31T00:00:00.000", "-10000.00", None),
        (
            "cost",
            date(year, 5, 9),
            f"{year}-04-30T00:00:00.000",
            "700000.00",
            "Kontraktorzy/2025",
        ),
        ("cost", date(year, 4, 20), None, "100000.00", "BIURO"),
        ("cost", date(year, 4, 22), None, "50000.00", "Zakupy pozostałe"),
    ]
    async with AsyncSessionLocal() as db:
        await db.execute(delete(FinanceArchiveDocument))
        await db.execute(delete(BoardBudget))
        for i, (kind, issued, sold, net, folder) in enumerate(rows):
            db.add(
                FinanceArchiveDocument(
                    source_id=f"{tag}-{i}",
                    schema_name="t",
                    kind=kind,
                    issue_date=issued,
                    currency="PLN",
                    net_amount=Decimal(net),
                    gross_amount=Decimal(net),
                    gross_pln=Decimal(net),
                    folder=folder,
                    meta={"transactionDate": sold} if sold else {},
                    file_type="pdf",
                    file_path=f"x/{tag}-{i}.pdf",
                    file_sha256="0" * 64,
                )
            )
        budget = BoardBudget(year=year + 1, status="adopted")
        db.add(budget)
        await db.flush()
        db.add(
            BoardBudgetLine(
                budget_id=budget.id, month=1, line="sales", amount=Decimal("2500000")
            )
        )
        await db.commit()

    body = (await app_client.get(f"{API}/summary", headers=_headers(board))).json()
    months = {(m["year"], m["month"]): m for m in body["months"]}
    assert months[(year, 4)]["sales"] == 1.0
    assert months[(year, 5)]["sales"] == 0.5
    assert months[(year, 6)]["sales"] == -0.01
    assert (
        months[(year, 4)]["contractors"] == 0.7 and months[(year, 4)]["costs"] == 0.85
    )
    row = next(y for y in body["years"] if y["year"] == year)
    assert row["contractors"] == 0.7 and row["office"] == 0.15
    assert row["contractor_margin"] == 0.79 and row["contractor_margin_pct"] == 53.0
    assert row["result"] == 0.64 and row["result_pct"] == 43.0
    assert body["budgets"][str(year + 1)][0] == 2.5
    assert body["budgets"][str(year + 1)][1] is None
