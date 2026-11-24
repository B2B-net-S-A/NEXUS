"""Kontrole dowodu pracy z katalogu reguł (roadmapa E2.2–E2.3). Bez bazy.

Wejście: odczyt RCP (``rcp_bnp``), podpisy PDF, czy jest mail z akceptacją,
miesiąc rozliczenia, imię i nazwisko z kontraktu oraz reguły klienta. Wyjście:
MD z RCP i grupy kontroli. Reguła na poziomie „Blokuje”, która nie przeszła,
blokuje przyjęcie (``blocking``); „Ostrzega” daje uwagę; „Wyłączone” nie
sprawdzamy wcale.

Mail akceptujący (E2.3): ``mails`` to wiadomości z łańcucha maila
(``acceptance_mail.read``). Data zgody to najwcześniejsza wiadomość z domeny
klienta i ma być nie później niż pierwszy dzień pracy dodatkowej; domena
nadawcy z parametru reguły. Mail bez daty albo bez nadawcy = „sprawdza człowiek”.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Optional, Sequence

from app.services.client_settlements import acceptance_mail
from app.services.client_settlements.acceptance_mail import MailMessage
from app.services.client_settlements.rcp_bnp import ParsedRcp, SignatureInfo

PDF = "application/pdf"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
TOLERANCE = Decimal("0.01")
#: Podsumowanie RCP pokazuje MD z jednym miejscem po przecinku (9 h nadgodzin
#: = 1,125 MD stoi jako 1,1). Różnica z godzinami mniejsza niż 0,05 MD na wiersz
#: to zaokrąglenie, nie błąd sum (próba IX–X 2026, BNP).
ROUNDING = Decimal("0.05")


@dataclass
class ProofResult:
    md_regular: Optional[Decimal]
    md_extra: Optional[Decimal]
    groups: list[dict[str, Any]] = field(default_factory=list)
    blocking: bool = False
    warn: bool = False
    #: Dane odczytu dla karty i listy (np. ``kesu`` w E6.3), poza kontrolami.
    meta: dict[str, Any] = field(default_factory=dict)


def _fmt(value: Decimal) -> str:
    return f"{value.normalize():f}".replace(".", ",")


def _param(rules: Mapping[str, Mapping[str, Any]], key: str, name: str) -> str:
    return str(rules[key]["params"].get(name, "")).strip()


def _param_dec(
    rules: Mapping[str, Mapping[str, Any]], key: str, name: str, default: str
) -> Decimal:
    try:
        return Decimal((_param(rules, key, name) or default).replace(",", "."))
    except InvalidOperation:
        return Decimal(default)


def name_tokens(text: Optional[str]) -> set[str]:
    raw = (
        unicodedata.normalize(
            # „ł” nie rozkłada się w NFKD i ginęłoby przy ASCII („Miłosz” → „miosz”).
            "NFKD",
            (text or "").replace("ł", "l").replace("Ł", "L"),
        )
        .encode("ascii", "ignore")
        .decode()
        .lower()
    )
    # Po zmianie nazwiska kartoteka ma „Nowe (Stare)”: nawias nie jest częścią słowa,
    # więc plik ze starym albo nowym nazwiskiem pasuje do kontraktu.
    for mark in "-()":
        raw = raw.replace(mark, " ")
    return {token for token in raw.split() if token}


class _Group:
    def __init__(
        self, result: ProofResult, rules: Mapping[str, Mapping[str, Any]], title: str
    ) -> None:
        self.result, self.rules, self.title = result, rules, title
        self.checks: list[dict[str, Any]] = []

    def ok(self, title: str, detail: Optional[str] = None) -> None:
        self.checks.append({"state": "ok", "title": title, "detail": detail})

    def info(self, title: str, detail: Optional[str] = None) -> None:
        self.checks.append({"state": "none", "title": title, "detail": detail})

    def warn(self, title: str, detail: Optional[str] = None) -> None:
        """Uwaga niezależna od poziomu reguły (nigdy nie blokuje)."""

        self.result.warn = True
        self.checks.append({"state": "warn", "title": title, "detail": detail})

    def fail(self, key: str, title: str, detail: Optional[str] = None) -> None:
        level = self.rules[key]["level"]
        if level == "off":
            return
        if level == "block":
            self.result.blocking = True
            self.checks.append(
                {"state": "fail", "title": title, "detail": detail, "rule": key}
            )
        else:
            self.result.warn = True
            self.checks.append(
                {"state": "warn", "title": title, "detail": detail, "rule": key}
            )

    def on(self, key: str) -> bool:
        return self.rules[key]["level"] != "off"

    def close(self) -> None:
        if self.checks:
            self.result.groups.append({"title": self.title, "checks": self.checks})


def evaluate(
    parsed: Optional[ParsedRcp],
    signatures: list[SignatureInfo],
    *,
    mime: str,
    month: str,
    person_name: str,
    has_mail: bool,
    rules: Mapping[str, Mapping[str, Any]],
    mails: Sequence[MailMessage] = (),
    client_mail: Optional[bool] = None,
    acceptor: str = "klienta",
) -> ProofResult:
    """``client_mail``: czy w mailach miesiąca jest wiadomość klienta
    (``acceptance_mail.from_client``); ``None`` = nadawcy nie odczytano.
    ``acceptor``: kto akceptuje (``mail_text.Senders.who``)."""

    result = ProofResult(md_regular=None, md_extra=None)
    rcp = _Group(result, rules, "RCP")

    if parsed is None:
        rcp.info(
            "Nie rozpoznano szablonu RCP",
            "MD wpisują Finanse; plik zostaje w NEXUS-ie.",
        )
        result.warn = True
        rcp.close()
        return result

    result.md_regular = parsed.md_regular
    result.md_extra = parsed.md_extra
    # „OPIS PRAC” bez wierszy z MD (konsultant wypełnił tylko godziny): suma z
    # podsumowania to MD podstawowe. Bez tego NEXUS liczył 0 MD (próba IX–XI 2026).
    md_from_total = not parsed.summary
    # Wiersze opisu, które nie sumują się do „SUMA:” (nachodzące napisy w PDF,
    # sklejone wiersze): MD z sumy, bo z wierszy wychodziło 15 zamiast 22 MD przy
    # statusie „ok” (próba IX–X 2026). Podziału na dodatkowe nie da się wtedy ufać.
    rows_total = parsed.md_regular + parsed.md_extra
    rows_mismatch = (
        not md_from_total
        and parsed.summary_total is not None
        and abs(rows_total - parsed.summary_total) > TOLERANCE
    )
    if md_from_total or rows_mismatch:
        result.md_regular = (
            parsed.summary_total
            if parsed.summary_total is not None
            else parsed.declared_md
        )
        result.md_extra = None
    per_md = _param_dec(rules, "fields.md_hours", "hours", "8")
    exact = None if md_from_total or rows_mismatch else rounded_in_file(parsed, per_md)
    if exact is not None:
        # Finanse fakturują MD z godzin (23,125), nie zaokrąglone z pliku (23,1).
        result.md_regular, result.md_extra = exact

    if parsed.month == month:
        rcp.ok(f"Miesiąc z RCP: {month}")
    else:
        rcp.fail(
            "proof.month",
            "RCP za inny miesiąc",
            f"W pliku: {parsed.month or 'brak pola Rozliczenie'}.",
        )

    if mime == PDF:
        good = [s for s in signatures if s.intact and s.entire_file]
        issuer_need = _param(rules, "proof.signed_pdf", "issuer").lower()
        trusted = [
            s
            for s in good
            if not issuer_need or issuer_need in (s.issuer or "").lower()
        ]
        if trusted:
            s = trusted[0]
            when = (
                s.signed_at.strftime("%d.%m.%Y %H:%M") if s.signed_at else "bez czasu"
            )
            rcp.ok(
                "Podpis elektroniczny ważny, plik bez zmian po podpisie",
                f"{s.signer or 'Podpisujący'}, {when}, wystawca: {s.issuer or 'nieznany'}.",
            )
        elif good:
            rcp.fail(
                "proof.signed_pdf",
                "Podpis innego wystawcy niż w regułach klienta",
                f"Wystawca: {good[0].issuer or 'nieznany'}.",
            )
        elif signatures:
            rcp.fail(
                "proof.signed_pdf", "Podpis nieważny albo plik zmieniony po podpisie"
            )
        else:
            rcp.fail("proof.signed_pdf", "PDF bez podpisu elektronicznego")
    elif mime == XLSX:
        if rcp.on("proof.excel_with_mail"):
            if has_mail:
                client_acceptance_mail(
                    rcp, "proof.excel_with_mail", client_mail, who=acceptor
                )
                if client_mail:
                    rcp.ok("Excel z mailem akceptującym usługi")
                if client_mail is not False and acceptor == "klienta":
                    _check_domain(
                        rcp,
                        "proof.excel_with_mail",
                        _param(rules, "proof.excel_with_mail", "domain"),
                        mails,
                    )
            else:
                rcp.fail(
                    "proof.excel_with_mail",
                    "Excel bez maila akceptującego usługi",
                    "Dołącz mail z akceptacją (MSG, EML albo PDF z wydrukiem).",
                )
        else:
            rcp.fail("proof.signed_pdf", "RCP w Excelu zamiast PDF z podpisem")

    rcp_names = name_tokens(f"{parsed.first_name or ''} {parsed.last_name or ''}")
    if (
        rcp_names
        and rcp_names <= name_tokens(person_name)
        or (rcp_names and name_tokens(person_name) <= rcp_names)
    ):
        rcp.ok("Imię i nazwisko jak w kontrakcie")
    else:
        rcp.fail("proof.name_match", "Inne imię lub nazwisko niż w kontrakcie")
    if parsed.check_ok is False:
        rcp.fail("fields.md_hours", "Szablon pokazuje błąd sum (pole Check)")
    rcp.close()

    sums = _Group(result, rules, "Pola i sumy")
    if rows_mismatch:
        sums.warn(
            "Wiersze opisu prac nie sumują się do SUMA",
            f"Wiersze: {_fmt(rows_total)} MD, SUMA: {_fmt(parsed.summary_total)} MD. "
            "MD z SUMA jako podstawowe; sprawdź podział na pracę dodatkową.",
        )
    if md_from_total:
        sums.info(
            "MD z sumy podsumowania",
            "Opis prac bez wierszy z MD: całość liczona jako MD podstawowe."
            if result.md_regular is not None
            else "Brak sumy MD w pliku: MD wpisują Finanse.",
        )
    working = [r for r in parsed.summary if r.md > 0 and not r.is_travel]
    allowed = {
        a.strip().lower()
        for a in _param(rules, "fields.product_id", "allowed").split(",")
        if a.strip()
    }
    if sums.on("fields.product_id"):
        missing = [r for r in working if not r.product]
        if missing or not working:
            sums.fail("fields.product_id", "Brak ID PRODUCT w podsumowaniu")
        else:
            products = sorted({r.product for r in working if r.product})
            note = (
                " (dozwolone też: " + ", ".join(sorted(allowed)) + ")"
                if allowed
                else ""
            )
            sums.ok(f"ID PRODUCT: {', '.join(products)}{note}")
    if sums.on("fields.cmdb"):
        if any(not r.cmdb for r in working) or not working:
            sums.fail("fields.cmdb", "Brak kodu CMDB w podsumowaniu")
        else:
            sums.ok("Kod CMDB uzupełniony")
    if sums.on("fields.md_hours"):
        total = parsed.summary_total
        if parsed.total_hours is None or total is None or per_md <= 0:
            sums.fail("fields.md_hours", "Nie da się policzyć sum MD z RCP")
        else:
            from_hours = parsed.total_hours / per_md
            if exact is not None:
                sums.ok(
                    "Sumy MD policzone od nowa",
                    f"{_fmt(parsed.total_hours)} h / {_fmt(per_md)} = "
                    f"{_fmt(from_hours.quantize(Decimal('0.001')))} MD, w podsumowaniu "
                    f"{_fmt(total)} MD (zaokrąglone do 0,1). MD z godzin.",
                )
            elif abs(from_hours - total) <= TOLERANCE and (
                parsed.declared_md is None
                or abs(parsed.declared_md - total) <= TOLERANCE
            ):
                sums.ok(
                    "Sumy MD policzone od nowa",
                    f"{_fmt(parsed.total_hours)} h / {_fmt(per_md)} = {_fmt(from_hours.quantize(Decimal('0.001')))} MD = podsumowanie.",
                )
            else:
                sums.fail(
                    "fields.md_hours",
                    "Sumy MD nie zgadzają się z godzinami",
                    f"{_fmt(parsed.total_hours)} h / {_fmt(per_md)} = {_fmt(from_hours.quantize(Decimal('0.001')))} MD, podsumowanie: {_fmt(total)} MD.",
                )
    if sums.on("fields.day_limit") and parsed.day_totals:
        limit = _param_dec(rules, "fields.day_limit", "hours", "24")
        worst = max(parsed.day_totals)
        if worst <= limit:
            sums.ok(
                f"Najwięcej w jednym dniu: {_fmt(worst)} h", f"Limit {_fmt(limit)} h."
            )
        else:
            day = parsed.day_totals.index(worst) + 1
            sums.fail(
                "fields.day_limit",
                f"{_fmt(worst)} h w dniu {day}",
                f"Limit {_fmt(limit)} h.",
            )
    sums.close()

    extra = _Group(result, rules, "Nadgodziny")
    if parsed.md_extra > 0:
        weekend = parsed.weekend_days
        if weekend:
            extra.ok("Weekend: dni " + ", ".join(str(d) for d in weekend))
        domain = _param(rules, "extra.mail_accept", "domain")
        if extra.on("extra.mail_accept"):
            if has_mail:
                client_acceptance_mail(
                    extra,
                    "extra.mail_accept",
                    client_mail,
                    " pracy dodatkowej",
                    who=acceptor,
                )
                if client_mail:
                    extra.ok("Mail akceptujący pracę dodatkową jest")
                if client_mail is not False and acceptor == "klienta":
                    # Domena klienta z reguły; w projekcie FIX akceptuje PM firmy.
                    _check_domain(extra, "extra.mail_accept", domain, mails)
            else:
                extra.fail(
                    "extra.mail_accept", "Brak maila z akceptacją pracy dodatkowej"
                )
        if extra.on("extra.mail_before") and has_mail and client_mail is not False:
            _check_before(extra, parsed, month, domain, mails)
    extra.close()

    if parsed.travel_total and parsed.travel_total > 0:
        travel = _Group(result, rules, "Delegacje")
        travel.info(
            f"Koszty delegacji w RCP: {_fmt(parsed.travel_total)} zł brutto",
            "Faktury kosztów i zasadność wyjazdu sprawdza człowiek.",
        )
        result.warn = True
        travel.close()
    return result


def rounded_in_file(
    parsed: ParsedRcp, per_md: Decimal
) -> Optional[tuple[Decimal, Decimal]]:
    """MD z godzin (dni zwykłe, praca dodatkowa), gdy podsumowanie różni się
    od godzin tylko zaokrągleniem do 0,1 MD.

    Różnicę dostaje ta część, której wiersze nie są pełnymi godzinami (1,1 MD
    to 8,8 h, więc wiersz jest zaokrąglony). Takie wiersze w obu częściach albo
    w żadnej: nie wiadomo, gdzie jest różnica, więc ``None`` (sprawdza człowiek)."""

    if parsed.total_hours is None or per_md <= 0:
        return None
    regular, extra = parsed.md_regular, parsed.md_extra
    exact = parsed.total_hours / per_md
    residue = exact - (regular + extra)
    rounded = [
        row
        for row in parsed.summary
        if row.md > 0 and not row.is_travel and (row.md * per_md) % 1 != 0
    ]
    if residue == 0 or abs(residue) >= ROUNDING * max(len(rounded), 1):
        return None
    if parsed.declared_md is not None and abs(parsed.declared_md - exact) > TOLERANCE:
        return None
    parts = {row.is_extra for row in rounded}
    if len(parts) != 1:
        return None
    if parts == {True}:
        return regular, extra + residue
    return regular + residue, extra


def _day(value: date) -> str:
    return value.strftime("%d.%m.%Y")


def client_acceptance_mail(
    group: _Group,
    key: str,
    client_mail: Optional[bool],
    what: str = "",
    who: str = "klienta",
) -> None:
    """Mail jest, ale czy od klienta (ciąg dalszy #3820, przegląd z 23.11.2026).

    Odpowiedź naszego PM-a, konsultanta albo nasze przekazanie bez cytatu
    klienta to nie akceptacja klienta. Nadawcy nie odczytano = sprawdza człowiek.
    ``True`` nic tu nie dopisuje: „ok” daje kontrola, która woła. ``who``: kto
    akceptuje — w projekcie FIX „PM-a firmy” (godziny to koszt, nie usługa)."""

    if client_mail is None:
        group.info(
            "Nadawcy maila nie odczytano: akceptację sprawdza człowiek",
            "W wątku nie ma adresu klienta, a nadawca którejś wiadomości jest bez adresu.",
        )
    elif not client_mail and who != "klienta":
        group.fail(
            key,
            f"Brak akceptacji {who}" + what,
            f"W mailu nie ma słowa akceptacji (np. „Akceptuję”) od {who}.",
        )
    elif not client_mail:
        group.fail(
            key,
            "Brak akceptacji klienta" + what,
            "Mail nie pochodzi z domeny klienta i nie cytuje jego wiadomości. "
            "Odpowiedź naszego PM-a albo konsultanta nie jest akceptacją klienta.",
        )


def _check_domain(
    group: _Group, key: str, raw: str, mails: Sequence[MailMessage]
) -> None:
    allowed = acceptance_mail.domains(raw)
    if not allowed:
        return
    senders = sorted({m.domain for m in mails if m.domain})
    if acceptance_mail.from_domain(mails, allowed):
        group.ok("Akceptacja z domeny " + ", ".join(allowed))
    elif not senders or any(m.sender is None for m in mails):
        # Outlook w firmie cytuje często „From: Nowak, Anna” bez adresu — wtedy
        # nie wiemy, skąd zgoda, i blokada byłaby fałszywa.
        group.info(
            "Nadawcy maila nie odczytano: domenę sprawdza człowiek",
            "Wymagana: " + ", ".join(allowed) + ".",
        )
    else:
        group.fail(
            key,
            "Mail akceptujący spoza domeny klienta",
            f"Wymagana: {', '.join(allowed)}; w mailu: {', '.join(senders)}.",
        )


def _check_before(
    group: _Group,
    parsed: ParsedRcp,
    month: str,
    domain: str,
    mails: Sequence[MailMessage],
) -> None:
    """Zgoda nie później niż pierwszy dzień pracy dodatkowej (ten sam dzień = przed)."""

    days = parsed.weekend_days
    accepted = acceptance_mail.acceptance_date(mails, acceptance_mail.domains(domain))
    if not days or accepted is None:
        group.info(
            "Czy akceptacja była przed pracą: sprawdza człowiek",
            None if days else "Z RCP nie wynika, w które dni była praca dodatkowa.",
        )
        return
    year, mon = (int(x) for x in month.split("-"))
    first = date(year, mon, min(days))
    if accepted <= first:
        group.ok(
            f"Akceptacja z {_day(accepted)}, przed pracą dodatkową",
            f"Pierwszy dzień pracy dodatkowej: {_day(first)}.",
        )
    else:
        group.fail(
            "extra.mail_before",
            f"Akceptacja z {_day(accepted)}, po pracy dodatkowej",
            f"Pierwszy dzień pracy dodatkowej: {_day(first)}.",
        )
