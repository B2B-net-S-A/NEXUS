"""Jednorazowe scalenie duplikatu PFRON 58469 → 122 (zgłoszenie z Rady, 19.11.2026).

Uruchomienie ręczne, z backendu, dopiero po zgodzie Artura na produkcji:
`python -m scripts.repairs.run_repair_pfron_client_merge`. Celowo NIE jest krokiem
`entrypoint.sh`, bo wdrożenie uruchomiłoby je bez tej zgody.

Znacznik w `app_settings`: `0738_pfron_client_merge`. Drugi przebieg sam kończy się na znaczniku.
"""

# Rekord 58469 („PFRON”, ręczny z 02.09.2026, nieaktywny) trzyma cztery zamknięte
# rekrutacje z jednym placementem i jeden kontakt; rekord 122 (Traffit, 23 kontrakty)
# ma pełną nazwę wyświetlaną. Rada (`/rada?tab=firma`) grupuje placementy po nazwie
# klienta rekrutacji, więc ten sam klient występował dwa razy. Przycisk „Scal”
# przeniósłby tylko kontakt — rekrutacje zostałyby na ukrytym wierszu — dlatego
# ta sama logika co przy Cardifie (`cardif_client_merge_repair.py`): rekrutacje
# z procesami, kontakty, materiały i alerty DL idą na 122, potem flaga scalenia.
# Zakres portfela 58469 zostaje (inwariant manifestu). Log: wyłącznie liczby i kody.
import asyncio
import app.models  # noqa: F401 — komplet mapperów przed pierwszym zapytaniem
from app.core.database import AsyncSessionLocal
from scripts.repairs.cardif_client_merge_repair import (
    CardifMergeTarget,
    run_cardif_client_merge,
    summarize_for_log,
)

MARKER = "0738_pfron_client_merge"
# Id są zaszyte, nazwa to kontrola, że na tej bazie znaczą to samo co na produkcji.
TARGET = CardifMergeTarget(source_id=58469, target_id=122, name_token="pfron")


async def repair():
    async with AsyncSessionLocal() as db:
        try:
            summary = await run_cardif_client_merge(db, target=TARGET, marker=MARKER)
            await db.commit()
        except Exception as exc:  # noqa: BLE001 — treść błędu może nieść dane osób
            await db.rollback()
            sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
            print(
                f"pfron client merge failed ({type(exc).__name__}, "
                f"sqlstate={sqlstate}); nothing written"
            )
            return
    print(f"pfron client merge: {summarize_for_log(summary)}")


if __name__ == "__main__":
    asyncio.run(repair())
