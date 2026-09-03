"""Tablica nie może gubić kart.

``get_kanban`` bucketuje wiersze dwiema ścieżkami — po ``stage_def_id`` i
awaryjnie po legacy enumie — a karta, która nie trafi w żadną, **znikała bez
śladu**: bez kolumny, bez licznika, bez ostrzeżenia. Produkcyjny szablon
„Default B2B" nie ma kolumny dla etapu ``interview``, więc pomiar z 2026-09-02
pokazał 1 633 niewidoczne karty na 1 009 z 3 950 rekrutacji (rekrutacja 1412:
92 pary w bazie, 89 kart na tablicy).

Te testy przypinają inwariant, którego brakowało: **każda para pojawia się na
tablicy dokładnie raz** — albo w kolumnie szablonu, albo w kubełku
``off_template``.

Kubełek celowo NIE ma ``stage``/``stage_def_id``/``category``: bez identyfikatora
na drucie jest nieadresowalny jako cel ``POST /api/pipeline/move``, więc nie da
się do niego przenieść kandydata przypadkiem. Pilnuje tego
``test_off_template_bucket_carries_no_move_target_identity``.

Rok 2034 wybrany, bo baza testowa jest wspólna dla przebiegu i nieczyszczona —
rok zajęty przez sąsiedni plik wraca jako „regresja" w kodzie, którego nikt nie
ruszał.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import app.models  # noqa: F401  (zarejestruj wszystkie mappery)
from app.models.skill import Skill  # noqa: F401
from httpx import AsyncClient

NOW = datetime(2034, 5, 12, 9, 0, tzinfo=timezone.utc)

# Szablon celowo BEZ `interview` i BEZ `prep_call` — odtwarza kształt
# produkcyjnego „Default B2B", na którym karty ginęły.
_TEMPLATE_STAGES = ("new", "screening", "cv_sent", "hired", "rejected")


async def _seed_board() -> dict:
    """Trzy kandydaci na jednej rekrutacji, każdy w innej relacji do szablonu.

    * ``mapped``   — etap ma kolumnę (trafia do niej fallbackiem po enumie),
    * ``orphan``   — etap ``interview``, którego szablon nie ma → kubełek,
    * ``foreign``  — ``stage_def_id`` z OBCEGO szablonu i legacy enum też spoza
      szablonu (kształt importu z Traffita) → kubełek.
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
        client = Client(name=f"OffTplClient-{tag}")
        db.add(client)
        await db.commit()
        await db.refresh(client)

        template = PipelineTemplate(name=f"OffTplTpl-{tag}")
        foreign_template = PipelineTemplate(name=f"OffTplForeign-{tag}")
        db.add_all([template, foreign_template])
        await db.commit()
        await db.refresh(template)
        await db.refresh(foreign_template)

        job = Job(
            title=f"OffTplJob-{tag}",
            status=JobStatus.published,
            client_id=client.id,
            pipeline_template_id=template.id,
        )
        terminal_for = {
            "hired": TerminalType.hired,
            "rejected": TerminalType.rejected,
        }
        stage_defs = [
            PipelineStageDef(
                template_id=template.id,
                name=name,
                order=order,
                category=(
                    StageCategoryEnum.terminal
                    if name in terminal_for
                    else StageCategoryEnum.internal
                ),
                legacy_enum_value=name,
                is_terminal=name in terminal_for,
                terminal_type=terminal_for.get(name),
            )
            for order, name in enumerate(_TEMPLATE_STAGES)
        ]
        # Etap z obcego szablonu — istnieje, ale nie należy do tej rekrutacji.
        foreign_def = PipelineStageDef(
            template_id=foreign_template.id,
            name=f"Etap obcego szablonu {tag}",
            order=0,
            category=StageCategoryEnum.internal,
            legacy_enum_value=None,
            is_terminal=False,
        )
        candidates = {
            key: Candidate(
                name="Jan",
                lastname=f"OffTpl-{key}-{tag}",
                email=f"offtpl-{key}-{tag}@example.com",
                status=CandidateStatus.active,
            )
            for key in ("mapped", "orphan", "foreign")
        }
        db.add_all([job, foreign_def, *stage_defs, *candidates.values()])
        await db.commit()
        await db.refresh(job)
        await db.refresh(foreign_def)
        for cand in candidates.values():
            await db.refresh(cand)

        db.add_all(
            [
                CandidateStage(
                    candidate_id=candidates["mapped"].id,
                    job_id=job.id,
                    stage=PipelineStage.screening,
                    moved_at=NOW - timedelta(days=3),
                ),
                CandidateStage(
                    candidate_id=candidates["orphan"].id,
                    job_id=job.id,
                    stage=PipelineStage.interview,
                    moved_at=NOW - timedelta(days=2),
                ),
                CandidateStage(
                    candidate_id=candidates["foreign"].id,
                    job_id=job.id,
                    stage=PipelineStage.prep_call,
                    stage_def_id=foreign_def.id,
                    moved_at=NOW - timedelta(days=1),
                ),
            ]
        )
        await db.commit()

        return {
            "job_id": job.id,
            "template_id": template.id,
            "foreign_def_id": foreign_def.id,
            "foreign_def_name": foreign_def.name,
            "mapped_id": candidates["mapped"].id,
            "orphan_id": candidates["orphan"].id,
            "foreign_id": candidates["foreign"].id,
        }


