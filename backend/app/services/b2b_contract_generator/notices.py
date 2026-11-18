"""Adres do formalnych doręczeń przypięty do wydanej umowy B2B."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.b2b_generated_contract import B2BGeneratedContract

NOTICES_SNAPSHOT_FIELD = "_b2b_notices_email"
LEGACY_NOTICES_EMAIL = "administracja@b2bnetwork.pl"


def issued_notices_email(snapshot: dict | None) -> str:
    # Wiersze sprzed zapisywania adresu wydano z dotychczasowym kontaktem.
    return (snapshot or {}).get(NOTICES_SNAPSHOT_FIELD, LEGACY_NOTICES_EMAIL)


async def contract_notices_email(
    db: AsyncSession, contract_id: int, *, number: str | None, default: str
) -> str:
    """Rejestr lub pierwsze wydanie. Bez śladu kopia zachowuje stary adres,
    a pierwsze wystawienie zapisuje aktualny adres w zdarzeniu.
    """
    linked = select(
        B2BGeneratedContract.render_payload[NOTICES_SNAPSHOT_FIELD].as_string()
    ).where(
        B2BGeneratedContract.contract_id == contract_id,
        B2BGeneratedContract.contract_status != "cancelled",
    )
    if number:
        linked = linked.where(B2BGeneratedContract.contract_number == number)
    generated = (
        await db.execute(linked.order_by(B2BGeneratedContract.id.desc()).limit(1))
    ).first()
    if generated is not None:
        return generated[0] or LEGACY_NOTICES_EMAIL

    first_issue = (
        await db.execute(
            select(Activity.details[NOTICES_SNAPSHOT_FIELD].as_string())
            .where(
                Activity.entity_type == "contract",
                Activity.entity_id == contract_id,
                Activity.action == "b2b_generated",
            )
            .order_by(Activity.id)
            .limit(1)
        )
    ).first()
    if first_issue is not None:
        return first_issue[0] or LEGACY_NOTICES_EMAIL
    return default
