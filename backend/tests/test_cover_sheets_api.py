"""0626: trasy „Karty przed CV” (Credit Agricole, 29.10.2026) — z bazą, CI.

Wzór to fikcyjna karta w układzie CA (``tests/_cover_sheet_docx.py``).
"""

from __future__ import annotations

import asyncio
import io
import uuid
from decimal import Decimal

import docx
import pytest

from app.api import cover_sheets
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import UserRole
from tests._cover_sheet_docx import cover_docx
from tests._jarvis_helpers import make_user

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


async def _pair(*, stored_rate: Decimal | None = None) -> tuple[int, int, int]:
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Bank Karta {uuid.uuid4().hex[:6]}")
        db.add(client)
        await db.flush()
        job = Job(
            title="Inżynier danych",
            status=JobStatus.published,
            client_id=client.id,
            must_skills=[{"name": "Oracle"}, {"name": "Ab Initio"}],
        )
        candidate = Candidate(
            name="Anna",
            lastname="Przykładowa",
            email=f"karta-{uuid.uuid4().hex[:6]}@example.com",
            years_it_experience=7,
            city="Kraków",
            skills=[{"name": "Oracle"}],
        )
        db.add_all([job, candidate])
        await db.flush()
        db.add(
            CandidateStage(
                candidate_id=candidate.id,
                job_id=job.id,
                stage=PipelineStage.cv_sent,
                client_rate_value=stored_rate,
                client_rate_unit="hourly" if stored_rate is not None else None,
                client_rate_currency="PLN" if stored_rate is not None else None,
            )
        )
        await db.commit()
        return client.id, job.id, candidate.id


async def _upload(app_client, headers, client_id: int, content: bytes):
    return await app_client.put(
        f"/api/clients/{client_id}/cover-sheet-template",
        files={"file": ("Karta przed CV.docx", content, DOCX)},
        headers=headers,
    )


def _texts(content: bytes) -> list[str]:
    return [p.text for p in docx.Document(io.BytesIO(content)).paragraphs]


@pytest.mark.asyncio
async def test_client_without_template_has_no_sheet(app_client, app_auth_headers):
    _, job_id, candidate_id = await _pair()
    url = f"/api/candidates/{candidate_id}/recruitments/{job_id}/cover-sheet"
    got = await app_client.get(url, headers=app_auth_headers)
    assert got.status_code == 200, got.text
    assert got.json() == {"enabled": False}
    refused = await app_client.get(f"{url}/docx", headers=app_auth_headers)
    assert refused.status_code == 409


