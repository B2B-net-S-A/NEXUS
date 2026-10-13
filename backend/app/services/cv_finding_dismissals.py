"""„To nieprawda” — pominięte uwagi QC CV i edytora (0439, 13.10.2026, D5).

Zespół mówił, że QC daje dużo nieprawdziwych uwag i nie da się ich odznaczyć:
ta sama fałszywa uwaga wracała przy każdym otwarciu okna i blokowała ruch.
Pominięcie dotyczy pary (kandydat, rekrutacja) i klucza uwagi, który liczy
serwer z pól pozycji (`cv_qc._assign_keys`). Nakłada je jedno miejsce —
`cv_qc.evaluate` — więc okno QC, zapisany przebieg (plakietka na Tablicy),
bramka ruchu, obejście i propozycje AI widzą to samo.

Uwagi, których nie da się pominąć (`NOT_DISMISSABLE`): brak CV firmowego
i reguły klienta (stawka, kontakt, zgoda RODO) — to ochrona przed wysłaniem
stawki albo kontaktu do klienta, nie ocena treści.
"""

from __future__ import annotations

import hashlib
import unicodedata
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cv_finding_dismissal import CvFindingDismissal
from app.services import dz_review as dz

# Powód → (etykieta, czy to błąd QC). Trafność sprawdzenia (`qc_quality`)
# liczą tylko powody „QC się myli”; „nie dotyczy” i „inny” to decyzja
# rekrutera, nie dowód, że sprawdzenie kłamie.
REASONS: dict[str, tuple[str, bool]] = {
    "in_cv": ("Jest w CV — QC tego nie znalazło", True),
    "other_name": ("Jest w źródłach pod inną nazwą", True),
    "wrong_place": ("Dotyczy innej roli albo sekcji", True),
    "not_needed": ("Nie dotyczy tej rekrutacji", False),
    "other": ("Inny powód", False),
}
QC_WRONG_REASONS = frozenset(code for code, (_, wrong) in REASONS.items() if wrong)
NOT_DISMISSABLE = frozenset({"cv_present", "client_rules"})
SOURCES = ("qc", "generator", "review")
NOTE_MAX = 500
QUOTE_MAX = 300
LABEL_MAX = 300


class DismissError(Exception):
    """Pominięcia nie da się zapisać — komunikat dla rekrutera (422)."""


def text_key(text: str, status: Optional[str] = None) -> str:
    """Klucz uwagi generatora albo kontroli AI: skrót znormalizowanego tekstu
    (i statusu kontroli AI — „niepotwierdzone” i „sprzeczne” to dwie uwagi)."""
    nkfd = unicodedata.normalize("NFKD", " ".join((text or "").split()).casefold())
    folded = "".join(ch for ch in nkfd if not unicodedata.combining(ch))
    raw = f"{folded}|{status}" if status else folded
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _view(row: CvFindingDismissal, by_name: Optional[str]) -> dict[str, Any]:
    label, _ = REASONS.get(row.reason, (row.reason, False))
    return {
        "id": row.id,
        "reason": row.reason,
        "reason_label": label,
        "note": row.note,
        "by_name": by_name,
        # Napis ISO, nie datetime: widok trafia do `checks`, które QC skrótuje
        # zwykłym `json.dumps` (`cv_qc._checks_hash`).
        "at": row.created_at.isoformat() if row.created_at else None,
    }


async def active(
    db: AsyncSession,
    candidate_id: int,
    job_id: int,
    sources: Iterable[str] = SOURCES,
) -> list[dict[str, Any]]:
    """Aktywne pominięcia pary: klucz, źródło, sprawdzenie i widok dla okna."""
    from app.models.user import User

    rows = (
        await db.execute(
            select(CvFindingDismissal, User.name)
            .outerjoin(User, User.id == CvFindingDismissal.dismissed_by_user_id)
            .where(
                CvFindingDismissal.candidate_id == candidate_id,
                CvFindingDismissal.job_id == job_id,
                CvFindingDismissal.source.in_(tuple(sources)),
                CvFindingDismissal.restored_at.is_(None),
            )
            .order_by(CvFindingDismissal.created_at.desc())
        )
    ).all()
    return [
        {
            "key": row.finding_key,
            "source": row.source,
            "check_key": row.check_key,
            "label": row.label,
            "view": _view(row, name),
        }
        for row, name in rows
    ]


def apply_dismissals(checks: list[dict], dismissals: list[dict[str, Any]]) -> int:
    """Przenieś pominięte pozycje QC do ``dismissed_items`` i przelicz status.

    Zwraca liczbę pominiętych pozycji blokujących. Pominięcie pozycji roli
    umiejętności krytycznej, której nie ma w CV w ogóle (``absent_in_cv``),
    nie ukrywa braku w całym CV — wraca jako osobna pozycja.
    """

    by_key = {d["key"]: d for d in dismissals if d["source"] == "qc"}
    blocking = 0
    if not by_key:
        return 0
    for check in checks:
        if check["key"] in NOT_DISMISSABLE:
            continue
        kept: list[dict] = []
        dismissed: list[dict] = []
        for item in check["items"]:
            hit = by_key.get(item.get("key") or "")
            if hit is None:
                kept.append(item)
            else:
                dismissed.append({**item, "dismissal": hit["view"]})
        if not dismissed:
            continue
        if check["key"] == "critical_skills":
            kept.extend(_whole_cv_gaps(kept, dismissed, by_key))
        check["items"] = kept
        check["dismissed_items"] = dismissed
        if check["severity"] == "blocking":
            blocking += len(dismissed)
        if check["status"] == "fail" and not kept:
            check["status"] = "pass"
        check["summary"] = f"{check['summary']} · pominięte: {len(dismissed)}"
    return blocking


