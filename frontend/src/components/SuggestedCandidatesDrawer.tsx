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
        className="w-full sm:max-w-xl h-full bg-white dark:bg-gray-900 shadow-2xl overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 flex items-center justify-between px-5 py-3.5 border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 z-10">
          <div className="flex items-center gap-2 min-w-0">
            <Sparkles className="w-5 h-5 text-purple-500 flex-shrink-0" aria-hidden />
            <div className="min-w-0">
              <h2
                id="suggested-candidates-drawer-title"
                className="font-semibold text-gray-900 dark:text-gray-100 text-sm truncate"
              >
                Sugerowani kandydaci
              </h2>
              <p className="text-xs text-gray-500 dark:text-gray-400 truncate">{jobTitle}</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 text-gray-500 hover:text-gray-700 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-md flex-shrink-0"
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
