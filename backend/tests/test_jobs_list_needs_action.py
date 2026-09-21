"""`needs_action_count` listy rekrutacji == liczba kart „po stronie rekrutera" na tablicy.

Lista liczy jednym zagregowanym zapytaniem (``services/job_needs_action.py``),
tablica — regułą karty (``services/pipeline_next_action.py``). Obie wychodzą
z tej samej reguły, więc na tej samej rekrutacji muszą dać tę samą liczbę.
``sort=attention`` używa TEGO SAMEGO wyrażenia jako klucza, więc kolejność
i paginacja są spójne z licznikiem w wierszu.

Daty są względne do „teraz" (licznik zależy od wieku karty), a asercje dotyczą
wyłącznie własnych wierszy — baza testowa jest wspólna i nieczyszczona.
"""

import uuid
from datetime import date, datetime, timedelta, timezone

import app.models  # noqa: F401  (zarejestruj wszystkie mappery)
from httpx import AsyncClient

from app.services.pipeline_next_action import NUDGE_DAYS

CUSTOM_AFTER_SCREENING = "Przepuszczony przez DZ"
CUSTOM_AT_CLIENT = "Preparation Meeting"


async def _seed(*, cards: list[tuple[str, int]], deadline: date | None = None) -> dict:
    """Rekrutacja z własnym szablonem; ``cards`` = (nazwa kolumny, dni na etapie)."""
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate, CandidateStatus
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.pipeline_template import (
        PipelineStageDef,
        PipelineTemplate,
        StageCategoryEnum,
        TerminalType,
    )
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    tag = uuid.uuid4().hex[:8]
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        client = Client(name=f"NeedsActionClient-{tag}")
        template = PipelineTemplate(name=f"NeedsActionTpl-{tag}")
        db.add_all([client, template])
        await db.flush()
        job = Job(
            title=f"NeedsActionJob-{tag}",
            status=JobStatus.published,
            client_id=client.id,
            pipeline_template_id=template.id,
            deadline=deadline,
        )
        terminal_for = {"hired": TerminalType.hired, "rejected": TerminalType.rejected}
        spec = [
            ("Nowy", "new", StageCategoryEnum.internal),
            ("Screening", "screening", StageCategoryEnum.internal),
            (CUSTOM_AFTER_SCREENING, None, StageCategoryEnum.internal),
            ("Zweryfikowany", "verified", StageCategoryEnum.internal),
            ("CV Wysłane", "cv_sent", StageCategoryEnum.internal),
            (CUSTOM_AT_CLIENT, None, StageCategoryEnum.internal),
            ("Interview Klient", "client_interview", StageCategoryEnum.external),
            ("Akceptacja", "acceptance", StageCategoryEnum.external),
            ("Umowa wysłana", None, StageCategoryEnum.external),
            ("Zatrudniony", "hired", StageCategoryEnum.terminal),
            ("Odrzucony", "rejected", StageCategoryEnum.terminal),
        ]
        stage_defs = [
            PipelineStageDef(
                template_id=template.id,
                name=name,
                order=order,
                category=category,
                legacy_enum_value=legacy,
                is_terminal=legacy in terminal_for,
                terminal_type=terminal_for.get(legacy),
            )
            for order, (name, legacy, category) in enumerate(spec)
        ]
        db.add_all([job, *stage_defs])
        await db.flush()
        def_by_name = {sd.name: sd for sd in stage_defs}
        for index, (column, days) in enumerate(cards):
            candidate = Candidate(
                name="Ruch",
                lastname=f"NeedsAction-{index}-{tag}",
                email=f"needsaction-{index}-{tag}@example.com",
                status=CandidateStatus.active,
            )
            db.add(candidate)
            await db.flush()
            sd = def_by_name[column]
            db.add(
                CandidateStage(
                    candidate_id=candidate.id,
                    job_id=job.id,
                    stage=(
                        PipelineStage(sd.legacy_enum_value)
                        if sd.legacy_enum_value
                        else PipelineStage.new
                    ),
                    # Wiersze z legacy enumem celowo BEZ `stage_def_id` —
                    # tak zapisuje je `/bulk-move`; lista i tablica muszą je
                    # zmapować do kolumny po enumie.
                    stage_def_id=None if sd.legacy_enum_value else sd.id,
                    # Godzina zapasu: test nie może stać na granicy doby.
                    moved_at=now - timedelta(days=days, hours=1),
                )
            )
        await db.commit()
        return {"job_id": job.id, "client_id": client.id, "tag": tag}


