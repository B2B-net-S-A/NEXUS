"""Jednorazowa naprawa `client-reference-from-title`, do 08.11.2026 krok w `entrypoint.sh`.

Znacznik w `app_settings` na produkcji: `client_reference_from_title_2026_10` (2026-10-15).
Drugi przebieg sam kończy się na znaczniku. Uruchomienie: `python -m scripts.repairs.run_client_reference_from_title`.
"""
# Numer u klienta z nazwy od klienta (15.10.2026, prośba DL Nordei) —
# jednorazowo: backfill 0380 znał tylko ZOB, więc „(42946)”, „RITM…”,
# „PKN…/EITE…” zostały wyłącznie w nazwie. Pola nie nadpisuje (poza kodem
# PEP/TP z odczytu maila i nawiasem wokół numeru), `updated_at` nie podbija,
# potem przelicza automatyczne tytuły dla rekrutera, których to dotyczy.
# Reguła: `app/services/job_working_title.py`. Marker w `app_settings`
# + advisory lock → drugi start kończy się od razu. Log: same liczby.
import asyncio
import app.models  # noqa: F401 — komplet mapperów przed pierwszym zapytaniem
from app.core.database import AsyncSessionLocal
from app.services.job_working_title import fill_client_references_from_titles

async def fill():
    async with AsyncSessionLocal() as db:
        try:
            receipt = await fill_client_references_from_titles(db)
            await db.commit()
        except Exception:
            await db.rollback()
            raise
    print(f"client reference from title: {receipt or 'nothing to do'}")

asyncio.run(fill())
