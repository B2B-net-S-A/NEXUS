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
import { useQuery } from "@tanstack/react-query";
import { Loader2, ShieldOff } from "lucide-react";

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

export function PlacementExclusionsTab() {
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
            Insights, Rada, KPI, wyścigi, pulpity i raporty. Trafia tu każda
            seria, w której jedno konto ustawiło etap „Zatrudniony” co najmniej{" "}
            {threshold} parom w jednym dniu, dla par bez etapu „CV wysłane”, oraz
            cała masowa seria z 24–25.09.2025. Historia etapów kandydata zostaje
            bez zmian.
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
        <>
          <p className="text-sm text-muted-foreground">
            {data.total}{" "}
            {pluralPl(data.total, "wykluczony placement", "wykluczone placementy", "wykluczonych placementów")}
          </p>
          <div className="overflow-x-auto rounded-xl border border-border">
            <table className="w-full text-sm">
              <thead className="bg-muted/60 text-left text-xs uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 font-medium">Kandydat</th>
                  <th className="px-3 py-2 font-medium">Rekrutacja</th>
                  <th className="px-3 py-2 font-medium whitespace-nowrap">Zatrudniony</th>
                  <th className="px-3 py-2 font-medium">Kto ustawił</th>
                  <th className="px-3 py-2 font-medium">Powód</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {data.items.map((item) => (
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
                      <p className="text-foreground">
                        {item.job_title ?? `Rekrutacja #${item.job_id}`}
                      </p>
                      {item.client_name && (
                        <p className="text-xs text-muted-foreground">{item.client_name}</p>
                      )}
                    </td>
                    <td className="px-3 py-2.5 whitespace-nowrap text-muted-foreground">
                      {formatDate(item.hired_at)}
                    </td>
                    <td className="px-3 py-2.5 text-foreground">
                      {item.moved_by_name ?? "—"}
                    </td>
                    <td className="px-3 py-2.5 min-w-[16rem]">
                      <p className="text-foreground">{item.reason_label}</p>
                      <p className="text-xs text-muted-foreground">
                        {item.had_cv_sent === true
                          ? "Para miała etap „CV wysłane”"
                          : item.had_cv_sent === false
                            ? "Bez etapu „CV wysłane”"
                            : null}
                        {item.series_size
                          ? ` · seria: ${countPl(item.series_size, "para", "pary", "par")} w dniu`
                          : null}
                      </p>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

export default PlacementExclusionsTab;
