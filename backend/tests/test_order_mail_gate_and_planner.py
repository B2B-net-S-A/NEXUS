"""Bramka auto-zapisu i planer — czyste funkcje, tabela przypadków.

Kontrakt: automat tylko wtedy, gdy WSZYSTKIE warunki naraz; każdy brak daje
powód po polsku. Fixture'y syntetyczne; lata 2031+.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.services.order_mail_gate import (
    VERDICT_AUTO,
    VERDICT_REVIEW,
    GateInput,
    evaluate,
)
from app.services.order_mail_planner import (
    ACTION_DECIDE_PERSON,
    ACTION_FILL_DRAFT,
    ACTION_FUTURE,
    ACTION_NEW,
    ACTION_NEW_DRAFT,
    ACTION_OVERLAP,
    ACTION_REVISION,
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

    def test_single_char_surname_typo_is_rescued(self):
        """Zgłoszenie: „drobna różnica w zapisie nazwiska" — literówka, nie tylko
        transpozycja. Substytucja/usunięcie też ma trafiać do kolejki, nie w
        „Brak takiej osoby". Ścieżka poczty (człowiek potwierdza)."""
        r = resolve_rows([_row("Jan Kowarski")], self.roster)  # kowalski→kowarski
        assert r[0].match_kind == MATCH_RESCUED and r[0].candidate_id == 1

    def test_reported_erste_consultant_matches_despite_diacritics_and_typo(self):
        roster = [
            RosterPerson(
                7,
                "Marcin",
                "Żółtaniecki",
                (RosterContract(70, "active", None, None),),
            )
        ]
        exact = resolve_rows([_row("Marcin Żółtaniecki")], roster)
        assert exact[0].match_kind == MATCH_EXACT and exact[0].contract_id == 70
        # Zapis bez diakrytyków (częsty w importach) — nadal EXACT (zwijanie).
        folded = resolve_rows([_row("Marcin Zoltaniecki")], roster)
        assert folded[0].match_kind == MATCH_EXACT
        # Drobna literówka (usunięcie znaku) — RESCUED do kolejki, nie MATCH_NONE.
        typo = resolve_rows([_row("Marcin Żółtanicki")], roster)
        assert typo[0].match_kind == MATCH_RESCUED and typo[0].candidate_id == 7

    def test_two_people_within_typo_distance_are_ambiguous(self):
        roster = self.roster + [
            RosterPerson(
                8, "Jan", "Kowalsci", (RosterContract(20, "active", None, None),)
            )
        ]
        # „Kowalski" jest o jedną edycję od „Kowalski"(id1) i „Kowalsci"(id8).
        r = resolve_rows([_row("Jan Kowalsii")], roster)
        assert r[0].match_kind == MATCH_AMBIGUOUS
        assert set(r[0].candidate_ids) == {1, 8}

    def test_far_name_still_unmatched(self):
        r = resolve_rows([_row("Zenon Zupełnie Inny")], self.roster)
        assert r[0].match_kind == MATCH_NONE

    @pytest.mark.parametrize(
        "name",
        [
            "Konrad Korcz",
            "Konrada Korcza",
            "Konradowi Korczowi",
            "Konradem Korczem",
            "Korcza Konrada",
            "Konard Korcz",
            "Konrad Krcz",
            "Konrada Korzca",
        ],
    )
    def test_pfron_name_forms_are_included_in_plan(self, name):
        roster = [
            RosterPerson(
                7, "Konrad", "Korcz", (RosterContract(70, "active", None, None),)
            )
        ]
        rows = [_row(name)]
        resolved = resolve_rows(rows, roster)
        proposal = plan_document(
            client_id=1,
            extraction=_extraction(rows),
            resolved=resolved,
            existing_orders_by_contract={},
            is_group_client=False,
            today=TODAY,
        )
        assert resolved[0].candidate_id == 7
        assert proposal.rows[0].contract_id == 70
        assert proposal.rows[0].action == ACTION_NEW

    def test_inflected_first_and_last_name(self):
        resolved = resolve_rows([_row("Jana Kowalskiego")], self.roster)
        assert resolved[0].match_kind == MATCH_RESCUED
        assert resolved[0].candidate_id == 1

    def test_short_surname_typo_requires_remaining_name_to_match(self):
        roster = [RosterPerson(7, "Konrad", "Korcz", ())]
        for name in ("Robert Korcz", "Konard Krcz", "Konrad Nowak"):
            resolved = resolve_rows([_row(name)], roster)
            assert resolved[0].match_kind == MATCH_NONE
            assert (
                resolved[0].reason
                == "Brak takiej osoby wśród konsultantów tego klienta"
            )

    def test_inflection_collision_requires_manual_choice(self):
        roster = [
            RosterPerson(7, "Konrad", "Korcz", ()),
            RosterPerson(8, "Konrad", "Korcza", ()),
        ]
        resolved = resolve_rows([_row("Konrada Korcza")], roster)
        assert resolved[0].match_kind == MATCH_AMBIGUOUS
        assert resolved[0].candidate_ids == (7, 8)


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

    @pytest.mark.parametrize(
        "a,b,expected",
        [
            # Ten sam numer — musi się zgadzać.
            ("4500030751", "30751", True),
            ("SAP 4500030751", "4500030751", True),
            ("Zamówienie nr 4500030751", "30751", True),
            ("4500 030 751", "4500030751", True),
            ("830/2031", "830/2031", True),
            ("oit / 0189/2031/itvm", "OIT/0189/2031/ITVM", True),
            ("22", "Zlecenie nr 22", True),
            # Różne numery — nie mogą się zgadzać (audyt 25.09.2026): końcówka
            # cyfr wyciągniętych z numeru ze strukturą łączyła cudze zamówienia.
            ("830/2031", "1830/2031", False),
            ("4/2031", "34/2031", False),
            ("3/07/2031/BL", "13/07/2031/BL", False),
            ("ABC/12345", "12345", False),
            ("4500030751", "4500030752", False),
            ("1234", "11234", False),
            ("", "12345", False),
        ],
    )
    def test_titles_collide_table(self, a, b, expected):
        assert titles_collide(a, b) is expected
        assert titles_collide(b, a) is expected

    def test_md_group_line_draft_is_never_filled_as_periodic_order(self):
        """Szkic linii zamówienia MD/kosztowego ma własny cykl życia (budżet,
        zamiana kontraktora). Wypełniony jak zamówienie okresowe dostawał
        numer, okres i stawkę z PDF-a automatem (audyt 25.09.2026) — teraz
        idzie do człowieka (``ACTION_GROUP``), także przy tym samym numerze."""
        from app.services.order_mail_planner import ACTION_GROUP

        for title in ("7/2031", "445"):
            p = plan_document(
                client_id=1,
                extraction=_extraction([_row("A A")]),
                resolved=[_resolved(0, "A A", contract_id=10)],
                existing_orders_by_contract={
                    10: [
                        ExistingOrder(
                            80,
                            "draft",
                            title,
                            date(2031, 4, 1),
                            None,
                            order_group_id=77,
                        )
                    ]
                },
                is_group_client=True,
                today=TODAY,
            )
            assert p.rows[0].action == ACTION_GROUP, title
            assert p.rows[0].target_order_id is None
            assert p.auto_eligible_actions is False

    def test_group_client_and_unresolved_person(self):
        """Zamówienie MD: osoba nieznaleziona czeka na decyzję DL (ticket 09.2026).

        Do 09.2026 automat zakładał jej po cichu nowego kandydata i szkic
        kontraktu. Na zamówieniu MD/kosztowym to decyzja Delivery Leada —
        zostaw / zastąp / usuń — w oknie zamówienia (patrz
        ``test_inactive_consultant_all_paths``). Okresowe zostaje przy szkicu.
        """
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
        assert [r.action for r in p.rows] == [ACTION_NEW, ACTION_DECIDE_PERSON]
        periodic = plan_document(
            client_id=1,
            extraction=_extraction(rows),
            resolved=resolved,
            existing_orders_by_contract={},
            is_group_client=True,
            today=TODAY,
            order_type="periodic",
        )
        assert [r.action for r in periodic.rows] == [ACTION_NEW, ACTION_NEW_DRAFT]


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
                1, "Nikt Nieznany", MATCH_AMBIGUOUS, reason="Pasują dwie osoby"
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

    def test_open_ended_policy_accepts_missing_end_date(self):
        """BIK: „bezterminowo" z reguły klienta nie jest niepełnym okresem."""
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
            _gate_input(
                extraction=ex,
                proposal=prop,
                deterministic_rows=tuple(rows),
                policies_applied=("BIK",),
                open_ended_period=True,
            )
        )
        assert v.verdict == VERDICT_AUTO, v.reasons

    def test_open_ended_policy_still_requires_start_date(self):
        rows = [_row("Jan Kowalski", start=None, end=None)]
        ex = _extraction(rows)
        ex.start_date = None
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
            _gate_input(
                extraction=ex,
                proposal=prop,
                deterministic_rows=tuple(rows),
                open_ended_period=True,
            )
        )
        assert v.verdict == VERDICT_REVIEW

    def test_bik_row_without_readable_name_goes_to_review(self):
        """Pozycja BIK bez imienia i nazwiska nie może zostać zapisana automatem."""
        from app.services.order_policies import (
            PolicyContext,
            apply_policies,
            policy_by_key,
        )
        from tests.test_bik_order_policy import SPACED

        text = SPACED.replace("Profil UR - Piotr Łęcki", "Profil UR - 12345")
        ex, _ = apply_policies(
            OrderExtraction(source="claude"),
            PolicyContext(document_text=text),
            [policy_by_key("bik")],
        )
        resolved = [
            _resolved(0, "Krystian Sowiński"),
            _resolved(1, "", kind="none", contract_id=None, live=()),
        ]
        prop = plan_document(
            client_id=1,
            extraction=ex,
            resolved=resolved,
            existing_orders_by_contract={},
            is_group_client=True,
            today=TODAY,
        )
        v = evaluate(
            _gate_input(
                extraction=ex,
                proposal=prop,
                resolved=tuple(resolved),
                deterministic_rows=tuple(policy_by_key("bik").extract_rows(text)),
                policies_applied=("BIK",),
                open_ended_period=True,
                current_rates={},
            )
        )
        assert v.verdict == VERDICT_REVIEW
        assert any("Pozycja 20" in r for r in v.reasons)

    def test_shadow_mode_still_reports_auto_verdict(self):
        v = evaluate(_gate_input(autoapply_enabled=False))
        assert v.verdict == VERDICT_AUTO


