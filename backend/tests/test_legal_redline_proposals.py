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
    entities = [Entity("PARTNER", "Jan Testowy", inflect=True)]
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


def test_output_name_does_not_repeat_the_suffix():
    from app.api.legal_redline import _output_name

    assert _output_name("Umowa 12-2026.docx") == "Umowa 12-2026 — poprawki asystenta.docx"
    assert _output_name("Umowa 12-2026 — poprawki asystenta.docx") == "Umowa 12-2026 — poprawki asystenta.docx"
    assert _output_name("Umowa.DOCX") == "Umowa — poprawki asystenta.docx"


# ── maska przed modelem (przegląd bezpieczeństwa 25.11) ─────────────────────

LEAK_PARAGRAPHS = [
    Paragraph(0, "Umowę zawarto z Janem Kowalskim, ul. Długa 5, Kraków."),
    Paragraph(1, "Pan JAN KOWALSKI prowadzi działalność jako Kowalski Consulting."),
    Paragraph(2, "Wynagrodzenie Kowalskiego płatne jest na rachunek firmy Kowalski Consulting."),
]
LEAK_PARTNER = {
    "full_name": "Jan Kowalski",
    "company": "Kowalski Consulting",
    "address": "ul. Długa 5",
    "postal_city": "Kraków",
    "nip": "",
    "regon": "",
    "email": "",
    "phone": "",
}


async def _prompt_for(monkeypatch, *, instruction, entities, law=()):
    from contextlib import asynccontextmanager

    from app.services import ai_quota

    seen = {}

    @asynccontextmanager
    async def fake_feature(_db, feature, **_kw):
        yield None

    class _Db:
        async def commit(self):
            return None

    def capture(messages):
        seen["prompt"] = messages[0]["content"]
        return json.dumps({"changes": [], "notes": ["[PARTNER] — zapis spełnia wymóg."]})

    async def fake_search(_db, _query, **_kw):
        return list(law)

    monkeypatch.setattr(ai_quota, "ai_feature", fake_feature)
    monkeypatch.setattr(proposals, "_call_model", capture)
    monkeypatch.setattr(proposals, "search_law", fake_search)
    result = await proposals.propose(
        _Db(), paragraphs=LEAK_PARAGRAPHS, instruction=instruction, entities=entities, user_id=1
    )
    return seen["prompt"], result


@pytest.mark.asyncio
async def test_no_form_of_the_name_or_address_reaches_the_model(monkeypatch):
    from app.services.legal.pseudonymize import partner_entities

    prompt, result = await _prompt_for(
        monkeypatch,
        instruction="Dopisz, że Jan Kowalski (Kowalskiemu przysługuje urlop) pracuje z ul. Długiej 5.",
        entities=partner_entities(LEAK_PARTNER),
        law=[
            SourcePassage(
                kind="law",
                ref="kc art. 77 § 1",
                text="Zmiana umowy z Janem Kowalskim wymaga formy.",
                label="art. 77 § 1 KC",
            )
        ],
    )
    lowered = prompt.lower()
    for leak in ("kowalsk", "długa 5", "długiej 5", "kraków", "consulting"):
        assert leak not in lowered, leak
    assert "[PARTNER]" in prompt and "[FIRMA_PARTNERA]" in prompt and "[ADRES_PARTNERA]" in prompt
    # Przepis z korpusu jest w źródłach, a znacznik wraca po stronie NEXUSA.
    assert "<<kc art. 77 § 1>>" in prompt
    assert result.notes == ["Jan Kowalski — zapis spełnia wymóg."]


def test_partner_entities_skip_empty_values():
    from app.services.legal.pseudonymize import partner_entities

    entities = partner_entities({**LEAK_PARTNER, "nip": "123-456-32-18", "address": ""})
    labels = [e.label for e in entities]
    assert "NIP" in labels and labels.count("ADRES_PARTNERA") == 2
    assert all(e.value.strip() for e in entities)
    assert next(e for e in entities if e.label == "PARTNER").inflect is True


@pytest.mark.asyncio
async def test_contract_without_generated_row_still_masks_company_and_address(monkeypatch):
    from types import SimpleNamespace

    from app.api import legal_redline as api
    from app.services.trainings import agreement

    async def fake_partner(_db, contract_id):
        assert contract_id == 5
        return dict(LEAK_PARTNER)

    class _Db:
        async def get(self, _model, _id):
            return SimpleNamespace(name="Bank Testowy", legal_name="Bank Testowy S.A.")

    monkeypatch.setattr(agreement, "partner_from_contract", fake_partner)
    entities = await api._contract_entities(_Db(), SimpleNamespace(id=5, client_id=9))
    values = {(e.label, e.value) for e in entities}
    assert ("FIRMA_PARTNERA", "Kowalski Consulting") in values
    assert ("ADRES_PARTNERA", "ul. Długa 5, Kraków") in values
    assert ("KLIENT", "Bank Testowy S.A.") in values


@pytest.mark.asyncio
async def test_search_law_uses_the_corpus_and_survives_failure(monkeypatch):
    from datetime import date

    from app.services.legal import corpus
    from app.services.legal_redline import foundation

    hit = corpus.ProvisionHit(
        id=1, act_key="kc", act_short_name="KC", ref="art. 77 § 1", ref_key="77 §1",
        kind="paragraph", heading=None, text="Uzupełnienie lub zmiana umowy wymaga formy.",
        repealed=False, version_id=1, version_ident="x", valid_from=date(2026, 1, 1),
        valid_to=None, url="https://eli.gov.pl/x",
    )

    async def ok(_db, _q, **_kw):
        return [hit]

    monkeypatch.setattr(corpus, "search_provisions", ok)
    passages = await foundation.search_law(object(), "forma zmiany")
    assert [p.ref for p in passages] == ["kc art. 77 § 1"] and passages[0].kind == "law"

    async def boom(_db, _q, **_kw):
        raise RuntimeError("brak korpusu")

    monkeypatch.setattr(corpus, "search_provisions", boom)
    assert await foundation.search_law(object(), "forma zmiany") == []


@pytest.mark.parametrize("bad", ["\x0b", "\x00", "\x1f"])
@pytest.mark.parametrize("field_name", ["new_text", "reason"])
def test_render_refuses_xml_control_characters(bad, field_name):
    from fastapi import HTTPException

    from app.api.legal_redline import _parse_changes

    change = {"id": "a1", "kind": "replace", "paragraph": 1, "find": "zdalnie", "new_text": "x", "reason": "y"}
    change[field_name] = f"tekst{bad}dalej"
    with pytest.raises(HTTPException) as exc:
        _parse_changes(json.dumps([change]))
    assert exc.value.status_code == 422 and "znaki sterujące" in exc.value.detail


def test_render_accepts_tabs_newlines_and_line_separator():
    from app.api.legal_redline import _parse_changes

    change = {"id": "a1", "kind": "replace", "paragraph": 1, "new_text": "a\tb\nc d", "reason": "ok"}
    assert _parse_changes(json.dumps([change]))[0].new_text == "a\tb\nc d"
