"""KEŚU klienta rozliczanego przez Jirę (roadmapa E6.3, Alior). Bez bazy.

Fixture'y ``tests/fixtures/kesu/`` to dwa prawdziwe KEŚU za październik 2026
po anonimizacji: nazwiska, stanowiska i opisy zadań podmienione, godziny, dni
i koszty dodatkowe bez zmian, a błędy formatu klienta (zdublowany nagłówek XML,
niezamienione ``&``) zostały. Stawki są fikcyjne (repo jest publiczne); na
prawdziwych stawkach z kontraktów kwoty zgadzały się co do grosza
z podpisanymi KEŚU i fakturami kontraktorów (sprawdzone na próbkach 13.11).
"""

from __future__ import annotations

import asyncio
import email.message
import io
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.client_settlements import (
    client_invoice,
    kesu,
    mail_file,
    rcp_bnp,
    rules_catalog,
    service,
)
from app.services.client_settlements.engine import Inputs, OrderState, compute
from app.services.consultant_portal import documents
from tests._outlook_msg import build_msg
from tests._signed_pdf import blank_pdf, signed_by

FIXTURES = Path(__file__).parent / "fixtures" / "kesu"
WITH_COSTS = (FIXTURES / "kesu_z_kosztami.xls").read_bytes()
NO_COSTS = (FIXTURES / "kesu_bez_kosztow.xls").read_bytes()
EIGHT = Decimal("8")

JIRA_SUBJECT = (
    "FW: [ALIOR JIRA] Rozliczenie kontraktora Ewa Kozłowska za miesiąc 10-2026 "
    "zaakceptowane przez opiekuna"
)
JIRA_BODY = """

Pozdrawiam,
Koordynator

-----Original Message-----
From: jira@klient.example <jira@klient.example>
Sent: Tuesday, November 3, 2026 1:09 PM
To: Ewa.Kozlowska@klient.example; Pawel.Opiekun@klient.example; Koordynator <koordynator@dostawca.example>
Subject: [ALIOR JIRA] Rozliczenie kontraktora Ewa Kozłowska za miesiąc 10-2026 zaakceptowane przez opiekuna

Dzień dobry,

Rozliczenie kontraktora Ewa Kozłowska za miesiąc 10-2026 zostało zaakceptowane przez Paweł Opiekun w dniu 03/11/2026 13:08:28.

KEŚU zostało załączone w formie pliku w tej wiadomości.
"""


def _rules(**overrides: str) -> dict:
    stored = {key: {"level": level, "params": {}} for key, level in overrides.items()}
    return rules_catalog.effective(stored)


def test_odczyt_keszu_xml_2003_z_bledami_formatu() -> None:
    a = kesu.parse(WITH_COSTS)
    b = kesu.parse(NO_COSTS)
    assert a is not None and b is not None
    assert (a.person, a.month, a.hours, a.total_hours, a.total_days) == (
        "Testowy Jan",
        "2026-10",
        Decimal("176"),
        Decimal("176"),
        Decimal("22.00"),
    )
    assert a.extra_costs == Decimal("205.00")
    assert (b.person, b.month, b.hours, b.extra_costs) == (
        "Kozłowska Ewa",
        "2026-10",
        Decimal("160"),
        Decimal("0"),
    )
    assert sum(1 for d in b.days if d.hours > 0) == 20
    assert "Show & Tell" in b.days[0].description
    # Zwykły czytnik Excela tego nie otworzy, a my tak: to nie XLSX ani XLS (BIFF).
    assert not WITH_COSTS.startswith(b"PK") and not WITH_COSTS.startswith(b"\xd0\xcf")


def test_inny_plik_to_nie_keszu() -> None:
    assert kesu.parse(b"%PDF-1.7 ...") is None
    assert kesu.parse(b"<?xml version='1.0'?><root/>") is None
    evil = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"/>'
    assert kesu.parse(evil) is None