@pytest.mark.parametrize(
    "reason",
    [
        "Total, excl. VAT 211 120,00 PLN podano jako suma zamówienia, ale nie jest jednoznacznie oznaczone jako total_value pola dokumentu (brak jasnego nagłówka 'Total value of order')",
        "Total_value pole 'Total, excl. VAT 72 960,00 PLN' istnieje w dokumencie, ale nie jest przypisane jednoznacznie jako 'total_value' pola zamówienia",
    ],
)
def test_unused_total_mapping_does_not_block_complete_periodic_order(reason):
    inp = _gate_input()
    inp.extraction.uncertain = True
    inp.extraction.uncertain_reasons = [reason]
    inp.extraction.total_value = None
    assert evaluate(inp).is_auto
    inp.proposal.rows[0].order_type = "cost"
    assert not evaluate(inp).is_auto
    inp.proposal.rows[0].order_type = "periodic"
    inp.extraction.total_value = Decimal("100")
    assert not evaluate(inp).is_auto
    inp.extraction.total_value = None
    inp.extraction.uncertain_reasons = [reason + "; sprzeczne stawki"]
    assert not evaluate(inp).is_auto


# ── Kody powodów (0316) ─────────────────────────────────────────────────────


def test_every_reason_the_gate_appends_carries_a_code():
    """Powód bez kodu byłby dla ponownej weryfikacji „inny powód" — czyli alarm.

    Test czyta ŹRÓDŁO bramki, nie jeden przykładowy werdykt: ręczna lista
    scenariuszy przepuściłaby powód dopisany jutro w gałęzi, o której nikt nie
    pomyślał, a skutkiem byłaby karta do Delivery Leada o zamówieniu, które
    tylko czeka na podpis umowy.
    """
    import ast
    import inspect

    from app.services import order_mail_gate

    tree = ast.parse(inspect.getsource(order_mail_gate))
    offenders: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if not (
            isinstance(node.func.value, ast.Name)
            and node.func.value.id == "reasons"
            and node.func.attr in ("append", "extend")
        ):
            continue
        arg = node.args[0]
        if node.func.attr == "append":
            ok = isinstance(arg, ast.Tuple) and len(arg.elts) == 2
        else:
            # `extend` bierze generator par albo JEDEN znany helper zwracający
            # pary. Gołe „dowolne wywołanie" przepuszczałoby dokładnie to,
            # przed czym ten test broni: helper oddający same napisy.
            ok = isinstance(arg, ast.GeneratorExp) and isinstance(arg.elt, ast.Tuple)
            ok = ok or (
                isinstance(arg, ast.Call)
                and isinstance(arg.func, ast.Name)
                and arg.func.id == "_row_evidence_reasons"
            )
        if not ok:
            offenders.append(node.lineno)
    assert offenders == [], f"powody bez kodu w order_mail_gate.py, linie: {offenders}"


