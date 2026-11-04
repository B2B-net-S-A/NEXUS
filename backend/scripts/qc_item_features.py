"""Cechy pozycji QC CV na produkcji — tylko odczyt, same liczby (17.10.2026).

Pomiar z docs/qc-no-coverage-measurement.md. Bieżący kod QC dla par
z przebiegiem w ostatnich N dniach (`QC_AUDIT_DAYS`, domyślnie 30); dla
pozycji sprawdzeń, które najczęściej zostają w panelu albo stoją za
obejściami, liczy:

- `must_in_cv` — rozkład `fix` (`ask_candidate` = „brak w CV, w oryginale
  i w rozmowie — zapytaj kandydata”, `ai` = jest w oryginale, `None` =
  kandydat mówił w rozmowie);
- `no_unsupported` — czy termin stoi w źródłach choćby luźno (podciąg), must
  czy nice i w jakiej sekcji CV stoi (lista umiejętności, podsumowanie, rola);
- `title_matches_role` — jaka część słów oczekiwanego tytułu stoi w nagłówku.

Bez treści, nazw i identyfikatorów — repo i logi Actions są publiczne.

Uruchomienie w kontenerze backendu (sesja bazy tylko do odczytu):
    ssh … "docker exec -i <backend> python -u -" < backend/scripts/qc_item_features.py
"""

import asyncio
import collections
import json
import os
import re
import sys

DAYS = int(os.environ.get("QC_AUDIT_DAYS", "30"))
_SENIORITY = frozenset(
    "senior junior mid regular lead starszy młodszy principal expert ekspert".split()
)
_SKILL_SECTIONS = frozenset({"skills", "technologies"})


def _words(text: str) -> set[str]:
    return set(re.findall(r"[^\W\d_]{3,}|\d+", (text or "").casefold()))


def _loose_in(text: str, req) -> bool:
    low = (text or "").casefold()
    names = (*req.terms, *req.alternatives, req.label)
    return any(name and name.casefold() in low for name in names)


async def main() -> None:
    from sqlalchemy import text

    from app.core.database import AsyncSessionLocal, engine
    from app.models.recruitment_pipeline import CandidateStage
    from app.services import cv_qc
    from app.services.skill_taxonomy_loader import refresh_alias_map

    await refresh_alias_map()
    real = cv_qc.compute_checks
    captured: dict = {}

    def spy(data):
        captured["data"] = data
        return real(data)

    cv_qc.compute_checks = spy
    counts: dict[str, collections.Counter] = collections.defaultdict(
        collections.Counter
    )
    errors: collections.Counter = collections.Counter()
    read_only = text("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
    async with AsyncSessionLocal() as db:
        await db.execute(read_only)
        await db.commit()
        stage_ids = (
            (
                await db.execute(
                    text(
                        "SELECT DISTINCT candidate_stage_id FROM cv_qc_runs "
                        "WHERE created_at > now() - make_interval(days => :days) "
                        "AND candidate_stage_id IS NOT NULL"
                    ),
                    {"days": DAYS},
                )
            )
            .scalars()
            .all()
        )
        for done, stage_id in enumerate(stage_ids, 1):
            if done % 50 == 0:
                print(f"{done}/{len(stage_ids)}", file=sys.stderr, flush=True)
            try:
                stage = await db.get(CandidateStage, stage_id)
                if stage is None:
                    continue
                _src, checks, _notes = await cv_qc.evaluate(db, stage)
            except Exception as exc:  # noqa: BLE001 — pomiar liczy klasy błędów
                errors[type(exc).__name__] += 1
                await db.rollback()
                await db.execute(read_only)
                await db.commit()
                continue
            data = captured.pop("data", None)
            if data is None or not data.has_cv:
                continue
            counts["pairs"]["all"] += 1
            sources = "\n".join(
                (
                    data.original_text or "",
                    data.notes_text or "",
                    data.answers_text or "",
                )
            )
            reqs = {r.label: r for r in (*data.must, *data.nice, *data.critical)}
            must = {r.label for r in data.must}
            sections = cv_qc._effective_sections(data.blocks)
            by_key = {check["key"]: check for check in checks}
            for item in by_key.get("must_in_cv", {}).get("items") or []:
                counts["must_in_cv"]["items"] += 1
                counts["must_in_cv"][f"fix:{item.get('fix')}"] += 1
            for item in by_key.get("no_unsupported", {}).get("items") or []:
                bucket = counts["no_unsupported"]
                bucket["items"] += 1
                req = reqs.get(item.get("requirement"))
                if req is None:
                    continue
                bucket["must" if req.label in must else "nice"] += 1
                bucket["loose_substring_in_sources"] += int(_loose_in(sources, req))
                found = {
                    str(section)
                    for block, section in zip(data.blocks, sections)
                    if cv_qc.match_in(block.text, req)
                }
                bucket["only_skills_sections"] += int(
                    bool(found) and found <= _SKILL_SECTIONS
                )
                for section in found:
                    counts["no_unsupported_sections"][section] += 1
            head = _words(" ".join(b.text for b in data.blocks[:3]))
            for _item in by_key.get("title_matches_role", {}).get("items") or []:
                best = 0.0
                for title in data.expected_titles:
                    wanted = [w for w in _words(title) if w not in _SENIORITY]
                    if wanted:
                        best = max(best, sum(w in head for w in wanted) / len(wanted))
                bucket = counts["title_matches_role"]
                bucket["items"] += 1
                bucket[
                    "overlap_0"
                    if best == 0
                    else "overlap_lt50"
                    if best < 0.5
                    else "overlap_50_75"
                    if best < 0.75
                    else "overlap_ge75"
                ] += 1
    cv_qc.compute_checks = real
    await engine.dispose()
    out = {"days": DAYS, **{k: dict(v) for k, v in counts.items()}}
    print(json.dumps({**out, "errors": dict(errors)}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
