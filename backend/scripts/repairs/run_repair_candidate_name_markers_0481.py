"""Jednorazowa naprawa `repair-candidate-name-markers-0481`, do 08.11.2026 krok w `entrypoint.sh`.

Znacznik w `app_settings` na produkcji: `0481_candidate_name_markers_v2` (2026-10-20).
Drugi przebieg sam kończy się na znaczniku. Uruchomienie: `python -m scripts.repairs.run_repair_candidate_name_markers_0481`.
"""
# Imię i nazwisko bez dopisków — druga runda (0481, 20.10.2026): klamry,
# nawias bez pary, „acive”, emoji, plus trzy ręczne poprawki rozjechanych pól
# zatwierdzone przez Artura. Safety-net migracji 0481 i jedyne miejsce, które
# zapisuje kolejkę indeksu zmienionych osób. Ten sam rdzeń co 0436; paragon
# w `app_settings` + advisory lock; porażka nie zapisuje niczego. Log: liczby.
import asyncio
import app.models  # noqa: F401 — komplet mapperów przed pierwszym zapytaniem
from app.core.database import AsyncSessionLocal
from app.services.candidate_name_marker_repair import (
    DETAILS_KEY_0481,
    MANUAL_FIXES_0481,
    REPAIR_MARKER_0481,
    run_candidate_name_marker_repair,
    summarize_for_log,
)

async def repair():
    async with AsyncSessionLocal() as db:
        try:
            summary = await run_candidate_name_marker_repair(
                db,
                marker=REPAIR_MARKER_0481,
                details_key=DETAILS_KEY_0481,
                manual_fixes=MANUAL_FIXES_0481,
            )
            await db.commit()
        except Exception as exc:  # noqa: BLE001 — treść błędu może nieść imiona
            await db.rollback()
            sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
            print(
                f"candidate name marker repair 0481 failed ({type(exc).__name__}, "
                f"sqlstate={sqlstate}); nothing written, next start retries"
            )
            return
    print(f"candidate name marker repair 0481: {summarize_for_log(summary)}")

asyncio.run(repair())
