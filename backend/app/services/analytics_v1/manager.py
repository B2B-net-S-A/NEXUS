"""Manager, client, commercial and PLN finance analytics.

All monetary queries return currency-level Decimal rows.  Conversion happens
only from the local ``fx_rates`` NBP cache.  If any required historical rate is
missing the whole endpoint suppresses monetary totals instead of nominally
mixing currencies.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Generic, TypeVar

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.periods import AnalyticsPeriod, WARSAW
from app.analytics.schemas import (
    AnalyticsQualityStatus,
    ClientFinanceData,
    ClientOperationsData,
    DeliveryLeadPerformanceData,
    DeliveryLeadPerformanceRow,
    FinanceClientRow,
    FinanceClientsData,
    FinanceSummaryData,
    FinanceTotals,
    FinanceTrendData,
    FinanceTrendPoint,
    FinancialAdjustmentCreate,
    FinancialAdjustmentRow,
    FinancialAdjustmentsData,
    RecruitmentUserData,
    TenderRow,
    TendersData,
)
from app.models.user import User
from app.services.analytics_v1.finance import (
    ConvertedFinance,
    convert_currency_rows,
    load_fx_history,
    margin_percentage,
    money_string,
)
from app.services.analytics_v1.service import AnalyticsV1Service


T = TypeVar("T")


@dataclass(frozen=True)
class AnalyticsManagerResult(Generic[T]):
    data: T
    quality_status: AnalyticsQualityStatus = AnalyticsQualityStatus.complete
    warnings: tuple[str, ...] = ()


class FinancialAdjustmentNotFoundError(LookupError):
    """Raised when an adjustment id does not exist."""


class FinancialAdjustmentConflictError(ValueError):
    """Raised when an adjustment cannot transition to approved."""


_CLIENT_OPERATIONS_SQL = text(
    """
    SELECT
      cl.id AS client_id,
      coalesce(nullif(cl.display_name, ''), cl.name) AS client_name,
      (
        SELECT count(*)
        FROM jobs j
        WHERE j.client_id = cl.id
      ) AS jobs_total,
      (
        SELECT count(*)
        FROM jobs j
        WHERE j.client_id = cl.id AND j.status = 'published'
      ) AS jobs_open,
      (
        SELECT count(*)
        FROM analytics_latest_candidate_stages latest
        JOIN jobs j ON j.id = latest.job_id
        WHERE j.client_id = cl.id
      ) AS pipeline_pairs,
      (
        SELECT count(*)
        FROM analytics_first_candidate_milestones hired
        JOIN jobs j ON j.id = hired.job_id
        WHERE j.client_id = cl.id
          AND hired.stage = 'hired'
          AND hired.reached_at >= :period_start
          AND hired.reached_at < :period_end
      ) AS placements,
      (
        SELECT count(*)
        FROM contracts c
        WHERE c.client_id = cl.id
          AND c.status IN ('active', 'ending')
          AND c.start_date IS NOT NULL
          AND c.start_date <= :report_date
          AND (c.end_date IS NULL OR c.end_date >= :report_date)
      ) AS active_contracts
    FROM clients cl
    WHERE cl.id = :client_id
    """
)

_FINANCE_ROWS_SQL = """
    SELECT
      c.client_id,
      coalesce(nullif(cl.display_name, ''), cl.name) AS client_name,
      coalesce(nullif(upper(c.currency), ''), 'PLN') AS currency,
      count(*) FILTER (WHERE c.start_date IS NOT NULL) AS active_contracts,
      count(*) FILTER (
        WHERE c.start_date IS NULL
           OR c.rate_client IS NULL
           OR c.rate_candidate IS NULL
      ) AS incomplete_contracts,
      sum(
        CASE c.rate_unit::text
          WHEN 'hourly' THEN c.rate_client * c.billing_hours_per_month
          WHEN 'daily' THEN c.rate_client * 22
          ELSE c.rate_client
        END
      ) FILTER (
        WHERE c.start_date IS NOT NULL
          AND c.rate_client IS NOT NULL
          AND c.rate_candidate IS NOT NULL
      ) AS revenue,
      sum(
        CASE c.rate_unit::text
          WHEN 'hourly' THEN c.rate_candidate * c.billing_hours_per_month
          WHEN 'daily' THEN c.rate_candidate * 22
          ELSE c.rate_candidate
        END
      ) FILTER (
        WHERE c.start_date IS NOT NULL
          AND c.rate_client IS NOT NULL
          AND c.rate_candidate IS NOT NULL
      ) AS costs
    FROM contracts c
    JOIN clients cl ON cl.id = c.client_id
    WHERE c.status <> 'draft'
      AND (c.start_date IS NULL OR c.start_date <= :report_date)
      AND (
        coalesce(c.terminated_at, c.end_date) IS NULL
        OR coalesce(c.terminated_at, c.end_date) >= :report_date
      )
      {client_filter}
    GROUP BY c.client_id, cl.display_name, cl.name, c.currency