def test_verdict_codes_line_up_with_their_reasons():
    clean = evaluate(_gate_input())
    assert (clean.reasons, clean.codes) == ([], [])
    dirty = evaluate(
        _gate_input(
            identification_method="marker",
            policies_applied=(),
            document_truncated=True,
            ocr_capped=True,
            deterministic_rows=(),
        )
    )
    assert dirty.verdict == VERDICT_REVIEW
    assert len(dirty.codes) == len(dirty.reasons) > 1
    assert all(dirty.codes)


# ── Audyt 22.09, druga runda (FIN-MAIL-01..07) ───────────────────────────────


def _plan(ex, resolved, **kw):
    return plan_document(
        client_id=1,
        extraction=ex,
        resolved=list(resolved),
        existing_orders_by_contract=kw.pop("existing", {}),
        is_group_client=False,
        today=TODAY,
        **kw,
    )


def test_document_total_is_copied_only_onto_a_single_person_order():
    """FIN-MAIL-01: wartość całego PDF-a nie ląduje na zamówieniu każdej osoby."""
    two = _extraction([_row("Jan Kowalski"), _row("Anna Nowak")])
    two.total_value = Decimal("120000")
    prop = _plan(
        two,
        (
            _resolved(0, "Jan Kowalski"),
            _resolved(1, "Anna Nowak", contract_id=11, live=(11,)),
        ),
    )
    assert [r.total_value for r in prop.rows] == [None, None]
    one = _extraction([_row("Jan Kowalski")])
    one.total_value = Decimal("60000")
    assert _plan(one, (_resolved(0, "Jan Kowalski"),)).rows[0].total_value == "60000"


