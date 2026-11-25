"""Silnik raportu kompetencji: snapshot z warunków kandydata i wysyłka (N3, N4).

Plan: b2bnetwork-www ``docs/raport-24h-wdrozenie.md``, makieta „3 · Mail z raportem”.
Raport liczymy z warunków, które kandydat podał w formularzu
(``competence_reports.conditions``), a nie z profilu: profil chroni zmiany
rekrutera z 14 dni, raport ma odpowiadać na to, o co osoba pytała.

- Lejek: otwarte rekrutacje (``is_open``) z technologią roli w ``must_skills``
  (rola stanowiskowa: tytuł albo kategoria kompetencji) → dni w biurze → miasto
  albo zdalnie → budżet od jego stawki. Reguły jak w ``dealbreaker_filters``:
  nieznane przechodzi, budżet równy stawce przechodzi. Krok, który przy tych
  warunkach niczego nie odfiltruje, nie trafia do lejka.
- „Co otworzy więcej”: przeliczenie z poluzowaniem JEDNEGO warunku; tylko
  zmiany z zyskiem co najmniej 1 projekt, najwyżej trzy.
- Projekty: tytuł publiczny bez nazwy klienta, budżet w dół do 5 zł; tytuł,
  miejsce i technologie, w których mimo to stoi nazwa klienta, odpadają.
- Wariant ``limited``: brak roli, brak stawek rynku albo CV nieodczytane po 20 h.

``send_report`` rezerwuje wiersz (``sent``) i commituje przed wysyłką, jak
``candidate_terms_queue.send_one``: restart w trakcie nie wyśle drugiego maila.
Nazwy ``build_snapshot``, ``rebuild_snapshot``, ``send_report`` i
``send_report_now`` to kontrakt z kolejką rekrutera.
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Optional

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.candidate_skill_usage import CandidateSkillUsage
from app.models.competence_category import CompetenceCategory
from app.models.competence_report import CompetenceReport
from app.models.job import Job
from app.models.user import User
from app.services import market_rates
from app.services.competence_report_email import (
    KIND,
    RenderedMail,
    ReportLinks,
    fmt_num,
    recipient_allowed,
    render_report_email,
)
from app.services.competence_report_schema import (
    FunnelStep,
    Lever,
    MarketRate,
    MissingTech,
    RatePosition,
    ReportConditions,
    ReportJob,
    ReportOwner,
    ReportProfile,
    ReportSnapshot,
    TechPremium,
    round_budget,
)
from app.services.competence_report_tokens import new_token, report_urls, token_expiry

logger = logging.getLogger(__name__)

#: Po tylu nieudanych wysyłkach raport przechodzi w ``failed``.
MAX_ATTEMPTS = 5
MAX_JOBS = 3
MAX_LEVERS = 3
JOB_SKILLS_SHOWN = 4
ACTIVITY_ACTION = "competence_report_sent"

# „Otwarte projekty {…}”, „najwięcej projektów {…}”.
ROLE_PHRASE: dict[str, str] = {
    "java": "z Javą",
    "python": "z Pythonem",
    "dotnet": "z .NET",
    "frontend": "z frontendem",
    "kotlin": "z Kotlinem",
    "go": "z Go",
    "php": "z PHP",
    "tester": "dla testerów",
    "devops": "dla DevOps",
    "business_analyst": "dla analityków biznesowych",
    "project_manager": "dla kierowników projektów",
    "data_engineer": "dla inżynierów danych",
}
FALLBACK_ROLE_LABEL = "Twój profil"


class ReportNotSendable(Exception):
    """Raport nie może teraz wyjść; ``reason`` to krótki kod bez danych osobowych."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# ── Fakty rekrutacji i warunki (bez bazy) ───────────────────────────────────


@dataclass(frozen=True)
class JobFacts:
    job_id: int
    days: Optional[int]
    needs_office: bool
    remote: bool
    office_tokens: frozenset[str]
    city: Optional[str]
    budget: Optional[float]
    must: tuple[str, ...]  # kanoniczne nazwy, małe litery
    skills: tuple[str, ...]  # do pokazania, pisownia z rekrutacji


