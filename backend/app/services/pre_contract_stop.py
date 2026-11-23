"""„Zatrzymaj do podpisu przedwstępnej” — ustawienie rekrutacji i wybór przy osobie.

Decyzje Artura z 23.11.2026 (``docs/claude/rekrutacja-tablica/stop-do-podpisu-przedwstepnej.md``):

- rekrutacja (``jobs.pre_contract_rule``): każda osoba podpisuje przedwstępną
  przed wybranym etapem; ``stop`` = karta stoi do podpisu obu stron; prośby
  zakładają się same od „Zweryfikowanego”;
- osoba (``pre_contract_requests.blocks_move``): ``None`` = jak rekrutacja,
  ``True`` = stop, ``False`` = wyjątek;
- blokada liczy się od kolumny etapu (wejście na nią i dalej), obowiązuje
  także Delivery Leada; zdejmuje ją DL, Head of Recruitment i admin;
- znika po podpisie obu stron. Prośba zamknięta bez podpisu przy ustawieniu
  rekrutacji nie zwalnia karty (inaczej anulowanie byłoby furtką), chyba że
  ostatnia prośba niosła wyjątek.

Ten moduł nie zapisuje niczego poza ``ensure_rule_request`` — liczy blokadę
dla ruchu, okna „Przesuń dalej” i plakietki.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pre_contract import PreContractRequest
from app.services.board_stage_badges import BOARD_COLUMN_ORDER
from app.services import pre_contracts as svc
from app.services.pre_contracts import (
    NEEDED_BEFORE_LABEL,
    NEEDED_COLUMN,
    is_signed,
    pair_columns,
)

#: Etapy, które da się wybrać w ustawieniu rekrutacji („do daty” — tylko przy osobie).
RULE_STAGES: tuple[str, ...] = ("cv_sent", "client_interview", "b2b_contract")

STOP_CODE = "PRE_CONTRACT_NOT_SIGNED"
#: Kod `auto_advance_skipped`, gdy automat zostawił kartę przed blokadą.
SKIP_REASON = "pre_contract_not_signed"
MSG_STOP_ROLE = (
    "Zatrzymać osobę do podpisu albo zdjąć blokadę może Delivery Lead klienta, "
    "Head of Recruitment albo admin."
)


def rule_of(job: Any) -> Optional[dict[str, Any]]:
    """Ustawienie rekrutacji albo ``None`` (brak / zły kształt = brak)."""
    return rule_of_raw(getattr(job, "pre_contract_rule", None))


def rule_of_raw(raw: Any) -> Optional[dict[str, Any]]:
    if not isinstance(raw, Mapping):
        return None
    if raw.get("needed_before") not in RULE_STAGES:
        return None
    return {
        "needed_before": raw["needed_before"],
        "stop": bool(raw.get("stop")),
        "set_by": raw.get("set_by"),
        "set_by_name": raw.get("set_by_name"),
        "set_at": raw.get("set_at"),
    }


@dataclass(frozen=True)
class Stop:
    """Karta stoi do podpisu przedwstępnej przed ``column``."""

    column: str
    needed_before: str
    origin: str  # "job" | "person"
    set_by: Optional[int]
    set_at: Optional[str]
    request_id: Optional[int]

    @property
    def stage_label(self) -> str:
        return NEEDED_BEFORE_LABEL.get(self.needed_before, "")


def _index(column: Optional[str]) -> Optional[int]:
    if column is None or column not in BOARD_COLUMN_ORDER:
        return None
    return BOARD_COLUMN_ORDER.index(column)


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value is not None else None


#: Kolumna blokady → klucz etapu (napis „przed …”).
_NEEDED_OF_COLUMN = {
    "cv_sent": "cv_sent",
    "client_interview": "client_interview",
    "hired": "b2b_contract",
}


def _earlier(*columns: Optional[str]) -> Optional[str]:
    known = [c for c in columns if _index(c) is not None]
    return min(known, key=lambda c: _index(c) or 0) if known else None


def stage_is_later(new: str, old: str) -> bool:
    """Etap ``new`` stawia blokadę dalej niż ``old`` („do daty” = bez kolumny = dalej)."""
    new_at, old_at = _index(NEEDED_COLUMN.get(new)), _index(NEEDED_COLUMN.get(old))
    if old_at is None:
        return False
    return new_at is None or new_at > old_at


def stop_from(
    *,
    rule: Optional[Mapping[str, Any]],
    requests: list[PreContractRequest],
    target_column: Optional[str],
    current_column: Optional[str] = None,
) -> Optional[Stop]:
    """Czysta reguła: blokada ruchu z ``current_column`` na ``target_column``
    (``None`` = „czy osoba w ogóle stoi do podpisu”). ``requests`` — prośby
    pary, najnowsza pierwsza.

    - podpisana umowa (którakolwiek) zwalnia kartę;
    - ruch w lewo albo w obrębie kolumny nigdy nie stoi;
    - wybór przy ostatniej prośbie wygrywa (``False`` = wyjątek), także po jej
      zamknięciu — anulowanie prośby nie jest furtką;
    - przy ustawieniu rekrutacji obowiązuje WCZEŚNIEJSZY z etapów: rekrutacji
      i prośby (zmiana etapu prośby nie przesuwa blokady w prawo)."""
    if any(is_signed(r) for r in requests):
        return None
    target_at = _index(target_column) if target_column is not None else None
    if target_column is not None:
        now_at = _index(current_column)
        if target_at is None or (now_at is not None and target_at <= now_at):
            return None
    current = next((r for r in requests if r.closed_at is None), None)
    latest = current or (requests[0] if requests else None)
    rule_stop = bool(rule and rule.get("stop"))
    rule_column = NEEDED_COLUMN.get(rule["needed_before"]) if rule_stop else None
    if latest is not None and latest.blocks_move is False:
        return None
    if latest is not None and latest.blocks_move is True:
        origin = "person"
        column = _earlier(NEEDED_COLUMN.get(latest.needed_before), rule_column)
    elif rule_stop:
        origin = "job"
        column = _earlier(
            rule_column, NEEDED_COLUMN.get(latest.needed_before) if latest else None
        )
        # Osoba bez żadnej prośby, która minęła etap jeszcze przed ustawieniem
        # rekrutacji, nie staje w połowie procesu.
        now_at, column_at = _index(current_column), _index(column)
        if (
            latest is None
            and now_at is not None
            and column_at is not None
            and now_at >= column_at
        ):
            return None
    else:
        return None
    if column is None:
        return None
    if target_at is not None and target_at < (_index(column) or 0):
        return None
    if origin == "person" and latest is not None:
        set_by, set_at = latest.blocks_set_by, _iso(latest.blocks_set_at)
    else:
        set_by, set_at = (rule or {}).get("set_by"), (rule or {}).get("set_at")
    return Stop(
        column=column,
        needed_before=_NEEDED_OF_COLUMN.get(column, ""),
        origin=origin,
        set_by=set_by,
        set_at=set_at,
        request_id=latest.id if latest is not None else None,
    )


async def pair_requests(
    db: AsyncSession, *, candidate_id: int, job_id: int
) -> list[PreContractRequest]:
    return list(
        (
            await db.execute(
                select(PreContractRequest)
                .where(
                    PreContractRequest.candidate_id == candidate_id,
                    PreContractRequest.job_id == job_id,
                )
                .order_by(PreContractRequest.id.desc())
            )
        )
        .scalars()
        .all()
    )


async def stop_for_pair(
    db: AsyncSession, *, job: Any, candidate_id: int, target_column: Optional[str]
) -> Optional[Stop]:
    rule = rule_of(job)
    requests = await pair_requests(db, candidate_id=candidate_id, job_id=job.id)
    if rule is None and not requests:
        return None
    columns = await pair_columns(db, [(candidate_id, job.id)])
    current_column = (columns.get((candidate_id, job.id)) or (None, None))[0]
    return stop_from(
        rule=rule,
        requests=requests,
        target_column=target_column,
        current_column=current_column,
    )


def stop_message(stop: Stop) -> str:
    source = "ustawienie rekrutacji" if stop.origin == "job" else "przy tej osobie"
    return (
        f"Osoba czeka na podpis umowy przedwstępnej ({stop.stage_label}; {source}). "
        "Blokadę zdejmuje Delivery Lead albo Head of Recruitment w panelu osoby › Umowa."
    )


async def assert_pre_contract_signed(
    db: AsyncSession, *, job: Any, candidate_id: int, target_column: Optional[str]
) -> None:
    """409 ``PRE_CONTRACT_NOT_SIGNED``, gdy ruch wchodzi na etap blokady."""
    if target_column is None:
        return
    stop = await stop_for_pair(
        db, job=job, candidate_id=candidate_id, target_column=target_column
    )
    if stop is None:
        return
    raise HTTPException(
        status_code=409,
        detail={
            "code": STOP_CODE,
            "message": stop_message(stop),
            "origin": stop.origin,
            "needed_before": stop.needed_before,
            "request_id": stop.request_id,
        },
    )


def stop_payload(
    stop: Optional[Stop], names: Mapping[int, str]
) -> Optional[dict[str, Any]]:
    """Kształt dla frontu (karta, prośba, okno ruchu)."""
    if stop is None:
        return None
    return {
        "column": stop.column,
        "needed_before": stop.needed_before,
        "origin": stop.origin,
        "set_by_name": names.get(stop.set_by) if stop.set_by else None,
        "set_at": stop.set_at,
    }


# ── Prośby z ustawienia rekrutacji ───────────────────────────────────────────

#: Od tej kolumny osoba w rekrutacji z ustawieniem dostaje prośbę (decyzja 23.11).
RULE_FROM_COLUMN = "verified"


def _rule_applies_at(rule: Mapping[str, Any], column: Optional[str]) -> bool:
    """Osoba na ``column`` stoi między „Zweryfikowanym” a etapem ustawienia."""
    at = _index(column)
    start = _index(RULE_FROM_COLUMN)
    end = _index(NEEDED_COLUMN.get(rule["needed_before"]))
    return (
        at is not None and start is not None and end is not None and start <= at < end
    )


async def ensure_rule_request(
    db: AsyncSession,
    *,
    job: Any,
    candidate_id: int,
    column: Optional[str],
    actor_id: Optional[int],
) -> Optional[PreContractRequest]:
    """Załóż prośbę z ustawienia rekrutacji, gdy osoba weszła na „Zweryfikowany”
    (albo dalej, ale przed etapem) i nie ma prośby w toku ani podpisanej umowy.
    Bez commita; wyścig z drugą prośbą kończy się bez błędu."""
    rule = rule_of(job)
    if rule is None or not _rule_applies_at(rule, column):
        return None
    requests = await pair_requests(db, candidate_id=candidate_id, job_id=job.id)
    if any(is_signed(r) or r.closed_at is None for r in requests):
        return None
    if requests and requests[0].blocks_move is False:
        return None  # wyjątek DL-a / HoR na ostatniej prośbie
    from app.services.stage_handoff_recipients import (  # noqa: PLC0415
        pair_recruiter_id,
    )

    assignee = await pair_recruiter_id(db, candidate_id=candidate_id, job_id=job.id)
    requester = rule.get("set_by") or actor_id or assignee or job.recruiter_id
    assignee = assignee or job.recruiter_id or requester
    if requester is None or assignee is None:
        return None
    req = PreContractRequest(
        candidate_id=candidate_id,
        job_id=job.id,
        client_id=job.client_id,
        needed_before=rule["needed_before"],
        reason="Ustawienie rekrutacji: każda osoba podpisuje umowę przedwstępną.",
        requested_by=requester,
        assignee_id=assignee,
    )
    try:
        async with db.begin_nested():
            db.add(req)
            await db.flush()
    except IntegrityError:
        return None
    await svc.add_watchers(db, req.id, [requester, assignee])
    event = await svc.add_event(
        db,
        req,
        "requested",
        actor_id=actor_id,
        payload={
            "needed_before": req.needed_before,
            "assignee_id": assignee,
            "from_rule": True,
        },
    )
    await svc.notify(
        db,
        req,
        event,
        message=(
            "rekrutacja wymaga umowy przedwstępnej "
            f"{NEEDED_BEFORE_LABEL.get(req.needed_before, '')} — wystaw ją."
        ),
        actor_id=actor_id,
        only_user_ids=[assignee],
    )
    return req


async def backfill_rule_requests(
    db: AsyncSession, *, job: Any, actor_id: Optional[int]
) -> int:
    """Po ustawieniu rekrutacji: prośby dla osób, które już stoją między
    „Zweryfikowanym” a etapem. Zwraca liczbę nowych próśb."""
    rule = rule_of(job)
    if rule is None:
        return 0
    from app.models.recruitment_pipeline import CandidateStage  # noqa: PLC0415

    candidate_ids = (
        await db.scalars(
            select(CandidateStage.candidate_id)
            .where(CandidateStage.job_id == job.id)
            .distinct()
        )
    ).all()
    columns = await pair_columns(db, [(cid, job.id) for cid in candidate_ids])
    made = 0
    for (cid, _jid), (column, _name) in sorted(columns.items()):
        if await ensure_rule_request(
            db, job=job, candidate_id=cid, column=column, actor_id=actor_id
        ):
            made += 1
    return made


# ── Kto zatrzymuje ───────────────────────────────────────────────────────────


async def can_set_stop(db: AsyncSession, user: Any, job: Any) -> bool:
    """Ustawienie rekrutacji, stop przy osobie, wyjątek i zdjęcie blokady:
    admin, Head of Recruitment i Delivery Lead tej rekrutacji albo jej klienta
    (decyzja Artura 23.11.2026). Rekruter widzi stan, nie zmienia go."""
    from app.models.user import UserRole  # noqa: PLC0415
    from app.services.board_tasks import dl_portfolio_client_ids  # noqa: PLC0415

    if user.has_any_role(UserRole.admin, UserRole.head_of_recruitment):
        return True
    if not user.has_role(UserRole.delivery_lead):
        return False
    if job.delivery_lead_id == user.id:
        return True
    return job.client_id is not None and job.client_id in await dl_portfolio_client_ids(
        db, user.id
    )


def rule_record(needed_before: str, stop: bool, user: Any) -> dict[str, Any]:
    """Wartość ``jobs.pre_contract_rule`` z autorem i chwilą (kalendarz firmy)."""
    from app.core.scheduling import local_now  # noqa: PLC0415

    return {
        "needed_before": needed_before,
        "stop": bool(stop),
        "set_by": user.id,
        "set_by_name": user.name,
        "set_at": local_now().isoformat(timespec="minutes"),
    }


def rule_payload(rule: Optional[Mapping[str, Any]]) -> Optional[dict[str, Any]]:
    """Ustawienie rekrutacji dla frontu (z nazwiskiem ustawiającego)."""
    if rule is None:
        return None
    return {
        "needed_before": rule["needed_before"],
        "needed_before_label": NEEDED_BEFORE_LABEL.get(rule["needed_before"], ""),
        "stop": bool(rule.get("stop")),
        "set_by_name": rule.get("set_by_name"),
        "set_at": rule.get("set_at"),
    }


async def retarget_rule_requests(
    db: AsyncSession,
    *,
    job: Any,
    previous: Optional[Mapping[str, Any]],
    actor_id: Optional[int],
) -> int:
    """Zmiana etapu w ustawieniu rekrutacji przenosi otwarte prośby, które
    dziedziczą ustawienie (``blocks_move IS NULL``) i stały na starym etapie.
    Bez tego nagłówek mówiłby „przed B2B”, a karty stałyby przed CV."""
    rule = rule_of(job)
    if (
        previous is None
        or rule is None
        or previous["needed_before"] == rule["needed_before"]
    ):
        return 0
    rows = (
        await db.scalars(
            select(PreContractRequest).where(
                PreContractRequest.job_id == job.id,
                PreContractRequest.closed_at.is_(None),
                PreContractRequest.blocks_move.is_(None),
                PreContractRequest.needed_before == previous["needed_before"],
            )
        )
    ).all()
    for req in rows:
        if is_signed(req):
            continue
        old = req.needed_before
        req.needed_before = rule["needed_before"]
        await svc.add_event(
            db,
            req,
            "updated",
            actor_id=actor_id,
            payload={"needed_before": [old, req.needed_before], "from_rule": True},
        )
    return len(rows)
