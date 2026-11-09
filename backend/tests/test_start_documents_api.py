"""Dokumenty do startu: API, ścieżka odmowy każdej roli (0649).

Droga: Delivery Lead ustawia listę → rekruter dodaje plik i PESEL → DL sprawdza
albo zwraca. Rekruter spoza pary, Viewer i obcy DL dostają odmowę. Każdy test
zakłada własne dane (shard ma wspólną bazę).
"""

from __future__ import annotations

import asyncio
import io
import uuid
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from docx import Document
from httpx import AsyncClient
from sqlalchemy import delete, select

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.core.security import hash_password
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, ContractType
from app.models.job import Job, JobStatus
from app.models.notification import Notification, NotificationType
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.section_permission import UserSectionOverride
from app.models.start_document import ClientStartDocument, PlacementStartDocument
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User, UserRole
from app.services import start_documents as svc
from app.tasks import start_documents_sweeper as sweeper

pytestmark = pytest.mark.asyncio

PDF = b"%PDF-1.4\n% test\n"
VALID_PESEL = "44051401458"


@pytest.fixture(autouse=True)
async def _no_bells_left_for_other_tests():
    """Baza shardu jest wspólna: te dzwonki zjadałyby limit `BATCH` testów wysyłki."""

    yield
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(Notification).where(
                Notification.notification_type.in_(
                    (
                        NotificationType.start_documents,
                        NotificationType.start_documents_due,
                        NotificationType.start_documents_returned,
                        NotificationType.start_documents_reminder,
                    )
                )
            )
        )
        await db.commit()


def _only_client(world: dict):
    """Pętla ma widzieć tylko klienta z testu, nie całą wspólną bazę."""

    original = svc.open_states

    async def _open_states(db, **_kwargs):
        return await original(db, client_ids=[world["client_id"]])

    return patch.object(svc, "open_states", _open_states)


@pytest.fixture
async def client(app_client: AsyncClient) -> AsyncClient:
    """Transport ASGI, bez serwera (nazwa lokalna, patrz conftest)."""

    return app_client


