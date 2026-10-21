"""Wagi rankingu „Dop.” z panelu „Ranking kandydatów” (decyzje Artura 21.10.2026).

Head of Recruitment ustawia trzy WAŻNOŚCI (podobieństwo CV, umiejętności,
lokalizacja) i próg nocnych propozycji. Stawka i dostępność są zablokowane
(D2): stawka od 30.09 daje każdemu tyle samo, dostępność ma 0 od 17.08. Wagi
są tylko ogólne (D3) — profile klienta i osoby zostają przy starych trasach
administratora.

Ważności nie muszą sumować się do 100: udział warstwy w „Dop.” to jej ważność
przez sumę ważności z wagą stawki (``FIXED_SALARY``), dokładnie tak, jak liczy
``request_matching_context.base_fit_profile``. Do bazy idzie globalny profil
(``user_id``/``client_id`` puste) o wagach rozpisanych na 90 pkt + 10 pkt
warstwy screeningu, której ``base_fit_profile`` nie czyta — wbudowane
60/10/15/5/0/10 to ważności 60/10/5 bez żadnej zmiany wyniku.

Szkic i próg leżą w ``app_settings``; próg ma fallback na
``AUTO_FULL_REVIEW_MIN_SCORE`` z env.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional

from sqlalchemy import select

from app.core.config import settings
from app.models.app_setting import AppSetting
from app.models.scoring_weight_change import ScoringWeightChange
from app.models.scoring_weight_profile import ScoringWeightProfile
from app.models.user import User
from app.services.scoring_service import DEFAULT_PROFILE, WeightProfile

EDITABLE: tuple[str, ...] = ("semantic", "skills", "location")
BASE_LAYERS: tuple[str, ...] = (
    "semantic",
    "skills",
    "salary",
    "location",
    "availability",
)
# Ważność stawki w skali panelu — kotwica przeliczenia (D2: zablokowana).
FIXED_SALARY = 15
FIXED_AVAILABILITY = 0
# Warstwa screeningu w profilu: ``base_fit_profile`` ją zeruje, ale stare
# ścieżki z pełnym profilem oczekują sumy 100 — zostaje jak we wbudowanych.
CHAMPION_RESERVE = 10.0
BASE_BUDGET = 100.0 - CHAMPION_RESERVE

THRESHOLD_KEY = "auto_full_review_min_score"
DRAFT_KEY = "ranking_weights_draft"
THRESHOLD_MIN = 50
THRESHOLD_MAX = 90
PUBLISHED_PROFILE_NAME = "Wagi ogólne (panel)"


@dataclass(frozen=True)
class PanelWeights:
    semantic: int
    skills: int
    location: int
    threshold: int

    def as_dict(self) -> dict:
        return asdict(self)

    def same_as(self, other: "PanelWeights") -> bool:
        return self.as_dict() == other.as_dict()

    @classmethod
    def from_dict(cls, data: dict) -> "PanelWeights":
        return cls(
            semantic=int(data["semantic"]),
            skills=int(data["skills"]),
            location=int(data["location"]),
            threshold=int(data["threshold"]),
        )


def validation_error(panel: PanelWeights) -> Optional[str]:
    """Komunikat po polsku albo ``None``. Zakresy jak suwaki panelu."""
    for name in EDITABLE:
        value = getattr(panel, name)
        if not 0 <= value <= 100:
            return "Ważność ustawia się od 0 do 100."
    if panel.semantic + panel.skills + panel.location <= 0:
        return (
            "Ustaw co najmniej jedną ważność większą od zera — inaczej wszyscy "
            "mieliby ten sam wynik."
        )
    if not THRESHOLD_MIN <= panel.threshold <= THRESHOLD_MAX:
        return f"Próg nocnych propozycji ustawia się od {THRESHOLD_MIN} do {THRESHOLD_MAX}%."
    return None


def engine_weights(panel: PanelWeights) -> dict[str, float]:
    """Wagi profilu w bazie: pięć warstw na ``BASE_BUDGET`` + screening."""
    importance = {
        "semantic": panel.semantic,
        "skills": panel.skills,
        "location": panel.location,
        "salary": FIXED_SALARY,
        "availability": FIXED_AVAILABILITY,
    }
    total = sum(importance.values())
    scale = BASE_BUDGET / total
    weights = {name: round(value * scale, 4) for name, value in importance.items()}
    weights["champion_fit"] = CHAMPION_RESERVE
    return weights


def profile_shares(profile: WeightProfile) -> dict[str, float]:
    """Udział każdej warstwy w „Dop.” (%), jak ``base_fit_profile``."""
    total = sum(getattr(profile, name) for name in BASE_LAYERS)
    if total <= 0:
        return {name: 0.0 for name in BASE_LAYERS}
    return {
        name: round(getattr(profile, name) * 100.0 / total, 2) for name in BASE_LAYERS
    }


def panel_shares(panel: PanelWeights) -> dict[str, float]:
    weights = engine_weights(panel)
    return profile_shares(WeightProfile(**weights))


def panel_from_profile(profile: WeightProfile, threshold: int) -> PanelWeights:
    """Ważności panelu z wag profilu (stawka = kotwica ``FIXED_SALARY``)."""
    base = sum(getattr(profile, name) for name in BASE_LAYERS)
    anchor = profile.salary if profile.salary > 0 else base / 100.0 * FIXED_SALARY

    def value(name: str) -> int:
        if anchor <= 0:
            return 0
        raw = getattr(profile, name) * FIXED_SALARY / anchor
        return max(0, min(100, int(round(raw))))

    return PanelWeights(
        semantic=value("semantic"),
        skills=value("skills"),
        location=value("location"),
        threshold=threshold,
    )


async def published_profile_row(db) -> Optional[ScoringWeightProfile]:
    """Aktywny profil ogólny, który wybiera ``resolve_active_profile``."""
    return await db.scalar(
        select(ScoringWeightProfile)
        .where(ScoringWeightProfile.active.is_(True))
        .where(ScoringWeightProfile.user_id.is_(None))
        .where(ScoringWeightProfile.client_id.is_(None))
        .order_by(ScoringWeightProfile.id.desc())
        .limit(1)
    )


def _env_threshold() -> float:
    return float(settings.AUTO_FULL_REVIEW_MIN_SCORE)


async def nightly_min_score(db) -> float:
    """Próg nocnych propozycji: zapis z panelu, a bez niego env."""
    row = await db.get(AppSetting, THRESHOLD_KEY)
    if row is not None and isinstance(row.value, dict):
        value = row.value.get("value")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return _env_threshold()


async def published_panel(
    db,
) -> tuple[PanelWeights, WeightProfile, Optional[ScoringWeightProfile]]:
    row = await published_profile_row(db)
    profile = WeightProfile.from_record(row) if row is not None else DEFAULT_PROFILE
    threshold = int(round(await nightly_min_score(db)))
    return panel_from_profile(profile, threshold), profile, row


async def read_draft(db) -> Optional[dict]:
    row = await db.get(AppSetting, DRAFT_KEY)
    if row is None or not isinstance(row.value, dict):
        return None
    try:
        panel = PanelWeights.from_dict(row.value.get("panel") or {})
    except (KeyError, TypeError, ValueError):
        return None
    return {
        "panel": panel,
        "updated_by": row.updated_by,
        "updated_at": row.updated_at,
        "restored_from": row.value.get("restored_from"),
    }


async def save_draft(
    db, panel: PanelWeights, *, actor_id: int, restored_from: Optional[int] = None
) -> bool:
    """Zapisuje szkic. Szkic równy opublikowanym = brak szkicu (``False``)."""
    published, _, _ = await published_panel(db)
    row = await db.get(AppSetting, DRAFT_KEY)
    if panel.same_as(published):
        if row is not None:
            await db.delete(row)
        return False
    value = {"panel": panel.as_dict(), "restored_from": restored_from}
    if row is None:
        db.add(AppSetting(key=DRAFT_KEY, value=value, updated_by=actor_id))
    else:
        row.value = value
        row.updated_by = actor_id
    return True


async def discard_draft(db) -> None:
    row = await db.get(AppSetting, DRAFT_KEY)
    if row is not None:
        await db.delete(row)


def profile_snapshot(row: Optional[ScoringWeightProfile]) -> dict:
    if row is None:
        return {"profile_id": None, "weights": None}
    return {"profile_id": row.id, "name": row.name, "weights": dict(row.weights or {})}


async def record_change(
    db,
    *,
    kind: str,
    actor_id: Optional[int],
    profile_id: Optional[int],
    before: dict,
    after: dict,
    reason: Optional[str] = None,
    measurement: Optional[dict] = None,
) -> ScoringWeightChange:
    change = ScoringWeightChange(
        kind=kind,
        actor_id=actor_id,
        profile_id=profile_id,
        before=before,
        after=after,
        reason=reason,
        measurement=measurement,
    )
    db.add(change)
    return change


async def history(db, *, limit: int = 50) -> list[dict]:
    rows = (
        await db.execute(
            select(ScoringWeightChange, User.name)
            .outerjoin(User, User.id == ScoringWeightChange.actor_id)
            .order_by(
                ScoringWeightChange.created_at.desc(), ScoringWeightChange.id.desc()
            )
            .limit(limit)
        )
    ).all()
    return [
        {
            "id": change.id,
            "created_at": change.created_at,
            "kind": change.kind,
            "actor_name": actor_name,
            "profile_id": change.profile_id,
            "before": change.before,
            "after": change.after,
            "reason": change.reason,
            "measurement": change.measurement,
        }
        for change, actor_name in rows
    ]


async def scoped_profiles(db) -> list[dict]:
    """Aktywne profile klienta albo osoby — wygrywają z wagami ogólnymi (D3)."""
    rows = (
        await db.execute(
            select(ScoringWeightProfile)
            .where(ScoringWeightProfile.active.is_(True))
            .where(
                ScoringWeightProfile.user_id.is_not(None)
                | ScoringWeightProfile.client_id.is_not(None)
            )
            .order_by(ScoringWeightProfile.name.asc())
        )
    ).scalars()
    return [
        {
            "id": row.id,
            "name": row.name,
            "client_id": row.client_id,
            "user_id": row.user_id,
        }
        for row in rows
    ]


async def panel_state(db) -> dict:
    published, profile, row = await published_panel(db)
    threshold_row = await db.get(AppSetting, THRESHOLD_KEY)
    draft = await read_draft(db)
    draft_payload = None
    if draft is not None:
        draft_name = (
            await db.scalar(select(User.name).where(User.id == draft["updated_by"]))
            if draft["updated_by"]
            else None
        )
        draft_payload = {
            "weights": draft["panel"].as_dict(),
            "shares": panel_shares(draft["panel"]),
            "updated_at": draft["updated_at"],
            "updated_by_name": draft_name,
            "restored_from": draft["restored_from"],
        }
    return {
        "published": {
            "weights": published.as_dict(),
            "shares": profile_shares(profile),
            "source": "profile" if row is not None else "built_in",
            "profile_id": row.id if row is not None else None,
            "updated_at": row.updated_at if row is not None else None,
            "threshold_source": "setting" if threshold_row is not None else "env",
        },
        "draft": draft_payload,
        "fixed": {"salary": FIXED_SALARY, "availability": FIXED_AVAILABILITY},
        "limits": {"threshold_min": THRESHOLD_MIN, "threshold_max": THRESHOLD_MAX},
        "scoped_profiles": await scoped_profiles(db),
        "history": await history(db),
    }
