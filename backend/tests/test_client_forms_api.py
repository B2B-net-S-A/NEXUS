"""0522: trasy formularza CV klienta pary osoba × rekrutacja (z bazą, CI).

Model zastąpiony atrapą (``client_form_fill._call_model``); wzór to fikcyjny
formularz w kształcie SWZ CEZ (``tests/_client_form_docx.py``).
"""

from __future__ import annotations

import io
import json
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import docx
import pytest
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import UserRole
from app.services import client_form_fill, storage_service
from tests._client_form_docx import form_docx
from tests._jarvis_helpers import make_user

CV = (
    "Anna Fikcyjna\n07.2023 – obecnie Automation Test Engineer / Bank Przykładowy S.A.\n"
    "Umiejętności: SQL, Selenium WebDriver"
)


@pytest.fixture
def storage(tmp_path, monkeypatch) -> Path:
    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(storage_service, "JOB_FILES_DIR", tmp_path / "job_files")
    monkeypatch.setattr(storage_service, "CLIENT_FORMS_DIR", tmp_path / "client_forms")
    return tmp_path


@asynccontextmanager
async def _no_quota(*_args, **_kwargs):
    yield


@pytest.fixture
def model(monkeypatch):
    answers: list[dict] = []
    monkeypatch.setattr(client_form_fill, "api_key_configured", lambda _m: True)
    monkeypatch.setattr(client_form_fill, "ai_feature", _no_quota)
    monkeypatch.setattr(
        client_form_fill, "_call_model", lambda *_a: json.dumps(answers.pop(0))
    )
    return answers


async def _pair(document: str = "client_form") -> tuple[int, int]:
    async with AsyncSessionLocal() as db:
        client = Client(
            name=f"Formularz {uuid.uuid4().hex[:6]}", cv_client_document=document
        )
        db.add(client)
        await db.flush()
        job = Job(
            title=f"Tester {uuid.uuid4().hex[:6]}",
            status=JobStatus.published,
            client_id=client.id,
        )
        candidate = Candidate(
            name="Anna",
            lastname=f"Fikcyjna-{uuid.uuid4().hex[:6]}",
            email=f"form-{uuid.uuid4().hex[:6]}@example.com",
            raw_cv_text=CV,
        )
        db.add_all([job, candidate])
        await db.flush()
        stage = CandidateStage(
            candidate_id=candidate.id, job_id=job.id, stage=PipelineStage.verified
        )
        db.add(stage)
        await db.commit()
        return job.id, stage.id


async def _add_template(app_client, headers, job_id: int) -> None:
    resp = await app_client.post(
        f"/api/jobs/{job_id}/files",
        files={
            "file": (
                "Zal 4b Formularz CV.docx",
                form_docx(),
                "application/octet-stream",
            )
        },
        headers=headers,
    )
    assert resp.status_code == 201 and resp.json()["client_form"] is True, resp.text


@pytest.mark.asyncio
async def test_without_template_the_form_says_where_to_add_it(
    app_client, app_auth_headers, storage
):
    _, stage_id = await _pair()
    url = f"/api/candidates/stages/{stage_id}/client-form"
    got = await app_client.get(url, headers=app_auth_headers)
    assert got.status_code == 200, got.text
    assert got.json()["status"] == "no_template"
    assert got.json()["client_document"] == "client_form"
    refused = await app_client.post(f"{url}/fill", headers=app_auth_headers)
    assert refused.status_code == 409
    assert "Plikach rekrutacji" in refused.json()["detail"]


