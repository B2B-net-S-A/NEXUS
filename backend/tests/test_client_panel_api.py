"""Panel klienta przez API: bramki, wyciek pól, zapisy, terminy. Dane fikcyjne."""

from __future__ import annotations

import io
import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from docx import Document
from httpx import AsyncClient
from sqlalchemy import func, select

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token, hash_password
from app.models.candidate import Candidate, CandidateStatus
from app.models.candidate_document import CandidateDocument, CandidateDocumentKind
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.client import Client
from app.models.client_interview_slot_request import ClientInterviewSlotRequest
from app.models.client_panel import (
    ClientPanel,
    ClientPanelRequest,
    ClientPanelView,
)
from app.models.contact import Contact
from app.models.contract import RateUnit
from app.models.job import Job, JobStatus, RemotePolicy
from app.models.note import Note
from app.models.notification import Notification, NotificationType
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from app.services import client_panel as service
from app.services import client_panel_requests as requests_service

_CV = """<article class="cv"><h1>Programista – Anna Przykładowa</h1>
<h2 data-cv-section="why_points">DLACZEGO NASZ KANDYDAT?</h2><ul><li>Zna Gerrit</li></ul>
<h2 data-cv-section="skills">UMIEJĘTNOŚCI</h2><p class="skill">Python, Linux</p>
<h2 data-cv-section="experience">DOŚWIADCZENIE</h2>
<div class="job"><p data-cv-section="role"><b>Inżynier</b> 02.2020 - obecnie</p>
<p data-cv-section="employer">Firma Testowa · IT</p>
<ul><li>Rozwijał kod w Python według DDD</li></ul></div></article>"""

_PRIVATE_EMAIL = "prywatny-adres-kandydata@example.com"
_PRIVATE_PHONE = "+48 500 111 222"
_PRIVATE_NOTE = "Notatka wewnętrzna: oczekuje dużo więcej"
_FORBIDDEN_KEYS = (
    "email",
    "phone",
    "expected_rate",
    "rate_from",
    "rate_latest",
    "notes",
    "note",
    "champion",
    "candidate_id",
    "budget",
    "working_title",
    "screening",
    "user_id",
    "delivery_lead_id",
    "recruiter_id",
    "created_by",
    "job_id",
    "client_id",
    "linkedin",
    "cv_extracted_data",
    "warnings",
    "ip_hash",
)


async def _user(role: UserRole) -> tuple[int, dict[str, str]]:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"panel-{role.value}-{tag}@example.com",
            password_hash=hash_password(f"Pan3l_{tag}!pw"),
            name=f"Osoba {role.value} {tag}",
            role=role,
            roles=[role.value],
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.commit()
        uid = user.id
    token = create_access_token(uid, role.value, roles=[role.value])
    return uid, {"Authorization": f"Bearer {token}"}


async def _candidate(
    db,
    *,
    job_id: int,
    actor: int,
    stage: PipelineStage = PipelineStage.cv_sent,
    html: str = _CV,
    name: str = "Anna",
    template: str | None = None,
    sent: bool = True,
) -> int:
    """Osoba z CV na wierszu sprzed wysyłki i etapem bieżącym ``stage``."""
    tag = uuid.uuid4().hex[:6]
    candidate = Candidate(
        name=name,
        lastname=f"Przykładowa{tag}",
        email=f"{tag}-{_PRIVATE_EMAIL}",
        phone=_PRIVATE_PHONE,
        status=CandidateStatus.active,
        city="Poznań",
        expected_rate_hourly=Decimal("987.65"),
    )
    db.add(candidate)
    await db.flush()
    base = datetime.now(timezone.utc) - timedelta(days=10)
    verified = CandidateStage(
        candidate_id=candidate.id,
        job_id=job_id,
        stage=PipelineStage.verified,
        moved_by=actor,
        moved_at=base,
        expected_rate_value=Decimal("987.65"),
    )
    db.add(verified)
    await db.flush()
    if html:
        db.add(
            CandidateStageCV(
                candidate_stage_id=verified.id,
                candidate_id=candidate.id,
                job_id=job_id,
                branded_status="draft",
                branded_draft_html=html,
                branded_template=template,
                branded_docx_filename=f"CV_{name}.docx",
                branded_language="pl",
            )
        )
    moved = base
    if sent:
        moved = base + timedelta(days=1)
        db.add(
            CandidateStage(
                candidate_id=candidate.id,
                job_id=job_id,
                stage=PipelineStage.cv_sent,
                moved_by=actor,
                moved_at=moved,
                client_rate_value=Decimal("150.50"),
                client_rate_unit=RateUnit.hourly,
                client_rate_currency="PLN",
            )
        )
    if stage != PipelineStage.cv_sent:
        db.add(
            CandidateStage(
                candidate_id=candidate.id,
                job_id=job_id,
                stage=stage,
                moved_by=actor,
                moved_at=moved + timedelta(days=1),
            )
        )
    db.add(
        Note(
            candidate_id=candidate.id,
            job_id=job_id,
            author_id=actor,
            content=_PRIVATE_NOTE,
        )
    )
    await db.flush()
    return candidate.id


class World:
    dl_id: int
    dl_headers: dict[str, str]
    recruiter_id: int
    recruiter_headers: dict[str, str]
    job_id: int
    client_id: int
    anna: int


async def _world(*, with_dl: bool = True) -> World:
    world = World()
    world.dl_id, world.dl_headers = await _user(UserRole.delivery_lead)
    world.recruiter_id, world.recruiter_headers = await _user(UserRole.recruiter)
    tag = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Klient Testowy {tag}")
        db.add(client)
        await db.flush()
        db.add(
            Contact(
                client_id=client.id,
                name="Kontakt Testowy",
                email=f"kontakt@klient-{tag}.example.com",
            )
        )
        job = Job(
            title=f"Programista Python {tag}",
            status=JobStatus.published,
            client_id=client.id,
            recruiter_id=world.recruiter_id,
            delivery_lead_id=world.dl_id if with_dl else None,
            description="Treść zapytania klienta",
            client_reference=f"ZOB-{tag}",
            location="Warszawa",
            remote_policy=RemotePolicy.hybrid,
            must_skills=[{"name": "Python"}, {"name": "DDD"}, {"name": "Gerrit"}],
            nice_skills=[{"name": "Linux"}],
            working_title="Tytuł roboczy wewnętrzny",
        )
        db.add(job)
        await db.flush()
        world.job_id = job.id
        world.client_id = client.id
        world.anna = await _candidate(db, job_id=job.id, actor=world.recruiter_id)
        await db.commit()
    return world


