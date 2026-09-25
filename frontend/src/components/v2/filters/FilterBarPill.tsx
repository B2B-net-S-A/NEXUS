"use client";

/**
 * Wspólne klocki paska filtrów nad tabelą — lista kandydatów (23.09.2026)
 * i lista rekrutacji (25.09.2026). Jeden wygląd przycisku z okienkiem na obu
 * listach: ustawiony filtr niesie wartość albo licznik i ✕ do wyczyszczenia.
 */

import type { ReactNode } from "react";
import { ChevronDown, X } from "lucide-react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

export function FieldLabel({ children, htmlFor }: { children: ReactNode; htmlFor?: string }) {
  return (
    <label htmlFor={htmlFor} className="block text-xs text-muted-foreground">
      {children}
    </label>
  );
}

/**
 * Przycisk filtra na pasku: otwiera okienko z polami grupy. Ustawiony filtr
 * jest wyróżniony i niesie swoją wartość (albo licznik), a ✕ obok czyści
 * grupę — ukryty, ale ustawiony filtr nie może wyglądać, jakby go nie było.
 */
export function FilterPill({
  label,
  icon,
  summary,
  count,
  onClear,
  contentClassName,
  children,
}: {
  label: string;
  icon: ReactNode;
  /** Wartość na przycisku („do 160 zł/h”); bez niej przycisk pokazuje licznik. */
  summary?: string | null;
  count: number;
  onClear?: () => void;
  contentClassName?: string;
  children: ReactNode;
}) {
  const active = count > 0;
  return (
    <div
      className={cn(
        "inline-flex h-9 shrink-0 items-center rounded-full border text-xs font-medium transition-colors md:h-8",
        active
          ? "border-primary/30 bg-primary/10 text-primary"
          : "border-border bg-card text-foreground hover:bg-accent",
      )}
    >
      <Popover>
        <PopoverTrigger asChild>
          <button
            type="button"
            className={cn(
              "flex h-full items-center gap-1.5 rounded-full pl-3 focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring",
              active && onClear ? "pr-1" : "pr-2.5",
            )}
          >
            <span aria-hidden className="[&>svg]:h-3.5 [&>svg]:w-3.5">
              {icon}
            </span>
            <span className="flex min-w-0 items-baseline">
              {label}
              {active && summary && (
                <span className="max-w-[200px] truncate font-semibold">: {summary}</span>
              )}
            </span>
            {active && !summary ? (
              <span className="rounded-full bg-primary px-1.5 text-[10px] leading-4 text-primary-foreground">
                {count}
              </span>
            ) : null}
            <ChevronDown className="h-3.5 w-3.5 opacity-60" aria-hidden />
          </button>
        </PopoverTrigger>
        <PopoverContent
          align="start"
          // Odstęp od krawędzi ekranu — na telefonie w poziomie okienko nie
          // dotyka krawędzi, a wysokość ogranicza prymityw (dostępne miejsce).
          collisionPadding={8}
          className={cn("w-80 space-y-3 text-sm", contentClassName)}
        >
          {children}
        </PopoverContent>
      </Popover>
      {active && onClear && (
        <button
          type="button"
          onClick={onClear}
          aria-label={`Wyczyść: ${label}`}
          className="hit-area mr-1 flex h-6 w-6 items-center justify-center rounded-full hover:bg-primary/15 focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
        >
          <X className="h-3 w-3" aria-hidden />
        </button>
      )}
    </div>
  );
}