@pytest.mark.parametrize(
    ("fixture", "rate_md", "fee", "total"),
    [
        # Stawka klienta 151,37 zł/h × 8 = 1 210,96 zł/MD, nocleg 205 zł brutto.
        # Formuła klienta nie zaokrągla dni: 22 × 1 489,48 dałoby 32 768,56.
        (WITH_COSTS, Decimal("1210.96"), "32768.58", "32973.58"),
        # 143,21 zł/h × 8 = 1 145,68 zł/MD.
        (NO_COSTS, Decimal("1145.68"), "28183.73", "28183.73"),
    ],
)
def test_stawka_razy_godziny_rowna_kwocie_keszu(
    fixture: bytes, rate_md: Decimal, fee: str, total: str
) -> None:
    parsed = kesu.parse(fixture)
    sums = kesu.amounts(parsed.hours, rate_md, parsed.extra_costs, md_hours=EIGHT)
    assert f"{sums.fee_gross:.2f}" == fee
    assert f"{sums.total_gross:.2f}" == total


@pytest.mark.parametrize(
    ("fixture", "rate_cost_md", "invoice_net"),
    [
        # Faktura kontraktora: 176 h × 95 zł = 16 720,00; 160 h × 90 zł = 14 400,00.
        (WITH_COSTS, Decimal("760"), "16720.00"),
        (NO_COSTS, Decimal("720"), "14400.00"),
    ],
)
def test_md_z_keszu_razy_stawka_kosztowa_rowne_fakturze_kontraktora(
    fixture: bytes, rate_cost_md: Decimal, invoice_net: str
) -> None:
    rules = _rules()
    proof = kesu.evaluate(
        kesu.parse(fixture),
        month="2026-10",
        person_name="nieistotne",
        jira=None,
        signatures=[],
        rates=kesu.Rates(None, None),
        cost_invoices=0,
        rules=rules,
    )
    result = compute(
        Inputs(
            md_regular=proof.md_regular,
            md_extra=None,
            rules=rules,
            order=OrderState(
                1, "Z-1", Decimal("100"), Decimal("100"), rate_cost_md, None
            ),
            onboarding_eligible=False,
            proof=proof,
        )
    )
    assert f"{result.amount_cost:.2f}" == invoice_net


def test_mail_z_jiry_osoba_miesiac_opiekun_i_jego_adres() -> None:
    jira = kesu.parse_jira(JIRA_SUBJECT, JIRA_BODY)
    assert jira == kesu.JiraAcceptance(
        person="Ewa Kozłowska",
        month="2026-10",
        approver="Paweł Opiekun",
        accepted_at=datetime(2026, 11, 3, 13, 8),
        # „Paweł” = „Pawel” w adresie: ł bez kreski przy porównaniu.
        approver_email="Pawel.Opiekun@klient.example",
    )
    assert kesu.person_from_subject(JIRA_SUBJECT) == "Ewa Kozłowska"
    assert kesu.person_from_subject("RE: KEŚU październik - Ewa Kozłowska") == (
        "Ewa Kozłowska"
    )
    assert kesu.person_from_subject("Faktura za październik") is None


def test_mail_z_jiry_z_pliku_msg_i_eml() -> None:
    msg = build_msg(
        subject=JIRA_SUBJECT,
        sender="koordynator@dostawca.example",
        body=JIRA_BODY,
        attachments=[("10-2026-test.xls", NO_COSTS), ("Nocleg FV.pdf", blank_pdf())],
    )
    eml = email.message.EmailMessage()
    eml["From"] = "koordynator@dostawca.example"
    eml["Subject"] = JIRA_SUBJECT
    eml.set_content(JIRA_BODY)
    eml.add_attachment(
        NO_COSTS, maintype="application", subtype="vnd.ms-excel", filename="k.xls"
    )
    for content, mime in (
        (msg, mail_file.MSG_MIME),
        (eml.as_bytes(), mail_file.EML_MIME),
    ):
        mail = mail_file.read(content, mime)
        assert mail is not None
        assert mail.subject == JIRA_SUBJECT
        jira = kesu.parse_jira(mail.subject, mail.body)
        assert jira is not None and jira.approver == "Paweł Opiekun"
        sheets = [kesu.parse(a.content) for a in mail.attachments]
        assert any(s is not None and s.hours == Decimal("160") for s in sheets)
    assert (
        mail_file.read(
            b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 100, mail_file.MSG_MIME
        )
        is None
    )


