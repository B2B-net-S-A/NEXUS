"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import { prepMeetingsApi, prepQueryKey, usePrep } from "@/lib/api/prepMeetings";
import { formatDayLabel, formatTime } from "@/lib/interview-cycle";
import { prepResponseView, type PrepResponseTone } from "@/lib/prep-response";
import { cn } from "@/lib/utils";

const TONE: Record<PrepResponseTone, string> = {
  ok: "bg-success-muted text-success-muted-foreground",
  info: "bg-info-muted text-info-muted-foreground",
  wait: "bg-warning-muted text-warning-muted-foreground",
  muted: "bg-muted text-muted-foreground",
};

/**
 * Odpowiedź kandydata przy prepie (0453, 17.10.2026, D5) i — gdy kandydat
 * zaproponował inny termin — „Przyjmij termin” dla ludzi pary (`can_edit`).
 * Przyjęcie przekłada TO SAMO spotkanie w kalendarzu prowadzącego; kandydat
 * dostaje aktualizację zaproszenia.
 */
export function PrepResponseChip({ eventId, className }: { eventId: number; className?: string }) {
  const toast = useToast();
  const qc = useQueryClient();
  const prep = usePrep(eventId);
  const accept = useMutation({
    mutationFn: (slot: { start: string; end: string }) => prepMeetingsApi.update(eventId, slot),
    onSuccess: (updated) => {
      qc.setQueryData(prepQueryKey(updated.event_id), updated);
      qc.invalidateQueries({ queryKey: ["interview-cycle"] });
      qc.invalidateQueries({ queryKey: ["calendar-events"] });
      qc.invalidateQueries({ queryKey: ["kanban"] });
      toast.showSuccess(
        `Prep ${updated.prep_no} przełożony na ${formatDayLabel(updated.start)}, ${formatTime(updated.start)} — kandydat dostał aktualizację zaproszenia.`,
      );
    },
    onError: (err) => toast.showError(apiErrorMessage(err, "Nie udało się przyjąć terminu.")),
  });
  if (!prep.data) return null;
  const view = prepResponseView(prep.data);
  if (!view) return null;
  return (
    <span className={cn("inline-flex flex-wrap items-center gap-1.5", className)}>
      <span
        data-testid="prep-response-chip"
        className={cn("rounded-md px-2 py-0.5 text-xs font-semibold", TONE[view.tone])}
      >
        {view.label}
      </span>
      {view.proposed && prep.data.can_edit ? (
        <button
          type="button"
          disabled={accept.isPending}
          onClick={() => accept.mutate(view.proposed as { start: string; end: string })}
          className="h-7 rounded-md bg-primary px-2.5 text-xs font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          {accept.isPending ? "Przekładam…" : "Przyjmij termin"}
        </button>
      ) : null}
    </span>
  );
}
