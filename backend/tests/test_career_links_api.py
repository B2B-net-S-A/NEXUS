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
import re
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
from app.services.career_consent import (
    CONSENT_CURRENT_TEXT_SHA256,
    CONSENT_FUTURE_TEXT_SHA256,
    CONSENT_TEXT_VERSION,
)

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


# Rekrutacja na stronie rekrutera i na ekranie zamkniętej rekrutacji.
_RECRUITER_JOB_KEYS = {"slug", "title", "city", "remote_policy", "theme", "category"}


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
                kind="recruitment_current",
                text_version=CONSENT_TEXT_VERSION,
                text_sha256=CONSENT_CURRENT_TEXT_SHA256,
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
    # „theme” (0478): sam identyfikator szablonu graficznego.
    assert set(body) == {
        "status",
        "recruiter",
        "theme",
        "published_at",
        "canonical_slug",
        "job",
    }
    # Jedyny link rekrutacji jest też jej linkiem kanonicznym (audyt 21.10.2026).
    assert body["canonical_slug"] == link["slug"]
    assert body["theme"] == "terminal"  # „Senior Java Developer” → Terminal
    # Data zatwierdzenia (bez godziny) — „datePosted” w danych JobPosting dla
    # Google (etap 6, decyzja D3 Artura 20.10.2026).
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", body["published_at"])
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
        "onsite_days_per_month",
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


async def test_closed_job_lists_other_open_jobs_even_without_recruiter_link(api):
    """Etap 5: zamknięty proces odsyła do innych otwartych rekrutacji osoby —
    tej samej listy co stały link, ale bez wymogu stałego linku."""
    uid, headers, job_id = await _owner_with_job(api)
    link = await _create_job_link(api, headers, job_id)
    assert (await _approve(api, headers, job_id)).status_code == 200
    other_id = await _seed_job(uid)
    other = await _create_job_link(api, headers, other_id)
    assert (await _approve(api, headers, other_id)).status_code == 200
    # Bez opublikowanego opisu rekrutacja nie trafia na listę.
    draft_id = await _seed_job(uid)
    await _create_job_link(api, headers, draft_id)
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        job.is_open = False
        job.status = JobStatus.closed
        await db.commit()

    body = (await api.get(f"/api/public/career/r/{link['slug']}")).json()
    assert body["status"] == "closed"
    assert body["recruiter"]["slug"] is None
    assert [j["slug"] for j in body["other_jobs"]] == [other["slug"]]
    assert set(body["other_jobs"][0]) == _RECRUITER_JOB_KEYS


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


async def test_approval_keeps_a_link_whose_random_suffix_looks_like_money(api):
    """Losowa końcówka sluga („…-zl1v”) trafiała we wzorzec kwoty i każde
    zatwierdzenie opisu wymieniało rozesłany adres — stary dawał 404."""
    _, headers, job_id = await _owner_with_job(api)
    link = await _create_job_link(api, headers, job_id)
    slug = f"{link['slug'].rsplit('-', 1)[0]}-zl1v"
    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(CandidateInviteLink).where(CandidateInviteLink.slug == link["slug"])
        )
        row.slug = slug
        await db.commit()

    resp = await _approve(api, headers, job_id)
    assert resp.status_code == 200, resp.text
    assert (await api.get(f"/api/public/career/r/{slug}")).status_code == 200


async def test_approval_still_replaces_a_link_whose_slug_names_the_client(api):
    """Kontrola czyta część sluga z tytułu — nazwa klienta w niej nadal
    wymienia adres przy zatwierdzeniu opisu."""
    from app.models.client import Client
    from app.services.career_slugs import slugify

    _, headers, job_id = await _owner_with_job(api)
    link = await _create_job_link(api, headers, job_id)
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        client_slug = slugify((await db.get(Client, job.client_id)).name)
        row = await db.scalar(
            select(CandidateInviteLink).where(CandidateInviteLink.slug == link["slug"])
        )
        row.slug = f"java-developer-{client_slug}-ab12"
        old_slug = row.slug
        await db.commit()

    resp = await _approve(api, headers, job_id)
    assert resp.status_code == 200, resp.text
    assert (await api.get(f"/api/public/career/r/{old_slug}")).status_code == 404
    async with AsyncSessionLocal() as db:
        new_slug = await db.scalar(
            select(CandidateInviteLink.slug).where(
                CandidateInviteLink.job_id == job_id,
                CandidateInviteLink.kind == "job",
            )
        )
    assert new_slug and new_slug != old_slug and client_slug not in new_slug
    assert (await api.get(f"/api/public/career/r/{new_slug}")).status_code == 200


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


async def test_edit_after_approval_keeps_the_page_on_the_approved_version(api):
    """19.10.2026: poprawka opisu nie zdejmuje strony — kandydat widzi wersję
    zatwierdzoną, formularz działa, a edytor pokazuje czekające zmiany.
    „Odrzuć zmiany” = zapis szkicu z wartościami z ``live``."""
    _, headers, job_id = await _owner_with_job(api)
    link = await _create_job_link(api, headers, job_id)
    approved = await _approve(api, headers, job_id)
    assert approved.status_code == 200, approved.text
    assert approved.json()["live"]["pending_changes"] is False

    edited = await api.put(
        f"/api/jobs/{job_id}/public-profile",
        json={"about": "Poprawiony opis, jeszcze bez zatwierdzenia."},
        headers=headers,
    )
    body = edited.json()
    assert body["status"] == "draft"
    assert body["live"]["pending_changes"] is True
    assert body["live"]["about"].startswith("Budujemy nowy system rozliczeń.")

    page = await api.get(f"/api/public/career/r/{link['slug']}")
    assert page.status_code == 200, page.text
    assert page.json()["job"]["about"].startswith("Budujemy nowy system rozliczeń.")
    assert "Poprawiony" not in page.text
    apply = await api.post(
        "/api/public/career/apply",
        data=_form(link["slug"], f"live-{uuid.uuid4().hex[:6]}@example.com"),
        files=_cv(),
    )
    assert apply.status_code == 201, apply.text

    live = body["live"]
    reverted = await api.put(
        f"/api/jobs/{job_id}/public-profile",
        json={
            "subtitle": live["subtitle"],
            "about": live["about"],
            "sections": live["sections"],
            "public_title": "",
        },
        headers=headers,
    )
    assert reverted.json()["status"] == "approved"
    assert reverted.json()["live"]["pending_changes"] is False


