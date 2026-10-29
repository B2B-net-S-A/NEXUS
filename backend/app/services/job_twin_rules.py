"""Zasady bliźniaków — jedno ustawienie dla całej firmy (decyzje Artura 29.10.2026).

Makieta: https://claude.ai/artifact/QTD7Sk3jBqL386Jq5LYs6m. Ustawienia →
Rekrutacja → „Zasady bliźniaków” (zmienia Head of Recruitment i admin).
Każda zasada ma tryb:

* ``required`` — para bez niej nie trafia na listę „Możliwe bliźniaki”, a
  w kaflu „Otwarte podobne” stoi z „nie spełnia zasad”. Ręcznie da się ją
  połączyć — okno pokazuje ostrzeżenie (decyzja Artura: „Wymagane” tylko
  filtruje listę, nie blokuje łączenia);
* ``warning`` — para zostaje, z uwagą przy parze i w oknie łączenia;
* ``off`` — zasada nie działa.

Zasady startowe jak w makiecie: wymagane podobieństwo od 80%, umiejętności
krytyczne i różni DL (tylko lista HoR); ostrzeżenia: wymagania ≥ 50%,
lokalizacja, tryb pracy, budżet ± 10 zł/h; wyłączone: klient i kategoria.
Zapis w ``app_settings`` (klucz :data:`SETTING_KEY`), ślad w ``activities``.
Pomiar na kopii produkcji z 22.10 (53 pary od 80%): krytyczne przechodzi 46,
lokalizacja 35, tryb pracy 29, budżet 43, klient 46, różni DL 9.
"""

from __future__ import annotations

import logging
import re
import time
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable, Literal, Optional, Sequence

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.models.job import Job

logger = logging.getLogger(__name__)

SETTING_KEY = "job_twin_rules"
Mode = Literal["required", "warning", "off"]
PairHint = Literal["careful", "default", "bold"]
# Najniższy próg, od którego w ogóle liczymy pary — niżej (72% → 103 pary
# różnych DL-i na kopii z 22.10) mieszają się już różne role.
MIN_SIMILARITY_FLOOR = 70
PAIR_HINT_THRESHOLDS = {"careful": 0.3, "default": 0.2, "bold": 0.15}
_CACHE_TTL_SECONDS = 60


class ModeRule(BaseModel):
    mode: Mode


class CriticalRule(ModeRule):
    mode: Mode = "required"
    # „Analityk Systemowy” w tytule pokrywa krytyczną „analiza systemowa”?
    include_title: bool = False


class MustRule(ModeRule):
    mode: Mode = "warning"
    min_share: int = Field(default=50, ge=10, le=100)


class BudgetRule(ModeRule):
    mode: Mode = "warning"
    max_diff: int = Field(default=10, ge=0, le=100)


class TwinRules(BaseModel):
    min_similarity: int = Field(default=80, ge=MIN_SIMILARITY_FLOOR, le=95)
    critical: CriticalRule = Field(default_factory=CriticalRule)
    must: MustRule = Field(default_factory=MustRule)
    location: ModeRule = Field(default_factory=lambda: ModeRule(mode="warning"))
    work_mode: ModeRule = Field(default_factory=lambda: ModeRule(mode="warning"))
    budget: BudgetRule = Field(default_factory=BudgetRule)
    client: ModeRule = Field(default_factory=lambda: ModeRule(mode="off"))
    category: ModeRule = Field(default_factory=lambda: ModeRule(mode="off"))
    # Tylko lista „Możliwe bliźniaki” (HoR): DL swoje łączy sam z kafla.
    different_dl: ModeRule = Field(default_factory=lambda: ModeRule(mode="required"))
    # Kotwica + 3 = najwięcej, ile mieści jedna rozmowa w „Screening dla”.
    max_twins: int = Field(default=3, ge=1, le=3)
    open_similar_limit: int = Field(default=8, ge=4, le=15)
    pair_hint: PairHint = "default"


RULE_LABELS = {
    "similarity": "Podobieństwo opisu",
    "critical": "Umiejętności krytyczne",
    "must": "Wymagania",
    "location": "Lokalizacja",
    "work_mode": "Tryb pracy",
    "budget": "Budżet",
    "client": "Klient",
    "category": "Kategoria kompetencji",
    "different_dl": "Delivery Lead",
}
# Zasady sprawdzane w ocenie pary (kolejność = kolejność w oknie).
PAIR_RULES = (
    "critical",
    "must",
    "location",
    "work_mode",
    "budget",
    "client",
    "category",
)

_cache: dict[str, Any] = {"at": 0.0, "rules": None}


def defaults() -> TwinRules:
    return TwinRules()


def reset_cache() -> None:
    _cache["at"] = 0.0
    _cache["rules"] = None


