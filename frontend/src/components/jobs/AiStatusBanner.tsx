"use client";

import Link from "next/link";
import { AlertTriangle, OctagonAlert } from "lucide-react";
import { cn } from "@/lib/utils";
import type { AiStatus } from "@/lib/candidate-search-api";

interface AiStatusBannerProps {
  /** Current status from ``meta.ai_status`` of any AI-backed response. */
  status: AiStatus;
  /**
   * Dokąd ma prowadzić CTA „wyszukaj manualnie”. Bez tego propa CTA w ogóle
   * się nie renderuje — i to jest domyślne zachowanie celowo.
   *
   * Wcześniej domyślną wartością było `/candidates/search`, co czyniło link
   * autoreferencyjnym: banner ma dziś dokładnie jedno miejsce renderowania —
   * `CandidateSearchView`, czyli sam widok wyszukiwania manualnego. Na stronie
   * globalnej link był no-opem, a z zakładki „Wyszukiwanie manualne” oferty
   * (`app/jobs/[id]/page.tsx` osadza ten sam widok) WYPROWADZAŁ z kontekstu —
   * gubiąc `addToJob`, prefill filtrów z oferty i `exclude_in_job_id`. Banner
   * zapala się wyłącznie podczas awarii AI, więc był to kosztowny fałszywy
   * ratunek dokładnie wtedy, gdy fallback jest najbardziej potrzebny.
   *
   * Wołający, który stoi POZA powierzchnią manualną, podaje href jawnie.
   */
  manualSearchHref?: string;
  className?: string;
}

/**
 * Surfaces the AI matching circuit-breaker state to the user.
 *
 * Renders nothing when the pipeline is healthy (the common case) — silence
 * is the right UX when everything is fine. Flipped on by the rolling
 * window in ``app/services/ai_health.py``.
 */
export function AiStatusBanner({
  status,
  manualSearchHref,
  className,
}: AiStatusBannerProps) {
  if (status === "ok") return null;

  if (status === "down") {
    return (
      <div
        role="alert"
        className={cn(
          "flex items-start gap-3 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-200",
          className,
        )}
      >
        <OctagonAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
        <div>
          <strong>AI matching niedostępny.</strong>{" "}
          Voyage AI / Qdrant ma problem — propozycje kandydatów mogą być puste.{" "}
          {manualSearchHref && (
            <Link
              href={manualSearchHref}
              className="underline underline-offset-2 hover:text-rose-900 dark:hover:text-rose-100"
            >
              Wyszukaj kandydatów manualnie →
            </Link>
          )}
        </div>
      </div>
    );
  }

  return (
    <div
      role="status"
      className={cn(
        "flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200",
        className,
      )}
    >
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
      <div>
        <strong>AI matching wolny.</strong>{" "}
        Ostatnie zapytania trwały &gt; 5s — wyniki mogą być opóźnione.{" "}
        {manualSearchHref && (
          <Link
            href={manualSearchHref}
            className="underline underline-offset-2 hover:text-amber-900 dark:hover:text-amber-100"
          >
            Spróbuj manual search
          </Link>
        )}
      </div>
    </div>
  );
}
