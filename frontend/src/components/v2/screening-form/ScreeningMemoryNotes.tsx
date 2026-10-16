"use client";

/**
 * Komunikaty pamięci rozmowy screeningowej (16.10.2026, decyzje Artura D1 A,
 * D2 A, D3 B): przywrócony szkic nad „Screening dla” i lista wpisów
 * odznaczonych rekrutacji nad przyciskami zapisu — zapis ich nie obejmie
 * i po nim znikną.
 */

import { History } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { PendingMemoryItem } from "@/lib/screening-memory";
import { countPl } from "@/lib/plural-pl";

/** „1 odpowiedź zostaje” / „2 odpowiedzi zostają” / „5 odpowiedzi zostaje”. */
export function answersStay(count: number): string {
  const last = count % 10;
  const teen = count % 100 >= 12 && count % 100 <= 14;
  const verb = count !== 1 && last >= 2 && last <= 4 && !teen ? "zostają" : "zostaje";
  return `${countPl(count, "odpowiedź", "odpowiedzi", "odpowiedzi")} ${verb}`;
}

/** „Wróciła 1 odpowiedź” / „Wróciły 2 odpowiedzi” / „Wróciło 5 odpowiedzi”. */
export function answersCameBack(count: number): string {
  const last = count % 10;
  const teen = count % 100 >= 12 && count % 100 <= 14;
  const verb = count === 1 ? "Wróciła" : last >= 2 && last <= 4 && !teen ? "Wróciły" : "Wróciło";
  return `${verb} ${countPl(count, "odpowiedź", "odpowiedzi", "odpowiedzi")}`;
}

/** Podpis pamięci przy rekrutacji na liście „Screening dla”. */
export function memoryChipLabel(answers: number): string {
  return answers > 0 ? `${countPl(answers, "odpowiedź", "odpowiedzi", "odpowiedzi")} w pamięci` : "wpisy w pamięci";
}

const TIME = new Intl.DateTimeFormat("pl-PL", { hour: "2-digit", minute: "2-digit" });
const DAY_TIME = new Intl.DateTimeFormat("pl-PL", { day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit" });

function when(at: number, now: Date): string {
  const date = new Date(at);
  return date.toDateString() === now.toDateString() ? TIME.format(date) : DAY_TIME.format(date);
}

export function MemoryRestoredNotice({
  savedAt,
  onDiscard,
  now = new Date(),
}: {
  savedAt: number;
  onDiscard: () => void;
  now?: Date;
}) {
  return (
    <p
      role="status"
      data-testid="screening-memory-restored"
      className="flex flex-wrap items-center gap-2 rounded-lg bg-info-muted px-3 py-2 text-xs text-info-muted-foreground"
    >
      <History className="h-3.5 w-3.5 shrink-0" aria-hidden />
      <span className="min-w-0 flex-1">
        <strong>Przywrócono niezapisany screening z {when(savedAt, now)}.</strong> Wpisy z rozmowy są z powrotem —
        zapisz, kiedy skończysz.
      </span>
      <Button type="button" size="sm" variant="outline" className="h-7 px-2 text-xs" onClick={onDiscard}>
        Odrzuć szkic
      </Button>
    </p>
  );
}

export function MemoryPendingNote({
  scope,
  items,
  onReselect,
}: {
  /** Co obejmie zapis: „tylko tę rekrutację”, „2 zaznaczone rekrutacje”. */
  scope: string;
  items: readonly PendingMemoryItem[];
  onReselect?: (jobId: number) => void;
}) {
  if (items.length === 0) return null;
  return (
    <div
      role="note"
      data-testid="screening-memory-pending"
      className="space-y-1 rounded-md bg-warning-muted px-3 py-2 text-xs text-warning-muted-foreground"
    >
      <p>
        <strong>Zapis obejmie {scope}.</strong> Wpisy odznaczonych rekrutacji są w pamięci — po zapisie znikną:
      </p>
      <ul className="list-disc space-y-0.5 pl-4">
        {items.map((item) => (
          <li key={item.jobId}>
            {item.title} — {item.answers > 0 ? countPl(item.answers, "odpowiedź", "odpowiedzi", "odpowiedzi") : "wpisy"}
            {item.canReselect && onReselect ? (
              <>
                {" · "}
                <button
                  type="button"
                  className="font-semibold underline underline-offset-2"
                  onClick={() => onReselect(item.jobId)}
                >
                  zaznacz
                </button>
              </>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}
