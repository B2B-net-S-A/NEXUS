"use client";

import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export interface WorkspaceMode<T extends string> {
  value: T;
  label: string;
  /** Licznik obok etykiety (np. dokumenty do sprawdzenia); 0/brak = bez plakietki. */
  count?: number;
  icon?: ReactNode;
}

/**
 * Przełącznik trybów jednego ekranu (Klienci: lista / kontakty; Kontrakty:
 * rejestr / obsługa / skrzynka zamówień). Zakładki z podkreśleniem pod
 * tytułem widoku — układ z makiety B (29.09.2026), wspólny dla obu ekranów.
 */
export function WorkspaceModeTabs<T extends string>({
  label,
  modes,
  value,
  onChange,
}: {
  label: string;
  modes: readonly WorkspaceMode<T>[];
  value: T;
  onChange: (next: T) => void;
}) {
  return (
    <div
      role="tablist"
      aria-label={label}
      className="flex gap-0.5 overflow-x-auto border-b border-border"
    >
      {modes.map((mode) => {
        const active = mode.value === value;
        return (
          <button
            key={mode.value}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(mode.value)}
            className={cn(
              "-mb-px inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap border-b-2 px-3 py-1.5 text-[13px] transition-colors pointer-coarse:min-h-10",
              active
                ? "border-primary font-semibold text-foreground"
                : "border-transparent font-medium text-muted-foreground hover:text-foreground",
            )}
          >
            {mode.icon}
            {mode.label}
            {mode.count ? (
              <span className="rounded-full bg-primary px-1.5 text-[11px] font-semibold leading-5 text-primary-foreground tabular-nums">
                {mode.count > 99 ? "99+" : mode.count}
              </span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}