@pytest.mark.asyncio
async def test_template_upload_sheet_edit_and_download(app_client, app_auth_headers):
    client_id, job_id, candidate_id = await _pair()
    bad = await _upload(
        app_client, app_auth_headers, client_id, cover_docx(labels=False)
    )
    assert bad.status_code == 422 and "nie rozpoznał" in bad.json()["detail"]

    uploaded = await _upload(app_client, app_auth_headers, client_id, cover_docx())
    assert uploaded.status_code == 200, uploaded.text
    meta = uploaded.json()["template"]
    assert meta["filename"] == "Karta przed CV.docx"
    assert [item["id"] for item in meta["fields"]][:3] == ["name", "role", "level"]

    url = f"/api/candidates/{candidate_id}/recruitments/{job_id}/cover-sheet"
    sheet = (await app_client.get(url, headers=app_auth_headers)).json()
    assert sheet["enabled"] is True
    fields = {item["id"]: item for item in sheet["fields"]}
    assert fields["name"]["value"] == "Anna Przykładowa"
    assert fields["level"]["value"] == "Specjalista" and fields["level"]["to_check"]
    assert fields["level"]["source_label"] == "z 7 lat stażu — sprawdź"
    assert fields["experience"]["value"] == "7 lat"
    # Bez CV firmowego: umiejętności obowiązkowe, które osoba ma.
    assert fields["profile"]["value"] == "Oracle"
    assert fields["profile"]["source"] == "job_skills"
    assert sheet["md_rate"] is None and "rate" in sheet["missing"]

    # Bez stawki do klienta pliku nie ma.
    refused = await app_client.get(f"{url}/docx", headers=app_auth_headers)
    assert refused.status_code == 409
    assert refused.json()["detail"].startswith("Wpisz stawkę do klienta")

    assert (
        await app_client.put(
            url, json={"fields": {"level": "Senior"}}, headers=app_auth_headers
        )
    ).status_code == 422
    assert (
        await app_client.put(
            url, json={"fields": {"rate": "1"}}, headers=app_auth_headers
        )
    ).status_code == 422
    saved = await app_client.put(
        f"{url}?client_rate=162.33&client_rate_unit=hourly",
        json={"fields": {"level": "Expert"}},
        headers=app_auth_headers,
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["md_rate_label"] == "1 298,64"
    level = next(f for f in saved.json()["fields"] if f["id"] == "level")
    assert level["value"] == "Expert" and level["source"] == "dl"

    download = await app_client.get(
        f"{url}/docx?client_rate=162.33&client_rate_unit=hourly",
        headers=app_auth_headers,
    )
    assert download.status_code == 200, download.text
    assert download.headers["x-content-type-options"] == "nosniff"
    assert "Karta_Anna_Przyk" in download.headers["content-disposition"]
    texts = _texts(download.content)
    assert "Poziom doświadczenia: Expert" in texts
    assert "Wynagrodzenie: 1 298,64 PLN netto za 1 MD" in texts

    # Pusta poprawka = wraca wartość wyliczona.
    back = await app_client.put(
        url, json={"fields": {"level": ""}}, headers=app_auth_headers
    )
    assert next(f for f in back.json()["fields"] if f["id"] == "level")["value"] == (
        "Specjalista"
    )

    removed = await app_client.delete(
        f"/api/clients/{client_id}/cover-sheet-template", headers=app_auth_headers
    )
    assert removed.status_code == 204
    assert (await app_client.get(url, headers=app_auth_headers)).json() == {
        "enabled": False
    }


@pytest.mark.asyncio
async def test_stored_client_rate_fills_the_wage(app_client, app_auth_headers):
    client_id, job_id, candidate_id = await _pair(stored_rate=Decimal("150"))
    assert (
        await _upload(app_client, app_auth_headers, client_id, cover_docx())
    ).status_code == 200
    url = f"/api/candidates/{candidate_id}/recruitments/{job_id}/cover-sheet"
    sheet = (await app_client.get(url, headers=app_auth_headers)).json()
    assert sheet["md_rate_label"] == "1 200,00"
    assert sheet["rate_origin"] == "stored"
    download = await app_client.get(f"{url}/docx", headers=app_auth_headers)
    assert download.status_code == 200
    assert "Wynagrodzenie: 1 200,00 PLN netto za 1 MD" in _texts(download.content)


@pytest.mark.asyncio
async def test_recruiter_never_sees_the_sheet(app_client, app_auth_headers):
    client_id, job_id, candidate_id = await _pair(stored_rate=Decimal("150"))
    assert (
        await _upload(app_client, app_auth_headers, client_id, cover_docx())
    ).status_code == 200
    _, recruiter = await make_user(UserRole.recruiter)
    url = f"/api/candidates/{candidate_id}/recruitments/{job_id}/cover-sheet"
    assert (await app_client.get(url, headers=recruiter)).status_code == 403
    assert (await app_client.get(f"{url}/docx", headers=recruiter)).status_code == 403
    assert (
        await app_client.put(url, json={"fields": {}}, headers=recruiter)
    ).status_code == 403
    assert (
        await _upload(app_client, recruiter, client_id, cover_docx())
    ).status_code == 403



@pytest.mark.asyncio
async def test_second_save_waits_for_the_first_and_keeps_its_field():
    # Dwa zapisy naraz na parze bez poprawek, każdy we własnej transakcji
    # (klient testowy wykonuje żądania po kolei, więc wyścig tylko tak):
    # drugi czeka na blokadę wiersza, nie pada na kluczu i widzi pole pierwszego.
    _, job_id, candidate_id = await _pair()
    async with AsyncSessionLocal() as first, AsyncSessionLocal() as second:
        form = await cover_sheets._locked_edits(first, candidate_id, job_id)
        form.fields = {"location": {"value": "Gdańsk", "source": "dl"}}
        await first.flush()
        waiting = asyncio.create_task(
            cover_sheets._locked_edits(second, candidate_id, job_id)
        )
        await asyncio.sleep(0.3)
        assert not waiting.done()  # czeka na blokadę pierwszego zapisu
        await first.commit()
        other = await asyncio.wait_for(waiting, timeout=5)
        assert other.id == form.id
        assert other.fields["location"]["value"] == "Gdańsk"
        await second.rollback()
