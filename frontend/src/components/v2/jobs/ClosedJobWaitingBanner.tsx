"use client";

import { Button } from "@/components/ui/button";

export interface ClosedJobWaitingBannerProps {
  /** „19.10” albo `null`, gdy serwer nie zna daty zamknięcia. */
  closedOn: string | null;
  reasonLabel: string | null;
  /** Imiona i nazwiska osób rekrutera od „CV wysłane”, w kolejności Tablicy. */
  people: readonly string[];
  /** Okno odrzucenia pierwszej osoby; brak = rekruter nie może odrzucać. */
  onRejectFirst?: () => void;
}

const NAMES_MAX = 6;

/**
 * Pasek nad Tablicą zamkniętej rekrutacji (28.10.2026): rekruter widzi, które
 * jego osoby nadal są w procesie, i odrzuca je po kolei oknem z mailem do
 * kandydata. Znika, gdy nie ma już jego osób od „CV wysłane”.
 */
export function ClosedJobWaitingBanner({
  closedOn,
  reasonLabel,
  people,
  onRejectFirst,
}: ClosedJobWaitingBannerProps) {
  if (people.length === 0) return null;
  const head = ["Rekrutacja zamknięta", closedOn, reasonLabel].filter(Boolean).join(" · ");
  const shown = people.slice(0, NAMES_MAX).join(", ");
  const rest = people.length - NAMES_MAX;
  return (
    <div
      role="status"
      data-testid="closed-job-waiting"
      className="flex flex-wrap items-center gap-3 rounded-lg border border-warning/40 bg-warning-muted px-3.5 py-2.5 text-sm"
    >
      <div className="min-w-0 flex-1">
        <p className="font-medium text-foreground">{head}</p>
        <p className="text-muted-foreground">
          {people.length === 1 ? "Twoja osoba nadal jest w procesie: " : `Twoje osoby nadal są w procesie (${people.length}): `}
          <span className="text-foreground">{shown}</span>
          {rest > 0 ? ` i ${rest} innych` : null}. Daj im znać i zamknij karty.
        </p>
      </div>
      {onRejectFirst ? (
        <Button type="button" size="sm" onClick={onRejectFirst}>
          Odrzuć i napisz: {people[0]}
        </Button>
      ) : null}
    </div>
  );
}
