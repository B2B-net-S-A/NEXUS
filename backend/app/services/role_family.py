"""Rodzina roli osoby i rekrutacji — tester to nie programista (27.10.2026).

Zgłoszenie Delivery Leada: okno „Kandydaci do dodania” proponowało Senior QA
Automation Engineera do „Full Stack Developer (Java, Angular)” z 77%. „Dop.”
w ~80% to podobieństwo tekstu CV, a tester automatyzujący w Javie pisze o Javie,
REST API, SQL i Dockerze tak samo jak programista. Najlepszy fullstack z 9/10
„musi mieć” miał 81%, tester z 4/10 — 71%. Słowa roli są celowo wycinane
z tytułu rekrutacji (`scoring_service._strip_role_words`), więc nic nie
porównywało ZAWODU osoby z zawodem rekrutacji.

Ten moduł robi tylko to porównanie, bez AI i bez zmiany „Dop.” (wagi „Dop.”
zmienia Head of Recruitment w panelu, po pomiarze):

* rodzina roli z tytułu (`family_of`) — kolejność reguł ma znaczenie:
  „QA Automation Engineer” to tester, „Data Analyst” to dane, nie analityk;
* rola osoby: obecne stanowisko z CV (`cv_extracted_data.current_position`),
  a gdy historia w NEXUSIE mówi wyraźnie co innego — historia (np. CV z 2023
  „Junior Full Stack Developer”, a 14 rekrutacji u nas, wszystkie testerskie);
* nieznana rola po którejkolwiek stronie = brak oznaczenia. Pary pokrewne
  (programista ↔ DevOps / dane, analityk ↔ dane / PM) nie są „inną rolą”.

Inna rola nie usuwa osoby z list ręcznych: przejście z QA do programowania
bywa prawdziwe. Okno ją oznacza i stawia na końcu, a nocny przegląd nie
publikuje jej jako propozycji, chyba że spełnia `KEEP_MUST_SHARE` wymagań.
Do puli dopełniania „Nowych” nie wchodzi wcale (29.10.2026): karta stamtąd
ląduje na tablicy bez człowieka, a lista technologii w CV architekta spełnia
„musi mieć” złożone z samych narzędzi.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Literal, Optional, Sequence

from sqlalchemy import select

Family = Literal["developer", "qa", "analyst", "pm", "devops", "data", "design"]

LABELS: dict[str, str] = {
    "developer": "programista",
    "qa": "tester",
    "analyst": "analityk",
    "pm": "PM / Scrum",
    "devops": "DevOps / admin",
    "data": "dane / BI",
    "design": "projektant UX/UI",
}

# Kolejność = pierwszeństwo. Tester przed programistą („Software Developer in
# Test”), dane przed analitykiem („Data Analyst”), projektant przed
# programistą („UI Designer (frontend)”).
_RULES: tuple[tuple[Family, re.Pattern[str]], ...] = tuple(
    (family, re.compile(pattern, re.IGNORECASE))
    for family, pattern in (
        (
            "qa",
            r"\bqa\b|tester|\bsdet\b|quality assurance|\bin test\b"
            r"|\btest(?:s|ów|ow)?\s+(?:automation\s+)?(?:engineer|specialist|analyst|lead|manager|architect)"
            r"|automation\s+test|test\s+automation|automatyz\w*\s+test|test\w*\s+automatyz"
            r"|inżynier\w*\s+test|specjalist\w*\s+(?:ds\.?\s+)?test|\bsqa\b|test\s*manager"
            r"|koordynator\w*\s+test|kierownik\w*\s+test|[—–-]\s*test\b",
        ),
        (
            "pm",
            r"project manager|kierownik\w*\s+projekt|scrum master|product owner"
            r"|product manager|delivery manager|agile coach|\bpmo\b|program manager",
        ),
        (
            "data",
            r"\bdata\s+(?:engineer|scientist|analyst|architect)|business intelligence|\bbi\b"
            r"|analityk\w*\s+danych|inżynier\w*\s+danych|machine learning|\bml\s+engineer|\bdba\b|\betl\b",
        ),
        # Samo „IT Analyst” / „Analityk” zostaje nieznane: w zamówieniach
        # Nordei to bywa rola techniczna, do której idą programiści.
        (
            "analyst",
            r"business\s+(?:(?:&|and)\s+systems?\s+)?analyst|systems?\s+analyst|functional\s+analyst"
            r"|analityk\w*\s+(?:biznesow|systemow|funkcjonaln)|analiz\w*\s+(?:systemow|biznesow)|\bba\b",
        ),
        (
            "devops",
            # „DevSecOps” nie zawiera „devops” (29.10.2026: rekrutacja
            # „DevSecOps - inżynier” była bez roli i nic jej nie pilnowało).
            r"dev\W?(?:sec\W?)?ops|secops|\bsre\b|site reliability|administrator|\badmin\b|sysadmin|platform engineer"
            r"|cloud engineer|network engineer",
        ),
        # Samo „Designer”/„Projektant” to w tytułach IT często projektant
        # hurtowni albo rozwiązania — UX/UI tylko z jawnym słowem.
        (
            "design",
            r"\bux\b|\bui\b|product designer|graphic designer|service designer"
            r"|visual designer|web designer|\bgrafik",
        ),
        (
            "developer",
            r"developer|deweloper|programist|software engineer|full[\s-]?stack|back[\s-]?end"
            r"|front[\s-]?end|\bdev\b|tech lead|inżynier\w*\s+oprogramowania",
        ),
    )
)

# Role pokrewne — osoba z jednej bywa dobrym kandydatem do drugiej.
_RELATED: frozenset[frozenset[str]] = frozenset(
    {
        frozenset({"developer", "devops"}),
        frozenset({"developer", "data"}),
        frozenset({"analyst", "data"}),
        frozenset({"analyst", "pm"}),
    }
)

# Historia „mówi wyraźnie”: co najmniej tyle rekrutacji z rozpoznaną rolą
# i taki udział jednej rodziny wśród nich.
HISTORY_MIN_PROCESSES = 3
HISTORY_MIN_SHARE = 0.75
# Ostatnie rekrutacje osoby, z których liczymy historię.
HISTORY_LAST_PROCESSES = 10
# Nocny przegląd publikuje osobę z inną rolą, gdy spełnia tyle „musi mieć”
# (tylko propozycje do okna; pula „Nowych” nie ma wyjątku).
KEEP_MUST_SHARE = 0.8

_POSITION_MAX = 60


def family_of(title: Optional[str]) -> Optional[Family]:
    """Rodzina roli z tytułu stanowiska albo rekrutacji; ``None`` = nie wiadomo."""
    if not title or not title.strip():
        return None
    matched = [family for family, pattern in _RULES if pattern.search(title)]
    # „Developer-Analyst”, „Data / ML Engineer / Product Owner”, „Product Owner
    # D4A (DevOps for Applications)” — nie wiadomo, która rola; lepiej nic niż
    # zły znak.
    if "pm" in matched and len(matched) > 1:
        return None
    if "developer" in matched:
        if "analyst" in matched:
            return None
        # „Fullstack Developer & UX/UI Designer” — programista z okiem do UX.
        if "design" in matched:
            matched.remove("design")
    return matched[0] if matched else None


def history_family(
    titles: Iterable[Optional[str]],
) -> tuple[Optional[Family], int, int]:
    """Rodzina z tytułów rekrutacji osoby: (rodzina, ile tej rodziny, ile rozpoznanych).

    Rodzina tylko wtedy, gdy historia jest wyraźna (`HISTORY_MIN_PROCESSES`,
    `HISTORY_MIN_SHARE`); inaczej ``None`` i liczby do opisu.
    """
    families = [f for f in (family_of(t) for t in titles) if f is not None]
    if not families:
        return None, 0, 0
    top, count = Counter(families).most_common(1)[0]
    if (
        len(families) >= HISTORY_MIN_PROCESSES
        and count / len(families) >= HISTORY_MIN_SHARE
    ):
        return top, count, len(families)
    return None, count, len(families)


@dataclass(frozen=True)
class RoleMismatch:
    family: Family
    label: str
    detail: str

    def as_dict(self) -> dict:
        return {"family": self.family, "label": self.label, "detail": self.detail}


def _short(text: str) -> str:
    text = " ".join(text.split())
    return (
        text if len(text) <= _POSITION_MAX else text[: _POSITION_MAX - 1].rstrip() + "…"
    )


def role_mismatch(
    job_family: Optional[Family],
    current_position: Optional[str],
    history_titles: Sequence[Optional[str]] = (),
) -> Optional[RoleMismatch]:
    """Osoba z innej roli niż rekrutacja — albo ``None``, gdy rola ta sama,
    pokrewna albo nieznana po którejkolwiek stronie."""
    if job_family is None:
        return None
    cv_family = family_of(current_position)
    hist, hist_count, hist_known = history_family(history_titles)
    family = hist or cv_family
    if family is None or family == job_family:
        return None
    if frozenset({family, job_family}) in _RELATED:
        return None
    label = LABELS[family]
    if hist is not None:
        detail = f"u nas {hist_count} z {hist_known} rekrutacji: {label}"
        if cv_family is not None and cv_family != hist and current_position:
            detail += f" · w CV „{_short(current_position)}”"
    else:
        detail = f"obecnie {_short(current_position or '')}"
    return RoleMismatch(family=family, label=label, detail=detail)


def current_position(candidate) -> Optional[str]:
    """Obecne stanowisko z odczytu CV, a bez niego to, co pokazuje wiersz okna."""
    data = getattr(candidate, "cv_extracted_data", None)
    if isinstance(data, dict):
        value = data.get("current_position")
        if isinstance(value, str) and value.strip():
            return value.strip()
    from app.services.proposal_facts import current_title  # noqa: PLC0415

    return current_title(candidate)[0]


def keeps_despite_role(requirements: Sequence[dict]) -> bool:
    """Czy osoba z inną rolą spełnia dość „musi mieć”, żeby zostać propozycją."""
    must = [r for r in requirements if isinstance(r, dict) and r.get("level") == "must"]
    if not must:
        return False
    met = sum(1 for r in must if r.get("status") == "met")
    return met / len(must) >= KEEP_MUST_SHARE


async def history_titles(
    db, candidate_ids: Sequence[int], *, exclude_job_id: Optional[int] = None
) -> dict[int, list[str]]:
    """Tytuły ostatnich rekrutacji osób w NEXUSIE (bez unieważnionych, bez
    kart wstawionych przez scraper ogłoszeń i przez dopełnianie „Nowych” —
    to nie była decyzja człowieka, a silnik nie może utwierdzać się sam)."""
    from app.models.job import Job  # noqa: PLC0415
    from app.models.recruitment_process import RecruitmentProcess  # noqa: PLC0415

    if not candidate_ids:
        return {}
    stmt = (
        select(RecruitmentProcess.candidate_id, Job.title)
        .join(Job, Job.id == RecruitmentProcess.job_id)
        .where(
            RecruitmentProcess.candidate_id.in_(list(candidate_ids)),
            RecruitmentProcess.voided_at.is_(None),
            (RecruitmentProcess.entry_source.is_(None))
            | RecruitmentProcess.entry_source.not_in(("auto_match", "system")),
        )
        .order_by(
            RecruitmentProcess.candidate_id,
            RecruitmentProcess.opened_at.desc().nulls_last(),
            RecruitmentProcess.id.desc(),
        )
    )
    if exclude_job_id is not None:
        stmt = stmt.where(RecruitmentProcess.job_id != exclude_job_id)
    out: dict[int, list[str]] = {}
    for candidate_id, title in (await db.execute(stmt)).all():
        titles = out.setdefault(candidate_id, [])
        if len(titles) < HISTORY_LAST_PROCESSES and title:
            titles.append(title)
    return out


async def mismatches_for_job(db, job, candidates: Sequence) -> dict[int, RoleMismatch]:
    """Osoby z innej roli niż rekrutacja — hurtowo, jedno zapytanie o historię."""
    job_family = family_of(getattr(job, "title", None))
    if job_family is None or not candidates:
        return {}
    titles = await history_titles(db, [c.id for c in candidates], exclude_job_id=job.id)
    out: dict[int, RoleMismatch] = {}
    for candidate in candidates:
        found = role_mismatch(
            job_family, current_position(candidate), titles.get(candidate.id, ())
        )
        if found is not None:
            out[candidate.id] = found
    return out
