"""Strona kariery (0339): linki, opis publiczny, formularz, zgody.

Pokrywa kontrakt ``career-contract.md``:

- CHECK-i ``candidate_invite_links`` (link ``recruiter`` bez sluga odrzucony);
- publiczny ``GET /r/{slug}`` nigdy nie zwraca klienta ani stawki (test na
  KSZTAŁT odpowiedzi, nie na wybrane pola), 404 bez zatwierdzonego opisu,
  ``closed`` dla zamkniętej rekrutacji;
- ``POST /apply`` w obu gałęziach (nowy e-mail / duplikat) × oba rodzaje linku;
- zgoda wymagana, zapisana, znika z kandydatem (CASCADE);
- pułapka na boty, powiadomienie ``new_application``, przypięcie w „Moich
  ludziach";
- zatwierdzenie odmawia 422 przy znaleziskach; walidacja sluga i 409.
"""

from __future__ import annotations

import io
import json
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.application_submission import ApplicationSubmission
from app.models.candidate import Candidate
from app.models.candidate_consent import CandidateConsent
from app.models.candidate_source_event import CandidateSourceEvent
from app.models.invite_link import CandidateInviteLink
from app.models.job import Job, JobStatus, RecruitmentType, RemotePolicy
from app.models.my_people import MyPeopleOverride
from app.models.notification import Notification, NotificationType
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import User, UserRole
from app.services.career_consent import CONSENT_TEXT_SHA256, CONSENT_TEXT_VERSION

pytestmark = pytest.mark.asyncio

_CLIENT_NAME_BASE = "Kwarcowy Bank Hipoteczny"


async def _seed_user(label: str = "career") -> tuple[int, str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"career-{label}-{unique}@example.com"
    password = f"T3st_{unique}!Car"
    async with AsyncSessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password(password),
            name=f"Marta Rekruterska{unique}",
            role=UserRole.recruiter,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user.id, email, password


async def _seed_job(
    owner_id: int,
    *,
    client_name: str | None = None,
    title: str | None = None,
    is_open: bool = True,
) -> int:
    from app.models.client import Client

    # Same litery: sufiks nie może przypadkiem zawierać „175"/„180", które
    # test kształtu odpowiedzi szuka jako wyciek stawki.
    unique = "".join(c for c in uuid.uuid4().hex if c.isalpha())[:6] or "abcdef"
    async with AsyncSessionLocal() as db:
        client = Client(name=client_name or f"{_CLIENT_NAME_BASE} {unique}")
        db.add(client)
        await db.flush()
        job = Job(
            title=title or f"Senior Java Developer {unique}",
            location="Warszawa",
            status=JobStatus.published,
            is_open=is_open,
            remote_policy=RemotePolicy.hybrid,
            onsite_days_per_week=2,
            recruitment_type=RecruitmentType.body_leasing,
            client_id=client.id,
            recruiter_id=owner_id,
            rate_budget_hourly=180,
            champion_profile={
                "basics": {
                    "rate_value": 175,
                    "rate_raw": "175 zł/h netto",
                    "start_date": "10.2026",
                    "contract_length": "12+ mies.",
                },
                "client": {"about": f"{client.name} — sekretny opis klienta"},
                "stack": {"must": [{"name": "Java 17"}], "nice": [{"name": "Kafka"}]},
            },
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job.id


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


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


async def _owner_with_job(api: AsyncClient):
    uid, email, password = await _seed_user()
    headers = await _login(api, email, password)
    job_id = await _seed_job(uid)
    return uid, headers, job_id


async def _create_job_link(api: AsyncClient, headers, job_id: int) -> dict:
    resp = await api.post("/api/invite-links", json={"job_id": job_id}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _approve(api: AsyncClient, headers, job_id: int, **fields) -> dict:
    body = {
        "subtitle": "Rozwój platformy płatności dla sektora finansowego",
        "about": "Budujemy nowy system rozliczeń.\n\nPracujesz w zespole 6 osób.",
        **fields,
    }
    put = await api.put(
        f"/api/jobs/{job_id}/public-profile", json=body, headers=headers
    )
    assert put.status_code == 200, put.text
    resp = await api.post(f"/api/jobs/{job_id}/public-profile/approve", headers=headers)
    return resp


def _form(link_slug: str, email: str, **extra) -> dict:
    return {
        "link_slug": link_slug,
        "first_name": "Jan",
        "last_name": "Kandydacki",
        "email": email,
        "consent": "true",
        **extra,
    }


def _cv():
    return {"cv": ("cv.pdf", io.BytesIO(b"%PDF-1.4 career"), "application/pdf")}


# ── Schemat ────────────────────────────────────────────────────────────────


async def test_recruiter_link_without_slug_is_rejected_by_check():
    uid, _, _ = await _seed_user("check")
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateInviteLink(
                token=f"v2${uuid.uuid4().hex}",
                created_by=uid,
                kind="recruiter",
                slug=None,
                job_id=None,
            )
        )
        with pytest.raises(IntegrityError):
            await db.commit()


async def test_job_link_without_job_is_rejected_by_check():
    uid, _, _ = await _seed_user("check2")
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateInviteLink(
                token=f"v2${uuid.uuid4().hex}",
                created_by=uid,
                kind="job",
                slug=f"x-{uuid.uuid4().hex[:6]}",
                job_id=None,
            )
        )
        with pytest.raises(IntegrityError):
            await db.commit()


async def test_consent_needs_exactly_one_subject():
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateConsent(
                kind="recruitment_current_future",
                text_version=CONSENT_TEXT_VERSION,
                text_sha256=CONSENT_TEXT_SHA256,
            )
        )
        with pytest.raises(IntegrityError):
            await db.commit()


