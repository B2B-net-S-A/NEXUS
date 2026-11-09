#!/usr/bin/env python3
"""Sonda EBI24: co naprawdę jest na koncie, zanim zaprojektujemy integrację.

Tylko odczyt (klient nie wysyła innych akcji) i tylko liczniki: bez nazw, NIP-ów,
numerów faktur i KSeF, kwot, identyfikatorów dokumentów. Wynik można bezpiecznie
pokazać, ale uruchamiaj ją z terminala, nie w publicznych logach Actions.

Odpowiada na pytania z ``docs/claude/integracje/ebi24-api-odczyt-i-pomiar.md``:

* ile dokumentów każdego typu ma konto,
* jaka część najnowszych faktur ma numer KSeF i status ``paid``,
* czy ``getKsefData`` daje XML, który czyta parser NEXUSA,
* czy filtr ``_createdDate`` z samą datą, po którym dostawca zaleca pobierać nowe
  dokumenty, naprawdę zawęża listę,
* czy pola ``paidAmount`` i ``remainingAmount`` są w nagłówku, czy dopiero
  w danych dokumentu, i czy zdarzają się płatności częściowe.

Użycie (w kontenerze backendu, po ustawieniu ``EBI24_*``)::

    python -m scripts.ebi24_probe
    python -m scripts.ebi24_probe --max-rows 2000 --xml-sample 10 --payment-sample 20

Duże pobrania podręcznik dopuszcza w godzinach 20:00–7:00; domyślne limity to
około 40 żądań.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import timedelta
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.scheduling import business_today  # noqa: E402
from app.services.client_invoicing import fa_sales  # noqa: E402
from app.services.ebi24.client import PAGE_SIZE_MAX, Ebi24ApiError, Ebi24Client  # noqa: E402
from app.services.ebi24.environment import load_config  # noqa: E402
from app.services.hr.ksef import fa, numbers  # noqa: E402

EXIT_DISABLED = 2
EXIT_API_ERROR = 3
SCHEMAS = ("INCOME_INVOICE", "COST_INVOICE", "INCOME_ORDER", "COST_ORDER", "FILE")
INVOICE_SCHEMAS = ("INCOME_INVOICE", "COST_INVOICE")
NEWEST_FIRST = ["-_bucketNumber"]
DATE_FILTER_DAYS = 30
#: Wartości słownikowe; wszystko inne liczymy jako „INNY”, żeby tekst z pola nie
#: przeszedł do wyniku.
_TOKEN = re.compile(r"^[A-Z][A-Z_]{0,39}$")
_MONTH = re.compile(r"^(\d{4}-\d{2})-\d{2}")
_DATE_CHARS = re.compile(r"^[\dT:.+Z -]{4,35}$")
MISSING = "(brak)"
OTHER = "INNY"


def _token(value: object) -> str:
    if value in (None, ""):
        return MISSING
    return value if isinstance(value, str) and _TOKEN.match(value) else OTHER


def _date_shape(value: object) -> str:
    """``9999-99-99`` zamiast wartości; inny tekst liczymy jako „INNY”."""

    if value in (None, ""):
        return MISSING
    if not isinstance(value, str) or not _DATE_CHARS.match(value):
        return OTHER
    return re.sub(r"\d", "9", value)


def _has_valid_number(row: dict[str, Any]) -> bool:
    return numbers.is_valid(row.get("_ksefReferenceNumber"))


def summarize(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Liczniki z nagłówków: do wyniku trafiają tylko wartości słownikowe i miesiące."""

    months: Counter[str] = Counter()
    for row in rows:
        issued = row.get("issuedDate")
        match = _MONTH.match(issued) if isinstance(issued, str) else None
        if match:
            months[match.group(1)] += 1
    origin = (
        row.get("_origin") if isinstance(row.get("_origin"), dict) else {}
        for row in rows
    )
    return {
        "rows": len(rows),
        "ksef_status": dict(Counter(_token(row.get("_ksefStatus")) for row in rows)),
        "valid_ksef_number": sum(_has_valid_number(row) for row in rows),
        "origin_channel": dict(Counter(_token(item.get("channel")) for item in origin)),
        "invoice_type": dict(Counter(_token(row.get("invoiceType")) for row in rows)),
        "paid_true": sum(row.get("paid") is True for row in rows),
        "paid_with_date": sum(
            row.get("paid") is True and bool(row.get("paidDate")) for row in rows
        ),
        "header_paid_amount": sum(row.get("paidAmount") is not None for row in rows),
        "header_remaining_amount": sum(
            row.get("remainingAmount") is not None for row in rows
        ),
        "issued_month": dict(sorted(months.items())),
        "created_date_shape": dict(
            Counter(_date_shape(row.get("_createdDate")) for row in rows)
        ),
        "with_custom_fields": sum(bool(row.get("customFields")) for row in rows),
        "with_tags": sum(bool(row.get("_documentTags")) for row in rows),
        "with_folder": sum(bool(row.get("_documentFolder")) for row in rows),
    }