"""

_ADJUSTMENTS_SQL = text(
    """
    SELECT
      'PLN' AS currency,
      0 AS active_contracts,
      0 AS incomplete_contracts,
      0::numeric AS revenue,
      sum(amount_pln) AS costs
    FROM financial_adjustments
    WHERE status = 'approved'
      AND adjustment_date >= :period_start
      AND adjustment_date < :period_end
    """
)

_FINANCE_TREND_SQL = text(
    """
    WITH months AS (
      SELECT month_start::date,
             least(
               (month_start + interval '1 month')::date,
               CAST(:period_end AS date)
             ) - 1 AS report_date
      FROM generate_series(
        date_trunc('month', CAST(:period_start AS date)),
        date_trunc('month', CAST(:period_end AS date) - 1),
        interval '1 month'
      ) AS month_start
    )
    SELECT
      m.month_start,
      coalesce(nullif(upper(c.currency), ''), 'PLN') AS currency,
      count(c.id) FILTER (WHERE c.start_date IS NOT NULL) AS active_contracts,
      count(c.id) FILTER (
        WHERE c.start_date IS NULL
           OR c.rate_client IS NULL
           OR c.rate_candidate IS NULL
      ) AS incomplete_contracts,
      sum(
        CASE c.rate_unit::text
          WHEN 'hourly' THEN c.rate_client * c.billing_hours_per_month
          WHEN 'daily' THEN c.rate_client * 22
          ELSE c.rate_client
        END
      ) FILTER (
        WHERE c.start_date IS NOT NULL
          AND c.rate_client IS NOT NULL
          AND c.rate_candidate IS NOT NULL
      ) AS revenue,
      sum(
        CASE c.rate_unit::text
          WHEN 'hourly' THEN c.rate_candidate * c.billing_hours_per_month
          WHEN 'daily' THEN c.rate_candidate * 22
          ELSE c.rate_candidate
        END
      ) FILTER (
        WHERE c.start_date IS NOT NULL
          AND c.rate_client IS NOT NULL
          AND c.rate_candidate IS NOT NULL
      ) AS costs
    FROM months m
    LEFT JOIN contracts c
      ON c.status <> 'draft'
      AND (c.start_date IS NULL OR c.start_date <= m.report_date)
      AND (
        coalesce(c.terminated_at, c.end_date) IS NULL
        OR coalesce(c.terminated_at, c.end_date) >= m.report_date
      )
    GROUP BY m.month_start, c.currency
    ORDER BY m.month_start, currency
    """
)

_TREND_ADJUSTMENTS_SQL = text(
    """
    SELECT
      date_trunc('month', adjustment_date)::date AS month_start,
      'PLN' AS currency,
      sum(amount_pln) AS costs
    FROM financial_adjustments
    WHERE status = 'approved'
      AND adjustment_date >= :period_start
      AND adjustment_date < :period_end
    GROUP BY month_start
    """
)

_FINANCIAL_ADJUSTMENT_COLUMNS = """
    id,
    adjustment_date,
    category,
    description,
    amount,
    currency,
    amount_pln,
    fx_rate,
    fx_date,
    status,
    created_by_user_id,
    approved_by_user_id,
    approved_at,
    created_at,
    updated_at
