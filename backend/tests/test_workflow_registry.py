"""Testy wersjonowanych workflow (M4 plan PR-05).

Kontrakty:

- bootstrap: mapping legacy→semantic albo kwarantanna `unmapped` (nigdy
  zgadywanie); rerun-safe (skip istniejących);
- draft-from-revision: PEŁNA parytetowość kopii (semantic_key, scorecard,
  terminalność, SLA, tracker, krawędzie) — audyt P0.2 o legacy clone;
- published = immutable (PATCH etapu → 409); edycja draftu działa;
- publish: walidacja grafu (unmapped/duplikaty/terminal reachability/SLA),
  atomowa podmiana published (partial unique), archiwizacja poprzedniej;
- rejestr semantyczny: mapping pokrywa KAŻDĄ wartość legacy PipelineStage.

Uses in-process fixtures (real postgres in CI) — migracja 0177 przez
`alembic upgrade heads`.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.models.recruitment_pipeline import PipelineStage
from app.services.semantic_states import (
    LEGACY_TO_SEMANTIC,
    SEMANTIC_STATES,
    semantic_for_legacy,
)

BASE = "/api/admin/workflows"


def test_registry_covers_every_legacy_stage():
    for stage in PipelineStage:
        key = semantic_for_legacy(stage.value)
        assert key is not None, f"brak mappingu dla legacy {stage.value}"
        assert key in SEMANTIC_STATES
    # terminal parity: hired/rejected/withdrawn mapują na terminale rejestru
    for legacy in ("hired", "rejected", "withdrawn"):
        state = SEMANTIC_STATES[LEGACY_TO_SEMANTIC[legacy]]
        assert state.is_terminal, f"{legacy} → {state.key} nie jest terminalem"


async def _seed_template(with_unmapped_custom: bool = False) -> int:
    from app.models.pipeline_template import (
        PipelineStageDef,
        PipelineTemplate,
        StageCategoryEnum,
        TerminalType,
    )

    async with AsyncSessionLocal() as db:
        tpl = PipelineTemplate(name=f"Wf-Tpl-{uuid.uuid4().hex[:6]}")
        db.add(tpl)
        await db.flush()
        db.add_all(
            [
                PipelineStageDef(
                    template_id=tpl.id,
                    name="Nowi",
                    order=1,
                    category=StageCategoryEnum.internal,
                    legacy_enum_value="new",
                ),
                PipelineStageDef(
                    template_id=tpl.id,
                    name="Screening",
                    order=2,
                    category=StageCategoryEnum.internal,
                    legacy_enum_value="screening",
                ),
                PipelineStageDef(
                    template_id=tpl.id,
                    name="Zatrudniony",
                    order=3,
                    category=StageCategoryEnum.terminal,
                    is_terminal=True,
                    terminal_type=TerminalType.hired,
                    legacy_enum_value="hired",
                ),
            ]
        )
        if with_unmapped_custom:
            db.add(
                PipelineStageDef(
                    template_id=tpl.id,
                    name="Custom bez legacy",
                    order=4,
                    category=StageCategoryEnum.internal,
                )
            )
        await db.commit()
        return tpl.id


async def test_bootstrap_maps_and_quarantines(
    app_client: AsyncClient, app_auth_headers
):
    tpl_mapped = await _seed_template()
    tpl_custom = await _seed_template(with_unmapped_custom=True)

    r = await app_client.post(f"{BASE}/bootstrap", headers=app_auth_headers)
    assert r.status_code == 200, r.text
    report = r.json()
    by_tpl = {d["template_id"]: d for d in report["details"]}

    assert by_tpl[tpl_mapped]["mapped"] == 3
    assert by_tpl[tpl_mapped]["unmapped_stage_ids"] == []
    assert by_tpl[tpl_custom]["mapped"] == 3
    assert len(by_tpl[tpl_custom]["unmapped_stage_ids"]) == 1

    # Rerun-safe: drugi bootstrap pomija istniejące definicje.
    r2 = await app_client.post(f"{BASE}/bootstrap", headers=app_auth_headers)
    by_tpl2 = {d["template_id"]: d for d in r2.json()["details"]}
    assert by_tpl2[tpl_mapped]["skipped_existing"] is True

    # Lista pokazuje kwarantannę.
    lst = await app_client.get(BASE, headers=app_auth_headers)
    assert lst.status_code == 200
    row = next(w for w in lst.json() if w["template_id"] == tpl_custom)
    published = [x for x in row["revisions"] if x["status"] == "published"]
    assert published and published[0]["unmapped_stages"] == 1


async def test_draft_full_parity_and_published_immutability(
    app_client: AsyncClient, app_auth_headers
):
    from sqlalchemy import select

    from app.models.pipeline_template import PipelineStageDef
    from app.models.workflow_revision import StageRevision

    tpl = await _seed_template()
    # nadaj scorecard schema legacy stage'owi (parity check)
    async with AsyncSessionLocal() as db:
        sd = await db.scalar(
            select(PipelineStageDef).where(
                PipelineStageDef.template_id == tpl,
                PipelineStageDef.name == "Screening",
            )
        )
        sd.scorecard_schema = {"title": "Tech", "questions": [{"id": "q1"}]}
        await db.commit()

    r = await app_client.post(f"{BASE}/bootstrap", headers=app_auth_headers)
    rev_id = next(
        d["revision_id"] for d in r.json()["details"] if d["template_id"] == tpl
    )

    # published → PATCH etapu = 409 (immutability)
    async with AsyncSessionLocal() as db:
        any_stage = await db.scalar(
            select(StageRevision).where(StageRevision.workflow_revision_id == rev_id)
        )
    patch = await app_client.patch(
        f"{BASE}/stage-revisions/{any_stage.id}",
        json={"name": "Hack"},
        headers=app_auth_headers,
    )
    assert patch.status_code == 409, patch.text

    # draft-from-revision: pełna kopia
    d = await app_client.post(
        f"{BASE}/revisions/{rev_id}/draft", headers=app_auth_headers
    )
    assert d.status_code == 200, d.text
    draft_id = d.json()["draft_revision_id"]

    async with AsyncSessionLocal() as db:
        src_stages = (
            (
                await db.execute(
                    select(StageRevision)
                    .where(StageRevision.workflow_revision_id == rev_id)
                    .order_by(StageRevision.order)
                )
            )
            .scalars()
            .all()
        )
        dst_stages = (
            (
                await db.execute(
                    select(StageRevision)
                    .where(StageRevision.workflow_revision_id == draft_id)
                    .order_by(StageRevision.order)
                )
            )
            .scalars()
            .all()
        )
    assert len(src_stages) == len(dst_stages)
    for s, t in zip(src_stages, dst_stages):
        assert (s.name, s.order, s.semantic_key, s.is_terminal, s.terminal_type) == (
            t.name,
            t.order,
            t.semantic_key,
            t.is_terminal,
            t.terminal_type,
        )
        assert s.scorecard_schema == t.scorecard_schema
        assert s.source_stage_def_id == t.source_stage_def_id

    # edycja draftu działa (np. przypisanie semantic_key)
    editable = dst_stages[0]
    ok = await app_client.patch(
        f"{BASE}/stage-revisions/{editable.id}",
        json={"name": "Nowi (v2)"},
        headers=app_auth_headers,
    )
    assert ok.status_code == 200, ok.text


async def test_publish_validates_and_swaps_atomically(
    app_client: AsyncClient, app_auth_headers
):
    from sqlalchemy import select

    from app.models.workflow_revision import (
        StageRevision,
        WorkflowRevision,
        WorkflowRevisionStatus,
    )

    tpl = await _seed_template(with_unmapped_custom=True)
    r = await app_client.post(f"{BASE}/bootstrap", headers=app_auth_headers)
    detail = next(d for d in r.json()["details"] if d["template_id"] == tpl)
    rev_id = detail["revision_id"]

    d = await app_client.post(
        f"{BASE}/revisions/{rev_id}/draft", headers=app_auth_headers
    )
    draft_id = d.json()["draft_revision_id"]

    # publish draftu z kwarantanną `unmapped` → 422 z listą problemów
    pub = await app_client.post(
        f"{BASE}/revisions/{draft_id}/publish", headers=app_auth_headers
    )
    assert pub.status_code == 422, pub.text
    assert any("unmapped" in p for p in pub.json()["detail"]["problems"])

    # przypisz semantic_key kwarantannie → publish przechodzi
    async with AsyncSessionLocal() as db:
        quarantined = await db.scalar(
            select(StageRevision).where(
                StageRevision.workflow_revision_id == draft_id,
                StageRevision.semantic_key == "unmapped",
            )
        )
    fix = await app_client.patch(
        f"{BASE}/stage-revisions/{quarantined.id}",
        json={"semantic_key": "internal_review"},
        headers=app_auth_headers,
    )
    assert fix.status_code == 200, fix.text

    pub2 = await app_client.post(
        f"{BASE}/revisions/{draft_id}/publish", headers=app_auth_headers
    )
    assert pub2.status_code == 200, pub2.text
    assert pub2.json()["archived_revision_id"] == rev_id

    # Niezmiennik: dokładnie jedna published per workflow
    async with AsyncSessionLocal() as db:
        wf_id = await db.scalar(
            select(WorkflowRevision.workflow_id).where(WorkflowRevision.id == draft_id)
        )
        published = (
            (
                await db.execute(
                    select(WorkflowRevision).where(
                        WorkflowRevision.workflow_id == wf_id,
                        WorkflowRevision.status == WorkflowRevisionStatus.published,
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(published) == 1 and published[0].id == draft_id


async def test_bootstrap_requires_admin(app_client: AsyncClient):
    r = await app_client.post(f"{BASE}/bootstrap")
    assert r.status_code in (401, 403)


def test_graph_validator_catches_problems():
    from types import SimpleNamespace

    from app.services.workflow_registry_service import validate_revision_graph

    def stage(i, name, terminal=False, ttype=None, key="identified", sla=None):
        return SimpleNamespace(
            id=i,
            name=name,
            order=i,
            semantic_key=key,
            is_terminal=terminal,
            terminal_type=ttype,
            sla_max_days=sla,
        )

    def edge(f, t):
        return SimpleNamespace(from_stage_revision_id=f, to_stage_revision_id=t)

    # OK: A → B(terminal), entry → A
    ok = validate_revision_graph(
        [stage(1, "A"), stage(2, "B", terminal=True, ttype="hired", key="hired")],
        [edge(None, 1), edge(1, 2)],
    )
    assert ok == [], ok

    # Nieosiągalny terminal + terminal bez typu + SLA 0
    bad = validate_revision_graph(
        [
            stage(1, "A", sla=0),
            stage(2, "B", terminal=True, key="hired"),
        ],
        [edge(None, 1)],
    )
    joined = " | ".join(bad)
    assert "terminal bez terminal_type" in joined
    assert "sla_max_days" in joined
    assert "nie ma ścieżki" in joined


async def test_revision_detail_exposes_stage_ids(
    app_client: AsyncClient, app_auth_headers
):
    """GET detali rewizji — operacyjny warunek użycia PATCH stage-revisions."""
    tpl = await _seed_template()
    r = await app_client.post(f"{BASE}/bootstrap", headers=app_auth_headers)
    rev_id = next(
        d["revision_id"] for d in r.json()["details"] if d["template_id"] == tpl
    )
    detail = await app_client.get(
        f"{BASE}/revisions/{rev_id}", headers=app_auth_headers
    )
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["status"] == "published"
    assert len(body["stages"]) == 3
    assert all("id" in s and "semantic_key" in s for s in body["stages"])
    assert body["edges_count"] > 0