# ── Link rekrutacji i opis publiczny ───────────────────────────────────────


async def test_new_job_link_has_slug_and_no_expiry(api):
    _, headers, job_id = await _owner_with_job(api)
    link = await _create_job_link(api, headers, job_id)
    assert link["kind"] == "job"
    assert link["expires_at"] is None
    assert link["slug"].startswith("senior-java-developer-")
    assert link["public_url"].endswith(f"/r/{link['slug']}")
    assert link["visit_count"] == 0
    assert link["status"] == "active"


async def test_public_page_is_404_until_profile_is_approved(api):
    _, headers, job_id = await _owner_with_job(api)
    link = await _create_job_link(api, headers, job_id)
    assert (await api.get(f"/api/public/career/r/{link['slug']}")).status_code == 404
    await api.put(
        f"/api/jobs/{job_id}/public-profile",
        json={"subtitle": "Szkic", "about": "Jeszcze nie"},
        headers=headers,
    )
    assert (await api.get(f"/api/public/career/r/{link['slug']}")).status_code == 404
    assert (
        await api.get("/api/public/career/r/nie-ma-takiego-xxxx")
    ).status_code == 404


async def test_public_page_never_leaks_client_or_rate(api):
    _, headers, job_id = await _owner_with_job(api)
    link = await _create_job_link(api, headers, job_id)
    approved = await _approve(api, headers, job_id)
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"

    resp = await api.get(f"/api/public/career/r/{link['slug']}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "open"
    # Kształt odpowiedzi jest zamknięty — nowe pole = świadoma decyzja.
    assert set(body) == {"status", "recruiter", "job"}
    assert set(body["recruiter"]) == {"first_name", "slug"}
    assert set(body["job"]) == {
        "slug",
        "title",
        "subtitle",
        "about",
        "must",
        "nice",
        "params",
        "show",
    }
    assert set(body["job"]["params"]) == {
        "city",
        "remote_policy",
        "onsite_days_per_week",
        "seniority",
        "contract",
        "start",
        "duration",
    }
    assert body["job"]["must"] == [{"name": "Java 17", "note": None}]
    assert body["job"]["nice"] == ["Kafka"]
    assert body["job"]["params"]["contract"] == "B2B"
    assert body["recruiter"]["first_name"] == "Marta"

    serialized = json.dumps(body, ensure_ascii=False)
    for forbidden in (_CLIENT_NAME_BASE, "175", "180", "zł", "sekretny", "Rekruterska"):
        assert forbidden not in serialized, forbidden

    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(CandidateInviteLink).where(CandidateInviteLink.slug == link["slug"])
        )
        assert row.visit_count == 1


