"""Mail koordynatora z godzinami zaakceptowanymi przez klienta → MD osoby. Bez bazy.

Dane fikcyjne: osoby „Jan Testowy”, „Anna Inna”, „Piotr Trzeci”, numer umowy
wymyślony. Układ jak w mailach koordynatorki rozliczeń CeZ z IX–X 2026: temat
„Zaakceptowane godziny przez cez: Umowa nr … - Październik 2026” albo
„AKCEPTACJA GODZIN CEZ WRZESIEŃ”, w treści wiersz na osobę „Imię Nazwisko: 176 h”
(też bez spacji i z punktorem w osobnej linii), „czekamy” albo „BRAK CZEKAMY”
dla osoby bez akceptacji, pod spodem stopka i cytat wcześniejszej wersji.
"""

from __future__ import annotations

from decimal import Decimal
from email.message import EmailMessage

from app.models.consultant_portal import CpDocument
from app.services.client_settlements import hours_summary, rules_catalog, service

MONTH = "2026-10"
SUBJECT = "ODP: Zaakceptowane godziny przez cez: Umowa nr CeZ 99 2025 Cz. II-sig- Październik 2026"
BODY = """Jan Testowy: 176 h
Anna Inna:112h
Piotr Trzeci: czekamy


Pozdrawiam,

Koordynator ds. Rozliczeń

Od: Koordynator
Wysłane: czwartek, 5 listopada 2026 17:04
Temat: Zaakceptowane godziny przez cez
Jan Testowy: 100 h
Piotr Trzeci: 999 h
"""

BULLETS = """Zaakceptowane godziny przez cez: Umowa nr CeZ 99 2025 Cz. II-sig


  *
Jan Testowy:168h
  *
Anna Inna: BRAK CZEKAMY
  *
Piotr Trzeci: 128h

Pozdrawiam,
"""


def _rules() -> dict:
    return rules_catalog.effective(
        {
            "proof.month": {"level": "block"},
            "proof.name_match": {"level": "warn"},
            "fields.md_hours": {"level": "block", "params": {"hours": "8"}},
        }
    )


def _hours(summary) -> dict[str, Decimal]:
    return {p.name: p.hours for p in summary.people}


def test_osoby_z_godzinami_bez_czekamy_i_bez_cytatu():
    summary = hours_summary.parse_text(SUBJECT, BODY)

    assert summary is not None
    assert summary.month == MONTH
    assert _hours(summary) == {
        "Jan Testowy": Decimal("176"),
        "Anna Inna": Decimal("112"),
    }


def test_punktory_w_osobnej_linii_i_brak_czekamy():
    summary = hours_summary.parse_text("PD: AKCEPTACJA GODZIN CEZ WRZESIEŃ", BULLETS)

    assert summary is not None
    assert summary.month is None  # bez roku: okres dokumentu z poczty
    assert _hours(summary) == {
        "Jan Testowy": Decimal("168"),
        "Piotr Trzeci": Decimal("128"),
    }


def test_mail_bez_znacznika_akceptacji_to_nie_zestawienie():
    assert hours_summary.parse_text("Pytanie o fakturę", "Jan Testowy: 176 h") is None


def test_same_czekamy_to_nie_zestawienie():
    body = "Jan Testowy: czekamy\nAnna Inna: czekamy\n"

    assert hours_summary.parse_text(SUBJECT, body) is None


def test_godziny_z_innej_jednostki_nie_sa_wierszem():
    body = "Jan Testowy: 22 MD\nAnna Inna: 160 h\n"

    assert _hours(hours_summary.parse_text(SUBJECT, body)) == {
        "Anna Inna": Decimal("160")
    }


def _eml(subject: str, body: str) -> bytes:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = "koordynator@firma-testowa.example"
    message["To"] = "rozliczenia@firma-testowa.example"
    message.set_content(body)
    return message.as_bytes()


def test_odczyt_z_eml():
    summary = hours_summary.parse(_eml(SUBJECT, BODY), "message/rfc822")

    assert _hours(summary)["Anna Inna"] == Decimal("112")
    assert hours_summary.parse(b"%PDF-1.4", "application/pdf") is None


async def test_rozliczenie_bierze_godziny_osoby_z_maila(tmp_path, monkeypatch):
    from app.services import storage_service

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    folder = tmp_path / "consultant_portal" / "1"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "godziny.eml").write_bytes(_eml(SUBJECT, BODY))
    doc = CpDocument(
        id=9,
        kind="report",
        mime="message/rfc822",
        file_path="consultant_portal/1/godziny.eml",
        period_year=2026,
        period_month=10,
        period_guessed=False,
    )

    jan = await service._proof(
        doc, [doc], month=MONTH, person_name="Jan Testowy", rules=_rules()
    )
    anna = await service._proof(
        doc, [doc], month=MONTH, person_name="Anna Inna", rules=_rules()
    )
    other_month = await service._proof(
        doc, [doc], month="2026-09", person_name="Jan Testowy", rules=_rules()
    )

    assert jan.md_regular == Decimal("22.000")
    assert anna.md_regular == Decimal("14.000")
    assert other_month.md_regular is None
