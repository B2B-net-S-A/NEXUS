"""Screening w „Nowych" + podpowiedzi Luny przy przepięciu (Pipeline v4, 23.09.2026).

* schemat: `origin`, `skipped`, `internal_note`; pominięte nie liczą się do
  dopasowania,
* odcięcie klienta: share portal i generator CV nie dostają pominiętych
  odpowiedzi ani notatki wewnętrznej,
* `suggest_answers`: pytania spoza rekrutacji i cytaty spoza materiałów
  odpadają, awaria modelu = `available: false` (nigdy 5xx),
* trasy: sekcja pipeline'u, członkostwo w rekrutacji.
"""

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from app.core.database import AsyncSessionLocal
from app.schemas.champion import ScreeningAnswers, client_safe_screening
from app.services import screening_reassign as svc
from app.services.cv_generator_b2b.standalone_service import (
    _format_candidate_answers,
    _has_candidate_answers,
)

CONTEXT = "/api/pipeline/stages/{stage_id}/screening/reassign-context"
SUGGEST = "/api/pipeline/stages/{stage_id}/screening/reassign-suggestions"


# ── schemat ──────────────────────────────────────────────────────────────────


def test_answer_defaults_are_manual_and_not_skipped() -> None:
    parsed = ScreeningAnswers.model_validate(
        {"answers": [{"question_id": "q1", "response": "tak"}]}
    )
    assert parsed.answers[0].origin == "manual"
    assert parsed.answers[0].skipped is False
    assert parsed.internal_note is None


def test_skipped_answers_do_not_count_towards_the_match() -> None:
    full = ScreeningAnswers.model_validate(
        {
            "answers": [{"question_id": "q1", "response": "tak"}],
            "overall_fit": "fit",
        }
    )
    with_skip = ScreeningAnswers.model_validate(
        {
            "answers": [
                {"question_id": "q1", "response": "tak"},
                {"question_id": "q2", "response": "", "skipped": True},
            ],
            "overall_fit": "fit",
            "internal_note": "Pominięte — przepięcie z rekrutacji Java",
        }
    )
    assert with_skip.match_percent() == full.match_percent() == 100.0


def test_all_skipped_is_zero_not_a_division_error() -> None:
    only_skipped = ScreeningAnswers.model_validate(
        {"answers": [{"question_id": "q1", "skipped": True}], "overall_fit": "fit"}
    )
    assert only_skipped.match_percent() == 0.0


def test_unknown_origin_and_too_long_internal_note_are_rejected() -> None:
    with pytest.raises(ValidationError):
        ScreeningAnswers.model_validate(
            {"answers": [{"question_id": "q1", "origin": "luna"}]}
        )
    with pytest.raises(ValidationError):
        ScreeningAnswers.model_validate({"internal_note": "x" * 2001})


# ── odcięcie klienta ─────────────────────────────────────────────────────────

RAW = {
    "answers": [
        {
            "question_id": "q1",
            "response": "5 lat Kafki",
            "origin": "reassign_suggested",
        },
        {"question_id": "q2", "response": "", "skipped": True},
        {"question_id": "q3", "response": "stare", "skipped": True},
    ],
    "overall_fit": "fit",
    "notes": "Widoczne dla klienta",
    "internal_note": "Pominięte — przepięcie, klient pyta o to samo",
}


def test_client_safe_screening_drops_skipped_and_internal_note() -> None:
    safe = client_safe_screening(RAW)
    assert safe is not None
    assert "internal_note" not in safe
    assert [a["question_id"] for a in safe["answers"]] == ["q1"]
    assert safe["notes"] == "Widoczne dla klienta"
    # Wejście nietknięte (to JSONB wiersza).
    assert len(RAW["answers"]) == 3 and "internal_note" in RAW


def test_client_safe_screening_on_empty_input() -> None:
    assert client_safe_screening(None) is None
    assert client_safe_screening({}) is None


def test_cv_generator_never_sees_skipped_answers() -> None:
    questions = [
        {"id": "q1", "question": "Kafka?"},
        {"id": "q3", "question": "Stare pytanie?"},
    ]
    text = _format_candidate_answers(RAW, questions)
    assert "5 lat Kafki" in text
    assert "stare" not in text
    assert "przepięcie" not in text
    only_skipped = {
        "answers": [{"question_id": "q3", "response": "x", "skipped": True}]
    }
    assert _has_candidate_answers(only_skipped) is False


# ── walidacja podpowiedzi ────────────────────────────────────────────────────

MATERIAL = "P: Ile lat z Kafką?\nO: Pięć lat z Kafką w bankowości.\n\n[2026-09-01]\nDostępny od października."


