"use client";

import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/** Karta kroku generatora: numer w kółku, tytuł, opcjonalna plakietka. */
export function StepCard({
  step,
  title,
  badge,
  children,
  className,
}: {
  step?: number;
  title: string;
  badge?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      aria-label={title}
      className={cn("rounded-xl border border-border bg-card p-5", className)}
    >
      <div className="mb-4 flex flex-wrap items-center gap-2.5">
        {step != null ? (
          <span
            aria-hidden
            className="inline-flex h-6 w-6 flex-none items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary"
          >
            {step}
          </span>
        ) : null}
        <h2 className="text-base font-semibold text-foreground">{title}</h2>
        {badge}
      </div>
      {children}
    </section>
  );
}

export interface SegmentedOption<T extends string> {
  value: T;
  label: string;
  disabled?: boolean;
  title?: string;
}

/** Przełącznik segmentowy (Redakcja / Pod rekrutację, PL / EN / Obie). */
export function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
  disabled = false,
}: {
  label: string;
  value: T;
  options: readonly SegmentedOption<T>[];
  onChange: (value: T) => void;
  disabled?: boolean;
}) {
  return (
    <div
      role="group"
      aria-label={label}
      className="inline-flex gap-1 rounded-lg border border-border bg-muted/60 p-1"
    >
      {options.map((option) => {
        const on = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={on}
            title={option.title}
            disabled={disabled || option.disabled}
            onClick={() => onChange(option.value)}
            className={cn(
              "h-8 rounded-md px-4 text-sm font-medium transition-colors",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              "disabled:cursor-not-allowed disabled:opacity-50",
              on
                ? "bg-card text-foreground shadow-xs"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

/** Mała plakietka stanu (ok / ostrzeżenie / info / neutralna). */
export function StatusChip({
  tone,
  children,
}: {
  tone: "ok" | "warn" | "info" | "neutral" | "danger";
  children: ReactNode;
}) {
  return (
    <span
      className={cn(
        "inline-flex h-6 items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 text-xs font-medium",
        tone === "ok" && "bg-success-muted text-success-muted-foreground",
        tone === "warn" && "bg-warning-muted text-warning-muted-foreground",
        tone === "info" && "bg-info-muted text-info-muted-foreground",
        tone === "danger" && "bg-destructive-muted text-destructive-muted-foreground",
        tone === "neutral" && "bg-muted text-muted-foreground",
      )}
    >
      {children}
    </span>
  );
}

/** Inicjały do awatara („Jan Kowalski” → „JK”). */
export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
}
