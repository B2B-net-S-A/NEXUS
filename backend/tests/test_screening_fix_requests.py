"""Prośba Delivery Leada o poprawki (D6, 08.10.2026).

„Wróć do poprawy” z „QC CV” niesie listę pól (`StageMove.fix_fields`).
Prośba to wersja `fix_requested` formularza screeningu (bez nowej kolumny na
etapie), otwarta, dopóki najnowszy wiersz pary to wiersz „Zweryfikowany”
z tego ruchu. Rekruter widzi ją w formularzu (pola „do poprawy”/„poprawione”),
w dzwonku i na liście „CV w drodze”.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.job import Job
from app.models.notification import Notification
from app.models.recruitment_pipeline import CandidateStage
from app.models.screening_form_version import ScreeningFormVersion
from app.models.user import UserRole
from app.services import screening_fix_requests as svc
from app.services import screening_form_rules as rules
from tests.test_board_tasks import _cleanup, _login, _move, _seed_user, _seed_world

QUESTIONS = [
    {"id": "q1", "question": "Jakie ma doświadczenie z Kafką?"},
    {"id": "q2", "question": "Dlaczego chce zmienić projekt?"},
]


# ── Jednostkowe ──────────────────────────────────────────────────────────────


def _job(**over):
    return SimpleNamespace(
        champion_profile={"screening_questions": QUESTIONS},
        pipeline_template_id=None,
        **over,
    )


def test_options_follow_the_form_order_and_carry_the_question_text() -> None:
    options = svc.fix_options(_job())
    keys = [o.key for o in options]
    assert keys[:2] == ["question:q1", "question:q2"]
    assert options[0].label == "Pytanie 1: Jakie ma doświadczenie z Kafką?"
    assert "field:overall_fit" in keys
    assert keys[-2:] == ["candidate_rate", "cv"]
    # Każde pole karty z formularza ma swój klucz (bez stawki — ma własny).
    for key in rules.FORM_CARD_FIELDS:
        assert f"field:{key}" in keys
    assert "field:rate" not in keys


def test_validate_dedupes_orders_and_refuses_unknown_keys() -> None:
    options = svc.fix_options(_job())
    assert svc.validate(["cv", "question:q2", "cv", " question:q1 "], options) == [
        "question:q1",
        "question:q2",
        "cv",
    ]
    assert svc.validate(None, options) == []
    with pytest.raises(HTTPException) as err:
        svc.validate(["question:q9"], options)
    assert err.value.status_code == 422
    assert err.value.detail["code"] == "FIX_FIELDS_INVALID"


def test_fix_list_only_on_return_from_qc_outside_nordea(monkeypatch) -> None:
    monkeypatch.setattr(svc, "cpro_enabled_for_client", lambda cid: cid == 7)
    svc.assert_allowed(from_column="cv_qc", target_column="verified", client_id=1)
    for kwargs in (
        dict(from_column="verified", target_column="verified", client_id=1),
        dict(from_column="cv_qc", target_column="cv_sent", client_id=1),
        dict(from_column="cv_qc", target_column="verified", client_id=7),
    ):
        with pytest.raises(HTTPException) as err:
            svc.assert_allowed(**kwargs)
        assert err.value.detail["code"] == "FIX_FIELDS_NOT_ALLOWED"


def test_describe_marks_changed_fields_from_the_snapshot_diff() -> None:
    before = rules.build_snapshot(
        sheet={
            "answers": [{"question_id": "q1", "response": "rok"}],
            "overall_fit": "uncertain",
        },
        card_fields={"availability": {"raw": "od zaraz"}},
        rate={"amount": 150, "unit": "hourly", "currency": "PLN"},
    )
    after = rules.build_snapshot(
        sheet={
            "answers": [{"question_id": "q1", "response": "3 lata produkcyjnie"}],
            "overall_fit": "uncertain",
        },
        card_fields={"availability": {"raw": "od zaraz"}},
        rate={"amount": 140, "unit": "hourly", "currency": "PLN"},
    )
    row = SimpleNamespace(
        version_no=4,
        created_at=datetime(2026, 10, 8, tzinfo=timezone.utc),
        snapshot=before,
        meta={
            "stage_id": 11,
            "fields": [
                {"key": "question:q1", "label": "Pytanie 1"},
                {"key": "field:availability", "label": "Dostępność"},
                {"key": "candidate_rate", "label": "Stawka kandydata"},
                {"key": "cv", "label": "CV firmowe"},
            ],
        },
    )
    out = svc.describe(
        row,
        current_snapshot=after,
        questions=["q1", "q2"],
        cv_changed=True,
        requested_by_name="Dorota DL",
        remark="Dopisz lata z Kafką",
    )
    changed = {f["key"]: f["changed"] for f in out["fields"]}
    assert changed == {
        "question:q1": True,
        "field:availability": False,
        "candidate_rate": True,
        "cv": True,
    }
    assert out["count"] == 4 and out["changed_count"] == 3
    assert out["stage_id"] == 11


def test_bell_suffix_lists_at_most_four_fields() -> None:
    assert svc.bell_suffix([]) is None
    assert svc.bell_suffix(["Pytanie 1", "CV firmowe"]) == (
        "Do poprawy (2): Pytanie 1, CV firmowe."
    )
    many = svc.bell_suffix([f"Pole {i}" for i in range(6)])
    assert many == "Do poprawy (6): Pole 0, Pole 1, Pole 2, Pole 3 i 2 więcej."


# ── Integracyjne: ruch, formularz, dzwonek, „CV w drodze” ────────────────────


@pytest_asyncio.fixture
async def api_client():
    from app.core.rate_limit import limiter as _limiter
    from app.main import app

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as c:
        yield c


async def _prepare(world: dict, rec_id: int, dl_id: int) -> None:
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, world["job_id"])
        job.delivery_lead_id = dl_id
        job.champion_profile = {"screening_questions": QUESTIONS}
        db.add(
            CandidateStage(
                candidate_id=world["candidate_id"],
                job_id=world["job_id"],
                stage="screening",
                stage_def_id=world["defs"]["screening"],
                moved_by=rec_id,
                screening_answers={
                    "answers": [{"question_id": "q1", "response": "rok"}],
                    "overall_fit": "fit",
                },
                moved_at=datetime.now(timezone.utc) - timedelta(hours=2),
            )
        )
        await db.commit()


async def _form(client: AsyncClient, headers: dict, world: dict) -> dict:
    resp = await client.get(
        "/api/screening-form",
        headers=headers,
        params={"candidate_id": world["candidate_id"], "job_id": world["job_id"]},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_dl_returns_with_fields_and_recruiter_sees_and_hands_back(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await _seed_world()
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "")
    rec_id, rec_creds = await _seed_user(UserRole.recruiter)
    dl_id, dl_creds = await _seed_user(UserRole.delivery_lead)
    rec = await _login(api_client, rec_creds)
    dl = await _login(api_client, dl_creds)
    await _prepare(world, rec_id, dl_id)
    cid, jid, defs = world["candidate_id"], world["job_id"], world["defs"]
    try:
        await _move(
            api_client,
            rec,
            world,
            "verified",
            expected_rate_value="140",
            expected_rate_unit="hourly",
            expected_rate_currency="PLN",
        )
        await _move(api_client, rec, world, "qc")

        unknown = await api_client.post(
            "/api/pipeline/move",
            headers=dl,
            json={
                "candidate_id": cid,
                "job_id": jid,
                "stage_def_id": defs["verified"],
                "fix_fields": ["question:q9"],
            },
        )
        assert unknown.status_code == 422, unknown.text
        assert unknown.json()["detail"]["code"] == "FIX_FIELDS_INVALID"

        await _move(
            api_client,
            dl,
            world,
            "verified",
            fix_fields=["question:q1", "candidate_rate", "cv"],
            recruiter_remark="Dopisz, ile lat z Kafką",
        )

        async with AsyncSessionLocal() as db:
            row = await db.scalar(
                select(ScreeningFormVersion).where(
                    ScreeningFormVersion.candidate_id == cid,
                    ScreeningFormVersion.job_id == jid,
                    ScreeningFormVersion.action == "fix_requested",
                )
            )
            assert row is not None and row.created_by == dl_id
            assert [f["key"] for f in row.meta["fields"]] == [
                "question:q1",
                "candidate_rate",
                "cv",
            ]
            bells = (
                await db.scalars(
                    select(Notification.message).where(
                        Notification.user_id == rec_id,
                        Notification.message.contains("Do poprawy (3)"),
                    )
                )
            ).all()
        assert bells, "rekruter dostaje listę pól w dzwonku"

        state = await _form(api_client, rec, world)
        fix = state["fix_request"]
        assert fix is not None and fix["count"] == 3
        assert fix["remark"] == "Dopisz, ile lat z Kafką"
        assert all(f["changed"] is False for f in fix["fields"])
        assert state["handback_stage_def_id"] == defs["qc"]

        board = (await api_client.get("/api/board-tasks", headers=rec)).json()
        returned = [
            r for r in board["cv_in_transit"]["returned"] if r["candidate_id"] == cid
        ]
        assert returned and returned[0]["fix_labels"][0].startswith("Pytanie 1")

        # Drugi raz z „Zweryfikowany” — listy poprawek nie ma skąd wysłać.
        again = await api_client.post(
            "/api/pipeline/move",
            headers=dl,
            json={
                "candidate_id": cid,
                "job_id": jid,
                "stage_def_id": defs["verified"],
                "fix_fields": ["cv"],
            },
        )
        assert again.status_code == 422, again.text
        assert again.json()["detail"]["code"] == "FIX_FIELDS_NOT_ALLOWED"

        # Rekruter poprawia odpowiedź — pole jest „poprawione”.
        async with AsyncSessionLocal() as db:
            newest = await db.scalar(
                select(CandidateStage)
                .where(CandidateStage.candidate_id == cid, CandidateStage.job_id == jid)
                .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
                .limit(1)
            )
            newest.screening_answers = {
                "answers": [{"question_id": "q1", "response": "3 lata produkcyjnie"}],
                "overall_fit": "fit",
            }
            await db.commit()
        fix = (await _form(api_client, rec, world))["fix_request"]
        assert {f["key"]: f["changed"] for f in fix["fields"]}["question:q1"] is True

        # Oddanie do przeglądu DL zamyka prośbę.
        await _move(api_client, rec, world, "qc")
        assert (await _form(api_client, rec, world))["fix_request"] is None
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(ScreeningFormVersion).where(
                    ScreeningFormVersion.candidate_id == cid
                )
            )
            await db.execute(
                delete(Notification).where(Notification.user_id.in_([rec_id, dl_id]))
            )
            await db.commit()
        await _cleanup(world, [rec_id, dl_id])


@pytest.mark.asyncio
async def test_nordea_has_no_dl_review_so_no_fix_list(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await _seed_world()
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", str(world["client_id"]))
    rec_id, rec_creds = await _seed_user(UserRole.recruiter)
    dl_id, dl_creds = await _seed_user(UserRole.delivery_lead)
    rec = await _login(api_client, rec_creds)
    dl = await _login(api_client, dl_creds)
    await _prepare(world, rec_id, dl_id)
    try:
        await _move(
            api_client,
            rec,
            world,
            "verified",
            expected_rate_value="140",
            expected_rate_unit="hourly",
            expected_rate_currency="PLN",
        )
        await _move(api_client, rec, world, "qc")
        resp = await api_client.post(
            "/api/pipeline/move",
            headers=dl,
            json={
                "candidate_id": world["candidate_id"],
                "job_id": world["job_id"],
                "stage_def_id": world["defs"]["verified"],
                "fix_fields": ["cv"],
            },
        )
        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"]["code"] == "FIX_FIELDS_NOT_ALLOWED"
    finally:
        await _cleanup(world, [rec_id, dl_id])
