"""Propozycje modelu „Popraw dokument”: maski, kotwice, cytaty — bez modelu.

Odpowiedź modelu jest wpisana w teście (fikcyjne dane), więc sprawdzamy to,
co robi kod: odmaskowanie, odrzucenie złej kotwicy i zmyślonych danych,
blokadę cytatu bez pokrycia oraz zachowanie bez modelu.
"""

from __future__ import annotations

import json

import pytest

from app.services.legal_redline import proposals
from app.services.legal_redline.foundation import (
    Entity,
    SourcePassage,
    detect_entities,
    mask,
    unmask,
    verify_sources,
)
from app.services.legal_redline.model import ChangeSource, Paragraph

PARAGRAPHS = [
    Paragraph(0, "§ 4 Ogólne zasady współpracy", heading=True),
    Paragraph(1, "Partner Jan Testowy, NIP 123-456-32-18, świadczy Usługi zdalnie."),
    Paragraph(2, "Kontakt: jan.testowy@example.com."),
    Paragraph(3, "Zmiany Umowy wymagają formy pisemnej pod rygorem nieważności."),
]
LAW = SourcePassage(
    kind="law",
    ref="kc-77-1",
    text="Uzupełnienie lub zmiana umowy wymaga zachowania formy, jaka była przewidziana do jej zawarcia.",
    label="art. 77 § 1 KC",
)


def test_mask_and_unmask_roundtrip():
    entities = [Entity("PARTNER", "Jan Testowy"), *detect_entities(PARAGRAPHS[1].text + " " + PARAGRAPHS[2].text)]
    masked, mapping = mask(PARAGRAPHS[1].text + " " + PARAGRAPHS[2].text, entities)
    assert "Jan Testowy" not in masked and "123-456-32-18" not in masked
    assert "example.com" not in masked
    assert "[PARTNER]" in masked and "[NIP]" in masked and "[EMAIL]" in masked
    assert unmask(masked, mapping) == PARAGRAPHS[1].text + " " + PARAGRAPHS[2].text


def test_verify_sources_states():
    passages = [LAW]
    checked = verify_sources(
        [
            ChangeSource(ref="kc-77-1", label="", quote="zmiana umowy wymaga  zachowania formy"),
            ChangeSource(ref="kc-77-1", label="", quote="forma elektroniczna jest zawsze wystarczająca"),
            ChangeSource(ref="kc-999", label="", quote="cokolwiek"),
        ],
        passages,
    )
    assert [c.state for c in checked] == ["ok", "mismatch", "missing"]
    assert checked[0].label == "art. 77 § 1 KC" and checked[0].kind == "law"


def _reply(changes, notes=()):
    return "Oto zmiany:\n" + json.dumps({"changes": changes, "notes": list(notes)}, ensure_ascii=False)


def _parse(reply_text, mapping=None):
    return proposals.parse_reply(
        reply_text,
        paragraphs=PARAGRAPHS,
        mapping=mapping or {"[PARTNER]": "Jan Testowy"},
        passages=[
            SourcePassage(kind="contract", ref="dokument", text="\n".join(p.text for p in PARAGRAPHS)),
            LAW,
        ],
    )


def test_reply_is_unmasked_anchored_and_verified():
    result = _parse(
        _reply(
            [
                {
                    "paragraph": 1,
                    "kind": "replace",
                    "find": "zdalnie",
                    "new_text": "zdalnie wyłącznie z terytorium EOG",
                    "reason": "[PARTNER] ma pracować z EOG.",
                    "sources": [],
                },
                {
                    "paragraph": 3,
                    "kind": "replace",
                    "find": "formy pisemnej",
                    "new_text": "formy pisemnej albo elektronicznej",
                    "reason": "Forma zmiany jak forma zawarcia.",
                    "sources": [{"ref": "kc-77-1", "quote": "Uzupełnienie lub zmiana umowy wymaga zachowania formy"}],
                },
            ],
            notes=["§ 12 spełnia wymóg."],
        )
    )
    assert result.status == "ok"
    assert [c.paragraph for c in result.changes] == [1, 3]
    first, second = result.changes
    assert first.reason == "Jan Testowy ma pracować z EOG."
    assert PARAGRAPHS[1].text[first.start : first.end] == "zdalnie"
    assert second.sources[0].state == "ok" and not second.blocked
    assert result.notes == ["§ 12 spełnia wymóg."]


def test_quote_without_cover_blocks_the_change():
    result = _parse(
        _reply(
            [
                {
                    "paragraph": 3,
                    "kind": "replace",
                    "find": "pisemnej",
                    "new_text": "dokumentowej",
                    "reason": "x",
                    "sources": [{"ref": "kc-77-1", "quote": "forma dokumentowa wystarcza zawsze"}],
                }
            ]
        )
    )
    assert result.changes[0].blocked is True


def test_bad_anchor_and_invented_marker_are_dropped():
    result = _parse(
        _reply(
            [
                {"paragraph": 1, "kind": "replace", "find": "nie ma takiego tekstu", "new_text": "x", "reason": "x"},
                {"paragraph": 2, "kind": "replace", "find": "Kontakt", "new_text": "Kontakt [EMAIL_7]", "reason": "x"},
                {"paragraph": 99, "kind": "insert_paragraph", "new_text": "x", "reason": "x"},
                {"paragraph": 3, "kind": "delete_paragraph", "reason": "zbędne"},
            ]
        )
    )
    assert [c.kind for c in result.changes] == ["delete_paragraph"]
    assert result.changes[0].find == PARAGRAPHS[3].text
    assert len(result.dropped) == 3
    assert any("[EMAIL_7]" in d.reason for d in result.dropped)


def test_garbage_reply_is_failed_not_an_error():
    assert _parse("model się zawiesił").status == "failed"


@pytest.mark.asyncio
async def test_without_instruction_model_is_not_called(monkeypatch):
    monkeypatch.setattr(proposals, "_call_model", lambda _m: pytest.fail("model wywołany"))
    result = await proposals.propose(None, paragraphs=PARAGRAPHS, instruction="  ", entities=[], user_id=None)
    assert result.status == "no_instruction" and result.changes == []


@pytest.mark.asyncio
async def test_model_gets_masked_text_and_failure_is_soft(monkeypatch):
    from contextlib import asynccontextmanager

    from app.services import ai_quota

    seen = {}

    @asynccontextmanager
    async def fake_feature(_db, feature, **_kw):
        seen["feature"] = feature.value
        yield None

    class _Db:
        async def commit(self):
            return None

    def boom(messages):
        seen["prompt"] = messages[0]["content"]
        raise RuntimeError("przeciążenie")

    monkeypatch.setattr(ai_quota, "ai_feature", fake_feature)
    monkeypatch.setattr(proposals, "_call_model", boom)
    result = await proposals.propose(
        _Db(),
        paragraphs=PARAGRAPHS,
        instruction="Dodaj wymóg pracy z EOG",
        entities=[Entity("PARTNER", "Jan Testowy")],
        user_id=7,
    )
    assert result.status == "failed" and result.changes == []
    assert seen["feature"] == "legal_redline"
    assert "Jan Testowy" not in seen["prompt"]
    assert "123-456-32-18" not in seen["prompt"]
    assert "jan.testowy@example.com" not in seen["prompt"]
    assert "[PARTNER]" in seen["prompt"]
