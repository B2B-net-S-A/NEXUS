"""Przegląd bazy bez regexa w Postgresie (08.11.2026): te same notatki, ta sama
decyzja bramki. Wynik bramki sprawdza też porównanie starego i nowego kodu na
kopii produkcji (opis PR-a)."""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.services import candidate_search_worker as worker
from app.services import must_text_evidence as mte
from app.services.full_candidate_scan import CandidateSnapshot
from app.services.full_search_measurement import VectorMeasurement
from app.services.request_matching_context import build_request_context
from app.services.scoring_service import DEFAULT_PROFILE
from tests.test_scoring_service import make_candidate, make_job


class _NotesDb:
    def __init__(self, rows):
        self.rows = rows
        self.statements = 0

    @asynccontextmanager
    async def _nested(self):
        yield

    def begin_nested(self):
        return self._nested()

    async def execute(self, statement, params):
        self.statements += 1
        # Regex w zapytaniu o notatki był kosztem, który ta zmiana usuwa.
        assert "~*" not in str(statement)
        return self.rows


def _person(cid=1):
    return SimpleNamespace(id=cid, raw_cv_text="", skills=None, verified_tech=None)


@pytest.mark.asyncio
async def test_notes_are_filtered_in_python_case_insensitively_with_one_query():
    db = _NotesDb(
        [
            (1, "Pracował z KAFKĄ w projekcie", None),
            (1, "Nic o technologii", None),
            (2, None, None),
            (3, "Zarządzanie PŁATNOŚCIAMI", None),
        ]
    )
    has_notes, texts = await mte._load_notes(
        db, [1, 2, 3], None, forms=["kafk", "płatnoś"]
    )
    assert db.statements == 1
    # Notatka bez słowa i pusta dalej mówią „ma notatki” (bramka `no_data`).
    assert has_notes == {1, 2, 3}
    assert texts == {
        1: ["Pracował z KAFKĄ w projekcie"],
        3: ["Zarządzanie PŁATNOŚCIAMI"],
    }


@pytest.mark.asyncio
async def test_no_forms_loads_only_the_has_notes_fact():
    has_notes, texts = await mte._load_notes(
        _NotesDb([(1, "Java", None)]), [1], None, forms=()
    )
    assert has_notes == {1}
    assert texts == {}


@pytest.mark.asyncio
async def test_gate_only_evidence_keeps_the_note_selection_of_all_labels():
    """Wstępny filtr ma dziury: „spring boot” nie łapie „Spring-Boot”, wzorzec
    już tak. Węższy zbiór notatek zmieniłby, kogo bramka ukrywa."""
    note = [(1, "Projekt na Spring-Boot", None)]
    both = ("spring boot", "spring")

    alone = _person()
    await mte.attach_gate_evidence(_NotesDb(note), [alone], ("spring boot",))
    assert alone._must_text_evidence.met == frozenset()

    narrowed = _person()
    await mte.attach_gate_evidence(
        _NotesDb(note), [narrowed], both, only=("spring boot",)
    )
    evidence = narrowed._must_text_evidence
    assert evidence.key == ("spring boot",)
    assert evidence.met == frozenset({"spring boot"})
    assert evidence.has_notes is True
    # Dowód dla samej bramki nie udaje dowodu dla pełnej listy.
    assert mte.evidence_for(narrowed, both) is None
    assert mte.evidence_for(narrowed, ("spring boot",)) is evidence


def test_token_screen_matches_checking_every_source_separately():
    candidate = _person()
    candidate.raw_cv_text = "Doświadczenie: Dockerem, Node.js oraz bazy NoSQL"
    labels = ("docker", "node.js", "kafka", "sql")
    from app.services.must_gate_terms import requirement_with_options

    expected = {
        label
        for label in labels
        if (requirement := requirement_with_options(label))
        and mte._mentions_lowered(
            requirement, candidate.raw_cv_text, candidate.raw_cv_text.lower()
        )
    }
    assert mte.text_met_labels(candidate, labels) == frozenset(expected)
    assert "docker" in expected and "kafka" not in expected


def _batch_fixture(monkeypatch, *, seen, attach):
    from app.api import matching

    candidate = make_candidate(skills=["Python"], expected_rate_currency="PLN")
    candidate.updated_at = datetime.now(timezone.utc)

    async def load(_db, _batch):
        return {candidate.id: candidate}

    async def gate(_db, **kwargs):
        seen.update(kwargs)
        return [candidate], {}, {}, 0, kwargs["inputs"]

    async def measurements(_vector, _candidates):
        return {candidate.id: VectorMeasurement(None, "missing_index")}

    monkeypatch.setattr(worker, "load_snapshot_batch", load)
    monkeypatch.setattr(matching, "_gate_and_dealbreakers", gate)
    monkeypatch.setattr(worker, "measure_candidates", measurements)
    monkeypatch.setattr(mte, "attach_gate_evidence", attach)
    context = build_request_context(make_job(must_skills=["Python"]), DEFAULT_PROFILE)
    return candidate, context


@pytest.mark.asyncio
async def test_full_scan_scores_evidence_only_for_people_past_the_gate(monkeypatch):
    seen, attached = {}, []

    async def attach(_db, candidates, labels, *, options=None, job_id=None):
        attached.append(([c.id for c in candidates], labels))

    candidate, context = _batch_fixture(monkeypatch, seen=seen, attach=attach)
    await worker.evaluate_batch(
        None, context, [CandidateSnapshot(candidate.id, "v1")], [1, 0]
    )
    assert seen["evidence_only"] == seen["inputs"].must_skills
    assert seen["candidates_loaded"] is True
    assert attached == [([candidate.id], seen["inputs"].gate_evidence_labels)]


@pytest.mark.asyncio
async def test_board_scoring_of_hidden_people_keeps_full_evidence_at_the_gate(
    monkeypatch,
):
    seen, attached = {}, []

    async def attach(_db, candidates, labels, *, options=None, job_id=None):
        attached.append(labels)

    candidate, context = _batch_fixture(monkeypatch, seen=seen, attach=attach)
    await worker.evaluate_batch(
        None,
        context,
        [CandidateSnapshot(candidate.id, "v1")],
        [1, 0],
        score_excluded=True,
    )
    assert seen["evidence_only"] is None
    assert attached == []
