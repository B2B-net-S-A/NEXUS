"""E-teczka — trasy: bramki, krąg widzących, pliki, zmiany Kadr, protokoły sprzętu.

Ścieżki odmowy: wyłączony moduł „Ludzie” (404 poza adminem), bez Kadr (403
z nazwą uprawnienia), przełożony i zespół nie widzą e-teczki (404), Płace
i recepcja tylko dokumentów ze swoim znacznikiem, plik spoza kręgu = 404,
usunięcie bez powodu (422) i umowy z generatora (409). Dane fikcyjne.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.api.hr_gates import MODULE_DISABLED_DETAIL
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.hr_document import HrDocument
from app.models.hr_ops import HrAuditEvent
from app.models.user import User
from app.services.hr import documents
from tests.hr_documents_seed import (
    PREFIX,
    docx_bytes,
    documents_on,  # noqa: F401  (fixture)
    documents_people_off,  # noqa: F401  (fixture)
    documents_routes,  # noqa: F401  (fixture)
    documents_store_root,  # noqa: F401  (fixture)
    pdf_bytes,
    png_bytes,
)
from tests.hr_settlements_seed import headers, make_user

pytestmark = pytest.mark.usefixtures("documents_routes", "documents_store_root")


@dataclass
class Cast:
    hr: User
    payroll: User
    reception: User
    boss: User
    person: User
    colleague: User
    admin: User


async def _cast() -> Cast:
    hr = await make_user(
        "recruiter", grants=("people_admin",), profile=False, name="Ewa Kadrowa"
    )
    payroll = await make_user(
        "recruiter", grants=("payroll",), profile=False, name="Filip Finansowy"
    )
    reception = await make_user(
        "recruiter", grants=("equipment",), profile=False, name="Rita Recepcja"
    )
    boss = await make_user("recruiter", employment_type="uop", name="Marta Przełożona")
    person = await make_user(
        "employee",
        employment_type="zlecenie",
        manager_user_id=boss.id,
        name="Celina Testowa",
    )
    colleague = await make_user("employee", employment_type="b2b", name="Ola Nowak")
    admin = await make_user("admin", profile=False, name="Adam Admin")
    return Cast(hr, payroll, reception, boss, person, colleague, admin)


async def _upload(
    client: AsyncClient,
    actor: User,
    user_id: int,
    *,
    kind: str = "contract",
    title: str = "Umowa zlecenia z 01.03.2026",
    content: bytes | None = None,
    filename: str = "umowa.pdf",
    mime: str = "application/pdf",
    **form,
):
    data = {"kind": kind, "title": title, **{k: str(v) for k, v in form.items()}}
    return await client.post(
        f"{PREFIX}/people/{user_id}",
        headers=headers(actor),
        data=data,
        files={"file": (filename, content or pdf_bytes(), mime)},
    )


async def _list(client: AsyncClient, actor: User, user_id: int):
    return await client.get(f"{PREFIX}/people/{user_id}", headers=headers(actor))


def _ids(response) -> set[int]:
    return {row["id"] for row in response.json()["documents"]}


# ── Bramki ────────────────────────────────────────────────────────────────────


@pytest.mark.usefixtures("documents_people_off")
async def test_people_module_off_hides_documents_except_admin(
    app_client: AsyncClient,
) -> None:
    cast = await _cast()

    own = await _list(app_client, cast.person, cast.person.id)
    hr_upload = await _upload(app_client, cast.hr, cast.person.id)
    admin = await _list(app_client, cast.admin, cast.person.id)

    assert own.status_code == 404 and own.json()["detail"] == MODULE_DISABLED_DETAIL
    assert hr_upload.status_code == 404
    assert admin.status_code == 200


@pytest.mark.usefixtures("documents_on")
async def test_only_kadry_change_documents(app_client: AsyncClient) -> None:
    cast = await _cast()
    created = await _upload(app_client, cast.hr, cast.person.id)
    assert created.status_code == 201, created.text
    document_id = created.json()["document"]["id"]

    by_person = await _upload(app_client, cast.person, cast.person.id)
    by_payroll = await app_client.patch(
        f"{PREFIX}/{document_id}", headers=headers(cast.payroll), json={"title": "X"}
    )
    by_reception = await app_client.post(
        f"{PREFIX}/{document_id}/remove",
        headers=headers(cast.reception),
        json={"note": "pomyłka"},
    )
    retention = await app_client.get(f"{PREFIX}/retention", headers=headers(cast.boss))

    for response in (by_person, by_payroll, by_reception, retention):
        assert response.status_code == 403, response.text
        assert response.json()["detail"]["permission"] == "people_admin"


# ── Krąg widzących ────────────────────────────────────────────────────────────


@pytest.mark.usefixtures("documents_on")
async def test_person_sees_own_documents_manager_and_team_do_not(
    app_client: AsyncClient,
) -> None:
    cast = await _cast()
    content = pdf_bytes()
    created = await _upload(app_client, cast.hr, cast.person.id, content=content)
    document_id = created.json()["document"]["id"]

    own = await _list(app_client, cast.person, cast.person.id)
    own_file = await app_client.get(
        f"{PREFIX}/{document_id}/file", headers=headers(cast.person)
    )
    boss = await _list(app_client, cast.boss, cast.person.id)
    boss_file = await app_client.get(
        f"{PREFIX}/{document_id}/file", headers=headers(cast.boss)
    )
    colleague = await _list(app_client, cast.colleague, cast.person.id)

    assert own.status_code == 200 and _ids(own) == {document_id}
    assert own.json()["can_manage"] is False
    assert own_file.status_code == 200 and own_file.content == content
    assert own_file.headers["content-type"] == "application/pdf"
    # Przełożony nie widzi e-teczki (ani listy, ani pliku) — jak obcej osoby.
    assert boss.status_code == 404
    assert boss_file.status_code == 404
    assert colleague.status_code == 404


@pytest.mark.usefixtures("documents_on")
async def test_payroll_and_reception_see_only_their_documents(
    app_client: AsyncClient,
) -> None:
    cast = await _cast()
    for_payroll = (
        await _upload(app_client, cast.hr, cast.person.id, kind="contract")
    ).json()["document"]["id"]
    for_reception = (
        await _upload(
            app_client, cast.hr, cast.person.id, kind="protocol", title="Protokół"
        )
    ).json()["document"]["id"]
    person_only = (
        await _upload(
            app_client, cast.hr, cast.person.id, kind="other", title="Notatka"
        )
    ).json()["document"]["id"]

    payroll = await _list(app_client, cast.payroll, cast.person.id)
    reception = await _list(app_client, cast.reception, cast.person.id)
    hr = await _list(app_client, cast.hr, cast.person.id)
    hidden = await app_client.get(
        f"{PREFIX}/{person_only}/file", headers=headers(cast.payroll)
    )

    assert _ids(payroll) == {for_payroll}
    assert payroll.json()["protocols"] is None  # Płace nie widzą protokołów sprzętu
    assert _ids(reception) == {for_reception}
    assert reception.json()["protocols"] == []
    assert _ids(hr) == {for_payroll, for_reception, person_only}
    assert hr.json()["can_manage"] is True
    assert hidden.status_code == 404


@pytest.mark.usefixtures("documents_on")
async def test_document_hidden_from_person_stays_hidden(
    app_client: AsyncClient,
) -> None:
    cast = await _cast()
    created = await _upload(
        app_client,
        cast.hr,
        cast.person.id,
        kind="other",
        title="Notatka Kadr",
        visible_to_person="false",
    )
    document_id = created.json()["document"]["id"]
    assert created.json()["document"]["audience"] == {
        "person": False,
        "payroll": False,
        "equipment": False,
    }

    own = await _list(app_client, cast.person, cast.person.id)
    own_file = await app_client.get(
        f"{PREFIX}/{document_id}/file", headers=headers(cast.person)
    )

    assert _ids(own) == set()
    assert own_file.status_code == 404


@pytest.mark.usefixtures("documents_on")
async def test_absence_proof_stays_with_person_and_kadry(
    app_client: AsyncClient,
    documents_store_root,  # noqa: F811
) -> None:
    """Dane o zdrowiu: ani wgranie, ani zmiana kręgu nie otwiera ich Płacom i recepcji."""

    cast = await _cast()
    for_payroll = await _upload(
        app_client,
        cast.hr,
        cast.person.id,
        kind="absence_proof",
        title="Zaświadczenie lekarskie",
        visible_to_payroll="true",
    )
    for_reception = await _upload(
        app_client,
        cast.hr,
        cast.person.id,
        kind="absence_proof",
        title="Zaświadczenie lekarskie",
        visible_to_equipment="true",
    )
    created = await _upload(
        app_client,
        cast.hr,
        cast.person.id,
        kind="absence_proof",
        title="Zaświadczenie lekarskie",
    )
    assert created.status_code == 201, created.text
    document_id = created.json()["document"]["id"]
    widened = await app_client.patch(
        f"{PREFIX}/{document_id}",
        headers=headers(cast.hr),
        json={"audience": {"person": True, "payroll": True, "equipment": False}},
    )
    payroll = await _list(app_client, cast.payroll, cast.person.id)

    message = "Potwierdzenie nieobecności widzą tylko osoba i Kadry."
    for response in (for_payroll, for_reception, widened):
        assert response.status_code == 422, response.text
        assert response.json()["detail"] == message
    assert created.json()["document"]["audience"] == {
        "person": True,
        "payroll": False,
        "equipment": False,
    }
    assert _ids(payroll) == set()
    # Odrzucone wgrania nie zostawiają plików w magazynie.
    stored = [path for path in documents_store_root.rglob("*") if path.is_file()]
    assert len(stored) == 1


@pytest.mark.usefixtures("documents_on")
async def test_document_download_leaves_trail(app_client: AsyncClient) -> None:
    cast = await _cast()
    contract_id = (await _upload(app_client, cast.hr, cast.person.id)).json()[
        "document"
    ]["id"]
    proof_id = (
        await _upload(
            app_client,
            cast.hr,
            cast.person.id,
            kind="absence_proof",
            title="Zaświadczenie lekarskie",
        )
    ).json()["document"]["id"]

    by_person = await app_client.get(
        f"{PREFIX}/{contract_id}/file", headers=headers(cast.person)
    )
    by_hr = await app_client.get(
        f"{PREFIX}/{proof_id}/file?disposition=inline", headers=headers(cast.hr)
    )
    hidden = await app_client.get(
        f"{PREFIX}/{proof_id}/file", headers=headers(cast.payroll)
    )

    assert by_person.status_code == 200 and by_hr.status_code == 200
    assert hidden.status_code == 404
    async with AsyncSessionLocal() as db:
        events = (
            await db.scalars(
                select(HrAuditEvent).where(
                    HrAuditEvent.entity_type == "hr_document",
                    HrAuditEvent.action == "document_downloaded",
                    HrAuditEvent.entity_id.in_([str(contract_id), str(proof_id)]),
                )
            )
        ).all()
    trail = {
        (e.entity_id, e.actor_user_id, e.subject_user_id, e.sensitivity) for e in events
    }
    assert trail == {
        (str(contract_id), cast.person.id, cast.person.id, "general"),
        (str(proof_id), cast.hr.id, cast.person.id, "health"),
    }
    assert {e.entity_id: e.details for e in events} == {
        str(contract_id): {"kind": "contract"},
        str(proof_id): {"kind": "absence_proof"},
    }


# ── Pliki ─────────────────────────────────────────────────────────────────────


@pytest.mark.usefixtures("documents_on")
async def test_upload_refuses_wrong_file_type(app_client: AsyncClient) -> None:
    cast = await _cast()
    html = await _upload(
        app_client,
        cast.hr,
        cast.person.id,
        content=b"<html><script>alert(1)</script></html>",
        filename="umowa.pdf",
    )
    unknown_kind = await _upload(app_client, cast.hr, cast.person.id, kind="nda")
    bad_date = await _upload(
        app_client, cast.hr, cast.person.id, valid_until="30.06.2027"
    )

    assert html.status_code == 422 and "PDF" in html.json()["detail"]
    assert unknown_kind.status_code == 422
    assert bad_date.status_code == 422 and "RRRR-MM-DD" in bad_date.json()["detail"]


@pytest.mark.usefixtures("documents_on")
async def test_inline_only_for_safe_types(app_client: AsyncClient) -> None:
    cast = await _cast()
    image = (
        await _upload(
            app_client,
            cast.hr,
            cast.person.id,
            kind="certificate",
            title="Zaświadczenie (skan)",
            content=png_bytes(),
            filename="skan.png",
            mime="image/png",
        )
    ).json()["document"]
    word = (
        await _upload(
            app_client,
            cast.hr,
            cast.person.id,
            kind="annex",
            title="Aneks",
            content=docx_bytes(),
            filename="aneks.docx",
            mime="application/octet-stream",
        )
    ).json()["document"]

    png = await app_client.get(
        f"{PREFIX}/{image['id']}/file?disposition=inline", headers=headers(cast.person)
    )
    docx = await app_client.get(
        f"{PREFIX}/{word['id']}/file?disposition=inline", headers=headers(cast.person)
    )

    assert image["mime"] == "image/png"
    assert word["mime"].endswith("wordprocessingml.document")
    assert png.headers["content-disposition"].startswith("inline")
    assert docx.headers["content-disposition"].startswith("attachment")


# ── Zmiany i usunięcie ────────────────────────────────────────────────────────


@pytest.mark.usefixtures("documents_on")
async def test_patch_title_date_and_audience(app_client: AsyncClient) -> None:
    cast = await _cast()
    document_id = (await _upload(app_client, cast.hr, cast.person.id)).json()[
        "document"
    ]["id"]
    until = (business_today() + timedelta(days=365)).isoformat()

    changed = await app_client.patch(
        f"{PREFIX}/{document_id}",
        headers=headers(cast.hr),
        json={
            "title": "  Umowa   zlecenia  ",
            "valid_until": until,
            "audience": {"person": True, "payroll": False, "equipment": True},
        },
    )
    empty = await app_client.patch(
        f"{PREFIX}/{document_id}", headers=headers(cast.hr), json={"title": "   "}
    )

    assert changed.status_code == 200, changed.text
    body = changed.json()["document"]
    assert body["title"] == "Umowa zlecenia"
    assert body["valid_until"] == until
    assert body["audience"] == {"person": True, "payroll": False, "equipment": True}
    assert empty.status_code == 422


@pytest.mark.usefixtures("documents_on")
async def test_remove_needs_reason_deletes_file_and_keeps_trail(
    app_client: AsyncClient,
    documents_store_root,  # noqa: F811
) -> None:
    cast = await _cast()
    created = (await _upload(app_client, cast.hr, cast.person.id)).json()["document"]
    async with AsyncSessionLocal() as db:
        path = (await db.get(HrDocument, created["id"])).file_path
    assert (documents_store_root / path).is_file()

    no_reason = await app_client.post(
        f"{PREFIX}/{created['id']}/remove", headers=headers(cast.hr), json={"note": " "}
    )
    removed = await app_client.post(
        f"{PREFIX}/{created['id']}/remove",
        headers=headers(cast.hr),
        json={"note": "Wgrany do złej osoby"},
    )
    again = await app_client.post(
        f"{PREFIX}/{created['id']}/remove",
        headers=headers(cast.hr),
        json={"note": "jeszcze raz"},
    )
    own = await _list(app_client, cast.person, cast.person.id)
    hr = await _list(app_client, cast.hr, cast.person.id)
    file_after = await app_client.get(
        f"{PREFIX}/{created['id']}/file", headers=headers(cast.hr)
    )

    assert no_reason.status_code == 422
    assert removed.status_code == 200
    assert again.status_code == 409
    assert not (documents_store_root / path).exists()
    assert _ids(own) == set()
    trail = hr.json()["documents"][0]
    assert trail["deleted"] is True and trail["deletion_reason"] == "mistake"
    assert trail["deleted_by_name"] == cast.hr.name
    assert file_after.status_code == 404


@pytest.mark.usefixtures("documents_on")
async def test_generated_agreement_cannot_be_removed_by_hand(
    app_client: AsyncClient,
) -> None:
    cast = await _cast()
    async with AsyncSessionLocal() as db:
        document = await documents.attach_generated(
            db,
            user_id=cast.person.id,
            kind="contract",
            title="Umowa zlecenia z generatora",
            content=pdf_bytes(),
            mime="application/pdf",
            source=documents.SOURCE_AGREEMENT,
            source_ref="hr_agreement:900",
            valid_until=None,
            actor_id=cast.hr.id,
        )
        await db.commit()

    removed = await app_client.post(
        f"{PREFIX}/{document.id}/remove",
        headers=headers(cast.hr),
        json={"note": "nie chcę"},
    )
    hide = await app_client.patch(
        f"{PREFIX}/{document.id}",
        headers=headers(cast.hr),
        json={"audience": {"person": False, "payroll": True, "equipment": False}},
    )
    own = await _list(app_client, cast.person, cast.person.id)

    assert removed.status_code == 409
    assert hide.status_code == 422
    assert _ids(own) == {document.id}
    assert own.json()["documents"][0]["source"] == "agreement"


@pytest.mark.usefixtures("documents_on")
async def test_student_statement_reports_profile_sync(app_client: AsyncClient) -> None:
    cast = await _cast()
    until = (business_today() + timedelta(days=120)).isoformat()

    created = await _upload(
        app_client,
        cast.hr,
        cast.person.id,
        kind="statement",
        title="Oświadczenie studenta",
        valid_until=until,
        purpose="student_status",
    )

    assert created.status_code == 201, created.text
    assert created.json()["profile_sync"] == {"status": "updated", "until": until}
    assert created.json()["document"]["purpose"] == "student_status"


# ── Protokoły sprzętu (odnośniki) ─────────────────────────────────────────────


async def _protocol_for(user: User, actor: User, *, signed: bytes | None = None) -> int:
    from app.services.equipment import protocols
    from app.services.equipment.holders import resolve_holder

    async with AsyncSessionLocal() as db:
        holder = await resolve_holder(db, "user", user.id)
        protocol = await protocols.create_protocol(
            db,
            kind="wydanie",
            holder=holder,
            lines=[
                {
                    "name": "Laptop testowy",
                    "category": "laptop",
                    "identifier": "LT-0001",
                }
            ],
            protocol_date=business_today(),
            actor=await db.get(User, actor.id),
        )
        if signed is not None:
            await protocols.save_signed_file(
                db,
                protocol,
                filename="skan.pdf",
                content=signed,
                method="papier",
                actor=await db.get(User, actor.id),
            )
        await db.commit()
        return protocol.id


@pytest.mark.usefixtures("documents_on")
async def test_equipment_protocols_are_links_for_person_hr_and_reception(
    app_client: AsyncClient,
    monkeypatch,
    documents_store_root,  # noqa: F811
) -> None:
    from app.services import cv_pdf_preview
    from app.services.equipment import protocols

    async def fake_pdf(_docx: bytes) -> bytes:
        return b"%PDF-1.4 protokol"

    monkeypatch.setattr(cv_pdf_preview, "pdf_from_docx", fake_pdf)
    # Katalog skanów modułu sprzętu liczy się przy imporcie — ten sam magazyn testu.
    monkeypatch.setattr(
        protocols, "SIGNED_DIR", documents_store_root / "equipment_protocols"
    )
    cast = await _cast()
    protocol_id = await _protocol_for(cast.person, cast.reception)
    scan = pdf_bytes()
    signed_id = await _protocol_for(cast.person, cast.reception, signed=scan)
    foreign_id = await _protocol_for(cast.colleague, cast.reception)

    own = await _list(app_client, cast.person, cast.person.id)
    rendered = await app_client.get(
        f"{PREFIX}/people/{cast.person.id}/protocols/{protocol_id}/file",
        headers=headers(cast.person),
    )
    signed = await app_client.get(
        f"{PREFIX}/people/{cast.person.id}/protocols/{signed_id}/file",
        headers=headers(cast.reception),
    )
    payroll = await app_client.get(
        f"{PREFIX}/people/{cast.person.id}/protocols/{protocol_id}/file",
        headers=headers(cast.payroll),
    )
    foreign = await app_client.get(
        f"{PREFIX}/people/{cast.person.id}/protocols/{foreign_id}/file",
        headers=headers(cast.hr),
    )

    numbers = {row["id"]: row for row in own.json()["protocols"]}
    assert set(numbers) == {protocol_id, signed_id}
    assert numbers[signed_id]["has_signed_file"] is True
    assert "total_value" not in numbers[protocol_id]  # bez wartości sprzętu
    assert rendered.status_code == 200 and rendered.content == b"%PDF-1.4 protokol"
    assert signed.status_code == 200 and signed.content == scan
    assert payroll.status_code == 404
    assert foreign.status_code == 404
    async with AsyncSessionLocal() as db:
        copies = await db.scalar(
            select(HrDocument.id).where(HrDocument.kind == "protocol").limit(1)
        )
    assert copies is None  # protokoły nie są kopiowane do e-teczki
