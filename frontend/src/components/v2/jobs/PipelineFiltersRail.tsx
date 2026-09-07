"use client";

/**
 * PipelineFiltersRail — lewa kolumna zakładki „Pipeline" (krok 04, program
 * „flow w języku C2", PR 3/7).
 *
 * Czysto prezentacyjny (bez własnego stanu poza hover) — `KanbanBoardV2`
 * liczy liczniki i trzyma filtry, ten komponent tylko je pokazuje i emituje
 * zdarzenia. Dzięki temu jest łatwy do przetestowania w izolacji.
 *
 * Filtry „Utknęli > 7 d" / „Zablokowani bramką" / „Rekruter" NIE usuwają
 * kart z tablicy (usunięcie zepsułoby indeksy `@hello-pangea/dnd` używane
 * przez `onDragEnd` — patrz komentarz w `KanbanBoardV2`) — przyciemniają
 * niepasujące karty. Stąd liczniki obok etykiet: ukrywanie nigdy nie jest
 * ciche (kontrakt programu C2).
 */

import { Filter, LayoutGrid, Users } from "lucide-react";

import { Checkbox } from "@/components/ui/checkbox";
import { cn } from "@/lib/utils";
import { colId, columnLabel, type KanbanColumn } from "@/components/v2/pages/kanban-shared";

const STAGE_DOT_COLOR: Record<string, string> = {
  internal: "bg-primary",
  external: "bg-card border border-border",
  terminal: "bg-muted-foreground",
};

function FilterPill({
  active,
  onClick,
  label,
  title,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  title?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      aria-pressed={active}
      className={cn(
        "rounded-full border px-2 py-0.5 text-[11px] transition-colors",
        active
          ? "border-primary bg-primary text-primary-foreground"
          : "border-border bg-background text-foreground hover:bg-accent"
      )}
    >
      {label}
    </button>
  );
}

export interface PipelineFiltersRailProps {
  /** Kolumny SZABLONU (bez kubełka „Poza szablonem") — do listy etapów. */
  stageCols: KanbanColumn[];
  focusedColId: string | null;
  onFocusColumn: (id: string) => void;
  /** 0 = kubełek nie istnieje / jest pusty → pigułka się nie renderuje. */
  offTemplateCount: number;
  onFocusOffTemplate: () => void;
  stuckFilter: boolean;
  onToggleStuckFilter: () => void;
  stuckCount: number;
  blockedFilter: boolean;
  onToggleBlockedFilter: () => void;
  blockedCount: number;
  recruiters: string[];
  recruiterFilter: string | null;
  onSetRecruiterFilter: (name: string | null) => void;
  hideEmptyColumns: boolean;
  onToggleHideEmptyColumns: () => void;
}

export function PipelineFiltersRail({
  stageCols,
  focusedColId,
  onFocusColumn,
  offTemplateCount,
  onFocusOffTemplate,
  stuckFilter,
  onToggleStuckFilter,
  stuckCount,
  blockedFilter,
  onToggleBlockedFilter,
  blockedCount,
  recruiters,
  recruiterFilter,
  onSetRecruiterFilter,
  hideEmptyColumns,
  onToggleHideEmptyColumns,
}: PipelineFiltersRailProps) {
  return (
    <aside className="space-y-4 self-start rounded-xl border border-border bg-card p-4">
      <div className="flex items-center gap-1.5 text-sm font-semibold text-foreground">
        <LayoutGrid className="h-4 w-4 text-primary" />
        Etapy
      </div>

      {stageCols.length > 0 && (
        <div className="space-y-0.5" role="list" aria-label="Etapy pipeline">
          {stageCols.map((col) => {
            const id = colId(col);
            const active = id === focusedColId;
            return (
              <button
                key={id}
                type="button"
                role="listitem"
                onClick={() => onFocusColumn(id)}
                aria-current={active ? "true" : undefined}
                className={cn(
                  "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs transition-colors",
                  active
                    ? "bg-primary/10 font-medium text-primary"
                    : "text-foreground hover:bg-accent"
                )}
              >
                <span
                  className={cn(
                    "h-1.5 w-1.5 shrink-0 rounded-full",
                    STAGE_DOT_COLOR[col.category ?? "internal"]
                  )}
                  aria-hidden="true"
                />
                <span className="min-w-0 flex-1 truncate">{columnLabel(col)}</span>
                <span className="tabular-nums text-muted-foreground">{col.count}</span>
              </button>
            );
          })}
        </div>
      )}

      <div className="space-y-1.5 border-t border-border pt-3">
        <div className="flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground">
          <Filter className="h-3 w-3" />
          Pokaż
        </div>
        <div className="flex flex-wrap gap-1">
          <FilterPill
            active={stuckFilter}
            onClick={onToggleStuckFilter}
            label={
              stuckCount > 0 ? `Utknęli > 7 d · ${stuckCount}` : "Utknęli > 7 d"
            }
            title="Podświetl kandydatów stojących na etapie dłużej niż 7 dni"
          />
          <FilterPill
            active={blockedFilter}
            onClick={onToggleBlockedFilter}
            label={
              blockedCount > 0
                ? `Zablokowani bramką · ${blockedCount}`
                : "Zablokowani bramką"
            }
            title="Podświetl kandydatów zablokowanych przez bramkę dopuszczalności lub weryfikację"
          />
          {offTemplateCount > 0 && (
            <FilterPill
              active={false}
              onClick={onFocusOffTemplate}
              label={`Poza szablonem · ${offTemplateCount}`}
              title="Przewiń do kolumny z kartami spoza szablonu"
            />
          )}
        </div>
      </div>

      {recruiters.length > 1 && (
        <div className="space-y-1.5">
          <div className="flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground">
            <Users className="h-3 w-3" />
            Rekruter
          </div>
          <div className="flex flex-wrap gap-1">
            <FilterPill
              active={recruiterFilter == null}
              onClick={() => onSetRecruiterFilter(null)}
              label="Wszyscy"
            />
            {recruiters.map((name) => (
              <FilterPill
                key={name}
                active={recruiterFilter === name}
                onClick={() =>
                  onSetRecruiterFilter(recruiterFilter === name ? null : name)
                }
                label={name}
              />
            ))}
          </div>
        </div>
      )}

      <div className="border-t border-border pt-3">
        <label className="flex cursor-pointer items-center gap-2 text-xs text-foreground">
          <Checkbox
            checked={hideEmptyColumns}
            onCheckedChange={() => onToggleHideEmptyColumns()}
            aria-label="Ukryj puste kolumny"
          />
          Ukryj puste kolumny
        </label>
      </div>
    </aside>
  );
}
