"""Deklaracja konsultanta w treści maila jako raport (reguła ``report.consultant_declaration``).

Decyzja Artura z 23.11.2026, „Deklaracja wystarcza”: u klienta bez pliku godzin
konsultantka pisze w mailu z fakturą „We wrześniu nie miałam dni wolnych”, a Finanse
fakturują pełny miesiąc (IX 2026: 22 dni robocze = 22 MD). Dotąd silnik czytał z `.eml`
tylko akceptację NN, więc taki mail nie dawał MD. Osoby, adresy i treści fikcyjne.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from email.message import EmailMessage

from app.models.consultant_portal import CpDocument
from app.services.client_settlements import mail_declaration
from app.services.client_settlements import rules_catalog as catalog
from app.services.client_settlements import service

EML = "message/rfc822"
SEPTEMBER = "2026-09"
#: IX 2026 i X 2026 mają po 22 dni robocze.
WORKING_DAYS = 22

EXAMPLE = """Dzień dobry,

Fakturę przesłałam przez KSeF. We wrześniu nie miałam dni wolnych.

Pozdrawiam
Anna Testowa
"""


def _rules(level: str = "warn") -> dict:
    return catalog.effective({mail_declaration.RULE: {"level": level, "params": {}}})


def _eml(body: str, subject: str = "Faktura wrzesień") -> bytes:
    message = EmailMessage()
    message["From"] = "Anna Testowa <anna.testowa@firma.example.com>"
    message["To"] = "rozliczenia@firma.example.com"
    message["Subject"] = subject
    message.set_content(body)
    return message.as_bytes()


def _evaluate(text: str, month: str = SEPTEMBER):
    parsed = mail_declaration.parse_text(text, month)
    assert parsed is not None
    return mail_declaration.evaluate(
        parsed, month=month, rules=_rules(), working_days=WORKING_DAYS
    )


def _titles(result) -> dict[str, str]:
    return {c["title"]: c["state"] for g in result.groups for c in g["checks"]}


def _read(
    body: str,
    *,
    rules: dict | None = None,
    from_consultant: bool = True,
    month: str = SEPTEMBER,
):
    doc = CpDocument(id=7, mime=EML, kind="report", file_path="x.eml")
    return asyncio.run(
        service._read_file(
            doc,
            _eml(body),
            reports=[doc],
            month=month,
            person_name="Anna Testowa",
            rules=rules if rules is not None else _rules(),
            other_md=Decimal("0"),
            working_days=WORKING_DAYS,
            consultant_mails=frozenset({7}) if from_consultant else frozenset(),
        )
    )


# ── Silnik czyta mail konsultanta ────────────────────────────────────────────


def test_mail_jak_w_probie_daje_pelny_miesiac():
    result = _read(EXAMPLE)
    assert result is not None
    assert result.md_regular == Decimal("22")
    assert result.md_extra == Decimal("0")
    assert not result.blocking and not result.warn
    assert (
        _titles(result)["Deklaracja w treści maila: bez dni wolnych (wrzesień 2026)"]
        == "ok"
    )


def test_bez_reguly_u_klienta_mail_nie_daje_md():
    assert _read(EXAMPLE, rules=_rules("off")) is None
    assert _read(EXAMPLE, rules=catalog.effective(None)) is None


def test_nadawca_spoza_kontraktu_nie_daje_md():
    assert _read(EXAMPLE, from_consultant=False) is None


def test_mail_bez_deklaracji_to_nie_dowod():
    assert _read("Dzień dobry, faktura poszła przez KSeF.") is None


# ── Odczyt zdania ────────────────────────────────────────────────────────────


def test_liczba_dni_wolnych_odejmuje_od_dni_roboczych():
    result = _evaluate("W październiku miałam 2 dni wolnego.", "2026-10")
    assert result.md_regular == Decimal("20")
    detail = next(c["detail"] for g in result.groups for c in g["checks"])
    assert detail == "22 dni roboczych − 2 = 20 MD."


def test_liczba_slowem_i_dzien_wolny():
    assert _evaluate("We wrześniu miałem jeden dzień wolny.").md_regular == Decimal(
        "21"
    )
    assert _evaluate("We wrześniu miałem 3 dni urlopu.").md_regular == Decimal("19")


def test_inne_formy_pelnego_miesiaca_i_bez_ogonkow():
    for text in (
        "We wrzesniu nie mialam dni wolnych",
        "Wrzesień bez dni wolnych.",
        "Za wrzesień pełny miesiąc.",
        "We wrześniu nie miałem żadnych dni wolnych.",
        "WRZESIEŃ 2026: nie miałam wolnego.",
    ):
        assert _evaluate(text).md_regular == Decimal("22"), text


def test_miesiac_inny_niz_rozliczany_bez_md():
    result = _evaluate("W sierpniu nie miałam dni wolnych.")
    assert result.md_regular is None
    assert "Deklaracja konsultanta za inny miesiąc" in _titles(result)


def test_rok_inny_niz_rozliczany_bez_md():
    result = _evaluate("We wrześniu 2025 nie miałam dni wolnych.")
    assert result.md_regular is None
    assert "Deklaracja konsultanta za inny miesiąc" in _titles(result)


def test_deklaracja_bez_nazwy_miesiaca_do_czlowieka():
    result = _evaluate("Nie miałam dni wolnych.")
    assert result.md_regular is None
    assert result.warn
    assert _titles(result)["Deklaracja bez nazwy miesiąca"] == "warn"


def test_przeczenie_miala_dni_wolne_do_czlowieka():
    result = _evaluate("We wrześniu miałam dni wolne.")
    assert result.md_regular is None
    assert _titles(result)["Deklaracja bez liczby dni wolnych"] == "warn"


def test_nieobecnosc_obok_deklaracji_do_czlowieka():
    for text in (
        "We wrześniu nie miałam dni wolnych, ale 3 dni byłam na L4.",
        "We wrześniu nie miałam dni wolnych. We wrześniu miałam 2 dni wolnego.",
        "We wrześniu nie miałam 2 dni wolnego.",
    ):
        result = _evaluate(text)
        assert result.md_regular is None, text
        assert result.warn, text


def test_zdania_z_recenzji_nie_daja_md():
    """Fałszywe MD to złe pieniądze: każde z tych zdań idzie do Finansów."""

    for text, month in (
        ("We wrześniu miałam 0,5 dnia wolnego.", SEPTEMBER),
        ("We wrześniu miałam 2,5 dnia wolnego.", SEPTEMBER),
        ("We wrześniu nie przepracowałam pełnego miesiąca.", SEPTEMBER),
        ("We wrześniu pełny miesiąc nie był możliwy.", SEPTEMBER),
        ("Nie miałam dni wolnych, pozdrawiam Marta", "2026-03"),
        ("Nie miałam dni wolnych. Pozdrawiam, Maja", "2026-05"),
        ("We wrześniu nie miałam dni wolnych, byłam chora.", SEPTEMBER),
        ("We wrześniu nie miałam dni wolnych, pracowałam 15 dni.", SEPTEMBER),
        ("We wrześniu będę miała 2 dni wolnego.", SEPTEMBER),
        ("Czy we wrześniu 5 dni wolnego?", SEPTEMBER),
    ):
        parsed = mail_declaration.parse_text(text, month)
        assert parsed is not None, text
        assert parsed.days_off is None, text
        result = mail_declaration.evaluate(
            parsed, month=month, rules=_rules(), working_days=WORKING_DAYS
        )
        assert result.md_regular is None, text
        assert result.warn, text


def test_przecinek_po_innym_zdaniu_nie_psuje_deklaracji():
    text = "Fakturę przesłałam przez KSeF, we wrześniu nie miałam dni wolnych."
    assert _evaluate(text).md_regular == Decimal("22")
    assert (
        _evaluate("Przepracowałam cały wrzesień 2026 r., bez dni wolnych.").md_regular
        is None
    )
    assert _evaluate("Przepracowałam pełny miesiąc we wrześniu.").md_regular == Decimal(
        "22"
    )


def test_wiecej_dni_wolnych_niz_roboczych_do_czlowieka():
    result = _evaluate("We wrześniu miałam 30 dni urlopu.")
    assert result.md_regular is None
    assert result.warn


def test_cytowany_watek_nie_jest_deklaracja():
    text = (
        "Przesyłam fakturę.\n\nOd: Anna Testowa\nTemat: Faktura sierpień\n"
        "W sierpniu nie miałam dni wolnych.\n"
    )
    assert mail_declaration.parse_text(text, SEPTEMBER) is None
    quoted = "Przesyłam fakturę.\n> We wrześniu nie miałam dni wolnych.\n"
    assert mail_declaration.parse_text(quoted, SEPTEMBER) is None


def test_zdanie_bez_deklaracji_nie_psuje_odczytu():
    text = "Proszę o wolny termin rozmowy. We wrześniu nie miałam dni wolnych."
    assert _evaluate(text).md_regular == Decimal("22")


def test_md_ponad_dni_robocze_z_innymi_klientami_ostrzega():
    rules = catalog.effective(
        {
            mail_declaration.RULE: {"level": "warn", "params": {}},
            "fields.md_month_limit": {"level": "warn", "params": {}},
        }
    )
    parsed = mail_declaration.parse_text(EXAMPLE, SEPTEMBER)
    result = mail_declaration.evaluate(
        parsed,
        month=SEPTEMBER,
        rules=rules,
        working_days=WORKING_DAYS,
        other_md=Decimal("5"),
    )
    assert result.md_regular == Decimal("22")
    assert result.warn


# ── Katalog reguł ────────────────────────────────────────────────────────────


def test_regula_domyslnie_wylaczona_nawet_przy_zapisanym_zestawie():
    """Zestaw zapisany przed tą regułą nie włącza jej sam: działa tylko u klienta,
    który ma ją w zestawie na miesiąc."""

    assert catalog.RULES[mail_declaration.RULE].level == "off"
    assert catalog.effective({})[mail_declaration.RULE]["level"] == "off"
    saved = catalog.clean_for_save([{"key": mail_declaration.RULE, "level": "warn"}])
    assert saved == {mail_declaration.RULE: {"level": "warn", "params": {}}}


# ── Lista dni „w dniach … byłam / będę niedostępna” (mLeasing, VI–VIII 2026) ──


def _listed(text: str, month: str):
    parsed = mail_declaration.parse_text(text, month)
    assert parsed is not None
    return parsed, mail_declaration.evaluate(
        parsed, month=month, rules=_rules(), working_days=0
    )


def test_lista_dni_w_czasie_przeszlym_odejmuje_dni_robocze():
    # VI 2026: 21 dni roboczych (Boże Ciało 4.06); 3.06 i 8.06 to dni robocze.
    parsed, result = _listed(
        "Fakturę przesłałam przez KSeF.\nW czerwcu w dniach 3.06 i 08.06 byłam niedostępna.",
        "2026-06",
    )
    assert parsed.days == (3, 8) and not parsed.planned
    assert result.md_regular == Decimal("19")
    assert not result.warn


def test_zakres_i_dzien_oraz_weekend_nie_liczy_sie():
    # VIII 2026: 21 dni roboczych; 17–21 to pn–pt, 31 to poniedziałek → 6 dni.
    _, result = _listed(
        "W sierpniu w dniach 17-21 oraz 31 byłam niedostępna.", "2026-08"
    )
    assert result.md_regular == Decimal("15")
    # 1–2.08 to sobota i niedziela: nic nie odejmują.
    _, weekend = _listed("W sierpniu w dniach 1-2 byłam niedostępna.", "2026-08")
    assert weekend.md_regular == Decimal("21")


def test_zapowiedz_daje_md_z_uwaga():
    parsed, result = _listed(
        "Fakturę przesłałam za pośrednictwem ksef\nW lipcu w dniach 27-31 będę niedostępna.",
        "2026-07",
    )
    assert parsed.planned
    assert result.md_regular == Decimal("18")
    assert result.warn
    titles = _titles(result)
    assert (
        titles["Zapowiedź w treści maila: 5 dni roboczych niedostępności (lipiec 2026)"]
        == "warn"
    )


def test_lista_dni_z_innego_miesiaca_albo_z_innym_slowem_to_czlowiek():
    other_month = mail_declaration.parse_text(
        "W lipcu w dniach 3.06 i 8.06 byłam niedostępna.", "2026-07"
    )
    assert other_month is not None and other_month.days_off is None
    extra = mail_declaration.parse_text(
        "W lipcu w dniach 27-31 byłam niedostępna przez chorobę.", "2026-07"
    )
    assert extra is not None and extra.days_off is None
    no_month = mail_declaration.parse_text(
        "W dniach 27-31 byłam niedostępna.", "2026-07"
    )
    assert no_month is not None and no_month.days_off is None
