"""Zespół dla klienta: token zespołu, widok dla DL-a, widok publiczny, wybór składu.

Reguły: ``docs/claude/klienci/zespol-dla-klienta.md``. Zespół to pojemnik na
zwykłe rekrutacje jednego klienta. Szczegóły osób po stronie klienta idą dalej
przez panel stanowiska (``services/client_panel.py``) i jego trasy publiczne,
więc blind CV, zgoda RODO i limity działają bez zmian. Odpowiedzi publiczne
powstają z jawnych list pól, nigdy ze zrzutu modelu.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, time, timezone
from decimal import Decimal
from typing import Any, Iterable, Mapping, Optional
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.scheduling import business_date, business_today
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_panel import ClientPanel, ClientPanelCandidate
from app.models.job import Job, JobStatus
from app.models.job_team_panel import JobTeam, JobTeamSelection
from app.models.notification import NotificationType
from app.models.pipeline_template import PipelineStageDef
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import User
from app.services import client_panel as panel_service
from app.services import job_team_rates as rates_service
from app.services.stage_client_rate import latest_client_rates

logger = logging.getLogger(__name__)

HOURS_PER_MONTH = 168
MAX_JOBS = 30
SELECTIONS_SHOWN = 5
DAILY_SELECTION_LIMIT = 30

MSG_NOT_FOUND = panel_service.MSG_NOT_FOUND
MSG_EXPIRED = panel_service.MSG_EXPIRED
MSG_NO_OPEN_POSITIONS = (
    "W tym zespole nie ma otwartej rekrutacji, więc link nie miałby czego pokazać."
)


# ── Token ────────────────────────────────────────────────────────────────────


def compute_token(team_id: int, nonce: str) -> str:
    """Ten sam schemat co panel rekrutacji, inna wiadomość HMAC."""
    digest = hmac.new(
        settings.SECRET_KEY.encode(),
        f"job-team-panel:{team_id}:{nonce}".encode(),
        hashlib.sha256,
    ).digest()
    return base64.b32encode(digest).decode().lower()[: panel_service.TOKEN_LENGTH]


def issue_token(team: JobTeam) -> str:
    """Nowy sekret linku zespołu; poprzedni przestaje działać."""
    team.panel_token_nonce = secrets.token_hex(16)
    token = compute_token(team.id, team.panel_token_nonce)
    team.panel_token_sha256 = panel_service.token_digest(token)
    return token


def current_token(team: JobTeam) -> Optional[str]:
    """Jak ``client_panel.current_token``: po zmianie sekretu bez martwego linku."""
    if not team.panel_token_nonce or not team.panel_token_sha256:
        return None
    token = compute_token(team.id, team.panel_token_nonce)
    if not hmac.compare_digest(
        panel_service.token_digest(token), team.panel_token_sha256
    ):
        return None
    return token


def team_urls(token: str) -> tuple[str, str]:
    """(pełny adres, krótki adres do przepisania, bez schematu)."""
    full = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/k/z/{token}"
    parts = urlsplit(full)
    return full, f"{parts.netloc}{parts.path}"


def is_expired(team: JobTeam, now: Optional[datetime] = None) -> bool:
    if team.panel_expires_at is None:
        return False
    return team.panel_expires_at <= (now or datetime.now(timezone.utc))


def _iso(value: Any) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _day(moment: Optional[datetime]) -> Optional[str]:
    return business_date(moment).isoformat() if moment is not None else None


def _number(value: Optional[Decimal]) -> Optional[float]:
    return float(value) if value is not None else None


def headcount(job: Job) -> int:
    return max(job.headcount or 1, 1)


def is_closed(job: Job) -> bool:
    return job.status == JobStatus.closed


# ── Zespół i jego rekrutacje ─────────────────────────────────────────────────


async def team_jobs(db: AsyncSession, team_id: int) -> list[Job]:
    rows = await db.scalars(select(Job).where(Job.team_id == team_id).order_by(Job.id))
    return list(rows.all())


def check_jobs_joinable(
    jobs: Iterable[Job], *, client_id: int, team_id: Optional[int]
) -> None:
    """Ten sam klient, otwarte, bez innego zespołu; inaczej 409."""
    for job in jobs:
        if job.client_id != client_id:
            raise HTTPException(
                status_code=409,
                detail="Zespół łączy rekrutacje jednego klienta.",
            )
        if is_closed(job):
            raise HTTPException(
                status_code=409,
                detail=f"Rekrutacja „{job.title}” jest zamknięta.",
            )
        if job.team_id is not None and job.team_id != team_id:
            raise HTTPException(
                status_code=409,
                detail=f"Rekrutacja „{job.title}” jest już w innym zespole.",
            )


async def _client_name(db: AsyncSession, client_id: int) -> Optional[str]:
    client = await db.get(Client, client_id)
    return (client.name or client.display_name) if client else None


async def summaries(db: AsyncSession, teams: list[JobTeam]) -> list[dict[str, Any]]:
    """Wiersze listy: liczba stanowisk i miejsc (osób do obsadzenia) w otwartych."""
    if not teams:
        return []
    ids = [team.id for team in teams]
    counts: dict[int, tuple[int, int]] = {}
    rows = await db.execute(
        select(Job.team_id, Job.headcount, Job.status).where(Job.team_id.in_(ids))
    )
    for team_id, count, status in rows.all():
        if status == JobStatus.closed:
            continue
        positions, seats = counts.get(team_id, (0, 0))
        counts[team_id] = (positions + 1, seats + max(count or 1, 1))
    client_ids = {team.client_id for team in teams}
    names = {
        row.id: row.name or row.display_name
        for row in (
            await db.execute(
                select(Client.id, Client.name, Client.display_name).where(
                    Client.id.in_(client_ids)
                )
            )
        ).all()
    }
    return [
        {
            "id": team.id,
            "name": team.name,
            "client_id": team.client_id,
            "client_name": names.get(team.client_id),
            "positions": counts.get(team.id, (0, 0))[0],
            "seats": counts.get(team.id, (0, 0))[1],
        }
        for team in teams
    ]


# ── Stan panelu zespołu i paneli stanowisk ───────────────────────────────────


async def sync_position_panels(
    db: AsyncSession,
    team: JobTeam,
    jobs: Iterable[Job],
    user_id: Optional[int],
    *,
    enable_positions: bool = False,
    rate_from_team: bool = False,
) -> list[int]:
    """Panele stanowisk idą za linkiem zespołu. Zwraca rekrutacje ze zmianą stanu.

    Włączenie linku albo dodanie stanowiska do włączonego zespołu
    (``enable_positions``): każde otwarte stanowisko ma włączony panel
    z ważnością zespołu. Stawka: nowy panel dostaje ustawienie zespołu;
    istniejący panel z ukrytą stawką zostaje z ukrytą (DL ukrył ją świadomie),
    chyba że zmiana przyszła z „Pokazuj stawki” na zespole (``rate_from_team``).
    Sama zmiana stawki na włączonym zespole nie rusza włączenia ani ważności
    paneli: stanowisko wyłączone przez DL-a zostaje wyłączone (audyt 24.11.2026).
    Wyłączony link: panele wszystkich stanowisk zespołu wyłączone.
    """
    changed: list[int] = []
    for job in jobs:
        if team.panel_enabled:
            if is_closed(job):
                continue
            existing = await panel_service.panel_for_job(db, job.id)
            if not enable_positions:
                if existing is not None and rate_from_team:
                    existing.show_rate = team.panel_show_rate
                continue
            panel = existing or await panel_service.get_or_create_panel(
                db, job.id, user_id
            )
            if panel.token_nonce is None:
                panel_service.issue_token(panel)
            if not panel.enabled:
                panel.enabled = True
                changed.append(job.id)
            panel.expires_at = team.panel_expires_at
            if existing is None or rate_from_team or panel.show_rate:
                panel.show_rate = team.panel_show_rate
        else:
            panel = await panel_service.panel_for_job(db, job.id)
            if panel is not None and panel.enabled:
                panel.enabled = False
                changed.append(job.id)
    return changed


# ── Widok dla Delivery Leada ─────────────────────────────────────────────────


async def _current_stages(
    db: AsyncSession, job_id: int, candidate_ids: Iterable[int]
) -> dict[int, str]:
    """Nazwa bieżącego etapu pary, jak na Tablicy (nazwa z szablonu albo kod)."""
    wanted = sorted(set(candidate_ids))
    if not wanted:
        return {}
    rows = await db.execute(
        select(CandidateStage.candidate_id, CandidateStage.stage, PipelineStageDef.name)
        .outerjoin(PipelineStageDef, PipelineStageDef.id == CandidateStage.stage_def_id)
        .where(
            CandidateStage.job_id == job_id,
            CandidateStage.candidate_id.in_(wanted),
        )
        .order_by(
            CandidateStage.candidate_id,
            CandidateStage.moved_at.desc(),
            CandidateStage.id.desc(),
        )
        .distinct(CandidateStage.candidate_id)
    )
    return {
        cid: (name or getattr(stage, "value", stage)) for cid, stage, name in rows.all()
    }


async def latest_expected_rates(
    db: AsyncSession, pairs: Iterable[tuple[int, int]]
) -> dict[tuple[int, int], tuple[float, Optional[str], Optional[str]]]:
    """Najnowsze oczekiwanie kandydata z wiersza etapu pary. Tylko dla DL-a."""
    wanted = sorted(set(pairs))
    if not wanted:
        return {}
    rows = await db.execute(
        select(
            CandidateStage.candidate_id,
            CandidateStage.job_id,
            CandidateStage.expected_rate_value,
            CandidateStage.expected_rate_unit,
            CandidateStage.expected_rate_currency,
        )
        .where(
            tuple_(CandidateStage.candidate_id, CandidateStage.job_id).in_(wanted),
            CandidateStage.expected_rate_value.is_not(None),
        )
        .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
    )
    out: dict[tuple[int, int], tuple[float, Optional[str], Optional[str]]] = {}
    for cand, job, value, unit, currency in rows.all():
        out.setdefault(
            (cand, job), (float(value), getattr(unit, "value", unit), currency)
        )
    return out


def _rate(raw: Optional[tuple]) -> Optional[dict[str, Any]]:
    if raw is None:
        return None
    value, unit, currency = raw
    return {"value": value, "unit": unit, "currency": currency}


def _full_name(name: Optional[str], lastname: Optional[str]) -> str:
    return " ".join(p for p in (name, lastname) if p).strip()


async def _people(db: AsyncSession, candidate_ids: Iterable[int]) -> dict[int, Any]:
    wanted = sorted(set(candidate_ids))
    if not wanted:
        return {}
    rows = await db.execute(
        select(
            Candidate.id,
            Candidate.name,
            Candidate.lastname,
            Candidate.availability_date,
        ).where(Candidate.id.in_(wanted))
    )
    return {row.id: row for row in rows.all()}


async def _position(
    db: AsyncSession, job: Job, rate_hint: Optional[dict[str, float]]
) -> dict[str, Any]:
    sent = await panel_service.sent_pairs(db, job.id)
    people = await _people(db, sent)
    stages = await _current_stages(db, job.id, sent)
    pairs = [(cid, job.id) for cid in sent]
    client_rates = await latest_client_rates(db, pairs)
    expected = await latest_expected_rates(db, pairs)
    lead = await db.get(User, job.delivery_lead_id) if job.delivery_lead_id else None
    candidates = []
    for cid in sorted(sent, key=lambda c: sent[c]):
        person = people.get(cid)
        if person is None:
            continue
        candidates.append(
            {
                "candidate_id": cid,
                "name": _full_name(person.name, person.lastname),
                "stage": stages.get(cid),
                "sent_at": _day(sent[cid]),
                "available_from": _iso(person.availability_date),
                "client_rate": _rate(client_rates.get((cid, job.id))),
                "expected_rate": _rate(expected.get((cid, job.id))),
            }
        )
    return {
        "job_id": job.id,
        # Ekran wewnętrzny: tytuł dla zespołu (`trzy-nazwy-rekrutacji.md`).
        "title": job.working_title or job.title,
        "headcount": headcount(job),
        "closed": is_closed(job),
        "budget_min": _number(job.rate_budget_hourly_min),
        "budget_max": _number(job.rate_budget_hourly),
        "delivery_lead": {"id": lead.id, "name": lead.name} if lead else None,
        "candidates": candidates,
        # Z4: stawki do klienta z jego historii w tej kategorii (tylko dla DL-a).
        "rate_hint": rate_hint,
    }


async def _selections(db: AsyncSession, team_id: int) -> list[dict[str, Any]]:
    rows = list(
        (
            await db.scalars(
                select(JobTeamSelection)
                .where(JobTeamSelection.team_id == team_id)
                .order_by(
                    JobTeamSelection.created_at.desc(), JobTeamSelection.id.desc()
                )
                .limit(SELECTIONS_SHOWN)
            )
        ).all()
    )
    ids = {
        int(cid)
        for row in rows
        for pick in row.picks or []
        for cid in pick.get("candidate_ids") or []
    }
    names = {
        cid: _full_name(person.name, person.lastname)
        for cid, person in (await _people(db, ids)).items()
    }
    return [
        {
            "id": row.id,
            "created_at": _iso(row.created_at),
            "author_name": row.author_name,
            "author_email": row.author_email,
            "note": row.note,
            "picks": [
                {
                    "job_id": pick.get("job_id"),
                    "candidates": [
                        {"candidate_id": int(cid), "name": names.get(int(cid))}
                        for cid in pick.get("candidate_ids") or []
                    ],
                }
                for pick in row.picks or []
            ],
        }
        for row in rows
    ]


async def _detail_variants(db: AsyncSession, team: JobTeam) -> list[dict[str, Any]]:
    """Zatwierdzone gotowe składy z imionami, jak w ``selections``."""
    stored = list(team.variants or [])
    ids = {
        int(cid)
        for variant in stored
        for pick in variant.get("picks") or []
        for cid in pick.get("candidate_ids") or []
    }
    names = {
        cid: _full_name(person.name, person.lastname)
        for cid, person in (await _people(db, ids)).items()
    }
    return [
        {
            "key": variant.get("key"),
            "name": variant.get("name"),
            "why": variant.get("why"),
            "picks": [
                {
                    "job_id": pick.get("job_id"),
                    "candidates": [
                        {"candidate_id": int(cid), "name": names.get(int(cid))}
                        for cid in pick.get("candidate_ids") or []
                    ],
                }
                for pick in variant.get("picks") or []
            ],
        }
        for variant in stored
    ]


async def team_detail(
    db: AsyncSession, team: JobTeam, jobs: Optional[list[Job]] = None
) -> dict[str, Any]:
    jobs = jobs if jobs is not None else await team_jobs(db, team.id)
    token = current_token(team) if team.panel_enabled else None
    url, short_url = team_urls(token) if token else (None, None)
    hints = await rates_service.rate_hints(db, jobs)
    return {
        "id": team.id,
        "name": team.name,
        "client_id": team.client_id,
        "client_name": await _client_name(db, team.client_id),
        "hours_per_month": HOURS_PER_MONTH,
        "positions": [await _position(db, job, hints.get(job.id)) for job in jobs],
        "panel": {
            "enabled": team.panel_enabled,
            "show_rate": team.panel_show_rate,
            "expires_at": _iso(team.panel_expires_at),
            "url": url,
            "short_url": short_url,
        },
        "selections": await _selections(db, team.id),
        "variants": await _detail_variants(db, team),
        "variants_approved_at": _iso(team.variants_approved_at),
    }


# ── Widok publiczny ──────────────────────────────────────────────────────────


async def load_public_team(db: AsyncSession, token: str) -> JobTeam:
    """Zespół z linku: nieznany albo wyłączony = 404, wygasły = 410."""
    if not panel_service._TOKEN_RE.match(token or ""):
        raise HTTPException(status_code=404, detail=MSG_NOT_FOUND)
    team = await db.scalar(
        select(JobTeam).where(
            JobTeam.panel_token_sha256 == panel_service.token_digest(token)
        )
    )
    if team is None or not team.panel_enabled:
        raise HTTPException(status_code=404, detail=MSG_NOT_FOUND)
    if is_expired(team):
        raise HTTPException(status_code=410, detail=MSG_EXPIRED)
    return team


@dataclass(frozen=True)
class PublicPosition:
    key: str
    job: Job
    panel: ClientPanel


async def public_positions(db: AsyncSession, team: JobTeam) -> list[PublicPosition]:
    """Otwarte stanowiska z działającym panelem; kluczem jest token panelu stanowiska."""
    out: list[PublicPosition] = []
    for job in await team_jobs(db, team.id):
        # Rekrutacja przeniesiona do innego klienta nie idzie linkiem zespołu
        # starego klienta (audyt 24.11.2026; PATCH i tak odmawia takiej zmiany).
        if is_closed(job) or job.client_id != team.client_id:
            continue
        panel = await panel_service.panel_for_job(db, job.id)
        if panel is None or not panel.enabled or panel_service.is_expired(panel):
            continue
        token = panel_service.current_token(panel)
        if token is None:
            continue
        out.append(PublicPosition(token, job, panel))
    return out


async def _owner_name(
    db: AsyncSession, team: JobTeam, positions: list[PublicPosition]
) -> Optional[str]:
    """Osoba prowadząca dla klienta: DL pierwszego stanowiska, inaczej autor zespołu."""
    for position in positions:
        if position.job.delivery_lead_id:
            lead = await db.get(User, position.job.delivery_lead_id)
            if lead is not None and lead.is_active:
                return lead.name
    author = await db.get(User, team.created_by) if team.created_by else None
    return author.name if author is not None else None


def public_variants(
    stored: Iterable[Mapping[str, Any]],
    seen: Mapping[int, tuple[str, Mapping[int, str]]],
) -> list[dict[str, Any]]:
    """Zatwierdzone składy w kształcie klienta: ``picks = {klucz: [public_id]}``.

    ``seen``: rekrutacja → (klucz stanowiska, {kandydat: public_id}) dla osób,
    które klient widzi teraz na liście. Osoba ukryta, wycofana albo ze
    stanowiska, którego klient nie widzi, wypada; skład bez nikogo wypada.
    """
    out: list[dict[str, Any]] = []
    for variant in stored:
        picks: dict[str, list[str]] = {}
        for pick in variant.get("picks") or []:
            position = seen.get(pick.get("job_id"))
            if position is None:
                continue
            key, people = position
            chosen = [
                people[int(cid)]
                for cid in pick.get("candidate_ids") or []
                if int(cid) in people
            ]
            if chosen:
                picks.setdefault(key, []).extend(chosen)
        if picks:
            out.append(
                {
                    "key": variant.get("key"),
                    "name": variant.get("name"),
                    "why": variant.get("why"),
                    "picks": picks,
                }
            )
    return out


def _estimate(
    view: Mapping[str, Any], hint: Optional[Mapping[str, float]]
) -> Optional[dict[str, float]]:
    """Widełki z historii klienta tylko tam, gdzie klient nie widzi żadnej stawki.

    Panel z ukrytą stawką nie dostaje widełek (inaczej wyłączenie stawek
    wypuszczałoby cenę inną drogą). Stanowisko z choć jedną stawką godzinową
    na liście też nie: klient widzi wtedy prawdziwą cenę, nie szacunek.
    """
    if not view["panel"]["show_rate"]:
        return None
    for candidate in view.get("candidates") or []:
        rate = candidate.get("rate")
        if rate and rate.get("unit") == rates_service.HOURLY:
            return None
    return rates_service.public_estimate(hint)


async def public_team_view(
    db: AsyncSession,
    team: JobTeam,
    positions: Optional[list[PublicPosition]] = None,
) -> dict[str, Any]:
    if positions is None:
        positions = await public_positions(db, team)
    items = []
    seen: dict[int, tuple[str, dict[int, str]]] = {}
    hints: dict[int, Optional[dict[str, float]]] = {}
    if any(position.panel.show_rate for position in positions):
        hints = await rates_service.rate_hints(db, [p.job for p in positions])
    for position in positions:
        view = await panel_service.public_panel_view(
            db, position.panel, position.job, None
        )
        items.append(
            {
                "key": position.key,
                "short": view["job"]["title"],
                "headcount": headcount(position.job),
                "estimate": _estimate(view, hints.get(position.job.id)),
                "view": view,
            }
        )
        if team.variants:
            listed = {c["public_id"] for c in view.get("candidates") or []}
            rows = await panel_service.candidate_rows(db, position.panel.id)
            seen[position.job.id] = (
                position.key,
                {
                    cid: row.public_id
                    for cid, row in rows.items()
                    if row.public_id in listed
                },
            )
    return {
        "team": {
            "name": team.name,
            "client_name": await _client_name(db, team.client_id),
            "expires_at": _iso(team.panel_expires_at),
            "owner": {"name": await _owner_name(db, team, positions)},
        },
        "hours_per_month": HOURS_PER_MONTH,
        "positions": items,
        "variants": public_variants(team.variants or [], seen),
    }


# ── Wybór składu ─────────────────────────────────────────────────────────────


def map_picks(
    picks: Mapping[str, list[str]],
    keys: Mapping[str, int],
    visible: Mapping[int, Mapping[str, int]],
) -> list[dict[str, Any]]:
    """``{klucz: [public_id]}`` → ``[{job_id, candidate_ids}]``; nieznane = 422.

    ``keys``: klucz stanowiska → rekrutacja; ``visible``: rekrutacja →
    {public_id: kandydat} dla osób, które klient widzi na liście.
    """
    out: list[dict[str, Any]] = []
    for key, public_ids in picks.items():
        job_id = keys.get(key)
        if job_id is None:
            raise HTTPException(
                status_code=422, detail="Tego stanowiska nie ma w zespole."
            )
        people = visible.get(job_id, {})
        chosen: list[int] = []
        for public_id in public_ids:
            candidate_id = people.get(public_id)
            if candidate_id is None:
                raise HTTPException(
                    status_code=422, detail="Tej osoby nie ma na liście stanowiska."
                )
            if candidate_id not in chosen:
                chosen.append(candidate_id)
        if chosen:
            out.append({"job_id": job_id, "candidate_ids": chosen})
    if not out:
        raise HTTPException(status_code=422, detail="Wybierz co najmniej jedną osobę.")
    return out


async def visible_people(
    db: AsyncSession, positions: Iterable[PublicPosition]
) -> dict[int, dict[str, int]]:
    """Rekrutacja → {public_id: kandydat}: osoby z listy klienta (bez ukrytych)."""
    out: dict[int, dict[str, int]] = {}
    for position in positions:
        sent = await panel_service.sent_pairs(db, position.job.id)
        rows = await db.scalars(
            select(ClientPanelCandidate).where(
                ClientPanelCandidate.panel_id == position.panel.id
            )
        )
        out[position.job.id] = {
            row.public_id: row.candidate_id
            for row in rows.all()
            if not row.hidden and row.candidate_id in sent
        }
    return out


async def guard_selection_write(db: AsyncSession, team: JobTeam) -> None:
    """Dzienny limit wyborów zespołu = 429; wiersz zespołu zablokowany do commitu."""
    await db.execute(select(JobTeam.id).where(JobTeam.id == team.id).with_for_update())
    day_start = datetime.combine(
        business_today(), time.min, ZoneInfo(settings.BUSINESS_TZ)
    ).astimezone(timezone.utc)
    written = await db.scalar(
        select(func.count(JobTeamSelection.id)).where(
            JobTeamSelection.team_id == team.id,
            JobTeamSelection.created_at >= day_start,
        )
    )
    if (written or 0) >= DAILY_SELECTION_LIMIT:
        raise HTTPException(
            status_code=429,
            detail="Dziś z tego linku wysłano już dużo wyborów. Spróbuj jutro albo napisz do osoby prowadzącej rekrutację.",
        )


def team_link(team_id: int) -> str:
    return f"/zespoly/{team_id}"


async def notify_selection(
    db: AsyncSession, team: JobTeam, row: JobTeamSelection, jobs: Iterable[Job]
) -> None:
    """Dzwonek DL-i zespołu. Bez treści od autora, jak w panelu rekrutacji."""
    from app.services.notification_triggers import _delivery_lead_targets, emit

    targets: list[int] = []
    for job in jobs:
        for user_id in await _delivery_lead_targets(db, job):
            if user_id not in targets:
                targets.append(user_id)
    for user_id in targets:
        try:
            async with db.begin_nested():
                await emit(
                    db,
                    user_id=user_id,
                    title="Klient wybrał skład zespołu",
                    message=f"{team.name}. Wybór czeka w zespole dla klienta.",
                    ntype=NotificationType.client_panel_request,
                    related_entity_type="job_team_selection",
                    related_entity_id=row.id,
                    link=team_link(team.id),
                )
        except Exception:  # noqa: BLE001 — dzwonek nie może cofnąć wyboru klienta
            logger.exception("job team: notification failed for selection %s", row.id)