def test_keszu_przyjmowane_jako_plik_rozliczenia() -> None:
    mime, _digest = documents.check_settlement_file(WITH_COSTS)
    assert mime == "application/vnd.ms-excel"
    assert documents.SETTLEMENT_EXTENSIONS[mime] == "xls"


def test_oswiadczenie_o_wlasnym_transporcie_nie_trafia_do_nexusa() -> None:
    assert kesu.is_transport_statement("Oświadczenie - własny transport.pdf")
    assert kesu.is_transport_statement("oswiadczenie_samochod_10.2026.docx")
    assert not kesu.is_transport_statement("Jan FV nocleg.pdf")
    assert not kesu.is_transport_statement("10-2026-ei00001.xls")


async def _evaluate(signatures_from: list[bytes], **rules: str):
    parsed = kesu.parse(WITH_COSTS)
    return kesu.evaluate(
        parsed,
        month="2026-10",
        person_name="Jan Testowy",
        jira=kesu.parse_jira(JIRA_SUBJECT, JIRA_BODY),
        # pyHanko waliduje we własnej pętli zdarzeń: w serwisie też idzie w wątku.
        signatures=[
            await asyncio.to_thread(rcp_bnp.signatures, pdf) for pdf in signatures_from
        ],
        rates=kesu.Rates(Decimal("1210.96"), Decimal("1210.96")),
        cost_invoices=1,
        rules=_rules(**rules),
    )


@pytest.mark.asyncio
async def test_keszu_bez_podpisu_klienta_czeka_na_podpis_klienta() -> None:
    at = datetime(2026, 11, 4, 13, 16, tzinfo=timezone.utc)
    ours = await signed_by(("Spółka", at))
    proof = await _evaluate([ours], **{"travel.extra_costs_confirm": "block"})
    data = proof.meta["kesu"]
    assert data["state"] == kesu.AWAITING_CLIENT
    assert kesu.STATE_LABELS[data["state"]] == "Czeka na podpis klienta"
    assert (data["fee_gross"], data["total_gross"]) == ("32768.58", "32973.58")
    titles = [c["title"] for g in proof.groups for c in g["checks"]]
    assert "Czeka na podpis klienta" in titles
    # Koszty dodatkowe ostrzegają nawet przy poziomie „Blokuje” (odpowiedź z 12.11).
    costs = next(g for g in proof.groups if g["title"] == "Koszty dodatkowe")
    assert costs["checks"][0]["state"] == "warn"
    assert proof.blocking is False

    both = await signed_by(("Spółka", at), ("Klient", at))
    signed = await _evaluate([ours, both])
    assert signed.meta["kesu"]["state"] == kesu.SIGNED
    nothing = await _evaluate([])
    assert nothing.meta["kesu"]["state"] == kesu.TO_COMPANY


@pytest.mark.asyncio
async def test_rozna_stawka_w_kontrakcie_i_zamowieniu_to_uwaga_bez_kwot() -> None:
    proof = kesu.evaluate(
        kesu.parse(NO_COSTS),
        month="2026-10",
        person_name="Ewa Kozłowska",
        jira=None,
        signatures=[],
        rates=kesu.Rates(Decimal("1145.68"), Decimal("1100.00")),
        cost_invoices=0,
        rules=_rules(),
    )
    checks = proof.groups[0]["checks"]
    differs = next(c for c in checks if "inna niż na zamówieniu" in c["title"])
    assert differs["state"] == "warn"
    assert "1145" not in str(checks) and "1 145" not in str(checks)
    # „Razem” liczy się ze stawki kontraktu.
    assert proof.meta["kesu"]["total_gross"] == "28183.73"


def _settlement(state: str, **meta: object) -> SimpleNamespace:
    return SimpleNamespace(
        checks=[
            {
                "remaining_after": "0",
                "kesu": {"state": state, "approver": "X", "extra_costs": "205.00"},
                **meta,
            }
        ],
        md_regular=Decimal("22"),
        md_extra=None,
        md_onboarding=Decimal("0"),
        md_charged=Decimal("22"),
    )


