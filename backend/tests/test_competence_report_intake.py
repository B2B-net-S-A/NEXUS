"""Raport kompetencji: przyjęcie warunków ze strony i rekord raportu (0792).

Decyzje Artura 25.11.2026: ``source=baza`` z ``report=1`` niesie warunki
(stawka, obecna stawka, forma, tryby, dni w biurze, miasta, start). Każde pole
trafia do profilu przez writery jak formularz warunków, osoba już w bazie też
dostaje raport (zmiana rekrutera z 14 dni zostaje), a opiekun idzie po kolei
z listy admina. Dane wyłącznie syntetyczne.
"""

from __future__ import annotations

import io
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.activity import Activity
from app.models.application_submission import ApplicationSubmission
from app.models.candidate import AvailabilityStatus, Candidate, CandidateStatus
from app.models.candidate_document import CandidateDocument
from app.models.competence_report import CompetenceReport, CompetenceReportOwner
from app.models.user import User, UserRole
from app.services import competence_report_ddl as ddl
from app.services.competence_report_store import SEND_DUE_AFTER, assign_owner

_URL = "/api/public/website-applications"
_TOKEN = "test-website-applications-token-not-a-secret"
_CONSENT = "Zgoda testowa na obecne i przyszłe rekrutacje (treść syntetyczna)."
_BACKEND = Path(__file__).resolve().parents[1]


@pytest_asyncio.fixture
async def api(monkeypatch) -> AsyncClient:
    from app.core.rate_limit import limiter
    from app.main import app

    async def _noop_embed(candidate_id, db):
        return True

    async def _noop_task(*args, **kwargs):
        return None

    monkeypatch.setattr("app.services.embedding_service.embed_candidate", _noop_embed)
    monkeypatch.setattr("app.api.public_share._invite_post_apply_task", _noop_task)
    monkeypatch.setattr(settings, "WEBSITE_APPLICATIONS_TOKEN", _TOKEN)
    limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as client:
        yield client


def _email(label: str) -> str:
    return f"raport-{label}-{uuid.uuid4().hex[:8]}@example.com"


def _form(email: str, **extra) -> dict:
    return {
        "source": "baza",
        "email": email,
        "report": "1",
        "rate": "180",
        "consent": _CONSENT,
        **extra,
    }


def _cv():
    return {"cv": ("cv.pdf", io.BytesIO(b"%PDF-1.4 raport"), "application/pdf")}


async def _post(api: AsyncClient, data, *, cv: bool = True):
    return await api.post(
        _URL,
        data=data,
        files=_cv() if cv else None,
        headers={"Authorization": f"Bearer {_TOKEN}"},
    )


async def _candidate(email: str) -> Candidate | None:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(Candidate).where(func.lower(Candidate.email) == email.lower())
        )


async def _reports(candidate_id: int) -> list[CompetenceReport]:
    async with AsyncSessionLocal() as db:
        rows = await db.scalars(
            select(CompetenceReport).where(
                CompetenceReport.candidate_id == candidate_id
            )
        )
        return list(rows)


async def _submission(email: str) -> ApplicationSubmission:
    async with AsyncSessionLocal() as db:
        [row] = list(
            await db.scalars(
                select(ApplicationSubmission).where(
                    func.lower(ApplicationSubmission.submitted_email) == email.lower()
                )
            )
        )
        return row


async def _new_user(label: str, *, active: bool = True) -> int:
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"opiekun-{label}-{uuid.uuid4().hex[:8]}@example.com",
            password_hash="not-a-real-hash",
            name=f"Opiekun {label}",
            role=UserRole.recruiter,
            is_active=active,
        )
        db.add(user)
        await db.commit()
        return user.id


# ── Każde pole formularza ────────────────────────────────────────────────


async def test_new_person_report_maps_every_field(api):
    email = _email("nowy")

    resp = await _post(
        api,
        _form(
            email,
            current_rate="150",
            contract="uop",
            work_mode=["hybrid", "remote"],
            office_days_max="2",
            office_city=[" Kraków ", "kraków", "Gdańsk"],
            start="1m",
        ),
    )

    assert resp.status_code == 201, resp.text
    person = await _candidate(email)
    assert person.expected_rate_hourly == Decimal("180.00")
    assert person.preferences["remote_modes"] == ["remote", "hybrid"]
    assert person.preferences["office_cities"] == ["Kraków", "Gdańsk"]
    assert person.preferences["contract_types"] == ["uop"]
    assert person.b2b_willingness == "employment_only"
    assert person.max_onsite_days_per_week == 2
    assert (person.notice_period, person.notice_period_unit) == (1, "months")
    assert person.availability_date is None

    entry = await _submission(email)
    assert entry.raw_payload["report"] is True
    assert entry.raw_payload["current_rate_hourly"] == 150
    # Obecna stawka nie udaje oczekiwania w historii stawek.
    assert entry.raw_payload["expected_rate_hourly"] == "180.00"
    assert "Prośba o raport kompetencji" in entry.submitted_message

    [report] = await _reports(person.id)
    assert report.status == "waiting_cv"
    assert report.email == email
    assert report.submission_id == entry.id
    assert report.send_due_at - report.created_at == SEND_DUE_AFTER
    assert report.sent_at is None and report.attempts == 0
    assert report.conditions == {
        "rate": 180,
        "current_rate": 150,
        "contract": "uop",
        "modes": ["remote", "hybrid"],
        "office_days_max": 2,
        "office_cities": ["Kraków", "Gdańsk"],
        "start": "1m",
    }