@dataclass(frozen=True)
class Terms:
    rate: int
    office_max: Optional[int]
    remote_only: bool
    cities: tuple[str, ...]
    remote_ok: bool


def terms_from(conditions: ReportConditions) -> Terms:
    modes = set(conditions.modes)
    remote_only = modes == {"remote"} or conditions.office_days_max == 0
    return Terms(
        rate=conditions.rate,
        office_max=conditions.office_days_max,
        remote_only=remote_only,
        cities=tuple(
            c
            for c in (market_rates.normalize_city(x) for x in conditions.office_cities)
            if c
        ),
        remote_ok=not modes or "remote" in modes,
    )


def _city_tokens(cities: Iterable[str]) -> set[str]:
    from app.services.location_utils import location_tokens

    out: set[str] = set()
    for city in cities:
        out |= location_tokens(city)
    return out


def _fails(job: JobFacts, t: Terms) -> list[str]:
    """Które warunki odrzucają rekrutację (kolejność jak w lejku)."""
    from app.services.dealbreaker_filters import office_days_exceeded
    from app.services.location_utils import tokens_overlap

    out: list[str] = []
    if not t.remote_only and office_days_exceeded(
        SimpleNamespace(max_onsite_days_per_week=t.office_max), job.days
    ):
        out.append("office_days")
    if t.remote_only:
        if job.needs_office:
            out.append("location")
    elif (
        t.cities
        and job.needs_office
        and job.office_tokens
        and not tokens_overlap(set(job.office_tokens), _city_tokens(t.cities))
    ):
        out.append("location")
    if job.budget is not None and job.budget < t.rate:
        out.append("budget")
    return out


def _count(jobs: Sequence[JobFacts], t: Terms) -> int:
    return sum(1 for job in jobs if not _fails(job, t))