def test_foreign_currency_goes_to_the_queue_and_travels_with_the_row():
    """FIN-MAIL-02: 110 EUR nie może zapisać się automatem jako 110 PLN."""
    from app.services.order_mail_gate import CODE_CURRENCY_FOREIGN

    ex = _extraction([_row("Jan Kowalski")])
    ex.currency = "eur"
    prop = _plan(ex, (_resolved(0, "Jan Kowalski"),))
    assert prop.rows[0].currency == "EUR"
    verdict = evaluate(_gate_input(extraction=ex, proposal=prop))
    assert verdict.verdict == VERDICT_REVIEW
    assert CODE_CURRENCY_FOREIGN in verdict.codes
    pln = _extraction([_row("Jan Kowalski")])
    pln.currency = "PLN"
    prop_pln = _plan(pln, (_resolved(0, "Jan Kowalski"),))
    assert evaluate(_gate_input(extraction=pln, proposal=prop_pln)).is_auto


def test_document_period_wins_over_the_model_row_period_for_ruled_clients():
    """FIN-MAIL-03: u klienta z okresem z reguły plan bierze okres dokumentu."""
    row = _row("Jan Kowalski", start="2031-05-05", end="2031-12-31")
    ex = _extraction([row])
    ex.end_date = None  # BIK: bezterminowo z reguły
    ruled = _plan(
        ex, (_resolved(0, "Jan Kowalski"),), document_period_authoritative=True
    )
    assert (ruled.rows[0].start_date, ruled.rows[0].end_date) == ("2031-04-01", None)
    plain = _plan(ex, (_resolved(0, "Jan Kowalski"),))
    assert (plain.rows[0].start_date, plain.rows[0].end_date) == (
        "2031-05-05",
        "2031-12-31",
    )


