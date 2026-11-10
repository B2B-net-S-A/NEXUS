"use client";

import { PrepBusyStrip } from "@/components/calendar/cycle/PrepBusyStrip";
import { useHostBusy } from "@/lib/api/sales-handoffs";
import { overlaps, spanOf } from "@/lib/interview-pick";
import { cn } from "@/lib/utils";

import { freeStarts, termFromFields } from "./helpers";

interface HostCalendarProps {
  hostId: number | null;
  hostName: string;
  /** Dzień `RRRR-MM-DD` z pola formularza; pusty = nie ma czego pokazać. */
  day: string;
  time: string;
  minutes: number;
  onPickTime: (time: string) => void;
}

/**
 * Kalendarz prowadzącego przy wyborze terminu: zajęte godziny (bez tytułów spotkań),
 * wolne początki do kliknięcia i ostrzeżenie o kolizji. To podpowiedź: zapis nigdy
 * od niej nie zależy, a bez połączonej skrzynki termin wpisuje się ręcznie.
 */
export function HostCalendar({ hostId, hostName, day, time, minutes, onPickTime }: HostCalendarProps) {
  const query = useHostBusy(hostId, day || null);
  if (hostId == null || !day) return null;
  if (query.isPending) return <p className="text-xs text-muted-foreground">Sprawdzam kalendarz…</p>;
  if (!query.isSuccess) {
    return (
      <p className="text-xs text-muted-foreground">
        Nie udało się wczytać kalendarza. Termin możesz wpisać ręcznie.
      </p>
    );
  }
  const { busy, calendar } = query.data;
  const start = termFromFields(day, time);
  const chosen = start ? spanOf(start, minutes) : null;
  const clash = Boolean(chosen && busy.some((block) => overlaps(chosen, block)));
  const free = calendar === "ok" ? freeStarts(day, minutes, busy) : [];
  return (
    <div className="space-y-1.5" data-testid="host-calendar">
      <PrepBusyStrip
        who={hostName}
        day={day}
        busy={busy}
        chosen={chosen}
        clash={clash}
        chosenLabel="to spotkanie"
        tour={false}
      />
      {calendar === "unavailable" && (
        <p className="text-xs text-muted-foreground">
          Kalendarz Outlook tej osoby nie jest połączony z NEXUSEM. Pasek pokazuje tylko spotkania zapisane
          w Sprzedaży, więc termin ustal z prowadzącym.
        </p>
      )}
      {free.length > 0 && (
        <div className="flex flex-wrap items-center gap-1" role="group" aria-label="Wolne godziny">
          <span className="text-xs text-muted-foreground">Wolne:</span>
          {free.map((slot) => (
            <button
              key={slot}
              type="button"
              aria-pressed={slot === time}
              onClick={() => onPickTime(slot)}
              className={cn(
                "rounded-md border px-1.5 py-0.5 text-xs tabular-nums",
                slot === time
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border text-foreground hover:bg-muted",
              )}
            >
              {slot}
            </button>
          ))}
        </div>
      )}
      {clash && (
        <p role="status" className="rounded-md bg-warning-muted px-2 py-1 text-xs text-warning-muted-foreground">
          {hostName} ma wtedy zajęte. Wybierz inną godzinę albo zapisz, jeśli to uzgodnione.
        </p>
      )}
    </div>
  );
}