async def _enable(app_client: AsyncClient, world: World, **extra: Any) -> str:
    response = await app_client.put(
        f"/api/client-panel/jobs/{world.job_id}",
        headers=world.dl_headers,
        json={"enabled": True, **extra},
    )
    assert response.status_code == 200, response.text
    return response.json()["url"].rsplit("/k/", 1)[1]


async def _public(app_client: AsyncClient, token: str, path: str = "", **kw) -> Any:
    return await app_client.get(f"/api/public/panel/{token}{path}", **kw)


def _author(**extra: Any) -> dict[str, Any]:
    return {
        "author_name": "Jan Klient",
        "author_email": "jan@obcy.example.com",
        **extra,
    }


def _keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return {str(k) for k in value} | {
            key for item in value.values() for key in _keys(item)
        }
    if isinstance(value, list):
        return {key for item in value for key in _keys(item)}
    return set()


def _assert_no_private_data(
    payload: Any, *, allowed: frozenset[str] = frozenset()
) -> None:
    # Klucze wymagań to dane rekrutacji, nie pola: pomijamy je przez `allowed`.
    keys = {key.casefold() for key in _keys(payload)} - allowed
    leaked = sorted(key for key in keys for bad in _FORBIDDEN_KEYS if bad in key)
    assert not leaked, f"Publiczna odpowiedź niesie zakazane pola: {leaked}"
    text = json.dumps(payload, ensure_ascii=False)
    for secret in (
        _PRIVATE_EMAIL,
        _PRIVATE_PHONE,
        _PRIVATE_NOTE,
        "987.65",
        "987,65",
        "Tytuł roboczy wewnętrzny",
    ):
        assert secret not in text


# ── Włączenie i link ─────────────────────────────────────────────────────────


async def test_panel_is_off_by_default_and_link_gives_404(
    app_client: AsyncClient,
) -> None:
    world = await _world()
    view = await app_client.get(
        f"/api/client-panel/jobs/{world.job_id}", headers=world.dl_headers
    )
    assert view.status_code == 200, view.text
    body = view.json()
    assert body["enabled"] is False
    assert body["url"] is None
    assert body["candidates"][0]["candidate_id"] == world.anna
    async with AsyncSessionLocal() as db:
        assert (
            await db.scalar(
                select(func.count(ClientPanel.id)).where(
                    ClientPanel.job_id == world.job_id
                )
            )
        ) == 0
    assert (await _public(app_client, "a" * 16)).status_code == 404


async def test_enabling_issues_a_link_valid_sixty_days_and_stores_only_a_digest(
    app_client: AsyncClient,
) -> None:
    world = await _world()
    token = await _enable(app_client, world)
    async with AsyncSessionLocal() as db:
        panel = await db.scalar(
            select(ClientPanel).where(ClientPanel.job_id == world.job_id)
        )
        assert panel.token_sha256 == service.token_digest(token)
        assert token not in (panel.token_sha256, panel.token_nonce)
        days = (panel.expires_at - datetime.now(timezone.utc)).days
        assert 59 <= days <= 60
    response = await _public(app_client, token)
    assert response.status_code == 200, response.text
    assert response.headers["x-robots-tag"] == "noindex"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"


async def test_disabled_rotated_expired_and_closed(app_client: AsyncClient) -> None:
    world = await _world()
    token = await _enable(app_client, world)
    url = f"/api/client-panel/jobs/{world.job_id}"

    rotated = await app_client.post(f"{url}/rotate-link", headers=world.dl_headers)
    assert rotated.status_code == 200
    new_token = rotated.json()["url"].rsplit("/k/", 1)[1]
    assert new_token != token
    assert (await _public(app_client, token)).status_code == 404
    assert (await _public(app_client, new_token)).status_code == 200

    await app_client.put(url, headers=world.dl_headers, json={"enabled": False})
    assert (await _public(app_client, new_token)).status_code == 404

    await app_client.put(url, headers=world.dl_headers, json={"enabled": True})
    async with AsyncSessionLocal() as db:
        panel = await db.scalar(
            select(ClientPanel).where(ClientPanel.job_id == world.job_id)
        )
        panel.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        await db.commit()
    gone = await _public(app_client, new_token)
    assert gone.status_code == 410
    assert "wygasł" in gone.json()["detail"]

    # Ponowne włączenie po wygaśnięciu daje nowy termin, DL może go przedłużyć.
    await app_client.put(url, headers=world.dl_headers, json={"enabled": False})
    again = await app_client.put(url, headers=world.dl_headers, json={"enabled": True})
    assert again.json()["expires_at"] is not None
    assert (await _public(app_client, new_token)).status_code == 200
    past = await app_client.put(
        url,
        headers=world.dl_headers,
        json={"expires_at": "2020-01-01T00:00:00Z"},
    )
    assert past.status_code == 422

    async with AsyncSessionLocal() as db:
        job = await db.get(Job, world.job_id)
        job.status = JobStatus.closed
        await db.commit()
    assert (await _public(app_client, new_token)).status_code == 410


async def _close_job(job_id: int) -> None:
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        job.status = JobStatus.closed
        await db.commit()


async def test_closed_recruitment_refuses_a_new_panel(app_client: AsyncClient) -> None:
    # 04.11.2026: panel włączony na zamkniętej rekrutacji dawał martwy link.
    world = await _world()
    await _close_job(world.job_id)
    url = f"/api/client-panel/jobs/{world.job_id}"

    refused = await app_client.put(
        url, headers=world.dl_headers, json={"enabled": True}
    )
    assert refused.status_code == 409
    assert "zamknięta" in refused.json()["detail"]

    view = (await app_client.get(url, headers=world.dl_headers)).json()
    assert view["job_closed"] is True
    assert view["enabled"] is False
    assert view["url"] is None