def test_gate_requires_the_ruled_period_and_matching_row_evidence():
    from app.services.order_mail_gate import CODE_ROW_EVIDENCE_PERIOD

    ex = _extraction([_row("Jan Kowalski")])
    prop = _plan(ex, (_resolved(0, "Jan Kowalski"),))
    # Okres od modelu (bez potwierdzenia regułą) u klienta z okresem z reguły.
    ex.confidence.update({"start_date": 0.99, "end_date": 0.99})
    held = evaluate(
        _gate_input(extraction=ex, proposal=prop, document_period_authoritative=True)
    )
    assert CODE_ROW_EVIDENCE_PERIOD in held.codes
    ex.confidence.update({"start_date": 1.0, "end_date": 1.0})
    assert evaluate(
        _gate_input(extraction=ex, proposal=prop, document_period_authoritative=True)
    ).is_auto
    # Wiersz z tabeli PDF ma inny okres niż plan.
    other = _row("Jan Kowalski", start="2031-04-01", end="2031-09-30")
    mismatch = evaluate(
        _gate_input(extraction=ex, proposal=prop, deterministic_rows=(other,))
    )
    assert CODE_ROW_EVIDENCE_PERIOD in mismatch.codes


def test_model_cannot_claim_rule_confidence():
    """FIN-MAIL-04: 1.0 od modelu nie udaje potwierdzenia regułą."""
    from app.services.order_pdf_parser import _normalize

    ex = _normalize(
        {
            "title": "7/2031",
            "start_date": "2031-04-01",
            "_confidence": {"title": 1.0, "start_date": 0.4},
        },
        source="claude",
    )
    assert ex.confidence["title"] < 1.0
    assert ex.confidence["start_date"] == 0.4


def test_return_after_break_with_a_namesake_is_not_automatic():
    """FIN-MAIL-07: powrót rozpoznany po nazwisku przy imienniku → kolejka."""
    from app.services.order_mail_gate import CODE_ACTION_NOT_AUTO
    from app.services.order_mail_planner import ACTION_REACTIVATE
    from app.services.order_mail_resolver import PersonElsewhere, annotate_namesakes

    resolved = annotate_namesakes(
        [_resolved(0, "Jan Kowalski", status="ended")],
        {
            "Jan Kowalski": (
                PersonElsewhere(candidate_id=100, full_name="Jan Kowalski"),
                PersonElsewhere(candidate_id=555, full_name="Jan Kowalski"),
            )
        },
    )
    assert resolved[0].namesake_ids == (555,)
    existing = {
        10: [
            ExistingOrder(1, "completed", "OLD/1", date(2030, 1, 1), date(2031, 2, 28))
        ]
    }
    ex = _extraction([_row("Jan Kowalski")])
    prop = _plan(ex, resolved, existing=existing)
    assert prop.rows[0].action == ACTION_REACTIVATE
    assert prop.rows[0].existing_person_ids == [555]
    verdict = evaluate(
        _gate_input(extraction=ex, proposal=prop, resolved=tuple(resolved))
    )
    assert verdict.verdict == VERDICT_REVIEW and CODE_ACTION_NOT_AUTO in verdict.codes
    # Bez imiennika powrót zostaje automatyczny (decyzja 10.09.2026).
    plain = _plan(ex, [_resolved(0, "Jan Kowalski", status="ended")], existing=existing)
    assert evaluate(_gate_input(extraction=ex, proposal=plain)).is_auto


def test_queue_redacts_amounts_and_other_clients_for_roles_without_finance():
    """FIN-MAIL-06: kwoty wierszy i nazwy innych klientów poza rolami z finansami."""
    from app.api.order_mail_queue import _redact_proposal

    proposal = {
        "blocking": [],
        "rows": [
            {
                "row_name": "Jan Kowalski",
                "rate_client": "900",
                "total_value": "50000",
                "currency": "PLN",
                "existing_person_ids": [7],
                "reasons": [
                    "„Jan Kowalski”: „Jan Kowalski” (#7) ma kontrakt #3 u klienta "
                    "„Bank Inny”. Sprawdź"
                ],
            }
        ],
        "resolved": [{"reason": "ma kontrakt #3 u klienta „Bank Inny”"}],
    }
    dl = _redact_proposal(proposal, show_finance=True, hide_other_clients=True)
    assert dl["rows"][0]["rate_client"] == "900"  # przypisany DL widzi kwoty
    assert "Bank Inny" not in str(dl)
    assert dl["rows"][0]["existing_person_ids"] == [7]
    tcm = _redact_proposal(
        proposal, show_finance=False, read_only_tcm=True, hide_other_clients=True
    )
    row = tcm["rows"][0]
    assert (row["rate_client"], row["total_value"], row["currency"]) == (None,) * 3
    assert row["existing_person_ids"] == [] and "Bank Inny" not in str(tcm)
    admin = _redact_proposal(proposal, show_finance=True)
    assert admin is proposal