async def test_closed_job_shows_the_closed_page_even_with_pending_changes(api):
    _, headers, job_id = await _owner_with_job(api)
    link = await _create_job_link(api, headers, job_id)
    assert (await _approve(api, headers, job_id)).status_code == 200
    await api.put(
        f"/api/jobs/{job_id}/public-profile",
        json={"about": "Zmiana po zamknięciu."},
        headers=headers,
    )
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        job.status = JobStatus.closed
        await db.commit()
    page = await api.get(f"/api/public/career/r/{link['slug']}")
    assert page.status_code == 200
    assert page.json()["status"] == "closed"


async def test_theme_change_keeps_the_approved_page(api):
    """0478: szablon graficzny działa od razu i nie cofa opisu do szkicu."""
    _, headers, job_id = await _owner_with_job(api)
    link = await _create_job_link(api, headers, job_id)
    assert (await _approve(api, headers, job_id)).status_code == 200
    url = f"/api/jobs/{job_id}/public-profile"

    before = (await api.get(url, headers=headers)).json()
    assert before["theme"] is None
    assert before["theme_default"] == "terminal"

    resp = await api.put(url, json={"theme": "jasny"}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "approved"
    assert resp.json()["theme"] == "jasny"
    page = await api.get(f"/api/public/career/r/{link['slug']}")
    assert page.json()["theme"] == "jasny"

    reset = await api.put(url, json={"theme": None}, headers=headers)
    assert reset.json()["theme"] is None and reset.json()["status"] == "approved"
    page = await api.get(f"/api/public/career/r/{link['slug']}")
    assert page.json()["theme"] == "terminal"

    bad = await api.put(url, json={"theme": "nie-ma-takiego"}, headers=headers)
    assert bad.status_code == 422
    # Sceny ról wycofane 28.10.2026 — nowego wyboru sceny nie da się zapisać.
    legacy = await api.put(url, json={"theme": "radar"}, headers=headers)
    assert legacy.status_code == 422


async def test_default_theme_follows_the_role_in_the_title(api):
    uid, email, password = await _seed_user()
    headers = await _login(api, email, password)
    job_id = await _seed_job(uid, title="Analityk systemowy")
    link = await _create_job_link(api, headers, job_id)
    assert (await _approve(api, headers, job_id)).status_code == 200
    profile = (
        await api.get(f"/api/jobs/{job_id}/public-profile", headers=headers)
    ).json()
    assert profile["theme_default"] == "jasny"
    page = await api.get(f"/api/public/career/r/{link['slug']}")
    assert page.json()["theme"] == "jasny"


async def test_poster_needs_a_live_page_and_returns_a_pdf(api):
    _, headers, job_id = await _owner_with_job(api)
    url = f"/api/jobs/{job_id}/public-profile/poster.pdf"
    # Bez linku i bez zatwierdzonego opisu plakat prowadziłby na 404.
    assert (await api.get(url, headers=headers)).status_code == 409
    await _create_job_link(api, headers, job_id)
    assert (await api.get(url, headers=headers)).status_code == 409
    assert (await _approve(api, headers, job_id)).status_code == 200
    try:
        import weasyprint  # noqa: F401
    except (ImportError, OSError):
        pytest.skip("WeasyPrint bez bibliotek systemowych (pango)")
    resp = await api.get(url, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content.startswith(b"%PDF")


async def test_link_results_count_applications_and_the_funnel(api):
    """Etap 4 linków: „Wyniki” liczą zgłoszenia z linków osoby (nowi i już
    w bazie) i to, jak daleko zaszły w rekrutacji linku."""
    _, headers, job_id = await _owner_with_job(api)
    link = await _create_job_link(api, headers, job_id)
    assert (await _approve(api, headers, job_id)).status_code == 200
    for _ in range(2):
        resp = await api.post(
            "/api/public/career/apply",
            data=_form(link["slug"], f"res-{uuid.uuid4().hex[:8]}@example.com"),
            files=_cv(),
        )
        assert resp.status_code == 201, resp.text

    body = (await api.get("/api/me/career-link/results", headers=headers)).json()
    rows = [r for r in body["links"] if r["slug"] == link["slug"]]
    assert len(rows) == 1, body
    row = rows[0]
    assert row["state"] == "live"
    assert row["applications"] == 2
    assert row["new_candidates"] == 2 and row["existing_candidates"] == 0
    # Przegląd AI wyłączony w testach — karta „Nowi” powstaje od razu.
    assert row["in_process"] == 2
    assert row["hired"] == 0
    assert body["days"] == 30
    assert body["totals"]["applications"] == sum(
        r["applications"] for r in body["links"]
    )
    # Od początku: to samo okno, bo zgłoszenia są świeże.
    everything = (
        await api.get(
            "/api/me/career-link/results", headers=headers, params={"days": 0}
        )
    ).json()
    assert everything["days"] is None
    assert [r for r in everything["links"] if r["slug"] == link["slug"]][0][
        "applications"
    ] == 2


async def test_link_results_hide_dead_links_without_applications(api):
    _, headers, job_id = await _owner_with_job(api)
    link = await _create_job_link(api, headers, job_id)
    revoke = await api.post(
        f"/api/invite-links/{link['token']}/revoke", headers=headers
    )
    assert revoke.status_code == 204, revoke.text
    body = (await api.get("/api/me/career-link/results", headers=headers)).json()
    assert all(r["slug"] != link["slug"] for r in body["links"])


async def test_approve_refuses_internal_codes(api):
    _, headers, job_id = await _owner_with_job(api)
    resp = await _approve(
        api, headers, job_id, about="Zgłoszenie RITM0866775 dotyczy zespołu płatności."
    )
    assert resp.status_code == 422, resp.text
    codes = {f["code"] for f in resp.json()["detail"]["findings"]}
    assert codes == {"internal_code"}


async def test_public_profile_is_open_to_recruiters_outside_the_team(api):
    """Od 23.09.2026 opis publiczny czyta i poprawia każdy rekruter, także
    spoza zespołu rekrutacji („nie musisz być przypisany")."""
    _, headers, job_id = await _owner_with_job(api)
    assert (await _approve(api, headers, job_id)).status_code == 200
    _, email, password = await _seed_user("outsider")
    outsider = await _login(api, email, password)

    resp = await api.get(f"/api/jobs/{job_id}/public-profile", headers=outsider)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "approved"

    edited = await api.put(
        f"/api/jobs/{job_id}/public-profile",
        json={"about": "Treść poprawiona przez kolegę z innego zespołu."},
        headers=outsider,
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["status"] == "draft"


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
        # Bez zaznaczonej zgody na przyszłe — tylko zgoda na tę rekrutację.
        consents = (
            await db.scalars(
                select(CandidateConsent).where(CandidateConsent.candidate_id == cand.id)
            )
        ).all()
        assert [c.kind for c in consents] == ["recruitment_current"]
        consent = consents[0]
        assert consent.text_version == CONSENT_TEXT_VERSION
        assert consent.text_sha256 == CONSENT_CURRENT_TEXT_SHA256
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
        data=_form(
            slug,
            existing_email,
            city="Gdańsk",
            expected_rate_hourly="150",
            consent_future="true",
        ),
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
        consents = (
            await db.scalars(
                select(CandidateConsent).where(
                    CandidateConsent.application_submission_id == sub.id
                )
            )
        ).all()
        # Link rekrutacji: zaznaczona zgoda na przyszłe = drugi wiersz z własnym
        # skrótem treści. Stały link rekrutera („Dołącz do bazy”, decyzja Artura
        # 19.10.2026): jedyna, obowiązkowa zgoda to zgoda na przyszłe procesy.
        expected = (
            {
                "recruitment_current": CONSENT_CURRENT_TEXT_SHA256,
                "recruitment_future": CONSENT_FUTURE_TEXT_SHA256,
            }
            if link_kind == "job"
            else {"recruitment_future": CONSENT_FUTURE_TEXT_SHA256}
        )
        assert {c.kind: c.text_sha256 for c in consents} == expected
        assert all(c.candidate_id is None for c in consents)
        assert sub.raw_payload["consent"]["kinds"] == list(expected)
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
    assert (await _approve(api, headers, job_id)).status_code == 200
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


async def test_legacy_apply_link_without_approved_profile_is_404(api):
    """R10-N10-9: stary `/apply/{token}` stosuje regułę `/r/{slug}` — bez
    zatwierdzonego opisu nie pokazuje tytułu i nie przyjmuje zgłoszeń."""
    _, headers, job_id = await _owner_with_job(api)
    token = (await _create_job_link(api, headers, job_id))["token"]

    meta = await api.get(f"/api/public/apply/{token}")
    assert meta.status_code == 404
    applied = await api.post(
        f"/api/public/apply/{token}",
        data={
            "first_name": "Ola",
            "last_name": "Szkic",
            "email": f"draft-{uuid.uuid4().hex[:6]}@example.com",
            "consent": "true",
        },
        files=_cv(),
    )
    assert applied.status_code == 404

    assert (await _approve(api, headers, job_id)).status_code == 200
    approved = await api.get(f"/api/public/apply/{token}")
    assert approved.status_code == 200, approved.text


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
    # Kształt odpowiedzi jest zamknięty (biała lista) — nowe pole = świadoma
    # decyzja. Etap 6: „O mnie”, scena i slug kategorii rekrutacji.
    assert set(body) == {"recruiter", "jobs"}
    assert body["recruiter"] == {"first_name": "Marta", "slug": slug, "about": None}
    assert [j["slug"] for j in body["jobs"]] == [link["slug"]]
    assert set(body["jobs"][0]) == _RECRUITER_JOB_KEYS
    assert body["jobs"][0]["theme"] == "terminal"  # „Senior Java Developer”
    assert "Kwarcowy" not in json.dumps(body)

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

    # Własny tytuł = zmiana treści publicznej → powrót do szkicu. Od 19.10.2026
    # strona zostaje na zatwierdzonym tytule, dopóki nikt nie zatwierdzi nowego.
    put = await api.put(
        f"/api/jobs/{job_id}/public-profile",
        json={"public_title": "  Data Engineer   (Azure) "},
        headers=headers,
    )
    assert put.status_code == 200, put.text
    assert put.json()["public_title"] == "Data Engineer (Azure)"
    assert put.json()["effective_title"] == "Data Engineer (Azure)"
    assert put.json()["status"] == "draft"
    assert put.json()["live"]["title"] == "Data Engineer Platformy"
    assert put.json()["live"]["pending_changes"] is True
    page = await api.get(f"/api/public/career/r/{link['slug']}")
    assert page.status_code == 200
    assert page.json()["job"]["title"] == "Data Engineer Platformy"

    # Pusty tytuł własny = powrót do domyślnego.
    clear = await api.put(
        f"/api/jobs/{job_id}/public-profile",
        json={"public_title": ""},
        headers=headers,
    )
    assert clear.json()["public_title"] is None
    assert clear.json()["effective_title"] == "Data Engineer Platformy"


async def test_hidden_must_section_with_client_name_is_refused(api):
    """R8-N4-1: kontrola czyta także sekcję wyłączoną przełącznikiem — jej
    włączenie po zatwierdzeniu nie może ominąć sprawdzenia nazwy klienta."""
    from app.models.client import Client

    _, headers, job_id = await _owner_with_job(api)
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        client_name = (await db.get(Client, job.client_id)).name
        job.champion_profile = {
            **(job.champion_profile or {}),
            "stack": {"must": [{"name": f"Znajomość systemów {client_name}"}]},
        }
        await db.commit()
    resp = await _approve(
        api,
        headers,
        job_id,
        sections={"must": False, "nice": True, "params": True, "process": True},
    )
    assert resp.status_code == 422, resp.text
    assert {f["code"] for f in resp.json()["detail"]["findings"]} == {"client_name"}


async def test_hidden_sections_vanish_from_every_public_surface(api):
    """Runda 8 (decyzja Artura 27.09.2026): wyłączona sekcja nie trafia do
    publicznego JSON-a (z niego strona buduje grafikę OG i opis meta), na
    listę strony rekrutera ani do podglądu karty w edytorze."""
    _, headers, job_id = await _owner_with_job(api)
    link = await _create_job_link(api, headers, job_id)
    hidden = {"must": False, "nice": False, "params": False, "process": True}
    approved = await _approve(api, headers, job_id, sections=hidden)
    assert approved.status_code == 200, approved.text
    assert approved.json()["preview"]["must"] == []
    assert approved.json()["preview"]["params"]["city"] is None
    # Migawka zatwierdzenia niesie pełne pola — edytor nie widzi „zmiany”.
    assert approved.json()["approved_content_stale"] is False

    page = await api.get(f"/api/public/career/r/{link['slug']}")
    assert page.status_code == 200, page.text
    job = page.json()["job"]
    assert job["must"] == [] and job["nice"] == []
    assert job["show"] == hidden
    for key in (
        "city",
        "remote_policy",
        "onsite_days_per_week",
        "onsite_days_per_month",
        "start",
        "duration",
    ):
        assert job["params"][key] is None, key
    serialized = json.dumps(job, ensure_ascii=False)
    for leaked in ("Java 17", "Kafka", "Warszawa", "10.2026", "12+ mies."):
        assert leaked not in serialized, leaked

    from app.core.cache import cache_invalidate

    await cache_invalidate("career_board")
    board = (await api.get("/api/public/career/jobs")).json()["jobs"]
    card = next(j for j in board if j["slug"] == link["slug"])
    assert card["must"] == [] and card["nice"] == []
    assert card["city"] is None and card["remote_policy"] is None

    slug = f"hid-{uuid.uuid4().hex[:6]}"
    await api.put("/api/me/career-link", json={"slug": slug}, headers=headers)
    listed = (await api.get(f"/api/public/career/p/{slug}")).json()["jobs"]
    assert [(j["city"], j["remote_policy"]) for j in listed] == [(None, None)]

    shown = {"must": True, "nice": True, "params": True, "process": True}
    assert (await _approve(api, headers, job_id, sections=shown)).status_code == 200
    job = (await api.get(f"/api/public/career/r/{link['slug']}")).json()["job"]
    assert job["must"] == [{"name": "Java 17", "note": None}]
    assert job["nice"] == ["Kafka"]
    assert job["params"]["city"] == "Warszawa"


async def test_job_link_slug_never_carries_the_client_name(api):
    """R8-N4-2: slug powstaje z tytułu, którego nikt nie sprawdził — z nazwą
    klienta dostaje sam ``rekrutacja-…``, a slug starszego linku z klientem
    zmienia się przy zatwierdzeniu opisu."""
    unique = "".join(c for c in uuid.uuid4().hex if c.isalpha())[:6] or "abcdef"
    client_name = f"Kwarcowy Bank {unique}"
    uid, email, password = await _seed_user("slug")
    headers = await _login(api, email, password)
    job_id = await _seed_job(
        uid, client_name=client_name, title=f"Java Developer ({client_name})"
    )
    link = await _create_job_link(api, headers, job_id)
    assert link["slug"].startswith("rekrutacja-"), link["slug"]

    old_slug = f"java-developer-kwarcowy-bank-{unique}-zz11"
    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(CandidateInviteLink).where(CandidateInviteLink.slug == link["slug"])
        )
        row.slug = old_slug
        await db.commit()

    approved = await _approve(api, headers, job_id, public_title="Java Developer")
    assert approved.status_code == 200, approved.text
    assert (await api.get(f"/api/public/career/r/{old_slug}")).status_code == 404
    async with AsyncSessionLocal() as db:
        new_slug = (
            await db.execute(
                select(CandidateInviteLink.slug).where(
                    CandidateInviteLink.job_id == job_id
                )
            )
        ).scalar_one()
    assert new_slug.startswith("java-developer-") and "kwarcowy" not in new_slug
    page = await api.get(f"/api/public/career/r/{new_slug}")
    assert page.status_code == 200 and page.json()["job"]["slug"] == new_slug


async def test_client_change_after_approval_returns_to_draft(api):
    """R8-N4-4: opis sprawdzono wobec klienta z chwili zatwierdzenia."""
    from app.models.client import Client

    _, headers, job_id = await _owner_with_job(api)
    link = await _create_job_link(api, headers, job_id)
    assert (await _approve(api, headers, job_id)).status_code == 200
    assert (await api.get(f"/api/public/career/r/{link['slug']}")).status_code == 200
    async with AsyncSessionLocal() as db:
        other = Client(name=f"Inny Klient {uuid.uuid4().hex[:6]}")
        db.add(other)
        await db.flush()
        job = await db.get(Job, job_id)
        job.client_id = other.id
        await db.commit()
    assert (await api.get(f"/api/public/career/r/{link['slug']}")).status_code == 404
    profile = await api.get(f"/api/jobs/{job_id}/public-profile", headers=headers)
    assert profile.json()["status"] == "draft"
    # Ponowne zatwierdzenie przy nowym kliencie przywraca stronę.
    assert (await _approve(api, headers, job_id)).status_code == 200
    assert (await api.get(f"/api/public/career/r/{link['slug']}")).status_code == 200


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


# ── audyt 22.09 r2: linki nieaktywnych (SEC-06) i liczenie wejść (FE-N01) ──


async def _deactivate(user_id: int) -> None:
    async with AsyncSessionLocal() as db:
        user = await db.get(User, user_id)
        user.is_active = False
        await db.commit()


async def test_recruiter_link_of_inactive_owner_is_404_for_page_and_apply(api):
    uid, headers, _ = await _owner_with_job(api)
    slug = f"gone-{uuid.uuid4().hex[:6]}"
    put = await api.put("/api/me/career-link", json={"slug": slug}, headers=headers)
    assert put.status_code == 200, put.text
    assert (await api.get(f"/api/public/career/p/{slug}")).status_code == 200

    await _deactivate(uid)

    assert (await api.get(f"/api/public/career/p/{slug}")).status_code == 404
    applicant = f"gone-{uuid.uuid4().hex[:6]}@example.com"
    resp = await api.post(
        "/api/public/career/apply", data=_form(slug, applicant), files=_cv()
    )
    assert resp.status_code == 404
    async with AsyncSessionLocal() as db:
        assert (
            await db.scalar(select(Candidate).where(Candidate.email == applicant))
        ) is None


async def test_job_link_of_inactive_owner_notifies_the_job_team(api):
    uid, headers, job_id = await _owner_with_job(api)
    link = await _create_job_link(api, headers, job_id)
    assert (await _approve(api, headers, job_id)).status_code == 200
    new_recruiter, _, _ = await _seed_user("next-recruiter")
    delivery_lead, _, _ = await _seed_user("dl")
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        job.recruiter_id = new_recruiter
        job.delivery_lead_id = delivery_lead
        await db.commit()
    await _deactivate(uid)

    page = await api.get(f"/api/public/career/r/{link['slug']}")
    assert page.status_code == 200
    assert page.json()["recruiter"]["slug"] is None

    applicant = f"team-{uuid.uuid4().hex[:6]}@example.com"
    resp = await api.post(
        "/api/public/career/apply", data=_form(link["slug"], applicant), files=_cv()
    )
    assert resp.status_code == 201, resp.text
    async with AsyncSessionLocal() as db:
        cand = await db.scalar(select(Candidate).where(Candidate.email == applicant))
        recipients = set(
            (
                await db.execute(
                    select(Notification.user_id).where(
                        Notification.notification_type
                        == NotificationType.new_application,
                        Notification.related_entity_id == cand.id,
                    )
                )
            ).scalars()
        )
    assert recipients == {new_recruiter, delivery_lead}


async def test_admin_soft_delete_revokes_the_recruiter_link(
    app_client, app_auth_headers
):
    uid, email, password = await _seed_user("revoke")
    login = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    slug = f"revoke-{uuid.uuid4().hex[:6]}"
    put = await app_client.put(
        "/api/me/career-link", json={"slug": slug}, headers=headers
    )
    assert put.status_code == 200, put.text

    deleted = await app_client.delete(
        f"/api/admin/users/{uid}", headers=app_auth_headers
    )
    assert deleted.status_code == 204, deleted.text
    async with AsyncSessionLocal() as db:
        link = await db.scalar(
            select(CandidateInviteLink).where(CandidateInviteLink.slug == slug)
        )
        assert link.revoked is True


async def _visits(slug: str) -> int:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(CandidateInviteLink.visit_count).where(
                CandidateInviteLink.slug == slug
            )
        )


async def test_link_previews_and_og_images_do_not_count_as_visits(api):
    _, headers, job_id = await _owner_with_job(api)
    link = await _create_job_link(api, headers, job_id)
    assert (await _approve(api, headers, job_id)).status_code == 200
    url = f"/api/public/career/r/{link['slug']}"
    start = await _visits(link["slug"])

    for ua in (
        "LinkedInBot/1.0 (compatible; Mozilla/5.0; +http://www.linkedin.com)",
        "Slackbot-LinkExpanding 1.0 (+https://api.slack.com/robots)",
        "facebookexternalhit/1.1",
    ):
        assert (await api.get(url, headers={"User-Agent": ua})).status_code == 200
    assert (await api.get(url, headers={"x-nexus-count-visit": "0"})).status_code == 200
    assert await _visits(link["slug"]) == start

    human = "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/130 Safari/537.36"
    assert (await api.get(url, headers={"User-Agent": human})).status_code == 200
    assert await _visits(link["slug"]) == start + 1


# ── „O mnie” na stronie rekrutera (etap 6, 20.10.2026) ──────────────────────


async def _recruiter_page(api: AsyncClient, headers, **body) -> tuple[str, dict]:
    slug = body.pop("slug", None) or f"about-{uuid.uuid4().hex[:6]}"
    put = await api.put(
        "/api/me/career-link", json={"slug": slug, **body}, headers=headers
    )
    assert put.status_code == 200, put.text
    return slug, put.json()


async def test_about_is_saved_cleaned_and_shown_on_the_recruiter_page(api):
    _, headers, _ = await _owner_with_job(api)
    about = "Rekrutuję w IT\u00ad — głównie Java i chmura.\n\nOdpisuję w dwa dni."
    slug, saved = await _recruiter_page(api, headers, about=about)
    clean = "Rekrutuję w IT — głównie Java i chmura. Odpisuję w dwa dni."
    assert saved["link"]["about"] == clean

    page = (await api.get(f"/api/public/career/p/{slug}")).json()
    assert page["recruiter"]["about"] == clean

    # Sam adres bez pola „about” nie kasuje „O mnie”; pusty tekst kasuje.
    _, kept = await _recruiter_page(api, headers, slug=slug)
    assert kept["link"]["about"] == clean
    _, cleared = await _recruiter_page(api, headers, slug=slug, about="  ")
    assert cleared["link"]["about"] is None
    page = (await api.get(f"/api/public/career/p/{slug}")).json()
    assert page["recruiter"]["about"] is None


async def test_about_keeps_with_a_new_address(api):
    _, headers, _ = await _owner_with_job(api)
    await _recruiter_page(api, headers, about="Szukam ludzi do projektów w chmurze.")
    slug, moved = await _recruiter_page(api, headers)
    assert moved["link"]["slug"] == slug
    assert moved["link"]["about"] == "Szukam ludzi do projektów w chmurze."


@pytest.mark.parametrize(
    ("about", "code"),
    [
        ("Rekrutuję dla Kwarcowy Bank Hipoteczny {u}.", "client_name"),
        ("Stawki do 180 zł/h netto.", "money"),
        ("Napisz: marta@example.com albo zadzwoń.", "contact"),
        ("Jestem Marta Rekruterska{u} i rekrutuję w IT.", "person_name"),
        ("Prowadzę RITM0866775 i inne zgłoszenia.", "internal_code"),
    ],
)
async def test_about_refuses_what_the_job_profile_refuses(api, about, code):
    uid, headers, job_id = await _owner_with_job(api)
    async with AsyncSessionLocal() as db:
        user = await db.get(User, uid)
        job = await db.get(Job, job_id)
        from app.models.client import Client

        client = await db.get(Client, job.client_id)
        unique_user = user.name.removeprefix("Marta Rekruterska")
        client_suffix = client.name.removeprefix(f"{_CLIENT_NAME_BASE} ")
    text = about.format(u=unique_user if code == "person_name" else client_suffix)
    slug = f"about-{uuid.uuid4().hex[:6]}"
    resp = await api.put(
        "/api/me/career-link", json={"slug": slug, "about": text}, headers=headers
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "CAREER_ABOUT_FINDINGS"
    assert code in {f["code"] for f in detail["findings"]}
    # Odmowa niczego nie zapisuje — także adresu.
    assert (await api.get(f"/api/public/career/p/{slug}")).status_code == 404


async def test_about_longer_than_two_sentences_limit_is_refused(api):
    _, headers, _ = await _owner_with_job(api)
    resp = await api.put(
        "/api/me/career-link",
        json={"slug": f"about-{uuid.uuid4().hex[:6]}", "about": "a" * 281},
        headers=headers,
    )
    assert resp.status_code == 422
    assert "280" in resp.json()["detail"]


# ── Tablica otwartych rekrutacji (etap 6, 20.10.2026) ──────────────────────


@pytest_asyncio.fixture
async def board(api):
    """Tablica bez cache: każdy odczyt liczy od nowa (TTL 60 s w produkcji)."""
    from app.core.cache import cache_invalidate

    async def _get() -> dict:
        await cache_invalidate("career_board")
        resp = await api.get("/api/public/career/jobs")
        assert resp.status_code == 200, resp.text
        return resp.json()

    return _get


async def test_board_lists_open_approved_jobs_without_client_or_rate(api, board):
    _, headers, job_id = await _owner_with_job(api)
    link = await _create_job_link(api, headers, job_id)
    assert (await _approve(api, headers, job_id)).status_code == 200
    body = await board()
    assert set(body) == {"jobs", "cv"}
    card = next(j for j in body["jobs"] if j["slug"] == link["slug"])
    # Kształt karty jest zamknięty — nowe pole = świadoma decyzja.
    assert set(card) == {
        "slug",
        "title",
        "subtitle",
        "city",
        "remote_policy",
        "category",
        "theme",
        "recruiter_first_name",
        "must",
        "nice",
    }
    # Etap 7 (21.10.2026): podgląd sceny na tablicy buduje się z wymagań.
    assert card["must"] == ["Java 17"]
    assert card["nice"] == ["Kafka"]
    assert card["title"].startswith("Senior Java Developer")
    assert card["subtitle"] == "Rozwój platformy płatności dla sektora finansowego"
    assert card["remote_policy"] == "hybrid"
    assert card["theme"] == "terminal"
    assert card["recruiter_first_name"] == "Marta"

    serialized = json.dumps(card, ensure_ascii=False)
    for forbidden in (_CLIENT_NAME_BASE, "175", "180", "zł", "sekretny", "Rekruterska"):
        assert forbidden not in serialized, forbidden
    # Odczyt tablicy nie jest wejściem na stronę rekrutacji.
    assert await _visits(link["slug"]) == 0


async def test_board_skips_unapproved_and_closed_jobs(api, board):
    uid, headers, job_id = await _owner_with_job(api)
    draft_job = await _seed_job(uid)
    await api.put(
        f"/api/jobs/{draft_job}/public-profile",
        json={"subtitle": "Szkic", "about": "Jeszcze nie"},
        headers=headers,
    )
    assert (await _approve(api, headers, job_id)).status_code == 200
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        job.status = JobStatus.closed
        await db.commit()

    body = await board()
    async with AsyncSessionLocal() as db:
        slugs = set(
            (
                await db.scalars(
                    select(CandidateInviteLink.slug).where(
                        CandidateInviteLink.job_id.in_([job_id, draft_job])
                    )
                )
            ).all()
        )
    assert not slugs & {j["slug"] for j in body["jobs"]}


async def test_board_creates_the_lead_link_once(api, board):
    uid, headers, job_id = await _owner_with_job(api)
    assert (await _approve(api, headers, job_id)).status_code == 200  # bez linku

    first = await board()
    second = await board()
    async with AsyncSessionLocal() as db:
        links = (
            await db.scalars(
                select(CandidateInviteLink).where(CandidateInviteLink.job_id == job_id)
            )
        ).all()
    assert len(links) == 1
    created = links[0]
    assert created.created_by == uid
    assert created.kind == "job"
    assert created.expires_at is None
    assert created.label == "Tablica kariery"
    from app.models.recruitment_priority import RecruitmentPriorityAuditEvent

    async with AsyncSessionLocal() as db:
        audit = (
            await db.scalars(
                select(RecruitmentPriorityAuditEvent).where(
                    RecruitmentPriorityAuditEvent.event_type == "invite_link_created",
                    RecruitmentPriorityAuditEvent.job_id == job_id,
                )
            )
        ).all()
    assert [a.payload["via"] for a in audit] == ["career_board"]
    for body in (first, second):
        assert created.slug in {j["slug"] for j in body["jobs"]}

    # Zgłoszenie z karty = link prowadzącego (blokada 12 h, „Z linków”, dzwonek).
    resp = await api.post(
        "/api/public/career/apply",
        data=_form(created.slug, f"tablica-{uuid.uuid4().hex[:8]}@example.com"),
        files=_cv(),
    )
    assert resp.status_code == 201, resp.text


async def test_board_follows_a_new_lead_and_respects_a_revoked_link(api, board):
    uid, headers, job_id = await _owner_with_job(api)
    old_link = await _create_job_link(api, headers, job_id)
    assert (await _approve(api, headers, job_id)).status_code == 200
    new_lead, _, _ = await _seed_user("lead2")
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        job.recruiter_id = new_lead
        await db.commit()

    body = await board()
    async with AsyncSessionLocal() as db:
        lead_link = await db.scalar(
            select(CandidateInviteLink).where(
                CandidateInviteLink.job_id == job_id,
                CandidateInviteLink.created_by == new_lead,
            )
        )
    assert lead_link is not None
    slugs = {j["slug"] for j in body["jobs"]}
    assert lead_link.slug in slugs and old_link["slug"] not in slugs

    # Prowadzący wyłączył swój link: nowego nie dostaje, karta bierze link
    # innej osoby, a bez żadnego aktywnego linku rekrutacji nie ma na tablicy.
    async with AsyncSessionLocal() as db:
        row = await db.get(CandidateInviteLink, lead_link.token)
        row.revoked = True
        await db.commit()
    slugs = {j["slug"] for j in (await board())["jobs"]}
    assert old_link["slug"] in slugs and lead_link.slug not in slugs

    async with AsyncSessionLocal() as db:
        for row in (
            await db.scalars(
                select(CandidateInviteLink).where(CandidateInviteLink.job_id == job_id)
            )
        ).all():
            row.revoked = True
        await db.commit()
    body = await board()
    async with AsyncSessionLocal() as db:
        count = len(
            (
                await db.scalars(
                    select(CandidateInviteLink).where(
                        CandidateInviteLink.job_id == job_id
                    )
                )
            ).all()
        )
    assert count == 2
    assert not {old_link["slug"], lead_link.slug} & {j["slug"] for j in body["jobs"]}


async def test_board_skips_a_broken_job_instead_of_failing(api, board, monkeypatch):
    _, headers, job_id = await _owner_with_job(api)
    link = await _create_job_link(api, headers, job_id)
    assert (await _approve(api, headers, job_id)).status_code == 200
    from app.services import job_public_profile as jpp

    real = jpp.visible_params

    def broken(job, sections):
        if job.id == job_id:
            raise ValueError("popsuta migawka")
        return real(job, sections)

    monkeypatch.setattr(jpp, "visible_params", broken)
    body = await board()
    assert link["slug"] not in {j["slug"] for j in body["jobs"]}


async def test_board_without_lead_takes_the_newest_active_link(api, board):
    uid, headers, job_id = await _owner_with_job(api)
    older = await _create_job_link(api, headers, job_id)
    newer = await _create_job_link(api, headers, job_id)
    assert (await _approve(api, headers, job_id)).status_code == 200
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        job.recruiter_id = None
        await db.commit()

    slugs = {j["slug"] for j in (await board())["jobs"]}
    assert newer["slug"] in slugs and older["slug"] not in slugs


async def test_board_without_lead_and_live_link_gets_a_head_of_recruitment_link(
    api, board
):
    """Decyzja Artura 21.10.2026: wygasły link i brak prowadzącego nie zdejmują
    rekrutacji z tablicy — link zakłada się na Head of Recruitment."""
    from datetime import datetime, timedelta, timezone

    _, headers, job_id = await _owner_with_job(api)
    expired = await _create_job_link(api, headers, job_id)
    assert (await _approve(api, headers, job_id)).status_code == 200
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=f"career-hor-{uuid.uuid4().hex[:8]}@example.com",
                password_hash=hash_password("T3st_hor!Car"),
                name="Olga Rekrutacyjna",
                role=UserRole.head_of_recruitment,
                is_active=True,
            )
        )
        job = await db.get(Job, job_id)
        job.recruiter_id = None
        row = await db.scalar(
            select(CandidateInviteLink).where(
                CandidateInviteLink.slug == expired["slug"]
            )
        )
        row.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        await db.commit()

    cards = {j["slug"] for j in (await board())["jobs"]}
    async with AsyncSessionLocal() as db:
        links = (
            await db.scalars(
                select(CandidateInviteLink).where(
                    CandidateInviteLink.job_id == job_id,
                    CandidateInviteLink.slug.in_(cards),
                )
            )
        ).all()
        assert len(links) == 1
        owner = await db.get(User, links[0].created_by)
    assert links[0].slug != expired["slug"] and links[0].expires_at is None
    assert owner.is_active and owner.has_role(UserRole.head_of_recruitment)
    # Drugi odczyt nie zakłada kolejnego linku.
    await board()
    async with AsyncSessionLocal() as db:
        count = len(
            (
                await db.scalars(
                    select(CandidateInviteLink).where(
                        CandidateInviteLink.job_id == job_id
                    )
                )
            ).all()
        )
    assert count == 2