async def test_panel_of_a_job_closed_later_can_still_be_switched_off(
    app_client: AsyncClient,
) -> None:
    world = await _world()
    token = await _enable(app_client, world)
    url = f"/api/client-panel/jobs/{world.job_id}"
    assert (await app_client.get(url, headers=world.dl_headers)).json()[
        "job_closed"
    ] is False
    await _close_job(world.job_id)

    gone = await _public(app_client, token)
    assert gone.status_code == 410
    # Ten tekst rozpoznaje ekran klienta (`panelFailureKind` w `ClientPanelApp.tsx`).
    assert gone.json()["detail"] == "Ta rekrutacja jest już zamknięta."

    view = (await app_client.get(url, headers=world.dl_headers)).json()
    assert view["job_closed"] is True
    assert view["enabled"] is True
    # Ponowne „włącz” na włączonym panelu to nie nowy link, a wyłączyć wolno zawsze.
    same = await app_client.put(url, headers=world.dl_headers, json={"enabled": True})
    assert same.status_code == 200
    off = await app_client.put(url, headers=world.dl_headers, json={"enabled": False})
    assert off.status_code == 200
    assert off.json()["enabled"] is False
    again = await app_client.put(url, headers=world.dl_headers, json={"enabled": True})
    assert again.status_code == 409


# ── Lista i wyciek pól ───────────────────────────────────────────────────────


async def test_public_panel_shape_has_no_private_fields(
    app_client: AsyncClient,
) -> None:
    world = await _world()
    token = await _enable(app_client, world)
    response = await _public(app_client, token)
    assert response.status_code == 200, response.text
    body = response.json()
    _assert_no_private_data(body)
    assert set(body) == {"panel", "job", "owner", "requirements", "candidates"}
    assert set(body["job"]) == {
        "title",
        "reference",
        "client_name",
        "request_text",
        "added_at",
        "work_mode",
        "location",
        "deadline",
    }
    assert body["job"]["work_mode"] == "hybrid"
    assert body["job"]["request_text"] == "Treść zapytania klienta"
    assert [r["key"] for r in body["requirements"]] == [
        "python",
        "ddd",
        "gerrit",
        "linux",
    ]
    person = body["candidates"][0]
    assert set(person) == {
        "public_id",
        "name",
        "title",
        "city",
        "available_from",
        "available_label",
        "available_confirmed_at",
        "rate",
        "statuses",
        "in_projects",
        "on_list",
        "missing",
        "sent_at",
        "state",
    }
    assert person["rate"] == {"value": "150.50", "unit": "hourly", "currency": "PLN"}
    assert person["statuses"] == {
        "python": "project",
        "ddd": "project",
        "gerrit": "none",
        "linux": "list",
    }
    assert (person["in_projects"], person["on_list"], person["missing"]) == (2, 1, 1)
    assert person["available_label"] == "do ustalenia"
    assert person["state"] == "none"


async def test_public_candidate_shape_has_no_private_fields(
    app_client: AsyncClient,
) -> None:
    world = await _world()
    token = await _enable(app_client, world)
    public_id = (await _public(app_client, token)).json()["candidates"][0]["public_id"]
    response = await _public(app_client, token, f"/candidates/{public_id}")
    assert response.status_code == 200, response.text
    body = response.json()
    _assert_no_private_data(body)
    assert set(body) == {
        "public_id",
        "name",
        "cv",
        "evidence",
        "terms",
        "files",
        "thread",
        "interview",
    }
    python = body["evidence"]["python"]
    assert python["status"] == "project"
    assert set(python["items"][0]) == {"kind", "quote", "term", "where", "dates"}
    assert python["items"][0]["where"] == "Firma Testowa"
    assert body["evidence"]["gerrit"] == {"status": "none", "items": []}
    assert body["cv"]["available"] is True
    assert body["cv"]["url"].endswith(f"/candidates/{public_id}/cv.pdf")
    assert body["interview"] == {"status": "none", "slots": [], "chosen": None}


async def test_rate_switch_hides_the_rate_everywhere(app_client: AsyncClient) -> None:
    world = await _world()
    token = await _enable(app_client, world, show_rate=False)
    body = (await _public(app_client, token)).json()
    assert body["candidates"][0]["rate"] is None
    public_id = body["candidates"][0]["public_id"]
    detail = (await _public(app_client, token, f"/candidates/{public_id}")).json()
    assert detail["terms"]["rate"] is None
    assert "150" not in json.dumps(body) + json.dumps(detail)


async def test_list_keeps_only_open_pairs_after_sending(
    app_client: AsyncClient,
) -> None:
    world = await _world()
    async with AsyncSessionLocal() as db:
        await _candidate(
            db,
            job_id=world.job_id,
            actor=world.recruiter_id,
            stage=PipelineStage.rejected,
            name="Odrzucona",
        )
        await _candidate(
            db,
            job_id=world.job_id,
            actor=world.recruiter_id,
            stage=PipelineStage.hired,
            name="Zatrudniona",
        )
        await _candidate(
            db,
            job_id=world.job_id,
            actor=world.recruiter_id,
            stage=PipelineStage.screening,
            name="Niewysłana",
            sent=False,
        )
        further = await _candidate(
            db,
            job_id=world.job_id,
            actor=world.recruiter_id,
            stage=PipelineStage.client_interview,
            name="Dalej",
        )
        await db.commit()
    token = await _enable(app_client, world)
    names = [c["name"] for c in (await _public(app_client, token)).json()["candidates"]]
    assert len(names) == 2
    assert not [
        n for n in names if n.startswith(("Odrzucona", "Zatrudniona", "Niewysł"))
    ]
    assert further in await _sent_ids(world.job_id)


async def _sent_ids(job_id: int) -> set[int]:
    async with AsyncSessionLocal() as db:
        return set(await service.sent_pairs(db, job_id))