def test_zaplata_po_podpisie_klienta_awaryjnie_po_mailu() -> None:
    rules = _rules(
        **{"pay.after_client_signature": "block", "pay.mail_accept_fallback": "warn"}
    )
    waiting = service.payment(_settlement(kesu.AWAITING_CLIENT), rules)
    assert waiting["can_pay"] is False and waiting["state"] == "fail"
    assert waiting["can_use_mail"] is True
    on_mail = service.payment(
        _settlement(kesu.AWAITING_CLIENT, pay_on_mail={"by": 1, "at": "x"}), rules
    )
    assert on_mail["can_pay"] is True and on_mail["state"] == "warn"
    signed = service.payment(_settlement(kesu.SIGNED), rules)
    assert signed["can_pay"] is True and signed["state"] == "ok"
    assert service.payment(_settlement(kesu.SIGNED), _rules()) is None
    no_fallback = service.payment(
        _settlement(kesu.AWAITING_CLIENT),
        _rules(**{"pay.after_client_signature": "block"}),
    )
    assert no_fallback["can_use_mail"] is False


def test_do_faktury_dopiero_po_podpisie_klienta() -> None:
    rules = _rules(**{"cl.after_signed_document": "block"})
    assert service.waits_for_signature(_settlement(kesu.AWAITING_CLIENT), rules)
    assert service.waits_for_signature(_settlement(kesu.TO_COMPANY), rules)
    assert not service.waits_for_signature(_settlement(kesu.SIGNED), rules)
    assert not service.waits_for_signature(_settlement(kesu.AWAITING_CLIENT), _rules())


def test_koszty_dodatkowe_na_fakturze_glownej() -> None:
    s = _settlement(kesu.SIGNED)
    base = client_invoice.Position(
        "Usługi; osoba",
        "MD",
        Decimal("22"),
        Decimal("1210.96"),
        Decimal("26641.12"),
        "base",
    )
    separate = client_invoice.extra_costs(
        s,
        [base],
        _rules_with_item("Koszty delegacji"),
        name="Usługi; osoba",
    )
    assert [(p.name, p.net, p.kind) for p in separate] == [
        ("Usługi; osoba", Decimal("26641.12"), "base"),
        ("Koszty delegacji", Decimal("166.67"), "extra_costs"),
    ]
    # Brutto faktury = „Razem w PLN BRUTTO” z KEŚU: (26 641,12 + 166,67) × 1,23.
    assert ((Decimal("26641.12") + Decimal("166.67")) * kesu.VAT).quantize(
        Decimal("0.01")
    ) == Decimal("32973.58")
    merged = client_invoice.extra_costs(s, [base], _rules_with_item(""), name="x")
    assert [(p.quantity, p.net) for p in merged] == [
        (Decimal("1"), Decimal("26807.79"))
    ]
    off = client_invoice.extra_costs(s, [base], _rules(), name="x")
    assert off == [base]


def _rules_with_item(item: str) -> dict:
    return rules_catalog.effective(
        {"cl.extra_costs_on_invoice": {"level": "warn", "params": {"item": item}}}
    )


def test_keszu_do_druku_ze_stawka_i_suma() -> None:
    parsed = kesu.parse(WITH_COSTS)
    html = kesu.render_html(
        parsed, rate_md=Decimal("1210.96"), md_hours=EIGHT, month="2026-10"
    )
    # Dzień 8 h: 1 210,96 / 8 × 1,23 × 8 = 1 489,48; razem z noclegiem 205 zł.
    assert "32 973,58" in html and "32 768,58" in html and "1 489,48" in html
    assert "Testowy Jan" in html
    assert (
        kesu.package_name("Ewa Kozłowska", "2026-10")
        == "KESU_Ewa_Kozlowska_10.2026.pdf"
    )


def _text_pdf(text: str) -> bytes:
    """Jednostronicowy PDF z tekstem (jak wizualizacja faktury), bez bibliotek."""

    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d >>stream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return out


