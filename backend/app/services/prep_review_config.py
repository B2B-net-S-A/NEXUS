"""Ustawienia oceny prepów (0505, decyzje Artura 22.10.2026).

Head of Recruitment i admin ustawiają w Ustawienia → Ocena prepów, z czego
składa się ocena Prepu 1 i Prepu 2: wagi kryteriów, tematy prowadzącego,
skalę odpowiedzi kandydata, progi poziomu, reguły, co trafia do notatki na
Prep 2 i wskazówki dla AI. Rekruter i Delivery Lead widzą te same ustawienia
bez edycji (link „Jak liczone” przy ocenie).

Każda publikacja to nowy wiersz ``prep_review_configs`` — obowiązuje
najnowszy, starsze są historią. Ustawienia startowe odtwarzają ocenę sprzed
0505: progi z ``PREP_REVIEW_*`` w env i do 20 pytań klienta.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.prep_meeting import PrepReviewConfigVersion
from app.models.user import User

logger = logging.getLogger(__name__)

PREP1_CRITERIA: tuple[str, ...] = (
    "topics",
    "must_answers",
    "client_questions",
    "talk_share",
)
PREP2_CRITERIA: tuple[str, ...] = (
    "prep1_followup",
    "topics",
    "client_questions",
    "talk_share",
)
ANSWER_GRADES: tuple[str, ...] = ("strong", "general", "weak", "missing")
MAX_TOPICS = 12
HISTORY_LIMIT = 20

CRITERION_LABELS = {
    "topics": "Tematy prowadzącego",
    "must_answers": "Odpowiedzi kandydata na must-have",
    "client_questions": "Pytania tego klienta",
    "talk_share": "Kandydat mówi, prowadzący słucha",
    "prep1_followup": "Poprawa punktów z Prepu 1",
}
GRADE_LABELS = {
    "strong": "Mocna",
    "general": "Ogólna",
    "weak": "Słaba",
    "missing": "Nie było",
}


class Topic(BaseModel):
    label: str = Field(min_length=2, max_length=160)
    required: bool = True


class PrepRules(BaseModel):
    weights: dict[str, int]
    topics: list[Topic] = Field(max_length=MAX_TOPICS)


class AnswerGrade(BaseModel):
    description: str = Field(min_length=3, max_length=240)
    points: int = Field(ge=0, le=100)


class FollowupRules(BaseModel):
    """Co trafia do notatki rekrutera na Prep 2."""

    weak_answers: bool = True
    general_answers: bool = True
    missing_required_topics: bool = True
    unpracticed_client_questions: bool = True
    max_items: int = Field(default=5, ge=1, le=12)


class PrepReviewConfig(BaseModel):
    prep1: PrepRules
    prep2: PrepRules
    answer_scale: dict[str, AnswerGrade]
    max_client_questions: int = Field(ge=0, le=20)
    good_threshold: int = Field(ge=50, le=100)
    weak_threshold: int = Field(ge=10, le=90)
    min_minutes_enabled: bool = True
    min_minutes: int = Field(ge=0, le=60)
    talk_share_enabled: bool = True
    talk_share_target: int = Field(ge=10, le=90)
    required_topic_caps_ok: bool = True
    weak_must_caps_ok: bool = True
    followup: FollowupRules = Field(default_factory=FollowupRules)
    ai_hints: str = Field(default="", max_length=1500)

    @model_validator(mode="after")
    def _consistent(self) -> "PrepReviewConfig":
        for name, rules, criteria in (
            ("Prep 1", self.prep1, PREP1_CRITERIA),
            ("Prep 2", self.prep2, PREP2_CRITERIA),
        ):
            if set(rules.weights) != set(criteria):
                raise ValueError(f"{name}: nieznane albo brakujące kryteria oceny.")
            if any(not 0 <= w <= 100 for w in rules.weights.values()):
                raise ValueError(f"{name}: waga kryterium to liczba od 0 do 100.")
            if sum(rules.weights.values()) != 100:
                raise ValueError(f"{name}: wagi kryteriów muszą dawać razem 100%.")
            labels = [t.label.strip().casefold() for t in rules.topics]
            if len(labels) != len(set(labels)):
                raise ValueError(f"{name}: ten sam temat prowadzącego jest dwa razy.")
        if set(self.answer_scale) != set(ANSWER_GRADES):
            raise ValueError(
                "Skala odpowiedzi ma cztery stopnie: mocna, ogólna, słaba, nie było."
            )
        points = [self.answer_scale[g].points for g in ANSWER_GRADES]
        if points != sorted(points, reverse=True):
            raise ValueError(
                "Punkty skali nie mogą rosnąć: mocna ≥ ogólna ≥ słaba ≥ nie było."
            )
        if self.weak_threshold >= self.good_threshold:
            raise ValueError("Próg „słaby” musi być niższy niż próg „dobry”.")
        return self


def defaults() -> PrepReviewConfig:
    """Ustawienia startowe: progi z env, lista tematów z makiet (22.10.2026)."""
    return PrepReviewConfig(
        prep1=PrepRules(
            weights={
                "topics": 25,
                "must_answers": 40,
                "client_questions": 20,
                "talk_share": 15,
            },
            topics=[
                Topic(label="Klient i projekt: zespół, technologia, tryb pracy"),
                Topic(label="Przebieg rozmowy u klienta: kto, ile trwa, live coding"),
                Topic(label="Doświadczenie pod każdy must-have"),
                Topic(label="Stawka i dostępność"),
                Topic(label="Pytania kandydata do klienta", required=False),
            ],
        ),
        prep2=PrepRules(
            weights={
                "prep1_followup": 40,
                "topics": 25,
                "client_questions": 20,
                "talk_share": 15,
            },
            topics=[
                Topic(label="Punkty z notatki na Prep 2"),
                Topic(label="Powtórka pytań klienta"),
                Topic(label="Logistyka: link Teams, kamera, punktualność"),
                Topic(label="Motywacja i ostatnie wątpliwości", required=False),
            ],
        ),
        answer_scale={
            "strong": AnswerGrade(
                description="Konkretny projekt, własna rola („ja”), skala albo liczby",
                points=100,
            ),
            "general": AnswerGrade(
                description="Zna temat, ale bez przykładu albo mówi „my” zamiast „ja”",
                points=50,
            ),
            "weak": AnswerGrade(
                description="Nie umie odpowiedzieć, myli pojęcia albo zmienia temat",
                points=0,
            ),
            "missing": AnswerGrade(description="Temat nie padł na prepie", points=0),
        },
        max_client_questions=20,
        good_threshold=round(settings.PREP_REVIEW_GOOD_COVERAGE * 100),
        weak_threshold=round(settings.PREP_REVIEW_WEAK_COVERAGE * 100),
        min_minutes=int(settings.PREP_REVIEW_MIN_MINUTES),
        talk_share_target=round(settings.PREP_REVIEW_GOOD_TALK_SHARE * 100),
    )


def _from_row(row: PrepReviewConfigVersion) -> PrepReviewConfig:
    """Wersja z bazy na tle startowej — klucz dodany później ma wartość startową."""
    base = defaults().model_dump()
    return PrepReviewConfig.model_validate({**base, **(row.config or {})})


async def _latest(db: AsyncSession) -> Optional[PrepReviewConfigVersion]:
    return await db.scalar(
        select(PrepReviewConfigVersion)
        .order_by(PrepReviewConfigVersion.id.desc())
        .limit(1)
    )


async def current(db: AsyncSession) -> tuple[PrepReviewConfig, Optional[int]]:
    """Obowiązujące ustawienia i numer wersji (``None`` = startowe).

    Wersja, której nie da się odczytać (zmiana schematu bez migracji danych),
    nie zatrzymuje oceny prepu — wraca startowa, a log mówi, która wersja.
    """
    row = await _latest(db)
    if row is None:
        return defaults(), None
    try:
        return _from_row(row), row.id
    except ValidationError:
        logger.warning(
            "prep_review_config: version %s unreadable, using defaults", row.id
        )
        return defaults(), None


async def publish(
    db: AsyncSession,
    *,
    actor: User,
    config: PrepReviewConfig,
    reason: Optional[str],
) -> tuple[PrepReviewConfigVersion, bool]:
    """Nowa wersja. Te same ustawienia co obowiązujące = bez nowego wiersza.

    Zwraca ``(wiersz, czy_zapisano)``. Bez commitu.
    """
    latest = await _latest(db)
    payload = config.model_dump()
    if latest is not None and latest.config == payload:
        return latest, False
    row = PrepReviewConfigVersion(
        created_by=actor.id,
        config=payload,
        reason=(reason or "").strip() or None,
    )
    db.add(row)
    await db.flush()
    return row, True


def _scalar_changes(before: dict, after: dict) -> list[str]:
    labels = {
        "good_threshold": ("Dobry od", "%"),
        "weak_threshold": ("Słaby poniżej", "%"),
        "min_minutes": ("Minimalna długość prepu", " min"),
        "talk_share_target": ("Kandydat mówi co najmniej", "%"),
        "max_client_questions": ("Najwięcej pytań klienta", ""),
    }
    out = []
    for key, (label, unit) in labels.items():
        if before.get(key) != after.get(key):
            out.append(f"{label}: {before.get(key)}{unit} → {after.get(key)}{unit}")
    toggles = {
        "min_minutes_enabled": "Reguła minimalnej długości",
        "talk_share_enabled": "Kryterium udziału kandydata",
        "required_topic_caps_ok": "Pominięty temat obowiązkowy = najwyżej OK",
        "weak_must_caps_ok": "Słaba odpowiedź na must-have = najwyżej OK",
    }
    for key, label in toggles.items():
        if before.get(key) != after.get(key):
            out.append(f"{label}: {'włączone' if after.get(key) else 'wyłączone'}")
    return out


def describe_changes(before: Optional[dict], after: dict) -> list[str]:
    """Zdania do historii zmian: co się zmieniło między wersjami."""
    if before is None:
        before = defaults().model_dump()
    out = _scalar_changes(before, after)
    for key, name in (("prep1", "Prep 1"), ("prep2", "Prep 2")):
        b, a = before.get(key) or {}, after.get(key) or {}
        for crit, weight in (a.get("weights") or {}).items():
            old = (b.get("weights") or {}).get(crit)
            if old != weight:
                out.append(
                    f"{name} · {CRITERION_LABELS.get(crit, crit)}: {old}% → {weight}%"
                )
        if (b.get("topics") or []) != (a.get("topics") or []):
            out.append(f"{name} · tematy prowadzącego zmienione")
    if before.get("answer_scale") != after.get("answer_scale"):
        out.append("Skala odpowiedzi kandydata zmieniona")
    if before.get("followup") != after.get("followup"):
        out.append("Zmieniono, co trafia do notatki na Prep 2")
    if before.get("ai_hints") != after.get("ai_hints"):
        out.append("Zmieniono wskazówki dla AI")
    return out


async def history(db: AsyncSession, limit: int = HISTORY_LIMIT) -> list[dict]:
    """Ostatnie wersje od najnowszej, z opisem zmian względem poprzedniej."""
    rows = (
        await db.execute(
            select(PrepReviewConfigVersion, User.name)
            .outerjoin(User, User.id == PrepReviewConfigVersion.created_by)
            .order_by(PrepReviewConfigVersion.id.desc())
            .limit(limit + 1)
        )
    ).all()
    out: list[dict] = []
    for index, (row, author) in enumerate(rows[:limit]):
        previous = rows[index + 1][0].config if index + 1 < len(rows) else None
        out.append(
            {
                "version": row.id,
                "created_at": _iso(row.created_at),
                "author": author,
                "reason": row.reason,
                "changes": describe_changes(previous, row.config or {}),
            }
        )
    return out


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None