def _whole_cv_gaps(
    kept: list[dict], dismissed: list[dict], by_key: dict[str, dict]
) -> list[dict]:
    """Krytyczna nieobecna w całym CV, której pozycje ról ktoś pominął."""
    still = {item.get("requirement") for item in kept}
    out: list[dict] = []
    for name in dict.fromkeys(
        item.get("requirement") for item in dismissed if item.get("absent_in_cv")
    ):
        if not name or name in still:
            continue
        # Ten sam zapis klucza co `cv_qc._assign_keys`.
        key = f"critical_skills|{dz._fold(' '.join(str(name).split()))}|cv"
        if key in by_key:
            continue
        out.append(
            {
                "key": key,
                "requirement": name,
                "detail": (
                    "Brak w CV — pominięta uwaga dotyczyła roli, a tej "
                    "umiejętności nie ma w całym CV."
                ),
                "fix": None,
            }
        )
    return out


def validate_reason(reason: str, note: Optional[str]) -> tuple[str, Optional[str]]:
    if reason not in REASONS:
        raise DismissError("Wybierz powód pominięcia.")
    clean = " ".join((note or "").split())[:NOTE_MAX] or None
    if reason == "other" and not clean:
        raise DismissError("Opisz, dlaczego uwaga jest nieprawdziwa.")
    return reason, clean


def new_row(
    *,
    candidate_id: int,
    job_id: int,
    stage_id: Optional[int],
    source: str,
    check_key: str,
    key: str,
    label: str,
    reason: str,
    note: Optional[str],
    quote: Optional[str],
    blocking: bool,
    user_id: int,
) -> CvFindingDismissal:
    return CvFindingDismissal(
        candidate_id=candidate_id,
        job_id=job_id,
        candidate_stage_id=stage_id,
        source=source,
        check_key=check_key[:40],
        finding_key=key[:400],
        label=(label or key)[:LABEL_MAX],
        reason=reason,
        note=note,
        evidence_quote=(quote or None) and quote[:QUOTE_MAX],
        blocking=blocking,
        dismissed_by_user_id=user_id,
        created_at=datetime.now(timezone.utc),
    )


async def insert_once(db: AsyncSession, row: CvFindingDismissal) -> bool:
    """Zapisz pominięcie; ``False``, gdy ta uwaga pary jest już pominięta.

    Podwójne kliknięcie albo dwie osoby naraz trafiają w indeks częściowy
    `uq_cv_finding_dismissals_active` — drugi wiersz to nie błąd, tylko ta sama
    decyzja. Zapis w savepoincie, żeby nie wycofać reszty transakcji.
    """
    from sqlalchemy.exc import IntegrityError

    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError:
        return False
    return True


async def restore(
    db: AsyncSession,
    *,
    dismissal_id: int,
    candidate_id: int,
    job_id: int,
    user_id: Optional[int],
    reason: str = "user",
) -> CvFindingDismissal:
    row = await db.get(CvFindingDismissal, dismissal_id)
    if (
        row is None
        or row.candidate_id != candidate_id
        or row.job_id != job_id
        or row.restored_at is not None
    ):
        raise DismissError("Tego pominięcia już nie ma — odśwież okno.")
    row.restored_at = datetime.now(timezone.utc)
    row.restored_by_user_id = user_id
    row.restored_reason = reason
    return row


async def has_blocking(db: AsyncSession, candidate_id: int, job_id: int) -> bool:
    """Czy para ma aktywne pominięcie uwagi blokującej."""
    return (
        await db.scalar(
            select(CvFindingDismissal.id)
            .where(
                CvFindingDismissal.candidate_id == candidate_id,
                CvFindingDismissal.job_id == job_id,
                CvFindingDismissal.blocking.is_(True),
                CvFindingDismissal.restored_at.is_(None),
            )
            .limit(1)
        )
    ) is not None


async def restore_on_card_return(
    db: AsyncSession, candidate_id: int, job_id: int
) -> int:
    """Zwrot karty przywraca pominięcia uwag blokujących osób bez prawa
    wysyłki — jak obejście doradcze (`cv_qc.spend_advisory_overrides`): po
    cofnięciu przez Delivery Leada QC znów pyta. Bez commitu.

    Prawo wysyłki autora to uprawnienie z bazy (panel „Osoby i role”), nie
    domyślny zestaw roli — stąd `resolve_effective_access` (audyt 48 h)."""
    from app.models.user import User
    from app.services.action_permissions import ProductAction, has_permission
    from app.services.effective_access import resolve_effective_access

    rows = (
        await db.scalars(
            select(CvFindingDismissal).where(
                CvFindingDismissal.candidate_id == candidate_id,
                CvFindingDismissal.job_id == job_id,
                CvFindingDismissal.blocking.is_(True),
                CvFindingDismissal.restored_at.is_(None),
            )
        )
    ).all()
    if not rows:
        return 0
    authors = {r.dismissed_by_user_id for r in rows if r.dismissed_by_user_id}
    users = {
        u.id: u
        for u in (await db.scalars(select(User).where(User.id.in_(authors)))).all()
    }
    await resolve_effective_access(db, users.values())
    spent = [
        r.id
        for r in rows
        if not (
            r.dismissed_by_user_id in users
            and has_permission(
                users[r.dismissed_by_user_id], ProductAction.recruitment_manage
            )
        )
    ]
    if spent:
        await db.execute(
            update(CvFindingDismissal)
            .where(CvFindingDismissal.id.in_(spent))
            .values(
                restored_at=datetime.now(timezone.utc),
                restored_reason="card_returned",
            )
        )
    return len(spent)
