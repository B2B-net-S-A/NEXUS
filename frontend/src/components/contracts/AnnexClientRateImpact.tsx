"use client";

// Podgląd w oknie „Zmień stawkę”: które zamówienia zmieni nowa stawka klienta
// i od którego miesiąca (ticket Finansów 16.11.2026, 0724). Backend liczy to
// tą samą funkcją, którą zapisuje aneks (`order_revenue_steps`), bez zapisu.

import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { formatIsoDatePl as formatDate } from "@/lib/date-pl";

export interface AnnexClientRateImpactRow {
  order_id: number;
  order_group_id: number | null;
  order_number: string | null;
  unit: string;
  currency: string;
  effective_from: string;
  first_month: string;
  old_rate: number | string | null;
  new_rate: number | string;
  old_md_rate: number | string | null;
  new_md_rate: number | string | null;
}

const RATE = new Intl.NumberFormat("pl-PL", {
  minimumFractionDigits: 3,
  maximumFractionDigits: 3,
});
const MONTH = new Intl.DateTimeFormat("pl-PL", { month: "long", year: "numeric" });
const UNIT: Record<string, string> = { daily: "MD", hourly: "h", monthly: "mies." };

function amount(value: number | string | null): string {
  return value == null ? "—" : RATE.format(Number(value));
}

/** „1 615,050 → 1 775,050 zł/MD” — w MD, gdy zamówienie ma stawkę MD. */
export function impactRateLabel(row: AnnexClientRateImpactRow): string {
  const md = row.new_md_rate != null;
  const currency = row.currency === "PLN" ? "zł" : row.currency;
  const unit = md ? "MD" : (UNIT[row.unit] ?? row.unit);
  const from = md ? row.old_md_rate : row.old_rate;
  const to = md ? row.new_md_rate : row.new_rate;
  return `${amount(from)} → ${amount(to)} ${currency}/${unit}`;
}

/** Pierwszy miesiąc rozliczenia nową stawką, gdy aneks nie jest od 1. dnia. */
export function impactMonthNote(row: AnnexClientRateImpactRow): string | null {
  if (row.first_month === row.effective_from) return null;
  const [year, month] = row.first_month.split("-").map(Number);
  return `Zużycie MD liczy się miesiącami: nowa stawka od rozliczenia za ${MONTH.format(
    new Date(year, month - 1, 1),
  )}.`;
}

export function AnnexClientRateImpact({
  contractId,
  effectiveDate,
  newRateClient,
}: {
  contractId: number;
  effectiveDate: string;
  newRateClient: string;
}) {
  const rate = Number(newRateClient);
  const enabled = Boolean(effectiveDate) && Number.isFinite(rate) && rate > 0;
  const query = useQuery<AnnexClientRateImpactRow[]>({
    queryKey: ["annex-client-rate-impact", contractId, effectiveDate, rate],
    queryFn: () =>
      api
        .get(`/api/contracts/${contractId}/amendments/client-rate-impact`, {
          params: { effective_date: effectiveDate, new_rate_client: rate },
        })
        .then((r) => r.data),
    enabled,
  });
  if (!enabled || query.isPending) return null;
  if (query.isError) {
    return (
      <p className="text-xs text-warning" role="status">
        {apiErrorMessage(query.error, "Nie udało się sprawdzić, które zamówienia zmieni aneks.")}
      </p>
    );
  }
  const rows = query.data ?? [];
  if (rows.length === 0) {
    return (
      <p className="text-xs text-muted-foreground" data-testid="annex-impact-none">
        Żadne trwające zamówienie nie zmieni stawki — aneks zmieni tylko kontrakt.
      </p>
    );
  }
  return (
    <div
      className="rounded-lg border border-success/20 bg-success-muted px-3 py-2 text-xs text-success-muted-foreground"
      data-testid="annex-impact"
    >
      <p className="font-semibold">Zmieni się też zamówienie klienta</p>
      <ul className="mt-1 space-y-0.5">
        {rows.map((row) => (
          <li key={row.order_id} className="tabular-nums">
            {row.order_number ?? `zamówienie #${row.order_id}`}: {impactRateLabel(row)} od{" "}
            {formatDate(row.effective_from)}.
          </li>
        ))}
      </ul>
      <p className="mt-1">
        {impactMonthNote(rows[0]) ??
          "Zużycie sprzed tego dnia zostaje po starej stawce. Wpis trafi do Historii zamówienia."}
      </p>
    </div>
  );
}
