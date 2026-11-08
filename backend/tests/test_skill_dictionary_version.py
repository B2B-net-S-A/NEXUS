"""Audyt 2 (08.11.2026), bez bazy: W4 nocny bieg unieważnia tylko zmienione hasła,
W5 wersja słownika, W7 odczyt requestu poza pętlą zdarzeń."""

from __future__ import annotations

import ast
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.skill_relation import SkillRelation
from app.services import job_request_intake, skill_relations, skill_taxonomy_loader
from app.services.skill_relations import AUTO_CURATOR, Pair

MAIN = Path(__file__).resolve().parents[1] / "app" / "main.py"


# ── W4 ──────────────────────────────────────────────────────────────────────


def _accepted(from_id: int, to_id: int) -> SkillRelation:
    return SkillRelation(
        from_skill_id=from_id,
        to_skill_id=to_id,
        kind="implies",
        status="accepted",
        curated_by=AUTO_CURATOR,
    )


def _night(
    monkeypatch: pytest.MonkeyPatch,
    *,
    pairs: list[Pair],
    existing: list[SkillRelation],
    kind: str = "typical",
) -> AsyncMock:
    """Nocny bieg z modelem: każda świeża para dostaje ``kind``."""

    async def many(*_a: object, **_k: object) -> list:
        return []

    async def kinds(_db: object, fresh: list[Pair], _d: object) -> dict:
        return {index: (kind, "powód") for index in range(len(fresh))}

    async def rows(_db: object) -> dict:
        return {(r.from_skill_id, r.to_skill_id, r.kind): r for r in existing}

    changed = AsyncMock(return_value=3)
    monkeypatch.setattr(skill_relations, "load_dictionary", AsyncMock())
    monkeypatch.setattr(skill_relations, "mine_pairs", many)
    monkeypatch.setattr(skill_relations, "glossary_pairs", lambda *_: [])
    monkeypatch.setattr(skill_relations, "load_glossary", lambda: {})
    monkeypatch.setattr(skill_relations, "merge_pairs", lambda *_: pairs)
    monkeypatch.setattr(skill_relations, "_existing", rows)
    monkeypatch.setattr(skill_relations, "model_for", lambda _f: "model-testowy")
    monkeypatch.setattr(skill_relations, "classify_pairs", kinds)
    monkeypatch.setattr(skill_relations, "find_alternatives", many)
    monkeypatch.setattr(skill_relations, "apply_guards", lambda _p, k, _d: k)
    monkeypatch.setattr(
        skill_relations.skill_curation, "after_dictionary_change", changed
    )
    return changed


def _db() -> MagicMock:
    db = MagicMock()
    db.commit = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_night_invalidates_only_skills_changed_tonight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    changed = _night(
        monkeypatch,
        pairs=[Pair(from_id=3, to_id=4)],
        existing=[_accepted(1, 2)],
    )
    summary = await skill_relations.run(_db())
    changed.assert_awaited_once()
    assert changed.await_args.args[1] == {4}
    assert summary["touched_skills"] == 1
    assert summary["invalidated_jobs"] == 3


@pytest.mark.asyncio
async def test_night_without_changes_invalidates_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    changed = _night(monkeypatch, pairs=[], existing=[_accepted(1, 2)])
    summary = await skill_relations.run(_db())
    changed.assert_not_awaited()
    assert summary["accepted"] == 0
    assert summary["invalidated_jobs"] == 0


