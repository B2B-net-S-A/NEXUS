"use client";

import { useQuery } from "@tanstack/react-query";
import { BarChart3, Loader2 } from "lucide-react";
import { phase3Api } from "@/lib/api";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import { SectionError } from "./_shared";

interface TimeToHireRow {
  recruiter_id: number;
  name: string;
  placements: number;
  median_days: number | null;
  p90_days: number | null;
}

interface TTHResponse {
  by_recruiter: TimeToHireRow[];
  total_placements: number;
}

export function TimeToHireSection() {
  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: ["insights-tth"],
    queryFn: () => phase3Api.timeToHire().then((r) => r.data as TTHResponse),
  });

  const rows = data?.by_recruiter ?? [];
  const totalPlacements = data?.total_placements ?? 0;
  // Zdanie „Brak zatrudnień w okresie" jest twierdzeniem o rekrutacji i nie
  // wolno go wypowiadać, gdy raport w ogóle nie odpowiedział (audyt F-20).
  // `isPending` zamiast `isLoading` — patrz komentarz w BoardKPI.
  const viewState = resolveViewState({
    isLoading: isPending,
    isError,
    error,
    isEmpty: rows.length === 0,
  });

  return (
    <section className="bg-card rounded-xl border border-border p-6 shadow-xs">
      <h2 className="text-base font-semibold text-foreground flex items-center gap-2 mb-4">
        <BarChart3 className="w-5 h-5 text-green-500" />
        Time-to-hire
        <span className="ml-auto text-xs text-muted-foreground font-normal">
          {/* Bez odpowiedzi z raportu `totalPlacements` to 0 z inicjalizacji,
              a nie zmierzone zero — nagłówek milczy zamiast zmyślać. */}
          {isBlockingViewState(viewState)
            ? "180 dni"
            : `180 dni · łącznie ${totalPlacements} zatrudnień`}
        </span>
      </h2>

      {viewState === "loading" ? (
        <div className="py-8 flex items-center justify-center">
          <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
        </div>
      ) : isBlockingViewState(viewState) ? (
        <SectionError
          label="Time-to-hire"
          error={error}
          onRetry={() => void refetch()}
        />
      ) : viewState === "empty" ? (
        <p className="text-sm text-muted-foreground py-4 text-center">
          Brak zatrudnień w okresie — dane pojawią się po pierwszej zamkniętej rekrutacji ze stage „Zatrudniony".
        </p>
      ) : (
        <table className="w-full text-sm">
          <thead className="text-xs uppercase text-muted-foreground">
            <tr>
              <th className="text-left py-2">Rekruter</th>
              <th className="text-right py-2">Zatrudnień</th>
              <th className="text-right py-2">Mediana (dni)</th>
              <th className="text-right py-2">P90 (dni)</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.recruiter_id} className="border-t border-border">
                <td className="py-2 font-medium text-foreground">{r.name}</td>
                <td className="py-2 text-right">{r.placements}</td>
                <td className="py-2 text-right">{r.median_days ?? "—"}</td>
                <td className="py-2 text-right">{r.p90_days ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
