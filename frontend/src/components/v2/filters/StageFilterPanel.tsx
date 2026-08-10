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

/**
 * All sub-values of the unified "Etap" filter. Mirrors the correlated
 * stage-move query on the backend: the picked stage(s) + who/when/client of
 * the matched move, plus the "Aktualny etap" current-only toggle.
 */
export interface StageFilterValue {
  /** Pipeline stage(s) — OR-combined. */
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
}

const EMPTY: StageFilterValue = {
  stages: [],
  currentOnly: false,
  clientIds: [],
  movedByIds: [],
  movedAfter: "",
  movedBefore: "",
};

function facetCount(v: StageFilterValue): number {
  return (
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
export function StageFilterPanel({ value, onChange }: StageFilterPanelProps) {
  const [open, setOpen] = useState(false);
  const count = facetCount(value);
  const isActive = count > 0;

  // Trigger summary: lead with the stage(s) when picked, else the bare label.
  const triggerText = (() => {
    if (value.stages.length === 1) {
      const opt = PIPELINE_STAGE_OPTIONS.find(
        (o) => o.value === value.stages[0],
      );
      return `Etap: ${opt?.label ?? value.stages[0]}`;
    }
    if (value.stages.length > 1) return `Etap: ${value.stages.length}`;
    return "Etap";
  })();

  const clearAll = () => {
    onChange({ ...EMPTY });
    setOpen(false);
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          size="md"
          variant="outline"
          className={cn(
            "justify-between gap-1.5 bg-card shadow-xs w-[180px]",
            "hover:bg-violet-50 hover:border-violet-300 dark:hover:bg-violet-950/30 dark:hover:border-violet-700",
            isActive &&
              "border-violet-400 bg-violet-50 text-violet-700 font-semibold dark:border-violet-500 dark:bg-violet-950/40 dark:text-violet-200",
          )}
          aria-expanded={open}
          title="Filtruj po etapie pipeline'u — etap, klient, kto i kiedy przeniósł kandydata"
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
        className="w-80 space-y-3 max-h-[80vh] overflow-y-auto p-3"
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

        {/* Aktualny etap — current-only toggle */}
        <label className="flex items-start justify-between gap-3 rounded-md border border-border bg-card px-2.5 py-2 cursor-pointer">
          <span className="space-y-0.5">
            <span className="block text-sm font-medium text-foreground">
              Aktualny etap
            </span>
            <span className="block text-[10px] leading-tight text-muted-foreground">
              Włączone: tylko kandydaci, których AKTUALNY etap pasuje. Wyłączone:
              też ci, którzy byli na etapie i poszli dalej (historycznie) — gdy
              filtrujesz po kliencie / osobie / dacie.
            </span>
          </span>
          <Switch
            checked={value.currentOnly}
            onCheckedChange={(checked) => onChange({ currentOnly: checked })}
            aria-label="Aktualny etap"
          />
        </label>

        {/* Etap */}
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-1.5">
            Etap
          </h4>
          <MultiSelectFilter<PipelineStageValue>
            value={value.stages}
            onChange={(stages) => onChange({ stages })}
            options={PIPELINE_STAGE_OPTIONS}
            placeholder="Dowolny etap"
            searchPlaceholder="Szukaj etapu…"
            triggerWidthClass="w-full"
            triggerLabel={(n) =>
              n === 1
                ? (PIPELINE_STAGE_OPTIONS.find((o) => o.value === value.stages[0])
                    ?.label ?? "Etap")
                : `Etap: ${n}`
            }
          />
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
            Klient rekrutacji, na której nastąpiło przejście na wybrany etap.
          </p>
        </div>

        {/* Umieszczony przez użytkownika */}
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-1.5">
            Umieszczony przez użytkownika
          </h4>
          <UserMultiSelect
            value={value.movedByIds}
            onChange={(movedByIds) => onChange({ movedByIds })}
            placeholder="Dowolny rekruter"
            searchPlaceholder="Szukaj rekrutera…"
            triggerWidthClass="w-full"
          />
          <p className="text-[10px] text-muted-foreground mt-1">
            Kto przeniósł kandydata na wybrany etap.
          </p>
        </div>

        {/* Data umieszczenia od / do */}
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-1.5">
            Data umieszczenia
          </h4>
          <div className="flex items-center gap-2">
            <div className="flex-1 space-y-1">
              <label className="block text-[10px] text-muted-foreground">
                od
              </label>
              <Input
                type="date"
                aria-label="Data umieszczenia na etap — od"
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
                aria-label="Data umieszczenia na etap — do"
                value={value.movedBefore}
                min={value.movedAfter || undefined}
                onChange={(e) => onChange({ movedBefore: e.target.value })}
                className="text-sm"
              />
            </div>
          </div>
          <p className="text-[10px] text-muted-foreground mt-1">
            Kiedy kandydat trafił na wybrany etap (zakres dat, włącznie).
          </p>
        </div>
      </PopoverContent>
    </Popover>
  );
}
