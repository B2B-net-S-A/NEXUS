"""Umowy B2B z NIP-em innej firmy (Finanse → Rozliczenia, audyt 25.11.2026).

Faktury kontraktorów z KSeF wiążą się z kontraktem po NIP-ie, a osoba bez
zatwierdzonego NIP-u (``candidates.nip``) ma tylko ``partner_nip`` z generatora
umów B2B. Ten bywa NIP-em innej firmy: inkubatora, który wystawia za wielu
konsultantów, albo firmy innej osoby. Takie faktury czekają teraz na Finanse
(``contractor_invoices.by_seller_nip``), a ta lista mówi, których kontraktów to
dotyczy, zanim Finanse zobaczą podpowiedź na karcie osoby.

Kontrakt trafia na listę, gdy jego ``partner_nip`` (bez własnego NIP-u osoby):

* ma w generatorze imię i nazwisko innej osoby niż kontrakt (``partner_name``
  to osoba, nie firma — patrz model),
* albo ma faktury z KSeF (kosztowe i kontraktorów), w których nazwie
  sprzedawcy nie ma imienia i nazwiska osoby z kontraktu.

Firma osoby bez jej nazwiska w nazwie (spółka z o.o.) też tu trafia: Finanse
zatwierdzają ją raz na karcie osoby i kontrakt znika z listy.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

from sqlalchemy import func, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_settlement import ClientContractorInvoice
from app.models.contract import Contract
from app.models.hr_approval import ApprovalDocument
from app.services.client_identity import client_display_name
from app.services.client_settlements.contractor_invoices import clean_nip, in_scope
from app.services.client_settlements.rcp_checks import name_tokens

PARTNER_OTHER_PERSON = "partner_other_person"
SELLER_WITHOUT_PERSON = "seller_without_person"
REASON_LABELS = {
    PARTNER_OTHER_PERSON: "W umowie B2B jako Partner jest inna osoba",
    SELLER_WITHOUT_PERSON: "Faktury z tego NIP-u wystawia firma bez imienia i nazwiska osoby",
}


@dataclass(frozen=True)
class _Row:
    contract_id: int
    client_id: Optional[int]
    first: Optional[str]
    last: Optional[str]
    partner_nip: str
    partner_name: Optional[str]
    partner_legal_name: Optional[str]
    generated_id: int


def _named(person: frozenset[str], text: Optional[str]) -> bool:
    return len(person) >= 2 and person <= name_tokens(text)


async def _rows(db: AsyncSession, today: date) -> list[_Row]:
    latest = (
        select(
            B2BGeneratedContract.contract_id,
            func.max(B2BGeneratedContract.id).label("generated_id"),
        )
        .where(
            B2BGeneratedContract.contract_id.is_not(None),
            B2BGeneratedContract.partner_nip.is_not(None),
        )
        .group_by(B2BGeneratedContract.contract_id)
        .subquery()
    )
    found = await db.execute(
        select(
            Contract.id,
            Contract.client_id,
            Candidate.name,
            Candidate.lastname,
            Candidate.nip,
            B2BGeneratedContract.partner_nip,
            B2BGeneratedContract.partner_name,
            B2BGeneratedContract.partner_legal_name,
            B2BGeneratedContract.id,
        )
        .join(latest, latest.c.contract_id == Contract.id)
        .join(B2BGeneratedContract, B2BGeneratedContract.id == latest.c.generated_id)
        .outerjoin(Candidate, Candidate.id == Contract.candidate_id)
        .where(in_scope(today))
        .order_by(Contract.id)
    )
    out = []
    for cid, client_id, first, last, own, partner, name, legal, gid in found.all():
        nip = clean_nip(partner)
        if nip and not clean_nip(own):
            out.append(
                _Row(int(cid), client_id, first, last, nip, name, legal, int(gid))
            )
    return out


async def _sellers(db: AsyncSession, nips: set[str]) -> dict[str, dict[str, int]]:
    """NIP → nazwa sprzedawcy → liczba faktur z KSeF (kosztowe i kontraktorów)."""

    if not nips:
        return {}
    both = union_all(
        select(
            ApprovalDocument.seller_nip.label("nip"),
            ApprovalDocument.seller_name.label("name"),
            ApprovalDocument.ksef_number.label("ksef"),
        ).where(
            ApprovalDocument.source == "ksef",
            ApprovalDocument.seller_nip.in_(nips),
        ),
        select(
            ClientContractorInvoice.seller_nip,
            ClientContractorInvoice.seller_name,
            ClientContractorInvoice.ksef_number,
        ).where(ClientContractorInvoice.seller_nip.in_(nips)),
    ).subquery()
    rows = await db.execute(
        select(
            both.c.nip, both.c.name, func.count(func.distinct(both.c.ksef))
        ).group_by(both.c.nip, both.c.name)
    )
    out: dict[str, dict[str, int]] = {}
    for nip, name, count in rows.all():
        out.setdefault(nip, {})[(name or "").strip() or "bez nazwy"] = int(count)
    return out


async def review(db: AsyncSession, today: date) -> dict[str, Any]:
    rows = await _rows(db, today)
    sellers = await _sellers(db, {row.partner_nip for row in rows})
    clients = {
        client.id: client_display_name(client)
        for client in await db.scalars(
            select(Client).where(
                Client.id.in_({row.client_id for row in rows if row.client_id})
            )
        )
    }
    items = []
    for row in rows:
        person = frozenset(name_tokens(f"{row.first or ''} {row.last or ''}"))
        reasons = []
        partner = name_tokens(row.partner_name)
        if len(partner) >= 2 and len(person) >= 2 and not person <= partner:
            reasons.append(PARTNER_OTHER_PERSON)
        names = sellers.get(row.partner_nip, {})
        if names and not any(_named(person, name) for name in names):
            reasons.append(SELLER_WITHOUT_PERSON)
        if not reasons:
            continue
        items.append(
            {
                "contract_id": row.contract_id,
                "client_id": row.client_id,
                "client_name": clients.get(row.client_id),
                "person": " ".join(p for p in (row.first, row.last) if p) or None,
                "partner_nip": row.partner_nip,
                "partner_name": row.partner_name,
                "partner_legal_name": row.partner_legal_name,
                "generated_contract_id": row.generated_id,
                "sellers": [
                    {"name": name, "invoices": count}
                    for name, count in sorted(names.items(), key=lambda nc: -nc[1])
                ],
                "invoices": sum(names.values()),
                "reasons": [{"key": r, "label": REASON_LABELS[r]} for r in reasons],
            }
        )
    items.sort(key=lambda item: (-item["invoices"], item["contract_id"]))
    return {"items": items}


__all__ = ["REASON_LABELS", "review"]
