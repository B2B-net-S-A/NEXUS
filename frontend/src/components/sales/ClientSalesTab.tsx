"use client";

import Link from "next/link";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { Card } from "@/components/ui/card";
import {
  useClientSalesSummary,
  type ClientSalesSummary,
  type OpportunityStatus,
} from "@/lib/api/sales";
import { countPl } from "@/lib/plural-pl";
import { warsawToday } from "@/lib/warsaw-date";
import { formatIsoDatePl } from "@/lib/date-pl";
import { resolveViewState } from "@/lib/view-state";

import { formatDealAmount } from "./format";

const TONES: Record<OpportunityStatus, "info" | "success" | "neutral"> = {
  open: "info",
  won: "success",
  lost: "neutral",
};

type Opportunity = ClientSalesSummary["opportunities"][number];

/** Suma kwot jednej waluty; przy kilku walutach kwoty nie sumujemy (bez kursu). */
function sumText(items: readonly Opportunity[]): string | null {
  const currencies = new Set(items.map((item) => item.currency));
  if (items.length === 0 || currencies.size !== 1) return null;
  const total = items.reduce((sum, item) => sum + (Number(item.value) || 0), 0);
  return formatDealAmount(total, items[0].currency);
}

/**
 * Trzy liczby nad listą szans (makieta 19.11.2026, wariant A ekranu
 * „Sprzedaż”): otwarte, wygrane w ostatnich 12 miesiącach i przegrane
 * — odpowiedź na „czy coś się dzieje” bez czytania listy.
 */
export function salesFigures(opportunities: readonly Opportunity[], today: string = warsawToday()) {
  const yearAgo = Date.parse(`${today}T00:00:00Z`) - 365 * 86_400_000;
  const open = opportunities.filter((item) => item.status === "open");
  const won = opportunities.filter(
    (item) => item.status === "won" && item.won_at !== null && Date.parse(item.won_at) >= yearAgo,
  );
  const lost = opportunities.filter((item) => item.status === "lost");
  return {
    open: { count: open.length, value: sumText(open) },
    won: { count: won.length, value: sumText(won) },
    lost: { count: lost.length, value: sumText(lost) },
  };
}

/** Zakładka „Sprzedaż” w karcie klienta: powiązana firma sprzedaży i jej szanse. */
export function ClientSalesTab({ clientId }: { clientId: number }) {
  const summary = useClientSalesSummary(clientId);
  const data = summary.data;
  const state = resolveViewState({
    isLoading: summary.isLoading,
    error: summary.error,
    isSuccess: summary.isSuccess,
    isEmpty: !data?.company,
  });
  if (state === "loading") return <p className="p-4 text-sm text-muted-foreground">Wczytywanie sprzedaży…</p>;
  if (state === "forbidden" || state === "not_found" || state === "error") {
    return <QueryStateNotice state={state} onRetry={() => void summary.refetch()} />;
  }
  if (state === "empty" || !data?.company) {
    return (
      <p className="p-4 text-sm text-muted-foreground">
        Ten klient nie jest powiązany z firmą w kartotece sprzedaży. Powiązanie ustawia handlowiec na
        karcie firmy w Sprzedaży.
      </p>
    );
  }
  return (
    <Card className="space-y-3 p-4">
      <p className="text-sm">
        Firma w Sprzedaży:{" "}
        <Link href={`/sales/companies/${data.company.id}`} className="text-primary hover:underline">
          {data.company.name}
        </Link>
      </p>
      {data.opportunities.length > 0 ? <SalesFigures opportunities={data.opportunities} /> : null}
      {data.opportunities.length === 0 ? (
        <p className="text-sm text-muted-foreground">Brak szans przy tej firmie.</p>
      ) : (
        <ul className="divide-y divide-border">
          {data.opportunities.map((opp) => (
            <li key={opp.id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
              <Link href={`/sales/opportunities/${opp.id}`} className="font-medium text-foreground hover:underline">
                {opp.title}
              </Link>
              <span className="flex items-center gap-3 text-xs text-muted-foreground">
                <StatusDot tone={TONES[opp.status]}>{opp.stage}</StatusDot>
                {opp.won_at && <span>wygrana {formatIsoDatePl(opp.won_at)}</span>}
                <span className="tabular-nums text-foreground">{formatDealAmount(opp.value, opp.currency)}</span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function SalesFigures({ opportunities }: { opportunities: readonly Opportunity[] }) {
  const figures = salesFigures(opportunities);
  const cells = [
    { label: countPl(figures.open.count, "otwarta szansa", "otwarte szanse", "otwartych szans"), ...figures.open },
    { label: "wygranych w 12 miesięcy", ...figures.won },
    { label: countPl(figures.lost.count, "przegrana", "przegrane", "przegranych"), ...figures.lost },
  ];
  return (
    <dl className="grid grid-cols-3 gap-3" data-testid="client-sales-figures">
      {cells.map((cell) => (
        <div key={cell.label} className="rounded-lg border border-border px-3 py-2">
          <dt className="text-xs text-muted-foreground">{cell.label.replace(/^\d+\s/, "")}</dt>
          <dd className="text-lg font-semibold tabular-nums text-foreground">
            {cell.count}
            {cell.value && cell.count > 0 ? (
              <span className="ml-1.5 text-xs font-normal text-muted-foreground">{cell.value}</span>
            ) : null}
          </dd>
        </div>
      ))}
    </dl>
  );
}
