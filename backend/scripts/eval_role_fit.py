"""Test oceny roli przez model (F51 ``role_fit``) na historii decyzji porcji.

Pytanie Artura z 16.11.2026: czy karty, którym model da „nie”, mają wyraźnie
niższe „Pasuje” niż reszta? Dopiero wtedy ocena wchodzi do porcji.

Decyzja = wyjście karty od systemu (``recruitment_processes.entry_source =
'system'``) z „Nowych” (``new``/``posting``) ruchem człowieka. Poprzedni etap
liczy ``lag()`` po CAŁEJ historii pary w ``candidate_stages``, nie od okna dat.
Etykieta: Pasuje = wyjście nie do ``rejected``; Nie pasuje = ``rejected``
z powodem z ``autofill_feedback.reason``.

Próba warstwowa ze stałym ziarnem: ``--pasuje`` decyzji Pasuje, WSZYSTKIE
„Inna rola” (``other_level_or_role``) i ``--other-rejected`` pozostałych
odrzuceń. Wagi warstw przenoszą odsetki z próby na całą historię.

Jedyny zapis do bazy to telemetria AI (``ai_feature``). Bez imion, nazwisk,
firm i stawek w wyniku: same id, werdykty i uzasadnienia modelu.

    python -m scripts.eval_role_fit --out /tmp/role_fit.json           # bieg
    python -m scripts.eval_role_fit --analyze /tmp/role_fit.json      # same liczby
    python -m scripts.eval_role_fit --dry-run                         # prompt, bez modelu
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import random
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Iterable, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from starlette.concurrency import run_in_threadpool

from app.core.database import AsyncSessionLocal
from app.models.job import Job
from app.services import role_fit
from app.services.ai_models import model_for
from app.services.ai_quota import ai_feature

ROLE_REASON = "other_level_or_role"
SEED = 20261116
_TZ = ZoneInfo("Europe/Warsaw")

_DECISIONS_SQL = """
WITH s AS (
    SELECT cs.id, cs.job_id, cs.candidate_id, cs.stage::text AS stage,
           cs.moved_by, cs.moved_at,
           lag(cs.stage::text) OVER (
               PARTITION BY cs.job_id, cs.candidate_id ORDER BY cs.moved_at, cs.id
           ) AS prev
    FROM candidate_stages cs
)
SELECT s.id AS stage_id, s.job_id, s.candidate_id, s.stage, s.moved_at,
       (rp.entry_meta->>'score')::float AS score,
       f.reason
FROM s
JOIN recruitment_processes rp
  ON rp.job_id = s.job_id AND rp.candidate_id = s.candidate_id
LEFT JOIN LATERAL (
    SELECT af.reason FROM autofill_feedback af
    WHERE af.job_id = s.job_id AND af.candidate_id = s.candidate_id
    ORDER BY (af.stage_id = s.id) DESC NULLS LAST,
             abs(extract(epoch FROM af.created_at - s.moved_at))
    LIMIT 1
) f ON s.stage = 'rejected'
WHERE rp.entry_source = 'system'
  AND s.moved_by IS NOT NULL
  AND s.prev IN ('new', 'posting')
  AND s.stage NOT IN ('new', 'posting')
