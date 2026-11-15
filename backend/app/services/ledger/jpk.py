"""JPK_V7M(3) (K5b): ewidencja VAT z deklaracją VAT-7 z rejestrów K5a.

Struktura: wzór 2025/12/19/14090 (crd.gov.pl), obowiązuje od rozliczenia za luty
2026 — schematy XSD w ``jpk_schema/`` (pobrane z crd.gov.pl 15.11.2026; w
``schemat.xsd`` adresy importów przepisane na pliki obok, reszta bajt w bajt),
więc walidacja nie sięga do sieci. Zasady wypełniania wg broszury MF „JPK_VAT
z deklaracją od 1 lutego 2026 r.”:

* ``NrKontrahenta`` bez kodu kraju (kod w ``KodKrajuNadaniaTIN``, krajowy NIP
  bez kodu); brak numeru = „BRAK” bez kodu kraju; brak nazwy = „BRAK”;
* faktura z numerem KSeF = ``NrKSeF``, inaczej ``BFK`` (faktura wystawiona poza
  KSeF, np. przez sprzedawcę zagranicznego);
* ``DataSprzedazy`` i ``DataWplywu`` tylko, gdy różne od daty wystawienia;
* ewidencja (``K_``) w groszach, deklaracja (``P_``) w pełnych złotych — od 50 gr
  w górę (art. 63 § 1 Ordynacji), z sumy pola ``K_`` wszystkich wierszy;
* P_37, P_38, P_48 i sumy kontrolne wg dokumentacji pól w XSD; P_51 = do
  wpłaty, P_53 = P_62 = nadwyżka do przeniesienia (zwrot P_54 — później);
* znaczniki GTU i TP (K5b-2) z ustawień kontrahenta — ``1`` w polach wiersza
  sprzedaży, GTU przed procedurami (kolejność z XSD); import usług bez
  znaczników (GTU nie stosuje się do nabyć z podatkiem należnym).

Plik zawiera faktury osób zespołu (D2): przygotowuje go osoba z listy
„Księgowi” z Płacami albo administrator, pobiera — osoba z Płacami albo
administrator. Wersja 1. = złożenie; po wersji oznaczonej jako wysłana kolejna
jest korektą z uzasadnieniem (P_ORDZU). P_39 = P_62 z JPK poprzedniego
miesiąca (wysłanego, inaczej ostatniego); pierwszy miesiąc w NEXUSIE — kwota
wpisana przy przygotowaniu (z deklaracji z Symfonii).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from lxml import etree
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ledger import LedgerVatFile
from app.services.finance_ledger.costs import LedgerError
from app.services.hr.payroll_lists import parameters as payroll_parameters
from app.services.ledger import vat
from app.services.ledger.documents import Viewer
from app.services.ledger.settings import MARKERS, LedgerSettings
from app.services.ledger_vat_schema import NOTE_MAX, REASON_MAX

NS = "http://crd.gov.pl/wzor/2025/12/19/14090/"
ETD = "http://crd.gov.pl/xml/schematy/dziedzinowe/mf/2022/09/13/eD/DefinicjeTypy/"
SCHEMA = Path(__file__).with_name("jpk_schema") / "schemat.xsd"
SYSTEM = "NEXUS"
BRAK = "BRAK"
ERRORS_SHOWN = 5
LOCK_KEY = "ledger-jpk"
#: Numer KSeF wg ``tns:TNumerKSeF``; inny numer = faktura poza KSeF (BFK).
KSEF = re.compile(
    r"^([1-9]((\d[1-9])|([1-9]\d))\d{7}|M\d{9}|[A-Z]{3}\d{7})-"
    r"(20[2-9][0-9]|2[1-9][0-9]{2}|[3-9][0-9]{3})(0[1-9]|1[0-2])"
    r"(0[1-9]|[1-2][0-9]|3[0-1])-([0-9A-F]{6})-?([0-9A-F]{6})-([0-9A-F]{2})$"
)
SALES_K: tuple[str, ...] = (
    "K_10", "K_11", "K_12", "K_13", "K_14", "K_15", "K_16", "K_17", "K_18",
    "K_19", "K_20", "K_21", "K_22", "K_23", "K_24", "K_25", "K_26", "K_27",
    "K_28", "K_29", "K_30", "K_31", "K_32", "K_33", "K_34", "K_35", "K_36",
    "K_360",
)  # fmt: skip
PURCHASE_K: tuple[str, ...] = (
    "K_40", "K_41", "K_42", "K_43", "K_44", "K_45", "K_46", "K_47",
)  # fmt: skip
#: Pola w parach (sekwencja w XSD — oba albo żadne).
PAIRS: dict[str, str] = {
    "K_15": "K_16", "K_17": "K_18", "K_19": "K_20", "K_23": "K_24",
    "K_25": "K_26", "K_27": "K_28", "K_29": "K_30", "K_31": "K_32",
    "K_40": "K_41", "K_42": "K_43",
}  # fmt: skip
TAX_PLUS = (
    "K_16",
    "K_18",
    "K_20",
    "K_24",
    "K_26",
    "K_28",
    "K_30",
    "K_32",
    "K_33",
    "K_34",
)
TAX_MINUS = ("K_35", "K_36", "K_360")
INPUT_TAX = ("K_41", "K_43", "K_44", "K_45", "K_46", "K_47")
P_ORDER: tuple[str, ...] = (
    "P_10", "P_11", "P_12", "P_13", "P_14", "P_15", "P_16", "P_17", "P_18",
    "P_19", "P_20", "P_21", "P_22", "P_23", "P_24", "P_25", "P_26", "P_27",
    "P_28", "P_29", "P_30", "P_31", "P_32", "P_33", "P_34", "P_35", "P_36",
    "P_360", "P_37", "P_38", "P_39", "P_40", "P_41", "P_42", "P_43", "P_44",
    "P_45", "P_46", "P_47", "P_48", "P_49", "P_50", "P_51", "P_52", "P_53",
    "P_62",
)  # fmt: skip
P_37_FROM = (
    "P_10", "P_11", "P_13", "P_15", "P_17", "P_19", "P_21", "P_22", "P_23",
    "P_25", "P_27", "P_29", "P_31",
)  # fmt: skip
P_38_PLUS = (
    "P_16",
    "P_18",
    "P_20",
    "P_24",
    "P_26",
    "P_28",
    "P_30",
    "P_32",
    "P_33",
    "P_34",
)
P_38_MINUS = ("P_35", "P_36", "P_360")
P_48_FROM = ("P_39", "P_41", "P_43", "P_44", "P_45", "P_46", "P_47")
#: „Do sprawdzenia” rejestrów, przy których JPK nie powstaje (niepełny albo bez
#: pola JPK); reszta to ostrzeżenia w odpowiedzi.
BLOCKING = ("rates", "missing_sales", "drafts")
#: Czego plik z NEXUSA nie ma albo bierze z ustawień — widoczne przy JPK
#: (porównanie z JPK z Symfonii w miesiącach równoległych to wyłapie).
NOTES: tuple[str, ...] = (
    "Znaczniki GTU i TP pochodzą z listy „Znaczniki kontrahentów” (zakładka VAT) "
    "i trafiają na wszystkie faktury sprzedaży kontrahenta; pozostałe procedury "
    "(np. MR_T, I_42, WSTO_EE) — nie w NEXUSIE.",
    "Import usług wchodzi do JPK z formularza zakupu zagranicznego (zakładka VAT); "
    "taka faktura z kolejki kosztów stoi na liście „do sprawdzenia”.",
)
PREPARE_ONLY = (
    "JPK zawiera faktury osób zespołu — przygotowuje go osoba z listy „Księgowi” "
    "z Płacami albo administrator."
)
DOWNLOAD_ONLY = (
    "JPK zawiera faktury osób zespołu — pobiera go osoba z Płacami albo administrator."
)


def zl(grosze: int) -> int:
    """Grosze → pełne złote (art. 63 § 1 OP: od 50 gr w górę, także dla minusa)."""

    return int((Decimal(grosze) / 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def money(grosze: int) -> str:
    sign = "-" if grosze < 0 else ""
    return f"{sign}{abs(grosze) // 100}.{abs(grosze) % 100:02d}"


def counterparty(
    tax_id: Optional[str], country: Optional[str]
) -> tuple[Optional[str], str]:
    """(``KodKrajuNadaniaTIN``, numer): numer bez kodu kraju, brak = „BRAK”."""

    number = "".join(ch for ch in (tax_id or "") if ch.isalnum()).upper()
    code = (country or "").upper()
    if not number:
        return None, BRAK
    if not code and number[:2].isalpha():
        # Numer VAT UE bez zapisanego kraju: kraj z prefiksu numeru.
        code = number[:2]
    if code == "GR" and number.startswith("EL"):
        code = "EL"
    if code in ("", "PL"):
        return None, number[2:] if number.startswith("PL") else number
    if number.startswith(code):
        number = number[len(code) :]
    # Grecja w JPK to EL (TKodKrajuJPK wyklucza GR).
    return ("EL" if code == "GR" else code), number or BRAK


def row_fields(groups: list[dict[str, Any]]) -> dict[str, int]:
    """Pola ``K_`` wiersza z grup rejestru (grosze); pary z XSD uzupełnione zerem."""

    out: dict[str, int] = {}
    for group in groups:
        category = vat.CATEGORIES[group["key"]]
        out[category.net_field] = out.get(category.net_field, 0) + group["net"]
        if category.vat_field:
            out[category.vat_field] = out.get(category.vat_field, 0) + group["vat"]
        if category.also:
            out[category.also] = out.get(category.also, 0) + group["net"]
    for first, second in PAIRS.items():
        if first in out or second in out:
            out.setdefault(first, 0)
            out.setdefault(second, 0)
    return out


def declaration(sums: dict[str, int], *, surplus: int) -> dict[str, int]:
    """Pola ``P_`` deklaracji w pełnych złotych z sum pól ``K_`` ewidencji."""

    fields = {f"P_{key[2:]}": zl(total) for key, total in sums.items()}
    p_38 = sum(fields.get(key, 0) for key in P_38_PLUS) - sum(
        fields.get(key, 0) for key in P_38_MINUS
    )
    fields["P_37"] = sum(fields.get(key, 0) for key in P_37_FROM)
    fields["P_38"] = p_38
    if surplus:
        fields["P_39"] = surplus
    p_48 = sum(fields.get(key, 0) for key in P_48_FROM)
    fields["P_48"] = p_48
    fields["P_51"] = max(p_38 - p_48, 0)
    if p_48 > p_38:
        fields["P_53"] = p_48 - p_38
        fields["P_62"] = p_48 - p_38
    return fields


def _iso(value: Optional[str]) -> Optional[date]:
    return date.fromisoformat(value) if value else None


#: Znaki spoza XML 1.0 (sterujące) — lxml odrzuca je wyjątkiem (500).
_NOT_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")


def _clip(value: Optional[str], limit: int) -> str:
    text = " ".join(_NOT_XML.sub(" ", value or "").split())
    return text[:limit] if text else BRAK


#: JPK_V7M(3) obowiązuje od rozliczenia za luty 2026 (wcześniej wzór (2)).
FIRST_PERIOD = (2026, 2)


def period_problem(year: int, month: int) -> Optional[str]:
    if (year, month) < FIRST_PERIOD:
        return (
            "JPK_V7M(3) obowiązuje od rozliczenia za luty 2026 — wcześniejsze "
            "okresy w Symfonii (wzór 2)."
        )
    return None


def row_problems(data: dict[str, Any]) -> list[str]:
    """Wiersze, których kwoty z dekretu nie mieszczą się w polach JPK (netto
    i VAT grup ≠ sumy wiersza) — plik by je zaniżył (przegląd K5b)."""

    out = []
    for kind in ("sales", "purchases"):
        for row in data[kind]:
            net = sum(group["net"] for group in row["groups"])
            tax = sum(
                group["vat"]
                for group in row["groups"]
                if vat.CATEGORIES[group["key"]].vat_field
            )
            if (net, tax) != (row["net"], row["vat"]):
                out.append(row["number"])
    return out


def _sub(parent: Any, tag: str, text: Any = None, **attrs: str) -> Any:
    node = etree.SubElement(parent, f"{{{NS}}}{tag}", attrs)
    if text is not None:
        node.text = str(text)
    return node


def _marker(node: Any, ksef_number: Optional[str]) -> None:
    if ksef_number and KSEF.match(ksef_number):
        _sub(node, "NrKSeF", ksef_number)
    else:
        _sub(node, "BFK", 1)


def _row(parent: Any, kind: str, index: int, row: dict[str, Any]) -> dict[str, int]:
    sales = kind == "sales"
    node = _sub(parent, "SprzedazWiersz" if sales else "ZakupWiersz")
    _sub(node, "LpSprzedazy" if sales else "LpZakupu", index)
    code, number = counterparty(row.get("tax_id"), row.get("country"))
    if code:
        _sub(node, "KodKrajuNadaniaTIN", code)
    _sub(node, "NrKontrahenta" if sales else "NrDostawcy", number[:50])
    _sub(
        node,
        "NazwaKontrahenta" if sales else "NazwaDostawcy",
        _clip(row.get("counterparty"), 512),
    )
    _sub(
        node,
        "DowodSprzedazy" if sales else "DowodZakupu",
        _clip(row.get("number"), 256),
    )
    day = _iso(row["date"])
    issued = _iso(row.get("issue_date")) or day
    _sub(node, "DataWystawienia" if sales else "DataZakupu", issued.isoformat())
    if day != issued:
        _sub(node, "DataSprzedazy" if sales else "DataWplywu", day.isoformat())
    _marker(node, row.get("ksef_number"))
    if sales:
        # GTU_01…GTU_13, potem procedury (TP) — sekwencja z XSD.
        for key in MARKERS:
            if key in (row.get("markers") or ()):
                _sub(node, key, 1)
    fields = row_fields(row["groups"])
    for key in SALES_K if sales else PURCHASE_K:
        if key in fields:
            _sub(node, key, money(fields[key]))
    return fields


def fingerprint(data: dict[str, Any]) -> str:
    """Odcisk rejestrów (dokumenty i kwoty) — zmiana po wysłaniu = korekta JPK."""

    rows = []
    for kind in ("sales", "purchases"):
        for row in data[kind]:
            entry: list[Any] = [
                kind,
                row["document_id"],
                row["net"],
                row["vat"],
                sorted((g["key"], g["net"], g["vat"]) for g in row["groups"]),
            ]
            # Znaczniki tylko, gdy są — odcisk wysłanych wersji bez znaczników
            # (K5b-1) zostaje ten sam (K5b-2).
            if row.get("markers"):
                entry.append(sorted(row["markers"]))
            rows.append(entry)
    raw = json.dumps(sorted(rows), ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def build(
    data: dict[str, Any],
    *,
    company: payroll_parameters.Company,
    email: str,
    phone: str,
    purpose: str,
    reason: Optional[str],
    surplus: int,
    now: datetime,
) -> tuple[bytes, dict[str, Any]]:
    """XML JPK_V7M(3) i sumy deklaracji z rejestrów miesiąca (pełnych — D2)."""

    root = etree.Element(f"{{{NS}}}JPK", nsmap={None: NS, "etd": ETD})
    head = _sub(root, "Naglowek")
    _sub(
        head,
        "KodFormularza",
        "JPK_VAT",
        kodSystemowy="JPK_V7M (3)",
        wersjaSchemy="1-0E",
    )
    _sub(head, "WariantFormularza", 3)
    _sub(
        head,
        "DataWytworzeniaJPK",
        now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    _sub(head, "NazwaSystemu", SYSTEM)
    _sub(head, "CelZlozenia", 2 if purpose == "correction" else 1, poz="P_7")
    _sub(head, "KodUrzedu", company.tax_office_code)
    _sub(head, "Rok", data["year"])
    _sub(head, "Miesiac", data["month"])
    subject = _sub(_sub(root, "Podmiot1", rola="Podatnik"), "OsobaNiefizyczna")
    _sub(subject, "NIP", company.nip)
    _sub(subject, "PelnaNazwa", _clip(company.name, 240))
    _sub(subject, "Email", email)
    if phone:
        _sub(subject, "Telefon", phone)

    # Ewidencja liczona przed deklaracją (sumy pól K_), dopinana na końcu.
    records = etree.Element(f"{{{NS}}}Ewidencja")
    sums: dict[str, int] = {}
    output_tax = input_tax = 0
    for kind, ctrl, count_tag, tax_tag in (
        ("sales", "SprzedazCtrl", "LiczbaWierszySprzedazy", "PodatekNalezny"),
        ("purchases", "ZakupCtrl", "LiczbaWierszyZakupow", "PodatekNaliczony"),
    ):
        tax = 0
        for index, row in enumerate(data[kind], start=1):
            fields = _row(records, kind, index, row)
            for key, value in fields.items():
                sums[key] = sums.get(key, 0) + value
            if kind == "sales":
                tax += sum(fields.get(key, 0) for key in TAX_PLUS) - sum(
                    fields.get(key, 0) for key in TAX_MINUS
                )
            else:
                tax += sum(fields.get(key, 0) for key in INPUT_TAX)
        node = _sub(records, ctrl)
        _sub(node, count_tag, len(data[kind]))
        _sub(node, tax_tag, money(tax))
        if kind == "sales":
            output_tax = tax
        else:
            input_tax = tax

    fields = declaration(sums, surplus=surplus)
    form = _sub(root, "Deklaracja")
    form_head = _sub(form, "Naglowek")
    _sub(
        form_head,
        "KodFormularzaDekl",
        "VAT-7",
        kodSystemowy="VAT-7 (23)",
        kodPodatku="VAT",
        rodzajZobowiazania="Z",
        wersjaSchemy="1-0E",
    )
    _sub(form_head, "WariantFormularzaDekl", 23)
    positions = _sub(form, "PozycjeSzczegolowe")
    for key in P_ORDER:
        if key in fields:
            _sub(positions, key, fields[key])
    if purpose == "correction" and reason:
        _sub(positions, "P_ORDZU", reason)
    _sub(form, "Pouczenia", 1)
    root.append(records)
    content = etree.tostring(root, xml_declaration=True, encoding="UTF-8")
    totals = {
        **{
            key: fields[key]
            for key in ("P_38", "P_39", "P_48", "P_51", "P_53", "P_62")
            if key in fields
        },
        "sales_rows": len(data["sales"]),
        "purchase_rows": len(data["purchases"]),
        "output_tax": output_tax,
        "input_tax": input_tax,
        "fingerprint": fingerprint(data),
    }
    return content, totals


@lru_cache(maxsize=1)
def _schema() -> Any:
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    return etree.XMLSchema(etree.parse(str(SCHEMA), parser))


def validate(content: bytes) -> list[str]:
    """Błędy schematu MF (pierwsze kilka); pusta lista = plik poprawny."""

    schema = _schema()
    document = etree.fromstring(
        content, etree.XMLParser(resolve_entities=False, no_network=True)
    )
    if schema.validate(document):
        return []
    return [
        f"wiersz {error.line}: {error.message}"
        for error in list(schema.error_log)[:ERRORS_SHOWN]
    ]


def can_prepare(viewer: Viewer) -> bool:
    return viewer.approver and (viewer.payroll or viewer.admin)


def can_download(viewer: Viewer) -> bool:
    return viewer.payroll or viewer.admin


def _previous(year: int, month: int) -> tuple[int, int]:
    return (year, month - 1) if month > 1 else (year - 1, 12)


async def _files(db: AsyncSession, year: int, month: int) -> list[LedgerVatFile]:
    return list(
        (
            await db.scalars(
                select(LedgerVatFile)
                .where(LedgerVatFile.year == year, LedgerVatFile.month == month)
                .order_by(LedgerVatFile.version)
            )
        ).all()
    )


async def previous_surplus(db: AsyncSession, year: int, month: int) -> Optional[int]:
    """P_62 z JPK poprzedniego miesiąca (ostatni wysłany, inaczej ostatni);
    ``None`` = w NEXUSIE nie ma JPK za poprzedni miesiąc."""

    files = await _files(db, *_previous(year, month))
    if not files:
        return None
    sent = [item for item in files if item.status == "sent"]
    latest = (sent or files)[-1]
    return int((latest.totals or {}).get("P_62", 0))


def _payload(item: LedgerVatFile, viewer: Viewer) -> dict[str, Any]:
    out = {
        "id": item.id,
        "version": item.version,
        "purpose": item.purpose,
        "status": item.status,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "sent_at": item.sent_at.isoformat() if item.sent_at else None,
        "sent_note": item.sent_note,
    }
    if can_download(viewer):
        totals = item.totals or {}
        out["totals"] = {
            key: totals.get(key)
            for key in (
                "P_38",
                "P_39",
                "P_48",
                "P_51",
                "P_62",
                "sales_rows",
                "purchase_rows",
            )
        }
        out["reason"] = item.reason
    return out


async def _missing(
    db: AsyncSession, settings: LedgerSettings
) -> tuple[payroll_parameters.Company, list[str]]:
    company = await payroll_parameters.load_company(db)
    missing = []
    if not company.tax_office_code:
        missing.append("kod urzędu skarbowego (Płace → Parametry → Dane płatnika)")
    if not settings.jpk.email:
        missing.append("e-mail do JPK (zakładka VAT, administrator)")
    return company, missing


async def overview(
    db: AsyncSession, viewer: Viewer, settings: LedgerSettings, *, year: int, month: int
) -> dict[str, Any]:
    """Wersje JPK miesiąca i to, czego brakuje do przygotowania (bez kwot bez Płac)."""

    files = await _files(db, year, month)
    _, missing = await _missing(db, settings)
    surplus = await previous_surplus(db, year, month)
    payroll = can_download(viewer)
    return {
        "year": year,
        "month": month,
        "files": [_payload(item, viewer) for item in files],
        "purpose": "correction"
        if any(item.status == "sent" for item in files)
        else "submission",
        "needs_opening_surplus": surplus is None and not files,
        # Pierwszy miesiąc w NEXUSIE: P_39 wpisuje się (i poprawia) przy każdej
        # wersji; potem przychodzi z P_62 poprzedniego JPK.
        "surplus_editable": surplus is None,
        "surplus_value": (month_surplus(files) if surplus is None else surplus)
        if payroll
        else None,
        "previous_surplus": surplus if payroll else None,
        "stale": await _stale(db, viewer, settings, files, year=year, month=month),
        "missing": missing,
        "notes": NOTES,
        "contact": {"email": settings.jpk.email, "phone": settings.jpk.phone},
        "can_prepare": can_prepare(viewer),
        "can_download": payroll,
        "can_mark_sent": viewer.approver,
        "can_edit_contact": viewer.admin,
    }


async def prepare(
    db: AsyncSession,
    viewer: Viewer,
    settings: LedgerSettings,
    *,
    year: int,
    month: int,
    reason: Optional[str],
    opening_surplus: Optional[int],
    now: datetime,
) -> dict[str, Any]:
    """Nowa wersja JPK miesiąca (bez commita): rejestry pełne, XSD, zapis pliku."""

    if not can_prepare(viewer):
        raise LedgerError(PREPARE_ONLY, status=403)
    problem = period_problem(year, month)
    if problem:
        raise LedgerError(problem, status=422)
    await db.execute(select(func.pg_advisory_xact_lock(func.hashtext(LOCK_KEY))))
    company, missing = await _missing(db, settings)
    if missing:
        raise LedgerError(f"Do JPK brakuje: {'; '.join(missing)}.", status=422)
    data = await vat.registers(
        db, replace(viewer, payroll=True), settings, year=year, month=month
    )
    blockers = [issue for issue in data["issues"] if issue["kind"] in BLOCKING]
    if blockers:
        listed = "; ".join(f"{issue['label']}: {issue['count']}" for issue in blockers)
        raise LedgerError(
            f"JPK nie powstanie, dopóki rejestr jest niepełny — {listed}.", status=422
        )
    unfit = row_problems(data)
    if unfit:
        raise LedgerError(
            "Kwoty tych dokumentów nie mieszczą się w polach JPK — sprawdź je: "
            f"{', '.join(unfit[:10])}.",
            status=422,
        )
    files = await _files(db, year, month)
    purpose = (
        "correction" if any(item.status == "sent" for item in files) else "submission"
    )
    text = " ".join((reason or "").split())[:REASON_MAX]
    if purpose == "correction" and len(text) < 3:
        raise LedgerError(
            "Korekta JPK: podaj uzasadnienie przyczyn korekty (P_ORDZU).", status=422
        )
    previous = await previous_surplus(db, year, month)
    surplus: Optional[int]
    if previous is not None:
        if opening_surplus is not None and opening_surplus != previous:
            raise LedgerError(
                "P_39 to P_62 z JPK za poprzedni miesiąc w NEXUSIE "
                f"({previous} zł) — nie wpisuje się jej ręcznie.",
                status=422,
            )
        surplus = previous
    elif opening_surplus is not None:
        # Pierwszy miesiąc w NEXUSIE: kwota z deklaracji z Symfonii, poprawialna
        # w każdej wersji (literówka nie zostaje w korektach — przegląd K5b).
        surplus = opening_surplus
    else:
        surplus = month_surplus(files)
    if surplus is None:
        raise LedgerError(
            "W NEXUSIE nie ma JPK za poprzedni miesiąc — podaj nadwyżkę z poprzedniej "
            "deklaracji (P_62, w pełnych złotych; 0, gdy jej nie było).",
            status=422,
        )
    if surplus < 0:
        raise LedgerError(
            "Nadwyżka z poprzedniej deklaracji nie może być ujemna.", status=422
        )
    content, totals = build(
        data,
        company=company,
        email=settings.jpk.email,
        phone=settings.jpk.phone,
        purpose=purpose,
        reason=text or None,
        surplus=surplus,
        now=now,
    )
    errors = validate(content)
    if errors:
        raise LedgerError(
            f"Plik JPK nie przechodzi schematu MF — {' | '.join(errors)}", status=422
        )
    item = LedgerVatFile(
        year=year,
        month=month,
        version=(files[-1].version + 1) if files else 1,
        purpose=purpose,
        reason=text if purpose == "correction" else None,
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
        totals=totals,
        status="prepared",
        created_by=viewer.user_id,
        created_at=now,
    )
    db.add(item)
    await db.flush()
    warnings = [
        f"{issue['label']}: {issue['count']}"
        for issue in data["issues"]
        if issue["kind"] not in BLOCKING
    ]
    return {"file": _payload(item, viewer), "warnings": warnings}


async def _get(db: AsyncSession, file_id: int) -> LedgerVatFile:
    item = await db.get(LedgerVatFile, file_id)
    if item is None:
        raise LedgerError("Nie ma takiego pliku JPK.", status=404)
    return item


async def download(db: AsyncSession, viewer: Viewer, file_id: int) -> tuple[str, bytes]:
    if not can_download(viewer):
        raise LedgerError(DOWNLOAD_ONLY, status=403)
    item = await _get(db, file_id)
    return f"JPK_V7M_{item.year}-{item.month:02d}_v{item.version}.xml", item.content


async def mark_sent(
    db: AsyncSession,
    viewer: Viewer,
    file_id: int,
    *,
    note: Optional[str],
    now: datetime,
) -> dict[str, Any]:
    """„Wysłany” (bez commita): wersja, którą wysłano bramką MF, z numerem UPO.

    Może to być starsza wersja (wysłana, zanim ktoś przygotował nową) — pozostałe
    nie wysłane wersje miesiąca stają się unieważnione. Ta sama blokada co
    „Przygotuj JPK”, żeby cel złożenia nowej wersji nie powstał z nieaktualnego
    stanu (przegląd K5b)."""

    if not viewer.approver:
        raise LedgerError(
            "Wysłanie JPK oznacza osoba z listy „Księgowi” albo administrator.",
            status=403,
        )
    await db.execute(select(func.pg_advisory_xact_lock(func.hashtext(LOCK_KEY))))
    item = await _get(db, file_id)
    if item.status != "prepared":
        raise LedgerError(
            "Ta wersja JPK jest już wysłana albo unieważniona.", status=409
        )
    files = await _files(db, item.year, item.month)
    if any(other.status == "sent" and other.version > item.version for other in files):
        raise LedgerError("Za ten miesiąc wysłano już nowszą wersję JPK.", status=409)
    if item.purpose == "submission" and any(other.status == "sent" for other in files):
        raise LedgerError(
            "Ta wersja to złożenie, a za ten miesiąc JPK jest już wysłany — "
            "przygotuj korektę.",
            status=409,
        )
    item.status = "sent"
    item.sent_at = now
    item.sent_by = viewer.user_id
    item.sent_note = " ".join((note or "").split())[:NOTE_MAX] or None
    for other in files:
        if other.id != item.id and other.status == "prepared":
            other.status = "void"
    await db.flush()
    return _payload(item, viewer)


def month_surplus(files: list[LedgerVatFile]) -> Optional[int]:
    """P_39 wersji tego miesiąca (wysłanej, inaczej ostatniej); ``None`` = brak."""

    if not files:
        return None
    sent = [item for item in files if item.status == "sent"]
    return int(((sent or files)[-1].totals or {}).get("P_39", 0))


async def _stale(
    db: AsyncSession,
    viewer: Viewer,
    settings: LedgerSettings,
    files: list[LedgerVatFile],
    *,
    year: int,
    month: int,
) -> Optional[str]:
    """Czy wysłany JPK jest nieaktualny: ``surplus`` — korekta poprzedniego
    miesiąca zmieniła P_62 (P_39 tego), ``registers`` — rejestr zmienił się po
    wysłaniu; ``None`` = aktualny albo nic nie wysłano."""

    sent = [item for item in files if item.status == "sent"]
    if not sent:
        return None
    last = sent[-1].totals or {}
    previous = await previous_surplus(db, year, month)
    if previous is not None and int(last.get("P_39", 0)) != previous:
        return "surplus"
    data = await vat.registers(
        db, replace(viewer, payroll=True), settings, year=year, month=month
    )
    return "registers" if fingerprint(data) != last.get("fingerprint") else None


async def month_status(
    db: AsyncSession, viewer: Viewer, settings: LedgerSettings, *, year: int, month: int
) -> dict[str, Any]:
    """Stan JPK do listy zamknięcia: ostatnia ważna wersja i czy wysłany plik jest
    nieaktualny (odcisk z rejestrów pełnych i P_39 — bez kwot w odpowiedzi)."""

    files = await _files(db, year, month)
    live = [item for item in files if item.status != "void"]
    if not live:
        return {"latest": None, "changed": False, "reason": None}
    latest = live[-1]
    reason = await _stale(db, viewer, settings, files, year=year, month=month)
    return {
        "latest": {
            "version": latest.version,
            "status": latest.status,
            "sent_at": latest.sent_at.isoformat() if latest.sent_at else None,
            "sent_note": latest.sent_note,
        },
        "changed": reason is not None,
        "reason": reason,
    }
