"use client";

/**
 * Insights → Zasady (decyzje Artura 05.11.2026, makiety
 * https://claude.ai/artifact/HMAfbAGeDULpmRAw4XjRd5): to, co decyduje, jak NEXUS
 * liczy i przydziela, w jednym miejscu. Przegląd mówi, co dziś obowiązuje i kto
 * to ostatnio zmienił, a wiersz otwiera ten sam ekran co w Ustawieniach.
 * Wartości liczy `GET /api/insights/rules-overview`.
 */

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { useEffect, useRef } from "react";
import { ChevronRight } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { LeagueRulesPanel } from "@/components/insights/views/zasady/LeagueRulesPanel";
import { KPI_TARGETS_INTRO, KpiTargetsSettings } from "@/components/settings/KpiTargetsSettings";
import { PlacementExclusionsTab } from "@/components/settings/PlacementExclusionsTab";
import { PREP_REVIEW_INTRO, PrepReviewSettings } from "@/components/settings/PrepReviewSettings";
import { QcQualityPanel } from "@/components/settings/QcQualityPanel";
import { TWIN_RULES_INTRO, TwinRulesSettings } from "@/components/settings/TwinRulesSettings";
import { RANKING_INTRO, RankingPanel } from "@/components/settings/ranking/RankingPanel";
import { AllocationRulesPanel } from "@/components/v2/competence-team/AllocationRulesPanel";
import { api } from "@/lib/api";
import {
  isRuleId,
  lastChangeText,
  RULES_OVERVIEW_QUERY_KEY,
  ruleHasOwnHeader,
  type RuleChange,
  type RuleId,
  type RuleRow,
  visibleRuleRows,
} from "@/lib/insights-rules";
import { hasSectionAccess } from "@/lib/section-access";
import { useUrlWriter } from "@/lib/url-selection";
import { cn } from "@/lib/utils";
import { isForbiddenError } from "@/lib/view-state";
import { hasRole, useAuthStore } from "@/store/auth";

interface OverviewRow {
  id: RuleId;
  now: string;
  last_change: RuleChange | null;
}

const groupsOf = (rows: readonly RuleRow[]): string[] => [...new Set(rows.map((r) => r.group))];

const INTRO: Partial<Record<RuleId, string>> = {
  blizniaki: TWIN_RULES_INTRO,
  ranking: RANKING_INTRO,
  prepy: PREP_REVIEW_INTRO,
  cele: KPI_TARGETS_INTRO,
};

function RuleScreen({ id }: { id: RuleId }) {
  const user = useAuthStore((s) => s.user);
  switch (id) {
    case "przydzial":
      return <AllocationRulesPanel />;
    case "blizniaki":
      return <TwinRulesSettings />;
    case "ranking":
      return (
        <RankingPanel
          insightsWrite={hasSectionAccess(user, "insights", "write")}
          isAdmin={hasRole(user, "admin")}
        />
      );
    case "prepy":
      return <PrepReviewSettings />;
    case "qc":
      return <QcQualityPanel embedded />;
    case "cele":
      return <KpiTargetsSettings />;
    case "liga":
      return <LeagueRulesPanel />;
    case "placementy":
      return <PlacementExclusionsTab />;
    // „Punkty aktywności” mają ekran w zakładce obok i wiersz tam prowadzi.
    case "aktywnosc":
      return null;
  }
}

function RulesOverview({
  rows,
  values,
  loaded,
  onOpen,
}: {
  rows: readonly RuleRow[];
  values: ReadonlyMap<RuleId, OverviewRow>;
  loaded: boolean;
  onOpen: (row: RuleRow) => void;
}) {
  return (
    <div className="space-y-5">
      {groupsOf(rows).map((group) => (
        <section key={group}>
          <h3 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{group}</h3>
          <div className="divide-y divide-border overflow-hidden rounded-xl border border-border bg-card">
            {rows
              .filter((r) => r.group === group)
              .map((row) => {
                const value = values.get(row.id);
                const never = loaded && !value?.last_change;
                return (
                  <button
                    key={row.id}
                    type="button"
                    onClick={() => onOpen(row)}
                    className="grid w-full grid-cols-1 gap-x-4 gap-y-1 px-4 py-1.5 text-left hover:bg-muted md:grid-cols-[14rem_minmax(0,1fr)_12rem_1rem] md:items-center"
                  >
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-semibold text-foreground">{row.title}</span>
                      <span className="block truncate text-xs text-muted-foreground">{row.question}</span>
                    </span>
                    <span className="min-w-0 text-[13px] text-foreground">{value?.now ?? "—"}</span>
                    <span className={cn("text-xs", never ? "text-warning-muted-foreground" : "text-muted-foreground")}>
                      {loaded ? lastChangeText(value?.last_change ?? null) : "—"}
                    </span>
                    <ChevronRight className="hidden h-4 w-4 text-muted-foreground md:block" aria-hidden />
                  </button>
                );
              })}
          </div>
        </section>
      ))}
    </div>
  );
}

