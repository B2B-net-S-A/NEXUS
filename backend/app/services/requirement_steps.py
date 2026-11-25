"""Schodki po wymaganiach w kolejce kart od systemu (decyzja Artura 23.11.2026).

Zgłoszenie: „ręczne wyszukiwanie jest lepsze niż porcja”. Artur wybrał wariant B
z makiet https://claude.ai/artifact/5SJB7AYPZWbFkVKf77jhnN: krytyczne jak dotąd
(brak = koniec kolejki), potem więcej spełnionych „musi mieć” = wyżej, „mile
widziane” rozstrzyga remis, dalej wynik z premiami. Ten sam klucz układa porcję,
dobór z puli i kolumnę „Nowi” na Tablicy.

Pomiar na kopii z 23.11 (karty od systemu od 09.11): osoby z kompletem krytycznych
i „musi mieć” szły do klienta w 4,4% decyzji, z mniej niż połową w 1,4%; „Pasuje”
tego nie odróżniało. Pełne „spełnia wszystko” z mile widzianymi nie odróżniało
niczego (2,5% przy średniej 2,8%), dlatego mile widziane są tylko dogrywką.

„Spełnia” = ślad w CV albo na liście umiejętności (``evidence_for``: doświadczenie
albo wzmianka), ta sama miara co ✓ / ~ w „Kluczowe w tej rekrutacji”.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from sqlalchemy import select

from app.models.candidate import Candidate

ALTERNATIVE_JOINER = " lub "


@dataclass(frozen=True)
class Requirement:
    label: str
    words: tuple[str, ...]


@dataclass(frozen=True)
class JobRequirements:
    critical: tuple[Requirement, ...] = ()
    must: tuple[Requirement, ...] = ()
    nice: tuple[Requirement, ...] = ()

    @property
    def empty(self) -> bool:
        return not (self.critical or self.must or self.nice)

    def words(self) -> set[str]:
        return {
            word
            for group in (self.critical, self.must, self.nice)
            for item in group
            for word in item.words
        }


@dataclass(frozen=True)
class Steps:
    """Ile wymagań osoba spełnia. ``must`` nie liczy krytycznych."""

    critical_missing: int = 0
    must: tuple[tuple[str, str], ...] = field(default=())
    nice: tuple[tuple[str, str], ...] = field(default=())

    @property
    def must_met(self) -> int:
        return sum(state != "none" for _, state in self.must)

    @property
    def nice_met(self) -> int:
        return sum(state != "none" for _, state in self.nice)

    @property
    def must_missing(self) -> int:
        return len(self.must) - self.must_met

    @property
    def nice_missing(self) -> int:
        return len(self.nice) - self.nice_met

    def key(self) -> tuple[int, int]:
        """Mniej braków = wyżej: najpierw „musi mieć”, potem „mile widziane”."""
        return (self.must_missing, self.nice_missing)

    def counts(self) -> dict[str, int]:
        return {
            "critical_missing": self.critical_missing,
            "must_met": self.must_met,
            "must_total": len(self.must),
            "nice_met": self.nice_met,
            "nice_total": len(self.nice),
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.counts(),
            "must": [{"label": label, "state": state} for label, state in self.must],
            "nice": [{"label": label, "state": state} for label, state in self.nice],
        }


def _plain(word: str) -> str:
    return word.rstrip("*").strip()


def _named(items: Any) -> list[str]:
    out = []
    for item in items if isinstance(items, list) else ():
        name = item.get("name") if isinstance(item, Mapping) else item
        if isinstance(name, str) and name.strip() and name.strip() not in out:
            out.append(name.strip())
    return out


def job_requirements(job: Any) -> JobRequirements:
    """Krytyczne, „musi mieć” (bez krytycznych) i „mile widziane” z profilu
    Championa, każde ze słowami swojego wiersza (wystarczy jedno)."""
    from app.services.champion_requirement_rows import label_row_words
    from app.services.critical_skills import stored_critical

    profile = getattr(job, "champion_profile", None)
    stack = profile.get("stack") if isinstance(profile, Mapping) else None
    if not isinstance(stack, Mapping):
        return JobRequirements()
    row_words = label_row_words(stack)

    def requirement(label: str) -> Requirement:
        words = row_words.get(label) or label.split(ALTERNATIVE_JOINER)
        plain = tuple(dict.fromkeys(w for w in (_plain(x) for x in words) if w))
        return Requirement(label=label, words=plain or (label,))

    critical = [c.strip() for c in (stored_critical(job) or []) if c and c.strip()]
    must = [m for m in _named(stack.get("must")) if m not in critical]
    nice = _named(stack.get("nice"))
    return JobRequirements(
        critical=tuple(requirement(x) for x in critical),
        must=tuple(requirement(x) for x in must),
        nice=tuple(requirement(x) for x in nice),
    )


_RANK = {"none": 0, "mention": 1, "experience": 2}


def _steps(reqs: JobRequirements, cid: int, evidence: Mapping) -> Steps:
    def state(item: Requirement) -> str:
        return max(
            (evidence.get((cid, word), ("none", 0))[0] for word in item.words),
            key=lambda s: _RANK.get(s, 0),
            default="none",
        )

    return Steps(
        critical_missing=sum(state(c) == "none" for c in reqs.critical),
        must=tuple((m.label, state(m)) for m in reqs.must),
        nice=tuple((n.label, state(n)) for n in reqs.nice),
    )


async def steps_for(db, job: Any, candidates: Iterable[Any]) -> dict[int, Steps]:
    """``{candidate_id: Steps}``; pusty, gdy rekrutacja nie ma wymagań."""
    from app.services.review_batch_facts import evidence_for

    reqs = job_requirements(job)
    people = list(candidates)
    if reqs.empty or not people:
        return {}
    evidence = await evidence_for(db, people, reqs.words())
    return {person.id: _steps(reqs, person.id, evidence) for person in people}


async def steps_for_jobs(
    db, boards: Mapping[int, tuple[Any, list[int]]]
) -> dict[int, dict[int, Steps]]:
    """``steps_for`` dla wielu Tablic (``{rekrutacja: (job, id)}``) przy włączonej
    porcji: osoby i oś technologii czytane raz, więc liczba zapytań nie rośnie
    z liczbą rekrutacji (``my-next-steps``)."""
    from app.services import review_batch
    from app.services.review_batch_facts import evidence_for

    out: dict[int, dict[int, Steps]] = {job_id: {} for job_id in boards}
    if not review_batch.enabled():
        return out
    live = {
        job_id: (job_requirements(job), ids)
        for job_id, (job, ids) in boards.items()
        if job is not None and ids
    }
    live = {job_id: v for job_id, v in live.items() if not v[0].empty}
    if not live:
        return out
    ids = sorted({int(cid) for _, cids in live.values() for cid in cids})
    people = (await db.scalars(select(Candidate).where(Candidate.id.in_(ids)))).all()
    by_id = {p.id: p for p in people}
    # Osoba tylko ze słowami swoich rekrutacji (loop_stall 25.11.2026: każda
    # osoba ze słowami wszystkich Tablic to 14× więcej par i 33 s CPU w pętli).
    words_of: dict[int, set[str]] = {}
    for reqs, cids in live.values():
        words = reqs.words()
        for cid in cids:
            words_of.setdefault(int(cid), set()).update(words)
    evidence = await evidence_for(
        db,
        people,
        {word for words in words_of.values() for word in words},
        labels_by_candidate=words_of,
    )
    for job_id, (reqs, cids) in live.items():
        out[job_id] = {
            cid: _steps(reqs, cid, evidence)
            for cid in dict.fromkeys(cids)
            if cid in by_id
        }
    return out


async def steps_for_ids(db, job: Any, candidate_ids: Iterable[int]) -> dict[int, Steps]:
    ids = sorted({int(cid) for cid in candidate_ids})
    if job is None or not ids or job_requirements(job).empty:
        return {}
    people = (await db.scalars(select(Candidate).where(Candidate.id.in_(ids)))).all()
    return await steps_for(db, job, people)


async def steps_if_enabled(
    db, job: Any, candidate_ids: Iterable[int]
) -> dict[int, Steps]:
    """Schodki tylko przy włączonej porcji — bez niej kolejność jak przed 23.11.2026."""
    from app.services import review_batch

    if not review_batch.enabled():
        return {}
    return await steps_for_ids(db, job, candidate_ids)
