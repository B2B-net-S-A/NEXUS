"""Rada (R5): posiedzenia, zamrożony pakiet z dzwonkiem, obowiązki roku."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, func, select

from app.core.database import AsyncSessionLocal
from app.models.board_document import BoardDocument, BoardMeeting
from app.models.notification import Notification, NotificationType
from app.services.board import meetings
from app.services.board.krs import KrsFiling
from tests.test_sales_companies_api import _headers, _user

API = "/api/supervisory-board"


def _doc(category: str, title: str, day: date) -> SimpleNamespace:
    return SimpleNamespace(category=category, title=title, subject=None, doc_date=day)


def _meeting(day: date, status: str = "held") -> SimpleNamespace:
    return SimpleNamespace(held_on=day, status=status)


def test_obligations_from_krs_documents_and_meetings() -> None:
    today = date(2026, 11, 18)
    items = {
        item["key"]: item
        for item in meetings.obligations(
            today=today,
            filings=[
                KrsFiling(2025, "financial_statement", date(2026, 7, 10), 50),
                KrsFiling(2025, "approval", date(2026, 7, 10), 50),
            ],
            statement_years=set(),
            documents=[
                _doc(
                    "resolution_supervisory",
                    "Ocena sprawozdania za 2025",
                    date(2026, 5, 20),
                ),
                _doc(
                    "resolution_supervisory",
                    "Ocena sprawozdania za 2024",
                    date(2025, 5, 20),
                ),
            ],
            meetings=[
                _meeting(date(2026, 3, 1)),
                _meeting(date(2026, 6, 1)),
                _meeting(date(2026, 12, 10), "planned"),
                _meeting(date(2025, 12, 1)),
            ],
        )
    }
    assert items["statement_prepared"]["status"] == "done"
    assert items["board_assessment"]["status"] == "done"
    assert items["agm_approval"]["status"] == "done"
    assert items["krs_filing"]["evidence"] == "wzmianka w KRS z 2026-07-10"
    assert items["meetings"]["status"] == "pending"  # 2 z 3, do 31.12 jeszcze 43 dni
    assert items["meetings"]["evidence"] == "odbyte: 2, zaplanowane: 1"


def test_obligations_overdue_without_evidence() -> None:
    items = {
        item["key"]: item
        for item in meetings.obligations(
            today=date(2026, 8, 1),
            filings=[],
            statement_years=set(),
            documents=[
                _doc(
                    "resolution_general",
                    "Zatwierdzenie sprawozdania",
                    date(2026, 6, 20),
                )
            ],
            meetings=[],
        )
    }
    assert items["statement_prepared"]["status"] == "overdue"
    assert items["board_assessment"]["status"] == "overdue"
    assert items["agm_approval"]["status"] == "done"  # uchwała WZA w Dokumentach
    # Termin złożenia liczy się od daty uchwały: 20.06 + 15 dni.
    assert items["krs_filing"]["due"] == "2026-07-05"
    assert items["krs_filing"]["status"] == "overdue"
    assert items["meetings"]["status"] == "pending"


@pytest.fixture
async def _clean_meetings():
    async with AsyncSessionLocal() as db:
        await db.execute(delete(BoardMeeting))
        await db.execute(delete(BoardDocument))
        await db.commit()
    yield


async def _bells(user_id: int) -> int:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.notification_type == NotificationType.board_meeting_pack,
            )
        )


async def test_meeting_pack_frozen_rings_board_and_blocks_delete(
    app_client, _clean_meetings
) -> None:
    admin = await _user(role="admin")
    board = await _user(role="board")
    doc = await app_client.post(
        f"{API}/documents",
        headers=_headers(admin),
        data={"category": "resolution_management", "title": "Uchwała Zarządu nr 1"},
    )
    assert doc.status_code == 201, doc.text
    body = {
        "held_on": "2026-12-10",
        "kind": "remote",
        "title": "Posiedzenie IV kwartał",
        "agenda": [
            {"title": "Informacja Zarządu", "document_ids": [doc.json()["id"]]},
            {"title": "Budżet 2027", "document_ids": []},
        ],
    }
    created = await app_client.post(
        f"{API}/meetings", headers=_headers(admin), json=body
    )
    assert created.status_code == 201, created.text
    meeting_id = created.json()["id"]
    assert created.json()["has_pack"] is False

    frozen = await app_client.post(
        f"{API}/meetings/{meeting_id}/pack", headers=_headers(admin)
    )
    assert frozen.status_code == 200, frozen.text
    pack = frozen.json()["pack"]
    assert {"summary", "budget", "documents", "krs_entries", "statement"} <= set(pack)
    assert [d["title"] for d in pack["documents"]] == ["Uchwała Zarządu nr 1"]
    assert await _bells(board.id) == 1

    listing = (await app_client.get(f"{API}/meetings", headers=_headers(board))).json()
    assert listing["items"][0]["has_pack"] is True
    assert "pack" not in listing["items"][0]
    assert {o["key"] for o in listing["obligations"]} >= {"meetings", "krs_filing"}
    read = await app_client.get(f"{API}/meetings/{meeting_id}", headers=_headers(board))
    assert read.json()["pack"]["as_of"]

    blocked = await app_client.delete(
        f"{API}/meetings/{meeting_id}", headers=_headers(admin)
    )
    assert blocked.status_code == 409


async def test_meetings_board_reads_admin_writes(app_client, _clean_meetings) -> None:
    admin = await _user(role="admin")
    board = await _user(role="board")
    recruiter = await _user(role="recruiter")
    body = {"held_on": "2026-12-10", "title": "Posiedzenie"}
    assert (
        await app_client.post(f"{API}/meetings", headers=_headers(board), json=body)
    ).status_code == 403
    assert (
        await app_client.get(f"{API}/meetings", headers=_headers(recruiter))
    ).status_code == 403
    bad_doc = await app_client.post(
        f"{API}/meetings",
        headers=_headers(admin),
        json={**body, "agenda": [{"title": "x", "document_ids": [999999]}]},
    )
    assert bad_doc.status_code == 422
    bad_kind = await app_client.post(
        f"{API}/meetings", headers=_headers(admin), json={**body, "kind": "party"}
    )
    assert bad_kind.status_code == 422
    created = await app_client.post(
        f"{API}/meetings", headers=_headers(admin), json=body
    )
    meeting_id = created.json()["id"]
    cancelled = await app_client.put(
        f"{API}/meetings/{meeting_id}",
        headers=_headers(admin),
        json={**body, "status": "cancelled"},
    )
    assert cancelled.json()["status"] == "cancelled"
    assert (
        await app_client.post(
            f"{API}/meetings/{meeting_id}/pack", headers=_headers(admin)
        )
    ).status_code == 409
    assert (
        await app_client.delete(f"{API}/meetings/{meeting_id}", headers=_headers(admin))
    ).status_code == 204
