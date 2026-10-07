"""Kontekst przeglądu Delivery Leada (D9, 08.10.2026).

DL do 07.10 wpisywał stawkę do klienta od zera, bez budżetu i marży, a
wymagania klienta porównywał z CV sam. `GET /api/dl-review/context` składa
wymagania z dowodem i źródłem, ryzyka, podpowiedź stawki do klienta i
agregaty konsultantów u klienta — kwoty tylko przy dostępie do finansów
klienta, stawki do klienta tylko przy ich podglądzie.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.job import Job, JobStatus, RemotePolicy
from app.models.recruitment_pipeline import CandidateStage
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User, UserRole
from app.services import client_consultant_rates as rates
from app.services import dl_review as svc
from tests._permission_grants import grant_permissions
from tests.test_board_tasks import _cleanup, _login, _move, _seed_user, _seed_world

# ── Jednostkowe ──────────────────────────────────────────────────────────────


def _candidate(**over) -> SimpleNamespace:
    base = dict(
        id=1,
        skills=[{"name": "Java"}],
        verified_tech=None,
        tags=None,
        experience=None,
        cv_extracted_data={},
        raw_cv_text="Pracowałem z Kafką w banku przez 5 lat.",
        current_position=None,
        headline=None,
        title=None,
    )
    base.update(over)
    return SimpleNamespace(**base)


def test_requirements_carry_the_evidence_source() -> None:
    items = [
        svc.RequirementInput("must:0", "Java", "critical"),
        svc.RequirementInput("must:1", "Kafka", "must"),
        svc.RequirementInput("must:2", "Kubernetes", "must"),
        svc.RequirementInput("must:3", "Docker", "must"),
        svc.RequirementInput("must:4", "Terraform", "must"),
        svc.RequirementInput("nice:0", "komunikatywność w zespole", "nice"),
    ]
    rows = svc.evaluate_requirements(
        _candidate(),
        items,
        note_texts=["Rozmowa: zna Dockera dobrze"],
        conversation_texts=["Kubernetes — 3 lata produkcyjnie"],
    )
    by_label = {r["label"]: r for r in rows}
    assert by_label["Java"]["sources"] == ["profil"]
    assert by_label["Kafka"]["sources"] == ["CV"]
    assert "Kafką" in (by_label["Kafka"]["candidate_value"] or "")
    assert by_label["Kubernetes"]["sources"] == ["rozmowa"]
    assert by_label["Docker"]["sources"] == ["notatka"]
    assert by_label["Terraform"]["status"] == "missing"
    # Zdanie bez technologii ocenia DL — nigdy „brak”.
    assert by_label["komunikatywność w zespole"]["status"] == "unknown"
    assert svc.requirements_score(rows) == (4, 5)


def test_client_rate_hint_prefers_this_pair_then_same_client() -> None:
    older = {"amount": 170.0, "at": "2026-05-01T10:00:00+00:00", "job_id": 1}
    newer = {"amount": 185.0, "at": "2026-09-01T10:00:00+00:00", "job_id": 2}
    pair = {"amount": 190.0, "at": "2026-10-01T10:00:00+00:00", "job_id": 3}
    assert (
        svc.pick_client_rate_hint(this_pair=pair, same_client=[older, newer])["source"]
        == "this_pair"
    )
    hint = svc.pick_client_rate_hint(this_pair=None, same_client=[older, newer])
    assert hint["source"] == "same_client" and hint["amount"] == 185.0
    assert svc.pick_client_rate_hint(this_pair=None, same_client=[]) is None


def test_hourly_uses_168_hours_and_refuses_other_currencies() -> None:
    assert svc.hourly_pln(1200, "daily", "PLN") == Decimal("150.00")
    assert svc.hourly_pln(25200, "monthly", "PLN") == Decimal("150.00")
    assert svc.hourly_pln(150, "hourly", "EUR") is None
    assert svc.hourly_pln(None, "hourly", "PLN") is None


def test_risks_name_what_dl_must_weigh() -> None:
    risks = svc.risks_for(
        eligibility_reason="Hiring manager odrzucił tę osobę",
        eligibility_code="manager_rejected",
        employed_elsewhere=["Bank X"],
        worked_at_client="tak, 2023",
        deal_breaker_hits=1,
        over_budget_by=12.0,
        sent_to_client_before=[
            {
                "job_title": "Java Dev",
                "sent_at": "2026-03-02T10:00:00",
                "outcome": "Odrzucony",
            }
        ],
        red_flags="długi okres wypowiedzenia",
        qc_status="failed",
    )
    codes = [r["code"] for r in risks]
    assert codes[:3] == ["manager_rejected", "deal_breaker", "qc_failed"]
    assert "over_budget" in codes and "employed_elsewhere" in codes
    assert any("Już u tego klienta" in r["label"] for r in risks)
    assert (
        svc.risks_for(
            eligibility_reason=None,
            eligibility_code="eligible",
            employed_elsewhere=[],
            worked_at_client=None,
            deal_breaker_hits=0,
            over_budget_by=-5.0,
            sent_to_client_before=[],
            red_flags=None,
            qc_status="passed",
        )
        == []
    )


def test_over_budget_label_keeps_grosze() -> None:
    # Zaokrąglenie do pełnych złotych dawało „ponad budżet o 0 zł/h”.
    def label(over: float) -> str:
        (risk,) = svc.risks_for(
            eligibility_reason=None,
            eligibility_code="eligible",
            employed_elsewhere=[],
            worked_at_client=None,
            deal_breaker_hits=0,
            over_budget_by=over,
            sent_to_client_before=[],
            red_flags=None,
            qc_status=None,
        )
        return risk["label"]

    assert label(0.4) == "Stawka ponad budżet o 0,40 zł/h"
    assert label(12.0) == "Stawka ponad budżet o 12 zł/h"
    assert label(7.5) == "Stawka ponad budżet o 7,50 zł/h"


def test_consultant_summary_medians_without_names() -> None:
    people = [
        rates.ConsultantRates(1, 5, Decimal("120"), Decimal("160")),
        rates.ConsultantRates(2, 5, Decimal("140"), Decimal("170")),
        rates.ConsultantRates(3, 9, Decimal("100"), Decimal("200")),
        rates.ConsultantRates(4, 5, None, Decimal("150")),
    ]
    out = rates.summarize(people, 5)
    assert out.consultants == 4
    assert out.client_margin_median_hourly == Decimal("40.00")
    assert out.category_count == 3
    assert (out.category_cost_min, out.category_cost_max) == (
        Decimal("120"),
        Decimal("140"),
    )
    assert out.category_margin_median_hourly == Decimal("35.00")
    assert rates.summarize([], 5).client_margin_median_hourly is None


# ── Integracyjne: macierz redakcji ───────────────────────────────────────────


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


async def _multi_role_user(*roles: UserRole) -> tuple[int, dict[str, str]]:
    unique = uuid.uuid4().hex[:8]
    email = f"dlr-{unique}@example.com"
    password = f"T3st_{unique}!Dl"
    async with AsyncSessionLocal() as db:
        u = User(
            email=email,
            password_hash=hash_password(password),
            name=f"DLR {unique}",
            role=roles[0],
            roles=[r.value for r in roles],
            is_active=True,
            profile_completed=True,
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u.id, {"email": email, "password": password}


@pytest.mark.asyncio
async def test_context_redaction_matrix_and_prefill(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await _seed_world()
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "")
    cid, jid, defs = world["candidate_id"], world["job_id"], world["defs"]
    rec_id, rec_creds = await _seed_user(UserRole.recruiter)
    rm_id, rm_creds = await _seed_user(UserRole.recruiter)
    admin_id, admin_creds = await _seed_user(UserRole.admin)
    dl_in_id, dl_in_creds = await _seed_user(UserRole.delivery_lead)
    dl_out_id, dl_out_creds = await _seed_user(UserRole.delivery_lead)
    hor_dl_id, hor_dl_creds = await _multi_role_user(
        UserRole.head_of_recruitment, UserRole.delivery_lead
    )
    await grant_permissions(rm_id, "recruitment_manage")
    unique = uuid.uuid4().hex[:6]
    other_job_id = None
    try:
        async with AsyncSessionLocal() as db:
            job = await db.get(Job, jid)
            job.delivery_lead_id = dl_in_id
            job.rate_budget_hourly = Decimal("160")
            job.rate_budget_hourly_min = Decimal("120")
            job.must_skills = ["Java", "Kafka"]
            db.add(
                DeliveryLeadClientAssignment(
                    delivery_lead_user_id=dl_in_id, client_id=world["client_id"]
                )
            )
            other = Job(
                title=f"DLR inna {unique}",
                location="Warszawa",
                status=JobStatus.closed,
                remote_policy=RemotePolicy.hybrid,
                client_id=world["client_id"],
                pipeline_template_id=world["template_id"],
            )
            db.add(other)
            await db.flush()
            other_job_id = other.id
            candidate = await db.get(Candidate, cid)
            candidate.raw_cv_text = "Java 11, Kafka w bankowości, 6 lat."
            # Ta osoba poszła już do tego klienta w innej rekrutacji za 185 zł/h.
            db.add(
                CandidateStage(
                    candidate_id=cid,
                    job_id=other.id,
                    stage="cv_sent",
                    stage_def_id=defs["cv_sent"],
                    moved_at=datetime.now(timezone.utc) - timedelta(days=60),
                    client_rate_value=Decimal("185"),
                    client_rate_unit="hourly",
                    client_rate_currency="PLN",
                )
            )
            db.add(
                CandidateStage(
                    candidate_id=cid,
                    job_id=jid,
                    stage="screening",
                    stage_def_id=defs["screening"],
                    moved_by=rec_id,
                    screening_answers={
                        "answers": [{"question_id": "q1", "response": "Kafka 3 lata"}],
                        "overall_fit": "fit",
                    },
                    moved_at=datetime.now(timezone.utc) - timedelta(hours=2),
                )
            )
            await db.commit()
        rec = await _login(api_client, rec_creds)
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
        url = f"/api/dl-review/context?candidate_id={cid}&job_id={jid}"

        assert (await api_client.get(url, headers=rec)).status_code == 403

        expected = {
            # (konto, kwoty klienta, stawki do klienta)
            "admin": (admin_creds, True, True),
            "dl_portfolio": (dl_in_creds, True, True),
            "dl_outside": (dl_out_creds, False, True),
            "hor_dl_outside": (hor_dl_creds, False, True),
            "recruiter_rm": (rm_creds, False, True),
        }
        for name, (creds, amounts, client_rates) in expected.items():
            headers = await _login(api_client, creds)
            resp = await api_client.get(url, headers=headers)
            assert resp.status_code == 200, (name, resp.text)
            body = resp.json()
            assert body["can_see_amounts"] is amounts, name
            assert body["can_see_client_rates"] is client_rates, name
            assert (body["client_rates"] is not None) is amounts, name
            hint = body["client_rate_hint"]
            assert hint is not None and hint["source"] == "same_client", name
            assert hint["amount"] == 185.0
            assert body["candidate_rate"]["hourly_pln"] == 140.0
            assert body["budget"] == {"min_hourly": 120.0, "max_hourly": 160.0}
            labels = {r["label"]: r for r in body["requirements"]}
            assert labels["Kafka"]["status"] == "met"
            assert "CV" in labels["Kafka"]["sources"]
            assert any(r["code"] == "sent_to_client_before" for r in body["risks"])
            assert body["previous_sends"][0]["client_rate"]["amount"] == 185.0
            assert any(o["key"] == "cv" for o in body["fix_options"])
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(DeliveryLeadClientAssignment).where(
                    DeliveryLeadClientAssignment.client_id == world["client_id"]
                )
            )
            if other_job_id is not None:
                await db.execute(
                    delete(CandidateStage).where(CandidateStage.job_id == other_job_id)
                )
                await db.execute(delete(Job).where(Job.id == other_job_id))
            await db.commit()
        await _cleanup(world, [rec_id, rm_id, admin_id, dl_in_id, dl_out_id, hor_dl_id])