async def test_hidden_person_disappears_and_detail_gives_404(
    app_client: AsyncClient,
) -> None:
    world = await _world()
    token = await _enable(app_client, world)
    public_id = (await _public(app_client, token)).json()["candidates"][0]["public_id"]
    hidden = await app_client.patch(
        f"/api/client-panel/jobs/{world.job_id}/candidates/{world.anna}",
        headers=world.dl_headers,
        json={"hidden": True},
    )
    assert hidden.status_code == 200, hidden.text
    assert (await _public(app_client, token)).json()["candidates"] == []
    assert (
        await _public(app_client, token, f"/candidates/{public_id}")
    ).status_code == 404
    assert (
        await _public(app_client, token, f"/candidates/{public_id}/cv.pdf")
    ).status_code == 404


async def test_show_other_candidates_off_returns_only_the_linked_person(
    app_client: AsyncClient,
) -> None:
    world = await _world()
    async with AsyncSessionLocal() as db:
        await _candidate(
            db, job_id=world.job_id, actor=world.recruiter_id, name="Beata"
        )
        await db.commit()
    token = await _enable(app_client, world)
    everyone = (await _public(app_client, token)).json()["candidates"]
    assert len(everyone) == 2
    await app_client.put(
        f"/api/client-panel/jobs/{world.job_id}",
        headers=world.dl_headers,
        json={"show_other_candidates": False},
    )
    assert (await _public(app_client, token)).json()["candidates"] == []
    focused = (
        await _public(app_client, token, params={"c": everyone[1]["public_id"]})
    ).json()["candidates"]
    assert [c["public_id"] for c in focused] == [everyone[1]["public_id"]]


async def test_rejected_evidence_counts_as_none(app_client: AsyncClient) -> None:
    world = await _world()
    token = await _enable(app_client, world)
    url = f"/api/client-panel/jobs/{world.job_id}/candidates/{world.anna}"
    refused = await app_client.patch(
        url, headers=world.dl_headers, json={"rejected_evidence": ["nieznane"]}
    )
    assert refused.status_code == 422
    done = await app_client.patch(
        url, headers=world.dl_headers, json={"rejected_evidence": ["linux"]}
    )
    assert done.status_code == 200
    person = (await _public(app_client, token)).json()["candidates"][0]
    assert person["statuses"]["linux"] == "none"
    admin = await app_client.get(
        f"/api/client-panel/jobs/{world.job_id}", headers=world.dl_headers
    )
    row = admin.json()["candidates"][0]
    assert row["rejected_evidence"] == ["linux"]
    assert row["weak"] == []


async def test_admin_view_lists_weak_evidence(app_client: AsyncClient) -> None:
    world = await _world()
    admin = await app_client.get(
        f"/api/client-panel/jobs/{world.job_id}", headers=world.dl_headers
    )
    weak = admin.json()["candidates"][0]["weak"]
    assert [(w["key"], w["where"]) for w in weak] == [("linux", "Umiejętności")]


async def test_blind_cv_masks_name_and_keeps_certificates_back(
    app_client: AsyncClient,
) -> None:
    world = await _world()
    async with AsyncSessionLocal() as db:
        blind = await _candidate(
            db,
            job_id=world.job_id,
            actor=world.recruiter_id,
            name="Ukryta",
            template="blind",
        )
        db.add(
            CandidateDocument(
                candidate_id=blind,
                filename="certyfikat-z-nazwiskiem.pdf",
                document_kind=CandidateDocumentKind.certificate,
                file_content=b"%PDF-1.4",
                content_type="application/pdf",
            )
        )
        await db.commit()
    token = await _enable(app_client, world)
    candidates = (await _public(app_client, token)).json()["candidates"]
    masked = [c for c in candidates if c["name"] == "Kandydat"]
    assert len(masked) == 1
    assert "Ukryta" not in json.dumps(candidates, ensure_ascii=False)
    detail = (
        await _public(app_client, token, f"/candidates/{masked[0]['public_id']}")
    ).json()
    assert detail["name"] == "Kandydat"
    assert detail["files"] == []
    assert detail["cv"]["filename"] == "CV.pdf"


# ── Pliki ────────────────────────────────────────────────────────────────────


async def test_files_only_the_ones_marked_by_the_dl(
    app_client: AsyncClient,
) -> None:
    world = await _world()
    async with AsyncSessionLocal() as db:
        certificate = CandidateDocument(
            candidate_id=world.anna,
            filename="certyfikat.pdf",
            document_kind=CandidateDocumentKind.certificate,
            file_content=b"%PDF-cert",
            content_type="application/pdf",
        )
        original_cv = CandidateDocument(
            candidate_id=world.anna,
            filename="cv-prywatne.pdf",
            document_kind=CandidateDocumentKind.cv,
            file_content=b"%PDF-cv",
            content_type="application/pdf",
        )
        other = CandidateDocument(
            candidate_id=world.anna,
            filename="skan.html",
            document_kind=CandidateDocumentKind.other,
            file_content=b"<script>1</script>",
            content_type="text/html",
        )
        db.add_all([certificate, original_cv, other])
        await db.commit()
        cert_id, cv_id, other_id = certificate.id, original_cv.id, other.id
    token = await _enable(app_client, world)
    public_id = (await _public(app_client, token)).json()["candidates"][0]["public_id"]
    base = f"/candidates/{public_id}"
    detail = (await _public(app_client, token, base)).json()
    assert detail["files"] == []
    assert (
        await _public(app_client, token, f"{base}/files/{cert_id}")
    ).status_code == 404
    assert (
        await _public(app_client, token, f"{base}/files/{cv_id}")
    ).status_code == 404
    assert (
        await _public(app_client, token, f"{base}/files/{other_id}")
    ).status_code == 404
    view = await app_client.get(
        f"/api/client-panel/jobs/{world.job_id}", headers=world.dl_headers
    )
    assert {d["id"] for d in view.json()["candidates"][0]["documents"]} == {
        cert_id,
        other_id,
    }
    marked = await app_client.patch(
        f"/api/client-panel/jobs/{world.job_id}/candidates/{world.anna}",
        headers=world.dl_headers,
        json={"shared_document_ids": [cert_id, other_id]},
    )
    assert marked.status_code == 200, marked.text
    served = await _public(app_client, token, f"{base}/files/{cert_id}")
    assert served.status_code == 200
    assert served.content == b"%PDF-cert"
    assert served.headers["x-robots-tag"] == "noindex"
    risky = await _public(app_client, token, f"{base}/files/{other_id}")
    assert risky.status_code == 200
    assert risky.headers["content-disposition"].startswith("attachment")


