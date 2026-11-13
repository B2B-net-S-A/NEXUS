"""Kontrole dowodu pracy z katalogu reguł (roadmapa E2.2–E2.3). Bez bazy.

Wejście: odczyt RCP (``rcp_bnp``), podpisy PDF, czy jest mail z akceptacją,
miesiąc rozliczenia, imię i nazwisko z kontraktu oraz reguły klienta. Wyjście:
MD z RCP i grupy kontroli. Reguła na poziomie „Blokuje”, która nie przeszła,
blokuje przyjęcie (``blocking``); „Ostrzega” daje uwagę; „Wyłączone” nie
sprawdzamy wcale.

Czego tu nie ma: czy mail akceptujący przyszedł przed pracą i z jakiej domeny
(treść maila czyta E2.3 w kolejnym kroku) — taka kontrola ma stan „none”
i opis, że sprawdza człowiek.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Optional

from app.services.client_settlements.rcp_bnp import ParsedRcp, SignatureInfo

PDF = "application/pdf"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
TOLERANCE = Decimal("0.01")


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
    return {token for token in raw.replace("-", " ").split() if token}


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
) -> ProofResult:
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
                rcp.ok("Excel z mailem akceptującym usługi")
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
        per_md = _param_dec(rules, "fields.md_hours", "hours", "8")
        total = parsed.summary_total
        if parsed.total_hours is None or total is None or per_md <= 0:
            sums.fail("fields.md_hours", "Nie da się policzyć sum MD z RCP")
        else:
            from_hours = parsed.total_hours / per_md
            if abs(from_hours - total) <= TOLERANCE and (
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
        if extra.on("extra.mail_accept"):
            if has_mail:
                extra.ok("Mail akceptujący pracę dodatkową jest")
            else:
                extra.fail(
                    "extra.mail_accept", "Brak maila z akceptacją pracy dodatkowej"
                )
        if extra.on("extra.mail_before") and has_mail:
            extra.info("Czy akceptacja była przed pracą: sprawdza człowiek")
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
