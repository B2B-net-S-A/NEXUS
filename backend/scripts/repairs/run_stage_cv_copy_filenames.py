"""Jednorazowa naprawa `stage-cv-copy-filenames`, do 08.11.2026 krok w `entrypoint.sh`.

Znacznik w `app_settings` na produkcji: `stage_cv_copy_filename_2026_10` (2026-10-15).
Drugi przebieg sam kończy się na znaczniku. Uruchomienie: `python -m scripts.repairs.run_stage_cv_copy_filenames`.
"""
# Nazwy plików kopii CV etapu (15.10.2026, zgłoszenie DL: „jak pobieram, mam
# dwa razy numer”) — jednorazowo: kopia (plik Word, CV z profilu, CV z innej
# rekrutacji) liczyła nazwę z surowego tytułu rekrutacji, więc u PKO numer
# zapytania stał w nazwie dwa razy, a nazwa jest zamrożona na zatwierdzonych
# wersjach. Podmienia tylko nazwę zbudowaną ze starego wzoru; treść, sumy
# kontrolne i `updated_at` bez zmian. Po kroku „client-reference-from-title”,
# bo nazwa roli i numer projektu czytają `client_reference`. Reguła:
# `scripts/repairs/stage_cv_copy_filename_repair.py`. Marker w `app_settings`
# + advisory lock → drugi start kończy się od razu. Log: same liczby.
import asyncio
import app.models  # noqa: F401 — komplet mapperów przed pierwszym zapytaniem
from app.core.database import AsyncSessionLocal
from scripts.repairs.stage_cv_copy_filename_repair import rename_copy_filenames

async def rename():
    async with AsyncSessionLocal() as db:
        try:
            receipt = await rename_copy_filenames(db)
            await db.commit()
        except Exception:
            await db.rollback()
            raise
    print(f"stage cv copy filenames: {receipt or 'nothing to do'}")

asyncio.run(rename())