async def test_marking_a_file_of_someone_else_is_refused(
    app_client: AsyncClient,
) -> None:
    world = await _world()
    async with AsyncSessionLocal() as db:
        other = await _candidate(
            db, job_id=world.job_id, actor=world.recruiter_id, name="Beata"
        )
        document = CandidateDocument(
            candidate_id=other,
            filename="cudzy.pdf",
            document_kind=CandidateDocumentKind.other,
            file_content=b"x",
        )
        db.add(document)
        await db.commit()
        document_id = document.id
    refused = await app_client.patch(
        f"/api/client-panel/jobs/{world.job_id}/candidates/{world.anna}",
        headers=world.dl_headers,
        json={"shared_document_ids": [document_id]},
    )
    assert refused.status_code == 422


async def test_cv_pdf_uses_the_conversion_and_no_panel_frame(
    app_client: AsyncClient, monkeypatch
) -> None:
    world = await _world()
    token = await _enable(app_client, world)
    public_id = (await _public(app_client, token)).json()["candidates"][0]["public_id"]
    seen: list[bytes] = []

    async def fake_pdf(docx: bytes) -> bytes:
        seen.append(docx)
        return b"%PDF-fake"

    monkeypatch.setattr("app.services.cv_pdf_preview.pdf_from_docx", fake_pdf)
    served = await _public(app_client, token, f"/candidates/{public_id}/cv.pdf")
    assert served.status_code == 200, served.text
    assert served.content == b"%PDF-fake"
    assert served.headers["content-type"] == "application/pdf"
    assert served.headers["cache-control"] == "no-store"
    text = "\n".join(p.text for p in Document(io.BytesIO(seen[0])).paragraphs)
    assert token not in text
    async with AsyncSessionLocal() as db:
        actions = (
            await db.scalars(
                select(ClientPanelView.action).where(
                    ClientPanelView.candidate_id == world.anna
                )
            )
        ).all()
    # Podgląd wczytuje plik sam: „otworzył plik” liczy dopiero przycisk.
    assert "file" not in actions


# ── Zapisy ───────────────────────────────────────────────────────────────────


async def _public_id(app_client: AsyncClient, token: str) -> str:
    return (await _public(app_client, token)).json()["candidates"][0]["public_id"]


async def test_question_reaches_the_dl_without_mailing_the_author(
    app_client: AsyncClient, monkeypatch
) -> None:
    sent: list[tuple] = []
    monkeypatch.setattr(
        requests_service, "send_email", lambda *a, **k: sent.append((a, k)) or True
    )
    world = await _world()
    token = await _enable(app_client, world)
    public_id = await _public_id(app_client, token)
    created = await app_client.post(
        f"/api/public/panel/{token}/candidates/{public_id}/questions",
        json=_author(body="Czy zna Kubernetes?"),
    )
    assert created.status_code == 201, created.text
    assert sent == []
    assert "jan@obcy" not in created.text
    async with AsyncSessionLocal() as db:
        bell = await db.scalar(
            select(Notification).where(
                Notification.user_id == world.dl_id,
                Notification.notification_type == NotificationType.client_panel_request,
            )
        )
    assert bell is not None
    assert bell.link == f"/jobs/{world.job_id}?win=client-panel"
    assert "Kubernetes" not in f"{bell.title} {bell.message}"

    state = (await _public(app_client, token)).json()["candidates"][0]["state"]
    assert state == "question_open"

    listed = await app_client.get(
        "/api/client-panel/requests",
        headers=world.dl_headers,
        params={"job_id": world.job_id, "status": "open"},
    )
    assert listed.status_code == 200, listed.text
    # Bez filtra rekrutacji lista też działa i obejmuje sprawy tej osoby.
    everywhere = await app_client.get(
        "/api/client-panel/requests", headers=world.dl_headers
    )
    assert everywhere.status_code == 200, everywhere.text
    assert world.job_id in {row["job_id"] for row in everywhere.json()}
    item = listed.json()[0]
    assert item["author_email"] == "jan@obcy.example.com"
    assert item["email_domain_known"] is False
    assert item["candidate_id"] == world.anna

    answered = await app_client.post(
        f"/api/client-panel/requests/{item['id']}/answer",
        headers=world.dl_headers,
        json={"answer": "Tak, 3 lata.", "send_email": False},
    )
    assert answered.status_code == 200, answered.text
    assert answered.json()["email_sent"] is False
    assert sent == []
    detail = (await _public(app_client, token, f"/candidates/{public_id}")).json()
    assert detail["thread"][0]["answer"] == "Tak, 3 lata."
    assert detail["thread"][0]["author"] == "Jan Klient"
    _assert_no_private_data(detail)
    state = (await _public(app_client, token)).json()["candidates"][0]["state"]
    assert state == "answered"

    twice = await app_client.post(
        f"/api/client-panel/requests/{item['id']}/answer",
        headers=world.dl_headers,
        json={"answer": "Jeszcze raz", "send_email": False},
    )
    assert twice.status_code == 409


async def test_answer_mail_goes_only_after_the_dl_click_and_without_the_link(
    app_client: AsyncClient, monkeypatch
) -> None:
    sent: list[tuple] = []
    monkeypatch.setattr(
        requests_service, "send_email", lambda *a, **k: sent.append((a, k)) or True
    )
    world = await _world()
    token = await _enable(app_client, world)
    public_id = await _public_id(app_client, token)
    async with AsyncSessionLocal() as db:
        contact = await db.scalar(
            select(Contact).where(Contact.client_id == world.client_id)
        )
        known_address = contact.email
    await app_client.post(
        f"/api/public/panel/{token}/candidates/{public_id}/questions",
        json=_author(author_email=known_address, body="Pytanie"),
    )
    listed = await app_client.get(
        "/api/client-panel/requests",
        headers=world.dl_headers,
        params={"job_id": world.job_id},
    )
    item = listed.json()[0]
    assert item["email_domain_known"] is True
    answered = await app_client.post(
        f"/api/client-panel/requests/{item['id']}/answer",
        headers=world.dl_headers,
        json={"answer": "Odpowiedź", "send_email": True},
    )
    assert answered.json()["email_sent"] is True
    (args, kwargs) = sent[0]
    assert args[0] == known_address
    assert "/k/" not in args[2] and token not in args[2]
    assert kwargs["reply_to"].startswith("panel-delivery_lead")


