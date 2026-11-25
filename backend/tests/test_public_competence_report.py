"""Strona tokenu raportu kompetencji: odczyt, zmiana warunków, wypis (0785).

Decyzje Artura 25.11.2026: link z maila z raportem prowadzi do ``/raport/<token>``,
gdzie kandydat zmienia warunki (zapis do profilu tymi samymi writerami co
zgłoszenie ze strony, zmiana rekrutera z 14 dni zostaje) albo wypisuje się
z raportów (także jednym kliknięciem z nagłówka maila). Dane syntetyczne.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.candidate import Candidate, CandidateStatus
from app.models.competence_report import CompetenceReport
from app.models.user import User, UserRole
from app.services.competence_report_tokens import new_token

_BASE = "/api/public/competence-report"
_CONDITIONS = {
    "rate": 180,
    "current_rate": 150,
    "contract": "b2b",
    "modes": ["hybrid"],
    "office_days_max": 2,
    "office_cities": ["Kraków"],
    "start": "1m",
}


def _body(**over) -> dict:
    return {**_CONDITIONS, **over}


async def _seed_candidate(**fields) -> int:
    async with AsyncSessionLocal() as db:
        person = Candidate(
            name="Raport",
            lastname=f"Syntetyczny-{uuid.uuid4().hex[:6]}",
            email=f"rk-{uuid.uuid4().hex[:8]}@example.com",
            source="manual",
            status=CandidateStatus.active,
            **fields,
        )
        db.add(person)
        await db.commit()
        return person.id


async def _seed_report(
    candidate_id: int,
    *,
    status: str = "sent",
    expires_in: timedelta = timedelta(days=30),
    sent: bool = True,
) -> tuple[str, int]:
    raw, hashed = new_token()
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        email = (await db.get(Candidate, candidate_id)).email
        row = CompetenceReport(
            candidate_id=candidate_id,
            email=email,
            status=status,
            conditions=dict(_CONDITIONS),
            created_at=now - timedelta(days=1),
            send_due_at=now - timedelta(hours=1),
            sent_at=now - timedelta(hours=1) if sent else None,
            token_hash=hashed,
            token_expires_at=now + expires_in,
        )
        db.add(row)
        await db.commit()
        return raw, row.id


async def _reports(candidate_id: int) -> list[CompetenceReport]:
    async with AsyncSessionLocal() as db:
        rows = await db.scalars(
            select(CompetenceReport)
            .where(CompetenceReport.candidate_id == candidate_id)
            .order_by(CompetenceReport.id)
        )
        return list(rows)


async def _activities(candidate_id: int, action: str) -> list[Activity]:
    async with AsyncSessionLocal() as db:
        rows = await db.scalars(
            select(Activity).where(
                Activity.entity_type == "candidate",
                Activity.entity_id == candidate_id,
                Activity.action == action,
            )
        )
        return list(rows)


async def _cleanup(candidate_id: int) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(CompetenceReport).where(
                CompetenceReport.candidate_id == candidate_id
            )
        )
        await db.execute(
            delete(Activity).where(
                Activity.entity_type == "candidate",
                Activity.entity_id == candidate_id,
            )
        )
        await db.execute(delete(Candidate).where(Candidate.id == candidate_id))
        await db.commit()


@pytest.fixture
async def person():
    cid = await _seed_candidate()
    yield cid
    await _cleanup(cid)


# ── Token ────────────────────────────────────────────────────────────────


async def test_unknown_short_and_expired_tokens_get_the_same_404(
    app_client: AsyncClient, person: int
):
    expired, _ = await _seed_report(person, expires_in=-timedelta(minutes=1))
    answers = [
        await app_client.get(f"{_BASE}/{'x' * 32}"),
        await app_client.get(f"{_BASE}/short"),
        await app_client.get(f"{_BASE}/{expired}"),
        await app_client.post(f"{_BASE}/{expired}/conditions", json=_body()),
        await app_client.post(f"{_BASE}/{'y' * 40}/conditions", json=_body()),
        await app_client.post(f"{_BASE}/{'z' * 40}/opt-out"),
    ]
    assert {r.status_code for r in answers} == {404}
    assert len({r.content for r in answers}) == 1


async def test_get_shows_conditions_without_profile_data(
    app_client: AsyncClient, person: int
):
    raw, _ = await _seed_report(person)
    async with AsyncSessionLocal() as db:
        candidate = await db.get(Candidate, person)
        name, lastname, email = candidate.name, candidate.lastname, candidate.email

    r = await app_client.get(f"{_BASE}/{raw}")

    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"conditions", "opted_out", "sent_at"}
    assert body["conditions"]["rate"] == 180
    assert body["conditions"]["office_cities"] == ["Kraków"]
    assert body["opted_out"] is False
    assert body["sent_at"]  # dzień wysyłki w kalendarzu firmy
    for secret in (name, lastname, email, str(person)):
        assert secret not in r.text


# ── Zmiana warunków ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "over",
    [
        {"rate": 0},
        {"rate": 2001},
        {"current_rate": 5000},
        {"contract": "dzieło"},
        {"modes": []},
        {"modes": ["kosmos"]},
        {"office_days_max": 6},
        {"office_days_max": None},
        {"office_cities": []},
        {"office_cities": [f"Miasto {i}" for i in range(11)]},
        {"office_cities": ["x" * 121]},
        {"start": "kiedyś"},
        {"start": None},
        {"email": "ktos@example.com"},  # pola spoza warunków są odrzucane
    ],
)
async def test_invalid_conditions_are_422_and_change_nothing(
    app_client: AsyncClient, person: int, over: dict
):
    raw, _ = await _seed_report(person)

    r = await app_client.post(f"{_BASE}/{raw}/conditions", json=_body(**over))

    assert r.status_code == 422, r.text
    [report] = await _reports(person)
    assert report.conditions == _CONDITIONS


async def test_remote_only_needs_no_days_or_cities_and_stores_none(
    app_client: AsyncClient, person: int
):
    raw, _ = await _seed_report(person)

    r = await app_client.post(
        f"{_BASE}/{raw}/conditions",
        json=_body(modes=["remote"], office_days_max=3, office_cities=["Gdańsk"]),
    )

    assert r.status_code == 200, r.text
    saved = r.json()["conditions"]
    assert (saved["modes"], saved["office_days_max"], saved["office_cities"]) == (
        ["remote"],
        None,
        [],
    )
    async with AsyncSessionLocal() as db:
        candidate = await db.get(Candidate, person)
    assert candidate.max_onsite_days_per_week == 0


async def test_conditions_reach_profile_and_report(
    app_client: AsyncClient, person: int
):
    raw, report_id = await _seed_report(person)

    r = await app_client.post(
        f"{_BASE}/{raw}/conditions",
        json=_body(
            rate=210,
            contract="uop",
            modes=["onsite", "hybrid", "hybrid"],
            office_days_max=3,
            office_cities=[" Wrocław ", "wrocław", "Poznań"],
            start="2-3m",
        ),
    )

    assert r.status_code == 200, r.text
    saved = r.json()["conditions"]
    assert saved["modes"] == ["hybrid", "onsite"]
    assert saved["office_cities"] == ["Wrocław", "Poznań"]
    [report] = await _reports(person)
    assert report.conditions["rate"] == 210
    assert report.conditions["contract"] == "uop"
    async with AsyncSessionLocal() as db:
        candidate = await db.get(Candidate, person)
    assert candidate.expected_rate_hourly == Decimal("210.00")
    assert candidate.b2b_willingness == "employment_only"
    assert candidate.preferences["office_cities"] == ["Wrocław", "Poznań"]
    assert candidate.preferences["contract_types"] == ["uop"]
    assert candidate.max_onsite_days_per_week == 3
    assert (candidate.notice_period, candidate.notice_period_unit) == (2, "months")
    [entry] = await _activities(person, "candidate_terms_answered")
    assert entry.user_id is None
    assert entry.details["via"] == "competence_report"
    assert entry.details["report_id"] == report_id
    assert entry.details["kept"] == []


async def test_recent_recruiter_edit_is_kept(app_client: AsyncClient):
    cid = await _seed_candidate(
        expected_rate_hourly=Decimal("100.00"),
        expected_rate_currency="PLN",
        preferences={"office_cities": ["Łódź"]},
    )
    now = datetime.now(timezone.utc)
    try:
        async with AsyncSessionLocal() as db:
            recruiter = User(
                email=f"rk-rekruter-{uuid.uuid4().hex[:8]}@example.com",
                password_hash="not-a-real-hash",
                name="Rekruter Syntetyczny",
                role=UserRole.recruiter,
            )
            db.add(recruiter)
            await db.flush()
            db.add_all(
                [
                    # Stawka z rozmowy 3 dni temu — zostaje.
                    Activity(
                        entity_type="candidate",
                        entity_id=cid,
                        action="profile_rate_changed",
                        user_id=recruiter.id,
                        details={"new_amount": "100.00"},
                        external_source="audit",
                        created_at=now - timedelta(days=3),
                    ),
                    # Miasta zmienione w profilu 20 dni temu — poza oknem.
                    Activity(
                        entity_type="candidate",
                        entity_id=cid,
                        action="updated",
                        user_id=recruiter.id,
                        details={"preferences": {"office_cities": ["Łódź"]}},
                        created_at=now - timedelta(days=20),
                    ),
                ]
            )
            await db.commit()
        raw, _ = await _seed_report(cid)

        r = await app_client.post(f"{_BASE}/{raw}/conditions", json=_body(rate=250))

        assert r.status_code == 200, r.text
        async with AsyncSessionLocal() as db:
            candidate = await db.get(Candidate, cid)
        assert candidate.expected_rate_hourly == Decimal("100.00")
        assert candidate.preferences["office_cities"] == ["Kraków"]
        [report] = await _reports(cid)
        assert report.conditions["rate"] == 250, "wartość kandydata leży w raporcie"
        [entry] = await _activities(cid, "candidate_terms_answered")
        assert entry.details["kept"] == ["rate"]
        assert "cities" in entry.details["saved"]
    finally:
        await _cleanup(cid)
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(User).where(User.email.like("rk-rekruter-%@example.com"))
            )
            await db.commit()


# ── Wypis ────────────────────────────────────────────────────────────────


async def test_opt_out_marks_every_report_and_stops_unsent(
    app_client: AsyncClient, person: int
):
    raw, _ = await _seed_report(person)
    await _seed_report(person, status="waiting_cv", sent=False)
    await _seed_report(person, status="ready", sent=False)
    url = f"{_BASE}/{raw}/opt-out"
    # Podgląd linku w poczcie nie wypisuje.
    assert (await app_client.get(url)).status_code == 405
    assert all(r.opted_out_at is None for r in await _reports(person))

    first = await app_client.post(url)

    assert first.status_code == 200 and first.json() == {"opted_out": True}
    rows = await _reports(person)
    assert [r.status for r in rows] == ["sent", "opted_out", "opted_out"]
    stamps = {r.opted_out_at for r in rows}
    assert len(stamps) == 1 and None not in stamps

    again = await app_client.post(url)

    assert again.status_code == 200 and again.json() == {"opted_out": True}
    rows = await _reports(person)
    assert len(rows) == 3, "wypis niczego nie usuwa"
    assert {r.opted_out_at for r in rows} == stamps
    assert len(await _activities(person, "competence_report_opted_out")) == 1
    view = await app_client.get(f"{_BASE}/{raw}")
    assert view.json()["opted_out"] is True


async def test_one_click_post_from_mail_client_works(
    app_client: AsyncClient, person: int
):
    raw, _ = await _seed_report(person)
    url = f"{_BASE}/{raw}/opt-out"

    form = await app_client.post(url, data={"List-Unsubscribe": "One-Click"})
    multipart = await app_client.post(
        url, files={"List-Unsubscribe": (None, "One-Click")}
    )

    assert (form.status_code, multipart.status_code) == (200, 200)
    [report] = await _reports(person)
    assert report.opted_out_at is not None


async def test_opt_out_works_after_link_expiry(app_client: AsyncClient, person: int):
    raw, _ = await _seed_report(
        person, status="waiting_cv", sent=False, expires_in=-timedelta(days=1)
    )

    r = await app_client.post(f"{_BASE}/{raw}/opt-out")

    assert r.status_code == 200, r.text
    [report] = await _reports(person)
    assert (report.status, report.opted_out_at is not None) == ("opted_out", True)
