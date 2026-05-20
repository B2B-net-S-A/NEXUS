"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";

interface ExpandableTextProps {
  /** The text to render. Whitespace/newlines are preserved (whitespace-pre-line). */
  text: string;
  /** How many lines to show when collapsed (Tailwind line-clamp-N). Default 3. */
  maxLines?: 2 | 3 | 4 | 5 | 6;
  /** Only show the toggle when the text is at least this many characters —
   *  avoids a pointless "Rozwiń" on a one-line summary. Default 160. */
  collapseThreshold?: number;
  className?: string;
}

const _CLAMP_CLASS: Record<number, string> = {
  2: "line-clamp-2",
  3: "line-clamp-3",
  4: "line-clamp-4",
  5: "line-clamp-5",
  6: "line-clamp-6",
};

/** Text block that collapses to `maxLines` with a "Rozwiń / Zwiń" toggle.
 *
 *  Used for AI summary, "O sobie", and long experience descriptions on the
 *  candidate profile — keeps the profile scannable without losing access to
 *  the full text. Short text (< collapseThreshold chars) renders inline with
 *  no toggle. */
export function ExpandableText({
  text,
  maxLines = 3,
  collapseThreshold = 160,
  className,
}: ExpandableTextProps) {
  const [expanded, setExpanded] = useState(false);
  const trimmed = text?.trim() ?? "";
  if (!trimmed) return null;

  const collapsible = trimmed.length >= collapseThreshold;

  return (
    <div className={className}>
      <p
        className={cn(
          "text-sm text-foreground whitespace-pre-line",
          collapsible && !expanded && _CLAMP_CLASS[maxLines],
        )}
      >
        {trimmed}
      </p>
      {collapsible && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="mt-1 text-xs font-medium text-primary hover:underline"
          aria-expanded={expanded}
        >
          {expanded ? "Zwiń" : "Rozwiń"}
        </button>
      )}
    </div>
  );
}
