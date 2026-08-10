"""Kanoniczne metryki Analytics v1 (plan §4.2, PR 3).

JEDYNA implementacja definicji metryk — router v1, przyszłe adaptery legacy
i KPI Coach v2 mają liczyć przez te funkcje, nigdy własnym SQL-em.

Definicje (plan §4.2):
- aktualny pipeline    = ostatni CandidateStage per kandydat × job
  (view ``analytics_current_pipeline``),
- milestone            = PIERWSZE osiągnięcie stage'a per kandydat × job
  (view ``analytics_first_milestones``): verified / cv_sent / interview /
  client_interview / hired,
- atrybucja            = ``first_moved_by`` pierwszego przejścia,
- rozmowa              = Call.status == completed, data efektywna
  ``COALESCE(started_at, created_at)``,
- źródło               = pierwszy CandidateSourceEvent (first-touch,
  view ``analytics_candidate_first_sources``),
- aktywny kontrakt     = date-effective ``start_date <= dziś < end_date``
  (NULL end = bezterminowy), status poza draft,
- wynik przetargu      = ``Job.close_reason``; NULL = "unknown",
- finanse              = Decimal; kwoty wychodzą jako decimal-string + PLN.

Wszystkie funkcje przyjmują ``Period`` ([start, end), Europe/Warsaw).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import distinct, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.analytics.periods import Period
from app.models.call import Call, CallStatus
from app.models.candidate import Candidate, CandidateStatus
from app.models.client import Client
from app.models.contract import Contract, ContractStatus
from app.models.job import Job, JobStatus
from app.models.user import User

# Stage'y milestone'ów w kolejności lejka.
FUNNEL_STAGES = ["verified", "cv_sent", "interview", "client_interview", "hired"]

# Status jakości sum finansowych (mapowany na QualityPayload w routerze).
QualityFlag = Literal["complete", "partial", "unavailable"]

# Efektywna data rozmowy (plan §4.2).
_CALL_EFFECTIVE_AT = func.coalesce(Call.started_at, Call.created_at)


def _dec(value: Decimal | int | float | None) -> str | None:
    """Kwota jako decimal-string (plan §4.5). None zostaje None."""
    if value is None:
        return None
    return str(Decimal(value).quantize(Decimal("0.01")))


# ── Viewer-safe ──────────────────────────────────────────────────────────────


async def overview(db: AsyncSession, period: Period) -> dict[str, Any]:
    """Bezpieczne agregaty operacyjne — bez PII, bez finansów, bez nazw."""
    today = date.today()

    candidates_total = (await db.execute(select(func.count(Candidate.id)))).scalar()
    candidates_active = (
        await db.execute(
            select(func.count(Candidate.id)).where(
                Candidate.status == CandidateStatus.active
            )
        )
    ).scalar()
    # jobs.total = PRAWDZIWY total (plan §3.2 — snapshoty kłamały).
    jobs_total = (await db.execute(select(func.count(Job.id)))).scalar()
    jobs_open = (
        await db.execute(
            select(func.count(Job.id)).where(Job.status == JobStatus.published)
        )
    ).scalar()
    clients_total = (await db.execute(select(func.count(Client.id)))).scalar()
    # clients.active = ma date-effective aktywny kontrakt DZIŚ (plan §4.2),
    # nie "status kolumny" (rozdzielenie total/active — §3.2).
    clients_active = (
        await db.execute(
            select(func.count(distinct(Contract.client_id))).where(
                Contract.status != ContractStatus.draft,
                Contract.start_date.isnot(None),
                Contract.start_date <= today,
                (Contract.end_date.is_(None)) | (Contract.end_date >= today),
            )
        )
    ).scalar()
    contracts_active = (
        await db.execute(
            select(func.count(Contract.id)).where(
                Contract.status != ContractStatus.draft,
                Contract.start_date.isnot(None),
                Contract.start_date <= today,
                (Contract.end_date.is_(None)) | (Contract.end_date >= today),
            )
        )
    ).scalar()
    # expiring = [dziś, dziś+30d] po datach, nie po statusie crona.
    expiring = (
        await db.execute(
            select(func.count(Contract.id)).where(
                Contract.status != ContractStatus.draft,
                Contract.end_date.isnot(None),
                Contract.end_date >= today,
                Contract.end_date <= date.fromordinal(today.toordinal() + 30),
            )
        )
    ).scalar()
    placements = (
        await db.execute(
            text(
                "SELECT COUNT(*) FROM analytics_first_milestones "
                "WHERE stage = 'hired' "
                "AND first_reached_at >= :start AND first_reached_at < :end"
            ),
            {"start": period.start, "end": period.end},
        )
    ).scalar()

    return {
        "candidates": {
            "total": candidates_total or 0,
            "active": candidates_active or 0,
        },
        "jobs": {"total": jobs_total or 0, "open": jobs_open or 0},
        "clients": {"total": clients_total or 0, "active": clients_active or 0},
        "contracts": {"active": contracts_active or 0, "expiring_30d": expiring or 0},
        "placements_in_period": placements or 0,
    }


async def pipeline_snapshot(db: AsyncSession) -> dict[str, Any]:
    """Aktualny pipeline = OSTATNI stage per kandydat × job (nie historia)."""
    rows = (
        await db.execute(
            text(
                "SELECT stage, COUNT(*) AS cnt FROM analytics_current_pipeline "
                "GROUP BY stage"
            )
        )
    ).all()
    return {"stages": {r.stage: r.cnt for r in rows}}


async def recruitment_funnel(db: AsyncSession, period: Period) -> dict[str, Any]:
    """Lejek = pierwsze osiągnięcia milestone'ów w okresie (raz per kandydat×job)."""
    rows = (
        await db.execute(
            text(
                "SELECT stage, COUNT(*) AS cnt FROM analytics_first_milestones "
                "WHERE first_reached_at >= :start AND first_reached_at < :end "
                "GROUP BY stage"
            ),
            {"start": period.start, "end": period.end},
        )
    ).all()
    counts = {r.stage: r.cnt for r in rows}
    return {"funnel": {stage: counts.get(stage, 0) for stage in FUNNEL_STAGES}}