async def test_allow_actions_off_refuses_every_write_with_403(
    app_client: AsyncClient,
) -> None:
    world = await _world()
    token = await _enable(app_client, world)
    public_id = await _public_id(app_client, token)
    await app_client.put(
        f"/api/client-panel/jobs/{world.job_id}",
        headers=world.dl_headers,
        json={"allow_actions": False},
    )
    base = f"/api/public/panel/{token}"
    person = f"{base}/candidates/{public_id}"
    start = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
    for url, payload in (
        (f"{person}/questions", _author(body="x")),
        (f"{person}/interview", _author(slots=[{"start": start}])),
        (f"{person}/not-fit", _author(reasons=["za mało lat"])),
        (f"{base}/requirements-change", _author(body="x")),
    ):
        refused = await app_client.post(url, json=payload)
        assert refused.status_code == 403, url
        assert "wyłączone" in refused.json()["detail"]
    async with AsyncSessionLocal() as db:
        assert (
            await db.scalar(
                select(func.count(ClientPanelRequest.id)).where(
                    ClientPanelRequest.job_id == world.job_id
                )
            )
        ) == 0


async def test_daily_limit_gives_429(app_client: AsyncClient) -> None:
    world = await _world()
    token = await _enable(app_client, world)
    async with AsyncSessionLocal() as db:
        panel = await db.scalar(
            select(ClientPanel).where(ClientPanel.job_id == world.job_id)
        )
        db.add_all(
            ClientPanelRequest(
                panel_id=panel.id,
                job_id=world.job_id,
                kind="requirements_change",
                author_name="Jan",
                author_email="jan@example.com",
                body="x",
            )
            for _ in range(requests_service.DAILY_WRITE_LIMIT)
        )
        await db.commit()
    limited = await app_client.post(
        f"/api/public/panel/{token}/requirements-change", json=_author(body="y")
    )
    assert limited.status_code == 429
    assert "Dziś" in limited.json()["detail"]


async def test_validation_and_honeypot(app_client: AsyncClient) -> None:
    world = await _world()
    token = await _enable(app_client, world)
    url = f"/api/public/panel/{token}/requirements-change"
    for bad in (
        _author(author_email="to-nie-adres", body="x"),
        _author(author_name="<b>Jan</b>", body="x"),
        _author(author_name="https://zly.example.com", body="x"),
        _author(body=""),
        _author(body="x" * 2001),
    ):
        assert (await app_client.post(url, json=bad)).status_code == 422
    trap = await app_client.post(url, json=_author(body="spam", honeypot="bot"))
    assert trap.status_code == 201
    async with AsyncSessionLocal() as db:
        assert (
            await db.scalar(
                select(func.count(ClientPanelRequest.id)).where(
                    ClientPanelRequest.job_id == world.job_id
                )
            )
        ) == 0


async def test_not_fit_moves_nothing(app_client: AsyncClient) -> None:
    world = await _world()
    token = await _enable(app_client, world)
    public_id = await _public_id(app_client, token)
    created = await app_client.post(
        f"/api/public/panel/{token}/candidates/{public_id}/not-fit",
        json=_author(reasons=["za mało Pythona"], body="Szukamy seniora"),
    )
    assert created.status_code == 201, created.text
    async with AsyncSessionLocal() as db:
        latest = await db.scalar(
            select(CandidateStage.stage)
            .where(
                CandidateStage.candidate_id == world.anna,
                CandidateStage.job_id == world.job_id,
            )
            .order_by(CandidateStage.moved_at.desc())
            .limit(1)
        )
        row = await db.scalar(
            select(ClientPanelRequest).where(ClientPanelRequest.job_id == world.job_id)
        )
    assert latest == PipelineStage.cv_sent
    assert row.reasons == ["za mało Pythona"]
    assert (await _public(app_client, token)).json()["candidates"][0][
        "state"
    ] == "not_fit"


# ── Terminy: ta sama droga co DL ─────────────────────────────────────────────


def _start(days: int) -> str:
    base = datetime.now(timezone.utc) + timedelta(days=days)
    return base.replace(hour=9, minute=0, second=0, microsecond=0).isoformat()


async def test_interview_goes_the_same_way_as_slots_from_the_dl(
    app_client: AsyncClient,
) -> None:
    world = await _world()
    token = await _enable(app_client, world)
    public_id = await _public_id(app_client, token)
    url = f"/api/public/panel/{token}/candidates/{public_id}/interview"
    created = await app_client.post(
        url,
        json=_author(
            duration_minutes=45,
            slots=[{"start": _start(3)}, {"start": _start(4)}],
            interviewers="Dwie osoby z zespołu",
            prep_note="Proszę o kamerkę",
        ),
    )
    assert created.status_code == 201, created.text
    assert created.json()["interview"]["status"] == "awaiting_recruiter"
    assert len(created.json()["interview"]["slots"]) == 2
    _assert_no_private_data(created.json())
    async with AsyncSessionLocal() as db:
        request = await db.scalar(
            select(ClientInterviewSlotRequest).where(
                ClientInterviewSlotRequest.job_id == world.job_id
            )
        )
        assert request.created_by == world.dl_id
        assert request.recruiter_id == world.recruiter_id
        assert "Proszę o kamerkę" in request.note
        latest = await db.scalar(
            select(CandidateStage)
            .where(
                CandidateStage.candidate_id == world.anna,
                CandidateStage.job_id == world.job_id,
            )
            .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
            .limit(1)
        )
        assert latest.stage == PipelineStage.client_interview
        assert latest.moved_by == world.dl_id
        bell = await db.scalar(
            select(Notification).where(
                Notification.user_id == world.recruiter_id,
                Notification.notification_type
                == NotificationType.interview_slots_requested,
            )
        )
        assert bell is not None
        panel_row = await db.scalar(
            select(ClientPanelRequest).where(ClientPanelRequest.job_id == world.job_id)
        )
        assert panel_row.kind == "interview"
        assert panel_row.slot_request_id == request.id
        slot_request_id = request.id
    state = (await _public(app_client, token)).json()["candidates"]
    assert state[0]["state"] == "interview_requested"

    again = await app_client.post(url, json=_author(slots=[{"start": _start(5)}]))
    assert again.status_code == 409
    assert isinstance(again.json()["detail"], str)
    assert "czekają już terminy" in again.json()["detail"]
    assert str(slot_request_id) not in again.text

    # Rekruter wybiera termin: klient widzi potwierdzoną godzinę.
    chosen = await app_client.post(
        f"/api/interview-cycle/slots/{slot_request_id}/choose",
        headers=world.recruiter_headers,
        json={"index": 0},
    )
    assert chosen.status_code == 200, chosen.text
    detail = (await _public(app_client, token, f"/candidates/{public_id}")).json()
    assert detail["interview"]["status"] == "confirmed"
    assert detail["interview"]["chosen"]["start"]
    state = (await _public(app_client, token)).json()["candidates"]
    assert state[0]["state"] == "interview_confirmed"