# ── Audyt 24.09, blok B (poczta zamówień) ────────────────────────────────────


def _two_people(ex_rows):
    return (
        _resolved(0, ex_rows[0].consultant_name),
        _resolved(1, ex_rows[1].consultant_name, contract_id=11, live=(11,)),
    )


def test_several_people_do_not_inherit_the_document_md_pool_or_rate():
    """W1: „60 MD na zamówienie" przy 3 osobach nie jest 60 MD każdej z nich.

    Ręczne „Zastosuj" nie czyta bramki — plan był jedynym zabezpieczeniem, a
    kopiował liczbę MD i stawkę z nagłówka na każdą osobę bez własnych.
    """
    rows = [_row("Jan Kowalski"), _row("Anna Nowak")]
    rows[1].rate_client = None
    rows[1].rate_unit = None
    ex = _extraction(rows)
    ex.md_total = Decimal("60")
    ex.rate_client = Decimal("1000.00")
    ex.rate_unit = "day"
    prop = _plan(ex, _two_people(rows), order_type="md")
    assert [r.md_total for r in prop.rows] == [None, None]
    assert (prop.rows[0].rate_client, prop.rows[0].rate_unit) == ("900.00", "day")
    assert (prop.rows[1].rate_client, prop.rows[1].rate_unit) == (None, None)

    # Dokument jednoosobowy: liczba MD i stawka dokumentu SĄ tej osoby.
    one = _row("Jan Kowalski")
    one.rate_client = None
    one.rate_unit = None
    single = _extraction([one])
    single.md_total = Decimal("60")
    single.rate_client = Decimal("1000.00")
    single.rate_unit = "day"
    row = _plan(single, (_resolved(0, "Jan Kowalski"),), order_type="md").rows[0]
    assert (row.md_total, row.rate_client, row.rate_unit) == ("60", "1000.00", "day")


def test_shared_md_pool_is_one_reason_not_a_missing_md_per_person():
    """W1: wspólna pula to jeden powód „wspólny budżet”, nie „brak MD” u osób."""
    from app.services.order_mail_gate import CODE_MD_MISSING, CODE_MD_SHARED_POOL

    rows = [_row("Jan Kowalski"), _row("Anna Nowak")]
    ex = _extraction(rows, uncertain=True)
    ex.uncertain_reasons = ["Brak liczby MD przy konsultantach"]
    ex.md_total = Decimal("60")
    resolved = _two_people(rows)
    prop = _plan(ex, resolved, order_type="md")
    verdict = evaluate(
        _gate_input(
            extraction=ex,
            proposal=prop,
            resolved=resolved,
            deterministic_rows=tuple(rows),
            current_rates={},
        )
    )
    assert verdict.verdict == VERDICT_REVIEW
    assert CODE_MD_SHARED_POOL in verdict.codes
    assert CODE_MD_MISSING not in verdict.codes
    assert not any("Odczyt niepewny: Brak liczby MD" in r for r in verdict.reasons)


def test_row_rate_keeps_its_own_unit_not_the_converted_document_unit():
    """W3: stawka wiersza w MD nie dostaje jednostki godzinowej dokumentu.

    Bank Pocztowy przelicza stawkę DOKUMENTU (1200 zł/MD → 150 zł/h). Wiersz
    osoby z 1200 bez jednostki brał jednostkę dokumentu i zapisywał się jako
    1200 zł/h.
    """
    row = _row("Jan Kowalski", rate="1200.00", unit=None)
    ex = _extraction([row])
    ex.rate_client = Decimal("150.00")
    ex.rate_client_md = Decimal("1200.00")
    ex.rate_unit = "hour"
    planned = _plan(ex, (_resolved(0, "Jan Kowalski"),)).rows[0]
    assert (planned.rate_client, planned.rate_unit) == ("1200.00", None)
    # Ta sama kwota w wierszu i w dokumencie — jednostka dokumentu jej dotyczy.
    same = _extraction([_row("Jan Kowalski", rate="150.00", unit=None)])
    same.rate_client = Decimal("150.00")
    same.rate_unit = "hour"
    planned = _plan(same, (_resolved(0, "Jan Kowalski"),)).rows[0]
    assert (planned.rate_client, planned.rate_unit) == ("150.00", "hour")


