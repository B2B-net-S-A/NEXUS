"""Szkolenia po analizie 13.11.2026: link dla trenera, stan szkolenia pracownika,
plik TCM dla uczestników. Dane fikcyjne — repo jest publiczne."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.scheduling import business_today
from app.models.user import UserRole
from tests.care_announcements_seed import headers, make_user
from tests.consultant_portal_seed import (  # noqa: F401  (fixture'y)
    BASE,
    install_mailer,
    make_person,
    portal_all,
    portal_restored,
    session_headers,
)
from tests.test_trainings_flow import MP4, PDF, STAFF, _order, _raw, _signed, _storage  # noqa: F401

JOIN = "https://teams.microsoft.com/l/meetup-join/19%3ameeting_test"


@pytest.mark.usefixtures("portal_all")
async def test_trainer_gets_the_meeting_link_only_after_signing(
    app_client, monkeypatch
) -> None:
    install_mailer(monkeypatch)
    person = await make_person()
    tcm = await make_user(UserRole.talent_community_manager, name="Tamara")
    trainer = await session_headers(app_client, person)
    created = await app_client.post(
        STAFF,
        headers=headers(tcm),
        json={**_order(), "trainer_contract_id": person.contract_id, "join_url": JOIN},
    )
    training_id = created.json()["training"]["id"]
    await app_client.post(f"{STAFF}/{training_id}/send", headers=headers(tcm))

    before = await app_client.get(f"{BASE}/trainings/{training_id}", headers=trainer)
    assert before.json()["training"]["join_url"] is None

    await _signed(training_id)
    after = await app_client.get(f"{BASE}/trainings/{training_id}", headers=trainer)
    assert after.json()["training"]["join_url"] == JOIN
    assert after.json()["training"]["status_label"] == "Umowa podpisana"
    # W kalendarzu panelu własne szkolenie jest „Prowadzisz”, z linkiem, bez zapisu.
    panel = (await app_client.get(f"{BASE}/trainings", headers=trainer)).json()
    row = next(r for r in panel["library"]["live"] if r["id"] == training_id)
    assert row["leading"] is True and row["join_url"] == JOIN and row["registered"] is False


@pytest.mark.usefixtures("_storage")
async def test_employee_training_is_ready_not_signed_and_tcm_file_can_go_out(
    app_client,
) -> None:
    tcm = await make_user(UserRole.talent_community_manager, name="Tamara")
    second = await make_user(UserRole.talent_community_manager, name="Teresa")
    lecturer = await make_user(UserRole.recruiter, name="Lena")
    listener = await make_user(UserRole.recruiter, name="Lucyna")
    created = await app_client.post(
        STAFF,
        headers=headers(tcm),
        json={
            **_order(
                deliverables=[],
                session_date=(business_today() - timedelta(days=1)).isoformat(),
            ),
            "trainer_user_id": lecturer.id,
        },
    )
    training_id = created.json()["training"]["id"]
    sent = await app_client.post(f"{STAFF}/{training_id}/send", headers=headers(tcm))
    assert sent.json()["training"]["status"] == "signed"
    assert sent.json()["training"]["status_label"] == "Gotowe do szkolenia"
    listed = (await app_client.get(STAFF, headers=headers(tcm))).json()
    row = next(r for r in listed["trainings"] if r["id"] == training_id)
    assert row["status_label"] == "Gotowe do szkolenia"

    await app_client.post(
        f"{STAFF}/{training_id}/files?kind=recording",
        headers={**headers(tcm), **_raw("nagranie.mp4", "video/mp4")},
        content=MP4,
    )
    uploaded = await app_client.post(
        f"{STAFF}/{training_id}/files?kind=internal",
        headers={**headers(tcm), **_raw("sciaga.pdf", "application/pdf")},
        content=PDF,
    )
    internal = next(
        f for f in uploaded.json()["training"]["files"] if f["kind"] == "internal"
    )
    assert internal["for_participants"] is False
    shared = await app_client.put(
        f"{STAFF}/{training_id}/files/{internal['id']}/participants",
        headers=headers(tcm),
        json={"value": True},
    )
    assert shared.status_code == 200, shared.text

    published = await app_client.post(
        f"{STAFF}/{training_id}/publish",
        headers=headers(second),
        json={"publish": True},
    )
    assert published.status_code == 200, published.text
    library = (
        await app_client.get(f"{STAFF}/library", headers=headers(listener))
    ).json()
    item = next(r for r in library["recordings"] if r["id"] == training_id)
    assert {f["file_name"] for f in item["files"]} == {"nagranie.mp4", "sciaga.pdf"}