async def _board(app_client: AsyncClient, headers: dict, job_id: int) -> dict:
    resp = await app_client.get(f"/api/pipeline/kanban/{job_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _column_candidate_ids(board: dict) -> list[int]:
    return [c["candidate_id"] for col in board["columns"] for c in col["items"]]


def _bucket_candidate_ids(board: dict) -> list[int]:
    bucket = board.get("off_template")
    if not bucket:
        return []
    return [c["candidate_id"] for c in bucket["items"]]


# ── Defekt ───────────────────────────────────────────────────────────────────


async def test_card_on_stage_missing_from_template_lands_in_off_template_bucket(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Kandydat na `interview` w szablonie bez tej kolumny — dziś znika."""
    world = await _seed_board()
    board = await _board(app_client, app_auth_headers, world["job_id"])

    assert world["orphan_id"] not in _column_candidate_ids(board), (
        "Kandydat na etapie spoza szablonu nie może udawać, że stoi w kolumnie "
        "szablonu — to zafałszowałoby lejek."
    )
    bucket = board["off_template"]
    assert bucket is not None, "Karta zniknęła z tablicy zamiast trafić do kubełka."
    assert world["orphan_id"] in _bucket_candidate_ids(board)
    assert "Interview Wewnętrzny" in bucket["missing_stage_labels"]


async def test_every_pair_appears_exactly_once_on_the_board(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Partycja wyczerpująca i rozłączna — nic nie ginie i nic się nie dubluje."""
    world = await _seed_board()
    board = await _board(app_client, app_auth_headers, world["job_id"])

    seeded = {world["mapped_id"], world["orphan_id"], world["foreign_id"]}
    in_columns = _column_candidate_ids(board)
    in_bucket = _bucket_candidate_ids(board)
    everywhere = in_columns + in_bucket

    assert set(everywhere) >= seeded, "Któraś z zasianych par zniknęła z tablicy."
    ours = [cid for cid in everywhere if cid in seeded]
    assert len(ours) == len(seeded), (
        "Karta pojawiła się na tablicy więcej niż raz — duplikat jest gorszy "
        "niż brak, bo fałszuje liczniki kolumn."
    )
    assert world["mapped_id"] in in_columns
    assert {world["orphan_id"], world["foreign_id"]} <= set(in_bucket)


async def test_off_template_carries_the_foreign_stage_name(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Kubełek ma nazwać etap, na którym stoi karta — inaczej nie da się jej wyprowadzić."""
    world = await _seed_board()
    board = await _board(app_client, app_auth_headers, world["job_id"])

    labels = board["off_template"]["missing_stage_labels"]
    assert world["foreign_def_name"] in labels, (
        f"Oczekiwano nazwy etapu z obcego szablonu wśród {labels}."
    )


async def test_off_template_count_matches_items(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Lustro asercji `test_kanban_view` rozszerzone na kubełek."""
    world = await _seed_board()
    board = await _board(app_client, app_auth_headers, world["job_id"])

    bucket = board["off_template"]
    assert bucket["count"] == len(bucket["items"])


# ── Kontrakt: kubełek nie jest celem ruchu ───────────────────────────────────


async def test_off_template_bucket_carries_no_move_target_identity(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Brak identyfikatora = brak możliwości upuszczenia karty w kubełek.

    Gdyby kubełek niósł `stage`, front wysłałby go w `POST /move` i backend
    rozwiązałby etap po `legacy_enum_value` — czyli po cichu przeniósłby
    kandydata na przypadkowy etap. Ten test pęka, gdy ktoś „uzupełni" model
    przez analogię do `KanbanColumn`.
    """
    world = await _seed_board()
    board = await _board(app_client, app_auth_headers, world["job_id"])

    assert set(board["off_template"].keys()) == {
        "name",
        "count",
        "items",
        "missing_stage_labels",
    }


async def test_off_template_absent_when_template_covers_every_card(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Zdrowa tablica nie dostaje pustego kubełka — stale pusty uczyłby go ignorować."""
    from app.core.database import AsyncSessionLocal
    from sqlalchemy import delete
    from app.models.recruitment_pipeline import CandidateStage

    world = await _seed_board()
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(CandidateStage).where(
                CandidateStage.job_id == world["job_id"],
                CandidateStage.candidate_id.in_(
                    [world["orphan_id"], world["foreign_id"]]
                ),
            )
        )
        await db.commit()

    board = await _board(app_client, app_auth_headers, world["job_id"])
    assert board["off_template"] is None


# ── Czysta funkcja: najtańszy trwały strażnik ────────────────────────────────


def test_bucket_partition_is_exhaustive_and_disjoint():
    """Bez DB i bez HTTP — przeżyje refaktor endpointu."""
    from types import SimpleNamespace

    from app.api.pipeline import _bucket_by_stage_def
    from app.models.recruitment_pipeline import PipelineStage

    stage_defs = [
        SimpleNamespace(id=1, legacy_enum_value="new"),
        SimpleNamespace(id=2, legacy_enum_value="screening"),
        SimpleNamespace(id=3, legacy_enum_value=None),  # custom, bez mapowania
    ]
    entries = [
        SimpleNamespace(candidate_id=10, stage_def_id=1, stage=PipelineStage.new),
        SimpleNamespace(candidate_id=11, stage_def_id=3, stage=PipelineStage.hired),
        SimpleNamespace(
            candidate_id=12, stage_def_id=None, stage=PipelineStage.screening
        ),
        # Sierota: def spoza szablonu, a enum bez kolumny.
        SimpleNamespace(candidate_id=13, stage_def_id=99, stage=PipelineStage.interview),
        # Sierota: brak def, enum bez kolumny.
        SimpleNamespace(
            candidate_id=14, stage_def_id=None, stage=PipelineStage.acceptance
        ),
    ]

    columns_map, off_template = _bucket_by_stage_def(entries, stage_defs)

    bucketed = [e for col in columns_map.values() for e in col] + list(off_template)
    assert len(bucketed) == len(entries), "Partycja gubi albo dubluje wpisy."
    assert {id(e) for e in bucketed} == {id(e) for e in entries}
    assert {e.candidate_id for e in off_template} == {13, 14}
    assert columns_map[1] == [entries[0]]
    assert columns_map[2] == [entries[2]]
    assert columns_map[3] == [entries[1]]
