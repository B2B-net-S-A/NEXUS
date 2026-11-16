"""Strażnik widełek w ogłoszeniu (16.11.2026) — czyste funkcje, bez bazy.

Publikacja bez widełek wymaga powodu; tekst dla umowy o pracę mówi, że wymaga
tego prawo (Dz.U. 2025 poz. 807), dla B2B — że to zalecane, bez przesądzania
zakresu prawa. Ścieżki z bazą: ``test_job_boards_queue.py``.
"""

from __future__ import annotations

from app.services.job_portals import jjit_payload, salary_guard


def test_contract_form_is_b2b_unless_the_ad_says_uop():
    assert salary_guard.contract_form("B2B") == "b2b"
    assert salary_guard.contract_form(None) == "b2b"
    assert salary_guard.contract_form("UoP") == "uop"
    assert salary_guard.contract_form("Umowa o pracę") == "uop"


def test_uop_message_says_the_law_requires_it():
    text = salary_guard.missing_salary_message("uop")
    assert "prawo wymaga" in text
    assert "Dz.U. 2025 poz. 807" in text
    assert "przed rozmową" in text


def test_b2b_message_recommends_and_leaves_the_law_open():
    text = salary_guard.missing_salary_message("b2b")
    assert "zalecane" in text
    assert "prawnikiem" in text
    assert "wymaga" not in text


def test_missing_reason_only_without_salary():
    salary = {"from": 150.0, "to": 190.0, "unit": "hour"}
    assert not salary_guard.missing_reason({"salary": salary})
    assert salary_guard.missing_reason({"salary": None})
    assert salary_guard.missing_reason({"salary": None, "no_salary_reason": " ok "})
    assert not salary_guard.missing_reason(
        {"salary": None, "no_salary_reason": "Stawka po rozmowie."}
    )


def test_normalize_keeps_reason_only_without_salary():
    reason = "  Stawka   zależy od profilu.  "
    bare = jjit_payload.normalize_options({"salary": None, "no_salary_reason": reason})
    assert bare["no_salary_reason"] == "Stawka zależy od profilu."
    with_salary = jjit_payload.normalize_options(
        {"salary": {"from": 100, "to": 150}, "no_salary_reason": reason}
    )
    assert with_salary["no_salary_reason"] is None
    long = jjit_payload.normalize_options({"no_salary_reason": "x" * 500})
    assert len(long["no_salary_reason"]) == salary_guard.REASON_MAX_LENGTH
