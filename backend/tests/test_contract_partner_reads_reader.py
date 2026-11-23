"""Czytnik danych firmy Partnera z umowy (bez modelu i bez bazy).

Numery NIP i REGON liczone w teście z prefiksów „000…” (poprawna cyfra
kontrolna, a urzędu skarbowego ani województwa o kodzie 000 nie ma, więc to nie
są czyjeś numery), dane firm zmyślone.
"""

from __future__ import annotations

import asyncio
import json

from app.core.config import settings
from app.services.contract_partner_reads import reader

_NIP_WEIGHTS = (6, 5, 7, 2, 3, 4, 5, 6, 7)
_REGON_WEIGHTS = (8, 9, 2, 3, 4, 5, 6, 7)


def valid_nip(prefix: str = "000000111") -> str:
    for _ in range(10):
        control = sum(int(d) * w for d, w in zip(prefix, _NIP_WEIGHTS)) % 11
        if control != 10:
            return prefix + str(control)
        prefix = prefix[:-1] + str((int(prefix[-1]) + 1) % 10)
    raise AssertionError("brak NIP-u dla prefiksu")


def valid_regon(prefix: str = "00000012") -> str:
    control = sum(int(d) * w for d, w in zip(prefix, _REGON_WEIGHTS)) % 11
    return prefix + str(control % 10)


def bad_nip() -> str:
    nip = valid_nip()
    return nip[:-1] + str((int(nip[-1]) + 1) % 10)


def _reply(**fields) -> str:
    base = {
        "gender": {"value": "K", "quote": "z Panią Anną Testową"},
        "partner_name": {"value": "Anna  Testowa", "quote": "z Panią Anną Testową"},
        "partner_legal_name": {
            "value": "Testowa Consulting Anna Testowa",
            "quote": "prowadzącą działalność pod firmą Testowa Consulting Anna Testowa",
        },
        "partner_entity_type": {"value": "sole_trader", "quote": None},
        "partner_nip": {"value": f"PL {valid_nip()}", "quote": f"NIP: {valid_nip()}"},
        "partner_regon": {"value": valid_regon(), "quote": None},
        "partner_business_address": {
            "value": "ul. Przykładowa 1, 00-001 Testowo",
            "quote": None,
        },
        "partner_email": {"value": "Anna@Example.com", "quote": None},
        "partner_phone": {"value": "+48 600 000 000", "quote": None},
    }
    base.update(fields)
    payload = {
        "document_kind": "contract",
        "agreement_number": "12/2026",
        "document_date": "2026-03-01",
        "fields": base,
    }
    return "```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"


def _field(result: reader.ReadResult, name: str) -> dict:
    return result.fields["fields"][name]


def _issues(result: reader.ReadResult) -> dict[str, str]:
    return {i["field"]: i["message"] for i in result.fields["issues"]}


def test_parse_reply_cleans_every_field_and_keeps_quotes():
    result = reader.parse_reply(_reply(), "image")
    assert result.status == "read" and result.mode == "image"
    assert set(result.fields["fields"]) == set(reader.FIELDS)
    assert _field(result, "gender")["value"] == "k"
    assert _field(result, "partner_name")["value"] == "Anna Testowa"
    assert _field(result, "partner_nip")["value"] == valid_nip()
    assert _field(result, "partner_regon")["value"] == valid_regon()
    assert _field(result, "partner_email")["value"] == "anna@example.com"
    assert _field(result, "partner_phone")["value"] == "+48 600 000 000"
    assert _field(result, "partner_name")["quote"] == "z Panią Anną Testową"
    # Skan: cytatu nie da się sprawdzić w tekście.
    assert _field(result, "partner_name")["quote_found"] is None
    assert result.fields["contract_variant"] == "jdg"
    assert result.fields["agreement_number"] == "12/2026"
    assert result.fields["issues"] == []


def test_missing_fields_stay_none_and_are_not_invented():
    result = reader.parse_reply(_reply(), "image")
    for name in ("partner_krs", "partner_seat", "partner_correspondence_address"):
        assert _field(result, name) == {
            "value": None,
            "quote": None,
            "quote_found": None,
        }


def test_bad_nip_checksum_is_dropped_with_a_note():
    result = reader.parse_reply(
        _reply(partner_nip={"value": bad_nip(), "quote": "NIP"}), "image"
    )
    assert _field(result, "partner_nip")["value"] is None
    assert "cyfrą kontrolną" in _issues(result)["partner_nip"]


