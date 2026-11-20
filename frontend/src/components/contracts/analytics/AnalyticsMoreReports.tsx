"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronRight, Loader2 } from "lucide-react";
import {
  contractAnalyticsExpansionApi,
  CONTRACT_TERMINATION_REASONS,
  type LocationDistribution,
  type RoleClientMix,
  type TerminationAnalysis,
} from "@/lib/api";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { countPl } from "@/lib/plural-pl";
import { cn } from "@/lib/utils";
import { resolveViewState, type ViewState } from "@/lib/view-state";

/** Kubełek backendu dla kontraktów bez rekrutacji i bez kategorii kompetencji. */
const UNKNOWN_ROLE = "Unknown";

function isFailedState(state: ViewState): state is "forbidden" | "not_found" | "error" {
  return state === "forbidden" || state === "not_found" || state === "error";
}

function Loading({ children }: { children: React.ReactNode }) {
  return (
    <p className="flex items-center gap-2 px-4 py-4 text-sm text-muted-foreground">
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> {children}
    </p>
  );
}

// ── Rola × klient ──────────────────────────────────────────────────────────

function RoleClientMixContent() {
  const { data, isLoading, isError, error, refetch } = useQuery<RoleClientMix>({
    queryKey: ["contract-analytics-role-client-mix"],
    queryFn: async () => (await contractAnalyticsExpansionApi.roleClientMix()).data,
  });
  const viewState = resolveViewState({ isLoading, isError, error });

  if (isLoading) return <Loading>Ładowanie rola × klient…</Loading>;
  // Awaria to nie „brak kontraktów” — stan błędu z ponowieniem.
  if (isFailedState(viewState)) {
    return <QueryStateNotice state={viewState} className="m-4" onRetry={() => void refetch()} />;
  }
  if (!data || data.rows.length === 0) {
    return <p className="px-4 py-4 text-sm text-muted-foreground">Brak aktywnych kontraktów do analizy.</p>;
  }

  // Macierz: rola → klient → liczba osób.
  const matrix: Record<string, Record<number, number>> = {};
  for (const row of data.rows) {
    matrix[row.role] ??= {};
    matrix[row.role][row.client_id] = row.active_count;
  }

  return (
    <div className="px-4 pb-4">
      <p className="mb-2 text-[12.5px] text-muted-foreground">
        {countPl(data.total_active, "kontraktor", "kontraktorów", "kontraktorów")} /{" "}
        {countPl(data.total_active_contracts, "kontrakt", "kontrakty", "kontraktów")}
      </p>
      <div className="relative overflow-x-auto">
        <table className="min-w-full text-xs tabular-nums">
          <thead className="text-left text-muted-foreground">
            <tr>
              <th className="sticky left-0 bg-card px-2 py-1">Rola</th>
              {data.clients.map((c) => (
                <th key={c.id} className="whitespace-nowrap px-2 py-1">
                  {c.name}
                </th>
              ))}
              <th className="px-2 py-1">Σ</th>
            </tr>
          </thead>
          <tbody>
            {data.roles.map((role) => {
              // Ta sama osoba bywa w kilku kolumnach klientów. Σ to liczba
              // różnych osób w roli, nie suma komórek.
              const rowSum = data.role_totals[role] ?? 0;
              return (
                <tr key={role} className="border-t border-border/60">
                  <td className="sticky left-0 bg-card px-2 py-1 font-medium">
                    {role === UNKNOWN_ROLE ? "Brak roli" : role}
                  </td>
                  {data.clients.map((c) => {
                    const cnt = matrix[role]?.[c.id] ?? 0;
                    const intensity = rowSum ? Math.min(1, cnt / rowSum) : 0;
                    return (
                      <td
                        key={c.id}
                        className="px-2 py-1 text-center"
                        style={{
                          backgroundColor: cnt > 0 ? `hsl(var(--primary) / ${0.1 + intensity * 0.4})` : undefined,
                        }}
                      >
                        {cnt || "·"}
                      </td>
                    );
                  })}
                  <td className="px-2 py-1 text-center font-medium">{rowSum}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Lokalizacja konsultantów ───────────────────────────────────────────────

function LocationContent() {
  const { data, isLoading, isError, error, refetch } = useQuery<LocationDistribution>({
    queryKey: ["contract-analytics-location-distribution"],
    queryFn: async () => (await contractAnalyticsExpansionApi.locationDistribution()).data,
  });
  const viewState = resolveViewState({ isLoading, isError, error });

  if (isLoading) return <Loading>Ładowanie lokalizacji…</Loading>;
  // Awaria nie może skasować sekcji bez śladu — stan błędu z ponowieniem.
  if (isFailedState(viewState)) {
    return <QueryStateNotice state={viewState} className="m-4" onRetry={() => void refetch()} />;
  }
  if (!data) return null;

  return (
    <div className="px-4 pb-4">
      <p className="mb-2 text-[12.5px] text-muted-foreground">
        {data.total_with_hub} z {data.total} z przypisanym hubem
      </p>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div>
          <h4 className="mb-2 text-xs font-semibold text-muted-foreground">Huby</h4>
          <ul className="space-y-1 text-sm">
            {data.hubs.map((h) => (
              <li key={h.hub_city ?? "unknown"} className="flex items-center justify-between">
                <span className={h.hub_city ? "text-foreground" : "text-muted-foreground"}>
                  {h.hub_city ?? "Brak hubu"}
                </span>
                <span className="font-medium tabular-nums">{h.count}</span>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h4 className="mb-2 text-xs font-semibold text-muted-foreground">Regiony</h4>
          <ul className="space-y-1 text-sm">
            {data.regions.map((r) => (
              <li key={r.region ?? "unknown"} className="flex items-center justify-between">
                <span className={r.region ? "text-foreground" : "text-muted-foreground"}>
                  {r.region ?? "Brak regionu"}
                </span>
                <span className="font-medium tabular-nums">{r.count}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}

// ── Powody zakończeń i retencja ────────────────────────────────────────────

function TerminationContent() {
  const { data, isLoading, isError, error, refetch } = useQuery<TerminationAnalysis>({
    queryKey: ["contract-analytics-termination-analysis"],
    queryFn: async () => (await contractAnalyticsExpansionApi.terminationAnalysis(12)).data,
  });
  const viewState = resolveViewState({ isLoading, isError, error });

  if (isLoading) return <Loading>Ładowanie analizy zakończeń…</Loading>;
  if (isFailedState(viewState)) {
    return <QueryStateNotice state={viewState} className="m-4" onRetry={() => void refetch()} />;
  }
  if (!data) return null;

  const reasonLabel = (v: string) => CONTRACT_TERMINATION_REASONS.find((r) => r.value === v)?.label ?? v;
  const maxCount = Math.max(1, ...data.by_reason.map((r) => r.count));

  return (
    <div className="px-4 pb-4">
      <p className="mb-2 text-[12.5px] text-muted-foreground">
        {countPl(data.total_terminated, "zakończenie", "zakończenia", "zakończeń")} w ostatnich{" "}
        {data.window_months} mies.
      </p>
      {data.by_reason.length === 0 ? (
        <p className="text-sm text-muted-foreground">Brak zakończeń w oknie.</p>
      ) : (
        <div className="grid grid-cols-1 items-start gap-5 xl:grid-cols-2">
          <div>
            <h4 className="mb-2 text-xs font-semibold text-muted-foreground">Powody</h4>
            <ul className="space-y-1">
              {data.by_reason.map((r) => (
                <li key={r.reason} className="text-sm">
                  <div className="flex justify-between text-xs text-muted-foreground">
                    <span>{reasonLabel(r.reason)}</span>
                    <span>
                      {r.count}
                      {r.avg_contract_days != null && <> · śr. {Math.round(r.avg_contract_days)} dni</>}
                    </span>
                  </div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                    <div
                      className="h-full rounded-full bg-warning"
                      style={{ width: `${(r.count / maxCount) * 100}%` }}
                    />
                  </div>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <h4 className="mb-2 text-xs font-semibold text-muted-foreground">Retencja per klient</h4>
            <div className="relative overflow-x-auto">
              <table className="w-full text-xs tabular-nums">
                <thead className="text-left text-muted-foreground">
                  <tr>
                    <th className="px-2 py-1">Klient</th>
                    <th className="px-2 py-1 text-right">Zakończone</th>
                    <th className="px-2 py-1 text-right">Do końca</th>
                    <th className="px-2 py-1 text-right">Przedwczesne</th>
                    <th className="px-2 py-1 text-right">Retencja</th>
                  </tr>
                </thead>
                <tbody>
                  {data.client_retention.map((c) => (
                    <tr key={c.client_id} className="border-t border-border/60">
                      <td className="px-2 py-1">{c.client_name}</td>
                      <td className="px-2 py-1 text-right">{c.total_ended}</td>
                      <td className="px-2 py-1 text-right text-success-muted-foreground">{c.kept_to_end}</td>
                      <td className="px-2 py-1 text-right text-destructive">{c.ended_early}</td>
                      <td className="px-2 py-1 text-right font-medium">{c.retention_pct}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Zwijane sekcje ─────────────────────────────────────────────────────────

const REPORTS = [
  {
    key: "roles",
    title: "Rola × klient — szczegóły",
    note: "Rolą jest tytuł rekrutacji, więc to zwykle długa lista ról po jednej osobie.",
    Content: RoleClientMixContent,
  },
  {
    key: "location",
    title: "Lokalizacja konsultantów",
    note: "Huby i regiony osób z aktywnym kontraktem.",
    Content: LocationContent,
  },
  {
    key: "terminations",
    title: "Powody zakończeń i retencja (12 mies.)",
    note: "Dlaczego kończą się umowy i u kogo ludzie zostają do końca.",
    Content: TerminationContent,
  },
] as const;

/**
 * Rzadsze zestawienia, zwinięte na dole: macierz „Rola × klient” (makieta ją
 * pomijała, ale z ekranu nic nie znika bez śladu), lokalizacja i powody
 * zakończeń. Dane pobierają się dopiero po rozwinięciu.
 */
export function AnalyticsMoreReports() {
  const [open, setOpen] = useState<Record<string, boolean>>({});
  return (
    <section aria-label="Więcej zestawień" className="space-y-2">
      <h2 className="text-[14px] font-semibold text-foreground">Więcej zestawień</h2>
      <div className="divide-y divide-border/70 rounded-xl border border-border bg-card shadow-xs">
        {REPORTS.map(({ key, title, note, Content }) => {
          const expanded = open[key] === true;
          return (
            <div key={key}>
              <button
                type="button"
                aria-expanded={expanded}
                aria-controls={`analytics-more-${key}`}
                onClick={() => setOpen((s) => ({ ...s, [key]: !expanded }))}
                className="flex w-full items-center gap-2 px-4 py-2.5 text-left hover:bg-muted/40"
              >
                <ChevronRight
                  className={cn("size-4 shrink-0 text-muted-foreground transition-transform", expanded && "rotate-90")}
                  aria-hidden
                />
                <span className="shrink-0 text-[13px] font-medium text-foreground">{title}</span>
                <span className="min-w-0 truncate text-[12px] text-muted-foreground">{note}</span>
              </button>
              {expanded ? (
                <div id={`analytics-more-${key}`}>
                  <Content />
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </section>
  );
}
