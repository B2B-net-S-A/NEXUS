"""Wymagania klientów do faktury z NEXUSA (reguły ``cl.*``, 23.11.2026) — bez bazy.

Reguły rozliczeń klienta (``rules_catalog``) sterują szkicem i FA(3): kilka
zamówień na jednej fakturze, ``NrUmowy``, pola ``DodatkowyOpis`` z kluczem
klienta, wzór opisu pozycji z rolą, tekst wymagany w każdej pozycji, mail
z fakturą obok KSeF. Adresy i numery fikcyjne.
"""

from __future__ import annotations

from datetime import date

from app.services.client_invoicing import requirements as req
from app.services.client_settlements import rules_catalog as catalog


def _rules(**on: dict) -> dict:
    stored = {
        key: {"level": value.pop("level", "block"), "params": value}
        for key, value in on.items()
    }
    return catalog.effective(stored)


def test_client_without_rules_changes_nothing() -> None:
    found = req.from_rules(catalog.effective(None), "2026-10")
    assert found == req.Requirements()
    assert req.ksef_fields(found, ["ZAM_1"]) == ()
    assert req.line_problems(found, [{"name": "Usługa"}]) == ([], [])
    assert (
        found.item_name(
            service="Usługi",
            order_number="Z",
            person="Jan",
            role="PO",
            period="2026-10",
        )
        is None
    )


def test_contract_number_and_date() -> None:
    found = req.from_rules(
        _rules(
            **{"cl.ksef_contract": {"number": " UR/2020/77 ", "date": "2020-03-02"}}
        ),
        "2026-10",
    )
    assert found.contract_number == "UR/2020/77"
    assert found.contract_date == date(2020, 3, 2)
    bad = req.from_rules(
        _rules(**{"cl.ksef_contract": {"number": "UR/1", "date": "2.03.2020"}}),
        "2026-10",
    )
    assert bad.contract_number == "UR/1" and bad.contract_date is None


def test_switched_off_contract_rule_is_ignored() -> None:
    found = req.from_rules(
        _rules(**{"cl.ksef_contract": {"number": "UR/1", "level": "off"}}), "2026-10"
    )
    assert found.contract_number is None


def test_extra_fields_with_order_numbers_and_empty_value_skipped() -> None:
    found = req.from_rules(
        _rules(
            **{
                "cl.ksef_fields": {
                    "key": "OSOBA",
                    "value": "koordynator@example.com",
                    "key2": "ZAMOWIENIA",
                    "value2": "{zamowienie}",
                }
            }
        ),
        "2026-11",
    )
    assert req.ksef_fields(found, ["ZAM_1", "ZAM_2"]) == (
        ("OSOBA", "koordynator@example.com"),
        ("ZAMOWIENIA", "ZAM_1, ZAM_2"),
    )
    empty = req.from_rules(
        _rules(**{"cl.ksef_fields": {"key": "OSOBA", "value": ""}}), "2026-11"
    )
    assert req.ksef_fields(empty, ["ZAM_1"]) == ()


def test_item_name_template_with_role_and_month() -> None:
    found = req.from_rules(
        _rules(
            **{
                "cl.item_name": {
                    "template": "{usluga} — {rola} — {osoba} — {miesiac} ({zamowienie})"
                }
            }
        ),
        "2026-09",
    )
    assert (
        found.item_name(
            service="Usługi informatyczne",
            order_number="445",
            person="Jan Przykładowy",
            role="Product Owner",
            period="2026-09",
        )
        == "Usługi informatyczne — Product Owner — Jan Przykładowy — wrzesień 2026 (445)"
    )
    # Brak roli nie zostawia znacznika w opisie.
    assert "{rola}" not in found.item_name(
        service="U", order_number="1", person="Jan", role=None, period="2026-09"
    )


def test_required_text_blocks_or_warns_per_level() -> None:
    lines = [{"name": "Usługi — Jan — JIRA ABC-1"}, {"name": "Usługi — Ola"}]
    block = req.from_rules(
        _rules(**{"cl.item_must_contain": {"text": "jira"}}), "2026-10"
    )
    blocking, warnings = req.line_problems(block, lines)
    assert warnings == [] and len(blocking) == 1
    assert (
        blocking[0]
        == "Klient wymaga „jira” w opisie każdej pozycji — brak w pozycji 2."
    )
    warn = req.from_rules(
        _rules(**{"cl.item_must_contain": {"text": "JIRA", "level": "warn"}}), "2026-10"
    )
    blocking, warnings = req.line_problems(warn, lines)
    assert blocking == [] and len(warnings) == 1
    # Pusty tekst = reguła bez działania.
    none = req.from_rules(_rules(**{"cl.item_must_contain": {"text": " "}}), "2026-10")
    assert req.line_problems(none, lines) == ([], [])


