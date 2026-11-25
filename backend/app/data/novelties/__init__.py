"""Nowości do przeklikania — rejestr nowych funkcji NEXUSA (decyzja Artura 28.10.2026).

Ludzie nie czytali artefaktów „co nowego” (30 dni do 27.10: 478 dymków Jarvisa
u 46 osób, 1 otwarty przewodnik). Nowość pokazuje się więc kropką na tym
przycisku, którego dotyczy, i zalicza się z pracy: przeklikaniem po prawdziwym
ekranie albo pierwszym użyciem funkcji. Samo „przeczytałem” nie istnieje.

Od 18.11.2026 (decyzja Artura) nowości nie wyskakują w ciągu dnia: przy
pierwszym wejściu dnia osoba przeklikuje porcję — wszystko, co weszło do jej
roli i czego jeszcze nie przeszła (``GET /novelties/daily``) — na rekrutacji
ćwiczebnej Poligonu, a potem do jutra nic się nie pokazuje.

Trzy poziomy (``tier``) mówią, jak duża jest zmiana (karta na liście porcji):

- ``dot`` — drobiazg; kroki opcjonalne (bez nich jeden krok na ``dot_anchor``);
- ``tour`` — nowa funkcja, co najmniej 2 kroki po kotwicach ``data-tour``
  (krok przechodzi po kliknięciu prawdziwego elementu);
- ``process`` — zmiana sposobu pracy (``path_prefix`` ekranu).

Wpis dopisuje PR, który wdraża nowość. Kotwice kroków muszą istnieć we
froncie jako ``data-tour`` — pilnuje tego test frontu
(``lib/novelties/__tests__/novelty-anchors.test.ts``), który czyta ten plik
ścieżką względną, jak przewodniki ekranów.
"""

from __future__ import annotations

import json
from collections.abc import Collection
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.config import settings
from app.models.user import UserRole
from app.services import permission_catalog
from app.services.section_permissions import ProductSection

NOVELTIES_PATH = Path(__file__).resolve().parent / "novelties.json"

_ANCHOR = r"^[a-z0-9][a-z0-9_.-]{1,59}$"
_NOVELTY_ID = r"^[a-z0-9][a-z0-9-]{2,59}$"

NoveltyTier = Literal["dot", "tour", "process"]

#: Domyślnie nowość żyje 45 dni od wdrożenia — potem znika z kropek i listy,
#: a panel „kto już umie” pokazuje ją jeszcze do 90 dni.
DEFAULT_ACTIVE_DAYS = 45
PANEL_DAYS = 90


class NoveltyAudience(BaseModel):
    """Kogo nowość dotyczy. Pusta lista ról i uprawnień = wszyscy."""

    model_config = ConfigDict(extra="forbid")

    roles: list[str] = Field(default_factory=list)
    #: Wystarczy jedno — przycisk pokazywany posiadaczom uprawnienia opisujemy
    #: uprawnieniem, nie listą ról.
    permissions: list[str] = Field(default_factory=list)

    @field_validator("roles")
    @classmethod
    def _known_roles(cls, value: list[str]) -> list[str]:
        known = {role.value for role in UserRole}
        unknown = [role for role in value if role not in known]
        if unknown:
            raise ValueError(f"Nieznana rola w nowości: {unknown}")
        return value

    @field_validator("permissions")
    @classmethod
    def _known_permissions(cls, value: list[str]) -> list[str]:
        unknown = [key for key in value if key not in permission_catalog.BY_KEY]
        if unknown:
            raise ValueError(f"Nieznane uprawnienie w nowości: {unknown}")
        return value


class TourStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    anchor: str = Field(pattern=_ANCHOR)
    text: str = Field(min_length=1, max_length=90)
    hint: str = Field(min_length=1, max_length=160)
    #: Krok, którego nie wolno wykonać naprawdę (np. „Zapisz” zakończenia
    #: kontraktu): przechodzi przyciskiem „Rozumiem”, nie kliknięciem kotwicy.
    ack: bool = False


