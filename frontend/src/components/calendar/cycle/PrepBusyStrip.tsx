"use client";

import { dayStrip, type Span } from "@/lib/interview-pick";
import { cn } from "@/lib/utils";

/**
 * Pasek dnia prowadzącego prep: zajęte bloki (bez tytułów spotkań) i wybrany
 * termin. `clash` — termin wpada na zajęte albo łamie regułę, więc ma kolor
 * ostrzeżenia. Wspólny dla „Inna godzina…” i „Zaplanuj Prep”.
 */
export function PrepBusyStrip({
  who,
  day,
  busy,
  chosen,
  clash,
}: {
  who: string;
  day: string;
  busy: Span[];
  chosen: Span | null;
  clash: boolean;
}) {
  const strip = dayStrip(day, busy, chosen);
  if (!strip) return null;
  return (
    <div data-testid="prep-busy-strip" data-tour="prep.organizer-calendar">
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2 text-xs">
        <span className="font-semibold">Kalendarz: {who}</span>
        <span className="flex items-center gap-3 text-muted-foreground">
          <span className="inline-flex items-center gap-1">
            <span aria-hidden="true" className="h-2.5 w-3 rounded-sm bg-muted-foreground/40" />
            zajęte
          </span>
          <span className="inline-flex items-center gap-1">
            <span aria-hidden="true" className="h-2.5 w-3 rounded-sm bg-primary" />
            ten prep
          </span>
        </span>
      </div>
      <div
        role="img"
        aria-label={`Zajętość: ${who}, ${day}`}
        className="relative h-7 overflow-hidden rounded border border-border bg-card"
      >
        {strip.busy.map((b, i) => (
          <span
            key={i}
            className="absolute inset-y-0.5 rounded-sm bg-muted-foreground/40"
            style={{ left: `${b.left}%`, width: `${b.width}%` }}
          />
        ))}
        {strip.chosen ? (
          <span
            className={cn(
              "absolute inset-y-0.5 rounded-sm",
              clash ? "bg-warning ring-2 ring-warning-muted-foreground" : "bg-primary",
            )}
            style={{ left: `${strip.chosen.left}%`, width: `${strip.chosen.width}%` }}
          />
        ) : null}
      </div>
      <div className="relative mt-1 h-4 text-[11px] text-muted-foreground">
        {strip.ticks.map((t, i) => (
          <span
            key={t.label}
            className="absolute"
            style={{
              left: `${t.left}%`,
              transform: i === 0 ? "none" : i === strip.ticks.length - 1 ? "translateX(-100%)" : "translateX(-50%)",
            }}
          >
            {t.label}
          </span>
        ))}
      </div>
    </div>
  );
}
