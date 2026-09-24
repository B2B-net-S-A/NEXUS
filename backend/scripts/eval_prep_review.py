"""Porównanie modeli oceny prepu (F24): GPT-6 Luna vs Sonnet 5 na prawdziwych prepach.

Reguła repo: przeniesienie funkcji na Lunę wymaga pomiaru. Skrypt bierze
ostatnie ``--limit`` transkryptów z ``prep_transcripts``, puszcza każdy przez
oba modele tym samym promptem co produkcja (``prep_review``) i NICZEGO nie
zapisuje. Wypisuje JSON z miarami per model:

* ``invalid_quotes`` — punkty „omówione”, których cytat nie przeszedł walidacji
  (model wymyślił fragment rozmowy),
* ``covered`` — ile punktów model uznał za omówione (z dowodem),
* ``agreement`` — odsetek punktów, w których oba modele dały ten sam status,
* ``level`` — poziom oceny liczony przez kod z odpowiedzi każdego modelu.

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
from app.models.prep_meeting import PrepMeeting, PrepTranscript
from app.services import prep_review
from app.services.ai_models import GPT_LUNA, SONNET_5
from app.services.prompt_fencing import fence, json_for_prompt


def _prompt(job: Job, prep_no: int, items: list, text: str) -> str:
    return prep_review._PROMPT.format(
        title=job.title or "rekrutacja",
        prep_no=prep_no,
        must=fence(
            "must_haves",
            json_for_prompt(
                [{"key": i.key, "name": i.label} for i in items if i.kind == "must"]
            ),
        ),
        questions=fence(
            "client_questions",
            json_for_prompt(
                [
                    {"key": i.key, "question": i.label}
                    for i in items
                    if i.kind == "question"
                ]
            ),
        ),
        transcript=fence("transcript", text),
    )


def _score(raw: Optional[str], items: list, text: str, tr: PrepTranscript) -> dict:
    if raw is None:
        return {"ok": False}
    try:
        parsed = prep_review.parse_review(raw, items=items, transcript=text)
    except ValueError:
        return {"ok": False}
    result = prep_review.grade(
        parsed["items"],
        talk_share=float(tr.talk_share) if tr.talk_share is not None else None,
        duration_seconds=tr.duration_seconds,
        own_projects_told=parsed["own_projects"]["told"],
    )
    return {
        "ok": True,
        "statuses": {i["key"]: i["status"] for i in parsed["items"]},
        "invalid_quotes": sum(1 for i in parsed["items"] if i.get("unverified")),
        "covered": sum(1 for i in parsed["items"] if i["status"] == "covered"),
        "level": result.level,
    }


async def run(limit: int) -> list[dict]:
    rows: list[dict] = []
    async with AsyncSessionLocal() as db:
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
            items = await prep_review.build_items(db, job)
            text = tr.plain_text[: prep_review.MAX_TRANSCRIPT_CHARS]
            prompt = _prompt(job, prep.prep_no, items, text)
            scores = {}
            for model in (GPT_LUNA, SONNET_5):
                try:
                    raw = await asyncio.to_thread(
                        prep_review._call_model, [model], prompt
                    )
                except Exception:  # noqa: BLE001 — pomiar, nie produkcja
                    raw = None
                scores[model] = _score(raw, items, text, tr)
            a, b = scores[GPT_LUNA], scores[SONNET_5]
            agreement = None
            if a.get("ok") and b.get("ok") and a["statuses"]:
                same = sum(
                    1 for k, v in a["statuses"].items() if b["statuses"].get(k) == v
                )
                agreement = round(same / len(a["statuses"]), 3)
            for s in scores.values():
                s.pop("statuses", None)
            rows.append(
                {
                    "prep_meeting_id": prep.id,
                    "items": len(items),
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
