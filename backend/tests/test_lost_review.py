"""Insights → „Przegrane” (25.11.2026): „Co zdecydowało?”, wnioski, R3 i AI F56.

Reguła: ``docs/claude/finanse-insights/przegrane-przeglad-z-dl.md``.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.analytics.periods import resolve_period
from app.api.insights_lost_review import period_label
from app.models.lost_review import JobLossReview, LostReviewLesson
from app.services import lost_review as service
from app.services import lost_review_schema as schema

BACKEND = Path(__file__).resolve().parent.parent
WARSAW = ZoneInfo("Europe/Warsaw")


# ── Czyste reguły ───────────────────────────────────────────────────────────


def test_why_keeps_click_order_and_drops_repeats() -> None:
    assert service.clean_why(
        ["too_few_cvs", "competitor_faster", "too_few_cvs"], "client"
    ) == (["too_few_cvs", "competitor_faster"], "client")


@pytest.mark.parametrize(
    ("why", "source", "code"),
    [
        (["za_drogo"], None, "lost_why_unknown"),
        (
            ["competitor_faster", "competitor_cheaper", "too_few_cvs"],
            None,
            "lost_why_too_many",
        ),
        ([], "maybe", "lost_why_source_unknown"),
    ],
)
def test_why_refuses_bad_input(why: list[str], source: str | None, code: str) -> None:
    with pytest.raises(service.LostReviewError) as exc:
        service.clean_why(why, source)
    assert exc.value.code == code


@pytest.mark.parametrize(
    ("facts", "stage"),
    [
        (service.JobFacts(), "no_cv"),
        (service.JobFacts(cvs=4), "cv_only"),
        (service.JobFacts(cvs=4, interviews=1), "interview"),
        (service.JobFacts(cvs=4, interviews=2, accepted=1), "acceptance"),
    ],
)
def test_loss_stage_is_the_furthest_stage(facts: service.JobFacts, stage: str) -> None:
    assert service.loss_stage(facts) == stage


def test_client_pattern_prefers_earlier_stage_on_tie() -> None:
    assert (
        service.client_pattern(
            {"no_cv": 0, "cv_only": 0, "interview": 0, "acceptance": 0}
        )
        is None
    )
    assert service.client_pattern(
        {"no_cv": 0, "cv_only": 2, "interview": 2, "acceptance": 0}
    ) == ("CV nie przechodzą do rozmów")
    assert service.client_pattern(
        {"no_cv": 0, "cv_only": 1, "interview": 3, "acceptance": 0}
    ) == ("Przegrywamy po rozmowach")


def _payload(**over) -> dict:
    base = {
        "counts": {"won": 18, "lost": 46, "competitor": 32, "idle": 14},
        "hit_ratio": 28.1,
        "known": 17,
        "stages": {"no_cv": 3, "cv_only": 26, "interview": 17, "acceptance": 0},
        "compare": {
            "won": {
                "count": 18,
                "first_cv_days": 3.5,
                "cvs": 5.0,
                "interview_share": 83,
            },
            "lost": {
                "count": 46,
                "first_cv_days": 4.1,
                "cvs": 4.5,
                "interview_share": 37,
            },
        },
        "trend": [{"label": "lis 26", "won": 18, "lost": 46, "hit_ratio": 28.1}],
        "why_counts": [],
        "source_counts": {"client": 0, "ours": 0, "unknown": 0},
        "client_verdicts": [{"label": "Za mało doświadczenia", "count": 8}],
        "clients": [
            {
                "client_id": 11,
                "name": "Nordea",
                "won": 6,
                "lost": 19,
                "idle": 3,
                "stages": {"no_cv": 2, "cv_only": 11, "interview": 6, "acceptance": 0},
                "pattern": "CV nie przechodzą do rozmów",
                "verdicts": [{"label": "Za mało doświadczenia", "count": 8}],
                "why": [],
                "lessons": [],
            }
        ],
        "jobs": [
            {
                "job_id": 1,
                "dl_name": "Imię Nazwisko-DL",
                "notes": "Kandydat Jan Kowalski-Notatka nie poszedł na rozmowę",
            }
        ],
        "lessons": [],
    }
    base.update(over)
    return base


def test_findings_name_the_gap_and_the_unknowns() -> None:
    text = " ".join(service.findings(_payload()))
    assert "37% przegranych i 83% wygranych" in text
    assert "mediana 3,5 i 4,1 dnia" in text
    assert "W 26 z 46 przegranych klient nie zaprosił" in text
    assert "W 29 z 46 przegranych nie wiemy" in text
    assert "14 przegranych zamknął NEXUS" in text
    assert "Nordea: 19 przegranych. CV nie przechodzą do rozmów." in text


def test_findings_without_losses() -> None:
    assert service.findings(
        _payload(counts={"won": 3, "lost": 0, "competitor": 0, "idle": 0})
    ) == ["W tym okresie nie ma przegranych rekrutacji."]


def test_model_input_has_no_people_or_notes() -> None:
    raw = json.dumps(
        service.model_input(_payload(period_label="listopad 2026")), ensure_ascii=False
    )
    assert "Nazwisko-DL" not in raw
    assert "Kowalski-Notatka" not in raw
    assert "Nordea" in raw and "listopad 2026" in raw
    # Model cytuje klucze w tekście dla ludzi — w wejściu są polskie nazwy etapów.
    assert "cv_only" not in raw and "no_cv" not in raw
    assert "CV bez rozmowy" in raw


def test_check_summary_keeps_known_clients_only() -> None:
    raw = json.dumps(
        {
            "wnioski": ["Przegrywamy przed rozmową: 26 z 46."],
            "rady": [
                {
                    "dla": "nordea",
                    "tekst": "CV z dowodem doświadczenia w pierwszym akapicie.",
                },
                {"dla": "Bank spoza danych", "tekst": "Coś."},
                {"dla": "wszyscy", "tekst": ""},
            ],
            "pytania_na_spotkanie": ["Czy pytamy HM o ocenę?"],
        }
    )
    out = service.check_summary("```json\n" + raw + "\n```", ["Nordea"])
    assert out["advice"] == [
        {"for": "Nordea", "text": "CV z dowodem doświadczenia w pierwszym akapicie."},
        {"for": "wszyscy", "text": "Coś."},
    ]
    assert out["questions"] == ["Czy pytamy HM o ocenę?"]


def test_check_summary_refuses_empty_reply() -> None:
    with pytest.raises(ValueError):
        service.check_summary('{"wnioski": [], "rady": []}', [])


def test_client_question_has_no_candidates_and_fits_the_case() -> None:
    q = service.client_question(
        title="Data Engineer", cvs=1, interviews=0, sender="Ola"
    )
    assert q["subject"] == "Krótkie pytanie o proces: Data Engineer"
    assert "Czego zabrakło naszemu kandydatowi?" in q["body"]
    assert q["body"].endswith("Ola")
    none_sent = service.client_question(title="X", cvs=0, interviews=0, sender=None)
    assert "kandydatów od nas na czas" in none_sent["body"]


def test_business_days_skip_the_weekend() -> None:
    friday = datetime(2026, 11, 20, 15, tzinfo=WARSAW)
    assert (
        service.business_days_since(friday, datetime(2026, 11, 24, 9, tzinfo=WARSAW))
        == 2
    )
    assert (
        service.business_days_since(friday, datetime(2026, 11, 25, 9, tzinfo=WARSAW))
        == 3
    )


def test_period_label() -> None:
    assert (
        period_label(resolve_period("month", anchor=datetime(2026, 11, 5).date()))
        == "listopad 2026"
    )
    assert (
        period_label(resolve_period("quarter", anchor=datetime(2026, 11, 5).date()))
        == "IV kwartał 2026"
    )


# ── Schemat i rejestr ───────────────────────────────────────────────────────


def test_schema_has_one_source_and_a_mirror() -> None:
    entrypoint = (BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    assert "from app.services import lost_review_schema" in entrypoint
    assert "*_LOST_REVIEW_TABLE_DDL," in entrypoint
    assert "*_LOST_REVIEW_AI_DDL," in entrypoint
    assert "ADD VALUE IF NOT EXISTS 'lost_review_summary'" in entrypoint
    # Bez numeru w ścieżce: pas migracji przepina numer, gdy inny PR wejdzie pierwszy.
    migration = next((BACKEND / "alembic/versions").glob("*_lost_review.py")).read_text(
        encoding="utf-8"
    )
    assert "from app.services import lost_review_schema as schema" in migration
    assert "schema.TABLE_DDL" in migration and "schema.AI_FEATURE_DDL" in migration


@pytest.mark.parametrize(("ddl", "model"), [(0, JobLossReview), (1, LostReviewLesson)])
def test_model_columns_match_the_ddl(ddl: int, model) -> None:
    columns = {
        line.split()[0]
        for line in schema.TABLE_DDL[ddl].splitlines()[1:]
        if line.split()[0] != ")"
    }
    assert columns == set(model.__table__.columns.keys())


def test_deep_health_probes_the_tables() -> None:
    main = (BACKEND / "app/main.py").read_text(encoding="utf-8")
    assert '("job_loss_reviews", JobLossReview)' in main
    assert '("lost_review_lessons", LostReviewLesson)' in main


def test_reminder_runs_in_the_idle_loop() -> None:
    idle = (BACKEND / "app/services/job_idle.py").read_text(encoding="utf-8")
    assert "run_ask_reminders_safely(moment)" in idle


# ── Baza: zamknięcie, odczyt modułu, wnioski, przypomnienie ────────────────


async def _job_via_api(app_client: AsyncClient, headers: dict[str, str]) -> int:
    from tests.test_job_close import _create_draft_job

    return await _create_draft_job(app_client, headers, "pytest-lost-review")


async def _sent_cv(job_id: int, *, client_reason: str | None = None) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.pipeline_template import (
        PipelineTemplate,
        RejectionReason,
        TerminalType,
    )
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    async with AsyncSessionLocal() as db:
        cand = Candidate(name="Przegrana", lastname=f"Test-{uuid.uuid4().hex[:8]}")
        db.add(cand)
        await db.flush()
        now = datetime.now(timezone.utc)
        db.add(
            CandidateStage(
                candidate_id=cand.id,
                job_id=job_id,
                stage=PipelineStage.cv_sent,
                moved_at=now - timedelta(hours=2),
            )
        )
        if client_reason:
            template = PipelineTemplate(name=f"Przegrane {uuid.uuid4().hex[:6]}")
            db.add(template)
            await db.flush()
            reason = RejectionReason(
                template_id=template.id,
                name=client_reason,
                category=TerminalType.rejected,
            )
            db.add(reason)
            await db.flush()
            db.add(
                CandidateStage(
                    candidate_id=cand.id,
                    job_id=job_id,
                    stage=PipelineStage.rejected,
                    moved_at=now - timedelta(hours=1),
                    ended_by="client",
                    rejection_reason_id=reason.id,
                )
            )
        await db.commit()


def _code(resp) -> str:
    return resp.json()["detail"]["code"]


@pytest.mark.asyncio
async def test_close_saves_what_decided_and_module_shows_it(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    job_id = await _job_via_api(app_client, app_auth_headers)
    await _sent_cv(job_id, client_reason="Brak doświadczenia")

    refused = await app_client.post(
        f"/api/jobs/{job_id}/close",
        json={
            "reason": "duplicate",
            "notes": "Duplikat",
            "lost_why": ["competitor_faster"],
            "acknowledge_active_cards": True,
        },
        headers=app_auth_headers,
    )
    assert refused.status_code == 422
    assert _code(refused) == "lost_why_not_lost"

    closed = await app_client.post(
        f"/api/jobs/{job_id}/close",
        json={
            "reason": "competitor",
            "lost_why": ["competitor_cheaper", "weaker_profile"],
            "lost_why_source": "client",
            "acknowledge_active_cards": True,
        },
        headers=app_auth_headers,
    )
    assert closed.status_code == 200, closed.text

    module = await app_client.get(
        "/api/insights/lost-review",
        params={"period": "month", "offset": 0},
        headers=app_auth_headers,
    )
    assert module.status_code == 200, module.text
    body = module.json()
    row = next(j for j in body["jobs"] if j["job_id"] == job_id)
    assert row["stage"] == "cv_only"
    assert row["cvs"] == 1
    assert row["why"] == ["competitor_cheaper", "weaker_profile"]
    assert row["source"] == "client"
    assert row["client_verdicts"] == ["Za mało doświadczenia"]
    assert body["period_label"]

    # Spotkanie: zmiana na „Nie wiemy” przez moduł, potem szkic pytania do HM.
    put = await app_client.put(
        f"/api/insights/lost-review/jobs/{job_id}/why",
        json={"why": [], "source": "unknown"},
        headers=app_auth_headers,
    )
    assert put.status_code == 200, put.text
    assert put.json() == {"job_id": job_id, "why": [], "source": "unknown"}
    question = await app_client.get(
        f"/api/insights/lost-review/jobs/{job_id}/client-question",
        headers=app_auth_headers,
    )
    assert question.status_code == 200
    assert "Czego zabrakło naszemu kandydatowi?" in question.json()["body"]


@pytest.mark.asyncio
async def test_why_refused_on_open_job(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    job_id = await _job_via_api(app_client, app_auth_headers)
    resp = await app_client.put(
        f"/api/insights/lost-review/jobs/{job_id}/why",
        json={"why": ["too_few_cvs"]},
        headers=app_auth_headers,
    )
    assert resp.status_code == 422
    assert _code(resp) == "lost_why_not_lost"


@pytest.mark.asyncio
async def test_client_lesson_becomes_a_rule_and_can_be_archived(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    job_id = await _job_via_api(app_client, app_auth_headers)
    created = await app_client.post(
        "/api/insights/lost-review/lessons",
        json={"scope": "client", "text": "  Pierwsze CV   do 48 h  ", "job_id": job_id},
        headers=app_auth_headers,
    )
    assert created.status_code == 201, created.text
    lesson = created.json()
    assert lesson["text"] == "Pierwsze CV do 48 h"
    assert lesson["client_id"] is not None
    rules = await app_client.get(
        f"/api/insights/lost-review/client-rules/{lesson['client_id']}",
        headers=app_auth_headers,
    )
    assert any(r["id"] == lesson["id"] for r in rules.json()["rules"])
    gone = await app_client.delete(
        f"/api/insights/lost-review/lessons/{lesson['id']}", headers=app_auth_headers
    )
    assert gone.status_code == 204
    rules = await app_client.get(
        f"/api/insights/lost-review/client-rules/{lesson['client_id']}",
        headers=app_auth_headers,
    )
    assert all(r["id"] != lesson["id"] for r in rules.json()["rules"])


@pytest.mark.asyncio
async def test_unknown_source_rings_the_dl_after_three_business_days(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    from app.core.database import AsyncSessionLocal

    job_id = await _job_via_api(app_client, app_auth_headers)
    closed = await app_client.post(
        f"/api/jobs/{job_id}/close",
        json={
            "reason": "competitor",
            "lost_why_source": "unknown",
            "acknowledge_active_cards": True,
        },
        headers=app_auth_headers,
    )
    assert closed.status_code == 200, closed.text
    async with AsyncSessionLocal() as db:
        row = await db.get(JobLossReview, job_id)
        assert row is not None and row.source == "unknown"
        too_early = row.updated_at + timedelta(days=1)
        await service.run_ask_reminders(db, now=too_early)
        assert row.ask_reminded_at is None
        later = row.updated_at + timedelta(days=7)
        await service.run_ask_reminders(db, now=later)
        assert row.ask_reminded_at == later
        await db.commit()
        # Drugi przebieg nie dzwoni drugi raz.
        assert (
            await db.scalar(
                select(JobLossReview.ask_reminded_at).where(
                    JobLossReview.job_id == job_id
                )
            )
        ) == later


@pytest.mark.asyncio
async def test_ai_summary_uses_model_reply_and_caches(
    app_client: AsyncClient, app_auth_headers: dict[str, str], monkeypatch
) -> None:
    job_id = await _job_via_api(app_client, app_auth_headers)
    await _sent_cv(job_id)
    closed = await app_client.post(
        f"/api/jobs/{job_id}/close",
        json={"reason": "competitor", "acknowledge_active_cards": True},
        headers=app_auth_headers,
    )
    assert closed.status_code == 200, closed.text
    calls: list[str] = []

    def fake_model(prompt: str) -> str:
        calls.append(prompt)
        return json.dumps(
            {
                "wnioski": ["Przegrywamy przed rozmową."],
                "rady": [
                    {"dla": "wszyscy", "tekst": "Pytajcie HM o ocenę po każdym CV."}
                ],
                "pytania_na_spotkanie": ["Kto pyta klienta?"],
            }
        )

    monkeypatch.setattr(service, "_call_model", fake_model)
    monkeypatch.setattr(
        "app.services.llm_providers.api_key_configured", lambda model: True
    )
    resp = await app_client.post(
        "/api/insights/lost-review/ai-summary",
        params={"period": "month", "offset": 0, "refresh": True},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["advice"] == [
        {"for": "wszyscy", "text": "Pytajcie HM o ocenę po każdym CV."}
    ]
    assert body["cached"] is False
    assert len(calls) == 1
    assert "Pytest Admin" not in calls[0]
    again = await app_client.post(
        "/api/insights/lost-review/ai-summary",
        params={"period": "month", "offset": 0},
        headers=app_auth_headers,
    )
    assert again.status_code == 200
    assert again.json()["cached"] is True
    assert len(calls) == 1


def test_viewer_roles_mirror_the_front() -> None:
    front = (BACKEND.parent / "frontend/src/lib/insights-roles.ts").read_text(
        encoding="utf-8"
    )
    line = next(
        row for row in front.splitlines() if "LOST_REVIEW_ROLES" in row and "=" in row
    )
    for role in service.VIEWER_ROLES:
        assert f'"{role.value}"' in line


def test_why_and_sources_mirror_the_front() -> None:
    front = (BACKEND.parent / "frontend/src/lib/lost-review.ts").read_text(
        encoding="utf-8"
    )
    for key, label in service.WHY.items():
        assert f'{{ key: "{key}", label: "{label}" }}' in front
    for key, label in service.SOURCES.items():
        assert f'{{ key: "{key}", label: "{label}" }}' in front


@pytest.mark.asyncio
async def test_close_with_hire_ignores_what_decided_instead_of_refusing(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    """Rekrutacja na kilka miejsc: jedno obsadziliśmy, resztę wzięła konkurencja.

    To wygrana w hit ratio, a pola „Co zdecydowało?” są opcjonalne — zamknięcie
    przechodzi, wybór się nie zapisuje (przegląd kodu 25.11.2026).
    """
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    job_id = await _job_via_api(app_client, app_auth_headers)
    async with AsyncSessionLocal() as db:
        cand = Candidate(name="Zatrudniony", lastname=f"Test-{uuid.uuid4().hex[:8]}")
        db.add(cand)
        await db.flush()
        db.add(
            CandidateStage(
                candidate_id=cand.id,
                job_id=job_id,
                stage=PipelineStage.hired,
                moved_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()
    closed = await app_client.post(
        f"/api/jobs/{job_id}/close",
        json={
            "reason": "competitor",
            "lost_why": ["competitor_faster"],
            "acknowledge_active_cards": True,
        },
        headers=app_auth_headers,
    )
    assert closed.status_code == 200, closed.text
    async with AsyncSessionLocal() as db:
        assert await db.get(JobLossReview, job_id) is None
