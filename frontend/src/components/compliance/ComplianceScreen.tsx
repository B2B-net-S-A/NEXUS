"use client";

import { useEffect, useMemo, useState } from "react";
import { BookOpen, CalendarClock, Settings2 } from "lucide-react";

import { InlineStats, QueryStateNotice } from "@/components/ds";
import { useComplianceChanges, useComplianceRuns } from "@/lib/api/compliance";
import { canOpenCompliance } from "@/lib/compliance-access";
import { useUrlWriter } from "@/lib/url-selection";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";
import { warsawToday } from "@/lib/warsaw-date";
import { hasRole, useAuthStore } from "@/store/auth";

import { ChangesView } from "./ChangesView";
import { DeadlinesView } from "./DeadlinesView";
import { SourcesView } from "./SourcesView";
import {
  LENSES,
  VIEWS,
  daysBetween,
  deadlineEntries,
  formatMoment,
  isLens,
  isView,
  lensRole,
  orderChanges,
  type Lens,
  type View,
} from "./compliance-model";

const VIEW_ICON: Record<View, typeof BookOpen> = {
  changes: BookOpen,
  calendar: CalendarClock,
  setup: Settings2,
};

const DEADLINE_WINDOW_DAYS = 60;
const NEW_WINDOW_DAYS = 7;

export const DISABLED_NOTICE = "Radar przepisów jest wyłączony — włącza go administrator (LAW_RADAR_ENABLED).";
const FORBIDDEN_NOTICE =
  "„Przepisy” widzą administrator, Head of Recruitment i osoby z uprawnieniem „Moduł Finanse”, „Płace”, „Kadry” albo „Kontrakty i zamówienia”.";

/** „Przepisy”: zmiany w prawie, terminy i to, co znaczą dla firmy na danych NEXUSA. */
export function ComplianceScreen() {
  const user = useAuthStore((s) => s.user);
  const hydrated = useAuthStore((s) => s.hydrated);
  if (!hydrated) return null;
  if (!canOpenCompliance(user)) {
    return <QueryStateNotice state="forbidden" description={FORBIDDEN_NOTICE} />;
  }
  return <ComplianceBody isAdmin={hasRole(user, "admin")} />;
}