async def _user(db, role: UserRole) -> tuple[int, str, str]:
    suffix = uuid.uuid4().hex[:8]
    pwd = f"T3st_{suffix}!"
    user = User(
        email=f"start-docs-{role.value}-{suffix}@example.com",
        password_hash=hash_password(pwd),
        name=f"Sd {role.value} {suffix}",
        role=role,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user.id, user.email, pwd


async def _world(stage: PipelineStage = PipelineStage.hired) -> dict:
    async with AsyncSessionLocal() as db:
        recruiter = await _user(db, UserRole.recruiter)
        other_recruiter = await _user(db, UserRole.recruiter)
        dl = await _user(db, UserRole.delivery_lead)
        foreign_dl = await _user(db, UserRole.delivery_lead)
        head = await _user(db, UserRole.head_of_recruitment)
        client = Client(name=f"StartDocs {uuid.uuid4().hex[:6]}")
        db.add(client)
        await db.flush()
        db.add(
            DeliveryLeadClientAssignment(
                client_id=client.id, delivery_lead_user_id=dl[0]
            )
        )
        job = Job(
            title="Analityk systemowy",
            client_id=client.id,
            delivery_lead_id=dl[0],
            status=JobStatus.published,
        )
        candidate = Candidate(
            name="Anna", lastname="Testowa", email=f"at-{uuid.uuid4().hex[:8]}@x.com"
        )
        db.add_all([job, candidate])
        await db.flush()
        db.add(
            CandidateStage(
                candidate_id=candidate.id,
                job_id=job.id,
                stage=PipelineStage.verified,
                moved_by=recruiter[0],
            )
        )
        await db.flush()
        db.add(
            CandidateStage(
                candidate_id=candidate.id,
                job_id=job.id,
                stage=stage,
                moved_by=recruiter[0],
            )
        )
        documents = {
            "agreement": ClientStartDocument(
                client_id=client.id, position=1, name="Umowa", kind="agreement"
            ),
            "nda": ClientStartDocument(
                client_id=client.id, position=2, name="NDA", kind="file"
            ),
            "pesel": ClientStartDocument(
                client_id=client.id, position=3, name="PESEL", kind="pesel"
            ),
            "certs": ClientStartDocument(
                client_id=client.id,
                position=4,
                name="Certyfikaty",
                kind="file",
                required=False,
            ),
        }
        db.add_all(documents.values())
        await db.commit()
        return {
            "recruiter": recruiter,
            "other_recruiter": other_recruiter,
            "dl": dl,
            "foreign_dl": foreign_dl,
            "head": head,
            "candidate_id": candidate.id,
            "job_id": job.id,
            "client_id": client.id,
            "documents": {key: doc.id for key, doc in documents.items()},
        }


async def _headers(client: AsyncClient, who: tuple[int, str, str]) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": who[1], "password": who[2]}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _url(world: dict, key: str, action: str) -> str:
    return (
        f"/api/start-documents/pair/{world['candidate_id']}/{world['job_id']}"
        f"/items/{world['documents'][key]}/{action}"
    )


async def _pair(client: AsyncClient, world: dict, headers: dict) -> dict:
    resp = await client.get(
        "/api/start-documents/pair",
        params={"candidate_id": world["candidate_id"], "job_id": world["job_id"]},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _state(pair: dict, name: str) -> str:
    return next(i["state"] for i in pair["items"] if i["name"] == name)


async def _upload_nda(client: AsyncClient, world: dict, headers: dict):
    return await client.put(
        _url(world, "nda", "file"),
        files={"file": ("nda.pdf", PDF, "application/pdf")},
        headers=headers,
    )


async def test_recruiter_delivers_and_set_counts_only_required(
    client: AsyncClient,
) -> None:
    world = await _world()
    headers = await _headers(client, world["recruiter"])
    pair = await _pair(client, world, headers)
    assert (pair["done"], pair["total"]) == (0, 3)
    assert pair["recruiter_name"] is not None
    assert pair["permissions"]["can_review"] is False

    resp = await _upload_nda(client, world, headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["done"] == 1
    assert _state(resp.json(), "NDA") == "delivered"
    assert (
        next(i for i in resp.json()["items"] if i["name"] == "NDA")["file_name"]
        == "nda.pdf"
    )


async def test_client_without_list_gets_null_and_nothing_on_the_card(
    client: AsyncClient,
) -> None:
    world = await _world()
    async with AsyncSessionLocal() as db:
        for doc in (
            await db.scalars(
                select(ClientStartDocument).where(
                    ClientStartDocument.client_id == world["client_id"]
                )
            )
        ).all():
            doc.archived_at = svc.utcnow()
        await db.commit()
    headers = await _headers(client, world["recruiter"])
    resp = await client.get(
        "/api/start-documents/pair",
        params={"candidate_id": world["candidate_id"], "job_id": world["job_id"]},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json() is None
    assert (await client.get("/api/start-documents/mine", headers=headers)).json()[
        "items"
    ] == []


async def test_file_must_really_be_a_pdf_or_image(client: AsyncClient) -> None:
    world = await _world()
    headers = await _headers(client, world["recruiter"])
    resp = await client.put(
        _url(world, "nda", "file"),
        files={"file": ("nda.pdf", b"MZ not a pdf", "application/pdf")},
        headers=headers,
    )
    assert resp.status_code in (415, 422)
    pesel_as_file = await client.put(
        _url(world, "pesel", "file"),
        files={"file": ("x.pdf", PDF, "application/pdf")},
        headers=headers,
    )
    assert pesel_as_file.status_code == 422


async def test_recruiter_from_the_board_sees_state_but_no_file_and_no_pesel(
    client: AsyncClient,
) -> None:
    """Stan pary widzi każdy z Tablicy, plik z KRK i PESEL tylko węższy krąg."""

    world = await _world()
    owner = await _headers(client, world["recruiter"])
    assert (await _upload_nda(client, world, owner)).status_code == 200
    await client.put(
        _url(world, "pesel", "pesel"), json={"pesel": VALID_PESEL}, headers=owner
    )
    for who in ("other_recruiter", "foreign_dl"):
        headers = await _headers(client, world[who])
        response = await client.get(_url(world, "nda", "file"), headers=headers)
        assert response.status_code == 403, who
        response = await client.get(_url(world, "pesel", "pesel"), headers=headers)
        assert response.status_code == 403, who
        response = await client.post(_url(world, "nda", "check"), headers=headers)
        assert response.status_code == 403, who
    pair = await _pair(client, world, await _headers(client, world["other_recruiter"]))
    assert pair["permissions"]["can_download"] is False
    assert pair["permissions"]["can_view_pesel"] is False
    assert VALID_PESEL not in str(pair)
    downloaded = await client.get(_url(world, "nda", "file"), headers=owner)
    assert downloaded.status_code == 200
    assert downloaded.content == PDF


async def test_candidate_outside_the_recruitment_gets_no_state_and_no_mail(
    client: AsyncClient,
) -> None:
    """Dowolny `candidate_id` w adresie nie może dać cudzego adresu e-mail."""

    world = await _world()
    async with AsyncSessionLocal() as db:
        stranger = Candidate(
            name="Obcy", lastname="Kandydat", email=f"ob-{uuid.uuid4().hex[:8]}@x.com"
        )
        db.add(stranger)
        await db.commit()
        stranger_id = stranger.id
    headers = await _headers(client, world["recruiter"])
    base = f"/api/start-documents/pair/{stranger_id}/{world['job_id']}"
    assert (await client.get(f"{base}/list-mail", headers=headers)).status_code == 404
    assert (await client.post(f"{base}/list-mail", headers=headers)).status_code == 404
    uploaded = await client.put(
        f"{base}/items/{world['documents']['nda']}/file",
        files={"file": ("nda.pdf", PDF, "application/pdf")},
        headers=headers,
    )
    assert uploaded.status_code == 404
    state = await client.get(
        "/api/start-documents/pair",
        params={"candidate_id": stranger_id, "job_id": world["job_id"]},
        headers=headers,
    )
    assert state.status_code == 404


async def test_read_only_recruitment_section_cannot_write(client: AsyncClient) -> None:
    """Sekcja „Rekrutacje” tylko do odczytu: stan tak, plik, PESEL i mail nie."""

    world = await _world()
    async with AsyncSessionLocal() as db:
        db.add(
            UserSectionOverride(
                user_id=world["recruiter"][0],
                section="pipeline",
                access="read",
            )
        )
        await db.commit()
    headers = await _headers(client, world["recruiter"])
    assert (await _pair(client, world, headers))["total"] == 3
    assert (await _upload_nda(client, world, headers)).status_code == 403
    pesel = await client.put(
        _url(world, "pesel", "pesel"), json={"pesel": VALID_PESEL}, headers=headers
    )
    assert pesel.status_code == 403
    mail_url = (
        f"/api/start-documents/pair/{world['candidate_id']}/{world['job_id']}/list-mail"
    )
    assert (await client.post(mail_url, headers=headers)).status_code == 403


async def test_link_on_the_list_must_be_a_real_address(client: AsyncClient) -> None:
    """Zły link wywracał kartę wszystkim rekruterom klienta (`new URL` na froncie)."""

    world = await _world()
    dl = await _headers(client, world["dl"])
    url = f"/api/start-documents/clients/{world['client_id']}"
    for bad in (
        "https://",
        "https://a b",
        "http://ekrk.ms.gov.pl",
        "javascript:alert(1)",
    ):
        response = await client.post(
            url, json={"name": "KRK", "link_url": bad}, headers=dl
        )
        assert response.status_code == 422, bad
    good = await client.post(
        url,
        json={"name": "KRK", "link_url": "https://ekrk.ms.gov.pl/ep-web"},
        headers=dl,
    )
    assert good.status_code == 201


async def test_viewer_has_no_access_at_all(client: AsyncClient) -> None:
    world = await _world()
    async with AsyncSessionLocal() as db:
        viewer = await _user(db, UserRole.user)
        await db.commit()
    headers = await _headers(client, viewer)
    resp = await client.get(
        "/api/start-documents/pair",
        params={"candidate_id": world["candidate_id"], "job_id": world["job_id"]},
        headers=headers,
    )
    assert resp.status_code == 403


async def test_pesel_is_validated_hidden_from_recruiter_and_read_is_logged(
    client: AsyncClient,
) -> None:
    world = await _world()
    recruiter = await _headers(client, world["recruiter"])
    bad = await client.put(
        _url(world, "pesel", "pesel"), json={"pesel": "44051401459"}, headers=recruiter
    )
    assert bad.status_code == 422
    saved = await client.put(
        _url(world, "pesel", "pesel"), json={"pesel": VALID_PESEL}, headers=recruiter
    )
    assert saved.status_code == 200, saved.text
    assert VALID_PESEL not in saved.text

    assert (
        await client.get(_url(world, "pesel", "pesel"), headers=recruiter)
    ).status_code == 403
    head = await _headers(client, world["head"])
    assert (
        await client.get(_url(world, "pesel", "pesel"), headers=head)
    ).status_code == 403

    dl = await _headers(client, world["dl"])
    read = await client.get(_url(world, "pesel", "pesel"), headers=dl)
    assert read.status_code == 200
    assert read.json() == {"pesel": VALID_PESEL}
    async with AsyncSessionLocal() as db:
        logged = await db.scalars(
            select(Activity).where(
                Activity.entity_id == world["candidate_id"],
                Activity.action == "start_documents_pesel_read",
            )
        )
        rows = logged.all()
    assert [row.user_id for row in rows] == [world["dl"][0]]
    assert VALID_PESEL not in str(rows[0].details)


async def test_only_delivery_lead_reviews_and_return_takes_the_file_out_of_the_set(
    client: AsyncClient,
) -> None:
    world = await _world()
    recruiter = await _headers(client, world["recruiter"])
    dl = await _headers(client, world["dl"])
    await _upload_nda(client, world, recruiter)

    denied = await client.post(
        _url(world, "nda", "return"), json={"reason": "zły plik"}, headers=recruiter
    )
    assert denied.status_code == 403
    assert (
        await client.post(_url(world, "nda", "check"), headers=recruiter)
    ).status_code == 403

    checked = await client.post(_url(world, "nda", "check"), headers=dl)
    assert checked.status_code == 200
    item = next(i for i in checked.json()["items"] if i["name"] == "NDA")
    assert item["checked_at"] is not None

    returned = await client.post(
        _url(world, "nda", "return"), json={"reason": "brak podpisu"}, headers=dl
    )
    assert returned.status_code == 200
    assert returned.json()["done"] == 0
    assert _state(returned.json(), "NDA") == "returned"
    async with AsyncSessionLocal() as db:
        bell = await db.scalar(
            select(Notification).where(
                Notification.user_id == world["recruiter"][0],
                Notification.notification_type
                == NotificationType.start_documents_returned,
            )
        )
    assert bell is not None
    assert "brak podpisu" in bell.message


async def test_new_file_after_a_return_clears_the_reason(client: AsyncClient) -> None:
    world = await _world()
    recruiter = await _headers(client, world["recruiter"])
    dl = await _headers(client, world["dl"])
    await _upload_nda(client, world, recruiter)
    await client.post(
        _url(world, "nda", "return"), json={"reason": "brak podpisu"}, headers=dl
    )
    resp = await _upload_nda(client, world, recruiter)
    item = next(i for i in resp.json()["items"] if i["name"] == "NDA")
    assert item["state"] == "delivered"
    assert item["reason"] is None


async def test_review_of_nothing_delivered_is_a_conflict(client: AsyncClient) -> None:
    world = await _world()
    dl = await _headers(client, world["dl"])
    assert (
        await client.post(_url(world, "nda", "check"), headers=dl)
    ).status_code == 409


async def test_not_applicable_needs_a_reason_and_can_be_undone(
    client: AsyncClient,
) -> None:
    world = await _world()
    dl = await _headers(client, world["dl"])
    assert (
        await client.post(
            _url(world, "nda", "not-applicable"), json={"reason": ""}, headers=dl
        )
    ).status_code == 422
    done = await client.post(
        _url(world, "nda", "not-applicable"),
        json={"reason": "NDA z poprzedniego kontraktu"},
        headers=dl,
    )
    assert done.json()["done"] == 1
    undone = await client.delete(_url(world, "nda", "state"), headers=dl)
    assert undone.json()["done"] == 0
    assert _state(undone.json(), "NDA") == "missing"


async def test_signature_ticks_agreement_through_live_contract(
    client: AsyncClient,
) -> None:
    world = await _world()
    async with AsyncSessionLocal() as db:
        db.add(
            Contract(
                candidate_id=world["candidate_id"],
                job_id=world["job_id"],
                client_id=world["client_id"],
                status=ContractStatus.active,
                contract_type=ContractType.b2b,
                start_date=business_today() + timedelta(days=30),
            )
        )
        await db.commit()
    pair = await _pair(client, world, await _headers(client, world["recruiter"]))
    assert _state(pair, "Umowa") == "delivered"
    assert pair["done"] == 1
    assert pair["deadline"] is not None


async def test_mine_gives_each_person_their_own_pairs(client: AsyncClient) -> None:
    world = await _world()
    for who, expected_role, expected in (
        ("recruiter", "recruiter", 1),
        ("dl", "delivery_lead", 1),
        ("other_recruiter", "recruiter", 0),
        ("foreign_dl", "recruiter", 0),
    ):
        headers = await _headers(client, world[who])
        body = (await client.get("/api/start-documents/mine", headers=headers)).json()
        assert body["role"] == expected_role, who
        rows = [r for r in body["items"] if r["job_id"] == world["job_id"]]
        assert len(rows) == expected, who


async def test_inactive_recruiter_hands_the_reminders_to_the_delivery_lead(
    client: AsyncClient,
) -> None:
    """Konto odeszłego rekrutera nie dostanie dzwonka, więc sprawa nie może zniknąć."""

    world = await _world()
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, world["job_id"])
        recruiter = await db.get(User, world["recruiter"][0])
        recruiter.is_active = False
        await db.commit()
        state = await svc.pair_state(db, world["candidate_id"], job)
    assert state.recruiter_id is None
    assert state.owner_id == world["dl"][0]


async def test_second_delivery_lead_of_the_client_does_not_get_foreign_pairs_on_the_list(
    client: AsyncClient,
) -> None:
    """Portfel daje dostęp do pary, ale lista i czerwona liczba są tylko „moje”."""

    world = await _world()
    async with AsyncSessionLocal() as db:
        db.add(
            DeliveryLeadClientAssignment(
                client_id=world["client_id"],
                delivery_lead_user_id=world["foreign_dl"][0],
            )
        )
        await db.commit()
    headers = await _headers(client, world["foreign_dl"])
    body = (await client.get("/api/start-documents/mine", headers=headers)).json()
    assert not [r for r in body["items"] if r["job_id"] == world["job_id"]]
    pair = await _pair(client, world, headers)
    assert pair["permissions"]["can_review"] is True


async def test_delivery_lead_who_also_recruits_keeps_both_lists(
    client: AsyncClient,
) -> None:
    world = await _world()
    async with AsyncSessionLocal() as db:
        user = await db.get(User, world["recruiter"][0])
        user.role = UserRole.delivery_lead
        user.roles = [UserRole.delivery_lead.value, UserRole.recruiter.value]
        await db.commit()
    headers = await _headers(client, world["recruiter"])
    body = (await client.get("/api/start-documents/mine", headers=headers)).json()
    assert [r for r in body["items"] if r["job_id"] == world["job_id"]]


async def test_pair_outside_active_stages_is_not_on_the_list(
    client: AsyncClient,
) -> None:
    world = await _world()
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateStage(
                candidate_id=world["candidate_id"],
                job_id=world["job_id"],
                stage=PipelineStage.rejected,
                moved_by=world["dl"][0],
            )
        )
        await db.commit()
    headers = await _headers(client, world["recruiter"])
    body = (await client.get("/api/start-documents/mine", headers=headers)).json()
    assert not [r for r in body["items"] if r["job_id"] == world["job_id"]]


async def test_card_badge_for_the_board(client: AsyncClient) -> None:
    world = await _world()
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, world["job_id"])
        badges = await svc.card_badges(db, job, [world["candidate_id"], 999_999_999])
    badge = badges[world["candidate_id"]]
    assert (badge["done"], badge["total"]) == (0, 3)
    assert badge["missing"] == ["Umowa", "NDA", "PESEL"]


async def test_client_list_edit_needs_permission_and_scope(client: AsyncClient) -> None:
    world = await _world()
    url = f"/api/start-documents/clients/{world['client_id']}"
    payload = {"name": "BHP", "kind": "file", "offset_days": -1}
    recruiter = await _headers(client, world["recruiter"])
    assert (await client.post(url, json=payload, headers=recruiter)).status_code == 403
    foreign = await _headers(client, world["foreign_dl"])
    assert (await client.post(url, json=payload, headers=foreign)).status_code == 403
    dl = await _headers(client, world["dl"])
    created = await client.post(url, json=payload, headers=dl)
    assert created.status_code == 201, created.text
    assert created.json()["name"] == "BHP"
    bad_link = await client.post(
        url, json={"name": "X", "link_url": "javascript:alert(1)"}, headers=dl
    )
    assert bad_link.status_code == 422
    gone = await client.delete(
        f"/api/start-documents/items/{created.json()['id']}", headers=dl
    )
    assert gone.status_code == 204
    names = [i["name"] for i in (await client.get(url, headers=dl)).json()["items"]]
    assert "BHP" not in names


async def test_template_upload_rejects_other_formats(client: AsyncClient) -> None:
    world = await _world()
    dl = await _headers(client, world["dl"])
    url = f"/api/start-documents/items/{world['documents']['nda']}/template"
    bad = await client.put(
        url, files={"file": ("x.exe", b"MZ", "application/x-msdownload")}, headers=dl
    )
    assert bad.status_code == 415
    fake = await client.put(
        url,
        files={"file": ("x.docx", b"not a zip", "application/octet-stream")},
        headers=dl,
    )
    assert fake.status_code == 415


async def test_template_is_filled_from_the_agreement_for_the_recruiter(
    client: AsyncClient,
) -> None:
    world = await _world()
    dl = await _headers(client, world["dl"])
    source = Document()
    table = source.add_table(rows=1, cols=1)
    table.cell(0, 0).text = "Consultant's name"
    out = io.BytesIO()
    source.save(out)
    url = f"/api/start-documents/items/{world['documents']['nda']}"
    await client.patch(
        url,
        json={"name": "NDA", "kind": "file", "fill_from_agreement": True},
        headers=dl,
    )
    uploaded = await client.put(
        f"{url}/template",
        files={"file": ("nda.docx", out.getvalue(), "application/octet-stream")},
        headers=dl,
    )
    assert uploaded.status_code == 200, uploaded.text
    recruiter = await _headers(client, world["recruiter"])
    with patch(
        "app.api.start_documents._agreement_payload",
        AsyncMock(return_value={"partner_name": "Anna Testowa"}),
    ):
        filled = await client.get(_url(world, "nda", "template"), headers=recruiter)
    assert filled.status_code == 200, filled.text
    text = Document(io.BytesIO(filled.content)).tables[0].cell(0, 0).text
    assert text.endswith("Anna Testowa")


async def test_list_mail_says_when_the_mailbox_is_not_connected(
    client: AsyncClient,
) -> None:
    world = await _world()
    recruiter = await _headers(client, world["recruiter"])
    url = (
        f"/api/start-documents/pair/{world['candidate_id']}/{world['job_id']}/list-mail"
    )
    preview = await client.get(url, headers=recruiter)
    assert preview.status_code == 200
    assert preview.json()["mailbox_connected"] is False
    assert "PESEL" in preview.json()["text"]
    sent = await client.post(url, headers=recruiter)
    assert sent.status_code == 409


async def test_sweeper_sends_one_digest_a_day_and_skips_outside_hours(
    client: AsyncClient,
) -> None:
    world = await _world()
    today = business_today()
    async with AsyncSessionLocal() as db:
        db.add(
            Contract(
                candidate_id=world["candidate_id"],
                job_id=world["job_id"],
                client_id=world["client_id"],
                status=ContractStatus.active,
                contract_type=ContractType.b2b,
                start_date=today,
            )
        )
        await db.commit()
    from app.core.scheduling import local_now

    now = local_now()
    early = now.replace(hour=7)
    assert (await sweeper.run_once(early))["recipients"] == 0
    late = now.replace(hour=10)
    with patch.object(sweeper, "load_calendar", _always_working), _only_client(world):
        await sweeper.run_once(late)
        await sweeper.run_once(late)
    async with AsyncSessionLocal() as db:
        bells = (
            await db.scalars(
                select(Notification).where(
                    Notification.user_id == world["recruiter"][0],
                    Notification.related_entity_type == "start_documents_digest",
                )
            )
        ).all()
    assert len(bells) == 1
    assert bells[0].notification_type == NotificationType.start_documents_due
    assert "Anna Testowa" in bells[0].message
    async with AsyncSessionLocal() as db:
        escalated = (
            await db.scalars(
                select(Notification.user_id).where(
                    Notification.related_entity_type == "start_documents_digest",
                    Notification.user_id.in_([world["dl"][0], world["head"][0]]),
                    Notification.notification_type
                    == NotificationType.start_documents_due,
                )
            )
        ).all()
    # Start dziś: Delivery Lead i Head of Recruitment też dostają listę.
    assert set(escalated) == {world["dl"][0], world["head"][0]}


async def test_undoing_not_applicable_does_not_count_a_returned_file(
    client: AsyncClient,
) -> None:
    world = await _world()
    recruiter = await _headers(client, world["recruiter"])
    dl = await _headers(client, world["dl"])
    await _upload_nda(client, world, recruiter)
    await client.post(
        _url(world, "nda", "return"), json={"reason": "brak podpisu"}, headers=dl
    )
    await client.post(
        _url(world, "nda", "not-applicable"), json={"reason": "jednak nie"}, headers=dl
    )
    undone = await client.delete(_url(world, "nda", "state"), headers=dl)
    assert _state(undone.json(), "NDA") == "missing"
    assert undone.json()["done"] == 0


async def test_returned_file_stops_being_stored(client: AsyncClient) -> None:
    """Odrzucony plik z danymi o karalności nie leży dalej bez powodu."""

    world = await _world()
    recruiter = await _headers(client, world["recruiter"])
    dl = await _headers(client, world["dl"])
    await _upload_nda(client, world, recruiter)
    await client.post(
        _url(world, "nda", "return"), json={"reason": "brak podpisu"}, headers=dl
    )
    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(PlacementStartDocument).where(
                PlacementStartDocument.candidate_id == world["candidate_id"]
            )
        )
    assert row.file_path is None
    assert row.file_name is None
    assert (await client.get(_url(world, "nda", "file"), headers=dl)).status_code == 404


