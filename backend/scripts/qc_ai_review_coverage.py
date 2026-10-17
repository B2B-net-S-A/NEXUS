"""Czy „BRAK POKRYCIA (kontrola AI)” ma pokrycie w źródłach — tylko odczyt, same liczby.

Pomiar 17.10.2026 (docs/qc-no-coverage-measurement.md). Dla bieżącego CV
etapu (dokument generatora z ostatnich N dni, `QC_AUDIT_DAYS`, domyślnie 30)
bierze uwagi niezależnej kontroli AI (`final_review`, prefiks „BRAK
POKRYCIA” / „NOT IN SOURCE”), wycina cytat twierdzenia i sprawdza go
w oryginale, notatkach i odpowiedziach ze screeningu — tych samych źródłach,
które czyta QC (`cv_qc.evaluate`). Każda uwaga trafia do jednego koszyka:

- `exact_original` — cytat stoi dosłownie w oryginale CV;
- `exact_notes_or_answers_only` — dosłownie tylko w notatkach albo odpowiedziach;
- `cov_ge80` / `cov_50_80` / `cov_lt50` — jaka część słów treści cytatu
  (rdzeń 5 liter) stoi w źródłach;
- `numbers_in_sources` / `no_words_not_found` — cytat bez słów (daty, liczby).

Wypisuje JSON z liczbami per pole CV. Bez treści, nazw i identyfikatorów —
repo i logi Actions są publiczne.

Uruchomienie w kontenerze backendu (sesja bazy tylko do odczytu):
    ssh … "docker exec -i <backend> python -u -" < backend/scripts/qc_ai_review_coverage.py
"""

import asyncio
import collections
import json
import os
import re
import sys

DAYS = int(os.environ.get("QC_AUDIT_DAYS", "30"))
_STOP = frozenset(
    "oraz with and the for dla przy jako into from that this nad pod przez które "
    "który która były było jest are was were have has".split()
)
_WARNING = re.compile(
    r"^(?:BRAK POKRYCIA|NOT IN SOURCE) \((?:kontrola AI|AI review)\): "
    r"(?P<field>[^—]{1,30}) —\s*[„\"](?P<snip>.*?)[”\"] \((?P<verdict>[^)]*)\)$"
)
_WORD = re.compile(r"[^\W\d_]{4,}")


def _stems(text: str) -> set[str]:
    return {w[:5] for w in _WORD.findall((text or "").casefold())}


def _bucket(snip: str, original: str, talk: str, sources: str) -> str:
    low = snip.casefold()
    if low in original.casefold():
        return "exact_original"
    if low in talk.casefold():
        return "exact_notes_or_answers_only"
    words = [s for s in _stems(snip) if s[:4] not in _STOP]
    if words:
        have = _stems(sources)
        cov = sum(s in have for s in words) / len(words)
        return "cov_ge80" if cov >= 0.8 else "cov_50_80" if cov >= 0.5 else "cov_lt50"
    nums = set(re.findall(r"\d+", snip))
    if nums and nums <= set(re.findall(r"\d+", sources)):
        return "numbers_in_sources"
    return "no_words_not_found"


async def main() -> None:
    from sqlalchemy import select, text

    from app.core.database import AsyncSessionLocal, engine
    from app.models.cv_generated_document import CvGeneratedDocument
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
        rows = (
            await db.execute(
                text(
                    "SELECT csv.candidate_stage_id, d.id FROM candidate_stage_cvs csv "
                    "JOIN cv_generated_documents d ON d.id = csv.generated_document_id "
                    "WHERE d.created_at > now() - make_interval(days => :days)"
                ),
                {"days": DAYS},
            )
        ).all()
        for done, (stage_id, doc_id) in enumerate(rows, 1):
            if done % 25 == 0:
                print(f"{done}/{len(rows)}", file=sys.stderr, flush=True)
            try:
                warnings = await db.scalar(
                    select(CvGeneratedDocument.warnings).where(
                        CvGeneratedDocument.id == doc_id
                    )
                )
                stage = await db.get(CandidateStage, stage_id)
                if stage is None:
                    continue
                await cv_qc.evaluate(db, stage)
            except Exception as exc:  # noqa: BLE001 — pomiar liczy klasy błędów
                errors[type(exc).__name__] += 1
                await db.rollback()
                await db.execute(read_only)
                await db.commit()
                continue
            data = captured.pop("data", None)
            if data is None:
                continue
            original = data.original_text or ""
            talk = "\n".join((data.notes_text or "", data.answers_text or ""))
            sources = "\n".join((original, talk))
            cv_text = cv_qc.dz.blocks_text(data.blocks)
            mismatch = cv_qc.cv_language(cv_text) != cv_qc.cv_language(original)
            counts["cvs"]["all"] += 1
            for raw in warnings if isinstance(warnings, list) else []:
                match = _WARNING.match(str(raw).strip())
                if not match:
                    continue
                snip = match.group("snip").rstrip("…").strip()
                bucket = (
                    _bucket(snip, original, talk, sources) if snip else "no_snippet"
                )
                field = match.group("field").strip()
                for key in (field, "ALL"):
                    counts[key]["warnings"] += 1
                    counts[key][bucket] += 1
                    counts[key]["snippet_le20"] += int(len(snip) <= 20)
                if mismatch:
                    counts["ALL_lang_mismatch"][bucket] += 1
    cv_qc.compute_checks = real
    await engine.dispose()
    out = {"days": DAYS, **{k: dict(v) for k, v in counts.items()}}
    print(json.dumps({**out, "errors": dict(errors)}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