function ComplianceBody({ isAdmin }: { isAdmin: boolean }) {
  const { replaceUrl } = useUrlWriter();
  const [view, setView] = useState<View>("changes");
  const [lens, setLens] = useState<Lens>("all");
  const [selectedId, setSelectedId] = useState<number | null>(null);

  // Adres czytany po zamontowaniu: strona jest prerenderowana bez `window`.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const v = params.get("view");
    const l = params.get("lens");
    const id = Number(params.get("id"));
    if (isView(v)) setView(v);
    if (isLens(l)) setLens(l);
    if (Number.isInteger(id) && id > 0) setSelectedId(id);
  }, []);

  const writeParams = (patch: Record<string, string | null>) => {
    const params = new URLSearchParams(window.location.search);
    for (const [key, value] of Object.entries(patch)) {
      if (value == null) params.delete(key);
      else params.set(key, value);
    }
    const query = params.toString();
    replaceUrl(`${window.location.pathname}${query ? `?${query}` : ""}`);
  };

  const today = warsawToday();
  const changes = useComplianceChanges(lensRole(lens));
  const runs = useComplianceRuns();
  const enabled = changes.data?.enabled === true;
  const list = useMemo(
    () => (changes.data?.enabled ? orderChanges(changes.data.changes) : []),
    [changes.data],
  );
  const state = resolveViewState({
    isLoading: changes.isLoading,
    isError: changes.isError,
    error: changes.error,
    isSuccess: changes.isSuccess,
    isEmpty: list.length === 0,
  });

  const lastCollect = runs.data?.runs.find((run) => run.kind === "collect" && run.status === "received");
  const toDecide = list.filter((change) => change.status === "new").length;
  const soon = deadlineEntries(list, today).filter(
    (entry) => entry.kind === "deadline" && entry.days >= 0 && entry.days <= DEADLINE_WINDOW_DAYS,
  ).length;
  const fresh = list.filter((change) => {
    const created = change.created_at.slice(0, 10);
    return daysBetween(created, today) <= NEW_WINDOW_DAYS;
  }).length;

  const openChange = (id: number) => {
    setSelectedId(id);
    setView("changes");
    writeParams({ view: "changes", id: String(id) });
  };

  const showsLens = view === "changes" || view === "calendar";

  return (
    <div className="space-y-3.5 pb-16">
      <header className="flex flex-wrap items-end gap-x-4 gap-y-2">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h1 className="font-display text-xl font-semibold leading-tight tracking-tight">Przepisy</h1>
            <p className="text-[13px] text-muted-foreground">
              Zmiany w prawie, terminy i to, co znaczą dla nas — z danymi z NEXUSA
            </p>
          </div>
        </div>
        {enabled ? (
          <InlineStats
            stats={[
              { id: "decide", label: "Do decyzji", value: toDecide },
              { id: "soon", label: `Terminy w ${DEADLINE_WINDOW_DAYS} dni`, value: soon },
              { id: "fresh", label: `Nowe w ${NEW_WINDOW_DAYS} dni`, value: fresh },
              {
                id: "checked",
                label: "Źródła sprawdzone",
                value: lastCollect ? formatMoment(lastCollect.received_at) : "—",
              },
            ]}
          />
        ) : null}
      </header>

      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border">
        <nav aria-label="Widoki" className="-mb-px flex max-w-full gap-0.5 overflow-x-auto">
          {VIEWS.map((item) => {
            const Icon = VIEW_ICON[item.value];
            const active = item.value === view;
            return (
              <button
                key={item.value}
                type="button"
                onClick={() => {
                  setView(item.value);
                  writeParams({ view: item.value });
                }}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap border-b-2 px-3 py-1.5 text-[13px] transition-colors pointer-coarse:min-h-10",
                  active
                    ? "border-primary font-semibold text-foreground"
                    : "border-transparent font-medium text-muted-foreground hover:text-foreground",
                )}
              >
                <Icon className="h-3.5 w-3.5" aria-hidden />
                {item.label}
              </button>
            );
          })}
        </nav>
        {showsLens ? (
          <div className="mb-1.5 flex flex-wrap gap-1" role="group" aria-label="Dla kogo">
            {LENSES.map((item) => (
              <button
                key={item.value}
                type="button"
                onClick={() => {
                  setLens(item.value);
                  writeParams({ lens: item.value === "all" ? null : item.value });
                }}
                aria-pressed={item.value === lens}
                className={cn(
                  "h-7 rounded-full border px-2.5 text-xs font-medium transition-colors pointer-coarse:min-h-10",
                  item.value === lens
                    ? "border-primary bg-primary/10 text-foreground"
                    : "border-border text-muted-foreground hover:text-foreground",
                )}
              >
                {item.label}
              </button>
            ))}
          </div>
        ) : null}
      </div>

      {view === "setup" ? (
        <SourcesView isAdmin={isAdmin} />
      ) : state === "loading" ? (
        <p className="py-6 text-sm text-muted-foreground">Wczytywanie zmian…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" ? (
        <QueryStateNotice
          state={state}
          description={state === "forbidden" ? FORBIDDEN_NOTICE : undefined}
          onRetry={() => changes.refetch()}
        />
      ) : changes.isSuccess && !enabled ? (
        <div role="status" className="rounded-lg border border-dashed border-border px-6 py-10 text-center">
          <p className="text-sm font-medium">{DISABLED_NOTICE}</p>
        </div>
      ) : state === "empty" ? (
        <div className="rounded-lg border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
          Brak zmian dla tej roli.
        </div>
      ) : view === "calendar" ? (
        <DeadlinesView changes={list} today={today} onOpen={openChange} />
      ) : (
        <ChangesView
          changes={list}
          selectedId={selectedId}
          onSelect={(id) => {
            setSelectedId(id);
            writeParams({ id: String(id) });
          }}
        />
      )}
    </div>
  );
}