@pytest.mark.asyncio
async def test_pair_already_accepted_does_not_count_as_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Para zatwierdzona wcześniej nie jest świeża, a inny rodzaj jej nie dotyka."""
    changed = _night(
        monkeypatch,
        pairs=[Pair(from_id=1, to_id=2)],
        existing=[_accepted(1, 2)],
    )
    await skill_relations.run(_db())
    changed.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_without_model_never_invalidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    changed = _night(monkeypatch, pairs=[Pair(from_id=3, to_id=4)], existing=[])
    summary = await skill_relations.run(_db(), use_model=False)
    changed.assert_not_awaited()
    assert summary["touched_skills"] == 0


# ── W5 ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def loader(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    refresh = AsyncMock(return_value=7)
    stored = AsyncMock(return_value="v1")
    monkeypatch.setattr(skill_taxonomy_loader, "refresh_alias_map", refresh)
    monkeypatch.setattr(skill_taxonomy_loader, "_stored_dictionary_version", stored)
    monkeypatch.setattr(skill_taxonomy_loader, "_loaded_version", None)
    return SimpleNamespace(refresh=refresh, stored=stored)


@pytest.mark.asyncio
async def test_sync_loads_on_start_and_then_only_on_change(
    loader: SimpleNamespace,
) -> None:
    assert await skill_taxonomy_loader.sync_dictionary_version() == 7
    assert await skill_taxonomy_loader.sync_dictionary_version() is None
    assert loader.refresh.await_count == 1
    loader.stored.return_value = "v2"
    assert await skill_taxonomy_loader.sync_dictionary_version() == 7
    assert loader.refresh.await_count == 2


@pytest.mark.asyncio
async def test_failed_reload_is_retried_on_next_check(
    loader: SimpleNamespace,
) -> None:
    loader.refresh.side_effect = [RuntimeError("baza"), 7]
    with pytest.raises(RuntimeError):
        await skill_taxonomy_loader.sync_dictionary_version()
    assert await skill_taxonomy_loader.sync_dictionary_version() == 7


@pytest.mark.asyncio
async def test_version_is_read_before_the_reload(loader: SimpleNamespace) -> None:
    """Zmiana w trakcie przeładowania daje jeszcze jedno przeładowanie."""

    async def change_during_reload() -> int:
        loader.stored.return_value = "v2"
        return 7

    loader.refresh.side_effect = change_during_reload
    await skill_taxonomy_loader.sync_dictionary_version()
    assert skill_taxonomy_loader._loaded_version == "v1"
    assert await skill_taxonomy_loader.sync_dictionary_version() == 7


def _functions_calling(name: str) -> list[str]:
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    return [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(
            isinstance(call, ast.Call) and ast.unparse(call.func) == name
            for call in ast.walk(node)
        )
    ]


def test_sync_loop_runs_outside_the_leader_gate() -> None:
    """Proces bez blokady lidera też musi widzieć nowy słownik."""
    assert "lifespan" in _functions_calling("skill_dictionary_sync_loop")
    assert "_start_background_tasks" not in _functions_calling(
        "skill_dictionary_sync_loop"
    )


def test_dictionary_version_stays_out_of_fingerprint_and_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Decyzja Artura z 08.11.2026: wersja jest stemplem. W odcisku dawałaby co
    rano 409 w oknie propozycji, bo słownik zmienia się prawie co noc."""
    from app.services.auto_full_review import _REVIEW_VERSION_KEYS
    from app.services.request_matching_context import build_request_context
    from app.services.scoring_service import DEFAULT_PROFILE
    from tests.test_scoring_service import make_job

    job = make_job(must_skills=["Python"])
    monkeypatch.setattr(skill_taxonomy_loader, "_loaded_version", "v1")
    before = build_request_context(job, DEFAULT_PROFILE).fingerprint
    monkeypatch.setattr(skill_taxonomy_loader, "_loaded_version", "v2")
    assert build_request_context(job, DEFAULT_PROFILE).fingerprint == before
    assert "skill_dictionary" not in _REVIEW_VERSION_KEYS


# ── W7 ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_with_proposals_runs_off_the_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import champion_client_context, champion_draft_service

    seen: dict[str, object] = {}

    def fake_with_proposals(intake: object, text: str) -> object:
        seen["thread"] = threading.current_thread()
        seen["text"] = text
        return intake

    async def same_intake(_db: object, intake: object) -> object:
        return intake

    async def matched(_db: object, *, client_id: int, intake: object) -> object:
        return intake

    context = AsyncMock(return_value=None)
    monkeypatch.setattr(champion_client_context, "load_client_context", context)
    monkeypatch.setattr(champion_client_context, "render_client_context", lambda _c: "")
    monkeypatch.setattr(
        champion_draft_service, "_call_claude_json", AsyncMock(return_value={})
    )
    monkeypatch.setattr(job_request_intake, "normalize_model_output", lambda *_: "x")
    monkeypatch.setattr(job_request_intake, "refine_rows", lambda intake, _t: intake)
    monkeypatch.setattr(job_request_intake, "apply_people_reach", same_intake)
    monkeypatch.setattr(job_request_intake, "match_hiring_manager", matched)
    monkeypatch.setattr(job_request_intake, "with_proposals", fake_with_proposals)

    db = MagicMock()
    db.scalar = AsyncMock(return_value=None)
    db.begin_nested = MagicMock(
        return_value=MagicMock(__aenter__=AsyncMock(), __aexit__=AsyncMock())
    )
    result = await job_request_intake.read_request(
        db, client_id=1, request_text="treść maila"
    )

    assert result == "x"
    assert seen["text"] == "treść maila"
    assert seen["thread"] is not threading.current_thread()