async def test_two_returns_of_one_person_give_two_bells(client: AsyncClient) -> None:
    world = await _world()
    recruiter = await _headers(client, world["recruiter"])
    dl = await _headers(client, world["dl"])
    await _upload_nda(client, world, recruiter)
    await client.put(
        _url(world, "certs", "file"),
        files={"file": ("cert.pdf", PDF, "application/pdf")},
        headers=recruiter,
    )
    for key in ("nda", "certs"):
        response = await client.post(
            _url(world, key, "return"), json={"reason": f"zły plik {key}"}, headers=dl
        )
        assert response.status_code == 200
    async with AsyncSessionLocal() as db:
        bells = (
            await db.scalars(
                select(Notification).where(
                    Notification.user_id == world["recruiter"][0],
                    Notification.notification_type
                    == NotificationType.start_documents_returned,
                )
            )
        ).all()
    assert len(bells) == 2


async def test_remind_says_when_nothing_went_out(client: AsyncClient) -> None:
    world = await _world()
    dl = await _headers(client, world["dl"])
    url = f"/api/start-documents/pair/{world['candidate_id']}/{world['job_id']}/remind"
    assert (await client.post(url, headers=dl)).json() == {"sent": True}
    assert (await client.post(url, headers=dl)).json() == {"sent": False}


