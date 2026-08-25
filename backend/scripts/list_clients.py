#!/usr/bin/env python3
"""Read-only podgląd klientów — ``id`` + nazwa, po fragmencie nazwy.

Po co osobne narzędzie: kilka polityk domenowych jest bramkowanych LISTĄ
``client_id`` w zmiennych środowiskowych (``MULTI_CONSULTANT_ORDER_CLIENT_IDS``,
``COST_ORDER_CLIENT_IDS``, ``BANK_POCZTOWY_ORDER_EXTRACTION_CLIENT_IDS``,
``CREDIT_AGRICOLE_ORDER_EXTRACTION_CLIENT_IDS``, ``ERSTE_GROSS_RATE_CLIENT_IDS``).
Bramka po ID, nie po nazwie, jest świadoma — Traffit nadpisuje ``Client.name``,
a rodzina rekordów tego samego banku bywa większa niż jeden wiersz. Cena tej
decyzji: żeby WŁĄCZYĆ politykę, trzeba znać numer, a numeru nie widać ani
w interfejsie, ani w repo. Bez tego skryptu jedyną drogą był panel Coolify
albo SSH — a SSH na tym serwerze nie działa.

**Wyłącznie SELECT.** Skrypt nie ma ścieżki zapisu i nie przyjmuje SQL-a
z zewnątrz: filtr jedzie parametrem wiązanym, a wildcardy ``%``/``_`` są
escapowane, więc ``%`` szuka znaku procenta, a nie zwraca całej bazy.

Wyjście jest CELOWO ubogie — ``id``, nazwa, nazwa wyświetlana, NIP. Żadnych
kwot, żadnych osób: to narzędzie odpowiada na pytanie „który numer wpisać
w zmienną", a jego wyjście ląduje w logu GitHub Actions.

Z ``--with-links`` dokłada, co do każdego znalezionego klienta jest
przypięte: kontrakty i umowy z generatora B2B. To jest materiał do
rozstrzygnięcia pomyłki „dwa podobnie nazwane rekordy klienta" (BNP Paribas
Cardif ↔ CARDIF - ASSURANCES…), której nie da się zobaczyć z interfejsu ani
policzyć bez dostępu do bazy. Wypisujemy IDENTYFIKATORY i statusy, a z osób —
samo nazwisko: log Actions ma pozwolić wskazać wiersz do poprawki, a nie
odtworzyć kartotekę.

Użycie::

    python -m scripts.list_clients --like cardif
    python -m scripts.list_clients --like cardif --with-links
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import func, or_, select

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.models.b2b_generated_contract import B2BGeneratedContract  # noqa: E402
from app.models.candidate import Candidate  # noqa: E402
from app.models.client import Client  # noqa: E402
from app.models.client_order import ClientOrder  # noqa: E402
from app.models.contract import Contract  # noqa: E402

# Znak ucieczki dla LIKE. Bez tego fragment „100%" albo „a_b" zachowuje się
# jak wzorzec, a nie jak tekst — ta sama reguła co w wyszukiwarce umów B2B.
_ESCAPE = "\\"


def escape_like(value: str) -> str:
    """Wildcardy LIKE stają się zwykłymi znakami."""
    return (
        value.replace(_ESCAPE, _ESCAPE * 2)
        .replace("%", f"{_ESCAPE}%")
        .replace("_", f"{_ESCAPE}_")
    )


async def find_clients(needle: str, limit: int) -> list[tuple[int, str, str, str]]:
    pattern = f"%{escape_like(needle.strip().lower())}%"
    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            select(Client.id, Client.name, Client.display_name, Client.nip)
            .where(
                or_(
                    func.lower(Client.name).like(pattern, escape=_ESCAPE),
                    func.lower(func.coalesce(Client.display_name, "")).like(
                        pattern, escape=_ESCAPE
                    ),
                    func.lower(func.coalesce(Client.legal_name, "")).like(
                        pattern, escape=_ESCAPE
                    ),
                )
            )
            .order_by(Client.id)
            .limit(limit)
        )
        return [(r[0], r[1] or "", r[2] or "", r[3] or "") for r in rows.all()]


async def print_links(client_ids: list[int]) -> None:
    """Kontrakty i umowy B2B przypięte do wskazanych klientów.

    ``job_client_id`` obok ``client_id`` to sedno raportu: rozjazd między
    klientem PRZYPISANYM a klientem REKRUTACJI, z której powiązanie powstało,
    jest najmocniejszą przesłanką pomyłki dostępną maszynowo.
    """
    if not client_ids:
        return
    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            select(
                Contract.id,
                Contract.client_id,
                Contract.status,
                Contract.job_id,
                Candidate.lastname,
                Candidate.name,
            )
            .join(Candidate, Candidate.id == Contract.candidate_id, isouter=True)
            .where(Contract.client_id.in_(client_ids))
            .order_by(Contract.id)
        )
        contracts = rows.all()
        print(f"=== contracts on those clients: {len(contracts)} ===")
        for cid, client_id, status, job_id, lastname, first in contracts:
            who = f"{(first or '')[:1]}. {lastname or ''}".strip()
            st = getattr(status, "value", status)
            print(
                f"contract={cid}\tclient={client_id}\tstatus={st}\tjob={job_id}\t{who}"
            )

        rows = await db.execute(
            select(
                B2BGeneratedContract.id,
                B2BGeneratedContract.contract_number,
                B2BGeneratedContract.client_id,
                B2BGeneratedContract.client_name,
                B2BGeneratedContract.job_id,
                B2BGeneratedContract.contract_id,
                B2BGeneratedContract.contract_status,
                B2BGeneratedContract.partner_name,
            )
            .where(B2BGeneratedContract.client_id.in_(client_ids))
            .order_by(B2BGeneratedContract.id)
        )
        gen = rows.all()
        print(f"=== b2b generated contracts on those clients: {len(gen)} ===")
        for gid, number, client_id, cname, job_id, contract_id, st, partner in gen:
            print(
                f"b2b={gid}\tnr={number}\tclient={client_id}\tprinted={cname}"
                f"\tjob={job_id}\tcontract={contract_id}\tstatus={st}\tpartner={partner}"
            )

        # Zamówienia klienta. Bez nich nie da się ODPOWIEDZIALNIE przepiąć
        # kontraktu na innego klienta: `client_orders` niesie WŁASNE
        # `client_id`, więc zmiana samego kontraktu zostawia zamówienie
        # wskazujące poprzedniego klienta — dokładnie te „osierocone powiązane
        # rekordy", o których sprawdzenie prosi ticket.
        #
        # `order_group_id` jest tu nośne: linia należąca do grupy
        # wielo-konsultantowej ma dodatkowe więzy, więc przepięcie jej samej
        # byłoby innym rodzajem sieroty.
        rows = await db.execute(
            select(
                ClientOrder.id,
                ClientOrder.client_id,
                ClientOrder.contract_id,
                ClientOrder.title,
                ClientOrder.status,
                ClientOrder.order_group_id,
            )
            .where(ClientOrder.client_id.in_(client_ids))
            .order_by(ClientOrder.id)
        )
        orders = rows.all()
        print(f"=== client orders on those clients: {len(orders)} ===")
        for oid, client_id, contract_id, title, order_status, group_id in orders:
            order_status = getattr(order_status, "value", order_status)
            print(
                f"order={oid}\tclient={client_id}\tcontract={contract_id}"
                f"\tstatus={order_status}\tgroup={group_id}\ttitle={title}"
            )


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--like", required=True, help="fragment nazwy klienta")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument(
        "--with-links",
        action="store_true",
        help="dołóż kontrakty i umowy B2B przypięte do znalezionych klientów",
    )
    args = parser.parse_args()

    rows = await find_clients(args.like, max(1, min(args.limit, 200)))
    # Nagłówek drukujemy ZAWSZE, także przy zerze trafień: pusty wydruk
    # w logu Actions nie odróżnia „nic nie pasuje" od „skrypt się nie wykonał".
    print(f"=== clients matching {args.like!r}: {len(rows)} ===")
    for cid, name, display, nip in rows:
        print(f"{cid}\t{name}\tdisplay={display}\tnip={nip}")
    if args.with_links:
        await print_links([r[0] for r in rows])


if __name__ == "__main__":
    asyncio.run(main())
