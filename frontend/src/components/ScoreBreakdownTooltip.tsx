"use client";

import { useState } from "react";
import { Info } from "lucide-react";
import type { ScoreBreakdown } from "@/lib/api";

interface Props {
  breakdown: ScoreBreakdown;
  compact?: boolean;
}

function Row({
  label,
  points,
  max,
  reason,
}: {
  label: string;
  points: number;
  max: number;
  reason: string;
}) {
  const pct = max > 0 ? (points / max) * 100 : 0;
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-24 text-muted-foreground dark:text-muted-foreground">{label}</span>
      <div className="flex-1 h-1.5 bg-muted dark:bg-muted rounded-full overflow-hidden">
        <div
          className="h-full bg-primary"
          style={{ width: `${Math.min(100, pct)}%` }}
        />
      </div>
      <span className="w-12 text-right text-foreground dark:text-muted-foreground">
        {points.toFixed(1)}/{max}
      </span>
      <span className="flex-1 text-[11px] text-muted-foreground truncate" title={reason}>
        {reason}
      </span>
    </div>
  );
}

export function ScoreBreakdownTooltip({ breakdown, compact }: Props) {
  const [open, setOpen] = useState(false);

  return (
    <div className="relative inline-block">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        onBlur={() => setTimeout(() => setOpen(false), 200)}
        className="inline-flex items-center gap-1 text-xs text-primary hover:text-primary/80 dark:text-primary"
        aria-label="Pokaż rozbicie punktów"
      >
        <Info className="w-3.5 h-3.5" />
        {!compact && "dlaczego ? "}
      </button>
      {open && (
        <div
          className="absolute z-50 mt-1 right-0 w-96 rounded-lg bg-card dark:bg-card shadow-lg border border-border dark:border-border p-3 space-y-1.5"
          onMouseDown={(e) => e.preventDefault()}
        >
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs uppercase tracking-wide text-muted-foreground">
              Rozbicie score (0-100)
            </span>
            <span className="text-lg font-bold text-foreground dark:text-foreground">
              {breakdown.total.toFixed(1)}
            </span>
          </div>
          <Row label="Semantic" {...breakdown.semantic} />
          <Row label="Skills" {...breakdown.skills} />
          <Row label="Salary" {...breakdown.salary} />
          <Row label="Location" {...breakdown.location} />
          <Row label="Availability" {...breakdown.availability} />
          {breakdown.champion_fit && (
            <Row label="Champion" {...breakdown.champion_fit} />
          )}

          {breakdown.penalties.length > 0 && (
            <div className="mt-2 rounded bg-destructive/10 dark:bg-destructive/15 border border-destructive/20 dark:border-red-800 p-2 text-xs text-destructive dark:text-red-300">
              ⛔ Penalties: {breakdown.penalties.join(", ")}
            </div>
          )}

          {breakdown.matching_must.length + breakdown.gap_must.length > 0 && (
            <div className="mt-2 text-[11px]">
              <div className="text-muted-foreground mb-0.5">Must-have:</div>
              <div className="flex flex-wrap gap-1">
                {breakdown.matching_must.map((s) => (
                  <span
                    key={`m-${s}`}
                    className="px-1.5 py-0.5 rounded bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300"
                  >
                    ✓ {s}
                  </span>
                ))}
                {breakdown.gap_must.map((s) => (
                  <span
                    key={`g-${s}`}
                    className="px-1.5 py-0.5 rounded bg-destructive/15 text-destructive dark:bg-red-900/30 dark:text-red-300"
                  >
                    ✗ {s}
                  </span>
                ))}
              </div>
            </div>
          )}

          {breakdown.matching_nice.length + breakdown.gap_nice.length > 0 && (
            <div className="mt-1 text-[11px]">
              <div className="text-muted-foreground mb-0.5">Nice-to-have:</div>
              <div className="flex flex-wrap gap-1">
                {breakdown.matching_nice.map((s) => (
                  <span
                    key={`mn-${s}`}
                    className="px-1.5 py-0.5 rounded bg-primary/15 text-primary dark:bg-primary/30 dark:text-primary"
                  >
                    ✓ {s}
                  </span>
                ))}
                {breakdown.gap_nice.map((s) => (
                  <span
                    key={`gn-${s}`}
                    className="px-1.5 py-0.5 rounded bg-muted text-muted-foreground dark:bg-muted dark:text-muted-foreground"
                  >
                    · {s}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