async def test_parallel_first_upload_gives_no_500_and_no_orphan_row(
    client: AsyncClient,
) -> None:
    world = await _world()
    recruiter = await _headers(client, world["recruiter"])
    first, second = await asyncio.gather(
        _upload_nda(client, world, recruiter), _upload_nda(client, world, recruiter)
    )
    assert {first.status_code, second.status_code} == {200}
    async with AsyncSessionLocal() as db:
        rows = (
            await db.scalars(
                select(PlacementStartDocument).where(
                    PlacementStartDocument.candidate_id == world["candidate_id"]
                )
            )
        ).all()
    assert len(rows) == 1


async def test_owner_and_delivery_lead_digests_merge_into_one(
    client: AsyncClient,
) -> None:
    """Indeks dnia pozwala na jeden dzwonek: druga lista przepadała po cichu."""

    world = await _world()
    today = business_today()
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, world["job_id"])
        second_job = Job(
            title="Tester",
            client_id=world["client_id"],
            delivery_lead_id=world["dl"][0],
            status=JobStatus.published,
        )
        own = Candidate(
            name="Własna", lastname="Osoba", email=f"wo-{uuid.uuid4().hex[:8]}@x.com"
        )
        db.add_all([second_job, own])
        await db.flush()
        # DL sam zweryfikował tę osobę, więc jest jej prowadzącym.
        for stage in (PipelineStage.verified, PipelineStage.hired):
            db.add(
                CandidateStage(
                    candidate_id=own.id,
                    job_id=second_job.id,
                    stage=stage,
                    moved_by=world["dl"][0],
                )
            )
            await db.flush()
        for candidate_id, job_id in (
            (world["candidate_id"], job.id),
            (own.id, second_job.id),
        ):
            db.add(
                Contract(
                    candidate_id=candidate_id,
                    job_id=job_id,
                    client_id=world["client_id"],
                    status=ContractStatus.active,
                    contract_type=ContractType.b2b,
                    start_date=today,
                )
            )
        await db.commit()
    from app.core.scheduling import local_now

    with patch.object(sweeper, "load_calendar", _always_working), _only_client(world):
        await sweeper.run_once(local_now().replace(hour=10))
    async with AsyncSessionLocal() as db:
        bells = (
            await db.scalars(
                select(Notification).where(
                    Notification.user_id == world["dl"][0],
                    Notification.related_entity_type == "start_documents_digest",
                )
            )
        ).all()
    assert len(bells) == 1
    assert "Anna Testowa" in bells[0].message
    assert "Własna Osoba" in bells[0].message