async def _newest(
    client: Ebi24Client, schema: str, max_rows: int
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    while len(rows) < max_rows:
        page = await client.list_documents(
            {"_schemaName": schema},
            start_row=len(rows),
            end_row=min(len(rows) + PAGE_SIZE_MAX, max_rows),
            sort_by=NEWEST_FIRST,
        )
        if not page.documents:
            break
        rows.extend(page.documents)
        if len(rows) >= page.total:
            break
    return rows


async def _date_filter(client: Ebi24Client, schema_total: int) -> dict[str, Any]:
    """Filtr z dokładnością do dnia; odmowa jest wynikiem pomiaru, nie awarią."""

    since = (business_today() - timedelta(days=DATE_FILTER_DAYS)).isoformat()
    criteria = {
        "_constructor": "AdvancedCriteria",
        "operator": "and",
        "criteria": [
            {
                "fieldName": "_schemaName",
                "operator": "equals",
                "value": "INCOME_INVOICE",
            },
            {
                "fieldName": "_createdDate",
                "operator": "greaterOrEqual",
                "value": since,
            },
        ],
    }
    try:
        page = await client.list_documents(criteria, start_row=0, end_row=1)
    except Ebi24ApiError as error:
        if error.category != "rejected":
            raise
        return {"days": DATE_FILTER_DAYS, "accepted": False}
    return {
        "days": DATE_FILTER_DAYS,
        "accepted": True,
        "total": page.total,
        "narrowed": page.total < schema_total,
    }


async def _xml_sample(
    client: Ebi24Client, schema: str, rows: Iterable[dict[str, Any]], limit: int
) -> dict[str, int]:
    parse = (
        fa_sales.parse_sales_invoice if schema == "INCOME_INVOICE" else fa.parse_invoice
    )
    counts = {"ok": 0, "not_found": 0, "unreadable": 0}
    candidates = (
        row
        for row in rows
        if row.get("_ksefStatus") == "COMPLETED"
        and _has_valid_number(row)
        and isinstance(row.get("_id"), str)
    )
    for row in candidates:
        if sum(counts.values()) >= limit:
            break
        try:
            parse(await client.get_ksef_xml(row["_id"]))
        except fa.InvoiceParseError:
            counts["unreadable"] += 1
        except Ebi24ApiError as error:
            if error.category == "not_found":
                counts["not_found"] += 1
            elif error.category in ("rejected", "too_large"):
                counts["unreadable"] += 1
            else:
                raise
        else:
            counts["ok"] += 1
    return counts


def _is_positive(value: object) -> bool:
    return isinstance(value, int) and value > 0


async def _payment_sample(
    client: Ebi24Client, rows: Iterable[dict[str, Any]], limit: int
) -> dict[str, int]:
    """Pola płatności z danych dokumentu: po połowie opłaconych i nieopłaconych."""

    readable = [row for row in rows if isinstance(row.get("_id"), str)]
    paid = [row for row in readable if row.get("paid") is True]
    unpaid = [row for row in readable if row.get("paid") is not True]
    half = limit // 2
    picked = (
        paid[: max(half, limit - len(unpaid))]
        + unpaid[: max(limit - half, limit - len(paid))]
    )
    counts = {
        "read": 0,
        "with_paid_amount": 0,
        "with_remaining_amount": 0,
        "partial": 0,
        "unreadable": 0,
    }
    for row in picked:
        try:
            document = await client.get_document(row["_id"])
        except Ebi24ApiError as error:
            if error.category not in ("rejected", "not_found", "invalid_response"):
                raise
            counts["unreadable"] += 1
            continue
        paid_amount = document.get("paidAmount")
        remaining = document.get("remainingAmount")
        counts["read"] += 1
        counts["with_paid_amount"] += paid_amount is not None
        counts["with_remaining_amount"] += remaining is not None
        counts["partial"] += _is_positive(paid_amount) and _is_positive(remaining)
    return counts


async def probe(
    client: Ebi24Client, *, max_rows: int, xml_sample: int, payment_sample: int
) -> dict[str, Any]:
    totals = {}
    for schema in SCHEMAS:
        page = await client.list_documents(
            {"_schemaName": schema}, start_row=0, end_row=1, sort_by=NEWEST_FIRST
        )
        totals[schema] = page.total
    newest = {}
    samples = {}
    payments = {}
    for schema in INVOICE_SCHEMAS:
        rows = await _newest(client, schema, max_rows)
        newest[schema] = summarize(rows)
        samples[schema] = await _xml_sample(client, schema, rows, xml_sample)
        payments[schema] = await _payment_sample(client, rows, payment_sample)
    return {
        "totals": totals,
        "newest": newest,
        "xml_sample": samples,
        "payment_sample": payments,
        "date_filter": await _date_filter(client, totals["INCOME_INVOICE"]),
    }


async def _run(max_rows: int, xml_sample: int, payment_sample: int) -> dict[str, Any]:
    async with Ebi24Client(load_config()) as client:
        return await probe(
            client,
            max_rows=max_rows,
            xml_sample=xml_sample,
            payment_sample=payment_sample,
        )


def _print(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--max-rows", type=int, default=1000)
    parser.add_argument("--xml-sample", type=int, default=5)
    parser.add_argument("--payment-sample", type=int, default=10)
    args = parser.parse_args(argv)
    config = load_config()
    if not config.enabled:
        _print({"error": config.disabled_reason})
        return EXIT_DISABLED
    try:
        _print(asyncio.run(_run(args.max_rows, args.xml_sample, args.payment_sample)))
    except Ebi24ApiError as error:
        _print(
            {
                "error": error.category,
                "message": str(error),
                "http_status": error.status,
                "retry_after": error.retry_after,
            }
        )
        return EXIT_API_ERROR
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
