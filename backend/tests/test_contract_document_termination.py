"""Reguła wypowiedzenia z podpisanej umowy — wzorce tekstu, bez modelu i bez bazy.

Fragmenty są fikcyjne, ale idą za dwiema generacjami wzoru umowy B2B:
dzisiejszą (``templates/contract/umowa_b2b_pl.html`` § 12) i redakcją
z 2025 r. („liczonym od kolejnego miesiąca … w formie pisemnej pod rygorem
nieważności … osobiście lub pocztą za potwierdzeniem odbioru”).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.contract_document_text import service, structure
from app.services.contract_document_text.termination import (
    DELIVERY_EMAIL,
    DELIVERY_IN_PERSON,
    DELIVERY_POST,
    FORM_DOCUMENTARY,
    FORM_WRITTEN,
    PERIOD_DAYS,
    PERIOD_END_OF_MONTH,
    PERIOD_FROM_NEXT_MONTH,
    parse_termination,
)
from app.services.framework_contract_text import ChunkRef, Passage, split_into_chunks

TODAY_TEMPLATE = """UMOWA O WSPÓŁPRACY B2B nr 31/2026
§ 11
Siła wyższa
Jeżeli stan siły wyższej trwa dłużej niż 15 dni, każda ze Stron może rozwiązać
Umowę ze skutkiem natychmiastowym, bez prawa dochodzenia odszkodowania.
§ 12
Rozwiązanie umowy
Umowa zostaje zawarta na czas nieokreślony.
Strony mają prawo do rozwiązania Umowy w następujących trybach:
za porozumieniem Stron w dowolnym terminie
Za wypowiedzeniem dokonanym przez którąkolwiek ze Stron, z zachowaniem okresu
1 miesiąca ze skutkiem na koniec miesiąca kalendarzowego.
Każdej ze Stron przysługuje prawo do rozwiązania Umowy ze skutkiem natychmiastowym
(bez zachowania okresu wypowiedzenia) w razie rażącego naruszenia jej postanowień.
Oświadczenie o wypowiedzeniu lub rozwiązaniu Umowy musi być złożone w formie
pisemnej lub dokumentowej (np. skan podpisany własnoręcznie lub kwalifikowany podpis
elektroniczny/zaufany) pod rygorem nieważności. Doręczenie może nastąpić osobiście,
pocztą tradycyjną na adres siedziby Strony lub mailowo na dedykowany adres dla
doręczeń formalnych:
• Dla B2BNET: doreczenia@example.com
§ 13
Postanowienia końcowe
Wszelkie zmiany i uzupełnienia Umowy wymagają dla swej ważności formy pisemnej
lub dokumentowej pod rygorem nieważności.
"""

EDITION_2025 = """UMOWA WSPÓŁPRACY nr 12/2025
zawarta w Warszawie pomiędzy Stronami.
§ 8
Rozwiązanie Umowy
1. Umowa zostaje zawarta na czas nieokreślony.
2. Każda ze Stron może wypowiedzieć Umowę z zachowaniem 1-miesięcznego okresu wypowiedze-
nia, liczonym od kolejnego miesiąca kalendarzowego następującego po miesiącu, w którym
doręczono wypowiedzenie.
3. Wypowiedzenie wymaga zachowania formy pisemnej pod rygorem nieważności i doręczenia
drugiej Stronie osobiście lub pocztą za potwierdzeniem odbioru.
§ 9
Postanowienia końcowe
1. Zmiany Umowy wymagają formy pisemnej pod rygorem nieważności.
"""


def test_todays_template_counts_to_the_end_of_the_month_and_allows_email() -> None:
    parsed = parse_termination(TODAY_TEMPLATE)
    assert parsed.reason is None
    rule = parsed.rule
    assert rule.period_kind == PERIOD_END_OF_MONTH
    assert (rule.period_months, rule.period_days) == (1, None)
    assert rule.forms == (FORM_WRITTEN, FORM_DOCUMENTARY)
    assert rule.under_nullity is True
    assert rule.delivery == (DELIVERY_IN_PERSON, DELIVERY_POST, DELIVERY_EMAIL)
    assert rule.period_clause.ref == "§ 12"
    assert "na koniec miesiąca" in rule.period_clause.text
    # Cytat to zdanie z umowy (złożone wiersze), nie przeróbka.
    assert rule.form_clause.text.startswith("Oświadczenie o wypowiedzeniu")
    assert rule.delivery_clause.text.startswith("Doręczenie może nastąpić osobiście")
    assert rule.notes == ()


def test_2025_edition_counts_from_the_next_month_and_needs_post_or_hand() -> None:
    parsed = parse_termination(EDITION_2025)
    rule = parsed.rule
    assert rule.period_kind == PERIOD_FROM_NEXT_MONTH
    assert rule.period_months == 1
    assert rule.forms == (FORM_WRITTEN,)
    assert rule.under_nullity is True
    # Bez maila — pismo mailem byłoby nieskuteczne wobec tej umowy.
    assert rule.delivery == (DELIVERY_IN_PERSON, DELIVERY_POST)
    assert rule.period_clause.ref == "§ 8 ust. 2"
    assert rule.form_clause.ref == "§ 8 ust. 3"
    # Dzielenie wyrazu na końcu wiersza nie psuje cytatu.
    assert "okresu wypowiedzenia, liczonym" in rule.period_clause.text


def test_amendment_form_clause_is_not_the_termination_form() -> None:
    """§ 13 / § 9 („zmiany Umowy wymagają formy pisemnej”) nie dotyczy wypowiedzenia."""
    text = EDITION_2025.replace(
        "3. Wypowiedzenie wymaga zachowania formy pisemnej pod rygorem nieważności i doręczenia\n"
        "drugiej Stronie osobiście lub pocztą za potwierdzeniem odbioru.\n",
        "",
    )
    rule = parse_termination(text).rule
    assert rule.forms == ()
    assert "Nie znaleziono zapisu o formie wypowiedzenia." in rule.notes


def test_days_period_without_month_anchor() -> None:
    text = (
        "§ 5\n1. Każda ze Stron może rozwiązać Umowę z zachowaniem 30 (trzydziestu) "
        "dni okresu wypowiedzenia.\n2. Wypowiedzenie wymaga formy pisemnej i może być "
        "przesłane pocztą elektroniczną.\n"
    )
    rule = parse_termination(text).rule
    assert (rule.period_kind, rule.period_days, rule.period_months) == (
        PERIOD_DAYS,
        30,
        None,
    )
    # „pocztą elektroniczną” to mail, nie poczta tradycyjna.
    assert rule.delivery == (DELIVERY_EMAIL,)


def test_word_number_and_anchor_in_the_next_sentence() -> None:
    text = (
        "§ 7\n2. Okres wypowiedzenia Umowy wynosi jeden miesiąc. Okres ten upływa "
        "z końcem miesiąca kalendarzowego.\n"
    )
    rule = parse_termination(text).rule
    assert rule.period_kind == PERIOD_END_OF_MONTH
    assert rule.period_months == 1


@pytest.mark.parametrize(
    "text, reason_part",
    [
        ("", "nie ma treści"),
        (
            "§ 1\nPartner świadczy usługi programistyczne na rzecz Klienta.\n",
            "nie ma zapisu o okresie wypowiedzenia",
        ),
        (
            "§ 8\n1. Każda ze Stron może wypowiedzieć Umowę z zachowaniem 1 miesiąca "
            "okresu wypowiedzenia.\n",
            "bez sposobu liczenia",
        ),
        (
            "§ 8\n1. W okresie pierwszych trzech miesięcy okres wypowiedzenia wynosi "
            "7 dni.\n2. Po tym czasie każda ze Stron może wypowiedzieć Umowę "
            "z zachowaniem 1 miesiąca okresu wypowiedzenia ze skutkiem na koniec "
            "miesiąca.\n",
            "więcej niż jeden okres",
        ),
        (
            "§ 8\n1. Umowę można wypowiedzieć z zachowaniem 1 miesiąca okresu "
            "wypowiedzenia ze skutkiem na koniec miesiąca, liczonym od kolejnego "
            "miesiąca.\n",
            "i o końcu miesiąca, i o kolejnym",
        ),
    ],
)
def test_unsure_text_gives_no_rule_with_a_reason(text: str, reason_part: str) -> None:
    parsed = parse_termination(text)
    assert parsed.rule is None
    assert reason_part in parsed.reason


def test_unrelated_deadline_after_termination_is_not_the_period() -> None:
    text = (
        "§ 4\nPartner zwróci sprzęt w terminie 7 dni od wypowiedzenia Umowy.\n"
        "§ 8\nUmowę można wypowiedzieć z zachowaniem 1 miesiąca okresu "
        "wypowiedzenia ze skutkiem na koniec miesiąca kalendarzowego.\n"
    )
    rule = parse_termination(text).rule
    assert rule.period_kind == PERIOD_END_OF_MONTH
    assert rule.period_clause.ref == "§ 8"


def test_document_number_and_range_ref() -> None:
    assert structure.document_number(EDITION_2025) == "12/2025"
    assert structure.document_number("Umowa o współpracy\n§ 1 ...") is None
    found = structure.markers(EDITION_2025)
    start = EDITION_2025.index("2. Każda")
    assert structure.range_ref(found, start, start + 40) == "§ 8 ust. 2"
    assert structure.range_ref(found, start, EDITION_2025.index("§ 9") + 5) == "§ 8–9"


def test_passage_ref_names_the_document_and_the_paragraph() -> None:
    chunks_text = split_into_chunks(EDITION_2025)
    chunks = [
        ChunkRef(id=100 + i, contract_id=9, index=i, text=t)
        for i, t in enumerate(chunks_text)
    ]
    hit = next(c for c in chunks if "1-miesięcznego" in c.text)
    document = SimpleNamespace(
        id=9,
        contract_id=4,
        doc_type="contract",
        filename="umowa-2025.pdf",
    )
    passage = service._passage(
        document, Passage(9, hit.index, hit.index, hit.text), chunks
    )
    assert passage.source.kind == "contract"
    assert passage.source.ref.startswith("umowa 12/2025 § 8")
    assert passage.source.url == "/contracts/4?tab=documents"
    assert passage.source.text == hit.text
