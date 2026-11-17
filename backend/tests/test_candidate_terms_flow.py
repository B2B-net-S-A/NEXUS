"""Warunki od kandydata na bazie: kolejka po aplikacji, wysyłka, formularz, zapis.

Ta sama ścieżka co T2 na stagingu 17.11.2026 (Pracuj.pl bez rekrutacji, dwie
drogi tej samej aplikacji, ochrona wartości rekrutera, wypis, odmowy API).
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select, update

NOTE = "Źródło: Pracuj.pl — oferta: Junior IT Analyst – Data & Reporting (f/m/x)"


def _window_now() -> datetime:
    """Dzisiaj 10:00 w Warszawie — w oknie wysyłki niezależnie od godziny biegu CI."""
    tz = ZoneInfo("Europe/Warsaw")
    local = datetime.now(timezone.utc).astimezone(tz)
    return local.replace(hour=10, minute=0, second=0, microsecond=0).astimezone(
        timezone.utc
    )


async def _seed(**fields) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        c = Candidate(
            name="Warunki",
            lastname=f"Test-{uuid.uuid4().hex[:6]}",
            email=f"wr-{uuid.uuid4().hex[:8]}@example.com",
            **fields,
        )
        db.add(c)
        await db.commit()
        return c.id


async def _cleanup(cid: int) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.activity import Activity
    from app.models.candidate import Candidate
    from app.models.candidate_source_event import CandidateSourceEvent
    from app.models.candidate_terms_request import CandidateTermsRequest

    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(CandidateTermsRequest).where(
                CandidateTermsRequest.candidate_id == cid
            )
        )
        await db.execute(
            delete(CandidateSourceEvent).where(CandidateSourceEvent.candidate_id == cid)
        )
        await db.execute(
            delete(Activity).where(
                Activity.entity_type == "candidate", Activity.entity_id == cid
            )
        )
        await db.execute(delete(Candidate).where(Candidate.id == cid))
        await db.commit()


async def _rows(cid: int):
    from app.core.database import AsyncSessionLocal
    from app.models.candidate_terms_request import CandidateTermsRequest

    async with AsyncSessionLocal() as db:
        return (
            await db.scalars(
                select(CandidateTermsRequest)
                .where(CandidateTermsRequest.candidate_id == cid)
                .order_by(CandidateTermsRequest.id)
            )
        ).all()


@pytest.fixture
def outbox(monkeypatch, routine_notification_email_enabled):
    """Wysyłka bez sieci: kanał SMTP „gotowy”, mail ląduje na liście."""
    from app.core.config import settings
    from app.services import email

    sent: list[tuple] = []
    monkeypatch.setattr(settings, "M365_APP_MAIL_ENABLED", False)
    monkeypatch.setattr(settings, "SMTP_ENABLED", True)
    monkeypatch.setattr(settings, "SMTP_HOST", "mailpit")
    monkeypatch.setattr(email, "send_email", lambda *a, **k: sent.append(a) or True)
    return sent


async def _send_queue() -> dict:
    from app.core.database import AsyncSessionLocal
    from app.services.candidate_terms_queue import process_queue

    async with AsyncSessionLocal() as db:
        return await process_queue(db, now=_window_now())


async def _mails_for(outbox: list, cid: int) -> list[tuple]:
    """Maile tego kandydata — kolejka w pełnym biegu niesie też wiersze innych testów."""
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        email = (await db.get(Candidate, cid)).email
    return [m for m in outbox if m[0] == email]


def _token(text_body: str) -> str:
    return re.search(r"/warunki/([\w-]+)", text_body).group(1)


@pytest.mark.asyncio
async def test_pracuj_application_gets_one_mail_with_link_and_answer_reaches_profile(
    app_client: AsyncClient, app_auth_headers: dict, outbox
):
    cid = await _seed()
    try:
        for _ in range(2):  # import i trasa portalu zapisują tę samą aplikację
            r = await app_client.post(
                f"/api/candidates/{cid}/sources",
                json={"channel": "posting", "utm_source": "pracuj", "note": NOTE},
                headers=app_auth_headers,
            )
            assert r.status_code == 201, r.text
        rows = await _rows(cid)
        assert len(rows) == 1 and rows[0].ad_title.startswith("Junior IT Analyst")

        await _send_queue()
        mine = await _mails_for(outbox, cid)
        assert len(mine) == 1
        (to, subject, text_body, html_body, reply_to, _sender) = mine[0]
        assert subject.endswith("Junior IT Analyst – Data & Reporting (f/m/x)")
        assert reply_to is None and "Odpowiedz na tego maila" not in text_body
        token = _token(text_body)
        row = (await _rows(cid))[0]
        assert row.action == "link" and token not in (row.token_sha256 or "")

        view = await app_client.get(f"/api/public/candidate-terms/{token}")
        assert view.status_code == 200
        assert view.json()["job_title"].startswith("Junior IT Analyst")
        assert view.json()["answers"] is None
        assert "email" not in view.text

        saved = await app_client.post(
            f"/api/public/candidate-terms/{token}",
            json={
                "rate": {"amount": "18500", "unit": "month", "currency": "PLN"},
                "modes": ["hybrid"],
                "onsite_days": 2,
                "cities": ["Gdańsk", "gdańsk", "Gdynia"],
                "start": {"kind": "notice", "value": 1, "unit": "months"},
                "future_consent": True,
            },
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["kept"] == []

        from app.core.database import AsyncSessionLocal
        from app.models.candidate import Candidate

        async with AsyncSessionLocal() as db:
            c = await db.get(Candidate, cid)
            assert str(c.expected_rate_hourly) == "110.12"
            assert c.preferences["remote_modes"] == ["hybrid"]
            assert c.preferences["office_cities"] == ["Gdańsk", "Gdynia"]
            assert c.max_onsite_days_per_week == 2
            assert (c.notice_period, c.notice_period_unit) == (1, "months")
            assert c.availability_date is None

        again = await app_client.get(f"/api/public/candidate-terms/{token}")
        assert again.json()["answers"]["future_consent"] is True
    finally:
        await _cleanup(cid)


@pytest.mark.asyncio
async def test_recruiter_rate_from_last_14_days_is_kept(
    app_client: AsyncClient, app_auth_headers: dict, outbox
):
    from app.core.database import AsyncSessionLocal
    from app.models.activity import Activity
    from app.models.user import User

    cid = await _seed()
    try:
        await app_client.post(
            f"/api/candidates/{cid}/sources",
            json={"channel": "posting", "utm_source": "jjit"},
            headers=app_auth_headers,
        )
        await _send_queue()
        token = _token((await _mails_for(outbox, cid))[0][2])
        async with AsyncSessionLocal() as db:
            user_id = await db.scalar(select(User.id).limit(1))
            db.add(
                Activity(
                    entity_type="candidate",
                    entity_id=cid,
                    action="profile_rate_changed",
                    user_id=user_id,
                    details={"new_amount": "95"},
                    external_source="audit",
                )
            )
            await db.commit()
        r = await app_client.post(
            f"/api/public/candidate-terms/{token}",
            json={
                "rate": {"amount": "150", "unit": "hour"},
                "start": {"kind": "now"},
            },
        )
        assert r.status_code == 200, r.text
        assert r.json() == {**r.json(), "saved": ["start"], "kept": ["rate"]}
    finally:
        await _cleanup(cid)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {},
        {"rate": {"amount": "5000", "unit": "hour"}},
        {"rate": {"amount": "150", "unit": "month"}},
        {"modes": ["remote"], "onsite_days": 9},
        {"start": {"kind": "notice", "value": 9, "unit": "months"}},
        {"start": {"kind": "date"}},
        {"modes": ["hybrid"], "cities": ["X"]},
        {"modes": ["spaceship"]},
    ],
)
async def test_invalid_answers_are_refused(
    app_client: AsyncClient, app_auth_headers: dict, outbox, body
):
    cid = await _seed()
    try:
        await app_client.post(
            f"/api/candidates/{cid}/sources",
            json={"channel": "posting", "utm_source": "pracuj"},
            headers=app_auth_headers,
        )
        await _send_queue()
        token = _token((await _mails_for(outbox, cid))[0][2])
        r = await app_client.post(f"/api/public/candidate-terms/{token}", json=body)
        assert r.status_code == 422, r.text
    finally:
        await _cleanup(cid)


@pytest.mark.asyncio
async def test_bad_and_expired_tokens(
    app_client: AsyncClient, app_auth_headers: dict, outbox
):
    from app.core.database import AsyncSessionLocal
    from app.models.candidate_terms_request import CandidateTermsRequest

    assert (
        await app_client.get("/api/public/candidate-terms/" + "x" * 32)
    ).status_code == 404
    assert (
        await app_client.get("/api/public/candidate-terms/short")
    ).status_code == 404
    cid = await _seed()
    try:
        await app_client.post(
            f"/api/candidates/{cid}/sources",
            json={"channel": "posting", "utm_source": "pracuj"},
            headers=app_auth_headers,
        )
        await _send_queue()
        token = _token((await _mails_for(outbox, cid))[0][2])
        async with AsyncSessionLocal() as db:
            res = await db.execute(
                update(CandidateTermsRequest)
                .where(CandidateTermsRequest.candidate_id == cid)
                .values(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
            )
            await db.commit()
        assert res.rowcount == 1
        assert (
            await app_client.get(f"/api/public/candidate-terms/{token}")
        ).status_code == 410
        post = await app_client.post(
            f"/api/public/candidate-terms/{token}", json={"modes": ["remote"]}
        )
        assert post.status_code == 410
        # Wypis działa także po terminie linku.
        out = await app_client.post(f"/api/public/candidate-terms/{token}/opt-out")
        assert out.status_code == 200 and out.json()["opted_out"] is True
    finally:
        await _cleanup(cid)


@pytest.mark.asyncio
async def test_after_opt_out_next_application_gets_thanks_only(
    app_client: AsyncClient, app_auth_headers: dict, outbox
):
    from app.core.database import AsyncSessionLocal
    from app.models.candidate_terms_request import CandidateTermsRequest

    cid = await _seed()
    try:
        await app_client.post(
            f"/api/candidates/{cid}/sources",
            json={"channel": "posting", "utm_source": "pracuj"},
            headers=app_auth_headers,
        )
        await _send_queue()
        token = _token((await _mails_for(outbox, cid))[0][2])
        await app_client.post(f"/api/public/candidate-terms/{token}/opt-out")
        async with AsyncSessionLocal() as db:  # poprzednia aplikacja sprzed doby
            await db.execute(
                update(CandidateTermsRequest)
                .where(CandidateTermsRequest.candidate_id == cid)
                .values(queued_at=datetime.now(timezone.utc) - timedelta(days=2))
            )
            await db.commit()
        await app_client.post(
            f"/api/candidates/{cid}/sources",
            json={"channel": "posting", "utm_source": "jjit"},
            headers=app_auth_headers,
        )
        await _send_queue()
        rows = await _rows(cid)
        assert [(r.action, r.skip_reason) for r in rows][-1] == ("thanks", "opted_out")
        assert "/warunki/" not in (await _mails_for(outbox, cid))[-1][2]
    finally:
        await _cleanup(cid)


@pytest.mark.asyncio
async def test_blacklisted_and_stale_get_no_mail(
    app_client: AsyncClient, app_auth_headers: dict, outbox
):
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate, CandidateStatus
    from app.models.candidate_terms_request import CandidateTermsRequest

    banned = await _seed(status=CandidateStatus.blacklisted)
    stale = await _seed()
    try:
        for cid in (banned, stale):
            await app_client.post(
                f"/api/candidates/{cid}/sources",
                json={"channel": "posting", "utm_source": "pracuj"},
                headers=app_auth_headers,
            )
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(CandidateTermsRequest)
                .where(CandidateTermsRequest.candidate_id == stale)
                .values(applied_at=_window_now() - timedelta(days=4))
            )
            await db.commit()
            assert (
                await db.get(Candidate, banned)
            ).status == CandidateStatus.blacklisted
        await _send_queue()
        assert await _mails_for(outbox, banned) == []
        assert await _mails_for(outbox, stale) == []
        assert [r.skip_reason for r in await _rows(banned)] == ["blacklisted"]
        assert [r.skip_reason for r in await _rows(stale)] == ["stale_application"]
    finally:
        await _cleanup(banned)
        await _cleanup(stale)
