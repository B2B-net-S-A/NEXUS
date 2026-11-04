"""Porównanie przeglądu DL (D10) nazywa pominięte uwagi QC tak jak okno osoby
(audyt 48 h, 13.10.2026).

Okno przeglądu jednej osoby (`build_context`) pokazuje ryzyko `qc_dismissed`
(„Pominięte uwagi blokujące QC”), a kolejka porównania (`build_queue`) dla tej
samej pary mówiła `qc_overridden` („Przesunięte mimo uwag QC”), bo nie
dostawała liczby pominięć. Delivery Lead widział dwie różne historie.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import dl_review as svc
from app.services import move_requirements


@pytest.fixture
def queue(monkeypatch: pytest.MonkeyPatch):
    async def access_for(_db, _user, _job):
        return SimpleNamespace()

    async def load_batch(_db, _job, ids, *, now):
        return SimpleNamespace(facts={cid: object() for cid in ids})

    def person(_batch, _job, candidate_id, *, access, budget_max, qc_status, **kw):
        risks = svc.risks_for(
            eligibility_reason=None,
            eligibility_code=None,
            employed_elsewhere=[],
            worked_at_client=None,
            deal_breaker_hits=0,
            over_budget_by=None,
            sent_to_client_before=[],
            red_flags=None,
            qc_status=qc_status,
            qc_dismissed=kw.get("qc_dismissed", 0),
        )
        return {
            "candidate_id": candidate_id,
            "risks": risks,
            "assessment": {"overall_fit": None, "overall_fit_label": None},
            "requirements": [],
            "_before": [],
        }

    statuses = {
        (1, 50): {"status": "overridden", "dismissed_blocking": 2},
        (2, 50): {"status": "overridden", "dismissed_blocking": 0},
    }

    async def qc_statuses(_db, pairs):
        return {pair: statuses[pair] for pair in pairs if pair in statuses}

    monkeypatch.setattr(svc, "access_for", access_for)
    monkeypatch.setattr(svc, "_load_batch", load_batch)
    monkeypatch.setattr(svc, "_person", person)
    monkeypatch.setattr(svc, "_budget", lambda _job: {"max_hourly": None})
    monkeypatch.setattr(move_requirements, "qc_statuses", qc_statuses)


def _task(candidate_id: int) -> SimpleNamespace:
    return SimpleNamespace(
        candidate_id=candidate_id, job_id=50, qc_status="overridden", since=None
    )


@pytest.mark.asyncio
async def test_queue_names_dismissed_findings_like_the_person_window(queue) -> None:
    rows = await svc.build_queue(
        object(), user=object(), job=SimpleNamespace(id=50), tasks=[_task(1), _task(2)]
    )
    codes = {row["candidate_id"]: [r["code"] for r in row["risks"]] for row in rows}
    assert codes[1] == ["qc_dismissed"]
    assert codes[2] == ["qc_overridden"]
