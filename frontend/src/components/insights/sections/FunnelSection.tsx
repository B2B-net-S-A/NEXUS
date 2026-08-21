"use client";

import { useQuery } from "@tanstack/react-query";
import { TrendingUp, Loader2 } from "lucide-react";
import { phase3Api } from "@/lib/api";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import { SectionError } from "./_shared";

interface FunnelRow {
  stage_def_id: number;
  stage_name: string;
  category: string;
  is_terminal: boolean;
  count: number;
  conversion_pct: number | null;
}

export function FunnelSection() {
  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: ["insights-funnel"],
    queryFn: () => phase3Api.funnel().then((r) => r.data as { funnel: FunnelRow[] }),
  });

  const funnel = data?.funnel ?? [];
  const maxCount = funnel.length ? Math.max(...funnel.map((f) => f.count), 1) : 1;
  // „Brak danych." to zdanie o rekrutacjach; 403/500 to zdanie o systemie.
  // Do audytu F-20 obie sytuacje mówiły tu to samo. Pusty stan wisi na
  // sukcesie: `isPending` (nie `isLoading`) obejmuje też przerwę między
  // ponowieniami, w której `funnel` jest pusty, a odpowiedzi jeszcze nie ma.
  const viewState = resolveViewState({
    isLoading: isPending,
    isError,
    error,
    isEmpty: funnel.length === 0,
  });

  return (
    <section className="bg-card rounded-xl border border-border p-6 shadow-xs">
      <h2 className="text-base font-semibold text-foreground flex items-center gap-2 mb-4">
        <TrendingUp className="w-5 h-5 text-primary" />
        Lejek rekrutacyjny
        <span className="ml-auto text-xs text-muted-foreground font-normal">
          Unikalni kandydaci na etap
        </span>
      </h2>

      {viewState === "loading" ? (
        <div className="py-8 flex items-center justify-center">
          <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
        </div>
      ) : isBlockingViewState(viewState) ? (
        <SectionError
          label="Lejek rekrutacyjny"
          error={error}
          onRetry={() => void refetch()}
        />
      ) : viewState === "empty" ? (
        <p className="text-sm text-muted-foreground py-4 text-center">Brak danych.</p>
      ) : (
        <div className="space-y-2">
          {funnel.map((f) => {
            const w = Math.max(2, (f.count / maxCount) * 100);
            return (
              <div key={f.stage_def_id} className="flex items-center gap-3">
                <span className="w-40 text-sm text-foreground truncate">{f.stage_name}</span>
                <div className="flex-1 h-5 bg-muted rounded-full overflow-hidden">
                  <div
                    className={f.is_terminal ? "h-full bg-slate-400" : "h-full bg-primary"}
                    style={{ width: `${w}%` }}
                  />
                </div>
                <span className="w-12 text-sm text-foreground text-right font-medium">
                  {f.count}
                </span>
                <span className="w-16 text-xs text-muted-foreground text-right">
                  {f.conversion_pct !== null ? `${f.conversion_pct}%` : "—"}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