def test_paczka_do_podpisu_keszu_i_faktury_kosztow_w_jednym_pdf() -> None:
    import pdfplumber

    package = kesu.merge_pdfs(
        _text_pdf("KESU strona"), [_text_pdf("Faktura nocleg"), _text_pdf("Bilet")]
    )
    with pdfplumber.open(io.BytesIO(package)) as pdf:
        texts = [page.extract_text() or "" for page in pdf.pages]
    assert texts == ["KESU strona", "Faktura nocleg", "Bilet"]


def test_paczka_z_keszu_wydrukowanym_przez_weasyprint() -> None:
    try:
        import weasyprint  # noqa: F401
    except (ImportError, OSError):
        pytest.skip("WeasyPrint bez bibliotek systemowych (pango)")
    import pdfplumber

    html = kesu.render_html(
        kesu.parse(NO_COSTS),
        rate_md=Decimal("1145.68"),
        md_hours=EIGHT,
        month="2026-10",
    )
    package = kesu.merge_pdfs(kesu.render_pdf(html), [_text_pdf("Faktura")])
    with pdfplumber.open(io.BytesIO(package)) as pdf:
        texts = [page.extract_text() or "" for page in pdf.pages]
    assert "Karta Ewidencji" in texts[0]
    assert "28 183,73" in "".join(texts)


def test_mail_do_opiekuna_ze_wzoru_rozliczen() -> None:
    draft = kesu.mail_draft(
        person="Ewa Kozłowska",
        month="2026-10",
        approver="Paweł Opiekun",
        approver_email="Pawel.Opiekun@klient.example",
    )
    assert draft["to"] == "Pawel.Opiekun@klient.example"
    assert draft["subject"] == "KEŚU październik - Ewa Kozłowska"
    assert "z naszym podpisem" in draft["body"]


def test_keszu_z_ogromnym_numerem_wiersza_nie_zjada_pamieci() -> None:
    """``ss:Index`` z pliku z zewnątrz nie może rozdmuchać listy wierszy."""

    evil = (
        b'<?xml version="1.0"?><Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" '
        b'xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet"><Worksheet ss:Name="a"><Table>'
        b'<Row><Cell><Data ss:Type="String">Karta Ewidencji</Data></Cell></Row>'
        b'<Row ss:Index="99999999"><Cell><Data ss:Type="String">x</Data></Cell></Row>'
        b"</Table></Worksheet></Workbook>"
    )
    import tracemalloc

    tracemalloc.start()
    assert kesu.parse(evil) is None
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert peak < 20 * 1024 * 1024


def test_msg_z_petla_w_lancuchu_sektorow_nie_zjada_pamieci() -> None:
    import struct
    import tracemalloc

    sector = 4096
    header = bytearray(sector)
    header[:8] = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    struct.pack_into("<HHH", header, 0x1C, 0xFFFE, 12, 6)
    struct.pack_into("<I", header, 0x2C, 1)  # jeden sektor FAT
    struct.pack_into("<I", header, 0x30, 1)  # katalog od sektora 1
    struct.pack_into("<IIIII", header, 0x38, 4096, 0xFFFFFFFE, 0, 0xFFFFFFFE, 0)
    struct.pack_into("<109I", header, 0x4C, 0, *([0xFFFFFFFF] * 108))
    fat = [0xFFFFFFFD, 1] + [0xFFFFFFFF] * (
        sector // 4 - 2
    )  # sektor 1 wskazuje sam na siebie
    data = bytes(header) + struct.pack(f"<{sector // 4}I", *fat) + bytes(sector)
    tracemalloc.start()
    assert mail_file.read(data, mail_file.MSG_MIME) is None
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert peak < 20 * 1024 * 1024


def test_oswiadczenie_o_prawach_autorskich_to_nie_oswiadczenie_o_transporcie() -> None:
    assert not kesu.is_transport_statement(
        "Oswiadczenie_o_przeniesieniu_praw_autorskich_10_2026.pdf"
    )
    assert not kesu.is_transport_statement("Oświadczenie autora.pdf")
