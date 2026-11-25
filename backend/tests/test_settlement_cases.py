"""Karta sprawy rozliczenia bez bazy: kto działa, terminy, adresat, telefon,
skrypt i treść. Uwagi jak w rozliczeniach z próby IX–X; dane fikcyjne.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from app.services.client_settlements import cases, feedback, order_issues, reminders
from app.services.client_settlements.cases import Done

MONTH = "2026-10"
ADDRESS = "rozliczenia@example.com"
CTX = feedback.Context(
    contract_id=1,
    client_id=2,
    client_name="Bank Przykładowy",
    person="Anna Przykładowa",
    month=MONTH,
    settlement_id=3,
)
OWNER = reminders.Owner(
    user_id=7, name="Opiekun", email="opiekun@example.com", source="contract_care"
)
SIGNED_PDF = {
    "rule": "proof.signed_pdf",
    "state": "fail",
    "title": "PDF bez podpisu elektronicznego",
    "detail": None,
}
NO_REPLY = {
    "rule": "proof.accept_has_hours",
    "state": "fail",
    "title": "Mail bez odpowiedzi akceptującego",
    "detail": "Jest prośba o akceptację, ale nie ma potwierdzenia.",
    "acceptors": ["kierownik@bank-przykladowy.example"],
}
MD_OVER = {
    "rule": "order.md_over",
    "state": "warn",
    "title": "Ponad zamówienie o 2 MD",
    "detail": "Zejdzie 19 MD (tyle zostało) i tyle idzie do faktury.",
}
LINE_RATE = {
    "rule": "order.line_rate",
    "state": "warn",
    "title": "Stawka linii zamówienia PO-7: 1 234 zł/MD",
    "detail": "Kontrakt: 1 200 zł/MD.",
}
LIMIT = {
    "rule": "fields.md_month_limit",
    "state": "warn",
    "title": "MD ponad dni robocze miesiąca",
    "detail": "23 MD przy 22 dniach roboczych.",
}


def _checks(*checks: dict) -> list[dict]:
    return [{"title": "RCP", "checks": list(checks)}, {"remaining_after": "0"}]


def _classify(*checks: dict, status: str = "warnings", **kwargs):
    return cases.classify(status=status, checks=_checks(*checks), month=MONTH, **kwargs)


# ── Kto działa ──────────────────────────────────────────────────────────────


def test_brak_podpisu_pdf_to_sprawa_konsultanta() -> None:
    out = _classify(SIGNED_PDF)
    assert list(out) == [cases.CONSULTANT]
    (reason,) = out[cases.CONSULTANT]
    assert reason.code == "proof.signed_pdf"
    assert reason.title == "PDF z RCP bez podpisu elektronicznego"


def test_brak_odpowiedzi_akceptujacego_to_sprawa_klienta_z_adresem() -> None:
    out = _classify(NO_REPLY)
    assert list(out) == [cases.CLIENT]
    (reason,) = out[cases.CLIENT]
    assert reason.code == feedback.ACCEPT_NO_REPLY
    assert reason.found.acceptor == "kierownik@bank-przykladowy.example"


def test_ponad_zamowienie_to_sprawa_dl_bez_kwot() -> None:
    issue = order_issues.OrderIssue(order_issues.OVER, 11, "PO-1", Decimal("2.000"))
    out = _classify(MD_OVER, issues=[issue])
    assert list(out) == [cases.DL]
    (reason,) = out[cases.DL]
    assert reason.title == "2 MD ponad pulę zamówienia PO-1"
    assert "zł" not in reason.title + (reason.detail or "")


def test_ponad_zamowienie_bez_zapisanego_problemu_bierze_uwage() -> None:
    out = _classify(MD_OVER)
    assert [r.title for r in out[cases.DL]] == ["Ponad zamówienie o 2 MD"]


def test_stawka_linii_dla_dl_bez_kwot_z_tytulu_uwagi() -> None:
    mismatch = {"order_id": 12, "number": "PO-7", "contract": True, "invoice": True}
    out = _classify(LINE_RATE, mismatches=[mismatch])
    (reason,) = out[cases.DL]
    assert (
        reason.title
        == "Stawka linii zamówienia PO-7 inna niż kontrakt i ostatnia faktura"
    )
    assert "zł" not in reason.title + (reason.detail or "")
    fallback = _classify(LINE_RATE)
    assert "zł" not in fallback[cases.DL][0].title


def test_linia_bez_stawki_i_brak_linii_to_sprawy_dl() -> None:
    out = _classify(
        {"state": "warn", "title": "Linia zamówienia bez stawki MD", "detail": "x"},
        {"state": "fail", "title": "Brak linii zamówienia w tym miesiącu"},
        order_number="PO-3",
    )
    codes = [r.code for r in out[cases.DL]]
    assert codes == [cases.NO_RATE, cases.NO_LINE]
    assert out[cases.DL][0].title == "Linia zamówienia PO-3 bez stawki MD"
    assert out[cases.DL][1].title == "Brak linii zamówienia na październik 2026"


def test_informacja_bez_poprawki_to_nie_sprawa(monkeypatch) -> None:
    # Kosmetyka przy dobrym MD (``Defect.notice``) idzie „na przyszłość”, bez gonienia.
    notice = SimpleNamespace(
        code="note.rows_sum", audience=feedback.CONSULTANT, title="Info", notice=True
    )
    monkeypatch.setitem(feedback.BY_CODE, "note.rows_sum", notice)
    monkeypatch.setattr(
        feedback, "defects_in", lambda **_: [feedback.Found("note.rows_sum")]
    )
    assert (
        _classify({"state": "ok", "title": "Wiersze", "notice": "note.rows_sum"}) == {}
    )


def test_uwaga_spoza_katalogu_to_decyzja_finansow() -> None:
    out = _classify(LIMIT)
    assert list(out) == [cases.FINANCE]
    assert out[cases.FINANCE][0].title == "MD ponad dni robocze miesiąca"


def test_kilka_osob_dziala_naraz_w_stalej_kolejnosci() -> None:
    issue = order_issues.OrderIssue(order_issues.OVER, 11, "PO-1", Decimal("2"))
    out = _classify(LIMIT, MD_OVER, NO_REPLY, SIGNED_PDF, issues=[issue])
    assert list(out) == [cases.CONSULTANT, cases.CLIENT, cases.DL, cases.FINANCE]


def test_nieodczytany_plik_bez_uwag_to_sprawa_finansow() -> None:
    out = cases.classify(
        status="checking",
        checks=[
            {
                "title": "RCP",
                "checks": [{"state": "none", "title": "Czeka na liczbę MD"}],
            }
        ],
        month=MONTH,
    )
    assert [r.code for r in out[cases.FINANCE]] == [cases.UNREAD]


def test_nieodczytany_plik_u_klienta_z_raportem_t4t_to_nie_sprawa() -> None:
    # Nordea: MD przyjdą z raportu klienta, plik konsultanta nie jest raportem.
    out = cases.classify(
        status="checking",
        checks=[
            {
                "title": "RCP",
                "checks": [{"state": "none", "title": "Czeka na liczbę MD"}],
            }
        ],
        month=MONTH,
        consultant_reports=False,
    )
    assert out == {}


def test_bez_uwag_i_przyjete_nie_maja_sprawy() -> None:
    # Samozamknięcie: przyjęcie albo nowy plik bez wady zdejmuje sprawę.
    assert _classify(SIGNED_PDF, status="accepted") == {}
    assert _classify(SIGNED_PDF, status="ok") == {}
    assert _classify({"state": "ok", "title": "Podpis ważny"}) == {}


def test_do_poprawy_od_finansow_to_sprawa_konsultanta() -> None:
    out = cases.classify(
        status="needs_fix", checks=[], month=MONTH, fix_reason="Brak podpisu klienta."
    )
    assert [r.code for r in out[cases.CONSULTANT]] == [feedback.NEEDS_FIX]


# ── Terminy ─────────────────────────────────────────────────────────────────

MONDAY = date(2026, 11, 2)


def test_plan_dzien_0_plus_3_5_7_dni_roboczych_z_swietem() -> None:
    steps = cases.schedule(MONDAY, MONDAY, {})
    assert [(s.key, s.due) for s in steps] == [
        (cases.MAIL, date(2026, 11, 2)),
        (cases.REMINDER, date(2026, 11, 5)),
        (cases.CALL, date(2026, 11, 9)),
        # 11.11 to święto: +7 dni roboczych wypada w czwartek 12.11.
        (cases.ESCALATION, date(2026, 11, 12)),
    ]
    assert [s.state for s in steps] == [
        cases.TODAY,
        cases.PLANNED,
        cases.PLANNED,
        cases.PLANNED,
    ]


def test_dzien_0_w_weekend_przechodzi_na_poniedzialek() -> None:
    steps = cases.schedule(date(2026, 10, 31), date(2026, 10, 31), {})
    assert steps[0].due == MONDAY
    assert steps[0].state == cases.UPCOMING


def test_zalegly_mail_i_kolejne_kroki_liczone_od_dzis() -> None:
    today = date(2026, 11, 25)
    steps = cases.schedule(MONDAY, today, {})
    assert steps[0].state == cases.OVERDUE
    assert steps[1].due == date(2026, 11, 30)
    assert steps[2].due == date(2026, 12, 2)
    assert steps[3].due == date(2026, 12, 4)
    assert cases.business_days_between(steps[0].due, today) == 16


def test_krok_zrobiony_pozniej_przesuwa_nastepne() -> None:
    done = {cases.MAIL: Done(on=date(2026, 11, 4))}
    steps = cases.schedule(MONDAY, date(2026, 11, 4), done)
    assert steps[0].state == cases.DONE
    assert steps[1].due == date(2026, 11, 9)
    assert steps[1].state == cases.UPCOMING
    assert cases.current_step(steps).key == cases.REMINDER


def test_telefon_przed_przypomnieniem_nie_przyspiesza_eskalacji() -> None:
    # Przeklikanie 25.11: mail i telefon tego samego dnia, przypomnienie za 3 dni.
    today = date(2026, 11, 25)
    done = {cases.MAIL: Done(on=today), cases.CALL: Done(on=today)}
    steps = cases.schedule(MONDAY, today, done)
    by_key = {s.key: s for s in steps}
    assert by_key[cases.REMINDER].due == date(2026, 11, 30)
    assert by_key[cases.REMINDER].state == cases.UPCOMING
    assert by_key[cases.ESCALATION].due == date(2026, 12, 2)
    assert by_key[cases.ESCALATION].due > by_key[cases.REMINDER].due


def test_wszystko_zrobione_nie_ma_biezacego_kroku() -> None:
    done = {key: Done(on=MONDAY) for key, _ in cases.PLAN}
    assert cases.current_step(cases.schedule(MONDAY, MONDAY, done)) is None


def test_finanse_maja_jeden_krok_decyzji() -> None:
    steps = cases.schedule(MONDAY, date(2026, 11, 10), {}, cases.FINANCE_PLAN)
    assert [(s.key, s.due, s.state) for s in steps] == [
        (cases.DECISION, date(2026, 11, 5), cases.OVERDUE)
    ]


def test_mail_zalicza_pierwszy_krok_potem_przypomnienie() -> None:
    assert cases.next_mail_step({}) == cases.MAIL
    assert cases.next_mail_step({cases.MAIL: Done(MONDAY)}) == cases.REMINDER
    both = {cases.MAIL: Done(MONDAY), cases.REMINDER: Done(MONDAY)}
    assert cases.next_mail_step(both) == cases.EXTRA


def _entry(on: date, step: str, *, action: str = cases.ACTION_MAIL, **details):
    return cases.LogEntry(
        at=datetime(on.year, on.month, on.day, 10, tzinfo=timezone.utc),
        action=action,
        actor=details.pop("actor", cases.CONSULTANT),
        step=step,
        by="Back office",
        details=details,
    )


def test_slad_liczy_tylko_udane_kroki_tej_osoby_od_dnia_0() -> None:
    entries = [
        _entry(date(2026, 10, 30), cases.MAIL, outcome="sent"),  # sprzed dnia 0
        _entry(MONDAY, cases.MAIL, outcome="failed"),
        _entry(date(2026, 11, 3), cases.MAIL, outcome="sent"),
        _entry(date(2026, 11, 3), cases.MAIL, outcome="sent", actor=cases.DL),
        _entry(
            date(2026, 11, 9), cases.CALL, action=cases.ACTION_CALL, result="no_answer"
        ),
    ]
    done = cases._done_from_log(entries, cases.CONSULTANT, MONDAY)
    assert done[cases.MAIL].on == date(2026, 11, 3)
    assert done[cases.CALL].note == "nie odebrał(a)"
    assert cases.REMINDER not in done


# ── Adresat, mail, telefon, skrypt ──────────────────────────────────────────


def _row(**kwargs):
    base = dict(
        s=SimpleNamespace(id=3, client_id=2, contract_id=1, period_month=MONTH),
        client_name=CTX.client_name,
        person=CTX.person,
        consultant_email="anna@example.com",
        consultant_phone="+48 600 000 001",
        consultant_phone_source="z kontraktu",
        pm_contact_id=None,
        contract_owner=7,
        client_owner=None,
        report_mime="application/pdf",
        report_sender=None,
        report_at=None,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def _case(actor: str, reasons, *, done=None) -> cases.Case:
    return cases.Case(
        settlement_id=3,
        contract_id=1,
        client_id=2,
        client_name=CTX.client_name,
        person=CTX.person,
        month=MONTH,
        status="warnings",
        actor=actor,
        reasons=reasons,
        day0=MONDAY,
        steps=cases.schedule(MONDAY, MONDAY, done or {}),
        today=MONDAY,
    )


def _user(uid: int, name: str, email: str):
    return SimpleNamespace(id=uid, name=name, email=email)


USERS = {
    7: _user(7, "Opiekun", "opiekun@example.com"),
    9: _user(9, "DL", "dl@example.com"),
}


def _fill(case, row, *, owner=OWNER, lead=None, by_mail=None, done=None, phones=None):
    cases._fill_contact(
        case,
        row,
        ctx=CTX,
        owner=owner,
        lead=lead,
        users=USERS,
        phones=phones or {},
        by_mail=by_mail or {},
        by_id={},
        address=ADDRESS,
        done=done or {},
    )
    return case


def test_mail_do_konsultanta_z_opiekunem_w_kopii_i_numerem() -> None:
    reasons = _classify(SIGNED_PDF)[cases.CONSULTANT]
    case = _fill(_case(cases.CONSULTANT, reasons), _row())
    assert case.recipient.kind == feedback.CONSULTANT
    assert (case.mail.to, case.mail.cc) == ("anna@example.com", "opiekun@example.com")
    assert case.mail.subject == (
        "Rozliczenie za październik 2026: pdf z rcp bez podpisu elektronicznego"
    )
    assert "zł" not in case.mail.text
    assert case.phones[0].as_dict() == {
        "who": "Konsultant",
        "name": CTX.person,
        "number": "+48 600 000 001",
        "source": "z kontraktu",
    }
    assert 2 <= len(case.script) <= 4
    assert "październik 2026" in case.script[0]
    # Eskalacja do opiekuna (DL/KAM).
    assert case.escalation_mail.to == "opiekun@example.com"
    assert case.escalation_mail.subject.startswith(
        "Eskalacja: rozliczenie za październik 2026"
    )


def test_przypomnienie_po_pierwszym_mailu() -> None:
    reasons = _classify(SIGNED_PDF)[cases.CONSULTANT]
    done = {cases.MAIL: Done(on=MONDAY, by="Back office")}
    case = _fill(_case(cases.CONSULTANT, reasons, done=done), _row(), done=done)
    assert case.mail.subject.startswith("Przypomnienie: ")
    assert case.mail_step == cases.REMINDER
    assert "02.11" in case.script[-1]


def test_brak_numeru_konsultanta_to_jawne_brak() -> None:
    reasons = _classify(SIGNED_PDF)[cases.CONSULTANT]
    case = _fill(
        _case(cases.CONSULTANT, reasons),
        _row(consultant_phone=None, consultant_phone_source=None),
    )
    assert case.phones[0].number is None


def test_bez_adresu_konsultanta_piszemy_do_opiekuna() -> None:
    reasons = _classify(SIGNED_PDF)[cases.CONSULTANT]
    case = _fill(_case(cases.CONSULTANT, reasons), _row(consultant_email=None))
    assert case.recipient.kind == "owner"
    assert case.recipient.why == "no_email"
    assert case.mail.to == "opiekun@example.com"
    assert "Przekaż konsultantowi" in case.mail.text
    # Eskalacja nie wraca do tej samej osoby.
    assert (
        case.escalation_mail is None or case.escalation_mail.to != "opiekun@example.com"
    )


def test_bez_adresu_konsultanta_i_opiekuna_brak_adresata() -> None:
    reasons = _classify(SIGNED_PDF)[cases.CONSULTANT]
    case = _fill(
        _case(cases.CONSULTANT, reasons),
        _row(consultant_email=None, contract_owner=None),
        owner=None,
    )
    assert case.recipient.kind == "none"
    assert case.mail is None


def test_akceptujacy_dostaje_mail_konsultant_w_kopii_telefon_z_kontaktow() -> None:
    reasons = _classify(NO_REPLY)[cases.CLIENT]
    contact = SimpleNamespace(name="Kierownik Przykładowy", phone=None)
    case = _fill(
        _case(cases.CLIENT, reasons),
        _row(),
        by_mail={(2, "kierownik@bank-przykladowy.example"): contact},
    )
    assert case.recipient.kind == feedback.CLIENT
    assert (case.mail.to, case.mail.cc) == (
        "kierownik@bank-przykladowy.example",
        "anna@example.com",
    )
    assert (
        case.mail.subject
        == "Akceptacja czasu pracy za październik 2026: Anna Przykładowa"
    )
    acceptor, consultant = case.phones
    # Brak numeru w kontaktach klienta = jawne „brak”, a konsultant jako drugi kontakt.
    assert (acceptor.who, acceptor.name, acceptor.number) == (
        "Akceptujący u klienta",
        "Kierownik Przykładowy",
        None,
    )
    assert consultant.number == "+48 600 000 001"


def test_bez_adresu_akceptujacego_konsultant_ma_dopytac() -> None:
    check = {**NO_REPLY, "acceptors": []}
    reasons = _classify(check)[cases.CLIENT]
    case = _fill(_case(cases.CLIENT, reasons), _row())
    assert case.recipient.kind == feedback.CONSULTANT
    assert case.recipient.why == "no_acceptor"
    assert "Poproś go o odpowiedź" in case.mail.text
    assert case.phones[0].number is None  # akceptujący bez adresu i numeru


def test_sprawa_dl_mail_do_dl_klienta_eskalacja_do_opiekuna() -> None:
    issue = order_issues.OrderIssue(order_issues.OVER, 11, "PO-1", Decimal("2"))
    reasons = _classify(MD_OVER, issues=[issue])[cases.DL]
    case = _case(cases.DL, reasons)
    _fill(case, _row(client_owner=7), lead=USERS[9], phones={9: "+48 600 000 009"})
    assert (case.recipient.label, case.mail.to) == (
        "Delivery Lead klienta",
        "dl@example.com",
    )
    assert "2 MD ponad pulę zamówienia PO-1" in case.mail.text
    assert "zł" not in case.mail.text
    assert case.phones[0].number == "+48 600 000 009"
    assert case.escalation_to.label == "Opiekun klienta"
    assert case.escalation_mail.to == "opiekun@example.com"


def test_sprawa_dl_bez_numeru_w_profilu() -> None:
    issue = order_issues.OrderIssue(order_issues.OVER, 11, "PO-1", Decimal("2"))
    case = _case(cases.DL, _classify(MD_OVER, issues=[issue])[cases.DL])
    _fill(case, _row(), lead=USERS[9])
    assert case.phones[0].number is None


def test_finanse_bez_maila_i_telefonu() -> None:
    reasons = _classify(LIMIT)[cases.FINANCE]
    case = _case(cases.FINANCE, reasons)
    payload = case.as_dict()
    assert (
        payload["mail"] is None and payload["phones"] == [] and payload["script"] == []
    )


def test_lista_bez_tresci_maili() -> None:
    reasons = _classify(SIGNED_PDF)[cases.CONSULTANT]
    case = _fill(_case(cases.CONSULTANT, reasons), _row())
    light = case.as_dict(full=False)
    assert "mail" not in light and "script" not in light
    assert light["actor_label"] == "Konsultant"
    assert light["current"]["key"] == cases.MAIL


def test_instrukcja_z_nowym_polem_nie_wywraca_karty() -> None:
    found = feedback.Found("x")
    text = cases.instruction_text("Za {month}: {nowe_pole}.", CTX, found, ADDRESS)
    assert text == "Za październik 2026: ."


def test_reczny_mail_odpowiedz_na_adres_rozliczen(monkeypatch) -> None:
    from app.core.config import settings
    from app.services.care.announcement_mail import GraphMailer, SimulatedMailer
    from app.services.consultant_portal import portal_mail

    monkeypatch.setattr(settings, "CONSULTANT_PORTAL_SETTLEMENTS_ADDRESSES", ADDRESS)
    monkeypatch.setattr(settings, "CONSULTANT_PORTAL_MAILBOX", "wsparcie@example.com")
    monkeypatch.setattr(
        portal_mail, "default_mailer", lambda: GraphMailer("wsparcie@example.com")
    )
    mailer = cases.default_mailer()
    assert isinstance(mailer, GraphMailer)
    assert mailer._reply_to == ADDRESS
    # Symulacja i brak nadawcy zostają bez zmian (nic nie wychodzi).
    simulated = SimulatedMailer()
    monkeypatch.setattr(portal_mail, "default_mailer", lambda: simulated)
    assert cases.default_mailer() is simulated
    monkeypatch.setattr(portal_mail, "default_mailer", lambda: None)
    assert cases.default_mailer() is None
