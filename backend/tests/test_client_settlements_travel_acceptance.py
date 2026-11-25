"""Akceptacja kosztów delegacji przez klienta (próba IX–X 2026). Bez bazy.

RCP z kosztami delegacji dawał uwagę „Delegacja do sprawdzenia”, choć klient
podpisał RCP z kwotą kosztów albo odpisał „Potwierdzam” na prośbę o akceptację.
Osoby, domeny i kwoty fikcyjne.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal as D

from app.services.client_settlements import mail_text, travel_acceptance
from app.services.client_settlements.rcp_bnp import SignatureInfo, parse_pdf_text
from app.services.client_settlements.rcp_checks import evaluate
from tests.test_client_settlements_rcp import PDF_TEXT, _eval, _rules

CLIENT = "bank-klienta.pl"
SENDERS = mail_text.Senders(
    client=frozenset({CLIENT}),
    own=frozenset({"nasza-firma.pl", "gmail.com"}),
    consultant=frozenset({f"jan.przykladowy@external.{CLIENT}"}),
)
PERSON = "Jan Przykładowy"
ITEMS = (
    ("Pociąg", D("235.4")),
    ("Taksówki i transport publiczny", D("0")),
    ("Hotele", D("610")),
    ("inne", D("0")),
)
TOTAL = D("845.40")


def _sig(
    signer: str = "NOWAK Ewa",
    domain: str | None = CLIENT,
    *,
    intact: bool = True,
    issuer: str = "Bank Klienta Subordinate CA",
) -> SignatureInfo:
    return SignatureInfo(
        intact=intact,
        entire_file=True,
        issuer=issuer,
        signer=signer,
        signer_email_domain=domain,
        signed_at=datetime(2026, 10, 1, 8, 15, tzinfo=timezone.utc),
    )


def _printout(reply_from: str, reply: str, request: str) -> mail_text.Mail:
    text = (
        f"PRZYKŁADOWY Jan <jan.przykladowy@external.{CLIENT}> 23.09.2026 12:18\n"
        "FW: Akceptacja kosztów wyjazdu do Krakowa\n"
        "Akceptacja kosztów.\n"
        f"From: NOWAK Ewa <{reply_from}>\n"
        "Sent: Wednesday, September 23, 2026 12:03 PM\n"
        f"To: PRZYKŁADOWY Jan <jan.przykladowy@external.{CLIENT}>\n"
        "Subject: RE: Akceptacja kosztów wyjazdu do Krakowa\n"
        f"{reply}\n"
        f"From: PRZYKŁADOWY Jan <jan.przykladowy@external.{CLIENT}>\n"
        "Subject: Akceptacja kosztów wyjazdu do Krakowa\n"
        f"{request}\n"
        "Kapitał zakładowy w wysokości 147 880 491 zł w całości wpłacony.\n"
    )
    mail = mail_text.from_printout(text)
    assert mail is not None
    return mail


REQUEST = (
    "Muszę potwierdzić koszty przed zakupem:\n"
    "Hotel Kraków, data przyjazdu: 2026-09-28, cena całkowita: 610.00 PLN\n"
    "Pociągi – szacowany koszt to około 220 PLN\nProśba o akceptację."
)


# ── podpis RCP ───────────────────────────────────────────────────────────────


def test_rcp_podpisany_przez_klienta_zdejmuje_uwage():
    verdict = travel_acceptance.by_signature(
        [_sig()], total=TOTAL, senders=SENDERS, person_name=PERSON
    )
    assert verdict is not None and verdict.ok
    assert "845,4 zł" in verdict.detail and CLIENT in verdict.detail


def test_podpis_z_innej_domeny_nie_jest_akceptacja_klienta():
    for domain in ("nasza-firma.pl", "gmail.com", None):
        assert (
            travel_acceptance.by_signature(
                [_sig(domain=domain)], total=TOTAL, senders=SENDERS, person_name=PERSON
            )
            is None
        )


def test_podpis_samego_konsultanta_nie_jest_akceptacja():
    verdict = travel_acceptance.by_signature(
        [_sig(signer="PRZYKŁADOWY Jan")],
        total=TOTAL,
        senders=SENDERS,
        person_name=PERSON,
    )
    assert verdict is None


def test_podpis_niewazny_albo_innego_wystawcy_nie_liczy_sie():
    assert (
        travel_acceptance.by_signature(
            [_sig(intact=False)], total=TOTAL, senders=SENDERS, person_name=PERSON
        )
        is None
    )
    assert (
        travel_acceptance.by_signature(
            [_sig(issuer="Inne CA")],
            total=TOTAL,
            senders=SENDERS,
            person_name=PERSON,
            issuer="Bank Klienta",
        )
        is None
    )


# ── mail klienta ─────────────────────────────────────────────────────────────


def test_mail_klienta_z_kwota_jak_w_rcp():
    mail = _printout(
        f"ewa.nowak@{CLIENT}", "Potwierdzam.", "Koszty wyjazdu razem 845,40 zł."
    )
    verdict = travel_acceptance.by_mail(
        [mail], total=TOTAL, items=ITEMS, senders=SENDERS
    )
    assert verdict is not None and verdict.ok
    assert f"ewa.nowak@{CLIENT}" in verdict.detail


def test_mail_klienta_z_pozycjami_jak_w_rcp():
    mail = _printout(
        f"ewa.nowak@{CLIENT}",
        "Akceptuję.",
        "Hotel: 610,00 zł\nPociąg Warszawa – Kraków – Warszawa: 235,40 zł",
    )
    verdict = travel_acceptance.by_mail(
        [mail], total=TOTAL, items=ITEMS, senders=SENDERS
    )
    assert verdict is not None and verdict.ok
    assert "Hotele 610 zł" in verdict.detail


def test_mail_klienta_na_inna_kwote_zostawia_uwage():
    """Klient zaakceptował szacunek (610 + ok. 220 zł), a w RCP jest 845,40 zł."""

    mail = _printout(f"ewa.nowak@{CLIENT}", "Potwierdzam.", REQUEST)
    verdict = travel_acceptance.by_mail(
        [mail], total=TOTAL, items=ITEMS, senders=SENDERS
    )
    assert verdict is not None and not verdict.ok
    # Kapitał zakładowy ze stopki banku to nie kwota akceptacji.
    assert verdict.detail == (
        f"Klient (ewa.nowak@{CLIENT}) zaakceptował: 610 zł, 220 zł. W RCP 845,4 zł."
    )


def test_akceptacja_z_innej_domeny_nie_liczy_sie():
    for sender in ("ewa.nowak@gmail.com", "koordynator@nasza-firma.pl"):
        mail = _printout(sender, "Potwierdzam.", "Koszty wyjazdu razem 845,40 zł.")
        assert (
            travel_acceptance.by_mail([mail], total=TOTAL, items=ITEMS, senders=SENDERS)
            is None
        )


def test_akceptacja_samego_konsultanta_nie_liczy_sie():
    mail = _printout(
        f"jan.przykladowy@external.{CLIENT}",
        "Potwierdzam.",
        "Koszty wyjazdu razem 845,40 zł.",
    )
    assert (
        travel_acceptance.by_mail([mail], total=TOTAL, items=ITEMS, senders=SENDERS)
        is None
    )


def test_potwierdzenie_bez_watku_o_wyjezdzie_nie_liczy_sie():
    text = (
        "FW: Time Sheet 09.2026\n"
        f"From: NOWAK Ewa <ewa.nowak@{CLIENT}>\n"
        "Potwierdzam. Faktura na 845,40 zł.\n"
    )
    mail = mail_text.from_printout(text)
    assert mail is not None
    assert (
        travel_acceptance.by_mail([mail], total=TOTAL, items=ITEMS, senders=SENDERS)
        is None
    )


def test_prosba_bez_odpowiedzi_klienta_nie_liczy_sie():
    mail = _printout(f"ewa.nowak@{CLIENT}", "Proszę o fakturę.", REQUEST)
    assert (
        travel_acceptance.by_mail([mail], total=TOTAL, items=ITEMS, senders=SENDERS)
        is None
    )


def test_pdf_bez_naglowka_maila_to_nie_wydruk():
    assert mail_text.from_printout("Faktura VAT nr 1/09/2026\nRazem 845,40 zł") is None


def test_kwoty_tylko_z_waluta():
    text = "Data 2026-09-28 12:18, tel. 600 100 200, hotel 1 234,50 zł, pociąg 99 PLN"
    assert travel_acceptance.amounts(text) == [D("1234.50"), D("99")]


# ── kontrola w RCP ───────────────────────────────────────────────────────────

TRAVEL_PDF = PDF_TEXT.replace(
    "SUMA 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0,00",
    "Pociąg 117,7 117,7 235,4\n"
    "Taksówki i transport publiczny 0\n"
    "Hotele 610 610\n"
    "inne 0\n"
    "SUMA 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 727,7 0 117,7 0 845,40",
)


def test_rcp_czyta_pozycje_kosztow_delegacji():
    parsed = parse_pdf_text(TRAVEL_PDF)
    assert parsed.travel_total == D("845.40")
    assert parsed.travel_items == ITEMS


def _travel_checks(result) -> list[dict]:
    return [c for g in result.groups if g["title"] == "Delegacje" for c in g["checks"]]


def test_akceptacja_klienta_zdejmuje_uwage_o_delegacji():
    verdict = travel_acceptance.Verdict(
        True, "Koszty delegacji w RCP podpisanym przez klienta", "x"
    )
    result = _eval(parse_pdf_text(TRAVEL_PDF), travel=verdict)
    assert not result.warn
    assert [c["state"] for c in _travel_checks(result)] == ["ok"]


def test_bez_akceptacji_uwaga_zostaje():
    result = _eval(parse_pdf_text(TRAVEL_PDF))
    assert result.warn
    (check,) = _travel_checks(result)
    assert check["state"] == "warn" and check["rule"] == "travel.rcp_costs"
    assert "Brak akceptacji kosztów od klienta" in check["detail"]


def test_inna_kwota_zostawia_uwage_z_kwotami():
    verdict = travel_acceptance.Verdict(
        False, "Akceptacja kosztów na inną kwotę", "Klient zaakceptował: 610 zł."
    )
    result = _eval(parse_pdf_text(TRAVEL_PDF), travel=verdict)
    assert result.warn
    (check,) = _travel_checks(result)
    assert check["title"] == "Delegacja do sprawdzenia"
    assert "Klient zaakceptował: 610 zł." in check["detail"]


def test_evaluate_przekazuje_godziny_dzien_po_dniu():
    result = evaluate(
        parse_pdf_text(PDF_TEXT),
        [],
        mime="application/pdf",
        month="2026-10",
        person_name="Anna Testowa",
        has_mail=True,
        rules=_rules(),
    )
    assert len(result.day_hours) == 31 and sum(result.day_hours) == D("174")