ORDER BY s.id
"""


@dataclass
class Decision:
    stage_id: int
    job_id: int
    candidate_id: int
    stage: str
    day: str  # dzień decyzji w kalendarzu firmy
    score: float
    reason: Optional[str]
    stratum: str = ""
    weight: float = 1.0
    verdict: Optional[str] = None
    why: str = ""

    @property
    def fits(self) -> bool:
        return self.stage != "rejected"


def stratum_of(d: Decision) -> str:
    if d.fits:
        return "pasuje"
    return "inna_rola" if d.reason == ROLE_REASON else "inne_odrzucenie"


def sample(
    decisions: list[Decision], *, pasuje: int, other_rejected: int, seed: int = SEED
) -> list[Decision]:
    """Warstwy: ``pasuje``, wszystkie ``inna_rola``, ``other_rejected`` reszty
    odrzuceń. Każda wybrana decyzja dostaje wagę ``N_warstwy / n_warstwy``."""
    rng = random.Random(seed)
    by: dict[str, list[Decision]] = defaultdict(list)
    for d in decisions:
        d.stratum = stratum_of(d)
        by[d.stratum].append(d)
    want = {
        "pasuje": pasuje,
        "inna_rola": len(by["inna_rola"]),
        "inne_odrzucenie": other_rejected,
    }
    out: list[Decision] = []
    for name, n in want.items():
        pool = sorted(by[name], key=lambda d: d.stage_id)
        picked = rng.sample(pool, min(n, len(pool)))
        for d in picked:
            d.weight = len(pool) / len(picked)
        out.extend(picked)
    return sorted(out, key=lambda d: d.stage_id)


# ── Liczby ──────────────────────────────────────────────────────────────────


def _wilson(k: int, n: int) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    z = 1.96
    p = k / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (mid - half, mid + half)


def _pct(part: float, whole: float) -> Optional[float]:
    return round(100.0 * part / whole, 1) if whole else None


def verdict_table(rows: Iterable[Decision]) -> list[dict[str, Any]]:
    """Werdykt × (n, % Pasuje w próbie i ważony, % „Inna rola” wśród odrzuceń)."""
    rows = [r for r in rows]
    out = []
    for verdict in (*role_fit.VERDICTS, None):
        group = [r for r in rows if r.verdict == verdict]
        if not group:
            continue
        fits = sum(r.fits for r in group)
        w_all = sum(r.weight for r in group)
        w_fit = sum(r.weight for r in group if r.fits)
        rejected = [r for r in group if not r.fits]
        role = [r for r in rejected if r.reason == ROLE_REASON]
        lo, hi = _wilson(fits, len(group))
        out.append(
            {
                "verdict": verdict or "błąd",
                "n": len(group),
                "pasuje_proba_pct": _pct(fits, len(group)),
                "pasuje_proba_ci95": (round(100 * lo, 1), round(100 * hi, 1)),
                "pasuje_wazone_pct": _pct(w_fit, w_all),
                "udzial_w_historii_pct": _pct(w_all, sum(r.weight for r in rows)),
                "inna_rola_wsrod_odrzucen_proba_pct": _pct(len(role), len(rejected)),
                "inna_rola_wsrod_odrzucen_wazone_pct": _pct(
                    sum(r.weight for r in role), sum(r.weight for r in rejected)
                ),
            }
        )
    return out


def verdict_by_stratum(rows: Iterable[Decision]) -> dict[str, dict[str, int]]:
    out: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        out[r.stratum][r.verdict or "błąd"] += 1
    return {k: dict(v) for k, v in out.items()}


_RANK = {"tak": 0, "pokrewna": 1, None: 1, "nie": 2}


def simulate(rows: Iterable[Decision]) -> dict[str, Any]:
    """Rekrutacja-dzień: górne 50% kart wg dzisiejszego wyniku wobec kolejności
    z oceną roli (``tak`` → ``pokrewna``/brak oceny → ``nie``, w środku wynik)
    i wobec porcji bez ``nie``. Liczy się tylko grupa z ≥ 2 kartami w próbie."""
    groups: dict[tuple[int, str], list[Decision]] = defaultdict(list)
    for r in rows:
        groups[(r.job_id, r.day)].append(r)
    acc: dict[str, list[float]] = {
        k: [0.0, 0.0, 0.0, 0.0] for k in ("wynik", "z_rola", "bez_nie")
    }  # [n, pasuje, waga, waga_pasuje]
    used = 0
    lost_fit = [0, 0.0]
    for cards in groups.values():
        if len(cards) < 2:
            continue
        used += 1
        k = math.ceil(len(cards) / 2)
        by_score = sorted(cards, key=lambda c: (-c.score, c.candidate_id))
        by_role = sorted(
            cards, key=lambda c: (_RANK[c.verdict], -c.score, c.candidate_id)
        )
        no_nie = [c for c in by_role if c.verdict != "nie"]
        for name, top in (
            ("wynik", by_score[:k]),
            ("z_rola", by_role[:k]),
            ("bez_nie", no_nie[:k]),
        ):
            a = acc[name]
            a[0] += len(top)
            a[1] += sum(c.fits for c in top)
            a[2] += sum(c.weight for c in top)
            a[3] += sum(c.weight for c in top if c.fits)
        for c in cards:
            if c.verdict == "nie" and c.fits:
                lost_fit[0] += 1
                lost_fit[1] += c.weight
    total_fit_w = sum(r.weight for r in rows if r.fits)
    return {
        "grup": used,
        **{
            name: {
                "kart": int(a[0]),
                "pasuje_proba_pct": _pct(a[1], a[0]),
                "pasuje_wazone_pct": _pct(a[3], a[2]),
            }
            for name, a in acc.items()
        },
        "pasuje_z_nie_w_grupach": lost_fit[0],
        "pasuje_z_nie_wazone_pct_wszystkich_pasuje": _pct(
            sum(r.weight for r in rows if r.fits and r.verdict == "nie"), total_fit_w
        ),
    }


def analyze(rows: list[Decision]) -> dict[str, Any]:
    return {
        "proba": len(rows),
        "ocenione": sum(r.verdict is not None for r in rows),
        "warstwy": dict(Counter(r.stratum for r in rows)),
        "werdykty_w_warstwach": verdict_by_stratum(rows),
        "tabela": verdict_table(rows),
        "symulacja": simulate(rows),
    }


# ── Dane z bazy ─────────────────────────────────────────────────────────────


async def load_decisions() -> list[Decision]:
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(text(_DECISIONS_SQL))).mappings().all()
        await db.rollback()
    return [
        Decision(
            stage_id=int(r["stage_id"]),
            job_id=int(r["job_id"]),
            candidate_id=int(r["candidate_id"]),
            stage=str(r["stage"]),
            day=r["moved_at"].astimezone(_TZ).date().isoformat(),
            score=float(r["score"] or 0.0),
            reason=r["reason"],
        )
        for r in rows
    ]


async def _job_blocks(job_ids: set[int]) -> dict[int, str]:
    from app.services import champion_view
    from app.services.cv_quoted_evidence import critical_labels

    async with AsyncSessionLocal() as db:
        jobs = (await db.scalars(select(Job).where(Job.id.in_(job_ids)))).all()
        briefs = dict(
            (
                await db.execute(
                    text(
                        "SELECT job_id, one_liner FROM job_plain_briefs "
                        "WHERE job_id = ANY(:ids) AND status = 'ready'"
                    ),
                    {"ids": list(job_ids)},
                )
            ).all()
        )
        out = {}
        for job in jobs:
            project = champion_view.project(job.champion_profile)
            about = " ".join(
                str(p)
                for p in (project.get("about"), project.get("responsibilities"))
                if p
            )
            out[job.id] = role_fit.job_block(
                job.working_title or job.title or "",
                one_liner=briefs.get(job.id),
                about=about,
                critical=critical_labels(job),
            )
        await db.rollback()
    return out


async def _people(candidate_ids: set[int]) -> dict[int, tuple[Any, Optional[str]]]:
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                text(
                    "SELECT id, experience, cv_extracted_data->>'current_position' "
                    "FROM candidates WHERE id = ANY(:ids)"
                ),
                {"ids": list(candidate_ids)},
            )
        ).all()
        await db.rollback()
    return {int(r[0]): (r[1], r[2]) for r in rows}


async def prompts_for(rows: list[Decision]) -> dict[int, str]:
    jobs = await _job_blocks({r.job_id for r in rows})
    people = await _people({r.candidate_id for r in rows})
    out = {}
    for r in rows:
        experience, position = people.get(r.candidate_id, (None, None))
        person = role_fit.person_block(
            experience, position, as_of=date.fromisoformat(r.day)
        )
        out[r.stage_id] = role_fit.prompt(jobs.get(r.job_id, ""), person)
    return out


async def _assess_one(user_prompt: str) -> Optional[role_fit.RoleFit]:
    async with AsyncSessionLocal() as db:
        async with ai_feature(db, role_fit.FEATURE, user_id=None):
            await db.commit()
            return await run_in_threadpool(role_fit.assess, user_prompt)


async def run(rows: list[Decision], *, max_calls: int, concurrency: int) -> int:
    prompts = await prompts_for(rows)
    # Ta sama para w tym samym dniu = ten sam prompt — jedno wywołanie.
    unique: dict[str, list[Decision]] = defaultdict(list)
    for r in rows:
        unique[prompts[r.stage_id]].append(r)
    todo = list(unique.items())[:max_calls]
    sem = asyncio.Semaphore(concurrency)
    calls = 0

    async def one(user_prompt: str, targets: list[Decision]) -> None:
        nonlocal calls
        async with sem:
            calls += 1
            result = await _assess_one(user_prompt)
        for t in targets:
            t.verdict = result.verdict if result else None
            t.why = result.why if result else ""

    await asyncio.gather(*(one(p, t) for p, t in todo))
    return calls


# ── Wejście ─────────────────────────────────────────────────────────────────


def _print(summary: dict[str, Any]) -> None:
    print(json.dumps(summary, ensure_ascii=False, indent=2))


async def main(args: argparse.Namespace) -> None:
    if args.analyze:
        with open(args.analyze, encoding="utf-8") as fh:
            data = json.load(fh)
        rows = [Decision(**r) for r in data["rows"]]
        _print({**data.get("meta", {}), **analyze(rows)})
        return
    decisions = await load_decisions()
    print(
        f"decyzji: {len(decisions)}, Pasuje: {sum(d.fits for d in decisions)}, "
        f"Inna rola: {sum(d.reason == ROLE_REASON for d in decisions)}"
    )
    rows = sample(
        decisions,
        pasuje=args.pasuje,
        other_rejected=args.other_rejected,
        seed=args.seed,
    )
    print(f"próba: {len(rows)} {dict(Counter(r.stratum for r in rows))}")
    if args.dry_run:
        prompts = await prompts_for(rows[:3])
        for r in rows[:3]:
            print(f"--- stage {r.stage_id} ({r.stratum})\n{prompts[r.stage_id]}\n")
        return
    if len(rows) > args.max_calls:
        print(f"UWAGA: próba {len(rows)} > limit {args.max_calls}, ostatnie bez oceny")
    calls = await run(rows, max_calls=args.max_calls, concurrency=args.concurrency)
    meta = {
        "model": model_for(role_fit.FEATURE),
        "wywolan": calls,
        "ziarno": args.seed,
        "decyzji_w_historii": len(decisions),
        "pasuje_w_historii": sum(d.fits for d in decisions),
        "inna_rola_w_historii": sum(d.reason == ROLE_REASON for d in decisions),
        "ostatnia_decyzja": max(d.day for d in decisions),
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(
            {"meta": meta, "rows": [asdict(r) for r in rows]}, fh, ensure_ascii=False
        )
    _print({**meta, **analyze(rows)})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pasuje", type=int, default=150)
    parser.add_argument("--other-rejected", type=int, default=60)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--max-calls", type=int, default=350)
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--out", default="/tmp/role_fit_eval.json")
    parser.add_argument(
        "--analyze", help="policz liczby z zapisanego wyniku, bez modelu"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="pokaż 3 prompty, bez modelu"
    )
    asyncio.run(main(parser.parse_args()))