def test_mail_address_and_subject_per_series() -> None:
    found = req.from_rules(
        _rules(
            **{
                "cl.invoice_mail": {
                    "email": "einvoice-pl@example.com",
                    "subject": "Faktura VAT Nr: {numer}_ Spółka_{mm}_{rrrr}",
                    "email_eu": "einvoice-eu@example.com",
                    "subject_eu": "attachment; Faktura UE VAT Nr: {numer}",
                    "attach": "PDF faktury",
                }
            }
        ),
        "2026-10",
    )
    pl = found.mail_for(
        series="PL",
        number="7/11/2026",
        ksef_number=None,
        period="2026-10",
        order_numbers=["Z1"],
    )
    assert pl == {
        "email": "einvoice-pl@example.com",
        "subject": "Faktura VAT Nr: 7/11/2026_ Spółka_10_2026",
        "attach": "PDF faktury",
    }
    eu = found.mail_for(
        series="UE",
        number="8/11/2026/UE",
        ksef_number="X",
        period="2026-10",
        order_numbers=[],
    )
    assert eu["email"] == "einvoice-eu@example.com"
    assert eu["subject"] == "attachment; Faktura UE VAT Nr: 8/11/2026/UE"


def test_mail_subject_with_ksef_number_waits_for_it() -> None:
    found = req.from_rules(
        _rules(
            **{
                "cl.invoice_mail": {
                    "email": "faktury@example.com",
                    "subject": "{ksef}",
                    "attach": "TS",
                }
            }
        ),
        "2026-10",
    )
    draft = found.mail_for(
        series="PL", number=None, ksef_number=None, period="2026-10", order_numbers=[]
    )
    assert draft["subject"] == "(numer KSeF po przyjęciu)"
    accepted = found.mail_for(
        series="PL",
        number="1/11/2026",
        ksef_number="1111111111-20261120-ABC",
        period="2026-10",
        order_numbers=[],
    )
    assert accepted["subject"] == "1111111111-20261120-ABC"
    # Seria UE bez osobnego adresu bierze adres główny.
    assert (
        found.mail_for(
            series="UE",
            number="1",
            ksef_number=None,
            period="2026-10",
            order_numbers=[],
        )["email"]
        == "faktury@example.com"
    )


def test_mail_without_address_is_none() -> None:
    found = req.from_rules(_rules(**{"cl.invoice_mail": {"subject": "x"}}), "2026-10")
    assert (
        found.mail_for(
            series="PL",
            number="1",
            ksef_number=None,
            period="2026-10",
            order_numbers=[],
        )
        is None
    )


def test_orders_together_and_signed_document_switches() -> None:
    found = req.from_rules(
        _rules(
            **{
                "cl.orders_together": {},
                "cl.after_signed_document": {},
                "cl.client_document": {
                    "kind": "protokół",
                    "per": "cały miesiąc",
                    "from": "",
                    "header": "",
                },
            }
        ),
        "2026-10",
    )
    assert found.orders_together is True
    assert found.signed_document == "protocol"


def test_signed_document_rule_without_document_kind_does_not_block() -> None:
    found = req.from_rules(_rules(**{"cl.after_signed_document": {}}), "2026-10")
    assert found.signed_document is None


def test_summary_lists_active_requirements_for_the_card() -> None:
    found = req.from_rules(
        _rules(
            **{
                "cl.ksef_contract": {"number": "UR/1", "date": ""},
                "cl.ksef_fields": {"key": "OSOBA", "value": "k@example.com"},
                "cl.item_must_contain": {"text": "JIRA"},
                "cl.orders_together": {},
            }
        ),
        "2026-10",
    )
    labels = [item["label"] for item in req.summary(found, ["ZAM_1", "ZAM_2"])]
    assert labels == [
        "Numery zamówień (KSeF)",
        "Numer umowy (KSeF)",
        "OSOBA (KSeF, pole dodatkowe)",
        "Każda pozycja zawiera",
    ]


