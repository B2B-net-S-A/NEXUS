"use client";

/**
 * Ustawienia → Konflikty. Rejestr konfliktów kandydat↔klient w całej bazie
 * (zakres klientów pilnuje backend tą samą bramką co profil klienta).
 *
 * Tylko odczyt: konflikt dodaje się i dezaktywuje na profilu kandydata.
 * Od 17.09.2026 konflikt jest ostrzeżeniem, nie blokadą — ten widok odpowiada
 * na pytanie „kto ma konflikt u klienta X" i „co wkrótce wygaśnie".
 */

import { useState } from "react";
import Link from "next/link";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { AlertOctagon, Loader2, Search } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import {
  phase5Api,
  type ConflictRegistryParams,
  type ConflictRegistryStateFilter,
  type ConflictType,
} from "@/lib/api";
import {
  CONFLICT_STATE_BADGE,
  CONFLICT_STATE_FILTER_LABELS,
  CONFLICT_STATE_LABELS,
  CONFLICT_TYPE_BADGE,
  CONFLICT_TYPE_LABELS,
  conflictKeys,
  conflictState,
  conflictTypeLabel,
  formatConflictDate,
  formatExpiry,
} from "@/lib/conflicts";
import { pluralPl } from "@/lib/plural-pl";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";

export const CONFLICTS_PAGE_SIZE = 50;
export const EXPIRING_WITHIN_DAYS = 30;