def test_bad_question_id_and_hallucinated_quote_are_dropped() -> None:
    parsed = {
        "suggestions": [
            {
                "question_id": "k1",
                "text": "5 lat z Kafką",
                "source_kind": "answer",
                "source_quote": "Pięć lat  z KAFKĄ",  # białe znaki i wielkość liter
                "confidence": "high",
            },
            {
                "question_id": "obce",
                "text": "x",
                "source_quote": "Pięć lat z Kafką",
            },
            {
                "question_id": "k2",
                "text": "Zna Kubernetes",
                "source_quote": "Kubernetes od 2019",  # nie ma w materiałach
            },
            {
                "question_id": "k1",
                "text": "druga podpowiedź do tego samego pytania",
                "source_quote": "Pięć lat z Kafką",
            },
        ]
    }
    out = svc.validate_suggestions(
        parsed, question_ids={"k1", "k2"}, material=MATERIAL, include_rates=True
    )
    assert [s["question_id"] for s in out] == ["k1"]
    assert out[0]["confidence"] == "high"
    assert out[0]["source_kind"] == "answer"


def test_garbage_from_the_model_gives_no_suggestions() -> None:
    assert (
        svc.validate_suggestions(
            "nie JSON", question_ids={"k1"}, material=MATERIAL, include_rates=True
        )
        == []
    )


def test_money_is_masked_without_rate_rights() -> None:
    assert "150" not in svc.mask_money(
        "Oczekuje 150 zł/h netto, wcześniej 1 200 PLN/MD"
    )
    assert "25k" not in svc.mask_money("chce 25k na rękę")
    assert svc.mask_money("Java 17, 5 lat") == "Java 17, 5 lat"
    parsed = {
        "suggestions": [
            {
                "question_id": "k1",
                "text": "Oczekuje 150 zł/h",
                "source_quote": "Pięć lat",
            }
        ]
    }
    out = svc.validate_suggestions(
        parsed, question_ids={"k1"}, material=MATERIAL, include_rates=False
    )
    assert "150" not in out[0]["text"]


# ── seed (baza) ──────────────────────────────────────────────────────────────


async def _seed_recruiter(app_client: AsyncClient) -> tuple[dict[str, str], int]:
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    unique = uuid.uuid4().hex[:8]
    email = f"reassign-{unique}@example.com"
    password = f"T3st_{unique}!Reas"
    async with AsyncSessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password(password),
            name="Reassign Recruiter",
            role=UserRole.recruiter,
            roles=["recruiter"],
            is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        uid = user.id
    resp = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}, uid


async def _seed_pair(owner_id: int | None, source_owner_id: int | None = None) -> dict:
    """Rekrutacja źródłowa z arkuszem screeningu + rekrutacja docelowa."""
    from app.models.candidate import Candidate, CandidateStatus
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.job_proposal import JobProposal
    from app.models.note import Note
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    tag = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        cli = Client(name=f"ReassignClient-{tag}")
        db.add(cli)
        await db.flush()
        source = Job(
            title=f"Java Source {tag}",
            status=JobStatus.published,
            client_id=cli.id,
            recruiter_id=source_owner_id,
            champion_profile={
                "screening_questions": [
                    {"id": "s1", "question": "Ile lat z Kafką?"},
                    {"id": "s2", "question": "Pominięte kiedyś?"},
                ]
            },
        )
        target = Job(
            title=f"Java Target {tag}",
            status=JobStatus.published,
            client_id=cli.id,
            recruiter_id=owner_id,
            champion_profile={
                "screening_questions": [
                    {"id": "t1", "question": "Doświadczenie z Kafką?"},
                    {"id": "t2", "question": "Od kiedy dostępny?"},
                ]
            },
        )
        cand = Candidate(
            name="Reas",
            lastname=f"Sign-{tag}",
            email=f"reassign-cand-{tag}@example.com",
            status=CandidateStatus("active"),
        )
        db.add_all([source, target, cand])
        await db.flush()
        now = datetime.now(timezone.utc)
        db.add(
            CandidateStage(
                candidate_id=cand.id,
                job_id=source.id,
                stage=PipelineStage.cv_sent,
                moved_at=now,
                screening_answers={
                    "answers": [
                        {"question_id": "s1", "response": "Pięć lat z Kafką w banku."},
                        {"question_id": "s2", "response": "tajne", "skipped": True},
                    ],
                    "overall_fit": "fit",
                    "answered_at": "2026-09-01T10:00:00+00:00",
                },
            )
        )
        stage = CandidateStage(
            candidate_id=cand.id,
            job_id=target.id,
            stage=PipelineStage.new,
            moved_at=now,
        )
        db.add(stage)
        db.add(
            JobProposal(
                job_id=target.id,
                candidate_id=cand.id,
                source="reassign",
                evidence={
                    "reassign": {
                        "job_id": source.id,
                        "stage": "cv_sent",
                        "sent_at": "2026-09-02",
                    }
                },
            )
        )
        db.add(
            Note(
                candidate_id=cand.id,
                job_id=source.id,
                content="Dostępny od października. Oczekuje 160 zł/h.",
            )
        )
        # Notatka spoza obu rekrutacji przepięcia — NIE może trafić do modelu.
        db.add(
            Note(
                candidate_id=cand.id,
                content="Prywatnie: rozwód, negocjuje z konkurencją NIEZWIĄZANE.",
            )
        )
        await db.commit()
        return {
            "stage_id": stage.id,
            "source_id": source.id,
            "target_id": target.id,
            "candidate_id": cand.id,
        }


