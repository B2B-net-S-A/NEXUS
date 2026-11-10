"use client";

import { Inbox } from "lucide-react";
import { useMemo, useState } from "react";

import { EmptyState } from "@/components/ds/EmptyState";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { TruncatedText } from "@/components/ds/TruncatedText";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import {
  SIGNAL_STRENGTH_LABELS,
  SIGNAL_TYPE_LABELS,
  signalPayload,
  useLatestSignalRun,
  useLeads,
  type Lead,
} from "@/lib/api/sales";
import { formatIsoDatePl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";

import { BotReport, runSummary } from "./BotReport";
import { SignalPanel } from "./SignalPanel";

export type SignalFilter = "check" | "weak" | "rejected" | "all";

const LAYOUT = "grid items-start gap-3 lg:grid-cols-[minmax(0,1fr)_380px]";

const EMPTY: Record<SignalFilter, string> = {
  check: "Wszystkie sygnały do sprawdzenia są rozpatrzone.",
  weak: "Brak słabych sygnałów.",
  rejected: "Nic jeszcze nie odrzucono.",
  all: "Bot nie przysłał jeszcze żadnego sygnału.",
};

/** Do sprawdzenia: nowy sygnał silny albo średni; słabe osobno, żeby nie udawały zadań. */
export function groupSignals(leads: readonly Lead[]): Record<SignalFilter, Lead[]> {
  const open = leads.filter((lead) => lead.status === "new" || lead.status === "contacted");
  const weak = (lead: Lead) => signalPayload(lead).strength === "weak";
  return {
    check: open.filter((lead) => !weak(lead)),
    weak: open.filter(weak),
    rejected: leads.filter((lead) => lead.status === "dismissed"),
    all: [...leads],
  };
}

function SignalRow({ lead, selected, onSelect }: { lead: Lead; selected: boolean; onSelect: () => void }) {
  const signal = signalPayload(lead);
  return (
    <li>
      <button
        type="button"
        aria-pressed={selected}
        onClick={onSelect}
        className={cn(
          "block w-full px-3 py-2 text-left leading-tight transition-colors hover:bg-muted/40",
          selected && "bg-primary/10 hover:bg-primary/10",
        )}
      >
        <span className="flex min-w-0 items-baseline gap-2">
          <TruncatedText className="max-w-[160px] shrink-0 text-sm font-medium text-foreground">
            {lead.company_name ?? "—"}
          </TruncatedText>
          <TruncatedText className="min-w-0 max-w-none flex-1 text-sm text-muted-foreground">{lead.title}</TruncatedText>
          {signal.published && (
            <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
              {formatIsoDatePl(signal.published)}
            </span>
          )}
        </span>
        <span className="mt-0.5 flex min-w-0 items-baseline gap-1.5 text-xs text-muted-foreground">
          {signal.strength && (
            <span className={cn("shrink-0", signal.strength !== "weak" && "font-medium text-primary")}>
              {SIGNAL_STRENGTH_LABELS[signal.strength]}
            </span>
          )}
          {signal.type && (
            <>
              <span aria-hidden>·</span>
              <span className="shrink-0">{SIGNAL_TYPE_LABELS[signal.type]}</span>
            </>
          )}
          {lead.status === "contacted" && (
            <>
              <span aria-hidden>·</span>
              <span className="shrink-0">W kontakcie</span>
            </>
          )}
          {lead.status === "dismissed" && lead.dismissed_reason && (
            <span className="ml-auto truncate pl-2">Odrzucone: {lead.dismissed_reason}</span>
          )}
        </span>
      </button>
    </li>
  );
}

/** Leady jako skrzynka sygnałów z bota (G1): lista po lewej, panel decyzji po prawej. */
export function SignalsInbox() {
  const [filter, setFilter] = useState<SignalFilter>("check");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [report, setReport] = useState(false);
  const latest = useLatestSignalRun("signals");
  const query = useLeads({ status: "new", source: "research", all_statuses: true, limit: 500 });
  const groups = useMemo(() => groupSignals(query.data?.items ?? []), [query.data]);
  const allLoaded = query.isSuccess;

  const state = resolveViewState({
    isLoading: query.isLoading,
    error: query.error,
    isSuccess: query.isSuccess,
    isEmpty: groups[filter].length === 0,
  });

  const options = (
    [
      ["check", "Do sprawdzenia"],
      ["weak", "Słabe"],
      ["rejected", "Odrzucone"],
      ["all", "Wszystkie"],
    ] as const
  ).map(([value, label]) => ({ value, label: allLoaded ? `${label} (${groups[value].length})` : label }));

  const items = groups[filter];
  const selected = items.find((lead) => lead.id === selectedId) ?? items[0];
  const run = latest.data?.run ?? null;
  const reasons = latest.data?.reject_reasons?.length ? latest.data.reject_reasons : undefined;

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 text-sm">
        <p className="min-w-0 text-muted-foreground">
          {latest.isError ? (
            "Nie udało się pobrać raportu bota."
          ) : run ? (
            <>
              <span className="font-medium text-foreground">Raport bota, {formatIsoDatePl(run.started_at)}:</span>{" "}
              {runSummary(run)}
            </>
          ) : latest.isSuccess ? (
            "Bot jeszcze nie przysłał żadnego raportu."
          ) : null}
        </p>
        {run && (
          <button type="button" className="shrink-0 text-xs text-primary hover:underline" onClick={() => setReport(true)}>
            Cały raport
          </button>
        )}
      </div>
      <SegmentedRadio size="sm" label="Filtr sygnałów" options={options} value={filter} onChange={setFilter} />
      {state === "loading" ? (
        <p className="py-6 text-sm text-muted-foreground">Wczytywanie sygnałów…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" ? (
        <QueryStateNotice
          state={state}
          description="Nie udało się pobrać sygnałów. Mogą istnieć, spróbuj ponownie za chwilę."
          onRetry={() => void query.refetch()}
        />
      ) : (
        <div className={LAYOUT}>
          <div className="min-w-0 overflow-hidden rounded-lg border border-border bg-card">
            {state === "empty" ? (
              <EmptyState icon={Inbox} title="Pusto" description={EMPTY[filter]} />
            ) : (
              <ul className="divide-y divide-border">
                {items.map((lead) => (
                  <SignalRow
                    key={lead.id}
                    lead={lead}
                    selected={!report && lead.id === selected?.id}
                    onSelect={() => {
                      setSelectedId(lead.id);
                      setReport(false);
                    }}
                  />
                ))}
              </ul>
            )}
          </div>
          {report && run ? (
            <BotReport run={run} onClose={() => setReport(false)} />
          ) : (
            selected && <SignalPanel key={selected.id} lead={selected} reasons={reasons} />
          )}
        </div>
      )}
    </div>
  );
}