async def sources(db: AsyncSession, period: Period) -> dict[str, Any]:
    """Źródła first-touch: distinct kandydaci w liczniku I mianowniku.

    hire_rate <= 100% z konstrukcji: licznik to podzbiór mianownika
    (kandydaci first-touched w okresie, którzy osiągnęli hired).
    """
    rows = (
        await db.execute(
            text(
                """
                SELECT
                    fs.channel,
                    COUNT(DISTINCT fs.candidate_id) AS candidates,
                    COUNT(DISTINCT fm.candidate_id) AS hired
                FROM analytics_candidate_first_sources fs
                LEFT JOIN analytics_first_milestones fm
                    ON fm.candidate_id = fs.candidate_id
                    AND fm.stage = 'hired'
                WHERE fs.captured_at >= :start AND fs.captured_at < :end
                GROUP BY fs.channel
                """
            ),
            {"start": period.start, "end": period.end},
        )
    ).all()
    out = []
    for r in rows:
        candidates = int(r.candidates or 0)
        hired = int(r.hired or 0)
        out.append(
            {
                "channel": r.channel,
                "candidates": candidates,
                "hired": hired,
                "hire_rate_pct": round(100.0 * hired / candidates, 1)
                if candidates
                else 0.0,
            }
        )
    out.sort(key=lambda x: -x["candidates"])
    return {"sources": out}


async def calls_aggregate(
    db: AsyncSession, period: Period, *, user_id: int | None = None
) -> dict[str, Any]:
    """Zakończone rozmowy po dacie efektywnej COALESCE(started_at, created_at)."""
    conds = [
        Call.status == CallStatus.completed,
        _CALL_EFFECTIVE_AT >= period.start,
        _CALL_EFFECTIVE_AT < period.end,
    ]
    if user_id is not None:
        conds.append(Call.user_id == user_id)
    total = (await db.execute(select(func.count(Call.id)).where(*conds))).scalar()
    return {"completed_calls": total or 0}


# ── Personal / team KPI (kanoniczne, NIE UserActivity) ──────────────────────


