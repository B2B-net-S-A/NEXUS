"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Plus, Search } from "lucide-react";

import { KanbanBoard, KanbanCard, KanbanColumn } from "@/components/ds/Kanban";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { personInitials } from "@/components/hr/people/hr-format";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  CASE_AREAS,
  CASE_AREA_LABELS,
  CASE_SOURCE_LABELS,
  CASE_STATUS_LABELS,
  useCases,
  type CaseArea,
  type CaseCard,
  type CaseStatus,
} from "@/lib/api/admin-cases";
import type { HrConfig } from "@/lib/api/hr";
import { resolveViewState } from "@/lib/view-state";

import { CaseFormDialog } from "./CaseFormDialog";
import {
  BOARD_COLUMNS,
  PRIORITY_BADGE,
  caseSubline,
  dueLabel,
  groupByStatus,
  shortDate,
} from "./case-format";

const ALL_AREAS = "all";
const MODULE_OFF_NOTICE =
  "Moduł „Sprawy administracja@” nie jest jeszcze włączony. Włącza go administrator w Ustawieniach → Kadry.";

type Scope = "mine" | "all";

function CaseTile({ card, onOpen }: { card: CaseCard; onOpen: () => void }) {
  const due = dueLabel(card);
  const subline = caseSubline(card);
  return (
    <KanbanCard onClick={onOpen} aria-label={`Sprawa: ${card.title}`}>
      <div className="mb-1.5 flex flex-wrap items-center gap-1">
        {card.source !== "manual" ? (
          <Badge variant="info" size="sm">
            {CASE_SOURCE_LABELS[card.source]}
          </Badge>
        ) : null}
        <Badge variant={PRIORITY_BADGE[card.priority]} size="sm">
          {card.priority}
        </Badge>
        {due ? (
          <Badge variant={due.overdue ? "danger" : "outline"} size="sm">
            {due.text}
          </Badge>
        ) : null}
        {card.follow_up_on && card.status === "waiting" ? (
          <Badge variant="outline" size="sm">
            kontakt {shortDate(card.follow_up_on)}
          </Badge>
        ) : null}
      </div>
      <p className="line-clamp-2 font-medium text-foreground">{card.title}</p>
      <p className="mt-0.5 truncate text-xs text-muted-foreground">
        {subline ? `${subline} · ` : ""}
        {CASE_AREA_LABELS[card.area].toLowerCase()}
      </p>
      <div className="mt-2 flex items-center justify-between gap-2 text-xs text-muted-foreground">
        <span className="truncate">
          {card.contract ? "kontrakt w NEXUSIE" : null}
          {card.checklist_total > 0
            ? `${card.contract ? " · " : ""}${card.checklist_done}/${card.checklist_total} na liście`
            : null}
          {card.status === "done" && card.closed_at ? `zrobione ${shortDate(card.closed_at)}` : null}
        </span>
        {card.assignee ? (
          <span
            title={card.assignee.name ?? undefined}
            className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-primary/10 text-[10px] font-semibold text-primary"
          >
            {personInitials(card.assignee.name ?? "")}
          </span>
        ) : (
          <span className="shrink-0">bez osoby</span>
        )}
      </div>
    </KanbanCard>
  );
}

