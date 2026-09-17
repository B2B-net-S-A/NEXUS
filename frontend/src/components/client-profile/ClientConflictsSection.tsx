"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { phase5Api, type ConflictRegistryParams } from "@/lib/api";
import {
  CONFLICT_STATE_BADGE,
  CONFLICT_STATE_LABELS,
  CONFLICT_TYPE_BADGE,
  conflictKeys,
  conflictState,
  conflictTypeLabel,
  formatExpiry,
} from "@/lib/conflicts";
import { cn } from "@/lib/utils";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";

export const CLIENT_CONFLICTS_LIMIT = 100;

interface Props {
  clientId: number;
}

/**
 * „Kto ma konflikt u tego klienta" — odczyt rejestru konfliktów zawężony do
 * klienta. Bez formularza: konflikt dodaje się na profilu kandydata.
 * Konflikt jest ostrzeżeniem (17.09.2026), nie blokadą.
 */
export function ClientConflictsSection({ clientId }: Props) {
  const params: ConflictRegistryParams = {
    client_id: clientId,
    state: "active",
    limit: CLIENT_CONFLICTS_LIMIT,
    offset: 0,
  };
  const query = useQuery({
    queryKey: conflictKeys.registry(params),
    queryFn: () => phase5Api.conflicts.registry(params).then((r) => r.data),
  });

  const items = query.data?.items ?? [];
  const total = query.data?.total ?? 0;
  const viewState = resolveViewState({
    isLoading: query.isPending,
    isError: query.isError,
    error: query.error,
    isEmpty: items.length === 0,
    isSuccess: query.isSuccess,
  });

  if (viewState === "loading") {
    return (
      <div className="flex justify-center py-4">
        <Loader2
          className="h-4 w-4 animate-spin text-muted-foreground"
          aria-label="Wczytywanie konfliktów"
        />
      </div>
    );
  }

  if (isBlockingViewState(viewState)) {
    return (
      <QueryStateNotice
        state={viewState as "forbidden" | "not_found" | "error"}
        onRetry={() => void query.refetch()}
        className="py-6"
      />
    );
  }

  if (viewState === "empty") {
    return (
      <p className="pt-4 text-sm text-muted-foreground">
        Żaden kandydat nie ma aktywnego konfliktu z tym klientem.
      </p>
    );
  }

  return (
    <div className="space-y-2 pt-4">
      <p className="text-xs text-muted-foreground">
        Konflikt jest ostrzeżeniem — kandydat pozostaje widoczny w wyszukiwaniu
        i można go zaproponować, z plakietką z powodem. Konflikt dodaje się
        i dezaktywuje na profilu kandydata.
      </p>
      <ul className="divide-y divide-border rounded-md border border-border">
        {items.map((row) => {
          const state = conflictState(row);
          const expiry = formatExpiry(row.expires_at);
          return (
            <li
              key={row.id}
              className="flex flex-wrap items-center gap-2 px-3 py-2 text-sm"
              data-testid={`client-conflict-${row.id}`}
            >
              <Link
                href={`/candidates/${row.candidate_id}`}
                className="font-medium text-foreground hover:underline"
              >
                {row.candidate_name || `Kandydat #${row.candidate_id}`}
              </Link>
              <span
                className={cn(
                  "rounded-full border px-2 py-0.5 text-xs",
                  CONFLICT_TYPE_BADGE[row.type] ?? "border-border bg-muted text-muted-foreground",
                )}
              >
                {conflictTypeLabel(row)}
              </span>
              {state !== "active" && (
                <span
                  className={cn(
                    "rounded-full border px-2 py-0.5 text-xs",
                    CONFLICT_STATE_BADGE[state],
                  )}
                >
                  {CONFLICT_STATE_LABELS[state]}
                </span>
              )}
              {expiry && <span className="text-xs text-muted-foreground">{expiry}</span>}
              {row.reason && (
                <span
                  className="min-w-0 flex-1 truncate text-xs text-muted-foreground"
                  title={row.reason}
                >
                  {row.reason}
                </span>
              )}
            </li>
          );
        })}
      </ul>
      {total > items.length && (
        <p className="text-xs text-muted-foreground">
          Pokazano {items.length} z {total}. Pełna lista: Ustawienia → Konflikty.
        </p>
      )}
    </div>
  );
}

export default ClientConflictsSection;
