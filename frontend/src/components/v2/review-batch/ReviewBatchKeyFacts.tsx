"use client";

import type { KeyEvidence, ReviewBatchKeyFacts } from "@/lib/api/reviewBatch";
import { cn } from "@/lib/utils";

/**
 * „Kluczowe w tej rekrutacji” na karcie porcji (R2 + R4, decyzje Artura
 * 12.11.2026, makieta M1): krytyczne z poziomem dowodu i polski zamiast
 * dziesięciu „?”. Klik w pozycję przewija CV po prawej do trafienia — to samo
 * wyszukiwanie co klik w zakładce „Wymagania”. Dowód tylko informuje: nikt
 * przez niego nie wypada z porcji.
 */

const EVIDENCE: Record<KeyEvidence, { mark: string; tone: string; title: string }> = {
  experience: { mark: "✓", tone: "bg-success/15 text-success", title: "doświadczenie w stanowiskach" },
  mention: { mark: "~", tone: "bg-warning/15 text-warning", title: "tylko wzmianka" },
  none: { mark: "✗", tone: "bg-destructive/15 text-destructive", title: "brak" },
};

const POLISH: Record<ReviewBatchKeyFacts["polish"]["state"], { mark: string; tone: string }> = {
  native: { mark: "✓", tone: "bg-success/15 text-success" },
  level: { mark: "✓", tone: "bg-success/15 text-success" },
  no: { mark: "✗", tone: "bg-destructive/15 text-destructive" },
  unknown: { mark: "?", tone: "bg-muted text-muted-foreground" },
};

export function hasKeyFacts(facts: ReviewBatchKeyFacts | null | undefined): facts is ReviewBatchKeyFacts {
  return Boolean(facts && facts.critical.length > 0);
}

export function ReviewBatchKeyFactsBlock({
  facts,
  restMatched,
  restTotal,
  onPick,
}: {
  facts: ReviewBatchKeyFacts;
  restMatched: number;
  restTotal: number;
  onPick?: (label: string) => void;
}) {
  const polish = POLISH[facts.polish.state];
  return (
    <div className="space-y-1.5" data-testid="review-key-facts" data-tour="review-batch.key-facts">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        Kluczowe w tej rekrutacji
      </div>
      <ul className="space-y-0.5">
        {facts.critical.map((row) => {
          const style = EVIDENCE[row.state];
          return (
            <li key={row.label}>
              <button
                type="button"
                onClick={() => onPick?.(row.label)}
                disabled={!onPick}
                title="Pokaż, gdzie to jest w CV"
                className="flex w-full items-center gap-2 rounded px-0.5 text-left text-sm hover:bg-muted disabled:hover:bg-transparent"
              >
                <span
                  className={cn("w-6 shrink-0 rounded text-center text-xs font-bold", style.tone)}
                  aria-label={style.title}
                >
                  {style.mark}
                </span>
                <span className="font-medium underline decoration-dotted underline-offset-2">{row.label}</span>
                <span className="min-w-0 truncate text-xs text-muted-foreground">{row.detail}</span>
              </button>
            </li>
          );
        })}
        <li className="flex items-center gap-2 px-0.5 text-sm" data-testid="review-key-polish">
          <span className={cn("w-6 shrink-0 rounded text-center text-xs font-bold", polish.tone)}>{polish.mark}</span>
          <span className="font-medium">Polski</span>
          <span className="min-w-0 truncate text-xs text-muted-foreground">{facts.polish.detail}</span>
        </li>
      </ul>
      {restTotal > 0 ? (
        <p className="text-xs text-muted-foreground">
          Wymagania z listy: {restMatched} z {restTotal} w profilu (całość w zakładce „Wymagania”)
        </p>
      ) : null}
    </div>
  );
}
