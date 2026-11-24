"""Aplikacje ze strony B2B Network: ``POST /api/public/website-applications``.

Kontrakt strony (``src/lib/forms/delivery.ts`` w repo strony): multipart,
``Authorization: Bearer``, 2xx = przyjęte. Pokrywa: sukces (oferta), duplikat
po e-mailu (kandydat bez zmian, wpis ``pending_review``), sam LinkedIn bez CV,
zły i brakujący token, za duży plik, zły typ, zgody z treścią i datą oraz
lustro kolumny ``consent_text`` w ``entrypoint.sh``.
"""

from __future__ import annotations

import io
import re
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.application_submission import ApplicationSubmission
from app.models.candidate import Candidate, CandidateStatus
from app.models.candidate_consent import CandidateConsent
from app.models.candidate_document import CandidateDocument


_URL = "/api/public/website-applications"
_TOKEN = "test-website-applications-token-not-a-secret"
_CONSENT = (
    "Wyrażam zgodę na przetwarzanie moich danych osobowych przez B2B.NET S.A. "
    "w celu przeprowadzenia rekrutacji, na którą przesyłam zgłoszenie."
)
_FUTURE = (
    "Wyrażam zgodę na przetwarzanie moich danych osobowych przez B2B.NET S.A. "
    "w celu prowadzenia przyszłych procesów rekrutacyjnych."
)
_BACKEND = Path(__file__).resolve().parents[1]


@pytest_asyncio.fixture
async def api(monkeypatch) -> AsyncClient:
    from app.core.rate_limit import limiter
    from app.main import app

    async def _noop_embed(candidate_id, db):
        return True

    async def _noop_task(*args, **kwargs):
        return None

    monkeypatch.setattr("app.services.embedding_service.embed_candidate", _noop_embed)
    monkeypatch.setattr("app.api.public_share._invite_post_apply_task", _noop_task)
    monkeypatch.setattr(settings, "WEBSITE_APPLICATIONS_TOKEN", _TOKEN)
    limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as client:
        yield client