async def test_inactive_delivery_lead_falls_back_to_the_client_portfolio_then_head(
    client: AsyncClient,
) -> None:
    world = await _world()
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, world["job_id"])
        recruiter = await db.get(User, world["recruiter"][0])
        recruiter.is_active = False
        dead_dl = await db.get(User, world["dl"][0])
        dead_dl.is_active = False
        db.add(
            DeliveryLeadClientAssignment(
                client_id=world["client_id"],
                delivery_lead_user_id=world["foreign_dl"][0],
            )
        )
        await db.commit()
        state = await svc.pair_state(db, world["candidate_id"], job)
        assert state.delivery_lead_id == world["foreign_dl"][0]
        foreign = await db.get(User, world["foreign_dl"][0])
        foreign.is_active = False
        await db.commit()
        state = await svc.pair_state(db, world["candidate_id"], job)
    assert state.owner_id is None


async def _always_working(_db, _start: date, _end: date):
    from app.services.hr.calendar import WorkCalendar

    class _Working(WorkCalendar):
        def is_working_day(self, day: date) -> bool:
            return True

    return _Working()


async def test_archived_position_keeps_the_file_of_the_pair() -> None:
    world = await _world()
    async with AsyncSessionLocal() as db:
        row = PlacementStartDocument(
            document_id=world["documents"]["nda"],
            candidate_id=world["candidate_id"],
            job_id=world["job_id"],
            status="delivered",
            file_path="x",
        )
        db.add(row)
        doc = await db.get(ClientStartDocument, world["documents"]["nda"])
        doc.archived_at = svc.utcnow()
        await db.commit()
        kept = await db.scalar(
            select(PlacementStartDocument).where(
                PlacementStartDocument.candidate_id == world["candidate_id"]
            )
        )
    assert kept is not None
