"""JustJoin.IT przez API z okna „Ogłoszenie” (03.11.2026) — z bazą, bez sieci.

Portal podmieniony na atrapę adaptera. Pilnuje:

- flaga wyłączona = okno bez zmian, zlecenia nie ma;
- publikuje DL rekrutacji, Head of Recruitment albo admin, rekruter nie;
- na portal idzie treść zakładki JustJoin.IT, nie opis publiczny;
- bez strony kariery, ze starą wersją albo ze znaleziskiem blokującym — odmowa;
- ogłoszenie oznaczone ręcznie nie kupuje drugiego kredytu;
- sukces workera zapisuje „gdzie wisi”, a zamknięcie je zdejmuje;
- zmiana treści idzie aktualizacją, nie nową publikacją.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, update

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.app_setting import AppSetting
from app.models.job_ad_publication import JobAdPublication
from app.models.job_posting import JobPosting, Portal, PostingStatus
from app.models.user import UserRole
from app.services import job_portals
from app.services.job_ad import fixed_blocks
from app.services.job_portals.base import PortalGone, PortalResult
from app.services.job_portals.jjit import JjitAdapter
from app.services.job_portals.service import (
    close_live_postings,
    process_one,
    sync_remote_states,
)
from tests.test_career_links_api import _login
from tests.test_job_ad_pracuj_mail_api import _job_with_lead
from tests.test_job_ads_api import _client_name, _seed_role_user

pytestmark = pytest.mark.asyncio

OPTIONS = {
    "category": "java",
    "experience_level": "senior",
    "working_time": "full_time",
    "workplace_type": "remote",
    "office_days": None,
    "city": "Warszawa",
    "salary": None,
}
TECH = [
    {"name": "Java", "level": "critical"},
    {"name": "Kafka", "level": "must"},
    {"name": "Kubernetes", "level": "nice"},
]
AD_URL = "https://justjoin.it/job-offer/senior-java-1"


class FakeJjit(JjitAdapter):
    calls: list[tuple[str, object]] = []
    gone = False

    async def publish(self, content):
        FakeJjit.calls.append(("publish", content))
        return PortalResult(external_id="ad-1", url=AD_URL)

    async def update(self, external_id, content):
        FakeJjit.calls.append(("update", content))
        return PortalResult(external_id=external_id, url=AD_URL)

    async def unpublish(self, external_id, *, external_ref=None):
        FakeJjit.calls.append(("close", external_id))

    async def status(self, external_id):
        if FakeJjit.gone:
            raise PortalGone("Ogłoszenia nie ma.")
        return {"state": "published"}


@pytest.fixture
def jjit_ready(monkeypatch):
    monkeypatch.setattr(settings, "PORTAL_JJIT_ENABLED", True)
    monkeypatch.setattr(settings, "JJIT_STATIC_ACCESS_TOKEN", "klucz-testowy")
    monkeypatch.setitem(job_portals.ADAPTERS, Portal.justjoinit, FakeJjit)
    FakeJjit.calls = []
    FakeJjit.gone = False


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


@pytest_asyncio.fixture(autouse=True)
async def _default_fixed_blocks():
    yield
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(AppSetting).where(AppSetting.key == fixed_blocks.BLOCKS_KEY)
        )
        await db.commit()


def _url(job_id: int) -> str:
    return f"/api/jobs/{job_id}/portal-ad/jjit"


def _mark_url(job_id: int) -> str:
    return f"/api/jobs/{job_id}/portal-ad/publications/jjit"


async def _state(api: AsyncClient, headers, job_id: int) -> dict:
    resp = await api.get(f"/api/jobs/{job_id}/portal-ad", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _edit(api: AsyncClient, headers, job_id: int, **content) -> dict:
    """Zapis poprawki z wersją z ekranu; technologie zawsze te same."""
    ad = (await _state(api, headers, job_id))["ad"]
    resp = await api.put(
        f"/api/jobs/{job_id}/portal-ad",
        json={
            "content": {**ad["content"], **content},
            "tech": TECH,
            "expected_updated_at": ad["updated_at"],
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _ready_job(api: AsyncClient, monkeypatch):
    """Ogłoszenie z technologiami i stroną kariery; (rekruter, DL, id DL-a, job)."""
    recruiter, lead, lead_id, job_id = await _job_with_lead(api, monkeypatch)
    await _edit(api, recruiter, job_id)
    published = await api.post(
        f"/api/jobs/{job_id}/portal-ad/career", json={}, headers=recruiter
    )
    assert published.status_code == 200, published.text
    return recruiter, lead, lead_id, job_id


async def _publish(api: AsyncClient, headers, job_id: int, **body):
    version = (await _state(api, headers, job_id))["ad"]["updated_at"]
    return await api.post(
        _url(job_id),
        json={"options": OPTIONS, "expected_updated_at": version, **body},
        headers=headers,
    )


async def _posting(job_id: int) -> JobPosting | None:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(JobPosting)
            .where(JobPosting.job_id == job_id)
            .order_by(JobPosting.id.desc())
        )


async def _process(job_id: int) -> None:
    await process_one((await _posting(job_id)).id)


async def _publication(job_id: int) -> JobAdPublication | None:
    async with AsyncSessionLocal() as db:
        return await db.get(JobAdPublication, (job_id, "jjit"))


async def test_flag_off_leaves_the_window_alone(api, monkeypatch):
    monkeypatch.setattr(settings, "PORTAL_JJIT_ENABLED", False)
    _recruiter, lead, _lead_id, job_id = await _ready_job(api, monkeypatch)
    assert (await _state(api, lead, job_id))["jjit_api"] is None
    resp = await _publish(api, lead, job_id)
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "portal_not_configured"
    assert await _posting(job_id) is None


async def test_recruiter_may_not_publish_but_lead_and_hor_may(
    api, monkeypatch, jjit_ready
):
    recruiter, lead, _lead_id, job_id = await _ready_job(api, monkeypatch)
    state = await _state(api, recruiter, job_id)
    assert state["jjit_api"]["ready"] is True
    assert state["jjit_api"]["status"] is None
    assert (await _publish(api, recruiter, job_id)).status_code == 403
    assert await _posting(job_id) is None

    hor = await _login(api, *await _seed_role_user(UserRole.head_of_recruitment))
    resp = await _publish(api, hor, job_id)
    assert resp.status_code == 200, resp.text
    assert resp.json()["jjit_api"]["status"] == "publishing"
    # Drugie kliknięcie w trakcie wysyłki nie tworzy drugiego zlecenia.
    first = (await _posting(job_id)).id
    assert (await _publish(api, lead, job_id)).status_code == 200
    assert (await _posting(job_id)).id == first


async def test_older_section_routes_keep_the_same_rule_for_jjit(
    api, monkeypatch, jjit_ready
):
    recruiter, lead, _lead_id, job_id = await _ready_job(api, monkeypatch)
    base = f"/api/jobs/{job_id}/portals/justjoinit"
    body = {"options": OPTIONS}
    assert (
        await api.post(f"{base}/publish", json=body, headers=recruiter)
    ).status_code == 403
    assert await _posting(job_id) is None
    assert (
        await api.post(f"{base}/publish", json=body, headers=lead)
    ).status_code == 200
    assert (await api.post(f"{base}/unpublish", headers=recruiter)).status_code == 403
    assert (
        await api.patch(f"{base}/options", json=body, headers=recruiter)
    ).status_code == 403
    assert (await api.post(f"{base}/unpublish", headers=lead)).status_code == 200


async def test_portal_gets_the_tab_text_and_the_window_learns_where_it_hangs(
    api, monkeypatch, jjit_ready
):
    _recruiter, lead, lead_id, job_id = await _ready_job(api, monkeypatch)
    before = await _state(api, lead, job_id)
    assert (await _publish(api, lead, job_id)).status_code == 200
    await _process(job_id)

    action, content = FakeJjit.calls[0]
    assert action == "publish"
    assert content.job["body_html"] == before["rendered"]["jjit"]["body_html"]
    assert content.title == before["rendered"]["title"]
    assert [item["name"] for item in content.job["must"]] == ["Java", "Kafka"]
    assert content.job["nice"] == ["Kubernetes"]
    assert f"nexus-job-{job_id}" in content.apply_url

    row = await _publication(job_id)
    assert row.url == AD_URL
    assert row.published_by == lead_id
    after = await _state(api, lead, job_id)
    assert after["jjit_api"]["status"] == "published"
    published = next(p for p in after["publications"] if p["portal"] == "jjit")
    assert published["outdated"] is False
    channels = {c["channel"]: c["state"] for c in after["reminders"]["channels"]}
    assert channels["jjit"] != "missing"


async def test_portal_url_outside_its_domain_is_not_shown_as_a_link(
    api, monkeypatch, jjit_ready
):
    _recruiter, lead, _lead_id, job_id = await _ready_job(api, monkeypatch)

    async def foreign(self, content):
        return PortalResult(external_id="ad-1", url="https://obca.strona/x")

    monkeypatch.setattr(FakeJjit, "publish", foreign)
    assert (await _publish(api, lead, job_id)).status_code == 200
    await _process(job_id)
    row = await _publication(job_id)
    assert row is not None and row.removed_at is None
    assert row.url is None


async def test_needs_a_current_career_page(api, monkeypatch, jjit_ready):
    monkeypatch.setattr(settings, "JJIT_APPLY_EMAIL", "")
    recruiter, lead, _lead_id, job_id = await _job_with_lead(api, monkeypatch)
    await _edit(api, recruiter, job_id)
    resp = await _publish(api, lead, job_id)
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "career_not_live"

    await api.post(f"/api/jobs/{job_id}/portal-ad/career", json={}, headers=recruiter)
    await _edit(api, recruiter, job_id, about="Inny opis projektu po publikacji.")
    resp = await _publish(api, lead, job_id)
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "career_not_live"
    assert await _posting(job_id) is None


async def test_portal_form_needs_no_career_page(api, monkeypatch, jjit_ready):
    """06.11.2026: przy formularzu JJIT kandydat nie widzi strony kariery."""
    monkeypatch.setattr(settings, "JJIT_APPLY_EMAIL", "justjoin.it@example.com")
    recruiter, lead, _lead_id, job_id = await _job_with_lead(api, monkeypatch)
    await _edit(api, recruiter, job_id)

    resp = await _publish(api, lead, job_id)

    assert resp.status_code == 200, resp.text
    assert await _posting(job_id) is not None
    await _process(job_id)
    published = [c for kind, c in FakeJjit.calls if kind == "publish"]
    assert len(published) == 1
    assert published[0].apply_url == ""
    row = await _publication(job_id)
    assert row is not None and row.url == AD_URL and row.removed_at is None


async def test_refuses_stale_version_and_blocked_text(api, monkeypatch, jjit_ready):
    recruiter, lead, _lead_id, job_id = await _ready_job(api, monkeypatch)
    stale = await _publish(
        api,
        lead,
        job_id,
        expected_updated_at=datetime(2020, 1, 1, tzinfo=timezone.utc).isoformat(),
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "job_ad_changed"

    await _edit(
        api, recruiter, job_id, about=f"System klienta {await _client_name(job_id)}."
    )
    blocked = await _publish(api, lead, job_id)
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "job_ad_blocked"
    assert await _posting(job_id) is None


async def test_text_blocked_after_the_click_never_leaves(api, monkeypatch, jjit_ready):
    recruiter, lead, _lead_id, job_id = await _ready_job(api, monkeypatch)
    assert (await _publish(api, lead, job_id)).status_code == 200
    await _edit(
        api, recruiter, job_id, about=f"System klienta {await _client_name(job_id)}."
    )
    await _process(job_id)
    assert FakeJjit.calls == []
    posting = await _posting(job_id)
    assert posting.status == PostingStatus.failed
    assert "fragmenty" in posting.last_error
    assert await _publication(job_id) is None


async def test_hand_marked_ad_does_not_buy_a_second_credit(
    api, monkeypatch, jjit_ready
):
    recruiter, lead, _lead_id, job_id = await _ready_job(api, monkeypatch)
    marked = await api.put(_mark_url(job_id), json={"url": AD_URL}, headers=recruiter)
    assert marked.status_code == 200, marked.text
    resp = await _publish(api, lead, job_id)
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "ad_marked_published"
    assert await _posting(job_id) is None

    # Po „Zdjęte z portalu” publikacja jest znów możliwa.
    assert (await api.delete(_mark_url(job_id), headers=recruiter)).status_code == 200
    assert (await _publish(api, lead, job_id)).status_code == 200


async def test_hand_marking_is_refused_while_the_api_holds_the_ad(
    api, monkeypatch, jjit_ready
):
    recruiter, lead, _lead_id, job_id = await _ready_job(api, monkeypatch)
    assert (await _publish(api, lead, job_id)).status_code == 200
    resp = await api.put(_mark_url(job_id), json={"url": AD_URL}, headers=recruiter)
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "jjit_api_live"


async def test_late_cleanup_does_not_erase_a_hand_mark(api, monkeypatch, jjit_ready):
    """Sprzątanie po niepewnej publikacji nie wie nic o ogłoszeniu wklejonym ręcznie.

    Zdjęcie oznaczenia pozwoliłoby kupić drugi kredyt przy wiszącym pierwszym.
    """
    recruiter, lead, _lead_id, job_id = await _ready_job(api, monkeypatch)
    assert (await _publish(api, lead, job_id)).status_code == 200
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(JobPosting)
            .where(JobPosting.job_id == job_id)
            .values(
                status=PostingStatus.failed,
                pending_action="close",
                next_attempt_at=None,
            )
        )
        await db.commit()
    marked = await api.put(_mark_url(job_id), json={"url": AD_URL}, headers=recruiter)
    assert marked.status_code == 200, marked.text

    await _process(job_id)
    assert FakeJjit.calls[-1][0] == "close"
    assert (await _publication(job_id)).removed_at is None
    resp = await _publish(api, lead, job_id)
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "ad_marked_published"


async def test_flag_off_does_not_let_a_recruiter_close_a_paid_ad(
    api, monkeypatch, jjit_ready
):
    recruiter, lead, _lead_id, job_id = await _ready_job(api, monkeypatch)
    assert (await _publish(api, lead, job_id)).status_code == 200
    await _process(job_id)
    monkeypatch.setattr(settings, "PORTAL_JJIT_ENABLED", False)

    base = f"/api/jobs/{job_id}/portals/justjoinit"
    assert (await api.post(f"{base}/unpublish", headers=recruiter)).status_code == 403
    assert (
        await api.patch(f"{base}/options", json={"options": OPTIONS}, headers=recruiter)
    ).status_code == 403
    assert (await _posting(job_id)).pending_action is None
    # Zamykanie działa dalej: flaga blokuje tylko nowe publikacje.
    assert (await api.post(f"{base}/unpublish", headers=lead)).status_code == 200


async def test_changed_text_goes_as_an_update_not_a_new_credit(
    api, monkeypatch, jjit_ready
):
    recruiter, lead, _lead_id, job_id = await _ready_job(api, monkeypatch)
    assert (await _publish(api, lead, job_id)).status_code == 200
    await _process(job_id)

    await _edit(api, recruiter, job_id, about="Nowy opis projektu.")
    state = await _state(api, lead, job_id)
    assert next(p for p in state["publications"] if p["portal"] == "jjit")["outdated"]
    await api.post(f"/api/jobs/{job_id}/portal-ad/career", json={}, headers=recruiter)
    # Aktualizacja strony kariery sama kolejkuje aktualizację portalu.
    assert (await _posting(job_id)).pending_action == "update"
    await _process(job_id)
    assert [call[0] for call in FakeJjit.calls] == ["publish", "update"]
    assert "Nowy opis projektu." in FakeJjit.calls[1][1].job["body_html"]
    state = await _state(api, lead, job_id)
    assert not next(p for p in state["publications"] if p["portal"] == "jjit")[
        "outdated"
    ]
    # Przycisk w oknie: bez ustawień zostają te zapisane przy publikacji.
    version = state["ad"]["updated_at"]
    resp = await api.post(
        _url(job_id), json={"expected_updated_at": version}, headers=lead
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["jjit_api"]["pending_action"] == "update"
    assert (await _posting(job_id)).options["category"] == "java"


async def test_taking_down_goes_through_the_portal_for_the_lead_only(
    api, monkeypatch, jjit_ready
):
    recruiter, lead, _lead_id, job_id = await _ready_job(api, monkeypatch)
    assert (await _publish(api, lead, job_id)).status_code == 200
    await _process(job_id)

    assert (await api.delete(_mark_url(job_id), headers=recruiter)).status_code == 403
    resp = await api.delete(_mark_url(job_id), headers=lead)
    assert resp.status_code == 200, resp.text
    assert resp.json()["jjit_api"]["pending_action"] == "close"
    # Do odpowiedzi portalu ogłoszenie dalej wisi.
    assert (await _publication(job_id)).removed_at is None

    await _process(job_id)
    assert FakeJjit.calls[-1][0] == "close"
    assert (await _publication(job_id)).removed_at is not None


async def test_closing_the_recruitment_takes_the_ad_down(api, monkeypatch, jjit_ready):
    _recruiter, lead, _lead_id, job_id = await _ready_job(api, monkeypatch)
    assert (await _publish(api, lead, job_id)).status_code == 200
    await _process(job_id)
    async with AsyncSessionLocal() as db:
        assert await close_live_postings(db, job_id) == 1
        await db.commit()
    await _process(job_id)
    assert (await _publication(job_id)).removed_at is not None


async def test_ad_gone_from_the_portal_stops_hanging_in_the_window(
    api, monkeypatch, jjit_ready
):
    _recruiter, lead, _lead_id, job_id = await _ready_job(api, monkeypatch)
    assert (await _publish(api, lead, job_id)).status_code == 200
    await _process(job_id)
    FakeJjit.gone = True
    monkeypatch.setattr(settings, "JOB_PORTAL_STATUS_SYNC_HOURS", 1)
    async with AsyncSessionLocal() as db:
        posting = await db.get(JobPosting, (await _posting(job_id)).id)
        posting.last_synced_at = None
        await db.commit()
    await sync_remote_states(limit=200)
    assert (await _posting(job_id)).status == PostingStatus.removed
    assert (await _publication(job_id)).removed_at is not None
