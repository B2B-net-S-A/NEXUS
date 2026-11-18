"""Rada (R7): gotówka, pulpit finansowy, raporty PDF, Firma, filtr dokumentów."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.board_document import BoardCashPosition, BoardDocument, BoardReport
from tests.test_sales_companies_api import _headers, _user

API = "/api/supervisory-board"


@pytest.fixture
async def _clean():
    async with AsyncSessionLocal() as db:
        await db.execute(delete(BoardReport))
        await db.execute(delete(BoardCashPosition))
        await db.execute(delete(BoardDocument))
        await db.commit()
    yield


async def test_cash_admin_writes_board_reads_and_outlook_uses_it(
    app_client, _clean
) -> None:
    admin = await _user(role="admin")
    board = await _user(role="board")
    recruiter = await _user(role="recruiter")
    day = business_today() - timedelta(days=1)
    body = {"as_of": day.isoformat(), "amount": "8250000.50", "note": "wyciągi"}
    assert (
        await app_client.put(f"{API}/cash", json=body, headers=_headers(board))
    ).status_code == 403
    saved = await app_client.put(f"{API}/cash", json=body, headers=_headers(admin))
    assert saved.status_code == 200, saved.text
    # Ponowny zapis tego samego dnia poprawia wpis, nie dokłada drugiego.
    again = await app_client.put(
        f"{API}/cash", json={**body, "amount": "8300000"}, headers=_headers(admin)
    )
    assert again.json()["id"] == saved.json()["id"]
    future = await app_client.put(
        f"{API}/cash",
        json={**body, "as_of": (business_today() + timedelta(days=2)).isoformat()},
        headers=_headers(admin),
    )
    assert future.status_code == 422
    listing = (await app_client.get(f"{API}/cash", headers=_headers(board))).json()
    assert [item["amount"] for item in listing["items"]] == [8300000.0]
    assert (
        await app_client.get(f"{API}/cash", headers=_headers(recruiter))
    ).status_code == 403

    outlook = await app_client.get(f"{API}/outlook", headers=_headers(board))
    assert outlook.status_code == 200, outlook.text
    data = outlook.json()
    assert data["cash"] == {"as_of": day.isoformat(), "amount": 8.3, "note": "wyciągi"}
    # Bez sprawozdania nie ma EBITDA, więc nie ma zdolności ani wyceny — None, nie zero.
    assert data["current"]["ebitda"] is None
    assert data["year_end"]["year"] == business_today().year


async def test_reports_render_pdf_and_admin_archives(app_client, _clean) -> None:
    admin = await _user(role="admin")
    board = await _user(role="board")
    year = business_today().year
    month = business_today().month
    pdf = await app_client.get(
        f"{API}/reports/render",
        params={"kind": "monthly", "year": year, "month": month},
        headers=_headers(board),
    )
    assert pdf.status_code == 200, pdf.text
    assert pdf.content.startswith(b"%PDF")
    assert "Rada-raport-" in pdf.headers["content-disposition"]
    for params in (
        {"kind": "monthly", "year": year},
        {"kind": "annual", "year": year + 1},
        {"kind": "monthly", "year": year + 1, "month": 1},
    ):
        bad = await app_client.get(
            f"{API}/reports/render", params=params, headers=_headers(board)
        )
        assert bad.status_code == 422, params
    for kind in ("annual", "budget"):
        ok = await app_client.get(
            f"{API}/reports/render",
            params={"kind": kind, "year": year},
            headers=_headers(board),
        )
        assert ok.status_code == 200 and ok.content.startswith(b"%PDF"), kind

    body = {"kind": "budget", "year": year}
    assert (
        await app_client.post(f"{API}/reports", json=body, headers=_headers(board))
    ).status_code == 403
    saved = await app_client.post(f"{API}/reports", json=body, headers=_headers(admin))
    assert saved.status_code == 201, saved.text
    listing = (await app_client.get(f"{API}/reports", headers=_headers(board))).json()
    assert [item["title"] for item in listing["items"]] == [f"Budżet i prognoza {year}"]
    assert listing["years"][0] == year
    file = await app_client.get(
        f"{API}/reports/{saved.json()['id']}/file", headers=_headers(board)
    )
    assert file.status_code == 200 and file.content.startswith(b"%PDF")
    gone = await app_client.delete(
        f"{API}/reports/{saved.json()['id']}", headers=_headers(admin)
    )
    assert gone.status_code == 204


async def test_people_view_counts_exits_without_names(app_client, _clean) -> None:
    board = await _user(role="board")
    finance = await _user("finance_module", role="finance")
    resp = await app_client.get(
        f"{API}/people", params={"period": "year"}, headers=_headers(board)
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert set(data) >= {"placements", "contractors", "flows", "exits", "period"}
    assert data["exits"]["count"] == len(data["exits"]["items"])
    for item in data["exits"]["items"]:
        assert "candidate" not in item and "name" not in item
    assert (
        await app_client.get(f"{API}/people", headers=_headers(finance))
    ).status_code == 403


async def test_documents_filter_by_year_and_month_of_the_document(
    app_client, _clean
) -> None:
    board = await _user(role="board")
    async with AsyncSessionLocal() as db:
        db.add_all(
            [
                BoardDocument(
                    category="minutes_supervisory",
                    title="Protokół z posiedzenia",
                    doc_date=date(2026, 6, 12),
                    source="upload",
                ),
                BoardDocument(
                    category="resolution_supervisory",
                    title="Uchwała z czerwca",
                    krs_entry_date=date(2026, 6, 30),
                    source="krs",
                ),
                BoardDocument(
                    category="resolution_supervisory",
                    title="Uchwała z maja",
                    doc_date=date(2026, 5, 2),
                    source="upload",
                ),
                BoardDocument(
                    category="statute",
                    title="Statut",
                    doc_date=date(2025, 11, 24),
                    source="upload",
                ),
            ]
        )
        await db.commit()

    june = (
        await app_client.get(
            f"{API}/documents",
            params={"year": 2026, "month": 6},
            headers=_headers(board),
        )
    ).json()
    assert sorted(d["title"] for d in june["items"]) == [
        "Protokół z posiedzenia",
        "Uchwała z czerwca",
    ]
    counts = {c["key"]: c["total"] for c in june["categories"]}
    assert counts["resolution_supervisory"] == 1 and counts["statute"] == 0
    assert june["years"] == [2026, 2025]
    year = (
        await app_client.get(
            f"{API}/documents", params={"year": 2026}, headers=_headers(board)
        )
    ).json()
    assert len(year["items"]) == 3
    assert (
        await app_client.get(
            f"{API}/documents", params={"month": 6}, headers=_headers(board)
        )
    ).status_code == 422
