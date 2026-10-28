"""„Oceń z AI” na zaznaczonych osobach (0609, 28.10.2026).

Pokrywa:

- regułę werdyktu (tabela) — „Dzwoń” i „Nie pasuje” tylko z cytatem, „Dzwoń”
  przy must-have w < 50% spada do „Może”, brak werdyktu = „AI nie oceniło”;
- powód, którego cytatu nie ma w CV ani notatce, znika; cytat z notatki
  jest oznaczony jako notatka;
- kolejność dzwonienia;
- trasę na bazie: zapis przy rekrutacji i zdarzenie audytu, brak CV i awaria
  modelu bez werdyktu, odmowa bez uprawnienia, dzienny limit, powrót do
  wyniku bez ponownego wywołania modelu.

Dane fikcyjne. Baza testowa jest wspólna: każdy test tworzy własne dane.
"""

from __future__ import annotations

import json
import os
import uuid

import pytest
from sqlalchemy import select

from app.services import candidate_ai_assessment as svc
from tests.test_my_people import _candidate, _job, _user

needs_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="wymaga PostgreSQL"
)

FIT_CV = (
    "Inżynier IAM. 2019–2025: wdrożenia SailPoint IdentityIQ w banku, "
    "onboarding aplikacji, przeglądy dostępu."
)
OTHER_CV = "Specjalistka ds. kadr i płac. Obsługa programu Płatnik, Excel."
_QUOTED = [{"text": "Wdrażał IdentityIQ.", "quote": "SailPoint IdentityIQ"}]


