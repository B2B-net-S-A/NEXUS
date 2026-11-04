"""Dopisek w imieniu na trasach kandydata (D6, 13.10.2026).

Ręczny wpis (``POST /api/candidates``, pola formularza ``/from-cv``, zmiana
w ``PATCH``) dostaje 422 ze zdaniem przy polu — front pokazuje je pod polem
(``loc = ["body", "name"|"lastname"]``, ``type = "candidate_name_marker"``).
Stary dopisek z importu NIE blokuje edycji innych pól, a ścieżki automatyczne
(``/bulk-import``) zdejmują go po cichu.

Baza testowa jest współdzielona: każdy scenariusz ma własny sufiks i sprząta.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.index_outbox import IndexOutboxEvent
from app.services.candidate_name_rules import name_marker_message


def _tag() -> str:
    return f"Dopisek{uuid.uuid4().hex[:8]}"


def _marker_error(field: str) -> dict:
    return {
        "loc": ["body", field],
        "msg": name_marker_message(),
        "type": "candidate_name_marker",
    }


async def _drop(*ids: int) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(IndexOutboxEvent).where(
                IndexOutboxEvent.entity_type == "candidate",
                IndexOutboxEvent.entity_id.in_(ids),
            )
        )
        await db.execute(delete(Candidate).where(Candidate.id.in_(ids)))
        await db.commit()


async def test_create_with_marker_is_refused_at_the_field(
    app_client: AsyncClient, app_auth_headers: dict
):
    resp = await app_client.post(
        "/api/candidates",
        json={"name": "[ACTIVE] Jan", "lastname": f"{_tag()} (czarna lista)"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == [_marker_error("name"), _marker_error("lastname")]


async def test_create_with_second_surname_in_brackets_passes(
    app_client: AsyncClient, app_auth_headers: dict
):
    resp = await app_client.post(
        "/api/candidates",
        json={"name": "Anna (Kowalska)", "lastname": _tag()},
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text
    await _drop(resp.json()["id"])


async def test_patch_refuses_only_a_changed_name_with_marker(
    app_client: AsyncClient, app_auth_headers: dict
):
    tag = _tag()
    async with AsyncSessionLocal() as db:
        legacy = Candidate(name="Jan [ACTIVE]", lastname=tag)
        db.add(legacy)
        await db.commit()
        candidate_id = legacy.id
    try:
        # Okno edycji wysyła imię i nazwisko przy każdym zapisie — stary
        # dopisek z importu nie blokuje zmiany telefonu.
        unchanged = await app_client.patch(
            f"/api/candidates/{candidate_id}",
            json={"name": "Jan [ACTIVE]", "lastname": tag, "phone": "+48 500 600 700"},
            headers=app_auth_headers,
        )
        assert unchanged.status_code == 200, unchanged.text

        changed = await app_client.patch(
            f"/api/candidates/{candidate_id}",
            json={"name": "Jan (zaakceptowany)", "lastname": tag},
            headers=app_auth_headers,
        )
        assert changed.status_code == 422, changed.text
        assert changed.json()["detail"] == [_marker_error("name")]

        fixed = await app_client.patch(
            f"/api/candidates/{candidate_id}",
            json={"name": "Jan", "lastname": tag},
            headers=app_auth_headers,
        )
        assert fixed.status_code == 200, fixed.text
        assert fixed.json()["name"] == "Jan"
    finally:
        await _drop(candidate_id)


async def test_bulk_import_strips_the_marker_instead_of_refusing(
    app_client: AsyncClient, app_auth_headers: dict
):
    tag = _tag()
    resp = await app_client.post(
        "/api/candidates/bulk-import",
        json=[{"name": "[ACTIVE] Jan", "lastname": f"{tag} (zaakceptowany)"}],
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text
    ids = resp.json()["ids"]
    try:
        assert len(ids) == 1
        async with AsyncSessionLocal() as db:
            created = await db.get(Candidate, ids[0])
            assert (created.name, created.lastname) == ("Jan", tag)
    finally:
        await _drop(*ids)


async def test_from_cv_form_name_with_marker_is_refused_before_the_paid_read(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    async def _must_not_run(*_a, **_kw):  # pragma: no cover — nie wolno
        raise AssertionError("odczyt CV przed odmową imienia z dopiskiem")

    monkeypatch.setattr(
        "app.services.cv_parser._parse_with_claude", _must_not_run, raising=True
    )
    resp = await app_client.post(
        "/api/candidates/from-cv",
        headers=app_auth_headers,
        files={"file": ("cv.pdf", b"%PDF-1.4 dopisek", "application/pdf")},
        data={"name": "Jan", "lastname": f"{_tag()} (CIPP/E)"},
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == [_marker_error("lastname")]
