"""Droga rekrutera do Delivery Leada (14.10.2026): rekruter nie czeka w ciemno
na CV firmowe.

Kontrakty:

- szkic automatu auto-CV = QC + poprawki AI z góry + dzwonek ``cv_ready``
  („CV gotowe do sprawdzenia”) do osoby, która przesunęła kartę; ręczna
  generacja i wybór CV z innych źródeł dostają QC (i poprawki), bez dzwonka;
- pominięcie albo awaria, przy których rekruter musi zrobić CV sam = dzwonek
  „Automat nie zrobił CV” z polskim powodem; ``pair_cv_exists`` = QC
  istniejącego CV, bez dzwonka;
- QC, które po wejściu do „QC CV” nie przeszło = zadanie „QC CV do poprawy”
  dla rekrutera kandydata, mailem jak zwrot do poprawy;
- karta Tablicy niesie ``auto_cv_state``, ``company_cv`` i ``qc.warnings_count``.

Dane fikcyjne. Testy z bazą biegną w CI.
"""

# ruff: noqa: F811  (fixture `pv_client` importowana z sąsiedniego pliku)
from __future__ import annotations

import ast
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.cv_qc_run import CvQcRun
from app.models.job import Job
from app.models.notification import Notification, NotificationType
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.services import cv_auto_generate as auto
from app.services import cv_qc
from app.services import notification_delivery as delivery
from app.services.notification_access import NOTIFICATION_SECTION_BY_TYPE
from app.services.notification_categories import (
    CATEGORY_INFO,
    NotificationCategory,
    category_for,
)
from app.services.section_permissions import ProductSection
from app.services.stage_handoff_recipients import (
    RETURNED_TITLE_PREFIXES,
    TITLE_QC_FAILED,
)
from app.tasks import notification_email_outbox as outbox
from tests.test_cv_auto_generate import (
    _auto_doc,
    _fake_attach,
    _fake_generator,
    _headers,
    _stage_cv,
    _world,
)
from tests.test_pending_gate_removed import pv_client  # noqa: F401

_REPO = Path(__file__).resolve().parents[2]
_BACKEND = _REPO / "backend"


# ── Jednostkowe ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("blocking", "warnings", "text"),
    [
        (0, 0, "QC bez uwag"),
        (0, 1, "QC: 1 uwaga"),
        (1, 2, "QC: 3 uwagi (1 blokuje)"),
        (2, 3, "QC: 5 uwag (2 blokuje)"),
        (0, 12, "QC: 12 uwag"),
        (0, 22, "QC: 22 uwagi"),
    ],
)
def test_findings_text_counts_everything_to_fix(blocking, warnings, text):
    assert cv_qc.findings_text(blocking, warnings) == text


def test_not_done_reasons_mirror_the_background_feed_labels():
    """Lustro `SKIP_REASON_PL` z `job-background-events.ts` — dzwonek i „Praca
    w tle” mówią to samo."""
    source = (
        _REPO / "frontend" / "src" / "lib" / "job-background-events.ts"
    ).read_text("utf-8")
    block = source[source.index("const SKIP_REASON_PL") :]
    block = block[: block.index("};")]
    labels = dict(re.findall(r'(\w+):\s*\n?\s*"([^"]+)"', block))
    for reason, label in auto.NOT_DONE_REASONS.items():
        if reason == "generation_failed":
            continue  # awaria nie jest pominięciem — feed ma własny komunikat
        assert labels.get(reason) == label, reason
    # Bez dzwonka: CV jest albo osoba i tak nie może generować.
    for silent in ("pair_cv_exists", "already_generated", "no_permission"):
        assert silent not in auto.NOT_DONE_REASONS


def test_not_done_reason_adds_the_generator_detail_only_for_client_rules():
    assert auto.not_done_reason(
        "client_rule_inputs_missing", "Reguła klienta wymaga numeru projektu."
    ) == (
        "reguła klienta wymaga danych, których automat nie ma "
        "(Reguła klienta wymaga numeru projektu)"
    )
    assert auto.not_done_reason("no_client", "coś") == (
        "rekrutacja nie ma przypisanego klienta"
    )
    # Awaria spoza listy (klasa wyjątku) = CV nie powstało.
    assert auto.not_done_reason("RuntimeError") == "generacja CV zakończyła się błędem"


