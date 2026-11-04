"""Pomiar oceny prepu (F24): GPT-6 Luna vs Sonnet 5 na prawdziwych prepach.

Reguła repo: zmiana promptu albo modelu funkcji wymaga pomiaru. Skrypt bierze
ostatnie ``--limit`` transkryptów z ``prep_transcripts``, puszcza każdy przez
oba modele tym samym promptem co produkcja (``prep_review.build_prompt``,
obowiązujące Ustawienia → Ocena prepów) i NICZEGO nie zapisuje. Wypisuje JSON
z miarami per model:

* ``invalid_quotes`` — punkty, których cytat nie przeszedł walidacji (model
  wymyślił fragment rozmowy),
* ``grades`` — ile odpowiedzi kandydata model dał jako mocne / ogólne /
  słabe / nie było,
* ``agreement`` — odsetek punktów (tematy i odpowiedzi), w których oba
  modele dały to samo,
* ``total`` i ``level`` — wynik i poziom liczone przez kod,
* ``followup`` — ile punktów trafiłoby do notatki na Prep 2,
* ``old_level`` — poziom zapisany dziś w ``prep_reviews`` (do porównania).

Uruchomienie w kontenerze backendu (bez nazwisk w wyjściu — same ID)::

    python -m scripts.eval_prep_review --limit 20
"""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Optional

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.job import Job
from app.models.prep_meeting import PrepMeeting, PrepReview, PrepTranscript
from app.services import prep_review, prep_review_config
from app.services.ai_models import GPT_LUNA, SONNET_5
from app.services.prep_review_scoring import (
    GRADES,
    followup_items,
    parse_review,
    score_review,
)


def _score(
    raw: Optional[str], items: list, text: str, tr: PrepTranscript, prep_no: int, config
) -> dict:
    if raw is None:
        return {"ok": False}
    try:
        parsed = parse_review(raw, items=items, transcript=text)
    except ValueError:
        return {"ok": False}
    score = score_review(
        parsed,
        config=config,
        prep_no=prep_no,
        talk_share=float(tr.talk_share) if tr.talk_share is not None else None,
        duration_seconds=tr.duration_seconds,
    )
    answers = parsed["answers"]
    return {
        "ok": True,
        "values": {
            **{t["key"]: t["status"] for t in parsed["topics"]},
            **{a["key"]: a["grade"] for a in answers},
        },
        "invalid_quotes": sum(
            1 for x in [*parsed["topics"], *answers] if x.get("unverified")
        ),
        "grades": {g: sum(1 for a in answers if a["grade"] == g) for g in GRADES},
        "total": score.total,
        "level": score.level,
        "caps": score.caps,
        "followup": len(followup_items(parsed, config)) if prep_no == 1 else None,
    }


async def run(limit: int) -> list[dict]:
    rows: list[dict] = []
    async with AsyncSessionLocal() as db:
        config, version = await prep_review_config.current(db)
        transcripts = (
            await db.scalars(
                select(PrepTranscript).order_by(PrepTranscript.id.desc()).limit(limit)
            )
        ).all()
        for tr in transcripts:
            prep = await db.get(PrepMeeting, tr.prep_meeting_id)
            job = await db.get(Job, tr.job_id)
            if prep is None or job is None:
                continue
            old = await db.scalar(
                select(PrepReview).where(PrepReview.prep_meeting_id == prep.id)
            )
            prep1 = await prep_review._prep1_review(db, prep)
            base = await prep_review.build_items(
                db, job, max_questions=config.max_client_questions
            )
            if prep.prep_no == 2:
                base = [i for i in base if i.kind == "question"]
            items = [
                *prep_review.topic_items(config, prep.prep_no),
                *base,
                *prep_review.followup_answer_items(
                    prep_review.prep1_followup_of(prep1)
                ),
            ]
            text = tr.plain_text[: prep_review.MAX_TRANSCRIPT_CHARS]
            prompt = prep_review.build_prompt(
                title=job.title or "",
                prep_no=prep.prep_no,
                items=items,
                config=config,
                transcript=text,
            )
            scores = {}
            for model in (GPT_LUNA, SONNET_5):
                try:
                    raw = await asyncio.to_thread(
                        prep_review._call_model, [model], prompt
                    )
                except Exception:  # noqa: BLE001 — pomiar, nie produkcja
                    raw = None
                scores[model] = _score(raw, items, text, tr, prep.prep_no, config)
            a, b = scores[GPT_LUNA], scores[SONNET_5]
            agreement = None
            if a.get("ok") and b.get("ok") and a["values"]:
                same = sum(1 for k, v in a["values"].items() if b["values"].get(k) == v)
                agreement = round(same / len(a["values"]), 3)
            for s in scores.values():
                s.pop("values", None)
            rows.append(
                {
                    "prep_meeting_id": prep.id,
                    "prep_no": prep.prep_no,
                    "minutes": round(tr.duration_seconds / 60),
                    "speakers": len(tr.speakers or []),
                    "items": len(items),
                    "config_version": version,
                    "old_level": old.level if old else None,
                    "agreement": agreement,
                    **scores,
                }
            )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(max(1, min(args.limit, 200)))), indent=2))


if __name__ == "__main__":
    main()
