"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Briefcase, Loader2, RefreshCw, Scale } from "lucide-react";
import {
  cortexApi,
  extractErrorMsg,
  type CortexSupplyDemand,
  type CortexSupplyDemandSkill,
} from "@/lib/api";
import { DataTable, type DataTableColumn } from "@/components/ds/DataTable";
import { EmptyState } from "@/components/ds/EmptyState";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

/**
 * Podaż/Popyt — supply (candidates with a fact) vs demand (open jobs requiring
 * the skill) per technology, sorted by gap (biggest shortage first). The gap
 * column flags positive values as "niedobór" via the warning token.
 */
export function SupplyDemandPanel() {
  const [onlyMust, setOnlyMust] = useState(false);

  const { data, isLoading, isError, error, refetch, isFetching } =
    useQuery<CortexSupplyDemand>({
      queryKey: ["cortex-supply-demand", onlyMust],
      queryFn: async () => (await cortexApi.supplyDemand(onlyMust)).data,
      placeholderData: (prev) => prev,
    });

  const columns: DataTableColumn<CortexSupplyDemandSkill>[] = useMemo(
    () => [
      {
        key: "skill",
        header: "Technologia",
        render: (row) => (
          <span className="font-medium text-foreground">{row.skill}</span>
        ),
      },
      {
        key: "supply",
        header: "Podaż",
        align: "right",
        render: (row) => (
          <span className="tabular-nums text-foreground">
            {row.supply.toLocaleString("pl-PL")}
          </span>
        ),
      },
      {
        key: "demand",
        header: "Popyt",
        align: "right",
        render: (row) => (
          <span className="tabular-nums text-foreground">
            {row.demand.toLocaleString("pl-PL")}
          </span>
        ),
      },
      {
        key: "gap",
        header: "Luka",
        align: "right",
        render: (row) => <GapCell gap={row.gap} />,
      },
    ],
    []
  );

  return (
    <div className="space-y-4">
      <div className="bg-card dark:bg-muted rounded-2xl shadow-sm p-6 space-y-4">
        <div className="flex flex-wrap items-center gap-3">
          <div className="min-w-0">
            <h3 className="font-semibold text-sm">Podaż vs popyt</h3>
            <p className="text-xs text-muted-foreground mt-0.5">
              Podaż = kandydaci z faktem dla technologii · popyt = otwarte
              rekrutacje jej wymagające · luka = popyt − podaż (dodatnia =
              niedobór).
            </p>
          </div>
          <div className="ml-auto flex items-center gap-3">
            <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground tabular-nums">
              <Briefcase className="w-3.5 h-3.5" />
              Otwarte rekrutacje:{" "}
              <span className="font-semibold text-foreground">
                {(data?.open_jobs ?? 0).toLocaleString("pl-PL")}
              </span>
            </span>
            <label className="inline-flex items-center gap-2 text-xs text-muted-foreground cursor-pointer select-none">
              <input
                type="checkbox"
                checked={onlyMust}
                onChange={(e) => setOnlyMust(e.target.checked)}
                className="rounded border-border text-primary focus:ring-primary"
              />
              Tylko must-have
            </label>
          </div>
        </div>

        {isError ? (
          <div className="space-y-3">
            <p className="flex items-center gap-2 text-sm text-destructive">
              <AlertTriangle className="w-4 h-4" />
              Nie udało się załadować danych podaż/popyt.
            </p>
            <p className="text-xs text-muted-foreground">
              {extractErrorMsg(error)}
            </p>
            <Button variant="outline" size="sm" onClick={() => refetch()}>
              <RefreshCw className="w-3.5 h-3.5" />
              Spróbuj ponownie
            </Button>
          </div>
        ) : isLoading || !data ? (
          <p className="text-sm text-muted-foreground">
            <Loader2 className="w-4 h-4 animate-spin inline mr-2" />
            Ładowanie danych podaż/popyt…
          </p>
        ) : data.skills.length === 0 ? (
          <EmptyState
            icon={Scale}
            title="Brak danych"
            description={
              onlyMust
                ? "Żadna otwarta rekrutacja nie ma technologii oznaczonych jako must-have."
                : "Brak otwartych rekrutacji z wymaganymi technologiami."
            }
          />
        ) : (
          <>
            <DataTable
              columns={columns}
              rows={data.skills}
              getRowKey={(row) => row.skill}
              empty="Brak technologii."
            />
            {isFetching ? (
              <p className="text-xs text-muted-foreground">
                <Loader2 className="w-3.5 h-3.5 animate-spin inline mr-1.5" />
                Odświeżanie…
              </p>
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}

/** Gap cell: positive = shortage (warning), negative = surplus (muted). */
function GapCell({ gap }: { gap: number }) {
  if (gap > 0) {
    return (
      <Badge variant="warning" size="sm" className="tabular-nums">
        niedobór +{gap.toLocaleString("pl-PL")}
      </Badge>
    );
  }
  if (gap < 0) {
    return (
      <span className="tabular-nums text-muted-foreground">
        nadwyżka {Math.abs(gap).toLocaleString("pl-PL")}
      </span>
    );
  }
  return <span className="tabular-nums text-muted-foreground">0</span>;
}
