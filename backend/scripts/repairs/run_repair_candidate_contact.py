"""Jednorazowa naprawa `repair-candidate-contact`, do 08.11.2026 krok w `entrypoint.sh`.

Znacznik w `app_settings` na produkcji: `0320_contract_candidate_contact` (2026-09-17).
Drugi przebieg sam kończy się na znaczniku. Uruchomienie: `python -m scripts.repairs.run_repair_candidate_contact`.
"""
# Kontakt do konsultanta na umowie (09.2026, ticket „E-mail i telefon kandydata
# w widoku kontraktu") — jednorazowo: e-mail i telefon wpisane w „Danych
# Partnera" generatora B2B trafiają z `render_payload` na powiązany kontrakt.
# Wyłącznie poziom pierwszy kolejności źródeł: profilu kandydata NIE
# materializujemy, bo fallback do niego liczy się przy odczycie i ma zostać
# żywy. Dopasowanie tylko po `b2b_generated_contracts.contract_id` — szukanie
# po kandydacie/rekrutacji byłoby zgadywaniem. Fill-only: ręczna poprawka
# w kontrakcie wygrywa. Logika w
# `app/services/contract_candidate_contact_backfill.py`; marker w `app_settings`
# + advisory lock; wartości (PII) pod osobnym kluczem szczegółów.
# Log: wyłącznie liczby i kody powodów.
import asyncio
import sys
import app.models  # noqa: F401 — komplet mapperów przed pierwszym zapytaniem
from app.core.database import AsyncSessionLocal
from app.services.contract_candidate_contact_backfill import (
    run_candidate_contact_backfill,
    summarize_for_log,
)

async def repair():
    async with AsyncSessionLocal() as db:
        try:
            summary = await run_candidate_contact_backfill(db)
            await db.commit()
        except Exception as exc:  # noqa: BLE001 — treść błędu może nieść kontakt
            await db.rollback()
            sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
            print(
                f"candidate contact backfill failed ({type(exc).__name__}, "
                f"sqlstate={sqlstate}); nothing written, next start retries"
            )
            sys.exit(1)
    print(f"candidate contact backfill: {summarize_for_log(summary)}")

asyncio.run(repair())