async def test_interview_without_a_dl_leaves_the_card_and_tells_the_recruiter(
    app_client: AsyncClient,
) -> None:
    world = await _world(with_dl=False)
    async with AsyncSessionLocal() as db:
        panel = ClientPanel(job_id=world.job_id, enabled=True)
        db.add(panel)
        await db.flush()
        token = service.issue_token(panel)
        panel.expires_at = service.default_expiry()
        await db.commit()
    public_id = await _public_id(app_client, token)
    created = await app_client.post(
        f"/api/public/panel/{token}/candidates/{public_id}/interview",
        json=_author(slots=[{"start": _start(3)}]),
    )
    assert created.status_code == 201, created.text
    async with AsyncSessionLocal() as db:
        request = await db.scalar(
            select(ClientInterviewSlotRequest).where(
                ClientInterviewSlotRequest.job_id == world.job_id
            )
        )
        assert request.created_by is None
        latest = await db.scalar(
            select(CandidateStage.stage)
            .where(
                CandidateStage.candidate_id == world.anna,
                CandidateStage.job_id == world.job_id,
            )
            .order_by(CandidateStage.moved_at.desc())
            .limit(1)
        )
        assert latest == PipelineStage.cv_sent
        bell = await db.scalar(
            select(Notification).where(
                Notification.user_id == world.recruiter_id,
                Notification.notification_type
                == NotificationType.interview_slots_requested,
            )
        )
        assert bell is not None


async def test_past_slot_is_refused_in_polish(app_client: AsyncClient) -> None:
    world = await _world()
    token = await _enable(app_client, world)
    public_id = await _public_id(app_client, token)
    refused = await app_client.post(
        f"/api/public/panel/{token}/candidates/{public_id}/interview",
        json=_author(slots=[{"start": "2020-01-01T09:00:00Z"}]),
    )
    assert refused.status_code == 422
    assert refused.json()["detail"] == "Termin rozmowy nie może być w przeszłości."


async def test_dl_route_keeps_its_409_with_the_open_request_id(
    app_client: AsyncClient,
) -> None:
    world = await _world()
    payload = {
        "candidate_id": world.anna,
        "job_id": world.job_id,
        "slots": [{"start": _start(3)}],
    }
    first = await app_client.post(
        "/api/interview-cycle/slots", headers=world.dl_headers, json=payload
    )
    assert first.status_code == 201, first.text
    assert first.json()["moved_to_client_interview"] is True
    second = await app_client.post(
        "/api/interview-cycle/slots", headers=world.dl_headers, json=payload
    )
    assert second.status_code == 409
    detail = second.json()["detail"]
    assert detail["code"] == "SLOTS_ALREADY_OPEN"
    assert detail["open_request_id"] == first.json()["id"]


# ── Dziennik i bramki ────────────────────────────────────────────────────────


async def test_events_are_best_effort_and_keep_no_raw_ip(
    app_client: AsyncClient,
) -> None:
    world = await _world()
    token = await _enable(app_client, world)
    public_id = await _public_id(app_client, token)
    base = f"/api/public/panel/{token}/events"
    for payload in (
        {"public_id": public_id, "action": "requirement", "detail": "x" * 500},
        {"action": "tab", "detail": "warunki"},
        {"action": "nieznana"},
        {"public_id": "nieistniejacy", "action": "tab"},
    ):
        response = await app_client.post(
            base, json=payload, headers={"X-Forwarded-For": "203.0.113.77"}
        )
        assert response.status_code == 204
    assert (
        await app_client.post(f"/api/public/panel/{'a' * 16}/events", json={})
    ).status_code == 204
    async with AsyncSessionLocal() as db:
        panel = await db.scalar(
            select(ClientPanel).where(ClientPanel.job_id == world.job_id)
        )
        rows = (
            await db.scalars(
                select(ClientPanelView).where(ClientPanelView.panel_id == panel.id)
            )
        ).all()
    requirement = next(r for r in rows if r.action == "requirement")
    assert requirement.candidate_id == world.anna
    assert len(requirement.detail) == service.DETAIL_MAX
    assert all("203.0.113.77" not in (r.ip_hash or "") for r in rows)
    assert all(r.action in ("open", "requirement", "tab") for r in rows)
    view = (
        await app_client.get(
            f"/api/client-panel/jobs/{world.job_id}", headers=world.dl_headers
        )
    ).json()
    assert view["views"]["total"] == len(rows)
    activity = await app_client.get(
        f"/api/client-panel/jobs/{world.job_id}/activity", headers=world.dl_headers
    )
    assert activity.status_code == 200
    assert "ip_hash" not in activity.text
    assert {"at", "action", "detail", "candidate_name"} == set(activity.json()[0])


