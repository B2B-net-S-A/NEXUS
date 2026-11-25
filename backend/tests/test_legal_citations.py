"""Weryfikator cytatów asystenta prawnego (bez modelu, bez bazy).

Teksty przepisów w fragmentach są skrócone; dane stron fikcyjne.
"""

from __future__ import annotations

from app.services.legal import citations as c

KC_61 = c.SourcePassage(
    "law",
    "art. 61 § 1",
    "§ 1. Oświadczenie woli, które ma być złożone innej osobie, jest złożone z chwilą, "
    "gdy doszło do niej w taki sposób, że mogła zapoznać się z jego treścią.",
    act_key="kc",
)
KC_111 = c.SourcePassage(
    "law", "art. 111", "Art. 111. § 1. Termin oznaczony w dniach…", act_key="kc"
)
KC_116 = c.SourcePassage(
    "law", "art. 116", "Art. 116. § 1. Jeżeli skutki…", act_key="kc"
)
RODO_6 = c.SourcePassage(
    "law",
    "art. 6 ust. 1",
    "1. Przetwarzanie jest zgodne z prawem wyłącznie w przypadkach, gdy:\n"
    "a) osoba wyraziła zgodę;\nb) przetwarzanie jest niezbędne do wykonania umowy;",
    act_key="rodo",
)
UMOWA_9 = c.SourcePassage(
    "contract",
    "§ 9",
    "§ 9. 1. Wypowiedzenie Umowy wymaga formy pisemnej pod rygorem nieważności.\n"
    "2. Okres wypowiedzenia wynosi 1 miesiąc ze skutkiem na koniec miesiąca.",
    label="Umowa B2B",
)


def _one(
    text: str, passages=(KC_61, KC_111, KC_116, RODO_6, UMOWA_9)
) -> c.CitationCheck:
    checks = c.verify(text, list(passages))
    assert len(checks) == 1, checks
    return checks[0]


def test_extracts_acts_by_abbreviation_and_name() -> None:
    found = c.extract(
        "Zob. art. 61 § 1 KC, art. 30 § 1 pkt 2 k.p., art. 6 ust. 1 lit. b RODO, "
        "art. 442^1 Kodeksu cywilnego i art. 22¹ § 1 kodeksu pracy."
    )
    assert [(f.ref, f.act_key) for f in found] == [
        ("art. 61 § 1", "kc"),
        ("art. 30 § 1 pkt 2", "kp"),
        ("art. 6 ust. 1 lit. b", "rodo"),
        ("art. 442¹", "kc"),
        ("art. 22¹ § 1", "kp"),
    ]
    assert found[3].key == "442^1"


def test_exact_quote_after_reference_is_ok() -> None:
    check = _one(
        "Zgodnie z art. 61 § 1 KC: „Oświadczenie woli, które ma być złożone innej "
        "osobie, jest złożone z chwilą, gdy doszło do niej”."
    )
    assert check.status == c.STATUS_OK
    assert check.passage is KC_61


def test_quote_with_omission_and_other_spacing_is_ok() -> None:
    check = _one(
        "Art. 61 § 1 k.c. stanowi: „oświadczenie woli (…) jest złożone   z chwilą, "
        "gdy doszło do niej w taki sposób, że mogła zapoznać się z jego treścią”."
    )
    assert check.status == c.STATUS_OK


def test_changed_quote_is_mismatch() -> None:
    check = _one(
        "Art. 61 § 1 KC: „Oświadczenie woli jest złożone z chwilą wysłania wiadomości”."
    )
    assert check.status == c.STATUS_MISMATCH
    assert check.reason == "quote_mismatch"


def test_quote_order_matters() -> None:
    assert not c.quote_matches("z jego treścią (…) Oświadczenie woli", KC_61.text)


def test_unknown_provision_is_missing() -> None:
    check = _one("Podstawa: art. 999 § 3 KC.")
    assert check.status == c.STATUS_MISSING
    assert check.reason == "not_found"


def test_reference_without_act_is_missing_with_reason() -> None:
    check = _one("Zgodnie z art. 5 ustawy strony postanawiają.")
    assert check.status == c.STATUS_MISSING
    assert check.reason == "act_unknown"


def test_same_ref_in_other_act_does_not_count() -> None:
    check = _one("Zob. art. 61 § 1 KP.")
    assert check.status == c.STATUS_MISSING


def test_letter_found_through_its_paragraph() -> None:
    check = _one(
        "Podstawą jest art. 6 ust. 1 lit. b RODO: „niezbędne do wykonania umowy”."
    )
    assert check.status == c.STATUS_OK
    assert check.passage is RODO_6


def test_range_needs_both_ends() -> None:
    assert _one("Terminy liczy art. 111–116 KC.").status == c.STATUS_OK
    check = _one("Terminy liczy art. 111–116 KC.", passages=(KC_111,))
    assert check.status == c.STATUS_MISSING
    assert check.reason == "range_end_missing"


def test_contract_paragraph_and_quote_before_reference() -> None:
    check = _one("„Wypowiedzenie Umowy wymaga formy pisemnej” (§ 9 ust. 1 Umowy).")
    assert check.citation.kind == c.KIND_CONTRACT
    assert check.status == c.STATUS_OK
    assert check.passage is UMOWA_9


def test_contract_paragraph_missing_in_given_contract() -> None:
    check = _one("Zgodnie z § 14 umowy ramowej Partner przekazuje raport.")
    assert check.status == c.STATUS_MISSING
    assert check.citation.document == "umowy ramowej"