export function ConflictsRegistryTab() {
  const [type, setType] = useState<ConflictType | "">("");
  const [status, setStatus] = useState<ConflictRegistryStateFilter>("active");
  const [expiringSoon, setExpiringSoon] = useState(false);
  const [search, setSearch] = useState("");
  const [appliedSearch, setAppliedSearch] = useState("");
  const [page, setPage] = useState(0);

  // `expiring_within_days` wymusza po stronie backendu stan aktywny, więc chip
  // działa tylko przy filtrze „Aktywne".
  const expiringActive = status === "active" && expiringSoon;
  const params: ConflictRegistryParams = {
    type: type || undefined,
    state: status,
    expiring_within_days: expiringActive ? EXPIRING_WITHIN_DAYS : undefined,
    q: appliedSearch || undefined,
    limit: CONFLICTS_PAGE_SIZE,
    offset: page * CONFLICTS_PAGE_SIZE,
  };

  const query = useQuery({
    queryKey: conflictKeys.registry(params),
    queryFn: () => phase5Api.conflicts.registry(params).then((r) => r.data),
    placeholderData: keepPreviousData,
    staleTime: 15 * 1000,
  });

  const data = query.data;
  const viewState = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isEmpty: (data?.items.length ?? 0) === 0,
    isSuccess: query.isSuccess,
  });
  const totalPages = data
    ? Math.max(1, Math.ceil(data.total / CONFLICTS_PAGE_SIZE))
    : 1;
  const filtered = !!(type || appliedSearch || expiringActive || status !== "active");
  const typeLabels: Record<string, string> = {
    ...CONFLICT_TYPE_LABELS,
    ...(data?.type_labels ?? {}),
  };

  return (
    <div className="space-y-5 rounded-2xl border border-border bg-card p-6">
      <div className="flex items-start gap-4">
        <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-warning-muted">
          <AlertOctagon className="h-6 w-6 text-warning-muted-foreground" />
        </div>
        <div>
          <h2 className="text-base font-bold text-foreground">Konflikty z klientami</h2>
          <p className="mt-0.5 text-sm text-muted-foreground">
            Kandydaci z czarną listą klienta, NDA, konkurencją albo obecnym
            zatrudnieniem u klienta. Konflikt jest ostrzeżeniem — kandydata
            można zaproponować, rekruter widzi plakietkę z powodem. Wpisy
            dodaje się i dezaktywuje na profilu kandydata.
          </p>
        </div>
      </div>

      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          setPage(0);
          setAppliedSearch(search.trim());
        }}
      >
        <label className="space-y-1 text-xs font-medium text-muted-foreground">
          <span className="block">Typ</span>
          <select
            aria-label="Typ konfliktu"
            value={type}
            onChange={(event) => {
              setType(event.target.value as ConflictType | "");
              setPage(0);
            }}
            className="h-9 rounded-lg border border-border bg-card px-3 text-sm text-foreground"
          >
            <option value="">Wszystkie</option>
            {Object.entries(typeLabels).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className="space-y-1 text-xs font-medium text-muted-foreground">
          <span className="block">Status</span>
          <select
            aria-label="Status konfliktu"
            value={status}
            onChange={(event) => {
              setStatus(event.target.value as ConflictRegistryStateFilter);
              setPage(0);
            }}
            className="h-9 rounded-lg border border-border bg-card px-3 text-sm text-foreground"
          >
            {(Object.keys(CONFLICT_STATE_FILTER_LABELS) as ConflictRegistryStateFilter[]).map(
              (value) => (
                <option key={value} value={value}>
                  {CONFLICT_STATE_FILTER_LABELS[value]}
                </option>
              ),
            )}
          </select>
        </label>
        <label className="min-w-[14rem] flex-1 space-y-1 text-xs font-medium text-muted-foreground">
          <span className="block">Szukaj</span>
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <input
              type="search"
              aria-label="Szukaj w konfliktach"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Kandydat albo klient…"
              className="h-9 w-full rounded-lg border border-border bg-card pl-9 pr-3 text-sm text-foreground placeholder:text-muted-foreground"
            />
          </div>
        </label>
        <button
          type="submit"
          className="h-9 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90"
        >
          Szukaj
        </button>
      </form>

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          aria-pressed={expiringActive}
          disabled={status !== "active"}
          onClick={() => {
            setExpiringSoon((v) => !v);
            setPage(0);
          }}
          className={cn(
            "rounded-full border px-3 py-1 text-xs font-medium transition-colors disabled:opacity-40",
            expiringActive
              ? "border-warning/25 bg-warning-muted text-warning-muted-foreground"
              : "border-border bg-card text-muted-foreground hover:bg-muted",
          )}
        >
          Wygasają w {EXPIRING_WITHIN_DAYS} dni
        </button>
      </div>

      {viewState === "loading" && (
        <div className="flex items-center justify-center gap-2 py-8 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          Ładowanie konfliktów…
        </div>
      )}

      {(viewState === "error" || viewState === "forbidden" || viewState === "not_found") && (
        <QueryStateNotice
          state={viewState}
          description={
            viewState === "forbidden"
              ? "Rejestr konfliktów wymaga dostępu do kandydatów."
              : undefined
          }
          onRetry={() => void query.refetch()}
        />
      )}

      {viewState === "empty" && (
        <p className="py-8 text-center text-sm text-muted-foreground">
          {filtered
            ? "Brak konfliktów pasujących do filtrów."
            : "Nie ma żadnych aktywnych konfliktów."}
        </p>
      )}

      {viewState === "ready" && data && (
        <>
          <div className="overflow-x-auto rounded-xl border border-border">
            <table className="w-full text-sm">
              <thead className="bg-muted/60 text-left text-xs uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 font-medium">Kandydat</th>
                  <th className="px-3 py-2 font-medium">Klient</th>
                  <th className="px-3 py-2 font-medium">Typ</th>
                  <th className="px-3 py-2 font-medium">Stan</th>
                  <th className="px-3 py-2 font-medium">Powód</th>
                  <th className="px-3 py-2 font-medium">Historia</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {data.items.map((row) => {
                  const state = conflictState(row);
                  const expiry = formatExpiry(row.expires_at);
                  return (
                    <tr key={row.id} className="align-top" data-testid={`conflict-registry-row-${row.id}`}>
                      <td className="px-3 py-2.5">
                        <Link
                          href={`/candidates/${row.candidate_id}`}
                          className="font-medium text-foreground hover:underline"
                        >
                          {row.candidate_name || `Kandydat #${row.candidate_id}`}
                        </Link>
                      </td>
                      <td className="px-3 py-2.5 text-foreground">
                        {row.client_name || `Klient #${row.client_id}`}
                      </td>
                      <td className="px-3 py-2.5">
                        <span
                          className={cn(
                            "inline-flex whitespace-nowrap rounded-full border px-2 py-0.5 text-xs",
                            CONFLICT_TYPE_BADGE[row.type] ?? "border-border bg-muted text-muted-foreground",
                          )}
                        >
                          {typeLabels[row.type] ?? conflictTypeLabel(row)}
                        </span>
                      </td>
                      <td className="px-3 py-2.5">
                        <span
                          className={cn(
                            "inline-flex rounded-full border px-2 py-0.5 text-xs",
                            CONFLICT_STATE_BADGE[state],
                          )}
                        >
                          {CONFLICT_STATE_LABELS[state]}
                        </span>
                        {expiry && (
                          <p className="mt-1 whitespace-nowrap text-xs text-muted-foreground">
                            {expiry}
                          </p>
                        )}
                      </td>
                      <td className="min-w-[12rem] px-3 py-2.5 text-muted-foreground">
                        {row.reason || "—"}
                      </td>
                      <td className="min-w-[12rem] px-3 py-2.5 text-xs text-muted-foreground">
                        <p>
                          Dodano {formatConflictDate(row.created_at) ?? "—"}
                          {row.created_by_name ? ` · ${row.created_by_name}` : ""}
                        </p>
                        {state === "inactive" && (
                          <p className="mt-1">
                            Dezaktywowano {formatConflictDate(row.deactivated_at) ?? "—"}
                            {row.deactivated_by_name ? ` · ${row.deactivated_by_name}` : ""}
                            {row.deactivation_reason ? ` — ${row.deactivation_reason}` : ""}
                          </p>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="flex items-center justify-between text-sm text-muted-foreground">
            <span>
              {data.total} {pluralPl(data.total, "konflikt", "konflikty", "konfliktów")} · strona{" "}
              {page + 1} z {totalPages}
            </span>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                disabled={page === 0}
                className="h-8 rounded-md border border-border px-3 disabled:opacity-40"
              >
                Poprzednia
              </button>
              <button
                type="button"
                onClick={() => setPage((p) => p + 1)}
                disabled={page + 1 >= totalPages}
                className="h-8 rounded-md border border-border px-3 disabled:opacity-40"
              >
                Następna
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

export default ConflictsRegistryTab;
