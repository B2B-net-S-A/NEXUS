"""„Pytania z rozmów”: proponowana odpowiedź pod pytaniem (F55, decyzja Artura 25.11.2026).

Testy bez bazy pilnują kontraktu odczytu odpowiedzi modelu (id spoza partii
odpadają, ``null`` = nagłówek działu, limit długości), partii, źródła
odpowiedzi dla ekranu, rejestru modelu, lustra migracji i decyzji dla
stagingu. Testy z bazą (``app_client``) — zapis bez nadpisywania i pola API.
"""

from __future__ import annotations

import importlib.util
import json
import re
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models.ai_feature import FEATURE_DATA_SENT, FEATURE_LABELS, AIFeatureKey
from app.models.interview_question import InterviewQuestion, InterviewQuestionSource
from app.services import interview_answer_proposals as iap
from app.services.ai_models import choice_for, fallbacks_for, model_for
from app.services.llm_prompts import ALL_TEMPLATES, INTERVIEW_ANSWER_PROPOSAL

BACKEND = Path(__file__).resolve().parents[1]
FEATURE = AIFeatureKey.interview_answer_proposal


def _q(qid: int, client_id: int = 1, role: str | None = None) -> iap.PendingQuestion:
    return iap.PendingQuestion(
        id=qid, text=f"Pytanie {qid}?", client_id=client_id, role=role
    )


# ── Odczyt odpowiedzi modelu ────────────────────────────────────────────────


def test_reply_drops_foreign_ids_and_keeps_null_for_headings() -> None:
    raw = json.dumps(
        [
            {"id": 1, "answer": "  Indeks B-drzewa przyspiesza wyszukiwanie.  "},
            {"id": 2, "answer": None},
            {"id": 99, "answer": "Obce id z innej partii."},
            {"id": "3", "answer": "Id jako tekst też przechodzi."},
        ]
    )
    assert iap.check_reply(raw, [1, 2, 3]) == {
        1: "Indeks B-drzewa przyspiesza wyszukiwanie.",
        2: None,
        3: "Id jako tekst też przechodzi.",
    }


def test_reply_skips_entries_without_a_decision_and_first_entry_wins() -> None:
    raw = (
        "```json\n"
        + json.dumps(
            {
                "answers": [
                    {"id": 1, "answer": "Pierwsza."},
                    {"id": 1, "answer": None},
                    {"id": 2},
                    {"id": 3, "answer": "   "},
                    {"id": 4, "answer": 17},
                    {"id": None, "answer": "x"},
                    "śmieć",
                ]
            }
        )
        + "\n```"
    )
    assert iap.check_reply(raw, [1, 2, 3, 4]) == {1: "Pierwsza."}


def test_reply_without_json_is_an_error_not_an_empty_result() -> None:
    with pytest.raises(ValueError):
        iap.check_reply("Nie umiem odpowiedzieć.", [1])


def test_long_answer_is_cut_at_a_sentence_end() -> None:
    sentence = "To jest zdanie o kolejkach komunikatów. "
    raw = json.dumps([{"id": 1, "answer": sentence * 60}])
    answer = iap.check_reply(raw, [1])[1]
    assert answer is not None
    assert len(answer) <= iap.ANSWER_MAX
    assert answer.endswith("komunikatów.")


def test_long_answer_without_sentence_end_is_hard_cut() -> None:
    answer = iap.clip_answer("a" * 2000)
    assert answer is not None
    assert len(answer) == iap.ANSWER_MAX + 1
    assert answer.endswith("…")


def test_answer_keeps_line_breaks_but_drops_blank_lines() -> None:
    assert iap.clip_answer("Wskazówka:  opowiedz\n\n\n o projekcie.  ") == (
        "Wskazówka: opowiedz\no projekcie."
    )


# ── Partie i prompt ─────────────────────────────────────────────────────────


def test_batches_stay_within_a_client_and_respect_size() -> None:
    pending = [_q(i, client_id=1) for i in range(1, 46)] + [_q(100, client_id=2)]
    batches = iap.make_batches(pending, size=20)
    assert [len(b) for b in batches] == [20, 20, 5, 1]
    for batch in batches:
        assert len({q.client_id for q in batch}) == 1


def test_batch_keeps_one_role_together_in_save_order() -> None:
    """Etykieta działu stoi przed swoimi pytaniami — model widzi je obok siebie."""
    pending = [
        _q(5, role="Java Developer · Java"),
        _q(2, role="Tester · Playwright"),
        _q(3, role=None),
        _q(1, role="Java Developer · Java"),
        _q(4, role="Tester · Playwright"),
    ]
    (batch,) = iap.make_batches(pending)
    assert [q.id for q in batch] == [1, 5, 2, 4, 3]


