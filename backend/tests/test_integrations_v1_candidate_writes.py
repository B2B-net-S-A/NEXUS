"""API v1: nowy kandydat, wgranie CV, notatka (``candidates:write``, ``notes:write``).

Dwie części:

* bez bazy — ciała ekranu wydzielone 15.10.2026 (``apply_candidate_create``,
  ``_ingest_candidate_cv_file``, ``_attach_candidate_document``,
  ``apply_note_create``) na atrapie sesji: konto serwisowe nie dostaje
  ``UserActivity``, nikogo nie oznacza i pisze notatkę systemową, a osoba
  z ekranu dostaje dokładnie to, co przed wydzieleniem;
* z bazą (CI) — trasy v1 przez HTTP: sukces, 403 bez scope'u, powtórka
  z paragonu, duplikat e-maila 409 z ``candidate_id``, dopisek w imieniu 422,
  notatka systemowa bez autora, CV jako główny plik, brak ``UserActivity``.

Dane są zmyślone (repo jest publiczne).
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.candidate_document import CandidateDocument, CandidateDocumentKind
from app.models.note import SYSTEM_NOTE_SOURCE, Note
from app.models.note_mention import NoteMention
from app.models.notification import Notification
from app.models.user import User
from app.models.user_activity import UserActivity
from app.schemas.candidate import CandidateCreate
from app.schemas.note import NoteCreate
from app.services.integration_actor import IntegrationActor
from app.services.write_author import WriteAuthor
from tests.test_service_accounts import _account_with_key

V1 = "/api/integrations/v1"
SERVICE = WriteAuthor.service_account(
    IntegrationActor(name="Integracja: Rozliczenia", service_account_id=3)
)
PERSON = SimpleNamespace(id=4, name="Ola Testowa", email="ola.testowa@example.com")


# ── Bez bazy: atrapa sesji ───────────────────────────────────────────────────


class _Nested:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _Session:
    """Sesja bez bazy: ``add``/``flush`` nadają id, ``execute`` oddaje wiersze."""

    def __init__(self, rows=(), gets=None):
        self.added: list = []
        self._rows = list(rows)
        self._gets = gets or {}
        self._next_id = 900

    def add(self, obj) -> None:
        self.added.append(obj)

    def begin_nested(self) -> _Nested:
        return _Nested()

    async def flush(self) -> None:
        for obj in self.added:
            if hasattr(obj, "id") and getattr(obj, "id", None) is None:
                obj.id = self._next_id
                self._next_id += 1

    async def execute(self, *_a, **_kw):
        return _Rows(self._rows)

    async def refresh(self, *_a, **_kw) -> None:
        return None

    async def get(self, model, ident):
        return self._gets.get((model.__name__, ident))

    def of(self, cls) -> list:
        return [obj for obj in self.added if isinstance(obj, cls)]


def test_write_author_person_and_service_account() -> None:
    person = WriteAuthor.person(SimpleNamespace(id=7, name=None, email="a@example.com"))
    assert (person.user_id, person.label, person.is_integration) == (
        7,
        "a@example.com",
        False,
    )
    assert (SERVICE.user, SERVICE.user_id, SERVICE.label, SERVICE.is_integration) == (
        None,
        None,
        "Integracja: Rozliczenia",
        True,
    )


# ── Bez bazy: wejście v1 ─────────────────────────────────────────────────────


def _body(**overrides):
    from app.api.integrations_v1.candidate_writes import CandidateCreateIn

    data = {
        "first_name": " Ola ",
        "last_name": "Testowa",
        "email": "ola.testowa@example.com",
    }
    data.update(overrides)
    return CandidateCreateIn.model_validate(data)


def test_input_strips_names_and_canonicalises_linkedin() -> None:
    body = _body(linkedin_url="pl.linkedin.com/in/ola-testowa/?trk=x")
    assert body.first_name == "Ola"
    assert body.linkedin_url == "https://linkedin.com/in/ola-testowa"


@pytest.mark.parametrize(
    "overrides",
    [
        {"nickname": "Ola"},  # nieznane pole
        {"linkedin_url": "https://www.linkedin.com/company/przyklad"},
        {"email": None},
        {"first_name": "   "},
    ],
)
def test_input_refuses_what_the_screen_would_store_wrongly(overrides) -> None:
    with pytest.raises(ValidationError):
        _body(**overrides)


def test_name_marker_is_422_at_the_v1_field() -> None:
    from app.api.integrations_v1.candidate_writes import _reject_name_markers

    _reject_name_markers(_body())  # czyste imię przechodzi
    with pytest.raises(HTTPException) as caught:
        _reject_name_markers(_body(first_name="[ACTIVE] Ola"))
    assert caught.value.status_code == 422
    errors = caught.value.detail["errors"]
    assert [e["loc"] for e in errors] == [["body", "first_name"]]
    assert errors[0]["type"] == "candidate_name_marker"


def test_screen_model_gets_the_v1_fields() -> None:
    from app.api.integrations_v1.candidate_writes import _screen_candidate

    data = _screen_candidate(
        _body(
            linkedin_url="linkedin.com/in/ola-testowa",
            country="pl",
            skills=["Python"],
            source="automat",
        )
    )
    assert isinstance(data, CandidateCreate)
    assert (data.name, data.lastname, data.email) == (
        "Ola",
        "Testowa",
        "ola.testowa@example.com",
    )
    assert data.linkedin == "https://linkedin.com/in/ola-testowa"
    assert data.country == "PL"
    assert data.skills == [{"name": "Python", "level": None}]


# ── Bez bazy: ciało „Dodaj kandydata” ────────────────────────────────────────


def _patch_create(monkeypatch, managers):
    from app.api import candidates as candidates_api
    from app.services import index_outbox_service, teams_notifications

    captured: dict = {}

    async def _recipients(_db, ids, *_a, **_kw):
        list(ids)
        return managers

    def _payload(**kwargs):
        captured["recruiter"] = kwargs["recruiter_name"]
        return {}

    def _spawn(coro, name):
        captured["spawned"] = name
        coro.close()

    monkeypatch.setattr(
        candidates_api, "find_candidate_by_email", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(candidates_api, "filter_notification_recipients", _recipients)
    monkeypatch.setattr(candidates_api, "spawn", _spawn)
    monkeypatch.setattr(
        candidates_api, "ws_manager", SimpleNamespace(notify_user=AsyncMock())
    )
    monkeypatch.setattr(teams_notifications, "candidate_payload", _payload)
    monkeypatch.setattr(teams_notifications, "notify_teams", AsyncMock())
    embed = AsyncMock(return_value=True)
    monkeypatch.setattr(index_outbox_service, "schedule_or_embed_candidate", embed)
    return captured, embed


def _new_candidate() -> CandidateCreate:
    return CandidateCreate(name="Ola", lastname="Testowa", email="ola@example.com")


async def test_service_account_create_has_no_user_activity(monkeypatch) -> None:
    from app.api.candidates import apply_candidate_create

    managers = [SimpleNamespace(id=1), SimpleNamespace(id=2)]
    captured, embed = _patch_create(monkeypatch, managers)
    db = _Session(rows=managers)

    candidate = await apply_candidate_create(db, _new_candidate(), author=SERVICE)

    assert candidate.created_by is None
    assert [(a.action, a.user_id) for a in db.of(Activity)] == [("created", None)]
    assert db.of(UserActivity) == []
    # Żaden admin nie jest autorem, więc dzwonek dostają wszyscy.
    assert sorted(n.user_id for n in db.of(Notification)) == [1, 2]
    assert captured == {
        "recruiter": "Integracja: Rozliczenia",
        "spawned": "teams_notify:candidate_added",
    }
    embed.assert_awaited_once_with(candidate.id, db)


async def test_person_create_is_unchanged(monkeypatch) -> None:
    from app.api.candidates import apply_candidate_create

    managers = [SimpleNamespace(id=4), SimpleNamespace(id=2)]
    captured, embed = _patch_create(monkeypatch, managers)
    db = _Session(rows=managers)

    candidate = await apply_candidate_create(
        db, _new_candidate(), author=WriteAuthor.person(PERSON)
    )

    assert candidate.created_by == 4
    assert [(a.action, a.user_id) for a in db.of(Activity)] == [("created", 4)]
    [ranking] = db.of(UserActivity)
    assert ranking.user_id == 4 and ranking.entity_id == candidate.id
    # Autor nie dostaje dzwonka o własnym kandydacie.
    assert [n.user_id for n in db.of(Notification)] == [2]
    assert captured["recruiter"] == "Ola Testowa"
    embed.assert_awaited_once()


async def test_duplicate_email_in_the_body_is_409(monkeypatch) -> None:
    from app.api import candidates as candidates_api

    _patch_create(monkeypatch, [])
    monkeypatch.setattr(
        candidates_api,
        "find_candidate_by_email",
        AsyncMock(return_value=[{"candidate_id": 77}]),
    )
    db = _Session()
    with pytest.raises(HTTPException) as caught:
        await candidates_api.apply_candidate_create(
            db, _new_candidate(), author=SERVICE
        )
    assert caught.value.status_code == 409
    assert db.added == []


# ── Bez bazy: CV ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("user_id", [None, 7])
async def test_cv_ingest_writes_ranking_only_for_a_person(
    monkeypatch, tmp_path, user_id
) -> None:
    from app.api import candidates as candidates_api

    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    store = AsyncMock(return_value=SimpleNamespace(id=1, content_sha256="h"))
    monkeypatch.setattr(candidates_api, "_store_candidate_cv_document", store)
    db = _Session()
    candidate = SimpleNamespace(id=42, cv_filename=None)

    await candidates_api._ingest_candidate_cv_file(
        db,
        candidate=candidate,
        content=b"%PDF-1.4 cv",
        safe_filename="cv.pdf",
        content_type="application/pdf",
        user_id=user_id,
    )

    assert store.await_args.kwargs["uploaded_by"] == user_id
    assert candidate.cv_filename == "cv.pdf"
    assert [(a.action, a.user_id) for a in db.of(Activity)] == [
        ("cv_uploaded", user_id)
    ]
    assert len(db.of(UserActivity)) == (0 if user_id is None else 1)
    assert (tmp_path / "candidate_42_cv.pdf").read_bytes() == b"%PDF-1.4 cv"


async def test_attached_document_keeps_the_screen_activity(monkeypatch) -> None:
    from app.api import candidates as candidates_api

    store = AsyncMock(return_value=SimpleNamespace(id=5))
    monkeypatch.setattr(candidates_api, "_store_candidate_document", store)
    db = _Session()

    document = await candidates_api._attach_candidate_document(
        db,
        candidate_id=42,
        safe_filename="cv-en.pdf",
        content=b"%PDF-1.4 en",
        content_type="application/pdf",
        kind=CandidateDocumentKind.cv,
        user_id=None,
    )

    assert document.id == 5
    kwargs = store.await_args.kwargs
    assert (kwargs["is_primary"], kwargs["uploaded_by"]) == (False, None)
    [activity] = db.of(Activity)
    assert (activity.action, activity.user_id) == ("document_uploaded", None)
    assert activity.details == {"filename": "cv-en.pdf", "document_kind": "cv"}


# ── Bez bazy: notatka ────────────────────────────────────────────────────────


def _patch_note(monkeypatch):
    from app.api import notes as notes_api

    resolve = AsyncMock(return_value=[5, 4])
    enqueue = AsyncMock(return_value=[])
    monkeypatch.setattr(notes_api, "_resolve_mentions", resolve)
    monkeypatch.setattr(notes_api, "enqueue_mention_notifications", enqueue)
    monkeypatch.setattr(notes_api, "_mention_snippet", AsyncMock(return_value="x"))
    monkeypatch.setattr(
        notes_api, "build_note_context_label", AsyncMock(return_value="notatce")
    )
    monkeypatch.setattr(notes_api, "_refresh_rate_from_after_dl_pair", AsyncMock())
    return resolve, enqueue


def _note_session(candidate) -> _Session:
    return _Session(rows=[candidate], gets={("Candidate", 42): candidate})


async def test_service_account_note_is_system_without_mentions(monkeypatch) -> None:
    from app.api.notes import apply_note_create

    resolve, enqueue = _patch_note(monkeypatch)
    candidate = SimpleNamespace(id=42, notes_count=2)
    db = _note_session(candidate)

    created = await apply_note_create(
        db,
        NoteCreate(content="Rozmowa z automatu @ola.testowa", candidate_id=42),
        author=SERVICE,
    )

    note = created.note
    assert (note.author_id, note.external_source) == (None, SYSTEM_NOTE_SOURCE)
    resolve.assert_not_awaited()
    enqueue.assert_not_awaited()
    assert db.of(NoteMention) == [] and db.of(UserActivity) == []
    assert (created.pairs, created.reply_pairs) == ([], [])
    assert candidate.notes_count == 3


async def test_person_note_is_unchanged(monkeypatch) -> None:
    from app.api.notes import apply_note_create

    resolve, enqueue = _patch_note(monkeypatch)
    candidate = SimpleNamespace(id=42, notes_count=0)
    db = _note_session(candidate)

    created = await apply_note_create(
        db,
        NoteCreate(content="Rozmowa @ola", candidate_id=42),
        author=WriteAuthor.person(PERSON),
    )

    assert (created.note.author_id, created.note.external_source) == (4, None)
    resolve.assert_awaited_once()
    # Autor nie oznacza sam siebie.
    assert [m.user_id for m in db.of(NoteMention)] == [5]
    assert enqueue.await_args.kwargs["author"] is PERSON
    assert enqueue.await_args.kwargs["notification_title"] == (
        "Ola Testowa oznaczył(a) Cię w notatce"
    )
    [ranking] = db.of(UserActivity)
    assert (ranking.user_id, ranking.entity_id) == (4, 42)
    assert ranking.details["mentioned_count"] == 1
    assert candidate.notes_count == 1


async def test_oauth_integration_person_still_writes_a_system_note(monkeypatch) -> None:
    """Token klienta OAuth (scraper) ma konto osoby — notatka systemowa jak
    przed wydzieleniem (``candidate_claim.is_integration_request``)."""
    from app.api.notes import apply_note_create

    _patch_note(monkeypatch)
    db = _note_session(SimpleNamespace(id=42, notes_count=0))
    created = await apply_note_create(
        db,
        NoteCreate(content="Wpis scrapera", candidate_id=42),
        author=WriteAuthor.person(PERSON, is_integration=True),
    )
    assert (created.note.author_id, created.note.external_source) == (
        4,
        SYSTEM_NOTE_SOURCE,
    )


# ── Z bazą (CI): trasy v1 ────────────────────────────────────────────────────


async def _key(app_client: AsyncClient, headers: dict, scopes: list[str]):
    account, api_key, _ = await _account_with_key(app_client, headers, scopes)
    return account, api_key


def _h(api_key: str, idem: str | None = None) -> dict:
    out = {"X-API-Key": api_key}
    if idem is not None:
        out["Idempotency-Key"] = idem
    return out


def _new(**overrides) -> dict:
    u = uuid.uuid4().hex[:8]
    data = {
        "first_name": "Ola",
        "last_name": f"Testowa-{u}",
        "email": f"v1-cw-{u}@example.com",
    }
    data.update(overrides)
    return data


async def _seed_candidate() -> int:
    u = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Ewa", lastname=f"Seed-{u}", email=f"v1-cw-seed-{u}@example.com"
        )
        db.add(cand)
        await db.commit()
        return cand.id


async def _ranking_rows(candidate_id: int) -> int:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(func.count())
            .select_from(UserActivity)
            .where(
                UserActivity.entity_type == "candidate",
                UserActivity.entity_id == candidate_id,
            )
        )


class TestCreateCandidate:
    async def test_creates_with_service_account_author(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        account, api_key = await _key(
            app_client, app_auth_headers, ["candidates:write"]
        )
        payload = _new(phone="+48 600 000 000", skills=["Python"], source="automat")
        resp = await app_client.post(
            f"{V1}/candidates", headers=_h(api_key, str(uuid.uuid4())), json=payload
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["created"] is True
        candidate_id = body["id"]

        admin_email = app_client.headers.get("X-Test-Admin-Email")
        async with AsyncSessionLocal() as db:
            cand = await db.get(Candidate, candidate_id)
            assert cand.created_by is None
            assert (cand.name, cand.email) == ("Ola", payload["email"])
            activity = await db.scalar(
                select(Activity).where(
                    Activity.entity_type == "candidate",
                    Activity.entity_id == candidate_id,
                    Activity.action == "created",
                )
            )
            assert activity.user_id is None
            assert activity.details["via"] == f"integration:{account['slug']}"
            admin_id = await db.scalar(select(User.id).where(User.email == admin_email))
            bell = await db.scalar(
                select(func.count())
                .select_from(Notification)
                .where(
                    Notification.user_id == admin_id,
                    Notification.link == f"/candidates/{candidate_id}",
                )
            )
        assert bell == 1
        assert await _ranking_rows(candidate_id) == 0

    async def test_replay_returns_the_same_candidate_once(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        _, api_key = await _key(app_client, app_auth_headers, ["candidates:write"])
        idem = str(uuid.uuid4())
        payload = _new()
        first = await app_client.post(
            f"{V1}/candidates", headers=_h(api_key, idem), json=payload
        )
        assert first.status_code == 201, first.text
        again = await app_client.post(
            f"{V1}/candidates", headers=_h(api_key, idem), json=payload
        )
        assert again.status_code == 201, again.text
        assert again.headers.get("Idempotent-Replayed") == "true"
        assert again.json() == first.json()
        async with AsyncSessionLocal() as db:
            count = await db.scalar(
                select(func.count())
                .select_from(Candidate)
                .where(Candidate.email == payload["email"])
            )
        assert count == 1

    async def test_same_email_is_409_with_only_the_candidate_id(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        existing_id = await _seed_candidate()
        async with AsyncSessionLocal() as db:
            email = (await db.get(Candidate, existing_id)).email
        _, api_key = await _key(app_client, app_auth_headers, ["candidates:write"])
        for params in ({}, {"dry_run": "true"}):
            resp = await app_client.post(
                f"{V1}/candidates",
                headers=_h(api_key, str(uuid.uuid4())),
                params=params,
                json=_new(email=f"  {email.upper()} "),
            )
            assert resp.status_code == 409, resp.text
            error = resp.json()["error"]
            assert error["code"] == "duplicate_candidate"
            assert error["details"] == {"candidate_id": existing_id}

    async def test_email_of_an_erased_person_is_409_without_data(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        """Osoba usunięta na żądanie (RODO) nie wraca z automatu — ekran tego
        nie sprawdza, bo tam decyduje człowiek."""
        from app.models.purged_candidate import PurgedCandidate
        from app.services.candidate_audit import (
            EMAIL_TOMBSTONE_SOURCE,
            candidate_email_tombstone,
        )

        email = f"v1-erased-{uuid.uuid4().hex[:8]}@example.com"
        async with AsyncSessionLocal() as db:
            db.add(
                PurgedCandidate(
                    external_source=EMAIL_TOMBSTONE_SOURCE,
                    external_id_hash=candidate_email_tombstone(email),
                )
            )
            await db.commit()
        _, api_key = await _key(app_client, app_auth_headers, ["candidates:write"])
        for params in ({}, {"dry_run": "true"}):
            resp = await app_client.post(
                f"{V1}/candidates",
                headers=_h(api_key, str(uuid.uuid4())),
                params=params,
                json=_new(email=email.upper()),
            )
            assert resp.status_code == 409, resp.text
            error = resp.json()["error"]
            assert error["code"] == "candidate_erased"
            assert "candidate_id" not in (error.get("details") or {})
        async with AsyncSessionLocal() as db:
            assert (
                await db.scalar(
                    select(func.count(Candidate.id)).where(
                        func.lower(Candidate.email) == email
                    )
                )
                == 0
            )

    async def test_name_marker_is_422(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        _, api_key = await _key(app_client, app_auth_headers, ["candidates:write"])
        resp = await app_client.post(
            f"{V1}/candidates",
            headers=_h(api_key, str(uuid.uuid4())),
            json=_new(last_name="Testowa (czarna lista)"),
        )
        assert resp.status_code == 422, resp.text
        error = resp.json()["error"]
        assert error["code"] == "validation_error"
        assert error["details"]["errors"][0]["loc"] == ["body", "last_name"]
        assert error["details"]["errors"][0]["type"] == "candidate_name_marker"

    async def test_dry_run_writes_nothing(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        _, api_key = await _key(app_client, app_auth_headers, ["candidates:write"])
        payload = _new()
        resp = await app_client.post(
            f"{V1}/candidates",
            headers=_h(api_key),
            params={"dry_run": "true"},
            json=payload,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"valid": True, "dry_run": True}
        async with AsyncSessionLocal() as db:
            assert (
                await db.scalar(
                    select(Candidate.id).where(Candidate.email == payload["email"])
                )
            ) is None

    async def test_requires_scope_and_idempotency_key(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        _, read_only = await _key(app_client, app_auth_headers, ["candidates:read"])
        resp = await app_client.post(
            f"{V1}/candidates", headers=_h(read_only, str(uuid.uuid4())), json=_new()
        )
        assert resp.status_code == 403, resp.text
        assert resp.json()["error"]["code"] == "insufficient_scope"

        _, writer = await _key(app_client, app_auth_headers, ["candidates:write"])
        resp = await app_client.post(
            f"{V1}/candidates", headers=_h(writer), json=_new()
        )
        assert resp.status_code == 400, resp.text
        assert resp.json()["error"]["code"] == "idempotency_key_required"

        resp = await app_client.post(
            f"{V1}/candidates",
            headers=_h(writer, str(uuid.uuid4())),
            json={**_new(), "status": "blacklisted"},
        )
        assert resp.status_code == 422, resp.text


@pytest.fixture
def _cv_env(monkeypatch, tmp_path):
    """Pliki do katalogu testu; odczyt AI w tle zastąpiony atrapą."""
    from app.api import candidates as candidates_api

    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    enrich = AsyncMock()
    monkeypatch.setattr(candidates_api, "_enrich_candidate_from_document_task", enrich)
    return enrich


def _pdf(tag: str) -> dict:
    return {"file": ("cv.pdf", f"%PDF-1.4 {tag}".encode(), "application/pdf")}


class TestUploadCv:
    async def test_upload_becomes_primary_and_is_read_after_commit(
        self, app_client: AsyncClient, app_auth_headers: dict, _cv_env
    ):
        candidate_id = await _seed_candidate()
        account, api_key = await _key(
            app_client, app_auth_headers, ["candidates:write"]
        )
        idem = str(uuid.uuid4())
        files = _pdf(uuid.uuid4().hex)
        resp = await app_client.post(
            f"{V1}/candidates/{candidate_id}/cv",
            headers=_h(api_key, idem),
            files=files,
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["is_primary"] is True

        async with AsyncSessionLocal() as db:
            doc = await db.get(CandidateDocument, body["document_id"])
            assert (doc.candidate_id, doc.document_kind, doc.is_primary) == (
                candidate_id,
                CandidateDocumentKind.cv,
                True,
            )
            assert doc.uploaded_by is None
            assert (await db.get(Candidate, candidate_id)).cv_filename == "cv.pdf"
            activity = await db.scalar(
                select(Activity).where(
                    Activity.entity_type == "candidate",
                    Activity.entity_id == candidate_id,
                    Activity.action == "cv_uploaded",
                )
            )
            assert activity.user_id is None
            assert activity.details["via"] == f"integration:{account['slug']}"
        assert await _ranking_rows(candidate_id) == 0
        _cv_env.assert_awaited_once()
        assert _cv_env.await_args.args[:2] == (candidate_id, body["document_id"])

        replay = await app_client.post(
            f"{V1}/candidates/{candidate_id}/cv",
            headers=_h(api_key, idem),
            files=files,
        )
        assert replay.status_code == 201, replay.text
        assert replay.headers.get("Idempotent-Replayed") == "true"
        assert replay.json() == body
        _cv_env.assert_awaited_once()  # powtórka nie czyta CV drugi raz

    async def test_second_file_without_make_primary_stays_beside(
        self, app_client: AsyncClient, app_auth_headers: dict, _cv_env
    ):
        candidate_id = await _seed_candidate()
        _, api_key = await _key(app_client, app_auth_headers, ["candidates:write"])
        first = await app_client.post(
            f"{V1}/candidates/{candidate_id}/cv",
            headers=_h(api_key, str(uuid.uuid4())),
            files=_pdf(uuid.uuid4().hex),
            data={"make_primary": "false"},
        )
        assert first.status_code == 201, first.text
        # Osoba nie miała głównego CV — pierwszy plik nim zostaje.
        assert first.json()["is_primary"] is True
        second = await app_client.post(
            f"{V1}/candidates/{candidate_id}/cv",
            headers=_h(api_key, str(uuid.uuid4())),
            files=_pdf(uuid.uuid4().hex),
            data={"make_primary": "false"},
        )
        assert second.status_code == 201, second.text
        assert second.json()["is_primary"] is False
        assert _cv_env.await_count == 1

    async def test_refusals(
        self, app_client: AsyncClient, app_auth_headers: dict, _cv_env
    ):
        candidate_id = await _seed_candidate()
        _, notes_only = await _key(app_client, app_auth_headers, ["notes:write"])
        resp = await app_client.post(
            f"{V1}/candidates/{candidate_id}/cv",
            headers=_h(notes_only, str(uuid.uuid4())),
            files=_pdf("x"),
        )
        assert resp.status_code == 403, resp.text

        _, api_key = await _key(app_client, app_auth_headers, ["candidates:write"])
        resp = await app_client.post(
            f"{V1}/candidates/{candidate_id}/cv",
            headers=_h(api_key, str(uuid.uuid4())),
            files={"file": ("cv.txt", b"tekst", "text/plain")},
        )
        assert resp.status_code == 415, resp.text
        assert resp.json()["error"]["code"] == "unsupported_media_type"

        resp = await app_client.post(
            f"{V1}/candidates/2000000000/cv",
            headers=_h(api_key, str(uuid.uuid4())),
            files=_pdf("x"),
        )
        assert resp.status_code == 404, resp.text
        _cv_env.assert_not_awaited()


class TestCreateNote:
    async def test_note_is_a_system_note_without_author(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        candidate_id = await _seed_candidate()
        admin_email = app_client.headers.get("X-Test-Admin-Email")
        account, api_key = await _key(app_client, app_auth_headers, ["notes:write"])
        idem = str(uuid.uuid4())
        payload = {"content": f"Wpis z automatu, do wiadomości @{admin_email}"}
        resp = await app_client.post(
            f"{V1}/candidates/{candidate_id}/notes",
            headers=_h(api_key, idem),
            json=payload,
        )
        assert resp.status_code == 201, resp.text
        note_id = resp.json()["note_id"]

        async with AsyncSessionLocal() as db:
            note = await db.get(Note, note_id)
            assert (note.candidate_id, note.author_id) == (candidate_id, None)
            assert note.external_source == SYSTEM_NOTE_SOURCE
            # Odczyt notatek pokaże „Integracja: <konto>” ze stempla.
            assert note.source_ref == f"integration:{account['slug']}"
            mentions = await db.scalar(
                select(func.count())
                .select_from(NoteMention)
                .where(NoteMention.note_id == note_id)
            )
            assert mentions == 0
            assert (await db.get(Candidate, candidate_id)).notes_count == 1
        assert await _ranking_rows(candidate_id) == 0

        replay = await app_client.post(
            f"{V1}/candidates/{candidate_id}/notes",
            headers=_h(api_key, idem),
            json=payload,
        )
        assert replay.status_code == 201, replay.text
        assert replay.headers.get("Idempotent-Replayed") == "true"
        assert replay.json() == {"note_id": note_id}
        async with AsyncSessionLocal() as db:
            count = await db.scalar(
                select(func.count())
                .select_from(Note)
                .where(Note.candidate_id == candidate_id)
            )
        assert count == 1

    async def test_refusals(self, app_client: AsyncClient, app_auth_headers: dict):
        candidate_id = await _seed_candidate()
        _, cand_only = await _key(app_client, app_auth_headers, ["candidates:write"])
        resp = await app_client.post(
            f"{V1}/candidates/{candidate_id}/notes",
            headers=_h(cand_only, str(uuid.uuid4())),
            json={"content": "x"},
        )
        assert resp.status_code == 403, resp.text
        assert resp.json()["error"]["code"] == "insufficient_scope"

        _, api_key = await _key(app_client, app_auth_headers, ["notes:write"])
        for path, body, status in (
            (f"/candidates/{candidate_id}/notes", {"content": "  "}, 422),
            (
                f"/candidates/{candidate_id}/notes",
                {"content": "x", "kind": "card"},
                422,
            ),
            (
                f"/candidates/{candidate_id}/notes",
                {"content": "x", "job_id": 2_000_000_000},
                404,
            ),
            ("/candidates/2000000000/notes", {"content": "x"}, 404),
        ):
            resp = await app_client.post(
                f"{V1}{path}", headers=_h(api_key, str(uuid.uuid4())), json=body
            )
            assert resp.status_code == status, (path, body, resp.text)