def test_company_nip_is_not_the_partner(monkeypatch):
    monkeypatch.setattr(settings, "KSEF_CONTEXT_NIP", valid_nip())
    result = reader.parse_reply(_reply(), "image")
    assert _field(result, "partner_nip")["value"] is None
    assert "B2B.net" in _issues(result)["partner_nip"]


def test_regon_from_krs_with_trailing_zeros_and_bad_regon():
    long_regon = valid_regon() + "00000"
    ok = reader.parse_reply(_reply(partner_regon={"value": long_regon}), "image")
    assert _field(ok, "partner_regon")["value"] == valid_regon()
    bad = reader.parse_reply(_reply(partner_regon={"value": "12345"}), "image")
    assert _field(bad, "partner_regon")["value"] is None
    assert "9 albo 14 cyfr" in _issues(bad)["partner_regon"]


def test_krs_makes_company_and_is_padded():
    result = reader.parse_reply(
        _reply(
            partner_entity_type={"value": "spółka", "quote": None},
            partner_krs={"value": "123456", "quote": "KRS 123456"},
        ),
        "image",
    )
    assert _field(result, "partner_krs")["value"] == "0000123456"
    assert _field(result, "partner_entity_type")["value"] == "company"
    assert result.fields["contract_variant"] == "company"


def test_bad_email_phone_and_gender():
    result = reader.parse_reply(
        _reply(
            partner_email={"value": "anna(at)example"},
            partner_phone={"value": "tel. 12"},
            gender={"value": "kobieta"},
        ),
        "image",
    )
    assert _field(result, "partner_email")["value"] is None
    assert _field(result, "partner_phone")["value"] is None
    assert _field(result, "gender")["value"] is None
    assert {"partner_email", "partner_phone"} <= set(_issues(result))


def test_plain_value_without_quote_object_is_accepted():
    result = reader.parse_reply(_reply(partner_seat="Testowo"), "image")
    assert _field(result, "partner_seat") == {
        "value": "Testowo",
        "quote": None,
        "quote_found": None,
    }


def test_quote_checked_against_pdf_text():
    text = "Umowa zawarta z Panią Anną Testową,\nprowadzącą działalność pod firmą XYZ"
    result = reader.parse_reply(_reply(), "text", document_text=text)
    assert _field(result, "partner_name")["quote_found"] is True
    assert _field(result, "partner_legal_name")["quote_found"] is False
    assert "cytatu nie ma" in _issues(result)["partner_legal_name"]


def test_document_that_is_not_a_contract_gets_a_note():
    payload = json.loads(_reply().strip("`").removeprefix("json\n"))
    payload["document_kind"] = "faktura"
    result = reader.parse_reply(json.dumps(payload))
    assert result.fields["document_kind"] == "other"
    assert "document_kind" in _issues(result)


def test_garbage_reply_is_failed():
    assert reader.parse_reply("nie wiem").status == "failed"
    assert reader.parse_reply("{to nie json}").status == "failed"
    assert reader.parse_reply("[1, 2]").status == "failed"


def test_every_field_has_a_label():
    assert set(reader.LABELS) == set(reader.FIELDS)


def test_clean_value_runs_the_same_rules_for_human_corrections():
    assert reader.clean_value("partner_nip", valid_nip()) == (valid_nip(), None)
    assert reader.clean_value("partner_nip", bad_nip())[0] is None
    assert reader.clean_value("partner_legal_name", "  ") == (None, None)
    assert reader.clean_value("partner_entity_type", "company") == ("company", None)


def test_read_document_with_fake_model(monkeypatch):
    monkeypatch.setattr(reader, "_call_model", lambda _blocks: _reply())
    result = asyncio.run(
        reader.read_document(b"\xff\xd8fake", "image/jpeg", "umowa.jpg")
    )
    assert result.status == "read" and result.mode == "image"
    assert result.as_json()["version"] == reader.READER_VERSION


def test_read_document_model_failure_is_failed(monkeypatch):
    def boom(_blocks):
        raise RuntimeError("przeciążenie")

    monkeypatch.setattr(reader, "_call_model", boom)
    result = asyncio.run(
        reader.read_document(b"\xff\xd8fake", "image/jpeg", "umowa.jpg")
    )
    assert result.status == "failed"


def test_read_document_skips_docx():
    result = asyncio.run(
        reader.read_document(b"PK", "application/vnd.openxmlformats", "umowa.docx")
    )
    assert result.status == "skipped"