async def user_kpis(db: AsyncSession, period: Period, user_id: int) -> dict[str, Any]:
    """KPI usera z kanonicznych danych ATS (plan PR 4 §KPI Coach v2):

    - completed_calls          — Call completed po dacie efektywnej,
    - first_verifications      — milestone'y verified z atrybucją first_moved_by,
    - candidates_added         — Candidate.created_by w okresie,
    - first_recommendations    — milestone'y cv_sent (atrybucja j.w.),
    - first_placements         — milestone'y hired (atrybucja j.w.).
    """
    calls = (await calls_aggregate(db, period, user_id=user_id))["completed_calls"]

    milestone_rows = (
        await db.execute(
            text(
                "SELECT stage, COUNT(*) AS cnt FROM analytics_first_milestones "
                "WHERE first_moved_by = :uid "
                "AND first_reached_at >= :start AND first_reached_at < :end "
                "GROUP BY stage"
            ),
            {"uid": user_id, "start": period.start, "end": period.end},
        )
    ).all()
    by_stage = {r.stage: r.cnt for r in milestone_rows}

    candidates_added = (
        await db.execute(
            select(func.count(Candidate.id)).where(
                Candidate.created_by == user_id,
                Candidate.created_at >= period.start,
                Candidate.created_at < period.end,
            )
        )
    ).scalar()

    return {
        "user_id": user_id,
        "completed_calls": calls,
        "first_verifications": by_stage.get("verified", 0),
        "candidates_added": candidates_added or 0,
        "first_recommendations": by_stage.get("cv_sent", 0),
        "first_placements": by_stage.get("hired", 0),
    }


async def team_kpis(
    db: AsyncSession,
    period: Period,
    *,
    user_ids: frozenset[int] | None = None,
) -> dict[str, Any]:
    """Wiersze KPI per aktywny user operacyjny — te same definicje co user_kpis.

    Jedno przejście SQL zamiast N × user_kpis. suma wierszy == totals
    (wymóg parity: team totals = suma wierszy, plan §8). ``user_ids=None``
    oznacza jawny scope organizacyjny. Przekazany (również pusty) zbiór jest
    twardym zakresem menedżerskim i filtruje każde źródło przed agregacją.
    """
    scoped_user_ids = sorted(user_ids) if user_ids is not None else None
    users_stmt = select(User.id, User.name).where(
        User.is_active.is_(True),
        User.role.in_(
            [
                "admin",
                "head_of_recruitment",
                "delivery_lead",
                "tac",
                "recruiter",
                "sourcer",
            ]
        ),
    )
    if scoped_user_ids is not None:
        users_stmt = users_stmt.where(User.id.in_(scoped_user_ids or [-1]))
    users_rows = (await db.execute(users_stmt)).all()

    calls_stmt = (
        select(Call.user_id, func.count(Call.id))
        .where(
            Call.status == CallStatus.completed,
            _CALL_EFFECTIVE_AT >= period.start,
            _CALL_EFFECTIVE_AT < period.end,
            Call.user_id.isnot(None),
        )
        .group_by(Call.user_id)
    )
    if scoped_user_ids is not None:
        calls_stmt = calls_stmt.where(Call.user_id.in_(scoped_user_ids or [-1]))
    calls_rows = (await db.execute(calls_stmt)).all()
    calls_by_user = {r[0]: r[1] for r in calls_rows}

    milestone_scope = ""
    milestone_params: dict[str, Any] = {
        "start": period.start,
        "end": period.end,
    }
    if scoped_user_ids is not None:
        milestone_scope = (
            "AND first_moved_by = ANY(CAST(:scoped_user_ids AS integer[])) "
        )
        milestone_params["scoped_user_ids"] = scoped_user_ids or [-1]
    milestones_rows = (
        await db.execute(
            text(
                "SELECT first_moved_by AS uid, stage, COUNT(*) AS cnt "
                "FROM analytics_first_milestones "
                "WHERE first_moved_by IS NOT NULL "
                f"{milestone_scope}"
                "AND first_reached_at >= :start AND first_reached_at < :end "
                "GROUP BY first_moved_by, stage"
            ),
            milestone_params,
        )
    ).all()
    milestones_by_user: dict[int, dict[str, int]] = {}
    for r in milestones_rows:
        milestones_by_user.setdefault(r.uid, {})[r.stage] = r.cnt

    added_stmt = (
        select(Candidate.created_by, func.count(Candidate.id))
        .where(
            Candidate.created_by.isnot(None),
            Candidate.created_at >= period.start,
            Candidate.created_at < period.end,
        )
        .group_by(Candidate.created_by)
    )
    if scoped_user_ids is not None:
        added_stmt = added_stmt.where(Candidate.created_by.in_(scoped_user_ids or [-1]))
    added_rows = (await db.execute(added_stmt)).all()
    added_by_user = {r[0]: r[1] for r in added_rows}

    rows = []
    for uid, name in users_rows:
        ms = milestones_by_user.get(uid, {})
        rows.append(
            {
                "user_id": uid,
                "user_name": name,
                "completed_calls": calls_by_user.get(uid, 0),
                "first_verifications": ms.get("verified", 0),
                "candidates_added": added_by_user.get(uid, 0),
                "first_recommendations": ms.get("cv_sent", 0),
                "first_placements": ms.get("hired", 0),
            }
        )
    rows.sort(key=lambda r: (-r["first_placements"], -r["first_verifications"]))

    totals = {
        key: sum(r[key] for r in rows)
        for key in (
            "completed_calls",
            "first_verifications",
            "candidates_added",
            "first_recommendations",
            "first_placements",
        )
    }
    return {"rows": rows, "totals": totals}