# ── Po przeglądzie kodu (23.11.2026) ────────────────────────────────────────

import pytest  # noqa: E402

from app.models.client_issued_invoice import ClientIssuedInvoice  # noqa: E402
from app.services.client_invoicing import (  # noqa: E402
    billing,
    issue,
    issue_settings,
    templates,
)


def _merged_invoice(**extra) -> ClientIssuedInvoice:
    data = dict(
        client_id=16,
        invoice_type="VAT",
        series_code="PL",
        status="draft",
        period_year=2026,
        period_month=10,
        buyer={"name": "Bank", "address_l1": "ul. 1"},
        lines=[
            {"name": "A", "order_key": "o1", "order_number": "Z1", "contract_id": 7},
            {"name": "B", "order_key": "o2", "order_number": "Z2", "contract_id": 8},
        ],
    )
    data.update(extra)
    return ClientIssuedInvoice(**data)


def test_removed_buyer_code_is_not_reused_for_a_new_buyer() -> None:
    data = issue_settings.normalize(
        {
            "clients": {
                "16": {
                    "buyers": [
                        {"code": "b1", "name": "Spółka A"},
                        {"name": "Spółka C (nowa)"},
                    ],
                    "contract_buyers": {"7": "b2", "8": "b1"},
                }
            }
        }
    )
    entry = data["clients"]["16"]
    assert [b["code"] for b in entry["buyers"]] == ["b1", "b3"]
    # Kontrakt usuniętego nabywcy nie przechodzi na nową spółkę.
    assert entry["contract_buyers"] == {"8": [{"code": "b1", "from": "2000-01"}]}


def test_template_from_invoice_drops_order_refs_of_lines() -> None:
    line = templates._template_line(  # noqa: SLF001
        {
            "name": "A",
            "quantity": "1",
            "unit_price": "10",
            "vat_rate": "23",
            "order_key": "o1",
            "order_number": "Z1",
            "contract_id": 7,
        }
    )
    assert "order_key" not in line and "order_number" not in line
    assert "contract_id" not in line


@pytest.mark.asyncio
async def test_template_is_refused_for_invoice_from_several_orders() -> None:
    with pytest.raises(issue.IssueError, match="zamówienia"):
        await templates.from_invoice(None, _merged_invoice(), actor_id=1)


def test_correction_does_not_require_a_buyer_from_the_list() -> None:
    settings = issue_settings.normalize(
        {"clients": {"16": {"buyers": [{"name": "Spółka A"}]}}}
    )
    assert issue.buyer_choice_needed(_merged_invoice(), settings) is True
    assert (
        issue.buyer_choice_needed(_merged_invoice(invoice_type="KOR"), settings)
        is False
    )


@pytest.mark.asyncio
async def test_signed_document_gate_blocks_people_without_contract() -> None:
    row = billing.BillingRow(
        client_id=16,
        kind="md",
        group_id=5,
        order_id=None,
        order_number="ORD-1",
        currency="PLN",
        lines=(
            billing.BillingLine(
                order_id=None,
                consultant="Pula zespołu",
                basis="md",
                quantity=None,
                unit_price=None,
                net=None,
                currency="PLN",
            ),
        ),
    )
    found = req.Requirements(signed_document="protocol")
    block = await issue._signature_block(None, row, found, {}, "2026-10")  # noqa: SLF001
    assert block is not None and "Pula zespołu" in block


# ── Nabywca kontraktu od miesiąca (zmiana nabywcy w CPro, 24.11.2026) ───────


def _two_buyers(mapping: dict) -> dict:
    return issue_settings.normalize(
        {
            "clients": {
                "16": {
                    "buyers": [
                        {"code": "b1", "name": "Spółka SA"},
                        {"code": "b2", "name": "Spółka Finland"},
                    ],
                    "contract_buyers": mapping,
                }
            }
        }
    )


def test_buyer_of_contract_changes_from_a_month_and_earlier_months_keep_the_old() -> (
    None
):
    data = _two_buyers(
        {
            "7": [
                {"code": "b2", "from": "2026-09"},
                {"code": "b1", "from": "2026-01"},
            ]
        }
    )
    assert data["clients"]["16"]["contract_buyers"]["7"] == [
        {"code": "b1", "from": "2026-01"},
        {"code": "b2", "from": "2026-09"},
    ]
    pick = issue_settings.buyer_for_contract
    assert pick(data, 16, 7, "2026-08")["code"] == "b1"
    assert pick(data, 16, 7, "2026-09")["code"] == "b2"
    assert pick(data, 16, 7, "2026-11")["code"] == "b2"
    # Przed pierwszym przypisaniem kontrakt nie ma nabywcy z listy.
    assert pick(data, 16, 7, "2025-12") is None


