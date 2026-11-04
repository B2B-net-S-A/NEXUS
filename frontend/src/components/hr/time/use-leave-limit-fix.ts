"use client";

import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import type { EntryPatch, MonthDay, TimesheetEntry } from "@/lib/api/hr-time";

import { formatHours } from "./time-format";

interface SaveEntry {
  mutate: (
    payload: EntryPatch & { id?: number },
    options: { onSuccess: () => void; onError: (err: unknown) => void },
  ) => void;
}

/**
 * „Skróć do 4 h” przy dniu z pół dnia nieobecności: jeden wpis skraca się od razu,
 * przy kilku okno wpisu, bo tylko człowiek wie, który skrócić.
 */
export function useLeaveLimitFix(
  save: SaveEntry,
  openEntry: (day: MonthDay, entry: TimesheetEntry) => void,
): (day: MonthDay) => void {
  const { showToast } = useToast();
  return (day) => {
    const last = day.entries[day.entries.length - 1];
    if (!last || day.capacity === null) return;
    if (day.entries.length > 1) {
      openEntry(day, last);
      return;
    }
    const hours = formatHours(day.capacity);
    save.mutate(
      { id: last.id, hours: day.capacity },
      {
        onSuccess: () => showToast(`Skrócono do ${hours} h`, "success"),
        onError: (err) => showToast(apiErrorMessage(err, "Nie udało się skrócić wpisu."), "error"),
      },
    );
  };
}
