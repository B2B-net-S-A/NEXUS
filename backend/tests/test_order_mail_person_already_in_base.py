"""Zamówienie z maila dla osoby, której nie ma w rosterze klienta.

Zgłoszenie 09.2026 (PKO BP, zamówienie 1893/2026, Piotr Michałowski):
dokument rozpoznał klienta po NIP-ie na ZDUBLOWANYM rekordzie (0 kontraktów),
więc roster był pusty, osoba wyszła jako „nowy kontraktor", a automat
zatrzymał się dopiero w writerze na przypadkowej przeszkodzie („kilka osób
o tym imieniu i nazwisku w bazie"). Zamówienie z unikalnym nazwiskiem
zapisałoby się automatem pod złym klientem.

Trzy rzeczy pilnowane tutaj:

1. osoba jednoznacznie obecna U TEGO klienta nie trafia do „nowego
   kontraktora" — dopasowuje się do jej kontraktu (kryterium regresyjne);
2. kilku różnych imienników U TEGO SAMEGO klienta nadal wymaga ręcznego
   wyboru — automat nie chowa problemu pod dopasowanie;
3. osoba spoza rostera, ale obecna w bazie, zatrzymuje automat i niesie
   konkretną podpowiedź zamiast domyślnego „Nowy kontraktor";
4. osoba spoza rostera i spoza bazy też zatrzymuje automat — zgłoszenie
   09.2026 (Nordea, umowa 1506/2026): PO od klienta przyszło przed podpisem
   umowy B2B i automat założył kandydata, szkic kontraktu i zamówienie.
   Wstrzymanie jest CZEKANIEM: gdy kontrakt powstanie z „podpisana
   obustronnie", ten sam dokument jedzie automatem.

Fixture'y syntetyczne; lata 2031+.
"""

from datetime import date
from decimal import Decimal

from app.services.order_mail_gate import (
    CODE_PERSON_DECISION_NEW,
    CODE_PERSON_NEW_TO_SYSTEM,
    VERDICT_AUTO,
    VERDICT_REVIEW,
    GateInput,
    evaluate,
)
from app.services.order_mail_recheck_reasons import (
    CATEGORY_AWAITING_CONTRACT,
    classify_hold,
)
from app.services.order_mail_planner import (
    ACTION_DECIDE_PERSON,
    ACTION_NEW,
    ACTION_NEW_DRAFT,
    plan_document,
)
from app.services.order_mail_resolver import (
    MATCH_AMBIGUOUS,
    MATCH_EXACT,
    MATCH_NONE,
    PersonElsewhere,
    RosterContract,
    RosterPerson,
    annotate_known_elsewhere,
    known_elsewhere_reason,
    resolve_rows,
)
from app.services.order_pdf_parser import ConsultantOrderRow, OrderExtraction

TODAY = date(2031, 9, 16)
DOCUMENT_NAME = "Piotr Michałowski"
#: Klient, którego rekord niesie kontrakty; „drugi rekord" to jego duplikat.
CLIENT_WITH_CONTRACTS = 26


def _row(name=DOCUMENT_NAME, start="2031-10-01", end="2031-12-31", md=None):
    return ConsultantOrderRow(
        consultant_name=name,
        rate_client=Decimal("1240.00"),
        rate_unit="day",
        md_total=md,
        start_date=start,
        end_date=end,
        uncertain=False,
    )


def _extraction(rows, title="1893/2031"):
    ex = OrderExtraction(
        title=title,
        start_date="2031-10-01",
        end_date="2031-12-31",
        consultant_rows=rows,
        source="claude",
        uncertain=False,
    )
    ex.confidence["title"] = 1.0
    return ex


def _plan(rows, resolved, *, client_id=CLIENT_WITH_CONTRACTS, existing=None):
    return plan_document(
        client_id=client_id,
        extraction=_extraction(rows),
        resolved=resolved,
        existing_orders_by_contract=existing or {},
        is_group_client=False,
        today=TODAY,
    )