@pytest.mark.parametrize(
    ("contract", "willingness", "types"),
    [("b2b", "b2b", ["b2b"]), ("any", None, ["b2b", "uop"])],
)
async def test_contract_maps_to_willingness_and_types(
    api, contract, willingness, types
):
    email = _email(f"forma-{contract}")

    resp = await _post(api, _form(email, contract=contract))

    assert resp.status_code == 201, resp.text
    person = await _candidate(email)
    assert person.b2b_willingness == willingness
    assert person.preferences["contract_types"] == types


async def test_start_now_is_today_in_company_calendar(api):
    email = _email("start-now")

    resp = await _post(api, _form(email, start="now"))

    assert resp.status_code == 201, resp.text
    person = await _candidate(email)
    assert person.availability_date == business_today()
    assert (person.notice_period, person.notice_period_unit) == (0, "days")


async def test_start_two_three_months_and_browsing(api):
    later, browsing = _email("start-23"), _email("start-browse")

    assert (await _post(api, _form(later, start="2-3m"))).status_code == 201
    assert (await _post(api, _form(browsing, start="browsing"))).status_code == 201

    person = await _candidate(later)
    assert (person.notice_period, person.notice_period_unit) == (2, "months")
    person = await _candidate(browsing)
    assert person.availability_status == AvailabilityStatus.open_to_offers
    assert person.availability_date is None and person.notice_period is None


async def test_remote_only_means_zero_office_days(api):
    email = _email("zdalnie")

    resp = await _post(api, _form(email, work_mode="remote", office_days_max="3"))

    assert resp.status_code == 201, resp.text
    person = await _candidate(email)
    assert person.preferences["remote_modes"] == ["remote"]
    assert person.max_onsite_days_per_week == 0


async def test_legacy_single_label_still_works_without_report(api):
    email, unknown = _email("etykieta"), _email("nieznana")
    base = {
        "source": "baza",
        "linkedin": "https://www.linkedin.com/in/syntetyczny",
        "consent": _CONSENT,
    }

    ok = await _post(api, {**base, "email": email, "work_mode": "Hybryda"}, cv=False)
    # Dawny formularz: nieznana etykieta przepada, zgłoszenie przechodzi.
    lax = await _post(api, {**base, "email": unknown, "work_mode": "Kosmos"}, cv=False)

    assert ok.status_code == 201, ok.text
    assert lax.status_code == 201, lax.text
    person = await _candidate(email)
    assert person.preferences["remote_modes"] == ["hybrid"]
    assert await _reports(person.id) == []
    assert "remote_modes" not in ((await _candidate(unknown)).preferences or {})


# ── Odmowy na granicy ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("extra", "field"),
    [
        ({"office_days_max": "6"}, "office_days_max"),
        ({"office_days_max": "-1"}, "office_days_max"),
        ({"office_days_max": "dwa"}, "office_days_max"),
        ({"rate": "-50"}, "rate"),
        ({"rate": "2500"}, "rate"),
        ({"rate": ""}, "rate"),
        ({"current_rate": "-5"}, "current_rate"),
        ({"current_rate": "abc"}, "current_rate"),
        ({"work_mode": ["remote", "kosmos"]}, "work_mode"),
        ({"contract": "zlecenie"}, "contract"),
        ({"start": "jutro"}, "start"),
        ({"report": "tak"}, "report"),
        ({"office_city": [f"Miasto {i}" for i in range(11)]}, "office_city"),
        ({"office_city": "x" * 121}, "office_city"),
    ],
    ids=[
        "dni-6",
        "dni-ujemne",
        "dni-tekst",
        "stawka-ujemna",
        "stawka-za-duza",
        "stawka-brak",
        "obecna-ujemna",
        "obecna-tekst",
        "tryb-nieznany",
        "forma-nieznana",
        "start-nieznany",
        "raport-nieznany",
        "miast-11",
        "miasto-za-dlugie",
    ],
)
async def test_out_of_range_values_are_422(api, extra, field):
    email = _email("zle")

    resp = await _post(api, _form(email, **extra))

    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"][0]["loc"] == ["body", field]
    assert await _candidate(email) is None


