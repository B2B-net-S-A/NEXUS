"""Pomiar karty z notatki (0421) na notatkach-kartach z produkcji — przed włączeniem.

Uruchamiany w kontenerze backendu przy WYŁĄCZONYM
``RECOMMENDATION_CARD_ASSIST_ENABLED``: woła tę samą funkcję
``recommendation_card_assist.model_reading`` co trasa, ale niczego nie
zapisuje w karcie ani w arkuszu — jedyny zapis to telemetria kosztu AI.

Próbka: najnowsze notatki rodzaju „karta” (wzór działu) z rekrutacją, której
Profil Championa ma pytania screeningowe. Reguła wzoru (bez AI) daje dla nich
„prawdę”, więc mierzymy, czy model — czytający notatkę jak tekst swobodny —
dochodzi do tych samych wartości:

* zgodność pola: wartość modelu zawiera wartość reguły albo odwrotnie
  (po złożeniu znaków),
* pola odrzucone przez ugruntowanie (cytat spoza notatki, nowy fakt),
* odpowiedzi i zdania (ułożone / odrzucone przez regułę faktów).

Wynik na ekran: same liczby. Próbki zdań (z hasłami) idą do pliku ``--out``
w kontenerze — do ręcznego przejrzenia, nie do logu workflowu.

    python -m scripts.eval_recommendation_card_note --limit 40 --out /tmp/card_note_eval.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter

from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.models.job import Job
from app.services import recommendation_card_assist as assist
from app.services import screening_sheets
from app.services.recommendation_card_parser import parse_card

_SAMPLE_SQL = """
    SELECT n.id, n.content, n.job_id
    FROM notes n
    JOIN jobs j ON j.id = n.job_id
    WHERE n.kind = 'card'
      AND n.parent_note_id IS NULL
      AND n.source_deleted_at IS NULL
      AND length(n.content) > 200
      AND jsonb_typeof(j.champion_profile) = 'object'
    ORDER BY n.created_at DESC
    LIMIT :n
"""


async def main(limit: int, out_path: str) -> None:
    totals: Counter[str] = Counter()
    per_field: Counter[str] = Counter()
    samples: list[dict] = []
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(text(_SAMPLE_SQL), {"n": limit * 3})).all()
    picked = 0
    for note_id, content, job_id in rows:
        if picked >= limit:
            break
        async with AsyncSessionLocal() as db:
            job = await db.get(Job, job_id)
            questions = screening_sheets.question_texts(job.champion_profile)
            if not questions:
                continue
            picked += 1
            note = assist.note_text(content)
            rule = parse_card(note)
            stats: dict[str, int] = {}
            try:
                fields, answers = await assist.model_reading(
                    db,
                    user_id=None,
                    note=note,
                    questions=questions,
                    language="pl",
                    stats=stats,
                )
            except Exception as exc:  # noqa: BLE001 — liczymy awarie
                totals["model_failed"] += 1
                totals[f"model_failed:{type(exc).__name__}"] += 1
                continue
            totals.update(stats)
            totals["notes"] += 1
            for key in assist.MODEL_FIELDS:
                truth = assist._fold(str((rule.fields.get(key) or {}).get("raw") or ""))
                got = assist._fold(str((fields.get(key) or {}).get("value") or ""))
                if truth and got:
                    agree = truth in got or got in truth
                    per_field[f"{key}:{'agree' if agree else 'differ'}"] += 1
                elif truth:
                    per_field[f"{key}:missed"] += 1
                elif got:
                    per_field[f"{key}:extra"] += 1
            for qid, answer in answers.items():
                if len(samples) < 30:
                    samples.append(
                        {
                            "note_id": note_id,
                            "question": questions[qid],
                            "keywords": answer["quote"],
                            "sentence": answer["sentence"],
                            "problem": answer["problem"],
                        }
                    )
    print(
        json.dumps(
            {"totals": totals, "fields": per_field}, ensure_ascii=False, indent=2
        )
    )
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(samples, handle, ensure_ascii=False, indent=2)
    print(f"Próbki odpowiedzi: {len(samples)} → {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--out", default="/tmp/card_note_eval.json")
    args = parser.parse_args()
    asyncio.run(main(args.limit, args.out))
