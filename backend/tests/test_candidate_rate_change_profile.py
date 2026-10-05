"""Zmiana stawki z profilu i z karty rekomendacji (0418, D4).

* okno stawki w profilu pyta o trwające procesy — lista rekrutacji od
  „Zweryfikowany” (bez wcześniejszych i bez zamkniętych),
* zapis z profilu niesie źródło „profile”,
* stawka wpisana ręcznie na karcie od „Zweryfikowany” to zmiana stawki
  w procesie (źródło „card”); przed weryfikacją karta stawki nie zgłasza.
"""

from __future__ import annotations

from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy import select

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.models.candidate_rate_change import CandidateRateChange
from app.models.recruitment_pipeline import PipelineStage
from tests.test_candidate_rate_change import URL, _body, _pair


async def _changes(cand_id: int) -> list[CandidateRateChange]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(CandidateRateChange)
                    .where(CandidateRateChange.candidate_id == cand_id)
                    .order_by(CandidateRateChange.id)
                )
            ).all()
        )


async def test_active_processes_lists_only_from_verified(app_client: AsyncClient):
    verified = await _pair(PipelineStage.verified)
    res = await app_client.get(
        f"{URL}/active-processes",
        headers=verified["rec_h"],
        params={"candidate_id": verified["cand_id"]},
    )
    assert res.status_code == 200, res.text
    rows = res.json()
    assert [r["job_id"] for r in rows] == [verified["job_id"]]
    assert rows[0]["board_column"] == "verified"
    assert rows[0]["current_label"] == "110 zł/h"

    early = await _pair(PipelineStage.screening)
    res = await app_client.get(
        f"{URL}/active-processes",
        headers=early["rec_h"],
        params={"candidate_id": early["cand_id"]},
    )
    assert res.json() == []


async def test_profile_source_is_recorded(app_client: AsyncClient):
    p = await _pair(PipelineStage.cv_sent)
    res = await app_client.post(
        URL, headers=p["rec_h"], json=_body(p, "130", source="profile", reason="other")
    )
    assert res.status_code == 200, res.text
    assert res.json()["change"]["source"] == "profile"
    assert res.json()["change"]["status"] == "requested"


async def test_manual_card_rate_after_verified_opens_a_rate_change(
    app_client: AsyncClient,
):
    p = await _pair(PipelineStage.cv_sent)
    res = await app_client.put(
        "/api/recommendation-cards",
        headers=p["rec_h"],
        json={
            "candidate_id": p["cand_id"],
            "job_id": p["job_id"],
            "fields": {"rate": "130 zł/h netto"},
        },
    )
    assert res.status_code == 200, res.text
    changes = await _changes(p["cand_id"])
    assert len(changes) == 1
    assert changes[0].source == "card"
    assert changes[0].requested_amount == Decimal("130")
    assert changes[0].status == "requested"


async def test_card_rate_before_verified_does_not_open_a_case(app_client: AsyncClient):
    p = await _pair(PipelineStage.screening)
    res = await app_client.put(
        "/api/recommendation-cards",
        headers=p["rec_h"],
        json={
            "candidate_id": p["cand_id"],
            "job_id": p["job_id"],
            "fields": {"rate": "130 zł/h"},
        },
    )
    assert res.status_code == 200, res.text
    assert await _changes(p["cand_id"]) == []