def test_role_label_is_title_and_top_five_must_haves() -> None:
    skills = [
        {"name": n} for n in ("IBM MQ", "Java", "Java", "Kafka", "SQL", "REST", "Git")
    ]
    assert (
        iap.role_label("  Programista   Integracji ", skills)
        == "Programista Integracji · IBM MQ, Java, Kafka, SQL, REST"
    )
    assert iap.role_label("Tester", []) == "Tester"
    assert iap.role_label(None, ["Python"]) == "Python"
    assert iap.role_label("", None) is None


def test_prompt_sends_question_and_role_only() -> None:
    prompt = iap.build_prompt(
        [
            iap.PendingQuestion(
                id=7, text="Czy zna RLS", client_id=42, role="DBA · PostgreSQL"
            )
        ]
    )
    payload = re.search(r"<pytania>\n(.*)\n</pytania>", prompt, re.S)
    assert payload is not None
    assert json.loads(payload.group(1)) == [
        {"id": 7, "pytanie": "Czy zna RLS", "stanowisko": "DBA · PostgreSQL"}
    ]
    assert "42" not in payload.group(1)


def test_prompt_tells_the_model_bare_topics_are_questions() -> None:
    text = re.sub(r"\s+", " ", INTERVIEW_ANSWER_PROPOSAL.render(questions=""))
    assert "Playwright" in text and "odpowiedz" in text
    assert "answer = null TYLKO" in text
    assert "Wskazówka:" in text
    assert ALL_TEMPLATES["interview_answer_proposal"] is INTERVIEW_ANSWER_PROPOSAL


# ── Źródło odpowiedzi dla ekranu ────────────────────────────────────────────


def _row(source, answer=None, stored=None):
    return SimpleNamespace(
        source=source, ideal_answer=answer, ideal_answer_source=stored
    )


@pytest.mark.parametrize(
    "row,expected",
    [
        (
            _row(InterviewQuestionSource.legacy_import, "Z arkusza", "excel"),
            ("Z arkusza", "excel"),
        ),
        (
            _row(InterviewQuestionSource.client_debrief, "Od modelu", "ai"),
            ("Od modelu", "ai"),
        ),
        (
            _row(InterviewQuestionSource.client_debrief, "Od DL", "manual"),
            ("Od DL", "manual"),
        ),
        # Zapisane przed 0779 (źródło NULL) — jak backfill.
        (_row(InterviewQuestionSource.legacy_import, "Stare"), ("Stare", "excel")),
        (_row(InterviewQuestionSource.client_debrief, "Stare"), ("Stare", "manual")),
        # Nagłówek działu po nocnym biegu.
        (_row(InterviewQuestionSource.client_debrief, None, "none"), (None, "none")),
        # Jeszcze nie przeliczone.
        (_row(InterviewQuestionSource.client_debrief), (None, None)),
        (_row(InterviewQuestionSource.client_debrief, "   "), (None, None)),
    ],
)
def test_bank_answer_source(row, expected) -> None:
    assert iap.bank_answer(row) == expected


def test_human_edit_makes_the_answer_manual_and_clearing_does_not_make_a_heading() -> (
    None
):
    assert iap.source_after_human_edit("Odpowiedź DL-a") == "manual"
    assert iap.source_after_human_edit("  ") is None
    assert iap.source_after_human_edit(None) is None


def test_api_contract_literal_includes_none() -> None:
    from app.api.interview_cycle import QuestionBankItemOut

    item = QuestionBankItemOut(
        id=1,
        text="Java",
        client_id=1,
        source="debrief",
        answer=None,
        answer_source="none",
    )
    assert item.answer_source == "none"
    assert (
        QuestionBankItemOut(id=1, text="x", client_id=1, source="archive").answer
        is None
    )
    with pytest.raises(ValueError):
        QuestionBankItemOut(
            id=1, text="x", client_id=1, source="archive", answer_source="gpt"
        )


# ── Rejestr, migracja, staging ──────────────────────────────────────────────


def test_feature_is_f55_on_sonnet_55_with_haiku_fallback() -> None:
    assert model_for(FEATURE) == "claude-sonnet-5-5"
    assert fallbacks_for(FEATURE) == ("claude-haiku-5-5",)
    assert choice_for(FEATURE).env_vars == ("INTERVIEW_ANSWER_PROPOSAL_MODEL",)
    assert choice_for(FEATURE).rationale.startswith("F55")
    assert "Pytania z rozmów" in FEATURE_LABELS[FEATURE]
    sent = " ".join(FEATURE_DATA_SENT[FEATURE])
    assert "bez nazwy klienta, danych kandydatów, nazwisk managerów i stawek" in sent


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r'"\s+"', "", text))


