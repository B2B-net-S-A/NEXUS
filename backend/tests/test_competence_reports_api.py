"""Kolejka rekrutera „Raporty ze strony” (N6, decyzje Artura 25.11.2026).

Bramki (rekruter tak, rola ``user`` nie, lista opiekunów tylko admin), zakres
„moje / wszystkie”, „Wstrzymaj” zatrzymujące automat, walidacja warunków,
zmiana opiekuna tylko na aktywną osobę z listy i podgląd maila bez nazwy klienta
i bez prawdziwego tokenu. Silnik raportu (``competence_report_engine``) jest
podstawiony — testy nie wysyłają maili. Dane wyłącznie syntetyczne.
"""

from __future__ import annotations

import sys
import types
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.activity import Activity
from app.models.candidate import Candidate, CandidateStatus
from app.models.client import Client
from app.models.competence_report import CompetenceReport, CompetenceReportOwner
from app.models.user import User, UserRole
from app.services.competence_report_queue import conditions_summary, hours_left
from app.services.competence_report_schema import (
    ReportConditions,
    ReportJob,
    ReportProfile,
    ReportSnapshot,
)

_URL = "/api/competence-reports"
_ENGINE = "app.services.competence_report_engine"


# ── Pomocniki ───────────────────────────────────────────────────────────────


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


@pytest.fixture
def engine(monkeypatch):
    """Podstawiony silnik: zapisuje wywołania, wysyłka tylko zmienia stan."""
    calls: dict[str, list] = {"send": [], "rebuild": []}
    fake = types.ModuleType(_ENGINE)

    async def send_report_now(db, report, user):
        calls["send"].append(report.id)
        report.status = "sent"
        report.sent_at = datetime.now(timezone.utc)
        report.sent_by_user_id = user.id

    async def rebuild_snapshot(db, report):
        calls["rebuild"].append(report.id)
        conditions = ReportConditions.model_validate(report.conditions)
        return _snapshot(conditions=conditions, role_label="Java przeliczona")

    fake.send_report_now = send_report_now
    fake.rebuild_snapshot = rebuild_snapshot
    monkeypatch.setitem(sys.modules, _ENGINE, fake)
    return calls


def _snapshot(
    *,
    conditions: ReportConditions | None = None,
    role_label: str = "Java",
    job_id: int = 1,
) -> ReportSnapshot:
    return ReportSnapshot(
        conditions=conditions or ReportConditions(rate=150, modes=("remote",)),
        profile=ReportProfile(role_label=role_label, years=6),
        jobs=(
            ReportJob(
                job_id=job_id,
                title="Platforma płatności",
                budget_max=155,
                skills=("Java 17", "Kafka"),
                place="zdalnie",
                meets=True,
            ),
        ),
    )


async def _user(role: UserRole, *, active: bool = True) -> tuple[int, str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"raport-q-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!Rq"
    async with AsyncSessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password(password),
            name=f"Osoba {role.value} {unique}",
            role=role,
            is_active=active,
        )
        db.add(user)
        await db.commit()
        return user.id, email, password


async def _login(api: AsyncClient, email: str, password: str) -> dict[str, str]:
    resp = await api.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _as(api: AsyncClient, role: UserRole) -> tuple[int, dict[str, str]]:
    user_id, email, password = await _user(role)
    return user_id, await _login(api, email, password)


