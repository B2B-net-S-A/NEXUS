"""Dane firm z umów: wybór pliku, plan zmian w profilu, poprawki, rejestr, flaga pętli.

Czyste funkcje — bez bazy i bez modelu. Dane zmyślone.
"""

from __future__ import annotations

import asyncio

import pytest

from app.core.config import settings
from app.services.contract_partner_reads import service
from app.tasks import contract_partner_reads as task
from tests.test_contract_partner_reads_reader import bad_nip, valid_nip, valid_regon


def _doc(doc_id: int, filename: str, content_type: str | None = None):
    return service.DocumentRow(
        id=doc_id,
        contract_id=1,
        filename=filename,
        file_path=f"contracts/1/{doc_id}.bin",
        content_type=content_type,
        content_sha256=None,
    )


# ── Wybór głównego pliku umowy ───────────────────────────────────────────────


def test_file_with_current_contract_number_wins():
    docs = [_doc(1, "Umowa 12-2025.pdf"), _doc(2, "Umowa 3-2026.pdf")]
    assert service.pick_main_document(docs, (12, 2025)).id == 1


def test_without_current_number_newest_number_then_pdf_then_newest_file():
    docs = [
        _doc(1, "Umowa 3-2026 skan.jpg"),
        _doc(2, "Umowa 3-2026.pdf"),
        _doc(3, "Umowa 40-2025.pdf"),
        _doc(4, "Umowa podpisana.pdf"),
    ]
    assert service.pick_main_document(docs, None).id == 2


def test_docx_only_means_no_file_to_read():
    docs = [
        _doc(1, "Umowa 3-2026.docx", "application/pdf"),
        _doc(2, "notatka.txt"),
    ]
    assert service.pick_main_document(docs, None) is None
    assert service.pick_main_document([], (1, 2026)) is None


def test_current_number_without_matching_file_falls_back_to_newest():
    docs = [_doc(1, "Umowa 1-2024.pdf"), _doc(2, "Umowa 2-2025.pdf")]
    assert service.pick_main_document(docs, (9, 2026)).id == 2


# ── Plan zmian w profilu kandydata ───────────────────────────────────────────


def _confirmed(**over):
    base = {
        "partner_legal_name": "Testowa Consulting",
        "partner_nip": valid_nip(),
        "partner_regon": valid_regon(),
        "partner_business_address": "ul. Przykładowa 1, 00-001 Testowo",
        "partner_email": "anna@example.com",
        "partner_phone": "+48 600 000 000",
    }
    base.update(over)
    return base


def test_only_empty_columns_are_written_by_default():
    current = {
        "legal_name": "Inna Firma",
        "nip": None,
        "regon": "",
        "business_address": None,
        "email": "stary@example.com",
        "phone": None,
    }
    plan = service.plan_candidate_changes(current, _confirmed(), overwrite=False)
    assert plan["legal_name"] == {"action": "kept"}
    assert plan["nip"] == {"action": "written", "value": valid_nip()}
    assert plan["regon"]["action"] == "written"
    assert plan["business_address"]["action"] == "written"
    assert plan["email"] == {"action": "kept"}
    assert plan["phone"]["action"] == "written"


def test_overwrite_changes_company_fields_but_never_contact():
    current = {
        "legal_name": "Inna Firma",
        "nip": "0001112223",
        "regon": None,
        "business_address": "stary adres",
        "email": "stary@example.com",
        "phone": "+48 500 000 000",
    }
    plan = service.plan_candidate_changes(current, _confirmed(), overwrite=True)
    assert plan["legal_name"] == {
        "action": "written",
        "value": "Testowa Consulting",
        "previous": "Inna Firma",
    }
    assert plan["nip"]["action"] == "written"
    assert plan["email"] == {"action": "kept"}
    assert plan["phone"] == {"action": "kept"}


def test_same_value_in_other_format_is_not_rewritten():
    nip = valid_nip()
    current = {
        "legal_name": "TESTOWA  consulting",
        "nip": f"PL {nip[:3]}-{nip[3:6]}-{nip[6:8]}-{nip[8:]}",
        "regon": valid_regon() + "00000",
    }
    plan = service.plan_candidate_changes(current, _confirmed(), overwrite=True)
    assert plan["legal_name"] == {"action": "same"}
    assert plan["nip"] == {"action": "same"}
    assert plan["regon"] == {"action": "same"}


def test_field_missing_in_contract_is_not_written():
    plan = service.plan_candidate_changes(
        {"nip": None}, _confirmed(partner_nip=None), overwrite=True
    )
    assert plan["nip"] == {"action": "no_value"}


# ── Poprawki człowieka ───────────────────────────────────────────────────────


def _result(**values):
    return {"fields": {name: {"value": value} for name, value in values.items()}}


def test_correction_replaces_read_value_and_is_listed():
    values, corrected = service.confirmed_values(
        _result(partner_nip=None, partner_legal_name="Testowa"),
        {"partner_nip": valid_nip(), "partner_legal_name": "Testowa"},
    )
    assert values["partner_nip"] == valid_nip()
    assert corrected == ["partner_nip"]


def test_bad_correction_is_refused_not_saved():
    with pytest.raises(service.PartnerReadError) as exc:
        service.confirmed_values(_result(), {"partner_nip": bad_nip()})
    assert exc.value.status_code == 422
    with pytest.raises(service.PartnerReadError):
        service.confirmed_values(_result(), {"stawka": "100"})


def test_correction_can_clear_a_wrong_value():
    values, corrected = service.confirmed_values(
        _result(partner_email="zly@example.com"), {"partner_email": ""}
    )
    assert values["partner_email"] is None and corrected == ["partner_email"]


# ── Rejestr ──────────────────────────────────────────────────────────────────


def test_compare_with_registry_marks_differences():
    nip = valid_nip()
    rows = service.compare_with_registry(
        {
            "partner_legal_name": "Testowa Consulting Anna Testowa",
            "partner_nip": nip,
            "partner_krs": None,
            "partner_business_address": "ul. Przykładowa 1, 00-001 Testowo",
        },
        {
            "name": "TESTOWA CONSULTING ANNA TESTOWA",
            "nip": nip,
            "krs": None,
            "address": "ul. Przykładowa 2, 00-001 Testowo",
        },
    )
    by_field = {row["field"]: row for row in rows}
    assert by_field["partner_legal_name"]["same"] is True
    assert by_field["partner_nip"]["same"] is True
    assert by_field["partner_business_address"]["same"] is False
    assert "partner_krs" not in by_field  # rejestr nic nie podał
    assert service.compare_with_registry({"partner_nip": nip}, None) == []


# ── Pętla za flagą ───────────────────────────────────────────────────────────


def test_loop_with_flag_off_does_nothing(monkeypatch):
    assert settings.CONTRACT_PARTNER_READ_ENABLED is False

    async def must_not_run(*_args, **_kwargs):
        raise AssertionError("pętla nie powinna nic robić przy wyłączonej fladze")

    monkeypatch.setattr(task.asyncio, "sleep", must_not_run)
    monkeypatch.setattr(task, "run_cycle", must_not_run)
    monkeypatch.setattr(service, "scan", must_not_run)
    assert asyncio.run(task.contract_partner_reads_loop()) is None