/** Tablica spraw administracja@: kolumny statusów, Moje/Wszystkie, obszar, szukaj. */
export function CasesBoard({ config }: { config: HrConfig }) {
  const router = useRouter();
  const canManageFromConfig = config.me.cases || config.me.is_admin;
  const [scope, setScope] = useState<Scope>(canManageFromConfig ? "all" : "mine");
  const [area, setArea] = useState<CaseArea | typeof ALL_AREAS>(ALL_AREAS);
  const [query, setQuery] = useState("");
  const [showClosed, setShowClosed] = useState(false);
  const [creating, setCreating] = useState(false);

  const cases = useCases({
    mine: scope === "mine",
    area: area === ALL_AREAS ? null : area,
    q: query,
    include_closed: showClosed,
  });
  const items = useMemo(() => cases.data?.items ?? [], [cases.data]);
  const columns = useMemo<readonly CaseStatus[]>(
    () => (showClosed ? [...BOARD_COLUMNS, "closed"] : BOARD_COLUMNS),
    [showClosed],
  );
  const grouped = useMemo(() => groupByStatus(items, columns), [items, columns]);
  const canManage = cases.data?.can_manage ?? canManageFromConfig;

  const state = resolveViewState({
    isLoading: cases.isLoading,
    isError: cases.isError,
    error: cases.error,
    isSuccess: cases.isSuccess,
    isEmpty: items.length === 0,
  });

  if (state === "not_found") {
    return <QueryStateNotice state="not_found" description={MODULE_OFF_NOTICE} />;
  }
  if (state === "forbidden") {
    return (
      <QueryStateNotice
        state="forbidden"
        description="Sprawy widzą osoby z uprawnieniem „Sprawy” i osoby przypisane do sprawy."
      />
    );
  }

  const overdue = items.filter((item) => item.overdue).length;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {canManage ? (
          <SegmentedRadio
            label="Zakres spraw"
            size="sm"
            value={scope}
            onChange={setScope}
            options={[
              { value: "mine", label: "Moje" },
              { value: "all", label: "Wszystkie" },
            ]}
          />
        ) : null}
        <Select value={area} onValueChange={(value) => setArea(value as CaseArea | "all")}>
          <SelectTrigger className="h-8 w-44" aria-label="Obszar">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL_AREAS}>Wszystkie obszary</SelectItem>
            {CASE_AREAS.map((key) => (
              <SelectItem key={key} value={key}>
                {CASE_AREA_LABELS[key]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <div className="relative w-full sm:w-60">
          <Search
            aria-hidden
            className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
          />
          <Input
            aria-label="Szukaj sprawy"
            placeholder="Szukaj w tytule i opisie…"
            className="h-8 pl-8"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
        <label className="flex items-center gap-2 text-sm text-muted-foreground">
          <Checkbox
            checked={showClosed}
            onCheckedChange={(checked) => setShowClosed(checked === true)}
          />
          Pokaż zamknięte
        </label>
        {cases.isSuccess && overdue > 0 ? (
          <span className="text-sm text-destructive">{overdue} po terminie</span>
        ) : null}
        {canManage ? (
          <Button size="sm" className="ml-auto" onClick={() => setCreating(true)}>
            <Plus className="h-4 w-4" aria-hidden />
            Nowa sprawa
          </Button>
        ) : null}
      </div>

      {state === "loading" ? (
        <p className="py-6 text-sm text-muted-foreground">Wczytywanie spraw…</p>
      ) : state === "error" ? (
        <QueryStateNotice
          state="error"
          description="Nie udało się wczytać spraw."
          onRetry={() => cases.refetch()}
        />
      ) : (
        <>
          {state === "empty" ? (
            <p className="text-sm text-muted-foreground">
              {query.trim() || area !== ALL_AREAS
                ? "Żadna sprawa nie pasuje do filtrów."
                : scope === "mine"
                  ? "Nie masz przypisanych spraw."
                  : "Nie ma otwartych spraw."}
            </p>
          ) : null}
          <KanbanBoard aria-label="Sprawy według statusu">
            {columns.map((status) => (
              <KanbanColumn
                key={status}
                title={CASE_STATUS_LABELS[status]}
                count={grouped[status].length}
                className="w-64"
              >
                {status === "done" && cases.data ? (
                  <p className="px-1 text-xs text-muted-foreground">
                    {cases.data.done_this_month} w tym miesiącu · na tablicy ostatnie 30 dni
                  </p>
                ) : null}
                {grouped[status].map((card) => (
                  <CaseTile
                    key={card.id}
                    card={card}
                    onOpen={() => router.push(`/people/cases/${card.id}`)}
                  />
                ))}
              </KanbanColumn>
            ))}
          </KanbanBoard>
          {cases.data?.truncated ? (
            <p className="text-xs text-muted-foreground">
              Pokazujemy 500 spraw — zawęź obszar albo wyszukiwanie.
            </p>
          ) : null}
        </>
      )}

      {canManage && creating ? (
        <CaseFormDialog
          open={creating}
          onOpenChange={setCreating}
          onCreated={(id) => router.push(`/people/cases/${id}`)}
        />
      ) : null}
    </div>
  );
}