def test_gross_document_total_is_not_carried_onto_the_order():
    """S1: stawka przeszła ÷ 1,23, wartość całkowita nie — nie przenosimy jej."""
    row = _row("Jan Kowalski", rate="1160.00")
    row.rate_client_gross = Decimal("1426.80")
    ex = _extraction([row])
    ex.rate_client = Decimal("1160.00")
    ex.rate_client_gross = Decimal("1426.80")
    ex.total_value = Decimal("32816.40")
    assert _plan(ex, (_resolved(0, "Jan Kowalski"),)).rows[0].total_value is None
    net = _extraction([_row("Jan Kowalski")])
    net.total_value = Decimal("60000")
    assert _plan(net, (_resolved(0, "Jan Kowalski"),)).rows[0].total_value == "60000"


def test_two_positions_of_one_person_wait_for_a_human():
    """W2: on-site 150 i off-site 130 tej samej osoby — nigdy dwa „nowe” automatem.

    Zabezpieczenie w zapisie trafiało przy drugiej pozycji w zamówienie
    pierwszej, więc druga przepadała, a dokument szedł jako zapisany.
    """
    from app.services.order_mail_gate import CODE_ACTION_NOT_AUTO
    from app.services.order_mail_planner import ACTION_SKIP, REPEATED_PERSON_REASON

    rows = [
        _row("Jan Kowalski", rate="150.00", unit="hour"),
        _row("Kowalski Jan", rate="130.00", unit="hour"),
        _row("Anna Nowak", rate="140.00", unit="hour"),
    ]
    resolved = (
        _resolved(0, "Jan Kowalski"),
        _resolved(1, "Kowalski Jan"),
        _resolved(2, "Anna Nowak", contract_id=11, live=(11,)),
    )
    prop = _plan(_extraction(rows), resolved)
    assert [r.action for r in prop.rows] == [ACTION_SKIP, ACTION_SKIP, ACTION_NEW]
    assert all(REPEATED_PERSON_REASON in r.reasons for r in prop.rows[:2])
    assert REPEATED_PERSON_REASON not in prop.rows[2].reasons
    assert prop.auto_eligible_actions is False
    verdict = evaluate(
        _gate_input(
            extraction=_extraction(rows),
            proposal=prop,
            resolved=resolved,
            deterministic_rows=tuple(rows),
            current_rates={},
        )
    )
    assert verdict.verdict == VERDICT_REVIEW
    assert CODE_ACTION_NOT_AUTO in verdict.codes


def test_two_positions_of_one_new_person_are_also_held():
    """W2: osoba spoza rostera (bez kontraktu) — to samo imię i nazwisko."""
    from app.services.order_mail_planner import ACTION_SKIP

    rows = [_row("Zenon Nowy", rate="150.00"), _row("Zenon Nowy", rate="130.00")]
    resolved = (
        ResolvedConsultant(0, "Zenon Nowy", MATCH_NONE, reason="Brak w rosterze"),
        ResolvedConsultant(1, "Zenon Nowy", MATCH_NONE, reason="Brak w rosterze"),
    )
    prop = _plan(_extraction(rows), resolved)
    assert [r.action for r in prop.rows] == [ACTION_SKIP, ACTION_SKIP]


def test_cost_order_for_several_people_goes_to_the_queue():
    """S3: wspólna kwota zlecenia kosztowego nie ma gdzie trafić przy zapisie
    per osoba — dokument szedł jako „zapisany automatycznie" z samymi szkicami."""
    from app.services.order_mail_gate import CODE_COST_SHARED_BUDGET

    rows = [_row("Jan Kowalski"), _row("Anna Nowak")]
    ex = _extraction(rows)
    ex.total_value = Decimal("250000")
    resolved = _two_people(rows)
    prop = _plan(ex, resolved, order_type="cost")
    verdict = evaluate(
        _gate_input(
            extraction=ex,
            proposal=prop,
            resolved=resolved,
            deterministic_rows=tuple(rows),
            current_rates={},
        )
    )
    assert verdict.verdict == VERDICT_REVIEW
    assert CODE_COST_SHARED_BUDGET in verdict.codes
    one = _extraction([_row("Jan Kowalski")])
    single = _plan(one, (_resolved(0, "Jan Kowalski"),), order_type="cost")
    assert (
        CODE_COST_SHARED_BUDGET
        not in evaluate(_gate_input(extraction=one, proposal=single)).codes
    )
