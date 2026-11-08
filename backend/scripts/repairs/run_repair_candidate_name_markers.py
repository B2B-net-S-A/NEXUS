"""Jednorazowa naprawa `repair-candidate-name-markers`, do 08.11.2026 krok w `entrypoint.sh`.

Znacznik w `app_settings` na produkcji: `0436_candidate_name_markers` (2026-10-13).
Drugi przebieg sam kończy się na znaczniku. Uruchomienie: `python -m scripts.repairs.run_repair_candidate_name_markers`.
"""
# Imię i nazwisko bez dopisków z Traffita (0436, 13.10.2026) — jednorazowo:
# „[ACTIVE]”, „(zaakceptowany)”, „(czarna lista)” znikają z imion; najpierw
# pole (czarna lista → status, „active” → dostępność), potem tekst, dopiski
# do `cv_extracted_data.traffit_name_marker`. Safety-net migracji 0436 (prod
# alembic bywa osierocony) i jedyne miejsce, które zapisuje kolejkę indeksu
# zmienionych osób — także po korekcie wykonanej przez migrację. Logika
# w `app/services/candidate_name_marker_repair.py`; paragon w `app_settings`
# + advisory lock; porażka nie zapisuje niczego. Log: wyłącznie liczby.
import asyncio
import app.models  # noqa: F401 — komplet mapperów przed pierwszym zapytaniem
from app.core.database import AsyncSessionLocal
from app.services.candidate_name_marker_repair import (
    run_candidate_name_marker_repair,
    summarize_for_log,
)

async def repair():
    async with AsyncSessionLocal() as db:
        try:
            summary = await run_candidate_name_marker_repair(db)
            await db.commit()
        except Exception as exc:  # noqa: BLE001 — treść błędu może nieść imiona
            await db.rollback()
            sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
            print(
                f"candidate name marker repair failed ({type(exc).__name__}, "
                f"sqlstate={sqlstate}); nothing written, next start retries"
            )
            return
    print(f"candidate name marker repair: {summarize_for_log(summary)}")

asyncio.run(repair())