async def _report(
    *,
    owner_id: int | None = None,
    status: str = "ready",
    snapshot: ReportSnapshot | None = None,
    due_in: timedelta = timedelta(hours=20),
) -> int:
    unique = uuid.uuid4().hex[:8]
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        candidate = Candidate(
            name="Osoba",
            lastname=f"Syntetyczna{unique}",
            email=f"raport-q-kand-{unique}@example.com",
            source="manual",
            status=CandidateStatus.active,
        )
        db.add(candidate)
        await db.flush()
        conditions = ReportConditions(rate=150, modes=("remote",))
        report = CompetenceReport(
            candidate_id=candidate.id,
            email=candidate.email,
            status=status,
            conditions=conditions.model_dump(mode="json"),
            snapshot=(
                (snapshot or _snapshot(conditions=conditions)).model_dump(mode="json")
                if status != "waiting_cv"
                else None
            ),
            owner_user_id=owner_id,
            created_at=now - timedelta(hours=3),
            send_due_at=now + due_in,
            token_hash=uuid.uuid4().hex * 2 if status == "sent" else None,
        )
        db.add(report)
        await db.commit()
        return report.id


async def _row(report_id: int) -> CompetenceReport:
    async with AsyncSessionLocal() as db:
        return await db.get(CompetenceReport, report_id)


async def _set_pool(*members: tuple[int, bool]) -> None:
    async with AsyncSessionLocal() as db:
        for user_id, active in members:
            db.add(CompetenceReportOwner(user_id=user_id, active=active, position=0))
        await db.commit()


@pytest_asyncio.fixture
async def clean_pool():
    """Lista opiekunów jest globalna — test ją zapisuje i sprząta po sobie."""
    async with AsyncSessionLocal() as db:
        saved = [
            (o.user_id, o.active, o.position, o.last_assigned_at)
            for o in await db.scalars(select(CompetenceReportOwner))
        ]
    yield
    async with AsyncSessionLocal() as db:
        await db.execute(delete(CompetenceReportOwner))
        for user_id, active, position, last in saved:
            db.add(
                CompetenceReportOwner(
                    user_id=user_id,
                    active=active,
                    position=position,
                    last_assigned_at=last,
                )
            )
        await db.commit()


# ── Czyste pomocniki ────────────────────────────────────────────────────────


def test_conditions_summary_reads_like_the_form() -> None:
    raw = ReportConditions(
        rate=180,
        current_rate=150,
        contract="any",
        modes=("hybrid",),
        office_days_max=2,
        office_cities=("Kraków", "Warszawa"),
        start="2-3m",
    ).model_dump(mode="json")
    assert conditions_summary(raw) == (
        "180 zł/h · teraz 150 zł/h · B2B lub UoP · hybrydowo · do 2 dni w biurze"
        " · Kraków, Warszawa · start za 2–3 miesiące"
    )
    remote = ReportConditions(rate=120, modes=("remote",), office_days_max=0)
    assert (
        conditions_summary(remote.model_dump(mode="json")) == "120 zł/h · B2B · zdalnie"
    )
    assert conditions_summary({"rate": -5}) == "—"


def test_hours_left_is_negative_after_the_deadline() -> None:
    now = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)
    assert hours_left(now + timedelta(hours=5, minutes=30), now) == 5.5
    assert hours_left(now - timedelta(minutes=90), now) == -1.5


# ── Bramki ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_recruiter_reads_the_queue_and_viewer_role_does_not(api) -> None:
    _, recruiter = await _as(api, UserRole.recruiter)
    _, viewer = await _as(api, UserRole.user)
    report_id = await _report()

    assert (await api.get(f"{_URL}?scope=all", headers=recruiter)).status_code == 200
    assert (await api.get(f"{_URL}/{report_id}", headers=recruiter)).status_code == 200
    assert (await api.get(f"{_URL}?scope=all", headers=viewer)).status_code == 403
    assert (await api.get(f"{_URL}/{report_id}", headers=viewer)).status_code == 403
    assert (
        await api.post(f"{_URL}/{report_id}/hold", headers=viewer)
    ).status_code == 403
    assert (await api.get(f"{_URL}?scope=all")).status_code == 401


@pytest.mark.asyncio
async def test_read_only_automation_role_cannot_act(api) -> None:
    _, automation = await _as(api, UserRole.automation)
    report_id = await _report()
    assert (await api.get(f"{_URL}/{report_id}", headers=automation)).status_code == 200
    assert (
        await api.post(f"{_URL}/{report_id}/hold", headers=automation)
    ).status_code == 403
    assert (await _row(report_id)).held_at is None


