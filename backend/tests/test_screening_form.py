"""Jeden formularz screeningu (0424, decyzje Artura D1–D10 z 07.10.2026).

Czyste reguły i walidacja wejścia: ``test_screening_form_rules.py``;
migracja i lustro w entrypoincie: ``test_screening_form_migration_mirror.py``.
Tu: trasy ``/api/screening-form`` z bazą (CI) — zapis na
najnowszy wiersz etapu, wersje (baseline, zmiana obok formularza, zapis bez
zmian), konflikt wersji, tylko do odczytu, blokada 12 h, notatka z rozmowy,
stawka (wpis przed „Zweryfikowany”, zadanie DL po „CV wysłane”, mail po
commicie), przywracanie i cofanie, scalanie kandydatów. Dane wyłącznie
fikcyjne.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

import app.models  # noqa: F401  (zarejestruj wszystkie mappery)
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.candidate import Candidate, CandidateStatus
from app.models.candidate_rate_change import CandidateRateChange
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.note import Note
from app.models.recommendation_card import RecommendationCard
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.recruitment_process import ProcessStatus, RecruitmentProcess
from app.models.screening_form_version import ScreeningFormVersion
from app.models.user import User, UserRole
from app.services import candidate_rate_change as rate_change
from app.services import note_kinds
from app.services import screening_form as form
from tests.test_interview_cycle import _user

BACKEND = Path(__file__).resolve().parents[1]
URL = "/api/screening-form"
QUESTIONS = [
    {"id": "q1", "question": "Jakie ma doświadczenie z Kafką?"},
    {"id": "q2", "question": "Dlaczego chce zmienić projekt?"},
]
QUESTION_TEXTS = {q["id"]: q["question"] for q in QUESTIONS}
NOTE = (
    "Rozmowa 07.10, kandydat fikcyjny\n"
    "kafka 3 lata prod, eventy płatności\n"
    "eng B2 gada swobodnie o tech\n"
)


# ── bez bazy ─────────────────────────────────────────────────────────────────


def test_candidate_merge_moves_form_history_before_the_generic_loop() -> None:
    source = (BACKEND / "app" / "services" / "candidate_merge.py").read_text(
        encoding="utf-8"
    )
    call = source.index("screening_form.merge_versions(")
    assert call < source.index("for ref in await _usable_references(db):", call)


# ── z bazą ───────────────────────────────────────────────────────────────────


async def _world(
    stage: PipelineStage = PipelineStage.screening,
    *,
    process: Optional[ProcessStatus] = ProcessStatus.open,
    job_status: JobStatus = JobStatus.published,
    rate: Optional[Decimal] = None,
    sheet: Optional[dict] = None,
    with_stage: bool = True,
) -> dict:
    rec_id, rec_h = await _user(UserRole.recruiter)
    dl_id, dl_h = await _user(UserRole.delivery_lead)
    tag = uuid.uuid4().hex[:8]
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        client = Client(name=f"FormClient-{tag}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"FormJob-{tag}",
            status=job_status,
            client_id=client.id,
            recruiter_id=rec_id,
            delivery_lead_id=dl_id,
            champion_profile={"screening_questions": QUESTIONS},
        )
        candidate = Candidate(
            name="Ola",
            lastname=f"Formularz-{tag}",
            email=f"form-{tag}@example.com",
            status=CandidateStatus.active,
        )
        db.add_all([job, candidate])
        await db.flush()
        if process is not None:
            db.add(
                RecruitmentProcess(
                    candidate_id=candidate.id,
                    job_id=job.id,
                    client_id=client.id,
                    status=process,
                    attempt_no=1,
                    opened_at=now - timedelta(days=2),
                )
            )
        stage_id = None
        if with_stage:
            row = CandidateStage(
                candidate_id=candidate.id,
                job_id=job.id,
                stage=stage,
                moved_by=rec_id,
                moved_at=now - timedelta(hours=1),
                expected_rate_value=rate,
                expected_rate_unit="hourly" if rate is not None else None,
                expected_rate_currency="PLN" if rate is not None else None,
                screening_answers=sheet,
            )
            db.add(row)
            await db.flush()
            stage_id = row.id
        await db.commit()
        return {
            "rec_id": rec_id,
            "rec_h": rec_h,
            "dl_id": dl_id,
            "dl_h": dl_h,
            "job_id": job.id,
            "cand_id": candidate.id,
            "stage_id": stage_id,
        }


def _params(w: dict) -> dict:
    return {"candidate_id": w["cand_id"], "job_id": w["job_id"]}


def _sheet(**answers: str) -> dict:
    return {
        "answers": [
            {"question_id": question_id, "response": response}
            for question_id, response in answers.items()
        ],
        "experience_checks": [],
        "overall_fit": "fit",
    }


def _rate(amount: int) -> dict:
    return {"amount": amount, "unit": "hourly", "currency": "PLN"}


def _payload(w: dict, *, expected: int, **parts: Any) -> dict:
    return {**_params(w), "expected_version": expected, **parts}


async def _put(
    client: AsyncClient,
    w: dict,
    *,
    expected: int,
    headers: Optional[dict] = None,
    **parts: Any,
) -> dict:
    res = await client.put(
        URL, headers=headers or w["rec_h"], json=_payload(w, expected=expected, **parts)
    )
    assert res.status_code == 200, res.text
    return res.json()


async def _state(client: AsyncClient, w: dict) -> dict:
    res = await client.get(URL, params=_params(w), headers=w["rec_h"])
    assert res.status_code == 200, res.text
    return res.json()


async def _versions(client: AsyncClient, w: dict) -> dict:
    res = await client.get(f"{URL}/versions", params=_params(w), headers=w["rec_h"])
    assert res.status_code == 200, res.text
    return res.json()


async def _restore(
    client: AsyncClient, w: dict, *, version_no: int, expected: int, mode: str
) -> dict:
    res = await client.post(
        f"{URL}/restore",
        headers=w["rec_h"],
        json={
            **_params(w),
            "version_no": version_no,
            "expected_version": expected,
            "mode": mode,
        },
    )
    assert res.status_code == 200, res.text
    return res.json()


def _answers(body: dict) -> dict[str, str]:
    return {a["question_id"]: a["response"] for a in (body["sheet"] or {})["answers"]}


async def _version_count(w: dict) -> int:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(func.count())
            .select_from(ScreeningFormVersion)
            .where(
                ScreeningFormVersion.candidate_id == w["cand_id"],
                ScreeningFormVersion.job_id == w["job_id"],
            )
        )


async def test_get_shows_an_empty_editable_form(app_client: AsyncClient):
    w = await _world()
    body = await _state(app_client, w)
    assert body["editable"] is True
    assert body["read_only_reason"] is None and body["read_only_message"] is None
    assert body["version"] == 0 and body["versions_count"] == 0
    assert body["stage_id"] == w["stage_id"]
    assert body["board_column"] == "screening"
    assert body["sheet"] is None and body["rate"] is None
    assert "rate" not in body["card"]["editable_fields"]
    assert "availability" in body["card"]["editable_fields"]
    assert body["rate_change_notifies"] is False
    assert body["can_edit_rate"] is True
    assert "screening_questions" in body["champion_profile"]


async def test_save_writes_on_the_newest_row_and_keeps_the_older_sheet(
    app_client: AsyncClient,
):
    """Arkusz pary stoi na starszym wierszu („Screening”), a karta poszła dalej.

    Zapis trafia na NAJNOWSZY wiersz — arkusz starszego wiersza to historia
    etapu i zostaje nietknięty, a formularz od teraz czyta nowy arkusz.
    """
    old_sheet = {
        "answers": [{"question_id": "q1", "response": "Kafka od roku"}],
        "overall_fit": "fit",
    }
    w = await _world(PipelineStage.screening, sheet=old_sheet)
    async with AsyncSessionLocal() as db:
        newest = CandidateStage(
            candidate_id=w["cand_id"],
            job_id=w["job_id"],
            stage=PipelineStage.verified,
            moved_by=w["rec_id"],
            moved_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        )
        db.add(newest)
        await db.commit()
        newest_id = newest.id

    before = await _state(app_client, w)
    assert before["stage_id"] == newest_id
    assert before["board_column"] == "verified"
    assert before["sheet_source_stage_id"] == w["stage_id"]
    assert _answers(before) == {"q1": "Kafka od roku"}

    body = await _put(
        app_client,
        w,
        expected=0,
        sheet=_sheet(q1="Kafka od 3 lat"),
        card={"fields": {"nationality": "polska"}},
    )

    # Stan sprzed zapisu (arkusz z importu) zostaje wersją bazową.
    assert body["saved_version"] == 2 and body["undo_to_version"] == 1
    assert body["sheet_source_stage_id"] is None
    assert _answers(body) == {"q1": "Kafka od 3 lat"}
    async with AsyncSessionLocal() as db:
        older = await db.get(CandidateStage, w["stage_id"])
        fresh = await db.get(CandidateStage, newest_id)
        assert older.screening_answers["answers"][0]["response"] == "Kafka od roku"
        (answer,) = fresh.screening_answers["answers"]
        assert answer["response"] == "Kafka od 3 lat"
        assert answer["question_text"] == QUESTION_TEXTS["q1"]
        activity = await db.scalar(
            select(Activity)
            .where(
                Activity.entity_type == "candidate",
                Activity.entity_id == w["cand_id"],
                Activity.action == "screening_form_saved",
            )
            .order_by(Activity.id.desc())
            .limit(1)
        )
    # Dziennik zdarzeń niesie nazwy pól, nigdy wartości (narodowość, stawka).
    assert activity.details["version_no"] == 2
    assert set(activity.details["fields"]) == {"nationality", "q1"}
    assert "polska" not in json.dumps(activity.details, ensure_ascii=False)

    versions = await _versions(app_client, w)
    assert [v["action"] for v in versions["items"]] == ["save", "baseline"]
    assert versions["items"][1]["created_by"] is None
    assert versions["items"][0]["created_by"] == w["rec_id"]


async def test_the_same_form_saved_twice_adds_one_version(app_client: AsyncClient):
    w = await _world()
    parts = {
        "sheet": _sheet(q1="Kafka od 3 lat"),
        "card": {"fields": {"english": "B2"}},
    }
    first = await _put(app_client, w, expected=0, **parts)
    assert first["saved_version"] == 1 and first["undo_to_version"] is None

    again = await _put(app_client, w, expected=1, **parts)
    assert again["saved_version"] is None and again["changed"] == []
    assert again["version"] == 1 and again["versions_count"] == 1
    assert await _version_count(w) == 1


async def test_a_stale_form_gets_a_version_conflict(app_client: AsyncClient):
    w = await _world()
    await _put(app_client, w, expected=0, sheet=_sheet(q1="Kafka od 3 lat"))

    res = await app_client.put(
        URL,
        headers=w["rec_h"],
        json=_payload(w, expected=0, sheet=_sheet(q1="Inna odpowiedź")),
    )

    assert res.status_code == 409, res.text
    detail = res.json()["detail"]
    assert detail["code"] == "SCREENING_FORM_VERSION_CONFLICT"
    assert detail["current_version"] == 1
    assert detail["saved_by_name"].startswith("Cycle recruiter")
    assert _answers(await _state(app_client, w)) == {"q1": "Kafka od 3 lat"}


async def test_a_change_made_beside_the_form_is_kept_and_recorded(
    app_client: AsyncClient,
):
    """Formularz otwarty przed zmianą starą trasą odsyła stary arkusz.

    Pole, którego rekruter nie ruszył, nie cofa cudzej zmiany; ta zmiana
    zostaje osobną wersją (``external``) bez autora.
    """
    w = await _world()
    await _put(app_client, w, expected=0, sheet=_sheet(q1="Kafka od roku"))
    async with AsyncSessionLocal() as db:
        stage = await db.get(CandidateStage, w["stage_id"])
        stage.screening_answers = {
            "answers": [{"question_id": "q1", "response": "Kafka od 5 lat"}],
            "overall_fit": "fit",
        }
        await db.commit()

    body = await _put(
        app_client,
        w,
        expected=1,
        sheet=_sheet(q1="Kafka od roku"),
        card={"fields": {"availability": "od zaraz"}},
    )

    assert body["saved_version"] == 3 and body["undo_to_version"] == 2
    assert _answers(body) == {"q1": "Kafka od 5 lat"}
    assert body["card"]["fields"]["availability"]["raw"] == "od zaraz"
    items = (await _versions(app_client, w))["items"]
    assert [v["action"] for v in items] == ["save", "external", "save"]
    external = items[1]
    assert external["created_by"] is None
    assert [(c["label"], c["before"], c["after"]) for c in external["changes"]] == [
        ("Pytanie 1", "Kafka od roku", "Kafka od 5 lat")
    ]
    assert [c["label"] for c in items[0]["changes"]] == ["Dostępność"]


async def test_empty_sheet_is_not_saved(app_client: AsyncClient):
    """Same puste odpowiedzi nie są rozmową — i nie mogą spełnić bramki
    „Zweryfikowany”, która liczy każdą pozycję arkusza."""
    w = await _world()
    body = await _put(
        app_client,
        w,
        expected=0,
        sheet={
            "answers": [{"question_id": "q1", "response": "  "}],
            "overall_fit": "fit",
        },
    )
    assert body["saved_version"] is None and body["changed"] == []
    assert body["sheet"] is None
    async with AsyncSessionLocal() as db:
        stage = await db.get(CandidateStage, w["stage_id"])
        assert stage.screening_answers is None
    assert await _version_count(w) == 0


@pytest.mark.parametrize(
    ("world", "reason"),
    [
        ({"job_status": JobStatus.closed}, "job_closed"),
        (
            {"stage": PipelineStage.verified, "process": ProcessStatus.closed},
            "process_closed",
        ),
        ({"process": ProcessStatus.voided}, "process_voided"),
        # Para bez procesu (import) — rozstrzyga kolumna najnowszego wiersza.
        ({"stage": PipelineStage.rejected, "process": None}, "process_closed"),
        # „Onboarding” procesu nie zamyka, ale osoba jest już zatrudniona.
        ({"stage": PipelineStage.onboarding}, "process_closed"),
        ({"process": None, "with_stage": False}, "no_stage"),
    ],
)
async def test_a_read_only_pair_refuses_the_save(
    app_client: AsyncClient, world: dict, reason: str
):
    w = await _world(**world)
    state = await _state(app_client, w)
    assert state["editable"] is False
    assert state["read_only_reason"] == reason
    assert state["read_only_message"]

    res = await app_client.put(
        URL, headers=w["rec_h"], json=_payload(w, expected=0, sheet=_sheet(q1="x"))
    )

    assert res.status_code == 409, res.text
    detail = res.json()["detail"]
    assert detail["code"] == "SCREENING_FORM_READ_ONLY"
    assert detail["reason"] == reason
    assert await _version_count(w) == 0


async def test_a_pair_without_a_process_in_screening_is_editable(
    app_client: AsyncClient,
):
    w = await _world(process=None)
    body = await _put(app_client, w, expected=0, sheet=_sheet(q1="Kafka od 3 lat"))
    assert body["saved_version"] == 1 and body["editable"] is True


async def test_claimed_person_blocks_another_recruiter_but_not_the_dl(
    app_client: AsyncClient,
):
    w = await _world(PipelineStage.new)
    holder_id, _holder_h = await _user(UserRole.recruiter)
    async with AsyncSessionLocal() as db:
        process = await db.scalar(
            select(RecruitmentProcess).where(
                RecruitmentProcess.candidate_id == w["cand_id"],
                RecruitmentProcess.job_id == w["job_id"],
            )
        )
        process.claimed_by_user_id = holder_id
        process.claimed_until = datetime.now(timezone.utc) + timedelta(hours=10)
        await db.commit()

    state = await _state(app_client, w)
    assert state["claim"]["user_id"] == holder_id
    assert state["claim"]["mine"] is False

    parts = {"sheet": _sheet(q1="Kafka od 3 lat")}
    refused = await app_client.put(
        URL, headers=w["rec_h"], json=_payload(w, expected=0, **parts)
    )
    assert refused.status_code == 423, refused.text
    assert refused.json()["detail"]["code"] == "CANDIDATE_CLAIMED"
    assert await _version_count(w) == 0

    # Delivery Lead rozstrzyga spory o osobę — blokada go nie wiąże.
    body = await _put(app_client, w, expected=0, headers=w["dl_h"], **parts)
    assert body["saved_version"] == 1


async def test_note_import_is_a_human_note_and_marks_the_fields(
    app_client: AsyncClient, monkeypatch
):
    monkeypatch.setattr(settings, "RECOMMENDATION_CARD_ASSIST_ENABLED", True)
    w = await _world()

    body = await _put(
        app_client,
        w,
        expected=0,
        note_import={"text": NOTE, "source_name": "notatka.docx"},
        card={
            "fields": {"english": "B2"},
            "origins": {"english": {"origin": "note_ai"}},
        },
        sheet={
            "answers": [
                {
                    "question_id": "q1",
                    "response": "Kandydat od 3 lat pracuje z Kafką na produkcji.",
                    "origin": "note_import",
                    "keywords": "kafka 3 lata prod",
                }
            ],
            "overall_fit": "fit",
        },
    )

    assert body["note_id"] is not None and body["saved_version"] == 1
    async with AsyncSessionLocal() as db:
        note = await db.get(Note, body["note_id"])
        stage = await db.get(CandidateStage, w["stage_id"])
    # Zwykła notatka z rozmowy, nie notatka-karta — projekcja kart nie
    # dopisze do karty pól, których rekruter nie przyjął.
    assert note.kind == note_kinds.HUMAN
    assert note.external_source == note_kinds.CARD_ASSIST_SOURCE
    assert note.content.startswith("Notatka z rozmowy (plik: notatka.docx)")
    assert note.job_id == w["job_id"] and note.author_id == w["rec_id"]
    english = body["card"]["fields"]["english"]
    assert english["origin"] == "note_ai" and english["note_id"] == note.id
    (answer,) = stage.screening_answers["answers"]
    assert answer["origin"] == "note_import"
    assert answer["keywords"] == "kafka 3 lata prod"
    top = (await _versions(app_client, w))["items"][0]
    assert top["source"] == "note_import" and top["note_id"] == note.id


async def test_failed_score_marking_does_not_fail_the_save(
    app_client: AsyncClient, monkeypatch
):
    from app.services import match_score_cache

    async def boom(*_args, **_kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError("cache down")

    monkeypatch.setattr(match_score_cache, "mark_stale_for_candidate", boom)
    w = await _world()

    body = await _put(app_client, w, expected=0, sheet=_sheet(q1="Kafka od 3 lat"))

    assert body["cache_invalidated"] is False
    assert body["saved_version"] == 1
    assert _answers(body) == {"q1": "Kafka od 3 lat"}


async def _pair_changes(w: dict) -> list[CandidateRateChange]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(CandidateRateChange)
                    .where(
                        CandidateRateChange.candidate_id == w["cand_id"],
                        CandidateRateChange.job_id == w["job_id"],
                    )
                    .order_by(CandidateRateChange.id)
                )
            ).all()
        )


async def test_rate_before_verified_is_only_noted(app_client: AsyncClient):
    w = await _world(PipelineStage.screening, rate=Decimal("110"))

    body = await _put(app_client, w, expected=0, rate=_rate(125))

    assert body["saved_version"] == 2 and body["undo_to_version"] == 1
    assert body["changed"] == ["Stawka kandydata"]
    assert body["rate"]["amount"] == 125.0 and body["rate"]["source"] == "stage"
    (change,) = await _pair_changes(w)
    assert change.status == "noted" and change.requires_decision is False
    assert change.source == "screening" and change.reason == "conversation"
    async with AsyncSessionLocal() as db:
        stage = await db.get(CandidateStage, w["stage_id"])
        card = await db.scalar(
            select(RecommendationCard).where(
                RecommendationCard.candidate_id == w["cand_id"],
                RecommendationCard.job_id == w["job_id"],
            )
        )
    assert stage.expected_rate_value == Decimal("125.00")
    # Pole karty „Stawka” niesie tekst tej samej stawki.
    assert card.fields_manual["rate"]["raw"] == "125 zł/h"
    history = (await _versions(app_client, w))["items"][0]["changes"]
    assert history == [
        {
            "section": "rate",
            "key": "rate",
            "label": "Stawka kandydata",
            "before": "110 zł/h",
            "after": "125 zł/h",
        }
    ]


async def test_rise_after_cv_sent_is_a_dl_task_and_the_mail_goes_after_commit(
    app_client: AsyncClient, monkeypatch, routine_notification_email_enabled
):
    w = await _world(PipelineStage.client_interview, rate=Decimal("110"))

    async def enabled_policy(_db):  # noqa: ANN001, ANN202
        return routine_notification_email_enabled

    monkeypatch.setattr(rate_change, "load_policy", enabled_policy)
    sent: list[tuple[list, int]] = []

    async def record(emails):  # noqa: ANN001, ANN202
        # Mail wychodzi PO commicie — sprawa jest już widoczna z innej sesji.
        async with AsyncSessionLocal() as other:
            committed = await other.scalar(
                select(func.count())
                .select_from(CandidateRateChange)
                .where(
                    CandidateRateChange.candidate_id == w["cand_id"],
                    CandidateRateChange.job_id == w["job_id"],
                )
            )
        sent.append((list(emails), committed))

    monkeypatch.setattr(rate_change, "send_pending_emails", record)

    state = await _state(app_client, w)
    assert state["rate_change_notifies"] is True
    await _put(app_client, w, expected=0, rate=_rate(125))

    (change,) = await _pair_changes(w)
    assert change.status == "requested" and change.requires_decision is True
    assert change.source == "screening"
    ((emails, committed),) = sent
    assert committed == 1
    async with AsyncSessionLocal() as db:
        dl = await db.get(User, w["dl_id"])
    assert dl.email in [email.to for email in emails]


async def test_undo_returns_the_previous_version_as_a_new_one(
    app_client: AsyncClient,
):
    w = await _world()
    first = await _put(
        app_client,
        w,
        expected=0,
        sheet=_sheet(q1="Kafka od roku"),
        card={"fields": {"availability": "od zaraz"}},
    )
    assert first["saved_version"] == 1
    second = await _put(
        app_client,
        w,
        expected=1,
        sheet=_sheet(q1="Kafka od 3 lat"),
        card={"fields": {"availability": "miesiąc"}},
    )
    assert second["saved_version"] == 2 and second["undo_to_version"] == 1

    body = await _restore(app_client, w, version_no=1, expected=2, mode="undo")

    assert body["saved_version"] == 3
    assert _answers(body) == {"q1": "Kafka od roku"}
    assert body["card"]["fields"]["availability"]["raw"] == "od zaraz"
    versions = await _versions(app_client, w)
    top = versions["items"][0]
    assert top["action"] == "undo" and top["restored_from_version"] == 1
    assert {c["label"] for c in top["changes"]} == {"Pytanie 1", "Dostępność"}
    assert versions["total"] == 3


async def test_undo_to_a_version_without_answers_clears_the_sheet(
    app_client: AsyncClient,
):
    w = await _world()
    await _put(app_client, w, expected=0, card={"fields": {"availability": "od zaraz"}})
    second = await _put(app_client, w, expected=1, sheet=_sheet(q1="Kafka od 3 lat"))
    assert second["undo_to_version"] == 1

    body = await _restore(app_client, w, version_no=1, expected=2, mode="undo")

    assert body["saved_version"] == 3 and body["sheet"] is None
    async with AsyncSessionLocal() as db:
        stage = await db.get(CandidateStage, w["stage_id"])
        assert stage.screening_answers is None


async def test_restore_keeps_the_rate_from_verified_but_undo_corrects_it(
    app_client: AsyncClient,
):
    """Od „Zweryfikowany” zmianą stawki zarządza Delivery Lead (0418) —
    przywrócenie wersji jej nie cofa; „Cofnij” tuż po zapisie poprawia
    pomyłkę (``reason="typo"``, bez zadania dla DL)."""
    w = await _world(PipelineStage.verified, rate=Decimal("110"))
    saved = await _put(app_client, w, expected=0, rate=_rate(125))
    assert saved["saved_version"] == 2 and saved["undo_to_version"] == 1

    restored = await _restore(app_client, w, version_no=1, expected=2, mode="restore")
    assert restored["rate_not_restored"] is True
    assert restored["saved_version"] is None
    assert restored["rate"]["amount"] == 125.0

    undone = await _restore(app_client, w, version_no=1, expected=2, mode="undo")
    assert undone["rate_not_restored"] is False
    assert undone["saved_version"] == 3
    assert undone["rate"]["amount"] == 110.0
    changes = await _pair_changes(w)
    assert [c.reason for c in changes] == ["conversation", "typo"]


async def test_restore_skips_an_answer_to_a_reworded_question(
    app_client: AsyncClient,
):
    w = await _world()
    await _put(
        app_client,
        w,
        expected=0,
        sheet=_sheet(q1="Kafka od roku", q2="Chce dłuższy projekt"),
    )
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, w["job_id"])
        job.champion_profile = {
            "screening_questions": [
                {"id": "q1", "question": "Ile lat pracuje z Kafką na produkcji?"},
                QUESTIONS[1],
            ]
        }
        await db.commit()
    await _put(
        app_client, w, expected=1, sheet=_sheet(q1="Trzy lata", q2="Szuka stabilności")
    )

    body = await _restore(app_client, w, version_no=1, expected=2, mode="restore")

    # Kandydat odpowiadał w wersji 1 na INNE pytanie 1 — ta odpowiedź zostaje.
    assert body["skipped_answers"] == ["Pytanie 1"]
    assert _answers(body) == {"q1": "Trzy lata", "q2": "Chce dłuższy projekt"}
    assert body["saved_version"] == 3


async def test_merge_moves_the_duplicate_history_above_the_survivor() -> None:
    tag = uuid.uuid4().hex[:8]
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        client = Client(name=f"MergeFormClient-{tag}")
        db.add(client)
        await db.flush()
        job_a = Job(
            title=f"MergeA-{tag}", status=JobStatus.published, client_id=client.id
        )
        job_b = Job(
            title=f"MergeB-{tag}", status=JobStatus.published, client_id=client.id
        )
        survivor = Candidate(
            name="Ola", lastname=f"Ocalala-{tag}", email=f"merge-s-{tag}@example.com"
        )
        duplicate = Candidate(
            name="Ola", lastname=f"Duplikat-{tag}", email=f"merge-d-{tag}@example.com"
        )
        db.add_all([job_a, job_b, survivor, duplicate])
        await db.flush()

        def version(
            candidate: Candidate,
            job: Job,
            number: int,
            action: str = "save",
            restored: Optional[int] = None,
        ) -> ScreeningFormVersion:
            return ScreeningFormVersion(
                candidate_id=candidate.id,
                job_id=job.id,
                version_no=number,
                action=action,
                source="form",
                restored_from_version=restored,
                snapshot={},
                changes=[],
                created_at=now,
            )

        db.add_all(
            [
                version(survivor, job_a, 1),
                version(survivor, job_a, 2),
                version(duplicate, job_a, 1),
                version(duplicate, job_a, 2, "undo", 1),
                version(duplicate, job_b, 1),
            ]
        )
        await db.commit()
        ids = {
            "survivor": survivor.id,
            "duplicate": duplicate.id,
            "a": job_a.id,
            "b": job_b.id,
        }

    async with AsyncSessionLocal() as db:
        moved = await form.merge_versions(
            db, survivor_id=ids["survivor"], duplicate_id=ids["duplicate"]
        )
        await db.commit()

    assert moved == 3
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(
                    ScreeningFormVersion.job_id,
                    ScreeningFormVersion.version_no,
                    ScreeningFormVersion.restored_from_version,
                ).where(ScreeningFormVersion.candidate_id == ids["survivor"])
            )
        ).all()
        left = await db.scalar(
            select(func.count())
            .select_from(ScreeningFormVersion)
            .where(ScreeningFormVersion.candidate_id == ids["duplicate"])
        )

    # Historia duplikatu wchodzi NAD ostatnią wersję ocalałego w tej samej
    # rekrutacji — nic nie znika, a „przywrócono z” wskazuje przesunięty numer.
    def by_pair(row: tuple) -> tuple[int, int]:
        return row[0], row[1]

    assert sorted((tuple(row) for row in rows), key=by_pair) == sorted(
        [
            (ids["a"], 1, None),
            (ids["a"], 2, None),
            (ids["a"], 3, None),
            (ids["a"], 4, 3),
            (ids["b"], 1, None),
        ],
        key=by_pair,
    )
    assert left == 0
