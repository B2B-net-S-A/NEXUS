"""„Poleć inżyniera” ze strony B2B Network (0806). Dane fikcyjne — repo jest publiczne.

Kontrakt strony: ``POST /api/public/website-referrals``, multipart,
``Authorization: Bearer`` (ten sam token co aplikacje), 2xx = przyjęte.
Pokrywa: nowego kandydata ze źródłem „polecenie” i zdarzeniem źródła,
polecenie przez sam LinkedIn, osobę już w bazie (profil bez zmian), adres
usunięty wcześniej na prośbę osoby, drugie wysłanie tego samego polecenia,
odmowy pól i tokenu, polecającego konsultanta (premia do faktury), brak
jakiegokolwiek maila i wyjścia na zewnątrz oraz listę z kwotą premii 1–5 tys. zł
i „Wypłacona” tylko dla Finansów.
"""

from __future__ import annotations

import smtplib
import uuid

import httpx
import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.application_submission import ApplicationSubmission
from app.models.candidate import Candidate, CandidateSource, CandidateStatus
from app.models.candidate_consent import CandidateConsent
from app.models.candidate_source_event import CandidateSourceEvent, SourceChannel
from app.models.user import UserRole
from app.models.website_intake import CandidateReferral
from tests.care_announcements_seed import headers, make_user
from tests.consultant_portal_seed import make_person

URL = "/api/public/website-referrals"
STAFF = "/api/candidate-referrals"
TOKEN = "test-website-applications-token-not-a-secret"
KNOWS = "Ta osoba wie, że ją polecam, i zgadza się na kontakt od B2B Network."
CONSENT = (
    "Wyrażam zgodę na przetwarzanie moich danych osobowych przez B2B.NET S.A. "
    "w celu obsługi polecenia i wypłaty premii."
)


@pytest.fixture
def outbound(monkeypatch) -> list[str]:
    """Każda próba wyjścia na zewnątrz (HTTP, SMTP, maile NEXUSA) trafia na listę."""
    calls: list[str] = []

    def _blocked(label: str):
        def _call(*args, **kwargs):
            calls.append(label)
            raise RuntimeError(f"wyjście na zewnątrz w teście: {label}")

        return _call

    async def _async_blocked(*args, **kwargs):
        calls.append("httpx.async")
        raise RuntimeError("wyjście HTTP w teście")

    monkeypatch.setattr(settings, "WEBSITE_APPLICATIONS_TOKEN", TOKEN)
    monkeypatch.setattr(
        httpx.AsyncHTTPTransport, "handle_async_request", _async_blocked
    )
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _blocked("httpx"))
    monkeypatch.setattr(smtplib.SMTP, "__init__", _blocked("smtp"))
    monkeypatch.setattr(smtplib.SMTP_SSL, "__init__", _blocked("smtp_ssl"))
    monkeypatch.setattr("app.services.email.send_email", _blocked("send_email"))
    monkeypatch.setattr(
        "app.services.m365.system_mail.send_system_email", _blocked("system_mail")
    )
    monkeypatch.setattr(
        "app.api.public_share._invite_post_apply_task", _blocked("post_apply_invite")
    )

    async def _noop_embed(candidate_id, db):
        return True

    monkeypatch.setattr("app.services.embedding_service.embed_candidate", _noop_embed)
    return calls


