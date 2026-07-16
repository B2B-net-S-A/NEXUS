"""Bootstrap i walidacja wersjonowanych workflow (M4 plan PR-05).

``bootstrap_workflow_revisions``: dla każdego nie-zarchiwizowanego legacy
``PipelineTemplate`` bez ``WorkflowDefinition`` tworzy definition + rewizję
nr 1 (published) z:

- ``StageRevision`` per legacy stage — ``semantic_key`` z mappingu
  ``LEGACY_TO_SEMANTIC`` albo kwarantanna ``unmapped`` (NIGDY zgadywanie),
- krawędziami = pełny digraf między etapami + krawędzie wejściowe
  (parity z dzisiejszym zachowaniem: legacy move nie waliduje przejść;
  zaostrzanie = świadoma nowa rewizja),
- raportem mappingu (mapped/unmapped per template) — AC planu: „100%
  aktywnych stages albo quarantine".

Idempotentny: templaty z istniejącą definicją są pomijane.

``validate_revision_graph``: walidacje wymagane przed publish —
spójność terminalności, semantic_key z rejestru, osiągalność terminala,
duplikaty orderów, sensowne SLA.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline_template import PipelineStageDef, PipelineTemplate
from app.models.workflow_revision import (
    StageRevision,
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowRevision,
    WorkflowRevisionStatus,
)
from app.services.semantic_states import (
    REGISTRY_VERSION,
    SEMANTIC_STATES,
    semantic_for_legacy,
)


@dataclass
class TemplateMappingReport:
    template_id: int
    template_name: str
    workflow_id: Optional[int] = None
    revision_id: Optional[int] = None
    mapped: int = 0
    unmapped_stage_ids: list[int] = field(default_factory=list)
    skipped_existing: bool = False


@dataclass
class BootstrapReport:
    registry_version: str = REGISTRY_VERSION
    templates: list[TemplateMappingReport] = field(default_factory=list)

    @property
    def total_unmapped(self) -> int:
        return sum(len(t.unmapped_stage_ids) for t in self.templates)

    def as_dict(self) -> dict:
        return {
            "registry_version": self.registry_version,
            "templates_total": len(self.templates),
            "templates_created": sum(
                1 for t in self.templates if not t.skipped_existing
            ),
            "templates_skipped_existing": sum(
                1 for t in self.templates if t.skipped_existing
            ),
            "stages_mapped": sum(t.mapped for t in self.templates),
            "stages_unmapped": self.total_unmapped,
            "details": [
                {
                    "template_id": t.template_id,
                    "template_name": t.template_name,
                    "workflow_id": t.workflow_id,
                    "revision_id": t.revision_id,
                    "mapped": t.mapped,
                    "unmapped_stage_ids": t.unmapped_stage_ids,
                    "skipped_existing": t.skipped_existing,
                }
                for t in self.templates
            ],
        }


async def bootstrap_workflow_revisions(
    db: AsyncSession, *, created_by: Optional[int] = None
) -> BootstrapReport:
    """Utwórz definitions + published rev 1 dla templateów bez definicji.

    Caller commituje. Rerun-safe: istniejące definicje są raportowane jako
    ``skipped_existing`` i nietykane (opublikowana rewizja jest immutable).
    """
    report = BootstrapReport()

    templates = (
        (
            await db.execute(
                select(PipelineTemplate).where(PipelineTemplate.archived.is_(False))
            )
        )
        .scalars()
        .all()
    )
    existing_bridges = set(
        (
            await db.execute(
                select(WorkflowDefinition.template_id).where(
                    WorkflowDefinition.template_id.is_not(None)
                )
            )
        )
        .scalars()
        .all()
    )

    for tpl in templates:
        entry = TemplateMappingReport(template_id=tpl.id, template_name=tpl.name)
        report.templates.append(entry)
        if tpl.id in existing_bridges:
            entry.skipped_existing = True
            continue

        definition = WorkflowDefinition(
            template_id=tpl.id,
            name=tpl.name,
            description=tpl.description,
            client_id=tpl.client_id,
            created_by=created_by,
        )
        db.add(definition)
        await db.flush()
        revision = WorkflowRevision(
            workflow_id=definition.id,
            revision_no=1,
            status=WorkflowRevisionStatus.published,
            source="bootstrap",
            registry_version=REGISTRY_VERSION,
            published_at=datetime.now(timezone.utc),
            published_by=created_by,
        )
        db.add(revision)
        await db.flush()

        stage_defs = (
            (
                await db.execute(
                    select(PipelineStageDef)
                    .where(PipelineStageDef.template_id == tpl.id)
                    .order_by(PipelineStageDef.order)
                )
            )
            .scalars()
            .all()
        )
        stage_revs: list[StageRevision] = []
        for sd in stage_defs:
            semantic = semantic_for_legacy(sd.legacy_enum_value)
            if semantic is None:
                semantic = "unmapped"
                entry.unmapped_stage_ids.append(sd.id)
            else:
                entry.mapped += 1
            sr = StageRevision(
                workflow_revision_id=revision.id,
                source_stage_def_id=sd.id,
                name=sd.name,
                order=sd.order,
                category=sd.category.value,
                semantic_key=semantic,
                is_terminal=sd.is_terminal,
                terminal_type=(sd.terminal_type.value if sd.terminal_type else None),
                tracker_enabled=sd.tracker_enabled,
                tracker_public_name=sd.tracker_public_name,
                sla_max_days=sd.sla_max_days,
                scorecard_schema=sd.scorecard_schema,
            )
            db.add(sr)
            stage_revs.append(sr)
        await db.flush()

        # Krawędzie: pełny digraf (parity z legacy — brak walidacji przejść)
        # + wejście na każdy NIE-terminalny etap.
        for src in stage_revs:
            if not src.is_terminal:
                db.add(
                    WorkflowEdge(
                        workflow_revision_id=revision.id,
                        from_stage_revision_id=None,
                        to_stage_revision_id=src.id,
                    )
                )
        for src in stage_revs:
            for dst in stage_revs:
                if src.id == dst.id:
                    continue
                db.add(
                    WorkflowEdge(
                        workflow_revision_id=revision.id,
                        from_stage_revision_id=src.id,
                        to_stage_revision_id=dst.id,
                    )
                )
        await db.flush()
        entry.workflow_id = definition.id
        entry.revision_id = revision.id

    return report


def validate_revision_graph(
    stages: list[StageRevision], edges: list[WorkflowEdge]
) -> list[str]:
    """Walidacje publish (plan PR-05). Zwraca listę problemów (pusta = OK)."""
    problems: list[str] = []
    if not stages:
        return ["rewizja nie ma żadnych etapów"]

    orders = [s.order for s in stages]
    if len(set(orders)) != len(orders):
        problems.append("zduplikowane wartości order")
    names = [s.name for s in stages]
    if len(set(names)) != len(names):
        problems.append("zduplikowane nazwy etapów")

    for s in stages:
        if s.semantic_key not in SEMANTIC_STATES:
            problems.append(f"nieznany semantic_key {s.semantic_key!r} ({s.name})")
        if s.is_terminal and not s.terminal_type:
            problems.append(f"terminal bez terminal_type: {s.name}")
        if not s.is_terminal and s.terminal_type:
            problems.append(f"terminal_type na nieterminalnym etapie: {s.name}")
        if s.sla_max_days is not None and s.sla_max_days < 1:
            problems.append(f"sla_max_days < 1 na etapie {s.name}")
        if s.semantic_key == "unmapped":
            problems.append(
                f"etap {s.name!r} w kwarantannie 'unmapped' — przypisz "
                "semantic_key przed publikacją"
            )

    terminal_ids = {s.id for s in stages if s.is_terminal}
    if not terminal_ids:
        problems.append("brak jakiegokolwiek etapu terminalnego")
    else:
        # Osiągalność: każdy nieterminalny etap ma ścieżkę do terminala.
        adjacency: dict[int, set[int]] = {}
        for e in edges:
            if e.from_stage_revision_id is None:
                continue
            adjacency.setdefault(e.from_stage_revision_id, set()).add(
                e.to_stage_revision_id
            )
        for s in stages:
            if s.is_terminal:
                continue
            seen: set[int] = set()
            frontier = [s.id]
            reachable = False
            while frontier:
                cur = frontier.pop()
                if cur in terminal_ids:
                    reachable = True
                    break
                for nxt in adjacency.get(cur, ()):  # noqa: B007
                    if nxt not in seen:
                        seen.add(nxt)
                        frontier.append(nxt)
            if not reachable:
                problems.append(f"etap {s.name!r} nie ma ścieżki do żadnego terminala")

    entry_edges = [e for e in edges if e.from_stage_revision_id is None]
    if not entry_edges:
        problems.append("brak krawędzi wejściowej (entry edge)")

    return problems