@pytest.mark.asyncio
async def test_owner_pool_is_admin_only(api, clean_pool) -> None:
    _, recruiter = await _as(api, UserRole.recruiter)
    _, admin = await _as(api, UserRole.admin)
    assert (await api.get(f"{_URL}/owners", headers=recruiter)).status_code == 403
    assert (
        await api.put(f"{_URL}/owners", json={"members": []}, headers=recruiter)
    ).status_code == 403
    assert (await api.get(f"{_URL}/owners", headers=admin)).status_code == 200


@pytest.mark.asyncio
async def test_admin_saves_an_ordered_pool_of_recruiters(api, clean_pool) -> None:
    _, admin = await _as(api, UserRole.admin)
    first, *_ = await _user(UserRole.recruiter)
    second, *_ = await _user(UserRole.head_of_recruitment)
    finance, *_ = await _user(UserRole.finance)
    disabled, *_ = await _user(UserRole.recruiter, active=False)

    body = {
        "members": [
            {"user_id": second, "active": True},
            {"user_id": first, "active": False},
        ]
    }
    resp = await api.put(f"{_URL}/owners", json=body, headers=admin)
    assert resp.status_code == 200, resp.text
    members = resp.json()["members"]
    assert [(m["user_id"], m["active"], m["position"]) for m in members] == [
        (second, True, 0),
        (first, False, 1),
    ]
    eligible = {p["id"] for p in resp.json()["eligible"]}
    assert {first, second} <= eligible
    assert finance not in eligible and disabled not in eligible

    for wrong in (finance, disabled):
        bad = {"members": [{"user_id": wrong, "active": True}]}
        assert (
            await api.put(f"{_URL}/owners", json=bad, headers=admin)
        ).status_code == 422
    twice = {"members": [{"user_id": first}, {"user_id": first}]}
    assert (
        await api.put(f"{_URL}/owners", json=twice, headers=admin)
    ).status_code == 422

    # Zdjęcie z listy usuwa wiersz; pozostali zachowują kolejność.
    only = {"members": [{"user_id": first, "active": True}]}
    resp = await api.put(f"{_URL}/owners", json=only, headers=admin)
    assert [m["user_id"] for m in resp.json()["members"]] == [first]


# ── Kolejka ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scope_mine_shows_only_own_reports_sorted_by_deadline(api) -> None:
    me, headers = await _as(api, UserRole.recruiter)
    other, *_ = await _user(UserRole.recruiter)
    late = await _report(owner_id=me, due_in=timedelta(hours=10))
    soon = await _report(owner_id=me, due_in=timedelta(hours=2))
    foreign = await _report(owner_id=other)
    unowned = await _report(owner_id=None)

    mine = (await api.get(f"{_URL}?scope=mine", headers=headers)).json()
    assert [r["id"] for r in mine] == [soon, late]
    assert mine[0]["owner"]["id"] == me
    assert 1.5 < mine[0]["hours_left"] <= 2
    assert mine[0]["conditions_summary"] == "150 zł/h · B2B · zdalnie"
    assert mine[0]["role_label"] == "Java"

    everything = {
        r["id"] for r in (await api.get(f"{_URL}?scope=all", headers=headers)).json()
    }
    assert {late, soon, foreign, unowned} <= everything


@pytest.mark.asyncio
async def test_status_filter_and_open_queue(api) -> None:
    me, headers = await _as(api, UserRole.recruiter)
    ready = await _report(owner_id=me)
    waiting = await _report(owner_id=me, status="waiting_cv")
    sent = await _report(owner_id=me, status="sent")

    open_ids = [
        r["id"] for r in (await api.get(f"{_URL}?status=open", headers=headers)).json()
    ]
    assert set(open_ids) == {ready, waiting}
    sent_ids = [
        r["id"] for r in (await api.get(f"{_URL}?status=sent", headers=headers)).json()
    ]
    assert sent_ids == [sent]
    assert (await api.get(f"{_URL}?status=zly", headers=headers)).status_code == 422