async def test_board_cv_link_belongs_to_head_of_recruitment(api, board):
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=f"career-hor-{uuid.uuid4().hex[:8]}@example.com",
                password_hash=hash_password("T3st_hor!Car"),
                name="Olga Rekrutacyjna",
                role=UserRole.head_of_recruitment,
                is_active=True,
            )
        )
        await db.commit()

    cv = (await board())["cv"]
    assert set(cv) == {"slug", "first_name"}
    slug = cv["slug"]
    async with AsyncSessionLocal() as db:
        link = await db.scalar(
            select(CandidateInviteLink).where(CandidateInviteLink.slug == slug)
        )
        owner = await db.get(User, link.created_by)
    assert link.kind == "recruiter" and not link.revoked
    assert owner.is_active and owner.has_role(UserRole.head_of_recruitment)
    assert cv["first_name"] == owner.name.split(" ")[0]

    email = f"zostaw-cv-{uuid.uuid4().hex[:8]}@example.com"
    resp = await api.post(
        "/api/public/career/apply", data=_form(slug, email), files=_cv()
    )
    assert resp.status_code == 201, resp.text
    async with AsyncSessionLocal() as db:
        candidate = await db.scalar(select(Candidate).where(Candidate.email == email))
        assert candidate is not None
        assert candidate.created_by == owner.id
        stages = (
            await db.scalars(
                select(CandidateStage).where(
                    CandidateStage.candidate_id == candidate.id
                )
            )
        ).all()
        assert stages == []


