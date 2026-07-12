"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Play } from "lucide-react";
import {
  cortexApi,
  extractErrorMsg,
  type CortexBackfillStatus,
  type CortexCoverage,
} from "@/lib/api";
import { useToast } from "@/components/Toast";
import { RequireRole } from "@/components/RequireRole";
import { DataTable, type DataTableColumn } from "@/components/ds/DataTable";
import { CoverageView } from "@/components/cortex/CoverageView";
import type { CortexUnmatchedTerm } from "@/lib/api";

export function CoveragePanel() {
  const { data, isLoading } = useQuery<CortexCoverage>({
    queryKey: ["cortex-coverage"],
    queryFn: async () => (await cortexApi.coverage()).data,
  });

  if (isLoading || !data) {
    return (
      <div className="bg-card dark:bg-muted rounded-2xl shadow-sm p-6 text-sm text-muted-foreground">
        <Loader2 className="w-4 h-4 animate-spin inline mr-2" />
        Ładowanie jakości danych…
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <CoverageView data={data} />
      <RequireRole roles={["admin"]}>
        <AdminBackfillCard unmatched={data.unmatched_terms} />
      </RequireRole>
    </div>
  );
}

const UNMATCHED_COLUMNS: DataTableColumn<CortexUnmatchedTerm>[] = [
  // DS DataTable nie ma domyślnego renderera komórki — bez `render` kolumna
  // jest pusta ("Falls back to nothing when omitted").
  { key: "term", header: "Termin", render: (row) => row.term },
  {
    key: "occurrences",
    header: "Wystąpienia",
    align: "right",
    render: (row) => row.occurrences.toLocaleString("pl-PL"),
  },
  {
    key: "last_seen_at",
    header: "Ostatnio widziany",
    render: (row) =>
      row.last_seen_at
        ? new Date(row.last_seen_at).toLocaleDateString("pl-PL")
        : "—",
  },
];

function AdminBackfillCard({ unmatched }: { unmatched: CortexUnmatchedTerm[] }) {
  const toast = useToast();
  const queryClient = useQueryClient();

  const { data: status } = useQuery<CortexBackfillStatus>({
    queryKey: ["cortex-traffit-backfill-status"],
    queryFn: async () => (await cortexApi.traffitBackfillStatus()).data,
    refetchInterval: (query) => (query.state.data?.running ? 3000 : false),
  });

  const trigger = useMutation({
    mutationFn: (limit?: number) => cortexApi.triggerTraffitBackfill(limit),
    onSuccess: () => {
      toast.showSuccess("Backfill wystartował");
      queryClient.invalidateQueries({
        queryKey: ["cortex-traffit-backfill-status"],
      });
    },
    onError: (e) => toast.showError(extractErrorMsg(e)),
  });

  const running = status?.running ?? false;

  return (
    <div className="bg-card dark:bg-muted rounded-2xl shadow-sm p-6 space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h3 className="font-semibold text-sm">
          Backfill faktów z Traffita (admin)
        </h3>
        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={() => trigger.mutate(100)}
            disabled={running || trigger.isPending}
            className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs font-medium hover:bg-accent disabled:opacity-50"
          >
            Batch próbny (100)
          </button>
          <button
            onClick={() => trigger.mutate(undefined)}
            disabled={running || trigger.isPending}
            className="inline-flex items-center gap-1.5 rounded-md bg-primary text-primary-foreground px-3 py-1.5 text-xs font-medium hover:bg-primary/90 disabled:opacity-50"
          >
            {running ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Play className="w-3.5 h-3.5" />
            )}
            {running ? "Backfill trwa…" : "Pełny backfill"}
          </button>
        </div>
      </div>

      {status && (status.running || status.finished_at) ? (
        <p className="text-xs text-muted-foreground tabular-nums">
          Postęp: {status.processed.toLocaleString("pl-PL")} /{" "}
          {status.total.toLocaleString("pl-PL")} · faktów:{" "}
          {status.facts_upserted.toLocaleString("pl-PL")} · poza taksonomią:{" "}
          {status.unmatched_tokens.toLocaleString("pl-PL")} · błędów:{" "}
          {status.errors}
          {status.last_error ? ` · ostatni błąd: ${status.last_error}` : ""}
          {!status.running && status.finished_at
            ? ` · zakończono ${new Date(status.finished_at).toLocaleString("pl-PL")}`
            : ""}
        </p>
      ) : null}

      <div className="space-y-2">
        <h4 className="text-xs font-medium text-muted-foreground">
          Terminy poza taksonomią (top {unmatched.length}) — kandydaci do
          rozszerzenia słownika skills/skill_aliases
        </h4>
        <DataTable
          columns={UNMATCHED_COLUMNS}
          rows={unmatched}
          getRowKey={(row) => row.term}
          empty="Brak niedopasowanych terminów — taksonomia pokrywa surowiec."
        />
      </div>
    </div>
  );
}
