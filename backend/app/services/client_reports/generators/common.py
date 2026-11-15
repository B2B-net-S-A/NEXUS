"""Wspólne odczyty generatorów: kontrakty i zamówienia klienta w okresie."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

#: Kontrakt „świadczył usługi” w okresie: podpisany (bez szkiców i czekających
#: na podpis) i nie unieważniony.
SERVING_STATUSES = ("active", "ending", "ended")


@dataclass(frozen=True)
class ContractInPeriod:
    contract_id: int
    person: str
    start_date: Optional[date]
    end_date: Optional[date]
    role: Optional[str]
    project_name: Optional[str]
    order_number: Optional[str]
    rate_client: Optional[Decimal]
    rate_client_currency: Optional[str]
    rate_unit: Optional[str]
    candidate_id: Optional[int] = None


_CONTRACTS_SQL = text(
    """
    SELECT k.id, trim(concat_ws(' ', c.name, c.lastname)) AS person,
           k.start_date, k.end_date, j.title AS role, k.project_name,
           (SELECT coalesce(g.order_number, o.title)
              FROM client_orders o
              LEFT JOIN client_order_groups g ON g.id = o.order_group_id
             WHERE o.contract_id = k.id
               AND (o.start_date IS NULL OR o.start_date <= :end)
               AND (o.end_date IS NULL OR o.end_date >= :start)
             ORDER BY o.start_date DESC NULLS LAST, o.id DESC
             LIMIT 1) AS order_number,
           k.rate_client, coalesce(k.rate_client_currency, k.currency) AS rate_client_currency,
           k.rate_unit::text AS rate_unit, k.candidate_id
      FROM contracts k
      JOIN candidates c ON c.id = k.candidate_id
      LEFT JOIN jobs j ON j.id = k.job_id
     WHERE k.client_id = :client_id
       AND k.voided_at IS NULL
       AND k.status::text IN ('active', 'ending', 'ended')
       AND k.start_date IS NOT NULL
       AND k.start_date <= :end
       AND (k.end_date IS NULL OR k.end_date >= :start)
     ORDER BY person, k.start_date
    """
)


async def contracts_in_period(
    db: AsyncSession, client_id: int, start: date, end: date
) -> list[ContractInPeriod]:
    result = await db.execute(
        _CONTRACTS_SQL, {"client_id": client_id, "start": start, "end": end}
    )
    return [ContractInPeriod(*row) for row in result.all()]
