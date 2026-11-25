"""Informacja zwrotna o wadach rozliczenia bez bazy: katalog, wykrycie, adresat,
termin i treść. Uwagi jak w rozliczeniach z powtórki 7 próby IX–X; dane fikcyjne.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.services.client_settlements import feedback, mail_text, reminders
from app.services.client_settlements.feedback import Found, Settings, Who

OWNER = reminders.Owner(
    user_id=7, name="Opiekun", email="opiekun@example.com", source="contract_care"
)
CTX = feedback.Context(
    contract_id=1,
    client_id=2,
    client_name="Bank Przykładowy",
    person="Anna Przykładowa",
    month="2026-10",
    settlement_id=3,
)
ADDRESS = "rozliczenia@example.com"


def _checks(*checks: dict) -> list[dict]:
    return [{"title": "RCP", "checks": list(checks)}, {"md_over": None}]


def _codes(**kwargs) -> list[str]:
    return [f.code for f in feedback.defects_in(**kwargs)]


# ── Przełącznik ─────────────────────────────────────────────────────────────


def test_default_is_off_and_garbage_closes_it() -> None:
    assert feedback.normalize(None) == Settings()
    assert feedback.normalize({"mode": "send", "external": "yes"}) == Settings()
    assert not Settings().active
    on = feedback.normalize({"mode": "on", "external": "panel", "every_days": 99})
    assert (on.mode, on.external, on.every_days) == ("on", "panel", 20)
    assert feedback.normalize({"every_days": True}).every_days == 3


def test_production_starts_dry_run_without_external_once() -> None:
    # Decyzja Artura 25.11.2026: najpierw na sucho; wpis admina nie jest nadpisywany.
    from app.services import client_settlement_feedback_schema as schema

    (seed,) = schema.DATA_DDL
    assert "ON CONFLICT (key) DO NOTHING" in seed
    assert '"mode": "dry_run"' in seed and '"external": "off"' in seed
    value = feedback.normalize({"mode": "dry_run", "external": "off", "every_days": 3})
    assert value.dry_run and value.external == "off"


# ── Wykrycie wad z uwag rozliczenia ────────────────────────────────────────


@pytest.mark.parametrize(
    ("check", "code"),
    [
        # BNP 377 IX
        (
            {
                "rule": "proof.excel_with_mail",
                "state": "warn",
                "title": "Excel bez maila akceptującego usługi",
                "detail": "Dołącz mail z akceptacją (MSG, EML albo PDF z wydrukiem).",
            },
            "proof.excel_with_mail",
        ),
        # BNP 367 IX i X
        (
            {
                "rule": "proof.signed_pdf",
                "state": "fail",
                "title": "PDF bez podpisu elektronicznego",
                "detail": None,
            },
            "proof.signed_pdf",
        ),
        # BNP 355 X i 654 X
        (
            {
                "state": "warn",
                "title": "Wiersze opisu prac nie sumują się do SUMA",
                "detail": "Wiersze: 15 MD, SUMA: 22 MD. MD z SUMA jako podstawowe.",
            },
            "fields.rows_sum",
        ),
        # Bosch 624 X
        (
            {
                "rule": "fields.md_hours",
                "state": "fail",
                "title": "Suma „Total Hours” inna niż suma wierszy",
                "detail": "W pliku 126 h, z wierszy 132 h. 132 h / 8 = 16,5 MD.",
            },
            "fields.total_hours",
        ),
        # PKO 717 X
        (
            {
                "rule": "proof.accept_has_hours",
                "state": "fail",
                "title": "Mail bez odpowiedzi akceptującego",
                "detail": "Jest prośba o akceptację, ale nie ma potwierdzenia.",
            },
            "accept.no_reply",
        ),
        (
            {
                "rule": "proof.accept_has_hours",
                "state": "warn",
                "title": "Akceptacja za inny miesiąc",
                "detail": "W mailu: wrzesień 2026.",
            },
            "accept.fix",
        ),
        # Orlen 429 X i 716 X
        (
            {
                "state": "warn",
                "title": "Kwota do faktury inna niż w protokole klienta",
                "detail": "Do faktury 100 zł netto, w protokole 90 zł netto.",
            },
            "amount.protocol",
        ),
    ],
)
def test_rehearsal_defects_map_to_catalog(check: dict, code: str) -> None:
    assert _codes(status="warnings", checks=_checks(check)) == [code]


@pytest.mark.parametrize(
    "check",
    [
        # Sprawy Finansów: bez komunikatu do nikogo.
        {"state": "warn", "title": "Zmiana stawki 29.10: ? → 50", "detail": "x"},
        {"state": "warn", "title": "Nadgodziny bez zgody", "rule": "extra.approval"},
        {"rule": "proof.signed_pdf", "state": "ok", "title": "Podpis ważny"},
        {"state": "none", "title": "Czeka na liczbę MD"},
    ],
)
def test_finance_matters_and_clean_checks_give_nothing(check: dict) -> None:
    assert _codes(status="warnings", checks=_checks(check)) == []


@pytest.mark.parametrize("status", ["ok", "accepted"])
def test_clean_or_accepted_settlement_has_no_defects(status: str) -> None:
    defect = {"rule": "proof.signed_pdf", "state": "fail", "title": "PDF bez podpisu"}
    assert _codes(status=status, checks=_checks(defect)) == []


def test_image_report_without_md_is_a_defect_with_private_mailbox() -> None:
    # CA 603 IX: Time Sheet jako JPG z prywatnej poczty, rozliczenie bez MD.
    found = feedback.defects_in(
        status="checking",
        checks=_checks({"state": "none", "title": "Czeka na liczbę MD"}),
        report_mime="image/jpeg",
        report_sender="Anna.P@Gmail.com",
    )
    assert found == [Found(feedback.IMAGE_REPORT, private=True)]
    # Z MD (OCR albo drugi plik) zdjęcie nie jest wadą.
    assert _codes(status="warnings", checks=[], report_mime="image/png") == []
    assert not feedback.is_private("anna@firma-konsultanta.pl")
    assert not feedback.is_private(None)


def test_image_is_not_a_defect_when_client_sends_hours() -> None:
    # Nordea (T4T): godziny przysyła klient, zdjęcie od konsultanta nie jest raportem.
    assert (
        _codes(
            status="checking",
            checks=[],
            report_mime="image/jpeg",
            consultant_reports=False,
        )
        == []
    )


def test_needs_fix_carries_finance_reason() -> None:
    found = feedback.defects_in(
        status="needs_fix", checks=[], fix_reason="Brak podpisu klienta. Reszta ok."
    )
    assert found == [Found(feedback.NEEDS_FIX, detail="Brak podpisu klienta")]


def test_one_defect_per_code_and_acceptor_from_check() -> None:
    no_reply = {
        "rule": "proof.accept_has_hours",
        "state": "fail",
        "title": "Mail bez odpowiedzi akceptującego",
        "acceptors": ["kierownik@bank.example"],
    }
    found = feedback.defects_in(status="warnings", checks=_checks(no_reply, no_reply))
    assert found == [Found("accept.no_reply", acceptor="kierownik@bank.example")]


def test_detail_keeps_first_sentence_only() -> None:
    assert feedback.first_sentence("Wiersze: 15 MD, SUMA: 22 MD. Rada.") == (
        "Wiersze: 15 MD, SUMA: 22 MD"
    )
    assert feedback.first_sentence("  ") is None


# ── Termin ──────────────────────────────────────────────────────────────────


def test_due_first_now_then_every_n_business_days() -> None:
    monday = date(2026, 11, 23)
    assert feedback.due(None, monday, 3)
    assert not feedback.due(monday, monday, 3)
    assert not feedback.due(monday, date(2026, 11, 25), 3)  # wt., śr.
    assert feedback.due(monday, date(2026, 11, 26), 3)  # wt., śr., czw.
    # Weekend się nie liczy: pt. → pon. to jeden dzień roboczy.
    assert not feedback.due(date(2026, 11, 27), date(2026, 11, 30), 2)


def test_months_for_watches_two_previous_months() -> None:
    assert feedback.months_for(date(2026, 1, 5)) == ["2025-12", "2025-11"]


# ── Adresat ─────────────────────────────────────────────────────────────────

ON_ALL = Settings(mode="on", external="all")
ON_PANEL = Settings(mode="on", external="panel")
ON_INTERNAL = Settings(mode="on", external="off")
WHO = Who(consultant_email="anna@example.com", owner=OWNER, panel_open=False)


def _target(code: str, found: Found, who: Who, settings: Settings):
    return feedback.target_for(feedback.BY_CODE[code], found, who, settings)[0]


def test_consultant_defect_goes_to_consultant_with_owner_in_copy() -> None:
    target = _target("proof.signed_pdf", Found("proof.signed_pdf"), WHO, ON_ALL)
    assert (target.kind, target.address, target.cc) == (
        "consultant",
        "anna@example.com",
        "opiekun@example.com",
    )


@pytest.mark.parametrize(
    ("settings", "why"), [(ON_INTERNAL, "external_off"), (ON_PANEL, "panel_closed")]
)
def test_without_external_mail_owner_gets_it_to_pass_on(
    settings: Settings, why: str
) -> None:
    target = _target("proof.signed_pdf", Found("proof.signed_pdf"), WHO, settings)
    assert (target.kind, target.user_id, target.why) == ("owner", 7, why)


def test_no_owner_and_no_mail_is_logged_without_recipient() -> None:
    who = Who(consultant_email="", owner=None, panel_open=True)
    target = _target("proof.signed_pdf", Found("proof.signed_pdf"), who, ON_ALL)
    assert (target.kind, target.why) == ("none", "no_email")


def test_acceptor_gets_reminder_with_consultant_in_copy() -> None:
    found = Found("accept.no_reply", acceptor="kierownik@bank.example")
    target = _target("accept.no_reply", found, WHO, ON_ALL)
    assert (target.kind, target.address, target.cc) == (
        "client",
        "kierownik@bank.example",
        "anna@example.com",
    )


def test_acceptor_unknown_falls_back_to_consultant_instruction() -> None:
    defect = feedback.BY_CODE["accept.no_reply"]
    target, instruction = feedback.target_for(
        defect, Found("accept.no_reply"), WHO, ON_ALL
    )
    assert (target.kind, target.why) == ("consultant", "no_acceptor")
    assert instruction == defect.consultant_instruction


def test_owner_defect_never_leaves_the_company() -> None:
    target = _target("amount.protocol", Found("amount.protocol"), WHO, ON_ALL)
    assert (target.kind, target.user_id) == ("owner", 7)
    no_owner = Who(consultant_email="anna@example.com", owner=None, panel_open=True)
    target = _target("amount.protocol", Found("amount.protocol"), no_owner, ON_ALL)
    assert target.kind == "none"


# ── Treść ───────────────────────────────────────────────────────────────────


def _item(code: str, found: Found, instruction: str | None = None) -> feedback.Item:
    defect = feedback.BY_CODE[code]
    return feedback.Item(1, defect, found, instruction or defect.instruction)


def test_consultant_mail_says_what_is_wrong_and_how_to_fix() -> None:
    target = feedback.Target("consultant", address="anna@example.com")
    subject, text = feedback.compose_mail(
        target,
        CTX,
        [
            _item(
                "fields.rows_sum",
                Found("fields.rows_sum", "Wiersze: 15 MD, SUMA: 22 MD"),
            ),
            _item("proof.signed_pdf", Found("proof.signed_pdf")),
        ],
        ADDRESS,
        reminder=False,
    )
    assert subject == "Rozliczenie za październik 2026: 2 rzeczy do poprawy"
    assert "Wiersze: 15 MD, SUMA: 22 MD" in text
    assert "kwalifikowanym podpisem elektronicznym" in text
    assert "popraw" in text.lower() and ADDRESS in text
    assert "zł" not in text


def test_reminder_subject_and_single_defect() -> None:
    target = feedback.Target("consultant", address="anna@example.com")
    subject, text = feedback.compose_mail(
        target,
        CTX,
        [_item(feedback.IMAGE_REPORT, Found(feedback.IMAGE_REPORT, private=True))],
        ADDRESS,
        reminder=True,
    )
    assert (
        subject
        == "Przypomnienie: Rozliczenie za październik 2026: raport godzin jako zdjęcie"
    )
    assert "z adresu firmowego, nie z prywatnej skrzynki" in text


def test_client_mail_asks_for_reply() -> None:
    target = feedback.Target("client", address="kierownik@bank.example")
    subject, text = feedback.compose_mail(
        target,
        CTX,
        [_item("accept.no_reply", Found("accept.no_reply"))],
        ADDRESS,
        reminder=False,
    )
    assert subject == "Akceptacja czasu pracy za październik 2026: Anna Przykładowa"
    assert "„Akceptuję”" in text and ADDRESS in text


def test_owner_bell_passes_consultant_defects_on_without_amounts() -> None:
    target = feedback.Target("owner", user_id=7)
    title, message = feedback.compose_bell(
        target,
        CTX,
        [
            _item("amount.protocol", Found("amount.protocol")),
            _item("proof.signed_pdf", Found("proof.signed_pdf")),
        ],
        ADDRESS,
    )
    assert title == "Rozliczenie październik 2026: Anna Przykładowa, Bank Przykładowy"
    assert "Przekaż konsultantowi: PDF z RCP bez podpisu elektronicznego" in message
    assert "protokołu klienta" in message
    assert "zł" not in message


# ── Adres akceptującego z prośby (PKO) ─────────────────────────────────────


def test_request_recipients_only_client_domain_without_consultant() -> None:
    mail = mail_text.Mail(
        subject="Prośba o akceptację TS za 10-2026",
        sender="anna@bank.example",
        to="Kierownik <kierownik@bank.example>, rozliczenia@b2b.example",
        cc="anna@bank.example",
        body="Proszę o akceptację 168 h.\nDo: druga.osoba@bank.example",
    )
    senders = mail_text.Senders(
        client=frozenset({"bank.example"}), consultant=frozenset({"anna@bank.example"})
    )
    assert mail_text.request_recipients(mail, senders) == (
        "kierownik@bank.example",
        "druga.osoba@bank.example",
    )


def test_no_reply_verdict_carries_acceptors() -> None:
    mail = mail_text.Mail(
        subject="Prośba o akceptację czasu pracy za październik 2026",
        sender="anna@konsultant.example",
        to="kierownik@bank.example",
        body="Proszę o akceptację 168 h za październik 2026.",
    )
    verdict = mail_text.judge(
        [mail],
        month="2026-10",
        hours=None,
        md=None,
        senders=mail_text.Senders(client=frozenset({"bank.example"})),
    )
    assert verdict.title == "Mail bez odpowiedzi akceptującego"
    assert verdict.acceptors == ("kierownik@bank.example",)


# ── Przypomnienie o brakującej deklaracji (mLeasing 438 X) ─────────────────


def test_missing_declaration_reminder_asks_for_sentence_not_file() -> None:
    subject, text = reminders.compose(
        "2026-09", "Leasing Przykładowy", ADDRESS, declaration=True
    )
    assert subject == "Deklaracja dni pracy za wrzesień 2026: prosimy o przesłanie"
    assert "„We wrześniu nie miałam/em dni wolnych”" in text
    assert "zrzut" not in text
    plain = reminders.compose("2026-09", "Bank", ADDRESS)[1]
    assert "raport z akceptacją klienta" in plain
    title, message = reminders.bell_text(
        "2026-10", "Leasing Przykładowy", ["Anna"], declaration=True
    )
    assert "deklaracji dni pracy" in message
