import { useEffect } from "react";

interface CandidateSearchDebounceOptions {
  draft: string;
  committed: string;
  onCommit: (value: string) => void;
  delay?: number;
}

/** Commit search drafts after 300 ms; Enter can still commit immediately. */
export function useCandidateSearchDebounce({
  draft,
  committed,
  onCommit,
  delay = 300,
}: CandidateSearchDebounceOptions): void {
  useEffect(() => {
    if (draft === committed) return;
    const timer = window.setTimeout(() => onCommit(draft), delay);
    return () => window.clearTimeout(timer);
  }, [committed, delay, draft, onCommit]);
}
