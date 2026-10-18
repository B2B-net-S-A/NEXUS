"use client";

import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { Network } from "lucide-react";

import { EmptyState } from "@/components/ds/EmptyState";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import { useStructureSummary, type StructureSummaryRow } from "@/lib/api/structure-proposals";
import { CALM_SUBLINE } from "@/lib/calm-table";
import { useUrlSyncedState, useUrlWriter } from "@/lib/url-selection";
import { countPl } from "@/lib/plural-pl";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";

import { StructureProposalsPanel } from "./StructureProposalsPanel";

function rowLine(row: StructureSummaryRow): string {
  if (!row.without_manager) return "każdy ma menedżera";
  const parts = [`${row.open} do uzupełnienia`];
  if (row.certain) parts.push(countPl(row.certain, "pewna", "pewne", "pewnych"));
  if (row.uncertain) parts.push(`${row.uncertain} do sprawdzenia`);
  if (row.none) parts.push(`${row.none} bez propozycji`);
  return parts.join(" · ");
}

/**
 * Opieka · „Struktura u klientów” (decyzja Artura 18.10.2026): klienci z zakresu
 * (Delivery Lead — swój portfel) z licznikami konsultantów bez menedżera i panel
 * propozycji wybranego klienta (`?client=`). Dzwonek „Uzupełnij strukturę
 * u klienta” prowadzi tutaj.
 */
export function StructureTab() {
  const searchParams = useSearchParams();
  const { replaceUrl } = useUrlWriter();
  const query = useStructureSummary();
  const rows = query.data?.items ?? [];
  // Dzwonek prowadzi z `?client=<id>`; wybór z listy zapisuje się w adresie.
  const [picked, setPicked] = useUrlSyncedState(searchParams?.get("client") ?? null, null);
  const fromUrl = Number(picked ?? "");
  const selectedId =
    Number.isFinite(fromUrl) && fromUrl > 0
      ? fromUrl
      : (rows.find((row) => row.open > 0)?.client_id ?? rows[0]?.client_id ?? null);
  const select = (clientId: number) => {
    setPicked(String(clientId));
    const params = new URLSearchParams(window.location.search);
    params.set("client", String(clientId));
    replaceUrl(`${window.location.pathname}?${params.toString()}`);
  };
  const view = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
    isEmpty: rows.length === 0,
  });
  if (view === "loading") {
    return <p className="p-4 text-sm text-muted-foreground">Liczę propozycje struktury…</p>;
  }
  if (view === "forbidden" || view === "not_found" || view === "error") {
    return (
      <QueryStateNotice
        state={view === "error" ? "error" : view}
        description={apiErrorMessage(query.error, "Nie możesz zobaczyć struktury u klientów.")}
        onRetry={() => query.refetch()}
      />
    );
  }
  if (view === "empty") {
    return (
      <EmptyState
        icon={Network}
        title="Brak klientów z aktywnymi konsultantami"
        description="Klienci pojawią się tu razem z aktywnymi kontraktami w Twoim zakresie."
      />
    );
  }
  const totals = query.data!.totals;
  return (
    <div className="grid gap-3 xl:grid-cols-[300px_minmax(0,1fr)]">
      <nav
        aria-label="Klienci"
        className="max-h-[calc(100dvh-14rem)] overflow-y-auto rounded-lg border border-border bg-card"
      >
        <p className="border-b border-border/60 px-3 py-2 text-xs text-muted-foreground">
          {totals.open
            ? `${countPl(totals.open, "konsultant", "konsultantów", "konsultantów")} bez menedżera u ${countPl(rows.filter((r) => r.open).length, "klienta", "klientów", "klientów")}`
            : "Każdy konsultant ma wskazanego menedżera"}
        </p>
        <ul>
          {rows.map((row) => (
            <li key={row.client_id} className="border-b border-border/60 last:border-b-0">
              <button
                type="button"
                aria-current={row.client_id === selectedId ? "true" : undefined}
                onClick={() => select(row.client_id)}
                className={cn(
                  "block w-full px-3 py-1.5 text-left text-sm hover:bg-muted/60",
                  row.client_id === selectedId && "bg-muted",
                )}
              >
                <span className="font-medium">{row.client_name}</span>
                <span className={CALM_SUBLINE}>{rowLine(row)}</span>
              </button>
            </li>
          ))}
        </ul>
      </nav>
      <div className="min-w-0 space-y-2">
        {selectedId ? (
          <>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="font-display text-base font-semibold">
                {rows.find((row) => row.client_id === selectedId)?.client_name ?? "Klient"}
              </h2>
              <Button variant="outline" size="sm" asChild>
                <Link href={`/clients/${selectedId}?tab=struktura`}>Struktura u klienta</Link>
              </Button>
            </div>
            <StructureProposalsPanel key={selectedId} clientId={selectedId} />
          </>
        ) : null}
      </div>
    </div>
  );
}