async def test_pick_cv_owner_rules():
    from datetime import datetime, timezone

    from app.services.career_board import pick_cv_owner

    now = datetime.now(timezone.utc)

    def link(owner: int, slug: str, *, revoked: bool = False) -> CandidateInviteLink:
        return CandidateInviteLink(
            token=slug, created_by=owner, kind="recruiter", slug=slug, revoked=revoked
        )

    # Pierwszy HoR z aktywnym linkiem wygrywa, nawet gdy nie ma najniższego id.
    assert pick_cv_owner([1, 2], [link(2, "b")], now) == ("b", None)
    # Nikt nie ma linku — zakładamy go pierwszemu.
    assert pick_cv_owner([3, 4], [], now) == (None, 3)
    # Wyłączony link to decyzja osoby: następny HoR bez linku, a gdy go nie ma — nic.
    assert pick_cv_owner([5, 6], [link(5, "e", revoked=True)], now) == (None, 6)
    assert pick_cv_owner([7], [link(7, "g", revoked=True)], now) == (None, None)
    assert pick_cv_owner([], [], now) == (None, None)


async def test_pick_board_link_rules():
    from datetime import datetime, timedelta, timezone

    from app.services.career_board import _pick_link

    now = datetime.now(timezone.utc)

    def link(owner: int, slug: str, *, revoked=False, expired=False):
        return CandidateInviteLink(
            token=slug,
            created_by=owner,
            kind="job",
            slug=slug,
            job_id=1,
            revoked=revoked,
            expires_at=now - timedelta(days=1) if expired else None,
        )

    other_new, lead_old = link(2, "other-new"), link(1, "lead-old")
    assert _pick_link([other_new, lead_old], 1, now) == (lead_old, None)
    assert _pick_link([other_new], 1, now) == (None, 1)
    lead_off = link(1, "lead-off", revoked=True)
    assert _pick_link([lead_off, other_new], 1, now) == (other_new, None)
    assert _pick_link([lead_off], 1, now) == (None, None)
    # Wygasły link prowadzącego to nie „wyłączył” — dostaje nowy (decyzja
    # Artura 21.10.2026: tablica nie gubi rekrutacji przez wygasły link).
    lead_expired = link(1, "x", expired=True)
    assert _pick_link([lead_expired], 1, now) == (None, 1)
    assert _pick_link([lead_expired, other_new], 1, now) == (None, 1)
    assert _pick_link([other_new, lead_old], None, now) == (other_new, None)
    # Bez prowadzącego i bez aktywnego linku — link Head of Recruitment.
    assert _pick_link([], None, now) == (None, None)
    assert _pick_link([], None, now, fallback_id=9) == (None, 9)
    assert _pick_link([link(2, "old", expired=True)], None, now, fallback_id=9) == (
        None,
        9,
    )
    assert _pick_link([other_new], None, now, fallback_id=9) == (other_new, None)
    hor_off = link(9, "hor-off", revoked=True)
    assert _pick_link([hor_off], None, now, fallback_id=9) == (None, None)