@pytest.mark.asyncio
async def test_fill_edit_refill_and_download(
    app_client, app_auth_headers, storage, model
):
    job_id, stage_id = await _pair()
    await _add_template(app_client, app_auth_headers, job_id)
    url = f"/api/candidates/stages/{stage_id}/client-form"
    assert (await app_client.get(url, headers=app_auth_headers)).json()[
        "status"
    ] == "not_filled"

    model.append(
        {
            "fields": [
                {
                    "id": "t1.r1.c1",
                    "value": "Bank Przykładowy S.A.",
                    "quote": "Bank Przykładowy S.A.",
                },
                {"id": "t2.r2.c2", "value": "TAK", "quote": "SQL"},
                {"id": "t2.r5.c3", "value": "9", "quote": "Selenium WebDriver"},
            ]
        }
    )
    filled = await app_client.post(f"{url}/fill", headers=app_auth_headers)
    assert filled.status_code == 200, filled.text
    body = filled.json()
    values = {item["id"]: item for item in body["fields"]}
    assert body["status"] == "filled" and body["message"] is None
    assert values["p2"]["value"].startswith("Anna Fikcyjna-")
    assert values["t1.r1.c1"]["source"] == "cv"
    assert values["t2.r5.c3"]["value"] is None  # ocena bez liczby w cytacie
    assert "t2.r5.c3" in body["missing"]

    edited = await app_client.put(
        url,
        json={"fields": {"t2.r5.c3": "6", "t1.r1.c1": ""}},
        headers=app_auth_headers,
    )
    assert edited.status_code == 200, edited.text
    edited_values = {item["id"]: item for item in edited.json()["fields"]}
    assert edited_values["t2.r5.c3"]["source"] == "recruiter"
    assert edited_values["t1.r1.c1"]["value"] is None
    unknown = await app_client.put(
        url, json={"fields": {"t99.r1.c1": "x"}}, headers=app_auth_headers
    )
    assert unknown.status_code == 422

    # Ponowne wypełnienie nie zdejmuje tego, co wpisał rekruter.
    model.append({"fields": [{"id": "t2.r5.c3", "value": "2", "quote": "SQL"}]})
    refilled = (await app_client.post(f"{url}/fill", headers=app_auth_headers)).json()
    assert {item["id"]: item for item in refilled["fields"]}["t2.r5.c3"]["value"] == "6"

    download = await app_client.get(f"{url}/docx", headers=app_auth_headers)
    assert download.status_code == 200, download.text
    assert download.headers["content-disposition"].startswith("attachment")
    document = docx.Document(io.BytesIO(download.content))
    assert document.tables[2].rows[5].cells[3].text == "6"
    assert (
        document.tables[2].rows[2].cells[2].text == ""
    )  # TAK z 1. wypełnienia zniknął

    async with AsyncSessionLocal() as db:
        actions = (
            (
                await db.execute(
                    text(
                        "SELECT action FROM activities WHERE entity_type = 'candidate' "
                        "AND action LIKE 'client_form_%' AND details->>'job_id' = :job "
                        "ORDER BY id"
                    ),
                    {"job": str(job_id)},
                )
            )
            .scalars()
            .all()
        )
    assert actions == ["client_form_filled", "client_form_saved", "client_form_filled"]


