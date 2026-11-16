"""Szkolenie od zamówienia do biblioteki (0694). Dane fikcyjne — repo jest publiczne.

Pilnuje reguł, których macierz uprawnień nie widzi, bo siedzą w treści handlera:

* trener widzi tylko swoje szkolenia (cudze i szkic = 404),
* pozycje C i D wyceny tylko przy zamówionej prezentacji i audio,
* zwrot pliku do poprawy niesie termin 3 dni roboczych (§ 11 ust. 4 umowy),
* faktura dopiero po przyjęciu kompletu plików, zapłata dopiero po fakturze,
* biblioteka dopiero po zapłacie (§ 8 ust. 3), nagranie publikuje druga osoba,
* plik z biblioteki tylko opublikowany i „dla uczestników”, bilet odtwarzania jednego pliku.

Umowę i podpisy kwalifikowane sprawdzają ``test_training_agreement.py`` i
``test_training_signing.py``; tu stan po podpisach ustawia baza.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import pytest
from sqlalchemy import update

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.training import Training
from app.models.user import UserRole
from app.services import storage_service
from tests.care_announcements_seed import headers, make_user
from tests.consultant_portal_seed import (  # noqa: F401  (fixture'y)
    BASE,
    install_mailer,
    make_person,
    portal_all,
    portal_restored,
    session_headers,
)

STAFF = "/api/trainings"
PDF = b"%PDF-1.4 materialy szkolenia"
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"0" * 64


def _raw(name: str, content_type: str) -> dict[str, str]:
    """Duże pliki idą surowym ciałem: sesja i bramka przed odczytem bajtów."""

    return {"Content-Type": content_type, "X-File-Name": quote(name)}


@pytest.fixture
def _storage(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    yield tmp_path


def _order(**extra) -> dict:
    return {
        "title": "Bezpieczeństwo w erze AI",
        "topic": "Bezpieczeństwo",
        "session_date": (business_today() + timedelta(days=14)).isoformat(),
        "time_from": "16:00",
        "time_to": "19:00",
        "duration_minutes": 180,
        "expected_participants": 60,
        "deliverables": [
            {"key": "materials", "due_days": 2},
            {"key": "presentation", "due_days": 2},
        ],
        **extra,
    }


QUOTE = {
    "agenda": [
        {"title": "Jak AI zmienia ataki", "minutes": 60},
        {"title": "Ćwiczenia", "minutes": 120},
    ],
    "fee_prep": "2400",
    "fee_delivery": "1800",
    "fee_presentation": "600",
    "fee_rights": "500",
}


async def _signed(training_id: int) -> None:
    """Stan po podpisach obu stron (podpisy sprawdzają osobne testy)."""

    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Training)
            .where(Training.id == training_id)
            .values(
                status="signed",
                agreement_number=f"SZK/{training_id}/2026",
                trainer_signed_at=now,
                company_signed_at=now,
            )
        )
        await db.commit()


@pytest.mark.usefixtures("portal_all", "_storage")
async def test_training_from_order_to_library(app_client, monkeypatch) -> None:
    mailer = install_mailer(monkeypatch)
    person = await make_person()
    other = await make_person()
    tcm = await make_user(UserRole.talent_community_manager, name="Tamara")
    second_tcm = await make_user(UserRole.talent_community_manager, name="Teresa")
    finance = await make_user(UserRole.finance, name="Felicja")
    recruiter = await make_user(UserRole.recruiter, name="Roksana")
    trainer = await session_headers(app_client, person)
    stranger = await session_headers(app_client, other)

    # Zamówienie: rekruter nie zakłada, TCM tak; szkic nie jest widoczny w panelu.
    body = {**_order(), "trainer_contract_id": person.contract_id}
    assert (
        await app_client.post(STAFF, headers=headers(recruiter), json=body)
    ).status_code == 403
    created = await app_client.post(STAFF, headers=headers(tcm), json=body)
    assert created.status_code == 201, created.text
    training_id = created.json()["training"]["id"]
    hidden = await app_client.get(f"{BASE}/trainings/{training_id}", headers=trainer)
    assert hidden.status_code == 404

    sent = await app_client.post(f"{STAFF}/{training_id}/send", headers=headers(tcm))
    assert sent.status_code == 200, sent.text
    assert sent.json()["training"]["status"] == "ordered"
    assert any("do wyceny" in mail["subject"] for mail in mailer.sent)
    assert all("—" not in mail["text"] for mail in mailer.sent)

    # Cudzy konsultant nie widzi szkolenia; trener widzi swoje z kwotami po wycenie.
    assert (
        await app_client.get(f"{BASE}/trainings/{training_id}", headers=stranger)
    ).status_code == 404
    mine = (await app_client.get(f"{BASE}/trainings", headers=trainer)).json()
    assert [row["id"] for row in mine["mine"]] == [training_id]

    # Wycena: D (audio) nie jest zamówione, C (prezentacja) jest wymagane.
    with_audio = await app_client.put(
        f"{BASE}/trainings/{training_id}/quote",
        headers=trainer,
        json={**QUOTE, "fee_audio": "900"},
    )
    assert with_audio.status_code == 422
    assert with_audio.json()["detail"]["code"] == "fee_not_ordered"
    without_c = {
        key: value for key, value in QUOTE.items() if key != "fee_presentation"
    }
    missing = await app_client.put(
        f"{BASE}/trainings/{training_id}/quote", headers=trainer, json=without_c
    )
    assert missing.status_code == 422
    assert missing.json()["detail"]["code"] == "fee_required"
    quoted = await app_client.put(
        f"{BASE}/trainings/{training_id}/quote", headers=trainer, json=QUOTE
    )
    assert quoted.status_code == 200, quoted.text
    assert quoted.json()["training"]["fees"]["total"] == "5300.00"

    # Odesłanie z uwagą wymaga uwagi; potem przyjęcie.
    assert (
        await app_client.post(
            f"{STAFF}/{training_id}/return", headers=headers(tcm), json={"note": ""}
        )
    ).status_code == 422
    returned = await app_client.post(
        f"{STAFF}/{training_id}/return",
        headers=headers(tcm),
        json={"note": "Dodaj przerwę"},
    )
    assert returned.json()["training"]["status"] == "returned"
    requoted = await app_client.put(
        f"{BASE}/trainings/{training_id}/quote", headers=trainer, json=QUOTE
    )
    assert requoted.status_code == 200
    accepted = await app_client.post(
        f"{STAFF}/{training_id}/accept", headers=headers(tcm)
    )
    assert accepted.json()["training"]["status"] == "accepted"

    # Finanse czytają z kwotami, rekruter nie widzi rejestru.
    assert (
        await app_client.get(f"{STAFF}/{training_id}", headers=headers(recruiter))
    ).status_code == 403
    read = await app_client.get(f"{STAFF}/{training_id}", headers=headers(finance))
    assert read.json()["training"]["fees"]["total"] == "5300.00"

    # Pliki dopiero po podpisach obu stron.
    early = await app_client.post(
        f"{BASE}/trainings/{training_id}/deliverables/materials",
        headers={**trainer, **_raw("material.pdf", "application/pdf")},
        content=PDF,
    )
    assert early.status_code == 409
    await _signed(training_id)

    project = await app_client.post(
        f"{BASE}/trainings/{training_id}/deliverables/presentation",
        headers={**trainer, **_raw("szkolenie.drp", "application/octet-stream")},
        content=b"projekt",
    )
    assert project.status_code == 422
    not_ordered = await app_client.post(
        f"{BASE}/trainings/{training_id}/deliverables/audio",
        headers={**trainer, **_raw("podcast.mp3", "audio/mpeg")},
        content=b"ID3audio",
    )
    assert not_ordered.status_code == 422

    materials = await app_client.post(
        f"{BASE}/trainings/{training_id}/deliverables/materials",
        headers={**trainer, **_raw("material.pdf", "application/pdf")},
        content=PDF,
    )
    assert materials.status_code == 201, materials.text
    slides = await app_client.post(
        f"{BASE}/trainings/{training_id}/deliverables/presentation",
        headers={**trainer, **_raw("slajdy.pdf", "application/pdf")},
        content=PDF,
    )
    assert slides.status_code == 201, slides.text
    rows = {row["key"]: row for row in slides.json()["training"]["handover"]}
    assert rows["materials"]["state"] == "submitted"

    # Zwrot do poprawy: uwaga i termin 3 dni roboczych; faktura jeszcze nie.
    card = (await app_client.get(f"{STAFF}/{training_id}", headers=headers(tcm))).json()
    files = {row["key"]: row["files"][0]["id"] for row in card["training"]["handover"]}
    back = await app_client.post(
        f"{STAFF}/{training_id}/files/{files['materials']}/review",
        headers=headers(tcm),
        json={"accept": False, "note": "Brak klucza do ćwiczenia 2"},
    )
    assert back.status_code == 200, back.text
    returned_row = next(
        row for row in back.json()["training"]["handover"] if row["key"] == "materials"
    )
    assert returned_row["state"] == "returned"
    assert returned_row["files"][0]["fix_due_on"] is not None
    invoice_early = await app_client.post(
        f"{BASE}/trainings/{training_id}/invoice",
        headers=trainer,
        files={"file": ("faktura.pdf", PDF, "application/pdf")},
    )
    assert invoice_early.status_code == 409

    fixed = await app_client.post(
        f"{BASE}/trainings/{training_id}/deliverables/materials",
        headers={**trainer, **_raw("material-v2.pdf", "application/pdf")},
        content=PDF + b"v2",
    )
    assert fixed.status_code == 201
    card = (await app_client.get(f"{STAFF}/{training_id}", headers=headers(tcm))).json()
    for row in card["training"]["handover"]:
        for item in row["files"]:
            ok = await app_client.post(
                f"{STAFF}/{training_id}/files/{item['id']}/review",
                headers=headers(tcm),
                json={"accept": True},
            )
            assert ok.status_code == 200
    view = (
        await app_client.get(f"{BASE}/trainings/{training_id}", headers=trainer)
    ).json()["training"]
    assert view["payment"]["invoice_ready_at"] is not None
    assert view["can_invoice"] is True
    invoice = await app_client.post(
        f"{BASE}/trainings/{training_id}/invoice",
        headers=trainer,
        files={"file": ("faktura.pdf", PDF, "application/pdf")},
    )
    assert invoice.status_code == 201, invoice.text

    # Nagranie wgrywa TCM; przed zapłatą biblioteka odmawia.
    recording = await app_client.post(
        f"{STAFF}/{training_id}/files?kind=recording",
        headers={**headers(tcm), **_raw("nagranie.mp4", "video/mp4")},
        content=MP4,
    )
    assert recording.status_code == 201, recording.text
    unpaid = await app_client.post(
        f"{STAFF}/{training_id}/publish",
        headers=headers(second_tcm),
        json={"publish": True},
    )
    assert unpaid.status_code == 409
    assert unpaid.json()["detail"]["code"] == "not_paid"

    # Zapłata: tylko Finanse.
    assert (
        await app_client.post(
            f"{STAFF}/{training_id}/paid", headers=headers(tcm), json={"paid": True}
        )
    ).status_code == 403
    paid = await app_client.post(
        f"{STAFF}/{training_id}/paid", headers=headers(finance), json={"paid": True}
    )
    assert paid.status_code == 200, paid.text

    # Nagranie publikuje druga osoba.
    own = await app_client.post(
        f"{STAFF}/{training_id}/publish", headers=headers(tcm), json={"publish": True}
    )
    assert own.status_code == 403
    assert own.json()["detail"]["code"] == "four_eyes"
    published = await app_client.post(
        f"{STAFF}/{training_id}/publish",
        headers=headers(second_tcm),
        json={"publish": True},
    )
    assert published.status_code == 200, published.text

    # Biblioteka: pracownik i inny konsultant widzą nagranie i materiały, bez kwot
    # i bez PPTX/faktury; bilet otwiera tylko ten plik.
    library = (
        await app_client.get(f"{STAFF}/library", headers=headers(recruiter))
    ).json()
    entry = next(row for row in library["recordings"] if row["id"] == training_id)
    kinds = sorted(item["kind"] for item in entry["files"])
    assert kinds == ["deliverable", "recording"]
    assert "5300" not in str(library)
    recording_id = next(i["id"] for i in entry["files"] if i["kind"] == "recording")
    ticket = (
        await app_client.get(
            f"{STAFF}/library/files/{recording_id}/ticket", headers=headers(recruiter)
        )
    ).json()["url"]
    played = await app_client.get(ticket, headers={"Range": "bytes=0-9"})
    assert played.status_code == 206
    assert played.content == MP4[:10]
    other_file = int(ticket.split("/")[-1].split("?")[0]) + 1
    forged = await app_client.get(
        f"/api/public/training-media/{other_file}?{ticket.split('?')[1]}"
    )
    assert forged.status_code == 403
    portal_library = (
        await app_client.get(f"{BASE}/trainings", headers=stranger)
    ).json()["library"]
    assert training_id in [row["id"] for row in portal_library["recordings"]]
    invoice_file = next(
        item["id"]
        for item in (
            await app_client.get(f"{STAFF}/{training_id}", headers=headers(tcm))
        ).json()["training"]["files"]
        if item["kind"] == "invoice"
    )
    assert (
        await app_client.get(
            f"{STAFF}/library/files/{invoice_file}", headers=headers(recruiter)
        )
    ).status_code == 404
    assert (
        await app_client.get(f"{BASE}/trainings/files/{invoice_file}", headers=stranger)
    ).status_code == 404

    # Plik, który TCM cofnął do poprawy po publikacji, znika z biblioteki
    # (przegląd bezpieczeństwa 13.11.2026: widać było pliki nieprzyjęte).
    material_id = next(i["id"] for i in entry["files"] if i["kind"] == "deliverable")
    material_ticket = (
        await app_client.get(
            f"{STAFF}/library/files/{material_id}/ticket", headers=headers(recruiter)
        )
    ).json()["url"]
    assert (await app_client.get(material_ticket)).status_code == 200
    back = await app_client.post(
        f"{STAFF}/{training_id}/files/{material_id}/review",
        headers=headers(tcm),
        json={"accept": False, "note": "Popraw literówkę w tytule"},
    )
    assert back.status_code == 200
    library = (
        await app_client.get(f"{STAFF}/library", headers=headers(recruiter))
    ).json()
    entry = next(row for row in library["recordings"] if row["id"] == training_id)
    assert [item["kind"] for item in entry["files"]] == ["recording"]
    assert (
        await app_client.get(f"{BASE}/trainings/files/{material_id}", headers=stranger)
    ).status_code == 404
    # Bilet z biblioteki nie przeżywa wycofania pliku z biblioteki.
    assert (await app_client.get(material_ticket)).status_code == 403


@pytest.mark.usefixtures("portal_all", "_storage")
async def test_employee_training_needs_no_agreement_and_takes_sign_ups(
    app_client,
) -> None:
    tcm = await make_user(UserRole.talent_community_manager, name="Tamara")
    lecturer = await make_user(UserRole.recruiter, name="Lena")
    listener = await make_user(UserRole.recruiter, name="Lucyna")
    person = await make_person()
    consultant = await session_headers(app_client, person)
    created = await app_client.post(
        STAFF,
        headers=headers(tcm),
        json={
            **_order(deliverables=[]),
            "trainer_user_id": lecturer.id,
            "join_url": "https://teams.microsoft.com/l/meetup-join/x",
        },
    )
    assert created.status_code == 201, created.text
    training_id = created.json()["training"]["id"]
    sent = await app_client.post(f"{STAFF}/{training_id}/send", headers=headers(tcm))
    assert sent.json()["training"]["status"] == "signed"
    assert sent.json()["training"]["can_publish"] is True

    live = (await app_client.get(f"{STAFF}/library", headers=headers(listener))).json()
    row = next(item for item in live["live"] if item["id"] == training_id)
    assert row["registered"] is False and row["join_url"] is None
    joined = await app_client.post(
        f"{STAFF}/library/{training_id}/registration",
        headers=headers(listener),
        json={"join": True},
    )
    assert joined.status_code == 200
    from_panel = await app_client.post(
        f"{BASE}/trainings/{training_id}/registration",
        headers=consultant,
        json={"join": True},
    )
    assert from_panel.status_code == 200
    live = (await app_client.get(f"{STAFF}/library", headers=headers(listener))).json()
    row = next(item for item in live["live"] if item["id"] == training_id)
    assert row["registered"] is True and row["join_url"].startswith("https://")
    people = (
        await app_client.get(f"{STAFF}/{training_id}/people", headers=headers(tcm))
    ).json()
    assert {item["who"] for item in people["registrations"]} == {"staff", "consultant"}


async def test_only_admin_sets_the_sharepoint_folder(app_client) -> None:
    tcm = await make_user(UserRole.talent_community_manager, name="Tamara")
    refused = await app_client.put(
        f"{STAFF}/settings",
        headers=headers(tcm),
        json={"share_url": "https://example.sharepoint.com/:f:/s/x/abc"},
    )
    assert refused.status_code == 403


async def test_big_upload_routes_check_the_caller_before_reading_the_body(
    app_client,
) -> None:
    """Przegląd bezpieczeństwa 13.11.2026: multipart parsował 2 GB przed sesją.

    Surowe ciało czyta dopiero handler, po zależnościach, więc wywołanie bez sesji
    i bez tokenu kończy się odmową, zanim serwer weźmie bajty."""

    pulled: list[int] = []
    multipart = {"Content-Type": "multipart/form-data; boundary=granica"}

    async def body():
        # Atak z przeglądu: multipart bez sesji; dawniej FastAPI zapisywał go
        # na dysk przed sprawdzeniem sesji.
        yield (
            b'--granica\r\nContent-Disposition: form-data; name="file"; '
            b'filename="a.pdf"\r\nContent-Type: application/pdf\r\n\r\n'
        )
        for _ in range(64):
            pulled.append(1)
            yield b"x" * 1024 * 1024
        yield b"\r\n--granica--\r\n"

    portal = await app_client.post(
        f"{BASE}/trainings/1/deliverables/materials", headers=multipart, content=body()
    )
    assert portal.status_code in (401, 404, 415)
    assert len(pulled) <= 2, "panel przeczytał ciało przed sesją"
    pulled.clear()
    staff = await app_client.post(
        f"{STAFF}/1/files?kind=recording", headers=multipart, content=body()
    )
    assert staff.status_code in (401, 403, 415)
    assert len(pulled) <= 2, "NEXUS przeczytał ciało przed tokenem"


async def test_odd_media_ticket_is_refused_not_an_error(app_client) -> None:
    for ticket in ("²9.é", "abc", "", "1.", "99999999999.x"):
        response = await app_client.get(
            f"/api/public/training-media/1?t={quote(ticket)}"
        )
        assert response.status_code == 403, ticket


async def test_cors_lets_the_browser_send_the_file_name(app_client) -> None:
    preflight = await app_client.options(
        "/api/trainings/1/files?kind=recording",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-file-name,content-type,authorization",
        },
    )
    allowed = preflight.headers.get("access-control-allow-headers", "").lower()
    assert "x-file-name" in allowed
