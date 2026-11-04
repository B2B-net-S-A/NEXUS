"use client";

import Link from "next/link";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { Card } from "@/components/ui/card";
import { useClientSalesSummary, type OpportunityStatus } from "@/lib/api/sales";
import { formatIsoDatePl } from "@/lib/date-pl";
import { resolveViewState } from "@/lib/view-state";

import { formatDealAmount } from "./format";

const TONES: Record<OpportunityStatus, "info" | "success" | "neutral"> = {
  open: "info",
  won: "success",
  lost: "neutral",
};

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