def _auth(value: str = TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {value}"}


def _email(label: str) -> str:
    return f"polecenie-{label}-{uuid.uuid4().hex[:8]}@example.com"


def _form(referred_contact: str, **extra) -> dict:
    return {
        "referrer_name": "Jan Testowy",
        "referrer_email": _email("polecajacy"),
        "referred_name": "Ewa Maria Przykładowa",
        "referred_contact": referred_contact,
        "referred_role": "QA Automation, 5 lat",
        "knows": KNOWS,
        "consent": [CONSENT],
        **extra,
    }


async def _referrals_for(contact_email: str) -> list[CandidateReferral]:
    async with AsyncSessionLocal() as db:
        return list(
            await db.scalars(
                select(CandidateReferral).where(
                    func.lower(CandidateReferral.referred_email)
                    == contact_email.lower()
                )
            )
        )


async def _make_candidate(**fields) -> Candidate:
    async with AsyncSessionLocal() as db:
        person = Candidate(
            name="Ewa",
            lastname="Wcześniejsza",
            source="strona WWW",
            status=CandidateStatus.active,
            preferences={},
            **fields,
        )
        db.add(person)
        await db.commit()
        return person


async def test_new_person_becomes_candidate_with_referral_source(
    app_client, outbound
) -> None:
    referred = _email("nowa")
    form = _form(referred)

    resp = await app_client.post(URL, data=form, headers=_auth())

    assert resp.status_code == 201, resp.text
    assert resp.json() == {"ok": True, "status": "received"}
    [referral] = await _referrals_for(referred)
    async with AsyncSessionLocal() as db:
        person = await db.get(Candidate, referral.candidate_id)
        events = list(
            await db.scalars(
                select(CandidateSourceEvent).where(
                    CandidateSourceEvent.candidate_id == person.id
                )
            )
        )
        consents = list(
            await db.scalars(
                select(CandidateConsent).where(
                    CandidateConsent.candidate_id == person.id
                )
            )
        )
        submission = await db.get(ApplicationSubmission, referral.submission_id)
    assert (person.name, person.lastname, person.email) == (
        "Ewa Maria",
        "Przykładowa",
        referred,
    )
    assert person.source == "polecenie"
    assert person.source_enum == CandidateSource.referral
    assert person.created_by is None
    assert [e.channel for e in events] == [SourceChannel.referral]
    assert "Jan Testowy" in events[0].note
    # Zgoda z formularza jest polecającego — polecany nie dostaje zgody za siebie.
    assert consents == []
    assert referral.was_in_database is False
    assert referral.statement_text == KNOWS
    assert [c["text"] for c in referral.consents] == [CONSENT]
    assert referral.referrer_email == form["referrer_email"]
    assert referral.referrer_contract_id is None
    assert referral.status == "new" and referral.bonus_amount is None
    assert submission.status == "pending_review"
    assert submission.matched_candidate_id == person.id
    assert "Jan Testowy" in submission.submitted_message
    assert "QA Automation" in submission.submitted_message
    assert submission.raw_payload["referral_id"] == referral.id
    assert outbound == []


async def test_linkedin_only_referral(app_client, outbound) -> None:
    slug = f"ewa-{uuid.uuid4().hex[:8]}"

    resp = await app_client.post(
        URL, data=_form(f"pl.linkedin.com/in/{slug}/?utm=x"), headers=_auth()
    )

    assert resp.status_code == 201, resp.text
    async with AsyncSessionLocal() as db:
        referral = await db.scalar(
            select(CandidateReferral).where(
                CandidateReferral.referred_linkedin == f"https://linkedin.com/in/{slug}"
            )
        )
        person = await db.get(Candidate, referral.candidate_id)
        submission = await db.get(ApplicationSubmission, referral.submission_id)
    assert referral.referred_email is None
    assert person.email is None
    assert person.linkedin == f"https://linkedin.com/in/{slug}"
    assert submission.submitted_email == ""
    assert outbound == []


async def test_person_already_in_base_is_not_touched(app_client, outbound) -> None:
    referred = _email("w-bazie")
    existing = await _make_candidate(email=referred.upper())

    resp = await app_client.post(URL, data=_form(referred), headers=_auth())

    assert resp.status_code == 201
    assert resp.json() == {"ok": True, "status": "received"}
    [referral] = await _referrals_for(referred)
    async with AsyncSessionLocal() as db:
        person = await db.get(Candidate, existing.id)
        submission = await db.get(ApplicationSubmission, referral.submission_id)
        count = await db.scalar(
            select(func.count(Candidate.id)).where(
                func.lower(Candidate.email) == referred.lower()
            )
        )
    assert count == 1
    assert (person.name, person.lastname, person.source) == (
        "Ewa",
        "Wcześniejsza",
        "strona WWW",
    )
    assert referral.candidate_id == existing.id and referral.was_in_database
    assert submission.matched_candidate_id == existing.id
    assert "już w bazie" in submission.submitted_message
    assert outbound == []


async def test_person_matched_by_linkedin_profile(app_client, outbound) -> None:
    slug = f"ewa-{uuid.uuid4().hex[:8]}"
    existing = await _make_candidate(linkedin=f"https://www.linkedin.com/in/{slug}/")

    resp = await app_client.post(
        URL, data=_form(f"https://linkedin.com/in/{slug}"), headers=_auth()
    )

    assert resp.status_code == 201
    async with AsyncSessionLocal() as db:
        referral = await db.scalar(
            select(CandidateReferral).where(
                CandidateReferral.candidate_id == existing.id
            )
        )
    assert referral is not None and referral.was_in_database


async def test_parallel_referral_of_the_same_new_person_links_to_one_profile(
    app_client, outbound, monkeypatch
) -> None:
    """Drugie żądanie widzi „nowa osoba”, a profil zapisało już pierwsze: bez 500."""
    from app.services import website_referrals

    referred = _email("naraz")
    await _make_candidate(email=referred)
    real = website_referrals._matching_candidate
    calls = {"n": 0}

    async def _late(db, ref):
        calls["n"] += 1
        return None if calls["n"] == 1 else await real(db, ref)

    monkeypatch.setattr(website_referrals, "_matching_candidate", _late)

    resp = await app_client.post(URL, data=_form(referred), headers=_auth())

    assert resp.status_code == 201, resp.text
    [referral] = await _referrals_for(referred)
    assert referral.candidate_id is not None and referral.was_in_database
    async with AsyncSessionLocal() as db:
        count = await db.scalar(
            select(func.count(Candidate.id)).where(
                func.lower(Candidate.email) == referred.lower()
            )
        )
    assert count == 1


async def test_erased_address_gets_no_profile(
    app_client, outbound, monkeypatch
) -> None:
    """Osoba, która prosiła o usunięcie, nie wraca do bazy z cudzego polecenia."""
    referred = _email("usunieta")

    async def _erased(db, email):
        return email == referred.lower()

    monkeypatch.setattr(
        "app.services.candidate_erasure_leftovers.email_was_erased", _erased
    )

    resp = await app_client.post(URL, data=_form(referred), headers=_auth())

    assert resp.status_code == 201
    [referral] = await _referrals_for(referred)
    async with AsyncSessionLocal() as db:
        submission = await db.get(ApplicationSubmission, referral.submission_id)
        count = await db.scalar(
            select(func.count(Candidate.id)).where(
                func.lower(Candidate.email) == referred.lower()
            )
        )
    assert count == 0
    assert referral.candidate_id is None
    assert submission.matched_candidate_id is None
    assert submission.submitted_email == referred
    assert "usunięty na prośbę" in submission.submitted_message
    assert outbound == []


async def test_same_referral_twice_is_recorded_once(app_client, outbound) -> None:
    referred = _email("dwa-razy")
    form = _form(referred)

    first = await app_client.post(URL, data=form, headers=_auth())
    second = await app_client.post(URL, data=form, headers=_auth())

    assert (first.status_code, second.status_code) == (201, 201)
    assert second.json() == {"ok": True, "status": "received"}
    rows = await _referrals_for(referred)
    assert len(rows) == 1
    async with AsyncSessionLocal() as db:
        submissions = await db.scalar(
            select(func.count(ApplicationSubmission.id)).where(
                func.lower(ApplicationSubmission.submitted_email) == referred.lower()
            )
        )
    assert submissions == 1


async def test_consultant_referrer_is_matched_to_contract(app_client, outbound) -> None:
    person = await make_person(activated=False)
    referred = _email("od-konsultanta")

    resp = await app_client.post(
        URL, data=_form(referred, referrer_email=person.email), headers=_auth()
    )

    assert resp.status_code == 201
    [referral] = await _referrals_for(referred)
    assert referral.referrer_contract_id == person.contract_id
    assert referral.referrer_candidate_id == person.candidate_id
    async with AsyncSessionLocal() as db:
        submission = await db.get(ApplicationSubmission, referral.submission_id)
    assert "konsultant B2B" in submission.submitted_message


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"referred_contact": "ewa w firmie"}, "referred_contact"),
        ({"referred_contact": "https://example.com/ewa"}, "referred_contact"),
        ({"referred_contact": "linkedin.com/company/firma"}, "referred_contact"),
        ({"knows": ""}, "knows"),
        ({"consent": []}, "consent"),
        ({"referrer_name": ""}, "referrer_name"),
        ({"referred_name": "Ewa\nPremia: 5000"}, "referred_name"),
        ({"referrer_email": "nie-adres"}, "referrer_email"),
    ],
)
async def test_invalid_fields_get_422_and_nothing_is_saved(
    app_client, outbound, change, field
) -> None:
    referred = _email("pole")
    form = {**_form(referred), **change}

    resp = await app_client.post(URL, data=form, headers=_auth())

    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"][0]["loc"] == ["body", field]
    assert await _referrals_for(referred) == []
    assert outbound == []