async def test_report_without_cv_is_refused_even_with_linkedin(api):
    email = _email("bezcv")

    resp = await _post(
        api, _form(email, linkedin="https://www.linkedin.com/in/syntetyczny"), cv=False
    )

    assert resp.status_code == 422
    assert resp.json()["detail"][0]["loc"] == ["body", "cv"]
    assert await _candidate(email) is None


async def test_report_on_offer_form_is_refused(api):
    email = _email("oferta")

    resp = await _post(
        api,
        _form(
            email,
            source="oferta",
            offer_slug="tester",
            first_name="Test",
            last_name="Syntetyczny",
        ),
    )

    assert resp.status_code == 422
    assert resp.json()["detail"][0]["loc"] == ["body", "report"]


# ── Osoba już w bazie ────────────────────────────────────────────────────


async def test_duplicate_gets_report_but_profile_waits_for_confirmation(api):
    """Decyzja 26.11.2026: osoba w bazie — warunki w raporcie, profil bez zmian,
    dopóki nie potwierdzi ich z linku raportu (wtedy ochrona 14 dni)."""
    email = _email("dup")
    recruiter = await _new_user("dup")
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        existing = Candidate(
            name="Osoba",
            lastname="Syntetyczna",
            email=email,
            source="manual",
            status=CandidateStatus.active,
            expected_rate_hourly=Decimal("100.00"),
            expected_rate_currency="PLN",
            preferences={"remote_modes": ["onsite"]},
            max_onsite_days_per_week=5,
        )
        db.add(existing)
        await db.flush()
        existing_id = existing.id
        db.add_all(
            [
                # Stawka zmieniona przez rekrutera 3 dni temu — zostaje.
                Activity(
                    entity_type="candidate",
                    entity_id=existing_id,
                    action="profile_rate_changed",
                    user_id=recruiter,
                    details={"new_amount": "100.00"},
                    external_source="audit",
                    created_at=now - timedelta(days=3),
                ),
                # Tryb pracy zmieniony 20 dni temu — poza oknem, nadpisany.
                Activity(
                    entity_type="candidate",
                    entity_id=existing_id,
                    action="candidate_work_mode_changed",
                    user_id=recruiter,
                    details={},
                    external_source="audit",
                    created_at=now - timedelta(days=20),
                ),
                # Forma współpracy zmieniona w profilu wczoraj — zostaje.
                Activity(
                    entity_type="candidate",
                    entity_id=existing_id,
                    action="updated",
                    user_id=recruiter,
                    details={"b2b_willingness": "b2b"},
                    created_at=now - timedelta(days=1),
                ),
            ]
        )
        await db.commit()

    resp = await _post(
        api,
        _form(
            email.upper(),
            rate="220",
            contract="uop",
            work_mode="hybrid",
            office_days_max="1",
            office_city="Wrocław",
        ),
    )

    assert resp.status_code == 201, resp.text
    person = await _candidate(email)
    assert person.id == existing_id
    assert (person.name, person.source) == ("Osoba", "manual")
    # Profil bez zmian: stawka, forma, tryb, dni i miasta jak przed zgłoszeniem.
    assert person.expected_rate_hourly == Decimal("100.00")
    assert person.b2b_willingness is None
    assert person.preferences == {"remote_modes": ["onsite"]}
    assert person.max_onsite_days_per_week == 5

    entry = await _submission(email)
    assert entry.matched_candidate_id == existing_id
    assert entry.status == "pending_review"
    assert entry.cv_filename == "cv.pdf"
    async with AsyncSessionLocal() as db:
        docs = list(
            await db.scalars(
                select(CandidateDocument).where(
                    CandidateDocument.candidate_id == existing_id
                )
            )
        )
        activity = await db.scalar(
            select(Activity).where(
                Activity.entity_id == existing_id,
                Activity.action == "applied_via_website",
            )
        )
    assert docs == [], "CV duplikatu nie wchodzi do profilu"
    assert "terms" not in activity.details
    assert Decimal(entry.raw_payload["expected_rate_hourly"]) == Decimal("220")
    assert entry.raw_payload["office_cities"] == ["Wrocław"]

    [report] = await _reports(existing_id)
    assert (report.status, report.submission_id) == ("waiting_cv", entry.id)
    assert report.conditions["rate"] == 220
    assert report.conditions["contract"] == "uop"
    assert report.conditions["modes"] == ["hybrid"]
    assert report.conditions["office_days_max"] == 1
    assert report.conditions["office_cities"] == ["Wrocław"]

    # Potwierdzenie z linku raportu: zapis do profilu, ale zmiany rekrutera
    # z 14 dni (stawka 3 dni temu, forma współpracy wczoraj) zostają.
    from app.services.competence_report_tokens import new_token

    raw, hashed = new_token()
    async with AsyncSessionLocal() as db:
        row = await db.get(CompetenceReport, report.id)
        row.status, row.sent_at = "sent", now
        row.token_hash, row.token_expires_at = hashed, now + timedelta(days=30)
        await db.commit()
    confirm = await api.post(
        f"/api/public/competence-report/{raw}/conditions",
        json={**report.conditions, "start": "1m"},
    )
    assert confirm.status_code == 200, confirm.text
    person = await _candidate(email)
    assert person.expected_rate_hourly == Decimal("100.00")
    assert person.b2b_willingness is None
    assert person.preferences["remote_modes"] == ["hybrid"]
    assert person.max_onsite_days_per_week == 1
    assert person.preferences["office_cities"] == ["Wrocław"]


