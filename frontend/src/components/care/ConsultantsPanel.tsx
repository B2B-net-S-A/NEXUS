"use client";

import { useState } from "react";
import { Users } from "lucide-react";

import { EmptyState } from "@/components/ds/EmptyState";
import { ListDetailLayout } from "@/components/ds/ListDetailLayout";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { useCareConsultants, type ConsultantRow } from "@/lib/api/care";
import { CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";
import { formatDayMonthPl } from "@/lib/date-pl";

import {
  CADENCE_BADGE,
  cadenceLabel,
  cadenceSubline,
  consultantsIn,
  contractForm,
  filterCounts,
  matchesFilter,
  monthTalks,
  rowSignals,
  signalText,
  sinceText,
  type ConsultantFilter,
} from "./cadence-format";
import { CadenceDialog } from "./CadenceDialog";
import { ConversationDialog } from "./ConversationDialog";
import { ConsultantPanel } from "./week/ConsultantPanel";

const FILTERS: [ConsultantFilter, string][] = [
  ["all", "Wszystkie rytmy"],
  ["biweekly", "Rytm: co 2 tygodnie"],
  ["paused", "Wstrzymani"],
  ["signals", "Z sygnałem"],
];

function NextTalk({ row }: { row: ConsultantRow }) {
  const next = row.next_contact;
  if (next?.overdue) {
    return (
      <Badge variant="danger" size="md">
        zaległa {next.overdue_days === 1 ? "1 dzień" : `${next.overdue_days} dni`}
      </Badge>
    );
  }
  if (next) {
    return (
      <>
        <span className="tabular-nums">{formatDayMonthPl(next.due_on)}</span>
        {next.kind === "pre_end" ? <span className={CALM_SUBLINE}>30 dni przed końcem</span> : null}
        {next.kind === "follow_up" ? <span className={CALM_SUBLINE}>umówiony kontakt</span> : null}
      </>
    );
  }
  if (row.cadence.level === "paused" && row.cadence.until_on) {
    return <span className="text-muted-foreground">po {formatDayMonthPl(row.cadence.until_on)}</span>;
  }
  return <span className={CALM_EMPTY}>—</span>;
}

function LastTalk({ row }: { row: ConsultantRow }) {
  const last = row.last_conversation;
  if (!last) return <span className={CALM_EMPTY}>bez rozmów</span>;
  const text = [
    formatDayMonthPl(last.occurred_on),
    last.satisfaction ? `${last.satisfaction}/5` : null,
    last.note_excerpt ? `„${last.note_excerpt}”` : "bez uwag",
  ]
    .filter(Boolean)
    .join(" · ");
  return <span className="line-clamp-2 text-muted-foreground">{text}</span>;
}

/**
 * „Opieka · Konsultanci” (makieta M1): rytm przy każdej osobie — kolor mówi,
 * jak często rozmawiamy, podpis dlaczego i do kiedy. Sygnał to podpowiedź,
 * nie zmiana; rytm zmienia się w oknie „Rytm kontaktu”. Kliknięcie osoby
 * otwiera jej oś. Awaria zapytania ≠ pusta lista.
 */
export function ConsultantsPanel() {
  const query = useCareConsultants();
  const [scope, setScope] = useState<"mine" | "all">("mine");
  const [filter, setFilter] = useState<ConsultantFilter>("all");
  const [selected, setSelected] = useState<number | null>(null);
  const [cadenceFor, setCadenceFor] = useState<number | null>(null);
  const [talk, setTalk] = useState<{ contractId: number; clientId: number } | null>(null);
  const items = query.data?.items ?? [];
  const inScope = consultantsIn(items, scope);
  const rows = inScope.filter((row) => matchesFilter(row, filter));
  const counts = filterCounts(inScope);
  const state = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
    isEmpty: rows.length === 0,
  });
  const selectedRow = items.find((row) => row.contract_id === selected) ?? null;
  const today = query.data?.today ?? "";

  const list = (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-1">
          <SegmentedRadio
            label="Zakres listy"
            size="sm"
            value={scope}
            onChange={setScope}
            options={(
              [
                ["mine", "Moi", consultantsIn(items, "mine").length],
                ["all", "Wszyscy w moim zakresie", items.length],
              ] as const
            ).map(([value, label, count]) => ({
              value,
              label: query.isSuccess ? `${label} (${count})` : label,
            }))}
          />
          <SegmentedRadio
            label="Filtr rytmu"
            size="sm"
            value={filter}
            onChange={setFilter}
            options={FILTERS.map(([value, label]) => ({
              value,
              label:
                value !== "all" && query.isSuccess ? `${label} (${counts[value]})` : label,
            }))}
          />
        </div>
        {query.isSuccess ? (
          <span className="text-xs text-muted-foreground" title="Kamienie i rozmowy według rytmu osób na liście">
            Rozmów w tym miesiącu według rytmów: <span className="font-semibold tabular-nums">{monthTalks(rows)}</span>
          </span>
        ) : null}
      </div>

      {state === "loading" ? (
        <p className="text-sm text-muted-foreground">Wczytywanie konsultantów…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" ? (
        <QueryStateNotice
          state={state}
          description={state === "error" ? "Nie udało się wczytać listy konsultantów." : undefined}
          onRetry={() => query.refetch()}
        />
      ) : state === "empty" ? (
        <EmptyState
          icon={Users}
          title={
            filter !== "all"
              ? "Nikt nie pasuje do tego filtra"
              : scope === "mine"
                ? "Nie opiekujesz się żadnym konsultantem"
                : "Brak trwających kontraktów"
          }
          description={
            scope === "mine" && filter === "all"
              ? "Opiekuna ustawia się na kontrakcie (zakładka „Opieka”), domyślnie dla klienta albo w „Przydziale”."
              : undefined
          }
        />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border bg-card">
          <table className="w-full text-sm" aria-label="Konsultanci i rytm kontaktu">
            <thead>
              <tr className={CALM_ROW}>
                <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Konsultant</th>
                <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Klient · menedżer u klienta</th>
                <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Rytm</th>
                <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Następna rozmowa</th>
                <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Ostatnio</th>
                <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Sygnał</th>
                {scope === "all" ? (
                  <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Opiekun</th>
                ) : null}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const subline = cadenceSubline(row.cadence);
                const signals = rowSignals(row);
                const about = [row.job_title, contractForm(row.contract_type), sinceText(row.start_date, today)]
                  .filter(Boolean)
                  .join(" · ");
                return (
                  <tr
                    key={row.contract_id}
                    className={cn(CALM_ROW, selected === row.contract_id && "bg-muted/60")}
                  >
                    <td className="px-3 py-1.5 align-top">
                      <button
                        type="button"
                        className="text-left font-medium hover:underline"
                        aria-label={`Oś konsultanta: ${row.candidate_name ?? "konsultant"}`}
                        onClick={() => setSelected(row.contract_id)}
                      >
                        {row.candidate_name ?? "Konsultant"}
                      </button>
                      {about ? <span className={CALM_SUBLINE}>{about}</span> : null}
                    </td>
                    <td className="px-3 py-1.5 align-top">
                      {row.client_name}
                      <span className={CALM_SUBLINE}>{row.manager?.name ?? "menedżer: nie wskazano"}</span>
                    </td>
                    <td className="px-3 py-1.5 align-top">
                      <span className="flex items-center gap-1.5">
                        <Badge variant={CADENCE_BADGE[row.cadence.level]} size="md">
                          {cadenceLabel(row.cadence.level)}
                        </Badge>
                        {row.can_change_cadence ? (
                          <Button
                            size="sm"
                            variant="quiet"
                            className="h-6 px-1.5 text-xs"
                            aria-label={`Zmień rytm: ${row.candidate_name ?? "konsultant"}`}
                            onClick={() => setCadenceFor(row.contract_id)}
                          >
                            Zmień
                          </Button>
                        ) : null}
                      </span>
                      {subline ? <span className={cn(CALM_SUBLINE, "max-w-44")}>{subline}</span> : null}
                    </td>
                    <td className="px-3 py-1.5 align-top">
                      <NextTalk row={row} />
                    </td>
                    <td className="max-w-52 px-3 py-1.5 align-top">
                      <LastTalk row={row} />
                    </td>
                    <td className="max-w-48 px-3 py-1.5 align-top">
                      {signals.length ? (
                        <span className="flex flex-wrap gap-1">
                          {signals.map((signal) => (
                            <Badge key={signal.kind} variant="warning" size="md">
                              {signalText(signal)}
                            </Badge>
                          ))}
                          {row.suggested_level ? (
                            <span className="text-xs text-muted-foreground">podnieść rytm?</span>
                          ) : null}
                        </span>
                      ) : (
                        <span className={CALM_EMPTY}>—</span>
                      )}
                    </td>
                    {scope === "all" ? (
                      <td className="px-3 py-1.5 align-top">
                        {row.owner?.name ?? <span className={CALM_EMPTY}>—</span>}
                      </td>
                    ) : null}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {query.isSuccess && !query.data.feedback_visible ? (
        <p className="text-xs text-muted-foreground">
          Opinie menedżerów w sygnałach widzą opiekun, Delivery Lead klienta, Head of Recruitment i administrator.
        </p>
      ) : null}
    </div>
  );

  return (
    <>
      <ListDetailLayout
        list={list}
        panel={
          selected != null ? (
            <ConsultantPanel
              key={selected}
              contractId={selected}
              onClose={() => setSelected(null)}
              onTalk={(clientId) =>
                setTalk({ contractId: selected, clientId: selectedRow?.client_id ?? clientId })
              }
            />
          ) : null
        }
        onClose={() => setSelected(null)}
        panelLabel="Oś konsultanta"
      />
      {cadenceFor != null ? (
        <CadenceDialog
          contractId={cadenceFor}
          open
          onOpenChange={(open) => {
            if (!open) setCadenceFor(null);
          }}
        />
      ) : null}
      {talk ? (
        <ConversationDialog
          contractId={talk.contractId}
          clientId={talk.clientId}
          open
          onOpenChange={(open) => {
            if (!open) setTalk(null);
          }}
        />
      ) : null}
    </>
  );
}