@pytest.mark.parametrize(
    "role", [UserRole.recruiter, UserRole.user, UserRole.automation]
)
async def test_roles_without_the_permission_get_403(
    app_client: AsyncClient, role: UserRole
) -> None:
    world = await _world()
    _, headers = await _user(role)
    base = f"/api/client-panel/jobs/{world.job_id}"
    assert (await app_client.get(base, headers=headers)).status_code == 403
    assert (
        await app_client.put(base, headers=headers, json={"enabled": True})
    ).status_code == 403
    assert (
        await app_client.get("/api/client-panel/requests", headers=headers)
    ).status_code == 403


async def test_internal_routes_require_a_login(app_client: AsyncClient) -> None:
    assert (await app_client.get("/api/client-panel/jobs/1")).status_code == 401
    assert (await app_client.get("/api/client-panel/requests")).status_code == 401


async def test_retention_removes_views_older_than_180_days() -> None:
    from app.tasks.queue_retention import prune_once

    world = await _world()
    async with AsyncSessionLocal() as db:
        panel = ClientPanel(job_id=world.job_id)
        db.add(panel)
        await db.flush()
        now = datetime.now(timezone.utc)
        db.add_all(
            [
                ClientPanelView(
                    panel_id=panel.id,
                    action="open",
                    created_at=now - timedelta(days=181),
                ),
                ClientPanelView(
                    panel_id=panel.id,
                    action="tab",
                    created_at=now - timedelta(days=179),
                ),
            ]
        )
        await db.commit()
        panel_id = panel.id
    result = await prune_once()
    assert result["client_panel_views"] >= 1
    async with AsyncSessionLocal() as db:
        left = (
            await db.scalars(
                select(ClientPanelView.action).where(
                    ClientPanelView.panel_id == panel_id
                )
            )
        ).all()
    assert left == ["tab"]


# ── Ramka w pobieranym pliku ─────────────────────────────────────────────────


def _plain_docx() -> bytes:
    document = Document()
    document.add_paragraph("Programista – Anna")
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


async def test_stamp_for_download_follows_the_panel_state(
    app_client: AsyncClient, monkeypatch
) -> None:
    world = await _world()
    plain = _plain_docx()
    async with AsyncSessionLocal() as db:
        unstamped = await service.stamp_for_download(
            db, job_id=world.job_id, candidate_id=world.anna, docx=plain
        )
    assert unstamped == plain
    token = await _enable(app_client, world)
    async with AsyncSessionLocal() as db:
        stamped = await service.stamp_for_download(
            db, job_id=world.job_id, candidate_id=world.anna, docx=plain
        )
        rows = await service.candidate_rows(
            db,
            (
                await db.scalar(
                    select(ClientPanel).where(ClientPanel.job_id == world.job_id)
                )
            ).id,
        )
    assert stamped != plain
    document = Document(io.BytesIO(stamped))
    assert len(document.tables) == 1
    targets = [rel.target_ref for rel in document.part.rels.values() if rel.is_external]
    assert targets == [
        service.panel_urls(token, rows[world.anna].public_id)[0],
    ]
    # Awaria odczytu panelu = plik bez ramki, a obiekty żądania zostają czytelne.
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, world.job_id)
        await db.commit()

        async def broken(*_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError("awaria")

        monkeypatch.setattr(service, "panel_for_job", broken)
        assert (
            await service.stamp_for_download(
                db, job_id=world.job_id, candidate_id=world.anna, docx=plain
            )
            == plain
        )
        assert job.title
        monkeypatch.undo()
    # Bez rekrutacji albo osoby plik zostaje bez ramki.
    async with AsyncSessionLocal() as db:
        assert (
            await service.stamp_for_download(
                db, job_id=None, candidate_id=world.anna, docx=plain
            )
            == plain
        )
    # Zamknięta rekrutacja: link by nie działał, więc Word nie dostaje ramki.
    await _close_job(world.job_id)
    async with AsyncSessionLocal() as db:
        assert (
            await service.stamp_for_download(
                db, job_id=world.job_id, candidate_id=world.anna, docx=plain
            )
            == plain
        )


async def test_generated_docx_download_gets_the_frame_only_with_the_intent(
    app_client: AsyncClient, app_auth_headers
) -> None:
    import hashlib

    from app.models.cv_generated_document import CvGeneratedDocument

    world = await _world()
    await _enable(app_client, world)
    stored = _plain_docx()
    async with AsyncSessionLocal() as db:
        row = CvGeneratedDocument(
            candidate_id=world.anna,
            job_id=world.job_id,
            candidate_name="Anna",
            filename="CV.docx",
            status="ready",
            docx_content=stored,
            docx_sha256=hashlib.sha256(stored).hexdigest(),
            render_payload={"name": "Anna"},
        )
        db.add(row)
        await db.commit()
        generated_id = row.id
    url = f"/api/cv-generator/generated/{generated_id}/docx"
    preview = await app_client.get(url, headers=app_auth_headers)
    assert preview.status_code == 200, preview.text
    assert preview.content == stored
    download = await app_client.get(
        url, headers=app_auth_headers, params={"intent": "download", "surface": "dock"}
    )
    assert download.status_code == 200
    assert download.content != stored
    assert len(Document(io.BytesIO(download.content)).tables) == 1
    async with AsyncSessionLocal() as db:
        kept = await db.get(CvGeneratedDocument, generated_id)
        assert kept.docx_content == stored
        assert kept.docx_sha256 == hashlib.sha256(stored).hexdigest()


async def test_only_the_recruitments_dl_manages_the_panel(
    app_client: AsyncClient,
) -> None:
    world = await _world()
    _, stranger_headers = await _user(UserRole.delivery_lead)
    url = f"/api/client-panel/jobs/{world.job_id}"
    refused = await app_client.put(
        url, headers=stranger_headers, json={"enabled": True}
    )
    assert refused.status_code == 403
    assert (await app_client.get(url, headers=stranger_headers)).status_code == 403
    assert (
        await app_client.put(url, headers=world.dl_headers, json={"enabled": True})
    ).status_code == 200
    listing = await app_client.get(
        "/api/client-panel/requests",
        params={"job_id": world.job_id},
        headers=stranger_headers,
    )
    assert listing.status_code == 403