def _gate(rows, resolved, proposal):
    return evaluate(
        GateInput(
            identification_method="registry_id",
            policies_applied=("PKO BP",),
            extraction=_extraction(rows),
            document_truncated=False,
            ocr_capped=False,
            resolved=tuple(resolved),
            proposal=proposal,
            deterministic_rows=tuple(rows),
            current_rates={},
            autoapply_enabled=True,
        )
    )


# ── 1) osoba jednoznacznie obecna u klienta ─────────────────────────────────


def test_person_on_the_client_roster_is_matched_not_offered_as_new_contractor():
    """Kryterium regresyjne: kontrakt #456 u tego klienta = dopasowanie, nie draft."""
    roster = [
        RosterPerson(
            11,
            "Piotr",
            "Michałowski",
            (RosterContract(456, "ending", date(2031, 7, 1), date(2031, 9, 30)),),
        )
    ]
    rows = [_row()]
    resolved = resolve_rows(rows, roster)

    assert resolved[0].match_kind == MATCH_EXACT
    assert resolved[0].contract_id == 456

    proposal = _plan(rows, resolved)
    assert proposal.rows[0].action != ACTION_NEW_DRAFT
    assert proposal.rows[0].action == ACTION_NEW
    assert proposal.rows[0].contract_id == 456
    assert proposal.rows[0].existing_person_ids == []
    assert _gate(rows, resolved, proposal).verdict == VERDICT_AUTO


def test_document_without_diacritics_still_matches_the_roster():
    """Skan bez polskich znaków to ta sama osoba, nie nowy kontraktor."""
    roster = [
        RosterPerson(
            11, "Piotr", "Michałowski", (RosterContract(456, "active", None, None),)
        )
    ]
    resolved = resolve_rows([_row("Michalowski Piotr")], roster)
    assert resolved[0].match_kind == MATCH_EXACT and resolved[0].contract_id == 456


# ── 2) prawdziwi imiennicy u TEGO SAMEGO klienta ────────────────────────────


def test_two_different_people_of_the_same_name_at_this_client_still_ask_a_human():
    """Automat nie chowa realnej niejednoznaczności pod dopasowaniem."""
    roster = [
        RosterPerson(
            11, "Piotr", "Michałowski", (RosterContract(456, "active", None, None),)
        ),
        RosterPerson(
            12, "Piotr", "Michałowski", (RosterContract(789, "active", None, None),)
        ),
    ]
    rows = [_row()]
    resolved = resolve_rows(rows, roster)

    assert resolved[0].match_kind == MATCH_AMBIGUOUS
    assert resolved[0].candidate_ids == (11, 12)
    assert resolved[0].contract_id is None
    assert "456" in resolved[0].reason and "789" in resolved[0].reason

    verdict = _gate(rows, resolved, _plan(rows, resolved))
    assert verdict.verdict == VERDICT_REVIEW
    assert any("wybierz ręcznie" in r for r in verdict.reasons)


# ── 3) osoba spoza rostera, ale obecna w bazie ──────────────────────────────


def _unmatched(rows, hits):
    resolved = resolve_rows(rows, [])
    assert resolved[0].match_kind == MATCH_NONE
    return annotate_known_elsewhere(resolved, {rows[0].consultant_name: hits})


