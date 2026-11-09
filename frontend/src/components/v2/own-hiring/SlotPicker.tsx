"use client";

import { useQuery } from "@tanstack/react-query";

import { ownHiringApi } from "@/lib/api/ownHiring";
import { cn } from "@/lib/utils";

import { formatTime } from "./format";

interface SlotPickerProps {
  kind: "teams" | "office";
  value: string | null;
  onChange: (slot: string) => void;
}

/** Wolne terminy właściciela: to samo źródło co strona dla kandydata. */
export function SlotPicker({ kind, value, onChange }: SlotPickerProps) {
  const slots = useQuery({
    queryKey: ["own-hiring", "slots", kind],
    queryFn: () => ownHiringApi.slots(kind),
    refetchOnWindowFocus: true,
  });
  if (slots.isPending) return <p className="text-xs text-muted-foreground">Sprawdzam kalendarz…</p>;
  if (slots.isError) {
    return <p className="text-xs text-destructive">Nie udało się pobrać terminów.</p>;
  }
  if (!slots.data.calendar_available) {
    return <p className="text-xs text-warning-muted-foreground">Kalendarz jest chwilowo niedostępny.</p>;
  }
  if (slots.data.days.length === 0) {
    return <p className="text-xs text-muted-foreground">Brak wolnych terminów w ustawionych oknach.</p>;
  }
  return (
    <div className="max-h-48 space-y-2 overflow-y-auto">
      {slots.data.days.map((day) => (
        <div key={day.date}>
          <p className="text-xs font-medium">{day.label}</p>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {day.slots.map((slot) => (
              <button
                key={slot}
                type="button"
                onClick={() => onChange(slot)}
                aria-pressed={value === slot}
                className={cn(
                  "rounded-md border px-2.5 py-1 text-xs tabular-nums",
                  value === slot
                    ? "border-primary bg-primary text-primary-foreground"
                    : "border-border hover:bg-muted",
                )}
              >
                {formatTime(slot)}
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
