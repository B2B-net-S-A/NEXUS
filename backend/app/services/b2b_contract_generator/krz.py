"""Sprawdzenie Partnera w Krajowym Rejestrze Zadłużonych (0799, 27.11.2026).

Prośba Błażeja i decyzje Artura z 27.11.2026 (makiety:
https://claude.ai/artifact/52333FTbcTvAGNovhQ4Rs3):

* **Półautomat.** KRZ nie ma API (FAQ Ministerstwa Sprawiedliwości, pyt. 8),
  więc NEXUS otwiera portal z NIP-em albo PESEL-em, a człowiek zaznacza wynik.
  NEXUS zapisuje wynik, kto i kiedy (``row.krz_check``). Gdy przyjdzie API od
  pośrednika, zastąpi tylko kliknięcie człowieka.
* **NIP i PESEL.** PESEL służy wyłącznie do wyszukania w portalu: nie trafia
  do API ani do bazy (RODO, wyrok NSA III OSK 1109/25). Zapisujemy sam wynik.
* **Bramka.** Wiersz B2B z Generatora bez wyniku albo z wpisem bez decyzji nie
  idzie do podpisu w NEXUSIE i nie da się go oznaczyć jako podpisanego. Wpis
  rozstrzyga Delivery Lead klienta (bez niego Head of Recruitment); admin
  i Head of Recruitment mogą zawsze. DOCX pobiera się bez przeszkód.
* **Poza bramką:** umowa zlecenia, wiersz z Excela, wiersz podpisany i umowa
  z wysyłki do aktywnych kontraktorów (trwające kontrakty są „na później,
  z API”).

Kształt ``krz_check``::

    {"result": "clear" | "entry", "entry_kind": str | None,
     "entry_note": str | None, "nip": "1234567890" | None,
     "checked_at": ISO, "checked_by": user_id,
     "decision": "allowed" | "rejected" | None, "decision_reason": str | None,
     "decided_at": ISO | None, "decided_by": user_id | None}
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.b2b_mass_send import B2BMassSendItem
from app.models.job import Job
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User, UserRole
from app.services.b2b_contract_generator import mandate

RESULT_CLEAR = "clear"
RESULT_ENTRY = "entry"
DECISION_ALLOWED = "allowed"
DECISION_REJECTED = "rejected"

KrzResult = Literal["clear", "entry"]
KrzDecision = Literal["allowed", "rejected"]

# Rodzaje wpisów z art. 2 ust. 1 ustawy o KRZ (Dz.U. 2025 poz. 1584).
ENTRY_KINDS: dict[str, str] = {
    "bankruptcy": "Upadłość",
    "consumer_bankruptcy": "Upadłość konsumencka",
    "restructuring": "Restrukturyzacja",
    "enforcement": "Umorzona egzekucja (bezskuteczna)",
    "business_ban": "Zakaz prowadzenia działalności",
    "alimony": "Dłużnik alimentacyjny",
    "other": "Inny wpis",
}
ENTRY_NOTE_MAX = 300
REASON_MAX = 500

# Portal publiczny KRZ — wyszukiwarka podmiotów. NIP i PESEL nie idą w adresie,
# człowiek wkleja je z NEXUSA (schowek).
PORTAL_URL = (
    "https://krz.ms.gov.pl/#!/application/KRZPortalPUB/1.9/"
    "KrzRejPubGui.WyszukiwaniePodmiotow?params=JTdCJTdE&seq=0"
)

MSG_NOT_CHECKED = (
    "Najpierw sprawdź Partnera w Krajowym Rejestrze Zadłużonych "
    "(przycisk „Sprawdź w KRZ”)."
)
MSG_WAITING_DECISION = (
    "Partner ma wpis w Krajowym Rejestrze Zadłużonych. Do podpisu umowa pójdzie "
    "po decyzji Delivery Leada klienta."
)
MSG_REJECTED = (
    "Delivery Lead nie dopuścił tej umowy do podpisu z powodu wpisu w Krajowym "
    "Rejestrze Zadłużonych."
)
MSG_NIP_CHANGED = (
    "NIP Partnera zmienił się po sprawdzeniu. Sprawdź go w Krajowym Rejestrze "
    "Zadłużonych jeszcze raz."
)


def nip_digits(value: Optional[str]) -> Optional[str]:
    digits = "".join(ch for ch in (value or "") if ch.isdigit())
    return digits or None


async def mass_send_row_ids(db: AsyncSession, row_ids: list[int]) -> set[int]:
    if not row_ids:
        return set()
    found = await db.scalars(
        select(B2BMassSendItem.generated_contract_id).where(
            B2BMassSendItem.generated_contract_id.in_(row_ids)
        )
    )
    return {rid for rid in found.all() if rid is not None}


def applies(row: B2BGeneratedContract, *, from_mass_send: bool) -> bool:
    """Czy bramka KRZ dotyczy tego wiersza (bez względu na stan sprawdzenia)."""
    if (row.source or "generator") != "generator":
        return False
    if mandate.is_mandate(row):
        return False
    if row.signature_status == "signed_both":
        return False
    return not from_mass_send


def current_check(row: B2BGeneratedContract) -> Optional[dict[str, Any]]:
    """Zapisany wynik, o ile dotyczy obecnego NIP-u Partnera.

    Poprawa umowy z innym NIP-em unieważnia wynik (inna firma), a wiersz bez
    NIP-u w chwili sprawdzenia (np. sam PESEL) zostaje ważny.
    """
    check = row.krz_check
    if not isinstance(check, dict) or check.get("result") not in (
        RESULT_CLEAR,
        RESULT_ENTRY,
    ):
        return None
    checked_nip = check.get("nip")
    if checked_nip and nip_digits(row.partner_nip) not in (None, checked_nip):
        return None
    return check


def nip_changed(row: B2BGeneratedContract) -> bool:
    check = row.krz_check
    return (
        isinstance(check, dict)
        and bool(check.get("nip"))
        and current_check(row) is None
    )


def block_reason(row: B2BGeneratedContract, *, from_mass_send: bool) -> Optional[str]:
    """Komunikat, który zatrzymuje wysyłkę i potwierdzenie podpisu; None = wolno."""
    if not applies(row, from_mass_send=from_mass_send):
        return None
    check = current_check(row)
    if check is None:
        return MSG_NIP_CHANGED if nip_changed(row) else MSG_NOT_CHECKED
    if check["result"] == RESULT_CLEAR:
        return None
    decision = check.get("decision")
    if decision == DECISION_ALLOWED:
        return None
    if decision == DECISION_REJECTED:
        return MSG_REJECTED
    return MSG_WAITING_DECISION


async def gate_reason(db: AsyncSession, row: B2BGeneratedContract) -> Optional[str]:
    from_mass_send = bool(await mass_send_row_ids(db, [row.id]))
    return block_reason(row, from_mass_send=from_mass_send)


def new_check(
    *,
    result: KrzResult,
    entry_kind: Optional[str],
    entry_note: Optional[str],
    nip: Optional[str],
    actor_id: int,
    now: datetime,
) -> dict[str, Any]:
    clean_note = (entry_note or "").strip()[:ENTRY_NOTE_MAX] or None
    is_entry = result == RESULT_ENTRY
    return {
        "result": result,
        "entry_kind": entry_kind if is_entry else None,
        "entry_note": clean_note if is_entry else None,
        "nip": nip_digits(nip),
        "checked_at": now.isoformat(),
        "checked_by": actor_id,
        "decision": None,
        "decision_reason": None,
        "decided_at": None,
        "decided_by": None,
    }


def same_result(old: Optional[dict[str, Any]], new: dict[str, Any]) -> bool:
    """Ten sam wynik dla tego samego NIP-u — ponowne pobranie DOCX go nie nadpisuje."""
    if not isinstance(old, dict):
        return False
    keys = ("result", "entry_kind", "entry_note", "nip")
    return all(old.get(k) == new.get(k) for k in keys)


def with_decision(
    check: dict[str, Any],
    *,
    decision: KrzDecision,
    reason: str,
    actor_id: int,
    now: datetime,
) -> dict[str, Any]:
    return {
        **check,
        "decision": decision,
        "decision_reason": reason.strip()[:REASON_MAX],
        "decided_at": now.isoformat(),
        "decided_by": actor_id,
    }


async def decider_ids(db: AsyncSession, row: B2BGeneratedContract) -> list[int]:
    """Kto rozstrzyga wpis: DL rekrutacji i DL klienta, bez nich Head of Recruitment."""
    ids: list[int] = []
    if row.job_id is not None:
        job_dl = await db.scalar(select(Job.delivery_lead_id).where(Job.id == row.job_id))
        if job_dl is not None:
            ids.append(job_dl)
    if row.client_id is not None:
        portfolio = await db.execute(
            select(DeliveryLeadClientAssignment.delivery_lead_user_id)
            .where(DeliveryLeadClientAssignment.client_id == row.client_id)
            .order_by(DeliveryLeadClientAssignment.is_head.desc())
        )
        ids.extend(uid for (uid,) in portfolio.all())
    active = await _active_with_role(db, ids, UserRole.delivery_lead)
    if active:
        return active
    hor = await db.scalars(
        select(User.id).where(
            User.roles.contains([UserRole.head_of_recruitment.value]),
            User.is_active.is_(True),
        )
    )
    return list(hor.all())


async def _active_with_role(
    db: AsyncSession, ids: list[int], role: UserRole
) -> list[int]:
    if not ids:
        return []
    rows = await db.scalars(
        select(User.id).where(
            User.id.in_(ids),
            User.is_active.is_(True),
            User.roles.contains([role.value]),
        )
    )
    allowed = set(rows.all())
    seen: set[int] = set()
    ordered: list[int] = []
    for uid in ids:
        if uid in allowed and uid not in seen:
            seen.add(uid)
            ordered.append(uid)
    return ordered


def always_decides(user: User) -> bool:
    return user.has_any_role(UserRole.admin, UserRole.head_of_recruitment)


@dataclass(frozen=True)
class EntryLabel:
    kind: Optional[str]
    label: str


def entry_label(check: Optional[dict[str, Any]]) -> Optional[EntryLabel]:
    if not isinstance(check, dict) or check.get("result") != RESULT_ENTRY:
        return None
    kind = check.get("entry_kind")
    return EntryLabel(kind=kind, label=ENTRY_KINDS.get(kind or "", "Wpis w KRZ"))