"""

_CREATE_FINANCIAL_ADJUSTMENT_SQL = text(
    f"""
    INSERT INTO financial_adjustments (
      adjustment_date,
      category,
      description,
      amount,
      currency,
      status,
      created_by_user_id
    ) VALUES (
      :adjustment_date,
      :category,
      :description,
      :amount,
      :currency,
      'draft',
      :created_by_user_id
    )
    RETURNING {_FINANCIAL_ADJUSTMENT_COLUMNS}
    """
)

_FINANCIAL_ADJUSTMENT_FOR_UPDATE_SQL = text(
    f"""
    SELECT {_FINANCIAL_ADJUSTMENT_COLUMNS}
    FROM financial_adjustments
    WHERE id = :adjustment_id
    FOR UPDATE
    """
)

_APPROVE_FINANCIAL_ADJUSTMENT_SQL = text(
    f"""
    UPDATE financial_adjustments
    SET amount_pln = :amount_pln,
        fx_rate = :fx_rate,
        fx_date = :fx_date,
        status = 'approved',
        approved_by_user_id = :approved_by_user_id,
        approved_at = now(),
        updated_at = now()
    WHERE id = :adjustment_id AND status = 'draft'
    RETURNING {_FINANCIAL_ADJUSTMENT_COLUMNS}
    """
)

_LATEST_NBP_RATE_SQL = text(
    """
    SELECT rate_to_pln, effective_date
    FROM fx_rates
    WHERE currency = :currency
      AND source = 'NBP'
      AND effective_date <= :adjustment_date
    ORDER BY effective_date DESC
    LIMIT 1
    """
)

_TENDERS_SQL_BASE = """
    SELECT
      j.id AS job_id,
      j.title AS job_title,
      cl.id AS client_id,
      coalesce(nullif(cl.display_name, ''), cl.name) AS client_name,
      j.status::text AS status,
      j.close_reason::text AS close_reason,
      coalesce(j.closed_at, j.created_at) AS event_at
    FROM jobs j
    JOIN clients cl ON cl.id = j.client_id
    WHERE j.recruitment_type = 'tender'
      AND coalesce(j.closed_at, j.created_at) >= :period_start
      AND coalesce(j.closed_at, j.created_at) < :period_end
      {scope_filter}
    ORDER BY event_at DESC, j.id DESC
"""

_DELIVERY_LEADS_SQL_BASE = """
    WITH job_counts AS (
      SELECT delivery_lead_id AS user_id, count(*) AS jobs
      FROM jobs
      WHERE delivery_lead_id IS NOT NULL
        AND created_at >= :period_start AND created_at < :period_end
      GROUP BY delivery_lead_id
    ), milestone_counts AS (
      SELECT j.delivery_lead_id AS user_id,
        count(*) FILTER (WHERE m.stage = 'verified') AS verifications,
        count(*) FILTER (WHERE m.stage = 'cv_sent') AS recommendations,
        count(*) FILTER (WHERE m.stage = 'hired') AS placements
      FROM analytics_first_candidate_milestones m
      JOIN jobs j ON j.id = m.job_id
      WHERE j.delivery_lead_id IS NOT NULL
        AND m.reached_at >= :period_start AND m.reached_at < :period_end
      GROUP BY j.delivery_lead_id
    )
    SELECT u.id AS user_id, u.name AS user_name,
      coalesce(j.jobs, 0) AS jobs,
      coalesce(m.verifications, 0) AS verifications,
      coalesce(m.recommendations, 0) AS recommendations,
      coalesce(m.placements, 0) AS placements
    FROM users u
    LEFT JOIN job_counts j ON j.user_id = u.id
    LEFT JOIN milestone_counts m ON m.user_id = u.id
    WHERE u.is_active IS TRUE
      AND (u.role = 'delivery_lead' OR u.roles ? 'delivery_lead')
      {scope_filter}
    ORDER BY placements DESC, recommendations DESC, verifications DESC, u.name