# ── Przetargi ────────────────────────────────────────────────────────────────


async def tenders(
    db: AsyncSession, period: Period, *, include_values: bool
) -> dict[str, Any]:
    """Wyniki przetargów po Job.close_reason; NULL = 'unknown' (plan §4.2).

    ``include_values`` (VIEW_FINANCE) dokłada sumy widełek — wariant
    viewer/TAC jest fizycznie bez kwot.
    """
    rows = (
        await db.execute(
            select(
                Job.close_reason,
                func.count(Job.id),
                func.sum(func.coalesce(Job.salary_max, 0)),
            )
            .where(
                Job.status == JobStatus.closed,
                Job.closed_at.isnot(None),
                Job.closed_at >= period.start,
                Job.closed_at < period.end,
            )
            .group_by(Job.close_reason)
        )
    ).all()
    outcomes = []
    for reason, cnt, value_sum in rows:
        entry: dict[str, Any] = {
            "outcome": reason.value if reason is not None else "unknown",
            "count": cnt,
        }
        if include_values:
            entry["salary_max_sum"] = _dec(value_sum or 0)
            entry["currency"] = "PLN"
        outcomes.append(entry)
    outcomes.sort(key=lambda o: -o["count"])
    won = sum(o["count"] for o in outcomes if o["outcome"] == "filled_by_us")
    total = sum(o["count"] for o in outcomes)
    return {
        "outcomes": outcomes,
        "closed_total": total,
        "won": won,
        "win_rate_pct": round(100.0 * won / total, 1) if total else 0.0,
    }


# ── Finanse (Decimal; pełna poprawność FX = plan PR 6) ──────────────────────


async def _active_contracts(
    db: AsyncSession, *, client_id: int | None = None, on: date | None = None
):
    """Kontrakty aktywne NA DZIEŃ ``on`` (domyślnie dziś).

    ``on`` czyni to zapytanie point-in-time (M7-P0.4): dla historycznego okresu
    zwraca kontrakty aktywne na koniec tamtego okresu, nie stan bieżący.
    """
    on = on or date.today()
    stmt = (
        select(Contract)
        .where(
            Contract.status != ContractStatus.draft,
            Contract.start_date.isnot(None),
            Contract.start_date <= on,
            (Contract.end_date.is_(None)) | (Contract.end_date >= on),
        )
        .options(
            selectinload(Contract.candidate_rate_schedule),
            selectinload(Contract.client_rate_schedule),
            selectinload(Contract.framework_rate_schedule),
        )
    )
    if client_id is not None:
        stmt = stmt.where(Contract.client_id == client_id)
    return (await db.execute(stmt)).scalars().all()


