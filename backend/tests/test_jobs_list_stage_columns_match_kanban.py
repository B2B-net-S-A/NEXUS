"""Lista rekrutacji i tablica liczą etapy z JEDNEJ definicji kolumn (UAT B33).

Do 09.2026 `GET /api/jobs?include_stage_counts=true` zwracał wyłącznie
`stage_breakdown` po legacy enumie `CandidateStage.stage`, a tablica
(`GET /api/pipeline/kanban/{id}`) kolumny szablonu. Własny etap szablonu bez
enuma („Przepuszczony przez DZ") niósł `stage=new`, więc lista liczyła go do
„Nowi", a front szczegółów — po pozycji za screeningiem — do „Zweryfikowani".
Ta sama rekrutacja: 4/1/1/2 na liście i 3/1/2/2 w szczegółach.

Teraz wiersz listy niesie `stage_columns`: te same kolumny (id definicji,
nazwa, enum, kategoria, terminal) i te same liczby co `columns` tablicy —
zbudowane tą samą funkcją kubełkującą. Front grupuje obie powierzchnie jedną
funkcją (`groupKanbanColumns`), więc liczby nie mają jak się rozjechać.

Rok 2041 wybrany, bo baza testowa jest wspólna dla przebiegu i nieczyszczona.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import app.models  # noqa: F401  (zarejestruj wszystkie mappery)
from app.models.skill import Skill  # noqa: F401
from httpx import AsyncClient

NOW = datetime(2041, 2, 3, 9, 0, tzinfo=timezone.utc)

CUSTOM_STAGE = "Przepuszczony przez DZ"


async def _seed() -> dict:
    """Szablon: new → screening → [własny etap bez enuma] → cv_sent → hired/rejected.

    Kandydaci: jeden na `new`, jeden na `screening`, jeden na własnym etapie
    (wiersz niesie `stage=new` — dokładnie kształt z produkcji).
    """
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
    async with AsyncSessionLocal() as db:
        client = Client(name=f"StageColsClient-{tag}")
        template = PipelineTemplate(name=f"StageColsTpl-{tag}")
        db.add_all([client, template])
        await db.commit()
        await db.refresh(client)
        await db.refresh(template)

        job = Job(
            title=f"StageColsJob-{tag}",
            status=JobStatus.published,
            client_id=client.id,
            pipeline_template_id=template.id,
        )
        terminal_for = {
            "hired": TerminalType.hired,
            "rejected": TerminalType.rejected,
        }
        spec = [
            ("Nowy", "new"),
            ("Screening", "screening"),
            (CUSTOM_STAGE, None),
            ("CV Wysłane", "cv_sent"),
            ("Zatrudniony", "hired"),
            ("Odrzucony", "rejected"),
        ]
        stage_defs = [
            PipelineStageDef(
                template_id=template.id,
                name=name,
                order=order,
                category=(
                    StageCategoryEnum.terminal
                    if legacy in terminal_for
                    else StageCategoryEnum.internal
                ),
                legacy_enum_value=legacy,
                is_terminal=legacy in terminal_for,
                terminal_type=terminal_for.get(legacy),
            )
            for order, (name, legacy) in enumerate(spec)
        ]
        candidates = {
            key: Candidate(
                name="Jan",
                lastname=f"StageCols-{key}-{tag}",
                email=f"stagecols-{key}-{tag}@example.com",
                status=CandidateStatus.active,
            )
            for key in ("fresh", "screened", "custom")
        }
        db.add_all([job, *stage_defs, *candidates.values()])
        await db.commit()
        await db.refresh(job)
        for sd in stage_defs:
            await db.refresh(sd)
        for cand in candidates.values():
            await db.refresh(cand)
        custom_def = next(sd for sd in stage_defs if sd.name == CUSTOM_STAGE)

        db.add_all(
            [
                CandidateStage(
                    candidate_id=candidates["fresh"].id,
                    job_id=job.id,
                    stage=PipelineStage.new,
                    moved_at=NOW - timedelta(days=3),
                ),
                CandidateStage(
                    candidate_id=candidates["screened"].id,
                    job_id=job.id,
                    stage=PipelineStage.screening,
                    moved_at=NOW - timedelta(days=2),
                ),
                # Własny etap: `stage_def_id` wskazuje kolumnę, legacy enum = new.
                CandidateStage(
                    candidate_id=candidates["custom"].id,
                    job_id=job.id,
                    stage=PipelineStage.new,
                    stage_def_id=custom_def.id,
                    moved_at=NOW - timedelta(days=1),
                ),
            ]
        )
        await db.commit()
        return {
            "job_id": job.id,
            "client_id": client.id,
            "custom_def_id": custom_def.id,
        }


async def _list_row(app_client: AsyncClient, headers: dict, world: dict) -> dict:
    resp = await app_client.get(
        "/api/jobs",
        params={"include_stage_counts": "true", "client_id": world["client_id"]},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    rows = [r for r in resp.json()["items"] if r["id"] == world["job_id"]]
    assert rows, "Zasiana rekrutacja nie wróciła z listy."
    return rows[0]


async def _board(app_client: AsyncClient, headers: dict, job_id: int) -> dict:
    resp = await app_client.get(f"/api/pipeline/kanban/{job_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _counts_by_def(columns: list[dict]) -> dict[int, int]:
    return {c["stage_def_id"]: c["count"] for c in columns}


async def test_list_stage_columns_equal_kanban_columns(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Kandydat na własnym etapie szablonu liczy się tak samo na liście i tablicy."""
    world = await _seed()
    row = await _list_row(app_client, app_auth_headers, world)
    board = await _board(app_client, app_auth_headers, world["job_id"])

    assert "stage_columns" in row, (
        "Wiersz listy nie niesie kolumn szablonu — lista liczy po legacy enumie, "
        "a tablica po kolumnach; własny etap ląduje w dwóch różnych kubełkach."
    )
    assert _counts_by_def(row["stage_columns"]) == _counts_by_def(board["columns"])
    assert _counts_by_def(row["stage_columns"])[world["custom_def_id"]] == 1
    assert row["off_template_count"] == 0


async def test_list_stage_columns_carry_the_same_fields_as_the_board(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Front grupuje po `stage`/`category`/`terminal_type`/`name` — muszą być identyczne."""
    world = await _seed()
    row = await _list_row(app_client, app_auth_headers, world)
    board = await _board(app_client, app_auth_headers, world["job_id"])

    fields = (
        "stage_def_id",
        "stage",
        "category",
        "name",
        "order",
        "terminal_type",
        "count",
    )
    assert [{k: c[k] for k in fields} for c in row["stage_columns"]] == [
        {k: c[k] for k in fields} for c in board["columns"]
    ]


async def test_legacy_breakdown_still_counts_every_pair(
    app_client: AsyncClient, app_auth_headers: dict
):
    """`stage_breakdown` zostaje dla starszych konsumentów i nadal sumuje się do par."""
    world = await _seed()
    row = await _list_row(app_client, app_auth_headers, world)

    assert sum(row["stage_breakdown"].values()) == 3
    assert sum(c["count"] for c in row["stage_columns"]) == 3
