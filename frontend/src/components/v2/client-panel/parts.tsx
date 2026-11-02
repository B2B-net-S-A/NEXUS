"use client";

/** Drobne klocki panelu klienta: kropka statusu, plakietka, zakładki, karta. */

import type { ReactNode } from "react";

import type { RequirementStatus } from "@/lib/api/clientPanel";
import { cn } from "@/lib/utils";

import { STATE_LABELS, STATUS_LABELS, type PillTone } from "./panel-logic";
import type { PanelCandidateState } from "@/lib/api/clientPanel";

const DOT_CLASS: Record<RequirementStatus, string> = {
  project: "bg-success",
  list: "border-4 border-warning",
  none: "border-[1.5px] border-muted-foreground/55",
};

export function StatusDot({
  status,
  size = "md",
  className,
}: {
  status: RequirementStatus;
  size?: "sm" | "md";
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-block shrink-0 rounded-full align-middle",
        size === "sm" ? "h-3 w-3" : "h-4 w-4",
        size === "sm" && status === "list" ? "border-[3px] border-warning" : DOT_CLASS[status],
        className,
      )}
      data-status={status}
      role="img"
      aria-label={STATUS_LABELS[status]}
    />
  );
}

const PILL_CLASS: Record<PillTone, string> = {
  neutral: "bg-muted text-muted-foreground",
  success: "bg-success-muted text-success-muted-foreground",
  warning: "bg-warning-muted text-warning-muted-foreground",
};

export function Pill({ tone = "neutral", children }: { tone?: PillTone; children: ReactNode }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-px text-xs font-medium",
        PILL_CLASS[tone],
      )}
    >
      {children}
    </span>
  );
}

export function StatePill({ state }: { state: PanelCandidateState }) {
  const { label, tone } = STATE_LABELS[state];
  if (!tone) return <span className="text-xs text-muted-foreground">{label}</span>;
  return <Pill tone={tone}>{label}</Pill>;
}

export function PanelTabs<T extends string>({
  tabs,
  active,
  onChange,
  label,
}: {
  tabs: readonly { id: T; label: string }[];
  active: T;
  onChange: (id: T) => void;
  label: string;
}) {
  return (
    <div
      role="tablist"
      aria-label={label}
      className="mb-2.5 flex shrink-0 gap-0.5 overflow-x-auto border-b border-border"
    >
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          aria-selected={active === tab.id}
          onClick={() => onChange(tab.id)}
          className={cn(
            "-mb-px whitespace-nowrap border-b-2 px-3 py-1.5 text-sm font-medium transition-colors",
            "focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring",
            active === tab.id
              ? "border-primary text-primary"
              : "border-transparent text-muted-foreground hover:text-foreground",
          )}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

export const PANEL_CARD = "rounded-xl border border-border bg-card";

/** Awaria odczytu: komunikat z „Ponów”, nigdy pusta lista. */
export function PanelRetry({ text, onRetry }: { text: string; onRetry: () => void }) {
  return (
    <div
      role="alert"
      className="rounded-xl border border-destructive/20 bg-destructive/10 p-4 text-sm"
    >
      <p>{text}</p>
      <button
        type="button"
        onClick={onRetry}
        className="mt-2 font-medium text-primary underline-offset-4 hover:underline"
      >
        Ponów
      </button>
    </div>
  );
}