async def test_duplicate_rate_is_not_written_at_intake(api):
    email = _email("dup-stawka")
    async with AsyncSessionLocal() as db:
        existing = Candidate(
            name="Osoba",
            lastname="Syntetyczna",
            email=email,
            source="manual",
            status=CandidateStatus.active,
        )
        db.add(existing)
        await db.commit()
        existing_id = existing.id
        version_before = existing.profile_rate_version

    resp = await _post(api, _form(email, rate="195"))

    assert resp.status_code == 201, resp.text
    person = await _candidate(email)
    assert person.expected_rate_hourly is None
    assert person.profile_rate_version == version_before
    async with AsyncSessionLocal() as db:
        audits = list(
            await db.scalars(
                select(Activity).where(
                    Activity.entity_id == existing_id,
                    Activity.action.in_(
                        ("profile_rate_changed", "candidate_work_mode_changed")
                    ),
                )
            )
        )
    assert audits == []
    [report] = await _reports(existing_id)
    assert report.conditions["rate"] == 195


# ── Opiekun po kolei ─────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def empty_pool():
    async with AsyncSessionLocal() as db:
        await db.execute(delete(CompetenceReportOwner))
        await db.commit()
    yield
    async with AsyncSessionLocal() as db:
        await db.execute(delete(CompetenceReportOwner))
        await db.commit()


async def test_empty_pool_gives_no_owner(api, empty_pool):
    async with AsyncSessionLocal() as db:
        assert await assign_owner(db) is None

    email = _email("bez-opiekuna")
    assert (await _post(api, _form(email))).status_code == 201
    [report] = await _reports((await _candidate(email)).id)
    assert report.owner_user_id is None


async def test_owner_round_robin_skips_inactive(api, empty_pool):
    first, second = await _new_user("a"), await _new_user("b")
    off_list, disabled = await _new_user("c"), await _new_user("d", active=False)
    async with AsyncSessionLocal() as db:
        db.add_all(
            [
                CompetenceReportOwner(user_id=second, position=2),
                CompetenceReportOwner(user_id=first, position=1),
                CompetenceReportOwner(user_id=off_list, position=0, active=False),
                CompetenceReportOwner(user_id=disabled, position=0),
            ]
        )
        await db.commit()

    owners = []
    for i in range(3):
        email = _email(f"kolejka-{i}")
        assert (await _post(api, _form(email))).status_code == 201
        [report] = await _reports((await _candidate(email)).id)
        owners.append(report.owner_user_id)

    assert owners == [first, second, first]


# ── Schemat: migracja, siatka entrypointu, sonda ─────────────────────────


def test_migration_reads_the_shared_ddl() -> None:
    migration = (_BACKEND / "alembic/versions/0792_competence_reports.py").read_text(
        encoding="utf-8"
    )
    assert 'down_revision = "0791_legal_client_fit"' in migration
    assert "for stmt in schema.TABLE_DDL:" in migration
    assert "for stmt in schema.DOWNGRADE_DDL:" in migration


def test_entrypoint_mirrors_the_ddl() -> None:
    entry = (_BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    assert "_competence_report_ddl.TABLE_DDL" in entry
    assert entry.count("_COMPETENCE_REPORT_DDL") >= 3, "lista musi być w fazie DDL"


def test_every_statement_is_idempotent() -> None:
    assert all("IF NOT EXISTS" in stmt for stmt in ddl.TABLE_DDL)


def test_status_check_matches_the_allowed_states() -> None:
    assert ddl.STATUSES == (
        "waiting_cv",
        "ready",
        "sent",
        "skipped",
        "opted_out",
        "failed",
    )


def test_deep_health_probes_both_tables() -> None:
    main = (_BACKEND / "app/main.py").read_text(encoding="utf-8")
    assert '("competence_reports", CompetenceReport)' in main
    assert '("competence_report_owners", CompetenceReportOwner)' in main