"""


def _report_date(period: AnalyticsPeriod, generated_at: datetime) -> date:
    last_period_day = period.end.date() - timedelta(days=1)
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=WARSAW)
    return min(generated_at.astimezone(WARSAW).date(), last_period_day)


def _month_bounds(value: date) -> tuple[date, date]:
    start = value.replace(day=1)
    end = (
        date(start.year + 1, 1, 1)
        if start.month == 12
        else date(start.year, start.month + 1, 1)
    )
    return start, end


def _finance_totals(value: ConvertedFinance) -> FinanceTotals:
    return FinanceTotals(
        revenue=money_string(value.revenue),
        costs=money_string(value.costs),
        margin=money_string(value.margin),
        margin_pct=margin_percentage(value),
    )


def _blank_totals() -> FinanceTotals:
    return FinanceTotals(revenue=None, costs=None, margin=None, margin_pct=None)


def _financial_adjustment_row(row: dict) -> FinancialAdjustmentRow:
    return FinancialAdjustmentRow(
        id=int(row["id"]),
        adjustment_date=row["adjustment_date"],
        category=str(row["category"]),
        description=str(row["description"]),
        amount=money_string(Decimal(row["amount"])) or "0.00",
        currency=str(row["currency"]),
        amount_pln=money_string(
            Decimal(row["amount_pln"]) if row["amount_pln"] is not None else None
        ),
        fx_rate=(
            format(Decimal(row["fx_rate"]), "f") if row["fx_rate"] is not None else None
        ),
        fx_date=row["fx_date"],
        status=row["status"],
        created_by_user_id=int(row["created_by_user_id"]),
        approved_by_user_id=(
            int(row["approved_by_user_id"])
            if row["approved_by_user_id"] is not None
            else None
        ),
        approved_at=row["approved_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _tender_outcome(status: str, close_reason: str | None) -> str:
    if status != "closed":
        return "pending"
    if close_reason == "filled_by_us":
        return "won"
    if not close_reason:
        return "unknown"
    return "lost"


class AnalyticsManagerService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def client_operations(
        self,
        period: AnalyticsPeriod,
        *,
        client_id: int,
        generated_at: datetime,
    ) -> ClientOperationsData:
        result = await self.db.execute(
            _CLIENT_OPERATIONS_SQL,
            {
                "client_id": client_id,
                "period_start": period.start,
                "period_end": period.end,
                "report_date": _report_date(period, generated_at),
            },
        )
        row = result.mappings().one()
        return ClientOperationsData(
            client_id=int(row["client_id"]),
            client_name=str(row["client_name"]),
            jobs_total=int(row["jobs_total"] or 0),
            jobs_open=int(row["jobs_open"] or 0),
            pipeline_pairs=int(row["pipeline_pairs"] or 0),
            placements=int(row["placements"] or 0),
            active_contracts=int(row["active_contracts"] or 0),
        )

    async def _finance_rows(
        self, *, report_date: date, client_id: int | None = None
    ) -> list[dict]:
        client_filter = "AND c.client_id = :client_id" if client_id is not None else ""
        query = text(_FINANCE_ROWS_SQL.format(client_filter=client_filter))
        params: dict[str, object] = {"report_date": report_date}
        if client_id is not None:
            params["client_id"] = client_id
        result = await self.db.execute(query, params)
        return [dict(row) for row in result.mappings().all()]

    async def _convert_rows(
        self, rows: list[dict], *, report_date: date
    ) -> ConvertedFinance:
        history = await load_fx_history(
            self.db,
            currencies=(str(row.get("currency") or "PLN") for row in rows),
            through=report_date,
        )
        return convert_currency_rows(rows, report_date=report_date, history=history)

    async def finance_summary(
        self, period: AnalyticsPeriod, *, generated_at: datetime
    ) -> AnalyticsManagerResult[FinanceSummaryData]:
        report_date = _report_date(period, generated_at)
        rows = await self._finance_rows(report_date=report_date)
        adjustment_start, adjustment_end = _month_bounds(report_date)
        adjustment_result = await self.db.execute(
            _ADJUSTMENTS_SQL,
            {"period_start": adjustment_start, "period_end": adjustment_end},
        )
        rows.extend(dict(row) for row in adjustment_result.mappings().all())
        converted = await self._convert_rows(rows, report_date=report_date)
        return AnalyticsManagerResult(
            data=FinanceSummaryData(
                report_date=report_date.isoformat(),
                active_contracts=converted.active_contracts,
                incomplete_contracts=converted.incomplete_contracts,
                totals=_finance_totals(converted),
            ),
            quality_status=converted.quality_status,
            warnings=tuple(converted.warnings),
        )

    async def client_finance(
        self,
        period: AnalyticsPeriod,
        *,
        client_id: int,
        generated_at: datetime,
    ) -> AnalyticsManagerResult[ClientFinanceData]:
        report_date = _report_date(period, generated_at)
        rows = await self._finance_rows(report_date=report_date, client_id=client_id)
        converted = await self._convert_rows(rows, report_date=report_date)
        if not rows:
            # Scope guard already established existence; read the canonical name.
            name_result = await self.db.execute(
                text(
                    "SELECT coalesce(nullif(display_name, ''), name) AS name "
                    "FROM clients WHERE id = :client_id"
                ),
                {"client_id": client_id},
            )
            client_name = str(name_result.scalar_one())
        else:
            client_name = str(rows[0]["client_name"])
        return AnalyticsManagerResult(
            data=ClientFinanceData(
                client_id=client_id,
                client_name=client_name,
                active_contracts=converted.active_contracts,
                incomplete_contracts=converted.incomplete_contracts,
                totals=_finance_totals(converted),
            ),
            quality_status=converted.quality_status,
            warnings=tuple(converted.warnings),
        )

    async def finance_clients(
        self, period: AnalyticsPeriod, *, generated_at: datetime
    ) -> AnalyticsManagerResult[FinanceClientsData]:
        report_date = _report_date(period, generated_at)
        rows = await self._finance_rows(report_date=report_date)
        grouped: dict[int, list[dict]] = defaultdict(list)
        names: dict[int, str] = {}
        for row in rows:
            client_id = int(row["client_id"])
            grouped[client_id].append(row)
            names[client_id] = str(row["client_name"])

        history = await load_fx_history(
            self.db,
            currencies=(str(row.get("currency") or "PLN") for row in rows),
            through=report_date,
        )
        converted_by_client: dict[int, ConvertedFinance] = {}
        missing_currencies: set[str] = set()
        warnings: list[str] = []
        has_partial = False
        for client_id, client_rows in grouped.items():
            converted = convert_currency_rows(
                client_rows,
                report_date=report_date,
                history=history,
            )
            converted_by_client[client_id] = converted
            missing_currencies.update(converted.missing_currencies)
            has_partial = has_partial or bool(converted.incomplete_contracts)
            warnings.extend(converted.warnings)

        unavailable = bool(missing_currencies)
        clients = [
            FinanceClientRow(
                client_id=client_id,
                client_name=names[client_id],
                active_contracts=value.active_contracts,
                incomplete_contracts=value.incomplete_contracts,
                totals=_blank_totals() if unavailable else _finance_totals(value),
            )
            for client_id, value in converted_by_client.items()
        ]
        clients.sort(key=lambda item: Decimal(item.totals.margin or "0"), reverse=True)
        status = (
            AnalyticsQualityStatus.unavailable
            if unavailable
            else AnalyticsQualityStatus.partial
            if has_partial
            else AnalyticsQualityStatus.complete
        )
        return AnalyticsManagerResult(
            data=FinanceClientsData(clients=clients),
            quality_status=status,
            warnings=tuple(dict.fromkeys(warnings)),
        )

    async def finance_trend(
        self, period: AnalyticsPeriod
    ) -> AnalyticsManagerResult[FinanceTrendData]:
        # Pass calendar dates explicitly so PostgreSQL session timezone cannot
        # move Warsaw midnight into the previous UTC month.
        params = {
            "period_start": period.start.date(),
            "period_end": period.end.date(),
        }
        contract_result = await self.db.execute(_FINANCE_TREND_SQL, params)
        grouped: dict[date, list[dict]] = defaultdict(list)
        for row in contract_result.mappings().all():
            grouped[row["month_start"]].append(dict(row))
        adjustment_result = await self.db.execute(
            _TREND_ADJUSTMENTS_SQL,
            {"period_start": period.start.date(), "period_end": period.end.date()},
        )
        for row in adjustment_result.mappings().all():
            grouped[row["month_start"]].append(
                {
                    "currency": row["currency"],
                    "active_contracts": 0,
                    "incomplete_contracts": 0,
                    "revenue": Decimal("0"),
                    "costs": row["costs"],
                }
            )

        all_currencies = {
            str(row.get("currency") or "PLN")
            for month_rows in grouped.values()
            for row in month_rows
        }
        history = await load_fx_history(
            self.db,
            currencies=all_currencies,
            through=period.end.date() - timedelta(days=1),
        )
        converted: dict[date, ConvertedFinance] = {}
        missing: set[str] = set()
        warnings: list[str] = []
        has_partial = False
        for month_start, month_rows in grouped.items():
            next_month = (
                date(month_start.year + 1, 1, 1)
                if month_start.month == 12
                else date(month_start.year, month_start.month + 1, 1)
            )
            report_date = min(next_month, period.end.date()) - timedelta(days=1)
            value = convert_currency_rows(
                month_rows, report_date=report_date, history=history
            )
            converted[month_start] = value
            missing.update(value.missing_currencies)
            has_partial = has_partial or bool(value.incomplete_contracts)
            warnings.extend(value.warnings)

        unavailable = bool(missing)
        points = [
            FinanceTrendPoint(
                month=month_start.strftime("%Y-%m"),
                active_contracts=value.active_contracts,
                incomplete_contracts=value.incomplete_contracts,
                totals=_blank_totals() if unavailable else _finance_totals(value),
            )
            for month_start, value in sorted(converted.items())
        ]
        status = (
            AnalyticsQualityStatus.unavailable
            if unavailable
            else AnalyticsQualityStatus.partial
            if has_partial
            else AnalyticsQualityStatus.complete
        )
        return AnalyticsManagerResult(
            data=FinanceTrendData(months=points),
            quality_status=status,
            warnings=tuple(dict.fromkeys(warnings)),
        )

    async def financial_adjustments(
        self,
        period: AnalyticsPeriod,
        *,
        adjustment_status: str | None = None,
        limit: int = 200,
    ) -> FinancialAdjustmentsData:
        status_clause = "AND status = :adjustment_status" if adjustment_status else ""
        query = text(
            f"""
            SELECT {_FINANCIAL_ADJUSTMENT_COLUMNS}
            FROM financial_adjustments
            WHERE adjustment_date >= :period_start
              AND adjustment_date < :period_end
              {status_clause}
            ORDER BY adjustment_date DESC, id DESC
            LIMIT :limit
            """
        )
        params: dict[str, object] = {
            "period_start": period.start.date(),
            "period_end": period.end.date(),
            "limit": limit,
        }
        if adjustment_status:
            params["adjustment_status"] = adjustment_status
        result = await self.db.execute(query, params)
        return FinancialAdjustmentsData(
            adjustments=[
                _financial_adjustment_row(dict(row)) for row in result.mappings().all()
            ]
        )

    async def create_financial_adjustment(
        self,
        payload: FinancialAdjustmentCreate,
        *,
        created_by_user_id: int,
    ) -> FinancialAdjustmentRow:
        result = await self.db.execute(
            _CREATE_FINANCIAL_ADJUSTMENT_SQL,
            {
                "adjustment_date": payload.adjustment_date,
                "category": payload.category,
                "description": payload.description,
                "amount": payload.amount,
                "currency": payload.currency,
                "created_by_user_id": created_by_user_id,
            },
        )
        return _financial_adjustment_row(dict(result.mappings().one()))

    async def approve_financial_adjustment(
        self,
        adjustment_id: int,
        *,
        approved_by_user_id: int,
    ) -> FinancialAdjustmentRow:
        current_result = await self.db.execute(
            _FINANCIAL_ADJUSTMENT_FOR_UPDATE_SQL,
            {"adjustment_id": adjustment_id},
        )
        current = current_result.mappings().one_or_none()
        if current is None:
            raise FinancialAdjustmentNotFoundError(
                f"Financial adjustment {adjustment_id} not found"
            )
        if str(current["status"]) != "draft":
            raise FinancialAdjustmentConflictError(
                "Only draft financial adjustments can be approved"
            )

        currency = str(current["currency"] or "PLN").upper()
        adjustment_date = current["adjustment_date"]
        if currency == "PLN":
            fx_rate = Decimal("1")
            fx_date = adjustment_date
        else:
            rate_result = await self.db.execute(
                _LATEST_NBP_RATE_SQL,
                {"currency": currency, "adjustment_date": adjustment_date},
            )
            rate_row = rate_result.mappings().one_or_none()
            if rate_row is None:
                raise FinancialAdjustmentConflictError(
                    f"Missing cached NBP rate for {currency} on or before "
                    f"{adjustment_date}"
                )
            fx_rate = Decimal(rate_row["rate_to_pln"])
            fx_date = rate_row["effective_date"]

        amount_pln = (Decimal(current["amount"]) * fx_rate).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
        approved_result = await self.db.execute(
            _APPROVE_FINANCIAL_ADJUSTMENT_SQL,
            {
                "adjustment_id": adjustment_id,
                "amount_pln": amount_pln,
                "fx_rate": fx_rate,
                "fx_date": fx_date,
                "approved_by_user_id": approved_by_user_id,
            },
        )
        approved = approved_result.mappings().one_or_none()
        if approved is None:  # Defensive against a concurrent status change.
            raise FinancialAdjustmentConflictError(
                "Financial adjustment is no longer a draft"
            )
        return _financial_adjustment_row(dict(approved))

    async def tenders(
        self,
        period: AnalyticsPeriod,
        *,
        client_ids: set[int] | None,
        limit: int = 200,
    ) -> TendersData:
        if client_ids == set():
            return TendersData(
                total=0,
                won=0,
                lost=0,
                pending=0,
                unknown=0,
                win_rate_pct=None,
                tenders=[],
            )
        scope_filter = (
            "AND j.client_id = ANY(CAST(:client_ids AS integer[]))"
            if client_ids is not None
            else ""
        )
        query = text(_TENDERS_SQL_BASE.format(scope_filter=scope_filter))
        params: dict[str, object] = {
            "period_start": period.start,
            "period_end": period.end,
        }
        if client_ids is not None:
            params["client_ids"] = sorted(client_ids)
        result = await self.db.execute(query, params)
        tenders: list[TenderRow] = []
        counts = {"won": 0, "lost": 0, "pending": 0, "unknown": 0}
        for row in result.mappings().all():
            outcome = _tender_outcome(str(row["status"]), row["close_reason"])
            counts[outcome] += 1
            if len(tenders) < limit:
                tenders.append(
                    TenderRow(
                        job_id=int(row["job_id"]),
                        job_title=str(row["job_title"]),
                        client_id=int(row["client_id"]),
                        client_name=str(row["client_name"]),
                        outcome=outcome,
                        event_at=row["event_at"],
                    )
                )
        resolved = counts["won"] + counts["lost"]
        return TendersData(
            total=sum(counts.values()),
            won=counts["won"],
            lost=counts["lost"],
            pending=counts["pending"],
            unknown=counts["unknown"],
            win_rate_pct=(
                round(counts["won"] * 100 / resolved, 2) if resolved else None
            ),
            tenders=tenders,
        )

    async def delivery_leads(
        self, period: AnalyticsPeriod, *, delivery_lead_ids: set[int] | None
    ) -> DeliveryLeadPerformanceData:
        if delivery_lead_ids == set():
            return DeliveryLeadPerformanceData(delivery_leads=[])
        scope_filter = (
            "AND u.id = ANY(CAST(:delivery_lead_ids AS integer[]))"
            if delivery_lead_ids is not None
            else ""
        )
        query = text(_DELIVERY_LEADS_SQL_BASE.format(scope_filter=scope_filter))
        params: dict[str, object] = {
            "period_start": period.start,
            "period_end": period.end,
        }
        if delivery_lead_ids is not None:
            params["delivery_lead_ids"] = sorted(delivery_lead_ids)
        result = await self.db.execute(query, params)
        return DeliveryLeadPerformanceData(
            delivery_leads=[
                DeliveryLeadPerformanceRow(
                    user_id=int(row["user_id"]),
                    user_name=str(row["user_name"]),
                    jobs=int(row["jobs"] or 0),
                    verifications=int(row["verifications"] or 0),
                    recommendations=int(row["recommendations"] or 0),
                    placements=int(row["placements"] or 0),
                )
                for row in result.mappings().all()
            ]
        )

    async def recruitment_user(
        self,
        period: AnalyticsPeriod,
        *,
        target: User,
        generated_at: datetime,
        calls_available: bool,
    ) -> RecruitmentUserData:
        kpis = await AnalyticsV1Service(self.db).personal_kpis(
            period,
            user_id=target.id,
            primary_role=target.role.value,
            generated_at=generated_at,
            calls_available=calls_available,
        )
        return RecruitmentUserData(
            user_id=target.id,
            user_name=target.name,
            primary_role=target.role.value,
            kpis=kpis,
        )
