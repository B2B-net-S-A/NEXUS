"""Dokończenie scalenia PFRON 58469 → 122: dokumenty, potem flaga scalenia (19.11.2026).

Uruchomienie ręczne, z backendu, po wdrożeniu tej zmiany:
`python -m scripts.repairs.run_repair_pfron_client_merge_documents`.
Celowo NIE jest krokiem `entrypoint.sh` (zmiana na produkcji tylko po zgodzie Artura).

Znacznik w `app_settings`: `0738_pfron_client_merge_documents`.
"""

# Pierwszy bieg (`run_repair_pfron_client_merge`) przepiął rekrutacje, kontakt
# i alerty, ale nie ukrył duplikatu: na 58469 zostało 11 wygenerowanych CV
# (`cv_generated_documents`) i 1 dokument poczty zamówień (`order_mail_documents`),
# których reguła „scalony wiersz nie trzyma żywych danych” nie puszcza. Oba to
# wyłącznie przypisanie do klienta, więc tu zmienia się tylko `client_id`
# i dopiero potem wołamy tę samą korektę, która ustawia flagę scalenia.
# Log: wyłącznie liczby i kody.
import asyncio
from datetime import datetime, timezone

from sqlalchemy import text

import app.models  # noqa: F401 — komplet mapperów przed pierwszym zapytaniem
from app.core.database import AsyncSessionLocal
from app.models.app_setting import AppSetting
from scripts.repairs.cardif_client_merge_repair import (
    merge_client,
    summarize_for_log,
)
from scripts.repairs.run_repair_pfron_client_merge import TARGET

MARKER = "0738_pfron_client_merge_documents"
_DOCUMENT_TABLES = ("cv_generated_documents", "order_mail_documents")
_IDENTITY_SQL = text(
    "SELECT count(*) FROM clients WHERE id IN (:s, :t) "
    "AND lower(coalesce(name, '')) LIKE :token"
)


async def run_pfron_documents_merge(db, *, target=TARGET, marker=MARKER):
    """``None`` = już wykonane. Wołający commituje."""

    await db.execute(text("SET LOCAL lock_timeout = '15s'"))
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": marker}
    )
    if await db.get(AppSetting, marker) is not None:
        return None

    params = {"s": target.source_id, "t": target.target_id}
    # Id są zaszyte; bez zgodnej nazwy obu stron nic nie ruszamy
    # (merge_client i tak zrobi własną kontrolę tożsamości).
    identity = await db.scalar(
        _IDENTITY_SQL, {**params, "token": f"%{target.name_token.lower()}%"}
    )
    moved: dict[str, int] = {}
    if identity == 2:
        for table in _DOCUMENT_TABLES:
            result = await db.execute(
                text(f"UPDATE {table} SET client_id = :t WHERE client_id = :s"),
                params,
            )
            moved[table] = int(result.rowcount or 0)
    summary = await merge_client(db, target)
    summary["documents_moved"] = moved
    summary["executed_at"] = datetime.now(timezone.utc).isoformat()
    # Pominięty bieg nie zostawia znacznika: pierwszy bieg zapisał „skipped”
    # i zablokował ponowienie po poprawieniu konfiguracji.
    if summary["skipped"] is None:
        db.add(AppSetting(key=marker, value=summary))
        await db.flush()
    return summary


async def repair():
    async with AsyncSessionLocal() as db:
        try:
            summary = await run_pfron_documents_merge(db)
            await db.commit()
        except Exception as exc:  # noqa: BLE001 — treść błędu może nieść dane osób
            await db.rollback()
            sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
            print(
                f"pfron documents merge failed ({type(exc).__name__}, "
                f"sqlstate={sqlstate}); nothing written"
            )
            return
    if summary is None:
        print("pfron documents merge: already applied")
        return
    print(
        f"pfron documents merge: {summarize_for_log(summary)}, "
        f"documents {sum(summary['documents_moved'].values())}"
    )


if __name__ == "__main__":
    asyncio.run(repair())
