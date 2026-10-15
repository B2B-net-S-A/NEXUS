"""API v1: zgłoszenia z linku rekrutacji (``applications:read`` / ``applications:write``).

Dwie części:

* bez bazy — ciało rozstrzygnięcia wydzielone 15.10.2026
  (``application_submissions.resolve_application_submission``) na atrapie
  sesji: osoba z ekranu dostaje dokładnie ten wpis co przed wydzieleniem,
  konto serwisowe — wpis bez osoby z powodem; bramka dostępu przed bramką
  „już rozstrzygnięte”; wejście v1 i projekcje (kontakt, cytaty z CV,
  stawka z formularza);
* z bazą (CI) — trasy przez HTTP: lista firmowa bez ukrytych klientów,
  kontakt tylko z ``candidates:contact``, plik CV z ``candidates:cv`` i ślad
  pobrania, rozpatrzenie link / merge / create / reject tym samym ciałem co
  ekran (autor = konto serwisowe), reguła „ten sam e-mail”, nagrobek RODO
  (409), powtórka z paragonu, próba bez zapisu, 403 bez scope'u.

Dane są zmyślone (repo jest publiczne).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.application_screening import ApplicationScreening
from app.models.application_submission import ApplicationSubmission
from app.models.candidate import Candidate
from app.models.candidate_document import CandidateDocument
from app.models.client import Client
from app.models.job import Job, JobStatus, RemotePolicy
from app.models.recruitment_pipeline import CandidateStage
from app.models.user_activity import UserActivity
from app.services import integration_application_reads as reads
from app.services.integration_actor import IntegrationActor
from app.services.write_author import WriteAuthor
from tests.test_service_accounts import _account_with_key

V1 = "/api/integrations/v1"
SERVICE = WriteAuthor.service_account(
    IntegrationActor(name="Integracja: Zgłoszenia", service_account_id=3)
)
PERSON = WriteAuthor.person(
    SimpleNamespace(id=7, name="Ola Testowa", email="ola.testowa@example.com")
)


# ── Bez bazy: ciało rozstrzygnięcia na atrapie sesji ─────────────────────────


class _Session:
    def __init__(self, submission):
        self._submission = submission
        self.added: list = []

    async def scalar(self, _stmt):
        return self._submission

    def add(self, obj) -> None:
        self.added.append(obj)


def _parked(**overrides) -> SimpleNamespace:
    values = {
        "id": 11,
        "status": "pending_review",
        "matched_candidate_id": 5,
        "job_id": None,
        "reviewed_by": None,
        "reviewed_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


async def _allow(_submission) -> None:
    return None


async def test_screen_reject_writes_the_same_entry_as_before() -> None:
    from app.api.application_submissions import resolve_application_submission

    submission = _parked()
    db = _Session(submission)
    result = await resolve_application_submission(
        db, 11, "reject", author=PERSON, authorize=_allow
    )
    assert result.candidate_id is None and result.primary_document is None
    assert submission.status == "rejected" and submission.reviewed_by == 7
    (activity,) = [obj for obj in db.added if isinstance(obj, Activity)]
    assert (activity.entity_type, activity.entity_id, activity.user_id) == (
        "application_submission",
        11,
        7,
    )
    # Bez klucza „reason” — wpis ekranu taki sam jak przed wydzieleniem.
    assert activity.details == {"resolve_action": "reject", "matched_candidate_id": 5}


async def test_service_account_reject_has_no_person_and_keeps_the_reason() -> None:
    from app.api.application_submissions import resolve_application_submission

    submission = _parked()
    db = _Session(submission)
    await resolve_application_submission(
        db,
        11,
        "reject",
        author=SERVICE,
        authorize=_allow,
        reason="Zgłoszenie testowe automatu",
    )
    assert submission.reviewed_by is None
    (activity,) = [obj for obj in db.added if isinstance(obj, Activity)]
    assert activity.user_id is None
    assert activity.details["reason"] == "Zgłoszenie testowe automatu"
    # Konto serwisowe nie zapisuje rankingu ludzi.
    assert not [obj for obj in db.added if isinstance(obj, UserActivity)]


async def test_access_is_checked_before_the_resolved_state_is_revealed() -> None:
    from app.api.application_submissions import resolve_application_submission

    async def deny(_submission) -> None:
        raise HTTPException(403, detail="Brak dostępu do rekrutacji")

    db = _Session(_parked(status="linked"))
    with pytest.raises(HTTPException) as caught:
        await resolve_application_submission(
            db, 11, "reject", author=PERSON, authorize=deny
        )
    assert caught.value.status_code == 403

    with pytest.raises(HTTPException) as caught:
        await resolve_application_submission(
            db, 11, "reject", author=PERSON, authorize=_allow
        )
    assert caught.value.status_code == 409


async def test_missing_submission_is_404() -> None:
    from app.api.application_submissions import resolve_application_submission

    with pytest.raises(HTTPException) as caught:
        await resolve_application_submission(
            _Session(None), 11, "reject", author=PERSON, authorize=_allow
        )
    assert caught.value.status_code == 404


# ── Bez bazy: wejście v1 ─────────────────────────────────────────────────────


def _resolve_in(**data):
    from app.api.integrations_v1.applications import ResolveIn

    return ResolveIn.model_validate(data)


def test_resolve_input_fields_follow_the_action() -> None:
    assert _resolve_in(action="link").candidate_id is None
    assert _resolve_in(action="merge", candidate_id=5).candidate_id == 5
    assert _resolve_in(action="reject", reason="  Duplikat  ").reason == "Duplikat"
    for bad in (
        {"action": "reject"},
        {"action": "reject", "reason": "   "},
        {"action": "create", "candidate_id": 5},
        {"action": "link", "reason": "po co"},
        {"action": "link", "status": "linked"},
        {"action": "approve"},
    ):
        with pytest.raises(ValidationError):
            _resolve_in(**bad)


# ── Bez bazy: projekcje ──────────────────────────────────────────────────────

_NOW = datetime(2026, 10, 15, 9, 0, tzinfo=timezone.utc)


def _submission(**overrides) -> SimpleNamespace:
    values = {
        "id": 21,
        "status": "linked",
        "job_id": 4,
        "created_at": _NOW - timedelta(days=2),
        "reviewed_at": _NOW - timedelta(days=1),
        "matched_candidate_id": 9,
        "submitted_first_name": "Ewa",
        "submitted_last_name": "Przykładowa",
        "submitted_email": "ewa.przykladowa@example.com",
        "submitted_phone": "+48 600 100 200",
        "submitted_linkedin": "https://linkedin.com/in/ewa-przykladowa",
        "submitted_message": "Chętnie porozmawiam.",
        "cv_filename": "CV-Ewa-Przykladowa.pdf",
        "cv_content_type": "application/pdf",
        "cv_size_bytes": 1234,
        "raw_payload": {
            "city": "Kraków",
            "availability_date": "2026-11-01",
            "work_mode": "remote",
            "expected_rate_hourly": "150.00",
            "link_kind": "job",
            "via": "career",
            "email": "ewa.przykladowa@example.com",
            "utm": {"source": "linkedin", "campaign": "jesien"},
        },
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _screening(**overrides) -> SimpleNamespace:
    values = {
        "status": "done",
        "verdict": "fits",
        "outcome": "added",
        "must_found": 2,
        "must_total": 3,
        "reasons": [
            {"text": "Zna Django", "quote": "5 lat Django"},
            {"text": "", "quote": "pusty powód wypada"},
            "nie słownik",
        ],
        "decided_at": _NOW - timedelta(hours=3),
        "overridden_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_contact_and_names_only_with_contact_scope() -> None:
    hidden = reads.contact_fields(_submission(), visible=False)
    assert hidden["contact_redacted"] is True
    assert {k: v for k, v in hidden.items() if k != "contact_redacted"} == {
        "first_name": None,
        "last_name": None,
        "email": None,
        "phone": None,
        "linkedin": None,
    }
    shown = reads.contact_fields(_submission(), visible=True)
    assert shown["email"] == "ewa.przykladowa@example.com"
    assert shown["first_name"] == "Ewa"


def test_screening_quotes_only_with_cv_scope() -> None:
    hidden = reads.screening_out(_screening(), show_quotes=False)
    assert hidden["reasons"] == [{"text": "Zna Django", "quote": None}]
    shown = reads.screening_out(_screening(), show_quotes=True)
    assert shown["reasons"] == [{"text": "Zna Django", "quote": "5 lat Django"}]
    assert reads.screening_out(None, show_quotes=True) is None


def test_answers_hide_the_expected_rate_without_amounts() -> None:
    hidden = reads.answers_out(_submission(), show_costs=False, show_contact=False)
    assert hidden["expected_rate_hourly"] is None and hidden["costs_redacted"] is True
    # Wiadomość to wolny tekst kandydata — jak kontakt.
    assert hidden["message"] is None and hidden["message_redacted"] is True
    assert hidden["city"] == "Kraków" and hidden["utm_source"] == "linkedin"
    # Kontakt z ``raw_payload`` nie wychodzi odpowiedziami formularza.
    assert "email" not in hidden
    shown = reads.answers_out(_submission(), show_costs=True, show_contact=True)
    assert shown["expected_rate_hourly"] == Decimal("150.00")
    assert (
        shown["message"] == "Chętnie porozmawiam."
        and shown["message_redacted"] is False
    )
    assert shown["availability_date"] == date(2026, 11, 1)
    broken = reads.answers_out(
        _submission(
            raw_payload={
                "expected_rate_hourly": "dużo",
                "availability_date": "od zaraz",
                "city": 7,
            }
        ),
        show_costs=True,
        show_contact=True,
    )
    assert broken["expected_rate_hourly"] is None
    assert broken["availability_date"] is None and broken["city"] is None


def test_list_item_has_no_cv_bytes_and_tracks_the_latest_change() -> None:
    later = _NOW - timedelta(minutes=5)
    item = reads.item_out(
        _submission(),
        "Python Developer",
        _screening(decided_at=later),
        contact=False,
        cv=False,
    )
    assert item["has_cv"] is True
    assert not {"cv_file_content", "cv_file_name", "raw_cv_text"} & set(item)
    assert item["updated_at"] == later
    cv = reads.cv_fields(_submission(), visible=False)
    assert cv["cv_file_name"] is None and cv["cv_size_bytes"] == 1234


# ── Z bazą (CI): trasy v1 ────────────────────────────────────────────────────


def _h(api_key: str, idem: str | None = None) -> dict:
    out = {"X-API-Key": api_key}
    if idem is not None:
        out["Idempotency-Key"] = idem
    return out


async def _key(
    app_client: AsyncClient, headers: dict, scopes: list[str]
) -> tuple[dict, str]:
    account, api_key, _ = await _account_with_key(app_client, headers, scopes)
    return account, api_key


async def _world(
    *,
    hidden_client: bool = False,
    status: str = "pending_review",
    matched: bool = True,
) -> dict:
    """Rekrutacja z kandydatką Ewą i jej zgłoszeniem (CV w bazie), ocena AI
    pod zgłoszeniem i zgłoszenie ze stałego linku (bez rekrutacji)."""
    tag = uuid.uuid4().hex[:8]
    now = datetime.now(timezone.utc)
    pdf = b"%PDF-1.4 zgloszenie " + tag.encode()
    async with AsyncSessionLocal() as db:
        client = Client(name=f"V1 Zgłoszenia {tag}", hidden=hidden_client)
        db.add(client)
        await db.flush()
        job = Job(
            title=f"Python Developer {tag}",
            location="Kraków",
            client_id=client.id,
            status=JobStatus.published,
            is_open=True,
            remote_policy=RemotePolicy.hybrid,
        )
        ewa = Candidate(
            name="Ewa",
            lastname=f"Przykładowa-{tag}",
            email=f"ewa-app-{tag}@example.com",
        )
        olaf = Candidate(
            name="Olaf", lastname=f"Testowy-{tag}", email=f"olaf-app-{tag}@example.com"
        )
        db.add_all([job, ewa, olaf])
        await db.flush()
        email = ewa.email if matched else f"nowa-app-{tag}@example.com"
        submission = ApplicationSubmission(
            job_id=job.id,
            status=status,
            submitted_first_name="Ewa" if matched else "Nowa",
            submitted_last_name=f"Przykładowa-{tag}",
            # Wielkie litery: „ten sam e-mail” nie rozróżnia wielkości liter.
            submitted_email=email.upper(),
            submitted_phone="+48 600 100 200",
            submitted_linkedin=f"https://linkedin.com/in/ewa-{tag}",
            submitted_message=f"Chętnie porozmawiam {tag}.",
            matched_candidate_id=ewa.id if matched else None,
            cv_filename=f"CV-Ewa-{tag}.pdf",
            cv_content_type="application/pdf",
            cv_size_bytes=len(pdf),
            cv_file_content=pdf,
            raw_payload={
                "city": "Kraków",
                "availability_date": "2026-11-01",
                "work_mode": "remote",
                "expected_rate_hourly": "150.00",
                "link_kind": "job",
                "via": "career",
                "utm": {"source": "linkedin"},
            },
        )
        loose = ApplicationSubmission(
            job_id=None,
            status="linked",
            submitted_first_name="Ewa",
            submitted_last_name=f"Przykładowa-{tag}",
            submitted_email=ewa.email,
            matched_candidate_id=ewa.id,
        )
        db.add_all([submission, loose])
        await db.flush()
        db.add(
            ApplicationScreening(
                submission_id=submission.id,
                candidate_id=ewa.id,
                job_id=job.id,
                status="done",
                verdict="fits",
                outcome="added",
                must_found=2,
                must_total=3,
                reasons=[{"text": "Zna Django", "quote": f"5 lat Django {tag}"}],
                decided_at=now,
            )
        )
        await db.commit()
        return {
            "tag": tag,
            "now": now,
            "pdf": pdf,
            "job_id": job.id,
            "ewa": ewa.id,
            "olaf": olaf.id,
            "email": email,
            "submission": submission.id,
            "loose": loose.id,
        }


async def _resolve(
    app_client: AsyncClient, api_key: str, submission_id: int, body: dict, **params
):
    return await app_client.post(
        f"{V1}/applications/{submission_id}/resolve",
        headers=_h(api_key, str(uuid.uuid4())),
        params=params,
        json=body,
    )


@pytest.fixture
def _cv_reads(monkeypatch) -> list:
    """Odczyt AI głównego CV po commicie — zapis wywołań zamiast modelu."""
    calls: list = []

    async def _record(candidate_id, document_id, digest):
        calls.append((candidate_id, document_id, digest))

    monkeypatch.setattr(
        "app.api.candidates._enrich_candidate_from_document_task", _record
    )
    return calls


class TestReadApplications:
    async def test_list_is_company_wide_without_hidden_clients_and_contact(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        world = await _world()
        hidden = await _world(hidden_client=True)
        _, api_key = await _key(app_client, app_auth_headers, ["applications:read"])
        resp = await app_client.get(
            f"{V1}/applications",
            headers=_h(api_key),
            params={
                "updated_since": (world["now"] - timedelta(minutes=5)).isoformat(),
                "page_size": 500,
            },
        )
        assert resp.status_code == 200, resp.text
        by_id = {item["id"]: item for item in resp.json()["items"]}
        assert world["submission"] in by_id and world["loose"] in by_id
        assert hidden["submission"] not in by_id

        item = by_id[world["submission"]]
        assert item["status"] == "pending_review"
        assert item["job_title"] == f"Python Developer {world['tag']}"
        assert item["matched_candidate_id"] == world["ewa"]
        assert item["contact_redacted"] is True
        assert item["first_name"] is None and item["email"] is None
        assert item["has_cv"] is True
        assert item["ai_screening"]["verdict"] == "fits"
        assert item["ai_screening"]["reasons"] == [
            {"text": "Zna Django", "quote": None}
        ]
        assert world["tag"] not in str(item["ai_screening"])

        _, contact_key = await _key(
            app_client, app_auth_headers, ["applications:read", "candidates:contact"]
        )
        resp = await app_client.get(
            f"{V1}/applications",
            headers=_h(contact_key),
            params={"job_id": world["job_id"], "status": "pending_review"},
        )
        (item,) = resp.json()["items"]
        assert item["first_name"] == "Ewa"
        assert item["email"] == world["email"].upper()

        resp = await app_client.get(
            f"{V1}/applications",
            headers=_h(api_key),
            params={"job_id": hidden["job_id"]},
        )
        assert resp.json()["items"] == []

    async def test_detail_answers_and_cv_name_per_scope(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        world = await _world()
        path = f"{V1}/applications/{world['submission']}"
        _, plain = await _key(app_client, app_auth_headers, ["applications:read"])
        body = (await app_client.get(path, headers=_h(plain))).json()
        assert body["answers"]["city"] == "Kraków"
        # Wiadomość kandydata tylko z candidates:contact.
        assert body["answers"]["message"] is None
        assert body["answers"]["message_redacted"] is True
        assert body["answers"]["expected_rate_hourly"] is None
        assert body["answers"]["costs_redacted"] is True
        assert body["cv_file_name"] is None and body["has_cv"] is True

        _, wide = await _key(
            app_client,
            app_auth_headers,
            ["applications:read", "candidates:cv", "amounts:read"],
        )
        body = (await app_client.get(path, headers=_h(wide))).json()
        assert body["answers"]["expected_rate_hourly"] == "150.00"
        assert body["cv_file_name"] == f"CV-Ewa-{world['tag']}.pdf"
        assert body["ai_screening"]["reasons"][0]["quote"] == (
            f"5 lat Django {world['tag']}"
        )

        hidden = await _world(hidden_client=True)
        resp = await app_client.get(
            f"{V1}/applications/{hidden['submission']}", headers=_h(wide)
        )
        assert resp.status_code == 404, resp.text

    async def test_cv_file_needs_both_scopes_and_leaves_a_trace(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        world = await _world()
        path = f"{V1}/applications/{world['submission']}/cv"
        _, plain = await _key(app_client, app_auth_headers, ["applications:read"])
        resp = await app_client.get(path, headers=_h(plain))
        assert resp.status_code == 403, resp.text
        assert resp.json()["error"]["details"]["missing"] == ["candidates:cv"]

        account, both = await _key(
            app_client, app_auth_headers, ["applications:read", "candidates:cv"]
        )
        resp = await app_client.get(path, headers=_h(both))
        assert resp.status_code == 200, resp.text
        assert resp.content == world["pdf"]
        assert resp.headers["content-disposition"].startswith("attachment")
        async with AsyncSessionLocal() as db:
            trace = await db.scalar(
                select(Activity).where(
                    Activity.entity_type == "candidate",
                    Activity.entity_id == world["ewa"],
                    Activity.action == "document_downloaded",
                )
            )
        assert trace is not None and trace.user_id is None
        assert trace.details["submission_id"] == world["submission"]
        assert trace.details["via"] == f"integration:{account['slug']}"


class TestResolveApplications:
    async def test_link_runs_the_screen_body_as_the_service_account(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        world = await _world()
        account, api_key = await _key(
            app_client, app_auth_headers, ["applications:write"]
        )
        idem = str(uuid.uuid4())
        url = f"{V1}/applications/{world['submission']}/resolve"
        first = await app_client.post(
            url, headers=_h(api_key, idem), json={"action": "link"}
        )
        assert first.status_code == 200, first.text
        assert first.json() == {
            "id": world["submission"],
            "status": "linked",
            "candidate_id": world["ewa"],
            "added_to_recruitment": True,
        }
        again = await app_client.post(
            url, headers=_h(api_key, idem), json={"action": "link"}
        )
        assert again.status_code == 200, again.text
        assert again.headers.get("Idempotent-Replayed") == "true"
        assert again.json() == first.json()

        async with AsyncSessionLocal() as db:
            submission = await db.get(ApplicationSubmission, world["submission"])
            assert submission.status == "linked" and submission.reviewed_by is None
            document = await db.scalar(
                select(CandidateDocument).where(
                    CandidateDocument.candidate_id == world["ewa"],
                    CandidateDocument.external_source == "apply_submission",
                )
            )
            assert document is not None and document.is_primary is False
            stage = await db.scalar(
                select(CandidateStage).where(
                    CandidateStage.candidate_id == world["ewa"],
                    CandidateStage.job_id == world["job_id"],
                )
            )
            assert stage is not None and stage.moved_by is None
            activities = (
                await db.scalars(
                    select(Activity).where(
                        Activity.entity_type == "candidate",
                        Activity.entity_id == world["ewa"],
                        Activity.action == "application_submission_resolved",
                    )
                )
            ).all()
            ranking = await db.scalar(
                select(func.count())
                .select_from(UserActivity)
                .where(
                    UserActivity.entity_type == "candidate",
                    UserActivity.entity_id == world["ewa"],
                )
            )
        assert len(activities) == 1
        assert activities[0].user_id is None
        assert activities[0].details["via"] == f"integration:{account['slug']}"
        assert ranking == 0

    async def test_merge_fills_only_empty_contact_fields(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        world = await _world()
        _, api_key = await _key(app_client, app_auth_headers, ["applications:write"])
        resp = await _resolve(
            app_client,
            api_key,
            world["submission"],
            {"action": "merge", "candidate_id": world["ewa"]},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "merged"
        async with AsyncSessionLocal() as db:
            ewa = await db.get(Candidate, world["ewa"])
        assert ewa.phone == "+48 600 100 200"
        assert ewa.email == world["email"]  # e-mail profilu bez zmian
        assert f"Chętnie porozmawiam {world['tag']}." in (ewa.profile_about or "")

    async def test_link_to_another_person_is_409(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        world = await _world()
        _, api_key = await _key(app_client, app_auth_headers, ["applications:write"])
        for params in ({}, {"dry_run": "true"}):
            resp = await _resolve(
                app_client,
                api_key,
                world["submission"],
                {"action": "link", "candidate_id": world["olaf"]},
                **params,
            )
            assert resp.status_code == 409, resp.text
            error = resp.json()["error"]
            assert error["code"] == "not_same_person"
            assert error["details"] == {"candidate_id": world["ewa"]}

    async def test_create_follows_the_same_email_and_erasure_rules(
        self, app_client: AsyncClient, app_auth_headers: dict, _cv_reads: list
    ):
        from app.models.purged_candidate import PurgedCandidate
        from app.services.candidate_audit import (
            EMAIL_TOMBSTONE_SOURCE,
            candidate_email_tombstone,
        )

        _, api_key = await _key(app_client, app_auth_headers, ["applications:write"])

        # E-mail zgłoszenia ma już kandydatka — drugi profil nie powstaje.
        taken = await _world()
        resp = await _resolve(
            app_client, api_key, taken["submission"], {"action": "create"}
        )
        assert resp.status_code == 409, resp.text
        error = resp.json()["error"]
        assert error["code"] == "duplicate_candidate"
        assert error["details"] == {"candidate_id": taken["ewa"]}

        # Adres osoby usuniętej na jej żądanie (RODO) nie wraca z automatu.
        erased = await _world(matched=False)
        async with AsyncSessionLocal() as db:
            db.add(
                PurgedCandidate(
                    external_source=EMAIL_TOMBSTONE_SOURCE,
                    external_id_hash=candidate_email_tombstone(erased["email"]),
                )
            )
            await db.commit()
        for params in ({}, {"dry_run": "true"}):
            resp = await _resolve(
                app_client,
                api_key,
                erased["submission"],
                {"action": "create"},
                **params,
            )
            assert resp.status_code == 409, resp.text
            assert resp.json()["error"]["code"] == "candidate_erased"

        fresh = await _world(matched=False)
        resp = await _resolve(
            app_client, api_key, fresh["submission"], {"action": "create"}
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "created" and body["added_to_recruitment"] is True
        async with AsyncSessionLocal() as db:
            created = await db.get(Candidate, body["candidate_id"])
            primary = await db.scalar(
                select(CandidateDocument).where(
                    CandidateDocument.candidate_id == created.id,
                    CandidateDocument.is_primary.is_(True),
                )
            )
        assert created.created_by is None
        assert created.email.lower() == fresh["email"]
        assert primary is not None
        assert [call[:2] for call in _cv_reads] == [(created.id, primary.id)]

    async def test_reject_needs_a_reason_and_records_it(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        world = await _world()
        _, api_key = await _key(app_client, app_auth_headers, ["applications:write"])
        resp = await _resolve(
            app_client, api_key, world["submission"], {"action": "reject"}
        )
        assert resp.status_code == 422, resp.text

        resp = await _resolve(
            app_client,
            api_key,
            world["submission"],
            {"action": "reject", "reason": "Zgłoszenie testowe automatu"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "rejected"
        assert resp.json()["candidate_id"] is None
        async with AsyncSessionLocal() as db:
            activity = await db.scalar(
                select(Activity).where(
                    Activity.entity_type == "application_submission",
                    Activity.entity_id == world["submission"],
                )
            )
        assert activity.details["reason"] == "Zgłoszenie testowe automatu"
        assert activity.user_id is None

        resp = await _resolve(
            app_client,
            api_key,
            world["submission"],
            {"action": "reject", "reason": "drugi raz"},
        )
        assert resp.status_code == 409, resp.text
        error = resp.json()["error"]
        assert error["code"] == "already_resolved"
        assert error["details"] == {"status": "rejected"}

    async def test_dry_run_writes_nothing(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        world = await _world()
        _, api_key = await _key(app_client, app_auth_headers, ["applications:write"])
        resp = await app_client.post(
            f"{V1}/applications/{world['submission']}/resolve",
            headers=_h(api_key),
            params={"dry_run": "true"},
            json={"action": "link"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json() == {
            "id": world["submission"],
            "status": "linked",
            "candidate_id": world["ewa"],
            "added_to_recruitment": True,
            "dry_run": True,
        }
        async with AsyncSessionLocal() as db:
            submission = await db.get(ApplicationSubmission, world["submission"])
            stage = await db.scalar(
                select(CandidateStage.id).where(
                    CandidateStage.candidate_id == world["ewa"],
                    CandidateStage.job_id == world["job_id"],
                )
            )
        assert submission.status == "pending_review" and stage is None

    async def test_scopes_and_hidden_clients(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        world = await _world()
        _, reader = await _key(app_client, app_auth_headers, ["applications:read"])
        resp = await _resolve(
            app_client, reader, world["submission"], {"action": "link"}
        )
        assert resp.status_code == 403, resp.text
        assert resp.json()["error"]["code"] == "insufficient_scope"

        _, other = await _key(app_client, app_auth_headers, ["candidates:read"])
        resp = await app_client.get(f"{V1}/applications", headers=_h(other))
        assert resp.status_code == 403, resp.text

        hidden = await _world(hidden_client=True)
        _, writer = await _key(app_client, app_auth_headers, ["applications:write"])
        resp = await _resolve(
            app_client, writer, hidden["submission"], {"action": "link"}
        )
        assert resp.status_code == 404, resp.text
        async with AsyncSessionLocal() as db:
            submission = await db.get(ApplicationSubmission, hidden["submission"])
        assert submission.status == "pending_review"
