"""„Jakość podpowiedzi systemu” — liczby, propozycje i raport (23.10.2026).

Kontrakty:

- liczby liczy kod: odrzucenia per kosz i powód, „Dzwonię”, porównanie
  z osobami dodanymi przez ludzi, najsłabsze rekrutacje;
- odpowiedź modelu bez tytułu albo z nieznanym koszem odpada, a bez modelu
  raport idzie z propozycjami z reguł;
- raport robi się w pierwszym dniu roboczym tygodnia, raz na tydzień,
  z dzwonkiem do odbiorców z ustawienia;
- decyzję „Robimy / Nie” zapisuje admin albo Head of Recruitment.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

import app.models  # noqa: F401
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.autofill_feedback import AutofillFeedback
from app.models.autofill_quality_report import AutofillQualityReport
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole
from app.services import autofill_quality as quality

_WARSAW = ZoneInfo("Europe/Warsaw")


def _local(day: date, hour: int) -> datetime:
    return datetime.combine(day, time(hour), tzinfo=_WARSAW)


# ── bez bazy ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("moment", "week"),
    [
        (_local(date(2026, 10, 26), 9), date(2026, 10, 19)),  # poniedziałek 9:00
        (_local(date(2026, 10, 26), 7), None),  # przed 8:00
        (_local(date(2026, 10, 27), 9), None),  # wtorek — raport był w poniedziałek
        # Wielkanocny poniedziałek 2026 (6.04) jest wolny — raport we wtorek.
        (_local(date(2026, 4, 7), 9), date(2026, 3, 30)),
    ],
)
def test_report_runs_on_the_first_working_day_of_the_week(moment, week):
    assert quality.report_week(moment) == week


def test_model_answer_is_checked_before_it_reaches_the_report():
    raw = (
        '{"proposals": ['
        '{"title": "Za młodzi do Seniora", "kind": "search", "evidence": "40 z 90", "fix": "lata w roli"},'
        '{"title": "", "kind": "search", "evidence": "x", "fix": "y"},'
        '{"title": "Zły kosz", "kind": "client", "evidence": "x", "fix": "y"},'
        '"śmieć"]}'
    )
    assert quality.check_proposals(raw) == [
        {
            "title": "Za młodzi do Seniora",
            "kind": "search",
            "evidence": "40 z 90",
            "fix": "lata w roli",
            "decision": None,
        }
    ]
    assert quality.check_proposals("to nie JSON") == []


def test_rule_proposals_take_the_most_common_reasons():
    data = {
        "rejected": 10,
        "buckets": [
            {
                "bucket": "search",
                "reasons": [
                    {
                        "reason": "too_junior",
                        "label": "Za mało doświadczenia",
                        "count": 4,
                    },
                    {"reason": "language", "label": "Język", "count": 2},
                    {"reason": "missing_skill", "label": "Brak", "count": 1},
                ],
            },
            {
                "bucket": "data",
                "reasons": [
                    {"reason": "too_expensive", "label": "Za droga", "count": 2}
                ],
            },
            {
                "bucket": "person",
                "reasons": [{"reason": "other", "label": "Inne", "count": 1}],
            },
            {"bucket": "other", "reasons": []},
        ],
    }
    proposals = quality.rule_proposals(data)
    assert [p["title"] for p in proposals] == [
        "„Za mało doświadczenia” — 4 odrzuceń",
        "„Język” — 2 odrzuceń",
        "„Za droga” — 2 odrzuceń",
    ]
    assert proposals[0]["evidence"] == "4 z 10 odrzuceń osób od systemu (40.0%)."
    assert [p["kind"] for p in proposals] == ["search", "search", "data"]
    assert quality.rule_proposals({"rejected": 0, "buckets": []}) == []


# ── z bazą ──────────────────────────────────────────────────────────────────


async def _feedback_world(rows: list[tuple[str, str]]) -> dict:
    """Rekrutacja z wierszami ``(powód, kosz)`` odrzuceń osób od systemu."""
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"AFQ client {tag}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"AFQ job {tag}",
            client_id=client.id,
            status=JobStatus.published,
            work_state="searching",
        )
        people = [
            Candidate(name="Jakość", lastname=f"{i}-{tag}") for i in range(len(rows))
        ]
        db.add_all([job, *people])
        await db.flush()
        db.add_all(
            [
                AutofillFeedback(
                    job_id=job.id,
                    candidate_id=person.id,
                    reason=reason,
                    learned_from="call",
                    bucket=bucket,
                    note=f"opis {i}",
                    snapshot={"kind": "autofill", "score": 70},
                )
                for i, (person, (reason, bucket)) in enumerate(zip(people, rows))
            ]
        )
        await db.commit()
        return {"job_id": job.id, "title": job.title}


async def test_summary_counts_buckets_and_worst_jobs():
    world = await _feedback_world(
        [
            ("too_junior", "search"),
            ("too_junior", "search"),
            ("missing_skill", "search"),
            ("too_expensive", "data"),
        ]
    )
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        data = await quality.summary(
            db,
            since=now - timedelta(minutes=5),
            until=now + timedelta(minutes=1),
            now=now,
        )
    assert data["rejected"] >= 4
    search = next(b for b in data["buckets"] if b["bucket"] == "search")
    assert search["label"] == "Błąd wyszukiwania" and search["total"] >= 3
    [job] = [j for j in data["worst_jobs"] if j["job_id"] == world["job_id"]]
    assert (job["feedback"], job["search_errors"], job["search_pct"]) == (4, 3, 75.0)
    assert job["top_reason"] == "too_junior"
    assert job["top_reason_label"] == "Za mało doświadczenia"
    assert set(data["verified"]) == {"system", "manual"}


async def test_weekly_report_is_built_once_and_rings_the_recipients(monkeypatch):
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        recipient = User(
            email=f"afq-{tag}@example.com",
            password_hash=hash_password(f"T3st_{tag}!R"),
            name=f"AFQ {tag}",
            role=UserRole.head_of_recruitment,
            is_active=True,
        )
        db.add(recipient)
        await db.commit()
        recipient_id = recipient.id
    monkeypatch.setattr(
        settings, "AUTOFILL_REPORT_RECIPIENT_EMAILS", f"AFQ-{tag}@example.com"
    )

    async def _no_model(db, data, notes):
        return []

    monkeypatch.setattr(quality, "model_proposals", _no_model)
    # Tydzień daleko w przeszłości — własny wiersz raportu w bazie wspólnej.
    monday = date(2031, 3, 3)
    now = _local(monday, 9)
    week = quality.report_week(now)
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(AutofillQualityReport).where(
                AutofillQualityReport.week_start == week
            )
        )
        await db.commit()

    async def _summary(db, *, since, until, now):
        return {
            "since": since.isoformat(),
            "until": until.isoformat(),
            "added": 40,
            "called": 10,
            "rejected": 8,
            "search_error_pct": 50.0,
            "buckets": [
                {
                    "bucket": "search",
                    "reasons": [
                        {
                            "reason": "too_junior",
                            "label": "Za mało doświadczenia",
                            "count": 4,
                        }
                    ],
                }
            ],
        }

    monkeypatch.setattr(quality, "summary", _summary)
    async with AsyncSessionLocal() as db:
        assert await quality.send_weekly_report(db, now) == 1
        await db.commit()
        assert await quality.send_weekly_report(db, now) == 0
    async with AsyncSessionLocal() as db:
        report = await db.scalar(
            select(AutofillQualityReport).where(
                AutofillQualityReport.week_start == week
            )
        )
        [note] = (
            await db.scalars(
                select(Notification).where(Notification.user_id == recipient_id)
            )
        ).all()
    assert report.from_model is False
    assert report.proposals[0]["title"] == "„Za mało doświadczenia” — 4 odrzuceń"
    assert note.notification_type == NotificationType.autofill_quality_report
    assert note.title == "Jakość podpowiedzi systemu: raport 24.02–02.03"
    assert note.link == f"/insights/autofill?report={report.id}"


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


async def _login(client: AsyncClient, role: UserRole) -> dict[str, str]:
    tag = uuid.uuid4().hex[:8]
    password = f"T3st_{tag}!Api"
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"afq-api-{tag}@example.com",
            password_hash=hash_password(password),
            name=f"AFQ API {tag}",
            role=role,
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.commit()
    resp = await client.post(
        "/api/auth/login", json={"email": user.email, "password": password}
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def test_api_reads_numbers_and_only_leaders_decide(api_client):
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(AutofillQualityReport).where(
                AutofillQualityReport.week_start == date(2031, 6, 2)
            )
        )
        report = AutofillQualityReport(
            week_start=date(2031, 6, 2),
            summary={"added": 1},
            proposals=[
                {
                    "title": "A",
                    "kind": "search",
                    "evidence": "",
                    "fix": "",
                    "decision": None,
                }
            ],
            from_model=False,
        )
        db.add(report)
        await db.commit()
        report_id = report.id
    admin = await _login(api_client, UserRole.admin)
    recruiter = await _login(api_client, UserRole.recruiter)

    summary = await api_client.get(
        "/api/autofill-quality/summary?days=7", headers=admin
    )
    assert summary.status_code == 200, summary.text
    assert {"added", "rejected", "buckets", "worst_jobs"} <= set(summary.json())
    reports = await api_client.get("/api/autofill-quality/reports", headers=admin)
    assert report_id in [r["id"] for r in reports.json()["items"]]

    path = f"/api/autofill-quality/reports/{report_id}/proposals/0/decision"
    denied = await api_client.post(path, headers=recruiter, json={"decision": "yes"})
    assert denied.status_code == 403
    ok = await api_client.post(path, headers=admin, json={"decision": "yes"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["proposals"][0]["decision"] == "yes"
    missing = await api_client.post(
        f"/api/autofill-quality/reports/{report_id}/proposals/5/decision",
        headers=admin,
        json={"decision": "no"},
    )
    assert missing.status_code == 404
