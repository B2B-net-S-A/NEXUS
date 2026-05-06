"use client";

import { useEffect } from "react";
import { X, Sparkles } from "lucide-react";
import { SuggestedCandidatesWidget } from "./SuggestedCandidatesWidget";

interface SuggestedCandidatesDrawerProps {
  jobId: number;
  jobTitle: string;
  onClose: () => void;
}

export function SuggestedCandidatesDrawer({
  jobId,
  jobTitle,
  onClose,
}: SuggestedCandidatesDrawerProps) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-black/40"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-labelledby="suggested-candidates-drawer-title"
    >
      <div
        className="w-full sm:max-w-xl h-full bg-card dark:bg-card shadow-2xl overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 flex items-center justify-between px-5 py-3.5 border-b border-border dark:border-border bg-card dark:bg-card z-10">
          <div className="flex items-center gap-2 min-w-0">
            <Sparkles className="w-5 h-5 text-purple-500 flex-shrink-0" aria-hidden />
            <div className="min-w-0">
              <h2
                id="suggested-candidates-drawer-title"
                className="font-semibold text-foreground dark:text-foreground text-sm truncate"
              >
                Sugerowani kandydaci
              </h2>
              <p className="text-xs text-muted-foreground dark:text-muted-foreground truncate">{jobTitle}</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 text-muted-foreground hover:text-foreground hover:bg-muted dark:hover:bg-muted rounded-md flex-shrink-0"
            aria-label="Zamknij"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-5">
          <SuggestedCandidatesWidget jobId={jobId} />
        </div>
      </div>
    </div>
  );
}