async def _rows(app_client, headers, *, client_ids, **params) -> list[dict]:
    resp = await app_client.get(
        "/api/jobs",
        params={"include_stage_counts": "true", "client_id": client_ids, **params},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["items"]


async def _board_owner_count(app_client, headers, job_id: int) -> tuple[int, dict]:
    resp = await app_client.get(f"/api/pipeline/kanban/{job_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    owners: dict[str, list[str | None]] = {}
    for column in resp.json()["columns"]:
        owners[column["name"]] = [i["next_action_owner"] for i in column["items"]]
    flat = [o for values in owners.values() for o in values]
    return sum(1 for o in flat if o == "recruiter"), owners


CARDS = [
    ("Nowy", 0),
    ("Nowy", 9),
    ("Screening", 2),
    (CUSTOM_AFTER_SCREENING, 1),
    ("Zweryfikowany", 3),
    ("CV Wysłane", NUDGE_DAYS - 1),  # czeka na klienta
    ("CV Wysłane", NUDGE_DAYS),  # ruch wraca do rekrutera
    (CUSTOM_AT_CLIENT, 1),  # pozycyjnie „u klienta"
    (CUSTOM_AT_CLIENT, NUDGE_DAYS + 3),
    ("Interview Klient", 2),
    ("Akceptacja", 1),  # czeka na kandydata
    ("Akceptacja", NUDGE_DAYS + 1),
    ("Umowa wysłana", 0),  # podpis umowy — rekruter
    ("Zatrudniony", 1),  # Delivery
    ("Odrzucony", 30),  # nikt
]


async def test_list_count_equals_board_owner_count(
    app_client: AsyncClient, app_auth_headers: dict
):
    world = await _seed(cards=CARDS)
    count, owners = await _board_owner_count(
        app_client, app_auth_headers, world["job_id"]
    )

    # Tablica: reguła karty, z korektami pozycyjnymi grup.
    assert owners["CV Wysłane"].count("client") == 1
    assert owners["CV Wysłane"].count("recruiter") == 1
    assert sorted(owners[CUSTOM_AT_CLIENT]) == ["client", "recruiter"]
    assert sorted(owners["Akceptacja"]) == ["candidate", "recruiter"]
    assert owners[CUSTOM_AFTER_SCREENING] == ["recruiter"]
    assert owners["Umowa wysłana"] == ["recruiter"]
    assert owners["Zatrudniony"] == ["delivery"]
    assert owners["Odrzucony"] == ["none"]
    assert count == 9

    rows = await _rows(app_client, app_auth_headers, client_ids=[world["client_id"]])
    row = next(r for r in rows if r["id"] == world["job_id"])
    assert row["needs_action_count"] == count
    assert row["new_proposals_count"] == 0


async def test_counts_are_absent_without_stage_counts(
    app_client: AsyncClient, app_auth_headers: dict
):
    world = await _seed(cards=[("Nowy", 0)])
    resp = await app_client.get(
        "/api/jobs", params={"client_id": world["client_id"]}, headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    row = next(r for r in resp.json()["items"] if r["id"] == world["job_id"])
    assert "needs_action_count" not in row
    assert "new_proposals_count" not in row


async def test_sort_attention_orders_and_paginates_stably(
    app_client: AsyncClient, app_auth_headers: dict
):
    today = date.today()
    worlds = {
        "three": await _seed(cards=[("Nowy", 0), ("Nowy", 1), ("Screening", 0)]),
        "one_overdue": await _seed(
            cards=[("Nowy", 0)], deadline=today - timedelta(days=10)
        ),
        "one_soon": await _seed(
            cards=[("Nowy", 0)], deadline=today + timedelta(days=5)
        ),
        "one_later": await _seed(
            cards=[("Nowy", 0)], deadline=today + timedelta(days=50)
        ),
        "one_no_deadline": await _seed(cards=[("Nowy", 0)]),
        # Sami „u klienta" przed progiem i odrzuceni → zero po stronie rekrutera.
        "zero": await _seed(
            cards=[("CV Wysłane", 0), ("Odrzucony", 3)],
            deadline=today - timedelta(days=30),
        ),
        "empty": await _seed(cards=[]),
    }
    client_ids = [w["client_id"] for w in worlds.values()]
    name_by_job = {w["job_id"]: name for name, w in worlds.items()}

    full = await _rows(
        app_client, app_auth_headers, client_ids=client_ids, sort="attention"
    )
    assert [name_by_job[r["id"]] for r in full][:5] == [
        "three",
        "one_overdue",
        "one_soon",
        "one_later",
        "one_no_deadline",
    ]
    assert {name_by_job[r["id"]] for r in full[5:]} == {"zero", "empty"}
    assert [r["needs_action_count"] for r in full] == [3, 1, 1, 1, 1, 0, 0]
    # Przeterminowana rekrutacja bez ruchu rekrutera stoi przed pustą.
    assert name_by_job[full[5]["id"]] == "zero"

    paged: list[int] = []
    for page in (1, 2, 3, 4):
        resp = await app_client.get(
            "/api/jobs",
            params={
                "client_id": client_ids,
                "sort": "attention",
                "page": page,
                "page_size": 2,
            },
            headers=app_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == 7
        paged.extend(r["id"] for r in body["items"])
    assert paged == [r["id"] for r in full]


async def test_board_card_carries_recruiter_availability_and_warning_codes(
    app_client: AsyncClient, app_auth_headers: dict
):
    from datetime import date as _date
    from decimal import Decimal

    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.candidate import AvailabilityStatus, Candidate
    from app.models.candidate_conflict import CandidateConflict, ConflictType
    from app.models.recruitment_pipeline import CandidateStage
    from app.models.user import User

    world = await _seed(cards=[("Zweryfikowany", 2), ("Nowy", 0)])
    async with AsyncSessionLocal() as db:
        mover = await db.scalar(select(User).order_by(User.id).limit(1))
        stages = (
            (
                await db.execute(
                    select(CandidateStage)
                    .where(CandidateStage.job_id == world["job_id"])
                    .order_by(CandidateStage.id)
                )
            )
            .scalars()
            .all()
        )
        flagged, plain = stages
        flagged.moved_by = mover.id
        # Stawka ponad budżet zamrożony na etapie → `budget_exceeded`.
        flagged.expected_rate_value = Decimal("50000")
        flagged.expected_rate_unit = "monthly"
        flagged.expected_rate_currency = "PLN"
        flagged.budget_max_at_move = 20000
        candidate = await db.get(Candidate, flagged.candidate_id)
        candidate.availability_status = AvailabilityStatus.actively_looking
        candidate.availability_date = _date(2041, 3, 1)
        db.add(
            CandidateConflict(
                candidate_id=flagged.candidate_id,
                client_id=world["client_id"],
                type=ConflictType.nda,
                active=True,
                expires_at=datetime.now(timezone.utc) + timedelta(days=90),
            )
        )
        await db.commit()
        flagged_id, plain_id, mover_id = flagged.id, plain.id, mover.id

    resp = await app_client.get(
        f"/api/pipeline/kanban/{world['job_id']}", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    cards = {i["id"]: i for c in resp.json()["columns"] for i in c["items"]}

    card = cards[flagged_id]
    assert card["recruiter_id"] == mover_id
    assert card["recruiter_name"]
    assert card["availability_status"] == "actively_looking"
    assert card["availability_date"] == "2041-03-01"
    assert card["warnings"] == ["budget_exceeded", "client_nda"]
    assert card["next_action_owner"] == "recruiter"

    other = cards[plain_id]
    assert other["warnings"] == []
    assert other["recruiter_id"] is None
    assert other["availability_date"] is None
