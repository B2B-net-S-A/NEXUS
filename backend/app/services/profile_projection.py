"""Pełny profil kandydata z odczytu CV v7: oś technologii i jej projekcja do tabeli.

Oś technologii (`skill_timeline`) odpowiada na pytanie „kiedy ta osoba używała
danej technologii i gdzie". Model jej NIE pisze: liczymy ją deterministycznie
z dat stanowisk (`experience[].technologies × start/end`), projektów oraz dat
użycia skilli podanych w CV. Dzięki temu każda liczba na osi da się wskazać
w źródle, a zmiana promptu nie może jej zmyślić.

Źródłem prawdy zostaje JSONB (`cv_extracted_data.skill_timeline`); tabela
`candidate_skill_usage` jest indeksem do zapytań typu „używał Kafki po 2023".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterable, Optional

from sqlalchemy import delete, insert
from sqlalchemy.ext.asyncio import AsyncSession

PROFILE_SCHEMA_VERSION = 2
FIRST_RICH_PROMPT_VERSION = 7
_MAX_CONTEXTS = 5
_MAX_TIMELINE_ENTRIES = 80
_SOURCE_RE = re.compile(r"^(?:claude|ollama):cv_enrichment:v(\d+)$")
_DATE_RE = re.compile(r"^(\d{4})(?:-(\d{2}))?$")


def is_rich_profile_parse(parsed: dict[str, Any]) -> bool:
    """True, gdy wynik pochodzi z promptu `cv_enrichment` v7 lub nowszego.

    Regex fallback i starsze odczyty nie niosą dat technologii ani certyfikatów,
    więc nie mogą stemplować `_profile_schema` — frontend pokazywałby puste
    sekcje jako „CV nie zawiera certyfikatów", co byłoby nieprawdą.
    """
    if not isinstance(parsed, dict):
        return False
    match = _SOURCE_RE.match(str(parsed.get("_source") or ""))
    return bool(match) and int(match.group(1)) >= FIRST_RICH_PROMPT_VERSION


def has_rich_profile(extracted: Any) -> bool:
    """True dla `cv_extracted_data` zapisanego z odczytu v7 (schemat 2+)."""
    if not isinstance(extracted, dict):
        return False
    try:
        return int(extracted.get("_profile_schema") or 0) >= PROFILE_SCHEMA_VERSION
    except (TypeError, ValueError):
        return False


def _month_index(value: Any, *, today: date, is_end: bool) -> Optional[int]:
    """`YYYY-MM`/`YYYY`/`present` → numer miesiąca (rok*12+miesiąc-1).

    Sam rok na początku to styczeń, na końcu grudzień (ale nie później niż dziś):
    „2019–2021" to pełne lata, nie dwa styczniowe dni.
    """
    if value is None:
        return None
    text = str(value).strip().casefold()
    today_index = today.year * 12 + today.month - 1
    if text == "present":
        return today_index if is_end else None
    match = _DATE_RE.match(text)
    if not match:
        return None
    year = int(match.group(1))
    if match.group(2):
        month = int(match.group(2))
        if not 1 <= month <= 12:
            return None
    else:
        month = 12 if is_end else 1
    index = year * 12 + month - 1
    return min(index, today_index)


def _format_month(index: int, *, precise: bool) -> str:
    year, month = divmod(index, 12)
    return f"{year}-{month + 1:02d}" if precise else str(year)


def _canonical_key(name: str) -> str:
    from app.services.skill_normalize import canonical_of

    return canonical_of(name) or name.strip().casefold()


@dataclass
class _Usage:
    display: str
    intervals: list[tuple[int, int]] = field(default_factory=list)
    first: Optional[int] = None
    last: Optional[int] = None
    precise_first: bool = False
    precise_last: bool = False
    current: bool = False
    contexts: list[dict[str, Optional[str]]] = field(default_factory=list)

    def add_point(self, index: Optional[int], *, precise: bool, is_end: bool) -> None:
        if index is None:
            return
        if is_end:
            if self.last is None or index > self.last:
                self.last, self.precise_last = index, precise
        elif self.first is None or index < self.first:
            self.first, self.precise_first = index, precise

    def add_context(self, company: Optional[str], role: Optional[str]) -> None:
        if not (company or role) or len(self.contexts) >= _MAX_CONTEXTS:
            return
        ctx = {"company": company, "role": role}
        if ctx not in self.contexts:
            self.contexts.append(ctx)


def _union_months(intervals: Iterable[tuple[int, int]]) -> int:
    total = 0
    current_start: Optional[int] = None
    current_end: Optional[int] = None
    for start, end in sorted(intervals):
        if current_end is None or start > current_end + 1:
            if current_end is not None and current_start is not None:
                total += current_end - current_start + 1
            current_start, current_end = start, end
        else:
            current_end = max(current_end, end)
    if current_end is not None and current_start is not None:
        total += current_end - current_start + 1
    return total


def _is_precise(value: Any) -> bool:
    return bool(value) and bool(re.match(r"^\d{4}-\d{2}$", str(value).strip()))


def build_skill_timeline(
    *,
    experience: Any,
    skills: Any,
    projects: Any = None,
    today: Optional[date] = None,
) -> list[dict[str, Any]]:
    """Oś technologii z odczytu CV: kiedy i gdzie kandydat używał danej technologii.

    Zwraca listę posortowaną od ostatnio używanej, każdy wpis::

        {"skill", "first_used", "last_used", "months", "is_current",
         "contexts": [{"company", "role"}]}

    `months` to suma miesięcy stanowisk i projektów z tą technologią, liczona
    bez podwójnego liczenia nakładających się okresów. Skill bez żadnej daty
    w CV nie trafia na oś — brak daty nie jest „nigdy".
    """
    today = today or date.today()
    usages: dict[str, _Usage] = {}

    def usage_for(name: Any) -> Optional[_Usage]:
        if not isinstance(name, str) or not name.strip():
            return None
        key = _canonical_key(name)
        if key not in usages:
            usages[key] = _Usage(display=" ".join(name.split())[:120])
        return usages[key]

    def fold_period(
        technologies: Any,
        start: Any,
        end: Any,
        company: Optional[str],
        role: Optional[str],
    ) -> None:
        if not isinstance(technologies, list):
            return
        start_index = _month_index(start, today=today, is_end=False)
        end_index = _month_index(end, today=today, is_end=True)
        if end is None and start_index is not None:
            # Brak daty końca w odczycie v6/v7 znaczy „CV nie podaje", a nie
            # „trwa". Liczymy wtedy tylko punkt startu, bez długości okresu.
            end_index = None
        is_current = str(end or "").strip().casefold() == "present"
        for tech in technologies:
            usage = usage_for(tech)
            if usage is None:
                continue
            usage.add_point(start_index, precise=_is_precise(start), is_end=False)
            usage.add_point(
                end_index if end_index is not None else start_index,
                precise=_is_precise(end) or is_current,
                is_end=True,
            )
            if (
                start_index is not None
                and end_index is not None
                and end_index >= start_index
            ):
                usage.intervals.append((start_index, end_index))
            usage.current = usage.current or is_current
            usage.add_context(company, role)

    for entry in experience if isinstance(experience, list) else []:
        if isinstance(entry, dict):
            fold_period(
                entry.get("technologies"),
                entry.get("start"),
                entry.get("end"),
                entry.get("company"),
                entry.get("role"),
            )
    for project in projects if isinstance(projects, list) else []:
        if isinstance(project, dict):
            fold_period(
                project.get("technologies"),
                project.get("start"),
                project.get("end"),
                project.get("company") or project.get("name"),
                project.get("role"),
            )
    for skill in skills if isinstance(skills, list) else []:
        if not isinstance(skill, dict):
            continue
        first_used, last_used = skill.get("first_used"), skill.get("last_used")
        if not (first_used or last_used):
            continue
        usage = usage_for(skill.get("name"))
        if usage is None:
            continue
        usage.add_point(
            _month_index(first_used, today=today, is_end=False),
            precise=_is_precise(first_used),
            is_end=False,
        )
        is_current = str(last_used or "").strip().casefold() == "present"
        usage.add_point(
            _month_index(last_used, today=today, is_end=True),
            precise=_is_precise(last_used) or is_current,
            is_end=True,
        )
        usage.current = usage.current or is_current

    timeline: list[dict[str, Any]] = []
    for usage in usages.values():
        if usage.first is None and usage.last is None:
            continue
        first = usage.first if usage.first is not None else usage.last
        last = usage.last if usage.last is not None else usage.first
        if first is None or last is None:
            continue
        timeline.append(
            {
                "skill": usage.display,
                "first_used": _format_month(first, precise=usage.precise_first),
                "last_used": _format_month(last, precise=usage.precise_last),
                "months": _union_months(usage.intervals) or None,
                "is_current": usage.current,
                "contexts": usage.contexts,
                "_last_index": last,
            }
        )
    timeline.sort(key=lambda row: (-row["_last_index"], row["skill"].casefold()))
    for row in timeline:
        row.pop("_last_index")
    return timeline[:_MAX_TIMELINE_ENTRIES]


def rich_profile_text_facts(
    candidate: Any, *, recent_years: int = 3
) -> dict[str, list[str]]:
    """Fakty profilu v7 dla tekstu embeddingu. Pusty słownik dla starych profili.

    Pusty wynik dla kandydata bez `_profile_schema` jest kontraktem, nie
    ostrożnością: tekst embeddingu 49 tys. starych profili musi zostać bajt
    w bajt taki sam, inaczej zmienia się `desired_hash` i cała baza idzie do
    ponownego indeksowania.
    """
    extracted = getattr(candidate, "cv_extracted_data", None)
    if not has_rich_profile(extracted):
        return {}
    certifications = [
        str(c.get("name"))
        for c in extracted.get("certifications") or []
        if isinstance(c, dict) and c.get("name")
    ]
    highlights = extracted.get("cv_highlights")
    sectors = (
        [str(x) for x in highlights.get("sectors") or [] if x]
        if isinstance(highlights, dict)
        else []
    )
    # Próg od daty ODCZYTU CV, nie od dziś: tekst embeddingu musi być funkcją
    # zapisanych danych. Zależność od zegara zmieniałaby `desired_hash` co
    # roku i reconciler uznawałby wektory za nieaktualne bez żadnej edycji.
    generated_at = (
        str(highlights.get("generated_at") or "")
        if isinstance(highlights, dict)
        else ""
    )
    if not generated_at[:4].isdigit():
        return {"certifications": certifications[:20], "sectors": sectors[:4]}
    threshold = int(generated_at[:4]) - recent_years
    recent: list[str] = []
    for entry in extracted.get("skill_timeline") or []:
        if not isinstance(entry, dict) or not entry.get("skill"):
            continue
        last = str(entry.get("last_used") or "")
        if last[:4].isdigit() and int(last[:4]) >= threshold:
            recent.append(str(entry["skill"]))
    return {
        "certifications": certifications[:20],
        "sectors": sectors[:4],
        "recent_skills": recent[:30],
    }


def _to_date(value: Optional[str], *, is_end: bool) -> Optional[date]:
    if not value:
        return None
    match = _DATE_RE.match(str(value))
    if not match:
        return None
    year = int(match.group(1))
    month = int(match.group(2)) if match.group(2) else (12 if is_end else 1)
    return date(year, month, 1)


def skill_usage_rows(candidate_id: int, extracted: Any) -> list[dict[str, Any]]:
    """Wiersze `candidate_skill_usage` z zapisanej osi (czysta funkcja)."""
    if not has_rich_profile(extracted):
        return []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in extracted.get("skill_timeline") or []:
        if not isinstance(entry, dict) or not isinstance(entry.get("skill"), str):
            continue
        canonical = _canonical_key(entry["skill"])[:120]
        if not canonical or canonical in seen:
            continue
        seen.add(canonical)
        rows.append(
            {
                "candidate_id": candidate_id,
                "skill_canonical": canonical,
                "skill_raw": entry["skill"][:120],
                "first_used": _to_date(entry.get("first_used"), is_end=False),
                "last_used": _to_date(entry.get("last_used"), is_end=True),
                "months": entry.get("months"),
                "is_current": bool(entry.get("is_current")),
                "contexts": entry.get("contexts") or [],
                "provenance": "cv",
                "source_ref": (
                    (extracted.get("cv_highlights") or {}).get("source_hash")
                    if isinstance(extracted.get("cv_highlights"), dict)
                    else None
                ),
            }
        )
    return rows


async def replace_skill_usage(db: AsyncSession, candidate: Any) -> int:
    """Przebuduj indeks `candidate_skill_usage` dla kandydata z jego osi w JSONB.

    Idempotentne (usuń + wstaw w transakcji wołającego). Słabszy odczyt przy
    FILL_EMPTY zachowuje oś w JSONB (`cv_enrichment`), więc indeks odbudowuje
    się z niej identycznie; profil bez osi zostaje bez wierszy.
    """
    from app.models.candidate_skill_usage import CandidateSkillUsage

    extracted = candidate.cv_extracted_data
    rows = skill_usage_rows(candidate.id, extracted)
    # Najpierw kasujemy zawsze: profil, który przestał być pełny (świadomy
    # odczyt nowego CV regexem), nie może zostawić osi poprzedniego pliku.
    await db.execute(
        delete(CandidateSkillUsage).where(
            CandidateSkillUsage.candidate_id == candidate.id,
            CandidateSkillUsage.provenance == "cv",
        )
    )
    if rows:
        await db.execute(insert(CandidateSkillUsage), rows)
    return len(rows)