async def test_context_without_reassign_is_none() -> None:
    async with AsyncSessionLocal() as db:
        assert await svc.reassign_context(db, candidate_id=-1, job_id=-1) is None


async def test_context_reads_the_proposal_fallback_and_skips_skipped() -> None:
    seed = await _seed_pair(owner_id=None)
    async with AsyncSessionLocal() as db:
        ctx = await svc.reassign_context(
            db, candidate_id=seed["candidate_id"], job_id=seed["target_id"]
        )
    assert ctx is not None
    assert ctx.source_job_id == seed["source_id"]
    assert ctx.date == "2026-09-02"
    assert ctx.answers == [
        {"question": "Ile lat z Kafką?", "answer": "Pięć lat z Kafką w banku."}
    ]


async def test_context_prefers_the_process_source() -> None:
    from app.models.recruitment_process import ProcessStatus, RecruitmentProcess

    seed = await _seed_pair(owner_id=None)
    other = await _seed_pair(owner_id=None)
    async with AsyncSessionLocal() as db:
        db.add(
            RecruitmentProcess(
                candidate_id=seed["candidate_id"],
                job_id=seed["target_id"],
                status=ProcessStatus.open,
                entry_source="reassign",
                reassign_from_job_id=other["source_id"],
                opened_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()
        ctx = await svc.reassign_context(
            db, candidate_id=seed["candidate_id"], job_id=seed["target_id"]
        )
    assert ctx is not None and ctx.source_job_id == other["source_id"]
    # Data z propozycji dotyczy innej rekrutacji źródłowej — nie jest przenoszona.
    assert ctx.date != "2026-09-02"


def _user(can_rates: bool):
    from app.models.user import User, UserRole

    return User(
        id=None,
        email="x@example.com",
        name="x",
        role=UserRole.admin if can_rates else UserRole.sourcer,
        roles=["admin"] if can_rates else ["sourcer"],
        is_active=True,
    )


async def _stage(stage_id: int):
    from app.models.recruitment_pipeline import CandidateStage

    async with AsyncSessionLocal() as db:
        return await db.get(CandidateStage, stage_id)


async def test_suggest_success_keeps_only_grounded_suggestions(monkeypatch) -> None:
    seed = await _seed_pair(owner_id=None)
    captured: dict = {}

    def fake(system: str, prompt: str) -> str:
        captured["prompt"] = prompt
        return (
            "```json\n"
            '{"suggestions": ['
            '{"question_id": "t1", "text": "Pięć lat z Kafką w banku.", '
            '"source_kind": "answer", "source_quote": "Pięć lat z Kafką w banku.", '
            '"confidence": "high"},'
            '{"question_id": "t2", "text": "Od października", "source_kind": "note", '
            '"source_quote": "Dostępny od października.", "confidence": "medium"},'
            '{"question_id": "zz", "text": "obce", "source_quote": "Pięć lat"},'
            '{"question_id": "t2", "text": "zmyślone", "source_quote": "od jutra"}'
            "]}\n```"
        )

    monkeypatch.setattr(svc, "_call_model", fake)
    stage = await _stage(seed["stage_id"])
    async with AsyncSessionLocal() as db:
        out = await svc.suggest_answers(db, stage=stage, user=_user(can_rates=False))
    assert out["available"] is True
    assert out["source"]["job_id"] == seed["source_id"]
    assert [s["question_id"] for s in out["suggestions"]] == ["t1", "t2"]
    # Bez prawa do stawek model nie dostaje kwoty; pominięta odpowiedź nie idzie.
    assert "160" not in captured["prompt"]
    assert "tajne" not in captured["prompt"]
    assert "<previous_screening>" in captured["prompt"]
    # Notatka z niezwiązanej rekrutacji zostaje poza modelem (przegląd
    # bezpieczeństwa 23.09.2026).
    assert "NIEZWIĄZANE" not in captured["prompt"]


async def test_model_error_is_graceful(monkeypatch) -> None:
    seed = await _seed_pair(owner_id=None)

    def boom(system: str, prompt: str) -> str:
        raise RuntimeError("model down")

    monkeypatch.setattr(svc, "_call_model", boom)
    stage = await _stage(seed["stage_id"])
    async with AsyncSessionLocal() as db:
        out = await svc.suggest_answers(db, stage=stage, user=_user(can_rates=True))
    assert out == {
        "available": False,
        "message": svc.MSG_MODEL_FAILED,
        "source": {
            "job_id": seed["source_id"],
            "job_title": out["source"]["job_title"],
            "date": "2026-09-02",
        },
        "suggestions": [],
    }


async def test_invalid_json_is_graceful(monkeypatch) -> None:
    seed = await _seed_pair(owner_id=None)
    monkeypatch.setattr(svc, "_call_model", lambda system, prompt: "nie JSON")
    stage = await _stage(seed["stage_id"])
    async with AsyncSessionLocal() as db:
        out = await svc.suggest_answers(db, stage=stage, user=_user(can_rates=True))
    assert out["available"] is False and out["message"] == svc.MSG_MODEL_FAILED


# ── trasy ────────────────────────────────────────────────────────────────────


async def test_routes_open_for_a_recruiter_outside_both_teams(
    app_client: AsyncClient, monkeypatch
):
    """Od 23.09.2026 rekrutację obsługuje każdy (decyzja Artura) — rekruter
    spoza zespołu obu rekrutacji widzi kontekst i dostaje podpowiedź."""
    seed = await _seed_pair(owner_id=None)
    headers, _uid = await _seed_recruiter(app_client)
    called = {"n": 0}

    def fake(system: str, prompt: str) -> str:
        called["n"] += 1
        return '{"suggestions": []}'

    monkeypatch.setattr(svc, "_call_model", fake)
    r = await app_client.get(CONTEXT.format(stage_id=seed["stage_id"]), headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["available"] is True
    assert r.json()["source"]["job_id"] == seed["source_id"]
    r = await app_client.post(
        SUGGEST.format(stage_id=seed["stage_id"]), headers=headers
    )
    assert r.status_code == 200, r.text
    assert called["n"] == 1


async def test_member_of_target_only_also_gets_source_answers(
    app_client: AsyncClient, monkeypatch
):
    """Członkostwo w poprzedniej rekrutacji nie jest już potrzebne, żeby
    zobaczyć jej odpowiedzi (23.09.2026: rekrutację widzi każdy)."""
    headers, uid = await _seed_recruiter(app_client)
    seed = await _seed_pair(owner_id=uid)
    called = {"n": 0}

    def fake(system: str, prompt: str) -> str:
        called["n"] += 1
        return '{"suggestions": []}'

    monkeypatch.setattr(svc, "_call_model", fake)
    r = await app_client.get(CONTEXT.format(stage_id=seed["stage_id"]), headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["available"] is True
    assert r.json()["source"]["job_id"] == seed["source_id"]
    assert r.json()["previous_answers_count"] == 1
    r = await app_client.post(
        SUGGEST.format(stage_id=seed["stage_id"]), headers=headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["source"]["job_id"] == seed["source_id"]
    assert called["n"] == 1


async def test_routes_for_a_member(app_client: AsyncClient, monkeypatch):
    headers, uid = await _seed_recruiter(app_client)
    seed = await _seed_pair(owner_id=uid, source_owner_id=uid)
    r = await app_client.get(CONTEXT.format(stage_id=seed["stage_id"]), headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["available"] is True
    assert body["source"]["job_id"] == seed["source_id"]
    assert body["previous_answers_count"] == 1

    monkeypatch.setattr(
        svc, "_call_model", lambda s, p: (_ for _ in ()).throw(RuntimeError("x"))
    )
    r = await app_client.post(
        SUGGEST.format(stage_id=seed["stage_id"]), headers=headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["available"] is False
    assert r.json()["message"] == svc.MSG_MODEL_FAILED


async def test_unknown_stage_is_404(app_client: AsyncClient, app_auth_headers):
    r = await app_client.get(
        CONTEXT.format(stage_id=2_000_000_000), headers=app_auth_headers
    )
    assert r.status_code == 404