def test_cv_ready_is_a_mutable_pipeline_bell():
    assert category_for(NotificationType.cv_ready) == NotificationCategory.pipeline
    assert category_for(NotificationType.stage_rule) == NotificationCategory.pipeline
    assert not CATEGORY_INFO[NotificationCategory.pipeline].mandatory
    assert NOTIFICATION_SECTION_BY_TYPE[NotificationType.cv_ready] == (
        ProductSection.pipeline
    )
    # Bez maila — dzwonek wystarcza.
    assert delivery.notification_kind(NotificationType.cv_ready) is None


def test_failed_qc_bell_is_mailed_like_a_return_not_like_a_review():
    title = f"{TITLE_QC_FAILED} Anna Testowa"
    assert title.startswith(RETURNED_TITLE_PREFIXES)
    assert (
        delivery.immediate_email_kind(
            NotificationType.board_task_waiting,
            title=title,
            related_entity_type="candidate_stage",
        )
        == "cv_returned"
    )
    returned = str(
        outbox.kind_clause("cv_returned").compile(dialect=postgresql.dialect())
    )
    review = str(outbox.kind_clause("dl_review").compile(dialect=postgresql.dialect()))
    # Kolejka maili czyta te same stałe co `immediate_email_kind`.
    assert returned.count("LIKE") == len(RETURNED_TITLE_PREFIXES)
    assert "NOT" in review


def test_every_stage_cv_source_schedules_qc_after_the_response():
    tree = ast.parse(
        (_BACKEND / "app" / "api" / "candidate_stage_cv.py").read_text("utf-8")
    )
    routes = {
        node.name: ast.unparse(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name
        in (
            "select_generated_cv",
            "select_document_cv",
            "upload_stage_cv",
            "select_stage_cv",
        )
    }
    assert len(routes) == 4
    for name, source in routes.items():
        assert (
            "_schedule_qc_after_attach(background_tasks, stage_id, current_user.id)"
            in source
        ), name


def test_only_the_qc_cv_entry_rings_the_recruiter():
    source = (_BACKEND / "app" / "api" / "pipeline.py").read_text("utf-8")
    assert source.count("notify_recruiter_on_fail=True") == 1
    attach = (_BACKEND / "app" / "services" / "cv_auto_generate.py").read_text("utf-8")
    assert "notify_recruiter_on_fail" not in attach


async def test_qc_after_attach_without_qc_rings_only_when_asked(monkeypatch):
    rung: list[tuple] = []

    async def _bell_ready(stage_id, user_id, result):
        rung.append((stage_id, user_id, result))

    monkeypatch.setattr(auto, "_bell_ready", _bell_ready)
    monkeypatch.setattr(settings, "CV_QC_GATE_ENABLED", False)
    await auto.qc_after_attach(5, 6)
    await auto.qc_after_attach(7, 8, notify_ready=True)
    assert rung == [(7, 8, None)]


async def test_fixes_are_not_prefetched_without_findings_or_for_a_file_cv(
    monkeypatch,
):
    called: list = []

    async def generate_fixes(db, stage, *, user_id):
        called.append(stage.id)

    monkeypatch.setattr(cv_qc, "generate_fixes", generate_fixes)
    clean = {"blocking_failed": 0, "warnings_count": 0, "cv": {"editable": True}}
    await auto._prefetch_fixes(1, 2, clean)
    from_file = {"blocking_failed": 2, "warnings_count": 0, "cv": {"editable": False}}
    await auto._prefetch_fixes(1, 2, from_file)
    assert called == []


# ── Z bazą: szkic automatu i dzwonek ─────────────────────────────────────────


async def _bells(user_id: int, ntype: NotificationType) -> list[Notification]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(Notification)
                    .where(
                        Notification.user_id == user_id,
                        Notification.notification_type == ntype,
                    )
                    .order_by(Notification.id)
                )
            ).all()
        )


