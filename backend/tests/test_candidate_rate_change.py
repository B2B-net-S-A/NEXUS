"""Zmiana stawki kandydata w trakcie procesu (0418, decyzje Artura 04.10.2026).

Pilnuje reguły ``services/candidate_rate_change.change_rate``:

* przed „Zweryfikowany” — wpis bez powiadomień (stawka się dopiero ustala),
* od „Zweryfikowany” — dzwonek DL i Head of Recruitment (informacja),
* wzrost po „CV wysłane” — ZADANIE DL (typ ``candidate_rate_change_task``),
* spadek i „pomyłka przy wpisie” — bez zadania,
* ta sama stawka — nic się nie dzieje,
* druga zmiana zastępuje otwartą sprawę (``superseded``),
* rekruter nie widzi w dzwonku stawki do klienta ani marży,
* autor zmiany nie dostaje dzwonka o własnej zmianie,
* historia stawek pokazuje stawkę zgłoszoną i tę sprzed zmiany.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy import select

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.models.candidate_rate_change import CandidateRateChange
from app.models.notification import Notification, NotificationType
from app.models.recruitment_pipeline import PipelineStage
from app.models.user import UserRole
from tests.test_interview_cycle import _client_interview, _user

URL = "/api/rate-changes"


async def _pair(
    stage: PipelineStage,
    *,
    rate: Decimal | None = Decimal("110"),
    client_rate: Decimal | None = None,
) -> dict:
    from app.models.candidate import Candidate, CandidateStatus
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.recruitment_pipeline import CandidateStage

    rec_id, rec_h = await _user(UserRole.recruiter)
    dl_id, dl_h = await _user(UserRole.delivery_lead)
    hor_id, hor_h = await _user(UserRole.head_of_recruitment)
    tag = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"RateClient-{tag}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"RateJob-{tag}",
            status=JobStatus.published,
            client_id=client.id,
            recruiter_id=rec_id,
            delivery_lead_id=dl_id,
        )
        cand = Candidate(
            name="Bartek",
            lastname=f"Stawka-{tag}",
            email=f"rate-cand-{tag}@example.com",
            status=CandidateStatus.active,
        )
        db.add_all([job, cand])
        await db.flush()
        db.add(
            CandidateStage(
                candidate_id=cand.id,
                job_id=job.id,
                stage=stage,
                moved_by=rec_id,
                expected_rate_value=rate,
                expected_rate_unit="hourly" if rate is not None else None,
                expected_rate_currency="PLN" if rate is not None else None,
                client_rate_value=client_rate,
                client_rate_unit="hourly" if client_rate is not None else None,
                client_rate_currency="PLN" if client_rate is not None else None,
            )
        )
        await db.commit()
        return {
            "rec_id": rec_id,
            "rec_h": rec_h,
            "dl_id": dl_id,
            "dl_h": dl_h,
            "hor_id": hor_id,
            "hor_h": hor_h,
            "job_id": job.id,
            "cand_id": cand.id,
            "client_id": client.id,
        }


async def _notes(change_id: int) -> dict[int, Notification]:
    async with AsyncSessionLocal() as db:
        rows = (
            await db.scalars(
                select(Notification).where(
                    Notification.related_entity_type == "candidate_rate_change",
                    Notification.related_entity_id == change_id,
                )
            )
        ).all()
    return {n.user_id: n for n in rows}


def _body(p: dict, amount: str, **extra) -> dict:
    return {
        "candidate_id": p["cand_id"],
        "job_id": p["job_id"],
        "amount": amount,
        **extra,
    }


async def test_before_verified_rate_change_is_recorded_without_notifications(
    app_client: AsyncClient,
):
    p = await _pair(PipelineStage.screening)
    res = await app_client.post(URL, headers=p["rec_h"], json=_body(p, "125"))
    assert res.status_code == 200, res.text
    change = res.json()["change"]
    assert change["status"] == "noted"
    assert change["requires_decision"] is False
    assert change["previous"]["label"] == "110 zł/h"
    assert await _notes(change["id"]) == {}


async def test_from_verified_dl_and_hor_get_information_not_a_task(
    app_client: AsyncClient,
):
    p = await _pair(PipelineStage.verified)
    res = await app_client.post(
        URL, headers=p["rec_h"], json=_body(p, "125", note="ma drugą ofertę")
    )
    assert res.status_code == 200, res.text
    change = res.json()["change"]
    assert change["status"] == "noted"
    notes = await _notes(change["id"])
    assert notes[p["dl_id"]].notification_type == NotificationType.candidate_rate_change
    assert (
        notes[p["hor_id"]].notification_type == NotificationType.candidate_rate_change
    )
    assert "110 zł/h → 125 zł/h" in notes[p["dl_id"]].message
    assert "ma drugą ofertę" in notes[p["dl_id"]].message
    # Autor (rekruter kandydata) nie dostaje dzwonka o własnej zmianie.
    assert p["rec_id"] not in notes


async def test_rise_after_cv_sent_is_a_dl_task_with_margin(app_client: AsyncClient):
    p = await _pair(PipelineStage.client_interview, client_rate=Decimal("150"))
    res = await app_client.post(URL, headers=p["rec_h"], json=_body(p, "125"))
    assert res.status_code == 200, res.text
    change = res.json()["change"]
    assert change["status"] == "requested"
    assert change["requires_decision"] is True
    notes = await _notes(change["id"])
    dl = notes[p["dl_id"]]
    assert dl.notification_type == NotificationType.candidate_rate_change_task
    assert "Do klienta 150 zł/h, marża 40 → 25 zł/h." in dl.message
    assert (
        notes[p["hor_id"]].notification_type == NotificationType.candidate_rate_change
    )

    async with AsyncSessionLocal() as db:
        row = await db.get(CandidateRateChange, change["id"])
        assert row.board_column == "client_interview"
        assert row.previous_hourly == Decimal("110.00")
        assert row.requested_hourly == Decimal("125.00")


async def test_recruiter_bell_does_not_carry_client_rate(app_client: AsyncClient):
    p = await _pair(PipelineStage.cv_sent, client_rate=Decimal("150"))
    res = await app_client.post(URL, headers=p["dl_h"], json=_body(p, "130"))
    assert res.status_code == 200, res.text
    notes = await _notes(res.json()["change"]["id"])
    assert p["dl_id"] not in notes
    recruiter = notes[p["rec_id"]]
    assert recruiter.title == "Ktoś zmienił stawkę Twojego kandydata"
    assert "Do klienta" not in recruiter.message
    assert "marża" not in recruiter.message
    assert "Do klienta 150 zł/h" in notes[p["hor_id"]].message


async def test_drop_and_typo_are_information_only(app_client: AsyncClient):
    p = await _pair(PipelineStage.cv_sent)
    drop = await app_client.post(URL, headers=p["rec_h"], json=_body(p, "100"))
    assert drop.status_code == 200, drop.text
    assert drop.json()["change"]["requires_decision"] is False

    typo = await app_client.post(
        URL, headers=p["rec_h"], json=_body(p, "190", reason="typo")
    )
    assert typo.status_code == 200, typo.text
    change = typo.json()["change"]
    assert change["requires_decision"] is False
    notes = await _notes(change["id"])
    assert notes[p["dl_id"]].notification_type == NotificationType.candidate_rate_change


async def test_same_rate_changes_nothing(app_client: AsyncClient):
    p = await _pair(PipelineStage.verified)
    res = await app_client.post(
        URL, headers=p["rec_h"], json=_body(p, "880", unit="daily")
    )
    assert res.status_code == 200, res.text
    # 880 zł/dzień = 110 zł/h — ta sama stawka w innej jednostce.
    assert res.json() == {"unchanged": True, "change": None}


async def test_second_rise_supersedes_the_open_case(app_client: AsyncClient):
    p = await _pair(PipelineStage.cv_sent)
    first = await app_client.post(URL, headers=p["rec_h"], json=_body(p, "125"))
    second = await app_client.post(URL, headers=p["rec_h"], json=_body(p, "135"))
    assert first.status_code == 200 and second.status_code == 200, second.text
    # Sprawa czeka na decyzję DL — „było” to stawka, z którą CV poszło do klienta.
    assert second.json()["change"]["previous"]["label"] == "110 zł/h"

    view = await app_client.get(
        URL,
        headers=p["dl_h"],
        params={"candidate_id": p["cand_id"], "job_id": p["job_id"]},
    )
    assert view.status_code == 200, view.text
    data = view.json()
    assert [c["status"] for c in data["changes"]] == ["requested", "superseded"]
    assert data["current"]["label"] == "135 zł/h"
    assert data["cv_at_client"] is True and data["notifies"] is True


async def test_correction_after_a_rise_keeps_the_dl_decision(app_client: AsyncClient):
    """Przegląd #2028: korekta 180 → 170 (także „pomyłka przy wpisie”) przy CV
    wysłanym za 110 nadal czeka na decyzję DL — zadanie nie znika po cichu."""

    p = await _pair(PipelineStage.cv_sent)
    first = await app_client.post(URL, headers=p["rec_h"], json=_body(p, "180"))
    fix = await app_client.post(
        URL, headers=p["rec_h"], json=_body(p, "170", reason="typo")
    )
    assert first.status_code == 200 and fix.status_code == 200, fix.text
    change = fix.json()["change"]
    assert change["status"] == "requested"
    assert change["requires_decision"] is True
    assert change["previous"]["label"] == "110 zł/h"

    # Zejście do stawki klienta lub niżej zamyka potrzebę decyzji.
    drop = await app_client.post(URL, headers=p["rec_h"], json=_body(p, "105"))
    assert drop.json()["change"]["status"] == "noted"


async def test_typo_correction_does_not_return_as_rate_from(app_client: AsyncClient):
    """Przegląd #2028: literówka 15 zł/h poprawiona na 150 nie zostaje
    obserwacją — najniższa byłaby „Stawką od” kandydata."""

    p = await _pair(PipelineStage.verified, rate=Decimal("15"))
    res = await app_client.post(
        URL, headers=p["rec_h"], json=_body(p, "150", reason="typo")
    )
    assert res.status_code == 200, res.text
    overview = await app_client.get(
        f"/api/candidates/{p['cand_id']}/rate-overview", headers=p["hor_h"]
    )
    assert overview.status_code == 200, overview.text
    amounts = {
        Decimal(str(o["amount_hourly"]))
        for o in overview.json()["observations"]
        if o["amount_hourly"] is not None
    }
    assert Decimal("15") not in amounts
    assert Decimal("150") in amounts


async def test_view_hides_client_rate_from_recruiter(app_client: AsyncClient):
    p = await _pair(PipelineStage.cv_sent, client_rate=Decimal("150"))
    params = {"candidate_id": p["cand_id"], "job_id": p["job_id"]}
    as_rec = await app_client.get(URL, headers=p["rec_h"], params=params)
    as_dl = await app_client.get(URL, headers=p["dl_h"], params=params)
    assert as_rec.json()["client_rate"] is None
    assert as_dl.json()["client_rate"]["label"] == "150 zł/h"


async def test_recruitments_tab_patch_goes_through_the_same_rule(
    app_client: AsyncClient,
):
    p = await _pair(PipelineStage.cv_sent)
    res = await app_client.patch(
        f"/api/candidates/{p['cand_id']}/recruitments/{p['job_id']}/expected-rate",
        headers=p["rec_h"],
        json={"rate_value": "125", "rate_unit": "hourly", "rate_currency": "PLN"},
    )
    assert res.status_code == 200, res.text
    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(CandidateRateChange).where(
                CandidateRateChange.candidate_id == p["cand_id"]
            )
        )
    assert row is not None
    assert row.source == "recruitments_tab"
    assert row.status == "requested"


async def test_rate_history_shows_requested_and_previous_rate(app_client: AsyncClient):
    p = await _pair(PipelineStage.cv_sent)
    res = await app_client.post(URL, headers=p["rec_h"], json=_body(p, "125"))
    assert res.status_code == 200, res.text
    overview = await app_client.get(
        f"/api/candidates/{p['cand_id']}/rate-overview", headers=p["hor_h"]
    )
    assert overview.status_code == 200, overview.text
    by_source = {o["source"]: o for o in overview.json()["observations"]}
    assert Decimal(str(by_source["rate_requested"]["amount_hourly"])) == Decimal("125")
    # Wiersz etapu nadpisany zmianą nie dubluje się, a 110 zostaje w historii.
    stage_amounts = [
        Decimal(str(o["amount_hourly"]))
        for o in overview.json()["observations"]
        if o["source"] == "stage"
    ]
    assert stage_amounts == [Decimal("110")]


async def test_debrief_rate_change_creates_case_and_is_returned(
    app_client: AsyncClient,
):
    p = await _pair(PipelineStage.client_interview, client_rate=Decimal("150"))
    event_id = await _client_interview(
        owner_id=p["rec_id"],
        cand_id=p["cand_id"],
        job_id=p["job_id"],
        client_id=p["client_id"],
        ended_min_ago=10,
    )
    url = f"/api/interview-cycle/events/{event_id}/debrief"
    before = await app_client.put(
        url,
        headers=p["rec_h"],
        json={
            "outcome": "good",
            "offer_acceptance": "likely",
            "no_client_questions": True,
            "rate_change": {
                "amount": "125",
                "negotiable": "maybe",
                "note": "druga oferta",
            },
        },
    )
    assert before.status_code == 200, before.text
    out = before.json()
    assert out["current_rate_label"] == "125 zł/h"
    assert out["rate_change"]["status"] == "requested"
    assert out["rate_change"]["negotiable"] == "maybe"

    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(CandidateRateChange).where(
                CandidateRateChange.candidate_id == p["cand_id"]
            )
        )
        assert row.source == "debrief"
        assert row.feedback_id == out["id"]

    # Ponowny zapis debriefu z tą samą stawką nie zakłada drugiej sprawy.
    again = await app_client.put(
        url,
        headers=p["rec_h"],
        json={
            "outcome": "good",
            "offer_acceptance": "likely",
            "no_client_questions": True,
            "rate_change": {"amount": "125"},
        },
    )
    assert again.status_code == 200, again.text
    async with AsyncSessionLocal() as db:
        count = len(
            (
                await db.scalars(
                    select(CandidateRateChange.id).where(
                        CandidateRateChange.candidate_id == p["cand_id"]
                    )
                )
            ).all()
        )
    assert count == 1

    # Przegląd #2028: późniejsza korekta (120) nie wraca do 125 przy kolejnym
    # zapisie debriefu, a DL nie dostaje drugiego zadania.
    later = await app_client.post(URL, headers=p["rec_h"], json=_body(p, "120"))
    assert later.status_code == 200, later.text
    resave = await app_client.put(
        url,
        headers=p["rec_h"],
        json={
            "outcome": "good",
            "offer_acceptance": "likely",
            "questions": ["Jak wdrażał CI?"],
            "rate_change": {"amount": "125"},
        },
    )
    assert resave.status_code == 200, resave.text
    assert resave.json()["current_rate_label"] == "120 zł/h"
    async with AsyncSessionLocal() as db:
        count = len(
            (
                await db.scalars(
                    select(CandidateRateChange.id).where(
                        CandidateRateChange.candidate_id == p["cand_id"]
                    )
                )
            ).all()
        )
    assert count == 2


def test_migration_and_entrypoint_share_the_schema() -> None:
    from pathlib import Path

    from app.services import candidate_rate_change_schema as schema

    backend = Path(__file__).resolve().parents[1]
    entrypoint = (backend / "entrypoint.sh").read_text(encoding="utf-8")
    migration = (
        backend / "alembic" / "versions" / "0418_candidate_rate_changes.py"
    ).read_text(encoding="utf-8")
    for stmt in schema.NOTIFICATION_ENUM_DDL:
        assert stmt in entrypoint
    assert "candidate_rate_change_schema as _rate_change" in entrypoint
    assert "*_RATE_CHANGE_DDL" in entrypoint
    assert "NOTIFICATION_ENUM_DDL" in migration and "ALL_DDL" in migration