async def test_self_referral_is_refused(app_client, outbound) -> None:
    me = _email("ja")

    resp = await app_client.post(
        URL, data=_form(me.upper(), referrer_email=me), headers=_auth()
    )

    assert resp.status_code == 422
    assert resp.json()["detail"][0]["loc"] == ["body", "referred_contact"]
    assert await _referrals_for(me) == []


@pytest.mark.parametrize("auth", [None, "Bearer zly-token", "Bearer "])
async def test_wrong_token_is_refused(app_client, outbound, auth) -> None:
    referred = _email("token")
    hdrs = {} if auth is None else {"Authorization": auth}

    resp = await app_client.post(URL, data=_form(referred), headers=hdrs)

    assert resp.status_code == 401
    assert await _referrals_for(referred) == []


async def _referral_id(app_client) -> int:
    referred = _email("lista")
    resp = await app_client.post(URL, data=_form(referred), headers=_auth())
    assert resp.status_code == 201
    [row] = await _referrals_for(referred)
    return row.id


async def test_recruiter_sets_bonus_and_finance_marks_paid(
    app_client, outbound
) -> None:
    referral_id = await _referral_id(app_client)
    recruiter = headers(await make_user(UserRole.recruiter))
    finance = headers(await make_user(UserRole.finance))
    item = f"{STAFF}/{referral_id}"

    listed = await app_client.get(STAFF, headers=recruiter, params={"status": "new"})
    assert listed.status_code == 200
    assert referral_id in {r["id"] for r in listed.json()["referrals"]}

    assert (
        await app_client.patch(item, headers=recruiter, json={"status": "contacted"})
    ).status_code == 200
    no_amount = await app_client.patch(
        item, headers=recruiter, json={"status": "started"}
    )
    assert no_amount.status_code == 422
    for wrong in ("999.99", "5000.01", "0"):
        bad = await app_client.patch(
            item, headers=recruiter, json={"bonus_amount": wrong}
        )
        assert bad.status_code == 422, wrong
    started = await app_client.patch(
        item,
        headers=recruiter,
        json={"status": "started", "bonus_amount": "2500", "note": "Senior QA"},
    )
    assert started.status_code == 200, started.text
    body = started.json()["referral"]
    assert (body["status"], body["bonus_amount"], body["status_note"]) == (
        "started",
        "2500.00",
        "Senior QA",
    )

    recruiter_pays = await app_client.post(f"{item}/paid", headers=recruiter)
    assert recruiter_pays.status_code == 403
    paid = await app_client.post(f"{item}/paid", headers=finance)
    assert paid.status_code == 200, paid.text
    assert paid.json()["referral"]["status"] == "paid"

    locked = await app_client.patch(
        item, headers=recruiter, json={"bonus_amount": "3000"}
    )
    assert locked.status_code == 409
    twice = await app_client.post(f"{item}/paid", headers=finance)
    assert twice.status_code == 409
    assert outbound == []


async def test_paid_needs_started_referral(app_client, outbound) -> None:
    referral_id = await _referral_id(app_client)
    finance = headers(await make_user(UserRole.finance))

    resp = await app_client.post(f"{STAFF}/{referral_id}/paid", headers=finance)

    assert resp.status_code == 409


async def test_recruiter_cannot_set_paid_through_patch(app_client, outbound) -> None:
    referral_id = await _referral_id(app_client)
    recruiter = headers(await make_user(UserRole.recruiter))

    resp = await app_client.patch(
        f"{STAFF}/{referral_id}", headers=recruiter, json={"status": "paid"}
    )

    assert resp.status_code == 422


@pytest.mark.parametrize("role", [UserRole.automation, UserRole.user])
async def test_roles_without_candidate_write_see_nothing(
    app_client, outbound, role
) -> None:
    referral_id = await _referral_id(app_client)
    other = headers(await make_user(role))

    assert (await app_client.get(STAFF, headers=other)).status_code == 403
    change = await app_client.patch(
        f"{STAFF}/{referral_id}", headers=other, json={"status": "contacted"}
    )
    assert change.status_code == 403