def test_migration_is_mirrored_in_entrypoint() -> None:
    path = BACKEND / "alembic" / "versions" / "0779_interview_answer_proposal.py"
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    assert module.down_revision == "0778_client_cv_file_format"
    migration = _squash(path.read_text())
    entry = _squash((BACKEND / "entrypoint.sh").read_text())
    for ddl in (
        "ALTER TABLE interview_questions ADD COLUMN IF NOT EXISTS ideal_answer_source VARCHAR(16) NULL",
        "UPDATE interview_questions SET ideal_answer_source = CASE "
        "WHEN source = 'legacy_import' THEN 'excel' ELSE 'manual' END "
        "WHERE ideal_answer_source IS NULL AND NULLIF(btrim(ideal_answer), '') IS NOT NULL",
    ):
        assert ddl in migration
        assert ddl in entry
    assert "ADD VALUE IF NOT EXISTS 'interview_answer_proposal'" in entry
    assert "SELECT 'interview_answer_proposal', TRUE, 0, now(), now()" in entry


def test_model_has_the_source_column() -> None:
    column = InterviewQuestion.__table__.columns["ideal_answer_source"]
    assert column.nullable and column.type.length == 16


def test_nightly_loop_is_registered_and_blocked_on_staging() -> None:
    from app.core.process_role import task_runs_in_role
    from app.core.staging import STAGING_ALLOWED_TASKS, STAGING_BLOCKED_TASKS
    from tests.test_staging_background_tasks import _registry_names

    assert "interview_answer_proposals" in _registry_names()
    assert "interview_answer_proposals" in STAGING_BLOCKED_TASKS
    assert "interview_answer_proposals" not in STAGING_ALLOWED_TASKS
    assert task_runs_in_role("interview_answer_proposals", "worker")
    assert not task_runs_in_role("interview_answer_proposals", "web")


@pytest.mark.parametrize(
    "hour,minute,inside",
    [
        (2, 39, False),
        (2, 40, True),
        (3, 0, True),
        (4, 59, True),
        (5, 0, False),
        (1, 0, False),
    ],
)
def test_night_window_starts_at_0240_warsaw(monkeypatch, hour, minute, inside) -> None:
    from app.tasks import interview_answer_proposals as task

    monkeypatch.setattr(task, "local_now", lambda: datetime(2026, 11, 26, hour, minute))
    assert task.in_night_window() is inside


# ── Bieg bez bazy: awaria modelu nie przerywa nocy ──────────────────────────


class _Session:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def scalar(self, _stmt):
        return 0


def _stub_run(monkeypatch, pending, model):
    stored: list[dict] = []

    @asynccontextmanager
    async def fake_feature(_db, feature, **_kw):
        assert feature is FEATURE
        yield None

    async def fake_pending(_db, *, limit):
        return pending[:limit]

    async def fake_store(_db, answers):
        stored.append(answers)
        return (
            sum(1 for a in answers.values() if a is not None),
            sum(1 for a in answers.values() if a is None),
        )

    monkeypatch.setattr("app.services.ai_quota.ai_feature", fake_feature)
    monkeypatch.setattr(iap, "api_key_configured", lambda _m: True)
    monkeypatch.setattr(iap, "pending_questions", fake_pending)
    monkeypatch.setattr(iap, "store", fake_store)
    monkeypatch.setattr(iap, "_call_model", model)
    return stored


def _ids_in(prompt: str) -> list[int]:
    payload = re.search(r"<pytania>\n(.*)\n</pytania>", prompt, re.S)
    return [item["id"] for item in json.loads(payload.group(1))]


async def test_failed_batch_is_skipped_and_the_rest_is_stored(monkeypatch) -> None:
    pending = [_q(i, client_id=1) for i in range(1, 4)] + [_q(10, client_id=2)]
    calls = {"n": 0}

    def model(prompt: str) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("przeciążenie")
        return json.dumps(
            [{"id": i, "answer": None if i == 10 else "Tak."} for i in _ids_in(prompt)]
        )

    stored = _stub_run(monkeypatch, pending, model)
    db = _Session()
    summary = await iap.run(db, limit=100)
    assert summary["status"] == "ok"
    assert summary["batches"] == 2 and summary["failed_batches"] == 1
    assert summary["headings"] == 1 and summary["answered"] == 0
    assert stored == [{10: None}]
    assert db.rollbacks == 1


async def test_three_failures_in_a_row_stop_the_night(monkeypatch) -> None:
    pending = [_q(i, client_id=i) for i in range(1, 6)]

    def model(_prompt: str) -> str:
        raise RuntimeError("401")

    stored = _stub_run(monkeypatch, pending, model)
    summary = await iap.run(_Session(), limit=100)
    assert summary["status"] == "provider_unavailable"
    assert summary["failed_batches"] == 3 and summary["batches"] == 3
    assert stored == []


async def test_zero_limit_and_missing_key_send_nothing(monkeypatch) -> None:
    def model(_prompt: str) -> str:  # pragma: no cover — nie może być wołany
        raise AssertionError("model wołany mimo braku zgody na bieg")

    _stub_run(monkeypatch, [_q(1)], model)
    assert (await iap.run(_Session(), limit=0))["status"] == "disabled"
    monkeypatch.setattr(iap, "api_key_configured", lambda _m: False)
    assert (await iap.run(_Session(), limit=10))["status"] == "unconfigured"
