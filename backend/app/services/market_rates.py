"""Stawki rynku do raportu kompetencji w 24 godziny (decyzje Artura 25.11.2026).

Źródło to wyłącznie stawki z rozmów (``candidates.rate_latest_hourly``) z ostatnich
12 miesięcy, w przedziale 60–400 zł/h, bez czarnej listy i bez usunięcia w źródle
(te same filtry co skrypt liczb specjalistów na stronę). Grupa to rola × lata × miasto:

- rola: główna technologia (umiejętność z CV z największą liczbą miesięcy spośród
  ``ROLES`` typu ``tech``), chyba że stanowisko z CV pasuje do roli bez programowania
  (tester, DevOps, analityk biznesowy, kierownik projektu, inżynier danych);
- lata: ``candidate_skill_usage.months`` głównej technologii (przy roli ze stanowiska
  najdłuższa umiejętność z CV) w przedziałach ``<3``, ``3–5``, ``5–8``, ``8+``;
- miasto: ``candidates.city`` z polską i angielską pisownią sześciu dużych miast.

Grupa poniżej ``MIN_GROUP`` osób się poszerza: bez miasta → sąsiedni przedział lat →
sama rola. Każdy zdjęty krok ustawia ``widened=True``. Wzorce sprawdzamy na
unikalnych nazwach umiejętności i stanowisk, osoby dołączamy po równości.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import local_now
from app.services.competence_report_schema import (
    MIN_GROUP,
    MarketGroup,
    MarketRate,
    TechPremium,
)

RoleKey = Literal[
    "java", "python", "dotnet", "frontend", "kotlin", "go", "php",
    "tester", "devops", "business_analyst", "project_manager", "data_engineer",
]

RATE_MIN, RATE_MAX = 60, 400
WINDOW_DAYS = 365
MAX_PREMIUMS = 5


@dataclass(frozen=True)
class RoleDef:
    role_label: str
    kind: Literal["tech", "position"]
    pattern: str  # składnia regex Postgresa (\m, \M = granice słowa)
    exclude: str | None = None


# Wzorce ze ``scripts/nexus/liczby-specjalistow.sql`` (b2bnetwork-www), podzbiór.
# Kolejność rozstrzyga remis: przy równych miesiącach albo stanowisku pasującym
# do kilku ról wygrywa wcześniejsza.
ROLES: dict[str, RoleDef] = {
    "java": RoleDef("Java", "tech", r"^(java|java [0-9]+|java ee|j2ee|jakarta ee)$"),
    "python": RoleDef("Python", "tech", r"^(python|python [0-9.]+)$"),
    "dotnet": RoleDef(
        ".NET / C#",
        "tech",
        r"^(c#|c#/\.net|\.net c#|c# \.net|\.net|\.net core|\.net framework|\.net [0-9]+"
        r"|asp\.net|asp\.net core|asp\.net mvc|asp\.net web api)$",
    ),
    "frontend": RoleDef(
        "Frontend (JavaScript / TypeScript)",
        "tech",
        r"^(javascript|vanilla javascript|es6|typescript|react|react\.js|reactjs"
        r"|angular|angularjs|vue|vue\.js|vuejs|vue [23])$",
    ),
    "kotlin": RoleDef("Kotlin", "tech", r"^kotlin( multiplatform| coroutines)?$"),
    "go": RoleDef("Go", "tech", r"^(go|golang)$"),
    "php": RoleDef("PHP", "tech", r"^php$"),
    "tester": RoleDef(
        "Tester",
        "position",
        r"(tester|testów|testowania|testing|\mtest\M|\mqa\M|quality assurance|quality engineer|sdet)",
        r"(test manager|qa manager|kierownik test|test lead|qa lead|head of (qa|test)"
        r"|test coordinator|koordynator test|pentest|penetra|usability)",
    ),
    "devops": RoleDef(
        "DevOps",
        "position",
        r"(devops|devsecops|\msre\M|site reliability|platform engineer|cloud engineer)",
    ),
    "business_analyst": RoleDef(
        "Analityk biznesowy",
        "position",
        r"(business analyst|analityk biznes|business systems? analyst|analityk system"
        r"|\msystems? analyst|it analyst|analityk it)",
    ),
    "project_manager": RoleDef(
        "Kierownik projektu",
        "position",
        r"(project manager|kierownik projekt|program manager|programme manager"
        r"|delivery manager|project lead)",
    ),
    "data_engineer": RoleDef(
        "Inżynier danych",
        "position",
        r"(data engineer|inżynier danych|big data|etl developer|etl engineer"
        r"|analytics engineer|data platform engineer|dwh developer|data warehouse)",
    ),
}

# Przedziały lat: etykieta → [od, do) w latach; ``None`` = bez górnej granicy.
BUCKETS: dict[str, tuple[int, int | None]] = {
    "<3": (0, 3),
    "3–5": (3, 5),
    "5–8": (5, 8),
    "8+": (8, None),
}
_WIDER: dict[str, str] = {"<3": "<5", "3–5": "3–8", "5–8": "5+", "8+": "5+"}
_RANGES: dict[str, tuple[int, int | None]] = {
    **BUCKETS,
    "<5": (0, 5),
    "3–8": (3, 8),
    "5+": (5, None),
}

_CITIES: dict[str, tuple[str, ...]] = {
    "Warszawa": ("warszawa", "warsaw"),
    "Kraków": ("kraków", "krakow", "cracow"),
    "Wrocław": ("wrocław", "wroclaw"),
    "Gdańsk": ("gdańsk", "gdansk"),
    "Poznań": ("poznań", "poznan"),
    "Łódź": ("łódź", "lodz"),
}
_CITY_OF = {alias: label for label, aliases in _CITIES.items() for alias in aliases}


# ── Bez bazy ────────────────────────────────────────────────────────────────


def _py_pattern(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern.replace(r"\m", r"\b").replace(r"\M", r"\b"))


_PY = {key: (_py_pattern(r.pattern), r.exclude and _py_pattern(r.exclude)) for key, r in ROLES.items()}


def _field(row: Any, name: str) -> Any:
    return row.get(name) if isinstance(row, Mapping) else getattr(row, name, None)


def _position_role(position: str) -> str | None:
    pos = position.lower()
    for key, role in ROLES.items():
        pattern, exclude = _PY[key]
        if role.kind == "position" and pattern.search(pos) and not (exclude and exclude.search(pos)):
            return key
    return None


def _tech_months(skill_usage_rows: Iterable[Any]) -> dict[str, int | None]:
    """Rola technologiczna → najdłuższe użycie pasującej umiejętności (``None`` = bez miesięcy)."""
    out: dict[str, int | None] = {}
    for row in skill_usage_rows:
        name = (_field(row, "skill_canonical") or "").strip().lower()
        months = _field(row, "months")
        for key, role in ROLES.items():
            if role.kind == "tech" and _PY[key][0].search(name):
                prev = out.get(key)
                out[key] = months if prev is None else max(prev, months or 0)
    return out


def resolve_role(cv_extracted_data: Mapping[str, Any] | None, skill_usage_rows: Iterable[Any]) -> RoleKey | None:
    """Rola kandydata: stanowisko spoza programowania albo technologia z największą liczbą miesięcy."""
    position = str((cv_extracted_data or {}).get("current_position") or "")
    by_position = _position_role(position)
    if by_position:
        return by_position  # type: ignore[return-value]
    months = _tech_months(skill_usage_rows)
    if not months:
        return None
    order = list(ROLES)
    return max(months, key=lambda key: (months[key] is not None, months[key] or 0, -order.index(key)))  # type: ignore[return-value]


def role_years(role: str, skill_usage_rows: Iterable[Any]) -> int | None:
    """Lata w roli tak, jak liczy je populacja: miesiące technologii roli albo najdłuższej umiejętności."""
    rows = list(skill_usage_rows)
    if ROLES[role].kind == "tech":
        months = _tech_months(rows).get(role)
    else:
        known = [m for m in (_field(row, "months") for row in rows) if m is not None]
        months = max(known) if known else None
    return None if months is None else months // 12


def years_bucket(years: int | None) -> str | None:
    if years is None or years < 0:
        return None
    for label, (low, high) in BUCKETS.items():
        if years >= low and (high is None or years < high):
            return label
    return None


def normalize_city(city: str | None) -> str | None:
    """Etykieta miasta: polska nazwa dla sześciu dużych miast, inaczej wpis bez spacji na brzegach."""
    value = (city or "").strip()
    if not value:
        return None
    return _CITY_OF.get(value.lower(), value)


def _city_key(label: str) -> str:
    return label.lower()


def _steps(bucket: str | None, city: str | None) -> list[tuple[str | None, str | None]]:
    """Kolejne grupy od najwęższej: bez miasta → szersze lata → sama rola."""
    steps: list[tuple[str | None, str | None]] = [(bucket, city)]
    for step in ((bucket, None), (_WIDER.get(bucket) if bucket else None, None), (None, None)):
        if step not in steps:
            steps.append(step)
    return steps


# ── Z bazą ──────────────────────────────────────────────────────────────────


def _city_sql() -> str:
    whens = " ".join(
        f"when lower(btrim(k.city)) in ({', '.join(repr(a) for a in aliases)}) then {label.lower()!r}"
        for label, aliases in _CITIES.items()
    )
    return f"case {whens} else nullif(lower(btrim(k.city)), '') end"


def _people_cte(params: dict[str, Any]) -> str:
    """CTE ``people(id, rate, city, role, months)``: cała populacja ze stawką i przypisaną rolą."""
    tech_rows, pos_rows = [], []
    for prio, (key, role) in enumerate(ROLES.items()):
        params[f"rk{prio}"], params[f"rp{prio}"], params[f"rx{prio}"] = key, role.pattern, role.exclude
        row = f"(:rk{prio}, {prio}, :rp{prio}, cast(:rx{prio} as text))"
        (tech_rows if role.kind == "tech" else pos_rows).append(row)
    params["since"] = local_now() - timedelta(days=WINDOW_DAYS)
    params["rate_min"], params["rate_max"] = RATE_MIN, RATE_MAX
    return f"""
    base as (
      select k.id, k.rate_latest_hourly::float as rate,
             lower(coalesce(k.cv_extracted_data->>'current_position', '')) as pos,
             {_city_sql()} as city
      from candidates k
      where k.status::text <> 'blacklisted' and k.blacklisted_at is null
        and k.external_deleted_at is null
        and k.rate_latest_hourly between :rate_min and :rate_max
        and k.rate_latest_at >= :since
    ),
    pos_roles as (
      select distinct on (p.pos) p.pos, r.key
      from (select distinct pos from base) p
      join (values {', '.join(pos_rows)}) r(key, prio, pattern, exclude)
        on p.pos ~ r.pattern and (r.exclude is null or p.pos !~ r.exclude)
      order by p.pos, r.prio
    ),
    usage as (
      select u.candidate_id, u.skill_canonical, u.months
      from candidate_skill_usage u join base b on b.id = u.candidate_id
    ),
    tech_names as (
      select n.skill_canonical, t.key, t.prio
      from (select distinct skill_canonical from usage) n
      join (values {', '.join(tech_rows)}) t(key, prio, pattern, exclude)
        on lower(n.skill_canonical) ~ t.pattern
    ),
    main_tech as (
      select distinct on (candidate_id) candidate_id, key, m
      from (
        select u.candidate_id, t.key, t.prio, max(u.months) m
        from usage u join tech_names t using (skill_canonical)
        group by u.candidate_id, t.key, t.prio
      ) x
      order by candidate_id, m desc nulls last, prio
    ),
    longest as (select candidate_id, max(months) m from usage group by candidate_id),
    people as (
      select b.id, b.rate, b.city,
             coalesce(pr.key, mt.key) as role,
             case when pr.key is not null then lg.m else mt.m end as months
      from base b
      left join pos_roles pr on pr.pos = b.pos
      left join main_tech mt on mt.candidate_id = b.id
      left join longest lg on lg.candidate_id = b.id
    )"""


def _group_filter(bucket: str | None, city: str | None, params: dict[str, Any], tag: str) -> str:
    """Warunek SQL na ``people`` dla jednej grupy (rola sprawdzana osobno)."""
    parts = ["true"]
    if bucket is not None:
        low, high = _RANGES[bucket]
        params[f"lo{tag}"] = low * 12
        parts.append(f"months >= :lo{tag}")
        if high is not None:
            params[f"hi{tag}"] = high * 12
            parts.append(f"months < :hi{tag}")
    if city is not None:
        params[f"city{tag}"] = _city_key(city)
        parts.append(f"city = :city{tag}")
    return " and ".join(parts)


def _round(value: float) -> int:
    """Zaokrąglenie „szkolne” (połówki w górę), nie bankierskie jak ``round``."""
    return math.floor(value + 0.5)


def _role_key(role: str) -> str:
    if role not in ROLES:
        raise ValueError(f"nieznana rola: {role}")
    return role


async def market_rate_for(
    db: AsyncSession, *, role: RoleKey, years: int | None, city: str | None
) -> MarketRate | None:
    """p25 / mediana / p75 najwęższej grupy z co najmniej ``MIN_GROUP`` osobami; ``None`` gdy żadnej."""
    role = _role_key(role)  # type: ignore[assignment]
    steps = _steps(years_bucket(years), normalize_city(city))
    params: dict[str, Any] = {"role": role}
    cte = _people_cte(params)
    cols = []
    for i, (bucket, step_city) in enumerate(steps):
        where = _group_filter(bucket, step_city, params, str(i))
        cols.append(
            f"count(*) filter (where {where}) as n{i}, "
            + ", ".join(
                f"percentile_cont({q}) within group (order by rate) filter (where {where}) as {name}{i}"
                for q, name in ((0.25, "a"), (0.5, "b"), (0.75, "c"))
            )
        )
    sql = f"with {cte} select {', '.join(cols)} from people where role = :role"
    row = (await db.execute(text(sql), params)).mappings().one()
    for i, (bucket, step_city) in enumerate(steps):
        if row[f"n{i}"] >= MIN_GROUP:
            return MarketRate(
                group=MarketGroup(
                    role_label=ROLES[role].role_label,
                    years_bucket=bucket,
                    city=step_city,
                    widened=i > 0,
                ),
                p25=_round(row[f"a{i}"]),
                median=_round(row[f"b{i}"]),
                p75=_round(row[f"c{i}"]),
                n=row[f"n{i}"],
            )
    return None


async def tech_premiums(
    db: AsyncSession, *, role: RoleKey, group: MarketGroup, skills: Sequence[str]
) -> list[TechPremium]:
    """Mediana z umiejętnością minus mediana bez niej w tej samej grupie co ``market_rate_for``.

    Tylko gdy obie strony mają co najmniej ``MIN_GROUP`` osób; dodatnie premie, malejąco,
    najwyżej ``MAX_PREMIUMS``. Jedno zapytanie na wywołanie (lista umiejętności w ``unnest``).
    """
    role = _role_key(role)  # type: ignore[assignment]
    names: dict[str, str] = {}
    for skill in skills:
        key = (skill or "").strip().lower()
        if key and key not in names:
            names[key] = skill.strip()
    if not names:
        return []
    params: dict[str, Any] = {"role": role, "skills": list(names), "min_group": MIN_GROUP}
    cte = _people_cte(params)
    where = _group_filter(group.years_bucket, group.city, params, "g")
    sql = f"""
    with {cte},
    grp as (select id, rate from people where role = :role and {where}),
    wanted as (select unnest(cast(:skills as text[])) as skill),
    hits as (
      select distinct u.skill_canonical as skill, u.candidate_id
      from usage u join grp g on g.id = u.candidate_id
      where u.skill_canonical = any(cast(:skills as text[]))
    ),
    sides as (
      select w.skill, g.rate, h.candidate_id is not null as has
      from wanted w cross join grp g
      left join hits h on h.skill = w.skill and h.candidate_id = g.id
    )
    select skill,
           percentile_cont(0.5) within group (order by rate) filter (where has)
             - percentile_cont(0.5) within group (order by rate) filter (where not has) as premium
    from sides
    group by skill
    having count(*) filter (where has) >= :min_group
       and count(*) filter (where not has) >= :min_group
    """
    rows = (await db.execute(text(sql), params)).all()
    premiums = [
        TechPremium(name=names[skill], premium=_round(value))
        for skill, value in rows
        if value is not None and _round(value) > 0
    ]
    premiums.sort(key=lambda p: (-p.premium, p.name.lower()))
    return premiums[:MAX_PREMIUMS]
