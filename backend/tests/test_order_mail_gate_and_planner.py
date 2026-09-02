"""Bramka auto-zapisu i planer — czyste funkcje, tabela przypadków.

Kontrakt: automat tylko wtedy, gdy WSZYSTKIE warunki naraz; każdy brak daje
powód po polsku. Fixture'y syntetyczne; lata 2031+.
"""

from datetime import date
from decimal import Decimal

from app.services.order_mail_gate import (
    VERDICT_AUTO,
    VERDICT_REVIEW,
    GateInput,
    evaluate,
)
from app.services.order_mail_planner import (
    ACTION_FILL_DRAFT,
    ACTION_FUTURE,
    ACTION_GROUP,
    ACTION_NEW,
    ACTION_OVERLAP,
    ACTION_REVISION,
    ACTION_SKIP,
    ExistingOrder,
    plan_document,
    titles_collide,
)
from app.services.order_mail_resolver import (
    MATCH_AMBIGUOUS,
    MATCH_EXACT,
    MATCH_NONE,
    MATCH_RESCUED,
    ResolvedConsultant,
    RosterContract,
    RosterPerson,
    resolve_rows,
)
from app.services.order_pdf_parser import ConsultantOrderRow, OrderExtraction

TODAY = date(2031, 3, 3)


def _row(name, rate="900.00", unit="day", start="2031-04-01", end="2031-06-30"):
    return ConsultantOrderRow(
        consultant_name=name,
        rate_client=Decimal(rate),
        rate_unit=unit,
        start_date=start,
        end_date=end,
        uncertain=False,
    )


def _extraction(rows, title="7/2031", conf_title=1.0, source="claude", uncertain=False):
    ex = OrderExtraction(
        title=title,
        start_date="2031-04-01",
        end_date="2031-06-30",
        consultant_rows=rows,
        source=source,
        uncertain=uncertain,
    )
    ex.confidence["title"] = conf_title
    return ex


def _resolved(idx, name, kind=MATCH_EXACT, contract_id=10, live=(10,), status="active"):
    return ResolvedConsultant(
        row_index=idx,
        row_name=name,
        match_kind=kind,
        candidate_id=100 + idx,
        contract_id=contract_id,
        contract_status=status,
        candidate_ids=(100 + idx,),
        live_contract_ids=live,
        reason="Dopasowanie dokładne",
    )


# ── Resolver (część czysta) ──────────────────────────────────────────────────


class TestResolveRows:
    roster = [
        RosterPerson(1, "Jan", "Kowalski", (RosterContract(10, "active", None, None),)),
        RosterPerson(
            2, "Anna", "Nowak-Testowa", (RosterContract(11, "ending", None, None),)
        ),
        RosterPerson(
            3, "Jan", "Kowalczyk", (RosterContract(12, "active", None, None),)
        ),
        RosterPerson(
            4,
            "Piotr",
            "Dwa",
            (
                RosterContract(13, "active", None, None),
                RosterContract(14, "active", None, None),
            ),
        ),
        RosterPerson(
            5,
            "Ewa",
            "Stara",
            (RosterContract(15, "ended", date(2031, 1, 1), date(2031, 2, 1)),),
        ),
    ]

    def test_exact_is_order_and_diacritic_insensitive(self):
        r = resolve_rows(
            [_row("KOWALSKI Jan"), _row("Nowak Testowa Anna")], self.roster
        )
        assert [x.match_kind for x in r] == [MATCH_EXACT, MATCH_EXACT]
        assert [x.contract_id for x in r] == [10, 11]

    def test_typo_is_rescued_not_exact(self):
        r = resolve_rows([_row("Jan Kowalksi")], self.roster)  # transpozycja
        assert r[0].match_kind == MATCH_RESCUED and r[0].candidate_id == 1

    def test_unknown_and_ambiguous(self):
        r = resolve_rows([_row("Zenon Nieznany")], self.roster)
        assert r[0].match_kind == MATCH_NONE
        roster = self.roster + [
            RosterPerson(
                9, "Jan", "Kowalski", (RosterContract(19, "active", None, None),)
            )
        ]
        r = resolve_rows([_row("Jan Kowalski")], roster)
        assert r[0].match_kind == MATCH_AMBIGUOUS and r[0].candidate_ids == (1, 9)

    def test_two_live_contracts_is_not_auto_material(self):
        r = resolve_rows([_row("Piotr Dwa")], self.roster)
        assert r[0].match_kind == MATCH_EXACT
        assert r[0].contract_id is None and r[0].live_contract_ids == (13, 14)

    def test_ended_contract_still_names_the_person(self):
        r = resolve_rows([_row("Ewa Stara")], self.roster)
        assert r[0].contract_id == 15 and r[0].contract_status == "ended"
        assert r[0].has_single_live_contract is False


