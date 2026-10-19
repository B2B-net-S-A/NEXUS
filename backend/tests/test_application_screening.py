"""Zgłoszenia z linku rekrutacji przegląda AI przed „Nowi” (0404, 29.09.2026).

Pokrywa:

- regułę werdyktu (tabela przypadków) — ``not_fit`` tylko, gdy model i kod
  się zgadzają; awaria modelu, brak CV = ``unclear``;
- odrzucenie powodu, którego cytatu nie ma w CV;
- link rekrutacji NIE otwiera procesu w requeście, stały link bez zmian,
  wyłączona flaga = dawne zachowanie;
- decyzję pętli: „Nowi” z plakietką, „Odrzuceni przez AI”, czarna lista,
  istniejący kandydat, „Dodaj mimo to”.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.application_screening import ApplicationScreening
from app.models.candidate import Candidate, CandidateStatus
from app.models.candidate_source_event import CandidateSourceEvent
from app.models.notification import Notification, NotificationType
from app.models.recruitment_pipeline import CandidateStage
from app.models.recruitment_process import RecruitmentProcess
from app.services import application_screening as svc
from app.services.process_entry_meta import application_screening_badge
from tests.test_career_links_api import (
    _approve,
    _create_job_link,
    _cv,
    _form,
    _owner_with_job,
)

CV_TEXT = (
    "Jan Kandydacki\n"
    "Samodzielna księgowa w biurze rachunkowym (2019–2025).\n"
    "Umiejętności: Excel, Symfonia, Płatnik."
)
JAVA_CV = "Senior Java Developer. Java 17, Spring Boot, Kafka — 6 lat w bankowości."


# ── Reguła (bez bazy) ───────────────────────────────────────────────────────

_QUOTED = [{"text": "Inna dziedzina.", "quote": "księgowa"}]


@pytest.mark.parametrize(
    ("model_verdict", "reasons", "found", "total", "expected"),
    [
        # Model i kod zgodni: odrzucenie.
        ("not_fit", _QUOTED, 0, 3, "not_fit"),
        ("not_fit", _QUOTED, 1, 3, "not_fit"),
        # Kod widzi ≥ 50% must-have — nie odrzucamy.
        ("not_fit", _QUOTED, 2, 4, "unclear"),
        ("not_fit", _QUOTED, 3, 3, "unclear"),
        # Rekrutacja bez must-have technologii: decyduje cytat modelu.
        ("not_fit", _QUOTED, 0, 0, "not_fit"),
        # Bez sprawdzonego cytatu nikogo nie odrzucamy.
        ("not_fit", [], 0, 3, "unclear"),
        ("not_fit", [], 0, 0, "unclear"),
        # „Pasuje” bez pokrycia must-have = do sprawdzenia.
        ("fits", [], 3, 3, "fits"),
        ("fits", [], 0, 0, "fits"),
        ("fits", [], 1, 3, "unclear"),
        ("unclear", _QUOTED, 0, 3, "unclear"),
        # Awaria / brak werdyktu.
        (None, [], 0, 3, "unclear"),
        ("maybe", _QUOTED, 0, 3, "unclear"),
    ],
)
def test_verdict_rule_table(model_verdict, reasons, found, total, expected):
    assert (
        svc.decide(
            model_verdict=model_verdict,
            kept_reasons=reasons,
            must_found=found,
            must_total=total,
        )
        == expected
    )


def test_quote_outside_cv_is_dropped():
    kept = svc.keep_quoted_reasons(
        [
            {
                "text": "Pracuje w księgowości.",
                "quote": "Samodzielna  księgowa\nw biurze",
            },
            {"text": "Nie zna Javy.", "quote": "Brak doświadczenia z Javą"},
            {"text": "Bez cytatu.", "quote": ""},
            "śmieci",
        ],
        [CV_TEXT],
    )
    assert kept == [
        {"text": "Pracuje w księgowości.", "quote": "Samodzielna  księgowa\nw biurze"}
    ]


def test_reasons_are_capped_and_trimmed():
    many = [{"text": "x" * 500, "quote": "Excel"} for _ in range(10)]
    kept = svc.keep_quoted_reasons(many, [CV_TEXT])
    assert len(kept) == svc.REASON_LIMIT
    assert len(kept[0]["text"]) == svc.REASON_TEXT_MAX


def test_parse_model_accepts_fenced_json_and_rejects_prose():
    verdict, reasons = svc.parse_model(
        '```json\n{"verdict": "not_fit", "reasons": [{"text": "a", "quote": "b"}]}\n```'
    )
    assert verdict == "not_fit" and reasons == [{"text": "a", "quote": "b"}]
    assert svc.parse_model('{"verdict": "whatever"}') == (None, [])
    with pytest.raises(ValueError):
        svc.parse_model("Nie umiem ocenić.")


def test_prompt_forbids_inferring_from_personal_traits():
    from app.services.llm_prompts import APPLICATION_SCREENING

    system = APPLICATION_SCREENING.system_prompt or ""
    for word in ("imienia", "wieku", "płci", "narodowości", "zdjęcia"):
        assert word in system


def test_badge_reads_only_known_fields():
    assert application_screening_badge({"kind": "auto_match", "score": 70}) is None
    assert application_screening_badge({"kind": "application_screening"}) is None
    assert application_screening_badge(
        {
            "kind": "application_screening",
            "verdict": "fits",
            "assessed": True,
            "must_found": 2,
            "must_total": 3,
        }
    ) == {
        "verdict": "fits",
        "assessed": True,
        "must_found": 2,
        "must_total": 3,
        "overridden": False,
        "deal_breaker_hit": False,
        "deal_breaker": None,
    }


def test_screening_applies_only_to_job_links(monkeypatch):
    class _Link:
        def __init__(self, kind, job_id):
            self.kind, self.job_id = kind, job_id

    monkeypatch.setattr(settings, "APPLICATION_SCREENING_ENABLED", True)
    assert svc.screening_applies(_Link("job", 5))
    assert not svc.screening_applies(_Link("recruiter", None))
    monkeypatch.setattr(settings, "APPLICATION_SCREENING_ENABLED", False)
    assert not svc.screening_applies(_Link("job", 5))


# ── Przepływ (baza) ─────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def api() -> AsyncClient:
    from app.core.rate_limit import limiter
    from app.main import app

    limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as client:
        yield client


@pytest.fixture(autouse=True)
def _stub_background(monkeypatch):
    async def _noop_embed(candidate_id, db):
        return True

    async def _noop_task(*args, **kwargs):
        return None

    monkeypatch.setattr("app.services.embedding_service.embed_candidate", _noop_embed)
    monkeypatch.setattr("app.api.public_share._invite_post_apply_task", _noop_task)


@pytest.fixture
def screening_on(monkeypatch):
    monkeypatch.setattr(settings, "APPLICATION_SCREENING_ENABLED", True)


def _luna(payload: dict | Exception, calls: list | None = None):
    def _fake(prompt: str) -> str:
        if calls is not None:
            calls.append(prompt)
        if isinstance(payload, Exception):
            raise payload
        return json.dumps(payload)

    return _fake


async def _apply(api, **extra):
    uid, headers, job_id = await _owner_with_job(api)
    link = await _create_job_link(api, headers, job_id)
    assert (await _approve(api, headers, job_id)).status_code == 200
    email = extra.pop("email", None) or f"scr-{uuid.uuid4().hex[:8]}@example.com"
    resp = await api.post(
        "/api/public/career/apply",
        data=_form(link["slug"], email, **extra),
        files=_cv(),
    )
    assert resp.status_code == 201, resp.text
    return uid, headers, job_id, email


async def _row_for(job_id: int) -> ApplicationScreening:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(ApplicationScreening).where(ApplicationScreening.job_id == job_id)
        )


async def _set_cv(row_id: int, text: str) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(ApplicationScreening)
            .where(ApplicationScreening.id == row_id)
            .values(cv_text=text)
        )
        await db.commit()


async def _stage(candidate_id: int, job_id: int):
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(CandidateStage).where(
                CandidateStage.candidate_id == candidate_id,
                CandidateStage.job_id == job_id,
            )
        )


async def test_job_link_does_not_open_process_in_request(api, screening_on):
    uid, _, job_id, email = await _apply(api, utm_source="justjoinit")
    async with AsyncSessionLocal() as db:
        cand = await db.scalar(select(Candidate).where(Candidate.email == email))
        assert cand is not None
        assert await _stage(cand.id, job_id) is None
        row = await _row_for(job_id)
        assert row is not None and row.status == "pending"
        assert row.candidate_id == cand.id and row.submission_id is None
        assert row.context["utm_source"] == "justjoinit"
        assert row.context["link_owner_id"] == uid
        # Dzwonek dopiero po decyzji pętli.
        assert (
            await db.scalar(
                select(Notification).where(
                    Notification.user_id == uid,
                    Notification.notification_type == NotificationType.new_application,
                    Notification.related_entity_id == cand.id,
                )
            )
        ) is None


async def test_flag_off_opens_process_in_request_as_before(api):
    _, _, job_id, email = await _apply(api)
    async with AsyncSessionLocal() as db:
        cand = await db.scalar(select(Candidate).where(Candidate.email == email))
    assert await _stage(cand.id, job_id) is not None
    assert await _row_for(job_id) is None


async def test_recruiter_link_is_unchanged(api, screening_on):
    uid, headers, _ = await _owner_with_job(api)
    slug = f"scr-{uuid.uuid4().hex[:6]}"
    assert (
        await api.put("/api/me/career-link", json={"slug": slug}, headers=headers)
    ).status_code == 200
    email = f"scr-rec-{uuid.uuid4().hex[:6]}@example.com"
    resp = await api.post(
        "/api/public/career/apply", data=_form(slug, email), files=_cv()
    )
    assert resp.status_code == 201, resp.text
    async with AsyncSessionLocal() as db:
        cand = await db.scalar(select(Candidate).where(Candidate.email == email))
        assert (
            await db.scalar(
                select(ApplicationScreening.id).where(
                    ApplicationScreening.candidate_id == cand.id
                )
            )
        ) is None
        assert (
            await db.scalar(
                select(Notification.id).where(
                    Notification.user_id == uid,
                    Notification.related_entity_id == cand.id,
                )
            )
        ) is not None


async def test_fitting_application_enters_new_with_badge(
    api, screening_on, monkeypatch
):
    uid, _, job_id, email = await _apply(api)
    row = await _row_for(job_id)
    await _set_cv(row.id, JAVA_CV)
    calls: list[str] = []
    monkeypatch.setattr(
        svc,
        "_call_model",
        _luna(
            {
                "verdict": "fits",
                "reasons": [
                    {"text": "Java w bankowości.", "quote": "Java 17, Spring Boot"}
                ],
            },
            calls,
        ),
    )
    assert await svc.process_one(row.id) == "added"
    assert calls and "<cv>" in calls[0] and "Rola:" in calls[0]
    stage = await _stage(row.candidate_id, job_id)
    assert stage is not None
    async with AsyncSessionLocal() as db:
        process = await db.scalar(
            select(RecruitmentProcess).where(
                RecruitmentProcess.candidate_id == row.candidate_id,
                RecruitmentProcess.job_id == job_id,
            )
        )
        assert process.entry_source == "application"
        assert application_screening_badge(process.entry_meta)["verdict"] == "fits"
        done = await db.get(ApplicationScreening, row.id)
        assert done.outcome == "added" and done.cv_text is None
        assert done.must_found == done.must_total
        assert (
            await db.scalar(
                select(Notification.id).where(
                    Notification.user_id == uid,
                    Notification.notification_type == NotificationType.new_application,
                    Notification.related_entity_id == row.candidate_id,
                )
            )
        ) is not None


async def test_not_fitting_application_stays_in_base_and_can_be_added(
    api, screening_on, monkeypatch
):
    _, headers, job_id, _ = await _apply(api)
    row = await _row_for(job_id)
    await _set_cv(row.id, CV_TEXT)
    monkeypatch.setattr(
        svc,
        "_call_model",
        _luna(
            {
                "verdict": "not_fit",
                "reasons": [
                    {
                        "text": "Księgowość, nie programowanie.",
                        "quote": "Samodzielna księgowa",
                    },
                    {"text": "Wymyślony powód.", "quote": "10 lat w Javie"},
                ],
            }
        ),
    )
    assert await svc.process_one(row.id) == "screened_out"
    assert await _stage(row.candidate_id, job_id) is None

    listed = await api.get(f"/api/jobs/{job_id}/screened-out", headers=headers)
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["candidate_id"] == row.candidate_id
    assert item["must_found"] == 0
    # Powód z cytatem spoza CV wypadł.
    assert [r["quote"] for r in item["reasons"]] == ["Samodzielna księgowa"]
    assert "email" not in item and "phone" not in item

    added = await api.post(
        f"/api/jobs/{job_id}/screened-out/{row.id}/add", headers=headers
    )
    assert added.status_code == 200, added.text
    assert await _stage(row.candidate_id, job_id) is not None
    async with AsyncSessionLocal() as db:
        done = await db.get(ApplicationScreening, row.id)
        assert done.outcome == "added" and done.overridden_by is not None
        assert (
            await db.scalar(
                select(Activity.id).where(
                    Activity.entity_id == row.candidate_id,
                    Activity.action == "application_screening_overridden",
                )
            )
        ) is not None
    again = await api.post(
        f"/api/jobs/{job_id}/screened-out/{row.id}/add", headers=headers
    )
    assert again.status_code == 409
    assert (await api.get(f"/api/jobs/{job_id}/screened-out", headers=headers)).json()[
        "total"
    ] == 0


async def test_model_failure_adds_person_as_not_assessed(
    api, screening_on, monkeypatch
):
    _, _, job_id, _ = await _apply(api)
    row = await _row_for(job_id)
    await _set_cv(row.id, CV_TEXT)
    monkeypatch.setattr(svc, "_call_model", _luna(RuntimeError("provider down")))
    assert await svc.process_one(row.id) == "added"
    async with AsyncSessionLocal() as db:
        done = await db.get(ApplicationScreening, row.id)
        assert done.verdict == "unclear"
        assert done.error == "model_error:RuntimeError"
        process = await db.scalar(
            select(RecruitmentProcess).where(
                RecruitmentProcess.candidate_id == row.candidate_id,
                RecruitmentProcess.job_id == job_id,
            )
        )
        assert application_screening_badge(process.entry_meta)["assessed"] is False


async def test_missing_cv_adds_without_calling_the_model(
    api, screening_on, monkeypatch
):
    _, _, job_id, _ = await _apply(api)
    row = await _row_for(job_id)
    calls: list[str] = []
    monkeypatch.setattr(svc, "_call_model", _luna({"verdict": "not_fit"}, calls))
    assert await svc.process_one(row.id) == "added"
    assert calls == []
    async with AsyncSessionLocal() as db:
        assert (await db.get(ApplicationScreening, row.id)).error == "no_cv"


async def test_blacklisted_existing_candidate_is_blocked(
    api, screening_on, monkeypatch
):
    uid, headers, job_id = await _owner_with_job(api)
    link = await _create_job_link(api, headers, job_id)
    assert (await _approve(api, headers, job_id)).status_code == 200
    email = f"scr-black-{uuid.uuid4().hex[:6]}@example.com"
    async with AsyncSessionLocal() as db:
        existing = Candidate(
            name="Stary",
            lastname="Profil",
            email=email,
            status=CandidateStatus.blacklisted,
        )
        db.add(existing)
        await db.commit()
        existing_id = existing.id
    resp = await api.post(
        "/api/public/career/apply",
        data=_form(link["slug"], email, utm_source="rocketjobs"),
        files=_cv(),
    )
    assert resp.status_code == 201, resp.text
    row = await _row_for(job_id)
    assert row.candidate_id == existing_id and row.submission_id is not None
    monkeypatch.setattr(svc, "_call_model", _luna({"verdict": "fits"}))
    assert await svc.process_one(row.id) == "blocked"
    assert await _stage(existing_id, job_id) is None
    async with AsyncSessionLocal() as db:
        # Źródło zgłoszenia także dla osoby już w bazie.
        source = await db.scalar(
            select(CandidateSourceEvent).where(
                CandidateSourceEvent.candidate_id == existing_id
            )
        )
        assert source is not None and source.utm_source == "rocketjobs"
        assert (
            await db.scalar(
                select(Notification.id).where(
                    Notification.user_id == uid,
                    Notification.related_entity_id == existing_id,
                )
            )
        ) is not None


async def test_existing_candidate_uses_submitted_cv(api, screening_on, monkeypatch):
    _, headers, job_id = await _owner_with_job(api)
    link = await _create_job_link(api, headers, job_id)
    assert (await _approve(api, headers, job_id)).status_code == 200
    email = f"scr-dup-{uuid.uuid4().hex[:6]}@example.com"
    async with AsyncSessionLocal() as db:
        db.add(Candidate(name="Stary", lastname="Profil", email=email))
        await db.commit()
    resp = await api.post(
        "/api/public/career/apply", data=_form(link["slug"], email), files=_cv()
    )
    assert resp.status_code == 201, resp.text
    row = await _row_for(job_id)
    await _set_cv(row.id, JAVA_CV)
    monkeypatch.setattr(
        svc,
        "_call_model",
        _luna({"verdict": "fits", "reasons": [{"text": "Java.", "quote": "Java 17"}]}),
    )
    # Istniejący kandydat nie czeka na odczyt CV — gotowy od razu po MIN_AGE.
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(ApplicationScreening)
            .where(ApplicationScreening.id == row.id)
            .values(created_at=datetime.now(timezone.utc) - timedelta(minutes=1))
        )
        await db.commit()
    assert row.id in await svc.claim_batch(limit=100)
    assert await svc.process_one(row.id) == "added"


async def test_job_closed_after_apply_still_adds_person_without_model(
    api, screening_on, monkeypatch
):
    """Przegląd kodu 29.09.2026: zgłoszenie do rekrutacji zamkniętej, zanim
    pętla je oceniła, znikało — bez procesu, dzwonka i wpisu na liście."""
    from app.models.job import Job, JobStatus

    def never(_prompt):
        raise AssertionError("model nie powinien oceniać zamkniętej rekrutacji")

    monkeypatch.setattr(svc, "_call_model", never)
    _, _, job_id, _ = await _apply(api)
    row = await _row_for(job_id)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Job).where(Job.id == job_id).values(status=JobStatus.closed)
        )
        await db.commit()
    assert await svc.process_one(row.id) == "added"
    assert await _stage(row.candidate_id, job_id) is not None


async def test_new_candidate_waits_for_cv_before_claim(api, screening_on):
    _, _, job_id, _ = await _apply(api)
    row = await _row_for(job_id)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(ApplicationScreening)
            .where(ApplicationScreening.id == row.id)
            .values(created_at=datetime.now(timezone.utc) - timedelta(minutes=1))
        )
        await db.commit()
    # CV nieodczytane, zgłoszenie młodsze niż 10 min — czeka.
    assert row.id not in await svc.claim_batch(limit=100)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(ApplicationScreening)
            .where(ApplicationScreening.id == row.id)
            .values(created_at=datetime.now(timezone.utc) - timedelta(minutes=11))
        )
        await db.commit()
    assert row.id in await svc.claim_batch(limit=100)


# ── Etap 2 linków (19.10.2026): karta z linku jest właściciela linku ────────


async def _process(candidate_id: int, job_id: int) -> RecruitmentProcess:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(RecruitmentProcess)
            .where(
                RecruitmentProcess.candidate_id == candidate_id,
                RecruitmentProcess.job_id == job_id,
            )
            .order_by(RecruitmentProcess.id.desc())
            .limit(1)
        )


async def _bells(user_id: int, candidate_id: int) -> list[str]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(Notification.message).where(
                        Notification.user_id == user_id,
                        Notification.related_entity_id == candidate_id,
                    )
                )
            ).all()
        )


def _assert_claimed_for(process: RecruitmentProcess, owner_id: int) -> None:
    from app.services.process_entry_meta import application_link_owner_id

    now = datetime.now(timezone.utc)
    assert process.claimed_by_user_id == owner_id
    # 12 h od wejścia karty do „Nowi” (decyzja A), nie od wysłania formularza.
    assert now + timedelta(hours=11, minutes=55) < process.claimed_until
    assert process.claimed_until <= now + timedelta(hours=12)
    assert process.owner_user_id == owner_id
    # Decyzja B: Liga i Cele bez zmian — kredyt KPI dalej przy weryfikacji.
    assert process.kpi_eligible is None and process.credit_user_id is None
    assert application_link_owner_id(process.entry_meta) == owner_id


def test_link_owner_reads_only_application_entries():
    from app.services.process_entry_meta import (
        application_link_entry_meta,
        application_link_owner_id,
        application_screening_entry_meta,
    )

    assert application_link_owner_id(application_link_entry_meta(7)) == 7
    screened = application_screening_entry_meta(
        verdict="fits", assessed=True, must_found=1, must_total=1, link_owner_id=9
    )
    assert application_link_owner_id(screened) == 9
    assert application_screening_badge(screened)["verdict"] == "fits"
    assert application_link_owner_id({"kind": "auto_match", "link_owner_id": 7}) is None
    assert application_link_owner_id({"kind": "application_link"}) is None
    assert (
        application_link_owner_id({"kind": "application_link", "link_owner_id": True})
        is None
    )
    assert application_link_owner_id(None) is None


async def test_flag_off_new_application_is_claimed_for_link_owner(api):
    uid, _, job_id, email = await _apply(api)
    async with AsyncSessionLocal() as db:
        cand = await db.scalar(select(Candidate).where(Candidate.email == email))
    _assert_claimed_for(await _process(cand.id, job_id), uid)
    assert any("jest Twoja do" in m for m in await _bells(uid, cand.id))


async def test_flag_off_existing_candidate_is_claimed_for_link_owner(api):
    uid, headers, job_id = await _owner_with_job(api)
    link = await _create_job_link(api, headers, job_id)
    assert (await _approve(api, headers, job_id)).status_code == 200
    email = f"scr-own-{uuid.uuid4().hex[:6]}@example.com"
    async with AsyncSessionLocal() as db:
        existing = Candidate(name="Stary", lastname="Profil", email=email)
        db.add(existing)
        await db.commit()
        existing_id = existing.id
    resp = await api.post(
        "/api/public/career/apply", data=_form(link["slug"], email), files=_cv()
    )
    assert resp.status_code == 201, resp.text
    _assert_claimed_for(await _process(existing_id, job_id), uid)
    assert any("jest Twoja do" in m for m in await _bells(uid, existing_id))


async def test_screened_application_is_claimed_from_entry_to_new(
    api, screening_on, monkeypatch
):
    uid, _, job_id, _ = await _apply(api)
    row = await _row_for(job_id)
    # Przegląd trwał 3 h — blokada i tak liczy 12 h od wejścia do „Nowi”.
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(ApplicationScreening)
            .where(ApplicationScreening.id == row.id)
            .values(created_at=datetime.now(timezone.utc) - timedelta(hours=3))
        )
        await db.commit()
    await _set_cv(row.id, JAVA_CV)
    monkeypatch.setattr(svc, "_call_model", _luna({"verdict": "fits"}))
    assert await svc.process_one(row.id) == "added"
    _assert_claimed_for(await _process(row.candidate_id, job_id), uid)
    assert any("jest Twoja do" in m for m in await _bells(uid, row.candidate_id))


async def test_add_despite_claims_for_link_owner_not_for_clicker(
    api, screening_on, monkeypatch
):
    from tests.test_career_links_api import _seed_user

    uid, _, job_id, _ = await _apply(api)
    clicker_id, _, _ = await _seed_user("clicker")
    row = await _row_for(job_id)
    await _set_cv(row.id, CV_TEXT)
    monkeypatch.setattr(
        svc,
        "_call_model",
        _luna(
            {
                "verdict": "not_fit",
                "reasons": [
                    {"text": "Inna dziedzina.", "quote": "Samodzielna księgowa"}
                ],
            }
        ),
    )
    assert await svc.process_one(row.id) == "screened_out"
    async with AsyncSessionLocal() as db:
        await svc.add_despite(
            db, job_id=job_id, screening_id=row.id, user_id=clicker_id
        )
        await db.commit()
        assert (await db.get(ApplicationScreening, row.id)).overridden_by == clicker_id
    process = await _process(row.candidate_id, job_id)
    _assert_claimed_for(process, uid)
    assert application_screening_badge(process.entry_meta)["overridden"] is True


async def test_inactive_link_owner_gets_no_claim(api, screening_on, monkeypatch):
    from app.models.user import User

    uid, _, job_id, _ = await _apply(api)
    row = await _row_for(job_id)
    async with AsyncSessionLocal() as db:
        await db.execute(update(User).where(User.id == uid).values(is_active=False))
        await db.commit()
    monkeypatch.setattr(svc, "_call_model", _luna({"verdict": "fits"}))
    assert await svc.process_one(row.id) == "added"
    process = await _process(row.candidate_id, job_id)
    assert process.claimed_by_user_id is None and process.claimed_until is None
    assert process.owner_user_id != uid


async def _candidate_led_by_someone_else(job_id: int) -> tuple[int, int, str, str]:
    """Osoba już w rekrutacji, prowadzi ją inny rekruter (blokada 12 h)."""
    from app.models.recruitment_pipeline import PipelineStage
    from app.models.user import User
    from app.services import candidate_claim
    from app.services.recruitment_process_commands import open_process
    from tests.test_career_links_api import _seed_user

    lead_id, _, _ = await _seed_user("lead")
    email = f"scr-led-{uuid.uuid4().hex[:6]}@example.com"
    async with AsyncSessionLocal() as db:
        cand = Candidate(name="Jan", lastname="Prowadzony", email=email)
        db.add(cand)
        await db.flush()
        await open_process(
            db,
            candidate_id=cand.id,
            job_id=job_id,
            stage=PipelineStage.new,
            actor_user_id=lead_id,
            entry_source=candidate_claim.ENTRY_ADDED_MANUAL,
            claim_for_user_id=lead_id,
        )
        lead_name = (await db.get(User, lead_id)).name
        await db.commit()
        return cand.id, lead_id, lead_name, email


async def _assert_two_bells(
    owner_id: int, lead_id: int, cand_id: int, lead_name: str, job_id: int
) -> None:
    owner_bells = await _bells(owner_id, cand_id)
    assert any(
        "jest już w tej rekrutacji" in m
        and f"prowadzi {lead_name}" in m
        and "etap" in m
        for m in owner_bells
    ), owner_bells
    lead_bells = await _bells(lead_id, cand_id)
    assert any("zgłosił(a) się ponownie przez link" in m for m in lead_bells), (
        lead_bells
    )
    # Karta i blokada prowadzącego bez zmian.
    assert (await _process(cand_id, job_id)).claimed_by_user_id == lead_id


async def test_already_in_job_rings_link_owner_and_lead_with_screening(
    api, screening_on, monkeypatch
):
    uid, headers, job_id = await _owner_with_job(api)
    link = await _create_job_link(api, headers, job_id)
    assert (await _approve(api, headers, job_id)).status_code == 200
    cand_id, lead_id, lead_name, email = await _candidate_led_by_someone_else(job_id)
    resp = await api.post(
        "/api/public/career/apply", data=_form(link["slug"], email), files=_cv()
    )
    assert resp.status_code == 201, resp.text
    row = await _row_for(job_id)
    monkeypatch.setattr(svc, "_call_model", _luna({"verdict": "fits"}))
    assert await svc.process_one(row.id) == "already_in_job"
    await _assert_two_bells(uid, lead_id, cand_id, lead_name, job_id)


async def test_already_in_job_rings_link_owner_and_lead_without_screening(api):
    uid, headers, job_id = await _owner_with_job(api)
    link = await _create_job_link(api, headers, job_id)
    assert (await _approve(api, headers, job_id)).status_code == 200
    cand_id, lead_id, lead_name, email = await _candidate_led_by_someone_else(job_id)
    resp = await api.post(
        "/api/public/career/apply", data=_form(link["slug"], email), files=_cv()
    )
    assert resp.status_code == 201, resp.text
    await _assert_two_bells(uid, lead_id, cand_id, lead_name, job_id)


async def test_board_card_names_the_link_owner(api):
    uid, headers, job_id, email = await _apply(api)
    async with AsyncSessionLocal() as db:
        cand = await db.scalar(select(Candidate).where(Candidate.email == email))
    board = await api.get(f"/api/pipeline/kanban/{job_id}", headers=headers)
    assert board.status_code == 200, board.text
    card = next(
        item
        for col in board.json()["columns"]
        for item in col.get("items", [])
        if item.get("candidate_id") == cand.id
    )
    assert card["entry_source"] == "application"
    assert card["entry_link_owner_id"] == uid
    assert card["entry_link_owner_name"].startswith("Marta Rekruterska")
    assert card["claim_user_id"] == uid
