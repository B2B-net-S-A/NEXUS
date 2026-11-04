"use client";

/**
 * Ustawienia → System → Wykluczone placementy (0343, decyzja C z 22.09.2026).
 *
 * Lista par (kandydat, rekrutacja), których „Zatrudniony" NIE liczy się jako
 * placement w żadnej statystyce: Insights, Rada, KPI, wyścigi, pulpity,
 * raporty, kreator metryk, kampanie, ścieżka rozwoju, Hall of Fame.
 * Powstaje regułą (serwer, `services/placement_exclusions.py`) — ekran
 * tylko pokazuje, niczego nie dodaje ani nie zdejmuje. Historia etapów
 * kandydata zostaje nietknięta.
 */

import Link from "next/link";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Loader2, Search, ShieldOff } from "lucide-react";

import api from "@/lib/api";
import { countPl, pluralPl } from "@/lib/plural-pl";
import { resolveViewState } from "@/lib/view-state";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";

export interface PlacementExclusionItem {
  id: number;
  candidate_id: number;
  candidate_name: string;
  job_id: number;
  job_title: string | null;
  client_id: number | null;
  client_name: string | null;
  hired_at: string | null;
  moved_by_user_id: number | null;
  moved_by_name: string | null;
  reason: string;
  reason_label: string;
  had_cv_sent: boolean | null;
  series_day: string | null;
  series_size: number | null;
  rule_version: number;
  detected_at: string;
}

export interface PlacementExclusionList {
  items: PlacementExclusionItem[];
  total: number;
  series_threshold: number;
  reasons: Record<string, string>;
}

export const placementExclusionsQueryKey = ["admin", "placement-exclusions"] as const;

const dateFormat = new Intl.DateTimeFormat("pl-PL", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
});

function formatDate(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : dateFormat.format(date);
}

export interface PlacementExclusionGroup {
  key: string;
  label: string;
  detail: string | null;
  items: PlacementExclusionItem[];
  accounts: number;
  days: number;
}

/** Wiersze w grupach po powodzie i etapie „CV wysłane” (20.10.2026) — na
 *  produkcji 227 wierszy to trzy powody, a każdy wiersz powtarzał ten sam opis. */
export function groupPlacementExclusions(items: PlacementExclusionItem[]): PlacementExclusionGroup[] {
  const groups = new Map<string, PlacementExclusionItem[]>();
  for (const item of items) {
    const key = `${item.reason}|${String(item.had_cv_sent)}`;
    groups.set(key, [...(groups.get(key) ?? []), item]);
  }
  return [...groups.entries()]
    .map(([key, rows]) => {
      const first = rows[0];
      return {
        key,
        label: first.reason_label,
        detail:
          first.had_cv_sent === true
            ? "Para miała etap „CV wysłane”"
            : first.had_cv_sent === false
              ? "Bez etapu „CV wysłane”"
              : null,
        items: rows,
        accounts: new Set(rows.map((r) => r.moved_by_user_id ?? r.moved_by_name)).size,
        days: new Set(rows.map((r) => r.series_day ?? r.hired_at?.slice(0, 10))).size,
      };
    })
    .sort((a, b) => b.items.length - a.items.length);
}

function matches(item: PlacementExclusionItem, needle: string): boolean {
  if (!needle) return true;
  const hay = [item.candidate_name, item.job_title, item.client_name, `#${item.job_id}`, String(item.job_id)]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  return hay.includes(needle);
}

export function PlacementExclusionsTab() {
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState<Set<string>>(new Set());
  const query = useQuery({
    queryKey: placementExclusionsQueryKey,
    queryFn: () =>
      api
        .get<PlacementExclusionList>("/api/admin/placement-exclusions")
        .then((r) => r.data),
    staleTime: 60 * 1000,
  });

  const data = query.data;
  const viewState = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isEmpty: (data?.items.length ?? 0) === 0,
    isSuccess: query.isSuccess,
  });
  const threshold = data?.series_threshold ?? 10;

  return (
    <div className="bg-card rounded-2xl border border-border p-6 space-y-5">
      <div className="flex items-start gap-4">
        <div className="w-12 h-12 rounded-xl bg-primary/10 flex items-center justify-center shrink-0">
          <ShieldOff className="w-6 h-6 text-primary" />
        </div>
        <div>
          <h2 className="text-base font-bold text-foreground">Wykluczone placementy</h2>
          <p className="text-sm text-muted-foreground mt-0.5">
            Te zatrudnienia nie liczą się jako placement w żadnej statystyce —
            Insights, Rada, KPI, wyścigi, pulpity i raporty. Historia etapów
            kandydata zostaje bez zmian. Ekran tylko pokazuje listę.
          </p>
        </div>
      </div>

      {viewState === "loading" && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground py-8 justify-center">
          <Loader2 className="w-4 h-4 animate-spin" />
          Ładowanie wykluczonych placementów…
        </div>
      )}

      {(viewState === "error" || viewState === "forbidden") && (
        <QueryStateNotice
          state={viewState}
          description={
            viewState === "forbidden"
              ? "Lista wykluczonych placementów jest dostępna tylko dla administratora."
              : undefined
          }
          onRetry={() => void query.refetch()}
        />
      )}

      {viewState === "empty" && (
        <p className="text-sm text-muted-foreground text-center py-8">
          Żaden placement nie jest wykluczony.
        </p>
      )}

      {viewState === "ready" && data && (
        <ExclusionGroups
          data={data}
          threshold={threshold}
          search={search}
          onSearch={setSearch}
          open={open}
          onToggle={(key) =>
            setOpen((prev) => {
              const next = new Set(prev);
              if (next.has(key)) next.delete(key);
              else next.add(key);
              return next;
            })
          }
        />
      )}
    </div>
  );
}

