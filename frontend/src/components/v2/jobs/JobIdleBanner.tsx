"use client";

import { Button } from "@/components/ui/button";
import { formatDayMonthPl } from "@/lib/date-pl";
import type { JobIdle } from "@/lib/job-idle-api";

export interface JobIdleBannerProps {
  idle: JobIdle | null | undefined;
  onClose: () => void;
  onSnooze: () => void;
  snoozing?: boolean;
}

export function lastMoveText(idle: JobIdle): string {
  if (!idle.last_move_at) return "żadnego CV do klienta";
  const day = formatDayMonthPl(idle.last_move_at);
  return idle.last_move_kind === "cv"
    ? `ostatnie CV do klienta ${day}, bez odpowiedzi`
    : `ostatnia odpowiedź klienta ${day}`;
}

/**
 * Pasek nad Tablicą rekrutacji bez ruchu (28.10.2026): od 14 dni nie poszło
 * CV do klienta ani nie wpisano odpowiedzi klienta. Dwa przyciski: „Zamknij…”
 * (dzisiejsze okno zamykania) i „Jeszcze trwa” (licznik od nowa).
 */
export function JobIdleBanner({ idle, onClose, onSnooze, snoozing = false }: JobIdleBannerProps) {
  if (!idle?.stage) return null;
  const closeOn = idle.close_on ? formatDayMonthPl(idle.close_on) : null;
  let after: string;
  if (idle.stage === "close" || !closeOn) {
    after = "NEXUS zamknie rekrutację przy najbliższym przeglądzie jako przegraną.";
  } else if (idle.stage === "remind" && idle.hor_on) {
    after = `${formatDayMonthPl(idle.hor_on)} dostanie to Head of Recruitment, a ${closeOn} NEXUS zamknie rekrutację jako przegraną.`;
  } else {
    after = `${closeOn} NEXUS zamknie rekrutację jako przegraną.`;
  }
  return (
    <div
      role="status"
      data-testid="job-idle-banner"
      data-tour="job.idle.banner"
      className="mb-3 flex flex-wrap items-center gap-3 rounded-lg border border-warning/40 bg-warning-muted px-4 py-2.5 text-sm"
    >
      <p className="min-w-0 flex-1 text-warning-muted-foreground">
        <strong>
          Bez ruchu od {idle.days} dni: {lastMoveText(idle)}.
        </strong>{" "}
        Jeśli nic się nie zmieni, {after}
      </p>
      <Button type="button" size="sm" variant="outline" onClick={onClose}>
        Zamknij…
      </Button>
      <Button
        type="button"
        size="sm"
        variant="outline"
        onClick={onSnooze}
        disabled={snoozing}
        data-tour="job.idle.snooze"
      >
        {snoozing ? "Zapisuję…" : "Jeszcze trwa"}
      </Button>
    </div>
  );
}
