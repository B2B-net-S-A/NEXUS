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
 * rejestr / obsługa / skrzynka zamówień). Te same klasy co dawny przełącznik
 * w `/contracts`, żeby oba ekrany wyglądały identycznie.
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
      className="inline-flex flex-wrap items-center gap-1 rounded-lg border border-[hsl(var(--border))] bg-muted/40 p-1"
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
              "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
              active
                ? "bg-background text-foreground shadow-xs"
                : "text-muted-foreground hover:text-foreground",
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