# ── Reguła (bez bazy) ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("model_verdict", "reasons", "found", "total", "expected"),
    [
        ("call", _QUOTED, 2, 2, "call"),
        ("call", _QUOTED, 0, 0, "call"),
        # „Dzwoń” bez cytatu albo bez pokrycia must-have — do dopytania.
        ("call", [], 2, 2, "maybe"),
        ("call", _QUOTED, 1, 3, "maybe"),
        # „Nie pasuje” zostaje z cytatem, także gdy słowo stoi w tekście.
        ("no_fit", _QUOTED, 2, 2, "no_fit"),
        ("no_fit", [], 0, 2, "maybe"),
        ("maybe", [], 0, 2, "maybe"),
        # Awaria / werdykt spoza listy = AI nie oceniło.
        (None, _QUOTED, 2, 2, None),
        ("fits", _QUOTED, 2, 2, None),
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


def _person(cv: str = FIT_CV, notes: str = "") -> svc.Person:
    from types import SimpleNamespace

    return svc.Person(
        candidate=SimpleNamespace(id=7),
        selection_index=3,
        cv_text=cv,
        notes_text=notes,
        profile="",
    )


def test_reason_without_quote_in_text_is_dropped():
    raw = json.dumps(
        {
            "verdict": "call",
            "strength": 5,
            "reasons": [
                {"text": "Zmyślony powód.", "quote": "10 lat w SAP IDM"},
                {"text": "Bez cytatu.", "quote": ""},
                {"text": "Wdrażał IdentityIQ.", "quote": "sailpoint  identityiq w banku"},
            ],
        }
    )
    out = svc.outcome_from(_person(), raw)
    assert out.verdict == "call"
    assert out.strength == 5
    assert [r["text"] for r in out.reasons] == ["Wdrażał IdentityIQ."]
    assert out.reasons[0]["source"] == "cv"
    assert out.error is None and out.model_called


def test_only_dropped_reasons_turn_call_into_maybe():
    raw = json.dumps(
        {"verdict": "call", "reasons": [{"text": "Zmyślone.", "quote": "Kubernetes"}]}
    )
    out = svc.outcome_from(_person(), raw)
    assert out.verdict == "maybe"
    assert out.reasons == []


def test_quote_from_a_note_is_marked_as_note():
    raw = json.dumps(
        {
            "verdict": "maybe",
            "reasons": [{"text": "Dostępny od grudnia.", "quote": "od grudnia"}],
        }
    )
    out = svc.outcome_from(_person(notes="Rozmowa: dostępny od grudnia."), raw)
    assert out.reasons[0]["source"] == "note"


@pytest.mark.parametrize(
    "raw", [RuntimeError("provider down"), "Nie umiem ocenić.", '{"verdict": 3}']
)
def test_model_failure_or_garbage_gives_no_verdict(raw):
    out = svc.outcome_from(_person(), raw)
    assert out.verdict is None
    assert out.error and out.model_called


def test_reasons_are_capped_at_two():
    raw = json.dumps(
        {
            "verdict": "call",
            "reasons": [
                {"text": f"Powód {i}.", "quote": "SailPoint IdentityIQ"}
                for i in range(4)
            ],
        }
    )
    assert len(svc.outcome_from(_person(), raw).reasons) == svc.REASON_LIMIT


def test_call_order_puts_call_first_and_unassessed_last():
    rows = [
        {"verdict": None, "selection_index": 0},
        {"verdict": "no_fit", "strength": 5, "selection_index": 1},
        {"verdict": "maybe", "strength": 2, "selection_index": 2},
        {"verdict": "call", "strength": 3, "selection_index": 3},
        {"verdict": "call", "strength": 5, "selection_index": 4},
        {"verdict": "call", "strength": 3, "must_found": 2, "must_total": 2, "selection_index": 5},
    ]
    ordered = [r["selection_index"] for r in sorted(rows, key=svc.call_order_key)]
    assert ordered == [4, 5, 3, 2, 1, 0]


def test_assessment_is_not_counted_as_opening_cv_files():
    from app.services import candidate_data_access_alerts as alerts

    assert svc.AUDIT_ACTION not in alerts.WATCHED_ACTIONS
    assert svc.AUDIT_ACTION not in alerts.FILE_ACTIONS


def test_prompt_forbids_personal_traits_and_requires_quotes():
    from app.services.llm_prompts import CANDIDATE_AI_ASSESSMENT

    system = CANDIDATE_AI_ASSESSMENT.system_prompt or ""
    assert "narodowości" in system and "DOSŁOWNY cytat" in system
    rendered = CANDIDATE_AI_ASSESSMENT.render(job="rola", cv="cv", notes="notatki")
    assert '"verdict": "call|maybe|no_fit"' in rendered


def test_job_block_names_critical_skills(monkeypatch):
    from types import SimpleNamespace

    import app.services.requirement_contract as contract
    from app.services import cv_quoted_evidence

    monkeypatch.setattr(contract, "requirements_for_job", lambda job: [])
    monkeypatch.setattr(contract, "requirement_labels", lambda reqs: {})
    monkeypatch.setattr(
        cv_quoted_evidence, "critical_labels", lambda job: ["SailPoint IIQ"]
    )
    job = SimpleNamespace(title="Inżynier IAM", champion_profile=None)
    assert "Krytyczne (bez tego odpada): SailPoint IIQ" in (
        cv_quoted_evidence.job_prompt_block(job, with_critical=True)
    )
    assert "Krytyczne" not in cv_quoted_evidence.job_prompt_block(job)


# ── Trasa na bazie ──────────────────────────────────────────────────────────


def _headers(uid: int, role: str = "recruiter") -> dict:
    from app.core.security import create_access_token

    return {"Authorization": f"Bearer {create_access_token(subject=uid, role=role)}"}


def _stub_model(monkeypatch, calls: list):
    """Model: CV z IdentityIQ = Dzwoń z cytatem, reszta = Nie pasuje z cytatem."""

    def call(prompt: str) -> str:
        calls.append(prompt)
        if "IdentityIQ" in prompt:
            return json.dumps(
                {
                    "verdict": "call",
                    "strength": 4,
                    "reasons": [
                        {"text": "Wdrażał IdentityIQ.", "quote": "SailPoint IdentityIQ"},
                        {"text": "Zmyślone.", "quote": "CyberArk od 2010"},
                    ],
                }
            )
        return json.dumps(
            {
                "verdict": "no_fit",
                "strength": 1,
                "reasons": [{"text": "Kadry i płace.", "quote": "kadr i płac"}],
            }
        )

    monkeypatch.setattr(svc, "_call_model", call)


async def _setup(role: str = "recruiter", member: bool = True):
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        me = await _user(db, role=role)
        job = await _job(db)
        if member:
            job.recruiter_id = me.id
        fit = await _candidate(db, raw_cv_text=FIT_CV)
        other = await _candidate(db, raw_cv_text=OTHER_CV)
        no_cv = await _candidate(db)
        await db.commit()
        return me.id, job.id, [fit.id, other.id, no_cv.id]


def _body(ids, **kw) -> dict:
    return {"batch_id": str(uuid.uuid4()), "candidate_ids": ids, **kw}


@needs_db
@pytest.mark.asyncio
async def test_assess_orders_by_verdict_and_saves_at_the_job(app_client, monkeypatch):
    from app.core.database import AsyncSessionLocal
    from app.models.activity import Activity
    from app.models.candidate_ai_assessment import CandidateAiAssessment

    uid, job_id, (fit, other, no_cv) = await _setup()
    calls: list = []
    _stub_model(monkeypatch, calls)
    body = _body([no_cv, other, fit])
    resp = await app_client.post(
        f"/api/jobs/{job_id}/ai-assessments", json=body, headers=_headers(uid)
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    rows = data["rows"]
    assert [r["candidate_id"] for r in rows] == [fit, other, no_cv]
    assert [r["verdict"] for r in rows] == ["call", "no_fit", None]
    # Powód bez cytatu w CV zniknął; cytat jest z CV.
    assert rows[0]["reasons"] == [
        {"text": "Wdrażał IdentityIQ.", "quote": "SailPoint IdentityIQ", "source": "cv"}
    ]
    assert rows[2]["error_kind"] == "no_cv"
    assert rows[0]["full_name"].startswith("Ola ")
    assert len(calls) == 2  # bez CV model nie jest wołany
    assert data["remaining_today"] == svc.DAILY_PEOPLE_LIMIT - 2

    async with AsyncSessionLocal() as db:
        saved = (
            await db.scalars(
                select(CandidateAiAssessment).where(
                    CandidateAiAssessment.batch_id == body["batch_id"]
                )
            )
        ).all()
        assert {(r.candidate_id, r.verdict, r.assessed_by) for r in saved} == {
            (fit, "call", uid),
            (other, "no_fit", uid),
            (no_cv, None, uid),
        }
        audit = (
            await db.scalars(
                select(Activity).where(
                    Activity.entity_type == "job",
                    Activity.entity_id == job_id,
                    Activity.action == svc.AUDIT_ACTION,
                )
            )
        ).all()
        assert len(audit) == 1
        assert audit[0].user_id == uid
        assert sorted(audit[0].details["candidate_ids"]) == sorted([fit, other, no_cv])
        assert "SailPoint" not in json.dumps(audit[0].details)

    latest = await app_client.get(
        f"/api/jobs/{job_id}/ai-assessments/latest", headers=_headers(uid)
    )
    assert latest.status_code == 200
    assert latest.json()["batch_id"] == body["batch_id"]
    assert [r["verdict"] for r in latest.json()["rows"]] == ["call", "no_fit", None]


@needs_db
@pytest.mark.asyncio
async def test_second_click_reuses_result_without_calling_the_model(
    app_client, monkeypatch
):
    uid, job_id, (fit, _other, _no_cv) = await _setup()
    calls: list = []
    _stub_model(monkeypatch, calls)
    url = f"/api/jobs/{job_id}/ai-assessments"
    first = await app_client.post(url, json=_body([fit]), headers=_headers(uid))
    assert first.status_code == 200
    again = await app_client.post(url, json=_body([fit]), headers=_headers(uid))
    assert again.status_code == 200
    assert again.json()["rows"][0]["verdict"] == "call"
    assert again.json()["rows"][0]["reused"] is True
    assert len(calls) == 1
    fresh = await app_client.post(
        url, json=_body([fit], refresh=True), headers=_headers(uid)
    )
    assert fresh.json()["rows"][0]["reused"] is False
    assert len(calls) == 2


@needs_db
@pytest.mark.asyncio
async def test_model_failure_leaves_people_without_verdict(app_client, monkeypatch):
    uid, job_id, (fit, other, _no_cv) = await _setup()

    def boom(prompt: str) -> str:
        raise RuntimeError("provider down")

    monkeypatch.setattr(svc, "_call_model", boom)
    resp = await app_client.post(
        f"/api/jobs/{job_id}/ai-assessments",
        json=_body([fit, other]),
        headers=_headers(uid),
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()["rows"]
    assert [r["verdict"] for r in rows] == [None, None]
    assert {r["error_kind"] for r in rows} == {"model"}
    # Kolejność zaznaczenia zostaje, gdy AI nic nie powiedziało.
    assert [r["candidate_id"] for r in rows] == [fit, other]


@needs_db
@pytest.mark.asyncio
async def test_daily_limit_refuses_before_calling_the_model(app_client, monkeypatch):
    from app.core.database import AsyncSessionLocal
    from app.models.candidate_ai_assessment import CandidateAiAssessment

    uid, job_id, (fit, other, _no_cv) = await _setup()
    calls: list = []
    _stub_model(monkeypatch, calls)
    monkeypatch.setattr(svc, "DAILY_PEOPLE_LIMIT", 1)
    body = _body([fit, other])
    resp = await app_client.post(
        f"/api/jobs/{job_id}/ai-assessments", json=body, headers=_headers(uid)
    )
    assert resp.status_code == 429
    detail = resp.json()["detail"]
    assert detail["code"] == "ai_assessment_daily_limit"
    assert detail["remaining_today"] == 1
    assert calls == []
    async with AsyncSessionLocal() as db:
        saved = await db.scalar(
            select(CandidateAiAssessment.id).where(
                CandidateAiAssessment.batch_id == body["batch_id"]
            )
        )
        assert saved is None


@needs_db
@pytest.mark.asyncio
async def test_batch_is_capped_at_thirty_people(app_client, monkeypatch):
    uid, job_id, (fit, _other, _no_cv) = await _setup()
    monkeypatch.setattr(svc, "MAX_BATCH", 1)
    calls: list = []
    _stub_model(monkeypatch, calls)
    body = _body([fit])
    url = f"/api/jobs/{job_id}/ai-assessments"
    assert (await app_client.post(url, json=body, headers=_headers(uid))).status_code == 200
    second = await app_client.post(
        url, json={**body, "candidate_ids": [_other]}, headers=_headers(uid)
    )
    assert second.status_code == 422
    assert second.json()["detail"]["code"] == "ai_assessment_batch_too_big"


@needs_db
@pytest.mark.asyncio
# Rekruter omija bramkę zespołu od 23.09.2026 (jak `proposals/bulk`), więc
# odmowa dotyczy ról bez prawa dodawania: Viewer i Praktykant.
@pytest.mark.parametrize("role", ["user", "trainee"])
async def test_refused_without_permission_to_add_to_the_job(
    app_client, monkeypatch, role
):
    uid, job_id, (fit, _other, _no_cv) = await _setup(role=role)
    calls: list = []
    _stub_model(monkeypatch, calls)
    url = f"/api/jobs/{job_id}/ai-assessments"
    resp = await app_client.post(url, json=_body([fit]), headers=_headers(uid, role))
    assert resp.status_code == 403
    latest = await app_client.get(f"{url}/latest", headers=_headers(uid, role))
    assert latest.status_code == 403
    assert calls == []
