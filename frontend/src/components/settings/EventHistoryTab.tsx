"use client";

/**
 * Ustawienia → Historia zdarzeń. Ogólnosystemowy dziennik krytycznych operacji
 * (usunięcia i zablokowane próby usunięć) — widoczny dla ról Admin i Finanse.
 *
 * Tylko odczyt. Wpisy przeżywają usunięcie obiektu, którego dotyczą, więc
 * etykieta obiektu to jego opis Z CHWILI zdarzenia, a nie link — obiektu może
 * już nie być.
 */

import { useState } from "react";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { History, Loader2, Search } from "lucide-react";

import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { pluralPl } from "@/lib/plural-pl";
import { resolveViewState } from "@/lib/view-state";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";

export interface CriticalEventItem {
  id: number;
  occurred_at: string;
  event_type: string;
  event_label: string;
  entity_type: string;
  entity_type_label: string;
  entity_id: number | null;
  entity_label: string | null;
  outcome: "executed" | "blocked";
  outcome_label: string;
  reason_code: string | null;
  reason: string | null;
  actor_user_id: number | null;
  actor_name: string | null;
  actor_email: string | null;
  client_id: number | null;
  client_name: string | null;
  details: Record<string, unknown>;
}

interface CriticalEventList {
  items: CriticalEventItem[];
  total: number;
  limit: number;
  offset: number;
  entity_types: Record<string, string>;
  event_types: Record<string, string>;
  outcomes: Record<string, string>;
}

const PAGE_SIZE = 50;