def _or_list(items: Sequence[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} albo {items[-1]}"


def _days(n: int) -> str:
    return f"{n} {'dzień' if n == 1 else 'dni'}"


def _office_step_active(t: Terms) -> bool:
    return not t.remote_only and t.office_max is not None and 0 < t.office_max < 5


def funnel(jobs: Sequence[JobFacts], t: Terms, *, role: str) -> tuple[FunnelStep, ...]:
    """Kroki narastająco; krok, który przy tych warunkach nie filtruje, pomijamy."""
    steps: list[tuple[str, str]] = [
        ("tech", f"Otwarte projekty {ROLE_PHRASE.get(role, '')}".strip())
    ]
    if _office_step_active(t):
        d = t.office_max
        steps.append(("office_days", f"Biuro do {d} {'dnia' if d == 1 else 'dni'}"))
    if t.remote_only:
        steps.append(("location", "Zdalnie"))
    elif t.cities:
        places = list(t.cities) + (["zdalnie"] if t.remote_ok else [])
        steps.append(("location", _or_list(places)))
    steps.append(("budget", f"Od {fmt_num(t.rate)} zł/h"))
    out: list[FunnelStep] = []
    remaining = list(jobs)
    for key, label in steps:
        if key != "tech":
            remaining = [job for job in remaining if key not in _fails(job, t)]
        out.append(FunnelStep(key=key, label=label, count=len(remaining)))  # type: ignore[arg-type]
    return tuple(out)


def _best_extra_city(jobs: Sequence[JobFacts], t: Terms) -> Optional[str]:
    """Miasto spoza jego listy z największą liczbą rekrutacji, którym brakuje tylko miasta."""
    mine = {c.lower() for c in t.cities}
    counts = Counter(
        job.city
        for job in jobs
        if job.city and job.city.lower() not in mine and _fails(job, t) == ["location"]
    )
    if not counts:
        return None
    return min(counts, key=lambda c: (-counts[c], c))


def levers(
    jobs: Sequence[JobFacts],
    t: Terms,
    *,
    role: str,
    median: Optional[int],
    profile_city: Optional[str],
) -> tuple[Lever, ...]:
    base = _count(jobs, t)
    options: list[tuple[str, str, Optional[str], Terms]] = []
    if _office_step_active(t):
        d = t.office_max + 1
        options.append(
            (
                "office_days_plus1",
                f"{d} dni w biurze zamiast {t.office_max}",
                None,
                replace(t, office_max=d),
            )
        )
    if not t.remote_only and t.cities:
        city = _best_extra_city(jobs, t)
        if city:
            options.append(
                (
                    "extra_city",
                    f"{city} jako dodatkowe miasto",
                    f"tu jest najwięcej projektów {ROLE_PHRASE.get(role, '')} poza Twoimi miastami".replace(
                        "  ", " "
                    ),
                    replace(t, cities=t.cities + (city,)),
                )
            )
    if median is not None and t.rate > median:
        options.append(
            (
                "rate_to_median",
                f"Stawka od {fmt_num(median)} zł/h",
                "to nadal mediana dla Twojego CV",
                replace(t, rate=median),
            )
        )
    if t.remote_only:
        cities = t.cities or ((profile_city,) if profile_city else ())
        if cities:
            options.append(
                (
                    "remote_to_hybrid",
                    "Hybrydowo, 1 dzień w biurze",
                    f"biuro: {_or_list(list(cities))}",
                    replace(t, remote_only=False, office_max=1, cities=tuple(cities)),
                )
            )
    found = []
    for key, label, hint, relaxed in options:
        gain = _count(jobs, relaxed) - base
        if gain >= 1:
            found.append(Lever(key=key, label=label, hint=hint, gain=gain))  # type: ignore[arg-type]
    found.sort(key=lambda lever: -lever.gain)
    return tuple(found[:MAX_LEVERS])


def _miss_reason(key: str, job: JobFacts, t: Terms) -> str:
    if key == "office_days":
        return f"o {_days((job.days or 0) - (t.office_max or 0))} w biurze za dużo"
    if key == "location":
        return "wymaga pracy w biurze" if t.remote_only else "poza Twoimi miastami"
    return "budżet poniżej Twojej stawki"


def pick_jobs(
    jobs: Sequence[JobFacts], t: Terms
) -> list[tuple[JobFacts, Optional[str]]]:
    """Najpierw spełniające wszystko, potem chybione o jeden warunek; wyższy budżet pierwszy."""

    def order(job: JobFacts) -> tuple:
        return (job.budget is None, -(job.budget or 0), job.job_id)

    meets = sorted((j for j in jobs if not _fails(j, t)), key=order)
    near = sorted((j for j in jobs if len(_fails(j, t)) == 1), key=order)
    picked: list[tuple[JobFacts, Optional[str]]] = [(j, None) for j in meets[:MAX_JOBS]]
    for job in near[: MAX_JOBS - len(picked)]:
        picked.append((job, _miss_reason(_fails(job, t)[0], job, t)))
    return picked


def place_of(job: JobFacts) -> Optional[str]:
    if job.needs_office:
        parts = [
            p
            for p in (job.city, f"{_days(job.days)} w biurze" if job.days else None)
            if p
        ]
        return ", ".join(parts) or "z biurem"
    return "zdalnie" if job.remote else None


def missing_tech(
    jobs: Sequence[JobFacts], *, have: set[str], role: str
) -> Optional[tuple[str, int, int]]:
    """``(nazwa, w ilu, z ilu)``: najczęstsza wymagana technologia, której nie ma w CV."""
    from app.services.dealbreaker_filters import gate_eligible_must_skills

    if not jobs:
        return None
    role_pattern = (
        market_rates._PY[role][0] if market_rates.ROLES[role].kind == "tech" else None
    )
    counts: Counter[str] = Counter()
    shown: dict[str, str] = {}
    for job in jobs:
        for name in set(gate_eligible_must_skills(job.must)):
            if name in have or (role_pattern and role_pattern.search(name)):
                continue
            counts[name] += 1
        for canon, display in zip(job.must, job.skills):
            shown.setdefault(canon, display)
    if not counts:
        return None
    name = min(counts, key=lambda n: (-counts[n], n))
    return shown.get(name, name), counts[name], len(jobs)


# ── Odczyt z bazy ───────────────────────────────────────────────────────────


def _canonical(names: Iterable[str]) -> list[str]:
    from app.services.scoring_service import canonical_skill_names

    return canonical_skill_names([n for n in names if n])


def _display_skills(raw: Any) -> dict[str, str]:
    """Kanoniczna nazwa → pisownia z rekrutacji (dla listy napisów)."""
    out: dict[str, str] = {}
    if isinstance(raw, list):
        for item in raw:
            value = (
                item
                if isinstance(item, str)
                else item.get("name")
                if isinstance(item, dict)
                else None
            )
            if isinstance(value, str) and value.strip():
                canon = _canonical([value])
                if canon:
                    out.setdefault(canon[0], value.strip())
    return out


def _job_city(location: Optional[str]) -> Optional[str]:
    from app.services.public_city import public_city

    text = public_city(location) or ""
    if not text or text.lstrip().startswith("{"):
        return None
    return market_rates.normalize_city(text.split(",")[0])


def job_facts(job: Job) -> JobFacts:
    from app.services.dealbreaker_filters import (
        resolve_effective_remote_policy,
        resolve_job_budget_hourly,
    )
    from app.services.location_utils import location_tokens

    days = (
        job.onsite_days_per_week if isinstance(job.onsite_days_per_week, int) else None
    )
    policy = resolve_effective_remote_policy(job)
    must = tuple(_canonical_raw(job.must_skills))
    display = _display_skills(job.must_skills)
    return JobFacts(
        job_id=job.id,
        days=days,
        needs_office=bool(days and days > 0) or policy in ("onsite", "hybrid"),
        remote=policy == "remote",
        office_tokens=frozenset(location_tokens(job.location)),
        city=_job_city(job.location),
        budget=resolve_job_budget_hourly(job),
        must=must,
        skills=tuple(display.get(m, m) for m in must),
    )


def _canonical_raw(raw: Any) -> list[str]:
    from app.services.scoring_service import canonical_skill_names

    return canonical_skill_names(raw)


def _matches_role(
    role: str, facts: JobFacts, title: str, category: Optional[str]
) -> bool:
    definition = market_rates.ROLES[role]
    if definition.kind == "tech":
        pattern = market_rates._PY[role][0]
        return any(pattern.search(name) for name in facts.must)
    return role in {
        market_rates._position_role(title or ""),
        market_rates._position_role(category or ""),
    }


async def _open_role_jobs(db: AsyncSession, role: str) -> list[tuple[Job, JobFacts]]:
    rows = (
        await db.execute(
            select(Job, CompetenceCategory.name_pl)
            .outerjoin(
                CompetenceCategory, CompetenceCategory.id == Job.competence_category_id
            )
            .where(Job.is_open.is_(True))
            .order_by(Job.id)
        )
    ).all()
    out = []
    for job, category in rows:
        facts = job_facts(job)
        if _matches_role(role, facts, job.title, category):
            out.append((job, facts))
    return out


async def _client_names(db: AsyncSession, job: Job) -> list[str]:
    from app.services.job_public_profile import _client_names as names_of

    return [n for n in await names_of(db, job.client_id) if n and len(n.strip()) >= 3]


def _mentions(text: Optional[str], names: Sequence[str]) -> bool:
    """Nazwa klienta jako osobne słowo („ING” nie trafia w „Engineering”)."""
    return any(
        re.search(rf"(?<!\w){re.escape(name.strip())}(?!\w)", text or "", re.IGNORECASE)
        for name in names
    )


async def _report_job(
    db: AsyncSession,
    job: Job,
    facts: JobFacts,
    miss_reason: Optional[str],
    role_label: str,
) -> ReportJob:
    from app.services.application_confirmation_email import public_job_title
    from app.services.job_public_profile import default_public_title

    names = await _client_names(db, job)
    title = await public_job_title(db, job.id) or default_public_title(
        job.title, names, getattr(job, "client_reference", None)
    )
    if _mentions(title, names):
        title = f"Projekt: {role_label}"
    place = place_of(facts)
    return ReportJob(
        job_id=job.id,
        title=title[:200],
        budget_max=round_budget(facts.budget),
        skills=tuple(
            s for s in facts.skills[:JOB_SKILLS_SHOWN] if not _mentions(s, names)
        ),
        place=None if _mentions(place, names) else place,
        meets=miss_reason is None,
        miss_reason=miss_reason,
    )


def _pct(value: int, median: int) -> int:
    return math.floor((value - median) * 100 / median + 0.5)


async def _usage_rows(db: AsyncSession, candidate_id: int) -> list[Any]:
    return list(
        (
            await db.execute(
                select(
                    CandidateSkillUsage.skill_canonical,
                    CandidateSkillUsage.skill_raw,
                    CandidateSkillUsage.months,
                ).where(CandidateSkillUsage.candidate_id == candidate_id)
            )
        ).all()
    )


def _fallback_label(candidate: Optional[Candidate]) -> str:
    data = (
        candidate.cv_extracted_data
        if candidate is not None and isinstance(candidate.cv_extracted_data, dict)
        else {}
    )
    position = " ".join(str(data.get("current_position") or "").split())
    return position[:60] or FALLBACK_ROLE_LABEL


async def _owner(db: AsyncSession, report: CompetenceReport) -> Optional[ReportOwner]:
    if report.owner_user_id is None:
        return None
    user = await db.get(User, report.owner_user_id)
    if user is None or not (user.name or "").strip():
        return None
    return ReportOwner(user_id=user.id, name=user.name.strip())


async def _strongest(
    db: AsyncSession, role: str, market: MarketRate, rows: Sequence[Any]
) -> Optional[TechPremium]:
    pattern = (
        market_rates._PY[role][0] if market_rates.ROLES[role].kind == "tech" else None
    )
    months: dict[str, int] = {}
    raw_of: dict[str, str] = {}
    for row in rows:
        key = (row.skill_canonical or "").strip().lower()
        if not key or (pattern and pattern.search(key)):
            continue
        months[key] = max(months.get(key, 0), row.months or 0)
        raw_of.setdefault(key, (row.skill_raw or row.skill_canonical).strip())
    if not months:
        return None
    premiums = await market_rates.tech_premiums(
        db, role=role, group=market.group, skills=list(months)
    )
    if not premiums:
        return None
    top = premiums[0]
    key = top.name.lower()
    return TechPremium(
        name=raw_of.get(key, top.name),
        premium=top.premium,
        months=months.get(key) or None,
    )


async def _missing(
    db: AsyncSession,
    role: str,
    market: Optional[MarketRate],
    jobs: Sequence[JobFacts],
    have: set[str],
) -> Optional[MissingTech]:
    found = missing_tech(jobs, have=have, role=role)
    if found is None:
        return None
    name, count, of = found
    premium = None
    if market is not None:
        premiums = await market_rates.tech_premiums(
            db, role=role, group=market.group, skills=[name]
        )
        premium = premiums[0].premium if premiums else None
    return MissingTech(name=name, premium=premium, jobs=count, of=of)


async def build_snapshot(
    db: AsyncSession, report: CompetenceReport, *, limited: bool = False
) -> ReportSnapshot:
    """Snapshot raportu z warunków formularza. Bez zapisu i bez commitu.

    ``limited=True`` (CV nieodczytane po 20 h): bez stawki i technologii, lejek
    i projekty tylko wtedy, gdy rolę da się ustalić z tego, co już jest.
    """
    conditions = ReportConditions.model_validate(report.conditions)
    candidate = await db.get(Candidate, report.candidate_id)
    rows = await _usage_rows(db, report.candidate_id)
    data = candidate.cv_extracted_data if candidate is not None else None
    role = market_rates.resolve_role(data if isinstance(data, dict) else None, rows)
    city = market_rates.normalize_city(
        candidate.city if candidate is not None else None
    )
    owner = await _owner(db, report)
    if role is None:
        return ReportSnapshot(
            variant="limited",
            conditions=conditions,
            profile=ReportProfile(role_label=_fallback_label(candidate), city=city),
            owner=owner,
        )
    role_label = market_rates.ROLES[role].role_label
    years = market_rates.role_years(role, rows)
    profile = ReportProfile(role_label=role_label, years=years, city=city)
    t = terms_from(conditions)
    market = (
        None
        if limited
        else await market_rates.market_rate_for(db, role=role, years=years, city=city)
    )
    open_jobs = await _open_role_jobs(db, role)
    facts = [f for _, f in open_jobs]
    by_id = {job.id: job for job, _ in open_jobs}
    jobs = tuple(
        [
            await _report_job(db, by_id[f.job_id], f, reason, role_label)
            for f, reason in pick_jobs(facts, t)
        ]
    )
    common = dict(
        conditions=conditions,
        profile=profile,
        funnel=funnel(facts, t, role=role),
        levers=levers(
            facts,
            t,
            role=role,
            median=market.median if market else None,
            profile_city=city,
        ),
        jobs=jobs,
        owner=owner,
    )
    if market is None:
        return ReportSnapshot(variant="limited", **common)
    rate_position = RatePosition(
        expected=conditions.rate,
        expected_vs_median_pct=_pct(conditions.rate, market.median),
        current=conditions.current_rate,
        current_vs_median_pct=_pct(conditions.current_rate, market.median)
        if conditions.current_rate
        else None,
    )
    have = set(_canonical(r.skill_canonical for r in rows))
    return ReportSnapshot(
        variant="full",
        market=market,
        rate_position=rate_position,
        strongest_tech=await _strongest(db, role, market, rows),
        missing_tech=await _missing(db, role, market, facts, have),
        **common,
    )


def fallback_snapshot(report: CompetenceReport) -> ReportSnapshot:
    """Najkrótszy raport, gdy złożenie pełnego się wywróciło (termin 24 h zostaje)."""
    return ReportSnapshot(
        variant="limited",
        conditions=ReportConditions.model_validate(report.conditions),
        profile=ReportProfile(role_label=FALLBACK_ROLE_LABEL),
    )


async def rebuild_snapshot(
    db: AsyncSession, report: CompetenceReport
) -> ReportSnapshot:
    """Po zmianie warunków: nowy snapshot zapisany na wierszu. Bez commitu."""
    snapshot = await build_snapshot(db, report)
    report.snapshot = snapshot.model_dump(mode="json")
    return snapshot


# ── Wysyłka ─────────────────────────────────────────────────────────────────


def _first_name(candidate: Optional[Candidate]) -> Optional[str]:
    from app.services.public_apply import PLACEHOLDER_NAME

    name = (candidate.name if candidate is not None else "") or ""
    return None if not name.strip() or name.strip() == PLACEHOLDER_NAME else name


def _deliver(
    mail: RenderedMail, *, to: str, event_at: datetime, reply_to: Optional[str]
) -> tuple[bool, bool]:
    """Wątek wysyłki; polityka sprawdzana jeszcze raz tuż przed nadawcą. ``(ok, niepewne)``."""
    from app.services.email import send_email
    from app.services.m365.app_mail import last_delivery_uncertain
    from app.services.notification_delivery import (
        guarded_send,
        last_send_policy_blocked,
    )

    ok = guarded_send(
        KIND,
        event_at,
        send_email,
        to,
        mail.subject,
        mail.text,
        mail.html,
        reply_to,
        settings.CANDIDATE_MAIL_SENDER_UPN or None,
        list_unsubscribe=mail.list_unsubscribe,
    )
    uncertain = bool(
        not ok
        and settings.M365_APP_MAIL_ENABLED
        and not last_send_policy_blocked()
        and last_delivery_uncertain()
    )
    return bool(ok), uncertain


async def _candidate_opted_out(db: AsyncSession, candidate_id: int) -> bool:
    return bool(
        await db.scalar(
            select(
                exists().where(
                    CompetenceReport.candidate_id == candidate_id,
                    CompetenceReport.opted_out_at.is_not(None),
                )
            )
        )
    )


async def _blocker(
    db: AsyncSession, row: CompetenceReport, *, manual: bool
) -> Optional[tuple[str, Optional[str]]]:
    """``(powód, nowy status albo None)`` gdy raport nie może wyjść."""
    from app.services.candidate_terms_queue import candidate_sender_ready
    from app.services.notification_delivery import load_policy

    if row.status != "ready" and not (manual and row.status == "failed"):
        return "not_ready", None
    if row.opted_out_at is not None or await _candidate_opted_out(db, row.candidate_id):
        return "opted_out", "opted_out"
    if row.held_at is not None and not manual:
        return "held", None
    if not row.snapshot:
        return "no_snapshot", None
    if not recipient_allowed(row.email):
        return "recipient_not_allowed", None if manual else "skipped"
    if not candidate_sender_ready():
        return "sender_not_ready", None
    policy = await load_policy(db)
    if not policy.allows(KIND, row.created_at):
        before = policy.kind_enabled(KIND) and not manual
        return ("before_enabled", "skipped") if before else ("mail_disabled", None)
    return None


async def send_report(
    db: AsyncSession,
    report: CompetenceReport,
    *,
    by_user_id: Optional[int],
    now: Optional[datetime] = None,
) -> None:
    """Wyślij raport. Commituje (rezerwacja przed wysyłką i wynik po niej).

    Rzuca ``ReportNotSendable`` z kodem, gdy raport nie może wyjść (wypis,
    wstrzymanie przy wysyłce automatycznej, adres spoza próby, mail wyłączony
    w Ustawieniach). Wysyłka rekrutera (``by_user_id``) przechodzi mimo
    „Wstrzymaj” i ponawia raport ``failed``. Nieudana wysyłka: ``attempts`` + 1,
    ``last_error``, po ``MAX_ATTEMPTS`` status ``failed``.
    """
    now = now or datetime.now(timezone.utc)
    row = await db.scalar(
        select(CompetenceReport)
        .where(CompetenceReport.id == report.id)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise ReportNotSendable("busy")
    blocked = await _blocker(db, row, manual=by_user_id is not None)
    if blocked is not None:
        reason, status = blocked
        if status is not None:
            row.status, row.last_error = status, reason
        # Commit, nie rollback: zwalnia blokadę, a nie wygasza obiektów wołającego.
        await db.commit()
        raise ReportNotSendable(reason)

    candidate = await db.get(Candidate, row.candidate_id)
    owner = await db.get(User, row.owner_user_id) if row.owner_user_id else None
    raw, digest = new_token()
    urls = report_urls(raw)
    mail = render_report_email(
        ReportSnapshot.model_validate(row.snapshot),
        first_name=_first_name(candidate),
        links=ReportLinks(
            edit_conditions_url=urls.edit_conditions_url,
            unsubscribe_url=urls.unsubscribe_url,
            one_click_unsubscribe_url=urls.one_click_unsubscribe_url,
        ),
    )
    to, event_at = row.email, row.created_at
    reply_to = owner.email if owner is not None and owner.is_active else None
    # Rezerwacja przed wysyłką: drugi worker go nie weźmie, a restart w trakcie
    # nie wyśle drugiego maila (niepewny wynik zostaje „sent”).
    row.token_hash, row.token_expires_at = digest, token_expiry(now)
    row.status, row.sent_at, row.sent_by_user_id = "sent", now, by_user_id
    row.last_error = None
    await db.commit()

    uncertain = False
    try:
        ok, uncertain = await asyncio.to_thread(
            _deliver, mail, to=to, event_at=event_at, reply_to=reply_to
        )
        error = None if ok else "policy_blocked_or_send_failed"
    except Exception as exc:  # noqa: BLE001 — wynik zapisujemy na wierszu
        logger.warning("[competence-report] send failed: %s", type(exc).__name__)
        ok, error = False, f"send_error:{type(exc).__name__}"[:120]
    if ok or uncertain:
        db.add(
            Activity(
                entity_type="candidate",
                entity_id=row.candidate_id,
                action=ACTIVITY_ACTION,
                user_id=by_user_id,
                external_source="system" if by_user_id is None else "manual",
                details={
                    "summary": "raport kompetencji wysłany",
                    "report_id": row.id,
                    "manual": by_user_id is not None,
                    **({"uncertain": True} if uncertain else {}),
                },
            )
        )
        await db.commit()
        return
    row.attempts = (row.attempts or 0) + 1
    row.status = "failed" if row.attempts >= MAX_ATTEMPTS else "ready"
    row.sent_at = row.sent_by_user_id = None
    row.token_hash = row.token_expires_at = None
    row.last_error = error
    await db.commit()


async def send_report_now(
    db: AsyncSession, report: CompetenceReport, user: User
) -> None:
    """„Wyślij teraz” z kolejki rekrutera: przed terminem, jako ``user``."""
    await send_report(db, report, by_user_id=user.id)