class Novelty(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=_NOVELTY_ID)
    title: str = Field(min_length=1, max_length=80)
    why: str = Field(min_length=1, max_length=200)
    tier: NoveltyTier
    shipped_on: date
    pr: Optional[int] = None
    audience: NoveltyAudience = Field(default_factory=NoveltyAudience)
    #: Gdzie jest nowość, słowami użytkownika („Rekrutacja → Kandydaci do dodania”).
    where: str = Field(min_length=1, max_length=80)
    #: Ekran, na który prowadzi pozycja listy „Nowości”.
    href: str = Field(pattern=r"^/[a-z0-9/_-]*$", max_length=80)
    #: Ekran porannej porcji (18.11.2026): gdzie na rekrutacji ćwiczebnej
    #: Poligonu stoi element, gdy ``href`` prowadzi tylko na listę (np. karta
    #: na Tablicy: ``/jobs/990001``). Brak = przeklikanie zaczyna się na ``href``.
    #: Wielkie litery tylko w query: parametry Rozliczeń są camelCase (``stSub``).
    practice_href: Optional[str] = Field(
        default=None, pattern=r"^/[a-z0-9/_-]*(\?[A-Za-z0-9_=&.-]+)?$", max_length=120
    )
    #: Kotwica ``data-tour``, przy której stoi kropka.
    dot_anchor: str = Field(pattern=_ANCHOR)
    #: Kliknięcie tej kotwicy poza przeklikaniem = „użyte w pracy”.
    used_anchor: Optional[str] = Field(default=None, pattern=_ANCHOR)
    #: Ekran, przy którego otwarciu pokazuje się okno zmiany procesu.
    path_prefix: Optional[str] = Field(default=None, pattern=r"^/[a-z0-9/_-]*$")
    #: Sekcja ekranu nowości (ta sama, którą sprawdza middleware i bramka
    #: tras). Osoba bez odczytu w tej sekcji nie dostaje nowości ani okna —
    #: nikt nie przeklikuje ekranu, do którego nie ma dostępu (Artur, 30.10.2026).
    section: Optional[ProductSection] = None
    steps: list[TourStep] = Field(default_factory=list, max_length=6)
    #: Nazwa przełącznika z ``Settings``: dopóki jest wyłączony, nowości nie ma,
    #: bo prowadziłaby po ekranie, którego nikt nie widzi.
    requires_setting: Optional[str] = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]*$")
    active_days: int = Field(default=DEFAULT_ACTIVE_DAYS, ge=7, le=90)

    @model_validator(mode="after")
    def _tier_shape(self) -> "Novelty":
        if self.tier != "dot" and len(self.steps) < 2:
            raise ValueError(f"{self.id}: przeklikanie potrzebuje co najmniej 2 kroków")
        if self.tier == "process" and not self.path_prefix:
            raise ValueError(f"{self.id}: zmiana procesu potrzebuje path_prefix ekranu")
        if self.tier != "process" and self.path_prefix:
            raise ValueError(
                f"{self.id}: path_prefix ma sens tylko przy zmianie procesu"
            )
        return self

    @field_validator("requires_setting")
    @classmethod
    def _known_setting(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not hasattr(settings, value):
            raise ValueError(f"Nieznany przełącznik w nowości: {value}")
        return value

    def switched_on(self) -> bool:
        return self.requires_setting is None or bool(
            getattr(settings, self.requires_setting, False)
        )

    def active_on(self, day: date) -> bool:
        return (
            self.shipped_on <= day < self.shipped_on + timedelta(days=self.active_days)
        )

    def in_panel_on(self, day: date) -> bool:
        return self.shipped_on <= day < self.shipped_on + timedelta(days=PANEL_DAYS)


@lru_cache(maxsize=1)
def load_novelties() -> dict[str, Novelty]:
    """Nowości po id, w kolejności pliku. Zły plik = wyjątek przy starcie testów."""
    raw = json.loads(NOVELTIES_PATH.read_text(encoding="utf-8"))
    by_id: dict[str, Novelty] = {}
    for item in raw:
        novelty = Novelty.model_validate(item)
        if novelty.id in by_id:
            raise ValueError(f"Powtórzone id nowości: {novelty.id}")
        by_id[novelty.id] = novelty
    return by_id


#: „Start w NEXUSIE” (decyzja Artura 30.10.2026): najważniejsze funkcje,
#: które każdy w swojej roli przeklikuje, zanim wejdzie dalej niż pulpit.
#: Ten sam kształt co nowość, ale bez terminu ważności, bez kropek i kart.
START_PATH = Path(__file__).resolve().parent / "start.json"


@lru_cache(maxsize=1)
def load_start_tours() -> dict[str, Novelty]:
    """Przeklikania Startu po id. Tylko ``tour``, id z przedrostkiem ``start-``."""
    raw = json.loads(START_PATH.read_text(encoding="utf-8"))
    by_id: dict[str, Novelty] = {}
    for item in raw:
        tour = Novelty.model_validate(item)
        if tour.tier != "tour" or not tour.id.startswith("start-"):
            raise ValueError(f"{tour.id}: Start to przeklikanie (tour) z id „start-…”")
        if tour.id in by_id or tour.id in load_novelties():
            raise ValueError(f"Powtórzone id przeklikania Startu: {tour.id}")
        by_id[tour.id] = tour
    return by_id


def in_audience(
    novelty: Novelty, roles: Collection[str], permissions: Collection[str]
) -> bool:
    audience = novelty.audience
    if not audience.roles and not audience.permissions:
        return True
    if audience.roles and set(roles) & set(audience.roles):
        return True
    if audience.permissions and set(permissions) & set(audience.permissions):
        return True
    return False


#: Lekcje nowości (decyzje Artura 23.11.2026): przeklikanie nie uczyło —
#: mediana 12 s na nowość, 61% przeklikań to sam „Rozumiem”. Lekcja łączy
#: wpisy jednej funkcji i ma trzy etapy na Poligonie: pokaz (kroki wpisów,
#: z podświetleniem), samodzielne zadanie z warunkiem zaliczenia (bez
#: podświetlenia) i pytanie „po co / kiedy”. Nie wyszło → z powrotem do pokazu.
LESSONS_PATH = Path(__file__).resolve().parent / "lessons.json"

#: Każdy wpis wdrożony od tego dnia musi należeć do lekcji (porcja zaczyna
#: się od ``DAILY_FLOOR`` 12.11.2026 — ta sama data).
LESSONS_FLOOR = date(2026, 11, 12)


class ClickCheck(BaseModel):
    """Osoba sama znajduje i klika element (kotwica ``data-tour``)."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["click"]
    anchor: str = Field(pattern=_ANCHOR)


class MoveCheck(BaseModel):
    """Ruch karty na rekrutacji ćwiczebnej do etapu ``to`` (kod etapu),
    opcjonalnie z powodem, którego nazwa zawiera ``reason_includes``."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["move"]
    to: str = Field(pattern=r"^[a-z_]{2,40}$")
    reason_includes: Optional[str] = Field(default=None, min_length=2, max_length=40)
    #: Co powiedzieć, gdy karta poszła gdzie indziej albo z innym powodem.
    feedback: str = Field(min_length=10, max_length=240)


class PageCheck(BaseModel):
    """Osoba sama dochodzi do ekranu (ścieżka i opcjonalnie parametry adresu)."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["page"]
    path_prefix: str = Field(pattern=r"^/[a-z0-9/_-]*$", max_length=80)
    query: dict[str, str] = Field(default_factory=dict)


LessonCheck = ClickCheck | MoveCheck | PageCheck


class LessonQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    q: str = Field(min_length=10, max_length=160)
    options: list[str] = Field(min_length=3, max_length=3)
    #: Indeks dobrej odpowiedzi w ``options`` (front miesza kolejność).
    answer: int = Field(ge=0, le=2)
    #: Wyjaśnienie po złej odpowiedzi.
    explain: str = Field(min_length=10, max_length=240)

    @field_validator("options")
    @classmethod
    def _distinct(cls, value: list[str]) -> list[str]:
        if len({v.strip().lower() for v in value}) != len(value):
            raise ValueError("Odpowiedzi w pytaniu muszą się różnić")
        if any(not v.strip() or len(v) > 90 for v in value):
            raise ValueError("Odpowiedź: od 1 do 90 znaków")
        return value


class Lesson(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^lekcja-[a-z0-9-]{2,52}$")
    title: str = Field(min_length=1, max_length=80)
    #: Wpisy z ``novelties.json``, których dotyczy lekcja — w kolejności pokazu.
    novelties: list[str] = Field(min_length=1, max_length=6)
    #: Zadanie samodzielne, słowami użytkownika.
    task: str = Field(min_length=10, max_length=240)
    #: Ekran Poligonu, na którym zaczyna się zadanie samodzielne.
    solo_href: str = Field(
        pattern=r"^/[a-z0-9/_-]*(\?[A-Za-z0-9_=&.-]+)?$", max_length=120
    )
    check: LessonCheck = Field(discriminator="kind")
    questions: list[LessonQuestion] = Field(min_length=2, max_length=4)


@lru_cache(maxsize=1)
def load_lessons() -> dict[str, Lesson]:
    """Lekcje po id. Wpis należy do najwyżej jednej lekcji; wpisy od
    ``LESSONS_FLOOR`` — do dokładnie jednej (pilnuje test)."""
    raw = json.loads(LESSONS_PATH.read_text(encoding="utf-8"))
    novelties = load_novelties()
    by_id: dict[str, Lesson] = {}
    owner: dict[str, str] = {}
    for item in raw:
        lesson = Lesson.model_validate(item)
        if lesson.id in by_id:
            raise ValueError(f"Powtórzone id lekcji: {lesson.id}")
        for novelty_id in lesson.novelties:
            if novelty_id not in novelties:
                raise ValueError(f"{lesson.id}: nieznana nowość {novelty_id}")
            if novelty_id in owner:
                raise ValueError(
                    f"{novelty_id} jest w dwóch lekcjach: {owner[novelty_id]}, {lesson.id}"
                )
            owner[novelty_id] = lesson.id
        by_id[lesson.id] = lesson
    return by_id


def lesson_of() -> dict[str, str]:
    """Id nowości → id lekcji."""
    return {
        nid: lesson.id for lesson in load_lessons().values() for nid in lesson.novelties
    }


#: Poligon NEXUSA (decyzje Artura 14.11.2026): onboarding nowej osoby na
#: rekrutacji ćwiczebnej. Rejestr ćwiczeń zapisujemy tu, bo postęp idzie do
#: ``novelty_progress`` (id ``poligon-…``) tym samym zdarzeniem co nowości.
#: Treść i ocena ćwiczeń są we froncie (``lib/poligon/exercises.ts``) —
#: test frontu pilnuje, że oba rejestry mają te same id.
POLIGON_PATH = Path(__file__).resolve().parent / "poligon.json"


class PoligonExercise(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^poligon-[a-z0-9-]{2,51}$")
    module: str = Field(min_length=1, max_length=60)
    title: str = Field(min_length=1, max_length=90)
    #: Czyja to ścieżka (15.11.2026: rekruter, Delivery Lead, TCM mają własne).
    #: Osoba przechodzi ćwiczenia każdej swojej roli; lustro `roles` w `exercises.ts`.
    roles: list[str] = Field(min_length=1)


class PoligonPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Kto może przejść poligon i zapisać postęp (mapa jest otwarta dla nich).
    roles: list[str]
    #: Kogo poligon blokuje, dopóki go nie przejdzie: te role…
    required_roles: list[str]
    #: …i konto założone tego dnia albo później (obecni mają Start za sobą).
    required_since: date
    #: Przeklikania Startu, które poligon zastępuje osobie, której jest
    #: wymagany — per rola z ``required_roles``.
    replaces: dict[str, list[str]]
    exercises: list[PoligonExercise] = Field(min_length=1)

    @field_validator("roles", "required_roles")
    @classmethod
    def _known_roles(cls, value: list[str]) -> list[str]:
        known = {role.value for role in UserRole}
        unknown = [role for role in value if role not in known]
        if unknown:
            raise ValueError(f"Nieznana rola w poligonie: {unknown}")
        return value

    @model_validator(mode="after")
    def _consistent(self) -> "PoligonPlan":
        ids = [e.id for e in self.exercises]
        if len(ids) != len(set(ids)):
            raise ValueError("Powtórzone id ćwiczenia poligonu")
        if not set(self.required_roles) <= set(self.roles):
            raise ValueError("required_roles poligonu musi być w roles")
        if not set(self.replaces) <= set(self.required_roles):
            raise ValueError("replaces poligonu tylko dla ról z required_roles")
        for exercise in self.exercises:
            if not set(exercise.roles) <= set(self.roles):
                raise ValueError(f"Rola spoza poligonu w ćwiczeniu {exercise.id}")
        empty = [
            role
            for role in self.required_roles
            if not any(role in e.roles for e in self.exercises)
        ]
        if empty:
            raise ValueError(f"Rola wymagana bez ćwiczeń poligonu: {empty}")
        return self

    def by_id(self) -> dict[str, PoligonExercise]:
        return {e.id: e for e in self.exercises}

    def exercises_for(self, roles: Collection[str]) -> list[PoligonExercise]:
        """Ścieżka osoby: ćwiczenia każdej jej roli, w kolejności rejestru."""
        return [e for e in self.exercises if set(e.roles) & set(roles)]

    def replaced_for(self, roles: Collection[str]) -> set[str]:
        return {tour for role in roles for tour in self.replaces.get(role, [])}


@lru_cache(maxsize=1)
def load_poligon() -> PoligonPlan:
    plan = PoligonPlan.model_validate(
        json.loads(POLIGON_PATH.read_text(encoding="utf-8"))
    )
    starts = load_start_tours()
    unknown = [
        tour_id
        for tours in plan.replaces.values()
        for tour_id in tours
        if tour_id not in starts
    ]
    if unknown:
        raise ValueError(f"Poligon zastępuje nieznane przeklikania Startu: {unknown}")
    clash = set(plan.by_id()) & (set(starts) | set(load_novelties()))
    if clash:
        raise ValueError(f"Id ćwiczenia poligonu zajęte przez nowość: {sorted(clash)}")
    return plan