def test_open_engagement_elsewhere_blocks_auto_and_names_the_contract():
    """Dokładnie przypadek ze zgłoszenia: kolejka mówi KOGO i GDZIE znaleziono."""
    rows = [_row()]
    resolved = _unmatched(
        rows,
        (
            PersonElsewhere(
                candidate_id=11,
                full_name="Piotr Michałowski",
                contract_id=456,
                contract_status="ending",
                client_id=CLIENT_WITH_CONTRACTS,
                client_name="Powszechna Kasa Oszczędności Bank Polski S.A",
            ),
        ),
    )
    assert resolved[0].known_elsewhere_ids == (11,)
    # Zdanie zaczyna się od nazwy Z DOKUMENTU — to ona stoi w tabeli osób obok.
    assert resolved[0].reason.startswith(f"„{DOCUMENT_NAME}”:")
    assert "#456" in resolved[0].reason
    assert "Powszechna Kasa Oszczędności Bank Polski S.A" in resolved[0].reason

    proposal = _plan(rows, resolved, client_id=58468)
    row = proposal.rows[0]
    # Plan zostaje przy szkicu — po potwierdzeniu writer dopnie tę kartotekę —
    # ale niesie znalezisko, więc kolejka nie proponuje „nowego kontraktora".
    assert row.action == ACTION_NEW_DRAFT
    assert row.existing_person_ids == [11]
    assert row.reasons == [resolved[0].reason]

    verdict = _gate(rows, resolved, proposal)
    assert verdict.verdict == VERDICT_REVIEW
    assert resolved[0].reason in verdict.reasons


def test_person_absent_from_the_base_waits_for_the_signed_agreement():
    """Zamówienie klienta nie zakłada kontraktora — czeka na podpisaną umowę.

    Zgłoszenie 09.2026 (Nordea, Adam Grono): PO przyszło przed podpisem umowy
    B2B, osoby nie było na rosterze klienta, a automat założył kandydata,
    szkic kontraktu i zamówienie. Kontrakt rodzi się z podpisanej umowy,
    a nie z PDF-a klienta.
    """
    rows = [_row("Zenon Zupełnie Nowy")]
    resolved = resolve_rows(rows, [])
    assert (
        resolved[0].match_kind == MATCH_NONE and resolved[0].known_elsewhere_ids == ()
    )

    proposal = _plan(rows, resolved)
    # Plan ZOSTAJE szkicem: ręczne „Zastosuj" bramki nie czyta, więc Delivery
    # Lead zachowuje drogę dla kontraktora bez umowy B2B (UoP, zlecenie).
    assert proposal.rows[0].action == ACTION_NEW_DRAFT
    assert proposal.rows[0].existing_person_ids == []

    verdict = _gate(rows, resolved, proposal)
    assert verdict.verdict == VERDICT_REVIEW
    assert CODE_PERSON_NEW_TO_SYSTEM in verdict.codes
    assert any("czeka na podpisaną umowę B2B" in r for r in verdict.reasons)


def test_waiting_for_the_agreement_is_silent_for_the_delivery_lead():
    """Kategoria „czeka na podpis": bez licznika prób i bez karty dla DL."""
    rows = [_row("Zenon Zupełnie Nowy")]
    resolved = resolve_rows(rows, [])
    verdict = _gate(rows, resolved, _plan(rows, resolved))

    assert classify_hold(verdict.codes) == CATEGORY_AWAITING_CONTRACT


def test_the_same_order_applies_itself_once_the_contract_exists():
    """Po „podpisana obustronnie" kontrakt istnieje — recheck dopisze zamówienie.

    To druga połowa reguły: wstrzymanie ma być CZEKANIEM, nie zablokowaniem.
    Ten sam dokument z tą samą osobą jedzie automatem, gdy tylko kontraktor
    pojawi się na rosterze klienta.
    """
    rows = [_row("Zenon Zupełnie Nowy")]
    roster = [
        RosterPerson(
            77,
            "Zenon",
            "Zupełnie Nowy",
            (RosterContract(654, "active", date(2031, 10, 1), None),),
        )
    ]
    resolved = resolve_rows(rows, roster)
    assert resolved[0].match_kind == MATCH_EXACT and resolved[0].contract_id == 654

    proposal = _plan(rows, resolved)
    assert _gate(rows, resolved, proposal).verdict == VERDICT_AUTO


