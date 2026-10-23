"""„Jakość podpowiedzi systemu” — ekran i raport poniedziałkowy (23.10.2026).

Decyzja Artura: powody odrzuceń osób od silnika „Nowi na 20” zbieramy, żeby
poprawiać wyszukiwanie; co tydzień raport z propozycjami dla Artura i Edwina.
Makiety B2 i B3: https://claude.ai/artifact/6qyrJf65QmsQdJteLZWVT2.

Podział pracy:

* LICZBY liczy kod (``summary``): ile osób system dodał, ile dostało
  „Dzwonię”, ile odrzucono z jakim powodem i w jakim koszu
  (``autofill_feedback.bucket_for``), ile doszło do „Zweryfikowanego” na tle
  osób dodanych przez ludzi, ile czeka po terminie, które rekrutacje mają
  najwięcej błędów wyszukiwania;
* PROPOZYCJE układa model z tych liczb i opisów odrzuceń (``AUTOFILL_QUALITY_REPORT``,
  klucz ``autofill_quality_report``). Kod odrzuca propozycję bez tytułu albo
  z nieznanym koszem; gdy model milczy, raport idzie z propozycjami z reguł
  (``rule_proposals``) — raport nigdy nie zależy od modelu.

Raport: pierwszy dzień roboczy tygodnia, 8–17, za poprzedni tydzień
(poniedziałek–niedziela), jeden na tydzień (``uq_autofill_quality_reports_week``).
Odbiorcy: ``AUTOFILL_REPORT_RECIPIENT_EMAILS`` (aktywne konta), bez tego —
aktywni admini. Dzwonek tylko wtedy, gdy w tygodniu cokolwiek się działo.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import DateTime, func, select
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.scheduling import is_business_day
from app.models.autofill_feedback import AutofillFeedback
from app.models.autofill_quality_report import AutofillQualityReport
from app.models.job import Job, JobStatus
from app.models.notification import NotificationType
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.recruitment_process import RecruitmentProcess
from app.models.user import User, UserRole
from app.services import candidate_claim
from app.services.autofill_feedback import REASON_LABELS
from app.services.autofill_feedback_schema import BUCKETS
from app.services.request_work_state import IN_WORK_STATES

logger = logging.getLogger(__name__)

FROM_HOUR = 8
UNTIL_HOUR = 17
MAX_PROPOSALS = 5
MAX_NOTES = 30
NOTE_MAX = 300
WORST_JOBS = 5
WORST_JOB_MIN_FEEDBACK = 3
REPORT_LINK = "/insights/autofill"
_VERIFIED_OR_LATER = (
    PipelineStage.verified,
    PipelineStage.interview,
    PipelineStage.cv_sent,
    PipelineStage.client_interview,
    PipelineStage.acceptance,
    PipelineStage.negotiation,
    PipelineStage.onboarding,
    PipelineStage.hired,
)
_MANUAL_SOURCES = (candidate_claim.ENTRY_ADDED_MANUAL, candidate_claim.ENTRY_PROPOSAL)
BUCKET_LABELS = {
    "search": "Błąd wyszukiwania",
    "data": "Brak danych",
    "person": "Sprawa osoby",
    "other": "Inne",
}


def _tz() -> ZoneInfo:
    return ZoneInfo(settings.BUSINESS_TZ)


def _pct(part: int, whole: int) -> Optional[float]:
    return round(100.0 * part / whole, 1) if whole else None


# ── Liczby ──────────────────────────────────────────────────────────────────


async def _cohort(
    db, sources: tuple[str, ...], since: datetime, until: datetime
) -> dict:
    """Ile osób z danego wejścia weszło w oknie i ile doszło do „Zweryfikowanego”."""
    reached = (
        select(CandidateStage.id)
        .where(
            CandidateStage.job_id == RecruitmentProcess.job_id,
            CandidateStage.candidate_id == RecruitmentProcess.candidate_id,
            CandidateStage.stage.in_(_VERIFIED_OR_LATER),
        )
        .exists()
    )
    added, verified = (
        await db.execute(
            select(
                func.count(),
                func.count().filter(reached),
            ).where(
                RecruitmentProcess.entry_source.in_(sources),
                RecruitmentProcess.opened_at >= since,
                RecruitmentProcess.opened_at < until,
            )
        )
    ).one()
    return {
        "added": int(added),
        "verified": int(verified),
        "verified_pct": _pct(int(verified), int(added)),
    }


async def _waiting_now(db, now: datetime) -> int:
    from app.services.autofill_decisions import due_decisions

    job_ids = list(
        (
            await db.scalars(
                select(Job.id).where(
                    Job.status == JobStatus.published,
                    Job.work_state.in_(IN_WORK_STATES),
                )
            )
        ).all()
    )
    return len(await due_decisions(db, job_ids, now))


async def _worst_jobs(db, since: datetime, until: datetime) -> list[dict]:
    from app.services.job_working_title import job_display_title_expr

    rows = (
        await db.execute(
            select(
                AutofillFeedback.job_id,
                AutofillFeedback.bucket,
                AutofillFeedback.reason,
            ).where(
                AutofillFeedback.created_at >= since,
                AutofillFeedback.created_at < until,
            )
        )
    ).all()
    per_job: dict[int, dict[str, Any]] = {}
    for job_id, bucket, reason in rows:
        entry = per_job.setdefault(
            int(job_id), {"total": 0, "search": 0, "reasons": {}}
        )
        entry["total"] += 1
        if bucket == "search":
            entry["search"] += 1
            entry["reasons"][reason] = entry["reasons"].get(reason, 0) + 1
    ranked = sorted(
        (
            (job_id, e)
            for job_id, e in per_job.items()
            if e["total"] >= WORST_JOB_MIN_FEEDBACK and e["search"] > 0
        ),
        key=lambda kv: (-kv[1]["search"] / kv[1]["total"], -kv[1]["total"], kv[0]),
    )[:WORST_JOBS]
    if not ranked:
        return []
    titles = dict(
        (
            await db.execute(
                select(Job.id, job_display_title_expr()).where(
                    Job.id.in_([job_id for job_id, _ in ranked])
                )
            )
        ).all()
    )
    out = []
    for job_id, e in ranked:
        top = max(e["reasons"].items(), key=lambda kv: (kv[1], kv[0]))[0]
        out.append(
            {
                "job_id": job_id,
                "job_title": titles.get(job_id) or f"#{job_id}",
                "feedback": e["total"],
                "search_errors": e["search"],
                "search_pct": _pct(e["search"], e["total"]),
                "top_reason": top,
                "top_reason_label": REASON_LABELS.get(top, top),
            }
        )
    return out


async def summary(db, *, since: datetime, until: datetime, now: datetime) -> dict:
    """Liczby okna ``[since, until)`` — wszystko, co pokazuje ekran B2."""
    system = await _cohort(db, (candidate_claim.ENTRY_SYSTEM,), since, until)
    manual = await _cohort(db, _MANUAL_SOURCES, since, until)
    decided_at = RecruitmentProcess.entry_meta["decided_at"].astext.cast(
        DateTime(timezone=True)
    )
    called = int(
        await db.scalar(
            select(func.count()).where(
                RecruitmentProcess.entry_source == candidate_claim.ENTRY_SYSTEM,
                decided_at >= since,
                decided_at < until,
            )
        )
        or 0
    )
    counts = (
        await db.execute(
            select(AutofillFeedback.bucket, AutofillFeedback.reason, func.count())
            .where(
                AutofillFeedback.created_at >= since,
                AutofillFeedback.created_at < until,
            )
            .group_by(AutofillFeedback.bucket, AutofillFeedback.reason)
        )
    ).all()
    buckets: dict[str, dict[str, Any]] = {
        b: {"bucket": b, "label": BUCKET_LABELS[b], "total": 0, "reasons": []}
        for b in BUCKETS
    }
    rejected = 0
    for bucket, reason, n in counts:
        entry = buckets.setdefault(
            bucket, {"bucket": bucket, "label": bucket, "total": 0, "reasons": []}
        )
        entry["total"] += int(n)
        entry["reasons"].append(
            {
                "reason": reason,
                "label": REASON_LABELS.get(reason, reason),
                "count": int(n),
            }
        )
        rejected += int(n)
    for entry in buckets.values():
        entry["reasons"].sort(key=lambda r: (-r["count"], r["reason"]))
    return {
        "since": since.isoformat(),
        "until": until.isoformat(),
        "added": system["added"],
        "called": called,
        "rejected": rejected,
        "decided_pct": _pct(called + rejected, system["added"]),
        "called_pct": _pct(called, called + rejected),
        "search_error_pct": _pct(buckets["search"]["total"], rejected),
        "verified": {"system": system, "manual": manual},
        "waiting_now": await _waiting_now(db, now),
        "buckets": [buckets[b] for b in BUCKETS],
        "worst_jobs": await _worst_jobs(db, since, until),
    }


# ── Propozycje ──────────────────────────────────────────────────────────────

_RULE_FIX = {
    "missing_skill": "Sprawdzić, czy umiejętności krytyczne są oznaczone w Championie tych rekrutacji, i obniżać w puli osoby bez spełnionego „musi mieć”.",
    "too_junior": "Mocniej liczyć lata w roli z CV, gdy rekrutacja wymaga doświadczenia.",
    "other_level_or_role": "Uwzględnić w wyniku poziom (junior, mid, senior) i tytuł roli z CV.",
    "location_mode": "Pomijać w dopełnianiu osoby z lokalizacją albo trybem pracy sprzecznym z rekrutacją.",
    "language": "Dopisywać wymóg języka do wierszy Championa i sprawdzać go w CV.",
    "too_expensive": "Pomijać w dopełnianiu osoby ze znaną „Stawką od” powyżej budżetu +15% i pytać o stawkę na początku rozmowy.",
    "outdated_cv": "Prosić o świeże CV osoby, których CV ma ponad rok, zanim system je doda.",
    "profile_mismatch": "Poprawić profile w bazie, na które wskazali rekruterzy.",
    "not_looking": "Pomijać osoby odrzucone z „Nie szuka pracy” przez 90 dni w każdej rekrutacji.",
    "no_answer": "Nie dokładać ponownie osób, które trzy razy nie odebrały, przez 30 dni.",
    "in_other_process": "Pomijać w dopełnianiu osoby w toku w innej rekrutacji od „Zweryfikowanego”.",
}


def rule_proposals(data: dict) -> list[dict]:
    """Propozycje z reguł — gdy model milczy. Najczęstsze powody z koszy
    „Błąd wyszukiwania” i „Brak danych”, potem „Sprawa osoby”."""
    rejected = int(data.get("rejected") or 0)
    if not rejected:
        return []
    picks: list[tuple[str, dict]] = []
    for bucket in data.get("buckets") or []:
        take = 2 if bucket["bucket"] == "search" else 1
        for reason in bucket["reasons"][:take]:
            if reason["reason"] in _RULE_FIX:
                picks.append((bucket["bucket"], reason))
    out = []
    for kind, reason in picks[:MAX_PROPOSALS]:
        out.append(
            {
                "title": f"„{reason['label']}” — {reason['count']} odrzuceń",
                "kind": kind if kind in ("search", "data", "person") else "person",
                "evidence": (
                    f"{reason['count']} z {rejected} odrzuceń osób od systemu "
                    f"({_pct(reason['count'], rejected)}%)."
                ),
                "fix": _RULE_FIX[reason["reason"]],
                "decision": None,
            }
        )
    return out


def check_proposals(raw: str) -> list[dict]:
    """Odpowiedź modelu → propozycje; zła albo pusta = ``[]``."""
    from app.services.cv_qc import _json_object

    try:
        parsed = _json_object(raw)
    except Exception:  # noqa: BLE001
        return []
    out = []
    for item in (parsed or {}).get("proposals") or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()[:200]
        kind = item.get("kind")
        if not title or kind not in ("search", "data", "person"):
            continue
        out.append(
            {
                "title": title,
                "kind": kind,
                "evidence": str(item.get("evidence") or "").strip()[:600],
                "fix": str(item.get("fix") or "").strip()[:600],
                "decision": None,
            }
        )
    return out[:MAX_PROPOSALS]


async def _notes(db, since: datetime, until: datetime) -> list[str]:
    rows = (
        await db.execute(
            select(AutofillFeedback.reason, AutofillFeedback.note)
            .where(
                AutofillFeedback.created_at >= since,
                AutofillFeedback.created_at < until,
                AutofillFeedback.note.is_not(None),
            )
            .order_by(AutofillFeedback.created_at.desc())
            .limit(MAX_NOTES)
        )
    ).all()
    return [
        f"- {REASON_LABELS.get(reason, reason)}: {note.strip()[:NOTE_MAX]}"
        for reason, note in rows
        if note and note.strip()
    ]


def _call_model(system: str, prompt: str, chain: tuple[str, ...]) -> str:
    from app.services.claude_client import call_claude, text_of

    message = call_claude(
        model=chain[0],
        fallback_models=list(chain[1:]) or None,
        max_tokens=2000,
        thinking={"type": "disabled"},
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return text_of(message)


async def model_proposals(db, data: dict, notes: list[str]) -> list[dict]:
    """Propozycje z modelu; ``[]``, gdy model niedostępny albo odpowiedź zła."""
    from fastapi.concurrency import run_in_threadpool

    from app.models.ai_feature import AIFeatureKey
    from app.services.ai_models import model_chain_for
    from app.services.ai_quota import ai_feature
    from app.services.llm_prompts import AUTOFILL_QUALITY_REPORT
    from app.services.llm_providers import api_key_configured
    from app.services.prompt_fencing import fence

    feature = AIFeatureKey.autofill_quality_report
    chain = tuple(model_chain_for(feature))
    if not chain or not api_key_configured(chain[0]):
        return []
    numbers = {k: v for k, v in data.items() if k not in ("since", "until")}
    prompt = AUTOFILL_QUALITY_REPORT.render(
        summary=fence("summary", json.dumps(numbers, ensure_ascii=False)),
        notes=fence("notes", "\n".join(notes) or "(brak opisów)"),
    )
    try:
        async with ai_feature(db, feature):
            await db.commit()
            raw = await run_in_threadpool(
                _call_model, AUTOFILL_QUALITY_REPORT.system_prompt or "", prompt, chain
            )
    except Exception as exc:  # noqa: BLE001 — model to dodatek
        logger.warning("[autofill_quality] model failed: %s", type(exc).__name__)
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            logger.warning("[autofill_quality] rollback failed")
        return []
    return check_proposals(raw)


# ── Raport poniedziałkowy ───────────────────────────────────────────────────


def report_week(now: datetime) -> Optional[date]:
    """Poniedziałek tygodnia, za który trzeba dziś zrobić raport — albo ``None``.

    Raport robimy w pierwszym dniu roboczym tygodnia (poniedziałek, a po
    święcie — następny dzień roboczy), 8–17, za poprzedni tydzień.
    """
    local = now.astimezone(_tz())
    if not (FROM_HOUR <= local.hour < UNTIL_HOUR) or not is_business_day(local):
        return None
    monday = local.date() - timedelta(days=local.weekday())
    for offset in range(local.weekday()):
        day = monday + timedelta(days=offset)
        if is_business_day(datetime.combine(day, time(12), tzinfo=_tz())):
            return None
    return monday - timedelta(days=7)


async def _recipients(db) -> list[int]:
    emails = [
        e.strip().lower()
        for e in (
            getattr(settings, "AUTOFILL_REPORT_RECIPIENT_EMAILS", "") or ""
        ).split(",")
        if e.strip()
    ]
    query = select(User.id).where(User.is_active.is_(True))
    if emails:
        query = query.where(func.lower(User.email).in_(emails))
    else:
        query = query.where(User.role == UserRole.admin)
    return sorted(int(uid) for uid in (await db.scalars(query)).all())


async def build_report(db, *, week_start: date, now: datetime) -> AutofillQualityReport:
    """Liczby i propozycje za tydzień od ``week_start``. Bez commitu."""
    since = datetime.combine(week_start, time(0), tzinfo=_tz()).astimezone(timezone.utc)
    until = since + timedelta(days=7)
    data = await summary(db, since=since, until=until, now=now)
    proposals: list[dict] = []
    if data["rejected"]:
        proposals = await model_proposals(db, data, await _notes(db, since, until))
    from_model = bool(proposals)
    if not proposals:
        proposals = rule_proposals(data)
    report = AutofillQualityReport(
        week_start=week_start,
        summary=data,
        proposals=proposals,
        from_model=from_model,
    )
    db.add(report)
    await db.flush()
    return report


async def send_weekly_report(db, now: datetime) -> int:
    """Raport za poprzedni tydzień + dzwonki. Nie commituje — robi to wołający."""
    from app.services.notification_triggers import emit

    week_start = report_week(now)
    if week_start is None:
        return 0
    exists = await db.scalar(
        select(AutofillQualityReport.id).where(
            AutofillQualityReport.week_start == week_start
        )
    )
    if exists is not None:
        return 0
    try:
        async with db.begin_nested():
            report = await build_report(db, week_start=week_start, now=now)
    except IntegrityError:
        return 0  # drugi proces zrobił ten raport chwilę wcześniej
    except Exception:  # noqa: BLE001 — raport nigdy nie psuje ticku
        logger.exception("autofill_quality: nie udało się zrobić raportu")
        return 0
    data = report.summary
    if not (data.get("added") or data.get("rejected")):
        return 0
    end = week_start + timedelta(days=6)
    title = f"Jakość podpowiedzi systemu: raport {week_start:%d.%m}–{end:%d.%m}"
    message = (
        f"System dodał {data['added']} osób, odrzucono {data['rejected']}, "
        f"błąd wyszukiwania {data.get('search_error_pct') or 0}% odrzuceń. "
        f"{len(report.proposals)} propozycji poprawek — „Robimy” albo „Nie”."
    )
    sent = 0
    for user_id in await _recipients(db):
        try:
            async with db.begin_nested():
                created = await emit(
                    db,
                    user_id=user_id,
                    title=title[:255],
                    message=message,
                    ntype=NotificationType.autofill_quality_report,
                    related_entity_type="autofill_quality_report",
                    related_entity_id=report.id,
                    link=f"{REPORT_LINK}?report={report.id}",
                )
            sent += int(created is not None)
        except Exception:  # noqa: BLE001 — jeden odbiorca nie blokuje reszty
            logger.exception("autofill_quality: dzwonek nie wyszedł user=%s", user_id)
    return sent


__all__ = [
    "BUCKET_LABELS",
    "build_report",
    "check_proposals",
    "report_week",
    "rule_proposals",
    "send_weekly_report",
    "summary",
]