async def load(db: AsyncSession) -> TwinRules:
    """Zasady firmy; brak wpisu albo zepsuty wpis = zasady startowe."""
    if (
        _cache["rules"] is not None
        and time.monotonic() - _cache["at"] < _CACHE_TTL_SECONDS
    ):
        return _cache["rules"]
    row = await db.get(AppSetting, SETTING_KEY)
    rules = defaults()
    if row is not None and isinstance(row.value, dict):
        try:
            rules = TwinRules.model_validate(row.value)
        except Exception:  # noqa: BLE001 — zły wpis nie może wyłączyć bliźniaków
            logger.warning(
                "job_twin_rules: niepoprawny wpis app_settings, zasady startowe"
            )
    _cache["rules"] = rules
    _cache["at"] = time.monotonic()
    return rules


async def save(db: AsyncSession, rules: TwinRules, *, user_id: int) -> TwinRules:
    from app.models.activity import Activity  # noqa: PLC0415

    before = (await load(db)).model_dump()
    row = await db.get(AppSetting, SETTING_KEY)
    value = rules.model_dump()
    if row is None:
        db.add(AppSetting(key=SETTING_KEY, value=value, updated_by=user_id))
    else:
        row.value = value
        row.updated_by = user_id
    changed = {
        k: {"before": before.get(k), "after": v}
        for k, v in value.items()
        if before.get(k) != v
    }
    db.add(
        Activity(
            entity_type="setting",
            entity_id=0,
            action="job_twin_rules_changed",
            user_id=user_id,
            details={"key": SETTING_KEY, "changed": changed},
        )
    )
    await db.flush()
    reset_cache()
    return rules


# ── Fakty rekrutacji i ocena pary ──────────────────────────────────────────


def _fold(text: Optional[str]) -> str:
    text = (text or "").replace("ł", "l").replace("Ł", "L")
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c)).strip()


# Lokalizacja w rekrutacji to wolny tekst („Warszawa, ul. Chmielna 89”,
# „Sporadycznie, 1-2 dni w miesiącu…”), więc miasta czytamy z listy znanych
# miast, a nie z podziału po przecinkach. Miasta spoza listy zasada pomija.
KNOWN_CITIES = (
    "warszawa",
    "krakow",
    "wroclaw",
    "gdansk",
    "gdynia",
    "sopot",
    "trojmiasto",
    "lodz",
    "poznan",
    "katowice",
    "gliwice",
    "lublin",
    "szczecin",
    "bydgoszcz",
    "torun",
    "rzeszow",
    "bialystok",
    "olsztyn",
    "kielce",
    "opole",
    "czestochowa",
    "bielsko-biala",
    "zielona gora",
    "radom",
    "plock",
    "sosnowiec",
    "tychy",
)


def _cities(location: Optional[str]) -> frozenset[str]:
    text = _fold(location)
    return frozenset(city for city in KNOWN_CITIES if re.search(rf"\b{city}\b", text))


@dataclass(frozen=True)
class JobFacts:
    id: int
    title: str
    critical: tuple[str, ...]
    must: tuple[str, ...]
    cities: frozenset[str]
    remote_policy: Optional[str]
    onsite_days: Optional[int]
    work_mode: str
    budget: Optional[float]
    client_id: Optional[int]
    category_id: Optional[int]
    delivery_lead_id: Optional[int]


def facts_of(job: Job) -> JobFacts:
    from app.services import critical_skills  # noqa: PLC0415
    from app.services.dealbreaker_filters import resolve_job_budget_hourly  # noqa: PLC0415
    from app.services.job_working_title import display_title  # noqa: PLC0415
    from app.services.scoring_service import job_explicit_must_skills  # noqa: PLC0415

    try:
        critical = tuple(critical_skills.effective_critical(job).labels)
    except Exception:  # noqa: BLE001 — profil bez kształtu = brak krytycznych
        critical = ()
    try:
        must = tuple(str(m) for m in job_explicit_must_skills(job) if m)
    except Exception:  # noqa: BLE001
        must = ()
    policy = (
        job.remote_policy.value
        if hasattr(job.remote_policy, "value")
        else job.remote_policy
    )
    days = job.onsite_days_per_week
    if policy == "remote":
        mode = "zdalnie"
    elif policy == "onsite":
        mode = "w biurze"
    elif policy == "hybrid":
        mode = f"{days} dni z biura" if days else "hybrydowo"
    else:
        mode = "nie podano"
    budget = resolve_job_budget_hourly(job)
    return JobFacts(
        id=job.id,
        title=display_title(job),
        critical=critical,
        must=must,
        cities=_cities(job.location),
        remote_policy=policy,
        onsite_days=days,
        work_mode=mode,
        budget=float(budget) if budget is not None else None,
        client_id=job.client_id,
        category_id=job.competence_category_id,
        delivery_lead_id=job.delivery_lead_id,
    )


_WORD = re.compile(r"[a-z0-9+#]+")


def _stems(text: str) -> set[str]:
    """Rdzenie słów (pierwsze 5 liter) — „analiza systemowa” i „Analityk
    Systemowy” mają te same: „anali”, „syste”."""
    return {w[:5] for w in _WORD.findall(_fold(text)) if len(w) >= 3}


