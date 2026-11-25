"""Kody osób klienta z pozycji faktur sprzedaży w KSeF → ``client_external_ids`` (25.11.2026).

Kontrola formalna faktur sprzedaży (reguła ``cl.contractor_person_id``) ostrzega
„NEXUS nie zna kodu … dopisz go w numerach osób”, gdy pozycja „Contractor
<osoba> ID: <kod>” nazywa osobę z kontraktem u klienta, a jej kodu nie ma
w kartotece. Automat ``time_reports.fill_from_ksef`` bierze kody tylko z faktur
przypiętych do linii zamówienia, więc faktury bez przypięcia zostawiały luki.

Skrypt bierze kod po „ID” przy pierwszej osobie po „Contractor” (bez osoby
klienta z „Contact:”), łączy osobę z kontraktem przez ``unknown_refs.same_person``
i dopisuje parę (kontrakt, kod), gdy:

* nazwisko z faktur pasuje do dokładnie jednej osoby z kontraktem u klienta,
* kodu nie ma jeszcze w kartotece klienta (u nikogo),
* osoba nie ma w kartotece ani w fakturach innego kodu,
* osoba ma jeden kontrakt albo dokładnie jeden obejmuje okres tych faktur.

Wpis: ``source=ksef_item``, ``state=suggested``, okres z miesięcy faktur.
Podpowiedź Finanse zatwierdzają albo odrzucają w kartotece raportu godzin
(Rozliczenia → Raport godzin); ``fill_from_ksef`` sam potwierdza ją, gdy kod
pojawi się na fakturze przypiętej do zamówienia tej osoby.

Wyjście skryptu to wyłącznie liczby. ``--review`` zapisuje CSV z nazwiskami
i kodami do przeglądu — dane osobowe: plik trzymaj poza repo.

Run:
    python -m scripts.backfill_client_person_numbers_from_ksef --client-id 11
    python -m scripts.backfill_client_person_numbers_from_ksef --client-id 11 --review /tmp/kody.csv
    python -m scripts.backfill_client_person_numbers_from_ksef --client-id 11 --apply
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Optional, Sequence

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import select, text  # noqa: E402

from app.core.database import AsyncSessionLocal, engine  # noqa: E402
from app.models.candidate import Candidate  # noqa: E402
from app.models.client_sales_invoice import ClientSalesInvoice  # noqa: E402
from app.models.client_time_report import ClientExternalId  # noqa: E402
from app.models.contract import Contract, ContractStatus  # noqa: E402
from app.services.client_invoicing import clients  # noqa: E402
from app.services.client_invoicing import unknown_refs as refs  # noqa: E402
from app.services.client_order_lines import month_bounds  # noqa: E402

logger = logging.getLogger("backfill_client_person_numbers_from_ksef")

#: Kod osoby u klienta po „ID” — ta sama postać co w kontroli formalnej faktury.
PERSON_CODE = re.compile(r"[A-Z]\d{5,7}")
_ID_FIELD = re.compile(r"\bID\b\s*:?\s*([^,;]*)", re.IGNORECASE)
SOURCE, STATE = "ksef_item", "suggested"

SKIP_OWNED = "kod jest już w kartotece klienta"
SKIP_NO_CONTRACT = "osoba bez kontraktu u klienta"
SKIP_AMBIGUOUS = "nazwisko pasuje do kilku osób"
SKIP_MANY_CODES = "osoba ma kilka kodów"
SKIP_MANY_CONTRACTS = "kilka kontraktów osoby obejmuje okres faktur"


@dataclass(frozen=True)
class Seen:
    """Kod przy osobie w jednej pozycji faktury."""

    code: str
    person: str
    month: str
    invoice_id: int


@dataclass(frozen=True)
class Holder:
    contract_id: int
    candidate_id: int
    person: str
    start: Optional[date]
    end: Optional[date]


@dataclass(frozen=True)
class Pair:
    contract_id: int
    code: str
    valid_from: date
    valid_to: date
    invoices: int
    invoice_names: tuple[str, ...]


def seen_in_item(name: str) -> Optional[tuple[str, str]]:
    """(osoba, kod) z „Contractor <osoba> ID: <kod>”; ``None`` bez obu."""

    people = refs.marked_people(name)
    found = _ID_FIELD.search(name)
    if not people or found is None or not found.group(1).split():
        return None
    token = found.group(1).split()[0].upper()
    if not PERSON_CODE.fullmatch(token):
        return None
    return people[0], token


def _overlaps(holder: Holder, first: date, last: date) -> bool:
    return (holder.start or date.min) <= last and (holder.end or date.max) >= first


def select_pairs(
    seen: Sequence[Seen],
    holders: Sequence[Holder],
    known: Iterable[tuple[int, str]],
) -> tuple[list[Pair], Counter[str]]:
    """Pary (kontrakt, kod) do dopisania i powody pominięcia (liczone na kod).

    ``known`` — (kontrakt, kod) już w kartotece klienta, w każdym stanie.
    """

    candidate_of = {h.contract_id: h.candidate_id for h in holders}
    owned: set[str] = set()
    codes_of: dict[int, set[str]] = defaultdict(set)
    for contract_id, code in known:
        owned.add(code.upper())
        if contract_id in candidate_of:
            codes_of[candidate_of[contract_id]].add(code.upper())

    matches: dict[str, tuple[Holder, ...]] = {}
    for item in seen:
        if item.person not in matches:
            matches[item.person] = tuple(
                h for h in holders if refs.same_person(h.person, item.person)
            )
    by_code: dict[str, list[Seen]] = defaultdict(list)
    for item in seen:
        by_code[item.code].append(item)
        hit = {h.candidate_id for h in matches[item.person]}
        if len(hit) == 1:
            codes_of[next(iter(hit))].add(item.code)

    pairs: list[Pair] = []
    skipped: Counter[str] = Counter()
    for code, items in sorted(by_code.items()):
        if code in owned:
            skipped[SKIP_OWNED] += 1
            continue
        hits = [matches[item.person] for item in items]
        candidates = {h.candidate_id for found in hits for h in found}
        if not candidates:
            skipped[SKIP_NO_CONTRACT] += 1
            continue
        if len(candidates) > 1:
            skipped[SKIP_AMBIGUOUS] += 1
            continue
        candidate = next(iter(candidates))
        if codes_of[candidate] != {code}:
            skipped[SKIP_MANY_CODES] += 1
            continue
        months = sorted({item.month for item in items})
        first, last = month_bounds(months[0])[0], month_bounds(months[-1])[1]
        own = {h.contract_id: h for found in hits for h in found}
        chosen = list(own.values())
        if len(chosen) > 1:
            chosen = [h for h in chosen if _overlaps(h, first, last)]
        if len(chosen) != 1:
            skipped[SKIP_MANY_CONTRACTS] += 1
            continue
        pairs.append(
            Pair(
                contract_id=chosen[0].contract_id,
                code=code,
                valid_from=first,
                valid_to=last,
                invoices=len({item.invoice_id for item in items}),
                invoice_names=tuple(sorted({item.person for item in items})),
            )
        )
    return pairs, skipped


async def _load(
    db, client_id: int
) -> tuple[list[Seen], list[Holder], list[tuple[int, str]]]:
    family = await clients.family(db, [client_id])
    holders = [
        Holder(
            contract_id=int(cid),
            candidate_id=int(cand),
            person=" ".join(part for part in (name, lastname) if part),
            start=start,
            end=end,
        )
        for cid, cand, name, lastname, start, end in (
            await db.execute(
                select(
                    Contract.id,
                    Contract.candidate_id,
                    Candidate.name,
                    Candidate.lastname,
                    Contract.start_date,
                    Contract.end_date,
                )
                .join(Candidate, Candidate.id == Contract.candidate_id)
                .where(
                    Contract.client_id.in_(family),
                    Contract.status != ContractStatus.void,
                )
            )
        ).all()
    ]
    known = [
        (int(cid), str(value))
        for cid, value in (
            await db.execute(
                select(ClientExternalId.contract_id, ClientExternalId.value).where(
                    ClientExternalId.client_id.in_(family),
                    ClientExternalId.kind == refs.PERSON_NO_KIND,
                )
            )
        ).all()
    ]
    seen: list[Seen] = []
    for invoice in await db.scalars(
        select(ClientSalesInvoice).where(
            ClientSalesInvoice.client_id.in_(family),
            ClientSalesInvoice.invoice_kind == "original",
            ClientSalesInvoice.invoice_type == "VAT",
        )
    ):
        sale = invoice.sale_date or invoice.issue_date
        month = (
            f"{invoice.period_year:04d}-{invoice.period_month:02d}"
            if invoice.period_year and invoice.period_month
            else f"{sale:%Y-%m}"
        )
        for item in invoice.items or []:
            if not isinstance(item, dict) or item.get("before_correction"):
                continue
            found = seen_in_item(str(item.get("name") or ""))
            if found is not None:
                seen.append(Seen(found[1], found[0], month, int(invoice.id)))
    return seen, holders, known


def _write_review(path: Path, pairs: Sequence[Pair], holders: Sequence[Holder]) -> None:
    person = {h.contract_id: h for h in holders}
    with path.open("w", newline="", encoding="utf-8") as fh:
        out = csv.writer(fh)
        out.writerow(
            [
                "contract_id",
                "kod",
                "osoba_w_kontrakcie",
                "osoba_na_fakturach",
                "start_kontraktu",
                "koniec_kontraktu",
                "od",
                "do",
                "faktury",
            ]
        )
        for pair in pairs:
            holder = person[pair.contract_id]
            out.writerow(
                [
                    pair.contract_id,
                    pair.code,
                    holder.person,
                    " / ".join(pair.invoice_names),
                    holder.start or "",
                    holder.end or "",
                    pair.valid_from,
                    pair.valid_to,
                    pair.invoices,
                ]
            )


async def run(client_id: int, *, apply: bool, review: Optional[Path]) -> dict:
    async with AsyncSessionLocal() as db:
        if not apply:
            # Dry-run nie może niczego zapisać, nawet przez pomyłkę w kodzie.
            await db.execute(text("SET TRANSACTION READ ONLY"))
        seen, holders, known = await _load(db, client_id)
        pairs, skipped = select_pairs(seen, holders, known)
        if review is not None:
            _write_review(review, pairs, holders)
        added: list[int] = []
        if apply:
            rows = [
                ClientExternalId(
                    client_id=client_id,
                    contract_id=pair.contract_id,
                    kind=refs.PERSON_NO_KIND,
                    value=pair.code,
                    valid_from=pair.valid_from,
                    valid_to=pair.valid_to,
                    source=SOURCE,
                    state=STATE,
                )
                for pair in pairs
            ]
            db.add_all(rows)
            await db.flush()
            added = [row.id for row in rows]
            await db.commit()
        else:
            await db.rollback()
    await engine.dispose()
    return {
        "mode": "apply" if apply else "dry-run",
        "items_with_code": len(seen),
        "codes": len({item.code for item in seen}),
        "pairs": len(pairs),
        "skipped": dict(skipped),
        # Id nowych wierszy — do cofnięcia jednym DELETE, bez nazwisk i kodów.
        "added_ids": added,
    }


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--client-id", type=int, required=True)
    parser.add_argument(
        "--apply", action="store_true", help="zapisz (domyślnie dry-run)"
    )
    parser.add_argument("--review", type=Path, help="CSV do przeglądu (dane osobowe)")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> None:
    logging.basicConfig(level=logging.WARNING)
    args = parse_args(argv)
    result = asyncio.run(run(args.client_id, apply=args.apply, review=args.review))
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