@pytest.mark.asyncio
async def test_model_down_leaves_a_form_to_fill_by_hand(
    app_client, app_auth_headers, storage, monkeypatch
):
    monkeypatch.setattr(client_form_fill, "api_key_configured", lambda _m: False)
    job_id, stage_id = await _pair()
    await _add_template(app_client, app_auth_headers, job_id)
    resp = await app_client.post(
        f"/api/candidates/stages/{stage_id}/client-form/fill", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["message"] == client_form_fill.MSG_UNAVAILABLE
    filled = [item for item in resp.json()["fields"] if item["value"]]
    assert [item["id"] for item in filled] == ["p2"]


@pytest.mark.asyncio
async def test_roles_without_candidate_documents_are_refused(
    app_client, app_auth_headers, storage
):
    _, stage_id = await _pair()
    _, viewer = await make_user(UserRole.user)
    url = f"/api/candidates/stages/{stage_id}/client-form"
    assert (await app_client.get(url, headers=viewer)).status_code == 403
    assert (await app_client.post(f"{url}/fill", headers=viewer)).status_code == 403
    assert (
        await app_client.get(
            "/api/candidates/stages/999999999/client-form", headers=app_auth_headers
        )
    ).status_code == 404


# ── PR 3: QC CV firmowego nie dotyczy klienta z formularzem (decyzja D3) ─────


@pytest.mark.asyncio
async def test_qc_gate_skips_company_cv_qc_for_form_clients(monkeypatch):
    from app.api import pipeline
    from app.core.config import settings
    from app.services import cv_qc

    monkeypatch.setattr(settings, "CV_QC_GATE_ENABLED", True)
    calls: list[int] = []

    async def _qc(db, *, candidate_id, job_id, user, stage):
        calls.append(job_id)

    monkeypatch.setattr(cv_qc, "assert_qc_passed", _qc)
    for document in ("client_form", "company_cv"):
        job_id, stage_id = await _pair(document)
        async with AsyncSessionLocal() as db:
            stage = await db.get(CandidateStage, stage_id)
            job = await db.get(Job, job_id)
            await pipeline._assert_cv_qc_gate(
                db,
                None,
                candidate_id=stage.candidate_id,
                job_id=job_id,
                stage_def=None,
                legacy_value="cv_sent",
                client_id=job.client_id,
            )
        if document == "client_form":
            assert calls == []
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_form_added_before_the_switch_is_recognized_on_first_view(
    app_client, app_auth_headers, storage
):
    """CEZ przed 0521: formularz leżał w Plikach, zanim klient przeszedł na
    formularz — nikt go nie oznaczył przy dodaniu."""
    job_id, stage_id = await _pair("company_cv")
    resp = await app_client.post(
        f"/api/jobs/{job_id}/files",
        files={
            "file": (
                "Zal 4a Formularz CV.docx",
                form_docx(),
                "application/octet-stream",
            )
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 201 and resp.json()["client_form"] is False
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        client = await db.get(Client, job.client_id)
        client.cv_client_document = "client_form"
        await db.commit()

    form = await app_client.get(
        f"/api/candidates/stages/{stage_id}/client-form", headers=app_auth_headers
    )
    assert form.status_code == 200, form.text
    assert form.json()["status"] == "not_filled"
    assert form.json()["template"]["filename"] == "Zal 4a Formularz CV.docx"
    listed = (
        await app_client.get(f"/api/jobs/{job_id}/files", headers=app_auth_headers)
    ).json()
    assert [item["client_form"] for item in listed["items"]] == [True]


# ── 0525: tabela punktowa (Excel) obok formularza (Word) ─────────────────────


def _rules_docx() -> bytes:
    import docx as python_docx

    document = python_docx.Document()
    document.add_paragraph(
        "Szczegółowy opis oceny. Punkty za lata w automatyzacji: 0 pkt do 2 lat, "
        "1 pkt więcej niż 2 lata, 2 pkt więcej niż 3 lata. ISTQB FL: 3 pkt."
    )
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_score_sheet_is_a_second_template_filled_with_points(
    app_client, app_auth_headers, storage, model
):
    from openpyxl import load_workbook

    from tests._client_score_xlsx import score_xlsx

    job_id, stage_id = await _pair()
    files_url = f"/api/jobs/{job_id}/files"

    async def upload(name: str, data: bytes) -> dict:
        resp = await app_client.post(
            files_url,
            files={"file": (name, data, "application/octet-stream")},
            headers=app_auth_headers,
        )
        assert resp.status_code == 201, resp.text
        return resp.json()

    form = await upload("Zal 4b Formularz CV.docx", form_docx())
    sheet = await upload("Zal 5b Tabela punktowa.xlsx", score_xlsx())
    await upload("Zal 5b Szczegolowy opis oceny.docx", _rules_docx())
    assert (form["client_form"], form["client_form_kind"]) == (True, "form")
    assert (sheet["client_form"], sheet["client_form_kind"]) == (True, "score")
    assert sheet["client_form_summary"].startswith("7 pól do wypełnienia")

    url = f"/api/candidates/stages/{stage_id}/client-form"
    model.append(
        {
            "fields": [
                {"id": "s0.r7.c4", "value": "TAK", "quote": "Automation Test Engineer"},
                {"id": "s0.r12.c4", "value": "2", "quote": "07.2023 – obecnie"},
                {"id": "s0.r13.c4", "value": "9", "quote": "Selenium WebDriver"},
            ]
        }
    )
    filled = await app_client.post(f"{url}/fill?kind=score", headers=app_auth_headers)
    assert filled.status_code == 200, filled.text
    body = filled.json()
    values = {item["id"]: item["value"] for item in body["fields"]}
    assert body["kind"] == "score"
    assert values["s0.r3.c2"] == "B2B.net S.A."
    assert values["s0.r12.c4"] == "2" and values["s0.r13.c4"] is None  # 9 > 5
    assert body["points"] == {"total": 2, "max": 13}
    # Formularz Word jest osobnym dokumentem tej pary.
    form_view = (await app_client.get(url, headers=app_auth_headers)).json()
    assert form_view["kind"] == "form" and form_view["status"] == "not_filled"

    download = await app_client.get(f"{url}/docx?kind=score", headers=app_auth_headers)
    assert download.status_code == 200, download.text
    assert download.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml"
    )
    assert ".xlsx" in download.headers["content-disposition"]
    workbook = load_workbook(io.BytesIO(download.content)).active
    assert workbook["D12"].value == 2 and workbook["D7"].value == "TAK"

    # Nowy Excel jako wzór zdejmuje tylko poprzednią tabelę, nie formularz.
    second = await upload("tabela v2.xlsx", score_xlsx())
    mark = await app_client.patch(
        f"{files_url}/{second['id']}",
        json={"client_form": True},
        headers=app_auth_headers,
    )
    assert mark.status_code == 200, mark.text
    listed = (await app_client.get(files_url, headers=app_auth_headers)).json()["items"]
    marked = {
        item["id"]: item["client_form_kind"] for item in listed if item["client_form"]
    }
    assert marked == {form["id"]: "form", second["id"]: "score"}


@pytest.mark.asyncio
async def test_points_follow_the_legend_of_the_score_template(
    app_client, app_auth_headers, storage, model
):
    """CEZ 26.11.2026: jedyny „Szczegółowy opis oceny” w rekrutacji to Excel
    oznaczony jako tabela punktowa, z zasadami w kolumnie „Legenda”. Bez
    osobnego pliku z zasadami punkty mają iść według legendy wzoru."""
    from tests._client_score_xlsx import score_xlsx_unheaded_maximum

    job_id, stage_id = await _pair()
    resp = await app_client.post(
        f"/api/jobs/{job_id}/files",
        files={
            "file": (
                "Zal 5 Szczegolowy opis oceny Tester.xlsx",
                score_xlsx_unheaded_maximum(),
                "application/octet-stream",
            )
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["client_form_kind"] == "score"

    model.append(
        {"fields": [{"id": "s0.r12.c4", "value": 2, "quote": "07.2023 – obecnie"}]}
    )
    url = f"/api/candidates/stages/{stage_id}/client-form"
    filled = await app_client.post(f"{url}/fill?kind=score", headers=app_auth_headers)
    assert filled.status_code == 200, filled.text
    values = {item["id"]: item["value"] for item in filled.json()["fields"]}
    assert values["s0.r12.c4"] == "2"

    # Formularz Word legendy nie dostaje: na stagingu wypełniał się z nią gorzej.
    from app.services import job_files

    async with AsyncSessionLocal() as db:
        assert await job_files.scoring_rules_text(db, job_id) == ""
        legend = await job_files.scoring_rules_text(db, job_id, score_legend=True)
    assert "1 pkt za każdy rok" in legend


@pytest.mark.asyncio
async def test_pdf_or_other_files_cannot_be_templates(
    app_client, app_auth_headers, storage
):
    job_id, _ = await _pair()
    resp = await app_client.post(
        f"/api/jobs/{job_id}/files",
        files={"file": ("opis.pdf", b"%PDF-1.4 opis", "application/octet-stream")},
        headers=app_auth_headers,
    )
    marked = await app_client.patch(
        f"/api/jobs/{job_id}/files/{resp.json()['id']}",
        json={"client_form": True},
        headers=app_auth_headers,
    )
    assert marked.status_code == 422
    assert marked.json()["detail"].startswith("Wzorem może być plik Word")


@pytest.mark.asyncio
async def test_years_grid_roles_and_screening_questions(
    app_client, app_auth_headers, storage, model
):
    """Lata liczy kod ze stanowisk; rekruter zdejmuje rolę i wysyła braki do screeningu."""
    job_id, stage_id = await _pair()
    await _add_template(app_client, app_auth_headers, job_id)
    url = f"/api/candidates/stages/{stage_id}/client-form"
    answer = {
        "fields": [],
        "roles": [
            {
                "key": "r1",
                "employer": "Bank Przykładowy S.A.",
                "title": "Automation Test Engineer",
                "start": "2023-07",
                "end": "obecnie",
                "quote": "07.2023 – obecnie Automation Test Engineer",
            }
        ],
        "years": [
            {
                "id": "t2.r2.c3",
                "roles": [
                    {
                        "key": "r1",
                        "level": "implied",
                        "quote": "Automation Test Engineer",
                    }
                ],
            },
            {"id": "t2.r5.c2", "roles": [], "skills_quote": "Selenium WebDriver"},
        ],
    }
    model.append(answer)
    filled = (await app_client.post(f"{url}/fill", headers=app_auth_headers)).json()
    values = {item["id"]: item for item in filled["fields"]}
    assert values["t2.r2.c3"]["value"] and values["t2.r2.c3"]["source"] == "cv"
    assert values["t2.r2.c3"]["years"]["basis"][0]["period"] == "07.2023 – obecnie"
    assert values["p3"]["value"] == values["t2.r2.c3"]["value"]
    assert values["t2.r5.c2"]["value"] is None
    assert values["t2.r5.c2"]["years"]["skills"] == "Selenium WebDriver"

    # Rola zdjęta w siatce → pole do uzupełnienia; braki do ściągi screeningu.
    saved = await app_client.put(
        f"{url}/years",
        json={"roles": {"t2.r2.c3": []}, "ask": ["t2.r2.c3", "t2.r5.c2"]},
        headers=app_auth_headers,
    )
    assert saved.status_code == 200, saved.text
    after = {item["id"]: item for item in saved.json()["fields"]}
    assert after["t2.r2.c3"]["value"] is None
    assert "t2.r2.c3" in saved.json()["missing"]
    assert after["t2.r5.c2"]["years"]["ask"] is True

    # Pole bez siatki lat → 422; wpis rekrutera nie gubi siatki.
    refused = await app_client.put(
        f"{url}/years", json={"roles": {"t1.r1.c1": []}}, headers=app_auth_headers
    )
    assert refused.status_code == 422
    typed = await app_client.put(
        url, json={"fields": {"t2.r5.c2": "1 rok"}}, headers=app_auth_headers
    )
    typed_value = {item["id"]: item for item in typed.json()["fields"]}["t2.r5.c2"]
    assert typed_value["source"] == "recruiter" and typed_value["years"]["ask"] is True

    # Ponowne wypełnienie zostawia pytania do screeningu i role zdjęte przez
    # rekrutera — klucz roli może się zmienić, dopasowanie po firmie i okresie.
    renamed = json.loads(json.dumps(answer).replace('"r1"', '"r7"'))
    model.append(renamed)
    refilled = (await app_client.post(f"{url}/fill", headers=app_auth_headers)).json()
    again = {item["id"]: item for item in refilled["fields"]}
    assert again["t2.r2.c3"]["years"]["ask"] is True
    assert again["t2.r2.c3"]["value"] is None
    assert [b["on"] for b in again["t2.r2.c3"]["years"]["basis"]] == [False]
    assert again["p3"]["value"] is not None


# ── 23.11.2026: na „QC CV” dopiero z formularzem (prośba DL CEZ) ─────────────


@pytest.mark.asyncio
async def test_qc_cv_waits_for_the_client_form(
    app_client, app_auth_headers, storage, monkeypatch
):
    from fastapi import HTTPException

    from app.core.config import settings
    from app.models.candidate_client_form import CandidateClientForm
    from app.models.user import User
    from app.services import pipeline_move_rules

    monkeypatch.setattr(settings, "DL_SKIPS_FILL_GATES", True)
    job_id, stage_id = await _pair()
    await _add_template(app_client, app_auth_headers, job_id)
    recruiter_id, _ = await make_user(UserRole.recruiter)
    lead_id, _ = await make_user(UserRole.delivery_lead)

    async def gate(user_id: int, target: str = "cv_qc", allow_skip: bool = True):
        async with AsyncSessionLocal() as db:
            stage = await db.get(CandidateStage, stage_id)
            return await pipeline_move_rules.assert_client_form_before_qc(
                db,
                candidate_id=stage.candidate_id,
                job=await db.get(Job, job_id),
                user=await db.get(User, user_id),
                target_column=target,
                allow_skip=allow_skip,
            )

    with pytest.raises(HTTPException) as refused:
        await gate(recruiter_id)
    assert refused.value.status_code == 409
    assert refused.value.detail["code"] == "CLIENT_FORM_REQUIRED"
    assert refused.value.detail["missing"] == ["client_form"]
    assert refused.value.detail["stage_id"] == stage_id
    assert (
        refused.value.detail["message"]
        == "Przed „QC CV” wypełnij formularz CV klienta."
    )
    # Skok ponad „QC CV” też czeka; ruch wstecz i na „Zweryfikowany” nie.
    with pytest.raises(HTTPException):
        await gate(recruiter_id, "cv_sent")
    assert await gate(recruiter_id, "verified") == []
    # Delivery Lead przechodzi i dostaje brak do śladu; ruch zbiorczy — nie.
    assert await gate(lead_id) == ["client_form"]
    with pytest.raises(HTTPException):
        await gate(lead_id, allow_skip=False)

    # Wypełniony formularz z pustymi polami wystarcza.
    async with AsyncSessionLocal() as db:
        stage = await db.get(CandidateStage, stage_id)
        db.add(
            CandidateClientForm(
                candidate_id=stage.candidate_id,
                job_id=job_id,
                kind="form",
                fields={},
                missing_count=9,
            )
        )
        await db.commit()
    assert await gate(recruiter_id) == []

    monkeypatch.setattr(settings, "CLIENT_FORM_QC_GATE_ENABLED", False)
    other_job, other_stage = await _pair()
    await _add_template(app_client, app_auth_headers, other_job)
    async with AsyncSessionLocal() as db:
        stage = await db.get(CandidateStage, other_stage)
        assert (
            await pipeline_move_rules.assert_client_form_before_qc(
                db,
                candidate_id=stage.candidate_id,
                job=await db.get(Job, other_job),
                user=await db.get(User, recruiter_id),
                target_column="cv_qc",
            )
            == []
        )


@pytest.mark.asyncio
async def test_company_cv_client_has_no_form_gate():
    from app.models.user import User
    from app.services import pipeline_move_rules

    job_id, stage_id = await _pair("company_cv")
    recruiter_id, _ = await make_user(UserRole.recruiter)
    async with AsyncSessionLocal() as db:
        stage = await db.get(CandidateStage, stage_id)
        assert (
            await pipeline_move_rules.assert_client_form_before_qc(
                db,
                candidate_id=stage.candidate_id,
                job=await db.get(Job, job_id),
                user=await db.get(User, recruiter_id),
                target_column="cv_qc",
            )
            == []
        )


@pytest.mark.asyncio
async def test_form_client_entering_qc_cv_gets_no_company_cv_qc_bell(monkeypatch):
    """Staging 23.11.2026: DL przesunął osobę CEZ na „QC CV”, a rekruterzy
    dostali „QC CV do poprawy” o CV firmowym, którego ten klient nie bierze."""
    from app.services import cv_qc

    rung: list[int] = []

    async def _failed(db, stage, *, user_id, persist):
        return {"passed": False, "override": None}

    async def _bell(db, stage, result):
        rung.append(stage.job_id)

    monkeypatch.setattr(cv_qc, "run_qc", _failed)
    monkeypatch.setattr(cv_qc, "_notify_recruiter_of_failed_qc", _bell)
    form_job, form_stage = await _pair("client_form")
    cv_job, cv_stage = await _pair("company_cv")
    await cv_qc.run_after_move(form_stage, None, notify_recruiter_on_fail=True)
    await cv_qc.run_after_move(cv_stage, None, notify_recruiter_on_fail=True)
    assert rung == [cv_job]


# ── 0756: plik wypełniony poza NEXUSEM, wgrany z dysku ───────────────────────


def _with_macros(content: bytes) -> bytes:
    import zipfile

    buffer = io.BytesIO(content)
    with zipfile.ZipFile(buffer, "a") as package:
        package.writestr("word/vbaProject.bin", b"makro")
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_uploaded_form_goes_to_qc_and_download_instead_of_the_nexus_fill(
    app_client, app_auth_headers, storage
):
    from fastapi import HTTPException

    from app.models.user import User
    from app.services import client_form_status, pipeline_move_rules

    job_id, stage_id = await _pair()
    await _add_template(app_client, app_auth_headers, job_id)
    recruiter_id, _ = await make_user(UserRole.recruiter)
    url = f"/api/candidates/stages/{stage_id}/client-form"

    async def gate() -> list[str]:
        async with AsyncSessionLocal() as db:
            stage = await db.get(CandidateStage, stage_id)
            return await pipeline_move_rules.assert_client_form_before_qc(
                db,
                candidate_id=stage.candidate_id,
                job=await db.get(Job, job_id),
                user=await db.get(User, recruiter_id),
                target_column="cv_qc",
            )

    with pytest.raises(HTTPException):
        await gate()

    async def upload(name: str, data: bytes, kind: str = "form"):
        return await app_client.post(
            f"{url}/upload?kind={kind}",
            files={"file": (name, data, "application/octet-stream")},
            headers=app_auth_headers,
        )

    # Odmowy: zły typ, makra, „PDF”, który nim nie jest, Excel bez wzoru tabeli.
    wrong = await upload("formularz.doc", b"stary word")
    assert wrong.status_code == 415
    assert wrong.json()["detail"].startswith("Wypełniony formularz wgraj")
    macros = await upload("formularz.docx", _with_macros(form_docx()))
    assert macros.status_code == 422 and "makrami" in macros.json()["detail"]
    fake_pdf = await upload("formularz.pdf", b"<html>")
    assert fake_pdf.status_code == 422
    assert (await upload("tabela.xlsx", b"x", kind="score")).status_code == 409
    assert (await upload("formularz.xlsx", b"x")).status_code == 415

    filled = form_docx()
    got = await upload("Formularz CV Anna — wypełniony.docx", filled)
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["uploaded"]["filename"] == "Formularz CV Anna — wypełniony.docx"
    assert body["uploaded"]["size"] == len(filled)
    assert body["uploaded"]["uploaded_at"]
    assert await gate() == []
    async with AsyncSessionLocal() as db:
        stage = await db.get(CandidateStage, stage_id)
        states = await client_form_status.job_states(db, job_id, [stage.candidate_id])
    assert states[stage.candidate_id].uploaded is True
    assert states[stage.candidate_id].missing == 0

    download = await app_client.get(f"{url}/docx", headers=app_auth_headers)
    assert download.status_code == 200, download.text
    assert download.content == filled
    assert ".docx" in download.headers["content-disposition"]

    # „Zastąp plik”: PDF zastępuje Word, stary plik znika z dysku.
    pdf = b"%PDF-1.4 wypelniony formularz"
    replaced = await upload("formularz.pdf", pdf)
    assert replaced.status_code == 200, replaced.text
    stored = list((storage / "client_forms").rglob("*"))
    assert [path.read_bytes() for path in stored if path.is_file()] == [pdf]
    download = await app_client.get(f"{url}/docx", headers=app_auth_headers)
    assert download.content == pdf
    assert download.headers["content-type"].startswith("application/pdf")

    # „Usuń”: wiersz założony samym wgraniem znika, bramka znów czeka.
    deleted = await app_client.delete(f"{url}/upload", headers=app_auth_headers)
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["uploaded"] is None
    assert deleted.json()["status"] == "not_filled"
    assert not [
        path for path in (storage / "client_forms").rglob("*") if path.is_file()
    ]
    with pytest.raises(HTTPException):
        await gate()
    again = await app_client.delete(f"{url}/upload", headers=app_auth_headers)
    assert again.status_code == 404


@pytest.mark.asyncio
async def test_removing_the_upload_keeps_the_nexus_fill(
    app_client, app_auth_headers, storage, model
):
    job_id, stage_id = await _pair()
    await _add_template(app_client, app_auth_headers, job_id)
    url = f"/api/candidates/stages/{stage_id}/client-form"
    model.append({"fields": []})
    assert (
        await app_client.post(f"{url}/fill", headers=app_auth_headers)
    ).status_code == 200
    up = await app_client.post(
        f"{url}/upload",
        files={"file": ("formularz.pdf", b"%PDF-1.4 x", "application/pdf")},
        headers=app_auth_headers,
    )
    assert up.status_code == 200 and up.json()["status"] == "filled"
    deleted = await app_client.delete(f"{url}/upload", headers=app_auth_headers)
    assert deleted.json()["status"] == "filled" and deleted.json()["uploaded"] is None
    download = await app_client.get(f"{url}/docx", headers=app_auth_headers)
    assert download.status_code == 200
    assert docx.Document(io.BytesIO(download.content))  # Word z wypełnienia NEXUSA


@pytest.mark.asyncio
async def test_upload_needs_candidate_write_access(app_client, storage):
    _, stage_id = await _pair()
    _, viewer = await make_user(UserRole.user)
    url = f"/api/candidates/stages/{stage_id}/client-form/upload"
    resp = await app_client.post(
        url,
        files={"file": ("formularz.pdf", b"%PDF-1.4 x", "application/pdf")},
        headers=viewer,
    )
    assert resp.status_code == 403
    assert (await app_client.delete(url, headers=viewer)).status_code == 403


# ── 0756: reguła klienta „doświadczenie = 10/10” ─────────────────────────────


SCALE_ANSWER = {
    "fields": [
        # Model ocenił „Staż w służbie zdrowia” na 9 bez doświadczenia w wierszu.
        {"id": "t2.r6.c3", "value": "9", "quote": "Selenium WebDriver"},
    ],
    "roles": [
        {
            "key": "r1",
            "employer": "Bank Przykładowy S.A.",
            "title": "Automation Test Engineer",
            "start": "2023-07",
            "end": "obecnie",
            "quote": "07.2023 – obecnie Automation Test Engineer",
        }
    ],
    "years": [
        {
            "id": "t2.r5.c2",
            "roles": [
                {"key": "r1", "level": "role", "quote": "Automation Test Engineer"}
            ],
        }
    ],
}


@pytest.mark.asyncio
async def test_scale_rule_fills_ten_where_the_row_has_experience(
    app_client, app_auth_headers, storage, model
):
    job_id, stage_id = await _pair()
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        client = await db.get(Client, job.client_id)
        client.client_form_scale_full_on_experience = True
        await db.commit()
    await _add_template(app_client, app_auth_headers, job_id)
    url = f"/api/candidates/stages/{stage_id}/client-form"
    model.append(SCALE_ANSWER)
    filled = (await app_client.post(f"{url}/fill", headers=app_auth_headers)).json()
    values = {item["id"]: item for item in filled["fields"]}
    assert values["t2.r5.c3"]["value"] == "10"
    assert values["t2.r5.c3"]["source"] == "client_rule"
    assert values["t2.r6.c3"]["value"] is None

    # Rola zdjęta w siatce → brak doświadczenia w wierszu → pole puste.
    saved = await app_client.put(
        f"{url}/years", json={"roles": {"t2.r5.c2": []}}, headers=app_auth_headers
    )
    after = {item["id"]: item for item in saved.json()["fields"]}
    assert after["t2.r5.c3"]["value"] is None

    # Wartość rekrutera wygrywa z regułą także po „Zapisz lata”.
    await app_client.put(
        url, json={"fields": {"t2.r5.c3": "7"}}, headers=app_auth_headers
    )
    saved = await app_client.put(
        f"{url}/years", json={"roles": {"t2.r5.c2": ["r1"]}}, headers=app_auth_headers
    )
    after = {item["id"]: item for item in saved.json()["fields"]}
    assert after["t2.r5.c3"]["value"] == "7"
    assert after["t2.r5.c3"]["source"] == "recruiter"


@pytest.mark.asyncio
async def test_without_the_client_flag_there_is_no_scale_rule(
    app_client, app_auth_headers, storage, model
):
    job_id, stage_id = await _pair()
    await _add_template(app_client, app_auth_headers, job_id)
    url = f"/api/candidates/stages/{stage_id}/client-form"
    model.append(SCALE_ANSWER)
    filled = (await app_client.post(f"{url}/fill", headers=app_auth_headers)).json()
    values = {item["id"]: item for item in filled["fields"]}
    assert values["t2.r5.c2"]["value"]  # lata z roli są
    assert values["t2.r5.c3"]["value"] is None  # skali nikt nie wpisał


@pytest.mark.asyncio
async def test_spare_rows_are_not_missing_in_the_window_nor_on_the_board(
    app_client, app_auth_headers, storage, model
):
    """23.11.2026: wolne wiersze wzoru nie liczą się do braków — okno i Tablica."""
    from app.services import client_form_status

    job_id, stage_id = await _pair()
    await _add_template(app_client, app_auth_headers, job_id)
    url = f"/api/candidates/stages/{stage_id}/client-form"
    model.append(
        {
            "fields": [
                {
                    "id": "t1.r1.c1",
                    "value": "Bank Przykładowy S.A.",
                    "quote": "Bank Przykładowy S.A.",
                },
            ]
        }
    )
    body = (await app_client.post(f"{url}/fill", headers=app_auth_headers)).json()
    assert {"t1.r1.c2", "t1.r1.c3"} <= set(body["missing"])
    spare_rows = {f"t1.r{row}.c{col}" for row in (2, 3) for col in (1, 2, 3, 4)}
    assert spare_rows <= set(body["spare"])
    assert not spare_rows & set(body["missing"])

    async with AsyncSessionLocal() as db:
        # Wiersz sprzed poprawki: licznik liczony z zapasowymi wierszami.
        await db.execute(
            text(
                "UPDATE candidate_client_forms SET missing_count = 99 WHERE job_id = :j"
            ),
            {"j": job_id},
        )
        await db.commit()
        candidate_id = (
            await db.execute(
                text("SELECT candidate_id FROM candidate_stages WHERE id = :s"),
                {"s": stage_id},
            )
        ).scalar_one()
        states = await client_form_status.job_states(db, job_id, [candidate_id])
    assert states[candidate_id].missing == len(body["missing"])
