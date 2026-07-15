"use client";

import * as React from "react";
import { ChevronDown, ChevronRight, Users } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { avatarTone } from "@/components/v2/pages/candidate-list-helpers";
import { StagePill } from "@/components/v2/candidates/StagePill";
import {
  type CandidateDetailData,
  CandidateDetailPanel,
} from "@/components/v2/candidates/CandidateDetailPanel";
import { CandidateRowDetail } from "@/components/v2/candidates/CandidateRowDetail";

export interface CandidatesSplitViewProps {
  rows: CandidateDetailData[];
  isLoading: boolean;
  isError: boolean;
  errorPanel?: React.ReactNode;
  selectedIds: Set<number>;
  onToggleSelect: (id: number) => void;
  /** Open the full profile / QuickView drawer for a candidate. */
  onOpenFullProfile: (id: number) => void;
  onAddCandidate?: () => void;
  page: number;
  totalPages: number;
  onPrevPage: () => void;
  onNextPage: () => void;
}

interface SplitRowProps {
  row: CandidateDetailData;
  checked: boolean;
  selected: boolean;
  expanded: boolean;
  onToggleCheck: () => void;
  onSelect: () => void;
  onToggleExpand: () => void;
}

function SplitRow({
  row,
  checked,
  selected,
  expanded,
  onToggleCheck,
  onSelect,
  onToggleExpand,
}: SplitRowProps) {
  const meta = [row.owner, row.stageDate].filter(Boolean).join(" · ");
  return (
    <div
      className={cn(
        "border-b border-border/70 border-l-[3px] transition-colors",
        selected
          ? "border-l-primary bg-primary/[0.06]"
          : "border-l-transparent hover:bg-muted/50",
      )}
    >
      <div className="flex items-start gap-2.5 px-3 py-3">
        <div className="pt-1.5">
          <Checkbox
            checked={checked}
            onCheckedChange={onToggleCheck}
            aria-label={`Zaznacz: ${row.name}`}
          />
        </div>
        <button
          type="button"
          onClick={onSelect}
          className="flex min-w-0 flex-1 items-start gap-3 text-left"
        >
          <div
            className={cn(
              "flex size-10 shrink-0 items-center justify-center rounded-full text-[13px] font-bold",
              avatarTone(String(row.id)),
            )}
          >
            {row.initials}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-baseline justify-between gap-2">
              <span className="truncate text-sm font-semibold text-foreground">
                {row.name}
              </span>
              {row.rateLabel ? (
                <span className="shrink-0 text-xs font-semibold tabular-nums text-foreground">
                  {row.rateLabel}
                </span>
              ) : null}
            </div>
            {row.role || row.location ? (
              <div className="truncate text-xs text-muted-foreground">
                {[row.role, row.location].filter(Boolean).join(" · ")}
              </div>
            ) : null}
            <div className="mt-1.5 flex min-w-0 items-center gap-2">
              {row.stage ? <StagePill stage={row.stage} size="sm" /> : null}
              {meta ? (
                <span className="truncate text-[11px] text-muted-foreground">
                  {meta}
                </span>
              ) : null}
            </div>
          </div>
        </button>
        <button
          type="button"
          onClick={onToggleExpand}
          aria-label={expanded ? "Zwiń szczegóły" : "Pokaż szczegóły"}
          aria-expanded={expanded}
          className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
        >
          <ChevronDown
            aria-hidden
            className={cn("size-4 transition-transform", expanded && "rotate-180")}
          />
        </button>
      </div>
      {expanded ? <CandidateRowDetail candidate={row} className="pl-[3.75rem]" /> : null}
    </div>
  );
}

/** Design option 1a+1b as an opt-in view: a scannable list with per-row
 *  expansion on the left and a docked profile panel on the right. Fed the same
 *  data the table/tiles views use — purely additive, so those views are
 *  untouched. */
export function CandidatesSplitView({
  rows,
  isLoading,
  isError,
  errorPanel,
  selectedIds,
  onToggleSelect,
  onOpenFullProfile,
  onAddCandidate,
  page,
  totalPages,
  onPrevPage,
  onNextPage,
}: CandidatesSplitViewProps) {
  // `undefined` = nothing chosen yet → default to the first row so the panel is
  // populated on arrival; `null` = user explicitly closed the panel.
  const [selectedId, setSelectedId] = React.useState<number | null | undefined>(
    undefined,
  );
  const [expanded, setExpanded] = React.useState<Record<number, boolean>>({});

  const effectiveSelectedId =
    selectedId === undefined
      ? rows.length > 0
        ? Number(rows[0].id)
        : null
      : selectedId;
  const selected =
    rows.find((r) => Number(r.id) === effectiveSelectedId) ?? null;

  const toggleExpand = (id: number) =>
    setExpanded((prev) => ({ ...prev, [id]: !prev[id] }));

  return (
    <div className="overflow-hidden rounded-lg border border-border bg-card">
      <div className="flex h-[70vh] min-h-[520px]">
        {/* List */}
        <div className="min-w-0 flex-1 overflow-y-auto">
          {isLoading ? (
            <div className="divide-y divide-border">
              {Array.from({ length: 8 }).map((_, i) => (
                <div key={i} className="flex items-center gap-3 px-3 py-3.5">
                  <Skeleton className="size-10 shrink-0 rounded-full" />
                  <div className="flex-1 space-y-2">
                    <Skeleton className="h-3.5 w-40" />
                    <Skeleton className="h-3 w-56" />
                  </div>
                </div>
              ))}
            </div>
          ) : isError && rows.length === 0 ? (
            (errorPanel ?? (
              <div className="py-16 text-center text-sm text-muted-foreground">
                Nie udało się wczytać kandydatów.
              </div>
            ))
          ) : rows.length === 0 ? (
            <div className="py-16 text-center text-sm text-muted-foreground">
              <Users className="mx-auto mb-3 h-12 w-12 text-muted-foreground" />
              Brak wyników. Zmień filtry
              {onAddCandidate ? (
                <>
                  {" lub "}
                  <button
                    type="button"
                    className="text-primary hover:underline"
                    onClick={onAddCandidate}
                  >
                    dodaj nowego kandydata
                  </button>
                </>
              ) : null}
              .
            </div>
          ) : (
            rows.map((row) => {
              const id = Number(row.id);
              return (
                <SplitRow
                  key={id}
                  row={row}
                  checked={selectedIds.has(id)}
                  selected={effectiveSelectedId === id}
                  expanded={!!expanded[id]}
                  onToggleCheck={() => onToggleSelect(id)}
                  onSelect={() => setSelectedId(id)}
                  onToggleExpand={() => toggleExpand(id)}
                />
              );
            })
          )}
        </div>

        {/* Docked profile panel */}
        {selected ? (
          <div className="hidden w-[420px] shrink-0 border-l border-border xl:block">
            <CandidateDetailPanel
              candidate={selected}
              onClose={() => setSelectedId(null)}
              onOpenProfile={() => onOpenFullProfile(Number(selected.id))}
            />
          </div>
        ) : null}
      </div>

      {/* Pagination */}
      {!isLoading && rows.length > 0 ? (
        <div className="flex h-12 items-center justify-between gap-3 border-t border-border bg-muted/40 px-4 text-sm dark:bg-muted/20">
          <span className="text-muted-foreground">
            Strona <span className="font-semibold text-foreground">{page}</span> z{" "}
            {totalPages}
          </span>
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="outline"
              disabled={page <= 1}
              onClick={onPrevPage}
            >
              Poprzednia
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={page >= totalPages}
              onClick={onNextPage}
            >
              Następna <ChevronRight className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