@pytest.mark.asyncio
async def test_preview_has_no_client_name_and_no_real_token(api) -> None:
    _, headers = await _as(api, UserRole.recruiter)
    client_name = f"Klient Tajny {uuid.uuid4().hex[:6]}"
    async with AsyncSessionLocal() as db:
        client = Client(name=client_name)
        db.add(client)
        await db.commit()
    report_id = await _report(snapshot=_snapshot(job_id=client.id + 900000))
    token_hash = uuid.uuid4().hex * 2
    async with AsyncSessionLocal() as db:
        row = await db.get(CompetenceReport, report_id)
        row.token_hash = token_hash
        await db.commit()

    detail = (await api.get(f"{_URL}/{report_id}", headers=headers)).json()
    html = detail["preview_html"]
    assert html and "Platforma płatności" in html
    assert client_name not in html
    assert token_hash not in html and "/raport/" not in html
    assert "#podglad-zmiana-warunkow" in html
    assert detail["preview_subject"].startswith("Twój raport kompetencji")

    waiting = await _report(status="waiting_cv")
    assert (await api.get(f"{_URL}/{waiting}", headers=headers)).json()[
        "preview_html"
    ] is None


# ── Akcje ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_hold_stops_auto_send_and_warns_about_the_promise(api) -> None:
    me, headers = await _as(api, UserRole.recruiter)
    report_id = await _report(owner_id=me)

    resp = await api.post(f"{_URL}/{report_id}/hold", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["held"] is True
    assert "24 godziny" in resp.json()["warning"]
    assert resp.json()["held_by"]["id"] == me
    row = await _row(report_id)
    assert row.held_at is not None and row.held_by_user_id == me

    listed = (await api.get(f"{_URL}?scope=mine", headers=headers)).json()
    assert next(r for r in listed if r["id"] == report_id)["held"] is True

    resp = await api.post(f"{_URL}/{report_id}/release", headers=headers)
    assert resp.json()["held"] is False and resp.json()["warning"] is None
    assert (await _row(report_id)).held_at is None

    async with AsyncSessionLocal() as db:
        actions = list(
            await db.scalars(
                select(Activity.action).where(
                    Activity.entity_type == "candidate",
                    Activity.entity_id == row.candidate_id,
                )
            )
        )
    assert actions.count("competence_report_held") == 1
    assert actions.count("competence_report_released") == 1


@pytest.mark.asyncio
async def test_sent_report_cannot_be_held_or_sent_again(api, engine) -> None:
    _, headers = await _as(api, UserRole.recruiter)
    report_id = await _report(status="sent")
    assert (
        await api.post(f"{_URL}/{report_id}/hold", headers=headers)
    ).status_code == 409
    assert (
        await api.post(f"{_URL}/{report_id}/send-now", headers=headers)
    ).status_code == 409
    waiting = await _report(status="waiting_cv")
    assert (
        await api.post(f"{_URL}/{waiting}/send-now", headers=headers)
    ).status_code == 409
    assert engine["send"] == []


@pytest.mark.asyncio
async def test_send_now_goes_through_the_engine_and_is_audited(api, engine) -> None:
    me, headers = await _as(api, UserRole.recruiter)
    report_id = await _report(owner_id=me)
    resp = await api.post(f"{_URL}/{report_id}/send-now", headers=headers)
    assert resp.status_code == 200, resp.text
    assert engine["send"] == [report_id]
    assert resp.json()["status"] == "sent" and resp.json()["sent_by"]["id"] == me
    async with AsyncSessionLocal() as db:
        activity = await db.scalar(
            select(Activity).where(
                Activity.action == "competence_report_sent_now",
                Activity.details["competence_report_id"].as_integer() == report_id,
            )
        )
    assert activity is not None and activity.user_id == me
    assert set(activity.details) == {"competence_report_id"}


@pytest.mark.asyncio
async def test_conditions_are_validated_saved_and_rebuilt(api, engine) -> None:
    _, headers = await _as(api, UserRole.recruiter)
    report_id = await _report()

    for bad in (
        {"rate": 150, "office_days_max": 6},
        {"rate": -1},
        {"rate": 150, "modes": ["teleport"]},
        {"rate": 150, "unknown": 1},
        {},
    ):
        resp = await api.patch(
            f"{_URL}/{report_id}/conditions", json=bad, headers=headers
        )
        assert resp.status_code == 422, bad
    assert engine["rebuild"] == []

    body = {
        "rate": 170,
        "modes": ["hybrid"],
        "office_days_max": 2,
        "office_cities": ["Gdańsk"],
    }
    resp = await api.patch(f"{_URL}/{report_id}/conditions", json=body, headers=headers)
    assert resp.status_code == 200, resp.text
    assert engine["rebuild"] == [report_id]
    assert resp.json()["conditions"]["rate"] == 170
    assert resp.json()["role_label"] == "Java przeliczona"
    row = await _row(report_id)
    assert row.snapshot["conditions"]["office_cities"] == ["Gdańsk"]

    async with AsyncSessionLocal() as db:
        activity = await db.scalar(
            select(Activity).where(
                Activity.action == "competence_report_conditions_changed",
                Activity.entity_id == row.candidate_id,
            )
        )
    # Same nazwy pól, bez wartości (stawki nie trafiają do Historii zdarzeń).
    assert activity.details["fields"] == [
        "modes",
        "office_cities",
        "office_days_max",
        "rate",
    ]
    assert "170" not in str(activity.details)


@pytest.mark.asyncio
async def test_waiting_report_saves_conditions_without_rebuild(api, engine) -> None:
    _, headers = await _as(api, UserRole.recruiter)
    report_id = await _report(status="waiting_cv")
    resp = await api.patch(
        f"{_URL}/{report_id}/conditions", json={"rate": 140}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert engine["rebuild"] == []
    assert (await _row(report_id)).conditions["rate"] == 140


@pytest.mark.asyncio
async def test_reassign_only_to_an_active_pool_member(api, clean_pool) -> None:
    me, headers = await _as(api, UserRole.recruiter)
    member, *_ = await _user(UserRole.recruiter)
    paused, *_ = await _user(UserRole.recruiter)
    outsider, *_ = await _user(UserRole.recruiter)
    await _set_pool((member, True), (paused, False))
    report_id = await _report(owner_id=me)

    choices = (await api.get(f"{_URL}/{report_id}", headers=headers)).json()[
        "owner_choices"
    ]
    assert member in {c["id"] for c in choices}
    assert not {paused, outsider} & {c["id"] for c in choices}

    for wrong in (paused, outsider, 10**9):
        resp = await api.post(
            f"{_URL}/{report_id}/owner", json={"user_id": wrong}, headers=headers
        )
        assert resp.status_code == 422, wrong
    assert (await _row(report_id)).owner_user_id == me

    resp = await api.post(
        f"{_URL}/{report_id}/owner", json={"user_id": member}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["owner"]["id"] == member
    row = await _row(report_id)
    assert row.owner_user_id == member
    # Mail podpisuje nowy opiekun.
    assert row.snapshot["owner"]["user_id"] == member

    async with AsyncSessionLocal() as db:
        activity = await db.scalar(
            select(Activity).where(
                Activity.action == "competence_report_owner_changed",
                Activity.entity_id == row.candidate_id,
            )
        )
    assert (
        activity.details["from_user_id"] == me
        and activity.details["to_user_id"] == member
    )
