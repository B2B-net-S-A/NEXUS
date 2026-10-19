"use client";

import { useState } from "react";
import { ChevronDown, Layers, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { MultiSelectFilter } from "@/components/v2/filters/MultiSelectFilter";
import { ClientMultiSelect } from "@/components/v2/filters/ClientMultiSelect";
import { UserMultiSelect } from "@/components/v2/filters/UserMultiSelect";
import {
  PIPELINE_STAGE_OPTIONS,
  type PipelineStageValue,
} from "@/lib/filter-options";
import type { BoardColumnKey } from "@/lib/board-stages";
import {
  STAGE_COLUMN_OPTIONS,
  STAGE_COLUMN_VALUES,
  stageColumnLabel,
} from "@/lib/stage-filter";

/**
 * All sub-values of the unified "Etap" filter. Mirrors the correlated
 * stage-move query on the backend: the picked stage(s) + who/when/client of
 * the matched move, plus the "Aktualny etap" current-only toggle.
 */
export interface StageFilterValue {
  /**
   * „Dodany na etap” — kolumny Tablicy (19.10.2026), LUB-owane. Panel pokazuje
   * tylko je; `stages` (kody etapu) niosą jeszcze stare linki i zapisy.
   */
  columns: BoardColumnKey[];
  /** Pipeline stage(s) — OR-combined (stare linki; panel ich nie wybiera). */
  stages: PipelineStageValue[];
  /** "Aktualny etap" — force CURRENT-stage matching (else auto/historical). */
  currentOnly: boolean;
  /** Client(s) owning the job on which the matched move happened. */
  clientIds: number[];
  /** Who moved the candidate onto the matched stage (0 = system import). */
  movedByIds: number[];
  /** Move date lower bound (inclusive), `YYYY-MM-DD`. */
  movedAfter: string;
  /** Move date upper bound (inclusive), `YYYY-MM-DD`. */
  movedBefore: string;
}

interface StageFilterPanelProps {
  value: StageFilterValue;
  /** Patch one or more sub-values. Caller resets `page` to 1. */
  onChange: (patch: Partial<StageFilterValue>) => void;
  /** Wyłącza cały filtr (np. „nie brał udziału w żadnej rekrutacji”). */
  disabled?: boolean;
}

const EMPTY: StageFilterValue = {
  columns: [],
  stages: [],
  currentOnly: false,
  clientIds: [],
  movedByIds: [],
  movedAfter: "",
  movedBefore: "",
};

function facetCount(v: StageFilterValue): number {
  return (
    (v.columns.length > 0 ? 1 : 0) +
    (v.stages.length > 0 ? 1 : 0) +
    (v.currentOnly ? 1 : 0) +
    (v.clientIds.length > 0 ? 1 : 0) +
    (v.movedByIds.length > 0 ? 1 : 0) +
    (v.movedAfter || v.movedBefore ? 1 : 0)
  );
}

/**
 * Unified Traffit-style "Etap" filter (the panel from the candidates toolbar).
 *
 * Bundles the pipeline-stage chip together with the stage-move correlated
 * who/when/client filters that previously lived buried in "Filtry
 * zaawansowane". Answers "kto i ilu kandydatów dodał na etap X dla klienta Y
 * w okresie od–do" in one place. Backend correlates every sub-field on the
 * SAME stage move (see GET /api/candidates `stage_*` params).
 */
export function StageFilterPanel({ value, onChange, disabled = false }: StageFilterPanelProps) {
  const [open, setOpen] = useState(false);
  const count = facetCount(value);
  const isActive = count > 0;

  // Trigger summary: lead with the stage(s) when picked, else the bare label.
  const legacyStageLabels = value.stages.map(
    (stage) => PIPELINE_STAGE_OPTIONS.find((o) => o.value === stage)?.label ?? stage,
  );
  const pickedLabels = [...value.columns.map(stageColumnLabel), ...legacyStageLabels];
  const triggerText = (() => {
    if (pickedLabels.length === 1) return `Etap: ${pickedLabels[0]}`;
    if (pickedLabels.length > 1) return `Etap: ${pickedLabels.length}`;
    return "Etap";
  })();
  // Kolejność jak na Tablicy — ten sam wybór daje ten sam adres.
  const setColumns = (columns: BoardColumnKey[]) =>
    onChange({
      columns: [...columns].sort(
        (a, b) => STAGE_COLUMN_VALUES.indexOf(a) - STAGE_COLUMN_VALUES.indexOf(b),
      ),
    });

  const clearAll = () => {
    onChange({ ...EMPTY });
    setOpen(false);
  };

  return (
    <Popover open={open && !disabled} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          size="md"
          variant="outline"
          disabled={disabled}
          className={cn(
            "justify-between gap-1.5 bg-card shadow-xs w-[180px]",
            "hover:bg-violet-50 hover:border-violet-300 dark:hover:bg-violet-950/30 dark:hover:border-violet-700",
            isActive &&
              "border-violet-400 bg-violet-50 text-violet-700 font-semibold dark:border-violet-500 dark:bg-violet-950/40 dark:text-violet-200",
          )}
          aria-expanded={open}
          title="Dodany na etap — na który etap, kto i kiedy przesunął kandydata"
        >
          <span className="flex items-center gap-2 truncate">
            <Layers className="h-4 w-4 shrink-0" />
            {triggerText}
          </span>
          {count > 1 ? (
            <Badge variant="burgundy" size="sm" className="-mr-0.5">
              {count}
            </Badge>
          ) : (
            <ChevronDown className="h-4 w-4 opacity-60 shrink-0" />
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        // Wysokość do krawędzi ekranu: samo `80dvh` nadpisywało limit z `PopoverContent`
        // i na laptopie (1280 × 720) góra okienka uciekała nad ekran.
        className="w-80 space-y-3 max-h-[min(80dvh,var(--radix-popover-content-available-height))] overflow-y-auto p-3"
      >
        <div className="flex items-center justify-between">
          <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
            Etapy
          </h3>
          {isActive && (
            <button
              type="button"
              onClick={clearAll}
              className="inline-flex items-center gap-1 text-[11px] text-muted-foreground hover:text-primary"
            >
              <X className="h-3 w-3" /> Wyczyść etap
            </button>
          )}
        </div>

        {/* Dodany na etap — kolumny Tablicy */}
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-1.5">
            Dodany na etap
          </h4>
          <MultiSelectFilter<BoardColumnKey>
            value={value.columns}
            onChange={setColumns}
            options={STAGE_COLUMN_OPTIONS}
            placeholder="Dowolny etap"
            searchPlaceholder="Szukaj etapu…"
            triggerWidthClass="w-full"
            triggerLabel={(n, selected) =>
              n === 1 ? stageColumnLabel(selected[0]) : `Etapy: ${n}`
            }
          />
          {legacyStageLabels.length > 0 && (
            <p className="mt-1 flex items-center justify-between gap-2 text-[10px] text-muted-foreground">
              <span className="min-w-0 truncate" title={legacyStageLabels.join(", ")}>
                Ze starego linku: {legacyStageLabels.join(", ")}
              </span>
              <button
                type="button"
                onClick={() => onChange({ stages: [] })}
                className="shrink-0 hover:text-primary"
              >
                Usuń
              </button>
            </p>
          )}
        </div>

        {/* Tylko obecny etap — current-only toggle */}
        <label className="flex items-start justify-between gap-3 rounded-md border border-border bg-card px-2.5 py-2 cursor-pointer">
          <span className="space-y-0.5">
            <span className="block text-sm font-medium text-foreground">
              Tylko osoby, które nadal są na tym etapie
            </span>
            <span className="block text-[10px] leading-tight text-muted-foreground">
              Wyłączone przy osobie lub dacie: także ci, którzy z tego etapu poszli
              dalej.
            </span>
          </span>
          <Switch
            checked={value.currentOnly}
            onCheckedChange={(checked) => onChange({ currentOnly: checked })}
            aria-label="Tylko osoby, które nadal są na tym etapie"
          />
        </label>

        {/* Dodany przez */}
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-1.5">
            Dodany przez
          </h4>
          <UserMultiSelect
            value={value.movedByIds}
            onChange={(movedByIds) => onChange({ movedByIds })}
            placeholder="Dowolna osoba"
            searchPlaceholder="Szukaj osoby…"
            triggerWidthClass="w-full"
          />
          <p className="text-[10px] text-muted-foreground mt-1">
            Kto przesunął osobę na ten etap.
          </p>
        </div>

        {/* Dodany od – do */}
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-1.5">
            Dodany od – do
          </h4>
          <div className="flex items-center gap-2">
            <div className="flex-1 space-y-1">
              <label className="block text-[10px] text-muted-foreground">
                od
              </label>
              <Input
                type="date"
                aria-label="Dodany na etap — od"
                value={value.movedAfter}
                max={value.movedBefore || undefined}
                onChange={(e) => onChange({ movedAfter: e.target.value })}
                className="text-sm"
              />
            </div>
            <div className="flex-1 space-y-1">
              <label className="block text-[10px] text-muted-foreground">
                do
              </label>
              <Input
                type="date"
                aria-label="Dodany na etap — do"
                value={value.movedBefore}
                min={value.movedAfter || undefined}
                onChange={(e) => onChange({ movedBefore: e.target.value })}
                className="text-sm"
              />
            </div>
          </div>
          <p className="text-[10px] text-muted-foreground mt-1">
            Kiedy osoba trafiła na ten etap (obie daty włącznie).
          </p>
        </div>

        {/* Klient */}
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-1.5">
            Klient
          </h4>
          <ClientMultiSelect
            value={value.clientIds}
            onChange={(clientIds) => onChange({ clientIds })}
          />
          <p className="text-[10px] text-muted-foreground mt-1">
            Klient rekrutacji, w której osoba trafiła na ten etap.
          </p>
        </div>
      </PopoverContent>
    </Popover>
  );
}
