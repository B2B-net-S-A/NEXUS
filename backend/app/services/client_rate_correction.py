"""Zmiana stawki do klienta po wysyłce CV (20.10.2026, wariant A).

Delivery Lead wpisuje stawkę do klienta przy „CV wysłane”, a potem klient
negocjuje albo okazuje się, że w oknie wysyłki była pomyłka. Poprawka idzie
tą samą trasą co dotąd (``PATCH …/client-rate``), ale:

* niesie powód (``REASONS``) i opcjonalną notatkę — powód ląduje w audycie
  ``client_rate_changed``, notatka jako wpis ``dl_rate`` (rekruter widzi
  zdanie zastępcze, jak przy każdej cenie dla klienta);
* po powstaniu zamówienia na tę parę stawki nie zmienia się w rekrutacji,
  tylko w zamówieniu (decyzja Artura 20.10.2026) — ``order_lock``;
* historia (``history``) składa się z wiersza wysyłki i wpisów audytu.
  Osobnej tabeli nie ma: audyt zapisywał stara → nowa kwota od P1-11.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract
from app.models.note import Note, NoteType
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User
from app.services import candidate_audit, note_kinds

REASONS: dict[str, str] = {
    "client_negotiated": "Klient wynegocjował inną stawkę",
    "send_mistake": "Pomyłka przy wysyłce CV",
    "other": "Inny powód",
}
NOTE_MAX = 500
NOTE_SOURCE = note_kinds.CLIENT_RATE_CHANGE_SOURCE

_UNIT_SUFFIX = {"hourly": "zł/h", "daily": "zł/dzień", "monthly": "zł/mies."}


@dataclass(frozen=True)
class RateValue:
    value: float
    unit: Optional[str]
    currency: Optional[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "unit": self.unit,
            "currency": self.currency or "PLN",
        }


@dataclass(frozen=True)
class SentRow:
    """Pierwszy wiersz „CV wysłane” pary — kiedy i kto wysłał."""

    at: datetime
    by_name: Optional[str]


@dataclass(frozen=True)
class AuditRow:
    at: datetime
    by_name: Optional[str]
    old: Optional[RateValue]
    new: Optional[RateValue]
    reason: Optional[str]
    note_id: Optional[int]


def rate_label(rate: Optional[RateValue]) -> str:
    if rate is None:
        return "brak stawki"
    amount = f"{rate.value:.2f}".rstrip("0").rstrip(".")
    suffix = _UNIT_SUFFIX.get(rate.unit or "", rate.unit or "")
    if rate.currency and rate.currency != "PLN":
        suffix = suffix.replace("zł", rate.currency)
    return f"{amount} {suffix}".strip()


def note_content(
    old: Optional[RateValue], new: Optional[RateValue], reason: str, text: Optional[str]
) -> str:
    """Treść wpisu ``dl_rate`` przy zmianie — kwoty, powód i słowa DL-a."""

    line = (
        f"Stawka do klienta zmieniona: {rate_label(old)} → {rate_label(new)} "
        f"({REASONS[reason]})."
    )
    extra = " ".join((text or "").split())
    return f"{line} {extra}" if extra else line


def record_note(
    db: AsyncSession,
    *,
    candidate_id: int,
    job_id: int,
    author_id: int,
    content: str,
) -> Note:
    note = Note(
        content=content,
        note_type=NoteType.general,
        candidate_id=candidate_id,
        job_id=job_id,
        author_id=author_id,
        external_source=NOTE_SOURCE,
        kind=note_kinds.DL_RATE,
    )
    db.add(note)
    return note


async def order_lock(
    db: AsyncSession, *, candidate_id: int, job_id: int
) -> Optional[dict[str, Any]]:
    """Zamówienie tej pary (bez anulowanych) — wtedy stawkę zmienia się w nim.

    Zamówienie należy do pary, gdy wskazuje tę rekrutację, albo — zamówienie
    sprzed pola ``job_id`` — gdy jego kontrakt powstał z tej rekrutacji.
    """

    row = (
        await db.execute(
            select(ClientOrder.id, ClientOrder.contract_id, ClientOrder.title)
            .join(Contract, Contract.id == ClientOrder.contract_id)
            .where(
                Contract.candidate_id == candidate_id,
                ClientOrder.status != ClientOrderStatus.cancelled,
                or_(
                    ClientOrder.job_id == job_id,
                    and_(ClientOrder.job_id.is_(None), Contract.job_id == job_id),
                ),
            )
            .order_by(ClientOrder.id.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    # Bez kwot zamówienia: historię czyta każda rola ze stawką do klienta,
    # a kwoty zamówień Delivery Lead widzi tylko w swoim portfelu.
    order_id, contract_id, title = row
    return {"order_id": order_id, "contract_id": contract_id, "title": title}


def order_lock_message(lock: dict[str, Any]) -> str:
    return (
        f"Ta osoba ma już zamówienie „{lock['title']}”. Stawkę do klienta "
        "zmień w zamówieniu, nie w rekrutacji."
    )


def build_history(
    *,
    sent: Optional[SentRow],
    audits: list[AuditRow],
    current: Optional[RateValue],
    note_texts: dict[int, str],
) -> dict[str, Any]:
    """Wysyłka + zmiany po niej, najnowsze na górze.

    Kwota wysyłki to „stara” kwota pierwszej zmiany po wysyłce (wiersz etapu
    mógł zostać nadpisany), a bez zmian — bieżąca stawka. Zmiany sprzed
    wysyłki (np. wpis w profilu przed „CV wysłane”) nie są historią po
    wysyłce.
    """

    after = [a for a in audits if sent is None or a.at >= sent.at]
    after.sort(key=lambda a: a.at)
    if sent is None:
        sent_payload = None
    else:
        sent_rate = after[0].old if after else current
        sent_payload = {
            "at": sent.at.isoformat(),
            "by_name": sent.by_name,
            "rate": sent_rate.as_dict() if sent_rate else None,
            "label": rate_label(sent_rate) if sent_rate else None,
        }
    changes = [
        {
            "at": a.at.isoformat(),
            "by_name": a.by_name,
            "old": a.old.as_dict() if a.old else None,
            "new": a.new.as_dict() if a.new else None,
            "old_label": rate_label(a.old),
            "new_label": rate_label(a.new),
            "reason": a.reason if a.reason in REASONS else None,
            "reason_label": REASONS.get(a.reason or ""),
            "note": _own_words(a, note_texts.get(a.note_id) if a.note_id else None),
        }
        for a in reversed(after)
    ]
    return {
        "current": current.as_dict() if current else None,
        "current_label": rate_label(current) if current else None,
        "sent": sent_payload,
        "changes": changes,
    }


def _own_words(row: AuditRow, content: Optional[str]) -> Optional[str]:
    """Słowa DL-a z wpisu ``dl_rate`` — bez zdania o kwotach, które historia i tak
    pokazuje. Wpis zmieniony później ręcznie zostaje w całości."""

    if not content or row.reason not in REASONS:
        return content or None
    prefix = note_content(row.old, row.new, row.reason, None)
    if content == prefix:
        return None
    if content.startswith(prefix + " "):
        return content[len(prefix) + 1 :]
    return content


def rate_from_details(details: dict[str, Any], prefix: str) -> Optional[RateValue]:
    """Kwota ``old``/``new`` z ``details`` wpisu audytu ``client_rate_changed``."""

    value = details.get(f"{prefix}_client_rate")
    if value is None:
        return None
    return RateValue(
        value=float(value),
        unit=details.get(f"{prefix}_client_rate_unit"),
        currency=details.get(f"{prefix}_client_rate_currency"),
    )


async def history(
    db: AsyncSession, *, candidate_id: int, job_id: int
) -> dict[str, Any]:
    from app.services.stage_client_rate import latest_client_rates

    sent_row = (
        await db.execute(
            select(CandidateStage.moved_at, User.name)
            .outerjoin(User, User.id == CandidateStage.moved_by)
            .where(
                CandidateStage.candidate_id == candidate_id,
                CandidateStage.job_id == job_id,
                CandidateStage.stage == PipelineStage.cv_sent,
            )
            .order_by(CandidateStage.moved_at, CandidateStage.id)
            .limit(1)
        )
    ).first()
    sent = SentRow(at=sent_row[0], by_name=sent_row[1]) if sent_row else None

    audit_rows = (
        await db.execute(
            select(Activity.created_at, Activity.details, User.name)
            .outerjoin(User, User.id == Activity.user_id)
            .where(
                Activity.entity_type == "candidate",
                Activity.entity_id == candidate_id,
                Activity.action == candidate_audit.CLIENT_RATE_CHANGED,
                Activity.details["job_id"].astext == str(job_id),
            )
            .order_by(Activity.created_at, Activity.id)
        )
    ).all()
    audits = []
    for at, details, by_name in audit_rows:
        details = details or {}
        note_id = details.get("note_id")
        audits.append(
            AuditRow(
                at=at,
                by_name=by_name,
                old=rate_from_details(details, "old"),
                new=rate_from_details(details, "new"),
                reason=details.get("reason"),
                note_id=int(note_id) if isinstance(note_id, int) else None,
            )
        )
    note_ids = [a.note_id for a in audits if a.note_id]
    note_texts: dict[int, str] = {}
    if note_ids:
        note_texts = {
            nid: content
            for nid, content in (
                await db.execute(
                    select(Note.id, Note.content).where(Note.id.in_(note_ids))
                )
            ).all()
        }

    latest = (await latest_client_rates(db, [(candidate_id, job_id)])).get(
        (candidate_id, job_id)
    )
    current = RateValue(*latest) if latest else None
    return build_history(
        sent=sent, audits=audits, current=current, note_texts=note_texts
    )