function RulesSideNav({
  rows,
  active,
  onOverview,
  onOpen,
}: {
  rows: readonly RuleRow[];
  active: RuleId;
  onOverview: () => void;
  onOpen: (row: RuleRow) => void;
}) {
  const item = (selected: boolean) =>
    cn(
      "block w-full rounded-lg px-2.5 py-1.5 text-left text-sm",
      selected ? "bg-primary/10 font-semibold text-primary" : "text-foreground hover:bg-muted",
    );
  return (
    <nav aria-label="Zasady" className="hidden w-52 shrink-0 self-start lg:sticky lg:top-4 lg:block">
      <button type="button" onClick={onOverview} className={item(false)}>
        Przegląd
      </button>
      {groupsOf(rows).map((group) => (
        <div key={group}>
          <div className="px-2.5 pb-1 pt-3 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            {group}
          </div>
          {rows
            .filter((r) => r.group === group)
            .map((row) => (
              <button
                key={row.id}
                type="button"
                onClick={() => onOpen(row)}
                aria-current={active === row.id ? "page" : undefined}
                className={item(active === row.id)}
              >
                {row.title}
              </button>
            ))}
        </div>
      ))}
    </nav>
  );
}

export function ZasadyView() {
  const { pushUrl } = useUrlWriter();
  const searchParams = useSearchParams();
  const user = useAuthStore((s) => s.user);
  const rows = visibleRuleRows(user);
  const raw = searchParams.get("zasada");
  const activeRow = isRuleId(raw) ? rows.find((r) => r.id === raw && !r.href) : undefined;

  const query = useQuery({
    queryKey: RULES_OVERVIEW_QUERY_KEY,
    queryFn: async () =>
      (await api.get<{ rules: OverviewRow[] }>("/api/insights/rules-overview")).data.rules,
  });

  // Panele z Ustawień nie znają tego klucza, a przegląd ma mówić, co obowiązuje
  // teraz: odświeża się po każdym zapisie w zakładce i przy zmianie ekranu.
  const queryClient = useQueryClient();
  useEffect(() => {
    return queryClient.getMutationCache().subscribe((event) => {
      if (event.type === "updated" && event.action.type === "success") {
        void queryClient.invalidateQueries({ queryKey: RULES_OVERVIEW_QUERY_KEY });
      }
    });
  }, [queryClient]);
  const previousRaw = useRef(raw);
  useEffect(() => {
    if (previousRaw.current === raw) return;
    previousRaw.current = raw;
    void queryClient.invalidateQueries({ queryKey: RULES_OVERVIEW_QUERY_KEY });
  }, [raw, queryClient]);

  const values = new Map((query.data ?? []).map((row) => [row.id, row]));

  const open = (next: RuleRow) => pushUrl(next.href ?? `/insights?tab=zasady&zasada=${next.id}`);
  const overview = () => pushUrl("/insights?tab=zasady");

  return (
    <div className="flex items-start gap-6">
      {/* Na przeglądzie lista jest nawigacją: kolumna z lewej zabierałaby jej szerokość. */}
      {activeRow ? <RulesSideNav rows={rows} active={activeRow.id} onOverview={overview} onOpen={open} /> : null}
      <div className="min-w-0 flex-1 space-y-4">
        {activeRow ? (
          <>
            <div className="space-y-1">
              <button
                type="button"
                onClick={overview}
                className="text-xs font-medium text-primary hover:underline lg:hidden"
              >
                Wróć do przeglądu
              </button>
              {ruleHasOwnHeader(activeRow) ? null : (
                <h2 className="text-xl font-bold tracking-tight text-foreground">{activeRow.title}</h2>
              )}
              {INTRO[activeRow.id] ? (
                <p className="max-w-3xl text-sm text-muted-foreground">{INTRO[activeRow.id]}</p>
              ) : null}
              {query.isSuccess ? (
                <p className="text-xs text-muted-foreground">
                  Ostatnia zmiana: {lastChangeText(values.get(activeRow.id)?.last_change ?? null)}
                  {values.get(activeRow.id)?.last_change ? null : ", działa wartość domyślna"}
                </p>
              ) : null}
            </div>
            <RuleScreen id={activeRow.id} />
          </>
        ) : (
          <>
            <div>
              <h2 className="text-xl font-bold tracking-tight text-foreground">Na jakich zasadach działa NEXUS</h2>
              <p className="text-sm text-muted-foreground">
                Co dziś obowiązuje i kto to ostatnio zmienił. „Nigdy” znaczy, że działa wartość domyślna. Kliknij wiersz,
                żeby otworzyć ekran. Widzą administrator i Head of Recruitment.
              </p>
            </div>
            {query.isError ? (
              <QueryStateNotice
                state={isForbiddenError(query.error) ? "forbidden" : "error"}
                description="Nie udało się wczytać tego, co dziś obowiązuje. Ekrany zasad działają: kliknij wiersz."
                onRetry={() => void query.refetch()}
              />
            ) : null}
            <RulesOverview rows={rows} values={values} loaded={query.isSuccess} onOpen={open} />
          </>
        )}
      </div>
    </div>
  );
}
