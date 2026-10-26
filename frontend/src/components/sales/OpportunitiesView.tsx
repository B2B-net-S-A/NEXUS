"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Plus, Target } from "lucide-react";
import { useMemo, useState } from "react";

import { EmptyState } from "@/components/ds/EmptyState";
import { FilterBar } from "@/components/ds/FilterBar";
import { InlineStats } from "@/components/ds/InlineStats";
import { KanbanBoard, KanbanCard, KanbanColumn } from "@/components/ds/Kanban";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { Button } from "@/components/ui/button";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  SERVICE_LINE_LABELS,
  useOpportunities,
  usePipelines,
  type Opportunity,
  type OpportunityStatus,
  type Stage,
} from "@/lib/api/sales";
import { CALM_AMOUNT, CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { formatIsoDatePl } from "@/lib/date-pl";
import { hasPermission } from "@/lib/permissions";
import { useUrlWriter } from "@/lib/url-selection";
import { resolveViewState } from "@/lib/view-state";
import { useAuthStore } from "@/store/auth";

import { daysLabel, daysSince, formatDealAmount, formatDealNumber } from "./format";
import { OpportunityFormDialog } from "./OpportunityFormDialog";

/** Szansa bez kontaktu dłużej niż tyle dni dostaje ostrzeżenie (Atlas: 14). */
export const STALE_AFTER_DAYS = 14;

const STATUS_TONES: Record<OpportunityStatus, "info" | "success" | "neutral"> = {
  open: "info",
  won: "success",
  lost: "neutral",
};
const STATUS_LABELS: Record<OpportunityStatus, string> = {
  open: "Otwarta",
  won: "Wygrana",
  lost: "Przegrana",
};

type View = "board" | "list";

export interface PipelineSummary {
  open: number;
  value: number;
  weighted: number;
  won: number;
}

/** Liczby nad tablicą: otwarte szanse, wartość lejka, prognoza ważona, wygrane. */
export function summarize(items: readonly Opportunity[]): PipelineSummary {
  return items.reduce<PipelineSummary>(
    (sum, item) => {
      if (item.status === "won") return { ...sum, won: sum.won + 1 };
      if (item.status !== "open") return sum;
      return {
        open: sum.open + 1,
        value: sum.value + Number(item.value ?? 0),
        weighted: sum.weighted + Number(item.weighted_value ?? 0),
        won: sum.won,
      };
    },
    { open: 0, value: 0, weighted: 0, won: 0 },
  );
}

/** Kolumny tablicy: etapy otwarte i wygrana. Przegrane są na liście. */
export function boardStages(stages: readonly Stage[]): Stage[] {
  return stages.filter((stage) => stage.outcome !== "lost");
}

function OpportunityTile({ item, onOpen }: { item: Opportunity; onOpen: () => void }) {
  const idle = daysSince(item.last_activity_at ?? item.created_at);
  return (
    <KanbanCard onClick={onOpen} aria-label={`${item.company.name} · ${item.title}`}>
      <p className="font-medium text-foreground">{item.company.name}</p>
      <p className="text-muted-foreground">{item.title}</p>
      <div className="mt-2 flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <span className="tabular-nums text-foreground">{formatDealAmount(item.value, item.currency)}</span>
        {item.status === "open" && idle !== null && idle > STALE_AFTER_DAYS ? (
          <span className="text-warning">bez kontaktu {daysLabel(idle)}</span>
        ) : item.expected_close_date ? (
          <span>zamknięcie {formatIsoDatePl(item.expected_close_date)}</span>
        ) : null}
      </div>
      {item.owner && <p className="mt-1 text-xs text-muted-foreground">{item.owner.name}</p>}
    </KanbanCard>
  );
}

export function OpportunitiesView() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { replaceUrl } = useUrlWriter();
  const user = useAuthStore((s) => s.user);
  const canEdit = hasPermission(user, "sales_edit");
  const view: View = searchParams?.get("view") === "list" ? "list" : "board";
  const mine = searchParams?.get("mine") === "1";
  const [q, setQ] = useState(searchParams?.get("q") ?? "");
  const [creating, setCreating] = useState(false);

  const pipelines = usePipelines();
  const pipeline = pipelines.data?.find((p) => p.is_default) ?? pipelines.data?.[0];
  const opportunities = useOpportunities(
    {
      pipeline_id: pipeline?.id ?? null,
      owner_id: mine ? (user?.id ?? null) : null,
      q,
    },
    Boolean(pipeline),
  );
  const items = useMemo(() => opportunities.data?.items ?? [], [opportunities.data]);
  const summary = useMemo(() => summarize(items), [items]);

  const writeParam = (key: string, value: string | null) => {
    const params = new URLSearchParams(window.location.search);
    if (value) params.set(key, value);
    else params.delete(key);
    const qs = params.toString();
    replaceUrl(qs ? `${window.location.pathname}?${qs}` : window.location.pathname);
  };

  const state = resolveViewState({
    isLoading: pipelines.isLoading || opportunities.isLoading,
    error: pipelines.error ?? opportunities.error,
    isSuccess: pipelines.isSuccess && opportunities.isSuccess,
    isEmpty: items.length === 0,
  });
  const open = (id: number) => router.push(`/sales/opportunities/${id}`);

  return (
    <div className="space-y-3">
      <FilterBar
        search={{
          value: q,
          onChange: (value) => {
            setQ(value);
            writeParam("q", value.trim() || null);
          },
          placeholder: "Szukaj szansy albo firmy…",
          ariaLabel: "Szukaj szansy albo firmy",
        }}
        filters={
          <div className="flex flex-wrap items-center gap-2">
            <SegmentedRadio
              size="sm"
              label="Czyje szanse"
              options={[
                { value: "all", label: "Wszystkie" },
                { value: "mine", label: "Moje" },
              ]}
              value={mine ? "mine" : "all"}
              onChange={(value) => writeParam("mine", value === "mine" ? "1" : null)}
            />
            <SegmentedRadio
              size="sm"
              label="Widok"
              options={[
                { value: "board", label: "Tablica" },
                { value: "list", label: "Lista" },
              ]}
              value={view}
              onChange={(value) => writeParam("view", value === "list" ? "list" : null)}
            />
          </div>
        }
        actions={
          canEdit ? (
            <Button size="sm" onClick={() => setCreating(true)}>
              <Plus className="mr-1 h-4 w-4" aria-hidden /> Szansa
            </Button>
          ) : null
        }
      />
      {state === "ready" && (
        <InlineStats
          stats={[
            { id: "open", label: "otwartych szans", value: summary.open },
            { id: "value", label: "w lejku", value: formatDealAmount(summary.value) },
            {
              id: "weighted",
              label: "prognoza ważona",
              value: formatDealAmount(summary.weighted),
              title: "Wartość × prawdopodobieństwo etapu",
            },
            { id: "won", label: "wygranych", value: summary.won },
          ]}
        />
      )}

      {state === "loading" ? (
        <p className="py-6 text-sm text-muted-foreground">Wczytywanie szans…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" ? (
        <QueryStateNotice state={state} onRetry={() => void opportunities.refetch()} />
      ) : state === "empty" ? (
        <EmptyState
          icon={Target}
          title={q || mine ? "Nic nie pasuje do filtrów" : "Nie ma jeszcze szans"}
          description={
            q || mine
              ? "Zmień wyszukiwanie albo pokaż wszystkie szanse."
              : "Dodaj pierwszą szansę — zacznij od firmy w zakładce Firmy."
          }
          action={
            canEdit && !q && !mine ? (
              <Button size="sm" onClick={() => setCreating(true)}>
                Dodaj szansę
              </Button>
            ) : undefined
          }
        />
      ) : view === "board" && pipeline ? (
        <KanbanBoard aria-label="Tablica szans">
          {boardStages(pipeline.stages).map((stage) => {
            const column = items.filter((item) => item.stage.id === stage.id);
            return (
              <KanbanColumn key={stage.id} title={stage.name} count={column.length}>
                {column.map((item) => (
                  <OpportunityTile key={item.id} item={item} onOpen={() => open(item.id)} />
                ))}
              </KanbanColumn>
            );
          })}
        </KanbanBoard>
      ) : (
        <div className="relative overflow-x-auto">
          <Table className="min-w-[860px]">
            <TableHeader>
              <TableRow>
                <TableHead className={`${CALM_HEAD} sticky left-0 bg-card`}>Szansa</TableHead>
                <TableHead className={CALM_HEAD}>Etap</TableHead>
                <TableHead className={CALM_HEAD}>Status</TableHead>
                <TableHead className={`${CALM_HEAD} text-right`}>Wartość (zł)</TableHead>
                <TableHead className={CALM_HEAD}>Opiekun</TableHead>
                <TableHead className={CALM_HEAD}>Ostatnia aktywność</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((item) => (
                <TableRow
                  key={item.id}
                  className={`${CALM_ROW} cursor-pointer`}
                  onClick={() => open(item.id)}
                >
                  <TableCell className="sticky left-0 bg-card">
                    <Link
                      href={`/sales/opportunities/${item.id}`}
                      className="font-medium text-foreground hover:underline"
                      onClick={(event) => event.stopPropagation()}
                    >
                      {item.title}
                    </Link>
                    <p className={CALM_SUBLINE}>
                      {item.company.name}
                      {item.service_line ? ` · ${SERVICE_LINE_LABELS[item.service_line]}` : ""}
                    </p>
                  </TableCell>
                  <TableCell>{item.stage.name}</TableCell>
                  <TableCell>
                    <StatusDot tone={STATUS_TONES[item.status]}>{STATUS_LABELS[item.status]}</StatusDot>
                  </TableCell>
                  <TableCell className={CALM_AMOUNT}>
                    {formatDealNumber(item.value)}
                  </TableCell>
                  <TableCell>{item.owner?.name ?? "—"}</TableCell>
                  <TableCell>
                    {formatIsoDatePl(item.last_activity_at)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {items.length === 0 && <p className={CALM_EMPTY}>Brak szans.</p>}
        </div>
      )}

      {creating && (
        <OpportunityFormDialog
          open={creating}
          onOpenChange={setCreating}
          onCreated={(opportunity) => open(opportunity.id)}
        />
      )}
    </div>
  );
}