async def _names(world: dict) -> tuple[str, str]:
    async with AsyncSessionLocal() as db:
        candidate = await db.get(Candidate, world["candidate_id"])
        job = await db.get(Job, world["job_id"])
        return f"{candidate.name} {candidate.lastname}", job.title


def _qc_result(world: dict, *, blocking: int, warnings: int, **extra) -> dict:
    return {
        "passed": blocking == 0,
        "override": None,
        "blocking_failed": blocking,
        "warnings_count": warnings,
        "candidate_id": world["candidate_id"],
        "candidate_name": "Anna Testowa",
        "job_id": world["job_id"],
        "job_title": "Java Developer",
        "cv": {"editable": True, "stage_id": world["stage_id"]},
        **extra,
    }


def _fake_qc(monkeypatch, world: dict, **kwargs) -> tuple[list, list]:
    qc_calls: list[int] = []
    fixes: list[tuple[int, int]] = []

    async def run_after_move(stage_id, user_id):
        qc_calls.append(stage_id)
        return _qc_result(world, **kwargs)

    async def generate_fixes(db, stage, *, user_id):
        fixes.append((stage.id, user_id))
        return {"status": "ok", "cached": False, "fixes": []}

    monkeypatch.setattr(cv_qc, "run_after_move", run_after_move)
    monkeypatch.setattr(cv_qc, "generate_fixes", generate_fixes)
    monkeypatch.setattr(settings, "CV_QC_GATE_ENABLED", True)
    return qc_calls, fixes


async def test_automaton_draft_rings_cv_ready_with_the_qc_result(monkeypatch):
    world = await _world()
    await _stage_cv(world)
    doc_id = await _auto_doc(world)
    _fake_attach(monkeypatch)
    qc_calls, fixes = _fake_qc(monkeypatch, world, blocking=1, warnings=2)

    assert await auto.attach_as_stage_draft(
        stage_id=world["stage_id"], user_id=world["user_id"], generated_id=doc_id
    )
    assert qc_calls == [world["stage_id"]]
    # Poprawki AI raz, na wierszu, na którym leży CV (klucz edytora).
    assert fixes == [(world["stage_id"], world["user_id"])]
    name, title = await _names(world)
    [bell] = await _bells(world["user_id"], NotificationType.cv_ready)
    assert bell.title == f"CV gotowe do sprawdzenia: {name}"
    assert bell.message == f"{title} · QC: 3 uwagi (1 blokuje)"
    assert bell.link == (
        f"/jobs/{world['job_id']}?candidate={world['candidate_id']}&panel=cv"
    )
    assert (bell.related_entity_type, bell.related_entity_id) == (
        "candidate_stage",
        world["stage_id"],
    )


async def test_automaton_draft_without_qc_still_says_the_cv_is_ready(monkeypatch):
    world = await _world()
    await _stage_cv(world)
    doc_id = await _auto_doc(world)
    _fake_attach(monkeypatch)
    monkeypatch.setattr(settings, "CV_QC_GATE_ENABLED", False)
    assert await auto.attach_as_stage_draft(
        stage_id=world["stage_id"], user_id=world["user_id"], generated_id=doc_id
    )
    _, title = await _names(world)
    [bell] = await _bells(world["user_id"], NotificationType.cv_ready)
    assert bell.message == title


async def test_manual_generation_gets_qc_and_fixes_but_no_bell(monkeypatch):
    world = await _world()
    await _stage_cv(world)
    doc_id = await _auto_doc(world)
    _fake_attach(monkeypatch)
    qc_calls, fixes = _fake_qc(monkeypatch, world, blocking=0, warnings=1)
    assert await auto.attach_as_stage_draft(
        stage_id=world["stage_id"],
        user_id=world["user_id"],
        generated_id=doc_id,
        activity_action="branded_cv_attached_after_generation",
    )
    assert qc_calls == [world["stage_id"]]
    assert fixes == [(world["stage_id"], world["user_id"])]
    assert await _bells(world["user_id"], NotificationType.cv_ready) == []


