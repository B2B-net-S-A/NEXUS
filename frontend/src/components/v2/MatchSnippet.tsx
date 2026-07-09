"use client";

import { useMemo } from "react";
import { cn } from "@/lib/utils";

interface MatchSnippetProps {
  /** Raw snippet from `candidate.match_snippet` — already includes the
   *  field prefix ("CV:", "Notatka:", …) from the backend. */
  snippet: string;
  /** Phrases the user searched for (q + q_all + q_any). Used to wrap
   *  matching substrings in <mark>. Order doesn't matter — we sort by
   *  length DESC so longer phrases get highlighted before shorter ones
   *  that are substrings of them. */
  terms: string[];
  className?: string;
}

/** Render a search snippet with the matched terms wrapped in <mark>.
 *
 *  Highlight is case-insensitive but preserves the original casing in the
 *  output. We scan the snippet character-by-character so the React output
 *  stays as plain strings + JSX nodes — no `dangerouslySetInnerHTML`, no
 *  XSS surface even if the backend snippet contains untrusted CV content
 *  (CV content is user-supplied, never trusted). */
export function MatchSnippet({
  snippet,
  terms,
  className,
}: MatchSnippetProps) {
  const parts = useMemo(() => highlightTerms(snippet, terms), [snippet, terms]);
  if (!snippet) return null;
  return (
    <span
      className={cn(
        "text-xs text-muted-foreground leading-normal",
        className,
      )}
    >
      {parts.map((part, i) =>
        part.match ? (
          <mark
            key={i}
            className="bg-amber-200/70 dark:bg-amber-700/40 text-foreground font-medium rounded px-1 mx-px"
          >
            {part.text}
          </mark>
        ) : (
          <span key={i}>{part.text}</span>
        ),
      )}
    </span>
  );
}

interface HighlightPart {
  text: string;
  match: boolean;
}

/** Pure helper — splits `text` into alternating plain/match parts based on
 *  the (case-insensitive) `terms`. Exported for unit testing. */
export function highlightTerms(text: string, terms: string[]): HighlightPart[] {
  if (!text) return [];
  const cleanTerms = terms
    .map((t) => t.trim())
    .filter((t) => t.length >= 2)
    // Longest first so a query like ["AI", "AI Engineer"] highlights the
    // whole phrase, not just "AI" inside it.
    .sort((a, b) => b.length - a.length);
  if (cleanTerms.length === 0) {
    return [{ text, match: false }];
  }

  const lower = text.toLowerCase();
  const parts: HighlightPart[] = [];
  let cursor = 0;

  while (cursor < text.length) {
    // Find the next match across all terms — earliest start wins.
    let nextStart = -1;
    let nextLen = 0;
    for (const term of cleanTerms) {
      const idx = lower.indexOf(term.toLowerCase(), cursor);
      if (idx < 0) continue;
      if (nextStart < 0 || idx < nextStart) {
        nextStart = idx;
        nextLen = term.length;
      }
    }
    if (nextStart < 0) {
      // No more matches — flush the rest as plain text.
      parts.push({ text: text.slice(cursor), match: false });
      break;
    }
    if (nextStart > cursor) {
      parts.push({ text: text.slice(cursor, nextStart), match: false });
    }
    parts.push({
      text: text.slice(nextStart, nextStart + nextLen),
      match: true,
    });
    cursor = nextStart + nextLen;
  }
  return parts;
}