async def test_closed_job_returns_closed_state(api):
    uid, headers, job_id = await _owner_with_job(api)
    link = await _create_job_link(api, headers, job_id)
    assert (await _approve(api, headers, job_id)).status_code == 200
    put = await api.put(
        "/api/me/career-link",
        json={"slug": f"marta-{uuid.uuid4().hex[:6]}"},
        headers=headers,
    )
    assert put.status_code == 200, put.text
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        job.is_open = False
        job.status = JobStatus.closed
        await db.commit()

    resp = await api.get(f"/api/public/career/r/{link['slug']}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "closed"
    assert body["job"]["about"] is None and body["job"]["must"] == []
    assert body["recruiter"]["slug"] == put.json()["link"]["slug"]
    # Zamknięta rekrutacja nie przyjmuje zgłoszeń — ani nowym, ani starym formularzem.
    apply = await api.post(
        "/api/public/career/apply",
        data=_form(link["slug"], f"closed-{uuid.uuid4().hex[:6]}@example.com"),
        files=_cv(),
    )
    assert apply.status_code == 404
    old = await api.get(f"/api/public/apply/{link['token']}")
    assert old.status_code == 404


async def test_approve_refuses_client_name_and_money(api):
    _, headers, job_id = await _owner_with_job(api)
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        from app.models.client import Client

        client_name = (await db.get(Client, job.client_id)).name
    resp = await _approve(
        api,
        headers,
        job_id,
        about=f"Projekt dla {client_name}. Budżet do 180 zł/h.",
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "PUBLIC_PROFILE_FINDINGS"
    codes = {f["code"] for f in detail["findings"]}
    assert codes == {"client_name", "money"}

    profile = await api.get(f"/api/jobs/{job_id}/public-profile", headers=headers)
    assert profile.json()["status"] == "draft"
    assert {f["code"] for f in profile.json()["findings"]} == codes


async def test_edit_after_approval_returns_to_draft_and_visibility_does_not(api):
    _, headers, job_id = await _owner_with_job(api)
    assert (await _approve(api, headers, job_id)).status_code == 200
    vis = await api.put(
        f"/api/jobs/{job_id}/public-profile/visibility",
        json={"show_on_recruiter_page": False},
        headers=headers,
    )
    assert vis.status_code == 200 and vis.json()["status"] == "approved"
    assert vis.json()["show_on_recruiter_page"] is False
    edited = await api.put(
        f"/api/jobs/{job_id}/public-profile",
        json={"about": "Nowa treść."},
        headers=headers,
    )
    assert edited.json()["status"] == "draft"


async def test_public_profile_requires_job_membership(api):
    _, _, job_id = await _owner_with_job(api)
    _, email, password = await _seed_user("outsider")
    outsider = await _login(api, email, password)
    resp = await api.get(f"/api/jobs/{job_id}/public-profile", headers=outsider)
    assert resp.status_code == 403


# ── Formularz ──────────────────────────────────────────────────────────────


async def test_apply_via_job_link_creates_candidate_consent_and_notification(api):
    uid, headers, job_id = await _owner_with_job(api)
    link = await _create_job_link(api, headers, job_id)
    assert (await _approve(api, headers, job_id)).status_code == 200
    applicant = f"job-apply-{uuid.uuid4().hex[:6]}@example.com"

    resp = await api.post(
        "/api/public/career/apply",
        data=_form(
            link["slug"],
            applicant,
            expected_rate_hourly="165",
            availability_date="2026-11-01",
            city="Kraków",
            work_mode="hybrid",
            utm_source="linkedin",
        ),
        files=_cv(),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json() == {"ok": True, "status": "received"}

    async with AsyncSessionLocal() as db:
        cand = await db.scalar(select(Candidate).where(Candidate.email == applicant))
        assert cand is not None and cand.created_by == uid
        assert float(cand.expected_rate_hourly) == 165.0
        assert cand.expected_rate_currency == "PLN"
        assert cand.city == "Kraków"
        assert str(cand.availability_date) == "2026-11-01"
        assert cand.preferences == {"remote_modes": ["hybrid"]}
        stage = await db.scalar(
            select(CandidateStage).where(
                CandidateStage.candidate_id == cand.id,
                CandidateStage.job_id == job_id,
            )
        )
        assert stage is not None
        consent = await db.scalar(
            select(CandidateConsent).where(CandidateConsent.candidate_id == cand.id)
        )
        assert consent is not None
        assert consent.text_version == CONSENT_TEXT_VERSION
        assert consent.text_sha256 == CONSENT_TEXT_SHA256
        source = await db.scalar(
            select(CandidateSourceEvent).where(
                CandidateSourceEvent.candidate_id == cand.id
            )
        )
        assert source.job_id == job_id and source.utm_source == "linkedin"
        notif = await db.scalar(
            select(Notification).where(
                Notification.user_id == uid,
                Notification.notification_type == NotificationType.new_application,
                Notification.related_entity_id == cand.id,
            )
        )
        assert notif is not None and notif.link == f"/candidates/{cand.id}"
        row = await db.scalar(
            select(CandidateInviteLink).where(CandidateInviteLink.slug == link["slug"])
        )
        assert row.use_count == 1

        # Art. 17 RODO: twarde usunięcie kandydata zabiera jego zgodę.
        consent_id = consent.id
        await db.execute(delete(Candidate).where(Candidate.id == cand.id))
        await db.commit()
        remaining = await db.scalar(
            select(CandidateConsent.id).where(CandidateConsent.id == consent_id)
        )
        assert remaining is None


async def test_apply_via_recruiter_link_pins_in_my_people_without_process(api):
    uid, headers, _ = await _owner_with_job(api)
    slug = f"marta-{uuid.uuid4().hex[:6]}"
    put = await api.put("/api/me/career-link", json={"slug": slug}, headers=headers)
    assert put.status_code == 200, put.text
    assert put.json()["link"]["public_url"].endswith(f"/{slug}")

    applicant = f"rec-apply-{uuid.uuid4().hex[:6]}@example.com"
    resp = await api.post(
        "/api/public/career/apply", data=_form(slug, applicant), files=_cv()
    )
    assert resp.status_code == 201, resp.text

    async with AsyncSessionLocal() as db:
        cand = await db.scalar(select(Candidate).where(Candidate.email == applicant))
        assert cand is not None and cand.created_by == uid
        assert (
            await db.scalar(
                select(CandidateStage).where(CandidateStage.candidate_id == cand.id)
            )
        ) is None
        pin = await db.scalar(
            select(MyPeopleOverride).where(
                MyPeopleOverride.user_id == uid,
                MyPeopleOverride.candidate_id == cand.id,
            )
        )
        assert pin is not None and pin.kind == "pinned"
        source = await db.scalar(
            select(CandidateSourceEvent).where(
                CandidateSourceEvent.candidate_id == cand.id
            )
        )
        assert source.job_id is None
        assert (
            await db.scalar(
                select(Notification).where(
                    Notification.user_id == uid,
                    Notification.notification_type == NotificationType.new_application,
                    Notification.related_entity_id == cand.id,
                )
            )
        ) is not None

    stats = await api.get("/api/me/career-link", headers=headers)
    assert stats.json()["stats"] == {"days": 30, "applications": 1, "new_candidates": 1}


@pytest.mark.parametrize("link_kind", ["job", "recruiter"])
async def test_duplicate_email_links_submission_with_consent(api, link_kind):
    uid, headers, job_id = await _owner_with_job(api)
    if link_kind == "job":
        slug = (await _create_job_link(api, headers, job_id))["slug"]
        assert (await _approve(api, headers, job_id)).status_code == 200
    else:
        slug = f"dup-{uuid.uuid4().hex[:6]}"
        assert (
            await api.put("/api/me/career-link", json={"slug": slug}, headers=headers)
        ).status_code == 200

    existing_email = f"dup-{uuid.uuid4().hex[:6]}@example.com"
    async with AsyncSessionLocal() as db:
        existing = Candidate(name="Stary", lastname="Profil", email=existing_email)
        db.add(existing)
        await db.commit()
        existing_id = existing.id

    resp = await api.post(
        "/api/public/career/apply",
        data=_form(slug, existing_email, city="Gdańsk", expected_rate_hourly="150"),
        files=_cv(),
    )
    assert resp.status_code == 201, resp.text

    async with AsyncSessionLocal() as db:
        cand = await db.get(Candidate, existing_id)
        assert cand.name == "Stary" and cand.city is None
        sub = await db.scalar(
            select(ApplicationSubmission).where(
                ApplicationSubmission.matched_candidate_id == existing_id
            )
        )
        assert sub is not None
        assert sub.job_id == (job_id if link_kind == "job" else None)
        assert sub.raw_payload["city"] == "Gdańsk"
        assert sub.raw_payload["expected_rate_hourly"] == "150.00"
        consent = await db.scalar(
            select(CandidateConsent).where(
                CandidateConsent.application_submission_id == sub.id
            )
        )
        assert consent is not None and consent.candidate_id is None
        assert sub.status == "linked"
        notif = await db.scalar(
            select(Notification).where(
                Notification.user_id == uid,
                Notification.related_entity_type == "candidate",
                Notification.related_entity_id == existing_id,
            )
        )
        assert notif is not None and notif.link == f"/candidates/{existing_id}"


async def test_apply_requires_consent_and_honeypot_is_silent(api):
    _, headers, _ = await _owner_with_job(api)
    slug = f"hp-{uuid.uuid4().hex[:6]}"
    await api.put("/api/me/career-link", json={"slug": slug}, headers=headers)

    no_consent = _form(slug, f"nc-{uuid.uuid4().hex[:6]}@example.com")
    no_consent.pop("consent")
    resp = await api.post("/api/public/career/apply", data=no_consent, files=_cv())
    assert resp.status_code == 422
    assert resp.json()["detail"][0]["loc"] == ["body", "consent"]

    bot_email = f"bot-{uuid.uuid4().hex[:6]}@example.com"
    bot = await api.post(
        "/api/public/career/apply",
        data=_form(slug, bot_email, website="http://spam.example"),
        files=_cv(),
    )
    assert bot.status_code == 201
    async with AsyncSessionLocal() as db:
        assert (
            await db.scalar(select(Candidate).where(Candidate.email == bot_email))
        ) is None


async def test_legacy_apply_endpoint_now_requires_consent(api):
    _, headers, job_id = await _owner_with_job(api)
    token = (await _create_job_link(api, headers, job_id))["token"]
    resp = await api.post(
        f"/api/public/apply/{token}",
        data={
            "first_name": "Ola",
            "last_name": "Bezzgody",
            "email": f"legacy-{uuid.uuid4().hex[:6]}@example.com",
        },
        files=_cv(),
    )
    assert resp.status_code == 422
    assert resp.json()["detail"][0]["loc"] == ["body", "consent"]


async def test_apply_via_unknown_or_unapproved_link_is_404(api):
    _, headers, job_id = await _owner_with_job(api)
    link = await _create_job_link(api, headers, job_id)
    unapproved = await api.post(
        "/api/public/career/apply",
        data=_form(link["slug"], f"u-{uuid.uuid4().hex[:6]}@example.com"),
        files=_cv(),
    )
    assert unapproved.status_code == 404
    unknown = await api.post(
        "/api/public/career/apply",
        data=_form("zupelnie-nieznany", f"u-{uuid.uuid4().hex[:6]}@example.com"),
        files=_cv(),
    )
    assert unknown.status_code == 404


# ── Stały link rekrutera ───────────────────────────────────────────────────


async def test_recruiter_slug_validation_reserved_and_conflict(api):
    _, headers, _ = await _owner_with_job(api)
    assert (
        await api.put("/api/me/career-link", json={"slug": "rodo"}, headers=headers)
    ).status_code == 422
    assert (
        await api.put(
            "/api/me/career-link", json={"slug": "Zła-Nazwa"}, headers=headers
        )
    ).status_code == 422

    slug = f"taken-{uuid.uuid4().hex[:6]}"
    assert (
        await api.put("/api/me/career-link", json={"slug": slug}, headers=headers)
    ).status_code == 200
    _, email, password = await _seed_user("second")
    other = await _login(api, email, password)
    conflict = await api.put("/api/me/career-link", json={"slug": slug}, headers=other)
    assert conflict.status_code == 409
    avail = await api.get(
        "/api/me/career-link/slug-available", params={"slug": slug}, headers=other
    )
    assert avail.json() == {"available": False, "reason": "Ten adres jest już zajęty."}
    mine = await api.get(
        "/api/me/career-link/slug-available", params={"slug": slug}, headers=headers
    )
    assert mine.json()["available"] is True


async def test_recruiter_page_lists_only_approved_visible_open_jobs(api):
    uid, headers, job_id = await _owner_with_job(api)
    link = await _create_job_link(api, headers, job_id)
    assert (await _approve(api, headers, job_id)).status_code == 200
    hidden_job = await _seed_job(uid)
    await _create_job_link(api, headers, hidden_job)  # bez zatwierdzonego opisu
    slug = f"page-{uuid.uuid4().hex[:6]}"
    await api.put("/api/me/career-link", json={"slug": slug}, headers=headers)

    resp = await api.get(f"/api/public/career/p/{slug}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["recruiter"] == {"first_name": "Marta", "slug": slug}
    assert [j["slug"] for j in body["jobs"]] == [link["slug"]]
    assert set(body["jobs"][0]) == {"slug", "title", "city", "remote_policy"}

    me = await api.get("/api/me/career-link", headers=headers)
    by_job = {j["job_id"]: j for j in me.json()["jobs"]}
    assert by_job[job_id]["profile_status"] == "approved"
    assert by_job[hidden_job]["profile_status"] == "none"

    assert (await api.delete("/api/me/career-link", headers=headers)).status_code == 204
    assert (await api.get(f"/api/public/career/p/{slug}")).status_code == 404
    # Ten sam adres wraca do właściciela po ponownym ustawieniu.
    again = await api.put("/api/me/career-link", json={"slug": slug}, headers=headers)
    assert again.status_code == 200


async def test_draft_is_503_without_ai_key(api, monkeypatch):
    _, headers, job_id = await _owner_with_job(api)
    monkeypatch.setattr(
        "app.services.llm_providers.api_key_configured", lambda model: False
    )
    resp = await api.post(f"/api/jobs/{job_id}/public-profile/draft", headers=headers)
    assert resp.status_code == 503


async def test_draft_prompt_carries_no_client_or_rate(monkeypatch):
    from app.services.job_public_profile import _DRAFT_PROMPT, draft_material

    job = Job(
        title="Senior Java Developer",
        champion_profile={
            "basics": {"rate_value": 175, "rate_raw": "175 zł/h"},
            "client": {"about": "Kwarcowy Bank"},
            "project": {"about": "Nowy system rozliczeń", "responsibilities": ""},
            "stack": {"must": [{"name": "Java"}]},
        },
    )
    prompt = _DRAFT_PROMPT.format(**draft_material(job))
    assert "Kwarcowy" not in prompt and "175" not in prompt
    assert "Nowy system rozliczeń" in prompt and "Java" in prompt


# ── Poprawki po teście na produkcji (0340) ─────────────────────────────────


async def test_published_job_not_handed_off_gets_a_link_and_an_open_page(api):
    """Link żyje do zamknięcia rekrutacji — ``is_open`` nie jest warunkiem."""
    uid, email, password = await _seed_user("notopen")
    headers = await _login(api, email, password)
    job_id = await _seed_job(uid, is_open=False)
    link = await _create_job_link(api, headers, job_id)
    assert link["status"] == "active"
    assert (await _approve(api, headers, job_id)).status_code == 200
    put = await api.put(
        "/api/me/career-link",
        json={"slug": f"marta-{uuid.uuid4().hex[:6]}"},
        headers=headers,
    )
    assert put.status_code == 200, put.text

    page = await api.get(f"/api/public/career/r/{link['slug']}")
    assert page.status_code == 200, page.text
    assert page.json()["status"] == "open"
    recruiter = await api.get(f"/api/public/career/p/{put.json()['link']['slug']}")
    assert recruiter.status_code == 200
    assert [j["slug"] for j in recruiter.json()["jobs"]] == [link["slug"]]
    mine = await api.get("/api/me/career-link", headers=headers)
    assert [j["job_id"] for j in mine.json()["jobs"]] == [job_id]


async def test_public_title_strips_client_and_codes_and_drives_the_slug(api):
    unique = "".join(c for c in uuid.uuid4().hex if c.isalpha())[:6] or "abcdef"
    client_name = f"Kwarcowy Bank {unique}"
    uid, email, password = await _seed_user("title")
    headers = await _login(api, email, password)
    job_id = await _seed_job(
        uid,
        client_name=client_name,
        title="Kwarcowy: Data Engineer Platformy (ZOB-3003)",
    )
    link = await _create_job_link(api, headers, job_id)
    assert link["slug"].startswith("data-engineer-platformy-"), link["slug"]
    assert "kwarcowy" not in link["slug"] and "zob" not in link["slug"]

    profile = await api.get(f"/api/jobs/{job_id}/public-profile", headers=headers)
    body = profile.json()
    assert body["public_title"] is None
    assert body["default_title"] == "Data Engineer Platformy"
    assert body["effective_title"] == "Data Engineer Platformy"
    assert body["preview"]["title"] == "Data Engineer Platformy"

    approved = await _approve(api, headers, job_id)
    assert approved.status_code == 200, approved.text
    page = await api.get(f"/api/public/career/r/{link['slug']}")
    assert page.json()["job"]["title"] == "Data Engineer Platformy"
    assert "Kwarcowy" not in page.text

    # Własny tytuł = zmiana treści publicznej → powrót do szkicu.
    put = await api.put(
        f"/api/jobs/{job_id}/public-profile",
        json={"public_title": "  Data Engineer   (Azure) "},
        headers=headers,
    )
    assert put.status_code == 200, put.text
    assert put.json()["public_title"] == "Data Engineer (Azure)"
    assert put.json()["effective_title"] == "Data Engineer (Azure)"
    assert put.json()["status"] == "draft"
    assert (await api.get(f"/api/public/career/r/{link['slug']}")).status_code == 404

    # Pusty tytuł własny = powrót do domyślnego.
    clear = await api.put(
        f"/api/jobs/{job_id}/public-profile",
        json={"public_title": ""},
        headers=headers,
    )
    assert clear.json()["public_title"] is None
    assert clear.json()["effective_title"] == "Data Engineer Platformy"


async def test_legacy_approval_without_title_in_hash_stays_approved(api):
    """Opis zatwierdzony przed 0340 (skrót bez tytułu) nie wraca do szkicu."""
    from app.models.job_public_profile import JobPublicProfile
    from app.services import job_public_profile as jpp

    _, headers, job_id = await _owner_with_job(api)
    link = await _create_job_link(api, headers, job_id)
    assert (await _approve(api, headers, job_id)).status_code == 200
    async with AsyncSessionLocal() as db:
        profile = await db.get(JobPublicProfile, job_id)
        profile.approved_hash = jpp.content_hash(
            profile.subtitle, profile.about, profile.sections
        )
        await db.commit()
    page = await api.get(f"/api/public/career/r/{link['slug']}")
    assert page.status_code == 200 and page.json()["status"] == "open"


async def test_career_link_exposes_base_urls(api):
    _, headers, _job = await _owner_with_job(api)
    resp = await api.get("/api/me/career-link", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["base_url"]
    assert body["recruiter_base_url"].endswith("/")