async def test_no_fixes_while_the_card_is_before_verified(monkeypatch):
    """CV wybrane w screeningu dostaje QC, ale poprawki AI dopiero od
    „Zweryfikowanego” — wcześniej rekruter może z tej wersji zrezygnować."""
    world = await _world()
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateStage(
                candidate_id=world["candidate_id"],
                job_id=world["job_id"],
                stage=PipelineStage.screening,
                moved_by=world["user_id"],
                moved_at=datetime.now(timezone.utc) + timedelta(seconds=5),
            )
        )
        await db.commit()
    qc_calls, fixes = _fake_qc(monkeypatch, world, blocking=2, warnings=0)
    await auto.qc_after_attach(world["stage_id"], world["user_id"])
    assert qc_calls == [world["stage_id"]]
    assert fixes == []


# ── Z bazą: pominięcia i awarie ──────────────────────────────────────────────


async def test_skip_the_recruiter_must_act_on_rings_with_the_reason(monkeypatch):
    world = await _world(with_cv=False)
    _fake_generator(monkeypatch)
    async with AsyncSessionLocal() as db:
        assert (
            await auto._enqueue(
                db, stage_id=world["stage_id"], user_id=world["user_id"]
            )
            is None
        )
    name, title = await _names(world)
    [bell] = await _bells(world["user_id"], NotificationType.cv_ready)
    assert bell.title == f"Automat nie zrobił CV: {name}"
    assert bell.message == f"{title} · kandydat nie ma w profilu pliku CV"
    assert bell.related_entity_id == world["stage_id"]


async def test_client_rule_refusal_rings_with_what_is_missing(monkeypatch):
    world = await _world()
    _fake_generator(
        monkeypatch, error=HTTPException(422, "Reguła klienta wymaga numeru projektu.")
    )
    async with AsyncSessionLocal() as db:
        await auto._enqueue(db, stage_id=world["stage_id"], user_id=world["user_id"])
    [bell] = await _bells(world["user_id"], NotificationType.cv_ready)
    assert bell.message.endswith("(Reguła klienta wymaga numeru projektu)")