async def _fx_rates_to_pln(
    db: AsyncSession, currencies: set[str], on: date
) -> dict[str, Decimal | None]:
    """Kurs raportowy → PLN per waluta: najnowszy kurs ≤ ``on`` z fx_rates.

    Brak kursu = None — NIGDY nominalne 1:1 (plan §3.4/PR 6). Świadomie NIE
    używamy fx_service.convert_to_pln, bo tamten degraduje do 1:1.
    """
    from app.models.fx_rate import FxRate

    out: dict[str, Decimal | None] = {}
    for cur in currencies:
        if cur == "PLN":
            out[cur] = Decimal("1")
            continue
        row = (
            await db.execute(
                select(FxRate.rate_to_pln)
                .where(FxRate.currency == cur, FxRate.effective_date <= on)
                .order_by(FxRate.effective_date.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        out[cur] = Decimal(row) if row is not None else None
    return out


async def _sum_finance(
    db: AsyncSession, contracts, *, on: date | None = None
) -> tuple[dict[str, Any], list[str], QualityFlag]:
    """Suma MRR/marży w PLN (Decimal) z obowiązkową konwersją FX.

    Zwraca (data, warnings, flag): flag == "unavailable" gdy jakikolwiek
    kontrakt w walucie bez kursu raportowego (plan PR 6 pkt 3) — bez kursu
    kwota NIE wchodzi do sumy i suma NIE udaje kompletnej.
    """
    on = on or date.today()
    currencies = {(c.currency or "PLN").upper() for c in contracts}
    rates = await _fx_rates_to_pln(db, currencies, on)

    mrr = Decimal("0")
    margin = Decimal("0")
    missing: dict[str, int] = {}
    warnings: list[str] = []
    for c in contracts:
        cur = (c.currency or "PLN").upper()
        rate = rates.get(cur)
        if rate is None:
            missing[cur] = missing.get(cur, 0) + 1
            continue
        if c.monthly_rate_client is not None:
            mrr += Decimal(c.monthly_rate_client) * rate
        if c.monthly_margin is not None:
            margin += Decimal(c.monthly_margin) * rate

    flag: QualityFlag = "complete"
    if missing:
        flag = "unavailable"
        details = ", ".join(f"{cur} ({n})" for cur, n in sorted(missing.items()))
        warnings.append(
            f"Brak kursu NBP dla walut: {details} — kwoty NIEDOSTĘPNE "
            "(uzupełnij fx_rates: POST /api/fx/refresh)"
        )
    foreign = [c for c in currencies if c != "PLN" and rates.get(c) is not None]
    if foreign:
        warnings.append(
            "Konwersja po kursie raportowym NBP (najnowszy ≤ "
            f"{on.isoformat()}): {', '.join(sorted(foreign))}"
        )

    data = {
        "mrr": _dec(mrr),
        "monthly_margin": _dec(margin),
        "margin_pct": (
            str((margin / mrr * 100).quantize(Decimal("0.1"))) if mrr else None
        ),
        "currency": "PLN",
        "active_contracts": len(contracts),
    }
    return data, warnings, flag


async def _bench_and_utilization(
    db: AsyncSession, *, on: date | None = None
) -> dict[str, Any]:
    """Bench = kandydat MIAŁ kontrakt, ale na dzień ``on`` nie ma aktywnego.

    Utilization = aktywni / (aktywni + bench) — mianownik to populacja
    konsultantów (ktokolwiek na kontrakcie do dnia ``on``), nie cała baza.
    ``on`` domyślnie dziś; przy okresie historycznym = koniec okresu (M7-P0.4).
    """
    on = on or date.today()
    active_cands = (
        await db.execute(
            select(func.count(distinct(Contract.candidate_id))).where(
                Contract.status != ContractStatus.draft,
                Contract.start_date.isnot(None),
                Contract.start_date <= on,
                (Contract.end_date.is_(None)) | (Contract.end_date >= on),
            )
        )
    ).scalar() or 0
    ever_cands = (
        await db.execute(
            select(func.count(distinct(Contract.candidate_id))).where(
                Contract.status != ContractStatus.draft,
                Contract.start_date.isnot(None),
                Contract.start_date <= on,
            )
        )
    ).scalar() or 0
    bench = max(0, ever_cands - active_cands)
    denominator = active_cands + bench
    return {
        "active_consultants": active_cands,
        "bench": bench,
        "utilization_pct": (
            round(100.0 * active_cands / denominator, 1) if denominator else None
        ),
    }


def finance_as_of(period: Period) -> date:
    """Data odniesienia point-in-time dla finansów danego okresu (M7-P0.4).

    Snapshot finansów „za okres" to stan na jego OSTATNI dzień, nigdy w
    przyszłości. Period jest półotwarty ``[start, end)``, więc ostatni objęty
    dzień = ``end - 1 dzień``; zawsze zaklamrowany do dziś. Dla bieżącego
    okresu (kind day/week/month/... zawsze rozwiązuje się do trwającego) wychodzi
    dziś = stan bieżący; dla zakresu historycznego (custom) = koniec zakresu.
    """
    last_day = (period.end - timedelta(days=1)).date()
    tz = period.start.tzinfo
    today = datetime.now(tz).date() if tz else date.today()
    return min(last_day, today)


async def finance_summary(
    db: AsyncSession, *, as_of: date | None = None
) -> tuple[dict[str, Any], list[str], "QualityFlag"]:
    """MRR/marża point-in-time na dzień ``as_of`` (domyślnie dziś), PLN + FX
    z kursu tej daty + bench/utilization na ten sam dzień (M7-P0.4)."""
    contracts = await _active_contracts(db, on=as_of)
    data, warnings, flag = await _sum_finance(db, contracts, on=as_of)
    data["consultants"] = await _bench_and_utilization(db, on=as_of)
    return data, warnings, flag


def _month_starts_back(n: int, *, today: date | None = None) -> list[date]:
    """Ostatnie n początków miesięcy (rosnąco) — prawdziwa arytmetyka
    kalendarza (28/29/30/31 dni), nie timedelta(30)."""
    today = today or date.today()
    y, m = today.year, today.month
    out: list[date] = []
    for _ in range(n):
        out.append(date(y, m, 1))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    return list(reversed(out))


async def finance_trend(
    db: AsyncSession, *, months: int = 12
) -> tuple[dict[str, Any], list[str], "QualityFlag"]:
    """Miesięczny trend MRR/marży: date-effective na 1. dzień każdego
    miesiąca, FX po kursie raportowym z tej daty."""
    month_starts = _month_starts_back(months)
    earliest = month_starts[0]
    stmt = (
        select(Contract)
        .where(
            Contract.status != ContractStatus.draft,
            Contract.start_date.isnot(None),
            Contract.start_date <= date.today(),
            (Contract.end_date.is_(None)) | (Contract.end_date >= earliest),
        )
        .options(
            selectinload(Contract.candidate_rate_schedule),
            selectinload(Contract.client_rate_schedule),
            selectinload(Contract.framework_rate_schedule),
        )
    )
    contracts = (await db.execute(stmt)).scalars().all()

    # Resolver legacy/live (plan PR 7): miesiące PRZED cutoverem modułu
    # 'finance' czytamy ze snapshotów DynaReportera (nieodtwarzalna
    # historia), od cutoveru — live ATS. NIGDY suma obu źródeł.
    from app.services.analytics_snapshots import (
        BOARD_MODULE,
        get_cutover,
        snapshot_for_month,
    )

    cutover = await get_cutover(db, BOARD_MODULE)

    points: list[dict[str, Any]] = []
    all_warnings: list[str] = []
    worst: QualityFlag = "complete"
    for month_start in month_starts:
        label = month_start.isoformat()[:7]
        if cutover is not None and month_start < cutover:
            snap = await snapshot_for_month(
                db, module=BOARD_MODULE, metric="board_monthly", period_label=label
            )
            if snap is None:
                worst = "partial" if worst == "complete" else worst
                all_warnings.append(
                    f"Brak snapshotu legacy dla {label} (miesiąc przed cutoverem)"
                )
                points.append(
                    {
                        "month": label,
                        "source": "legacy",
                        "mrr": None,
                        "monthly_margin": None,
                        "active_contracts": None,
                    }
                )
                continue
            revenue = Decimal(snap.get("revenue", "0"))
            costs = Decimal(snap.get("consultant_costs", "0")) + Decimal(
                snap.get("other_costs", "0")
            )
            points.append(
                {
                    "month": label,
                    "source": "legacy",
                    # Miesięczny przychód traktujemy jak MRR (kontrakt board).
                    "mrr": _dec(revenue),
                    "monthly_margin": _dec(revenue - costs),
                    "active_contracts": snap.get("active_consultants"),
                }
            )
            continue

        active = [
            c
            for c in contracts
            if c.start_date is not None
            and c.start_date <= month_start
            and (c.end_date is None or c.end_date >= month_start)
        ]
        data, warnings, flag = await _sum_finance(db, active, on=month_start)
        if flag == "unavailable":
            worst = "unavailable"
        points.append(
            {
                "month": label,
                "source": "live",
                "mrr": data["mrr"],
                "monthly_margin": data["monthly_margin"],
                "active_contracts": data["active_contracts"],
            }
        )
        for w in warnings:
            if w not in all_warnings:
                all_warnings.append(w)
    return {"months": points, "currency": "PLN"}, all_warnings, worst


async def finance_clients(
    db: AsyncSession, *, limit: int = 20, as_of: date | None = None
) -> tuple[dict[str, Any], list[str], "QualityFlag"]:
    """Per-klient MRR/marża point-in-time na ``as_of`` (domyślnie dziś), FX, top
    wg MRR (M7-P0.4)."""
    contracts = await _active_contracts(db, on=as_of)
    by_client: dict[int, list] = {}
    for c in contracts:
        by_client.setdefault(c.client_id, []).append(c)

    client_names = {
        r.id: r.name
        for r in (
            await db.execute(
                select(Client.id, Client.name).where(
                    Client.id.in_(list(by_client.keys()) or [0])
                )
            )
        ).all()
    }

    rows: list[dict[str, Any]] = []
    all_warnings: list[str] = []
    worst: QualityFlag = "complete"
    for client_id, cs in by_client.items():
        data, warnings, flag = await _sum_finance(db, cs, on=as_of)
        if flag == "unavailable":
            worst = "unavailable"
        rows.append(
            {
                "client_id": client_id,
                "client_name": client_names.get(client_id, f"#{client_id}"),
                "mrr": data["mrr"],
                "monthly_margin": data["monthly_margin"],
                "active_contracts": data["active_contracts"],
            }
        )
        for w in warnings:
            if w not in all_warnings:
                all_warnings.append(w)
    rows.sort(key=lambda r: Decimal(r["mrr"] or "0"), reverse=True)
    return {"clients": rows[:limit]}, all_warnings, worst


async def client_operations(
    db: AsyncSession, period: Period, client_id: int
) -> dict[str, Any]:
    """Operacyjny widok klienta — bez kwot (TAC/HoR-safe)."""
    today = date.today()
    open_jobs = (
        await db.execute(
            select(func.count(Job.id)).where(
                Job.client_id == client_id, Job.status == JobStatus.published
            )
        )
    ).scalar()
    active = (
        await db.execute(
            select(func.count(Contract.id)).where(
                Contract.client_id == client_id,
                Contract.status != ContractStatus.draft,
                Contract.start_date.isnot(None),
                Contract.start_date <= today,
                (Contract.end_date.is_(None)) | (Contract.end_date >= today),
            )
        )
    ).scalar()
    placements = (
        await db.execute(
            text(
                "SELECT COUNT(*) FROM analytics_first_milestones fm "
                "JOIN jobs j ON j.id = fm.job_id "
                "WHERE j.client_id = :cid AND fm.stage = 'hired' "
                "AND fm.first_reached_at >= :start AND fm.first_reached_at < :end"
            ),
            {"cid": client_id, "start": period.start, "end": period.end},
        )
    ).scalar()
    return {
        "open_jobs": open_jobs or 0,
        "active_consultants": active or 0,
        "placements_in_period": placements or 0,
    }


async def client_finance(
    db: AsyncSession, client_id: int, *, as_of: date | None = None
) -> tuple[dict[str, Any], list[str], "QualityFlag"]:
    contracts = await _active_contracts(db, client_id=client_id, on=as_of)
    return await _sum_finance(db, contracts, on=as_of)


# ── /meta/metrics — rejestr definicji ────────────────────────────────────────

METRIC_DEFINITIONS: list[dict[str, str]] = [
    {
        "name": "current_pipeline",
        "definition": "Ostatni CandidateStage per kandydat × job (view analytics_current_pipeline)",
        "unit": "count",
        "source": "live_ats",
    },
    {
        "name": "first_milestone",
        "definition": "Pierwsze osiągnięcie stage'a (verified/cv_sent/interview/client_interview/hired) per kandydat × job; atrybucja = moved_by pierwszego przejścia",
        "unit": "count",
        "source": "live_ats",
    },
    {
        "name": "completed_call",
        "definition": "Call.status = completed; data = COALESCE(started_at, created_at)",
        "unit": "count",
        "source": "cloudtalk",
    },
    {
        "name": "first_touch_source",
        "definition": "Pierwszy CandidateSourceEvent per kandydat; licznik i mianownik = distinct candidates",
        "unit": "count",
        "source": "live_ats",
    },
    {
        "name": "active_contract",
        "definition": "Date-effective: start_date <= dziś < end_date (NULL = bezterminowy), status ≠ draft",
        "unit": "count",
        "source": "live_ats",
    },
    {
        "name": "tender_outcome",
        "definition": "Job.close_reason zamkniętych rekrutacji; NULL = unknown",
        "unit": "count",
        "source": "live_ats",
    },
    {
        "name": "mrr",
        "definition": "Suma monthly_rate_client aktywnych (date-effective) kontraktów; Decimal, PLN; waluty obce wymagają kursu (PR 6)",
        "unit": "PLN",
        "source": "live_ats",
    },
]
