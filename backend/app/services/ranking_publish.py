"""Pomiar szkicu w tle, publikacja i „Przywróć” (panel „Ranking kandydatów”).

Decyzja Artura D1 (21.10.2026): Head of Recruitment publikuje sam, ale
dopiero po pomiarze na historii. Publikacja wymaga ukończonego pomiaru TEGO
szkicu przy TYCH opublikowanych wagach (``fingerprint``); gdy któraś miara
w punktach procentowych spada o więcej niż 2 pkt — także powodu.

Pomiar biegnie w procesie web (jeden naraz). Wdrożenie zabija go w trakcie:
wiersz bez znaku życia od ``STALE_AFTER`` czyta się jako przerwany, a nowy
pomiar można uruchomić od razu.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select

from app.models.app_setting import AppSetting
from app.models.scoring_weight_change import ScoringWeightMeasurement
from app.models.scoring_weight_profile import ScoringWeightProfile
from app.services import ranking_lab
from app.services import ranking_weights as rw
from app.services.match_score_cache import mark_stale_for_profile
from app.services.scoring_service import WeightProfile, scoring_algorithm_version

logger = logging.getLogger(__name__)

STALE_AFTER = timedelta(minutes=5)
MIN_REASON = 10
_lock = asyncio.Lock()


class PanelError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def current_baseline(db) -> dict:
    panel, profile, row = await rw.published_panel(db)
    return {
        "panel": panel.as_dict(),
        "threshold": panel.threshold,
        "weights": {name: round(getattr(profile, name), 4) for name in rw.BASE_LAYERS},
        "profile_id": row.id if row is not None else None,
    }


def fingerprint(baseline: dict, draft: dict) -> str:
    payload = {
        "weights": baseline["weights"],
        "threshold": baseline["threshold"],
        "draft": draft,
        # Zmiana silnika między pomiarem a publikacją unieważnia pomiar.
        "engine": scoring_algorithm_version(),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:32]


def _last_sign_of_life(row: ScoringWeightMeasurement) -> datetime:
    beat = (row.progress or {}).get("at")
    if beat:
        try:
            return datetime.fromisoformat(beat)
        except ValueError:
            pass
    return row.started_at or row.created_at


def is_stale(row: ScoringWeightMeasurement) -> bool:
    return row.status in ("queued", "running") and (
        _now() - _last_sign_of_life(row) > STALE_AFTER
    )


async def latest(db) -> Optional[ScoringWeightMeasurement]:
    return await db.scalar(
        select(ScoringWeightMeasurement)
        .order_by(ScoringWeightMeasurement.id.desc())
        .limit(1)
    )


async def current_fingerprint(db) -> Optional[str]:
    draft = await rw.read_draft(db)
    if draft is None:
        return None
    return fingerprint(await current_baseline(db), draft["panel"].as_dict())


def present(
    row: Optional[ScoringWeightMeasurement], current: Optional[str]
) -> Optional[dict]:
    if row is None:
        return None
    stale = is_stale(row)
    return {
        "id": row.id,
        "status": "failed" if stale else row.status,
        "error": (
            "Pomiar przerwany (np. wdrożeniem nowej wersji) — uruchom go ponownie."
            if stale
            else row.error
        ),
        "progress": row.progress,
        "result": row.result,
        "draft": row.draft,
        "baseline": row.baseline,
        "fresh": current is not None and row.fingerprint == current,
        "created_at": row.created_at,
        "finished_at": row.finished_at,
    }


async def measurement_state(db) -> Optional[dict]:
    return present(await latest(db), await current_fingerprint(db))


async def start(db, *, actor_id: int) -> ScoringWeightMeasurement:
    draft = await rw.read_draft(db)
    if draft is None:
        raise PanelError(409, "Najpierw zmień wagi — nie ma szkicu do sprawdzenia.")
    row = await latest(db)
    if row is not None and row.status in ("queued", "running") and not is_stale(row):
        raise PanelError(409, "Pomiar już trwa — poczekaj na wynik.")
    baseline = await current_baseline(db)
    draft_values = draft["panel"].as_dict()
    row = ScoringWeightMeasurement(
        status="queued",
        requested_by=actor_id,
        baseline=baseline,
        draft=draft_values,
        fingerprint=fingerprint(baseline, draft_values),
        progress={
            "done": 0,
            "target": ranking_lab.MEASURE_JOBS,
            "at": _now().isoformat(),
        },
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    _schedule(row.id)
    return row


def _schedule(measurement_id: int) -> None:
    from app.core.tasks import spawn

    spawn(run(measurement_id), f"ranking_measurement:{measurement_id}")


async def _update(measurement_id: int, **values) -> None:
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        row = await db.get(ScoringWeightMeasurement, measurement_id)
        if row is None:
            return
        for key, value in values.items():
            setattr(row, key, value)
        await db.commit()


async def run(measurement_id: int) -> None:
    from app.core.database import AsyncSessionLocal

    async with _lock:
        async with AsyncSessionLocal() as db:
            row = await db.get(ScoringWeightMeasurement, measurement_id)
            if row is None or row.status != "queued":
                return
            baseline, draft = dict(row.baseline), dict(row.draft)
        await _update(measurement_id, status="running", started_at=_now())

        async def progress(done: int, target: int) -> None:
            await _update(
                measurement_id,
                progress={"done": done, "target": target, "at": _now().isoformat()},
            )

        try:
            result = await ranking_lab.measure(
                baseline["weights"],
                float(baseline["threshold"]),
                rw.PanelWeights.from_dict(draft),
                progress=progress,
            )
        except Exception:  # noqa: BLE001 — błąd trafia do wiersza i do logu
            logger.exception("ranking measurement %s failed", measurement_id)
            await _update(
                measurement_id,
                status="failed",
                error="Pomiar nie powiódł się. Spróbuj ponownie za chwilę.",
                finished_at=_now(),
            )
            return
        if not result["jobs"]:
            await _update(
                measurement_id,
                status="failed",
                error="Nie znalazłem zamkniętych rekrutacji do pomiaru.",
                finished_at=_now(),
            )
            return
        await _update(measurement_id, status="done", result=result, finished_at=_now())


async def publish(db, *, actor_id: int, reason: Optional[str]) -> None:
    # Blokada wiersza szkicu: druga równoczesna publikacja czeka i dostaje
    # 409 („nie ma szkicu”) zamiast drugiego profilu albo skasowania szkicu,
    # który ktoś zapisał w międzyczasie.
    await db.get(AppSetting, rw.DRAFT_KEY, with_for_update=True)
    draft = await rw.read_draft(db)
    if draft is None:
        raise PanelError(409, "Nie ma szkicu do opublikowania.")
    panel = draft["panel"]
    baseline = await current_baseline(db)
    current = fingerprint(baseline, panel.as_dict())
    row = await latest(db)
    if (
        row is None
        or row.status != "done"
        or row.fingerprint != current
        or not row.result
    ):
        raise PanelError(
            409,
            "Najpierw sprawdź ten szkic na historii — publikacja wymaga "
            "aktualnego pomiaru.",
        )
    reason = (reason or "").strip() or None
    if row.result.get("needs_reason") and (reason is None or len(reason) < MIN_REASON):
        raise PanelError(
            422,
            "Któraś miara spada o więcej niż 2 pkt — wpisz powód zmiany "
            f"(co najmniej {MIN_REASON} znaków).",
        )

    profile = await rw.published_profile_row(db)
    before = {
        "panel": baseline["panel"],
        "threshold": baseline["threshold"],
        "weights": dict(profile.weights or {}) if profile is not None else None,
    }
    weights = rw.engine_weights(panel)
    if profile is None:
        profile = await db.scalar(
            select(ScoringWeightProfile).where(
                ScoringWeightProfile.name == rw.PUBLISHED_PROFILE_NAME
            )
        )
        if profile is None:
            profile = ScoringWeightProfile(
                name=rw.PUBLISHED_PROFILE_NAME, weights=weights, active=True
            )
            db.add(profile)
            await db.flush()
        profile.user_id = None
        profile.client_id = None
        profile.active = True
    profile.weights = weights
    profile.updated_at = _now()
    await mark_stale_for_profile(db, profile.id)

    setting = await db.get(AppSetting, rw.THRESHOLD_KEY)
    if setting is None:
        db.add(
            AppSetting(
                key=rw.THRESHOLD_KEY,
                value={"value": panel.threshold},
                updated_by=actor_id,
            )
        )
    else:
        setting.value = {"value": panel.threshold}
        setting.updated_by = actor_id

    result = row.result
    await rw.record_change(
        db,
        kind="publish",
        actor_id=actor_id,
        profile_id=profile.id,
        before=before,
        after={
            "panel": panel.as_dict(),
            "threshold": panel.threshold,
            "weights": weights,
        },
        reason=reason,
        measurement={
            "id": row.id,
            "jobs": result.get("jobs"),
            "before": result.get("before"),
            "after": result.get("after"),
            "max_drop_pt": result.get("max_drop_pt"),
        },
    )
    await rw.discard_draft(db)
    await db.commit()


def is_global_snapshot(snapshot: dict) -> bool:
    """Stan profilu z edycji admina, który działał jako wagi ogólne (D3:
    profile klienta i osoby nie przechodzą do szkicu wag ogólnych)."""
    return (
        snapshot.get("user_id") is None
        and snapshot.get("client_id") is None
        and snapshot.get("active", True) is True
    )


async def restore(db, change_id: int, *, actor_id: int) -> None:
    """„Przywróć” = nowy szkic z wagami, które wprowadziła ta zmiana."""
    from app.models.scoring_weight_change import ScoringWeightChange

    change = await db.get(ScoringWeightChange, change_id)
    if change is None:
        raise PanelError(404, "Nie ma takiej zmiany w historii.")
    after = change.after or {}
    published, _, _ = await rw.published_panel(db)
    if after.get("panel"):
        panel = rw.PanelWeights.from_dict(
            {**after["panel"], "threshold": after.get("threshold", published.threshold)}
        )
    elif after.get("weights") and is_global_snapshot(after):
        known = {
            name: float(after["weights"][name])
            for name in (*rw.BASE_LAYERS, "champion_fit")
            if name in after["weights"]
        }
        panel = rw.panel_from_profile(WeightProfile(**known), published.threshold)
    else:
        raise PanelError(
            422,
            "Tej zmiany nie da się przywrócić — dotyczyła profilu klienta albo osoby, "
            "nieaktywnego profilu albo usunięcia profilu.",
        )
    error = rw.validation_error(panel)
    if error:
        raise PanelError(422, error)
    await rw.save_draft(db, panel, actor_id=actor_id, restored_from=change.id)
    await db.commit()