def _auth(token: str = _TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _email(label: str) -> str:
    return f"www-{label}-{uuid.uuid4().hex[:8]}@example.com"


def _offer_form(email: str, **extra) -> dict:
    fields = {
        "source": "oferta",
        "offer_slug": "programista-python",
        "offer_title": "Programista Python",
        "first_name": "Jan",
        "last_name": "Stronowy",
        "email": email,
        "rate": "150",
        "available_from": "1 grudnia",
        "city": "Warszawa",
        "work_mode": "Zdalnie",
        **extra,
    }
    return {**fields, "consent": [_CONSENT, _FUTURE]}


def _cv(name: str = "cv.pdf", body: bytes = b"%PDF-1.4 www", mime="application/pdf"):
    return {"cv": (name, io.BytesIO(body), mime)}


async def _post(api: AsyncClient, data, files=None, headers=None):
    return await api.post(
        _URL, data=data, files=files, headers=_auth() if headers is None else headers
    )


async def _candidate(email: str) -> Candidate | None:
    async with AsyncSessionLocal() as db:
        return await db.scalar(select(Candidate).where(Candidate.email == email))


async def _submissions(email: str) -> list[ApplicationSubmission]:
    async with AsyncSessionLocal() as db:
        rows = await db.scalars(
            select(ApplicationSubmission).where(
                func.lower(ApplicationSubmission.submitted_email) == email.lower()
            )
        )
        return list(rows)


async def test_offer_application_creates_candidate_consents_and_queue_entry(api):
    email = _email("oferta")

    resp = await _post(api, _offer_form(email), files=_cv())

    assert resp.status_code == 201, resp.text
    assert resp.json() == {"ok": True, "status": "received"}
    person = await _candidate(email)
    assert person is not None
    assert (person.name, person.lastname, person.source) == (
        "Jan",
        "Stronowy",
        "strona WWW",
    )
    assert person.created_by is None
    assert str(person.expected_rate_hourly) == "150.00"
    assert person.city == "Warszawa"
    # „1 grudnia” to nie data — zostaje surowy tekst w zgłoszeniu.
    assert person.availability_date is None
    assert person.preferences == {"remote_modes": ["remote"]}
    async with AsyncSessionLocal() as db:
        consents = list(
            await db.scalars(
                select(CandidateConsent)
                .where(CandidateConsent.candidate_id == person.id)
                .order_by(CandidateConsent.id)
            )
        )
        docs = list(
            await db.scalars(
                select(CandidateDocument).where(
                    CandidateDocument.candidate_id == person.id
                )
            )
        )
    assert [(c.kind, c.consent_text) for c in consents] == [
        ("recruitment_current", _CONSENT),
        ("recruitment_future", _FUTURE),
    ]
    assert all(c.given_at is not None and len(c.text_sha256) == 64 for c in consents)
    assert (
        len(docs) == 1 and docs[0].is_primary and docs[0].external_source == "website"
    )
    [entry] = await _submissions(email)
    assert entry.status == "pending_review"
    assert entry.matched_candidate_id == person.id
    assert entry.job_id is None
    assert "oferta „Programista Python”" in entry.submitted_message
    assert "dostępny od: 1 grudnia" in entry.submitted_message
    assert entry.raw_payload["offer"] == {
        "slug": "programista-python",
        "title": "Programista Python",
    }


async def test_duplicate_email_never_touches_candidate(api):
    email = _email("dup")
    async with AsyncSessionLocal() as db:
        existing = Candidate(
            name="Anna",
            lastname="Istniejąca",
            email=email,
            linkedin="https://www.linkedin.com/in/anna-istniejaca",
            source="manual",
            status=CandidateStatus.active,
        )
        db.add(existing)
        await db.commit()
        existing_id = existing.id

    resp = await _post(
        api,
        _offer_form(email.upper(), first_name="Obca", last_name="Osoba"),
        files=_cv(),
    )

    assert resp.status_code == 201, resp.text
    assert resp.json() == {"ok": True, "status": "received"}
    person = await _candidate(email)
    assert (person.id, person.name, person.lastname, person.source) == (
        existing_id,
        "Anna",
        "Istniejąca",
        "manual",
    )
    assert person.linkedin == "https://www.linkedin.com/in/anna-istniejaca"
    async with AsyncSessionLocal() as db:
        docs = list(
            await db.scalars(
                select(CandidateDocument).where(
                    CandidateDocument.candidate_id == existing_id
                )
            )
        )
        own_consents = list(
            await db.scalars(
                select(CandidateConsent).where(
                    CandidateConsent.candidate_id == existing_id
                )
            )
        )
    assert docs == [] and own_consents == []
    [entry] = await _submissions(email.upper())
    assert entry.status == "pending_review"
    assert entry.matched_candidate_id == existing_id
    assert (entry.submitted_first_name, entry.submitted_last_name) == ("Obca", "Osoba")
    assert entry.cv_filename == "cv.pdf" and entry.cv_size_bytes == len(b"%PDF-1.4 www")
    async with AsyncSessionLocal() as db:
        consents = list(
            await db.scalars(
                select(CandidateConsent).where(
                    CandidateConsent.application_submission_id == entry.id
                )
            )
        )
    assert {c.consent_text for c in consents} == {_CONSENT, _FUTURE}


async def test_talent_pool_with_linkedin_only_and_no_cv(api):
    email = _email("baza")
    linkedin = "https://www.linkedin.com/in/kandydat-www"
    talent_consent = (
        "Wyrażam zgodę na przetwarzanie moich danych w celu prowadzenia "
        "obecnych i przyszłych procesów rekrutacyjnych."
    )

    resp = await _post(
        api,
        {
            "source": "baza",
            "email": email,
            "linkedin": linkedin,
            "rate": "180,5",
            "consent": talent_consent,
        },
    )

    assert resp.status_code == 201, resp.text
    person = await _candidate(email)
    assert person is not None
    assert person.linkedin == linkedin
    assert person.source == "strona WWW"
    assert str(person.expected_rate_hourly) == "180.50"
    async with AsyncSessionLocal() as db:
        [consent] = list(
            await db.scalars(
                select(CandidateConsent).where(
                    CandidateConsent.candidate_id == person.id
                )
            )
        )
        docs = list(
            await db.scalars(
                select(CandidateDocument).where(
                    CandidateDocument.candidate_id == person.id
                )
            )
        )
    assert (consent.kind, consent.consent_text) == (
        "recruitment_current_future",
        talent_consent,
    )
    assert docs == []
    [entry] = await _submissions(email)
    assert "bez CV (podany LinkedIn)" in entry.submitted_message


async def test_talent_pool_without_cv_and_linkedin_is_refused(api):
    email = _email("pusty")

    resp = await _post(api, {"source": "baza", "email": email, "consent": _CONSENT})

    assert resp.status_code == 422
    assert resp.json()["detail"][0]["loc"] == ["body", "cv"]
    assert await _candidate(email) is None


async def test_offer_without_cv_is_refused(api):
    email = _email("bezcv")

    resp = await _post(api, _offer_form(email))

    assert resp.status_code == 422
    assert resp.json()["detail"][0]["loc"] == ["body", "cv"]


async def test_missing_consent_is_refused(api):
    email = _email("bezzgody")
    form = {k: v for k, v in _offer_form(email).items() if k != "consent"}

    resp = await _post(api, form, files=_cv())

    assert resp.status_code == 422
    assert resp.json()["detail"][0]["loc"] == ["body", "consent"]
    assert await _candidate(email) is None


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer zly-token"},
        {"Authorization": f"Basic {_TOKEN}"},
        {"Authorization": "Bearer łódź".encode()},
    ],
    ids=["brak", "zly", "inny-schemat", "spoza-ascii"],
)
async def test_bad_or_missing_token_is_401(api, headers):
    email = _email("token")

    resp = await _post(api, _offer_form(email), files=_cv(), headers=headers)

    assert resp.status_code == 401
    assert resp.headers.get("www-authenticate") == "Bearer"
    assert await _candidate(email) is None


