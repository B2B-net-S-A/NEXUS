"use client";

import {
  recentFactDate,
  recentFactLabel,
  recentFactText,
  recentFactsTitle,
  type RecentFact,
} from "@/lib/candidate-recent-facts";
import { cn } from "@/lib/utils";

/** Wysokość linii pod wierszem — wirtualizacja listy liczy ją co do piksela. */
export const RECENT_FACTS_LINE_HEIGHT = 28;

/**
 * „Ostatnio z osobą” pod wierszem listy kandydatów: najnowsza informacja,
 * a za nią wcześniejsza (`lib/candidate-recent-facts.ts`). Pełna szerokość,
 * żeby zdanie się nie ucinało jak w wąskiej kolumnie.
 */
export function RecentFactsLine({
  facts,
  onOpen,
  className,
}: {
  /** `undefined` — odpowiedź bez pola (stary backend w trakcie wdrożenia). */
  facts: readonly RecentFact[] | null | undefined;
  onOpen?: () => void;
  className?: string;
}) {
  const [latest, earlier] = facts ?? [];
  return (
    <button
      type="button"
      onClick={onOpen}
      data-testid="recent-facts-line"
      title={facts?.length ? recentFactsTitle(facts) : undefined}
      style={{ height: RECENT_FACTS_LINE_HEIGHT }}
      className={cn(
        "flex w-full shrink-0 items-center overflow-hidden border-t border-border/40 px-4 text-left text-xs",
        className,
      )}
    >
      <span className="min-w-0 truncate pl-12">
        <span className="text-muted-foreground">Ostatnio z osobą: </span>
        {!facts ? (
          <span className="text-muted-foreground">—</span>
        ) : !latest ? (
          <span className="text-muted-foreground">brak notatek i odrzuceń</span>
        ) : (
          <>
            <span className="font-semibold tabular-nums text-foreground">{recentFactDate(latest.at)}</span>{" "}
            <span className="font-semibold text-foreground">{recentFactLabel(latest)}</span>
            <span className="text-foreground"> — {recentFactText(latest)}</span>
            {earlier ? (
              <span className="text-muted-foreground">
                {" · wcześniej "}
                <span className="tabular-nums">{recentFactDate(earlier.at)}</span> {recentFactLabel(earlier)} —{" "}
                {recentFactText(earlier)}
              </span>
            ) : null}
          </>
        )}
      </span>
    </button>
  );
}
