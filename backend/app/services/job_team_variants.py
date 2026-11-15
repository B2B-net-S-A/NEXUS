"""Gotowe składy zespołu (Z3, 0712): automat proponuje, DL zatwierdza, klient widzi.

Reguły: ``docs/claude/klienci/zespol-dla-klienta.md``. Propozycje liczy się na
żądanie i nie zapisuje; w ``job_teams.variants`` są tylko składy zatwierdzone
przez DL-a. Nazwę i uzasadnienie pisze DL, a czyta je klient: zwykły tekst,
z limitem długości. Ten moduł nie ma nic wspólnego z ``services/job_team.py``
(reguła „Rekruter rekrutacji”).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Callable, Iterable, Mapping, Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today
from app.models.client_interview_slot_request import (
    OPEN_SLOT_STATUSES,
    ClientInterviewSlotRequest,
    all_slots_past,
)
from app.models.client_panel import ClientPanelRequest
from app.models.job import Job
from app.services import client_panel as panel_service
from app.services import client_panel_evidence as evidence_service
from app.services import job_team_panel as team_service
from app.services.stage_client_rate import latest_client_rates

MAX_VARIANTS = 3
NAME_MAX = 60
WHY_MAX = 240
KEY_MAX = 40

_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


# ── Reguły propozycji (bez bazy) ─────────────────────────────────────────────


@dataclass(frozen=True)
class Option:
    """Osoba wysłana na stanowisko, tak jak widzi ją automat."""

    candidate_id: int
    available_from: Optional[date] = None
    # Tylko stawka godzinowa do klienta; inna jednostka = brak stawki (jak ekran).
    hourly: Optional[float] = None
    in_projects: int = 0
    # Kolejność wysyłki CV: ostatni, stały remis.
    order: int = 0
    hidden: bool = False
    not_fit: bool = False


@dataclass(frozen=True)
class SeatGroup:
    job_id: int
    seats: int
    options: tuple[Option, ...]


def _start(option: Option, today: date) -> date:
    """Dzień startu do porównań: data z przeszłości = dziś, brak daty = na końcu."""
    if option.available_from is None:
        return date.max
    return max(option.available_from, today)


def _rate(option: Option) -> float:
    return option.hourly if option.hourly is not None else float("inf")


def _fast(option: Option, today: date) -> tuple:
    return (_start(option, today), _rate(option))


def _cheap(option: Option, today: date) -> tuple:
    return (_rate(option), _start(option, today))


def _evidence(option: Option, today: date) -> tuple:
    return (-option.in_projects, _rate(option))


@dataclass(frozen=True)
class Rule:
    key: str
    name: str
    why: str
    sort_key: Callable[[Option, date], tuple]


RULES: tuple[Rule, ...] = (
    Rule(
        "fast",
        "Najszybszy start",
        "Na każde miejsce osoba dostępna najwcześniej; przy remisie tańsza.",
        _fast,
    ),
    Rule(
        "cheap",
        "Najniższa cena",
        "Na każde miejsce najniższa stawka; przy remisie wcześniejszy start.",
        _cheap,
    ),
    Rule(
        "evidence",
        "Najwięcej w CV",
        "Na każde miejsce osoba z największą liczbą wymagań w opisach projektów; "
        "przy remisie tańsza.",
        _evidence,
    ),
)


def ranked(options: Iterable[Option], rule: Rule, today: date) -> list[Option]:
    """Kolejność osób stanowiska według reguły, bez ukrytych i „nie pasuje”."""
    eligible = [o for o in options if not o.hidden and not o.not_fit]
    return sorted(
        eligible,
        key=lambda o: (*rule.sort_key(o, today), o.order, o.candidate_id),
    )


def summary(chosen: Iterable[Option], today: date) -> dict[str, Any]:
    """Cena za godzinę (suma znanych stawek), start (najpóźniejszy), osoby bez daty."""
    people = list(chosen)
    rates = [o.hourly for o in people if o.hourly is not None]
    dated = [max(o.available_from, today) for o in people if o.available_from]
    return {
        "hourly_total": round(sum(rates), 2) if rates else None,
        "start": max(dated).isoformat() if dated else None,
        "unknown_start": sum(1 for o in people if o.available_from is None),
    }


def propose(groups: Iterable[SeatGroup], today: date) -> list[dict[str, Any]]:
    """Trzy składy automatu; na każde miejsce jedna osoba. Duplikaty zostają."""
    groups = list(groups)
    out: list[dict[str, Any]] = []
    for rule in RULES:
        picks: list[dict[str, Any]] = []
        chosen: list[Option] = []
        for group in groups:
            top = ranked(group.options, rule, today)[: max(group.seats, 1)]
            if not top:
                continue
            picks.append(
                {"job_id": group.job_id, "candidate_ids": [o.candidate_id for o in top]}
            )
            chosen.extend(top)
        out.append(
            {
                "key": rule.key,
                "name": rule.name,
                "why": rule.why,
                "picks": picks,
                **summary(chosen, today),
            }
        )
    return out


# ── Dane do propozycji ───────────────────────────────────────────────────────


async def _not_fit_ids(db: AsyncSession, panel_id: int) -> set[int]:
    rows = await db.scalars(
        select(ClientPanelRequest.candidate_id).where(
            ClientPanelRequest.panel_id == panel_id,
            ClientPanelRequest.kind == "not_fit",
            ClientPanelRequest.candidate_id.is_not(None),
        )
    )
    return set(rows.all())


async def seat_group(db: AsyncSession, job: Job) -> SeatGroup:
    """Osoby stanowiska: te same pary co w widoku DL-a (wysłane, proces otwarty)."""
    sent = await panel_service.sent_pairs(db, job.id)
    order = {
        cid: index for index, cid in enumerate(sorted(sent, key=lambda c: sent[c]))
    }
    people = await panel_service._load_people(db, sent)
    panel = await panel_service.panel_for_job(db, job.id)
    rows = await panel_service.candidate_rows(db, panel.id) if panel else {}
    not_fit = await _not_fit_ids(db, panel.id) if panel else set()
    cvs = await panel_service.pair_cvs(db, job.id, sent)
    rates = await latest_client_rates(db, [(cid, job.id) for cid in sent])
    requirements = evidence_service.requirements_from_job(
        job.must_skills, job.nice_skills
    )
    options: list[Option] = []
    for cid in order:
        person = people.get(cid)
        if person is None:
            continue
        cv = cvs.get(cid)
        row = rows.get(cid)
        found = evidence_service.evidence_map(
            cv.html if cv else None,
            requirements,
            (row.rejected_evidence if row is not None else None) or (),
        )
        rate = rates.get((cid, job.id))
        options.append(
            Option(
                candidate_id=cid,
                available_from=person.availability_date,
                hourly=rate[0] if rate is not None and rate[1] == "hourly" else None,
                in_projects=evidence_service.counts(found)[0],
                order=order[cid],
                hidden=bool(row is not None and row.hidden),
                not_fit=cid in not_fit,
            )
        )
    return SeatGroup(job.id, team_service.headcount(job), tuple(options))


async def proposal(db: AsyncSession, jobs: Iterable[Job]) -> list[dict[str, Any]]:
    groups = [
        await seat_group(db, job) for job in jobs if not team_service.is_closed(job)
    ]
    return propose(groups, business_today())


# ── Zatwierdzenie przez DL-a ─────────────────────────────────────────────────


def clean_text(value: str, *, limit: int, required: bool) -> str:
    """Tekst od DL-a dla klienta: bez znaków sterujących, jedna spacja, limit."""
    cleaned = " ".join(_CONTROL_RE.sub(" ", value).split())
    if required and not cleaned:
        raise ValueError("Podaj nazwę składu.")
    if len(cleaned) > limit:
        raise ValueError(f"Najwyżej {limit} znaków.")
    return cleaned


def clean_key(value: str) -> str:
    cleaned = value.strip().lower()
    if not cleaned or len(cleaned) > KEY_MAX or not _KEY_RE.match(cleaned):
        raise ValueError("Nieprawidłowy klucz składu.")
    return cleaned


def validate_variants(
    variants: Iterable[Mapping[str, Any]],
    *,
    seats: Mapping[int, int],
    sent: Mapping[int, Iterable[int]],
) -> list[dict[str, Any]]:
    """Składy do zapisu albo 422.

    ``seats``: rekrutacja zespołu → liczba miejsc; ``sent``: rekrutacja → osoby
    z listy wysłanych. Pusta lista osób na stanowisku znika z zapisu.
    """
    out: list[dict[str, Any]] = []
    keys: set[str] = set()
    for variant in variants:
        if variant["key"] in keys:
            raise HTTPException(
                status_code=422, detail="Dwa składy mają ten sam klucz."
            )
        keys.add(variant["key"])
        picks: list[dict[str, Any]] = []
        jobs: set[int] = set()
        for pick in variant["picks"]:
            job_id = pick["job_id"]
            if job_id not in seats:
                raise HTTPException(
                    status_code=422, detail="Tej rekrutacji nie ma w zespole."
                )
            if job_id in jobs:
                raise HTTPException(
                    status_code=422,
                    detail="Stanowisko powtarza się w jednym składzie.",
                )
            jobs.add(job_id)
            chosen = list(dict.fromkeys(pick["candidate_ids"]))
            allowed = set(sent.get(job_id, ()))
            if any(cid not in allowed for cid in chosen):
                raise HTTPException(
                    status_code=422,
                    detail="Ta osoba nie jest na liście wysłanych CV tego stanowiska.",
                )
            if len(chosen) > seats[job_id]:
                raise HTTPException(
                    status_code=422,
                    detail="W składzie jest więcej osób niż miejsc na stanowisku.",
                )
            if chosen:
                picks.append({"job_id": job_id, "candidate_ids": chosen})
        if not picks:
            raise HTTPException(
                status_code=422, detail="Skład musi mieć co najmniej jedną osobę."
            )
        out.append(
            {
                "key": variant["key"],
                "name": variant["name"],
                "why": variant["why"],
                "picks": picks,
            }
        )
    return out


async def sent_by_job(db: AsyncSession, jobs: Iterable[Job]) -> dict[int, set[int]]:
    return {job.id: set(await panel_service.sent_pairs(db, job.id)) for job in jobs}


# ── Rozmowy z całym składem ──────────────────────────────────────────────────


async def has_open_request(db: AsyncSession, *, job_id: int, candidate_id: int) -> bool:
    """Czekający wniosek o terminy; ten ze wszystkimi minionymi terminami nie blokuje."""
    open_request = await db.scalar(
        select(ClientInterviewSlotRequest).where(
            ClientInterviewSlotRequest.job_id == job_id,
            ClientInterviewSlotRequest.candidate_id == candidate_id,
            ClientInterviewSlotRequest.status.in_(OPEN_SLOT_STATUSES),
        )
    )
    return open_request is not None and not all_slots_past(
        open_request.slots or (), datetime.now(timezone.utc)
    )