# ── Planer ───────────────────────────────────────────────────────────────────


class TestPlanner:
    def test_new_future_fill_draft(self):
        rows = [_row("A A"), _row("B B"), _row("C C")]
        resolved = [
            _resolved(0, "A A", contract_id=10),
            _resolved(1, "B B", contract_id=11, live=(11,)),
            _resolved(2, "C C", contract_id=12, live=(12,)),
        ]
        existing = {
            11: [
                ExistingOrder(
                    50, "active", "5/2030", date(2030, 10, 1), date(2031, 3, 31)
                )
            ],
            12: [ExistingOrder(60, "draft", "(bez numeru)", None, None)],
        }
        p = plan_document(
            client_id=1,
            extraction=_extraction(rows),
            resolved=resolved,
            existing_orders_by_contract=existing,
            is_group_client=False,
            today=TODAY,
        )
        assert [r.action for r in p.rows] == [
            ACTION_NEW,
            ACTION_FUTURE,
            ACTION_FILL_DRAFT,
        ]
        assert p.rows[2].target_order_id == 60
        assert p.auto_eligible_actions is True

    def test_revision_and_overlap_go_to_review(self):
        rows = [_row("A A"), _row("B B")]
        resolved = [
            _resolved(0, "A A", contract_id=10),
            _resolved(1, "B B", contract_id=11, live=(11,)),
        ]
        existing = {
            10: [
                ExistingOrder(
                    70, "active", "7/2031", date(2031, 1, 1), date(2031, 3, 31)
                )
            ],  # ten sam numer
            11: [
                ExistingOrder(
                    71, "active", "9/2030", date(2031, 1, 1), date(2031, 5, 31)
                )
            ],  # nachodzi
        }
        p = plan_document(
            client_id=1,
            extraction=_extraction(rows),
            resolved=resolved,
            existing_orders_by_contract=existing,
            is_group_client=False,
            today=TODAY,
        )
        assert [r.action for r in p.rows] == [ACTION_REVISION, ACTION_OVERLAP]
        assert p.auto_eligible_actions is False

    def test_bik_short_number_collides_with_long(self):
        assert titles_collide("4500030751", "30751") is True
        assert titles_collide("4500030751", "4500030752") is False
        assert titles_collide("OIT/0189/2031/ITVM", "OIT/0189/2031/ITVM") is True

    def test_group_client_and_unresolved_person(self):
        rows = [_row("A A"), _row("Nikt Nieznany")]
        resolved = [
            _resolved(0, "A A"),
            ResolvedConsultant(1, "Nikt Nieznany", MATCH_NONE, reason="Brak"),
        ]
        p = plan_document(
            client_id=1,
            extraction=_extraction(rows),
            resolved=resolved,
            existing_orders_by_contract={},
            is_group_client=True,
            today=TODAY,
        )
        assert [r.action for r in p.rows] == [ACTION_GROUP, ACTION_SKIP]


# ── Bramka ───────────────────────────────────────────────────────────────────


def _gate_input(**over):
    rows = [_row("Jan Kowalski")]
    resolved = (_resolved(0, "Jan Kowalski"),)
    ex = _extraction(rows)
    prop = plan_document(
        client_id=1,
        extraction=ex,
        resolved=list(resolved),
        existing_orders_by_contract={},
        is_group_client=False,
        today=TODAY,
    )
    base = dict(
        identification_method="registry_id",
        policies_applied=("PKO BP",),
        extraction=ex,
        document_truncated=False,
        ocr_capped=False,
        resolved=resolved,
        proposal=prop,
        deterministic_rows=tuple(rows),
        current_rates={10: (Decimal("850"), "day")},
        autoapply_enabled=True,
        excluded_client_ids=frozenset(),
    )
    base.update(over)
    return GateInput(**base)


