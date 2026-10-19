"""E-teczka — retencja po odejściu: lista „do usunięcia po terminie”, bez automatu.

Ścieżki odmowy: osoba pracująca i osoba, której okres jeszcze trwa, nie są na
liście; usunięcie bez potwierdzenia = 422; pozycja, która przestała być po
terminie (osoba wróciła), jest pomijana z powodem; okresy spoza 10–50 lat
(minimum 10 lat — decyzja Artura 19.10.2026) i nieznany rodzaj = 422; tylko
Kadry. Dane fikcyjne.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.hr_document import HrDocument
from app.models.hr_profile import EmployeeProfile
from app.models.user import User
from app.services.hr import documents_retention
from tests.hr_documents_seed import (
    PREFIX,
    documents_on,  # noqa: F401  (fixture)
    documents_routes,  # noqa: F401  (fixture)
    documents_store_root,  # noqa: F401  (fixture)
    pdf_bytes,
)
from tests.hr_settlements_seed import headers, make_user

pytestmark = pytest.mark.usefixtures(
    "documents_on", "documents_routes", "documents_store_root"
)


async def _hr() -> User:
    return await make_user(
        "recruiter", grants=("people_admin",), profile=False, name="Ewa Kadrowa"
    )


async def _upload(client: AsyncClient, hr: User, user_id: int, kind: str) -> int:
    response = await client.post(
        f"{PREFIX}/people/{user_id}",
        headers=headers(hr),
        data={"kind": kind, "title": f"Dokument {kind}"},
        files={"file": ("plik.pdf", pdf_bytes(), "application/pdf")},
    )
    assert response.status_code == 201, response.text
    return response.json()["document"]["id"]


async def _exit(user_id: int, last_day: date) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(EmployeeProfile)
            .where(EmployeeProfile.user_id == user_id)
            .values(
                employment_status="exited",
                last_working_day=last_day,
                exited_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()


def _years_ago(years: int) -> date:
    today = business_today()
    return date(today.year - years, 6, 30)


async def test_due_lists_only_documents_past_term_of_people_who_left(
    app_client: AsyncClient,
) -> None:
    hr = await _hr()
    long_gone = await make_user(employment_type="b2b", name="Borys Wzorcowy")
    recent = await make_user(employment_type="b2b", name="Anna Przykładowa")
    working = await make_user(employment_type="b2b", name="Ola Nowak")
    old_other = await _upload(app_client, hr, long_gone.id, "other")  # 5 lat
    old_contract = await _upload(app_client, hr, long_gone.id, "contract")  # 10 lat
    recent_other = await _upload(app_client, hr, recent.id, "other")
    working_other = await _upload(app_client, hr, working.id, "other")
    await _exit(long_gone.id, _years_ago(6))
    await _exit(recent.id, _years_ago(1))

    response = await app_client.get(f"{PREFIX}/retention", headers=headers(hr))

    assert response.status_code == 200, response.text
    ids = {row["id"] for row in response.json()["items"]}
    assert old_other in ids
    assert not {old_contract, recent_other, working_other} & ids
    row = next(row for row in response.json()["items"] if row["id"] == old_other)
    assert row["person_name"] == long_gone.name
    assert row["delete_from"] == date(_years_ago(6).year + 6, 1, 1).isoformat()
    kinds = {entry["kind"]: entry["years"] for entry in response.json()["retention"]}
    assert kinds["other"] == 5 and kinds["contract"] == 10


async def test_delete_needs_confirmation_and_rechecks_each_document(
    app_client: AsyncClient,
    documents_store_root,  # noqa: F811
) -> None:
    hr = await _hr()
    gone = await make_user(employment_type="b2b")
    back = await make_user(employment_type="b2b")
    due_id = await _upload(app_client, hr, gone.id, "other")
    returned_id = await _upload(app_client, hr, back.id, "other")
    await _exit(gone.id, _years_ago(7))
    await _exit(back.id, _years_ago(7))
    async with AsyncSessionLocal() as db:
        path = (await db.get(HrDocument, due_id)).file_path
    # Osoba wróciła do pracy po tym, jak Kadry otworzyły listę.
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(EmployeeProfile)
            .where(EmployeeProfile.user_id == back.id)
            .values(employment_status="active", last_working_day=None, exited_at=None)
        )
        await db.commit()

    unconfirmed = await app_client.post(
        f"{PREFIX}/retention/delete",
        headers=headers(hr),
        json={"document_ids": [due_id]},
    )
    deleted = await app_client.post(
        f"{PREFIX}/retention/delete",
        headers=headers(hr),
        json={"document_ids": [due_id, returned_id], "confirm": True},
    )

    assert unconfirmed.status_code == 422
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted"] == [due_id]
    assert deleted.json()["skipped"] == [{"id": returned_id, "reason": "not_due"}]
    assert not (documents_store_root / path).exists()
    async with AsyncSessionLocal() as db:
        trail = await db.get(HrDocument, due_id)
        kept = await db.get(HrDocument, returned_id)
    assert trail.deletion_reason == "retention" and trail.file_path is None
    assert trail.title == "Dokument other"  # ślad zostaje
    assert kept.deleted_at is None and kept.file_path is not None


async def test_longer_retention_takes_document_off_the_list(
    app_client: AsyncClient,
) -> None:
    hr = await _hr()
    gone = await make_user(employment_type="b2b")
    doc_id = await _upload(app_client, hr, gone.id, "other")
    await _exit(gone.id, _years_ago(6))

    saved = await app_client.put(
        f"{PREFIX}/settings/retention",
        headers=headers(hr),
        json={"years": {"other": 12}},
    )
    after = await app_client.get(f"{PREFIX}/retention", headers=headers(hr))

    assert saved.status_code == 200, saved.text
    assert {e["kind"]: e["years"] for e in saved.json()["retention"]}["other"] == 12
    assert doc_id not in {row["id"] for row in after.json()["items"]}


@pytest.mark.parametrize(
    "years", [{"other": 0}, {"other": 9}, {"contract": 9}, {"other": 51}, {"nda": 5}]
)
async def test_retention_settings_refuse_bad_values(
    app_client: AsyncClient, years
) -> None:
    hr = await _hr()
    response = await app_client.put(
        f"{PREFIX}/settings/retention", headers=headers(hr), json={"years": years}
    )
    assert response.status_code == 422


async def test_nothing_is_deleted_without_a_person_clicking() -> None:
    """Sama lista nic nie kasuje — wywołanie ``due`` nie zmienia żadnego wiersza."""

    hr = await _hr()
    gone = await make_user(employment_type="b2b")
    async with AsyncSessionLocal() as db:
        from app.services.hr import documents

        actor = await db.get(User, hr.id)
        document, _ = await documents.upload(
            db,
            user_id=gone.id,
            kind="other",
            title="Notatka",
            content=pdf_bytes(),
            file_name=None,
            valid_until=None,
            purpose=None,
            audience=None,
            actor=actor,
        )
        await db.commit()
    await _exit(gone.id, _years_ago(9))

    async with AsyncSessionLocal() as db:
        listed = await documents_retention.due(db)
        await db.commit()
    async with AsyncSessionLocal() as db:
        still = await db.scalar(select(HrDocument).where(HrDocument.id == document.id))

    assert document.id in {item.document.id for item in listed}
    assert still.deleted_at is None and still.file_path is not None
