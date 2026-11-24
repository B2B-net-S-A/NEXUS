"""Wymagania klienta do faktury z NEXUSA — z reguł rozliczeń klienta (``cl.*``, 23.11.2026).

Finanse wystawiały faktury w eBI24 i pamiętały wymagania klientów same: BNP
chce w KSeF ``NrUmowy`` i numer każdego zamówienia, Credit Agricole pole
dodatkowe „OSOBA” z adresem koordynatora, BIK rolę i numery JIRA w opisie
pozycji, Bosch fakturę mailem na adres zależny od serii, Pekao fakturę dopiero
po obustronnie podpisanym protokole. Tu te wymagania są konfiguracją klienta
w „Reguły klienta” (``rules_catalog``, wersje od miesiąca), a nie warunkami
na nazwę klienta w kodzie.

* ``from_rules`` — reguły klienta na miesiąc usługi faktury → ``Requirements``,
* ``ksef_fields`` / ``Requirements.item_name`` / ``line_problems`` /
  ``Requirements.mail_for`` / ``summary`` — co z tego idzie do szkicu, FA(3)
  i na kartę faktury,
* ``load`` i ``unsigned_people`` — odczyt z bazy (reguły, podpisane dokumenty).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.client_invoicing.export import month_label
from app.services.client_settlements import signoffs

FIELD_MAX = 256
#: Temat z ``{ksef}`` przed przyjęciem faktury w KSeF.
KSEF_PENDING = "(numer KSeF po przyjęciu)"
NUMBER_PENDING = "(numer faktury po wysyłce)"
EU_SERIES = frozenset({"UE", "KORUE"})


@dataclass(frozen=True)
class Mail:
    email: str
    subject: str
    email_eu: str
    subject_eu: str
    attach: str


@dataclass(frozen=True)
class Requirements:
    """Wymagania klienta do faktury; domyślne wartości = klient bez reguł."""

    orders_together: bool = False
    #: ``cl.collective_invoice``: faktura z KSeF na całe zamówienie, którego numer
    #: ma w NEXUSIE kilka zamówień osób (VeloBank) — numer wiąże wszystkie.
    collective_invoice: bool = False
    contract_number: Optional[str] = None
    contract_date: Optional[date] = None
    #: Pary (klucz, wzór wartości) ``DodatkowyOpis``.
    fields: tuple[tuple[str, str], ...] = ()
    item_template: Optional[str] = None
    must_contain: Optional[str] = None
    must_contain_blocks: bool = False
    mail: Optional[Mail] = None
    #: Rodzaj dokumentu (``protocol``/``sheet``), który klient musi podpisać przed fakturą.
    signed_document: Optional[str] = None
    #: ``cl.bzone_order``: dni pracy osoby w miesiącu pod zleceniem B-ZONE (blokuje).
    bzone_order: bool = False
    #: ``cl.client_protocol``: protokół odbioru od klienta za miesiąc (ostrzega).
    client_protocol: bool = False

    def item_name(
        self,
        *,
        service: str,
        order_number: Optional[str],
        person: str,
        role: Optional[str],
        period: str,
    ) -> Optional[str]:
        """Opis pozycji ze wzoru ``cl.item_name``; ``None`` = opis domyślny."""

        if not self.item_template:
            return None
        return render_item_name(
            self.item_template,
            order_number=order_number,
            person=person,
            role=role,
            service=service,
            month=month_label(period),
        )

    def mail_for(
        self,
        *,
        series: str,
        number: Optional[str],
        ksef_number: Optional[str],
        period: Optional[str],
        order_numbers: Sequence[str],
    ) -> Optional[dict[str, str]]:
        """Adres, temat i załączniki maila z fakturą; ``None`` = klient bez wymogu."""

        mail = self.mail
        if mail is None:
            return None
        eu = series in EU_SERIES
        email = (mail.email_eu if eu and mail.email_eu else mail.email).strip()
        if "@" not in email:
            return None
        subject = mail.subject_eu if eu and mail.subject_eu else mail.subject
        year, month = (
            (period or "").split("-") if period and "-" in period else ("", "")
        )
        values = {
            "{numer}": number or NUMBER_PENDING,
            "{ksef}": ksef_number or KSEF_PENDING,
            "{mm}": month,
            "{m}": str(int(month)) if month.isdigit() else month,
            "{rrrr}": year,
            "{zamowienie}": ", ".join(order_numbers),
        }
        for token, value in values.items():
            subject = subject.replace(token, value)
        return {"email": email, "subject": _clean(subject), "attach": mail.attach}


def _clean(text: Any, limit: int = FIELD_MAX) -> str:
    return " ".join(str(text or "").split())[:limit]


def _on(rules: dict[str, dict[str, Any]], key: str) -> Optional[dict[str, str]]:
    rule = rules.get(key)
    if not rule or rule.get("level") == "off":
        return None
    return {k: str(v or "") for k, v in (rule.get("params") or {}).items()}


def _date(raw: str) -> Optional[date]:
    try:
        return date.fromisoformat(raw.strip())
    except ValueError:
        return None


def render_item_name(
    pattern: str,
    *,
    order_number: Optional[str],
    person: str,
    role: Optional[str] = None,
    service: Optional[str] = None,
    month: Optional[str] = None,
) -> str:
    """Wzór opisu pozycji: ``{zamowienie}``, ``{osoba}``, ``{rola}``, ``{usluga}``, ``{miesiac}``.

    Pole bez wartości znika razem z separatorem przed nim („A — {rola} — B” bez
    roli = „A — B”), żeby w opisie nie zostawał znacznik ani podwójna kreska.
    """

    values = {
        "{zamowienie}": order_number or "—",
        "{osoba}": person,
        "{rola}": role or "",
        "{usluga}": service or "",
        "{miesiac}": month or "",
    }
    text = pattern
    for token, value in values.items():
        text = text.replace(token, value)
    text = " ".join(text.split())
    for separator in (" — —", " - -", ", ,"):
        while separator in text:
            text = text.replace(separator, separator[:2])
    return text.strip(" —-,")


def from_rules(rules: dict[str, dict[str, Any]], period: str) -> Requirements:
    contract = _on(rules, "cl.ksef_contract") or {}
    fields_rule = _on(rules, "cl.ksef_fields") or {}
    fields = tuple(
        (_clean(fields_rule.get(k)), str(fields_rule.get(v) or "").strip())
        for k, v in (("key", "value"), ("key2", "value2"))
        if _clean(fields_rule.get(k))
    )
    item = _on(rules, "cl.item_name") or {}
    must = _on(rules, "cl.item_must_contain") or {}
    mail_rule = _on(rules, "cl.invoice_mail")
    mail = (
        Mail(
            email=_clean(mail_rule.get("email")),
            subject=str(mail_rule.get("subject") or ""),
            email_eu=_clean(mail_rule.get("email_eu")),
            subject_eu=str(mail_rule.get("subject_eu") or ""),
            attach=_clean(mail_rule.get("attach")),
        )
        if mail_rule is not None
        else None
    )
    signed = (
        signoffs.document_rule(rules, period)
        if _on(rules, "cl.after_signed_document") is not None
        and "cl.client_document" in rules
        else None
    )
    return Requirements(
        orders_together=_on(rules, "cl.orders_together") is not None,
        collective_invoice=_on(rules, "cl.collective_invoice") is not None,
        contract_number=_clean(contract.get("number")) or None,
        contract_date=_date(contract.get("date") or "") if contract else None,
        fields=fields,
        item_template=str(item.get("template") or "").strip() or None,
        must_contain=_clean(must.get("text")) or None,
        must_contain_blocks=(rules.get("cl.item_must_contain") or {}).get("level")
        == "block",
        mail=mail,
        signed_document=signed,
        bzone_order=_on(rules, "cl.bzone_order") is not None,
        client_protocol=_on(rules, "cl.client_protocol") is not None,
    )


def ksef_fields(
    found: Requirements, order_numbers: Sequence[str]
) -> tuple[tuple[str, str], ...]:
    """Pola ``DodatkowyOpis`` z wartościami (``{zamowienie}`` = numery faktury)."""

    out = []
    for key, pattern in found.fields:
        value = _clean(pattern.replace("{zamowienie}", ", ".join(order_numbers)))
        if value:
            out.append((key, value))
    return tuple(out)


def line_problems(
    found: Requirements, lines: Iterable[dict[str, Any]]
) -> tuple[list[str], list[str]]:
    """(blokujące wysyłkę, ostrzeżenia) z reguły ``cl.item_must_contain``."""

    text = found.must_contain
    if not text:
        return [], []
    missing = [
        str(index)
        for index, line in enumerate(lines, start=1)
        if text.lower() not in str(line.get("name") or "").lower()
    ]
    if not missing:
        return [], []
    where = "pozycji" if len(missing) == 1 else "pozycjach"
    message = (
        f"Klient wymaga „{text}” w opisie każdej pozycji — brak w {where} "
        f"{', '.join(missing)}."
    )
    return ([message], []) if found.must_contain_blocks else ([], [message])


def summary(found: Requirements, order_numbers: Sequence[str]) -> list[dict[str, str]]:
    """Wymagania klienta na kartę szkicu (co NEXUS wpisze do KSeF i sprawdzi)."""

    out: list[dict[str, str]] = []
    if order_numbers and (found.orders_together or len(order_numbers) > 1):
        out.append(
            {"label": "Numery zamówień (KSeF)", "value": ", ".join(order_numbers)}
        )
    if found.contract_number:
        value = found.contract_number
        if found.contract_date:
            value += f" z {found.contract_date.strftime('%d.%m.%Y')}"
        out.append({"label": "Numer umowy (KSeF)", "value": value})
    for key, value in ksef_fields(found, order_numbers):
        out.append({"label": f"{key} (KSeF, pole dodatkowe)", "value": value})
    if found.must_contain:
        out.append({"label": "Każda pozycja zawiera", "value": found.must_contain})
    if found.bzone_order:
        out.append(
            {"label": "Zlecenie B-ZONE", "value": "na każdy dzień pracy w miesiącu"}
        )
    if found.client_protocol:
        out.append({"label": "Protokół odbioru", "value": "od klienta za ten miesiąc"})
    return out


def pdf_notes(found: Requirements, order_numbers: Sequence[str]) -> list[str]:
    """Umowa i pola dodatkowe klienta w uwagach PDF-u (te same co w KSeF)."""

    out = []
    if found.contract_number:
        when = (
            f" z {found.contract_date.strftime('%d.%m.%Y')}"
            if found.contract_date
            else ""
        )
        out.append(f"Umowa: {found.contract_number}{when}.")
    out.extend(f"{key}: {value}." for key, value in ksef_fields(found, order_numbers))
    return out


# ── Odczyt z bazy ───────────────────────────────────────────────────────────


async def load(db: AsyncSession, client_id: Optional[int], period: str) -> Requirements:
    """Wymagania klienta na miesiąc usługi (``period`` = ``RRRR-MM``)."""

    if client_id is None:
        return Requirements()
    from app.services.client_settlements import service

    return from_rules(await service.rules_for(db, client_id, period), period)


async def unsigned_people(
    db: AsyncSession,
    found: Requirements,
    *,
    contract_ids: Iterable[int],
    period: str,
) -> set[int]:
    """Kontrakty bez podpisanego dokumentu klienta za miesiąc (``cl.after_signed_document``).

    Ta sama miara co „Do faktury” w rozliczeniach: przyjęte RCP faktyczne osoby
    z kompletem podpisów dokumentu z reguły ``cl.client_document``.
    """

    ids = {int(i) for i in contract_ids if i is not None}
    if found.signed_document is None or not ids:
        return set()
    from app.models.client_settlement import ClientSettlement
    from app.services.client_settlements import service

    rows = await db.execute(
        select(ClientSettlement.contract_id, ClientSettlement.checks).where(
            ClientSettlement.contract_id.in_(ids),
            ClientSettlement.period_month == period,
            ClientSettlement.kind == service.ACTUAL,
            ClientSettlement.status == "accepted",
        )
    )
    signed = {
        contract_id
        for contract_id, checks in rows.all()
        if signoffs.is_complete(checks, found.signed_document)
    }
    return ids - signed


__all__ = [
    "Requirements",
    "from_rules",
    "ksef_fields",
    "line_problems",
    "load",
    "pdf_notes",
    "render_item_name",
    "summary",
    "unsigned_people",
]