def test_legacy_mapping_without_month_counts_from_the_start() -> None:
    data = _two_buyers({"7": "b2", "8": [{"code": "b1", "from": "bad"}]})
    assert data["clients"]["16"]["contract_buyers"] == {
        "7": [{"code": "b2", "from": "2000-01"}]
    }
    assert issue_settings.buyer_for_contract(data, 16, 7, "2026-10")["code"] == "b2"


def test_choosing_a_buyer_in_a_draft_applies_from_its_month_only() -> None:
    data = _two_buyers({"7": [{"code": "b1", "from": "2026-01"}]})
    assert issue_settings.remember_buyer(data, 16, [7], "b2", "2026-09") is True
    pick = issue_settings.buyer_for_contract
    assert pick(data, 16, 7, "2026-08")["code"] == "b1"
    assert pick(data, 16, 7, "2026-10")["code"] == "b2"
    # Ten sam nabywca, co już obowiązuje w miesiącu — nic do zapisania.
    assert issue_settings.remember_buyer(data, 16, [7], "b2", "2026-10") is False
    # Poprawka sierpnia nie rusza września.
    assert issue_settings.remember_buyer(data, 16, [7], "b2", "2026-08") is True
    assert pick(data, 16, 7, "2026-07")["code"] == "b1"
    assert pick(data, 16, 7, "2026-08")["code"] == "b2"
    assert data["clients"]["16"]["contract_buyers"]["7"] == [
        {"code": "b1", "from": "2026-01"},
        {"code": "b2", "from": "2026-08"},
    ]


# ── Numer umowy per zamówienie albo grupa (BNP, decyzja Artura 28.11.2026) ───

_BY_ORDER = {
    "number": "UR/2020/77",
    "date": "2020-03-02",
    "by_order": "ZAM/7_2026=UR/2015/5; zam/8_2026 = UR/2015/6 z 2015-06-01",
}


def test_contract_map_gives_the_order_its_contract_and_others_the_default() -> None:
    found = req.from_rules(_rules(**{"cl.ksef_contract": dict(_BY_ORDER)}), "2026-11")
    assert found.contract_for("ZAM/7_2026") == ("UR/2015/5", None)
    # Wielkość liter i spacje w numerze zamówienia się nie liczą.
    assert found.contract_for(" ZAM/8_2026 ") == ("UR/2015/6", date(2015, 6, 1))
    assert found.contract_for("ZAM/9_2026") == ("UR/2020/77", date(2020, 3, 2))
    assert found.contract_for(None) == ("UR/2020/77", date(2020, 3, 2))

    mapped = req.with_contract(found, ["ZAM/7_2026"])
    assert (mapped.contract_number, mapped.contract_date) == ("UR/2015/5", None)
    assert req.summary(mapped, ["ZAM/7_2026"])[0] == {
        "label": "Numer umowy (KSeF)",
        "value": "UR/2015/5",
    }
    other = req.with_contract(found, ["ZAM/9_2026"])
    assert (other.contract_number, other.contract_date) == (
        "UR/2020/77",
        date(2020, 3, 2),
    )
    assert other.contract_conflict == ()


def test_invoice_with_orders_of_two_contracts_has_no_contract_and_a_conflict() -> None:
    found = req.from_rules(_rules(**{"cl.ksef_contract": dict(_BY_ORDER)}), "2026-11")
    mixed = req.with_contract(found, ["ZAM/7_2026", "ZAM/9_2026"])
    assert mixed.contract_number is None and mixed.contract_date is None
    assert mixed.contract_conflict == ("UR/2015/5", "UR/2020/77")


def test_contract_typed_in_the_draft_wins_over_the_rules() -> None:
    found = req.from_rules(_rules(**{"cl.ksef_contract": dict(_BY_ORDER)}), "2026-11")
    typed = req.with_contract(
        found, ["ZAM/7_2026", "ZAM/9_2026"], override=("UR/2016/9", None)
    )
    assert (typed.contract_number, typed.contract_date) == ("UR/2016/9", None)
    assert typed.contract_conflict == ()
    # Bez reguły klienta numer ze szkicu też trafia do KSeF.
    bare = req.with_contract(
        req.Requirements(), [], override=("UR/2016/9", date(2016, 1, 4))
    )
    assert (bare.contract_number, bare.contract_date) == (
        "UR/2016/9",
        date(2016, 1, 4),
    )