def test_person_in_base_without_any_engagement_also_waits_for_confirmation():
    rows = [_row()]
    resolved = _unmatched(
        rows, (PersonElsewhere(candidate_id=11, full_name="Piotr Michałowski"),)
    )
    assert resolved[0].known_elsewhere_ids == (11,)
    assert "zastosuj ręcznie" in resolved[0].reason
    assert _gate(rows, resolved, _plan(rows, resolved)).verdict == VERDICT_REVIEW


def test_namesakes_in_the_base_are_listed_rather_than_guessed():
    hits = (
        PersonElsewhere(11, "Piotr Michałowski", 456, "active", 26, "Klient A"),
        PersonElsewhere(12, "Piotr Michałowski", 999, "active", 77, "Klient B"),
    )
    reason = known_elsewhere_reason(DOCUMENT_NAME, hits)
    assert "#11" in reason and "#12" in reason
    assert "automat nie zgaduje" in reason


def test_md_order_carries_the_finding_next_to_the_decide_person_message():
    """Zamówienie MD/kosztowe: decyzję i tak podejmuje człowiek — pokaż mu oba zdania."""
    rows = [_row()]
    resolved = _unmatched(
        rows,
        (
            PersonElsewhere(
                candidate_id=11,
                full_name="Piotr Michałowski",
                contract_id=456,
                contract_status="active",
                client_id=CLIENT_WITH_CONTRACTS,
                client_name="Bank Właściwy Rekord",
            ),
        ),
    )
    proposal = plan_document(
        client_id=58468,
        extraction=_extraction(rows),
        resolved=resolved,
        existing_orders_by_contract={},
        is_group_client=True,
        today=TODAY,
        order_type="md",
    )
    row = proposal.rows[0]
    assert row.action == ACTION_DECIDE_PERSON
    assert row.existing_person_ids == [11]
    assert any("Nie znaleziono" in r for r in row.reasons)
    assert any("Bank Właściwy Rekord" in r for r in row.reasons)


def test_md_order_for_an_unknown_person_says_it_once():
    """Planer i bramka mówią o tym samym — kolejka ma dostać jedno zdanie.

    Wiersz niesie liczbę MD: bez niej doszedłby `CODE_MD_MISSING`, a jeden
    powód spoza „czeka na podpis" przesuwa dokument do kategorii `other`
    (i do kart dla Delivery Leada) — czyli test mierzyłby co innego.
    """
    rows = [_row("Zenon Zupełnie Nowy", md=Decimal("20"))]
    resolved = resolve_rows(rows, [])
    proposal = plan_document(
        client_id=CLIENT_WITH_CONTRACTS,
        extraction=_extraction(rows),
        resolved=resolved,
        existing_orders_by_contract={},
        is_group_client=True,
        today=TODAY,
        order_type="md",
    )
    assert proposal.rows[0].action == ACTION_DECIDE_PERSON

    verdict = _gate(rows, resolved, proposal)
    assert verdict.verdict == VERDICT_REVIEW
    # Powód z planera (krok 8) zostaje; bramka nie dokłada drugiego o tym samym.
    assert CODE_PERSON_NEW_TO_SYSTEM not in verdict.codes
    assert CODE_PERSON_DECISION_NEW in verdict.codes
    assert classify_hold(verdict.codes) == CATEGORY_AWAITING_CONTRACT


def test_annotation_never_touches_a_row_that_matched_the_roster():
    """Podpowiedź dotyczy wyłącznie wierszy bez dopasowania u tego klienta."""
    roster = [
        RosterPerson(
            11, "Piotr", "Michałowski", (RosterContract(456, "active", None, None),)
        )
    ]
    rows = [_row()]
    resolved = resolve_rows(rows, roster)
    annotated = annotate_known_elsewhere(
        resolved,
        {DOCUMENT_NAME: (PersonElsewhere(99, "Piotr Michałowski"),)},
    )
    assert annotated[0].known_elsewhere_ids == ()
    assert annotated[0].contract_id == 456