const dateTimeFormat = new Intl.DateTimeFormat("pl-PL", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

function formatWhen(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : dateTimeFormat.format(date);
}

export function EventHistoryTab() {
  const [entityType, setEntityType] = useState("");
  const [outcome, setOutcome] = useState("");
  const [search, setSearch] = useState("");
  const [appliedSearch, setAppliedSearch] = useState("");
  const [page, setPage] = useState(0);

  const query = useQuery({
    queryKey: ["event-history", entityType, outcome, appliedSearch, page],
    queryFn: () =>
      api
        .get<CriticalEventList>("/api/settings/event-history", {
          params: {
            entity_type: entityType || undefined,
            outcome: outcome || undefined,
            q: appliedSearch || undefined,
            limit: PAGE_SIZE,
            offset: page * PAGE_SIZE,
          },
        })
        .then((r) => r.data),
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
  const totalPages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;
  const filtered = !!(entityType || outcome || appliedSearch);

  return (
    <div className="bg-card rounded-2xl border border-border p-6 space-y-5">
      <div className="flex items-start gap-4">
        <div className="w-12 h-12 rounded-xl bg-primary/10 flex items-center justify-center shrink-0">
          <History className="w-6 h-6 text-primary" />
        </div>
        <div>
          <h2 className="text-base font-bold text-foreground">Historia zdarzeń</h2>
          <p className="text-sm text-muted-foreground mt-0.5">
            Krytyczne operacje w systemie: usunięcia klientów, kontraktorów,
            kontraktów, umów i zamówień — także próby zablokowane. Wpisy
            zostają trwale, również po usunięciu obiektu.
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
        <label className="text-xs font-medium text-muted-foreground space-y-1">
          <span className="block">Obiekt</span>
          <select
            aria-label="Rodzaj obiektu"
            value={entityType}
            onChange={(event) => {
              setEntityType(event.target.value);
              setPage(0);
            }}
            className="h-9 px-3 border border-border rounded-lg text-sm bg-card text-foreground"
          >
            <option value="">Wszystkie</option>
            {Object.entries(data?.entity_types ?? {}).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs font-medium text-muted-foreground space-y-1">
          <span className="block">Wynik</span>
          <select
            aria-label="Wynik operacji"
            value={outcome}
            onChange={(event) => {
              setOutcome(event.target.value);
              setPage(0);
            }}
            className="h-9 px-3 border border-border rounded-lg text-sm bg-card text-foreground"
          >
            <option value="">Wszystkie</option>
            <option value="executed">Wykonano</option>
            <option value="blocked">Zablokowano</option>
          </select>
        </label>
        <label className="text-xs font-medium text-muted-foreground space-y-1 flex-1 min-w-[14rem]">
          <span className="block">Szukaj</span>
          <div className="relative">
            <Search className="w-4 h-4 text-muted-foreground absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="search"
              aria-label="Szukaj w historii zdarzeń"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Obiekt, klient, osoba, powód…"
              className="w-full h-9 pl-9 pr-3 border border-border rounded-lg text-sm bg-card text-foreground placeholder:text-muted-foreground"
            />
          </div>
        </label>
        <button
          type="submit"
          className="h-9 px-4 rounded-lg text-sm font-medium bg-primary text-primary-foreground hover:bg-primary/90"
        >
          Szukaj
        </button>
      </form>

      {viewState === "loading" && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground py-8 justify-center">
          <Loader2 className="w-4 h-4 animate-spin" />
          Ładowanie historii zdarzeń…
        </div>
      )}

      {(viewState === "error" || viewState === "forbidden") && (
        <QueryStateNotice
          state={viewState}
          description={
            viewState === "forbidden"
              ? "Historia zdarzeń jest dostępna dla ról Admin i Finanse."
              : undefined
          }
          onRetry={() => void query.refetch()}
        />
      )}

      {viewState === "empty" && (
        <p className="text-sm text-muted-foreground text-center py-8">
          {filtered
            ? "Brak zdarzeń pasujących do filtrów."
            : "Nie odnotowano jeszcze żadnych zdarzeń."}
        </p>
      )}

      {viewState === "ready" && data && (
        <>
          <div className="overflow-x-auto rounded-xl border border-border">
            <table className="w-full text-sm">
              <thead className="bg-muted/60 text-left text-xs uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 font-medium whitespace-nowrap">Kiedy</th>
                  <th className="px-3 py-2 font-medium">Kto</th>
                  <th className="px-3 py-2 font-medium">Operacja</th>
                  <th className="px-3 py-2 font-medium">Obiekt</th>
                  <th className="px-3 py-2 font-medium">Wynik</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {data.items.map((item) => (
                  <tr key={item.id} className="align-top">
                    <td className="px-3 py-2.5 whitespace-nowrap text-muted-foreground">
                      {formatWhen(item.occurred_at)}
                    </td>
                    <td className="px-3 py-2.5">
                      <p className="font-medium text-foreground">
                        {item.actor_name ?? "System"}
                      </p>
                      {item.actor_email && (
                        <p className="text-xs text-muted-foreground">{item.actor_email}</p>
                      )}
                    </td>
                    <td className="px-3 py-2.5 text-foreground">{item.event_label}</td>
                    <td className="px-3 py-2.5">
                      <p className="text-foreground">
                        {item.entity_label ??
                          `${item.entity_type_label}${item.entity_id ? ` #${item.entity_id}` : ""}`}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {item.entity_type_label}
                        {item.client_name && item.entity_type !== "client"
                          ? ` · klient: ${item.client_name}`
                          : ""}
                      </p>
                    </td>
                    <td className="px-3 py-2.5 min-w-[16rem]">
                      <span
                        className={cn(
                          "inline-flex px-2 py-0.5 rounded-full text-xs font-semibold",
                          item.outcome === "blocked"
                            ? "bg-destructive/15 text-destructive"
                            : "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200",
                        )}
                      >
                        {item.outcome_label}
                      </span>
                      {item.reason && (
                        <p className="text-xs text-muted-foreground mt-1">{item.reason}</p>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex items-center justify-between text-sm text-muted-foreground">
            <span>
              {data.total} {pluralPl(data.total, "zdarzenie", "zdarzenia", "zdarzeń")} · strona{" "}
              {page + 1} z {totalPages}
            </span>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                disabled={page === 0}
                className="h-8 px-3 rounded-md border border-border disabled:opacity-40"
              >
                Poprzednia
              </button>
              <button
                type="button"
                onClick={() => setPage((p) => p + 1)}
                disabled={page + 1 >= totalPages}
                className="h-8 px-3 rounded-md border border-border disabled:opacity-40"
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

export default EventHistoryTab;