def test_contract_map_without_default_number_leaves_other_orders_without() -> None:
    found = req.from_rules(
        _rules(**{"cl.ksef_contract": {"by_order": "ZAM/7_2026=UR/2015/5"}}),
        "2026-11",
    )
    assert found.contract_number is None
    assert req.with_contract(found, ["ZAM/9_2026"]).contract_number is None
    assert req.with_contract(found, ["ZAM/7_2026"]).contract_number == "UR/2015/5"


def test_unreadable_contract_map_is_refused_when_rules_are_saved() -> None:
    def save(by_order: str) -> dict:
        return catalog.clean_for_save(
            [
                {
                    "key": "cl.ksef_contract",
                    "level": "block",
                    "params": {"number": "UR/1", "by_order": by_order},
                }
            ]
        )

    for bad in ("ZAM/7_2026 UR/2015/5", "=UR/2015/5", "ZAM/7_2026=", "A=B z 2.03.2015"):
        with pytest.raises(catalog.RulesError, match="ZAM_1=UM/2015/1"):
            save(bad)
    saved = save("ZAM/7_2026=UR/2015/5;\nZAM/8_2026=UR/2015/6 z 2015-06-01;")
    assert saved["cl.ksef_contract"]["params"]["by_order"].startswith("ZAM/7_2026=")


def test_contract_override_lives_in_the_draft_and_survives_a_buyer_edit() -> None:
    invoice = _merged_invoice(
        lines=[{"name": "A", "order_key": "g1", "order_number": "ZAM/7_2026"}],
        client_order_number="ZAM/7_2026",
    )
    found = req.from_rules(_rules(**{"cl.ksef_contract": dict(_BY_ORDER)}), "2026-11")
    assert issue.resolve_contract(found, invoice).contract_number == "UR/2015/5"
    issue.set_contract(invoice, "  UR/2016/9 ", "2016-01-04")
    assert issue.contract_override(invoice) == ("UR/2016/9", date(2016, 1, 4))
    assert issue.resolve_contract(found, invoice).contract_number == "UR/2016/9"
    assert (
        issue.resolve_contract(found, invoice, override=False).contract_number
        == "UR/2015/5"
    )
    # Front odsyła nabywcę bez pól umowy — numer ze szkicu zostaje.
    invoice.buyer = issue.keep_contract(
        issue.clean_buyer({"name": "Bank 2"}, invoice.buyer), invoice.buyer
    )
    assert invoice.buyer["name"] == "Bank 2"
    assert issue.contract_override(invoice) == ("UR/2016/9", date(2016, 1, 4))
    issue.set_contract(invoice, "", None)
    assert issue.contract_override(invoice) is None
    assert "contract_number" not in invoice.buyer
    with pytest.raises(issue.IssueError, match="numeru umowy"):
        issue.set_contract(invoice, "", "2016-01-04")


def test_orders_together_split_by_contract() -> None:
    def row(group_id: int, number: str) -> billing.BillingRow:
        return billing.BillingRow(
            client_id=16,
            kind="md",
            group_id=group_id,
            order_id=None,
            order_number=number,
            currency="PLN",
            lines=(
                billing.BillingLine(
                    order_id=None,
                    consultant=f"Osoba {group_id}",
                    basis="md",
                    quantity=None,
                    unit_price=None,
                    net=None,
                    currency="PLN",
                ),
            ),
        )

    rows = {r.key: r for r in (row(1, "ZAM/1"), row(2, "ZAM/7_2026"), row(3, "ZAM/2"))}
    found = req.from_rules(
        _rules(**{"cl.ksef_contract": dict(_BY_ORDER), "cl.orders_together": {}}),
        "2026-11",
    )
    units = issue._units(  # noqa: SLF001
        list(rows),
        rows,
        split="order",
        settings=issue_settings.normalize({}),
        reqs={16: found},
        infos={},
        period="2026-11",
    )
    assert [[r.order_number for r in unit.rows] for unit in units] == [
        ["ZAM/1", "ZAM/2"],
        ["ZAM/7_2026"],
    ]