async def test_every_link_of_a_job_points_google_to_one_canonical_slug(api, board):
    """Audyt 21.10.2026: kilka linków jednej rekrutacji (każdy rekruter swój,
    link tablicy) to w Google jedna oferta — canonical i identyfikator JobPosting
    biorą slug linku z tablicy, a nie slug otwartej strony."""
    _, headers, job_id = await _owner_with_job(api)
    first = await _create_job_link(api, headers, job_id)
    second = await _create_job_link(api, headers, job_id)
    assert (await _approve(api, headers, job_id)).status_code == 200
    card = next(
        j
        for j in (await board())["jobs"]
        if j["slug"] in {first["slug"], second["slug"]}
    )
    for link in (first, second):
        page = await api.get(f"/api/public/career/r/{link['slug']}")
        assert page.status_code == 200, page.text
        assert page.json()["canonical_slug"] == card["slug"]


async def test_board_skips_the_link_of_a_deactivated_owner_and_gets_a_hor_link(
    api, board
):
    """Decyzja Artura 22.10.2026 (audyt F62): link osoby z wyłączonym kontem
    nie stoi na tablicy ani w canonical — rekrutacja dostaje link Head of
    Recruitment jak rekrutacja bez prowadzącego."""
    uid, headers, job_id = await _owner_with_job(api)
    gone = await _create_job_link(api, headers, job_id)
    assert (await _approve(api, headers, job_id)).status_code == 200
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=f"career-hor-{uuid.uuid4().hex[:8]}@example.com",
                password_hash=hash_password("T3st_hor!Car"),
                name="Olga Rekrutacyjna",
                role=UserRole.head_of_recruitment,
                is_active=True,
            )
        )
        await db.commit()
    await _deactivate(uid)

    cards = (await board())["jobs"]
    assert gone["slug"] not in {card["slug"] for card in cards}
    async with AsyncSessionLocal() as db:
        link = await db.scalar(
            select(CandidateInviteLink).where(
                CandidateInviteLink.job_id == job_id,
                CandidateInviteLink.slug.in_([card["slug"] for card in cards]),
            )
        )
        assert link is not None
        owner = await db.get(User, link.created_by)
    assert owner.is_active and owner.has_role(UserRole.head_of_recruitment)

    # Strona pod starym linkiem dalej działa, ale canonical wskazuje link HoR.
    page = await api.get(f"/api/public/career/r/{gone['slug']}")
    assert page.status_code == 200
    assert page.json()["canonical_slug"] == link.slug


async def test_links_of_inactive_owners_are_dropped_before_picking():
    from datetime import datetime, timezone

    from app.services.career_board import _links_of_active_owners, _pick_link

    now = datetime.now(timezone.utc)
    gone = CandidateInviteLink(created_by=7, slug="gone", revoked=False)
    links = _links_of_active_owners([gone], active_ids={9})
    assert links == []
    # Bez prowadzącego i bez żywego linku — link zakłada Head of Recruitment.
    assert _pick_link(links, None, now, fallback_id=9) == (None, 9)
