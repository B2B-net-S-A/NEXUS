"""Pobranie „CV z chwili dodania” z rekrutacji zostawia ślad (audyt 22.10, F25).

Alarm masowego przeglądania CV (0508) liczy wyłącznie zdarzenia
``candidate_audit`` w ``activities``. Trasa
``GET /api/candidates/stages/{id}/cv/original/download`` oddawała bajty CV
kandydata bez wpisu, więc podgląd i zapis CV z Tablicy i panelu osoby były
dla alarmu niewidoczne. Bez bazy: trasa wołana wprost.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import app.models  # noqa: F401
from app.api import candidate_stage_cv as stage_cv_api
from app.services import candidate_audit


class _FakeDb:
    def __init__(self):
        self.commits = 0

    async def commit(self):
        self.commits += 1


def _snapshot(content):
    csv = SimpleNamespace(
        candidate_id=4242,
        original_cv_filename="resume.pdf",
        original_cv_content=content,
    )

    async def load_csv(db, stage_id, user, **kwargs):
        return csv

    async def load_bytes(_csv):
        return content

    return load_csv, load_bytes


@pytest.fixture
def recorded(monkeypatch):
    events: list[dict] = []

    def record(db, **kwargs):
        events.append(kwargs)

    monkeypatch.setattr(stage_cv_api.candidate_audit, "record_candidate_audit", record)
    monkeypatch.setattr(stage_cv_api, "snapshot_exists", lambda csv: True)
    return events


def _use_snapshot(monkeypatch, content):
    load_csv, load_bytes = _snapshot(content)
    monkeypatch.setattr(stage_cv_api, "_load_csv_for_stage", load_csv)
    monkeypatch.setattr(stage_cv_api, "load_original_cv_bytes", load_bytes)


@pytest.mark.asyncio
@pytest.mark.parametrize("disposition", ["attachment", "inline"])
async def test_download_records_audit_for_the_candidate(
    recorded, monkeypatch, disposition
) -> None:
    _use_snapshot(monkeypatch, b"%PDF-1.4 dummy")
    db = _FakeDb()
    res = await stage_cv_api.download_original_cv(
        55, SimpleNamespace(id=7), db, disposition=disposition
    )
    assert res.status_code == 200
    (event,) = recorded
    assert event["action"] == candidate_audit.DOCUMENT_DOWNLOADED
    assert event["user_id"] == 7
    assert event["entity_id"] == 4242
    assert event["details"] == {
        "stage_id": 55,
        "endpoint": "stage-cv-original",
        "disposition": disposition,
    }
    assert db.commits == 1


@pytest.mark.asyncio
async def test_missing_bytes_leave_no_audit(recorded, monkeypatch) -> None:
    _use_snapshot(monkeypatch, None)
    with pytest.raises(HTTPException) as exc:
        await stage_cv_api.download_original_cv(
            55, SimpleNamespace(id=7), _FakeDb(), disposition="attachment"
        )
    assert exc.value.status_code == 404
    assert recorded == []