function ExclusionGroups({
  data,
  threshold,
  search,
  onSearch,
  open,
  onToggle,
}: {
  data: PlacementExclusionList;
  threshold: number;
  search: string;
  onSearch: (value: string) => void;
  open: Set<string>;
  onToggle: (key: string) => void;
}) {
  const groups = useMemo(() => groupPlacementExclusions(data.items), [data.items]);
  const needle = search.trim().toLowerCase();
  const visible = groups
    .map((group) => ({ ...group, shown: group.items.filter((item) => matches(item, needle)) }))
    .filter((group) => group.shown.length > 0);
  const found = visible.reduce((sum, group) => sum + group.shown.length, 0);

  return (
    <>
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-sm text-muted-foreground">
          {data.total}{" "}
          {pluralPl(data.total, "wykluczony placement", "wykluczone placementy", "wykluczonych placementów")}
          {needle ? ` · pasuje ${found}` : ""}
        </p>
        <label className="relative ml-auto">
          <span className="sr-only">Szukaj osoby lub rekrutacji</span>
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <input
            type="search"
            value={search}
            onChange={(event) => onSearch(event.target.value)}
            placeholder="Osoba, rekrutacja, klient, nr"
            className="h-9 w-72 rounded-lg border border-input bg-background pl-8 pr-2 text-sm"
          />
        </label>
      </div>

      {visible.length === 0 ? (
        <p className="text-sm text-muted-foreground text-center py-6">
          Nic nie pasuje do „{search.trim()}”.
        </p>
      ) : (
        <div className="divide-y divide-border overflow-hidden rounded-xl border border-border">
          {visible.map((group) => {
            // Przy wyszukiwaniu i przy jednej grupie wiersze widać od razu.
            const expanded = Boolean(needle) || groups.length === 1 || open.has(group.key);
            const Chevron = expanded ? ChevronDown : ChevronRight;
            return (
              <section key={group.key} aria-label={group.label}>
                <button
                  type="button"
                  aria-expanded={expanded}
                  onClick={() => onToggle(group.key)}
                  className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-muted/50"
                >
                  <Chevron className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
                  <span className="min-w-0 flex-1">
                    <span className="block font-semibold text-foreground">{group.label}</span>
                    <span className="block text-xs text-muted-foreground">
                      {[group.detail, countPl(group.accounts, "konto", "konta", "kont"), countPl(group.days, "dzień", "dni", "dni")]
                        .filter(Boolean)
                        .join(" · ")}
                    </span>
                  </span>
                  <span className="rounded-full bg-primary/10 px-2.5 py-0.5 text-xs font-bold text-primary tabular-nums">
                    {needle ? `${group.shown.length} z ${group.items.length}` : group.items.length}
                  </span>
                </button>
                {expanded && <ExclusionRows items={group.shown} />}
              </section>
            );
          })}
        </div>
      )}

      <p className="text-xs text-muted-foreground">
        Nowa seria trafia tu sama, gdy jedno konto ustawi etap „Zatrudniony” co najmniej{" "}
        {threshold} parom w jednym dniu, dla par bez etapu „CV wysłane”. Do tego cała
        masowa seria z 24–25.09.2025.
      </p>
    </>
  );
}

function ExclusionRows({ items }: { items: PlacementExclusionItem[] }) {
  return (
    <div className="overflow-x-auto border-t border-border">
      <table className="w-full text-sm">
        <thead className="bg-muted/60 text-left text-xs uppercase tracking-wide text-muted-foreground">
          <tr>
            <th className="px-3 py-2 font-medium">Kandydat</th>
            <th className="px-3 py-2 font-medium">Rekrutacja</th>
            <th className="px-3 py-2 font-medium whitespace-nowrap">Zatrudniony</th>
            <th className="px-3 py-2 font-medium">Kto ustawił</th>
            <th className="px-3 py-2 font-medium">Seria</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {items.map((item) => (
            <tr key={item.id} className="align-top">
              <td className="px-3 py-2.5">
                <Link
                  href={`/candidates/${item.candidate_id}`}
                  className="font-medium text-foreground hover:text-primary hover:underline"
                >
                  {item.candidate_name}
                </Link>
              </td>
              <td className="px-3 py-2.5">
                <p className="text-foreground">{item.job_title ?? `Rekrutacja #${item.job_id}`}</p>
                {item.client_name && <p className="text-xs text-muted-foreground">{item.client_name}</p>}
              </td>
              <td className="px-3 py-2.5 whitespace-nowrap text-muted-foreground">{formatDate(item.hired_at)}</td>
              <td className="px-3 py-2.5 text-foreground">{item.moved_by_name ?? "—"}</td>
              <td className="px-3 py-2.5 text-muted-foreground">
                {item.series_size ? `${countPl(item.series_size, "para", "pary", "par")} w dniu` : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default PlacementExclusionsTab;