class TestGate:
    def test_all_conditions_met_is_auto(self):
        v = evaluate(_gate_input())
        assert v.verdict == VERDICT_AUTO and v.reasons == []

    def test_each_condition_alone_blocks(self):
        cases = {
            "marker": dict(identification_method="marker"),
            "no_policy": dict(policies_applied=()),
            "regex": dict(
                extraction=_extraction([_row("Jan Kowalski")], source="regex")
            ),
            "rescued": dict(
                resolved=(_resolved(0, "Jan Kowalski", kind=MATCH_RESCUED),)
            ),
            "two_contracts": dict(
                resolved=(
                    _resolved(0, "Jan Kowalski", contract_id=None, live=(10, 11)),
                )
            ),
            "ended": dict(
                resolved=(_resolved(0, "Jan Kowalski", live=(), status="ended"),)
            ),
            "title_model": dict(
                extraction=_extraction([_row("Jan Kowalski")], conf_title=0.9)
            ),
            "no_det_rows": dict(deterministic_rows=()),
            "rate_mismatch": dict(
                deterministic_rows=(_row("Jan Kowalski", rate="950.00"),)
            ),
            "truncated": dict(document_truncated=True),
            "ocr": dict(ocr_capped=True),
            "band": dict(
                extraction=_extraction([_row("Jan Kowalski", rate="9000")]),
                deterministic_rows=(_row("Jan Kowalski", rate="9000"),),
            ),
            "deviation": dict(current_rates={10: (Decimal("500"), "day")}),
            "excluded": dict(excluded_client_ids=frozenset({1})),
            "uncertain": dict(
                extraction=_extraction([_row("Jan Kowalski")], uncertain=True)
            ),
        }
        for name, over in cases.items():
            inp = _gate_input(**over)
            if "extraction" in over:
                # planer musi zobaczyć tę samą ekstrakcję
                inp = GateInput(
                    **{
                        **inp.__dict__,
                        "proposal": plan_document(
                            client_id=1,
                            extraction=over["extraction"],
                            resolved=list(inp.resolved),
                            existing_orders_by_contract={},
                            is_group_client=False,
                            today=TODAY,
                        ),
                    }
                )
            v = evaluate(inp)
            assert v.verdict == VERDICT_REVIEW, name
            assert v.reasons, name

    def test_document_level_atomicity_one_bad_row_blocks_all(self):
        rows = [_row("Jan Kowalski"), _row("Nikt Nieznany")]
        resolved = (
            _resolved(0, "Jan Kowalski"),
            ResolvedConsultant(
                1, "Nikt Nieznany", MATCH_NONE, reason="Brak takiej osoby"
            ),
        )
        ex = _extraction(rows)
        prop = plan_document(
            client_id=1,
            extraction=ex,
            resolved=list(resolved),
            existing_orders_by_contract={},
            is_group_client=False,
            today=TODAY,
        )
        v = evaluate(
            _gate_input(
                extraction=ex,
                resolved=resolved,
                proposal=prop,
                deterministic_rows=tuple(rows),
            )
        )
        assert v.verdict == VERDICT_REVIEW
        assert any("Nikt Nieznany" in r for r in v.reasons)

    def test_missing_end_date_blocks(self):
        rows = [_row("Jan Kowalski", end=None)]
        ex = _extraction(rows)
        ex.end_date = None
        prop = plan_document(
            client_id=1,
            extraction=ex,
            resolved=[_resolved(0, "Jan Kowalski")],
            existing_orders_by_contract={},
            is_group_client=False,
            today=TODAY,
        )
        v = evaluate(
            _gate_input(extraction=ex, proposal=prop, deterministic_rows=tuple(rows))
        )
        assert v.verdict == VERDICT_REVIEW and any(
            "okres niepełny" in r for r in v.reasons
        )

    def test_shadow_mode_still_reports_auto_verdict(self):
        v = evaluate(_gate_input(autoapply_enabled=False))
        assert v.verdict == VERDICT_AUTO
