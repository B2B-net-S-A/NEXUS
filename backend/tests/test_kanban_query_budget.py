"""Tablica (`build_kanban_view`): stała, ograniczona liczba zapytań.

18.11.2026 w szczycie `GET /api/pipeline/kanban/{job_id}` miał p95 18,2 s przy
średnio 94 zapytaniach. Pomiar na stagingu (kopia produkcji): 93–109 zapytań
niezależnie od rozmiaru Tablicy (148–1 992 kart) — nie N+1 po kartach, tylko
osobne zapytania odznak, część powtórzona w jednym żądaniu (nazwiska ×3,
definicje etapów ×3, domyślny szablon ×2, rodzina klienta ×2, auto-CV ×2).
Po zmianie: 44–90 zapytań, odpowiedź bajt w bajt ta sama
(`docs/performance-hot-routes-2026-11-completion-report.md`).

Koszt zapytania to ok. 1,4 ms CPU pętli zdarzeń
(`docs/claude/podstawy/stabilizacja-pod-obciazeniem-reguly-po-audycie-13.md`),
więc te testy patrzą na WYKONANY SQL: liczba nie rośnie z liczbą kart, ma sufit
i tabele, które czytano kilka razy, czyta się raz.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import app.models  # noqa: F401  (zarejestruj wszystkie mappery)
from sqlalchemy import event

from app.core.database import AsyncSessionLocal, engine

#: Najwięcej, ile Tablica z kopii produkcji wykonała po zmianie (90); przed
#: zmianą ta sama Tablica robiła 101.
KANBAN_STATEMENT_CEILING = 90

_TEMPLATE_STAGES = (
    "new",
    "screening",
    "cv_sent",
    "client_interview",
    "hired",
    "rejected",
)
_CARD_STAGES = ("new", "screening", "cv_sent", "rejected")


@contextmanager
def _capture_sql():
    seen: list[str] = []

    def _on(conn, cursor, statement, parameters, context, executemany):
        seen.append(" ".join(statement.split()))

    event.listen(engine.sync_engine, "before_cursor_execute", _on)
    try:
        yield seen
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _on)


def _reads_of(statements: list[str], table: str) -> list[str]:
    """Samodzielne odczyty tabeli (``SELECT <tabela>.…``) — bez zapytań, które
    tylko dołączają ją JOIN-em (opieka po odejściu, zegary klienta, terminarz)."""
    return [s for s in statements if s.startswith(f"SELECT {table}.")]


async def _seed_board(per_stage: int) -> int:
    """Rekrutacja z własnym szablonem: ``per_stage`` kart w każdym z etapów
    ``_CARD_STAGES`` i jedna osoba „Zatrudniona” bez umowy (rodzina klienta)."""
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
        client = Client(name=f"KanbanBudget-{tag}")
        template = PipelineTemplate(name=f"KanbanBudgetTpl-{tag}")
        db.add_all([client, template])
        await db.commit()
        await db.refresh(client)
        await db.refresh(template)
        terminal_for = {"hired": TerminalType.hired, "rejected": TerminalType.rejected}
        defs = {
            name: PipelineStageDef(
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
        }
        job = Job(
            title=f"KanbanBudgetJob-{tag}",
            status=JobStatus.published,
            client_id=client.id,
            pipeline_template_id=template.id,
        )
        db.add_all([job, *defs.values()])
        await db.commit()
        await db.refresh(job)

        plan = [s for s in _CARD_STAGES for _ in range(per_stage)] + ["hired"]
        candidates = [
            Candidate(
                name="Jan",
                lastname=f"KanbanBudget-{i}-{tag}",
                email=f"kanban-budget-{i}-{tag}@example.com",
                status=CandidateStatus.active,
            )
            for i in range(len(plan))
        ]
        db.add_all(candidates)
        await db.commit()
        for i, (cand, stage) in enumerate(zip(candidates, plan)):
            await db.refresh(cand)
            db.add(
                CandidateStage(
                    candidate_id=cand.id,
                    job_id=job.id,
                    stage=PipelineStage(stage),
                    stage_def_id=defs[stage].id,
                    moved_at=now - timedelta(days=2, minutes=i),
                )
            )
        await db.commit()
        return job.id


async def _board_statements(job_id: int) -> list[str]:
    from app.api.pipeline import build_kanban_view
    from app.models.job import Job

    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        with _capture_sql() as seen:
            await build_kanban_view(db, job)
        return list(seen)


async def test_kanban_statement_count_does_not_grow_with_cards():
    small = await _board_statements(await _seed_board(per_stage=2))
    large = await _board_statements(await _seed_board(per_stage=8))

    assert len(large) == len(small), (
        f"Tablica 4× większa wykonała {len(large)} zapytań zamiast {len(small)} — "
        "zapytanie w pętli po kartach."
    )


async def test_kanban_statement_count_stays_under_the_ceiling():
    statements = await _board_statements(await _seed_board(per_stage=3))

    assert len(statements) <= KANBAN_STATEMENT_CEILING, (
        f"Tablica wykonała {len(statements)} zapytań (sufit "
        f"{KANBAN_STATEMENT_CEILING}). Nowa odznaka = jedno zapytanie hurtowe "
        "albo dane z tych, które Tablica już czyta."
    )


async def test_kanban_reads_shared_lookups_once():
    """Nazwiska, definicje etapów, domyślny szablon, rodzina klienta i stan
    auto-CV czytało po kilka serwisów naraz — teraz raz na Tablicę."""
    statements = await _board_statements(await _seed_board(per_stage=2))

    # Nazwiska z kart: jedno zapytanie w `build_kanban_view` (zero, gdy na
    # kartach nie ma nikogo). Osobne ma tylko „Prowadzi” (`pair_owner`) —
    # tej Tablicy go nie ma.
    names = [
        s for s in statements if s.startswith("SELECT users.id, users.name FROM users")
    ]
    assert len(names) <= 1, names
    assert len(_reads_of(statements, "pipeline_stage_defs")) == 1
    assert len(_reads_of(statements, "pipeline_templates")) <= 1
    # Rodzina klienta = dwa zapytania (klient → korzeń, korzeń → scaleni);
    # liczymy pierwsze, czyli ile razy rodzinę czytano.
    family = [
        s
        for s in statements
        if "clients.merged_into_client_id FROM clients WHERE clients.id" in s
    ]
    assert len(family) == 1, family
    auto_cv = [s for s in statements if "DISTINCT cv_generated_documents.stage_id" in s]
    assert len(auto_cv) == 1, auto_cv


# ── Follow-up liczony tylko dla kart „czeka na klienta” ─────────────────────


class _FakeCatalog:
    """Katalog etapów jednego szablonu (``board_tasks._Catalog`` w miniaturze)."""

    def __init__(self, defs):
        self.defs = {d.id: d for d in defs}

    def effective_def_id(self, template_id, stage_def_id):
        return stage_def_id if stage_def_id in self.defs else None


def _def(def_id, name, legacy):
    from types import SimpleNamespace

    return SimpleNamespace(
        id=def_id,
        name=name,
        legacy_enum_value=legacy,
        category="internal",
        terminal_type=None,
    )


def test_board_waiting_ids_keeps_only_cards_waiting_for_the_client():
    from types import SimpleNamespace

    from app.services.candidate_followups import board_waiting_ids

    catalog = _FakeCatalog(
        [
            _def(1, "Nowi", "new"),
            _def(5, "CV Wysłane", "cv_sent"),
            _def(6, "Interview Klient", "client_interview"),
            _def(11, "Odrzucony", "rejected"),
        ]
    )
    stages = [
        SimpleNamespace(candidate_id=10, stage_def_id=1, stage="new"),
        SimpleNamespace(candidate_id=20, stage_def_id=5, stage="cv_sent"),
        SimpleNamespace(candidate_id=30, stage_def_id=6, stage="client_interview"),
        SimpleNamespace(candidate_id=40, stage_def_id=11, stage="rejected"),
        # Wiersz bez definicji etapu: kolumna z legacy enumu.
        SimpleNamespace(candidate_id=50, stage_def_id=None, stage="cv_sent"),
        # Etap bez odpowiednika w szablonie — „poza szablonem”, nie follow-up.
        SimpleNamespace(candidate_id=60, stage_def_id=999, stage="cv_sent"),
    ]

    assert board_waiting_ids(catalog, template_id=7, stages=stages) == [20, 30, 50]