def test_paragraph_inside_article_is_not_a_contract_reference() -> None:
    found = c.extract("Zob. art. 61 § 1 KC oraz § 9 Umowy.")
    assert [(f.kind, f.ref) for f in found] == [
        (c.KIND_LAW, "art. 61 § 1"),
        (c.KIND_CONTRACT, "§ 9"),
    ]


def test_blocking_when_any_citation_is_not_ok() -> None:
    ok = c.verify("Art. 61 § 1 KC.", [KC_61])
    bad = c.verify("Art. 61 § 1 KC i art. 999 KC.", [KC_61])
    assert not c.blocking(ok)
    assert c.blocking(bad)
    assert not c.blocking([])


def test_contract_passage_ref_may_name_the_document_first() -> None:
    signed = c.SourcePassage(
        "contract",
        "umowa 12/2025 § 8 ust. 2",
        "2. Wypowiedzenie wymaga formy pisemnej pod rygorem nieważności.",
    )
    assert c.passage_key(signed) == "§8 ust.2"
    check = _one(
        "Zgodnie z § 8 ust. 2 Umowy wypowiedzenie wymaga formy pisemnej.", (signed,)
    )
    assert check.status == c.STATUS_OK


# ── przegląd kodu 25.11: podjednostki, rodzaj dokumentu, kawałki cytatu ─────

KC_111_DIVIDED = c.SourcePassage(
    "law", "art. 111 § 1", "§ 1. Termin oznaczony w dniach kończy się z upływem ostatniego dnia.", act_key="kc"
)
KC_111_PAR2 = c.SourcePassage(
    "law", "art. 111 § 2", "§ 2. Jeżeli początkiem terminu jest zdarzenie…", act_key="kc"
)
KC_112 = c.SourcePassage(
    "law", "art. 112", "Art. 112. Termin oznaczony w tygodniach kończy się z upływem dnia.", act_key="kc"
)
CLIENT_9 = c.SourcePassage(
    "client",
    "§ 9",
    "§ 9. 1. Wypowiedzenie Umowy wymaga formy pisemnej pod rygorem nieważności.",
    label="Umowa ramowa",
)
TEMPLATE_9 = c.SourcePassage(
    "template",
    "§ 9",
    "§ 9. 1. Wypowiedzenie Umowy wymaga formy pisemnej pod rygorem nieważności.",
    label="Wzór",
)


def test_missing_paragraph_of_a_divided_article_is_missing() -> None:
    # Art. 111 ma w źródle § 1 i § 2 — § 7 nie istnieje, nadrzędny artykuł nie pokrywa.
    check = _one("Zgodnie z art. 111 § 7 KC termin biegnie dalej.", (KC_111, KC_111_DIVIDED, KC_111_PAR2))
    assert check.status == c.STATUS_MISSING


def test_paragraph_of_an_undivided_article_is_not_ok() -> None:
    check = _one("Zgodnie z art. 112 § 3 KC termin biegnie dalej.", (KC_112,))
    assert check.status != c.STATUS_OK
    quoted = _one("Art. 112 § 3 KC: „Termin oznaczony w tygodniach”.", (KC_112,))
    assert quoted.status != c.STATUS_OK


def test_missing_ust_of_a_contract_paragraph_is_missing() -> None:
    assert _one("Zgodnie z § 9 ust. 8 Umowy.").status == c.STATUS_MISSING
    # Ustęp, który stoi w tekście paragrafu, dalej się znajduje.
    assert _one("Zgodnie z § 9 ust. 2 Umowy.").status == c.STATUS_OK


def test_framework_agreement_reference_reads_only_client_passages() -> None:
    text_ramowa = "„Wypowiedzenie Umowy wymaga formy pisemnej” (§ 9 ust. 1 umowy ramowej)."
    assert _one(text_ramowa, (UMOWA_9,)).status == c.STATUS_MISSING
    assert _one(text_ramowa, (CLIENT_9,)).status == c.STATUS_OK
    text_umowa = "„Wypowiedzenie Umowy wymaga formy pisemnej” (§ 9 ust. 1 Umowy)."
    assert _one(text_umowa, (CLIENT_9,)).status == c.STATUS_MISSING
    assert _one(text_umowa, (TEMPLATE_9,)).status == c.STATUS_MISSING
    text_wzor = "„Wypowiedzenie Umowy wymaga formy pisemnej” (§ 9 ust. 1 wzoru)."
    assert _one(text_wzor, (UMOWA_9,)).status == c.STATUS_MISSING
    assert _one(text_wzor, (TEMPLATE_9,)).status == c.STATUS_OK


def test_short_pieces_around_an_omission_do_not_match() -> None:
    # Przykład z przeglądu: kawałki „Klient” i „kara umowna” pozwalały
    # przeskoczyć „nie” i odwrócić sens zapisu.
    source = "1. Klient może naliczyć karę umowną. 2. Kara umowna nie przekracza wynagrodzenia."
    assert not c.quote_matches("Klient (…) kara umowna (…) przekracza wynagrodzenia", source)
    assert not c.quote_matches("kara (…) wynagrodzenia", source)


def test_quote_pieces_must_hit_word_boundaries() -> None:
    source = "Kara umowna nie przekracza wynagrodzenia miesięcznego."
    assert not c.quote_matches("mowna nie przekracza wynagrodzenia", source)
    assert c.quote_matches("umowna nie przekracza wynagrodzenia", source)
    assert c.quote_matches(
        "Kara umowna nie przekracza (…) wynagrodzenia miesięcznego", source
    )