def _covered(label: str, pool: Iterable[str]) -> bool:
    folded = _fold(label)
    if not folded:
        return True
    wanted = _stems(label)
    for item in pool:
        other = _fold(item)
        if not other:
            continue
        if folded in other or other in folded:
            return True
        if wanted and wanted <= _stems(item):
            return True
    return False


@dataclass(frozen=True)
class RuleCheck:
    key: str
    mode: str
    ok: bool
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": RULE_LABELS[self.key],
            "mode": self.mode,
            "ok": self.ok,
            "detail": self.detail,
        }


def _check_critical(rule: CriticalRule, a: JobFacts, b: JobFacts) -> tuple[bool, str]:
    missing: list[str] = []
    for own, other in ((a, b), (b, a)):
        pool = [*other.critical, *other.must] + (
            [other.title] if rule.include_title else []
        )
        for label in own.critical:
            if not _covered(label, pool):
                missing.append(f"„{label}” — nie ma w drugiej")
    if missing:
        return False, "; ".join(missing[:2])
    if not a.critical and not b.critical:
        return True, "żadna nie ma krytycznych"
    return True, "krytyczne obu są w wymaganiach drugiej"


def _check_must(rule: MustRule, a: JobFacts, b: JobFacts) -> tuple[bool, str]:
    if not a.must or not b.must:
        return False, "jedna rekrutacja nie ma wymagań"
    small, big = (a.must, b.must) if len(a.must) <= len(b.must) else (b.must, a.must)
    shared = [m for m in small if _covered(m, big)]
    share = round(100 * len(shared) / len(small))
    return share >= rule.min_share, f"wspólne {len(shared)} z {len(small)} = {share}%"


def evaluate(rules: TwinRules, a: JobFacts, b: JobFacts) -> list[RuleCheck]:
    """Ocena pary według zasad (bez podobieństwa i DL — te liczy lista)."""
    out: list[RuleCheck] = []
    if rules.critical.mode != "off":
        ok, detail = _check_critical(rules.critical, a, b)
        out.append(RuleCheck("critical", rules.critical.mode, ok, detail))
    if rules.must.mode != "off":
        ok, detail = _check_must(rules.must, a, b)
        out.append(RuleCheck("must", rules.must.mode, ok, detail))
    if rules.location.mode != "off":
        if a.remote_policy == "remote" and b.remote_policy == "remote":
            ok, detail = True, "obie zdalne"
        elif not a.cities or not b.cities:
            ok, detail = False, "brak miasta w jednej z rekrutacji"
        else:
            common = sorted(a.cities & b.cities)
            ok = bool(common)
            detail = f"{', '.join(common).title()} w obu" if ok else "różne miasta"
        out.append(RuleCheck("location", rules.location.mode, ok, detail))
    if rules.work_mode.mode != "off":
        ok = a.work_mode == b.work_mode
        detail = (
            a.work_mode if ok else f"{a.work_mode} vs {b.work_mode} → osobna stawka"
        )
        out.append(RuleCheck("work_mode", rules.work_mode.mode, ok, detail))
    if rules.budget.mode != "off":
        if a.budget is None or b.budget is None:
            ok, detail = True, "budżet podany w jednej albo żadnej"
        else:
            diff = abs(a.budget - b.budget)
            ok = diff <= rules.budget.max_diff
            detail = f"do {a.budget:g} vs do {b.budget:g} zł/h"
        out.append(RuleCheck("budget", rules.budget.mode, ok, detail))
    if rules.client.mode != "off":
        ok = a.client_id is not None and a.client_id == b.client_id
        out.append(
            RuleCheck(
                "client",
                rules.client.mode,
                ok,
                "ten sam klient" if ok else "różni klienci",
            )
        )
    if rules.category.mode != "off":
        ok = a.category_id is not None and a.category_id == b.category_id
        out.append(
            RuleCheck(
                "category",
                rules.category.mode,
                ok,
                "ta sama kategoria" if ok else "różne kategorie",
            )
        )
    return out


def required_failures(checks: Sequence[RuleCheck]) -> list[RuleCheck]:
    return [c for c in checks if c.mode == "required" and not c.ok]


def warnings(checks: Sequence[RuleCheck]) -> list[RuleCheck]:
    return [c for c in checks if c.mode == "warning" and not c.ok]


def similarity_ok(rules: TwinRules, similarity: int) -> bool:
    return similarity >= rules.min_similarity


def dl_ok(rules: TwinRules, a: JobFacts, b: JobFacts) -> bool:
    if rules.different_dl.mode != "required":
        return True
    return a.delivery_lead_id is None or a.delivery_lead_id != b.delivery_lead_id


async def facts_for(db: AsyncSession, job_ids: Iterable[int]) -> dict[int, JobFacts]:
    ids = sorted(set(job_ids))
    if not ids:
        return {}
    jobs = (await db.execute(select(Job).where(Job.id.in_(ids)))).scalars()
    return {job.id: facts_of(job) for job in jobs}