async def test_unconfigured_token_refuses_everything(api, monkeypatch):
    monkeypatch.setattr(settings, "WEBSITE_APPLICATIONS_TOKEN", "")
    email = _email("bezkonfig")

    resp = await _post(api, _offer_form(email), files=_cv(), headers=_auth(""))

    assert resp.status_code == 401
    assert await _candidate(email) is None


async def test_too_large_cv_is_413(api, monkeypatch):
    from app.api import public_share

    monkeypatch.setattr(public_share, "_MAX_CV_BYTES", 16)
    email = _email("duzy")

    resp = await _post(
        api, _offer_form(email), files=_cv(body=b"%PDF-1.4 " + b"x" * 64)
    )

    assert resp.status_code == 413
    assert await _candidate(email) is None


async def test_wrong_cv_type_is_415(api):
    email = _email("typ")

    resp = await _post(
        api,
        _offer_form(email),
        files=_cv(
            name="cv.exe", body=b"MZ\x90\x00binary", mime="application/x-msdownload"
        ),
    )

    assert resp.status_code == 415
    assert await _candidate(email) is None


async def test_pdf_name_with_foreign_content_is_415(api):
    email = _email("podszyty")

    resp = await _post(api, _offer_form(email), files=_cv(body=b"<html>nie pdf</html>"))

    assert resp.status_code == 415
    assert await _candidate(email) is None


def test_consent_text_column_is_mirrored_in_entrypoint():
    entrypoint = re.sub(r"\s+", " ", (_BACKEND / "entrypoint.sh").read_text())
    migration = (
        _BACKEND / "alembic" / "versions" / "0773_candidate_consent_text.py"
    ).read_text()
    ddl = (
        "ALTER TABLE candidate_consents ADD COLUMN IF NOT EXISTS consent_text TEXT NULL"
    )
    assert ddl in migration
    assert ddl in entrypoint


async def test_link_closes_new_person_entry_without_duplicating_cv(api):
    from app.api.application_submissions import resolve_application_submission
    from app.services.write_author import WriteAuthor

    email = _email("polacz")
    resp = await _post(api, _offer_form(email), files=_cv())
    assert resp.status_code == 201, resp.text
    person = await _candidate(email)
    [entry] = await _submissions(email)

    async def _allow(submission):
        return None

    async with AsyncSessionLocal() as db:
        result = await resolve_application_submission(
            db, entry.id, "link", author=WriteAuthor(), authorize=_allow
        )
        await db.commit()
        docs = list(
            await db.scalars(
                select(CandidateDocument).where(
                    CandidateDocument.candidate_id == person.id
                )
            )
        )

    assert result.candidate_id == person.id
    assert result.submission.status == "linked"
    assert len(docs) == 1