async def test_existing_pair_cv_gets_qc_without_a_bell(monkeypatch):
    """Para ma już CV firmowe (np. wybrane w screeningu) — automat nie generuje,
    ale QC i poprawki AI liczą się od razu dla wiersza z tym CV."""
    world = await _world(with_cv=False)
    async with AsyncSessionLocal() as db:
        screening = CandidateStage(
            candidate_id=world["candidate_id"],
            job_id=world["job_id"],
            stage=PipelineStage.screening,
            moved_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        db.add(screening)
        await db.flush()
        db.add(
            CandidateStageCV(
                candidate_stage_id=screening.id,
                candidate_id=world["candidate_id"],
                job_id=world["job_id"],
                branded_status="draft",
                branded_draft_html="<p>CV wybrane w screeningu</p>",
            )
        )
        await db.commit()
        pair_stage_id = screening.id
    calls: list[tuple] = []

    async def qc_after_attach(stage_id, user_id, *, notify_ready=False):
        calls.append((stage_id, user_id, notify_ready))

    monkeypatch.setattr(auto, "qc_after_attach", qc_after_attach)
    _fake_generator(monkeypatch)
    async with AsyncSessionLocal() as db:
        assert (
            await auto._enqueue(
                db, stage_id=world["stage_id"], user_id=world["user_id"]
            )
            is None
        )
    # Sprawdzone przed plikiem CV w profilu — bez pliku nie ma „brak pliku CV”.
    assert calls == [(pair_stage_id, world["user_id"], False)]
    assert await _bells(world["user_id"], NotificationType.cv_ready) == []


# ── Z bazą: QC po wejściu do „QC CV” ─────────────────────────────────────────


async def test_failed_qc_after_handoff_rings_the_recruiter_once_a_day(monkeypatch):
    world = await _world()
    outcome = {"passed": False, "override": None}

    async def run_qc(db, stage, *, user_id, persist=True, own_session=False):
        return _qc_result(world, blocking=2, warnings=1, **outcome)

    monkeypatch.setattr(cv_qc, "run_qc", run_qc)

    # Po podpięciu CV (bez flagi) — nic.
    await cv_qc.run_after_move(world["stage_id"], world["user_id"])
    assert await _bells(world["user_id"], NotificationType.board_task_waiting) == []

    for _ in range(2):
        result = await cv_qc.run_after_move(
            world["stage_id"], world["user_id"], notify_recruiter_on_fail=True
        )
        assert result is not None and result["blocking_failed"] == 2
    [bell] = await _bells(world["user_id"], NotificationType.board_task_waiting)
    assert bell.title == f"{TITLE_QC_FAILED} Anna Testowa"
    assert bell.message == "Java Developer · QC: 3 uwagi (2 blokuje)"
    assert bell.link == (
        f"/jobs/{world['job_id']}?candidate={world['candidate_id']}&panel=cv"
    )


@pytest.mark.parametrize(
    "outcome",
    [
        {"passed": True, "override": None},
        {"passed": False, "override": {"reason": "Klient prosił", "at": None}},
    ],
)
async def test_passed_or_overridden_qc_does_not_ring(monkeypatch, outcome):
    world = await _world()

    async def run_qc(db, stage, *, user_id, persist=True, own_session=False):
        return _qc_result(world, blocking=1, warnings=0, **outcome)

    monkeypatch.setattr(cv_qc, "run_qc", run_qc)
    await cv_qc.run_after_move(
        world["stage_id"], world["user_id"], notify_recruiter_on_fail=True
    )
    assert await _bells(world["user_id"], NotificationType.board_task_waiting) == []


# ── Z bazą: karta Tablicy ────────────────────────────────────────────────────


async def test_board_card_says_cv_in_progress_company_cv_and_warnings(
    pv_client: AsyncClient,
):
    world = await _world()
    headers = _headers(world["user_id"])

    async def _card() -> dict:
        board = await pv_client.get(
            f"/api/pipeline/kanban/{world['job_id']}", headers=headers
        )
        assert board.status_code == 200, board.text
        [card] = [
            item
            for column in board.json()["columns"]
            for item in column["items"]
            if item["candidate_id"] == world["candidate_id"]
        ]
        return card

    card = await _card()
    assert card["auto_cv_state"] is None
    assert card["company_cv"] is False
    assert card["qc"]["warnings_count"] == 0

    await _auto_doc(world, status="processing")
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateStageCV(
                candidate_stage_id=world["stage_id"],
                candidate_id=world["candidate_id"],
                job_id=world["job_id"],
                branded_status="draft",
                branded_draft_html="<p>CV firmowe</p>",
            )
        )
        db.add(
            CvQcRun(
                candidate_id=world["candidate_id"],
                job_id=world["job_id"],
                candidate_stage_id=world["stage_id"],
                passed=True,
                blocking_failed=0,
                warnings_count=3,
                result={"checks": []},
            )
        )
        await db.commit()
    card = await _card()
    assert card["auto_cv_state"] == "processing"
    assert card["company_cv"] is True
    assert card["qc"]["status"] == "passed"
    assert card["qc"]["warnings_count"] == 3


@pytest.fixture(autouse=True)
def _generation_without_confirmation(monkeypatch):
    """Ten moduł sprawdza tryb sprzed 21.10.2026 (generacja zaraz po ruchu).

    Domyślnie ruch na „Zweryfikowany” już nie generuje CV — patrz
    `test_cv_confirm_before_generate.py`.
    """
    from app.core.config import settings as _settings

    monkeypatch.setattr(_settings, "CV_AUTO_GENERATE_WITHOUT_CONFIRMATION", True)
