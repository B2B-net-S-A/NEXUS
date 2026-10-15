"""API v1 — Akademia (scope ``academy:read``).

Bez bazy: liczniki etapów z ``status_counts`` (każdy status, także zero),
daty edycji z ``program_dates``, uczestnik bez kontaktu bez
``candidates:contact``.

Na bazie (CI): lista programów z licznikami, szczegóły (źródła bez rekrutacji
ukrytego klienta, terminy w biurze, edycje), uczestnicy w kolejności ekranu,
kontakt tylko z ``candidates:contact``, filtr statusu, 403 bez scope'u,
404 dla programu, którego nie ma.

Dane są zmyślone (repo jest publiczne). Baza testowa jest wspólna
i nieczyszczona — każdy test zakłada własny program i filtruje po nim.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from httpx import AsyncClient

import app.models  # noqa: F401  (zarejestruj wszystkie mappery)
from app.api.integrations_v1 import academy as v1_academy
from app.models.academy import ACADEMY_STATUSES
from app.services.academy_documents import program_dates

V1 = "/api/integrations/v1"


# ── Bez bazy ─────────────────────────────────────────────────────────────────


def test_counts_cover_every_status_and_sum_in_progress():
    out = v1_academy.counts_out(
        {"new": 3, "scheduled": 1, "signed": 2, "rejected": 4, "luna_skipped": 1}
    )
    assert set(out.by_status) == set(ACADEMY_STATUSES)
    assert out.by_status["to_call"] == 0
    assert out.total == 10
    assert out.in_progress == 4
    assert (out.luna_skipped, out.unscreened, out.reapplied_excluded) == (1, 0, 0)


def test_cohort_dates_come_from_the_documents_rule():
    out = v1_academy.cohort_out(date(2026, 11, 1))
    assert (out.program_start, out.program_end) == program_dates(date(2026, 11, 1))
    assert out.program_start.weekday() < 5


def _application(**extra):
    values = {
        "id": 1,
        "candidate_id": 2,
        "status": "signed",
        "screening_verdict": "call",
        "source_job_id": 3,
        "applied_at": datetime(2026, 9, 1, tzinfo=timezone.utc),
        "reapplied_at": None,
        "call_attempts": 1,
        "last_call_at": None,
        "session_id": None,
        "attended": True,
        "task_due": None,
        "task_result": "passed",
        "contract_sent_at": None,
        "signed_at": None,
        "cohort_month": date(2026, 10, 1),
        "closed_stage": None,
        "closed_at": None,
        "note": "Notatka rekrutera",
        "closed_reason": "Powód",
        "screening": {"facts": {"quote": "cytat z CV"}},
    }
    values.update(extra)
    return SimpleNamespace(**values)


@pytest.mark.parametrize("contact", [False, True])
def test_participant_contact_only_with_contact_scope(contact):
    out = v1_academy.participant_out(
        _application(),
        first_name="Anna",
        last_name="Przykładowa",
        email="anna@example.com",
        phone="+48 600 000 000",
        session_starts_at=None,
        contact=contact,
        source_visible=contact,
    )
    assert out.first_name == "Anna"
    # Źródło spoza rejestru (klient ukryty albo usunięty) = brak źródła.
    assert out.source_job_id == (3 if contact else None)
    assert out.contact_redacted is (not contact)
    assert out.email == ("anna@example.com" if contact else None)
    assert out.phone == ("+48 600 000 000" if contact else None)
    dumped = str(out.model_dump())
    # Notatka, powód wykluczenia i fakty z CV nie wychodzą nigdy.
    assert "Notatka rekrutera" not in dumped
    assert "Powód" not in dumped
    assert "cytat z CV" not in dumped


# ── Na bazie ─────────────────────────────────────────────────────────────────


def _h(api_key: str) -> dict:
    return {"X-API-Key": api_key}


async def _key(app_client: AsyncClient, headers: dict, scopes: list[str]) -> str:
    from tests.test_service_accounts import _account_with_key

    _, api_key, _ = await _account_with_key(app_client, headers, scopes)
    return api_key


async def _world() -> dict:
    """Program z dwoma ogłoszeniami (jedno u klienta ukrytego), terminem
    w biurze i trzema zgłoszeniami: w toku, podpisane, wykluczone."""
    from app.core.database import AsyncSessionLocal
    from app.models.academy import (
        AcademyApplication,
        AcademyProgram,
        AcademyProgramSource,
        AcademySession,
    )
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    tag = uuid.uuid4().hex[:8]
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        program = AcademyProgram(
            name=f"V1 Akademia {tag}",
            conditions=["Umowa zlecenie — pasuje?"],
            max_experience_years=3,
        )
        client = Client(name=f"V1 Akademia klient {tag}")
        hidden = Client(name=f"V1 Akademia ukryty {tag}", hidden=True)
        db.add_all([program, client, hidden])
        await db.flush()
        posting = Job(
            title=f"Akademia testerów {tag}",
            client_id=client.id,
            status=JobStatus.published,
        )
        orphan = Job(
            title=f"Ogłoszenie ukryte {tag}",
            client_id=hidden.id,
            status=JobStatus.published,
        )
        anna = Candidate(
            name="Anna",
            lastname=f"Przykładowa-{tag}",
            email=f"anna-{tag}@example.com",
            phone="+48 600 000 001",
        )
        jan = Candidate(
            name="Jan", lastname=f"Testowy-{tag}", email=f"jan-{tag}@example.com"
        )
        ewa = Candidate(
            name="Ewa", lastname=f"Wzorcowa-{tag}", email=f"ewa-{tag}@example.com"
        )
        db.add_all([posting, orphan, anna, jan, ewa])
        await db.flush()
        session = AcademySession(
            program_id=program.id,
            starts_at=now + timedelta(days=7),
            location="Biuro, sala 1",
            capacity=8,
        )
        db.add_all(
            [
                session,
                AcademyProgramSource(program_id=program.id, job_id=posting.id),
                AcademyProgramSource(program_id=program.id, job_id=orphan.id),
                CandidateStage(
                    candidate_id=anna.id,
                    job_id=posting.id,
                    stage=PipelineStage.new,
                    moved_at=now - timedelta(days=3),
                ),
            ]
        )
        await db.flush()
        scheduled = AcademyApplication(
            program_id=program.id,
            candidate_id=anna.id,
            source_job_id=posting.id,
            applied_at=now - timedelta(days=3),
            status="scheduled",
            screening_verdict="call",
            session_id=session.id,
        )
        signed = AcademyApplication(
            program_id=program.id,
            candidate_id=jan.id,
            source_job_id=posting.id,
            applied_at=now - timedelta(days=20),
            status="signed",
            cohort_month=date(2079, 3, 1),
            signed_at=now - timedelta(days=2),
            note="Notatka rekrutera",
        )
        rejected = AcademyApplication(
            program_id=program.id,
            candidate_id=ewa.id,
            # Zgłoszenie z ogłoszenia klienta ukrytego — źródło nie wychodzi.
            source_job_id=orphan.id,
            applied_at=now - timedelta(days=1),
            status="rejected",
            closed_stage="new",
            closed_reason="Brak wymaganego doświadczenia",
            closed_at=now,
        )
        db.add_all([scheduled, signed, rejected])
        await db.commit()
        return {
            "program_id": program.id,
            "posting_id": posting.id,
            "orphan_id": orphan.id,
            "session_id": session.id,
            "anna": anna.id,
            "jan": jan.id,
            "ewa": ewa.id,
            "tag": tag,
        }


async def _all_programs(app_client: AsyncClient, api_key: str) -> dict:
    found: dict = {}
    page = 1
    while True:
        resp = await app_client.get(
            f"{V1}/academy/programs",
            headers=_h(api_key),
            params={"page": page, "page_size": 500},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        found.update({item["id"]: item for item in body["items"]})
        if not body["has_more"]:
            return found
        page += 1


class TestPrograms:
    async def test_list_counts_and_next_cohort(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        world = await _world()
        api_key = await _key(app_client, app_auth_headers, ["academy:read"])
        program = (await _all_programs(app_client, api_key))[world["program_id"]]
        assert program["name"].startswith("V1 Akademia")
        assert program["is_active"] is True
        assert program["max_experience_years"] == 3
        assert program["call_questions"] == ["Umowa zlecenie — pasuje?"]
        counts = program["counts"]
        assert counts["by_status"]["scheduled"] == 1
        assert counts["by_status"]["signed"] == 1
        assert counts["by_status"]["rejected"] == 1
        assert counts["by_status"]["new"] == 0
        assert (counts["total"], counts["in_progress"]) == (3, 1)
        # Ogłoszenie u klienta ukrytego nie istnieje dla klucza.
        assert program["sources_count"] == 1
        assert (
            program["next_cohort"]["program_start"] >= program["next_cohort"]["month"]
        )

    async def test_inactive_filter(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        world = await _world()
        api_key = await _key(app_client, app_auth_headers, ["academy:read"])
        resp = await app_client.get(
            f"{V1}/academy/programs",
            headers=_h(api_key),
            params={"is_active": "false", "page_size": 500},
        )
        assert resp.status_code == 200, resp.text
        assert world["program_id"] not in {i["id"] for i in resp.json()["items"]}

    async def test_detail_sources_sessions_and_cohorts(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        world = await _world()
        api_key = await _key(app_client, app_auth_headers, ["academy:read"])
        resp = await app_client.get(
            f"{V1}/academy/programs/{world['program_id']}", headers=_h(api_key)
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert [s["job_id"] for s in body["sources"]] == [world["posting_id"]]
        assert body["sources"][0]["applicants"] == 1
        sessions = {s["id"]: s for s in body["sessions"]}
        assert sessions[world["session_id"]]["taken"] == 1
        assert sessions[world["session_id"]]["cancelled"] is False
        assert body["cohorts"] == [
            {
                "month": "2079-03-01",
                "program_start": program_dates(date(2079, 3, 1))[0].isoformat(),
                "program_end": program_dates(date(2079, 3, 1))[1].isoformat(),
                "contract_sent": 0,
                "signed": 1,
            }
        ]
        # Szczegóły programu nie niosą danych osobowych.
        assert world["tag"] not in str(body["sessions"]) + str(body["cohorts"])

    async def test_missing_program_is_404(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        api_key = await _key(app_client, app_auth_headers, ["academy:read"])
        for path in ("", "/participants"):
            resp = await app_client.get(
                f"{V1}/academy/programs/2147483000{path}", headers=_h(api_key)
            )
            assert resp.status_code == 404, resp.text
            assert resp.json()["error"]["code"] == "not_found"


class TestParticipants:
    async def test_names_without_contact_in_screen_order(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        world = await _world()
        api_key = await _key(app_client, app_auth_headers, ["academy:read"])
        resp = await app_client.get(
            f"{V1}/academy/programs/{world['program_id']}/participants",
            headers=_h(api_key),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == 3
        # Najpierw osoby w toku i podpisane (najnowsze pierwsze), wykluczeni na końcu.
        assert [p["candidate_id"] for p in body["items"]] == [
            world["anna"],
            world["jan"],
            world["ewa"],
        ]
        anna = body["items"][0]
        assert anna["first_name"] == "Anna"
        assert anna["status"] == "scheduled"
        assert anna["session_id"] == world["session_id"]
        assert anna["session_starts_at"] is not None
        for person in body["items"]:
            assert person["contact_redacted"] is True
            assert person["email"] is None and person["phone"] is None
            assert "note" not in person and "closed_reason" not in person
        assert body["items"][1]["cohort_month"] == "2079-03-01"
        assert [p["source_job_id"] for p in body["items"]] == [
            world["posting_id"],
            world["posting_id"],
            None,
        ]

    async def test_contact_scope_shows_email_and_phone(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        world = await _world()
        api_key = await _key(
            app_client, app_auth_headers, ["academy:read", "candidates:contact"]
        )
        resp = await app_client.get(
            f"{V1}/academy/programs/{world['program_id']}/participants",
            headers=_h(api_key),
            params={"status": ["scheduled"]},
        )
        assert resp.status_code == 200, resp.text
        (anna,) = resp.json()["items"]
        assert anna["contact_redacted"] is False
        assert anna["email"] == f"anna-{world['tag']}@example.com"
        assert anna["phone"] == "+48 600 000 001"

    async def test_pagination_and_unknown_status(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        world = await _world()
        api_key = await _key(app_client, app_auth_headers, ["academy:read"])
        url = f"{V1}/academy/programs/{world['program_id']}/participants"
        resp = await app_client.get(
            url, headers=_h(api_key), params={"page": 2, "page_size": 2}
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert [p["candidate_id"] for p in body["items"]] == [world["ewa"]]
        assert body["has_more"] is False
        resp = await app_client.get(
            url, headers=_h(api_key), params={"status": "hired"}
        )
        assert resp.status_code == 422, resp.text
        assert resp.json()["error"]["code"] == "validation_error"


_ROUTES = [
    "/academy/programs",
    "/academy/programs/1",
    "/academy/programs/1/participants",
]


class TestScope:
    @pytest.mark.parametrize("path", _ROUTES)
    async def test_other_scope_is_403(
        self, app_client: AsyncClient, app_auth_headers: dict, path: str
    ):
        api_key = await _key(app_client, app_auth_headers, ["insights:read"])
        resp = await app_client.get(f"{V1}{path}", headers=_h(api_key))
        assert resp.status_code == 403, resp.text
        assert resp.json()["error"]["code"] == "insufficient_scope"

    async def test_contact_scope_alone_does_not_open_academy(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        api_key = await _key(app_client, app_auth_headers, ["candidates:contact"])
        resp = await app_client.get(f"{V1}/academy/programs", headers=_h(api_key))
        assert resp.status_code == 403, resp.text
