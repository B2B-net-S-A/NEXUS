"""Kafelki pulpitu „Ludzi w NEXUSIE” (17.10.2026).

* Cztery nowe typy kafelków zapisują się w układzie pulpitu (lustro frontu
  pilnuje ``test_dashboard_tile_types_mirror.py``).
* „W zastępstwie” (``GET /api/hr/dashboard/substitution``) liczy wyłącznie to,
  co silnik zastępstw przekazał osobie: rekrutacje nieobecnego (Rekruter bez
  uśpienia albo DL, otwarte), jego rozmowy u klienta do końca zastępstwa i jego
  otwarte procesy. Ostrzeżenie „zastępca nieobecny” widzi wpisany zastępca
  i przełożony nieobecnego, nikt inny. Wyłączony moduł urlopów = 404, konto
  techniczne = 403.

Silnik (``workforce_context``) podmieniamy na gotowy kontekst — jego reguły
mają własne testy; tu sprawdzamy, co kafelek z nich robi. Dane fikcyjne.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today, local_day_start_utc
from app.core.security import create_access_token
from app.models.app_setting import AppSetting
from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.hr_profile import EmployeeProfile
from app.models.job import Job, JobStatus
from app.models.job_previous_recruiter import JobPreviousRecruiter
from app.models.recruitment_process import ProcessStatus, RecruitmentProcess
from app.models.user import User, UserRole
from app.services import dashboard_tiles
from app.services.hr import substitution_summary as summary_module
from app.services.hr_foundation_schema import HR_MODULE_KEYS, HR_MODULES_SETTING
from app.services.workforce_availability import Delegation, WorkforceContext

URL = "/api/hr/dashboard/substitution"
HR_TILE_TYPES = ("hr_substitution", "hr_my_time", "hr_approvals", "equipment_tasks")


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.id, role=user.role.value)
    return {"Authorization": f"Bearer {token}"}


async def _user(db, role: str, *, manager_id: int | None = None) -> User:
    marker = uuid.uuid4().hex[:10]
    user = User(
        email=f"tile-{marker}@example.com",
        name=f"Osoba {marker}",
        role=UserRole(role),
        roles=[role],
        is_active=True,
    )
    db.add(user)
    await db.flush()
    if manager_id is not None:
        db.add(EmployeeProfile(user_id=user.id, manager_user_id=manager_id))
        await db.flush()
    return user


async def _set_modules(value: dict) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, HR_MODULES_SETTING)
        if row is None:
            db.add(AppSetting(key=HR_MODULES_SETTING, value=value))
        else:
            row.value = value
        await db.commit()


async def _modules(value: dict):
    async with AsyncSessionLocal() as db:
        previous = await db.scalar(
            select(AppSetting.value).where(AppSetting.key == HR_MODULES_SETTING)
        )
    await _set_modules(value)
    return previous or {key: False for key in HR_MODULE_KEYS}


@pytest_asyncio.fixture
async def modules_on():
    previous = await _modules({key: True for key in HR_MODULE_KEYS})
    yield
    await _set_modules(previous)


@pytest_asyncio.fixture
async def modules_off():
    previous = await _modules({key: False for key in HR_MODULE_KEYS})
    yield
    await _set_modules(previous)


def _engine(monkeypatch, context: WorkforceContext) -> None:
    async def fake_context(db, *, refresh: bool = False) -> WorkforceContext:
        return context

    monkeypatch.setattr(summary_module, "workforce_context", fake_context)


# ── Typy kafelków ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("tile_type", HR_TILE_TYPES)
def test_layout_accepts_hr_tile_types(tile_type: str) -> None:
    layout = dashboard_tiles.DashboardLayout.model_validate(
        {
            "tiles": [
                {
                    "id": str(uuid.uuid4()),
                    "type": tile_type,
                    "x": 0,
                    "y": 0,
                    "w": 6,
                    "h": 3,
                }
            ]
        }
    )
    assert layout.tiles[0].type == tile_type


def test_hr_tile_rejects_metric_and_board_scope() -> None:
    base = {
        "id": str(uuid.uuid4()),
        "type": "hr_my_time",
        "x": 0,
        "y": 0,
        "w": 6,
        "h": 3,
    }
    with pytest.raises(ValueError):
        dashboard_tiles.DashboardTile.model_validate(
            {**base, "config": {"board_scope": "all"}}
        )


@pytest.mark.asyncio
async def test_dashboard_saves_and_reads_hr_tiles(app_client) -> None:
    async with AsyncSessionLocal() as db:
        person = await _user(db, "recruiter")
        await db.commit()
    tiles = [
        {
            "id": str(uuid.uuid4()),
            "type": tile_type,
            "x": 0,
            "y": index * 3,
            "w": 6,
            "h": 3,
        }
        for index, tile_type in enumerate(HR_TILE_TYPES)
    ]
    saved = await app_client.put(
        "/api/users/me/dashboard",
        json={"tiles": tiles, "expected_version": 0},
        headers=_headers(person),
    )
    assert saved.status_code == 200, saved.text
    read = await app_client.get("/api/users/me/dashboard", headers=_headers(person))
    assert [tile["type"] for tile in read.json()["tiles"]] == list(HR_TILE_TYPES)
    assert read.json()["dropped_tiles"] == []


# ── „W zastępstwie”: bramka ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_substitution_is_404_with_leave_module_off_except_admin(
    app_client, modules_off, monkeypatch
) -> None:
    _engine(monkeypatch, WorkforceContext())
    async with AsyncSessionLocal() as db:
        recruiter = await _user(db, "recruiter")
        admin = await _user(db, "admin")
        await db.commit()

    denied = await app_client.get(URL, headers=_headers(recruiter))
    assert denied.status_code == 404
    assert denied.json()["detail"] == "Ten moduł nie jest jeszcze włączony."
    allowed = await app_client.get(URL, headers=_headers(admin))
    assert allowed.status_code == 200, allowed.text


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["automation", "user"])
async def test_substitution_refuses_technical_and_viewer_accounts(
    app_client, modules_on, monkeypatch, role: str
) -> None:
    _engine(monkeypatch, WorkforceContext())
    async with AsyncSessionLocal() as db:
        account = await _user(db, role)
        await db.commit()

    response = await app_client.get(URL, headers=_headers(account))
    assert response.status_code == 403
    assert response.json()["detail"] == "Zastępstwa widzą pracownicy firmy."


@pytest.mark.asyncio
async def test_substitution_without_cover_is_empty(
    app_client, modules_on, monkeypatch
) -> None:
    _engine(monkeypatch, WorkforceContext(fresh=True))
    async with AsyncSessionLocal() as db:
        recruiter = await _user(db, "recruiter")
        await db.commit()

    body = (await app_client.get(URL, headers=_headers(recruiter))).json()
    assert body["items"] == []
    assert body["warnings"] == []
    assert body["fresh"] is True


# ── „W zastępstwie”: co liczy ─────────────────────────────────────────────────


def _at(day: date, hour: int) -> datetime:
    return local_day_start_utc(day) + timedelta(hours=hour)


@pytest.mark.asyncio
async def test_substitution_counts_only_work_the_engine_handed_over(
    app_client, modules_on, monkeypatch
) -> None:
    today = business_today()
    end = today + timedelta(days=3)
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        absent = await _user(db, "delivery_lead")
        cover = await _user(db, "delivery_lead")
        stranger = await _user(db, "delivery_lead")
        client = Client(name=f"Klient Przykładowy {tag}")
        db.add(client)
        await db.flush()
        recruited = Job(
            title=f"Java {tag}",
            working_title=f"Java Developer {tag}",
            status=JobStatus.published,
            is_open=True,
            client_id=client.id,
            recruiter_id=absent.id,
        )
        led = Job(
            title=f"QA {tag}",
            status=JobStatus.published,
            is_open=True,
            client_id=client.id,
            delivery_lead_id=absent.id,
            recruiter_id=cover.id,
        )
        closed = Job(
            title=f"Zamknięta {tag}",
            status=JobStatus.closed,
            is_open=False,
            client_id=client.id,
            recruiter_id=absent.id,
        )
        parked = Job(
            title=f"Uśpiona {tag}",
            status=JobStatus.published,
            is_open=True,
            client_id=client.id,
            recruiter_id=absent.id,
        )
        foreign = Job(
            title=f"Cudza {tag}",
            status=JobStatus.published,
            is_open=True,
            client_id=client.id,
            recruiter_id=stranger.id,
        )
        db.add_all([recruited, led, closed, parked, foreign])
        await db.flush()
        db.add(
            JobPreviousRecruiter(
                job_id=parked.id, user_id=absent.id, via="owner", reason="priority"
            )
        )
        tomorrow = today + timedelta(days=1)
        far = datetime.now(timezone.utc) + timedelta(days=30)

        def event(start: datetime, *, kind=EventType.client_interview, owner=absent):
            return CalendarEvent(
                title="Rozmowa u klienta: Kandydat Przykładowy",
                event_type=kind,
                start_time=start,
                status=EventStatus.scheduled,
                created_by=owner.id,
                operational_owner_id=owner.id,
                job_id=recruited.id,
            )

        db.add_all(
            [
                event(_at(tomorrow, 8)),
                event(_at(end, 12)),
                event(datetime.now(timezone.utc) - timedelta(hours=2)),  # już było
                event(far),  # po zastępstwie
                event(_at(tomorrow, 9), kind=EventType.prep_call),  # nie u klienta
                event(_at(tomorrow, 10), owner=stranger),
            ]
        )
        candidates = [
            Candidate(name="Kandydat", lastname=f"Przykładowy{tag}{i}")
            for i in range(3)
        ]
        db.add_all(candidates)
        await db.flush()
        db.add_all(
            [
                RecruitmentProcess(
                    candidate_id=candidates[0].id,
                    job_id=recruited.id,
                    status=ProcessStatus.open,
                    owner_user_id=absent.id,
                ),
                RecruitmentProcess(
                    candidate_id=candidates[1].id,
                    job_id=led.id,
                    status=ProcessStatus.open,
                    owner_user_id=absent.id,
                ),
                RecruitmentProcess(
                    candidate_id=candidates[2].id,
                    job_id=recruited.id,
                    status=ProcessStatus.closed,
                    owner_user_id=absent.id,
                ),
            ]
        )
        await db.commit()

    _engine(
        monkeypatch,
        WorkforceContext(
            fresh=True,
            delegations={
                absent.id: Delegation(
                    owner_id=absent.id,
                    performer_id=cover.id,
                    start_date=today - timedelta(days=1),
                    end_date=end,
                    source_ids=("a",),
                )
            },
        ),
    )

    body = (await app_client.get(URL, headers=_headers(cover))).json()
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["owner_user_id"] == absent.id
    assert item["owner_name"] == absent.name
    assert item["end_date"] == end.isoformat()
    # Rekruter i DL nieobecnego; bez zamkniętej, uśpionej i cudzej.
    assert item["recruitments"]["count"] == 2
    titles = {row["title"] for row in item["recruitments"]["items"]}
    assert titles == {f"Java Developer {tag}", f"QA {tag}"}
    assert {row["client_name"] for row in item["recruitments"]["items"]} == {
        f"Klient Przykładowy {tag}"
    }
    # Dwie rozmowy u klienta nieobecnego w oknie zastępstwa.
    assert item["client_meetings"]["count"] == 2
    assert (
        item["client_meetings"]["items"][0]["client_name"]
        == f"Klient Przykładowy {tag}"
    )
    assert item["pipeline_cards"] == 2

    # Ten sam kontekst nie daje niczego osobie, która nie zastępuje.
    other = (await app_client.get(URL, headers=_headers(stranger))).json()
    assert other["items"] == []


@pytest.mark.asyncio
async def test_absent_substitute_warning_reaches_substitute_and_manager_only(
    app_client, modules_on, monkeypatch
) -> None:
    async with AsyncSessionLocal() as db:
        manager = await _user(db, "delivery_lead")
        absent = await _user(db, "recruiter", manager_id=manager.id)
        substitute = await _user(db, "recruiter")
        colleague = await _user(db, "recruiter")
        await db.commit()

    _engine(
        monkeypatch,
        WorkforceContext(
            fresh=True,
            issues=[
                {
                    "user_id": absent.id,
                    "substitute_id": substitute.id,
                    "code": "substitute_absent",
                },
                # Inne wyjątki silnika nie są tym ostrzeżeniem.
                {
                    "user_id": absent.id,
                    "substitute_id": None,
                    "code": "substitute_missing",
                },
            ],
        ),
    )

    as_substitute = (await app_client.get(URL, headers=_headers(substitute))).json()
    assert as_substitute["warnings"] == [
        {
            "owner_user_id": absent.id,
            "owner_name": absent.name,
            "substitute_user_id": substitute.id,
            "substitute_name": substitute.name,
            "you_are_substitute": True,
        }
    ]
    as_manager = (await app_client.get(URL, headers=_headers(manager))).json()
    assert [w["you_are_substitute"] for w in as_manager["warnings"]] == [False]
    assert as_manager["warnings"][0]["owner_name"] == absent.name
    as_colleague = (await app_client.get(URL, headers=_headers(colleague))).json()
    assert as_colleague["warnings"] == []
    # Ani rodzaju nieobecności, ani dat urlopu w ostrzeżeniu (D6).
    assert set(as_manager["warnings"][0]) == {
        "owner_user_id",
        "owner_name",
        "substitute_user_id",
        "substitute_name",
        "you_are_substitute",
    }
